# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the stock repository (PLAN.md T11.5); fictitious data only."""

from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.stock import Lot, Movement, MovementKind, StockCategory, StockType
from cbrn_dashboard.storage import stock_repo
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import (
    ConstraintViolationError,
    ForeignKeyError,
    RowNotFoundError,
    WriteContext,
)

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")
OPERATOR = "op-demo"


def _ctx(conn: DatabaseConnection) -> WriteContext:
    return WriteContext(conn, CLOCK, OPERATOR)


def _log(conn: DatabaseConnection) -> list[dict[str, object]]:
    cursor = conn.execute(
        "SELECT operator, entity, entity_id, action, before_json, after_json"
        " FROM change_log ORDER BY id"
    )
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _entities(conn: DatabaseConnection) -> Counter[tuple[object, object]]:
    return Counter((row["entity"], row["action"]) for row in _log(conn))


def _type(
    conn: DatabaseConnection,
    code: str = "DEMO-ITEM",
    category: str = "other",
    minimum_quantity: int | None = None,
) -> int:
    return stock_repo.insert_type(
        _ctx(conn),
        code=code,
        built_in=False,
        category=category,
        label_pt_br="Item demo",
        label_en_us=None,
        label_es_es=None,
        minimum_quantity=minimum_quantity,
        active=True,
    )


def _lot(
    conn: DatabaseConnection,
    type_id: int,
    code: str = "DEMO-L001",
    expires_on: str | None = None,
    price: int | None = None,
    currency: str | None = None,
) -> int:
    return stock_repo.insert_lot(
        _ctx(conn),
        type_id=type_id,
        lot_code=code,
        expires_on=expires_on,
        unit_price_minor=price,
        currency=currency,
        notes=None,
    )


def _movement(
    conn: DatabaseConnection,
    lot_id: int,
    moved_on: str = "2026-03-01",
    kind: str = "receipt",
    quantity: int = 10,
    reference: str = "",
) -> int:
    return stock_repo.insert_movement(
        _ctx(conn),
        lot_id=lot_id,
        moved_on=moved_on,
        kind=kind,
        quantity=quantity,
        reference=reference,
        note=None,
    )


# --------------------------------------------------------------------------- types


def test_the_seeded_types_are_read_ordered_by_code(migrated_db: DatabaseConnection) -> None:
    rows = stock_repo.list_types(migrated_db)

    assert len(rows) == 17
    assert [row.code for row in rows] == sorted(row.code for row in rows)
    glove = stock_repo.get_type_by_code(migrated_db, "GLOVE")
    assert glove is not None
    assert (glove.built_in, glove.category, glove.active) == (True, "ppe", True)
    assert (glove.label_pt_br, glove.minimum_quantity) == (None, None)
    assert stock_repo.get_type(migrated_db, glove.id) == glove
    assert stock_repo.get_type(migrated_db, 9999) is None
    assert stock_repo.get_type_by_code(migrated_db, "NO-SUCH") is None


def test_a_type_round_trips_and_is_logged(migrated_db: DatabaseConnection) -> None:
    type_id = _type(migrated_db, "DEMO-X", category="antidote", minimum_quantity=0)

    row = stock_repo.get_type(migrated_db, type_id)

    assert row is not None
    assert (row.code, row.built_in, row.category) == ("DEMO-X", False, "antidote")
    assert (row.label_pt_br, row.minimum_quantity, row.active) == ("Item demo", 0, True)
    log = _log(migrated_db)
    assert [(entry["entity"], entry["action"]) for entry in log] == [("stock_item_type", "insert")]
    assert log[0]["operator"] == OPERATOR
    assert log[0]["entity_id"] == type_id


def test_update_type_reports_whether_anything_changed(migrated_db: DatabaseConnection) -> None:
    type_id = _type(migrated_db)
    before = len(_log(migrated_db))

    def write(minimum: int | None, active: bool) -> bool:
        return stock_repo.update_type(
            _ctx(migrated_db),
            type_id,
            code="DEMO-ITEM",
            category="other",
            label_pt_br="Item demo",
            label_en_us=None,
            label_es_es=None,
            minimum_quantity=minimum,
            active=active,
        )

    assert write(None, True) is False
    assert len(_log(migrated_db)) == before
    assert write(7, False) is True

    row = stock_repo.get_type(migrated_db, type_id)
    assert row is not None
    assert (row.minimum_quantity, row.active) == (7, False)
    assert len(_log(migrated_db)) == before + 1
    active = stock_repo.list_types(migrated_db, include_inactive=False)
    active_codes = [item.code for item in active]
    assert "DEMO-ITEM" not in active_codes
    assert len(active_codes) == 17
    with pytest.raises(RowNotFoundError):
        stock_repo.update_type(
            _ctx(migrated_db),
            9999,
            code="X",
            category="other",
            label_pt_br="x",
            label_en_us=None,
            label_es_es=None,
            minimum_quantity=None,
            active=True,
        )


def test_a_duplicate_type_code_is_a_constraint_violation(migrated_db: DatabaseConnection) -> None:
    with pytest.raises(ConstraintViolationError):
        _type(migrated_db, "GLOVE")


def test_type_in_use_follows_the_lots_and_blocks_the_delete(
    migrated_db: DatabaseConnection,
) -> None:
    type_id = _type(migrated_db)
    assert stock_repo.type_in_use(migrated_db, type_id) is False
    _lot(migrated_db, type_id)

    assert stock_repo.type_in_use(migrated_db, type_id) is True
    log_size = len(_log(migrated_db))
    with pytest.raises(ForeignKeyError):
        stock_repo.delete_type(_ctx(migrated_db), type_id)
    assert len(_log(migrated_db)) == log_size


def test_delete_type_logs_one_row(migrated_db: DatabaseConnection) -> None:
    type_id = _type(migrated_db)

    assert stock_repo.delete_type(_ctx(migrated_db), type_id) == 1

    assert stock_repo.get_type(migrated_db, type_id) is None
    assert _entities(migrated_db) == Counter(
        {("stock_item_type", "insert"): 1, ("stock_item_type", "delete"): 1}
    )


# --------------------------------------------------------------------------- lots


def test_a_lot_round_trips_and_is_logged(migrated_db: DatabaseConnection) -> None:
    type_id = _type(migrated_db)
    lot_id = _lot(migrated_db, type_id, "DEMO-L001", "2027-05-31", 1250, "USD")

    row = stock_repo.get_lot(migrated_db, lot_id)

    assert row is not None
    assert (row.type_id, row.lot_code, row.expires_on) == (type_id, "DEMO-L001", "2027-05-31")
    assert (row.unit_price_minor, row.currency, row.notes) == (1250, "USD", None)
    assert stock_repo.get_lot_by_code(migrated_db, type_id, "DEMO-L001") == row
    assert stock_repo.get_lot_by_code(migrated_db, type_id, "OTHER") is None
    assert stock_repo.get_lot(migrated_db, 9999) is None
    assert ("stock_lot", "insert") in _entities(migrated_db)


def test_a_lot_without_expiry_or_price_stores_nulls(migrated_db: DatabaseConnection) -> None:
    lot_id = _lot(migrated_db, _type(migrated_db))

    row = stock_repo.get_lot(migrated_db, lot_id)

    assert row is not None
    assert (row.expires_on, row.unit_price_minor, row.currency) == (None, None, None)


def test_lot_constraints_surface_as_constraint_violations(
    migrated_db: DatabaseConnection,
) -> None:
    type_id = _type(migrated_db)
    _lot(migrated_db, type_id, "DEMO-L001")

    with pytest.raises(ConstraintViolationError):
        _lot(migrated_db, type_id, "DEMO-L001")  # same type and code
    with pytest.raises(ConstraintViolationError):
        _lot(migrated_db, type_id, "DEMO-L002", price=100)  # price without currency
    with pytest.raises(ConstraintViolationError):
        _lot(migrated_db, type_id, "DEMO-L003", expires_on="31/12/2027")
    with pytest.raises(ConstraintViolationError):
        _lot(migrated_db, 9999, "DEMO-L004")  # no such type
    assert len(stock_repo.list_lots(migrated_db)) == 1


def test_update_lot_logs_one_row_and_reports_a_no_op(migrated_db: DatabaseConnection) -> None:
    type_id = _type(migrated_db)
    lot_id = _lot(migrated_db, type_id)
    before = len(_log(migrated_db))

    def write(code: str, price: int | None, currency: str | None) -> bool:
        return stock_repo.update_lot(
            _ctx(migrated_db),
            lot_id,
            type_id=type_id,
            lot_code=code,
            expires_on=None,
            unit_price_minor=price,
            currency=currency,
            notes=None,
        )

    assert write("DEMO-L001", None, None) is False
    assert len(_log(migrated_db)) == before
    assert write("DEMO-L009", 300, "EUR") is True

    row = stock_repo.get_lot(migrated_db, lot_id)
    assert row is not None
    assert (row.lot_code, row.unit_price_minor, row.currency) == ("DEMO-L009", 300, "EUR")
    assert _log(migrated_db)[-1]["action"] == "update"
    assert len(_log(migrated_db)) == before + 1


def test_lots_are_listed_by_type_id_code_and_id_and_filtered_by_type(
    migrated_db: DatabaseConnection,
) -> None:
    first = _type(migrated_db, "DEMO-A")
    second = _type(migrated_db, "DEMO-B")
    b2 = _lot(migrated_db, second, "L-2")
    a2 = _lot(migrated_db, first, "L-2")
    a1 = _lot(migrated_db, first, "L-1")

    assert [row.id for row in stock_repo.list_lots(migrated_db)] == [a1, a2, b2]
    assert [row.id for row in stock_repo.list_lots(migrated_db, first)] == [a1, a2]
    assert [row.id for row in stock_repo.list_lots(migrated_db, second)] == [b2]
    assert stock_repo.list_lots(migrated_db, 9999) == []


def test_deleting_a_lot_logs_the_lot_and_each_movement(migrated_db: DatabaseConnection) -> None:
    type_id = _type(migrated_db)
    lot_id = _lot(migrated_db, type_id)
    other = _lot(migrated_db, type_id, "DEMO-L002")
    _movement(migrated_db, lot_id)
    _movement(migrated_db, lot_id, "2026-03-02", "issue", 3)
    _movement(migrated_db, lot_id, "2026-03-03", "loss", 1)
    kept = _movement(migrated_db, other)
    before = len(_log(migrated_db))

    assert stock_repo.delete_lot(_ctx(migrated_db), lot_id) == 4

    rows = _log(migrated_db)[before:]
    assert Counter((row["entity"], row["action"]) for row in rows) == Counter(
        {("stock_lot", "delete"): 1, ("stock_movement", "delete"): 3}
    )
    assert all(row["before_json"] and row["after_json"] is None for row in rows)
    assert stock_repo.get_lot(migrated_db, lot_id) is None
    assert stock_repo.list_movements(migrated_db, lot_id) == []
    assert [row.id for row in stock_repo.list_movements(migrated_db)] == [kept]
    with pytest.raises(RowNotFoundError):
        stock_repo.delete_lot(_ctx(migrated_db), lot_id)


def test_lot_in_use_follows_the_movements(migrated_db: DatabaseConnection) -> None:
    lot_id = _lot(migrated_db, _type(migrated_db))
    assert stock_repo.lot_in_use(migrated_db, lot_id) is False

    _movement(migrated_db, lot_id)

    assert stock_repo.lot_in_use(migrated_db, lot_id) is True


# --------------------------------------------------------------------------- movements


def test_a_movement_round_trips_and_is_logged(migrated_db: DatabaseConnection) -> None:
    lot_id = _lot(migrated_db, _type(migrated_db))

    movement_id = _movement(migrated_db, lot_id, "2026-02-20", "receipt", 12, "NF-1")

    row = stock_repo.get_movement(migrated_db, movement_id)
    assert row is not None
    assert (row.lot_id, row.moved_on, row.kind, row.quantity) == (
        lot_id,
        "2026-02-20",
        "receipt",
        12,
    )
    assert (row.reference, row.note) == ("NF-1", None)
    assert stock_repo.get_movement(migrated_db, 9999) is None
    assert ("stock_movement", "insert") in _entities(migrated_db)


def test_an_empty_reference_is_stored_as_an_empty_text_not_null(
    migrated_db: DatabaseConnection,
) -> None:
    lot_id = _lot(migrated_db, _type(migrated_db))

    row = stock_repo.get_movement(migrated_db, _movement(migrated_db, lot_id))

    assert row is not None
    assert row.reference == ""


def test_movement_constraints_surface_as_constraint_violations(
    migrated_db: DatabaseConnection,
) -> None:
    lot_id = _lot(migrated_db, _type(migrated_db))
    _movement(migrated_db, lot_id)

    with pytest.raises(ConstraintViolationError):
        _movement(migrated_db, lot_id)  # same lot, date, kind, quantity and reference
    with pytest.raises(ConstraintViolationError):
        _movement(migrated_db, lot_id, quantity=0)
    with pytest.raises(ConstraintViolationError):
        _movement(migrated_db, lot_id, kind="sale")
    with pytest.raises(ConstraintViolationError):
        _movement(migrated_db, 9999)
    assert len(stock_repo.list_movements(migrated_db)) == 1


def test_movements_are_listed_by_lot_date_and_id(migrated_db: DatabaseConnection) -> None:
    type_id = _type(migrated_db)
    first = _lot(migrated_db, type_id, "L-1")
    second = _lot(migrated_db, type_id, "L-2")
    late = _movement(migrated_db, first, "2026-03-04", "issue", 1)
    early = _movement(migrated_db, first, "2026-03-01")
    same_day = _movement(migrated_db, first, "2026-03-04", "loss", 1)
    other = _movement(migrated_db, second)

    assert [row.id for row in stock_repo.list_movements(migrated_db)] == [
        early,
        late,
        same_day,
        other,
    ]
    assert [row.id for row in stock_repo.list_movements(migrated_db, first)] == [
        early,
        late,
        same_day,
    ]
    assert [row.id for row in stock_repo.list_movements(migrated_db, second)] == [other]


# --------------------------------------------------------------------------- domain converters


def test_the_converters_build_the_domain_objects(migrated_db: DatabaseConnection) -> None:
    type_id = _type(migrated_db, "DEMO-X", category="decontaminant", minimum_quantity=5)
    lot_id = _lot(migrated_db, type_id, "DEMO-L001", "2027-05-31", 1250, "BRL")
    movement_id = _movement(migrated_db, lot_id, "2026-02-20", "adjustment_in", 4)
    type_row = stock_repo.get_type(migrated_db, type_id)
    lot_row = stock_repo.get_lot(migrated_db, lot_id)
    movement_row = stock_repo.get_movement(migrated_db, movement_id)
    assert type_row is not None
    assert lot_row is not None
    assert movement_row is not None

    assert stock_repo.type_to_domain(type_row) == StockType(
        id=type_id,
        code="DEMO-X",
        category=StockCategory.DECONTAMINANT,
        minimum_quantity=5,
        active=True,
    )
    assert stock_repo.lot_to_domain(lot_row, {type_id: "DEMO-X"}) == Lot(
        id=lot_id,
        type_code="DEMO-X",
        lot_code="DEMO-L001",
        expires_on=date(2027, 5, 31),
        unit_price_minor=1250,
        currency="BRL",
    )
    assert stock_repo.movement_to_domain(movement_row) == Movement(
        id=movement_id,
        lot_id=lot_id,
        moved_on=date(2026, 2, 20),
        kind=MovementKind.ADJUSTMENT_IN,
        quantity=4,
    )


def test_a_lot_of_an_unknown_type_code_and_without_expiry_converts(
    migrated_db: DatabaseConnection,
) -> None:
    type_id = _type(migrated_db)
    row = stock_repo.get_lot(migrated_db, _lot(migrated_db, type_id))
    assert row is not None

    lot = stock_repo.lot_to_domain(row, {})

    assert lot.type_code == f"#{type_id}"
    assert (lot.expires_on, lot.unit_price_minor, lot.currency) == (None, None, None)
