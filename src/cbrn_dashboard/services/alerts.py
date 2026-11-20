# SPDX-License-Identifier: GPL-3.0-or-later
"""Alert service: the alerts as of a date, computed on demand (PLAN.md T6.2, section 5.5).

Qt-free and read-only. Alerts are never stored (X7: no acknowledgement or snooze): every call
gathers the inputs from the personnel and infrastructure services (the very same domain objects and
configuration-derived rules those services use for their own as-of views) and the readings from
:meth:`~cbrn_dashboard.services.indicators.IndicatorService.evaluate`, then calls the rule functions
of ``domain/alerts.py``. No rule is implemented here, so the alerts, the pages and the indicators
cannot disagree. A past as-of date gives the alerts of that date from the records known today.
The stock alerts (T11.8) come from ``stock.alert_inputs()`` and the P11 window of the stock service;
without a stock service there are none.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from cbrn_dashboard.domain import alerts as rules
from cbrn_dashboard.domain.alerts import Alert, Severity
from cbrn_dashboard.domain.indicators import IndicatorReading, IndicatorRegistry, Module
from cbrn_dashboard.domain.stock import Lot, Movement, StockRules, StockType
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.services.stock import StockService

__all__ = ["AlertService"]


class AlertService:
    """The alerts of PLAN 5.5 for an as-of date, sorted by severity and then due date."""

    def __init__(
        self,
        *,
        personnel: PersonnelService,
        infrastructure: InfrastructureService,
        indicators: IndicatorService,
        stock: StockService | None = None,
    ) -> None:
        self._personnel = personnel
        self._infrastructure = infrastructure
        self._indicators = indicators
        self._stock = stock

    def alerts(
        self, as_of: date, *, readings: Sequence[IndicatorReading] | None = None
    ) -> list[Alert]:
        """Every alert on ``as_of``: critical first, then by due date (undated last).

        ``readings`` are the indicator readings of ``as_of`` when the caller has just evaluated
        them (the dashboard does); without them they are evaluated here. They are never kept.
        """
        people = self._personnel.alert_inputs()
        assets = self._infrastructure.alert_inputs()
        stock_types: tuple[StockType, ...] = ()
        stock_lots: tuple[Lot, ...] = ()
        stock_movements: tuple[Movement, ...] = ()
        stock_rules = StockRules()
        if self._stock is not None:
            stock_types, stock_lots, stock_movements = self._stock.alert_inputs()
            stock_rules = self._stock.stock_rules()
        return rules.all_alerts(
            staff=people.staff,
            certs=people.certificates,
            personnel_rules=people.rules,
            assets=assets.assets,
            asset_types=assets.types,
            status_events=assets.status_events,
            maintenance=assets.maintenance,
            infrastructure_rules=assets.rules,
            readings=self._indicators.evaluate(as_of) if readings is None else list(readings),
            registry=self._registry(),
            d=as_of,
            stock_types=stock_types,
            stock_lots=stock_lots,
            stock_movements=stock_movements,
            stock_rules=stock_rules,
        )

    def _registry(self) -> IndicatorRegistry:
        """The indicator service's registry, rebuilt from its public ``definitions()``."""
        registry = IndicatorRegistry()
        for definition in self._indicators.definitions():
            registry.register(definition)
        return registry

    def alerts_filtered(
        self,
        as_of: date,
        *,
        module: Module | None = None,
        severity: Severity | None = None,
    ) -> list[Alert]:
        """:meth:`alerts` restricted to one module and/or one severity (order kept)."""
        return [
            alert
            for alert in self.alerts(as_of)
            if (module is None or alert.module is module)
            and (severity is None or alert.severity is severity)
        ]

    def counts(
        self, as_of: date, *, readings: Sequence[IndicatorReading] | None = None
    ) -> Mapping[Severity, int]:
        """The number of alerts per severity on ``as_of`` (always all three keys).

        ``readings`` as in :meth:`alerts`.
        """
        return rules.count_by_severity(self.alerts(as_of, readings=readings))

    def has_actionable(self, as_of: date) -> bool:
        """True when at least one alert on ``as_of`` is a warning or critical (not info only)."""
        return rules.has_actionable(self.alerts(as_of))
