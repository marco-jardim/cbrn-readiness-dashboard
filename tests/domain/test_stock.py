# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for ``cbrn_dashboard.domain.stock`` (PLAN T11.4, D33 to D35, P11, P12).

Every test uses fixed dates: the as-of date ``D`` is passed in, and the module has no clock.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from datetime import date, timedelta

import pytest

from cbrn_dashboard.domain.dates import add_months
from cbrn_dashboard.domain.stock import (
    ANTIDOTE_PAGE_CATEGORIES,
    CATEGORY_ORDER,
    EXPIRY_REQUIRED_CATEGORIES,
    MAX_SCHEDULE_MONTHS,
    SIGN,
    CurrencyValue,
    Lot,
    LotRow,
    LotStatus,
    Movement,
    MovementKind,
    ScheduleBucketKind,
    ScheduleTypeQuantity,
    StockCategory,
    StockDataError,
    StockRules,
    StockType,
    TypeSummary,
    expiry_schedule,
    first_negative_day,
    lot_rows,
    lot_status,
    quantity_on,
    stock_value,
    type_summaries,
    valid_quantity,
    validity,
)

D = date(2026, 11, 20)
RULES = StockRules()

R = MovementKind.RECEIPT
ISSUE = MovementKind.ISSUE
DISPOSAL = MovementKind.DISPOSAL
LOSS = MovementKind.LOSS
ADJ_IN = MovementKind.ADJUSTMENT_IN
ADJ_OUT = MovementKind.ADJUSTMENT_OUT

CHEM = "ANTIDOTE_CHEMICAL"
DECON = "DECONTAMINANT"
GLOVE = "GLOVE"
O2 = "OXYGEN_CYLINDER"

_IDS = itertools.count(1)


def day(offset: int, base: date = D) -> date:
    """The date ``offset`` days from ``base`` (negative: before)."""
    return base + timedelta(days=offset)


def mv(lot_id: int, offset: int, kind: MovementKind, quantity: int, base: date = D) -> Movement:
    return Movement(next(_IDS), lot_id, day(offset, base), kind, quantity)


def make_lot(
    lot_id: int,
    type_code: str = CHEM,
    lot_code: str = "L",
    expires_on: date | None = None,
    price: int | None = None,
    currency: str | None = None,
) -> Lot:
    return Lot(lot_id, type_code, lot_code, expires_on, price, currency)


def types(minimum: int | None = None) -> tuple[StockType, ...]:
    """One type per category, deliberately not in display order."""
    return (
        StockType(3, GLOVE, StockCategory.PPE),
        StockType(1, CHEM, StockCategory.ANTIDOTE, minimum),
        StockType(4, O2, StockCategory.OTHER),
        StockType(2, DECON, StockCategory.DECONTAMINANT),
    )


# --------------------------------------------------------------------------- enums and constants


def test_enums_and_constants() -> None:
    assert [c.value for c in StockCategory] == [
        "antidote",
        "decontaminant",
        "detector",
        "ppe",
        "other",
    ]
    assert tuple(StockCategory) == CATEGORY_ORDER
    assert [k.value for k in MovementKind] == [
        "receipt",
        "issue",
        "disposal",
        "loss",
        "adjustment_in",
        "adjustment_out",
    ]
    assert {s.value for s in LotStatus} == {
        "VALID",
        "EXPIRING",
        "EXPIRED",
        "EMPTY",
        "NOT_RECEIVED",
    }
    both = frozenset({StockCategory.ANTIDOTE, StockCategory.DECONTAMINANT})
    assert both == ANTIDOTE_PAGE_CATEGORIES
    assert both == EXPIRY_REQUIRED_CATEGORIES
    assert StockRules().expiry_warning_days == 90
    assert StockRules(expiry_warning_days=7).expiry_warning_days == 7
    assert MAX_SCHEDULE_MONTHS == 60


@pytest.mark.parametrize(
    ("kind", "sign"),
    [
        (MovementKind.RECEIPT, 1),
        (MovementKind.ADJUSTMENT_IN, 1),
        (MovementKind.ISSUE, -1),
        (MovementKind.DISPOSAL, -1),
        (MovementKind.LOSS, -1),
        (MovementKind.ADJUSTMENT_OUT, -1),
    ],
)
def test_sign_of_each_kind(kind: MovementKind, sign: int) -> None:
    assert SIGN[kind] == sign
    assert set(SIGN) == set(MovementKind)


# --------------------------------------------------------------------------- quantity_on


def _signed_sum_movements() -> list[Movement]:
    return [
        mv(1, -10, R, 10),
        mv(1, -5, ISSUE, 3),
        mv(1, 0, LOSS, 1),  # on d: counts
        mv(1, 0, ADJ_IN, 4),  # on d: counts
        mv(1, 1, R, 100),  # after d: ignored
        mv(2, -1, R, 7),  # another lot
        mv(1, -20, ADJ_OUT, 2),  # backdated outflow before the receipt
    ]


@pytest.mark.parametrize(
    ("offset", "lot_id", "expected"),
    [
        (-21, 1, 0),  # before everything
        (-20, 1, -2),  # the backdated outflow alone: negative on that day
        (-11, 1, -2),
        (-10, 1, 8),  # a receipt on d counts
        (-5, 1, 5),
        (-1, 1, 5),
        (0, 1, 5 - 1 + 4),  # loss and adjustment in on d count
        (1, 1, 108),  # a movement dated after the old d counts on the new d
        (0, 2, 7),
        (-2, 2, 0),
        (0, 3, 0),  # a lot without movements
    ],
)
def test_quantity_on_sums_signed_movements_up_to_and_including_d(
    offset: int, lot_id: int, expected: int
) -> None:
    assert quantity_on(_signed_sum_movements(), lot_id, day(offset)) == expected


def test_quantity_on_of_nothing_is_zero() -> None:
    assert quantity_on([], 1, D) == 0


# --------------------------------------------------------------------------- first_negative_day


@pytest.mark.parametrize(
    ("movements", "expected"),
    [
        pytest.param([], None, id="no-movements"),
        pytest.param([mv(1, -10, R, 10), mv(1, -5, ISSUE, 10)], None, id="down-to-zero"),
        pytest.param(
            [mv(1, -10, R, 10), mv(1, -5, ISSUE, 6), mv(1, -3, ISSUE, 5)],
            day(-3),
            id="outflow-after-receipt",
        ),
        pytest.param(
            # backdating an issue before the receipt makes the balance negative on that day
            [mv(1, -10, R, 10), mv(1, -5, ISSUE, 4), mv(1, -20, ISSUE, 8)],
            day(-20),
            id="backdated-outflow",
        ),
        pytest.param(
            # the order inside one day is ignored: the issue listed first does not matter
            [mv(1, -5, ISSUE, 5), mv(1, -5, R, 5)],
            None,
            id="same-day-order-ignored",
        ),
        pytest.param(
            [mv(1, -5, ISSUE, 6), mv(1, -5, R, 5)],
            day(-5),
            id="same-day-net-negative",
        ),
        pytest.param(
            # not in date order on purpose: the totals are taken in ascending date order
            [mv(1, 0, ISSUE, 4), mv(1, -9, R, 2), mv(1, -4, R, 2), mv(1, -2, LOSS, 1)],
            day(0),
            id="unsorted-input",
        ),
        pytest.param(
            [
                mv(1, -9, R, 3),
                mv(1, -4, ADJ_OUT, 3),
                mv(1, -2, ADJ_IN, 1),
                mv(1, -1, DISPOSAL, 1),
            ],
            None,
            id="all-kinds-balanced",
        ),
        pytest.param(
            # lots are balanced separately: lot 2 is negative on day -3, lot 1 on day -2
            [
                mv(1, -9, R, 1),
                mv(1, -2, ISSUE, 2),
                mv(2, -9, R, 1),
                mv(2, -3, ISSUE, 2),
            ],
            day(-3),
            id="two-lots-earliest",
        ),
        pytest.param(
            # one lot's surplus does not cover another lot's outflow
            [mv(1, -9, R, 100), mv(2, -9, R, 1), mv(2, -1, ISSUE, 2)],
            day(-1),
            id="lots-do-not-cover-each-other",
        ),
    ],
)
def test_first_negative_day(movements: list[Movement], expected: date | None) -> None:
    assert first_negative_day(movements) == expected


# --------------------------------------------------------------------------- validity


@pytest.mark.parametrize(
    ("expiry_offset", "expected"),
    [
        (None, True),  # no expiry date: valid
        (-1, False),
        (0, True),  # expires on d: still valid on d
        (1, True),
        (400, True),
    ],
)
def test_validity_and_valid_quantity(expiry_offset: int | None, expected: bool) -> None:
    expires_on = None if expiry_offset is None else day(expiry_offset)
    lot = make_lot(1, expires_on=expires_on)
    movements = [mv(1, -30, R, 10), mv(1, 5, ISSUE, 10)]  # the issue is after d
    assert validity(lot, D) is expected
    assert valid_quantity(lot, movements, D) == (10 if expected else 0)


def test_valid_quantity_of_a_lot_not_yet_received_is_zero() -> None:
    lot = make_lot(1, expires_on=day(30))
    assert valid_quantity(lot, [mv(1, 1, R, 10)], D) == 0
    assert valid_quantity(lot, [], D) == 0


# --------------------------------------------------------------------------- status


STATUS_CASES = [
    pytest.param([], -30, LotStatus.NOT_RECEIVED, id="no-movement-beats-expired"),
    pytest.param([(1, R, 5)], 400, LotStatus.NOT_RECEIVED, id="only-future-movement"),
    pytest.param([(-100, R, 5), (-50, ISSUE, 5)], -10, LotStatus.EMPTY, id="empty-beats-expired"),
    pytest.param([(-100, R, 5), (-50, ISSUE, 5)], 10, LotStatus.EMPTY, id="empty-beats-expiring"),
    pytest.param([(-100, R, 5), (-50, DISPOSAL, 5)], None, LotStatus.EMPTY, id="empty-no-expiry"),
    pytest.param([(-10, R, 5)], -1, LotStatus.EXPIRED, id="expired-the-day-before"),
    pytest.param([(-10, R, 5)], 0, LotStatus.EXPIRING, id="expires-exactly-on-d"),
    pytest.param([(-10, R, 5)], 1, LotStatus.EXPIRING, id="expires-the-day-after"),
    pytest.param([(-10, R, 5)], 90, LotStatus.EXPIRING, id="expires-on-d-plus-p11"),
    pytest.param([(-10, R, 5)], 91, LotStatus.VALID, id="one-day-after-the-window"),
    pytest.param([(-10, R, 5)], None, LotStatus.VALID, id="no-expiry-date"),
    pytest.param([(-10, R, 5)], 400, LotStatus.VALID, id="far-expiry"),
    pytest.param([(0, R, 5)], 400, LotStatus.VALID, id="receipt-on-d-counts"),
    pytest.param([(-10, R, 5), (1, ISSUE, 5)], 400, LotStatus.VALID, id="later-outflow-ignored"),
    pytest.param([(-10, R, 5), (0, ISSUE, 5)], 400, LotStatus.EMPTY, id="outflow-on-d-counts"),
    pytest.param([(0, ADJ_IN, 2)], 400, LotStatus.VALID, id="adjustment-in-only"),
]


@pytest.mark.parametrize(("spec", "expiry_offset", "expected"), STATUS_CASES)
def test_status_order(
    spec: list[tuple[int, MovementKind, int]], expiry_offset: int | None, expected: LotStatus
) -> None:
    expires_on = None if expiry_offset is None else day(expiry_offset)
    lot = make_lot(1, expires_on=expires_on)
    movements = [mv(1, offset, kind, quantity) for offset, kind, quantity in spec]
    assert lot_status(lot, movements, D, RULES) is expected
    (row,) = lot_rows(types(), [lot], movements, D, RULES)
    assert row.status is expected


@pytest.mark.parametrize(
    ("window", "expiry_offset", "expected"),
    [
        (0, -1, LotStatus.EXPIRED),
        (0, 0, LotStatus.EXPIRING),
        (0, 1, LotStatus.VALID),
        (30, 30, LotStatus.EXPIRING),
        (30, 31, LotStatus.VALID),
        (365, 365, LotStatus.EXPIRING),
        (365, 366, LotStatus.VALID),
    ],
)
def test_the_window_is_the_p11_setting(
    window: int, expiry_offset: int, expected: LotStatus
) -> None:
    lot = make_lot(1, expires_on=day(expiry_offset))
    movements = [mv(1, -10, R, 5)]
    assert lot_status(lot, movements, D, StockRules(expiry_warning_days=window)) is expected


def test_status_ignores_the_movements_of_other_lots() -> None:
    lot = make_lot(1, expires_on=day(400))
    other = [mv(2, -10, R, 5)]
    assert lot_status(lot, other, D, RULES) is LotStatus.NOT_RECEIVED


def test_status_of_a_past_date_uses_the_movements_known_by_then() -> None:
    lot = make_lot(1, expires_on=day(100))
    movements = [mv(1, -10, R, 5)]
    assert lot_status(lot, movements, day(-30), RULES) is LotStatus.NOT_RECEIVED
    assert lot_status(lot, movements, day(-11), RULES) is LotStatus.NOT_RECEIVED
    assert lot_status(lot, movements, day(-10), RULES) is LotStatus.VALID  # 110 days to go
    assert lot_status(lot, movements, day(9), RULES) is LotStatus.VALID  # 91 days to go
    assert lot_status(lot, movements, day(10), RULES) is LotStatus.EXPIRING  # 90 days to go
    assert lot_status(lot, movements, day(100), RULES) is LotStatus.EXPIRING  # on the day
    assert lot_status(lot, movements, day(101), RULES) is LotStatus.EXPIRED


# --------------------------------------------------------------------------- lot_rows


def _lots_and_movements() -> tuple[list[Lot], list[Movement]]:
    """The lots of the demo data (design section 7), listed out of order on purpose."""
    lots = [
        make_lot(5, CHEM, "DEMO-L005"),
        make_lot(8, O2, "O2-1"),
        make_lot(1, CHEM, "DEMO-L001", day(400), 1500, "BRL"),
        make_lot(4, CHEM, "DEMO-L004", day(-100)),
        make_lot(7, GLOVE, "G-1"),
        make_lot(2, CHEM, "DEMO-L002", day(20)),
        make_lot(6, DECON, "DEC-1", day(10), 200, "USD"),
        make_lot(9, CHEM, "A-LOT", day(20)),
        make_lot(3, CHEM, "DEMO-L003", day(-15)),
    ]
    movements = [
        mv(1, -200, R, 50),
        mv(1, -30, ISSUE, 5),
        mv(2, -100, R, 10),
        mv(3, -300, R, 4),
        mv(4, -400, R, 10),
        mv(4, -50, DISPOSAL, 10),
        mv(5, -10, R, 3),
        mv(6, -5, R, 2),
        mv(7, -3, ADJ_IN, 5),  # adjustment only: no receipt date
        mv(8, -10, R, 4),
        mv(9, -1, R, 1),
    ]
    return lots, movements


def test_lot_rows_are_sorted_by_category_type_expiry_and_lot_code() -> None:
    lots, movements = _lots_and_movements()
    rows = lot_rows(types(), lots, movements, D, RULES)
    # antidote: expiry ascending (the tie on day 20 is broken by lot code, no expiry last),
    # then decontaminant, ppe, other
    assert [row.lot_id for row in rows] == [4, 3, 9, 2, 1, 5, 6, 7, 8]
    assert [row.category for row in rows][:6] == [StockCategory.ANTIDOTE] * 6


def test_lot_rows_fields() -> None:
    lots, movements = _lots_and_movements()
    rows = {row.lot_id: row for row in lot_rows(types(), lots, movements, D, RULES)}
    expected: dict[int, tuple[int, int, LotStatus, int | None, date | None, int | None]] = {
        # lot: (on hand, valid, status, days to expiry, received on, value)
        1: (45, 45, LotStatus.VALID, 400, day(-200), 45 * 1500),
        2: (10, 10, LotStatus.EXPIRING, 20, day(-100), None),
        3: (4, 0, LotStatus.EXPIRED, -15, day(-300), None),
        4: (0, 0, LotStatus.EMPTY, -100, day(-400), None),
        5: (3, 3, LotStatus.VALID, None, day(-10), None),
        6: (2, 2, LotStatus.EXPIRING, 10, day(-5), 2 * 200),
        7: (5, 5, LotStatus.VALID, None, None, None),
        8: (4, 4, LotStatus.VALID, None, day(-10), None),
        9: (1, 1, LotStatus.EXPIRING, 20, day(-1), None),
    }
    for lot_id, (on_hand, valid, status, days, received, value) in expected.items():
        row = rows[lot_id]
        assert (
            row.on_hand,
            row.valid_quantity,
            row.status,
            row.days_to_expiry,
            row.received_on,
            row.value_minor,
        ) == (on_hand, valid, status, days, received, value), lot_id
    row = rows[1]
    assert (row.type_code, row.lot_code, row.expires_on) == (CHEM, "DEMO-L001", day(400))
    assert (row.unit_price_minor, row.currency) == (1500, "BRL")
    assert rows[6].category is StockCategory.DECONTAMINANT
    assert rows[7].category is StockCategory.PPE
    assert rows[8].category is StockCategory.OTHER


def test_lot_rows_first_receipt_is_the_earliest_receipt_on_or_before_d() -> None:
    lot = make_lot(1, expires_on=day(400))
    movements = [mv(1, -5, R, 2), mv(1, -20, R, 3), mv(1, -30, ADJ_IN, 1), mv(1, 3, R, 9)]
    (row,) = lot_rows(types(), [lot], movements, D, RULES)
    assert row.received_on == day(-20)
    (earlier,) = lot_rows(types(), [lot], movements, day(-10), RULES)
    assert earlier.received_on == day(-20)
    (before,) = lot_rows(types(), [lot], movements, day(-25), RULES)
    assert before.received_on is None  # only an adjustment so far
    assert before.status is LotStatus.VALID


def test_lot_rows_of_a_past_date() -> None:
    lots, movements = _lots_and_movements()
    rows = {row.lot_id: row for row in lot_rows(types(), lots, movements, day(-30), RULES)}
    assert rows[8].status is LotStatus.NOT_RECEIVED  # first received 10 days before D
    assert rows[8].on_hand == 0
    assert rows[1].on_hand == 45  # the issue on day -30 counts on day -30
    earlier = {row.lot_id: row for row in lot_rows(types(), lots, movements, day(-60), RULES)}
    assert earlier[1].on_hand == 50  # the issue of day -30 is still to come
    assert earlier[4].on_hand == 10  # the disposal of day -50 is still to come
    assert earlier[4].status is LotStatus.EXPIRED  # expired on day -100
    assert earlier[3].status is LotStatus.EXPIRING  # expires on day -15: 45 days later


def test_lot_rows_without_lots_and_with_an_unknown_type() -> None:
    assert lot_rows(types(), [], [], D, RULES) == ()
    with pytest.raises(StockDataError) as info:
        lot_rows(types(), [make_lot(1, "NO_SUCH_TYPE")], [], D, RULES)
    assert info.value.code == "UNKNOWN_TYPE"
    assert isinstance(info.value, ValueError)


# --------------------------------------------------------------------------- type_summaries


def chem_summary(
    stock_types: Sequence[StockType], lots: list[Lot], movements: list[Movement]
) -> TypeSummary:
    (summary,) = [
        s for s in type_summaries(stock_types, lots, movements, D, RULES) if s.type_code == CHEM
    ]
    return summary


def test_type_summaries_counts_and_quantities() -> None:
    lots, movements = _lots_and_movements()
    summaries = {s.type_code: s for s in type_summaries(types(), lots, movements, D, RULES)}
    chem = summaries[CHEM]
    assert chem.type_id == 1
    assert chem.category is StockCategory.ANTIDOTE
    assert chem.active is True
    assert chem.in_use is True
    assert chem.on_hand == 45 + 10 + 4 + 0 + 3 + 1
    assert chem.valid == 45 + 10 + 3 + 1  # expiring lots are valid, the expired one is not
    assert chem.expired_qty == 4
    assert chem.expiring_qty == 10 + 1
    assert chem.lots_expired == 1
    assert chem.lots_expiring == 2
    assert chem.minimum is None
    assert chem.below_minimum is None
    decon = summaries[DECON]
    assert (decon.on_hand, decon.valid, decon.expiring_qty, decon.lots_expiring) == (2, 2, 2, 1)
    assert (decon.expired_qty, decon.lots_expired) == (0, 0)


def test_type_summaries_are_sorted_by_category_then_code() -> None:
    extra = (*types(), StockType(5, "ANTIDOTE_BIOLOGICAL", StockCategory.ANTIDOTE))
    result = type_summaries(extra, [], [], D, RULES)
    assert [s.type_code for s in result] == [
        "ANTIDOTE_BIOLOGICAL",
        CHEM,
        DECON,
        GLOVE,
        O2,
    ]


@pytest.mark.parametrize(
    ("on_hand", "minimum", "expected"),
    [
        (0, None, None),  # no minimum: never below, whatever the quantity
        (7, None, None),
        (0, 0, False),  # a minimum of 0 is never below
        (3, 0, False),
        (4, 5, True),  # one below
        (5, 5, False),  # equal: not below (strict)
        (6, 5, False),  # one above
        (0, 5, True),
    ],
)
def test_below_minimum(on_hand: int, minimum: int | None, expected: bool | None) -> None:
    lot = make_lot(1, expires_on=day(400))
    movements = [mv(1, -10, R, on_hand)] if on_hand else []
    summary = chem_summary(types(minimum), [lot], movements)
    assert summary.valid == on_hand
    assert summary.minimum == minimum
    assert summary.below_minimum is expected


def test_an_expired_lot_does_not_count_towards_the_minimum() -> None:
    lots = [make_lot(1, expires_on=day(-1)), make_lot(2, lot_code="B", expires_on=day(30))]
    movements = [mv(1, -10, R, 10), mv(2, -10, R, 4)]
    summary = chem_summary(types(5), lots, movements)
    assert summary.on_hand == 14
    assert summary.valid == 4  # the expiring lot counts, the expired one does not
    assert summary.below_minimum is True


@pytest.mark.parametrize(
    ("receipt_offset", "expected"),
    [(-5, True), (0, True), (1, False), (None, False)],
)
def test_type_in_use_on_d(receipt_offset: int | None, expected: bool) -> None:
    lots = [make_lot(1, expires_on=day(400))]
    movements = [] if receipt_offset is None else [mv(1, receipt_offset, R, 3)]
    summaries = {s.type_code: s for s in type_summaries(types(), lots, movements, D, RULES)}
    assert summaries[CHEM].in_use is expected
    assert summaries[DECON].in_use is False  # no lot at all


def test_an_inactive_type_is_reported_as_inactive() -> None:
    inactive = (StockType(1, CHEM, StockCategory.ANTIDOTE, 5, active=False),)
    (summary,) = type_summaries(inactive, [], [], D, RULES)
    assert summary.active is False
    assert summary.below_minimum is True  # the rule is unchanged; callers decide on alerts


# --------------------------------------------------------------------------- stock_value


def _value_rows() -> tuple[list[Lot], list[Movement]]:
    lots = [
        make_lot(1, CHEM, "V1", day(200), 1000, "BRL"),
        make_lot(2, CHEM, "V2", day(5), 500, "BRL"),  # expiring: still valid
        make_lot(3, CHEM, "V3", day(-1), 250, "BRL"),  # expired
        make_lot(4, DECON, "V4", day(200), 2000, "USD"),
        make_lot(5, DECON, "V5", day(-30), 700, "USD"),  # expired
        make_lot(6, GLOVE, "V6"),  # unpriced, with stock
        make_lot(7, GLOVE, "V7"),  # unpriced, never received
        make_lot(8, O2, "V8", None, 900, "EUR"),  # priced but emptied
        make_lot(9, GLOVE, "V9", None, 100, None),  # a price without a currency
        make_lot(10, O2, "V10"),  # unpriced and emptied
    ]
    movements = [
        mv(1, -100, R, 3),
        mv(2, -100, R, 2),
        mv(3, -100, R, 4),
        mv(4, -100, R, 1),
        mv(5, -100, R, 2),
        mv(6, -100, R, 5),
        mv(8, -100, R, 3),
        mv(8, -50, ISSUE, 3),
        mv(9, -100, R, 2),
        mv(10, -100, R, 1),
        mv(10, -50, LOSS, 1),
    ]
    return lots, movements


def test_values_in_two_currencies_are_kept_apart_and_unpriced_lots_are_counted() -> None:
    lots, movements = _value_rows()
    rows = lot_rows(types(), lots, movements, D, RULES)
    value = stock_value(rows)
    assert dict(value.by_currency) == {
        "BRL": CurrencyValue(valid_minor=3 * 1000 + 2 * 500, expired_minor=4 * 250),
        "USD": CurrencyValue(valid_minor=1 * 2000, expired_minor=2 * 700),
    }
    assert list(value.by_currency) == ["BRL", "USD"]
    assert "EUR" not in value.by_currency  # the only EUR lot is empty
    assert value.unpriced_lots == 2  # V6 and V9; V7 and V10 hold nothing


def test_value_of_a_past_date_and_of_nothing() -> None:
    lots, movements = _value_rows()
    earlier = stock_value(lot_rows(types(), lots, movements, day(-120), RULES))
    assert dict(earlier.by_currency) == {}
    assert earlier.unpriced_lots == 0
    empty = stock_value([])
    assert dict(empty.by_currency) == {}
    assert empty.unpriced_lots == 0


def test_a_currency_with_only_expired_stock_has_a_zero_valid_value() -> None:
    lots = [make_lot(1, DECON, "X", day(-1), 700, "USD")]
    rows = lot_rows(types(), lots, [mv(1, -10, R, 2)], D, RULES)
    assert dict(stock_value(rows).by_currency) == {"USD": CurrencyValue(0, 1400)}


# --------------------------------------------------------------------------- expiry_schedule


#: (lot id, type code, lot code, expiry date, quantity received); a quantity of 0 means that the
#: lot was never received.
Entry = tuple[int, str, str, date | None, int]

SCHEDULE_ENTRIES: list[Entry] = [
    (1, CHEM, "E1", date(2026, 11, 19), 4),  # the day before d: expired
    (2, CHEM, "E2", date(2026, 11, 20), 6),  # on d: this month
    (3, CHEM, "N1", date(2026, 11, 30), 1),  # this month, same type as E2
    (4, DECON, "D1", date(2026, 11, 25), 3),  # this month, another type
    (5, CHEM, "J1", date(2027, 1, 15), 5),  # across the year boundary
    (6, CHEM, "J2", date(2027, 1, 31), 2),
    (7, GLOVE, "G1", date(2027, 10, 31), 9),  # the last day of the 12th month
    (8, GLOVE, "G2", date(2027, 11, 1), 8),  # the first day after the horizon
    (9, O2, "O1", None, 2),  # no expiry date
    (10, CHEM, "EMPTY", date(2026, 12, 5), 5),  # emptied below: left out
    (11, CHEM, "NOT-RECEIVED", date(2026, 12, 6), 0),  # left out
    (12, CHEM, "X", date(2026, 12, 1), 1),
]


def schedule_rows(
    entries: list[Entry], d: date, issued: dict[int, int] | None = None
) -> tuple[LotRow, ...]:
    """The lot rows on ``d`` of the entries; ``issued`` maps a lot id to a quantity issued."""
    lots = [make_lot(lot_id, kind, code, expires) for lot_id, kind, code, expires, _ in entries]
    movements = [mv(lot_id, -300, R, qty, d) for lot_id, _, _, _, qty in entries if qty > 0]
    movements += [mv(lot_id, -100, ISSUE, qty, d) for lot_id, qty in (issued or {}).items()]
    return lot_rows(types(), lots, movements, d, RULES)


def month(year: int, number: int) -> date:
    return date(year, number, 1)


def ids(rows: Sequence[LotRow]) -> list[int]:
    return [row.lot_id for row in rows]


def totals(by_type: Sequence[ScheduleTypeQuantity]) -> list[tuple[str, int, int]]:
    return [(item.type_code, item.quantity, item.lots) for item in by_type]


def test_schedule_buckets_across_a_year_boundary_with_an_expired_lot() -> None:
    rows = schedule_rows(SCHEDULE_ENTRIES, D, issued={10: 5})
    buckets = expiry_schedule(rows, D)
    assert len(buckets) == 15
    assert [b.kind for b in buckets] == [
        ScheduleBucketKind.EXPIRED,
        *[ScheduleBucketKind.MONTH] * 12,
        ScheduleBucketKind.LATER,
        ScheduleBucketKind.NO_EXPIRY,
    ]
    months = [b.month for b in buckets if b.kind is ScheduleBucketKind.MONTH]
    assert months == [month(2026, 11), month(2026, 12), *[month(2027, m) for m in range(1, 11)]]
    assert buckets[0].month is None
    assert buckets[13].month is None
    assert buckets[14].month is None

    by_month = {b.month: b for b in buckets if b.kind is ScheduleBucketKind.MONTH}
    assert ids(buckets[0].lots) == [1]
    assert ids(by_month[month(2026, 11)].lots) == [2, 4, 3]  # by expiry date
    assert ids(by_month[month(2026, 12)].lots) == [12]  # the emptied and unreceived lots are out
    assert ids(by_month[month(2027, 1)].lots) == [5, 6]
    assert ids(by_month[month(2027, 10)].lots) == [7]
    for number in range(2, 10):
        assert by_month[month(2027, number)].lots == ()
    assert ids(buckets[13].lots) == [8]
    assert ids(buckets[14].lots) == [9]


def test_schedule_adds_quantities_per_type_inside_one_bucket_only() -> None:
    rows = schedule_rows(SCHEDULE_ENTRIES, D, issued={10: 5})
    buckets = expiry_schedule(rows, D)
    by_month = {b.month: b for b in buckets if b.kind is ScheduleBucketKind.MONTH}
    # November: two antidote lots add up, the decontaminant stays on its own line
    assert totals(by_month[month(2026, 11)].by_type) == [(CHEM, 7, 2), (DECON, 3, 1)]
    # January has the same total for the same type: never added to November's
    assert totals(by_month[month(2027, 1)].by_type) == [(CHEM, 7, 2)]
    assert totals(by_month[month(2026, 12)].by_type) == [(CHEM, 1, 1)]
    assert totals(buckets[0].by_type) == [(CHEM, 4, 1)]
    assert totals(buckets[13].by_type) == [(GLOVE, 8, 1)]
    assert totals(buckets[14].by_type) == [(O2, 2, 1)]
    assert totals(by_month[month(2027, 5)].by_type) == []


def test_schedule_around_the_end_of_the_year_with_a_short_horizon() -> None:
    d = date(2026, 12, 15)
    entries: list[Entry] = [
        (1, CHEM, "A", date(2026, 12, 14), 2),  # expired the day before
        (2, CHEM, "B", date(2026, 12, 31), 3),
        (3, CHEM, "C", date(2027, 1, 1), 4),
        (4, CHEM, "D", date(2027, 2, 28), 5),
        (5, CHEM, "E", date(2027, 3, 1), 6),  # first day after the three months
        (6, CHEM, "F", date(2026, 12, 15), 7),  # on d
    ]
    buckets = expiry_schedule(schedule_rows(entries, d), d, months=3)
    assert [b.kind for b in buckets] == [
        ScheduleBucketKind.EXPIRED,
        ScheduleBucketKind.MONTH,
        ScheduleBucketKind.MONTH,
        ScheduleBucketKind.MONTH,
        ScheduleBucketKind.LATER,
        ScheduleBucketKind.NO_EXPIRY,
    ]
    assert [b.month for b in buckets[1:4]] == [month(2026, 12), month(2027, 1), month(2027, 2)]
    assert [ids(b.lots) for b in buckets] == [[1], [6, 2], [3], [4], [5], []]


@pytest.mark.parametrize(("months", "buckets_expected"), [(1, 4), (12, 15), (24, 27), (60, 63)])
def test_schedule_horizon(months: int, buckets_expected: int) -> None:
    buckets = expiry_schedule([], D, months)
    assert len(buckets) == buckets_expected
    assert all(b.lots == () and b.by_type == () for b in buckets)
    assert buckets[1].month == month(2026, 11)
    assert buckets[months].month == add_months(month(2026, 11), months - 1)
    assert buckets[months + 1].kind is ScheduleBucketKind.LATER


def test_schedule_horizon_of_one_month_puts_the_next_month_later() -> None:
    entries: list[Entry] = [
        (1, CHEM, "A", date(2026, 11, 30), 1),
        (2, CHEM, "B", date(2026, 12, 1), 1),
    ]
    buckets = expiry_schedule(schedule_rows(entries, D), D, months=1)
    assert ids(buckets[1].lots) == [1]
    assert buckets[2].kind is ScheduleBucketKind.LATER
    assert ids(buckets[2].lots) == [2]


@pytest.mark.parametrize("months", [0, -1, 61, 1000, True])
def test_schedule_rejects_a_horizon_outside_1_to_60(months: int) -> None:
    with pytest.raises(StockDataError) as info:
        expiry_schedule([], D, months)
    assert info.value.code == "INVALID_MONTHS"


def test_schedule_leaves_out_lots_without_stock() -> None:
    entries: list[Entry] = [(1, CHEM, "A", None, 3), (2, CHEM, "B", date(2026, 12, 1), 3)]
    rows = schedule_rows(entries, D, issued={1: 3, 2: 3})
    assert all(b.lots == () for b in expiry_schedule(rows, D))
