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
the database is newer than the newest migration. :func:`backup_before_migration` copies a non-empty
database with SQLite's online backup API before the first migration runs (task T7.1 later moves it
into ``storage/backup.py``).

Errors derive from :class:`~cbrn_dashboard.storage.db.DatabaseError`, carry a stable ``code`` and
never contain SQL text or record contents.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from importlib import resources
from pathlib import Path

from cbrn_dashboard.storage.db import DatabaseConnection, DatabaseError, open_database

__all__ = [
    "DEFAULT_PACKAGE",
    "REBUILD_FLAG",
    "DatabaseIdentity",
    "DatabaseTooNewError",
    "Migration",
    "MigrationError",
    "MigrationFailedError",
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

BACKUP_DIR_NAME = "backups"
DEMO_DIR_NAME = "demo"

_FILE_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_BACKUP_NAME = re.compile(r"^pre-migration-v\d{4}-(\d{3,})\.sqlite3$")
_COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


# --------------------------------------------------------------------------- errors


class MigrationError(DatabaseError):
    """Base class of the migration errors."""

    code = "MIGRATION_ERROR"


class MigrationSyntaxError(MigrationError):
    """A migration file ends with an incomplete SQL statement."""

    code = "MIGRATION_SYNTAX"


class MigrationSequenceError(MigrationError):
    """The migration files are not contiguous from 0001, or a file name is invalid."""

    code = "MIGRATION_SEQUENCE"


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
    """Whether the leading comment block of ``sql`` holds the table-rebuild flag line."""
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("--"):
            return False
        if stripped == REBUILD_FLAG:
            return True
    return False


def load_migrations(package: str = DEFAULT_PACKAGE) -> list[Migration]:
    """Load the ``.sql`` files of ``package`` through ``importlib.resources``, sorted by number.

    Raises :class:`MigrationSequenceError` for a file whose name does not match
    ``NNNN_name.sql`` and when the numbers are not contiguous from 0001.
    """
    found: list[Migration] = []
    for entry in resources.files(package).iterdir():
        if not entry.name.endswith(".sql") or not entry.is_file():
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


def split_statements(sql: str) -> list[str]:
    """Split ``sql`` into single statements without ``executescript()``.

    The text is accumulated line by line and cut whenever :func:`sqlite3.complete_statement` says
    the buffer is a complete statement. That handles ``CREATE TRIGGER ... BEGIN ...; END;`` bodies
    and semicolons inside string literals. Chunks that hold only whitespace or comments are
    skipped; a non-empty unterminated tail raises :class:`MigrationSyntaxError`.
    """
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            if not _is_blank(buffer):
                statements.append(buffer.strip())
            buffer = ""
    if not _is_blank(buffer):
        msg = "The migration ends with an incomplete SQL statement."
        raise MigrationSyntaxError(msg)
    return statements


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

    Raises :class:`MigrationSequenceError` when the files are not contiguous from 0001 (checked
    first, so nothing is executed), :class:`DatabaseTooNewError` when ``user_version`` is higher
    than the newest migration (the database is left untouched), :class:`MigrationSyntaxError` for
    an incomplete statement and :class:`MigrationFailedError` when a migration fails; migrations
    committed before the failing one stay applied.
    """
    if migrations is not None and package is not None:
        msg = "Pass either migrations or package, not both."
        raise ValueError(msg)
    if migrations is None:
        ordered = load_migrations(DEFAULT_PACKAGE if package is None else package)
    else:
        ordered = _ordered(migrations)

    target = ordered[-1].number if ordered else 0
    current = _user_version(conn)
    if current > target:
        raise DatabaseTooNewError(current, target)

    pending = [migration for migration in ordered if migration.number > current]
    if not pending:
        return MigrationResult(current, current, ())

    prepared: list[tuple[Migration, list[str]]] = []
    for migration in pending:
        try:
            prepared.append((migration, split_statements(migration.sql)))
        except MigrationSyntaxError as exc:
            msg = f"Migration {migration.number:04d} ends with an incomplete SQL statement."
            raise MigrationSyntaxError(msg) from exc

    if before_migrate is not None:
        before_migrate(current, target)
    applied: list[int] = []
    for migration, statements in prepared:
        _apply(conn, migration, statements)
        applied.append(migration.number)
    return MigrationResult(current, target, tuple(applied))


# --------------------------------------------------------------------------- backup


class DatabaseIdentity(StrEnum):
    """Which database a connection belongs to; always passed explicitly, never inferred."""

    REAL = "real"
    DEMO = "demo"


def _next_backup_number(folder: Path) -> int:
    highest = 0
    for entry in folder.iterdir():
        match = _BACKUP_NAME.fullmatch(entry.name)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def backup_before_migration(
    conn: sqlite3.Connection,
    *,
    data_dir: Path,
    identity: DatabaseIdentity,
    from_version: int,
    enabled: bool = True,
) -> Path | None:
    """Copy a non-empty database with SQLite's online backup API; return the new file or ``None``.

    A real database goes to ``<data_dir>/backups/``, a demo database to
    ``<data_dir>/demo/backups/``. ``None`` is returned (and nothing is written) when ``enabled`` is
    false, for example when the restore service migrates a temporary copy, and when the database
    has no user tables (a fresh file). The file name is
    ``pre-migration-v<from_version>-<n>.sqlite3`` with the next free sequence number ``n``.
    """
    if not enabled:
        return None
    count: object = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='table'"
    ).fetchone()[0]
    if count == 0:
        return None
    folder = data_dir / BACKUP_DIR_NAME
    if identity is DatabaseIdentity.DEMO:
        folder = data_dir / DEMO_DIR_NAME / BACKUP_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / (
        f"pre-migration-v{from_version:04d}-{_next_backup_number(folder):03d}.sqlite3"
    )
    target = open_database(destination)
    try:
        conn.backup(target)
    except BaseException:
        target.close()
        destination.unlink(missing_ok=True)
        raise
    target.close()
    return destination


# --------------------------------------------------------------------------- convenience


def open_and_migrate(
    path: Path,
    *,
    data_dir: Path,
    identity: DatabaseIdentity,
    backup: bool = True,
    package: str | None = None,
) -> DatabaseConnection:
    """Open the database at ``path`` and migrate it, backing it up first when it is not empty.

    The connection is closed before any error propagates. ``package`` replaces the real migration
    package (for tests).
    """
    conn = open_database(path)

    def before(from_version: int, _to_version: int) -> None:
        backup_before_migration(
            conn,
            data_dir=data_dir,
            identity=identity,
            from_version=from_version,
            enabled=backup,
        )

    try:
        migrate(conn, package=package, before_migrate=before)
    except BaseException:
        conn.close()
        raise
    return conn
