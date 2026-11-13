# SPDX-License-Identifier: GPL-3.0-or-later
"""Restoring a database from an encrypted backup (PLAN.md D04, D25, risk K05, task T7.3).

:meth:`RestoreService.restore` COPIES a backup into the live database with SQLite's online backup
API. It never renames or swaps database files and it is not described as atomic: if the copy fails
the live database is put back from the safety copy taken first. The sequence is (D04, "Restore"):

1. a read-only live connection is refused (``READ_ONLY``);
2. the file is decrypted (wrong passphrase, damaged file, newer format: ``WRONG_PASSPHRASE``,
   ``CORRUPT_BACKUP``, ``BACKUP_TOO_NEW``) and the plaintext goes ONLY into ``<data>/tmp/``, a
   uniquely named ``restore-XXXX.sqlite3`` made by ``tempfile.mkstemp``;
3. ``PRAGMA integrity_check`` on that temporary copy (``INTEGRITY_FAILED``);
4. a backup whose ``app_meta.is_demo`` differs from the live database is refused
   (``DEMO_MISMATCH``); without an ``app_meta`` table it is ``NOT_AN_APPLICATION_DATABASE``;
5. the RESTORED database's own ``user_version`` decides (the header copy is informational): newer
   than the newest migration is ``BACKUP_TOO_NEW``;
6. an older copy is migrated, with the pre-migration backup OFF (no plaintext copy may be written
   outside ``tmp/``); a failure is ``MIGRATION_FAILED``;
7. the live database must be quiescent: this process holds no other connection on the file
   (``OTHER_CONNECTIONS_OPEN``, see :func:`~cbrn_dashboard.storage.db.open_connections`; other
   processes are excluded by the single-instance lock), no transaction is open
   (``TRANSACTION_OPEN``) and no ``<db>-journal`` file exists (``JOURNAL_PRESENT``). The same
   checks also run before anything is read from the live database, because reading it would
   otherwise roll a hot journal back, which is a write;
8. a safety copy of the current database is made first, by copying
   (``<db>.before-restore-<UTC timestamp>``); it must verify (``SAFETY_COPY_FAILED``) and the pool
   is rotated to the last two;
9. the validated temporary database is copied into the live one; on ANY failure from here to the
   change-log row, the live database is restored from the safety copy and ``RESTORE_COPY_FAILED``
   is raised;
10. ``PRAGMA integrity_check`` and ``user_version`` are checked on the live connection (the same
    handle keeps being used: the backup API copies INTO it);
11. a ``restore`` row is written to ``change_log`` in the restored database, naming the safety
    copy (file name only), the schema version and the version migrated from;
12. ALWAYS (success and every failure) the temporary connection is closed and the decrypted
    temporary file is deleted.

Every failure before step 9 leaves the live database untouched (not one write). Log lines carry
event codes only (``RESTORE.DONE``, ``RESTORE.FAILED``): never paths, contents or the passphrase,
which is not stored anywhere. Time comes from the injected ``Clock`` only. No Qt.

``clean_tmp`` empties ``<data>/tmp/`` (leftovers of a crash); ``tmp_cleanup_startup`` is the body
of the start-up hook, registered in ``app.py`` in ONE line::

    StartupHook(
        "tmp-cleanup", tmp_cleanup_startup,
        runs_read_only=False, runs_in_demo=True, needs_trusted_clock=False,
    )

In read-only mode nothing may be written or deleted in the data folder, so it does not run there.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.logging_setup import log_event, log_exception
from cbrn_dashboard.services.errors import READ_ONLY, ServiceError
from cbrn_dashboard.storage import repository
from cbrn_dashboard.storage.app_meta import read_is_demo
from cbrn_dashboard.storage.backup import (
    BEFORE_RESTORE_KEEP,
    BackupKind,
    DatabaseIdentity,
    create_backup,
    database_path,
    rotate,
)
from cbrn_dashboard.storage.crypto_backup import (
    ALLOWED_PARAMS,
    BackupFileError,
    DecryptedBackup,
    ScryptParams,
    read_backup,
)
from cbrn_dashboard.storage.db import (
    DatabaseConnection,
    DatabaseError,
    open_connections,
    open_database,
)
from cbrn_dashboard.storage.migrate import load_migrations, migrate

__all__ = [
    "BACKUP_TOO_NEW",
    "BACKUP_UNREADABLE",
    "CORRUPT_BACKUP",
    "DEMO_MISMATCH",
    "INTEGRITY_FAILED",
    "JOURNAL_PRESENT",
    "MIGRATION_FAILED",
    "NOT_AN_APPLICATION_DATABASE",
    "OTHER_CONNECTIONS_OPEN",
    "RESTORE_COPY_FAILED",
    "SAFETY_COPY_FAILED",
    "TEMP_FILE_FAILED",
    "TMP_DIR_NAME",
    "TRANSACTION_OPEN",
    "WRONG_PASSPHRASE",
    "CleanupContext",
    "RestoreResult",
    "RestoreService",
    "clean_tmp",
    "tmp_cleanup_startup",
]

#: The folder (inside the data folder) that is the only place decrypted data may be written to.
TMP_DIR_NAME = "tmp"

# Error codes (stable; the UI translates the code).
WRONG_PASSPHRASE = "WRONG_PASSPHRASE"
CORRUPT_BACKUP = "CORRUPT_BACKUP"
BACKUP_TOO_NEW = "BACKUP_TOO_NEW"
#: The backup file could not be read (missing, locked, no permission).
BACKUP_UNREADABLE = "BACKUP_UNREADABLE"
#: The decrypted temporary file could not be created or written in ``<data>/tmp/``.
TEMP_FILE_FAILED = "TEMP_FILE_FAILED"
INTEGRITY_FAILED = "INTEGRITY_FAILED"
DEMO_MISMATCH = "DEMO_MISMATCH"
NOT_AN_APPLICATION_DATABASE = "NOT_AN_APPLICATION_DATABASE"
MIGRATION_FAILED = "MIGRATION_FAILED"
OTHER_CONNECTIONS_OPEN = "OTHER_CONNECTIONS_OPEN"
TRANSACTION_OPEN = "TRANSACTION_OPEN"
JOURNAL_PRESENT = "JOURNAL_PRESENT"
SAFETY_COPY_FAILED = "SAFETY_COPY_FAILED"
RESTORE_COPY_FAILED = "RESTORE_COPY_FAILED"

_TEMP_PREFIX = "restore-"
_TEMP_SUFFIX = ".sqlite3"
_JOURNAL_SUFFIX = "-journal"
_KNOWN_FILE_CODES = frozenset({WRONG_PASSPHRASE, CORRUPT_BACKUP, BACKUP_TOO_NEW})


@dataclass(frozen=True)
class RestoreResult:
    """A finished restore: the safety copy, the schema version now in force and the old one."""

    safety_copy: Path
    restored_schema_version: int
    migrated_from: int | None


# --------------------------------------------------------------------------- small helpers


def _no_operator() -> str:
    return ""


def _remove(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _user_version(conn: sqlite3.Connection) -> int:
    value: object = conn.execute("PRAGMA user_version").fetchone()[0]
    if not isinstance(value, int):
        msg = "Unexpected value for PRAGMA user_version."
        raise DatabaseError(msg)
    return value


def _integrity_ok(conn: sqlite3.Connection) -> bool:
    """Whether ``PRAGMA integrity_check`` returns the single row ``ok``."""
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    return len(rows) == 1 and bool(rows[0][0] == "ok")


def _copy_into(source: sqlite3.Connection, target: sqlite3.Connection) -> None:
    """Step 9: copy ``source`` into ``target`` with SQLite's online backup API."""
    source.backup(target)


def _newest_schema_version() -> int:
    migrations = load_migrations()
    return migrations[-1].number if migrations else 0


def _has_app_meta(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_meta'")
    return row.fetchone() is not None


# --------------------------------------------------------------------------- the service


class RestoreService:
    """Restore a live database from an encrypted backup (see the module docstring).

    ``identity`` says whether the live database is the real or the demo one (it decides where the
    database file and its safety copies are); ``operator`` returns the optional operator label of
    the ``change_log`` row.
    """

    def __init__(
        self,
        *,
        data_dir: Path,
        identity: DatabaseIdentity,
        clock: Clock,
        operator: Callable[[], str] = _no_operator,
    ) -> None:
        self._data_dir = data_dir
        self._identity = identity
        self._clock = clock
        self._operator = operator

    # ------------------------------------------------------------------ public

    def restore(
        self,
        live: DatabaseConnection,
        backup_path: Path,
        passphrase: str,
        *,
        allowed_params: frozenset[ScryptParams] = ALLOWED_PARAMS,
    ) -> RestoreResult:
        """Restore ``backup_path`` into the database behind ``live``; see the module docstring.

        Raises :class:`~cbrn_dashboard.services.errors.ServiceError` with one of the codes of the
        module. ``allowed_params`` is handed to the backup reader (tests pass cheap parameters).
        """
        try:
            result = self._restore(live, backup_path, passphrase, allowed_params)
        except ServiceError:
            log_event("RESTORE.FAILED", level=logging.WARNING)
            raise
        except Exception as exc:
            log_exception("RESTORE.FAILED", exc)
            raise
        log_event("RESTORE.DONE")
        return result

    # ------------------------------------------------------------------ the sequence

    def _restore(
        self,
        live: DatabaseConnection,
        backup_path: Path,
        passphrase: str,
        allowed_params: frozenset[ScryptParams],
    ) -> RestoreResult:
        if live.read_only:  # step 1
            raise ServiceError(READ_ONLY)
        live_path = database_path(self._data_dir, self._identity)
        self._require_quiescent(live, live_path)  # before anything is read from ``live``
        decrypted = self._decrypt(backup_path, passphrase, allowed_params)  # step 2 (in memory)
        temp_path = self._write_temporary(decrypted.database_bytes)
        del decrypted
        temp_conn: DatabaseConnection | None = None
        try:
            temp_conn = self._open_temporary(temp_path)
            if not self._safe_integrity(temp_conn):  # step 3
                raise ServiceError(INTEGRITY_FAILED)
            self._check_demo(live, temp_conn)  # step 4
            found = self._check_version(temp_conn)  # step 5
            newest = _newest_schema_version()
            migrated_from = self._migrate_if_older(temp_conn, found, newest)  # step 6
            self._require_quiescent(live, live_path)  # step 7
            safety = self._safety_copy(live, live_path)  # step 8
            version = self._copy_into_live(temp_conn, live, safety, newest, migrated_from)
        finally:  # step 12
            if temp_conn is not None:
                with contextlib.suppress(sqlite3.Error):
                    temp_conn.close()
            _remove(temp_path)
            _remove(temp_path.with_name(temp_path.name + _JOURNAL_SUFFIX))
        return RestoreResult(
            safety_copy=safety, restored_schema_version=version, migrated_from=migrated_from
        )

    # ------------------------------------------------------------------ steps 2 and 3

    @staticmethod
    def _decrypt(
        backup_path: Path, passphrase: str, allowed_params: frozenset[ScryptParams]
    ) -> DecryptedBackup:
        try:
            return read_backup(backup_path, passphrase, allowed_params=allowed_params)
        except BackupFileError as exc:
            code = exc.code if exc.code in _KNOWN_FILE_CODES else CORRUPT_BACKUP
            raise ServiceError(code) from exc
        except OSError as exc:
            raise ServiceError(BACKUP_UNREADABLE) from exc

    def _write_temporary(self, content: bytes) -> Path:
        """Write the decrypted database to a new unique file in ``<data>/tmp/`` only."""
        folder = self._data_dir / TMP_DIR_NAME
        try:
            folder.mkdir(parents=True, exist_ok=True)
            handle_number, name = tempfile.mkstemp(
                prefix=_TEMP_PREFIX, suffix=_TEMP_SUFFIX, dir=folder
            )
        except OSError as exc:
            raise ServiceError(TEMP_FILE_FAILED) from exc
        path = Path(name)
        try:
            with os.fdopen(handle_number, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            _remove(path)
            raise ServiceError(TEMP_FILE_FAILED) from exc
        except BaseException:
            _remove(path)
            raise
        return path

    @staticmethod
    def _open_temporary(path: Path) -> DatabaseConnection:
        try:
            return open_database(path)
        except (sqlite3.Error, DatabaseError) as exc:
            raise ServiceError(INTEGRITY_FAILED) from exc

    @staticmethod
    def _safe_integrity(conn: sqlite3.Connection) -> bool:
        try:
            return _integrity_ok(conn)
        except (sqlite3.Error, DatabaseError):
            return False

    # ------------------------------------------------------------------ steps 4 to 6

    @staticmethod
    def _check_demo(live: DatabaseConnection, temp_conn: DatabaseConnection) -> None:
        try:
            if not _has_app_meta(temp_conn):
                raise ServiceError(NOT_AN_APPLICATION_DATABASE)
            backup_is_demo = read_is_demo(temp_conn)
        except (sqlite3.Error, DatabaseError) as exc:
            raise ServiceError(INTEGRITY_FAILED) from exc
        if backup_is_demo != read_is_demo(live):
            raise ServiceError(DEMO_MISMATCH)

    @staticmethod
    def _check_version(temp_conn: DatabaseConnection) -> int:
        try:
            found = _user_version(temp_conn)
        except (sqlite3.Error, DatabaseError) as exc:
            raise ServiceError(INTEGRITY_FAILED) from exc
        if found > _newest_schema_version():
            raise ServiceError(BACKUP_TOO_NEW)
        return found

    @staticmethod
    def _migrate_if_older(temp_conn: DatabaseConnection, found: int, newest: int) -> int | None:
        """Migrate the temporary copy when it is older; NO pre-migration backup is made."""
        if found >= newest:
            return None
        try:
            migrate(temp_conn, before_migrate=None)
        except (sqlite3.Error, DatabaseError) as exc:
            raise ServiceError(MIGRATION_FAILED) from exc
        return found

    # ------------------------------------------------------------------ step 7

    @staticmethod
    def _require_quiescent(live: DatabaseConnection, live_path: Path) -> None:
        if open_connections(live_path) != 1:
            raise ServiceError(OTHER_CONNECTIONS_OPEN)
        if live.in_transaction:
            raise ServiceError(TRANSACTION_OPEN)
        journal = live_path.with_name(live_path.name + _JOURNAL_SUFFIX)
        if journal.exists() or journal.is_symlink():
            raise ServiceError(JOURNAL_PRESENT)

    # ------------------------------------------------------------------ step 8

    def _safety_copy(self, live: DatabaseConnection, live_path: Path) -> Path:
        try:
            result = create_backup(
                live,
                data_dir=self._data_dir,
                identity=self._identity,
                kind=BackupKind.BEFORE_RESTORE,
                clock=self._clock,
                database=live_path,
            )
        except (OSError, sqlite3.Error, DatabaseError) as exc:
            raise ServiceError(SAFETY_COPY_FAILED) from exc
        if not result.verified:
            raise ServiceError(SAFETY_COPY_FAILED)
        rotate(
            self._data_dir,
            self._identity,
            BackupKind.BEFORE_RESTORE,
            BEFORE_RESTORE_KEEP,
            protect=result.path,
            database=live_path,
        )
        return result.path

    # ------------------------------------------------------------------ steps 9 to 11

    def _copy_into_live(
        self,
        temp_conn: DatabaseConnection,
        live: DatabaseConnection,
        safety: Path,
        schema_version: int,
        migrated_from: int | None,
    ) -> int:
        """Copy, check and log; on any failure put the safety copy back. Returns the version."""
        try:
            _copy_into(temp_conn, live)  # step 9
            if not _integrity_ok(live):  # step 10
                msg = "integrity_check failed after the copy"
                raise DatabaseError(msg)
            version = _user_version(live)
            if version != schema_version:
                msg = "unexpected schema version after the copy"
                raise DatabaseError(msg)
            repository.log_event(  # step 11
                repository.WriteContext(live, self._clock, self._operator()),
                "database",
                "restore",
                after={
                    "safety_copy": safety.name,
                    "schema_version": version,
                    "migrated_from": migrated_from,
                },
            )
        except Exception as exc:
            self._put_back(live, safety)
            raise ServiceError(RESTORE_COPY_FAILED) from exc
        return version

    @staticmethod
    def _put_back(live: DatabaseConnection, safety: Path) -> None:
        """Copy the safety copy back into ``live`` (the same API); never raises."""
        try:
            if live.in_transaction:
                live.execute("ROLLBACK")
            source = open_database(safety, read_only=True)
            try:
                source.backup(live)
            finally:
                source.close()
            if not _integrity_ok(live):
                log_event("RESTORE.ROLLBACK_FAILED", level=logging.ERROR)
        except Exception as exc:
            log_exception("RESTORE.ROLLBACK_FAILED", exc)


# --------------------------------------------------------------------------- tmp clean-up


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _remove_entry(path: Path) -> None:
    """Delete a file, a link (the link only, never what it points to) or a folder tree."""
    if _is_link(path):
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
    elif path.is_dir():
        for child in list(path.iterdir()):
            _remove_entry(child)
        path.rmdir()
    else:
        path.unlink()


def clean_tmp(data_dir: Path) -> int:
    """Empty ``<data>/tmp/`` (files and sub-folders) and return how many entries were removed.

    A missing folder is fine (0). A link is removed as a link and never followed out of the
    folder; if ``tmp`` itself is a link nothing is touched. An ``OSError`` on one entry does not
    stop the others (that entry is not counted). The folder itself is kept.
    """
    folder = data_dir / TMP_DIR_NAME
    if _is_link(folder) or not folder.is_dir():
        return 0
    try:
        entries = list(folder.iterdir())
    except OSError:
        return 0
    removed = 0
    for entry in entries:
        try:
            _remove_entry(entry)
        except OSError:
            continue
        removed += 1
    return removed


class _Located(Protocol):
    @property
    def path(self) -> Path: ...


class CleanupContext(Protocol):
    """The part of the application context the hook reads (``location.path`` is the data folder)."""

    @property
    def location(self) -> _Located: ...


def tmp_cleanup_startup(context: CleanupContext) -> None:
    """``StartupHook.run`` callable: empty ``<data>/tmp/``; it never raises for a file problem."""
    removed = clean_tmp(context.location.path)
    if removed:
        log_event("RESTORE.TMP_CLEANED", count=removed)
