# SPDX-License-Identifier: GPL-3.0-or-later
"""Stock alerts (PLAN T11.8, D34, D35): each kind on, just inside and just outside its boundary."""

from __future__ import annotations

from datetime import date

import pytest

from cbrn_dashboard.domain.alerts import (
    SEVERITY_OF,
    Alert,
    AlertKind,
    Severity,
    SubjectKind,
    all_alerts,
    stock_alerts,
)
from cbrn_dashboard.domain.indicators import IndicatorRegistry, Module
from cbrn_dashboard.domain.infrastructure import InfrastructureRules
from cbrn_dashboard.domain.personnel import PersonnelRules
from cbrn_dashboard.domain.stock import (
    Lot,
    Movement,
    MovementKind,
    StockCategory,
    StockRules,
    StockType,
)

D = date(2026, 3, 5)
RULES = StockRules(expiry_warning_days=90)
ANTIDOTE = StockType(1, "ANTIDOTE_CHEMICAL", StockCategory.ANTIDOTE)
GLOVE = StockType(2, "GLOVE", StockCategory.PPE)


def _lot(lot_id: int, code: str, expires: date | None, type_code: str = "ANTIDOTE_CHEMICAL") -> Lot:
    return Lot(lot_id, type_code, code, expires)


def _move(move_id: int, lot_id: int, day: date, kind: MovementKind, quantity: int) -> Movement:
    return Movement(move_id, lot_id, day, kind, quantity)


def _receipt(lot_id: int, quantity: int, day: date = date(2025, 1, 10)) -> Movement:
    return _move(lot_id * 100, lot_id, day, MovementKind.RECEIPT, quantity)


def _alerts(
    types: list[StockType], lots: list[Lot], movements: list[Movement], d: date = D
) -> list[Alert]:
    return stock_alerts(types, lots, movements, d, RULES)


def test_the_kinds_and_their_severities() -> None:
    assert SEVERITY_OF[AlertKind.LOT_EXPIRED] is Severity.CRITICAL
    assert SEVERITY_OF[AlertKind.LOT_EXPIRING] is Severity.WARNING
    assert SEVERITY_OF[AlertKind.LOW_STOCK] is Severity.CRITICAL
    assert {SubjectKind.LOT.value, SubjectKind.ITEM_TYPE.value} == {"LOT", "ITEM_TYPE"}


def test_an_expired_lot_with_stock_is_critical_with_its_due_date() -> None:
    lots = [_lot(1, "L-1", date(2026, 3, 4))]  # expired yesterday: just outside validity
    [alert] = _alerts([ANTIDOTE], lots, [_receipt(1, 4)])

    assert alert == Alert(
        kind=AlertKind.LOT_EXPIRED,
        severity=Severity.CRITICAL,
        module=Module.STOCK,
        subject_kind=SubjectKind.LOT,
        subject_ref="L-1",
        subject_id=1,
        dimension="category=antidote;item=ANTIDOTE_CHEMICAL",
        due_on=date(2026, 3, 4),
        days_remaining=-1,
        value=4.0,
    )


def test_a_lot_expiring_today_is_expiring_not_expired() -> None:
    [alert] = _alerts([ANTIDOTE], [_lot(1, "L-1", D)], [_receipt(1, 4)])

    assert (alert.kind, alert.severity, alert.days_remaining) == (
        AlertKind.LOT_EXPIRING,
        Severity.WARNING,
        0,
    )


def test_the_expiring_window_is_inclusive_at_p11_days() -> None:
    inside = date(2026, 6, 3)  # D + 90
    outside = date(2026, 6, 4)  # D + 91
    lots = [_lot(1, "IN", inside), _lot(2, "OUT", outside)]
    found = _alerts([ANTIDOTE], lots, [_receipt(1, 1), _receipt(2, 1)])

    assert [(a.subject_ref, a.kind, a.days_remaining) for a in found] == [
        ("IN", AlertKind.LOT_EXPIRING, 90)
    ]


def test_the_window_follows_the_rules() -> None:
    lots = [_lot(1, "L-1", date(2026, 3, 20))]
    short = stock_alerts([ANTIDOTE], lots, [_receipt(1, 1)], D, StockRules(expiry_warning_days=10))
    wide = stock_alerts([ANTIDOTE], lots, [_receipt(1, 1)], D, StockRules(expiry_warning_days=15))

    assert short == []
    assert [a.kind for a in wide] == [AlertKind.LOT_EXPIRING]


def test_an_empty_a_not_received_and_a_no_expiry_lot_never_alert() -> None:
    lots = [
        _lot(1, "EMPTY", date(2026, 1, 1)),
        _lot(2, "FUTURE", date(2026, 1, 1)),
        _lot(3, "NOEXP", None),
    ]
    movements = [
        _receipt(1, 5),
        _move(150, 1, date(2025, 12, 1), MovementKind.DISPOSAL, 5),
        _receipt(2, 5, date(2026, 4, 1)),  # first received after the as-of date
        _receipt(3, 5),
    ]

    assert _alerts([ANTIDOTE], lots, movements) == []


def test_a_lot_has_at_most_one_alert() -> None:
    lots = [_lot(1, "A", date(2026, 1, 1)), _lot(2, "B", date(2026, 4, 1))]
    found = _alerts([ANTIDOTE], lots, [_receipt(1, 3), _receipt(2, 3)])

    assert sorted(a.subject_id or 0 for a in found) == [1, 2]
    assert {a.kind for a in found} == {AlertKind.LOT_EXPIRED, AlertKind.LOT_EXPIRING}


def test_a_lot_of_a_non_antidote_category_carries_its_category() -> None:
    [alert] = _alerts([GLOVE], [_lot(1, "G-1", date(2026, 1, 1), "GLOVE")], [_receipt(1, 2)])

    assert alert.dimension == "category=ppe;item=GLOVE"


def test_low_stock_is_critical_with_value_and_threshold_and_no_date() -> None:
    types = [StockType(1, "ANTIDOTE_CHEMICAL", StockCategory.ANTIDOTE, minimum_quantity=10)]
    lots = [_lot(1, "L-1", date(2027, 1, 1))]
    [alert] = _alerts(types, lots, [_receipt(1, 9)])  # 9 < 10: just below

    assert alert == Alert(
        kind=AlertKind.LOW_STOCK,
        severity=Severity.CRITICAL,
        module=Module.STOCK,
        subject_kind=SubjectKind.ITEM_TYPE,
        subject_ref="ANTIDOTE_CHEMICAL",
        subject_id=1,
        dimension="category=antidote;item=ANTIDOTE_CHEMICAL",
        due_on=None,
        days_remaining=None,
        value=9.0,
        threshold=10.0,
    )


def test_low_stock_is_strict_at_the_minimum() -> None:
    types = [StockType(1, "ANTIDOTE_CHEMICAL", StockCategory.ANTIDOTE, minimum_quantity=10)]
    lots = [_lot(1, "L-1", date(2027, 1, 1))]

    assert _alerts(types, lots, [_receipt(1, 10)]) == []
    assert _alerts(types, lots, [_receipt(1, 11)]) == []


def test_an_expired_quantity_is_not_valid_so_it_counts_towards_low_stock() -> None:
    types = [StockType(1, "ANTIDOTE_CHEMICAL", StockCategory.ANTIDOTE, minimum_quantity=5)]
    lots = [_lot(1, "OLD", date(2026, 1, 1))]
    found = _alerts(types, lots, [_receipt(1, 50)])

    assert {a.kind for a in found} == {AlertKind.LOT_EXPIRED, AlertKind.LOW_STOCK}
    [low] = [a for a in found if a.kind is AlertKind.LOW_STOCK]
    assert (low.value, low.threshold) == (0.0, 5.0)


def test_a_type_without_a_minimum_and_a_zero_minimum_never_give_low_stock() -> None:
    no_minimum = StockType(1, "ANTIDOTE_CHEMICAL", StockCategory.ANTIDOTE)
    zero = StockType(2, "GLOVE", StockCategory.PPE, minimum_quantity=0)

    assert _alerts([no_minimum, zero], [], []) == []


def test_an_inactive_type_never_gives_low_stock() -> None:
    types = [
        StockType(1, "ANTIDOTE_CHEMICAL", StockCategory.ANTIDOTE, minimum_quantity=10, active=False)
    ]

    assert _alerts(types, [], []) == []


def test_a_type_has_at_most_one_low_stock() -> None:
    types = [StockType(1, "ANTIDOTE_CHEMICAL", StockCategory.ANTIDOTE, minimum_quantity=10)]
    lots = [_lot(1, "A", date(2027, 1, 1)), _lot(2, "B", date(2027, 1, 1))]
    found = _alerts(types, lots, [_receipt(1, 2), _receipt(2, 3)])

    assert [a.kind for a in found] == [AlertKind.LOW_STOCK]
    assert found[0].value == 5.0


@pytest.mark.parametrize(
    ("as_of", "kinds"),
    [
        (date(2026, 3, 5), [AlertKind.LOT_EXPIRED]),  # expired 2026-01-01, stock on hand
        (date(2025, 12, 1), [AlertKind.LOT_EXPIRING]),  # inside the window, 31 days before
        (date(2025, 6, 1), []),  # received, far from the expiry
        (date(2025, 1, 9), []),  # before the first receipt: not received
    ],
)
def test_a_past_as_of_date_gives_the_alerts_of_that_date(
    as_of: date, kinds: list[AlertKind]
) -> None:
    found = _alerts([ANTIDOTE], [_lot(1, "L-1", date(2026, 1, 1))], [_receipt(1, 4)], as_of)

    assert [a.kind for a in found] == kinds


def test_all_alerts_has_stock_defaults_and_sorts_stock_with_the_rest() -> None:
    base = {
        "staff": [],
        "certs": [],
        "personnel_rules": PersonnelRules(),
        "assets": [],
        "asset_types": [],
        "status_events": [],
        "maintenance": [],
        "infrastructure_rules": InfrastructureRules(),
        "readings": [],
        "registry": IndicatorRegistry(),
        "d": D,
    }

    assert all_alerts(**base) == []  # type: ignore[arg-type]
    combined = all_alerts(
        **base,  # type: ignore[arg-type]
        stock_types=[ANTIDOTE],
        stock_lots=[_lot(1, "SOON", date(2026, 4, 1)), _lot(2, "OLD", date(2026, 1, 1))],
        stock_movements=[_receipt(1, 1), _receipt(2, 1)],
        stock_rules=RULES,
    )

    # critical first, then the warning; the due date orders inside a severity
    assert [(a.subject_ref, a.severity) for a in combined] == [
        ("OLD", Severity.CRITICAL),
        ("SOON", Severity.WARNING),
    ]
