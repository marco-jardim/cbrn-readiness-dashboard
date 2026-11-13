# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo data for the budget module (PLAN.md T5.5, D25, D15, I07).

Everything here is fictitious. Every amount comes from ``ctx.rng`` (a ``random.Random`` seeded per
generator), every date is computed from ``ctx.today`` (the injected clock's date) and nothing is
read from a real source: no real figure of any budget is used. Money is always whole minor units
(integers); no float is ever used for an amount and no currency is converted.

What is created (everything goes THROUGH ``services.budget.BudgetService``, so every row is
validated and written to the change log with the operator label ``DEMO``):

* one user-defined funding source, ``DEMO-SRC-A``, next to the two built-in ones;
* budget entries for the current fiscal year of ``ctx.today`` and the three before it, for both
  built-in sources and the DEMO source; the OPCW trust fund has entries in BRL AND in USD, so the
  totals keep two currencies apart for the same source and year (D15);
* several DATED execution rows per entry, spread over its fiscal year. In the current fiscal year
  all but one row are dated on or before ``ctx.today``; the last one is dated after it, so a reading
  as of today visibly ignores it. The exception is 31 December: a row must stay inside its entry's
  fiscal year, no day of it is left after today, so there is no row after today on that date.
  Every executed total stays at or below the allocation, and the
  executed fractions vary, so some sources fall below a mid-year pro-rated target and others above;
* ONE entry with no allocated amount that still has execution rows: the USD entry of the DEMO
  source in the current fiscal year, alone in its (year, source, currency) group, so
  ``BUD_EXEC_RATE`` is "No data" for that group.

Every description and label starts with ``DEMO``.

Qt-free.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

from cbrn_dashboard.services.budget import BudgetService, EntryInput, SourceInput

if TYPE_CHECKING:
    # The package imports this module to register it, so DemoContext is only needed for typing.
    from cbrn_dashboard.demo import DemoContext

__all__ = ["DEMO_SOURCE_CODE", "FISCAL_YEARS_BACK", "OPERATOR", "generate"]

#: Operator label written to the change log for every row this generator creates.
OPERATOR = "DEMO"

#: Code of the user-defined demo funding source.
DEMO_SOURCE_CODE = "DEMO-SRC-A"

#: How many fiscal years before the current one get entries.
FISCAL_YEARS_BACK = 3

_UNIT = 100  # amounts are multiples of 100 minor units (whole currency units): round-ish
_ALLOCATION_STEP = 100_000  # allocations are multiples of 1,000.00 of the currency


@dataclass(frozen=True)
class _Plan:
    """One entry to create in every fiscal year (or only in the current one)."""

    source_code: str
    currency: str
    description: str
    current_year_only: bool = False
    no_allocation: bool = False


# The order is the creation order. Descriptions are unique within (source, currency).
_PLAN: tuple[_Plan, ...] = (
    _Plan("DIRSA", "BRL", "DEMO - DIRSA annual allocation"),
    _Plan("OPCW_TRUST_FUND", "BRL", "DEMO - local counterpart"),
    _Plan("OPCW_TRUST_FUND", "USD", "DEMO - trust fund contribution"),
    _Plan(DEMO_SOURCE_CODE, "BRL", "DEMO - equipment"),
    _Plan(DEMO_SOURCE_CODE, "BRL", "DEMO - training"),
    _Plan(
        DEMO_SOURCE_CODE,
        "USD",
        "DEMO - pending allocation",
        current_year_only=True,
        no_allocation=True,
    ),
)

# Share (percent of the allocation) executed up to today in the current fiscal year: alternating
# a low and a high band makes some groups fall below a mid-year pro-rated target and others above.
_CURRENT_YEAR_BANDS: tuple[tuple[int, int], ...] = ((4, 12), (30, 62))
_PAST_YEAR_PERCENT = (85, 100)
_FUTURE_PERCENT = (3, 10)  # the row dated after today, in percent of the allocation


def _split(total_units: int, count: int, rng: random.Random) -> list[int]:
    """Split ``total_units`` into ``count`` positive parts with random proportions (exact sum)."""
    weights = [rng.randint(1, 10) for _ in range(count)]
    weight_sum = sum(weights)
    parts = [total_units * weight // weight_sum for weight in weights[:-1]]
    parts.append(total_units - sum(parts))
    return parts


def _days_of_year(year: int) -> int:
    return (date(year + 1, 1, 1) - date(year, 1, 1)).days


def generate(ctx: DemoContext) -> None:
    """Create the demo funding source, entries and execution rows (see the module docstring)."""
    # Imported here, not at the top: the package imports this module while it is still being
    # initialised, and these two helpers are defined in the package itself.
    from cbrn_dashboard.demo import assert_demo_identifier

    service = BudgetService(ctx.conn, ctx.clock, lambda: OPERATOR)
    rng = ctx.rng
    current_year = ctx.today.year

    assert_demo_identifier(DEMO_SOURCE_CODE)
    labels = (
        "DEMO - fonte A (fictícia)",
        "DEMO - source A (fictitious)",
        "DEMO - fuente A (ficticia)",
    )
    for label in labels:
        assert_demo_identifier(label)
    service.create_source(
        SourceInput(
            code=DEMO_SOURCE_CODE,
            label_pt_br=labels[0],
            label_en_us=labels[1],
            label_es_es=labels[2],
        )
    )
    source_ids: dict[str, int] = {}
    for code in ("DIRSA", "OPCW_TRUST_FUND", DEMO_SOURCE_CODE):
        source = service.get_source_by_code(code)
        if source is None:  # pragma: no cover - the built-in sources exist after migration
            msg = f"funding source {code} is missing"
            raise LookupError(msg)
        source_ids[code] = source.id

    current_entries = 0
    for year in range(current_year - FISCAL_YEARS_BACK, current_year + 1):
        is_current = year == current_year
        for plan in _PLAN:
            if plan.current_year_only and not is_current:
                continue
            assert_demo_identifier(plan.description)
            # All amounts below are random and fictitious. They are NOT real budget figures.
            allocated = rng.randrange(50, 500) * _ALLOCATION_STEP
            allocated_units = allocated // _UNIT
            entry_id = service.create_entry(
                EntryInput(
                    fiscal_year=year,
                    source_id=source_ids[plan.source_code],
                    allocated_minor=None if plan.no_allocation else allocated,
                    currency=plan.currency,
                    description=plan.description,
                    notes="DEMO - fictitious data",
                )
            )
            first_day = date(year, 1, 1)
            if is_current:
                low, high = _CURRENT_YEAR_BANDS[current_entries % len(_CURRENT_YEAR_BANDS)]
                current_entries += 1
                percent = rng.randint(low, high)
                span = (ctx.today - first_day).days + 1  # days from 1 January up to and with today
                offsets = sorted(rng.sample(range(span), min(rng.randint(3, 6), span)))
                days = [first_day + timedelta(days=offset) for offset in offsets]
                amounts = _split(allocated_units * percent // 100, len(days), rng)
                remaining = (date(year, 12, 31) - ctx.today).days
                # One row after today: the as-of reading must ignore it. On 31 December there is
                # no day left in the fiscal year, so there is none.
                if remaining > 0:
                    days.append(ctx.today + timedelta(days=rng.randint(1, remaining)))
                    amounts.append(allocated_units * rng.randint(*_FUTURE_PERCENT) // 100)
            else:
                percent = rng.randint(*_PAST_YEAR_PERCENT)
                offsets = sorted(rng.sample(range(_days_of_year(year)), rng.randint(4, 8)))
                days = [first_day + timedelta(days=offset) for offset in offsets]
                amounts = _split(allocated_units * percent // 100, len(days), rng)
            for day, units in zip(days, amounts, strict=True):
                service.add_execution(entry_id, day, units * _UNIT, "DEMO - fictitious execution")
