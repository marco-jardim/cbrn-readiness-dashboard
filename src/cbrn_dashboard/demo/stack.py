# SPDX-License-Identifier: GPL-3.0-or-later
"""The module services over one demo connection, for the generators that read across modules.

The targets and snapshots generators (PLAN.md T10.1) need the indicator service, which in turn needs
the four module services. They are built here once, all with the operator label ``DEMO`` and the
injected clock, so everything those generators write is validated, logged and attributed exactly
like the data of the module generators.

Qt-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.services.stock import StockService

if TYPE_CHECKING:
    from cbrn_dashboard.demo import DemoContext

__all__ = ["OPERATOR", "DemoServices", "build_services"]

#: Operator label written to the change log for every row the cross-module generators create.
OPERATOR = "DEMO"


@dataclass(frozen=True)
class DemoServices:
    """The services the cross-module generators use."""

    infrastructure: InfrastructureService
    budget: BudgetService
    indicators: IndicatorService
    stock: StockService | None = None


def _operator() -> str:
    return OPERATOR


def build_services(ctx: DemoContext) -> DemoServices:
    """The module services and the indicator service over ``ctx.conn`` and ``ctx.clock``."""
    personnel = PersonnelService(ctx.conn, ctx.clock, _operator)
    infrastructure = InfrastructureService(ctx.conn, ctx.clock, _operator)
    exercises = ExercisesService(ctx.conn, ctx.clock, _operator)
    budget = BudgetService(ctx.conn, ctx.clock, _operator)
    stock = StockService(ctx.conn, ctx.clock, _operator)
    indicators = IndicatorService(
        ctx.conn,
        ctx.clock,
        _operator,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
        stock=stock,
    )
    return DemoServices(
        infrastructure=infrastructure, budget=budget, indicators=indicators, stock=stock
    )
