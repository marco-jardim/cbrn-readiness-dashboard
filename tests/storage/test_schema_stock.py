# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for migration 0009, the stock schema (PLAN.md T11.3, O01-O04, D33, A16).

The tests use the shared ``migrated_db`` fixture (a fresh database with every real migration
applied) and plain SQL. The data is fictitious.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from cbrn_dashboard.storage.migrate import load_migrations, migrate

STOCK_TABLES = ("stock_item_type", "stock_lot", "stock_movement")

# (code, category) of the 17 built-in types, in seed order (PLAN.md T11.3).
BUILT_IN_TYPES = (
    ("ANTIDOTE_CHEMICAL", "antidote"),
    ("ANTIDOTE_RAD_NUCLEAR", "antidote"),
    ("ANTIDOTE_BIOLOGICAL", "antidote"),
    ("DECONTAMINANT", "decontaminant"),
    ("DETECTOR_CHEMICAL", "detector"),
    ("DETECTOR_RAD_NUCLEAR", "detector"),
    ("DETECTOR_BIOLOGICAL", "detector"),
    ("MASK_FULL_FACE", "ppe"),
    ("FILTER_CBRN", "ppe"),
    ("PPE_LEVEL_A", "ppe"),
    ("PPE_LEVEL_B", "ppe"),
    ("PPE_LEVEL_C", "ppe"),
    ("GLOVE", "ppe"),
    ("BOOT", "ppe"),
    ("APRON", "ppe"),
    ("OXYGEN_CYLINDER", "other"),
    ("ISOLATION_STRETCHER", "other"),
)
KINDS = ("receipt", "issue", "disposal", "loss", "adjustment_in", "adjustment_out")
BAD_DATES = [
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
]


def _type_id(db: DatabaseConnection, code: str = "ANTIDOTE_CHEMICAL") -> int:
    row = db.execute("SELECT id FROM stock_item_type WHERE code = ?", (code,)).fetchone()
    assert row is not None
    return int(row[0])


def _add_type(
    db: DatabaseConnection,
    code: str = "DEMO_TYPE",
    category: str = "other",
    minimum_quantity: int | None = None,
) -> int:
    cursor = db.execute(
        "INSERT INTO stock_item_type (code, category, minimum_quantity) VALUES (?, ?, ?)",
        (code, category, minimum_quantity),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_lot(
    db: DatabaseConnection,
    *,
    type_id: int | None = None,
    lot_code: str = "DEMO-L001",
    expires_on: str | None = "2030-12-31",
    unit_price_minor: int | None = None,
    currency: str | None = None,
) -> int:
    owner = _type_id(db) if type_id is None else type_id
    cursor = db.execute(
        "INSERT INTO stock_lot (type_id, lot_code, expires_on, unit_price_minor, currency) "
        "VALUES (?, ?, ?, ?, ?)",
        (owner, lot_code, expires_on, unit_price_minor, currency),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _add_movement(
    db: DatabaseConnection,
    lot_id: int,
    *,
    moved_on: str = "2030-01-15",
    kind: str = "receipt",
    quantity: int = 10,
    reference: str | None = None,
) -> int:
    """Insert a movement; with ``reference=None`` the column default (empty string) applies."""
    if reference is None:
        cursor = db.execute(
            "INSERT INTO stock_movement (lot_id, moved_on, kind, quantity) VALUES (?, ?, ?, ?)",
            (lot_id, moved_on, kind, quantity),
        )
    else:
        cursor = db.execute(
            "INSERT INTO stock_movement (lot_id, moved_on, kind, quantity, reference) "
            "VALUES (?, ?, ?, ?, ?)",
            (lot_id, moved_on, kind, quantity, reference),
        )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _count(db: DatabaseConnection, table: str) -> int:
    row = db.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0])


# --------------------------------------------------------------------------- structure and seed


@pytest.mark.parametrize("table", STOCK_TABLES)
def test_tables_are_strict(migrated_db: DatabaseConnection, table: str) -> None:
    row = migrated_db.execute(
        "SELECT strict FROM pragma_table_list WHERE name = ?", (table,)
    ).fetchone()
    assert row is not None
    assert row[0] == 1


def test_there_is_no_stored_quantity_column(migrated_db: DatabaseConnection) -> None:
    """The quantity of a lot comes from its movements (D33), never from a column."""
    for table in ("stock_item_type", "stock_lot"):
        columns = {row[1] for row in migrated_db.execute(f"PRAGMA table_info({table})")}
        assert "quantity" not in columns
        assert "on_hand" not in columns


def test_the_lot_type_index_exists(migrated_db: DatabaseConnection) -> None:
    rows = migrated_db.execute("PRAGMA index_info(stock_lot_type_id_idx)").fetchall()
    assert [row[2] for row in rows] == ["type_id"]


def test_the_17_built_in_types_are_seeded(migrated_db: DatabaseConnection) -> None:
    rows = migrated_db.execute(
        "SELECT code, built_in, category, label_pt_br, label_en_us, label_es_es,"
        " minimum_quantity, active FROM stock_item_type ORDER BY id"
    ).fetchall()
    assert len(rows) == 17
    assert [(row[0], row[2]) for row in rows] == list(BUILT_IN_TYPES)
    for row in rows:
        assert row[1] == 1, row[0]
        assert row[3:7] == (None, None, None, None), row[0]
        assert row[7] == 1, row[0]


def test_built_in_codes_are_upper_snake_case(migrated_db: DatabaseConnection) -> None:
    for (code,) in migrated_db.execute("SELECT code FROM stock_item_type"):
        assert code == code.upper()
        assert " " not in code


def test_no_lot_or_movement_is_seeded(migrated_db: DatabaseConnection) -> None:
    assert _count(migrated_db, "stock_lot") == 0
    assert _count(migrated_db, "stock_movement") == 0


def test_the_migration_writes_no_change_log_row(migrated_db: DatabaseConnection) -> None:
    row = migrated_db.execute(
        "SELECT count(*) FROM change_log WHERE entity LIKE 'stock%'"
    ).fetchone()
    assert row[0] == 0


# --------------------------------------------------------------------------- stock_item_type


def test_user_type_defaults(migrated_db: DatabaseConnection) -> None:
    type_id = _add_type(migrated_db)
    row = migrated_db.execute(
        "SELECT built_in, active, minimum_quantity FROM stock_item_type WHERE id = ?", (type_id,)
    ).fetchone()
    assert tuple(row) == (0, 1, None)


def test_type_code_is_unique(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_type(migrated_db, "GLOVE")
    assert _count(migrated_db, "stock_item_type") == 17


@pytest.mark.parametrize("category", ["antidote", "decontaminant", "detector", "ppe", "other"])
def test_the_five_categories_are_accepted(migrated_db: DatabaseConnection, category: str) -> None:
    _add_type(migrated_db, category=category)
    assert _count(migrated_db, "stock_item_type") == 18


@pytest.mark.parametrize("category", ["", "vaccine", "Antidote", "PPE", "antidote ", "tools"])
def test_a_category_outside_the_five_is_rejected(
    migrated_db: DatabaseConnection, category: str
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_type(migrated_db, category=category)
    assert _count(migrated_db, "stock_item_type") == 17


def test_a_type_needs_a_category(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("INSERT INTO stock_item_type (code) VALUES ('DEMO_TYPE')")


@pytest.mark.parametrize("column", ["built_in", "active"])
def test_type_flags_accept_only_zero_and_one(migrated_db: DatabaseConnection, column: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            f"INSERT INTO stock_item_type (code, category, {column}) "
            "VALUES ('BAD_FLAG', 'other', 2)"
        )


@pytest.mark.parametrize("minimum", [None, 0, 1, 500])
def test_null_zero_and_positive_minimum_are_accepted(
    migrated_db: DatabaseConnection, minimum: int | None
) -> None:
    type_id = _add_type(migrated_db, minimum_quantity=minimum)
    row = migrated_db.execute(
        "SELECT minimum_quantity FROM stock_item_type WHERE id = ?", (type_id,)
    ).fetchone()
    assert row[0] == minimum


def test_a_negative_minimum_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_type(migrated_db, minimum_quantity=-1)
    assert _count(migrated_db, "stock_item_type") == 17


def test_a_negative_minimum_is_rejected_on_update(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("UPDATE stock_item_type SET minimum_quantity = -5 WHERE code = 'BOOT'")


def test_database_does_not_protect_unused_built_in_types(
    migrated_db: DatabaseConnection,
) -> None:
    """Protecting built-in types is a service rule, not a database rule."""
    migrated_db.execute("DELETE FROM stock_item_type WHERE code = 'APRON'")
    assert _count(migrated_db, "stock_item_type") == 16


def test_unused_user_type_can_be_deleted(migrated_db: DatabaseConnection) -> None:
    type_id = _add_type(migrated_db)
    migrated_db.execute("DELETE FROM stock_item_type WHERE id = ?", (type_id,))
    assert _count(migrated_db, "stock_item_type") == 17


def test_type_in_use_cannot_be_deleted(migrated_db: DatabaseConnection) -> None:
    type_id = _add_type(migrated_db)
    _add_lot(migrated_db, type_id=type_id)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("DELETE FROM stock_item_type WHERE id = ?", (type_id,))
    assert _count(migrated_db, "stock_item_type") == 18


def test_built_in_type_in_use_cannot_be_deleted(migrated_db: DatabaseConnection) -> None:
    _add_lot(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute("DELETE FROM stock_item_type WHERE code = 'ANTIDOTE_CHEMICAL'")
    assert _count(migrated_db, "stock_item_type") == 17


# --------------------------------------------------------------------------- stock_lot


def test_lot_without_expiry_price_or_currency_is_accepted(migrated_db: DatabaseConnection) -> None:
    lot_id = _add_lot(migrated_db, expires_on=None)
    row = migrated_db.execute(
        "SELECT expires_on, unit_price_minor, currency, notes FROM stock_lot WHERE id = ?",
        (lot_id,),
    ).fetchone()
    assert tuple(row) == (None, None, None, None)


def test_lot_with_unknown_type_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_lot(migrated_db, type_id=999_999)
    assert _count(migrated_db, "stock_lot") == 0


def test_lot_code_cannot_be_null(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO stock_lot (type_id, lot_code) VALUES (?, NULL)", (_type_id(migrated_db),)
        )


def test_duplicate_type_and_lot_code_is_rejected(migrated_db: DatabaseConnection) -> None:
    _add_lot(migrated_db, lot_code="DEMO-L001")
    with pytest.raises(sqlite3.IntegrityError):
        _add_lot(migrated_db, lot_code="DEMO-L001", expires_on="2031-01-31")
    assert _count(migrated_db, "stock_lot") == 1


def test_same_lot_code_on_another_type_is_accepted(migrated_db: DatabaseConnection) -> None:
    chemical = _type_id(migrated_db, "ANTIDOTE_CHEMICAL")
    biological = _type_id(migrated_db, "ANTIDOTE_BIOLOGICAL")
    _add_lot(migrated_db, type_id=chemical)
    _add_lot(migrated_db, type_id=biological)
    _add_lot(migrated_db, type_id=biological, lot_code="DEMO-L002")
    assert _count(migrated_db, "stock_lot") == 3


@pytest.mark.parametrize("day", ["2030-12-31", "1900-01-01", "2200-12-31"])
def test_expiry_date_of_iso_shape_is_accepted(migrated_db: DatabaseConnection, day: str) -> None:
    _add_lot(migrated_db, expires_on=day)
    assert _count(migrated_db, "stock_lot") == 1


@pytest.mark.parametrize("day", BAD_DATES)
def test_expiry_date_of_another_shape_is_rejected(
    migrated_db: DatabaseConnection, day: str
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_lot(migrated_db, expires_on=day)
    assert _count(migrated_db, "stock_lot") == 0


@pytest.mark.parametrize("price", [0, 1, 12_345])
def test_price_with_currency_is_accepted(migrated_db: DatabaseConnection, price: int) -> None:
    lot_id = _add_lot(migrated_db, unit_price_minor=price, currency="BRL")
    row = migrated_db.execute(
        "SELECT unit_price_minor, currency FROM stock_lot WHERE id = ?", (lot_id,)
    ).fetchone()
    assert tuple(row) == (price, "BRL")


def test_negative_price_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_lot(migrated_db, unit_price_minor=-1, currency="BRL")
    assert _count(migrated_db, "stock_lot") == 0


def test_price_without_currency_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_lot(migrated_db, unit_price_minor=100, currency=None)
    assert _count(migrated_db, "stock_lot") == 0


def test_currency_without_price_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_lot(migrated_db, unit_price_minor=None, currency="BRL")
    assert _count(migrated_db, "stock_lot") == 0


@pytest.mark.parametrize("currency", ["", "B", "BR", "BRLX", "BRL ", "brl", "Brl", "B2L", "123"])
def test_bad_currency_is_rejected(migrated_db: DatabaseConnection, currency: str) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_lot(migrated_db, unit_price_minor=100, currency=currency)
    assert _count(migrated_db, "stock_lot") == 0


def test_currency_allow_list_is_not_a_database_rule(migrated_db: DatabaseConnection) -> None:
    """Any ISO 4217 shaped code is stored; the allow-list is a service rule (D15)."""
    _add_lot(migrated_db, unit_price_minor=100, currency="CHF")
    assert _count(migrated_db, "stock_lot") == 1


def test_price_above_2_pow_53_round_trips_exactly(migrated_db: DatabaseConnection) -> None:
    big = 9_007_199_254_740_993  # 2**53 + 1: not exactly representable as a float
    lot_id = _add_lot(migrated_db, unit_price_minor=big, currency="USD")
    value = migrated_db.execute(
        "SELECT unit_price_minor FROM stock_lot WHERE id = ?", (lot_id,)
    ).fetchone()[0]
    assert isinstance(value, int)
    assert value == big


# --------------------------------------------------------------------------- stock_movement


@pytest.mark.parametrize("kind", KINDS)
def test_the_six_kinds_are_accepted(migrated_db: DatabaseConnection, kind: str) -> None:
    lot_id = _add_lot(migrated_db)
    _add_movement(migrated_db, lot_id, kind=kind)
    assert _count(migrated_db, "stock_movement") == 1


@pytest.mark.parametrize("kind", ["", "transfer", "Receipt", "ISSUE", "adjustment", "receipt "])
def test_a_kind_outside_the_six_is_rejected(migrated_db: DatabaseConnection, kind: str) -> None:
    lot_id = _add_lot(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        _add_movement(migrated_db, lot_id, kind=kind)
    assert _count(migrated_db, "stock_movement") == 0


@pytest.mark.parametrize("quantity", [0, -1, -100])
def test_a_quantity_of_zero_or_less_is_rejected(
    migrated_db: DatabaseConnection, quantity: int
) -> None:
    lot_id = _add_lot(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        _add_movement(migrated_db, lot_id, quantity=quantity)
    assert _count(migrated_db, "stock_movement") == 0


def test_a_quantity_of_one_is_accepted(migrated_db: DatabaseConnection) -> None:
    lot_id = _add_lot(migrated_db)
    _add_movement(migrated_db, lot_id, quantity=1)
    assert _count(migrated_db, "stock_movement") == 1


@pytest.mark.parametrize("day", ["2030-01-15", "1900-01-01", "2200-12-31"])
def test_movement_date_of_iso_shape_is_accepted(migrated_db: DatabaseConnection, day: str) -> None:
    lot_id = _add_lot(migrated_db)
    _add_movement(migrated_db, lot_id, moved_on=day)
    assert _count(migrated_db, "stock_movement") == 1


@pytest.mark.parametrize("day", BAD_DATES)
def test_movement_date_of_another_shape_is_rejected(
    migrated_db: DatabaseConnection, day: str
) -> None:
    lot_id = _add_lot(migrated_db)
    with pytest.raises(sqlite3.IntegrityError):
        _add_movement(migrated_db, lot_id, moved_on=day)
    assert _count(migrated_db, "stock_movement") == 0


def test_movement_with_unknown_lot_is_rejected(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _add_movement(migrated_db, 999_999)
    assert _count(migrated_db, "stock_movement") == 0


def test_reference_defaults_to_the_empty_string_and_cannot_be_null(
    migrated_db: DatabaseConnection,
) -> None:
    lot_id = _add_lot(migrated_db)
    movement_id = _add_movement(migrated_db, lot_id)
    row = migrated_db.execute(
        "SELECT reference FROM stock_movement WHERE id = ?", (movement_id,)
    ).fetchone()
    assert row[0] == ""
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO stock_movement (lot_id, moved_on, kind, quantity, reference) "
            "VALUES (?, '2030-02-01', 'issue', 1, NULL)",
            (lot_id,),
        )


def test_duplicate_movement_key_is_rejected(migrated_db: DatabaseConnection) -> None:
    lot_id = _add_lot(migrated_db)
    _add_movement(migrated_db, lot_id, reference="DEMO-REF-1")
    with pytest.raises(sqlite3.IntegrityError):
        _add_movement(migrated_db, lot_id, reference="DEMO-REF-1")
    assert _count(migrated_db, "stock_movement") == 1


def test_duplicate_movement_key_without_reference_is_rejected(
    migrated_db: DatabaseConnection,
) -> None:
    lot_id = _add_lot(migrated_db)
    _add_movement(migrated_db, lot_id)
    with pytest.raises(sqlite3.IntegrityError):
        _add_movement(migrated_db, lot_id)
    with pytest.raises(sqlite3.IntegrityError):
        _add_movement(migrated_db, lot_id, reference="")
    assert _count(migrated_db, "stock_movement") == 1


def test_movement_key_differing_in_one_part_is_accepted(migrated_db: DatabaseConnection) -> None:
    lot_id = _add_lot(migrated_db)
    other_lot = _add_lot(migrated_db, lot_code="DEMO-L002")
    _add_movement(migrated_db, lot_id)
    _add_movement(migrated_db, lot_id, moved_on="2030-01-16")
    _add_movement(migrated_db, lot_id, kind="adjustment_in")
    _add_movement(migrated_db, lot_id, quantity=11)
    _add_movement(migrated_db, lot_id, reference="DEMO-REF-1")
    _add_movement(migrated_db, other_lot)
    assert _count(migrated_db, "stock_movement") == 6


def test_note_is_not_part_of_the_movement_key(migrated_db: DatabaseConnection) -> None:
    lot_id = _add_lot(migrated_db)
    _add_movement(migrated_db, lot_id)
    with pytest.raises(sqlite3.IntegrityError):
        migrated_db.execute(
            "INSERT INTO stock_movement (lot_id, moved_on, kind, quantity, note) "
            "VALUES (?, '2030-01-15', 'receipt', 10, 'another note')",
            (lot_id,),
        )


def test_deleting_a_lot_deletes_its_movements(migrated_db: DatabaseConnection) -> None:
    doomed = _add_lot(migrated_db, lot_code="DEMO-L001")
    kept = _add_lot(migrated_db, lot_code="DEMO-L002")
    _add_movement(migrated_db, doomed, moved_on="2030-01-15")
    _add_movement(migrated_db, doomed, moved_on="2030-02-15", kind="issue", quantity=3)
    kept_movement = _add_movement(migrated_db, kept)

    migrated_db.execute("DELETE FROM stock_lot WHERE id = ?", (doomed,))

    remaining = [row[0] for row in migrated_db.execute("SELECT id FROM stock_movement")]
    assert remaining == [kept_movement]
    assert _count(migrated_db, "stock_lot") == 1


def test_foreign_key_check_is_clean(migrated_db: DatabaseConnection) -> None:
    lot_id = _add_lot(migrated_db)
    _add_movement(migrated_db, lot_id)
    assert migrated_db.execute("PRAGMA foreign_key_check").fetchall() == []


# --------------------------------------------------------------------------- upgrade from 0008


@pytest.fixture
def at_eight(tmp_path: Path) -> Iterator[DatabaseConnection]:
    """A database migrated only up to 0008, with fictitious rows in existing tables."""
    conn = open_database(tmp_path / "before-0009.sqlite3")
    try:
        migrate(conn, migrations=load_migrations()[:8])
        yield conn
    finally:
        conn.close()


def _snapshot(db: DatabaseConnection) -> dict[str, list[tuple[object, ...]]]:
    """Every row of the tables that exist before 0009, in a stable order."""
    names = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND name NOT LIKE 'stock_%' ORDER BY name"
        )
    ]
    return {
        name: [tuple(row) for row in db.execute(f"SELECT * FROM {name} ORDER BY 1")]
        for name in names
    }


def test_upgrade_from_8_leaves_existing_rows_untouched(at_eight: DatabaseConnection) -> None:
    source = int(
        at_eight.execute("SELECT id FROM funding_source WHERE code = 'DIRSA'").fetchone()[0]
    )
    entry = at_eight.execute(
        "INSERT INTO budget_entry "
        "(fiscal_year, source_id, currency, allocated_minor, description) "
        "VALUES (2030, ?, 'BRL', 100000, 'Demo training')",
        (source,),
    ).lastrowid
    at_eight.execute(
        "INSERT INTO budget_execution (entry_id, executed_on, amount_minor) "
        "VALUES (?, '2030-03-31', 5000)",
        (entry,),
    )
    bed = int(at_eight.execute("SELECT id FROM asset_type WHERE code = 'bed'").fetchone()[0])
    at_eight.execute(
        "INSERT INTO asset (type_id, tag, in_service_from) VALUES (?, 'DEMO-A001', '2025-01-01')",
        (bed,),
    )
    at_eight.execute(
        "INSERT INTO funding_source (code, built_in, label_pt_br) "
        "VALUES ('DEMO_FUND', 0, 'Fonte de demonstracao')"
    )
    before = _snapshot(at_eight)
    assert before["budget_entry"] and before["asset"] and before["funding_source"]
    tables_before = {
        row[0] for row in at_eight.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert not {name for name in tables_before if name.startswith("stock_")}

    result = migrate(at_eight)

    assert result.from_version == 8
    assert result.applied[:1] == (9,)
    assert at_eight.execute("PRAGMA user_version").fetchone()[0] == result.to_version
    assert _snapshot(at_eight) == before
    assert _count(at_eight, "stock_item_type") == 17
    assert _count(at_eight, "stock_lot") == 0
    assert _count(at_eight, "stock_movement") == 0
    assert at_eight.execute("PRAGMA foreign_key_check").fetchall() == []


def test_upgrade_from_8_with_empty_tables_seeds_the_types(at_eight: DatabaseConnection) -> None:
    migrate(at_eight)
    codes = [row[0] for row in at_eight.execute("SELECT code FROM stock_item_type ORDER BY id")]
    assert codes == [code for code, _ in BUILT_IN_TYPES]


def test_the_latest_version_is_at_least_9() -> None:
    assert max(m.number for m in load_migrations()) >= 9
