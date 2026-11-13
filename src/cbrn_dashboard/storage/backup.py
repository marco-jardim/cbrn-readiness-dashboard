# SPDX-License-Identifier: GPL-3.0-or-later
"""Consistent local database copies and their rotation (PLAN.md D04, D25, P06, task T7.1).

Every copy is made with SQLite's online backup API (``Connection.backup``), which copies the last
COMMITTED state of the database. That is safe while another connection holds an open write
transaction: its uncommitted rows are not in the copy. The copy is written under a temporary name
(``<name>.partial``) in the destination folder and renamed into place only when it is complete, so
a partial file never looks like a backup; on any failure the temporary file is removed.

Three kinds of copy, each with its OWN pool (a pool is never rotated by another kind):

========================  ====================================================  =====  ==========
kind                      file name                                             keeps  folder
========================  ====================================================  =====  ==========
``DAILY``                 ``daily-<YYYYMMDDTHHMMSSZ>-v<NNNN>.sqlite3``          P06    backups
``PRE_MIGRATION``         ``pre-migration-<YYYYMMDDTHHMMSSZ>-v<NNNN>.sqlite3``  3      backups
``BEFORE_RESTORE``        ``<db file name>.before-restore-<YYYYMMDDTHHMMSSZ>``  2      beside db
========================  ====================================================  =====  ==========

The timestamp is the UTC instant of the injected :class:`~cbrn_dashboard.clock.Clock`; ``NNNN`` is
the schema version (``PRAGMA user_version``; for a pre-migration copy the version BEFORE
migrating). Two copies in the same second get a numeric suffix (``-2``, ``-3``), so nothing is ever
overwritten. The backup folder of a real database is ``<data>/backups/``; of a demo database
``<data>/demo/backups/`` (D25). The identity is always passed explicitly, never inferred.

Rotation rules that hold together (see :func:`rotate`): it runs only after a new copy passed
``PRAGMA quick_check`` (:func:`create_backup` deletes a failing copy and the caller then does not
rotate); the pool keeps the newest ``keep`` copies, never fewer than :data:`MIN_KEEP`; the newest
verified copy is passed as ``protect`` and is never deleted; files whose names do not parse, files
of another kind and anything that is not a regular file are never touched.

No Qt, no wall clock: time comes from the ``Clock`` argument only.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from cbrn_dashboard.clock import Clock, SystemClock
from cbrn_dashboard.domain.dates import (
    InvalidTimestampError,
    format_utc_timestamp,
    parse_utc_timestamp,
)
from cbrn_dashboard.paths import DATABASE_FILE_NAME
from cbrn_dashboard.storage.db import DatabaseError, open_database

__all__ = [
    "BEFORE_RESTORE_KEEP",
    "MIN_KEEP",
    "PRE_MIGRATION_KEEP",
    "BackupInfo",
    "BackupKind",
    "BackupResult",
    "BackupVerificationError",
    "DatabaseIdentity",
    "RotationResult",
    "backup_before_migration",
    "backups_dir",
    "copy_database",
    "create_backup",
    "database_path",
    "list_backups",
    "parse_backup_name",
    "pool_dir",
    "rotate",
    "verify_backup",
]

BACKUPS_DIR_NAME = "backups"
#: The demo database lives in ``<data>/demo/`` under this name (kept equal to the constants of
#: ``cbrn_dashboard.demo``, which this layer must not import).
DEMO_DIR_NAME = "demo"
DEMO_DATABASE_FILE_NAME = "demo.sqlite3"

#: Suffix of the temporary name a copy has until it is complete.
PARTIAL_SUFFIX = ".partial"
_JOURNAL_SUFFIX = "-journal"

#: Fewest copies any pool keeps (the hard floor of P06).
MIN_KEEP = 2
#: The pre-migration pool keeps the last 3 copies.
PRE_MIGRATION_KEEP = 3
#: The ``.before-restore-*`` pool keeps the last 2 copies.
BEFORE_RESTORE_KEEP = 2

_STAMP = r"([0-9]{8}T[0-9]{6}Z)"
_PREFIXED = re.compile(rf"(daily|pre-migration)-{_STAMP}-v([0-9]{{4,}})(?:-([0-9]+))?\.sqlite3")
_RESTORE = re.compile(rf"(.+)\.before-restore-{_STAMP}(?:-([0-9]+))?")


# --------------------------------------------------------------------------- types


class DatabaseIdentity(StrEnum):
    """Which database a connection belongs to; always passed explicitly, never inferred."""

    REAL = "real"
    DEMO = "demo"


class BackupKind(StrEnum):
    """The three pools of copies; the value is the prefix used in the file name."""

    DAILY = "daily"
    PRE_MIGRATION = "pre-migration"
    BEFORE_RESTORE = "before-restore"


class BackupVerificationError(DatabaseError):
    """A copy failed ``PRAGMA quick_check``; the copy was removed."""

    code = "BACKUP_VERIFY_FAILED"


@dataclass(frozen=True)
class BackupInfo:
    """What a backup file name says. ``schema_version`` is ``None`` for ``BEFORE_RESTORE``."""

    path: Path
    kind: BackupKind
    created_utc: datetime
    schema_version: int | None
    sequence: int = 1

    @property
    def sort_key(self) -> tuple[datetime, int]:
        """Order of creation: the UTC instant in the name, then the sequence suffix."""
        return (self.created_utc, self.sequence)


@dataclass(frozen=True)
class BackupResult:
    """A finished copy: ``verified`` is the result of ``quick_check`` (a failed copy is removed)."""

    path: Path
    verified: bool
    kind: BackupKind
    schema_version: int


@dataclass(frozen=True)
class RotationResult:
    """What :func:`rotate` did. ``keep`` is the number actually used (after the floor)."""

    deleted: tuple[Path, ...] = ()
    failed: tuple[Path, ...] = ()
    keep: int = MIN_KEEP
    clamped: bool = False


# --------------------------------------------------------------------------- places


def backups_dir(data_dir: Path, identity: DatabaseIdentity) -> Path:
    """``<data>/backups/`` for the real database, ``<data>/demo/backups/`` for the demo one."""
    if identity is DatabaseIdentity.DEMO:
        return data_dir / DEMO_DIR_NAME / BACKUPS_DIR_NAME
    return data_dir / BACKUPS_DIR_NAME


def database_path(data_dir: Path, identity: DatabaseIdentity) -> Path:
    """The database file of ``identity`` inside the data folder."""
    if identity is DatabaseIdentity.DEMO:
        return data_dir / DEMO_DIR_NAME / DEMO_DATABASE_FILE_NAME
    return data_dir / DATABASE_FILE_NAME


def pool_dir(
    data_dir: Path,
    identity: DatabaseIdentity,
    kind: BackupKind,
    *,
    database: Path | None = None,
) -> Path:
    """The folder of a pool: ``backups/`` or, for ``BEFORE_RESTORE``, the database's own folder."""
    if kind is BackupKind.BEFORE_RESTORE:
        return (database or database_path(data_dir, identity)).parent
    return backups_dir(data_dir, identity)


# --------------------------------------------------------------------------- names


def _stamp(instant: datetime) -> str:
    return format_utc_timestamp(instant).replace("-", "").replace(":", "")


def _file_name(
    kind: BackupKind, instant: datetime, schema_version: int, sequence: int, database_name: str
) -> str:
    suffix = "" if sequence == 1 else f"-{sequence}"
    if kind is BackupKind.BEFORE_RESTORE:
        return f"{database_name}.before-restore-{_stamp(instant)}{suffix}"
    return f"{kind.value}-{_stamp(instant)}-v{schema_version:04d}{suffix}.sqlite3"


def _parse_stamp(text: str) -> datetime | None:
    iso = f"{text[0:4]}-{text[4:6]}-{text[6:8]}T{text[9:11]}:{text[11:13]}:{text[13:15]}Z"
    try:
        return parse_utc_timestamp(iso)
    except InvalidTimestampError:
        return None


def _sequence(text: str | None) -> int | None:
    if text is None:
        return 1
    value = int(text)
    return value if value >= 2 else None


def parse_backup_name(name: str, *, folder: Path | None = None) -> BackupInfo | None:
    """Read kind, UTC instant, schema version and sequence from a file NAME; ``None`` otherwise.

    ``folder`` only decides the ``path`` of the result (default: the bare name). A
    ``BEFORE_RESTORE`` name is accepted for any database file name; :func:`list_backups` narrows
    it to the right database.
    """
    path = Path(name) if folder is None else folder / name
    prefixed = _PREFIXED.fullmatch(name)
    if prefixed is not None:
        created = _parse_stamp(prefixed.group(2))
        sequence = _sequence(prefixed.group(4))
        if created is None or sequence is None:
            return None
        return BackupInfo(
            path, BackupKind(prefixed.group(1)), created, int(prefixed.group(3)), sequence
        )
    restore = _RESTORE.fullmatch(name)
    if restore is not None:
        created = _parse_stamp(restore.group(2))
        sequence = _sequence(restore.group(3))
        if created is None or sequence is None:
            return None
        return BackupInfo(path, BackupKind.BEFORE_RESTORE, created, None, sequence)
    return None


def list_backups(
    data_dir: Path,
    identity: DatabaseIdentity,
    kind: BackupKind | None = None,
    *,
    database: Path | None = None,
) -> list[BackupInfo]:
    """The recognised copies of one pool (or of all pools), newest first.

    Only regular files whose name parses are listed: temporary ``.partial`` files, other files,
    symbolic links and folders are not backups. A ``BEFORE_RESTORE`` copy counts only when it
    belongs to ``database`` (default: the database of ``identity``).
    """
    kinds = tuple(BackupKind) if kind is None else (kind,)
    database_name = (database or database_path(data_dir, identity)).name
    found: list[BackupInfo] = []
    for pool in kinds:
        folder = pool_dir(data_dir, identity, pool, database=database)
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            info = parse_backup_name(entry.name, folder=folder)
            if info is None or info.kind is not pool:
                continue
            if pool is BackupKind.BEFORE_RESTORE and not entry.name.startswith(
                f"{database_name}.before-restore-"
            ):
                continue
            if entry.is_symlink() or not entry.is_file():
                continue
            found.append(info)
    found.sort(key=lambda info: info.sort_key, reverse=True)
    return found


# --------------------------------------------------------------------------- copying


def _remove(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def copy_database(source: sqlite3.Connection, dest: Path) -> None:
    """Write a consistent copy of the database behind ``source`` to ``dest``.

    Uses SQLite's online backup API, so the copy holds the last committed state even while another
    connection has an open write transaction. ``dest`` is opened through
    :func:`~cbrn_dashboard.storage.db.open_database`, written under ``<dest>.partial`` and renamed
    into place only when complete (an existing ``dest`` is replaced). On any failure the temporary
    file is removed and the error propagates. ``source`` should not hold an open transaction of its
    own.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + PARTIAL_SUFFIX)
    journal = temporary.with_name(temporary.name + _JOURNAL_SUFFIX)
    _remove(temporary)
    _remove(journal)
    try:
        target = open_database(temporary)
        try:
            source.backup(target)
        finally:
            target.close()
        temporary.replace(dest)
    except BaseException:
        _remove(temporary)
        _remove(journal)
        raise


def verify_backup(path: Path) -> bool:
    """Open the copy read-only and run ``PRAGMA quick_check``; never raises.

    ``True`` only for the single row ``ok``. A missing, empty, truncated or non-database file, or
    any error while checking, gives ``False``.
    """
    try:
        if path.stat().st_size == 0:
            return False
        conn = open_database(path, read_only=True)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
        finally:
            conn.close()
    except Exception:
        return False
    return len(rows) == 1 and bool(rows[0][0] == "ok")


def _user_version(conn: sqlite3.Connection) -> int:
    value: object = conn.execute("PRAGMA user_version").fetchone()[0]
    if not isinstance(value, int):
        msg = "Unexpected value for PRAGMA user_version."
        raise DatabaseError(msg)
    return value


def _taken(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _free_path(
    folder: Path,
    kind: BackupKind,
    instant: datetime,
    schema_version: int,
    database_name: str,
) -> Path:
    """The first name not in use for this second: no suffix, then ``-2``, ``-3`` ..."""
    sequence = 1
    while True:
        candidate = folder / _file_name(kind, instant, schema_version, sequence, database_name)
        partial = candidate.with_name(candidate.name + PARTIAL_SUFFIX)
        if not (_taken(candidate) or _taken(partial)):
            return candidate
        sequence += 1


def create_backup(
    conn: sqlite3.Connection,
    *,
    data_dir: Path,
    identity: DatabaseIdentity,
    kind: BackupKind,
    clock: Clock,
    quick_check: Callable[[Path], bool] = verify_backup,
    schema_version: int | None = None,
    database: Path | None = None,
) -> BackupResult:
    """Copy the database behind ``conn`` into the pool of ``kind`` and check the copy.

    The file name carries the UTC instant of ``clock`` and the schema version (``user_version`` of
    ``conn`` unless ``schema_version`` is given). A copy that fails ``quick_check`` is removed (it
    is useless as a backup) and ``verified`` is ``False``: it is not counted, and the caller must
    not rotate because of it. Errors while copying propagate (the temporary file is removed).
    ``database`` overrides the database file that a ``BEFORE_RESTORE`` copy is named after and
    placed beside.
    """
    version = _user_version(conn) if schema_version is None else schema_version
    instant = clock.utc_now()
    folder = pool_dir(data_dir, identity, kind, database=database)
    folder.mkdir(parents=True, exist_ok=True)
    database_name = (database or database_path(data_dir, identity)).name
    path = _free_path(folder, kind, instant, version, database_name)
    copy_database(conn, path)
    verified = quick_check(path)
    if not verified:
        _remove(path)
    return BackupResult(path=path, verified=verified, kind=kind, schema_version=version)


# --------------------------------------------------------------------------- rotation


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def rotate(
    data_dir: Path,
    identity: DatabaseIdentity,
    kind: BackupKind,
    keep: int,
    *,
    protect: Path | None = None,
    database: Path | None = None,
) -> RotationResult:
    """Delete the oldest copies of ONE pool so that the newest ``keep`` remain.

    Call it only after a new copy passed ``quick_check``, and pass that copy as ``protect``: it is
    never deleted, even when a clock that went backwards makes it look old. ``keep`` below
    :data:`MIN_KEEP` is raised to the floor (``clamped`` in the result). Ordered by the UTC instant
    in the name, then the sequence. Files that do not parse, belong to another kind or are not
    regular files are not touched; because at least ``MIN_KEEP`` copies are kept, the only
    remaining copy is never deleted. A deletion that fails with ``OSError`` is listed in
    ``failed`` and does not stop the others.
    """
    effective = max(keep, MIN_KEEP)
    protected = None if protect is None else _resolved(protect)
    deleted: list[Path] = []
    failed: list[Path] = []
    for info in list_backups(data_dir, identity, kind, database=database)[effective:]:
        if protected is not None and _resolved(info.path) == protected:
            continue
        try:
            info.path.unlink()
        except OSError:
            failed.append(info.path)
        else:
            deleted.append(info.path)
    return RotationResult(
        deleted=tuple(deleted),
        failed=tuple(failed),
        keep=effective,
        clamped=effective != keep,
    )


# --------------------------------------------------------------------------- pre-migration


def backup_before_migration(
    conn: sqlite3.Connection,
    *,
    data_dir: Path,
    identity: DatabaseIdentity,
    from_version: int,
    enabled: bool = True,
    clock: Clock | None = None,
) -> Path | None:
    """Copy a non-empty database before it is migrated; return the new file or ``None``.

    A real database goes to ``<data_dir>/backups/``, a demo database to
    ``<data_dir>/demo/backups/``. ``None`` is returned (and nothing is written) when ``enabled`` is
    false, for example when the restore service migrates a temporary copy, and when the database
    has no user tables (a fresh file). The name is
    ``pre-migration-<UTC timestamp>-v<from_version>.sqlite3``. The copy is checked; on success the
    pre-migration pool is rotated to the last :data:`PRE_MIGRATION_KEEP` copies (daily backups
    never touch it). Raises :class:`BackupVerificationError` when the copy fails the check, so the
    migration does not run without a usable backup.
    """
    if not enabled:
        return None
    count: object = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    if count == 0:
        return None
    result = create_backup(
        conn,
        data_dir=data_dir,
        identity=identity,
        kind=BackupKind.PRE_MIGRATION,
        clock=SystemClock() if clock is None else clock,
        schema_version=from_version,
    )
    if not result.verified:
        msg = "The pre-migration backup failed its integrity check and was removed."
        raise BackupVerificationError(msg)
    rotate(
        data_dir,
        identity,
        BackupKind.PRE_MIGRATION,
        PRE_MIGRATION_KEEP,
        protect=result.path,
    )
    return result.path
