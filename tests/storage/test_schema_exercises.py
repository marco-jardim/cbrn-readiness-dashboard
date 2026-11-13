# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercises schema, migration 0004 (T4.1): every Accept bullet, in plain SQL.

All data is fictitious. The ``migrated_db`` fixture (``tests/storage/conftest.py``) is a fresh
database with every real migration applied and foreign keys ON.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from cbrn_dashboard.storage.db import DatabaseConnection

TABLES = ("exercise_edition", "exercise_country", "evaluation_metric", "evaluation_result")


# --------------------------------------------------------------------------- helpers


def add_edition(
    conn: DatabaseConnection,
    code: str = "DEMO-EX-01",
    *,
    kind: str = "CBRAMED",
    start_on: str = "2026-03-02",
    end_on: str = "2026-03-06",
    participants: int | None = 10,
) -> int:
    """Insert an edition and return its id."""
    cursor = conn.execute(
        "INSERT INTO exercise_edition (code, kind, start_on, end_on, participants)"
        " VALUES (?, ?, ?, ?, ?)",
        (code, kind, start_on, end_on, participants),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def add_metric(
    conn: DatabaseConnection,
    code: str = "DEMO-M1",
    *,
    scale_min: float | None = 1.0,
    scale_max: float | None = 5.0,
) -> int:
    """Insert a metric and return its id."""
    cursor = conn.execute(
        "INSERT INTO evaluation_metric (code, scale_min, scale_max) VALUES (?, ?, ?)",
        (code, scale_min, scale_max),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def add_country(conn: DatabaseConnection, edition_id: int, country_code: str) -> None:
    conn.execute(
        "INSERT INTO exercise_country (edition_id, country_code) VALUES (?, ?)",
        (edition_id, country_code),
    )


def add_result(
    conn: DatabaseConnection, edition_id: int, metric_id: int, value: float = 4.0
) -> None:
    conn.execute(
        "INSERT INTO evaluation_result (edition_id, metric_id, value) VALUES (?, ?, ?)",
        (edition_id, metric_id, value),
    )


def count(conn: DatabaseConnection, table: str) -> int:
    value: int = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return value


# --------------------------------------------------------------------------- tables


@pytest.mark.parametrize("table", TABLES)
def test_table_exists_and_is_strict(migrated_db: DatabaseConnection, table: str) -> None:
    row = migrated_db.execute(
        "SELECT type, strict FROM pragma_table_list WHERE schema = 'main' AND name = ?", (table,)
    ).fetchone()
    assert row is not None
    assert row["type"] == "table"
    assert row["strict"] == 1


def test_no_metric_is_seeded(migrated_db: DatabaseConnection) -> None:
    assert count(migrated_db, "evaluation_metric") == 0
    assert count(migrated_db, "evaluation_result") == 0
    assert count(migrated_db, "exercise_edition") == 0
    assert count(migrated_db, "exercise_country") == 0


# --------------------------------------------------------------------------- edition


def test_kind_accepts_the_three_values(migrated_db: DatabaseConnection) -> None:
    for number, kind in enumerate(("CBRAMED", "EXBRAMED", "OTHER")):
        add_edition(migrated_db, f"DEMO-EX-{number}", kind=kind)
    assert count(migrated_db, "exercise_edition") == 3


@pytest.mark.parametrize("kind", ["OTHERS", "cbramed", "", "TABLETOP"])
def test_kind_outside_the_three_is_rejected(migrated_db: DatabaseConnection, kind: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        add_edition(migrated_db, kind=kind)


def test_kind_null_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO exercise_edition (code, kind, start_on, end_on)"
            " VALUES ('DEMO-EX-01', NULL, '2026-03-02', '2026-03-06')"
        )


def test_end_before_start_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        add_edition(migrated_db, start_on="2026-03-06", end_on="2026-03-05")


def test_end_equal_to_start_is_accepted(migrated_db: DatabaseConnection) -> None:
    add_edition(migrated_db, start_on="2026-03-06", end_on="2026-03-06")
    assert count(migrated_db, "exercise_edition") == 1


def test_negative_participants_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        add_edition(migrated_db, participants=-1)


@pytest.mark.parametrize("participants", [None, 0, 25])
def test_participants_null_zero_and_positive_are_accepted(
    migrated_db: DatabaseConnection, participants: int | None
) -> None:
    edition_id = add_edition(migrated_db, participants=participants)
    stored = migrated_db.execute(
        "SELECT participants FROM exercise_edition WHERE id = ?", (edition_id,)
    ).fetchone()[0]
    assert stored == participants


def test_edition_code_is_unique(migrated_db: DatabaseConnection) -> None:
    add_edition(migrated_db, "DEMO-EX-01")
    with pytest.raises(sqlite3.IntegrityError):
        add_edition(migrated_db, "DEMO-EX-01")


# --------------------------------------------------------------------------- countries


@pytest.mark.parametrize("country_code", ["B", "BRA", ""])
def test_country_code_of_wrong_length_is_rejected(
    migrated_db: DatabaseConnection, country_code: str
) -> None:
    edition_id = add_edition(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        add_country(migrated_db, edition_id, country_code)


@pytest.mark.parametrize("country_code", ["br", "Br", "1A", "B1", "B ", "ÉA"])
def test_country_code_that_is_not_two_uppercase_letters_is_rejected(
    migrated_db: DatabaseConnection, country_code: str
) -> None:
    edition_id = add_edition(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        add_country(migrated_db, edition_id, country_code)


def test_country_code_of_two_uppercase_letters_is_accepted(migrated_db: DatabaseConnection) -> None:
    edition_id = add_edition(migrated_db)
    add_country(migrated_db, edition_id, "BR")
    assert count(migrated_db, "exercise_country") == 1


def test_same_country_twice_in_one_edition_is_rejected(migrated_db: DatabaseConnection) -> None:
    edition_id = add_edition(migrated_db)
    add_country(migrated_db, edition_id, "BR")
    with pytest.raises(sqlite3.IntegrityError):
        add_country(migrated_db, edition_id, "BR")


def test_same_country_in_two_editions_is_accepted(migrated_db: DatabaseConnection) -> None:
    first = add_edition(migrated_db, "DEMO-EX-01")
    second = add_edition(migrated_db, "DEMO-EX-02")
    add_country(migrated_db, first, "BR")
    add_country(migrated_db, second, "BR")
    assert count(migrated_db, "exercise_country") == 2


def test_country_of_a_missing_edition_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        add_country(migrated_db, 999, "BR")


# --------------------------------------------------------------------------- metrics


def test_metric_code_is_unique(migrated_db: DatabaseConnection) -> None:
    add_metric(migrated_db, "DEMO-M1")
    with pytest.raises(sqlite3.IntegrityError):
        add_metric(migrated_db, "DEMO-M1")


def test_metric_defaults(migrated_db: DatabaseConnection) -> None:
    metric_id = add_metric(migrated_db)
    row = migrated_db.execute(
        "SELECT higher_is_better, active FROM evaluation_metric WHERE id = ?", (metric_id,)
    ).fetchone()
    assert (row["higher_is_better"], row["active"]) == (1, 1)


def test_scale_max_below_scale_min_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        add_metric(migrated_db, scale_min=5.0, scale_max=1.0)


@pytest.mark.parametrize(
    ("scale_min", "scale_max"), [(1.0, 5.0), (3.0, 3.0), (None, 5.0), (1.0, None), (None, None)]
)
def test_valid_or_partial_scales_are_accepted(
    migrated_db: DatabaseConnection, scale_min: float | None, scale_max: float | None
) -> None:
    add_metric(migrated_db, scale_min=scale_min, scale_max=scale_max)
    assert count(migrated_db, "evaluation_metric") == 1


@pytest.mark.parametrize("column", ["higher_is_better", "active"])
def test_flags_outside_zero_and_one_are_rejected(
    migrated_db: DatabaseConnection, column: str
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(f"INSERT INTO evaluation_metric (code, {column}) VALUES ('DEMO-M1', 2)")


def test_metric_in_use_cannot_be_deleted(migrated_db: DatabaseConnection) -> None:
    edition_id = add_edition(migrated_db)
    metric_id = add_metric(migrated_db)
    add_result(migrated_db, edition_id, metric_id)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("DELETE FROM evaluation_metric WHERE id = ?", (metric_id,))
    assert count(migrated_db, "evaluation_metric") == 1
    assert count(migrated_db, "evaluation_result") == 1


def test_unused_metric_can_be_deleted(migrated_db: DatabaseConnection) -> None:
    metric_id = add_metric(migrated_db)
    migrated_db.execute("DELETE FROM evaluation_metric WHERE id = ?", (metric_id,))
    assert count(migrated_db, "evaluation_metric") == 0


def test_metric_becomes_deletable_once_its_edition_is_gone(
    migrated_db: DatabaseConnection,
) -> None:
    edition_id = add_edition(migrated_db)
    metric_id = add_metric(migrated_db)
    add_result(migrated_db, edition_id, metric_id)
    migrated_db.execute("DELETE FROM exercise_edition WHERE id = ?", (edition_id,))
    migrated_db.execute("DELETE FROM evaluation_metric WHERE id = ?", (metric_id,))
    assert count(migrated_db, "evaluation_metric") == 0


# --------------------------------------------------------------------------- results


def test_second_result_for_same_edition_and_metric_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    edition_id = add_edition(migrated_db)
    metric_id = add_metric(migrated_db)
    add_result(migrated_db, edition_id, metric_id, 4.0)
    with pytest.raises(sqlite3.IntegrityError):
        add_result(migrated_db, edition_id, metric_id, 3.0)


def test_same_metric_in_two_editions_and_two_metrics_in_one_edition_are_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    first = add_edition(migrated_db, "DEMO-EX-01")
    second = add_edition(migrated_db, "DEMO-EX-02")
    metric_one = add_metric(migrated_db, "DEMO-M1")
    metric_two = add_metric(migrated_db, "DEMO-M2")
    add_result(migrated_db, first, metric_one)
    add_result(migrated_db, second, metric_one)
    add_result(migrated_db, first, metric_two)
    assert count(migrated_db, "evaluation_result") == 3


def test_negative_respondents_is_rejected(migrated_db: DatabaseConnection) -> None:
    edition_id = add_edition(migrated_db)
    metric_id = add_metric(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO evaluation_result (edition_id, metric_id, value, respondents)"
            " VALUES (?, ?, 4.0, -1)",
            (edition_id, metric_id),
        )


@pytest.mark.parametrize("respondents", [None, 0, 12])
def test_respondents_null_zero_and_positive_are_accepted(
    migrated_db: DatabaseConnection, respondents: int | None
) -> None:
    edition_id = add_edition(migrated_db)
    metric_id = add_metric(migrated_db)
    migrated_db.execute(
        "INSERT INTO evaluation_result (edition_id, metric_id, value, respondents)"
        " VALUES (?, ?, 4.0, ?)",
        (edition_id, metric_id, respondents),
    )
    assert count(migrated_db, "evaluation_result") == 1


def test_result_value_is_required(migrated_db: DatabaseConnection) -> None:
    edition_id = add_edition(migrated_db)
    metric_id = add_metric(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO evaluation_result (edition_id, metric_id, value) VALUES (?, ?, NULL)",
            (edition_id, metric_id),
        )


def test_result_of_a_missing_edition_or_metric_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    edition_id = add_edition(migrated_db)
    metric_id = add_metric(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        add_result(migrated_db, 999, metric_id)
    with pytest.raises(sqlite3.IntegrityError):
        add_result(migrated_db, edition_id, 999)


# --------------------------------------------------------------------------- cascade


def test_deleting_an_edition_deletes_its_countries_and_results(
    migrated_db: DatabaseConnection,
) -> None:
    doomed = add_edition(migrated_db, "DEMO-EX-01")
    kept = add_edition(migrated_db, "DEMO-EX-02")
    metric_id = add_metric(migrated_db)
    for edition_id in (doomed, kept):
        add_country(migrated_db, edition_id, "BR")
        add_country(migrated_db, edition_id, "CL")
        add_result(migrated_db, edition_id, metric_id)

    migrated_db.execute("DELETE FROM exercise_edition WHERE id = ?", (doomed,))

    assert count(migrated_db, "exercise_edition") == 1
    for table in ("exercise_country", "evaluation_result"):
        remaining = migrated_db.execute(f"SELECT DISTINCT edition_id FROM {table}").fetchall()
        assert [row["edition_id"] for row in remaining] == [kept]
    assert count(migrated_db, "exercise_country") == 2
    assert count(migrated_db, "evaluation_result") == 1
    assert count(migrated_db, "evaluation_metric") == 1


def test_result_metric_index_exists(migrated_db: DatabaseConnection) -> None:
    columns = [
        row["name"]
        for row in migrated_db.execute(
            "SELECT name FROM pragma_index_info('evaluation_result_metric_idx') ORDER BY seqno"
        )
    ]
    assert columns == ["metric_id"]
