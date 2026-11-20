# SPDX-License-Identifier: GPL-3.0-or-later
"""The stock indicators (PLAN.md T11.7, D35, D36, K22): definitions and the emission rule.

The expected numbers are worked out by hand from the fictitious dataset below (as of 2026-03-05,
P11 = 90 days, so the warning window ends on 2026-06-03, both ends inclusive).
"""

from datetime import date

from cbrn_dashboard.domain.indicators import Direction, Module, UnitKind
from cbrn_dashboard.domain.registry import build_registry
from cbrn_dashboard.domain.stock import (
    Lot,
    Movement,
    MovementKind,
    StockCategory,
    StockRules,
    StockType,
    indicator_definitions,
    indicator_values,
)

D = date(2026, 3, 5)
RULES = StockRules(expiry_warning_days=90)
RECEIVED = date(2026, 1, 1)

CHEMICAL = "ANTIDOTE_CHEMICAL"
BIOLOGICAL = "ANTIDOTE_BIOLOGICAL"
DECON = "DECONTAMINANT"


def _type(
    type_id: int,
    code: str,
    category: StockCategory,
    *,
    minimum: int | None = None,
    active: bool = True,
) -> StockType:
    return StockType(type_id, code, category, minimum, active)


def _lot(lot_id: int, code: str, expires_on: date | None) -> Lot:
    return Lot(lot_id, code, f"DEMO-L{lot_id:03d}", expires_on)


def _receipt(lot_id: int, quantity: int) -> Movement:
    return Movement(lot_id, lot_id, RECEIVED, MovementKind.RECEIPT, quantity)


def _dataset() -> tuple[list[StockType], list[Lot], list[Movement]]:
    types = [
        _type(1, CHEMICAL, StockCategory.ANTIDOTE),
        _type(2, BIOLOGICAL, StockCategory.ANTIDOTE, minimum=20),  # a minimum and no lot
        _type(3, DECON, StockCategory.DECONTAMINANT, active=False),  # inactive, still has stock
        _type(4, "DEMO-OLD", StockCategory.DECONTAMINANT, active=False),  # inactive, no stock
        _type(5, "DETECTOR_CHEMICAL", StockCategory.DETECTOR),  # active, unused, no minimum
    ]
    lots = [
        _lot(1, CHEMICAL, date(2026, 6, 3)),  # the last day of the window: expiring
        _lot(2, CHEMICAL, date(2026, 3, 4)),  # expired yesterday
        _lot(3, CHEMICAL, date(2026, 6, 4)),  # one day after the window: valid
        _lot(4, DECON, date(2027, 1, 1)),
    ]
    movements = [_receipt(1, 10), _receipt(2, 4), _receipt(3, 7), _receipt(4, 3)]
    return types, lots, movements


def test_the_four_definitions_follow_the_design() -> None:
    by_code = {item.code: item for item in indicator_definitions()}
    assert list(by_code) == [
        "STOCK_VALID_QTY",
        "STOCK_LOTS_EXPIRING",
        "STOCK_LOTS_EXPIRED",
        "STOCK_TYPES_BELOW_MIN",
    ]
    assert {item.module for item in by_code.values()} == {Module.STOCK}
    assert {item.unit for item in by_code.values()} == {UnitKind.COUNT}
    assert by_code["STOCK_VALID_QTY"].direction is Direction.HIGHER_IS_BETTER
    assert by_code["STOCK_VALID_QTY"].dimension_keys == ("category", "item")
    for code in ("STOCK_LOTS_EXPIRING", "STOCK_LOTS_EXPIRED", "STOCK_TYPES_BELOW_MIN"):
        assert by_code[code].direction is Direction.LOWER_IS_BETTER
        assert by_code[code].dimension_keys == ("category",)


def test_the_registry_holds_them_last_and_module_stock_is_the_last_member() -> None:
    codes = build_registry().codes()
    assert codes[-4:] == tuple(item.code for item in indicator_definitions())
    assert list(Module)[-1] is Module.STOCK


def test_the_values_match_the_hand_computed_numbers() -> None:
    types, lots, movements = _dataset()
    values = indicator_values(types, lots, movements, D, RULES)
    assert [(v.code, v.dimension, v.value) for v in values] == [
        ("STOCK_VALID_QTY", f"category=antidote;item={BIOLOGICAL}", 0.0),
        ("STOCK_VALID_QTY", f"category=antidote;item={CHEMICAL}", 17.0),
        ("STOCK_VALID_QTY", f"category=decontaminant;item={DECON}", 3.0),
        ("STOCK_LOTS_EXPIRING", "category=antidote", 1.0),
        ("STOCK_LOTS_EXPIRING", "category=decontaminant", 0.0),
        ("STOCK_LOTS_EXPIRED", "category=antidote", 1.0),
        ("STOCK_LOTS_EXPIRED", "category=decontaminant", 0.0),
        ("STOCK_TYPES_BELOW_MIN", "category=antidote", 1.0),
    ]


def test_the_context_of_the_valid_quantity_carries_the_minimum_only_when_set() -> None:
    types, lots, movements = _dataset()
    by_dimension = {
        v.dimension: v.context
        for v in indicator_values(types, lots, movements, D, RULES)
        if v.code == "STOCK_VALID_QTY"
    }
    assert by_dimension[f"category=antidote;item={CHEMICAL}"] == {
        "on_hand": 21.0,
        "expired": 4.0,
        "expiring": 10.0,
    }
    assert by_dimension[f"category=antidote;item={BIOLOGICAL}"] == {
        "on_hand": 0.0,
        "expired": 0.0,
        "expiring": 0.0,
        "minimum": 20.0,
    }
    assert by_dimension[f"category=decontaminant;item={DECON}"] == {
        "on_hand": 3.0,
        "expired": 0.0,
        "expiring": 0.0,
    }


def test_no_stock_gives_no_value_at_all() -> None:
    types, _, _ = _dataset()
    plain = [item for item in types if item.minimum_quantity is None and item.active]
    assert indicator_values(plain, [], [], D, RULES) == []
    assert indicator_values([], [], [], D, RULES) == []


def test_a_type_is_in_use_only_from_its_first_movement() -> None:
    types = [_type(1, CHEMICAL, StockCategory.ANTIDOTE)]
    lots = [_lot(1, CHEMICAL, date(2027, 1, 1))]
    movements = [Movement(1, 1, date(2026, 3, 6), MovementKind.RECEIPT, 5)]
    assert indicator_values(types, lots, movements, D, RULES) == []  # not yet received
    later = indicator_values(types, lots, movements, date(2026, 3, 6), RULES)
    assert [(v.code, v.value) for v in later] == [
        ("STOCK_VALID_QTY", 5.0),
        ("STOCK_LOTS_EXPIRING", 0.0),
        ("STOCK_LOTS_EXPIRED", 0.0),
    ]


def test_a_minimum_of_zero_is_counted_but_never_below() -> None:
    types = [_type(1, CHEMICAL, StockCategory.ANTIDOTE, minimum=0)]
    values = indicator_values(types, [], [], D, RULES)
    assert [(v.code, v.value) for v in values] == [
        ("STOCK_VALID_QTY", 0.0),
        ("STOCK_LOTS_EXPIRING", 0.0),
        ("STOCK_LOTS_EXPIRED", 0.0),
        ("STOCK_TYPES_BELOW_MIN", 0.0),
    ]


def test_the_minimum_is_strict_and_an_expired_lot_does_not_count_as_valid() -> None:
    types = [_type(1, CHEMICAL, StockCategory.ANTIDOTE, minimum=5)]
    lots = [_lot(1, CHEMICAL, date(2026, 3, 4)), _lot(2, CHEMICAL, date(2027, 1, 1))]
    movements = [_receipt(1, 9), _receipt(2, 5)]
    values = {v.code: v.value for v in indicator_values(types, lots, movements, D, RULES)}
    assert values["STOCK_VALID_QTY"] == 5.0  # the expired 9 are not valid
    assert values["STOCK_TYPES_BELOW_MIN"] == 0.0  # 5 is not below 5
    below = indicator_values(types, lots, [_receipt(1, 9), _receipt(2, 4)], D, RULES)
    assert {v.code: v.value for v in below}["STOCK_TYPES_BELOW_MIN"] == 1.0  # 4 is below 5


def test_an_inactive_type_with_a_minimum_is_not_counted_below() -> None:
    types = [
        _type(1, CHEMICAL, StockCategory.ANTIDOTE, minimum=50, active=False),
        _type(2, BIOLOGICAL, StockCategory.ANTIDOTE),
    ]
    lots = [_lot(1, CHEMICAL, date(2027, 1, 1))]
    values = indicator_values(types, lots, [_receipt(1, 2)], D, RULES)
    assert [v.code for v in values] == [
        "STOCK_VALID_QTY",
        "STOCK_LOTS_EXPIRING",
        "STOCK_LOTS_EXPIRED",
    ]
