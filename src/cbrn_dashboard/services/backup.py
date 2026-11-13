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

The manual encrypted backup (D04, P05, P09, K06, task T7.2) is
``BackupService.create_encrypted_backup``: it checks the passphrase (:func:`check_passphrase`),
takes a consistent
snapshot of the open database in memory, writes the ``.cbrnbak`` container, reads it back with the
same passphrase to be sure it can be restored, and records the time for the reminder. The
passphrase is never stored, logged or put into an error; a read-only connection still makes the
backup and writes nothing to the database or the data folder. Event codes:
``BACKUP.ENCRYPTED_DONE``, ``BACKUP.ENCRYPTED_FAILED``, ``BACKUP.ENCRYPTED_RECORD_FAILED``.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from cbrn_dashboard import __version__
from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain.config import PASSPHRASE_LENGTH_FLOOR, ConfigError, ReadinessConfig
from cbrn_dashboard.domain.dates import (
    InvalidTimestampError,
    days_between,
    format_utc_timestamp,
    parse_utc_timestamp,
)
from cbrn_dashboard.logging_setup import log_event, log_exception
from cbrn_dashboard.paths import DataLocation
from cbrn_dashboard.services.errors import ServiceError
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
from cbrn_dashboard.storage.crypto_backup import (
    DEFAULT_PARAMS,
    FILE_EXTENSION,
    BackupFileError,
    ScryptParams,
    database_snapshot_bytes,
    read_backup,
    write_backup,
)
from cbrn_dashboard.storage.db import DatabaseConnection, DatabaseError
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import get_value, load_config, set_value

__all__ = [
    "BACKUP_VERIFY_FAILED",
    "BACKUP_WRITE_FAILED",
    "LAST_ENCRYPTED_KEY",
    "MIN_DISTINCT_CHARACTERS",
    "PASSPHRASE_BLOCKLISTED",
    "PASSPHRASE_MISMATCH",
    "PASSPHRASE_TOO_FEW_DISTINCT",
    "PASSPHRASE_TOO_SHORT",
    "BackupService",
    "EncryptedBackupResult",
    "StartupContext",
    "check_passphrase",
    "daily_backup_hook",
    "daily_backup_startup",
]

#: Setting that holds the UTC time of the last successful encrypted backup (reminder, P09).
LAST_ENCRYPTED_KEY = "backup.last_encrypted_utc"

# --------------------------------------------------------------------------- passphrase rule

#: The confirmation (the UI asks twice) differs from the passphrase.
PASSPHRASE_MISMATCH = "PASSPHRASE_MISMATCH"
#: Fewer characters than P05 (never below the hard floor of 12).
PASSPHRASE_TOO_SHORT = "PASSPHRASE_TOO_SHORT"
#: Fewer than :data:`MIN_DISTINCT_CHARACTERS` different characters.
PASSPHRASE_TOO_FEW_DISTINCT = "PASSPHRASE_TOO_FEW_DISTINCT"
#: One of the obvious choices of :data:`_BLOCKLIST`.
PASSPHRASE_BLOCKLISTED = "PASSPHRASE_BLOCKLISTED"
#: The encrypted file was written but could not be read back; it was deleted.
BACKUP_VERIFY_FAILED = "BACKUP_VERIFY_FAILED"
#: The encrypted file could not be written.
BACKUP_WRITE_FAILED = "BACKUP_WRITE_FAILED"

#: A passphrase needs at least this many different characters.
MIN_DISTINCT_CHARACTERS = 6

# Short list of obvious choices. A passphrase is blocked when its lower-cased form, or that form
# without leading/trailing non-letters (digits, punctuation, spaces), or the same without inner
# spaces, equals one of these (also compared without their own leading/trailing non-letters). So
# "Password1234!" and "senha 2026" are blocked. Keep it short: it only stops the obvious.
_BLOCKLIST_RAW: tuple[str, ...] = (
    "password",
    "passphrase",
    "123456789012",
    "012345678901",
    "qwertyuiopas",
    "qwertyuiop",
    "asdfghjkl",
    "abcdefghijkl",
    "letmein",
    "welcome",
    "changeme",
    "administrator",
    "senha",
    "contrasena",
    "contrase\u00f1a",
    "cbrn",
    "cbrndashboard",
    "readinessdashboard",
    "cbrn readiness dashboard",  # the app name
    "cbrnreadinessdashboard",
)


def _strip_ends(text: str) -> str:
    """``text`` without leading and trailing characters that are not letters."""
    start = 0
    end = len(text)
    while start < end and not text[start].isalpha():
        start += 1
    while end > start and not text[end - 1].isalpha():
        end -= 1
    return text[start:end]


def _blocklist_forms(text: str) -> set[str]:
    folded = unicodedata.normalize("NFC", text).casefold()
    forms = {folded, _strip_ends(folded), _strip_ends("".join(folded.split()))}
    forms.discard("")
    return forms


_BLOCKLIST: frozenset[str] = frozenset(
    form for word in _BLOCKLIST_RAW for form in _blocklist_forms(word)
)


def check_passphrase(passphrase: str, confirmation: str | None, *, min_length: int) -> None:
    """Raise :class:`ServiceError` when ``passphrase`` is not acceptable for a backup (P05).

    Codes, in this order: ``PASSPHRASE_MISMATCH`` (``confirmation`` is given and differs),
    ``PASSPHRASE_TOO_SHORT`` (fewer than ``max(min_length, 12)`` characters: the stored P05 can
    never lower the hard floor), ``PASSPHRASE_TOO_FEW_DISTINCT`` (fewer than 6 different
    characters), ``PASSPHRASE_BLOCKLISTED``. Lengths are counted in characters after Unicode NFC
    normalisation, the same text that is used for the key. The passphrase is never included in
    the error.
    """
    normalised = unicodedata.normalize("NFC", passphrase)
    if confirmation is not None and unicodedata.normalize("NFC", confirmation) != normalised:
        raise ServiceError(PASSPHRASE_MISMATCH)
    if len(normalised) < max(min_length, PASSPHRASE_LENGTH_FLOOR):
        raise ServiceError(PASSPHRASE_TOO_SHORT)
    if len(set(normalised)) < MIN_DISTINCT_CHARACTERS:
        raise ServiceError(PASSPHRASE_TOO_FEW_DISTINCT)
    if _blocklist_forms(normalised) & _BLOCKLIST:
        raise ServiceError(PASSPHRASE_BLOCKLISTED)


@dataclass(frozen=True)
class EncryptedBackupResult:
    """A finished encrypted backup: the file and the schema version of the copy inside it."""

    path: Path
    schema_version: int


def _no_operator() -> str:
    return ""


class BackupService:
    """Daily backup and listing for the database behind ``conn``.

    ``identity`` says whether the database is the real one or the demo one; it is passed
    explicitly and decides the backup folder. ``quick_check`` is the integrity check of a new copy
    (injectable for tests). ``operator`` returns the optional operator label for the change log
    rows this service writes (the time of the last encrypted backup).
    """

    def __init__(
        self,
        conn: DatabaseConnection,
        clock: Clock,
        *,
        data_dir: Path,
        identity: DatabaseIdentity,
        quick_check: Callable[[Path], bool] = verify_backup,
        operator: Callable[[], str] = _no_operator,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._data_dir = data_dir
        self._identity = identity
        self._quick_check = quick_check
        self._operator = operator

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

    # ------------------------------------------------------------------ the encrypted backup

    def _config(self) -> ReadinessConfig:
        """The stored configuration; the defaults when it cannot be read."""
        try:
            return load_config(self._conn)
        except (ConfigError, sqlite3.Error, DatabaseError):
            return ReadinessConfig()

    def create_encrypted_backup(
        self,
        dest: Path,
        passphrase: str,
        confirmation: str | None = None,
        *,
        params: ScryptParams = DEFAULT_PARAMS,
    ) -> EncryptedBackupResult:
        """Write an encrypted ``.cbrnbak`` copy of the database to ``dest`` (D04).

        The passphrase is checked first (:func:`check_passphrase` with the stored P05); a refusal
        writes nothing. The extension ``.cbrnbak`` is appended to ``dest`` when it is missing. The
        snapshot is taken in memory, so this works on a read-only connection and writes nothing to
        the data folder. The written file is read back with the same passphrase and compared with
        the snapshot; a file that does not read back is deleted and reported as
        ``BACKUP_VERIFY_FAILED``, a file that cannot be written as ``BACKUP_WRITE_FAILED``. Only
        after that the time is recorded for the reminder, and only on a writable connection.
        ``params`` are the scrypt parameters of the new file (tests pass a cheap set).
        """
        check_passphrase(passphrase, confirmation, min_length=self._config().min_passphrase_length)
        target = (
            dest
            if dest.name.lower().endswith(FILE_EXTENSION)
            else dest.with_name(dest.name + FILE_EXTENSION)
        )
        try:
            snapshot, schema_version = database_snapshot_bytes(self._conn)
            write_backup(
                target,
                snapshot,
                passphrase,
                app_version=__version__,
                schema_version=schema_version,
                params=params,
            )
        except (OSError, sqlite3.Error, DatabaseError) as exc:
            log_event("BACKUP.ENCRYPTED_FAILED", level=logging.WARNING)
            raise ServiceError(BACKUP_WRITE_FAILED) from exc
        if not self._reads_back(target, snapshot, passphrase, params):
            with contextlib.suppress(OSError):
                target.unlink(missing_ok=True)
            log_event("BACKUP.ENCRYPTED_FAILED", level=logging.WARNING)
            raise ServiceError(BACKUP_VERIFY_FAILED)
        self._record_encrypted_backup()
        log_event("BACKUP.ENCRYPTED_DONE")
        return EncryptedBackupResult(path=target, schema_version=schema_version)

    @staticmethod
    def _reads_back(target: Path, snapshot: bytes, passphrase: str, params: ScryptParams) -> bool:
        """Whether ``target`` decrypts with ``passphrase`` to exactly ``snapshot``."""
        try:
            # The file was just written with ``params``, so they are accepted for the read-back.
            restored = read_backup(target, passphrase, allowed_params=frozenset({params}))
        except (BackupFileError, OSError):
            return False
        return restored.database_bytes == snapshot

    def _record_encrypted_backup(self) -> None:
        """Store the time of this backup; skipped on a read-only connection."""
        if self._conn.read_only:
            return
        stamp = format_utc_timestamp(self._clock.utc_now())
        try:
            set_value(
                WriteContext(self._conn, self._clock, self._operator()),
                LAST_ENCRYPTED_KEY,
                stamp,
            )
        except (ConfigError, sqlite3.Error, DatabaseError):
            log_event("BACKUP.ENCRYPTED_RECORD_FAILED", level=logging.WARNING)

    def last_encrypted_backup(self) -> datetime | None:
        """The UTC instant of the last successful encrypted backup, or ``None`` if unknown."""
        try:
            value = get_value(self._conn, LAST_ENCRYPTED_KEY)
        except (ConfigError, sqlite3.Error, DatabaseError):
            return None
        if not isinstance(value, str):
            return None
        try:
            return parse_utc_timestamp(value)
        except InvalidTimestampError:
            return None

    def encrypted_backup_reminder_due(self) -> bool:
        """Whether to remind the operator: never backed up, or older than P09 days.

        Compares LOCAL calendar dates through the clock: exactly P09 days ago is not yet due.
        """
        last = self.last_encrypted_backup()
        if last is None:
            return True
        age = days_between(self._clock.local_date_of(last), self._clock.local_date())
        return age > self._config().backup_reminder_days


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
