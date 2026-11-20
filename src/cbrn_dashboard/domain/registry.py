# SPDX-License-Identifier: GPL-3.0-or-later
"""Composition point of the indicator registry (PLAN T1.6).

Each module owns its indicator definitions and exposes one ``indicator_definitions`` function.
This file only lists those providers; it never defines an indicator itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from cbrn_dashboard.domain import budget, exercises, infrastructure, personnel, stock
from cbrn_dashboard.domain.indicators import IndicatorDefinition, IndicatorRegistry

IndicatorProvider = Callable[[], Sequence[IndicatorDefinition]]

# One provider per line, in display order: the personnel, infrastructure, exercises, budget and
# stock modules each contribute their ``indicator_definitions`` function. A new module adds exactly
# one line here (import at the top of the file, entry below).
PROVIDERS: tuple[IndicatorProvider, ...] = (
    personnel.indicator_definitions,
    infrastructure.indicator_definitions,
    exercises.indicator_definitions,
    budget.indicator_definitions,
    stock.indicator_definitions,
)


def build_registry(providers: Iterable[IndicatorProvider] = PROVIDERS) -> IndicatorRegistry:
    """Register every definition of every provider, in order; duplicate codes are rejected."""
    registry = IndicatorRegistry()
    for provider in providers:
        for definition in provider():
            registry.register(definition)
    return registry
