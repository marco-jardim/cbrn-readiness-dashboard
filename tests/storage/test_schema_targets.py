# SPDX-License-Identifier: GPL-3.0-or-later
"""Schema tests of migration 0006 (indicator targets; PLAN.md task T6.1, D14, P03)."""

from __future__ import annotations

import sqlite3

import pytest

from cbrn_dashboard.storage.db import DatabaseConnection


def _count(db: DatabaseConnection) -> int:
    row = db.execute("SELECT count(*) FROM indicator_target").fetchone()
    return int(row[0])


def test_table_exists_and_is_strict(migrated_db: DatabaseConnection) -> None:
    row = migrated_db.execute(
        "SELECT strict FROM pragma_table_list WHERE name = ?", ("indicator_target",)
    ).fetchone()
    assert row is not None
    assert row[0] == 1


def test_columns_are_those_of_the_plan(migrated_db: DatabaseConnection) -> None:
    columns = [row[1] for row in migrated_db.execute("PRAGMA table_info(indicator_target)")]
    assert columns == [
        "indicator_code",
        "dimension",
        "warning_value",
        "critical_value",
        "enabled",
    ]


def test_no_default_targets_are_seeded(migrated_db: DatabaseConnection) -> None:
    # P03: the application invents no readiness standard.
    assert _count(migrated_db) == 0


def test_primary_key_is_code_and_dimension(migrated_db: DatabaseConnection) -> None:
    keys = {
        row[1]: row[5]
        for row in migrated_db.execute("PRAGMA table_info(indicator_target)")
        if row[5] > 0
    }
    assert keys == {"indicator_code": 1, "dimension": 2}


def test_duplicate_code_and_dimension_is_rejected(migrated_db: DatabaseConnection) -> None:
    sql = "INSERT INTO indicator_target (indicator_code, dimension) VALUES (?, ?)"
    migrated_db.execute(sql, ("PERS_CERT_VALID", "level=A"))
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(sql, ("PERS_CERT_VALID", "level=A"))


def test_same_code_with_another_dimension_is_accepted(migrated_db: DatabaseConnection) -> None:
    for dimension in ("level=A", "level=B", ""):
        migrated_db.execute(
            "INSERT INTO indicator_target (indicator_code, dimension) VALUES (?, ?)",
            ("PERS_CERT_VALID", dimension),
        )
    assert _count(migrated_db) == 3


def test_dimension_defaults_to_empty_text(migrated_db: DatabaseConnection) -> None:
    sql = "INSERT INTO indicator_target (indicator_code) VALUES (?)"
    migrated_db.execute(sql, ("PERS_TRAINING_12M",))
    row = migrated_db.execute("SELECT dimension FROM indicator_target").fetchone()
    assert row[0] == ""
    with pytest.raises(sqlite3.IntegrityError):  # '' is the same key as the default
        migrated_db.execute(sql, ("PERS_TRAINING_12M",))


def test_enabled_defaults_to_one_and_accepts_only_zero_or_one(
    migrated_db: DatabaseConnection,
) -> None:
    migrated_db.execute("INSERT INTO indicator_target (indicator_code) VALUES ('A_CODE')")
    assert migrated_db.execute("SELECT enabled FROM indicator_target").fetchone()[0] == 1
    migrated_db.execute("UPDATE indicator_target SET enabled = 0")
    for bad in (2, -1):
        with pytest.raises(sqlite3.IntegrityError):
            migrated_db.execute(
                "INSERT INTO indicator_target (indicator_code, enabled) VALUES ('X_CODE', ?)",
                (bad,),
            )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("UPDATE indicator_target SET enabled = 2")


def test_thresholds_may_be_null_and_are_stored_as_reals(migrated_db: DatabaseConnection) -> None:
    migrated_db.execute(
        "INSERT INTO indicator_target (indicator_code, dimension, warning_value, critical_value) "
        "VALUES ('A_CODE', '', NULL, NULL)"
    )
    migrated_db.execute(
        "INSERT INTO indicator_target (indicator_code, dimension, warning_value, critical_value) "
        "VALUES ('B_CODE', '', 5, NULL)"
    )
    row = migrated_db.execute(
        "SELECT typeof(warning_value), critical_value FROM indicator_target "
        "WHERE indicator_code = 'B_CODE'"
    ).fetchone()
    assert row[0] == "real"
    assert row[1] is None


@pytest.mark.parametrize("column", ["warning_value", "critical_value"])
def test_text_in_a_real_column_is_rejected(migrated_db: DatabaseConnection, column: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            f"INSERT INTO indicator_target (indicator_code, {column}) VALUES ('A_CODE', 'high')"
        )


def test_code_is_required(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("INSERT INTO indicator_target (dimension) VALUES ('level=A')")
