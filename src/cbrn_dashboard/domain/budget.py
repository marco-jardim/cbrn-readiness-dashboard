# SPDX-License-Identifier: GPL-3.0-or-later
"""Budget rules and the ``BUD_EXEC_RATE`` indicator (PLAN T5.2, §5.4, A08, P08, D15, D27).

Pure domain code: no Qt, no I/O, no clock. Every as-of function takes ``as_of`` explicitly and the
domain only works with codes and numbers; it never produces translated text.

Money
-----
Amounts are whole minor units (``int``, for example cents) together with an ISO 4217 currency code.
Sums are integer sums, so they are exact; floats appear only in the final ratio. Amounts of
different currencies are NEVER added (D15): every total is keyed by its currency.

Fiscal year
-----------
The fiscal year of a date is its calendar year (A08). An execution row belongs to the fiscal year
of its ``budget_entry``, whatever its own date; it counts only when dated on or before ``as_of``.

Pro-rating (P08)
----------------
``BUD_EXEC_RATE`` is year-to-date. When pro-rating is on, its target is multiplied by the elapsed
fraction of the year (day of the year / days in the year, linear), so a year-end target is not
Critical every January. :func:`target_scale` gives the factor that the indicator service passes to
``indicators.evaluate(..., target_scale=...)``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from cbrn_dashboard.domain.dates import day_of_year, days_in_year
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorDefinition,
    IndicatorValue,
    Module,
    UnitKind,
    encode_dimension,
)

BUD_EXEC_RATE = "BUD_EXEC_RATE"

# --------------------------------------------------------------------------------------------
# Currency allow-list (D15)
# --------------------------------------------------------------------------------------------

# Currency code -> number of decimal places of its minor unit (ISO 4217).
# Adding a currency is a commit, not a setting (plan §5.1).
CURRENCY_DECIMALS: Mapping[str, int] = MappingProxyType({"BRL": 2, "USD": 2, "EUR": 2})

DEFAULT_CURRENCY = "BRL"  # A08


class InvalidCurrencyError(ValueError):
    """A currency code is not in the allow-list."""

    code = "INVALID_CURRENCY"


class TooManyDecimalsError(ValueError):
    """An amount has more fraction digits than its currency allows."""

    code = "TOO_MANY_DECIMALS"


class InvalidAmountError(ValueError):
    """An amount is not a finite number."""

    code = "INVALID_AMOUNT"


def is_valid_currency(code: str) -> bool:
    """Whether ``code`` is in the allow-list."""
    return isinstance(code, str) and code in CURRENCY_DECIMALS


def currency_decimals(code: str) -> int:
    """Decimal places of the currency's minor unit; raises for a currency outside the list."""
    if not is_valid_currency(code):
        msg = f"currency not in the allow-list: {code!r}"
        raise InvalidCurrencyError(msg)
    return CURRENCY_DECIMALS[code]


def minor_to_decimal(minor: int, currency: str) -> Decimal:
    """Exact value of ``minor`` minor units, for example 12345 BRL -> ``Decimal('123.45')``."""
    decimals = currency_decimals(currency)
    digits = tuple(int(char) for char in str(abs(minor)))
    return Decimal((1 if minor < 0 else 0, digits, -decimals))


def decimal_to_minor(amount: Decimal, currency: str) -> int:
    """Exact whole minor units of ``amount``; never rounds.

    Raises :class:`TooManyDecimalsError` when the value needs more fraction digits than the
    currency allows, and :class:`InvalidAmountError` for NaN or infinity.
    """
    decimals = currency_decimals(currency)
    if not amount.is_finite():
        msg = f"amount is not finite: {amount!r}"
        raise InvalidAmountError(msg)
    sign, digits, exponent = amount.as_tuple()
    if not isinstance(exponent, int):  # pragma: no cover - finite decimals have an int exponent
        msg = f"amount is not finite: {amount!r}"
        raise InvalidAmountError(msg)
    coefficient = int("".join(str(digit) for digit in digits))
    shift = exponent + decimals
    # ``int ** int`` is typed ``Any`` (a negative exponent would give a float); the exponents here
    # are never negative, so declare the results as ``int``.
    minor: int
    if shift >= 0:
        factor: int = 10**shift
        minor = coefficient * factor
    else:
        divisor: int = 10**-shift
        minor, remainder = divmod(coefficient, divisor)
        if remainder:
            msg = f"{amount} has more than {decimals} decimal places for {currency}"
            raise TooManyDecimalsError(msg)
    return -minor if sign else minor


# --------------------------------------------------------------------------------------------
# Data objects
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BudgetEntry:
    """One allocation line; ``allocated_minor`` is ``None`` when the amount is empty."""

    id: int
    fiscal_year: int
    source_code: str
    currency: str
    allocated_minor: int | None


@dataclass(frozen=True)
class BudgetExecution:
    """One spending row of an entry, dated ``executed_on``."""

    entry_id: int
    executed_on: date
    amount_minor: int


@dataclass(frozen=True)
class BudgetTotal:
    """Totals of one (fiscal year, source, currency) group.

    ``allocated_minor`` is ``None`` ("missing") when every entry of the group has an empty amount.
    ``rate`` is ``None`` (No data) when allocated is missing or zero.
    """

    fiscal_year: int
    source_code: str
    currency: str
    allocated_minor: int | None
    executed_minor: int
    rate: float | None


_GroupKey = tuple[int, str, str]


# --------------------------------------------------------------------------------------------
# Fiscal year and pro-rating
# --------------------------------------------------------------------------------------------


def fiscal_year_of(d: date) -> int:
    """The fiscal year of a date is its calendar year (A08)."""
    return d.year


def elapsed_fraction(as_of: date) -> float:
    """Linear fraction of the year elapsed: day of the year / days in the year (P08).

    1 January of a 365-day year is 1/365; 31 December is exactly 1.0.
    """
    return day_of_year(as_of) / days_in_year(as_of.year)


def target_scale(as_of: date, *, prorate: bool) -> float:
    """Factor for the ``BUD_EXEC_RATE`` target: the elapsed fraction, or 1.0 when P08 is off."""
    return elapsed_fraction(as_of) if prorate else 1.0


# --------------------------------------------------------------------------------------------
# Totals
# --------------------------------------------------------------------------------------------


def orphan_executions(
    entries: Iterable[BudgetEntry], executions: Iterable[BudgetExecution]
) -> list[BudgetExecution]:
    """Execution rows whose ``entry_id`` matches no entry, in input order."""
    known = {entry.id for entry in entries}
    return [row for row in executions if row.entry_id not in known]


def _rate(allocated: int | None, executed: int) -> float | None:
    if allocated is None or allocated == 0:
        return None
    return executed / allocated


def totals(
    entries: Iterable[BudgetEntry], executions: Iterable[BudgetExecution], as_of: date
) -> list[BudgetTotal]:
    """Totals per (fiscal year, source, currency), sorted by that key.

    * allocated: sum of the entered amounts; ``None`` when every entry of the group is empty;
    * executed: sum of the rows of the group's entries dated on or before ``as_of``;
    * rate: executed / allocated, ``None`` when allocated is missing or zero.

    Execution rows with an unknown entry are ignored (see :func:`orphan_executions`). Nothing is
    ever added across currencies.
    """
    key_of_entry: dict[int, _GroupKey] = {}
    allocated: dict[_GroupKey, int | None] = {}
    for entry in entries:
        key = (entry.fiscal_year, entry.source_code, entry.currency)
        key_of_entry[entry.id] = key
        current = allocated.get(key)
        if entry.allocated_minor is None:
            allocated.setdefault(key, None)
        else:
            allocated[key] = (current or 0) + entry.allocated_minor
    executed: dict[_GroupKey, int] = dict.fromkeys(allocated, 0)
    for row in executions:
        row_key = key_of_entry.get(row.entry_id)
        if row_key is None or row.executed_on > as_of:
            continue
        executed[row_key] += row.amount_minor
    return [
        BudgetTotal(
            fiscal_year=key[0],
            source_code=key[1],
            currency=key[2],
            allocated_minor=allocated[key],
            executed_minor=executed[key],
            rate=_rate(allocated[key], executed[key]),
        )
        for key in sorted(allocated)
    ]


def totals_for_year(
    entries: Iterable[BudgetEntry],
    executions: Iterable[BudgetExecution],
    as_of: date,
    fiscal_year: int,
) -> list[BudgetTotal]:
    """:func:`totals` restricted to one fiscal year."""
    return [row for row in totals(entries, executions, as_of) if row.fiscal_year == fiscal_year]


def multi_year_table(
    entries: Iterable[BudgetEntry], executions: Iterable[BudgetExecution], as_of: date
) -> list[BudgetTotal]:
    """Budget planning table (R36): all fiscal years, sorted by year, source and currency."""
    return totals(entries, executions, as_of)


# --------------------------------------------------------------------------------------------
# Indicator
# --------------------------------------------------------------------------------------------


def indicator_definitions() -> tuple[IndicatorDefinition, ...]:
    """The budget indicator definitions (registry provider)."""
    return (
        IndicatorDefinition(
            code=BUD_EXEC_RATE,
            module=Module.BUDGET,
            unit=UnitKind.RATIO,
            direction=Direction.HIGHER_IS_BETTER,
            dimension_keys=("currency", "source"),
            source="R24",
        ),
    )


def indicator_values(
    entries: Iterable[BudgetEntry], executions: Iterable[BudgetExecution], as_of: date
) -> list[IndicatorValue]:
    """``BUD_EXEC_RATE`` per (source, currency) of the as-of date's fiscal year, by dimension."""
    rows = totals_for_year(entries, executions, as_of, fiscal_year_of(as_of))
    values: list[IndicatorValue] = []
    for row in rows:
        context: Mapping[str, float] | None = None
        if row.allocated_minor is not None:
            context = {
                "allocated_minor": float(row.allocated_minor),
                "executed_minor": float(row.executed_minor),
            }
        values.append(
            IndicatorValue(
                code=BUD_EXEC_RATE,
                value=row.rate,
                dimension=encode_dimension({"currency": row.currency, "source": row.source_code}),
                context=context,
            )
        )
    values.sort(key=lambda item: item.dimension)
    return values
