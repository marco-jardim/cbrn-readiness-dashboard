# SPDX-License-Identifier: GPL-3.0-or-later
"""Migration runner and core schema (T1.3): every Accept bullet of the task."""

from __future__ import annotations

import ast
import inspect
import itertools
import sqlite3
from contextlib import closing
from datetime import timedelta
from importlib import resources
from pathlib import Path

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.storage import migrate as migrate_module
from cbrn_dashboard.storage.db import DatabaseError, open_database
from cbrn_dashboard.storage.migrate import (
    DatabaseIdentity,
    DatabaseTooNewError,
    Migration,
    MigrationError,
    MigrationFailedError,
    MigrationInTransactionError,
    MigrationSequenceError,
    MigrationSyntaxError,
    backup_before_migration,
    load_migrations,
    migrate,
    open_and_migrate,
    split_statements,
)

_package_numbers = itertools.count(1)

CREATE_A = "CREATE TABLE a (x INTEGER) STRICT;\n"
CREATE_B = "CREATE TABLE b (x INTEGER) STRICT;\n"
CREATE_C = "CREATE TABLE c (x INTEGER) STRICT;\n"


# --------------------------------------------------------------------------- helpers


def make_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> str:
    """Write a migrations package under ``tmp_path`` and make it importable (unique name)."""
    name = f"t13_migrations_{next(_package_numbers)}"
    folder = tmp_path / "packages" / name
    folder.mkdir(parents=True)
    (folder / "__init__.py").write_text("", encoding="utf-8")
    for file_name, sql in files.items():
        (folder / file_name).write_text(sql, encoding="utf-8")
    monkeypatch.syspath_prepend(str(folder.parent))
    return name


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def user_version(conn: sqlite3.Connection) -> int:
    value: int = conn.execute("PRAGMA user_version").fetchone()[0]
    return value


def schema_text(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()
    return [(row[0], row[1]) for row in rows]


def foreign_keys(conn: sqlite3.Connection) -> int:
    value: int = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    return value


# --------------------------------------------------------------------------- real package


def test_fresh_database_reaches_the_latest_version(tmp_path: Path) -> None:
    latest = max(m.number for m in load_migrations())
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        result = migrate(conn)
        assert result.from_version == 0
        assert result.to_version == latest
        assert result.applied == tuple(range(1, latest + 1))
        assert user_version(conn) == latest
        for table in ("app_meta", "setting", "change_log"):
            cursor = conn.execute("SELECT strict FROM pragma_table_list WHERE name=?", (table,))
            assert cursor.fetchone()[0] == 1, table


def test_running_again_changes_nothing(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        first = migrate(conn)
        before = schema_text(conn)
        second = migrate(conn)
        assert second.applied == ()
        assert second.from_version == second.to_version == first.to_version
        assert schema_text(conn) == before
        assert user_version(conn) == first.to_version


def test_migrations_are_loaded_through_importlib_resources() -> None:
    first = load_migrations()[0]
    assert first.number == 1
    assert first.name == "core"
    assert first.rebuild is False
    assert "CREATE TABLE change_log" in first.sql
    assert (resources.files("cbrn_dashboard.storage.migrations") / "0001_core.sql").is_file()


def test_runner_does_not_use_executescript() -> None:
    tree = ast.parse(inspect.getsource(migrate_module))
    used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "executescript" not in used


def test_core_migration_creates_only_the_core_tables(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn, migrations=load_migrations()[:1])
        assert table_names(conn) == {"app_meta", "setting", "change_log"}
        assert conn.execute("SELECT count(*) FROM app_meta").fetchone()[0] == 0


# --------------------------------------------------------------------------- change_log


def _insert_log(conn: sqlite3.Connection, action: str = "insert") -> None:
    conn.execute(
        "INSERT INTO change_log (at_utc, entity, entity_id, action) VALUES (?, ?, ?, ?)",
        ("2026-01-01T00:00:00Z", "thing", 1, action),
    )


def test_change_log_is_append_only(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn)
        _insert_log(conn)
        with pytest.raises(sqlite3.DatabaseError, match="change_log is append-only"):
            conn.execute("UPDATE change_log SET operator = 'x'")
        with pytest.raises(sqlite3.DatabaseError, match="change_log is append-only"):
            conn.execute("DELETE FROM change_log")
        row = conn.execute("SELECT operator, count(*) FROM change_log").fetchone()
        assert (row[0], row[1]) == ("", 1)


@pytest.mark.parametrize("verb", ["INSERT OR REPLACE INTO", "REPLACE INTO"])
def test_change_log_row_cannot_be_overwritten_by_replace(tmp_path: Path, verb: str) -> None:
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn)
        _insert_log(conn)
        before = tuple(conn.execute("SELECT * FROM change_log WHERE id = 1").fetchone())
        with pytest.raises(sqlite3.DatabaseError, match="change_log is append-only"):
            conn.execute(
                f"{verb} change_log (id, at_utc, entity, entity_id, action) "
                "VALUES (1, '2030-01-01T00:00:00Z', 'forged', 9, 'delete')"
            )
        assert tuple(conn.execute("SELECT * FROM change_log WHERE id = 1").fetchone()) == before
        assert conn.execute("SELECT count(*) FROM change_log").fetchone()[0] == 1


def test_change_log_still_accepts_new_rows_with_or_without_an_id(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn)
        _insert_log(conn)
        conn.execute(
            "INSERT INTO change_log (id, at_utc, entity, action)"
            " VALUES (50, '2026-01-01T00:00:00Z', 'thing', 'insert')"
        )
        conn.execute(
            "REPLACE INTO change_log (id, at_utc, entity, action)"
            " VALUES (51, '2026-01-01T00:00:00Z', 'thing', 'insert')"
        )
        _insert_log(conn)
        ids = [row[0] for row in conn.execute("SELECT id FROM change_log ORDER BY id")]
        assert ids == [1, 50, 51, 52]


def test_change_log_rejects_an_unknown_action(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn)
        for action in ("insert", "update", "delete", "import", "restore"):
            _insert_log(conn, action)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_log(conn, "truncate")
        assert conn.execute("SELECT count(*) FROM change_log").fetchone()[0] == 5


# --------------------------------------------------------------------------- newer database


def test_newer_database_is_refused_and_left_untouched(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    with closing(open_database(db)) as conn:
        conn.execute("CREATE TABLE keep (x INTEGER) STRICT")
        conn.execute("PRAGMA user_version = 999")
    before = db.read_bytes()
    with closing(open_database(db)) as conn, pytest.raises(DatabaseTooNewError) as caught:
        migrate(conn)
    assert caught.value.code == "DATABASE_TOO_NEW"
    assert isinstance(caught.value, DatabaseError)
    assert db.read_bytes() == before


def test_open_and_migrate_closes_the_connection_on_error(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    with closing(open_database(db)) as conn:
        conn.execute("PRAGMA user_version = 999")
    with pytest.raises(DatabaseTooNewError):
        open_and_migrate(db, data_dir=tmp_path, identity=DatabaseIdentity.REAL)
    db.unlink()  # fails on Windows while a connection is still open


# --------------------------------------------------------------------------- failing migrations


def test_a_broken_migration_rolls_back_and_keeps_the_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path, monkeypatch, {"0001_bad.sql": CREATE_A + "INSERT INTO nowhere VALUES (1);\n"}
    )
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationFailedError) as caught:
            migrate(conn, package=package)
        assert caught.value.number == 1
        assert caught.value.code == "MIGRATION_FAILED"
        assert isinstance(caught.value.__cause__, sqlite3.Error)
        assert "nowhere" not in str(caught.value)
        assert user_version(conn) == 0
        assert table_names(conn) == set()
        assert not conn.in_transaction


def test_a_failure_at_the_last_statement_leaves_no_earlier_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {
            "0001_good.sql": CREATE_A,
            "0002_bad.sql": CREATE_B + CREATE_C + "CREATE TABLE d (x INTEGER;\n",
        },
    )
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationFailedError) as caught:
            migrate(conn, package=package)
        assert caught.value.number == 2
        # the earlier, already committed migration stays applied
        assert user_version(conn) == 1
        assert table_names(conn) == {"a"}


def test_the_failing_migration_can_be_retried_after_a_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = make_package(
        tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, "0002_b.sql": "SELECT * FROM nowhere;\n"}
    )
    fixed = make_package(tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, "0002_b.sql": CREATE_B})
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationFailedError):
            migrate(conn, package=broken)
        result = migrate(conn, package=fixed)
        assert result.applied == (2,)
        assert table_names(conn) == {"a", "b"}


# --------------------------------------------------------------------------- contiguity


def _assert_untouched(conn: sqlite3.Connection, version: int) -> None:
    assert user_version(conn) == version
    assert table_names(conn) == set()


@pytest.mark.parametrize("preset", [0, 2, 3])
def test_a_gap_in_the_files_is_refused_and_nothing_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, preset: int
) -> None:
    package = make_package(tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, "0003_c.sql": CREATE_C})
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        conn.execute(f"PRAGMA user_version = {preset}")
        calls: list[tuple[int, int]] = []
        with pytest.raises(MigrationSequenceError) as caught:
            migrate(conn, package=package, before_migrate=lambda a, b: calls.append((a, b)))
        assert caught.value.code == "MIGRATION_SEQUENCE"
        assert calls == []
        _assert_untouched(conn, preset)


def test_a_gap_in_a_list_of_migrations_is_refused(tmp_path: Path) -> None:
    gap = [Migration(1, "a", CREATE_A, False), Migration(3, "c", CREATE_C, False)]
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationSequenceError):
            migrate(conn, migrations=gap)
        _assert_untouched(conn, 0)


def test_a_list_not_starting_at_0001_is_refused(tmp_path: Path) -> None:
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationSequenceError):
            migrate(conn, migrations=[Migration(2, "b", CREATE_B, False)])
        _assert_untouched(conn, 0)


def test_a_duplicate_number_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = make_package(tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, "0001_b.sql": CREATE_B})
    with pytest.raises(MigrationSequenceError):
        load_migrations(package)
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationSequenceError):
            migrate(conn, package=package)
        _assert_untouched(conn, 0)


def test_first_file_not_0001_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = make_package(tmp_path, monkeypatch, {"0002_b.sql": CREATE_B})
    with pytest.raises(MigrationSequenceError):
        load_migrations(package)


@pytest.mark.parametrize("bad_name", ["1_core.sql", "0002_Core.sql", "0002-core.sql", "0002_.sql"])
def test_a_badly_named_sql_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_name: str
) -> None:
    package = make_package(tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, bad_name: CREATE_B})
    with pytest.raises(MigrationSequenceError):
        load_migrations(package)


def test_other_files_in_the_package_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, "README.md": "text", "notes.txt": "x"}
    )
    assert [m.number for m in load_migrations(package)] == [1]


def test_migrations_are_applied_in_numeric_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {
            "0003_c.sql": "INSERT INTO a VALUES (3);\n",
            "0001_a.sql": CREATE_A,
            "0002_b.sql": "INSERT INTO a VALUES (2);\n",
        },
    )
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        assert migrate(conn, package=package).applied == (1, 2, 3)
        assert [row[0] for row in conn.execute("SELECT x FROM a ORDER BY rowid")] == [2, 3]


# --------------------------------------------------------------------------- statement splitting

SPLIT_SAMPLE = """\
-- header comment; with a semicolon
CREATE TABLE t (a TEXT) STRICT;
/* block comment; also with one */
INSERT INTO t VALUES ('a;b');
CREATE TRIGGER trg BEFORE DELETE ON t
BEGIN
    SELECT RAISE(ABORT, 'no; delete');
    SELECT 1;
END;
-- trailing comment only
"""


def test_split_keeps_trigger_bodies_and_string_literals_whole() -> None:
    statements = split_statements(SPLIT_SAMPLE)
    assert len(statements) == 3
    assert statements[0].endswith("CREATE TABLE t (a TEXT) STRICT;")
    assert "'a;b'" in statements[1]
    assert statements[2].startswith("CREATE TRIGGER trg")
    assert statements[2].endswith("END;")
    assert "SELECT 1;" in statements[2]


@pytest.mark.parametrize("text", ["", "\n\n", "-- only a comment\n", "/* a */\n-- b\n", ";\n;\n"])
def test_split_skips_chunks_without_statements(text: str) -> None:
    assert split_statements(text) == []


def test_split_accepts_a_last_statement_without_a_newline() -> None:
    assert split_statements("SELECT 1;") == ["SELECT 1;"]


@pytest.mark.parametrize(
    "text", ["SELECT 1", "SELECT 1;\nSELECT 2", "CREATE TRIGGER t BEGIN SELECT 1;"]
)
def test_split_rejects_an_unterminated_tail(text: str) -> None:
    with pytest.raises(MigrationError) as caught:
        split_statements(text)
    assert caught.value.code == "MIGRATION_SYNTAX"


def test_a_migration_with_a_trigger_and_literals_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(tmp_path, monkeypatch, {"0001_t.sql": SPLIT_SAMPLE})
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn, package=package)
        assert conn.execute("SELECT a FROM t").fetchone()[0] == "a;b"
        with pytest.raises(sqlite3.DatabaseError, match="no; delete"):
            conn.execute("DELETE FROM t")


def test_an_unterminated_migration_runs_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, "0002_b.sql": CREATE_B + "SELECT 1"}
    )
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationError):
            migrate(conn, package=package)
        _assert_untouched(conn, 0)


# --------------------------------------------------------------------------- table rebuild

PARENT_CHILD = (
    "CREATE TABLE parent (id INTEGER PRIMARY KEY) STRICT;\n"
    "CREATE TABLE child (id INTEGER PRIMARY KEY,"
    " parent_id INTEGER NOT NULL REFERENCES parent(id)) STRICT;\n"
)
# Only possible while foreign keys are off: the dangling child is repaired before COMMIT.
DANGLING_CHILD = "INSERT INTO child (parent_id) VALUES (99);\n"
DANGLING_THEN_FIXED = DANGLING_CHILD + "INSERT INTO parent (id) VALUES (99);\n"
FLAG = "-- migrate: table-rebuild\n"


def test_the_rebuild_flag_is_read_from_the_header_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {
            "0001_plain.sql": CREATE_A,
            "0002_flagged.sql": "-- Rebuild the table.\n\n" + FLAG + CREATE_B,
            # a flag line after the first statement is not part of the header
            "0003_late.sql": CREATE_C + FLAG,
        },
    )
    assert [m.rebuild for m in load_migrations(package)] == [False, True, False]


def test_a_rebuild_migration_runs_with_foreign_keys_off_and_restores_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {"0001_fk.sql": PARENT_CHILD, "0002_rebuild.sql": FLAG + DANGLING_THEN_FIXED},
    )
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        assert foreign_keys(conn) == 1
        migrate(conn, package=package)
        assert user_version(conn) == 2
        assert foreign_keys(conn) == 1
        assert conn.execute("SELECT count(*) FROM child").fetchone()[0] == 1


def test_the_same_statements_fail_without_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {"0001_fk.sql": PARENT_CHILD, "0002_plain.sql": DANGLING_THEN_FIXED},
    )
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationFailedError) as caught:
            migrate(conn, package=package)
        assert caught.value.number == 2
        assert user_version(conn) == 1
        assert foreign_keys(conn) == 1


def test_a_rebuild_leaving_a_dangling_key_is_rolled_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {
            "0001_fk.sql": PARENT_CHILD,
            "0002_rebuild.sql": FLAG + DANGLING_CHILD,
        },
    )
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationFailedError) as caught:
            migrate(conn, package=package)
        assert caught.value.number == 2
        assert user_version(conn) == 1
        assert conn.execute("SELECT count(*) FROM child").fetchone()[0] == 0
        assert foreign_keys(conn) == 1
        assert not conn.in_transaction


def test_a_failing_rebuild_statement_turns_foreign_keys_back_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {"0001_fk.sql": PARENT_CHILD, "0002_rebuild.sql": FLAG + "DROP TABLE nowhere;\n"},
    )
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationFailedError):
            migrate(conn, package=package)
        assert foreign_keys(conn) == 1
        assert user_version(conn) == 1


# --------------------------------------------------------------------------- hook


def test_before_migrate_is_called_once_and_only_when_there_is_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {"0001_a.sql": CREATE_A, "0002_b.sql": CREATE_B, "0003_c.sql": CREATE_C},
    )
    calls: list[tuple[int, int]] = []
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn, package=package, before_migrate=lambda a, b: calls.append((a, b)))
        assert calls == [(0, 3)]
        migrate(conn, package=package, before_migrate=lambda a, b: calls.append((a, b)))
        assert calls == [(0, 3)]


# --------------------------------------------------------------------------- backup


BACKUP_CLOCK = FixedClock.at("2026-03-05T02:30:00Z")
#: Name of the pre-migration backup made at ``BACKUP_CLOCK`` from schema version 1 (T7.1 naming).
FIRST_BACKUP = "pre-migration-20260305T023000Z-v0001.sqlite3"


def _packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str, str]:
    one = {"0001_a.sql": CREATE_A}
    two = {**one, "0002_b.sql": CREATE_B}
    three = {**two, "0003_c.sql": CREATE_C}
    return (
        make_package(tmp_path, monkeypatch, one),
        make_package(tmp_path, monkeypatch, two),
        make_package(tmp_path, monkeypatch, three),
    )


def _migrate_and_close(
    db: Path,
    data: Path,
    package: str,
    identity: DatabaseIdentity = DatabaseIdentity.REAL,
    *,
    backup: bool = True,
    clock: FixedClock = BACKUP_CLOCK,
) -> None:
    open_and_migrate(
        db, data_dir=data, identity=identity, backup=backup, package=package, clock=clock
    ).close()


def _files(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_a_non_empty_database_is_backed_up_before_migrating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one, two, three = _packages(tmp_path, monkeypatch)
    data = tmp_path / "data"
    data.mkdir()
    db = data / "db.sqlite3"

    # a fresh (empty) database is not backed up
    _migrate_and_close(db, data, one)
    assert _files(data / "backups") == []

    with closing(open_database(db)) as conn:
        conn.execute("INSERT INTO a VALUES (42)")

    _migrate_and_close(db, data, two)
    assert _files(data / "backups") == [FIRST_BACKUP]
    with closing(open_database(data / "backups" / FIRST_BACKUP)) as old:
        assert user_version(old) == 1
        assert table_names(old) == {"a"}
        assert old.execute("SELECT x FROM a").fetchone()[0] == 42

    # nothing to apply: no new backup; the next migration makes a new one (name: time, version)
    _migrate_and_close(db, data, two)
    assert len(_files(data / "backups")) == 1
    _migrate_and_close(db, data, three, clock=BACKUP_CLOCK.advanced(timedelta(hours=1)))
    with closing(open_database(db)) as conn:
        assert user_version(conn) == 3
    assert _files(data / "backups") == [
        FIRST_BACKUP,
        "pre-migration-20260305T033000Z-v0002.sqlite3",
    ]
    assert not (data / "demo").exists()


def test_a_demo_database_is_backed_up_under_demo_backups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one, two, _ = _packages(tmp_path, monkeypatch)
    data = tmp_path / "data"
    data.mkdir()
    db = data / "demo.sqlite3"
    _migrate_and_close(db, data, one, DatabaseIdentity.DEMO)
    _migrate_and_close(db, data, two, DatabaseIdentity.DEMO)
    assert _files(data / "demo" / "backups") == [FIRST_BACKUP]
    assert not (data / "backups").exists()


def test_backup_can_be_turned_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    one, two, _ = _packages(tmp_path, monkeypatch)
    data = tmp_path / "data"
    data.mkdir()
    db = data / "db.sqlite3"
    for package in (one, two):
        _migrate_and_close(db, data, package, backup=False)
    assert [p.name for p in data.rglob("*")] == ["db.sqlite3"]


def test_backup_helper_decides_by_content_and_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one, _, _ = _packages(tmp_path, monkeypatch)
    data = tmp_path / "data"
    data.mkdir()

    def backup(conn: sqlite3.Connection, *, enabled: bool = True) -> Path | None:
        return backup_before_migration(
            conn,
            data_dir=data,
            identity=DatabaseIdentity.REAL,
            from_version=0,
            enabled=enabled,
            clock=BACKUP_CLOCK,
        )

    with closing(open_database(data / "db.sqlite3")) as conn:
        assert backup(conn) is None  # empty database
        migrate(conn, package=one)
        assert backup(conn, enabled=False) is None
        assert _files(data / "backups") == []
        made = backup(conn)
        assert made == data / "backups" / "pre-migration-20260305T023000Z-v0000.sqlite3"
        assert made is not None
        assert made.is_file()


# --------------------------------------------------------------------------- README


def test_readme_reserves_the_numbers_until_v010_and_states_the_max_plus_one_rule() -> None:
    text = (resources.files("cbrn_dashboard.storage.migrations") / "README.md").read_text(
        encoding="utf-8"
    )
    for number, module in (
        ("0002", "personnel"),
        ("0003", "infrastructure"),
        ("0004", "exercises"),
        ("0005", "budget"),
        ("0006", "indicator targets"),
        ("0007", "snapshots"),
    ):
        assert any(number in line and module in line for line in text.splitlines()), number
    assert "until v0.1.0" in text
    assert "max+1" in text
    assert "-- migrate: table-rebuild" in text
    assert "ascending order" in text


# --------------------------------------------------------------------------- QA round 1: runner
# P1A-10 (rebuild flag / DROP TABLE), P1A-12 (splitter / transaction control), P1A-14 (file
# extension / negative user_version), P1A-15 (open transaction).


def _pair(first: str, second: str, *, rebuild: bool = False) -> list[Migration]:
    return [Migration(1, "first", first, False), Migration(2, "second", second, rebuild)]


def _assert_refused_before_anything_ran(migrations: list[Migration], db: Path) -> None:
    """``migrate`` raises ``MigrationSyntaxError``; no hook call, no table, no version bump."""
    calls: list[tuple[int, int]] = []
    with closing(open_database(db)) as conn:
        with pytest.raises(MigrationSyntaxError) as caught:
            migrate(conn, migrations=migrations, before_migrate=lambda a, b: calls.append((a, b)))
        assert caught.value.code == "MIGRATION_SYNTAX"
        assert calls == []
        _assert_untouched(conn, 0)
        assert not conn.in_transaction


# --- P1A-10: misspelled rebuild flag

FLAG_VARIANTS = [
    "--migrate: table-rebuild",
    "-- migrate: table-rebuild.",
    "-- Migrate: table-rebuild",
    "--  migrate : table-rebuild",
    "-- migrate: table_rebuild",
    "-- MIGRATE: TABLE-REBUILD",
    "-- migrate:table-rebuild",
    "-- migrate: something-else",
]


@pytest.mark.parametrize("variant", FLAG_VARIANTS)
def test_a_misspelled_rebuild_flag_is_refused_at_load_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    package = make_package(
        tmp_path, monkeypatch, {"0001_a.sql": f"-- Header.\n{variant}\n\n{CREATE_A}"}
    )
    with pytest.raises(MigrationSyntaxError) as caught:
        load_migrations(package)
    assert caught.value.code == "MIGRATION_SYNTAX"
    assert "CREATE" not in str(caught.value)  # no SQL text in the message


@pytest.mark.parametrize("variant", FLAG_VARIANTS)
def test_a_misspelled_flag_with_a_drop_table_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variant: str
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {"0001_fk.sql": PARENT_CHILD, "0002_drop.sql": f"{variant}\nDROP TABLE parent;\n"},
    )
    one = make_package(tmp_path, monkeypatch, {"0001_fk.sql": PARENT_CHILD})
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn, package=one)
        conn.execute("INSERT INTO parent (id) VALUES (1)")
        conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 1)")
        calls: list[tuple[int, int]] = []
        with pytest.raises(MigrationSyntaxError):
            migrate(conn, package=package, before_migrate=lambda a, b: calls.append((a, b)))
        assert calls == []
        assert user_version(conn) == 1
        assert conn.execute("SELECT count(*) FROM parent").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM child").fetchone()[0] == 1


def test_a_misspelled_flag_in_a_migration_list_is_refused(tmp_path: Path) -> None:
    migrations = _pair(CREATE_A, f"--migrate: table-rebuild\n{CREATE_B}")
    _assert_refused_before_anything_ran(migrations, tmp_path / "db.sqlite3")


def test_a_late_or_correct_flag_line_is_still_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path,
        monkeypatch,
        {
            "0001_a.sql": f"-- Header, migrate: nothing special.\n{FLAG}{CREATE_A}",
            # outside the leading comment block a directive-like comment is just a comment
            "0002_b.sql": CREATE_B + "-- migrate: table-rebuild.\n",
        },
    )
    assert [m.rebuild for m in load_migrations(package)] == [True, False]


# --- P1A-10: DROP TABLE without the flag


@pytest.mark.parametrize(
    "drop",
    [
        "DROP TABLE a;",
        "drop table a;",
        "Drop   Table IF EXISTS a;",
        "DROP\n  TABLE a;",
        "/* gone */ DROP -- why\n TABLE a;",
        "-- header comment\nDROP TABLE a;",
    ],
)
def test_an_unflagged_drop_table_is_refused_and_nothing_runs(tmp_path: Path, drop: str) -> None:
    migrations = _pair(CREATE_A, CREATE_B + drop + "\n" + CREATE_C)
    _assert_refused_before_anything_ran(migrations, tmp_path / "db.sqlite3")


def test_an_unflagged_drop_table_takes_no_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one = make_package(tmp_path, monkeypatch, {"0001_a.sql": CREATE_A})
    two = make_package(
        tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, "0002_drop.sql": "DROP TABLE a;\n"}
    )
    data = tmp_path / "data"
    data.mkdir()
    db = data / "db.sqlite3"
    _migrate_and_close(db, data, one)
    with closing(open_database(db)) as conn:
        conn.execute("INSERT INTO a VALUES (7)")
    with pytest.raises(MigrationSyntaxError):
        _migrate_and_close(db, data, two)
    assert _files(data / "backups") == []
    with closing(open_database(db)) as conn:
        assert user_version(conn) == 1
        assert conn.execute("SELECT x FROM a").fetchone()[0] == 7


def test_a_flagged_rebuild_with_drop_table_still_works(tmp_path: Path) -> None:
    rebuild = (
        FLAG
        + "CREATE TABLE parent_new (id INTEGER PRIMARY KEY, note TEXT) STRICT;\n"
        + "INSERT INTO parent_new (id) SELECT id FROM parent;\n"
        + "DROP TABLE parent;\n"
        + "ALTER TABLE parent_new RENAME TO parent;\n"
    )
    first = Migration(1, "fk", PARENT_CHILD, False)
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn, migrations=[first])
        conn.execute("INSERT INTO parent (id) VALUES (1)")
        conn.execute("INSERT INTO child (id, parent_id) VALUES (1, 1)")
        result = migrate(conn, migrations=[first, Migration(2, "rebuild", rebuild, True)])
        assert result.applied == (2,)
        assert user_version(conn) == 2
        assert foreign_keys(conn) == 1
        assert conn.execute("SELECT count(*) FROM parent").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM child").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_drop_index_and_drop_trigger_are_allowed_without_the_flag(tmp_path: Path) -> None:
    first = (
        CREATE_A
        + "CREATE INDEX ix ON a (x);\n"
        + "CREATE TRIGGER trg AFTER INSERT ON a BEGIN SELECT 1; END;\n"
    )
    second = "DROP INDEX ix;\nDROP TRIGGER trg;\n"
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        assert migrate(conn, migrations=_pair(first, second)).applied == (1, 2)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert {"ix", "trg"}.isdisjoint(names)


# --- P1A-12: several statements per line, transaction control

ONE_LINE = "CREATE TABLE a (x INTEGER) STRICT; CREATE TABLE b (x INTEGER) STRICT;"


def test_split_cuts_several_statements_on_one_line() -> None:
    assert split_statements(ONE_LINE) == [
        "CREATE TABLE a (x INTEGER) STRICT;",
        "CREATE TABLE b (x INTEGER) STRICT;",
    ]
    assert split_statements(ONE_LINE + "\r\n" + ONE_LINE + "\r\n") == [
        "CREATE TABLE a (x INTEGER) STRICT;",
        "CREATE TABLE b (x INTEGER) STRICT;",
        "CREATE TABLE a (x INTEGER) STRICT;",
        "CREATE TABLE b (x INTEGER) STRICT;",
    ]


def test_split_handles_comments_and_literals_between_statements_on_one_line() -> None:
    statements = split_statements(
        "INSERT INTO t VALUES ('a;b'); /* x; y */ INSERT INTO t VALUES (2); -- done; ok\nSELECT 3;"
    )
    assert len(statements) == 3
    assert statements[0] == "INSERT INTO t VALUES ('a;b');"
    assert statements[1].endswith("INSERT INTO t VALUES (2);")
    assert statements[2].endswith("SELECT 3;")


def test_split_keeps_a_trigger_with_end_in_a_string_literal_whole() -> None:
    trigger = "CREATE TRIGGER trg AFTER INSERT ON a BEGIN SELECT 'END; COMMIT;'; SELECT 2; END;"
    statements = split_statements(trigger + " " + CREATE_B)
    assert statements == [trigger, CREATE_B.strip()]


def test_two_statements_on_one_line_are_both_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = make_package(
        tmp_path, monkeypatch, {"0001_ab.sql": "\ufeff" + ONE_LINE + "\n" + CREATE_C}
    )
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        migrate(conn, package=package)
        assert table_names(conn) == {"a", "b", "c"}
        assert user_version(conn) == 1


def test_the_real_migrations_split_and_pass_the_checks() -> None:
    for migration in load_migrations():
        assert split_statements(migration.sql), migration.number


FORBIDDEN = [
    "BEGIN;",
    "BEGIN IMMEDIATE;",
    "begin transaction;",
    "COMMIT;",
    "END;",
    "end transaction;",
    "ROLLBACK;",
    "SAVEPOINT s;",
    "RELEASE s;",
    "RELEASE SAVEPOINT s;",
    "VACUUM;",
    "ATTACH DATABASE 'other.db' AS other;",
    "DETACH DATABASE other;",
    "PRAGMA foreign_keys = OFF;",
    "pragma user_version = 5;",
    "/* c */ COMMIT;",
    "-- c\nCOMMIT;",
]


@pytest.mark.parametrize("statement", FORBIDDEN)
def test_split_refuses_transaction_control_vacuum_attach_and_pragma(statement: str) -> None:
    with pytest.raises(MigrationSyntaxError) as caught:
        split_statements(CREATE_A + statement + "\n")
    assert caught.value.code == "MIGRATION_SYNTAX"


@pytest.mark.parametrize("statement", FORBIDDEN)
def test_a_forbidden_statement_is_refused_before_anything_runs(
    tmp_path: Path, statement: str
) -> None:
    # CREATE_A and the statement share a line: the cut must not hide the statement
    second = CREATE_B.rstrip("\n") + " " + statement + "\n" + CREATE_C
    _assert_refused_before_anything_ran(_pair(CREATE_A, second), tmp_path / "db.sqlite3")


def test_a_forbidden_statement_takes_no_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    one = make_package(tmp_path, monkeypatch, {"0001_a.sql": CREATE_A})
    two = make_package(
        tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, "0002_b.sql": CREATE_B + "COMMIT;\n"}
    )
    data = tmp_path / "data"
    data.mkdir()
    db = data / "db.sqlite3"
    _migrate_and_close(db, data, one)
    with closing(open_database(db)) as conn:
        conn.execute("INSERT INTO a VALUES (7)")
    with pytest.raises(MigrationSyntaxError):
        _migrate_and_close(db, data, two)
    assert _files(data / "backups") == []
    with closing(open_database(db)) as conn:
        assert user_version(conn) == 1
        assert table_names(conn) == {"a"}


# --- P1A-14: extension case, negative user_version


@pytest.mark.parametrize("bad_name", ["0002_b.SQL", "0002_b.Sql", "0002_b.sQl"])
def test_a_sql_file_with_an_upper_case_extension_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_name: str
) -> None:
    package = make_package(tmp_path, monkeypatch, {"0001_a.sql": CREATE_A, bad_name: CREATE_B})
    with pytest.raises(MigrationSequenceError) as caught:
        load_migrations(package)
    assert caught.value.code == "MIGRATION_SEQUENCE"
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        with pytest.raises(MigrationSequenceError):
            migrate(conn, package=package)
        _assert_untouched(conn, 0)


@pytest.mark.parametrize("version", [-1, -3, -2147483648])
def test_a_negative_user_version_is_refused_and_nothing_runs(tmp_path: Path, version: int) -> None:
    calls: list[tuple[int, int]] = []
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        conn.execute(f"PRAGMA user_version = {version}")
        with pytest.raises(MigrationSequenceError) as caught:
            migrate(
                conn,
                migrations=_pair(CREATE_A, CREATE_B),
                before_migrate=lambda a, b: calls.append((a, b)),
            )
        assert caught.value.code == "MIGRATION_SEQUENCE"
        assert calls == []
        _assert_untouched(conn, version)


# --- P1A-15: an open transaction of the caller


@pytest.mark.parametrize("begin", ["BEGIN", "BEGIN IMMEDIATE"])
def test_migrate_refuses_to_run_inside_an_open_transaction_and_leaves_it_alone(
    tmp_path: Path, begin: str
) -> None:
    calls: list[tuple[int, int]] = []
    with closing(open_database(tmp_path / "db.sqlite3")) as conn:
        conn.execute("CREATE TABLE keep (x INTEGER) STRICT")
        conn.execute(begin)
        conn.execute("INSERT INTO keep VALUES (42)")
        with pytest.raises(MigrationInTransactionError) as caught:
            migrate(
                conn,
                migrations=_pair(CREATE_A, CREATE_B),
                before_migrate=lambda a, b: calls.append((a, b)),
            )
        assert caught.value.code == "MIGRATION_IN_TRANSACTION"
        assert isinstance(caught.value, MigrationError)
        assert calls == []
        assert conn.in_transaction  # the caller's transaction was not rolled back
        conn.execute("COMMIT")
        assert [row[0] for row in conn.execute("SELECT x FROM keep")] == [42]
        assert user_version(conn) == 0
        assert table_names(conn) == {"keep"}
