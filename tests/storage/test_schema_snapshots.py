# SPDX-License-Identifier: GPL-3.0-or-later
"""Schema tests of migration 0007 (readiness snapshots; PLAN.md task T8.1, D13, K13, R31).

All data is fictitious; plain SQL on the migrated database.
"""

from __future__ import annotations

import sqlite3

import pytest

from cbrn_dashboard.storage.db import DatabaseConnection

TABLES = ("readiness_snapshot", "readiness_snapshot_value", "snapshot_withdrawal")


def _snapshot(db: DatabaseConnection, origin: str = "manual") -> int:
    cursor = db.execute(
        "INSERT INTO readiness_snapshot"
        " (taken_at_utc, as_of, origin, app_version, config_hash, config_json)"
        " VALUES ('2026-03-05T12:00:00Z', '2026-03-05', ?, '0.1.0', 'abc', '{}')",
        (origin,),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _value(db: DatabaseConnection, snapshot_id: int, code: str = "A_CODE", dim: str = "") -> None:
    db.execute(
        "INSERT INTO readiness_snapshot_value"
        " (snapshot_id, indicator_code, dimension, value, status, warning_value, critical_value)"
        " VALUES (?, ?, ?, 0.5, 'OK', 0.4, 0.2)",
        (snapshot_id, code, dim),
    )


def _withdrawal(db: DatabaseConnection, snapshot_id: int, reason: str = "entered in error") -> int:
    cursor = db.execute(
        "INSERT INTO snapshot_withdrawal (snapshot_id, withdrawn_at_utc, reason)"
        " VALUES (?, '2026-03-06T12:00:00Z', ?)",
        (snapshot_id, reason),
    )
    assert cursor.lastrowid is not None
    return int(cursor.lastrowid)


def _count(db: DatabaseConnection, table: str) -> int:
    assert table in TABLES
    return int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


@pytest.fixture
def filled(migrated_db: DatabaseConnection) -> DatabaseConnection:
    """One snapshot with one value and one withdrawal."""
    snapshot_id = _snapshot(migrated_db)
    _value(migrated_db, snapshot_id)
    _withdrawal(migrated_db, snapshot_id)
    return migrated_db


@pytest.mark.parametrize("table", TABLES)
def test_tables_exist_and_are_strict(migrated_db: DatabaseConnection, table: str) -> None:
    row = migrated_db.execute("SELECT strict FROM pragma_table_list WHERE name = ?", (table,))
    assert row.fetchone()[0] == 1


def test_columns_are_those_of_the_plan(migrated_db: DatabaseConnection) -> None:
    def columns(table: str) -> list[str]:
        return [row[1] for row in migrated_db.execute(f"PRAGMA table_info({table})")]

    assert columns("readiness_snapshot") == [
        "id",
        "taken_at_utc",
        "as_of",
        "origin",
        "app_version",
        "config_hash",
        "config_json",
        "note",
    ]
    assert columns("readiness_snapshot_value") == [
        "snapshot_id",
        "indicator_code",
        "dimension",
        "value",
        "status",
        "warning_value",
        "critical_value",
    ]
    assert columns("snapshot_withdrawal") == [
        "id",
        "snapshot_id",
        "withdrawn_at_utc",
        "reason",
        "operator",
    ]


def test_no_snapshot_is_seeded(migrated_db: DatabaseConnection) -> None:
    assert [_count(migrated_db, table) for table in TABLES] == [0, 0, 0]


def test_as_of_is_indexed(migrated_db: DatabaseConnection) -> None:
    indexed = [
        row[0]
        for row in migrated_db.execute(
            "SELECT m.name FROM pragma_index_list('readiness_snapshot') AS i,"
            " pragma_index_info(i.name) AS m"
        )
    ]
    assert "as_of" in indexed


@pytest.mark.parametrize("origin", ["manual", "monthly", "report", "retroactive"])
def test_known_origins_are_accepted(migrated_db: DatabaseConnection, origin: str) -> None:
    _snapshot(migrated_db, origin)
    assert _count(migrated_db, "readiness_snapshot") == 1


@pytest.mark.parametrize("origin", ["auto", "", "MANUAL", "import"])
def test_other_origins_are_rejected(migrated_db: DatabaseConnection, origin: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _snapshot(migrated_db, origin)


def test_required_columns(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO readiness_snapshot (taken_at_utc, as_of, origin, app_version,"
            " config_hash) VALUES ('2026-03-05T12:00:00Z', '2026-03-05', 'manual', '0.1.0', 'abc')"
        )  # no config_json


def test_value_key_is_snapshot_code_and_dimension(migrated_db: DatabaseConnection) -> None:
    keys = {
        row[1]: row[5]
        for row in migrated_db.execute("PRAGMA table_info(readiness_snapshot_value)")
        if row[5] > 0
    }
    assert keys == {"snapshot_id": 1, "indicator_code": 2, "dimension": 3}


def test_duplicate_value_key_is_rejected(migrated_db: DatabaseConnection) -> None:
    snapshot_id = _snapshot(migrated_db)
    _value(migrated_db, snapshot_id, "A_CODE", "level=A")
    with pytest.raises(sqlite3.IntegrityError):
        _value(migrated_db, snapshot_id, "A_CODE", "level=A")


def test_same_code_with_another_dimension_or_snapshot_is_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    first = _snapshot(migrated_db)
    second = _snapshot(migrated_db)
    for snapshot_id in (first, second):
        for dim in ("level=A", "level=B", ""):
            _value(migrated_db, snapshot_id, "A_CODE", dim)
    assert _count(migrated_db, "readiness_snapshot_value") == 6


def test_value_dimension_defaults_to_empty_text_and_value_may_be_null(
    migrated_db: DatabaseConnection,
) -> None:
    snapshot_id = _snapshot(migrated_db)
    migrated_db.execute(
        "INSERT INTO readiness_snapshot_value (snapshot_id, indicator_code, status)"
        " VALUES (?, 'A_CODE', 'NO_DATA')",
        (snapshot_id,),
    )
    row = migrated_db.execute(
        "SELECT dimension, value, warning_value, critical_value FROM readiness_snapshot_value"
    ).fetchone()
    assert tuple(row) == ("", None, None, None)


def test_value_for_an_unknown_snapshot_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _value(migrated_db, 999)


def test_withdrawal_for_an_unknown_snapshot_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _withdrawal(migrated_db, 999)


def test_snapshot_id_is_unique_on_withdrawals(migrated_db: DatabaseConnection) -> None:
    unique = [
        row
        for row in migrated_db.execute("PRAGMA index_list(snapshot_withdrawal)")
        if row[2] == 1 and row[3] == "u"
    ]
    assert len(unique) == 1
    snapshot_id = _snapshot(migrated_db)
    _withdrawal(migrated_db, snapshot_id)
    with pytest.raises(sqlite3.IntegrityError):
        _withdrawal(migrated_db, snapshot_id, "again")
    assert _count(migrated_db, "snapshot_withdrawal") == 1


def test_empty_reason_is_rejected(migrated_db: DatabaseConnection) -> None:
    snapshot_id = _snapshot(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        _withdrawal(migrated_db, snapshot_id, "")
    assert _count(migrated_db, "snapshot_withdrawal") == 0


def test_withdrawal_operator_defaults_to_empty_text(migrated_db: DatabaseConnection) -> None:
    _withdrawal(migrated_db, _snapshot(migrated_db))
    assert migrated_db.execute("SELECT operator FROM snapshot_withdrawal").fetchone()[0] == ""


# --------------------------------------------------------------------------- append-only

UPDATES = {
    "readiness_snapshot": "UPDATE readiness_snapshot SET note = 'changed'",
    "readiness_snapshot_value": "UPDATE readiness_snapshot_value SET status = 'CRITICAL'",
    "snapshot_withdrawal": "UPDATE snapshot_withdrawal SET reason = 'changed'",
}


@pytest.mark.parametrize("table", TABLES)
def test_update_raises_and_leaves_the_row(filled: DatabaseConnection, table: str) -> None:
    before = [tuple(row) for row in filled.execute(f"SELECT * FROM {table}")]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        filled.execute(UPDATES[table])
    assert [tuple(row) for row in filled.execute(f"SELECT * FROM {table}")] == before


@pytest.mark.parametrize("table", TABLES)
def test_delete_raises_and_leaves_the_row(filled: DatabaseConnection, table: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        filled.execute(f"DELETE FROM {table}")
    assert _count(filled, table) == 1


def test_update_of_a_key_column_raises_too(filled: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        filled.execute("UPDATE readiness_snapshot SET id = 77")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        filled.execute("UPDATE readiness_snapshot_value SET dimension = 'x'")


REPLACES = {
    "readiness_snapshot": (
        "INSERT OR REPLACE INTO readiness_snapshot"
        " (id, taken_at_utc, as_of, origin, app_version, config_hash, config_json)"
        " VALUES (1, '2030-01-01T00:00:00Z', '2030-01-01', 'manual', '9', 'x', '{}')"
    ),
    "readiness_snapshot_value": (
        "INSERT OR REPLACE INTO readiness_snapshot_value"
        " (snapshot_id, indicator_code, dimension, value, status)"
        " VALUES (1, 'A_CODE', '', 99, 'CRITICAL')"
    ),
    "snapshot_withdrawal": (
        "INSERT OR REPLACE INTO snapshot_withdrawal (id, snapshot_id, withdrawn_at_utc, reason)"
        " VALUES (1, 1, '2030-01-01T00:00:00Z', 'replaced')"
    ),
}

# The withdrawal can also be replaced through its UNIQUE snapshot_id, with a new id.
REPLACE_BY_SNAPSHOT_ID = (
    "INSERT OR REPLACE INTO snapshot_withdrawal (id, snapshot_id, withdrawn_at_utc, reason)"
    " VALUES (50, 1, '2030-01-01T00:00:00Z', 'replaced')"
)


@pytest.mark.parametrize("table", TABLES)
def test_insert_or_replace_with_an_existing_key_raises(
    filled: DatabaseConnection, table: str
) -> None:
    before = [tuple(row) for row in filled.execute(f"SELECT * FROM {table}")]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        filled.execute(REPLACES[table])
    assert [tuple(row) for row in filled.execute(f"SELECT * FROM {table}")] == before


def test_insert_or_replace_through_the_unique_snapshot_id_raises(
    filled: DatabaseConnection,
) -> None:
    before = [tuple(row) for row in filled.execute("SELECT * FROM snapshot_withdrawal")]
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        filled.execute(REPLACE_BY_SNAPSHOT_ID)
    assert [tuple(row) for row in filled.execute("SELECT * FROM snapshot_withdrawal")] == before


def test_new_rows_can_still_be_appended(filled: DatabaseConnection) -> None:
    second = _snapshot(filled, "monthly")
    _value(filled, second)
    _withdrawal(filled, second, "second one")
    assert [_count(filled, table) for table in TABLES] == [2, 2, 2]
