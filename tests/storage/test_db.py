# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for ``cbrn_dashboard.storage.db`` (PLAN T1.2); real SQLite files under ``tmp_path``."""

from __future__ import annotations

import shutil
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

import pytest

from cbrn_dashboard.storage.db import (
    MIN_SQLITE_VERSION,
    DatabaseError,
    DatabaseNotFoundError,
    HotJournalError,
    ReadOnlyDatabaseError,
    SqliteTooOldError,
    check_sqlite_version,
    database_is_writable,
    open_database,
    read_pragmas,
    transaction,
)

SCHEMA = (
    "CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT",
    "CREATE TABLE child ("
    " id INTEGER PRIMARY KEY,"
    " parent_id INTEGER NOT NULL REFERENCES parent (id)"
    ") STRICT",
    "CREATE TABLE item (id INTEGER PRIMARY KEY, label TEXT NOT NULL) STRICT",
)

ODD_PATH_PARTS = ("pasta com espaço ção", "dados é.sqlite3")


def _create(path: Path) -> None:
    """Create a small populated database at ``path`` (read-write, then closed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(open_database(path)) as conn:
        for statement in SCHEMA:
            conn.execute(statement)
        conn.execute("INSERT INTO item (id, label) VALUES (1, 'one')")


def _count(conn: sqlite3.Connection) -> int:
    value: int = conn.execute("SELECT count(*) FROM item").fetchone()[0]
    return value


# --------------------------------------------------------------------------- pragmas and FK


def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with closing(open_database(path)) as conn:
        conn.execute("INSERT INTO parent (id) VALUES (1)")
        conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 1)")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO child (id, parent_id) VALUES (2, 99)")


def test_pragmas_read_back(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    with closing(open_database(path, busy_timeout_ms=1234)) as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY) STRICT")
        conn.execute("INSERT INTO t (id) VALUES (1)")
        pragmas = read_pragmas(conn)
        assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]
    assert pragmas == {
        "foreign_keys": 1,
        "journal_mode": "delete",
        "synchronous": 2,
        "secure_delete": 1,
        "busy_timeout": 1234,
        "user_version": 0,
    }
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]


def test_default_busy_timeout_and_row_factory(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        assert read_pragmas(conn)["busy_timeout"] == 5000
        assert conn.row_factory is sqlite3.Row
        assert conn.isolation_level is None
        assert not conn.in_transaction


def test_negative_busy_timeout_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="busy_timeout_ms"):
        open_database(tmp_path / "db.sqlite3", busy_timeout_ms=-1)


def test_read_write_open_creates_the_file(tmp_path: Path) -> None:
    path = tmp_path / "new.sqlite3"
    assert not path.exists()
    with closing(open_database(path)):
        pass
    assert path.is_file()


def test_strict_tables_work_on_the_runtime_sqlite(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        conn.execute("CREATE TABLE s (id INTEGER PRIMARY KEY, n INTEGER NOT NULL) STRICT")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO s (id, n) VALUES (1, 'not a number')")


# --------------------------------------------------------------------------- read-only


@pytest.mark.parametrize(
    "parts",
    [("plain", "db.sqlite3"), ODD_PATH_PARTS],
    ids=["plain", "spaces-and-non-ascii"],
)
def test_read_only_connection_reads_and_rejects_writes(
    tmp_path: Path, parts: tuple[str, str]
) -> None:
    path = tmp_path.joinpath(*parts)
    _create(path)
    with closing(open_database(path, read_only=True)) as conn:
        assert conn.read_only is True
        assert _count(conn) == 1
        assert read_pragmas(conn)["foreign_keys"] == 1
        with pytest.raises(ReadOnlyDatabaseError) as insert_error:
            conn.execute("INSERT INTO item (id, label) VALUES (2, 'two')")
        assert insert_error.value.code == "READ_ONLY"
        assert isinstance(insert_error.value.__cause__, sqlite3.OperationalError)
        with pytest.raises(ReadOnlyDatabaseError):
            conn.execute("CREATE TABLE extra (id INTEGER PRIMARY KEY) STRICT")
        with pytest.raises(ReadOnlyDatabaseError):
            conn.executemany("INSERT INTO item (id, label) VALUES (?, ?)", [(3, "x"), (4, "y")])
        with pytest.raises(ReadOnlyDatabaseError):
            conn.executescript("CREATE TABLE extra2 (id INTEGER PRIMARY KEY)")
        assert _count(conn) == 1
    with closing(open_database(path)) as conn:
        assert _count(conn) == 1


def test_read_only_open_does_not_touch_the_folder(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    before = sorted(p.name for p in tmp_path.iterdir())
    with closing(open_database(path, read_only=True)) as conn:
        assert _count(conn) == 1
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_read_only_open_of_a_missing_file(tmp_path: Path) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()
    with pytest.raises(DatabaseNotFoundError) as error:
        open_database(folder / "missing.sqlite3", read_only=True)
    assert error.value.code == "DATABASE_NOT_FOUND"
    assert list(folder.iterdir()) == []


# --------------------------------------------------------------------------- hot journal


ROWS = 3000
PAYLOAD = "a" * 300


def _make_hot_journal_copy(tmp_path: Path) -> Path:
    """Return a copy of a database that has a genuine hot rollback journal.

    A writer with a tiny page cache updates thousands of rows in one uncommitted transaction;
    SQLite must spill dirty pages into the database file, which first syncs the rollback journal.
    The database and its journal are then copied byte for byte (without committing) into another
    folder; the copy is a database with a hot journal.
    """
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = source_dir / "hot.sqlite3"
    with closing(open_database(source)) as setup:
        setup.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, payload TEXT NOT NULL) STRICT")
        with transaction(setup):
            setup.executemany(
                "INSERT INTO t (id, payload) VALUES (?, ?)",
                ((i, PAYLOAD) for i in range(ROWS)),
            )

    target_dir = tmp_path / "copy"
    target_dir.mkdir()
    target = target_dir / source.name
    writer = open_database(source)
    try:
        writer.execute("PRAGMA cache_size=1")
        writer.execute("BEGIN")
        writer.execute("UPDATE t SET payload = ?", ("b" * 300,))
        journal = source.with_name(source.name + "-journal")
        assert journal.is_file()
        shutil.copyfile(source, target)
        shutil.copyfile(journal, target.with_name(target.name + "-journal"))
        assert target.with_name(target.name + "-journal").stat().st_size > 0
        writer.execute("ROLLBACK")
    finally:
        writer.close()
    return target


def test_read_only_open_of_a_hot_journal_database(tmp_path: Path) -> None:
    target = _make_hot_journal_copy(tmp_path)
    journal = target.with_name(target.name + "-journal")
    with pytest.raises(HotJournalError) as error:
        open_database(target, read_only=True)
    assert error.value.code == "HOT_JOURNAL"
    assert journal.is_file()  # a read-only open must not recover (or delete) the journal


def test_read_write_open_recovers_the_hot_journal(tmp_path: Path) -> None:
    target = _make_hot_journal_copy(tmp_path)
    journal = target.with_name(target.name + "-journal")
    assert journal.stat().st_size > 0
    with closing(open_database(target)) as conn:
        total = conn.execute("SELECT count(*) FROM t").fetchone()[0]
        query = "SELECT count(*) FROM t WHERE payload = ?"
        original = conn.execute(query, (PAYLOAD,)).fetchone()[0]
        assert total == ROWS
        assert original == ROWS  # the unfinished update was rolled back
    assert not journal.exists()
    with closing(open_database(target, read_only=True)) as conn:  # now it opens read-only
        assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == ROWS


# --------------------------------------------------------------------------- writability


def test_database_is_writable_for_a_normal_file(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    assert database_is_writable(path) is True


def test_database_is_not_writable_when_missing(tmp_path: Path) -> None:
    assert database_is_writable(tmp_path / "missing.sqlite3") is False
    assert not (tmp_path / "missing.sqlite3").exists()


def test_database_file_with_read_only_attribute_is_not_writable(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    path.chmod(stat.S_IREAD)
    try:
        assert database_is_writable(path) is False
        assert database_is_writable(tmp_path / "other.sqlite3") is False
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
    assert database_is_writable(path) is True


# --------------------------------------------------------------------------- transactions


def test_transaction_commits_on_success(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with closing(open_database(path)) as conn:
        with transaction(conn) as inner:
            assert inner is conn
            assert conn.in_transaction
            conn.execute("INSERT INTO item (id, label) VALUES (2, 'two')")
        assert not conn.in_transaction
    with closing(open_database(path)) as other:
        assert _count(other) == 2


def test_transaction_rolls_back_on_exception(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with closing(open_database(path)) as conn:
        with pytest.raises(RuntimeError, match="boom"), transaction(conn):
            conn.execute("INSERT INTO item (id, label) VALUES (2, 'two')")
            raise RuntimeError("boom")
        assert not conn.in_transaction
        assert _count(conn) == 1


def test_transaction_rolls_back_on_sql_error(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with closing(open_database(path)) as conn:
        with pytest.raises(sqlite3.IntegrityError), transaction(conn):
            conn.execute("INSERT INTO item (id, label) VALUES (2, 'two')")
            conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 99)")
        assert _count(conn) == 1


def test_deferred_transaction_commits(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with closing(open_database(path)) as conn:
        with transaction(conn, immediate=False):
            conn.execute("INSERT INTO item (id, label) VALUES (2, 'two')")
        assert _count(conn) == 2


def test_immediate_transaction_takes_the_write_lock(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with (
        closing(open_database(path)) as first,
        closing(open_database(path, busy_timeout_ms=0)) as second,
    ):
        with transaction(first), pytest.raises(sqlite3.OperationalError, match="locked"):
            second.execute("BEGIN IMMEDIATE")
        second.execute("BEGIN IMMEDIATE")
        second.execute("ROLLBACK")


def test_nested_transaction_joins_the_outer_one(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with closing(open_database(path)) as conn:
        with transaction(conn):
            conn.execute("INSERT INTO item (id, label) VALUES (2, 'two')")
            with transaction(conn) as inner:
                assert inner is conn
                conn.execute("INSERT INTO item (id, label) VALUES (3, 'three')")
            assert conn.in_transaction  # the inner block did not commit
            with closing(open_database(path)) as other:
                assert _count(other) == 1  # nothing visible before the outer commit
        assert not conn.in_transaction
        assert _count(conn) == 3


def test_nested_exception_rolls_back_everything(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with closing(open_database(path)) as conn:
        with pytest.raises(RuntimeError, match="inner"), transaction(conn):
            conn.execute("INSERT INTO item (id, label) VALUES (2, 'two')")
            with transaction(conn):
                conn.execute("INSERT INTO item (id, label) VALUES (3, 'three')")
                raise RuntimeError("inner")
        assert not conn.in_transaction
        assert _count(conn) == 1


def test_nested_success_with_outer_failure_rolls_back_everything(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with closing(open_database(path)) as conn:
        with pytest.raises(RuntimeError, match="outer"), transaction(conn):
            with transaction(conn):
                conn.execute("INSERT INTO item (id, label) VALUES (2, 'two')")
            raise RuntimeError("outer")
        assert not conn.in_transaction
        assert _count(conn) == 1


def test_transaction_on_a_read_only_connection(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite3"
    _create(path)
    with closing(open_database(path, read_only=True)) as conn:
        with pytest.raises(ReadOnlyDatabaseError), transaction(conn):
            pytest.fail("the body must not run")
        assert not conn.in_transaction


# --------------------------------------------------------------------------- SQLite version


def test_older_sqlite_raises_a_clear_error() -> None:
    with pytest.raises(SqliteTooOldError) as error:
        check_sqlite_version((3, 36, 0))
    assert error.value.code == "SQLITE_TOO_OLD"
    assert "3.37.0" in str(error.value)
    assert "3.36.0" in str(error.value)
    assert isinstance(error.value, DatabaseError)


@pytest.mark.parametrize("version", [(3, 37, 0), (3, 45, 1), (4, 0, 0)])
def test_new_enough_sqlite_passes(version: tuple[int, int, int]) -> None:
    check_sqlite_version(version)


def test_runtime_sqlite_version_passes() -> None:
    assert MIN_SQLITE_VERSION == (3, 37, 0)
    check_sqlite_version()


def test_open_database_checks_the_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 36, 0))
    path = tmp_path / "db.sqlite3"
    with pytest.raises(SqliteTooOldError):
        open_database(path)
    assert not path.exists()


def test_error_codes_are_stable() -> None:
    assert DatabaseError.code == "DATABASE_ERROR"
    assert ReadOnlyDatabaseError.code == "READ_ONLY"
    assert HotJournalError.code == "HOT_JOURNAL"
    assert SqliteTooOldError.code == "SQLITE_TOO_OLD"
    assert DatabaseNotFoundError.code == "DATABASE_NOT_FOUND"
