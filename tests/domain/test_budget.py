# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the budget rules and the BUD_EXEC_RATE indicator (PLAN T5.2)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pytest

from cbrn_dashboard.domain import budget
from cbrn_dashboard.domain.budget import (
    CURRENCY_DECIMALS,
    DEFAULT_CURRENCY,
    BudgetEntry,
    BudgetExecution,
    BudgetTotal,
    InvalidAmountError,
    InvalidCurrencyError,
    TooManyDecimalsError,
)
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorStatus,
    Module,
    Target,
    TargetKey,
    UnitKind,
    evaluate,
)
from cbrn_dashboard.domain.registry import build_registry

SRC_A = "DEMO-SRC-A"
DIRSA = "DIRSA"
OPCW = "OPCW_TRUST_FUND"


def entry(
    entry_id: int,
    *,
    year: int = 2026,
    source: str = SRC_A,
    currency: str = "BRL",
    allocated: int | None = 1000,
) -> BudgetEntry:
    return BudgetEntry(
        id=entry_id,
        fiscal_year=year,
        source_code=source,
        currency=currency,
        allocated_minor=allocated,
    )


def spent(entry_id: int, on: date, amount: int) -> BudgetExecution:
    return BudgetExecution(entry_id=entry_id, executed_on=on, amount_minor=amount)


# --------------------------------------------------------------------------------------------
# Totals
# --------------------------------------------------------------------------------------------


def test_totals_sum_several_entries_of_one_group() -> None:
    entries = [entry(1, allocated=1000), entry(2, allocated=2500), entry(3, allocated=500)]
    executions = [spent(1, date(2026, 2, 1), 400), spent(2, date(2026, 3, 1), 600)]
    result = budget.totals(entries, executions, date(2026, 6, 30))
    assert result == [
        BudgetTotal(
            fiscal_year=2026,
            source_code=SRC_A,
            currency="BRL",
            allocated_minor=4000,
            executed_minor=1000,
            rate=0.25,
        )
    ]


@pytest.mark.parametrize(
    ("as_of", "executed", "rate"),
    [
        (date(2026, 1, 9), 0, 0.0),
        (date(2026, 1, 10), 100, 0.1),  # a row dated exactly on as_of is included
        (date(2026, 3, 31), 100, 0.1),
        (date(2026, 4, 1), 300, 0.3),
        (date(2026, 12, 31), 600, 0.6),
    ],
)
def test_executed_amounts_are_read_as_of_the_date(as_of: date, executed: int, rate: float) -> None:
    entries = [entry(1, allocated=1000)]
    executions = [
        spent(1, date(2026, 1, 10), 100),
        spent(1, date(2026, 4, 1), 200),
        spent(1, date(2026, 11, 15), 300),
    ]
    (row,) = budget.totals(entries, executions, as_of)
    assert row.executed_minor == executed
    assert row.rate == pytest.approx(rate)


@pytest.mark.parametrize(
    ("allocated_values", "expected_allocated", "expected_rate"),
    [
        ([0], 0, None),
        ([0, 0], 0, None),
        ([None], None, None),
        ([None, None], None, None),
        ([None, 800], 800, 0.25),  # an empty amount contributes nothing next to entered ones
        ([800, None, 200], 1000, 0.2),
        ([500, -100], 400, 0.5),  # negatives are not rejected here and must not crash
    ],
)
def test_rate_is_no_data_for_zero_or_missing_allocated(
    allocated_values: list[int | None], expected_allocated: int | None, expected_rate: float | None
) -> None:
    entries = [entry(i, allocated=value) for i, value in enumerate(allocated_values, start=1)]
    executions = [spent(1, date(2026, 5, 5), 200)]
    (row,) = budget.totals(entries, executions, date(2026, 6, 1))
    assert row.allocated_minor == expected_allocated
    assert row.rate == expected_rate


def test_missing_allocated_still_reports_executed_amount() -> None:
    entries = [entry(1, allocated=None)]
    (row,) = budget.totals(entries, [spent(1, date(2026, 5, 5), 70)], date(2026, 6, 1))
    assert (row.allocated_minor, row.executed_minor, row.rate) == (None, 70, None)


def test_negative_execution_does_not_crash() -> None:
    (row,) = budget.totals([entry(1)], [spent(1, date(2026, 5, 5), -50)], date(2026, 6, 1))
    assert row.executed_minor == -50
    assert row.rate == pytest.approx(-0.05)


def test_two_currencies_are_kept_apart() -> None:
    entries = [
        entry(1, currency="BRL", allocated=1000),
        entry(2, currency="USD", allocated=200),
        entry(3, currency="USD", allocated=300),
    ]
    executions = [spent(1, date(2026, 2, 2), 500), spent(2, date(2026, 2, 2), 50)]
    result = budget.totals(entries, executions, date(2026, 12, 31))
    assert [(r.currency, r.allocated_minor, r.executed_minor) for r in result] == [
        ("BRL", 1000, 500),
        ("USD", 500, 50),
    ]
    values = budget.indicator_values(entries, executions, date(2026, 12, 31))
    assert [(v.dimension, v.value) for v in values] == [
        (f"currency=BRL;source={SRC_A}", 0.5),
        (f"currency=USD;source={SRC_A}", 0.1),
    ]


def test_sources_are_grouped_and_sorted() -> None:
    entries = [
        entry(1, source=OPCW, allocated=100),
        entry(2, source=DIRSA, allocated=200),
        entry(3, source=SRC_A, allocated=300),
        entry(4, source=DIRSA, currency="EUR", allocated=400),
    ]
    result = budget.totals(entries, [], date(2026, 1, 1))
    assert [(r.source_code, r.currency) for r in result] == [
        (SRC_A, "BRL"),
        (DIRSA, "BRL"),
        (DIRSA, "EUR"),
        (OPCW, "BRL"),
    ]


def test_totals_of_nothing_is_empty() -> None:
    assert budget.totals([], [], date(2026, 1, 1)) == []
    assert budget.indicator_values([], [], date(2026, 1, 1)) == []


def test_rows_belong_to_the_fiscal_year_of_their_entry() -> None:
    entries = [entry(1, year=2025, allocated=1000), entry(2, year=2026, allocated=1000)]
    executions = [spent(1, date(2026, 1, 1), 250), spent(2, date(2026, 1, 1), 100)]
    result = budget.totals(entries, executions, date(2026, 1, 1))
    assert [(r.fiscal_year, r.executed_minor) for r in result] == [(2025, 250), (2026, 100)]


# --------------------------------------------------------------------------------------------
# Orphans
# --------------------------------------------------------------------------------------------


def test_orphan_executions_are_ignored_and_reported() -> None:
    orphan = spent(99, date(2026, 3, 3), 777)
    good = spent(1, date(2026, 3, 3), 10)
    entries = [entry(1)]
    assert budget.orphan_executions(entries, [good, orphan]) == [orphan]
    assert budget.orphan_executions(entries, [good]) == []
    (row,) = budget.totals(entries, [good, orphan], date(2026, 12, 31))
    assert row.executed_minor == 10


# --------------------------------------------------------------------------------------------
# Multi-year table
# --------------------------------------------------------------------------------------------


def test_multi_year_table_is_sorted_by_year_source_currency() -> None:
    entries = [
        entry(1, year=2027, source=SRC_A),
        entry(2, year=2025, source=OPCW),
        entry(3, year=2026, source=DIRSA, currency="USD"),
        entry(4, year=2025, source=DIRSA),
        entry(5, year=2026, source=DIRSA, currency="BRL"),
    ]
    table = budget.multi_year_table(entries, [], date(2026, 6, 1))
    assert [(r.fiscal_year, r.source_code, r.currency) for r in table] == [
        (2025, DIRSA, "BRL"),
        (2025, OPCW, "BRL"),
        (2026, DIRSA, "BRL"),
        (2026, DIRSA, "USD"),
        (2027, SRC_A, "BRL"),
    ]


def test_totals_for_year_filters_one_year() -> None:
    entries = [entry(1, year=2025), entry(2, year=2026), entry(3, year=2026, source=DIRSA)]
    rows = budget.totals_for_year(entries, [], date(2026, 6, 1), 2026)
    assert [(r.fiscal_year, r.source_code) for r in rows] == [(2026, SRC_A), (2026, DIRSA)]


# --------------------------------------------------------------------------------------------
# Fiscal year
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "year"),
    [
        (date(2025, 12, 31), 2025),
        (date(2026, 1, 1), 2026),
        (date(2026, 6, 15), 2026),
        (date(2028, 2, 29), 2028),
    ],
)
def test_fiscal_year_is_the_calendar_year(day: date, year: int) -> None:
    assert budget.fiscal_year_of(day) == year


def test_indicator_values_switch_fiscal_year_on_1_january() -> None:
    entries = [
        entry(1, year=2025, allocated=1000),
        entry(2, year=2026, source=DIRSA, allocated=2000),
    ]
    executions = [spent(1, date(2025, 12, 20), 500), spent(2, date(2026, 1, 1), 200)]

    before = budget.indicator_values(entries, executions, date(2025, 12, 31))
    assert [(v.dimension, v.value) for v in before] == [(f"currency=BRL;source={SRC_A}", 0.5)]

    after = budget.indicator_values(entries, executions, date(2026, 1, 1))
    assert [(v.dimension, v.value) for v in after] == [(f"currency=BRL;source={DIRSA}", 0.1)]


# --------------------------------------------------------------------------------------------
# Integer arithmetic
# --------------------------------------------------------------------------------------------


def test_many_small_rows_sum_exactly() -> None:
    entries = [entry(i, allocated=10 if i % 2 else 20) for i in range(1, 2001)]
    executions = [spent(1, date(2026, 1, 2), 10 if i % 2 else 20) for i in range(1, 3001)]
    (row,) = budget.totals(entries, executions, date(2026, 12, 31))
    assert row.allocated_minor == 1000 * 10 + 1000 * 20
    assert row.executed_minor == 1500 * 10 + 1500 * 20
    assert isinstance(row.allocated_minor, int)
    assert isinstance(row.executed_minor, int)
    assert row.rate == 1.5


def test_amounts_above_2_pow_53_stay_exact() -> None:
    big = 2**53
    entries = [entry(1, allocated=big + 1), entry(2, allocated=1)]
    executions = [spent(1, date(2026, 1, 2), big + 1), spent(2, date(2026, 1, 3), 2)]
    (row,) = budget.totals(entries, executions, date(2026, 12, 31))
    assert row.allocated_minor == big + 2
    assert row.executed_minor == big + 3
    assert float(big + 1) == float(big)  # a float could not tell these two apart
    assert row.allocated_minor != row.executed_minor


# --------------------------------------------------------------------------------------------
# Pro-rating (P08)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 1, 1), 1 / 365),
        (date(2026, 12, 31), 1.0),
        (date(2026, 7, 2), 183 / 365),
        (date(2028, 1, 1), 1 / 366),
        (date(2028, 2, 29), 60 / 366),
        (date(2028, 12, 31), 1.0),
    ],
)
def test_elapsed_fraction(day: date, expected: float) -> None:
    assert budget.elapsed_fraction(day) == pytest.approx(expected)


def test_target_scale_switch() -> None:
    day = date(2026, 7, 2)
    assert budget.target_scale(day, prorate=True) == budget.elapsed_fraction(day)
    assert budget.target_scale(day, prorate=False) == 1.0


def _status_for(as_of: date, *, prorate: bool) -> IndicatorStatus:
    # Allocated 1000, executed 300 on 10 January: the rate is 0.30 on both dates.
    entries = [entry(1, allocated=1000)]
    executions = [spent(1, date(2026, 1, 10), 300)]
    (definition,) = budget.indicator_definitions()
    (value,) = budget.indicator_values(entries, executions, as_of)
    assert value.value == pytest.approx(0.30)
    targets: dict[TargetKey, Target] = {
        (definition.code, value.dimension): Target(warning_value=0.9, critical_value=0.5)
    }
    reading = evaluate(
        definition, value, targets, target_scale=budget.target_scale(as_of, prorate=prorate)
    )
    return reading.status


def test_prorated_status_differs_between_january_and_december() -> None:
    assert _status_for(date(2026, 1, 15), prorate=True) is IndicatorStatus.OK
    assert _status_for(date(2026, 12, 15), prorate=True) is IndicatorStatus.CRITICAL


def test_status_without_prorating_uses_the_target_unchanged() -> None:
    assert _status_for(date(2026, 1, 15), prorate=False) is IndicatorStatus.CRITICAL
    assert _status_for(date(2026, 12, 15), prorate=False) is IndicatorStatus.CRITICAL


# --------------------------------------------------------------------------------------------
# Currencies
# --------------------------------------------------------------------------------------------


def test_allow_list_and_default() -> None:
    assert dict(CURRENCY_DECIMALS) == {"BRL": 2, "USD": 2, "EUR": 2}
    assert DEFAULT_CURRENCY == "BRL"
    assert DEFAULT_CURRENCY in CURRENCY_DECIMALS
    with pytest.raises(TypeError):
        CURRENCY_DECIMALS["XXX"] = 2


@pytest.mark.parametrize(
    ("code", "valid"),
    [("BRL", True), ("USD", True), ("EUR", True), ("GBP", False), ("brl", False), ("", False)],
)
def test_is_valid_currency(code: str, valid: bool) -> None:
    assert budget.is_valid_currency(code) is valid


def test_currency_decimals() -> None:
    assert budget.currency_decimals("USD") == 2
    with pytest.raises(InvalidCurrencyError) as info:
        budget.currency_decimals("GBP")
    assert info.value.code == "INVALID_CURRENCY"


@pytest.fixture
def other_decimals(monkeypatch: pytest.MonkeyPatch) -> None:
    """The allow-list with a currency of 0 decimals (JPY) and one of 3 decimals (KWD) added."""
    widened = MappingProxyType({**CURRENCY_DECIMALS, "JPY": 0, "KWD": 3})
    monkeypatch.setattr(budget, "CURRENCY_DECIMALS", widened)


@pytest.mark.usefixtures("other_decimals")
@pytest.mark.parametrize(
    ("minor", "currency", "text"),
    [
        (0, "JPY", "0"),
        (1234567, "JPY", "1234567"),
        (-5, "JPY", "-5"),
        (0, "KWD", "0.000"),
        (5, "KWD", "0.005"),
        (1234567, "KWD", "1234.567"),
        (-1500, "KWD", "-1.500"),
        (12345, "BRL", "123.45"),
    ],
)
def test_minor_to_decimal_with_zero_and_three_decimal_currencies(
    minor: int, currency: str, text: str
) -> None:
    assert budget.currency_decimals(currency) == {"JPY": 0, "KWD": 3, "BRL": 2}[currency]
    assert str(budget.minor_to_decimal(minor, currency)) == text
    assert budget.minor_to_decimal(minor, currency) == Decimal(text)
    assert budget.decimal_to_minor(Decimal(text), currency) == minor


@pytest.mark.usefixtures("other_decimals")
@pytest.mark.parametrize(
    ("text", "currency", "minor"),
    [
        ("1234", "JPY", 1234),
        ("1234.0", "JPY", 1234),
        ("1E+3", "JPY", 1000),
        ("1.5", "KWD", 1500),
        ("1.234", "KWD", 1234),
        ("0.0050", "KWD", 5),
        ("2", "KWD", 2000),
    ],
)
def test_decimal_to_minor_with_zero_and_three_decimal_currencies(
    text: str, currency: str, minor: int
) -> None:
    assert budget.decimal_to_minor(Decimal(text), currency) == minor


@pytest.mark.usefixtures("other_decimals")
@pytest.mark.parametrize(
    ("text", "currency"), [("1234.5", "JPY"), ("0.1", "JPY"), ("1.2345", "KWD")]
)
def test_decimal_to_minor_refuses_more_decimals_than_the_currency_has(
    text: str, currency: str
) -> None:
    with pytest.raises(TooManyDecimalsError):
        budget.decimal_to_minor(Decimal(text), currency)


def test_the_extra_currencies_are_not_in_the_real_allow_list() -> None:
    assert not budget.is_valid_currency("JPY")
    assert not budget.is_valid_currency("KWD")


@pytest.mark.parametrize(
    ("minor", "currency", "text"),
    [
        (0, "BRL", "0.00"),
        (5, "BRL", "0.05"),
        (12345, "USD", "123.45"),
        (-250, "EUR", "-2.50"),
        (2**60 + 7, "BRL", "11529215046068469.83"),
    ],
)
def test_minor_to_decimal_is_exact(minor: int, currency: str, text: str) -> None:
    assert budget.minor_to_decimal(minor, currency) == Decimal(text)
    assert str(budget.minor_to_decimal(minor, currency)) == text
    assert budget.decimal_to_minor(Decimal(text), currency) == minor


@pytest.mark.parametrize(
    ("text", "minor"),
    [
        ("1", 100),
        ("1.5", 150),
        ("0.01", 1),
        ("-0.01", -1),
        ("1E+2", 10000),
        ("12345678901234567890.12", 1234567890123456789012),
    ],
)
def test_decimal_to_minor(text: str, minor: int) -> None:
    assert budget.decimal_to_minor(Decimal(text), "BRL") == minor


@pytest.mark.parametrize("text", ["1.005", "0.001", "-3.141"])
def test_decimal_to_minor_rejects_too_many_decimals(text: str) -> None:
    with pytest.raises(TooManyDecimalsError) as info:
        budget.decimal_to_minor(Decimal(text), "BRL")
    assert info.value.code == "TOO_MANY_DECIMALS"


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity"])
def test_decimal_to_minor_rejects_non_finite(text: str) -> None:
    with pytest.raises(InvalidAmountError) as info:
        budget.decimal_to_minor(Decimal(text), "BRL")
    assert info.value.code == "INVALID_AMOUNT"


def test_conversions_reject_unknown_currency() -> None:
    with pytest.raises(InvalidCurrencyError):
        budget.minor_to_decimal(100, "GBP")
    with pytest.raises(InvalidCurrencyError):
        budget.decimal_to_minor(Decimal("1.00"), "GBP")


# --------------------------------------------------------------------------------------------
# Indicator definition
# --------------------------------------------------------------------------------------------


def test_definition_is_registered_in_the_real_registry() -> None:
    registry = build_registry()
    assert "BUD_EXEC_RATE" in registry
    definition = registry.get("BUD_EXEC_RATE")
    assert definition.unit is UnitKind.RATIO
    assert definition.direction is Direction.HIGHER_IS_BETTER
    assert definition.module is Module.BUDGET
    assert definition.dimension_keys == ("currency", "source")
    assert definition.source == "R24"
    assert definition in budget.indicator_definitions()


def test_indicator_values_context_dimension_and_order() -> None:
    entries = [
        entry(1, source=OPCW, allocated=400),
        entry(2, source=DIRSA, allocated=None),
        entry(3, source=DIRSA, currency="USD", allocated=0),
        entry(4, source=DIRSA, currency="EUR", allocated=1000),
    ]
    executions = [spent(1, date(2026, 3, 1), 100), spent(4, date(2026, 3, 1), 250)]
    values = budget.indicator_values(entries, executions, date(2026, 6, 1))
    assert [(v.code, v.dimension, v.value) for v in values] == [
        ("BUD_EXEC_RATE", "currency=BRL;source=DIRSA", None),
        ("BUD_EXEC_RATE", "currency=BRL;source=OPCW_TRUST_FUND", 0.25),
        ("BUD_EXEC_RATE", "currency=EUR;source=DIRSA", 0.25),
        ("BUD_EXEC_RATE", "currency=USD;source=DIRSA", None),
    ]
    assert values[0].context is None
    assert values[1].context == {"allocated_minor": 400.0, "executed_minor": 100.0}
    assert values[3].context == {"allocated_minor": 0.0, "executed_minor": 0.0}
    for value in values:
        build_registry().get("BUD_EXEC_RATE").validate_dimension(value.dimension)


def test_without_targets_the_status_is_no_target() -> None:
    definition = build_registry().get("BUD_EXEC_RATE")
    executions = [spent(1, date(2026, 2, 2), 100)]
    (value,) = budget.indicator_values([entry(1)], executions, date(2026, 3, 3))
    assert evaluate(definition, value, {}).status is IndicatorStatus.NO_TARGET
    (nodata,) = budget.indicator_values([entry(1, allocated=None)], [], date(2026, 3, 3))
    assert evaluate(definition, nodata, {}).status is IndicatorStatus.NO_DATA
