# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening the SQLite database (PLAN.md D06, D02, task T1.2).

``open_database`` is the single place where connections are created. It uses the standard-library
``sqlite3`` module only, with plain SQL, and applies the D06 settings:

* ``isolation_level=None``: the module never opens implicit transactions; every transaction is an
  explicit ``BEGIN`` (see :func:`transaction`);
* ``foreign_keys=ON``, ``journal_mode=DELETE`` (never WAL), ``synchronous=FULL``,
  ``secure_delete=ON`` and a busy timeout (read-write connections);
* read-only connections use a ``mode=ro`` URI built with ``Path.as_uri()``, plus ``foreign_keys``,
  ``busy_timeout`` and ``query_only``; they issue no pragma that needs a write lock.

Errors carry a stable ``code`` (the UI translates the code, never the message) and their messages
never contain record contents.

Writes through a read-only connection surface as :class:`ReadOnlyDatabaseError`. The translation is
done by :class:`DatabaseConnection` in ``execute``, ``executemany`` and ``executescript``; cursors
obtained from ``conn.cursor()`` are not translated, so code should call ``conn.execute`` directly.
The translation applies to any ``SQLITE_READONLY`` error, so it also reports a read-write
connection whose database file has turned read-only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from cbrn_dashboard.paths import is_file_writable

if TYPE_CHECKING:
    from _typeshed import SupportsLenAndGetItem

__all__ = [
    "MIN_SQLITE_VERSION",
    "DatabaseConnection",
    "DatabaseError",
    "DatabaseNotFoundError",
    "HotJournalError",
    "ReadOnlyDatabaseError",
    "SqliteTooOldError",
    "check_sqlite_version",
    "database_is_writable",
    "open_database",
    "read_pragmas",
    "transaction",
]

#: Oldest SQLite that supports ``STRICT`` tables.
MIN_SQLITE_VERSION: tuple[int, int, int] = (3, 37, 0)

#: Primary result code ``SQLITE_READONLY`` (extended codes keep it in their low byte).
_SQLITE_READONLY = 8
_PRIMARY_CODE_MASK = 0xFF
_JOURNAL_SUFFIX = "-journal"
_HOT_JOURNAL_MESSAGE = (
    "The database has an unfinished write (hot journal) and cannot be opened read-only."
)

#: SQL parameters: anything ``sqlite3`` accepts (wider than typeshed's private alias).
type _Params = SupportsLenAndGetItem[object] | Mapping[str, object]


# --------------------------------------------------------------------------- errors


class DatabaseError(Exception):
    """Base class of the storage errors; ``code`` is stable and translated by the UI."""

    code: str = "DATABASE_ERROR"


class ReadOnlyDatabaseError(DatabaseError):
    """A write was attempted through a read-only connection (or onto a read-only database)."""

    code = "READ_ONLY"


class HotJournalError(DatabaseError):
    """The database has a hot rollback journal, which a read-only connection cannot recover."""

    code = "HOT_JOURNAL"


class SqliteTooOldError(DatabaseError):
    """The SQLite library is older than :data:`MIN_SQLITE_VERSION`."""

    code = "SQLITE_TOO_OLD"


class DatabaseNotFoundError(DatabaseError):
    """A read-only open was requested for a database file that does not exist."""

    code = "DATABASE_NOT_FOUND"


# --------------------------------------------------------------------------- connection


def _is_read_only_error(exc: sqlite3.Error) -> bool:
    """Whether ``exc`` is ``SQLITE_READONLY`` or one of its extended codes."""
    return (
        exc.sqlite_errorcode & _PRIMARY_CODE_MASK
    ) == _SQLITE_READONLY or exc.sqlite_errorname.startswith("SQLITE_READONLY")


def _raise_if_read_only(exc: sqlite3.Error) -> None:
    if _is_read_only_error(exc):
        msg = "The database is read-only: the change was not made."
        raise ReadOnlyDatabaseError(msg) from exc


class DatabaseConnection(sqlite3.Connection):
    """``sqlite3.Connection`` that reports read-only failures as :class:`ReadOnlyDatabaseError`."""

    read_only: bool = False

    def execute(self, sql: str, parameters: _Params = (), /) -> sqlite3.Cursor:
        try:
            return super().execute(sql, parameters)
        except sqlite3.OperationalError as exc:
            _raise_if_read_only(exc)
            raise

    def executemany(self, sql: str, parameters: Iterable[_Params], /) -> sqlite3.Cursor:
        try:
            return super().executemany(sql, parameters)
        except sqlite3.OperationalError as exc:
            _raise_if_read_only(exc)
            raise

    def executescript(self, sql_script: str, /) -> sqlite3.Cursor:
        # Kept for completeness only: the migration runner must not use it.
        try:
            return super().executescript(sql_script)
        except sqlite3.OperationalError as exc:
            _raise_if_read_only(exc)
            raise


# --------------------------------------------------------------------------- version check


def check_sqlite_version(version: tuple[int, int, int] | None = None) -> None:
    """Raise :class:`SqliteTooOldError` when SQLite is older than 3.37 (``STRICT`` tables).

    ``version`` is injectable for tests; by default it is ``sqlite3.sqlite_version_info``.
    """
    found = sqlite3.sqlite_version_info if version is None else version
    if tuple(found) < MIN_SQLITE_VERSION:
        needed = ".".join(str(part) for part in MIN_SQLITE_VERSION)
        have = ".".join(str(part) for part in found)
        msg = f"SQLite {needed} or newer is required (found {have})."
        raise SqliteTooOldError(msg)


# --------------------------------------------------------------------------- opening


def _journal_path(path: Path) -> Path:
    return path.with_name(path.name + _JOURNAL_SUFFIX)


def _probe_schema(conn: sqlite3.Connection) -> None:
    """Force a read of the schema: it fails for a non-database file or a hot journal."""
    conn.execute("SELECT count(*) FROM sqlite_master").fetchone()


def _open_read_write(path: Path, busy_timeout_ms: int) -> DatabaseConnection:
    conn = sqlite3.connect(path, isolation_level=None, factory=DatabaseConnection)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA secure_delete=ON")
        _probe_schema(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def _open_read_only(path: Path, busy_timeout_ms: int) -> DatabaseConnection:
    if not path.is_file():
        msg = "The database file does not exist."
        raise DatabaseNotFoundError(msg)
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, isolation_level=None, factory=DatabaseConnection)
    conn.read_only = True
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys=ON")
        _probe_schema(conn)
        conn.execute("PRAGMA query_only=ON")
    except ReadOnlyDatabaseError as exc:
        # Nothing is written while opening, so a read-only failure here means SQLite wanted to
        # roll a hot journal back (SQLITE_READONLY_ROLLBACK).
        conn.close()
        raise HotJournalError(_HOT_JOURNAL_MESSAGE) from exc
    except sqlite3.Error as exc:
        conn.close()
        # Any other read failure with a journal beside the file is treated the same way.
        if _journal_path(path).exists():
            raise HotJournalError(_HOT_JOURNAL_MESSAGE) from exc
        raise
    except BaseException:
        conn.close()
        raise
    return conn


def open_database(
    path: Path, *, read_only: bool = False, busy_timeout_ms: int = 5000
) -> DatabaseConnection:
    """Open the database at ``path``; the single place connections are created (D06).

    Read-write mode creates the file when it is missing (the parent folder must exist) and applies
    the D06 pragmas. Read-only mode raises :class:`DatabaseNotFoundError` for a missing file and
    :class:`HotJournalError` for a database with a hot journal. Raises :class:`SqliteTooOldError`
    when the SQLite library is too old.
    """
    check_sqlite_version()
    if busy_timeout_ms < 0:
        msg = "busy_timeout_ms must not be negative"
        raise ValueError(msg)
    if read_only:
        return _open_read_only(path, busy_timeout_ms)
    return _open_read_write(path, busy_timeout_ms)


# --------------------------------------------------------------------------- transactions


@contextmanager
def transaction(
    conn: sqlite3.Connection, *, immediate: bool = True
) -> Iterator[sqlite3.Connection]:
    """Explicit transaction: ``BEGIN [IMMEDIATE]``, ``COMMIT`` on success, ``ROLLBACK`` on error.

    Re-entrant: when a transaction is already open the inner block does nothing itself and the
    outer block owns commit and rollback. A read-only connection raises
    :class:`ReadOnlyDatabaseError` before any ``BEGIN``.
    """
    if isinstance(conn, DatabaseConnection) and conn.read_only:
        msg = "A transaction cannot be started on a read-only database."
        raise ReadOnlyDatabaseError(msg)
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


# --------------------------------------------------------------------------- inspection

_INT_PRAGMAS = ("foreign_keys", "synchronous", "secure_delete", "busy_timeout", "user_version")


def _pragma(conn: sqlite3.Connection, name: str) -> int | str:
    row = conn.execute(f"PRAGMA {name}").fetchone()
    value: object = row[0]
    if isinstance(value, int | str):
        return value
    msg = f"Unexpected value for PRAGMA {name}."
    raise DatabaseError(msg)


def read_pragmas(conn: sqlite3.Connection) -> dict[str, int | str]:
    """Current value of the pragmas D06 cares about (used by tests and the self-test)."""
    values: dict[str, int | str] = {"journal_mode": _pragma(conn, "journal_mode")}
    for name in _INT_PRAGMAS:
        values[name] = _pragma(conn, name)
    return values


def database_is_writable(path: Path) -> bool:
    """Whether the database FILE itself can be written, not only its folder (D02).

    Delegates to :func:`cbrn_dashboard.paths.is_file_writable`: a missing file is not writable.
    """
    return is_file_writable(path)
