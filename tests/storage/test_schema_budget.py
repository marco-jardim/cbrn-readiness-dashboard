# SPDX-License-Identifier: GPL-3.0-or-later
"""Schema tests of migrations 0005 and 0008 (budget; PLAN.md T5.1, A08, D15, D16, D27, R24)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from cbrn_dashboard.storage.migrate import load_migrations, migrate

BIG_AMOUNT = 9_007_199_254_740_993  # 2**53 + 1: not exactly representable as a float


def _source_id(db: DatabaseConnection, code: str = "DIRSA") -> int:
    row = db.execute("SELECT id FROM funding_source WHERE code = ?", (code,)).fetchone()
    assert row is not None
    return int(row[0])


def _add_source(db: DatabaseConnection, code: str = "TEST_FUND") -> int:
    cursor = db.execute("INSERT INTO funding_source (code) VALUES (?)", (code,))
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_entry(
    db: DatabaseConnection,
    *,
    fiscal_year: int = 2030,
    source_id: int | None = None,
    currency: str = "BRL",
    allocated_minor: int | None = 100_000,
    description: str | None = None,
) -> int:
    """Insert an entry; with ``description=None`` the column default (``''``) applies."""
    source = _source_id(db) if source_id is None else source_id
    if description is None:
        cursor = db.execute(
            "INSERT INTO budget_entry (fiscal_year, source_id, currency, allocated_minor) "
            "VALUES (?, ?, ?, ?)",
            (fiscal_year, source, currency, allocated_minor),
        )
    else:
        cursor = db.execute(
            "INSERT INTO budget_entry "
            "(fiscal_year, source_id, currency, allocated_minor, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (fiscal_year, source, currency, allocated_minor, description),
        )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_execution(
    db: DatabaseConnection,
    entry_id: int,
    *,
    executed_on: str = "2030-03-31",
    amount_minor: int = 5_000,
) -> int:
    cursor = db.execute(
        "INSERT INTO budget_execution (entry_id, executed_on, amount_minor) VALUES (?, ?, ?)",
        (entry_id, executed_on, amount_minor),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _count(db: DatabaseConnection, table: str) -> int:
    row = db.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0])


# --------------------------------------------------------------------------- structure


@pytest.mark.parametrize("table", ["funding_source", "budget_entry", "budget_execution"])
def test_tables_are_strict(migrated_db: DatabaseConnection, table: str) -> None:
    row = migrated_db.execute(
        "SELECT strict FROM pragma_table_list WHERE name = ?", (table,)
    ).fetchone()
    assert row is not None
    assert row[0] == 1


def test_budget_entry_has_no_executed_minor_column(migrated_db: DatabaseConnection) -> None:
    columns = {row[1] for row in migrated_db.execute("PRAGMA table_info(budget_entry)")}
    assert "executed_minor" not in columns
    assert {
        "id",
        "fiscal_year",
        "source_id",
        "currency",
        "allocated_minor",
        "description",
        "notes",
    } <= columns


# --------------------------------------------------------------------------- funding_source


def test_built_in_sources_are_seeded(migrated_db: DatabaseConnection) -> None:
    rows = migrated_db.execute(
        "SELECT code, built_in, label_pt_br, label_en_us, label_es_es, active "
        "FROM funding_source ORDER BY code"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("COMAER", 1, None, None, None, 1),
        ("DIRSA", 1, None, None, None, 1),
    ]


def test_user_source_defaults(migrated_db: DatabaseConnection) -> None:
    source_id = _add_source(migrated_db)
    row = migrated_db.execute(
        "SELECT built_in, active FROM funding_source WHERE id = ?", (source_id,)
    ).fetchone()
    assert tuple(row) == (0, 1)


def test_source_code_is_unique(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_source(migrated_db, "DIRSA")


@pytest.mark.parametrize("column", ["built_in", "active"])
def test_source_flags_accept_only_zero_and_one(
    migrated_db: DatabaseConnection, column: str
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(f"INSERT INTO funding_source (code, {column}) VALUES ('BAD_FLAG', 2)")


def test_unused_user_source_can_be_deleted(migrated_db: DatabaseConnection) -> None:
    source_id = _add_source(migrated_db)
    migrated_db.execute("DELETE FROM funding_source WHERE id = ?", (source_id,))
    assert _count(migrated_db, "funding_source") == 2


def test_source_in_use_cannot_be_deleted(migrated_db: DatabaseConnection) -> None:
    source_id = _add_source(migrated_db)
    _add_entry(migrated_db, source_id=source_id)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("DELETE FROM funding_source WHERE id = ?", (source_id,))
    assert _count(migrated_db, "funding_source") == 3


def test_built_in_source_in_use_cannot_be_deleted(migrated_db: DatabaseConnection) -> None:
    _add_entry(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("DELETE FROM funding_source WHERE code = 'DIRSA'")


def test_database_does_not_protect_unused_built_in_sources(
    migrated_db: DatabaseConnection,
) -> None:
    """Protecting built-in sources is a service rule (task T5.3), not a database rule."""
    migrated_db.execute("DELETE FROM funding_source WHERE code = 'COMAER'")
    codes = [row[0] for row in migrated_db.execute("SELECT code FROM funding_source")]
    assert codes == ["DIRSA"]


# --------------------------------------------------------------------------- budget_entry


def test_currency_of_three_upper_case_letters_is_accepted(
    migrated_db: DatabaseConnection,
) -> None:
    entry_id = _add_entry(migrated_db, currency="BRL")
    row = migrated_db.execute(
        "SELECT currency FROM budget_entry WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row[0] == "BRL"


@pytest.mark.parametrize("currency", ["", "B", "BR", "BRLX", "BRL ", "brl", "Brl", "B2L", "123"])
def test_bad_currency_is_rejected(migrated_db: DatabaseConnection, currency: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_entry(migrated_db, currency=currency)
    assert _count(migrated_db, "budget_entry") == 0


def test_currency_allow_list_is_not_a_database_rule(migrated_db: DatabaseConnection) -> None:
    """Any ISO 4217 shaped code is stored; BRL, USD and EUR are the service's allow-list (D15)."""
    _add_entry(migrated_db, currency="CHF")
    assert _count(migrated_db, "budget_entry") == 1


def test_duplicate_entry_key_with_description_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    _add_entry(migrated_db, description="Training")
    with pytest.raises(sqlite3.IntegrityError):
        _add_entry(migrated_db, description="Training")
    assert _count(migrated_db, "budget_entry") == 1


def test_duplicate_entry_key_without_description_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    first = _add_entry(migrated_db)
    row = migrated_db.execute(
        "SELECT description FROM budget_entry WHERE id = ?", (first,)
    ).fetchone()
    assert row[0] == ""
    with pytest.raises(sqlite3.IntegrityError):
        _add_entry(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        _add_entry(migrated_db, description="")
    assert _count(migrated_db, "budget_entry") == 1


def test_description_cannot_be_null(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO budget_entry (fiscal_year, source_id, currency, description) "
            "VALUES (2030, ?, 'BRL', NULL)",
            (_source_id(migrated_db),),
        )


def test_entry_key_differing_in_one_part_is_accepted(migrated_db: DatabaseConnection) -> None:
    other_source = _add_source(migrated_db)
    _add_entry(migrated_db, description="Training")
    _add_entry(migrated_db, description="Equipment")
    _add_entry(migrated_db, description="Training", currency="USD")
    _add_entry(migrated_db, description="Training", fiscal_year=2031)
    _add_entry(migrated_db, description="Training", source_id=other_source)
    _add_entry(migrated_db)  # empty description next to named ones
    assert _count(migrated_db, "budget_entry") == 6


def test_allocated_minor_may_be_null(migrated_db: DatabaseConnection) -> None:
    entry_id = _add_entry(migrated_db, allocated_minor=None)
    row = migrated_db.execute(
        "SELECT allocated_minor FROM budget_entry WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row[0] is None


def test_allocated_minor_zero_is_accepted(migrated_db: DatabaseConnection) -> None:
    _add_entry(migrated_db, allocated_minor=0)
    assert _count(migrated_db, "budget_entry") == 1


def test_negative_allocated_minor_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_entry(migrated_db, allocated_minor=-1)
    assert _count(migrated_db, "budget_entry") == 0


@pytest.mark.parametrize("year", [1900, 2026, 2200])
def test_fiscal_year_inside_1900_to_2200_is_accepted(
    migrated_db: DatabaseConnection, year: int
) -> None:
    _add_entry(migrated_db, fiscal_year=year)
    assert _count(migrated_db, "budget_entry") == 1


@pytest.mark.parametrize("year", [-1, 0, 26, 1899, 2201, 20260])
def test_fiscal_year_outside_1900_to_2200_is_rejected(
    migrated_db: DatabaseConnection, year: int
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_entry(migrated_db, fiscal_year=year)
    assert _count(migrated_db, "budget_entry") == 0


def test_entry_with_unknown_source_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_entry(migrated_db, source_id=999_999)


def test_amounts_above_2_pow_53_round_trip_exactly(migrated_db: DatabaseConnection) -> None:
    entry_id = _add_entry(migrated_db, allocated_minor=BIG_AMOUNT)
    execution_id = _add_execution(migrated_db, entry_id, amount_minor=BIG_AMOUNT)
    allocated = migrated_db.execute(
        "SELECT allocated_minor FROM budget_entry WHERE id = ?", (entry_id,)
    ).fetchone()[0]
    executed = migrated_db.execute(
        "SELECT amount_minor FROM budget_execution WHERE id = ?", (execution_id,)
    ).fetchone()[0]
    assert isinstance(allocated, int)
    assert allocated == BIG_AMOUNT
    assert isinstance(executed, int)
    assert executed == BIG_AMOUNT


# --------------------------------------------------------------------------- budget_execution


def test_execution_with_zero_amount_is_accepted(migrated_db: DatabaseConnection) -> None:
    entry_id = _add_entry(migrated_db)
    _add_execution(migrated_db, entry_id, amount_minor=0)
    assert _count(migrated_db, "budget_execution") == 1


def test_execution_with_negative_amount_is_rejected(migrated_db: DatabaseConnection) -> None:
    entry_id = _add_entry(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        _add_execution(migrated_db, entry_id, amount_minor=-1)
    assert _count(migrated_db, "budget_execution") == 0


@pytest.mark.parametrize("day", ["2030-03-31", "1900-01-01", "2200-12-31"])
def test_execution_date_of_iso_shape_is_accepted(migrated_db: DatabaseConnection, day: str) -> None:
    entry_id = _add_entry(migrated_db)
    _add_execution(migrated_db, entry_id, executed_on=day)
    assert _count(migrated_db, "budget_execution") == 1


@pytest.mark.parametrize(
    "day",
    [
        "",
        "2030-3-31",
        "30-03-2030",
        "2030/03/31",
        "20300331",
        "2030-03-31 ",
        " 2030-03-31",
        "2030-03-311",
        "2030-03-31T00:00:00",
        "abcd-ef-gh",
        "2030-0a-31",
    ],
)
def test_execution_date_of_another_shape_is_rejected(
    migrated_db: DatabaseConnection, day: str
) -> None:
    entry_id = _add_entry(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        _add_execution(migrated_db, entry_id, executed_on=day)
    assert _count(migrated_db, "budget_execution") == 0


def test_execution_with_unknown_entry_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_execution(migrated_db, 999_999)


def test_duplicate_execution_key_is_rejected(migrated_db: DatabaseConnection) -> None:
    entry_id = _add_entry(migrated_db)
    _add_execution(migrated_db, entry_id, executed_on="2030-03-31", amount_minor=5_000)
    with pytest.raises(sqlite3.IntegrityError):
        _add_execution(migrated_db, entry_id, executed_on="2030-03-31", amount_minor=5_000)
    assert _count(migrated_db, "budget_execution") == 1


def test_same_date_with_another_amount_is_accepted(migrated_db: DatabaseConnection) -> None:
    entry_id = _add_entry(migrated_db)
    _add_execution(migrated_db, entry_id, executed_on="2030-03-31", amount_minor=5_000)
    _add_execution(migrated_db, entry_id, executed_on="2030-03-31", amount_minor=6_000)
    _add_execution(migrated_db, entry_id, executed_on="2030-04-30", amount_minor=5_000)
    assert _count(migrated_db, "budget_execution") == 3


def test_same_execution_on_another_entry_is_accepted(migrated_db: DatabaseConnection) -> None:
    first = _add_entry(migrated_db, description="Training")
    second = _add_entry(migrated_db, description="Equipment")
    _add_execution(migrated_db, first)
    _add_execution(migrated_db, second)
    assert _count(migrated_db, "budget_execution") == 2


def test_deleting_an_entry_deletes_its_executions(migrated_db: DatabaseConnection) -> None:
    doomed = _add_entry(migrated_db, description="Training")
    kept = _add_entry(migrated_db, description="Equipment")
    _add_execution(migrated_db, doomed, executed_on="2030-03-31")
    _add_execution(migrated_db, doomed, executed_on="2030-04-30")
    kept_execution = _add_execution(migrated_db, kept)

    migrated_db.execute("DELETE FROM budget_entry WHERE id = ?", (doomed,))

    remaining = [row[0] for row in migrated_db.execute("SELECT id FROM budget_execution")]
    assert remaining == [kept_execution]
    assert _count(migrated_db, "budget_entry") == 1


def test_foreign_key_check_is_clean(migrated_db: DatabaseConnection) -> None:
    entry_id = _add_entry(migrated_db)
    _add_execution(migrated_db, entry_id)
    assert migrated_db.execute("PRAGMA foreign_key_check").fetchall() == []


# --------------------------------------------------------------------------- migration 0008 (R24)


@pytest.fixture
def at_seven(tmp_path: Path) -> Iterator[DatabaseConnection]:
    """A database migrated only up to 0007: the Trust Fund is still a built-in source."""
    conn = open_database(tmp_path / "before-0008.sqlite3")
    try:
        migrate(conn, migrations=load_migrations()[:7])
        yield conn
    finally:
        conn.close()


def _sources(db: DatabaseConnection) -> list[tuple[object, ...]]:
    rows = db.execute(
        "SELECT code, built_in, active, label_pt_br, label_en_us, label_es_es "
        "FROM funding_source ORDER BY code"
    ).fetchall()
    return [tuple(row) for row in rows]


def _migrate_to_latest(db: DatabaseConnection) -> None:
    result = migrate(db)
    latest = max(m.number for m in load_migrations())
    assert result.applied == tuple(range(8, latest + 1))


def test_before_0008_the_trust_fund_is_a_built_in_source(at_seven: DatabaseConnection) -> None:
    assert _sources(at_seven) == [
        ("DIRSA", 1, 1, None, None, None),
        ("OPCW_TRUST_FUND", 1, 1, None, None, None),
    ]


def test_0008_deletes_an_unused_trust_fund_and_adds_comaer(at_seven: DatabaseConnection) -> None:
    dirsa_entry = _add_entry(at_seven, source_id=_source_id(at_seven, "DIRSA"))
    removed_id = _source_id(at_seven, "OPCW_TRUST_FUND")
    _migrate_to_latest(at_seven)

    assert _sources(at_seven) == [
        ("COMAER", 1, 1, None, None, None),
        ("DIRSA", 1, 1, None, None, None),
    ]
    assert _count(at_seven, "budget_entry") == 1
    assert at_seven.execute("SELECT id FROM budget_entry").fetchone()[0] == dirsa_entry
    assert at_seven.execute("PRAGMA foreign_key_check").fetchall() == []
    # A fresh id: reusing the removed id would inherit its change_log history (P10-01).
    assert _source_id(at_seven, "COMAER") != removed_id


def test_0008_keeps_a_used_trust_fund_as_an_inactive_user_source(
    at_seven: DatabaseConnection,
) -> None:
    trust_fund = _source_id(at_seven, "OPCW_TRUST_FUND")
    entry_id = _add_entry(at_seven, source_id=trust_fund, description="Contribution")
    execution_id = _add_execution(at_seven, entry_id, amount_minor=7_000)
    _migrate_to_latest(at_seven)

    assert _sources(at_seven) == [
        ("COMAER", 1, 1, None, None, None),
        ("DIRSA", 1, 1, None, None, None),
        (
            "OPCW_TRUST_FUND",
            0,
            0,
            "Trust Fund da OPAQ",
            "OPCW Trust Fund",
            "Fondo Fiduciario de la OPAQ",
        ),
    ]
    assert _source_id(at_seven, "OPCW_TRUST_FUND") == trust_fund
    entry = at_seven.execute(
        "SELECT source_id, description FROM budget_entry WHERE id = ?", (entry_id,)
    ).fetchone()
    assert tuple(entry) == (trust_fund, "Contribution")
    execution = at_seven.execute(
        "SELECT entry_id, amount_minor FROM budget_execution WHERE id = ?", (execution_id,)
    ).fetchone()
    assert tuple(execution) == (entry_id, 7_000)
    assert at_seven.execute("PRAGMA foreign_key_check").fetchall() == []


def test_0008_promotes_an_existing_user_source_comaer(at_seven: DatabaseConnection) -> None:
    at_seven.execute(
        "INSERT INTO funding_source (code, built_in, active, label_pt_br) "
        "VALUES ('COMAER', 0, 0, 'Meu COMAER')"
    )
    comaer = _source_id(at_seven, "COMAER")
    entry_id = _add_entry(at_seven, source_id=comaer)
    _migrate_to_latest(at_seven)

    assert _sources(at_seven) == [
        ("COMAER", 1, 1, None, None, None),
        ("DIRSA", 1, 1, None, None, None),
    ]
    assert _source_id(at_seven, "COMAER") == comaer
    row = at_seven.execute(
        "SELECT source_id FROM budget_entry WHERE id = ?", (entry_id,)
    ).fetchone()
    assert row[0] == comaer
    assert at_seven.execute("PRAGMA foreign_key_check").fetchall() == []
