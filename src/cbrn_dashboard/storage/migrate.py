# SPDX-License-Identifier: GPL-3.0-or-later
"""Schema migrations (PLAN.md D06, task T1.3).

Migrations are numbered ``.sql`` files in the package ``cbrn_dashboard.storage.migrations`` and are
loaded with :mod:`importlib.resources`, so they also work inside the frozen executable. The schema
version is ``PRAGMA user_version``.

The runner never uses ``Connection.executescript()``: Python's ``sqlite3`` commits a pending
transaction before it runs a script. Instead each file is split into statements with
:func:`sqlite3.complete_statement` and every statement runs through ``execute()`` inside one
explicit ``BEGIN IMMEDIATE`` ... ``COMMIT`` per migration. ``user_version`` is set in the same
transaction (it is transactional), and any error ends in ``ROLLBACK``.

``PRAGMA foreign_keys`` does nothing inside a transaction. A migration that rebuilds tables says so
in its leading comment block with the line ``-- migrate: table-rebuild``; for such a migration the
runner switches foreign keys off before ``BEGIN``, runs ``PRAGMA foreign_key_check`` before
``COMMIT`` (any row rolls the migration back) and switches foreign keys on again afterwards.

The runner refuses to run when the available migration files are not contiguous from 0001 and when
the database is newer than the newest migration. :func:`backup_before_migration` (implemented in
``storage/backup.py``, task T7.1, and re-exported here) copies a non-empty database with SQLite's
online backup API before the first migration runs.

Errors derive from :class:`~cbrn_dashboard.storage.db.DatabaseError`, carry a stable ``code`` and
never contain SQL text or record contents.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.storage.backup import DatabaseIdentity, backup_before_migration
from cbrn_dashboard.storage.db import DatabaseConnection, DatabaseError, open_database

__all__ = [
    "DEFAULT_PACKAGE",
    "REBUILD_FLAG",
    "DatabaseIdentity",
    "DatabaseTooNewError",
    "Migration",
    "MigrationError",
    "MigrationFailedError",
    "MigrationInTransactionError",
    "MigrationResult",
    "MigrationSequenceError",
    "MigrationSyntaxError",
    "backup_before_migration",
    "load_migrations",
    "migrate",
    "open_and_migrate",
    "split_statements",
]

#: The package that holds the real migration files.
DEFAULT_PACKAGE = "cbrn_dashboard.storage.migrations"

#: Header comment line that flags a migration as a table rebuild.
REBUILD_FLAG = "-- migrate: table-rebuild"

_FILE_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
#: A header comment line that looks like a ``migrate:`` directive (any case or spacing).
_DIRECTIVE = re.compile(r"(?i)^--\s*migrate\s*:")
#: The first one or two keywords of a statement, after leading whitespace and comments.
_LEADING_WORDS = re.compile(
    r"^(?:\s|--[^\n]*+|/\*.*?\*/)*+([A-Za-z]+)(?:(?:\s|--[^\n]*+|/\*.*?\*/)++([A-Za-z]+))?",
    re.DOTALL,
)
#: Statements a migration may not start with: the runner owns the transaction, ``user_version``
#: and ``foreign_keys``, and a migration must stay inside the one database file.
_FORBIDDEN_FIRST_WORDS = frozenset(
    {
        "BEGIN",
        "COMMIT",
        "END",
        "ROLLBACK",
        "SAVEPOINT",
        "RELEASE",
        "VACUUM",
        "ATTACH",
        "DETACH",
        "PRAGMA",
    }
)


# --------------------------------------------------------------------------- errors


class MigrationError(DatabaseError):
    """Base class of the migration errors."""

    code = "MIGRATION_ERROR"


class MigrationSyntaxError(MigrationError):
    """A migration file is refused: incomplete or forbidden statement, or a misspelled flag."""

    code = "MIGRATION_SYNTAX"


class MigrationSequenceError(MigrationError):
    """The migration files are not contiguous from 0001, or a file name is invalid."""

    code = "MIGRATION_SEQUENCE"


class MigrationInTransactionError(MigrationError):
    """``migrate()`` was called while the connection already had an open transaction."""

    code = "MIGRATION_IN_TRANSACTION"


class MigrationFailedError(MigrationError):
    """A migration failed and was rolled back; earlier migrations stay applied."""

    code = "MIGRATION_FAILED"

    def __init__(self, number: int) -> None:
        super().__init__(f"Migration {number:04d} failed and was rolled back.")
        self.number = number


class DatabaseTooNewError(DatabaseError):
    """The database was written by a newer program version than this one."""

    code = "DATABASE_TOO_NEW"

    def __init__(self, found: int, supported: int) -> None:
        super().__init__(
            f"The database has schema version {found}; this program supports up to {supported}."
        )
        self.found = found
        self.supported = supported


# --------------------------------------------------------------------------- loading


@dataclass(frozen=True)
class Migration:
    """One numbered migration file."""

    number: int
    name: str
    sql: str
    rebuild: bool = False


@dataclass(frozen=True)
class MigrationResult:
    """What :func:`migrate` did: versions before and after, and the numbers it applied."""

    from_version: int
    to_version: int
    applied: tuple[int, ...]


def _has_rebuild_flag(sql: str) -> bool:
    """Whether the leading comment block of ``sql`` holds the table-rebuild flag line.

    Raises :class:`MigrationSyntaxError` for a header line that looks like a ``migrate:``
    directive (any case or spacing) but is not exactly :data:`REBUILD_FLAG`; a misspelled flag
    must never be silently taken for "no flag".
    """
    flagged = False
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("--"):
            break
        if stripped == REBUILD_FLAG:
            flagged = True
        elif _DIRECTIVE.match(stripped):
            msg = f"A header comment looks like a migrate directive but is not {REBUILD_FLAG!r}."
            raise MigrationSyntaxError(msg)
    return flagged


def load_migrations(package: str = DEFAULT_PACKAGE) -> list[Migration]:
    """Load the ``.sql`` files of ``package`` through ``importlib.resources``, sorted by number.

    Raises :class:`MigrationSequenceError` for a file whose name does not match
    ``NNNN_name.sql`` and when the numbers are not contiguous from 0001.
    """
    found: list[Migration] = []
    for entry in resources.files(package).iterdir():
        if not entry.name.lower().endswith(".sql") or not entry.is_file():
            continue
        match = _FILE_NAME.fullmatch(entry.name)
        if match is None:
            msg = f"The migration file name {entry.name!r} does not match NNNN_name.sql."
            raise MigrationSequenceError(msg)
        sql = entry.read_text(encoding="utf-8-sig")
        found.append(
            Migration(
                number=int(match.group(1)),
                name=match.group(2),
                sql=sql,
                rebuild=_has_rebuild_flag(sql),
            )
        )
    return _ordered(found)


def _ordered(migrations: Sequence[Migration]) -> list[Migration]:
    """Sort by number and require the numbers to be exactly 1, 2, 3, ... (no hole, no duplicate)."""
    ordered = sorted(migrations, key=lambda migration: migration.number)
    for expected, migration in enumerate(ordered, start=1):
        if migration.number != expected:
            msg = (
                "The migration files are not contiguous from 0001 "
                f"(expected {expected:04d}, found {migration.number:04d})."
            )
            raise MigrationSequenceError(msg)
    return ordered


# --------------------------------------------------------------------------- splitting


def _is_blank(text: str) -> bool:
    """Whether ``text`` holds nothing but whitespace, comments and stray semicolons."""
    return not _COMMENT.sub(" ", text).replace(";", " ").strip()


def _leading_words(statement: str) -> tuple[str, str]:
    """The first two keywords of ``statement`` in upper case (``""`` when absent)."""
    match = _LEADING_WORDS.match(statement)
    if match is None:
        return "", ""
    return match.group(1).upper(), (match.group(2) or "").upper()


def split_statements(sql: str) -> list[str]:
    """Split ``sql`` into single statements without ``executescript()``.

    The text is scanned character by character; at every ``;`` the buffer is cut when
    :func:`sqlite3.complete_statement` says it is a complete statement, so several statements on
    one line are split too. That handles ``CREATE TRIGGER ... BEGIN ...; END;`` bodies, semicolons
    inside string literals and comments. Chunks that hold only whitespace or comments are skipped;
    a non-empty unterminated tail raises :class:`MigrationSyntaxError`.

    A statement whose first keyword is ``BEGIN``, ``COMMIT``, ``END``, ``ROLLBACK``,
    ``SAVEPOINT``, ``RELEASE``, ``VACUUM``, ``ATTACH``, ``DETACH`` or ``PRAGMA`` is refused with
    :class:`MigrationSyntaxError` (the runner owns the transaction, ``user_version`` and
    ``foreign_keys``). A ``CREATE TRIGGER ... BEGIN ... END;`` is one statement that starts with
    ``CREATE`` and stays allowed.
    """
    statements: list[str] = []
    start = 0
    for index, char in enumerate(sql):
        if char != ";":
            continue
        chunk = sql[start : index + 1]
        if sqlite3.complete_statement(chunk):
            if not _is_blank(chunk):
                statements.append(chunk.strip())
            start = index + 1
    if not _is_blank(sql[start:]):
        msg = "The migration ends with an incomplete SQL statement."
        raise MigrationSyntaxError(msg)
    for statement in statements:
        first = _leading_words(statement)[0]
        if first in _FORBIDDEN_FIRST_WORDS:
            msg = f"A migration statement starts with {first}, which a migration may not use."
            raise MigrationSyntaxError(msg)
    return statements


def _refuse_drop_table(statements: Sequence[str]) -> None:
    """Refuse a statement that starts with ``DROP TABLE`` (used for migrations without the flag).

    Without foreign keys switched off, dropping a parent table runs an implicit ``DELETE FROM``
    that cascades into the child tables. The scan only looks at the leading keywords of each
    statement; a ``DROP TABLE`` inside a trigger body is not detected.
    """
    for statement in statements:
        if _leading_words(statement) == ("DROP", "TABLE"):
            msg = f"DROP TABLE needs the {REBUILD_FLAG!r} header; the migration has none."
            raise MigrationSyntaxError(msg)


# --------------------------------------------------------------------------- running


def _user_version(conn: sqlite3.Connection) -> int:
    value: object = conn.execute("PRAGMA user_version").fetchone()[0]
    if not isinstance(value, int):
        msg = "Unexpected value for PRAGMA user_version."
        raise DatabaseError(msg)
    return value


def _rollback(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.execute("ROLLBACK")


def _apply(conn: DatabaseConnection, migration: Migration, statements: Sequence[str]) -> None:
    """Run one migration in its own explicit transaction."""
    number = migration.number
    if migration.rebuild:
        conn.execute("PRAGMA foreign_keys=OFF")  # a no-op once BEGIN has run
    try:
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in statements:
                conn.execute(statement)
            if migration.rebuild and conn.execute("PRAGMA foreign_key_check").fetchall():
                msg = "foreign_key_check reported violations"
                raise sqlite3.IntegrityError(msg)
            conn.execute(f"PRAGMA user_version = {int(number)}")
            conn.execute("COMMIT")
        except Exception as exc:
            _rollback(conn)
            raise MigrationFailedError(number) from exc
        except BaseException:
            _rollback(conn)
            raise
    finally:
        if migration.rebuild:
            conn.execute("PRAGMA foreign_keys=ON")


def migrate(
    conn: DatabaseConnection,
    *,
    migrations: Sequence[Migration] | None = None,
    package: str | None = None,
    before_migrate: Callable[[int, int], None] | None = None,
) -> MigrationResult:
    """Bring the database behind ``conn`` to the newest schema version.

    ``migrations`` or ``package`` (both optional, not together) replace the real migration files;
    that is meant for tests. ``before_migrate(from_version, to_version)`` is called exactly once,
    before the first migration, and only when there is something to apply (the backup hook).

    Raises :class:`MigrationInTransactionError` (code ``MIGRATION_IN_TRANSACTION``) when ``conn``
    already has an open transaction (checked first; the caller's transaction is left untouched),
    :class:`MigrationSequenceError` when the files are not contiguous from 0001 or ``user_version``
    is negative (checked first, so nothing is executed), :class:`DatabaseTooNewError` when
    ``user_version`` is higher than the newest migration (the database is left untouched),
    :class:`MigrationSyntaxError` for an incomplete or forbidden statement, a misspelled rebuild
    flag or a ``DROP TABLE`` without the flag (all before the backup hook), and
    :class:`MigrationFailedError` when a migration fails; migrations committed before the failing
    one stay applied.
    """
    if conn.in_transaction:
        msg = "A transaction is already open on this connection; commit or roll it back first."
        raise MigrationInTransactionError(msg)
    if migrations is not None and package is not None:
        msg = "Pass either migrations or package, not both."
        raise ValueError(msg)
    if migrations is None:
        ordered = load_migrations(DEFAULT_PACKAGE if package is None else package)
    else:
        ordered = _ordered(migrations)

    target = ordered[-1].number if ordered else 0
    current = _user_version(conn)
    if current < 0:
        msg = f"The database has a negative schema version ({current})."
        raise MigrationSequenceError(msg)
    if current > target:
        raise DatabaseTooNewError(current, target)

    pending = [migration for migration in ordered if migration.number > current]
    if not pending:
        return MigrationResult(current, current, ())

    prepared: list[tuple[Migration, list[str]]] = []
    for migration in pending:
        try:
            _has_rebuild_flag(migration.sql)  # raises for a misspelled flag line
            statements = split_statements(migration.sql)
            if not migration.rebuild:
                _refuse_drop_table(statements)
        except MigrationSyntaxError as exc:
            msg = f"Migration {migration.number:04d} is refused: {exc}"
            raise MigrationSyntaxError(msg) from exc
        prepared.append((migration, statements))

    if before_migrate is not None:
        before_migrate(current, target)
    applied: list[int] = []
    for migration, statements in prepared:
        _apply(conn, migration, statements)
        applied.append(migration.number)
    return MigrationResult(current, target, tuple(applied))


# --------------------------------------------------------------------------- backup


#
# The pre-migration backup lives in ``storage/backup.py`` (task T7.1) and is re-exported here, with
# ``DatabaseIdentity``, so existing imports from this module keep working.


# --------------------------------------------------------------------------- convenience


def open_and_migrate(
    path: Path,
    *,
    data_dir: Path,
    identity: DatabaseIdentity,
    backup: bool = True,
    package: str | None = None,
    clock: Clock | None = None,
) -> DatabaseConnection:
    """Open the database at ``path`` and migrate it, backing it up first when it is not empty.

    The connection is closed before any error propagates. ``package`` replaces the real migration
    package (for tests); ``clock`` stamps the pre-migration backup (default: the system clock).
    """
    conn = open_database(path)

    def before(from_version: int, _to_version: int) -> None:
        backup_before_migration(
            conn,
            data_dir=data_dir,
            identity=identity,
            from_version=from_version,
            enabled=backup,
            clock=clock,
        )

    try:
        migrate(conn, package=package, before_migrate=before)
    except BaseException:
        conn.close()
        raise
    return conn
