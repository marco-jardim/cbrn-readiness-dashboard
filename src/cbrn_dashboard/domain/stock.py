# SPDX-License-Identifier: GPL-3.0-or-later
"""Stock rules by lot (PLAN T11.4, D32 to D36, A15, A16, P11, P12).

Pure domain code: no Qt, no I/O, no clock. Every function takes the as-of date ``d`` explicitly, so
a past as-of date gives the reading computed from the movements as known now for that date. Only
codes and numbers are produced; the UI maps the codes to labels. Stock is management data only
(type, lot, quantity, expiry date, price, movements): there is no clinical field (D19, D38).

Rules
-----
* The quantity of a lot on ``d`` is the signed sum of its movements dated on or before ``d``
  (D33): receipt and adjustment-in count +1, the other kinds -1. The quantity is never stored.
* The end-of-day balance of a lot must never be negative; :func:`first_negative_day` finds the
  first date on which it is (the order of the movements inside one day is ignored).
* A lot is *valid* on ``d`` when ``expires_on`` is empty or not before ``d`` (D34). Its valid
  quantity is the quantity on hand if it is valid, else 0. An empty expiry date means "no expiry".
* The status on ``d`` is the first that applies of: not received (no movement on or before ``d``),
  empty (nothing on hand), expired (``expires_on < d``), expiring (``d <= expires_on <= d`` plus
  the P11 window, both ends inclusive, as ``is_due_soon`` of the infrastructure rules), valid.
* A type is below its minimum (D35, P12) when its valid quantity is strictly less than the
  minimum; a type with no minimum is never below it, and a minimum of 0 is never reached from
  below.
* Currencies are never added together (D15): values are totalled per currency.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType

from cbrn_dashboard.domain.dates import add_months, days_between, month_start

__all__ = [
    "ANTIDOTE_PAGE_CATEGORIES",
    "CATEGORY_ORDER",
    "EXPIRY_REQUIRED_CATEGORIES",
    "MAX_SCHEDULE_MONTHS",
    "SIGN",
    "CurrencyValue",
    "Lot",
    "LotRow",
    "LotStatus",
    "Movement",
    "MovementKind",
    "ScheduleBucket",
    "ScheduleBucketKind",
    "ScheduleTypeQuantity",
    "StockCategory",
    "StockDataError",
    "StockRules",
    "StockType",
    "StockValue",
    "TypeSummary",
    "expiry_schedule",
    "first_negative_day",
    "lot_rows",
    "lot_status",
    "quantity_on",
    "signed_quantity",
    "stock_value",
    "type_summaries",
    "valid_quantity",
    "validity",
]

#: Largest accepted horizon of the expiry schedule, in months.
MAX_SCHEDULE_MONTHS = 60


# --------------------------------------------------------------------------------------------
# Enums and constants
# --------------------------------------------------------------------------------------------


class StockCategory(StrEnum):
    """Category of a stock item type; the order of the members is the display order."""

    ANTIDOTE = "antidote"
    DECONTAMINANT = "decontaminant"
    DETECTOR = "detector"
    PPE = "ppe"
    OTHER = "other"


class MovementKind(StrEnum):
    """The six kinds of dated movement (D33); the quantity is positive, the kind gives the sign."""

    RECEIPT = "receipt"
    ISSUE = "issue"
    DISPOSAL = "disposal"
    LOSS = "loss"
    ADJUSTMENT_IN = "adjustment_in"
    ADJUSTMENT_OUT = "adjustment_out"


class LotStatus(StrEnum):
    """Status of a lot on a date; the order of precedence is NOT_RECEIVED, EMPTY, EXPIRED, ..."""

    VALID = "VALID"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    EMPTY = "EMPTY"
    NOT_RECEIVED = "NOT_RECEIVED"


#: Sign of each movement kind: +1 adds to the stock, -1 takes from it.
SIGN: Mapping[MovementKind, int] = MappingProxyType(
    {
        MovementKind.RECEIPT: 1,
        MovementKind.ISSUE: -1,
        MovementKind.DISPOSAL: -1,
        MovementKind.LOSS: -1,
        MovementKind.ADJUSTMENT_IN: 1,
        MovementKind.ADJUSTMENT_OUT: -1,
    }
)

#: The categories of the antidotes page.
ANTIDOTE_PAGE_CATEGORIES: frozenset[StockCategory] = frozenset(
    {StockCategory.ANTIDOTE, StockCategory.DECONTAMINANT}
)
#: The categories whose lots must have an expiry date (D34).
EXPIRY_REQUIRED_CATEGORIES: frozenset[StockCategory] = frozenset(
    {StockCategory.ANTIDOTE, StockCategory.DECONTAMINANT}
)
#: The categories in display order.
CATEGORY_ORDER: tuple[StockCategory, ...] = tuple(StockCategory)

_CATEGORY_INDEX: Mapping[StockCategory, int] = MappingProxyType(
    {category: index for index, category in enumerate(CATEGORY_ORDER)}
)


class StockDataError(ValueError):
    """Inconsistent input of a stock function; ``code`` is stable (``UNKNOWN_TYPE``, ...)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# --------------------------------------------------------------------------------------------
# Data objects
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class StockRules:
    """Configuration taken by the rules (P11); the service reads it from the settings."""

    expiry_warning_days: int = 90


@dataclass(frozen=True)
class StockType:
    """An item type; ``minimum_quantity`` is ``None`` when no minimum is set (P12)."""

    id: int
    code: str
    category: StockCategory
    minimum_quantity: int | None = None
    active: bool = True


@dataclass(frozen=True)
class Lot:
    """A lot of one item type; ``expires_on`` is ``None`` for "no expiry date"."""

    id: int
    type_code: str
    lot_code: str
    expires_on: date | None = None
    unit_price_minor: int | None = None
    currency: str | None = None


@dataclass(frozen=True)
class Movement:
    """A dated movement of a lot; ``quantity`` is positive and the kind gives the sign."""

    id: int
    lot_id: int
    moved_on: date
    kind: MovementKind
    quantity: int


@dataclass(frozen=True)
class LotRow:
    """One lot as read on a date.

    ``received_on`` is the date of the first receipt on or before the as-of date (``None`` when
    there is none). ``days_to_expiry`` is signed: negative once expired, ``None`` without expiry.
    ``value_minor`` is the quantity on hand times the unit price, ``None`` without a price.
    """

    lot_id: int
    type_code: str
    category: StockCategory
    lot_code: str
    received_on: date | None
    expires_on: date | None
    on_hand: int
    valid_quantity: int
    status: LotStatus
    days_to_expiry: int | None
    unit_price_minor: int | None
    currency: str | None
    value_minor: int | None


@dataclass(frozen=True)
class TypeSummary:
    """One item type as read on a date.

    ``on_hand`` adds every lot, ``valid`` the valid ones (expiring lots are valid),
    ``expired_qty`` and ``expiring_qty`` the quantity of the lots in those statuses. ``in_use``
    means the type has a lot with a movement on or before the date. ``below_minimum`` is ``None``
    when no minimum is set.
    """

    type_id: int
    type_code: str
    category: StockCategory
    active: bool
    in_use: bool
    on_hand: int
    valid: int
    expired_qty: int
    expiring_qty: int
    lots_expired: int
    lots_expiring: int
    minimum: int | None
    below_minimum: bool | None


@dataclass(frozen=True)
class CurrencyValue:
    """Value in minor units of one currency: lots still valid, and expired lots in stock."""

    valid_minor: int
    expired_minor: int


@dataclass(frozen=True)
class StockValue:
    """Stock value per currency (never added across currencies, D15).

    ``unpriced_lots`` counts the lots with stock on hand and no price (or no currency): their
    value is missing from the totals.
    """

    by_currency: Mapping[str, CurrencyValue]
    unpriced_lots: int


class ScheduleBucketKind(StrEnum):
    """The kinds of bucket of the expiry schedule."""

    EXPIRED = "EXPIRED"
    MONTH = "MONTH"
    LATER = "LATER"
    NO_EXPIRY = "NO_EXPIRY"


@dataclass(frozen=True)
class ScheduleTypeQuantity:
    """Quantity of one type inside one bucket (quantities are never added across types)."""

    type_code: str
    category: StockCategory
    quantity: int
    lots: int


@dataclass(frozen=True)
class ScheduleBucket:
    """One bucket of the expiry schedule.

    ``month`` is the first day of the month for a ``MONTH`` bucket and ``None`` otherwise. The
    lots are sorted by expiry date, category, type code and lot code.
    """

    kind: ScheduleBucketKind
    month: date | None
    lots: tuple[LotRow, ...]
    by_type: tuple[ScheduleTypeQuantity, ...]


# --------------------------------------------------------------------------------------------
# Quantities
# --------------------------------------------------------------------------------------------


def signed_quantity(movement: Movement) -> int:
    """The quantity of ``movement`` with the sign of its kind."""
    return SIGN[movement.kind] * movement.quantity


def quantity_on(movements: Iterable[Movement], lot_id: int, d: date) -> int:
    """Signed sum of the movements of ``lot_id`` dated on or before ``d``."""
    return sum(
        signed_quantity(movement)
        for movement in movements
        if movement.lot_id == lot_id and movement.moved_on <= d
    )


def _first_negative_day_of(movements: Iterable[Movement]) -> date | None:
    net: dict[date, int] = {}
    for movement in movements:
        net[movement.moved_on] = net.get(movement.moved_on, 0) + signed_quantity(movement)
    running = 0
    for day in sorted(net):
        running += net[day]
        if running < 0:
            return day
    return None


def first_negative_day(movements: Iterable[Movement]) -> date | None:
    """The first date on which the end-of-day balance of a lot is negative, else ``None``.

    The running totals are taken in ascending date order and the order inside one day is ignored.
    Movements of several lots are balanced separately; the earliest such date is returned.
    """
    by_lot: dict[int, list[Movement]] = {}
    for movement in movements:
        by_lot.setdefault(movement.lot_id, []).append(movement)
    days = [day for day in map(_first_negative_day_of, by_lot.values()) if day is not None]
    return min(days) if days else None


# --------------------------------------------------------------------------------------------
# Validity and status
# --------------------------------------------------------------------------------------------


def validity(lot: Lot, d: date) -> bool:
    """Whether ``lot`` is valid on ``d``: no expiry date, or ``expires_on >= d`` (D34)."""
    return lot.expires_on is None or lot.expires_on >= d


def valid_quantity(lot: Lot, movements: Iterable[Movement], d: date) -> int:
    """The quantity of ``lot`` on hand on ``d`` if the lot is valid on ``d``, else 0."""
    return quantity_on(movements, lot.id, d) if validity(lot, d) else 0


def _status(
    expires_on: date | None, on_hand: int, *, received: bool, d: date, rules: StockRules
) -> LotStatus:
    if not received:
        return LotStatus.NOT_RECEIVED
    if on_hand <= 0:
        return LotStatus.EMPTY
    if expires_on is None:
        return LotStatus.VALID
    days = days_between(d, expires_on)
    if days < 0:
        return LotStatus.EXPIRED
    if days <= rules.expiry_warning_days:
        return LotStatus.EXPIRING
    return LotStatus.VALID


def lot_status(lot: Lot, movements: Iterable[Movement], d: date, rules: StockRules) -> LotStatus:
    """The status of ``lot`` on ``d``: NOT_RECEIVED > EMPTY > EXPIRED > EXPIRING > VALID."""
    own = [movement for movement in movements if movement.lot_id == lot.id]
    received = any(movement.moved_on <= d for movement in own)
    on_hand = quantity_on(own, lot.id, d)
    return _status(lot.expires_on, on_hand, received=received, d=d, rules=rules)


# --------------------------------------------------------------------------------------------
# Rows and summaries
# --------------------------------------------------------------------------------------------


def _group_by_lot(movements: Iterable[Movement], d: date) -> dict[int, list[Movement]]:
    grouped: dict[int, list[Movement]] = {}
    for movement in movements:
        if movement.moved_on <= d:
            grouped.setdefault(movement.lot_id, []).append(movement)
    return grouped


def _row(
    lot: Lot, category: StockCategory, own: Sequence[Movement], d: date, rules: StockRules
) -> LotRow:
    """The row of ``lot``; ``own`` holds its movements dated on or before ``d``."""
    on_hand = sum(signed_quantity(movement) for movement in own)
    receipts = [movement.moved_on for movement in own if movement.kind is MovementKind.RECEIPT]
    expires_on = lot.expires_on
    price = lot.unit_price_minor
    return LotRow(
        lot_id=lot.id,
        type_code=lot.type_code,
        category=category,
        lot_code=lot.lot_code,
        received_on=min(receipts) if receipts else None,
        expires_on=expires_on,
        on_hand=on_hand,
        valid_quantity=on_hand if validity(lot, d) else 0,
        status=_status(expires_on, on_hand, received=bool(own), d=d, rules=rules),
        days_to_expiry=None if expires_on is None else days_between(d, expires_on),
        unit_price_minor=price,
        currency=lot.currency,
        value_minor=None if price is None else on_hand * price,
    )


def _row_order(row: LotRow) -> tuple[int, str, bool, date, str, int]:
    return (
        _CATEGORY_INDEX[row.category],
        row.type_code,
        row.expires_on is None,
        row.expires_on or date.min,
        row.lot_code,
        row.lot_id,
    )


def lot_rows(
    types: Iterable[StockType],
    lots: Iterable[Lot],
    movements: Iterable[Movement],
    d: date,
    rules: StockRules,
) -> tuple[LotRow, ...]:
    """One row per lot as read on ``d``, sorted by category, type code, expiry and lot code.

    Lots without an expiry date come last inside their type. A lot whose type is not in ``types``
    raises :class:`StockDataError` (``UNKNOWN_TYPE``).
    """
    category_of = {item.code: item.category for item in types}
    grouped = _group_by_lot(movements, d)
    rows: list[LotRow] = []
    for lot in lots:
        category = category_of.get(lot.type_code)
        if category is None:
            raise StockDataError("UNKNOWN_TYPE", lot.type_code)
        rows.append(_row(lot, category, grouped.get(lot.id, ()), d, rules))
    return tuple(sorted(rows, key=_row_order))


def type_summaries(
    types: Iterable[StockType],
    lots: Iterable[Lot],
    movements: Iterable[Movement],
    d: date,
    rules: StockRules,
) -> tuple[TypeSummary, ...]:
    """One summary per type as read on ``d``, sorted by category and type code.

    A type without lots has all quantities 0 and is not in use. ``below_minimum`` is ``None``
    without a minimum, otherwise ``valid < minimum`` (strict).
    """
    type_list = list(types)
    rows = lot_rows(type_list, lots, movements, d, rules)
    by_type: dict[str, list[LotRow]] = {}
    for row in rows:
        by_type.setdefault(row.type_code, []).append(row)
    summaries: list[TypeSummary] = []
    for item in type_list:
        own = by_type.get(item.code, [])
        valid = sum(row.valid_quantity for row in own)
        expired = [row for row in own if row.status is LotStatus.EXPIRED]
        expiring = [row for row in own if row.status is LotStatus.EXPIRING]
        minimum = item.minimum_quantity
        summaries.append(
            TypeSummary(
                type_id=item.id,
                type_code=item.code,
                category=item.category,
                active=item.active,
                in_use=any(row.status is not LotStatus.NOT_RECEIVED for row in own),
                on_hand=sum(row.on_hand for row in own),
                valid=valid,
                expired_qty=sum(row.on_hand for row in expired),
                expiring_qty=sum(row.on_hand for row in expiring),
                lots_expired=len(expired),
                lots_expiring=len(expiring),
                minimum=minimum,
                below_minimum=None if minimum is None else valid < minimum,
            )
        )
    return tuple(sorted(summaries, key=lambda s: (_CATEGORY_INDEX[s.category], s.type_code)))


# --------------------------------------------------------------------------------------------
# Value and expiry schedule
# --------------------------------------------------------------------------------------------


def stock_value(rows: Iterable[LotRow]) -> StockValue:
    """Value of the stock per currency: valid lots (expiring included) and expired lots.

    Only lots with stock on hand count. A lot with stock and no price (or no currency) adds to
    ``unpriced_lots`` instead. Currencies are never added together (D15); they are sorted by code.
    """
    valid: dict[str, int] = {}
    expired: dict[str, int] = {}
    unpriced = 0
    for row in rows:
        if row.on_hand <= 0:
            continue
        if row.value_minor is None or row.currency is None:
            unpriced += 1
            continue
        valid.setdefault(row.currency, 0)
        expired.setdefault(row.currency, 0)
        if row.status is LotStatus.EXPIRED:
            expired[row.currency] += row.value_minor
        else:
            valid[row.currency] += row.value_minor
    by_currency = {
        code: CurrencyValue(valid_minor=valid[code], expired_minor=expired[code])
        for code in sorted(valid)
    }
    return StockValue(by_currency=MappingProxyType(by_currency), unpriced_lots=unpriced)


def _bucket(kind: ScheduleBucketKind, month: date | None, rows: list[LotRow]) -> ScheduleBucket:
    ordered = sorted(
        rows,
        key=lambda row: (
            row.expires_on or date.max,
            _CATEGORY_INDEX[row.category],
            row.type_code,
            row.lot_code,
            row.lot_id,
        ),
    )
    totals: dict[str, ScheduleTypeQuantity] = {}
    for row in ordered:
        current = totals.get(row.type_code)
        totals[row.type_code] = ScheduleTypeQuantity(
            type_code=row.type_code,
            category=row.category,
            quantity=row.on_hand + (current.quantity if current else 0),
            lots=1 + (current.lots if current else 0),
        )
    by_type = tuple(
        sorted(totals.values(), key=lambda item: (_CATEGORY_INDEX[item.category], item.type_code))
    )
    return ScheduleBucket(kind=kind, month=month, lots=tuple(ordered), by_type=by_type)


def expiry_schedule(
    rows: Iterable[LotRow], d: date, months: int = 12
) -> tuple[ScheduleBucket, ...]:
    """Bucket the lots with stock by expiry: expired, one bucket per month, later, no expiry.

    The month buckets run from the month of ``d`` for ``months`` months (1 to
    :data:`MAX_SCHEDULE_MONTHS`) and are all returned, empty ones included. A lot expiring in the
    month of ``d`` but before ``d`` is expired. Quantities are added per type inside one bucket
    only. Lots with nothing on hand are left out. Another ``months`` raises
    :class:`StockDataError` (``INVALID_MONTHS``).
    """
    if isinstance(months, bool) or not 1 <= months <= MAX_SCHEDULE_MONTHS:
        raise StockDataError("INVALID_MONTHS", str(months))
    first = month_start(d)
    starts = [add_months(first, offset) for offset in range(months)]
    end = add_months(first, months)
    expired: list[LotRow] = []
    later: list[LotRow] = []
    no_expiry: list[LotRow] = []
    monthly: dict[date, list[LotRow]] = {start: [] for start in starts}
    for row in rows:
        if row.on_hand <= 0:
            continue
        if row.expires_on is None:
            no_expiry.append(row)
        elif row.expires_on < d:
            expired.append(row)
        elif row.expires_on >= end:
            later.append(row)
        else:
            monthly[month_start(row.expires_on)].append(row)
    buckets = [_bucket(ScheduleBucketKind.EXPIRED, None, expired)]
    buckets.extend(_bucket(ScheduleBucketKind.MONTH, start, monthly[start]) for start in starts)
    buckets.append(_bucket(ScheduleBucketKind.LATER, None, later))
    buckets.append(_bucket(ScheduleBucketKind.NO_EXPIRY, None, no_expiry))
    return tuple(buckets)
