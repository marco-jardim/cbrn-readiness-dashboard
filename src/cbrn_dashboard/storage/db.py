# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening the SQLite database (PLAN.md D06, D02, task T1.2).

``open_database`` is the single place where connections are created. It uses the standard-library
``sqlite3`` module only, with plain SQL, and applies the D06 settings:

* ``isolation_level=None``: the module never opens implicit transactions; every transaction is an
  explicit ``BEGIN`` (see :func:`transaction`);
* ``foreign_keys=ON``, ``journal_mode=DELETE`` (never WAL), ``synchronous=FULL``,
  ``secure_delete=ON`` and a busy timeout (read-write connections);
* read-only connections use a ``mode=ro`` URI built by :func:`read_only_uri` (``Path.as_uri()``,
  or an equivalent URI with an empty authority for a UNC path), plus ``foreign_keys``,
  ``busy_timeout`` and ``query_only``; they issue no pragma that needs a write lock.

Errors carry a stable ``code`` (the UI translates the code, never the message) and their messages
never contain record contents.

Writes through a read-only connection surface as :class:`ReadOnlyDatabaseError`. The translation is
done by :class:`DatabaseConnection` in ``execute``, ``executemany`` and ``executescript``; cursors
obtained from ``conn.cursor()`` are not translated, so code should call ``conn.execute`` directly.
The translation goes by the extended result code (:func:`classify_sqlite_error`):
``SQLITE_READONLY_ROLLBACK`` is a hot journal, ``SQLITE_READONLY_DBMOVED`` is
:class:`DatabaseMovedError`, every other ``SQLITE_READONLY*`` is :class:`ReadOnlyDatabaseError`, so
a read-write connection whose database file has turned read-only is reported as well.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

from cbrn_dashboard.paths import is_file_writable

if TYPE_CHECKING:
    from _typeshed import SupportsLenAndGetItem

__all__ = [
    "MIN_SQLITE_VERSION",
    "DatabaseConnection",
    "DatabaseError",
    "DatabaseMovedError",
    "DatabaseNotFoundError",
    "HotJournalError",
    "NotADatabaseError",
    "ReadOnlyDatabaseError",
    "SqliteTooOldError",
    "check_sqlite_version",
    "classify_sqlite_error",
    "database_is_writable",
    "open_database",
    "read_only_uri",
    "read_pragmas",
    "transaction",
]

#: Oldest SQLite that supports ``STRICT`` tables.
MIN_SQLITE_VERSION: tuple[int, int, int] = (3, 37, 0)

#: Primary result codes (extended codes keep the primary code in their low byte).
_SQLITE_READONLY = 8
_SQLITE_BUSY = 5
_SQLITE_LOCKED = 6
_SQLITE_NOTADB = 26
#: Extended result codes that get their own error.
_SQLITE_READONLY_ROLLBACK = 776
_SQLITE_READONLY_DBMOVED = 1032
_PRIMARY_CODE_MASK = 0xFF
_JOURNAL_SUFFIX = "-journal"
_HOT_JOURNAL_MESSAGE = (
    "The database has an unfinished write (hot journal) and cannot be opened read-only."
)
_READ_ONLY_MESSAGE = "The database is read-only: the change was not made."
_MOVED_MESSAGE = "The database file was moved or replaced while it was open."
_NOT_A_DATABASE_MESSAGE = "The file is not a database."

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


class DatabaseMovedError(DatabaseError):
    """The database file was moved, renamed or replaced while the connection was open."""

    code = "DATABASE_MOVED"


class NotADatabaseError(DatabaseError):
    """The file exists but is not an SQLite database (or is corrupt at its first page)."""

    code = "NOT_A_DATABASE"


# --------------------------------------------------------------------------- connection

_MESSAGES: Mapping[type[DatabaseError], str] = {
    HotJournalError: _HOT_JOURNAL_MESSAGE,
    DatabaseMovedError: _MOVED_MESSAGE,
    ReadOnlyDatabaseError: _READ_ONLY_MESSAGE,
    NotADatabaseError: _NOT_A_DATABASE_MESSAGE,
}


def classify_sqlite_error(code: int, name: str) -> type[DatabaseError] | None:
    """The :class:`DatabaseError` subclass for an SQLite result, or ``None`` when it has none.

    ``code`` is the (extended) result code and ``name`` its symbolic name.
    ``SQLITE_READONLY_ROLLBACK`` (776) is a hot journal, ``SQLITE_READONLY_DBMOVED`` (1032) is
    :class:`DatabaseMovedError`, every other ``SQLITE_READONLY*`` is
    :class:`ReadOnlyDatabaseError` and ``SQLITE_NOTADB`` (26) is :class:`NotADatabaseError`.
    """
    if code == _SQLITE_READONLY_ROLLBACK:
        return HotJournalError
    if code == _SQLITE_READONLY_DBMOVED:
        return DatabaseMovedError
    primary = code & _PRIMARY_CODE_MASK
    if primary == _SQLITE_READONLY or name.startswith("SQLITE_READONLY"):
        return ReadOnlyDatabaseError
    if primary == _SQLITE_NOTADB:
        return NotADatabaseError
    return None


def _translate(exc: sqlite3.Error) -> DatabaseError | None:
    """The translated error for ``exc`` (read-only family only), or ``None`` to re-raise as is."""
    error_class = classify_sqlite_error(exc.sqlite_errorcode, exc.sqlite_errorname)
    if error_class is None or error_class is NotADatabaseError:
        # "Not a database" is reported by the read-only open only; elsewhere callers keep seeing
        # the sqlite3 error.
        return None
    return error_class(_MESSAGES[error_class])


def _raise_if_read_only(exc: sqlite3.Error) -> None:
    translated = _translate(exc)
    if translated is not None:
        raise translated from exc


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


def _journal_has_content(path: Path) -> bool:
    """Whether a rollback journal beside ``path`` exists and is not empty (empty means stale)."""
    try:
        return _journal_path(path).stat().st_size > 0
    except OSError:
        return False


def _percent_encode(text: str) -> str:
    """Percent-encode the UTF-8 bytes of ``text``; only ASCII letters, digits and ``-._~/`` stay."""
    parts: list[str] = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if byte < 0x80 and (char.isalnum() or char in "-._~/"):
            parts.append(char)
        else:
            parts.append(f"%{byte:02X}")
    return "".join(parts)


def read_only_uri(path: PurePath) -> str:
    """The ``file:`` URI with ``?mode=ro`` for ``path``; pure, it never touches the file system.

    ``Path.absolute()`` is used, not ``resolve()``: ``resolve()`` turns a mapped network drive into
    its UNC form. A drive path keeps ``Path.as_uri()``. SQLite rejects a URI with an authority, so
    a UNC path (``\\\\server\\share\\...``) becomes ``file:////server/share/...``: an empty
    authority followed by a path that itself starts with ``//server/share``.
    """
    absolute = path.absolute() if isinstance(path, Path) else path
    drive = absolute.drive
    if drive.startswith("\\\\"):
        share = drive.replace("\\", "/")  # //server/share
        rest = "/".join(absolute.parts[1:])
        uri = "file:" + "//" + _percent_encode(share) + "/" + _percent_encode(rest)
    else:
        uri = absolute.as_uri()
    return uri + "?mode=ro"


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
    conn = sqlite3.connect(
        read_only_uri(path), uri=True, isolation_level=None, factory=DatabaseConnection
    )
    conn.read_only = True
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys=ON")
        _probe_schema(conn)
        conn.execute("PRAGMA query_only=ON")
    except ReadOnlyDatabaseError as exc:
        # Nothing is written while opening, so a read-only failure here with a non-empty journal
        # beside the file means SQLite wanted to roll a hot journal back.
        conn.close()
        if _journal_has_content(path):
            raise HotJournalError(_HOT_JOURNAL_MESSAGE) from exc
        raise
    except DatabaseError:
        # Already translated by extended code (hot journal, moved database).
        conn.close()
        raise
    except sqlite3.Error as exc:
        conn.close()
        error_class = classify_sqlite_error(exc.sqlite_errorcode, exc.sqlite_errorname)
        if error_class is NotADatabaseError:
            raise NotADatabaseError(_NOT_A_DATABASE_MESSAGE) from exc
        primary = exc.sqlite_errorcode & _PRIMARY_CODE_MASK
        # A busy or locked database is not an unfinished write; an empty journal is stale.
        if primary not in (_SQLITE_BUSY, _SQLITE_LOCKED) and _journal_has_content(path):
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
    :class:`HotJournalError` for a database with a hot journal and :class:`NotADatabaseError` for
    a file that is not a database. Raises :class:`SqliteTooOldError` when the SQLite library is too
    old.
    """
    check_sqlite_version()
    if busy_timeout_ms < 0:
        msg = "busy_timeout_ms must not be negative"
        raise ValueError(msg)
    if read_only:
        return _open_read_only(path, busy_timeout_ms)
    return _open_read_write(path, busy_timeout_ms)


# --------------------------------------------------------------------------- transactions


#: Numbers for savepoint names; a name is ``cbrn_sp_<n>``, so it is always a valid identifier.
_savepoint_numbers = itertools.count(1)
_ROLLBACK_FAILED_NOTE = "The rollback itself also failed."


def _rollback(conn: sqlite3.Connection, *statements: str, original: BaseException) -> None:
    """Run the rollback ``statements``; if one fails, ``original`` stays the error raised."""
    try:
        if conn.in_transaction:
            for statement in statements:
                conn.execute(statement)
    except (sqlite3.Error, DatabaseError):
        original.add_note(_ROLLBACK_FAILED_NOTE)


@contextmanager
def transaction(
    conn: sqlite3.Connection, *, immediate: bool = True
) -> Iterator[sqlite3.Connection]:
    """Explicit transaction: ``BEGIN [IMMEDIATE]``, ``COMMIT`` on success, ``ROLLBACK`` on error.

    Nesting is real: when a transaction is already open the inner block is a ``SAVEPOINT``. It is
    released on success; on any exception it is rolled back to the savepoint (the inner block's
    writes are undone, nothing else) and the exception is re-raised. A caller that catches that
    exception can carry on and the outer block can still commit; one that lets it propagate makes
    the outer block roll back everything. The outermost block owns ``COMMIT`` and ``ROLLBACK``.
    If a rollback statement fails, the original exception is the one raised. A read-only
    connection raises :class:`ReadOnlyDatabaseError` before any statement.
    """
    if isinstance(conn, DatabaseConnection) and conn.read_only:
        msg = "A transaction cannot be started on a read-only database."
        raise ReadOnlyDatabaseError(msg)
    if conn.in_transaction:
        name = f"cbrn_sp_{next(_savepoint_numbers)}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
            conn.execute(f"RELEASE {name}")
        except BaseException as exc:
            _rollback(conn, f"ROLLBACK TO {name}", f"RELEASE {name}", original=exc)
            raise
        return
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException as exc:
        _rollback(conn, "ROLLBACK", original=exc)
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
