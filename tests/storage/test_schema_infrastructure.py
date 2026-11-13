# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for migration 0003, the infrastructure schema (PLAN.md T3.1, A05, A06, D16).

The tests use the shared ``migrated_db`` fixture (a fresh database with every real migration
applied) and plain SQL. The data is fictitious.
"""

from __future__ import annotations

import sqlite3

import pytest

from cbrn_dashboard.storage.db import DatabaseConnection

BUILT_IN_CODES = ("bed", "bay", "neg_pressure_filtration", "decon_tent")
INFRASTRUCTURE_TABLES = ("asset_type", "asset", "asset_status_event", "maintenance_event")


def _type_id(conn: DatabaseConnection, code: str) -> int:
    row = conn.execute("SELECT id FROM asset_type WHERE code = ?", (code,)).fetchone()
    assert row is not None
    return int(row[0])


def _add_asset(conn: DatabaseConnection, tag: str, type_code: str = "bed") -> int:
    cursor = conn.execute(
        "INSERT INTO asset (type_id, tag, in_service_from) VALUES (?, ?, '2025-01-01')",
        (_type_id(conn, type_code), tag),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_user_type(conn: DatabaseConnection, code: str) -> int:
    cursor = conn.execute(
        "INSERT INTO asset_type (code, label_pt_br) VALUES (?, 'Tipo de demonstração')", (code,)
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _count(conn: DatabaseConnection, table: str, where: str, params: tuple[object, ...]) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table} WHERE {where}", params).fetchone()
    return int(row[0])


# --------------------------------------------------------------------------- tables and seed


def test_tables_are_strict(migrated_db: DatabaseConnection) -> None:
    strict = {row[1]: row[5] for row in migrated_db.execute("PRAGMA table_list").fetchall()}
    for table in INFRASTRUCTURE_TABLES:
        assert strict[table] == 1, table


def test_built_in_types_are_seeded(migrated_db: DatabaseConnection) -> None:
    rows = migrated_db.execute(
        "SELECT code, built_in, label_pt_br, label_en_us, label_es_es,"
        " default_maintenance_interval_days, active FROM asset_type"
    ).fetchall()
    assert sorted(row[0] for row in rows) == sorted(BUILT_IN_CODES)
    for row in rows:
        assert row[1] == 1
        assert row[2] is None
        assert row[3] is None
        assert row[4] is None
        assert row[5] is None
        assert row[6] == 1


def test_no_asset_is_seeded(migrated_db: DatabaseConnection) -> None:
    assert _count(migrated_db, "asset", "1 = 1", ()) == 0


def test_type_code_is_unique(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("INSERT INTO asset_type (code) VALUES ('bed')")


def test_user_type_defaults(migrated_db: DatabaseConnection) -> None:
    type_id = _add_user_type(migrated_db, "demo_shelter")
    row = migrated_db.execute(
        "SELECT built_in, active, default_maintenance_interval_days FROM asset_type WHERE id = ?",
        (type_id,),
    ).fetchone()
    assert tuple(row) == (0, 1, None)


@pytest.mark.parametrize("column", ["built_in", "active"])
def test_type_boolean_columns_accept_only_0_and_1(
    migrated_db: DatabaseConnection, column: str
) -> None:
    insert = f"INSERT INTO asset_type (code, {column}) VALUES (?, ?)"
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(insert, ("demo_bad", 2))
    migrated_db.execute(insert, ("demo_zero", 0))
    migrated_db.execute(insert, ("demo_one", 1))


# --------------------------------------------------------------------------- status events


def test_status_other_than_the_three_is_rejected(migrated_db: DatabaseConnection) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset_status_event (asset_id, effective_on, status)"
            " VALUES (?, '2025-02-01', 'broken')",
            (asset_id,),
        )


def test_the_three_statuses_are_accepted(migrated_db: DatabaseConnection) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    for day, status in (
        ("2025-02-01", "operational"),
        ("2025-02-02", "degraded"),
        ("2025-02-03", "out_of_service"),
    ):
        migrated_db.execute(
            "INSERT INTO asset_status_event (asset_id, effective_on, status) VALUES (?, ?, ?)",
            (asset_id, day, status),
        )
    assert _count(migrated_db, "asset_status_event", "asset_id = ?", (asset_id,)) == 3


def test_second_status_event_on_the_same_day_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    migrated_db.execute(
        "INSERT INTO asset_status_event (asset_id, effective_on, status)"
        " VALUES (?, '2025-02-01', 'operational')",
        (asset_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset_status_event (asset_id, effective_on, status)"
            " VALUES (?, '2025-02-01', 'degraded')",
            (asset_id,),
        )


def test_status_event_on_another_day_or_for_another_asset_is_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    first = _add_asset(migrated_db, "DEMO-A001")
    second = _add_asset(migrated_db, "DEMO-A002")
    for asset_id, day in ((first, "2025-02-01"), (first, "2025-02-02"), (second, "2025-02-01")):
        migrated_db.execute(
            "INSERT INTO asset_status_event (asset_id, effective_on, status)"
            " VALUES (?, ?, 'operational')",
            (asset_id, day),
        )
    assert _count(migrated_db, "asset_status_event", "1 = 1", ()) == 3


def test_status_event_for_an_unknown_asset_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset_status_event (asset_id, effective_on, status)"
            " VALUES (999, '2025-02-01', 'operational')"
        )


# --------------------------------------------------------------------------- maintenance events


def test_maintenance_kind_outside_the_list_is_rejected(migrated_db: DatabaseConnection) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO maintenance_event (asset_id, performed_on, kind)"
            " VALUES (?, '2025-03-01', 'repainting')",
            (asset_id,),
        )


@pytest.mark.parametrize("kind", ["preventive", "corrective", "inspection"])
def test_maintenance_kinds_are_accepted(migrated_db: DatabaseConnection, kind: str) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    migrated_db.execute(
        "INSERT INTO maintenance_event (asset_id, performed_on, kind, next_due_on)"
        " VALUES (?, '2025-03-01', ?, '2025-09-01')",
        (asset_id, kind),
    )
    assert _count(migrated_db, "maintenance_event", "asset_id = ?", (asset_id,)) == 1


def test_duplicate_maintenance_event_is_rejected(migrated_db: DatabaseConnection) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    migrated_db.execute(
        "INSERT INTO maintenance_event (asset_id, performed_on, kind)"
        " VALUES (?, '2025-03-01', 'preventive')",
        (asset_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO maintenance_event (asset_id, performed_on, kind, note)"
            " VALUES (?, '2025-03-01', 'preventive', 'second try')",
            (asset_id,),
        )


def test_other_kind_same_day_is_accepted(migrated_db: DatabaseConnection) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    for kind in ("preventive", "inspection"):
        migrated_db.execute(
            "INSERT INTO maintenance_event (asset_id, performed_on, kind)"
            " VALUES (?, '2025-03-01', ?)",
            (asset_id, kind),
        )
    assert _count(migrated_db, "maintenance_event", "asset_id = ?", (asset_id,)) == 2


def test_maintenance_event_for_an_unknown_asset_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO maintenance_event (asset_id, performed_on, kind)"
            " VALUES (999, '2025-03-01', 'inspection')"
        )


# --------------------------------------------------------------------------- intervals (A06)


def test_negative_default_interval_on_a_type_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset_type (code, default_maintenance_interval_days)"
            " VALUES ('demo_negative', -1)"
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "UPDATE asset_type SET default_maintenance_interval_days = -30 WHERE code = 'bed'"
        )


def test_zero_and_null_default_interval_on_a_type_are_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    for code, interval in (("demo_zero", 0), ("demo_null", None), ("demo_positive", 180)):
        migrated_db.execute(
            "INSERT INTO asset_type (code, default_maintenance_interval_days) VALUES (?, ?)",
            (code, interval),
        )
    rows = dict(
        migrated_db.execute(
            "SELECT code, default_maintenance_interval_days FROM asset_type"
            " WHERE code LIKE 'demo_%'"
        ).fetchall()
    )
    assert rows == {"demo_zero": 0, "demo_null": None, "demo_positive": 180}


def test_negative_interval_on_an_asset_is_rejected(migrated_db: DatabaseConnection) -> None:
    type_id = _type_id(migrated_db, "bed")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset (type_id, tag, in_service_from, maintenance_interval_days)"
            " VALUES (?, 'DEMO-A001', '2025-01-01', -1)",
            (type_id,),
        )
    asset_id = _add_asset(migrated_db, "DEMO-A002")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "UPDATE asset SET maintenance_interval_days = -7 WHERE id = ?", (asset_id,)
        )


def test_zero_and_null_interval_on_an_asset_are_accepted(migrated_db: DatabaseConnection) -> None:
    type_id = _type_id(migrated_db, "bed")
    for tag, interval in (("DEMO-A001", 0), ("DEMO-A002", None), ("DEMO-A003", 90)):
        migrated_db.execute(
            "INSERT INTO asset (type_id, tag, in_service_from, maintenance_interval_days)"
            " VALUES (?, ?, '2025-01-01', ?)",
            (type_id, tag, interval),
        )
    rows = dict(migrated_db.execute("SELECT tag, maintenance_interval_days FROM asset").fetchall())
    assert rows == {"DEMO-A001": 0, "DEMO-A002": None, "DEMO-A003": 90}


# --------------------------------------------------------------------------- dates (P3-04)

BAD_DATES = ("2025-1-01", "2025/01/01", "01-01-2025", "20250101", "2025-01-01T00:00:00", "", "x")


@pytest.mark.parametrize("bad", BAD_DATES)
def test_asset_dates_must_be_iso_shaped(migrated_db: DatabaseConnection, bad: str) -> None:
    type_id = _type_id(migrated_db, "bed")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset (type_id, tag, in_service_from) VALUES (?, 'DEMO-A001', ?)",
            (type_id, bad),
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset (type_id, tag, in_service_from, in_service_until)"
            " VALUES (?, 'DEMO-A002', '2025-01-01', ?)",
            (type_id, bad),
        )


@pytest.mark.parametrize("bad", BAD_DATES)
def test_event_dates_must_be_iso_shaped(migrated_db: DatabaseConnection, bad: str) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset_status_event (asset_id, effective_on, status)"
            " VALUES (?, ?, 'operational')",
            (asset_id, bad),
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO maintenance_event (asset_id, performed_on, kind)"
            " VALUES (?, ?, 'inspection')",
            (asset_id, bad),
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO maintenance_event (asset_id, performed_on, kind, next_due_on)"
            " VALUES (?, '2025-03-01', 'inspection', ?)",
            (asset_id, bad),
        )


def test_asset_in_service_until_before_from_is_rejected(migrated_db: DatabaseConnection) -> None:
    type_id = _type_id(migrated_db, "bed")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset (type_id, tag, in_service_from, in_service_until)"
            " VALUES (?, 'DEMO-A001', '2025-06-01', '2025-05-31')",
            (type_id,),
        )
    asset_id = _add_asset(migrated_db, "DEMO-A002")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "UPDATE asset SET in_service_until = '2024-12-31' WHERE id = ?", (asset_id,)
        )


def test_asset_in_service_until_on_or_after_from_or_null_is_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    type_id = _type_id(migrated_db, "bed")
    cases = (("DEMO-A001", "2025-06-01"), ("DEMO-A002", "2026-01-01"), ("DEMO-A003", None))
    for tag, until in cases:
        migrated_db.execute(
            "INSERT INTO asset (type_id, tag, in_service_from, in_service_until)"
            " VALUES (?, ?, '2025-06-01', ?)",
            (type_id, tag, until),
        )
    assert _count(migrated_db, "asset", "1 = 1", ()) == 3


def test_next_due_before_performed_is_rejected(migrated_db: DatabaseConnection) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO maintenance_event (asset_id, performed_on, kind, next_due_on)"
            " VALUES (?, '2025-03-01', 'preventive', '2025-02-28')",
            (asset_id,),
        )


def test_next_due_on_or_after_performed_or_null_is_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    asset_id = _add_asset(migrated_db, "DEMO-A001")
    cases = (("preventive", "2025-03-01"), ("corrective", "2025-09-01"), ("inspection", None))
    for kind, due in cases:
        migrated_db.execute(
            "INSERT INTO maintenance_event (asset_id, performed_on, kind, next_due_on)"
            " VALUES (?, '2025-03-01', ?, ?)",
            (asset_id, kind, due),
        )
    assert _count(migrated_db, "maintenance_event", "asset_id = ?", (asset_id,)) == 3


# --------------------------------------------------------------------------- assets and types


def test_asset_tag_is_unique(migrated_db: DatabaseConnection) -> None:
    _add_asset(migrated_db, "DEMO-A001")
    with pytest.raises(sqlite3.IntegrityError):
        _add_asset(migrated_db, "DEMO-A001", type_code="bay")


def test_asset_with_an_unknown_type_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset (type_id, tag, in_service_from)"
            " VALUES (999, 'DEMO-A001', '2025-01-01')"
        )


def test_asset_requires_in_service_from(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO asset (type_id, tag) VALUES (?, 'DEMO-A001')",
            (_type_id(migrated_db, "bed"),),
        )


def test_type_in_use_cannot_be_deleted(migrated_db: DatabaseConnection) -> None:
    type_id = _add_user_type(migrated_db, "demo_shelter")
    migrated_db.execute(
        "INSERT INTO asset (type_id, tag, in_service_from) VALUES (?, 'DEMO-A001', '2025-01-01')",
        (type_id,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("DELETE FROM asset_type WHERE id = ?", (type_id,))
    assert _count(migrated_db, "asset_type", "id = ?", (type_id,)) == 1


def test_built_in_type_in_use_cannot_be_deleted(migrated_db: DatabaseConnection) -> None:
    _add_asset(migrated_db, "DEMO-A001", type_code="decon_tent")
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("DELETE FROM asset_type WHERE code = 'decon_tent'")


def test_unused_user_type_can_be_deleted(migrated_db: DatabaseConnection) -> None:
    type_id = _add_user_type(migrated_db, "demo_shelter")
    migrated_db.execute("DELETE FROM asset_type WHERE id = ?", (type_id,))
    assert _count(migrated_db, "asset_type", "id = ?", (type_id,)) == 0


def test_deleting_an_asset_deletes_its_events(migrated_db: DatabaseConnection) -> None:
    doomed = _add_asset(migrated_db, "DEMO-A001")
    kept = _add_asset(migrated_db, "DEMO-A002")
    for asset_id in (doomed, kept):
        migrated_db.execute(
            "INSERT INTO asset_status_event (asset_id, effective_on, status)"
            " VALUES (?, '2025-02-01', 'degraded')",
            (asset_id,),
        )
        migrated_db.execute(
            "INSERT INTO maintenance_event (asset_id, performed_on, kind)"
            " VALUES (?, '2025-03-01', 'corrective')",
            (asset_id,),
        )

    migrated_db.execute("DELETE FROM asset WHERE id = ?", (doomed,))

    assert _count(migrated_db, "asset", "id = ?", (doomed,)) == 0
    assert _count(migrated_db, "asset_status_event", "asset_id = ?", (doomed,)) == 0
    assert _count(migrated_db, "maintenance_event", "asset_id = ?", (doomed,)) == 0
    assert _count(migrated_db, "asset_status_event", "asset_id = ?", (kept,)) == 1
    assert _count(migrated_db, "maintenance_event", "asset_id = ?", (kept,)) == 1
