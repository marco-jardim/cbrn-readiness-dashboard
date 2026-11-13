# SPDX-License-Identifier: GPL-3.0-or-later
"""Composition point of the indicator registry (PLAN T1.6).

Each module owns its indicator definitions and exposes one ``indicator_definitions`` function.
This file only lists those providers; it never defines an indicator itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from cbrn_dashboard.domain import budget, exercises
from cbrn_dashboard.domain.indicators import IndicatorDefinition, IndicatorRegistry

IndicatorProvider = Callable[[], Sequence[IndicatorDefinition]]

# One provider per line, in display order. T2.2, T3.2, T4.3 and T5.2 each add exactly one line
# here importing their module's ``indicator_definitions`` function (import at the top of the file,
# entry below). Empty until those tasks land.
PROVIDERS: tuple[IndicatorProvider, ...] = (
    exercises.indicator_definitions,
    budget.indicator_definitions,
)


def build_registry(providers: Iterable[IndicatorProvider] = PROVIDERS) -> IndicatorRegistry:
    """Register every definition of every provider, in order; duplicate codes are rejected."""
    registry = IndicatorRegistry()
    for provider in providers:
        for definition in provider():
            registry.register(definition)
    return registry
