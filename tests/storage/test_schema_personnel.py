# SPDX-License-Identifier: GPL-3.0-or-later
"""Personnel schema (T2.1, migration 0002): every Accept bullet of the task."""

from __future__ import annotations

import sqlite3

import pytest

from cbrn_dashboard.storage.db import DatabaseConnection

PERSONNEL_TABLES = (
    "staff_member",
    "ppe_certification",
    "training_course",
    "training_record",
    "academic_degree",
)


# --------------------------------------------------------------------------- helpers


def add_staff(conn: sqlite3.Connection, identifier: str = "DEMO-P001") -> int:
    cursor = conn.execute(
        "INSERT INTO staff_member (identifier, active_from) VALUES (?, '2024-01-01')",
        (identifier,),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def add_course(conn: sqlite3.Connection, code: str = "DEMO-COURSE-1") -> int:
    cursor = conn.execute("INSERT INTO training_course (code) VALUES (?)", (code,))
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def add_certificate(
    conn: sqlite3.Connection,
    staff_id: int,
    *,
    level: str = "A",
    issued_on: str = "2024-02-01",
    valid_until: str = "2026-02-01",
) -> None:
    conn.execute(
        "INSERT INTO ppe_certification (staff_id, ppe_level, issued_on, valid_until) "
        "VALUES (?, ?, ?, ?)",
        (staff_id, level, issued_on, valid_until),
    )


def add_training(
    conn: sqlite3.Connection,
    staff_id: int,
    course_id: int,
    completed_on: str = "2024-03-01",
) -> None:
    conn.execute(
        "INSERT INTO training_record (staff_id, course_id, completed_on) VALUES (?, ?, ?)",
        (staff_id, course_id, completed_on),
    )


def add_degree(
    conn: sqlite3.Connection,
    staff_id: int,
    *,
    level: str = "master",
    field: str | None = None,
    year: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO academic_degree (staff_id, level, field, year) VALUES (?, ?, ?, ?)",
        (staff_id, level, field, year),
    )


def column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def count(conn: sqlite3.Connection, table: str) -> int:
    value: int = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return value


# --------------------------------------------------------------------------- tables


def test_the_five_tables_exist_and_are_strict(migrated_db: DatabaseConnection) -> None:
    rows = migrated_db.execute("PRAGMA table_list").fetchall()
    strict = {row[1]: row[5] for row in rows if row[0] == "main"}
    for table in PERSONNEL_TABLES:
        assert table in strict, table
        assert strict[table] == 1, table


def test_the_core_tables_of_0001_are_still_there(migrated_db: DatabaseConnection) -> None:
    names = {
        row[0] for row in migrated_db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"app_meta", "setting", "change_log"} <= names


def test_the_course_list_starts_empty(migrated_db: DatabaseConnection) -> None:
    assert count(migrated_db, "training_course") == 0


# --------------------------------------------------------------------------- checks


@pytest.mark.parametrize("level", ["D", "a", "", "AA"])
def test_unknown_ppe_level_is_rejected(migrated_db: DatabaseConnection, level: str) -> None:
    staff_id = add_staff(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        add_certificate(migrated_db, staff_id, level=level)


@pytest.mark.parametrize("level", ["A", "B", "C"])
def test_known_ppe_levels_are_accepted(migrated_db: DatabaseConnection, level: str) -> None:
    staff_id = add_staff(migrated_db)
    add_certificate(migrated_db, staff_id, level=level)
    assert count(migrated_db, "ppe_certification") == 1


def test_valid_until_before_issued_on_is_rejected(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        add_certificate(migrated_db, staff_id, issued_on="2024-02-01", valid_until="2024-01-31")


def test_valid_until_equal_to_issued_on_is_accepted(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    add_certificate(migrated_db, staff_id, issued_on="2024-02-01", valid_until="2024-02-01")
    assert count(migrated_db, "ppe_certification") == 1


def test_unknown_degree_level_is_rejected(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        add_degree(migrated_db, staff_id, level="bachelor")


@pytest.mark.parametrize("level", ["specialisation", "master", "doctorate"])
def test_known_degree_levels_are_accepted(migrated_db: DatabaseConnection, level: str) -> None:
    staff_id = add_staff(migrated_db)
    add_degree(migrated_db, staff_id, level=level)
    assert count(migrated_db, "academic_degree") == 1


def test_unknown_degree_status_is_rejected(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO academic_degree (staff_id, level, status) VALUES (?, 'master', 'dropped')",
            (staff_id,),
        )


def test_degree_status_defaults_to_completed(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    add_degree(migrated_db, staff_id)
    status = migrated_db.execute("SELECT status FROM academic_degree").fetchone()[0]
    assert status == "completed"


def test_in_progress_degree_status_is_accepted(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    migrated_db.execute(
        "INSERT INTO academic_degree (staff_id, level, status) "
        "VALUES (?, 'doctorate', 'in_progress')",
        (staff_id,),
    )
    assert count(migrated_db, "academic_degree") == 1


def test_identifier_is_unique(migrated_db: DatabaseConnection) -> None:
    add_staff(migrated_db, "DEMO-P001")
    with pytest.raises(sqlite3.IntegrityError):
        add_staff(migrated_db, "DEMO-P001")
    add_staff(migrated_db, "DEMO-P002")
    assert count(migrated_db, "staff_member") == 2


def test_course_code_is_unique(migrated_db: DatabaseConnection) -> None:
    add_course(migrated_db, "DEMO-COURSE-1")
    with pytest.raises(sqlite3.IntegrityError):
        add_course(migrated_db, "DEMO-COURSE-1")


# --------------------------------------------------------------------------- D17 and D24


@pytest.mark.parametrize("table", ["staff_member", "ppe_certification", "training_record"])
def test_personal_tables_have_no_notes_column(migrated_db: DatabaseConnection, table: str) -> None:
    assert "notes" not in column_names(migrated_db, table)


def test_no_renewal_from_is_null_by_default(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    add_certificate(migrated_db, staff_id)
    row = migrated_db.execute(
        "SELECT no_renewal_from, no_renewal_reason FROM ppe_certification"
    ).fetchone()
    assert row[0] is None
    assert row[1] is None


def test_no_renewal_from_has_no_default_in_the_schema(migrated_db: DatabaseConnection) -> None:
    columns = {row[1]: row for row in migrated_db.execute("PRAGMA table_info(ppe_certification)")}
    assert columns["no_renewal_from"][3] == 0  # nullable
    assert columns["no_renewal_from"][4] is None  # no default


@pytest.mark.parametrize("reason", ["left_unit", "role_change", "other"])
def test_known_no_renewal_reasons_are_accepted(
    migrated_db: DatabaseConnection, reason: str
) -> None:
    staff_id = add_staff(migrated_db)
    migrated_db.execute(
        "INSERT INTO ppe_certification "
        "(staff_id, ppe_level, issued_on, valid_until, no_renewal_from, no_renewal_reason) "
        "VALUES (?, 'A', '2024-02-01', '2026-02-01', '2025-06-01', ?)",
        (staff_id, reason),
    )
    stored = migrated_db.execute("SELECT no_renewal_reason FROM ppe_certification").fetchone()[0]
    assert stored == reason


@pytest.mark.parametrize("reason", ["retired", "", "LEFT_UNIT"])
def test_unknown_no_renewal_reason_is_rejected(
    migrated_db: DatabaseConnection, reason: str
) -> None:
    staff_id = add_staff(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO ppe_certification "
            "(staff_id, ppe_level, issued_on, valid_until, no_renewal_from, no_renewal_reason) "
            "VALUES (?, 'A', '2024-02-01', '2026-02-01', '2025-06-01', ?)",
            (staff_id, reason),
        )


def test_null_no_renewal_reason_is_accepted(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    migrated_db.execute(
        "INSERT INTO ppe_certification "
        "(staff_id, ppe_level, issued_on, valid_until, no_renewal_from, no_renewal_reason) "
        "VALUES (?, 'A', '2024-02-01', '2026-02-01', '2025-06-01', NULL)",
        (staff_id,),
    )
    assert count(migrated_db, "ppe_certification") == 1


# --------------------------------------------------------------------------- natural keys


def test_second_certificate_with_the_same_key_is_rejected(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    add_certificate(migrated_db, staff_id, level="A", issued_on="2024-02-01")
    with pytest.raises(sqlite3.IntegrityError):
        add_certificate(
            migrated_db, staff_id, level="A", issued_on="2024-02-01", valid_until="2030-01-01"
        )


def test_certificates_differing_in_one_key_part_are_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    first = add_staff(migrated_db, "DEMO-P001")
    second = add_staff(migrated_db, "DEMO-P002")
    add_certificate(migrated_db, first, level="A", issued_on="2024-02-01")
    add_certificate(migrated_db, first, level="B", issued_on="2024-02-01")
    add_certificate(migrated_db, first, level="A", issued_on="2025-02-01")
    add_certificate(migrated_db, second, level="A", issued_on="2024-02-01")
    assert count(migrated_db, "ppe_certification") == 4


def test_second_training_record_with_the_same_key_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    staff_id = add_staff(migrated_db)
    course_id = add_course(migrated_db)
    add_training(migrated_db, staff_id, course_id, "2024-03-01")
    with pytest.raises(sqlite3.IntegrityError):
        add_training(migrated_db, staff_id, course_id, "2024-03-01")


def test_training_records_differing_in_one_key_part_are_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    first = add_staff(migrated_db, "DEMO-P001")
    second = add_staff(migrated_db, "DEMO-P002")
    course_a = add_course(migrated_db, "DEMO-COURSE-1")
    course_b = add_course(migrated_db, "DEMO-COURSE-2")
    add_training(migrated_db, first, course_a, "2024-03-01")
    add_training(migrated_db, first, course_b, "2024-03-01")
    add_training(migrated_db, first, course_a, "2025-03-01")
    add_training(migrated_db, second, course_a, "2024-03-01")
    assert count(migrated_db, "training_record") == 4


def test_second_degree_with_the_same_key_is_rejected(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    add_degree(migrated_db, staff_id, level="master", field="DEMO-FIELD", year=2020)
    with pytest.raises(sqlite3.IntegrityError):
        add_degree(migrated_db, staff_id, level="master", field="DEMO-FIELD", year=2020)


def test_second_degree_with_empty_field_and_year_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    staff_id = add_staff(migrated_db)
    add_degree(migrated_db, staff_id, level="master", field=None, year=None)
    with pytest.raises(sqlite3.IntegrityError):
        add_degree(migrated_db, staff_id, level="master", field=None, year=None)


def test_second_degree_with_empty_field_and_the_same_year_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    staff_id = add_staff(migrated_db)
    add_degree(migrated_db, staff_id, level="master", field=None, year=2020)
    with pytest.raises(sqlite3.IntegrityError):
        add_degree(migrated_db, staff_id, level="master", field=None, year=2020)


def test_degrees_differing_only_in_field_are_accepted(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    add_degree(migrated_db, staff_id, level="master", field="DEMO-FIELD-1", year=2020)
    add_degree(migrated_db, staff_id, level="master", field="DEMO-FIELD-2", year=2020)
    add_degree(migrated_db, staff_id, level="master", field=None, year=2020)
    assert count(migrated_db, "academic_degree") == 3


def test_degrees_differing_in_year_level_or_staff_are_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    first = add_staff(migrated_db, "DEMO-P001")
    second = add_staff(migrated_db, "DEMO-P002")
    add_degree(migrated_db, first, level="master", field="DEMO-FIELD", year=2020)
    add_degree(migrated_db, first, level="master", field="DEMO-FIELD", year=2021)
    add_degree(migrated_db, first, level="doctorate", field="DEMO-FIELD", year=2020)
    add_degree(migrated_db, second, level="master", field="DEMO-FIELD", year=2020)
    add_degree(migrated_db, first, level="master", field="DEMO-FIELD", year=None)
    assert count(migrated_db, "academic_degree") == 5


# --------------------------------------------------------------------------- foreign keys


def test_deleting_a_staff_member_deletes_the_children(migrated_db: DatabaseConnection) -> None:
    leaving = add_staff(migrated_db, "DEMO-P001")
    staying = add_staff(migrated_db, "DEMO-P002")
    course_id = add_course(migrated_db)
    for staff_id in (leaving, staying):
        add_certificate(migrated_db, staff_id)
        add_training(migrated_db, staff_id, course_id)
        add_degree(migrated_db, staff_id)

    migrated_db.execute("DELETE FROM staff_member WHERE id = ?", (leaving,))

    for table in ("ppe_certification", "training_record", "academic_degree"):
        remaining = migrated_db.execute(f"SELECT staff_id FROM {table}").fetchall()
        assert [row[0] for row in remaining] == [staying], table
    assert count(migrated_db, "training_course") == 1


def test_a_course_in_use_cannot_be_deleted(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    course_id = add_course(migrated_db)
    add_training(migrated_db, staff_id, course_id)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("DELETE FROM training_course WHERE id = ?", (course_id,))
    assert count(migrated_db, "training_course") == 1
    assert count(migrated_db, "training_record") == 1


def test_an_unused_course_can_be_deleted(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    used = add_course(migrated_db, "DEMO-COURSE-1")
    unused = add_course(migrated_db, "DEMO-COURSE-2")
    add_training(migrated_db, staff_id, used)
    migrated_db.execute("DELETE FROM training_course WHERE id = ?", (unused,))
    codes = [row[0] for row in migrated_db.execute("SELECT code FROM training_course")]
    assert codes == ["DEMO-COURSE-1"]


def test_a_course_can_be_deleted_after_its_records_are_gone(
    migrated_db: DatabaseConnection,
) -> None:
    staff_id = add_staff(migrated_db)
    course_id = add_course(migrated_db)
    add_training(migrated_db, staff_id, course_id)
    migrated_db.execute("DELETE FROM staff_member WHERE id = ?", (staff_id,))
    migrated_db.execute("DELETE FROM training_course WHERE id = ?", (course_id,))
    assert count(migrated_db, "training_course") == 0


def test_foreign_keys_are_on_for_the_connection(migrated_db: DatabaseConnection) -> None:
    assert migrated_db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_unknown_staff_id_is_rejected_everywhere(migrated_db: DatabaseConnection) -> None:
    course_id = add_course(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        add_certificate(migrated_db, 9999)
    with pytest.raises(sqlite3.IntegrityError):
        add_training(migrated_db, 9999, course_id)
    with pytest.raises(sqlite3.IntegrityError):
        add_degree(migrated_db, 9999)


def test_unknown_course_id_is_rejected(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        add_training(migrated_db, staff_id, 9999)


# --------------------------------------------------------------------------- STRICT typing


def test_strict_typing_rejects_text_in_an_integer_column(migrated_db: DatabaseConnection) -> None:
    staff_id = add_staff(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO academic_degree (staff_id, level, year) VALUES (?, 'master', 'twenty')",
            (staff_id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO training_course (code, active) VALUES ('DEMO-COURSE-1', 'yes')"
        )
