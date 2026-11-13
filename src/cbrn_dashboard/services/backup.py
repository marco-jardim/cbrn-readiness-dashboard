# SPDX-License-Identifier: GPL-3.0-or-later
"""Automatic local backups (PLAN.md D04, P06, K05, task T7.1).

:class:`BackupService` makes the daily backup of one open database: at most one per LOCAL calendar
day (the date defined in ``clock.py``, however many times the program starts), checks the copy,
and only then rotates the daily pool to the newest P06 copies. The pre-migration pool and the
``.before-restore-*`` pool are never touched by the daily rotation.

The start-up registry of ``app.py`` (T1.9) registers the hook once, in ONE line::

    StartupHook(
        "daily-backup", daily_backup_startup,
        runs_read_only=False, runs_in_demo=False, needs_trusted_clock=False,
    )

The hook is skipped in read-only mode and in demo mode (``runs_read_only`` and ``runs_in_demo`` are
false). ``needs_trusted_clock`` is false because the backup itself still runs when the clock sanity
check failed; only the rotation is skipped for the session (``clock_suspect``).

Log lines carry event codes and counts only (``BACKUP.DAILY_DONE``, ``BACKUP.DAILY_FAILED``,
``BACKUP.ROTATED``), never paths or contents. No Qt.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain.config import ConfigError, ReadinessConfig
from cbrn_dashboard.logging_setup import log_event, log_exception
from cbrn_dashboard.paths import DataLocation
from cbrn_dashboard.storage.backup import (
    BackupInfo,
    BackupKind,
    BackupResult,
    DatabaseIdentity,
    create_backup,
    list_backups,
    rotate,
    verify_backup,
)
from cbrn_dashboard.storage.db import DatabaseConnection, DatabaseError
from cbrn_dashboard.storage.settings_repo import load_config

__all__ = [
    "BackupService",
    "StartupContext",
    "daily_backup_hook",
    "daily_backup_startup",
]


class BackupService:
    """Daily backup and listing for the database behind ``conn``.

    ``identity`` says whether the database is the real one or the demo one; it is passed
    explicitly and decides the backup folder. ``quick_check`` is the integrity check of a new copy
    (injectable for tests).
    """

    def __init__(
        self,
        conn: DatabaseConnection,
        clock: Clock,
        *,
        data_dir: Path,
        identity: DatabaseIdentity,
        quick_check: Callable[[Path], bool] = verify_backup,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._data_dir = data_dir
        self._identity = identity
        self._quick_check = quick_check

    # ------------------------------------------------------------------ queries

    def list_backups(self, kind: BackupKind | None = None) -> list[BackupInfo]:
        """The recognised copies (all pools, or one), newest first."""
        return list_backups(self._data_dir, self._identity, kind)

    def daily_backup_due(self) -> bool:
        """Whether no daily copy exists whose UTC instant falls on today's LOCAL calendar date."""
        today = self._clock.local_date()
        return not any(
            self._clock.local_date_of(info.created_utc) == today
            for info in list_backups(self._data_dir, self._identity, BackupKind.DAILY)
        )

    # ------------------------------------------------------------------ the daily backup

    def run_daily_backup(self, *, rotate: bool = True) -> BackupResult | None:
        """Make the daily backup when it is due; return ``None`` when nothing was done.

        At most one copy per local day: a second call on the same day returns ``None``. A
        read-only connection writes nothing and returns ``None``. A copy that fails the check is
        removed (``verified`` is ``False`` in the result), is not counted, and causes no deletion.
        After a verified copy the daily pool is rotated to P06 copies unless ``rotate`` is false
        (the caller passes ``False`` when the clock sanity check failed). A copying error is
        logged (type and frames only) and gives ``None``.
        """
        if self._conn.read_only or not self.daily_backup_due():
            return None
        try:
            result = create_backup(
                self._conn,
                data_dir=self._data_dir,
                identity=self._identity,
                kind=BackupKind.DAILY,
                clock=self._clock,
                quick_check=self._quick_check,
            )
        except (OSError, sqlite3.Error, DatabaseError) as exc:
            log_exception("BACKUP.DAILY_FAILED", exc)
            return None
        if not result.verified:
            log_event("BACKUP.DAILY_FAILED", level=logging.WARNING)
            return result
        log_event("BACKUP.DAILY_DONE")
        if rotate:
            self._rotate_daily(result.path)
        return result

    def _daily_keep(self) -> int:
        """P06 from the stored configuration; the default when it cannot be read."""
        try:
            return load_config(self._conn).daily_backups_kept
        except (ConfigError, sqlite3.Error, DatabaseError):
            return ReadinessConfig().daily_backups_kept

    def _rotate_daily(self, newest: Path) -> None:
        outcome = rotate(
            self._data_dir,
            self._identity,
            BackupKind.DAILY,
            self._daily_keep(),
            protect=newest,
        )
        if outcome.clamped:
            log_event("BACKUP.KEEP_CLAMPED", level=logging.WARNING, count=outcome.keep)
        if outcome.deleted:
            log_event("BACKUP.ROTATED", count=len(outcome.deleted))
        if outcome.failed:
            log_event("BACKUP.ROTATE_FAILED", level=logging.WARNING, count=len(outcome.failed))


# --------------------------------------------------------------------------- start-up hook


def daily_backup_hook(
    conn: DatabaseConnection,
    clock: Clock,
    *,
    data_dir: Path,
    identity: DatabaseIdentity,
    clock_suspect: bool,
) -> None:
    """Body of the start-up hook: the daily backup; rotation is skipped when the clock is suspect.

    Read-only connections write nothing. The registration (see the module docstring) declares that
    the hook does not run in read-only mode or in demo mode.
    """
    BackupService(conn, clock, data_dir=data_dir, identity=identity).run_daily_backup(
        rotate=not clock_suspect
    )


class StartupContext(Protocol):
    """The part of the application context the hook reads (``ui.shell.context.AppContext``)."""

    @property
    def conn(self) -> DatabaseConnection | None: ...

    @property
    def clock(self) -> Clock: ...

    @property
    def location(self) -> DataLocation: ...

    @property
    def clock_suspect(self) -> bool: ...


def daily_backup_startup(context: StartupContext) -> None:
    """``StartupHook.run`` callable: the daily backup of the real database in the data folder."""
    if context.conn is None:
        return
    daily_backup_hook(
        context.conn,
        context.clock,
        data_dir=context.location.path,
        identity=DatabaseIdentity.REAL,
        clock_suspect=context.clock_suspect,
    )
