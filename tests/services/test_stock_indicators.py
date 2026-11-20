# SPDX-License-Identifier: GPL-3.0-or-later
"""The stock indicators through the services (PLAN.md T11.7): values, targets, dashboard chart.

All data is fictitious and is written THROUGH the stock service. Expected numbers are worked out by
hand: as of 2026-03-05 (the date of the fixture clock), P11 = 90 days, so the window ends on
2026-06-03 (inclusive).
"""

from dataclasses import dataclass
from datetime import date

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.services.alerts import AlertService
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.dashboard import CHART_STOCK, DashboardService, SeriesSpec
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.services.stock import InitialReceipt, LotInput, StockService
from cbrn_dashboard.storage.db import DatabaseConnection

AS_OF = date(2026, 3, 5)
CHEMICAL = "ANTIDOTE_CHEMICAL"
BIOLOGICAL = "ANTIDOTE_BIOLOGICAL"
DECON = "DECONTAMINANT"
GLOVE = "GLOVE"


@dataclass
class Stack:
    stock: StockService
    indicators: IndicatorService
    dashboard: DashboardService
    with_stock: bool = True


def _stack(conn: DatabaseConnection, clock: FixedClock, *, with_stock: bool = True) -> Stack:
    def operator() -> str:
        return "op-demo"

    personnel = PersonnelService(conn, clock, operator)
    infrastructure = InfrastructureService(conn, clock, operator)
    exercises = ExercisesService(conn, clock, operator)
    budget = BudgetService(conn, clock, operator)
    stock = StockService(conn, clock, operator)
    wired = stock if with_stock else None
    indicators = IndicatorService(
        conn,
        clock,
        operator,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
        stock=wired,
    )
    alerts = AlertService(personnel=personnel, infrastructure=infrastructure, indicators=indicators)
    dashboard = DashboardService(
        indicators=indicators,
        alerts=alerts,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
        stock=wired,
    )
    return Stack(stock, indicators, dashboard, with_stock)


@pytest.fixture
def stack(db: DatabaseConnection, clock: FixedClock) -> Stack:
    return _stack(db, clock)


def _type_id(stack: Stack, code: str) -> int:
    found = stack.stock.get_type_by_code(code)
    assert found is not None
    return found.id


def _lot(stack: Stack, code: str, lot_code: str, expires_on: str | None, quantity: int) -> int:
    return stack.stock.create_lot(
        LotInput(type_id=_type_id(stack, code), lot_code=lot_code, expires_on=expires_on),
        InitialReceipt(moved_on="2026-01-01", quantity=quantity),
    )


def _stock_readings(stack: Stack, as_of: date = AS_OF) -> dict[tuple[str, str], float | None]:
    return {
        (r.code, r.dimension): r.value
        for r in stack.indicators.evaluate(as_of)
        if r.code.startswith("STOCK_")
    }


def _seed(stack: Stack) -> None:
    _lot(stack, CHEMICAL, "DEMO-L001", "2026-06-03", 10)  # the last day of the window: expiring
    _lot(stack, CHEMICAL, "DEMO-L002", "2026-03-04", 4)  # expired yesterday
    _lot(stack, CHEMICAL, "DEMO-L003", "2026-06-04", 7)  # one day after the window: valid
    stack.stock.set_minimum(_type_id(stack, BIOLOGICAL), 20)  # a minimum and no lot
    _lot(stack, DECON, "DEMO-L004", "2027-01-01", 3)
    stack.stock.deactivate_type(_type_id(stack, DECON))  # inactive, still has stock
    _lot(stack, GLOVE, "DEMO-L005", None, 100)  # a second category


def test_a_database_with_no_stock_gives_no_stock_value(stack: Stack) -> None:
    assert _stock_readings(stack) == {}
    assert stack.dashboard.data(AS_OF).charts[-1].key != CHART_STOCK
    assert not [t for t in stack.dashboard.data(AS_OF).tiles if t.code.startswith("STOCK_")]


def test_the_values_of_a_fictitious_stock_match_the_hand_computed_numbers(stack: Stack) -> None:
    _seed(stack)
    assert _stock_readings(stack) == {
        ("STOCK_VALID_QTY", f"category=antidote;item={BIOLOGICAL}"): 0.0,
        ("STOCK_VALID_QTY", f"category=antidote;item={CHEMICAL}"): 17.0,
        ("STOCK_VALID_QTY", f"category=decontaminant;item={DECON}"): 3.0,
        ("STOCK_VALID_QTY", f"category=ppe;item={GLOVE}"): 100.0,
        ("STOCK_LOTS_EXPIRING", "category=antidote"): 1.0,
        ("STOCK_LOTS_EXPIRING", "category=decontaminant"): 0.0,
        ("STOCK_LOTS_EXPIRING", "category=ppe"): 0.0,
        ("STOCK_LOTS_EXPIRED", "category=antidote"): 1.0,
        ("STOCK_LOTS_EXPIRED", "category=decontaminant"): 0.0,
        ("STOCK_LOTS_EXPIRED", "category=ppe"): 0.0,
        ("STOCK_TYPES_BELOW_MIN", "category=antidote"): 1.0,
    }


def test_the_window_is_inclusive_at_its_last_day(stack: Stack) -> None:
    _seed(stack)
    key = ("STOCK_LOTS_EXPIRING", "category=antidote")
    # from 2026-03-05 the window ends on 2026-06-03: only DEMO-L001 (that day) is inside
    assert _stock_readings(stack, AS_OF)[key] == 1.0
    # from 2026-03-06 it ends on 2026-06-04: DEMO-L003 (that day) joins it
    assert _stock_readings(stack, date(2026, 3, 6))[key] == 2.0


def test_a_target_on_the_valid_quantity_gives_a_status_and_the_minimum_does_not(
    stack: Stack,
) -> None:
    _seed(stack)
    dimension = f"category=antidote;item={BIOLOGICAL}"
    # the minimum (20) alone gives no status: the value 0 has no target
    before = {(r.code, r.dimension): r.status for r in stack.indicators.evaluate(AS_OF)}
    assert before[("STOCK_VALID_QTY", dimension)] is IndicatorStatus.NO_TARGET
    stack.indicators.set_target("STOCK_VALID_QTY", dimension, warning_value=10, critical_value=5)
    after = {(r.code, r.dimension): r.status for r in stack.indicators.evaluate(AS_OF)}
    assert after[("STOCK_VALID_QTY", dimension)] is IndicatorStatus.CRITICAL  # 0 <= 5
    other = f"category=antidote;item={CHEMICAL}"
    assert after[("STOCK_VALID_QTY", other)] is IndicatorStatus.NO_TARGET


def test_the_stock_chart_has_the_valid_quantity_and_the_minimum(stack: Stack) -> None:
    _seed(stack)
    [chart] = [c for c in stack.dashboard.data(AS_OF).charts if c.key == CHART_STOCK]
    # antidotes and decontaminants only, with a value; the glove (ppe) is not charted
    assert chart.categories == (BIOLOGICAL, CHEMICAL, DECON)
    assert chart.series == (
        SeriesSpec("stock_valid", (0.0, 17.0, 3.0)),
        SeriesSpec("stock_minimum", (20.0, None, None)),
    )
    assert "valid" not in {s.key for s in chart.series}


def test_without_a_stock_service_nothing_changes(db: DatabaseConnection, clock: FixedClock) -> None:
    bare = _stack(db, clock, with_stock=False)
    _seed(bare)
    assert _stock_readings(bare) == {}
    assert all(c.key != CHART_STOCK for c in bare.dashboard.data(AS_OF).charts)
