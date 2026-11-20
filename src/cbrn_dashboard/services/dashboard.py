# SPDX-License-Identifier: GPL-3.0-or-later
"""Dashboard service: the figures of the overview page for an as-of date (PLAN.md T6.5, 5.4).

Qt-free and read-only. Everything is recomputed from the module services on every call (R05: the
dashboard is re-evaluated on every start and on every change); nothing is cached or stored, and no
composite readiness score is computed (deferred item X4).

The result is codes and numbers only; the UI turns codes into words:

* :class:`Tile` - one per reading of ``IndicatorService.evaluate`` (same order), with the unit, the
  direction, the value, the status and the thresholds actually in force (the pro-rated ones for
  ``BUD_EXEC_RATE``). ``INFRA_AVAILABLE`` carries ``{"in_service": n}`` as context.
* alert counts per severity (always the three keys),
* :class:`ChartSpec` - a Qt-free chart description; category and series KEYS are codes (PPE level,
  asset type code, edition code, funding source code, ``allocated``/``executed``). The UI converts
  it to the chart adapter's data and offers the same numbers as a table.

Charts, in this fixed order: ``personnel_valid_by_level``, ``infrastructure_availability``,
``exercises_by_edition``, then one ``budget_<CUR>`` chart per currency that has an entry in the
fiscal year of the as-of date, and last ``stock_antidotes_by_item`` (only when a stock service is
wired and at least one antidote or decontaminant type has a value). Currencies are never mixed in
one chart (D15). Budget amounts in a
chart are MAJOR units as floats for display only; the exact integers stay in the tiles' context and
on the budget page. A chart without data is still present, with empty categories.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.budget import BudgetTotal, fiscal_year_of, minor_to_decimal
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorReading,
    IndicatorStatus,
    Module,
    UnitKind,
    decode_dimension,
)
from cbrn_dashboard.domain.personnel import PpeLevel, is_active
from cbrn_dashboard.domain.stock import ANTIDOTE_PAGE_CATEGORIES
from cbrn_dashboard.services.alerts import AlertService
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.services.stock import StockService

__all__ = [
    "CHART_BUDGET_PREFIX",
    "CHART_EXERCISES",
    "CHART_INFRASTRUCTURE",
    "CHART_PERSONNEL",
    "CHART_STOCK",
    "MAX_EDITIONS",
    "ChartSpec",
    "DashboardData",
    "DashboardService",
    "SeriesSpec",
    "Tile",
]

#: Chart keys (the UI maps them to titles).
CHART_PERSONNEL = "personnel_valid_by_level"
CHART_INFRASTRUCTURE = "infrastructure_availability"
CHART_EXERCISES = "exercises_by_edition"
#: The budget chart of currency ``CUR`` has the key ``budget_CUR``.
CHART_BUDGET_PREFIX = "budget_"
#: Valid stock and minimum per antidote and decontaminant type (series ``stock_valid`` and
#: ``stock_minimum``); present only when at least one such type has a value (D36).
CHART_STOCK = "stock_antidotes_by_item"

#: The exercises chart shows at most this many of the most recent finished editions.
MAX_EDITIONS = 12

_VALID_CERTIFICATES = "PERS_CERT_VALID"
_STOCK_VALID_QTY = "STOCK_VALID_QTY"
_EMPTY: Mapping[str, float] = MappingProxyType({})


@dataclass(frozen=True)
class Tile:
    """One indicator reading for the dashboard: codes and numbers only."""

    code: str
    dimension: str
    dimension_parts: Mapping[str, str]
    module: Module
    unit: UnitKind
    direction: Direction
    value: float | None
    status: IndicatorStatus
    warning_value: float | None
    critical_value: float | None
    context: Mapping[str, float]


@dataclass(frozen=True)
class SeriesSpec:
    """One series of a chart: its code and one value per category (``None`` = not recorded)."""

    key: str
    values: tuple[float | None, ...]


@dataclass(frozen=True)
class ChartSpec:
    """A Qt-free chart description; the keys are codes, never display text."""

    key: str
    categories: tuple[str, ...]
    series: tuple[SeriesSpec, ...]
    unit: UnitKind
    parameters: Mapping[str, str]


@dataclass(frozen=True)
class DashboardData:
    """Everything the dashboard shows for one as-of date."""

    as_of: date
    tiles: tuple[Tile, ...]
    alert_counts: Mapping[Severity, int]
    charts: tuple[ChartSpec, ...]


def _read_only(values: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(values))


def _major(minor: int | None, currency: str) -> float | None:
    """Minor units as a float number of major units, for display only."""
    return None if minor is None else float(minor_to_decimal(minor, currency))


class DashboardService:
    """Tiles, alert counts and chart descriptions of the dashboard for an as-of date."""

    def __init__(
        self,
        *,
        indicators: IndicatorService,
        alerts: AlertService,
        personnel: PersonnelService,
        infrastructure: InfrastructureService,
        exercises: ExercisesService,
        budget: BudgetService,
        stock: StockService | None = None,
    ) -> None:
        self._indicators = indicators
        self._alerts = alerts
        self._personnel = personnel
        self._infrastructure = infrastructure
        self._exercises = exercises
        self._budget = budget
        self._stock = stock

    # ----- the public view

    def data(self, as_of: date) -> DashboardData:
        """The dashboard for ``as_of``, recomputed from the services (nothing is cached)."""
        readings = self._indicators.evaluate(as_of)  # once: the alert counts reuse these readings
        tiles = tuple(self._tile(reading) for reading in readings)
        counts = self._alerts.counts(as_of, readings=readings)
        return DashboardData(
            as_of=as_of,
            tiles=tiles,
            alert_counts=MappingProxyType({s: int(counts.get(s, 0)) for s in Severity}),
            charts=(
                self._personnel_chart(as_of, tiles),
                self._infrastructure_chart(as_of),
                self._exercises_chart(as_of),
                *self._budget_charts(as_of),
                *self._stock_charts(tiles),
            ),
        )

    # ----- tiles

    def _tile(self, reading: IndicatorReading) -> Tile:
        definition = self._indicators.definition(reading.code)
        context = _EMPTY if not reading.context else MappingProxyType(dict(reading.context))
        return Tile(
            code=reading.code,
            dimension=reading.dimension,
            dimension_parts=_read_only(decode_dimension(reading.dimension)),
            module=definition.module,
            unit=definition.unit,
            direction=definition.direction,
            value=reading.value,
            status=reading.status,
            warning_value=reading.warning_value,
            critical_value=reading.critical_value,
            context=context,
        )

    # ----- charts

    def _personnel_chart(self, as_of: date, tiles: tuple[Tile, ...]) -> ChartSpec:
        """Valid certificates per PPE level; empty when no person is active on ``as_of``."""
        staff = self._personnel.alert_inputs().staff
        if not any(is_active(person, as_of) for person in staff):
            return ChartSpec(
                CHART_PERSONNEL, (), (SeriesSpec("valid", ()),), UnitKind.COUNT, _read_only({})
            )
        levels = tuple(level.value for level in PpeLevel)
        values: dict[str, float | None] = dict.fromkeys(levels)
        for tile in tiles:
            level = tile.dimension_parts.get("level")
            if tile.code == _VALID_CERTIFICATES and level is not None and level in values:
                values[level] = tile.value
        return ChartSpec(
            key=CHART_PERSONNEL,
            categories=levels,
            series=(SeriesSpec("valid", tuple(values[level] for level in levels)),),
            unit=UnitKind.COUNT,
            parameters=_read_only({}),
        )

    def _infrastructure_chart(self, as_of: date) -> ChartSpec:
        """Available and in-service assets per asset type; empty when nothing is in service."""
        rows = sorted(self._infrastructure.availability(as_of), key=lambda row: row.type_code)
        if not any(row.in_service for row in rows):
            rows = []
        return ChartSpec(
            key=CHART_INFRASTRUCTURE,
            categories=tuple(row.type_code for row in rows),
            series=(
                SeriesSpec("available", tuple(float(row.available) for row in rows)),
                SeriesSpec("in_service", tuple(float(row.in_service) for row in rows)),
            ),
            unit=UnitKind.COUNT,
            parameters=_read_only({}),
        )

    def _exercises_chart(self, as_of: date) -> ChartSpec:
        """Participants and countries of the most recent editions ended on or before ``as_of``."""
        editions = self._exercises.history(as_of)[-MAX_EDITIONS:]
        return ChartSpec(
            key=CHART_EXERCISES,
            categories=tuple(edition.code for edition in editions),
            series=(
                SeriesSpec(
                    "participants",
                    tuple(
                        None if edition.participants is None else float(edition.participants)
                        for edition in editions
                    ),
                ),
                SeriesSpec(
                    "countries", tuple(float(len(edition.countries)) for edition in editions)
                ),
            ),
            unit=UnitKind.COUNT,
            parameters=_read_only({}),
        )

    def _stock_charts(self, tiles: tuple[Tile, ...]) -> tuple[ChartSpec, ...]:
        """Valid quantity and minimum per antidote or decontaminant type that has a value.

        Taken from the ``STOCK_VALID_QTY`` tiles, so the chart follows the emission rule (a type
        in use on the date or with a minimum). Without such a tile (or without a stock service)
        there is no stock chart at all: a fresh database shows no stock (D36, K22). The minimum
        is ``None`` (not recorded, D30) for a type without one. The series keys are
        ``stock_valid`` and ``stock_minimum``, never ``valid`` (that is the personnel series).
        """
        if self._stock is None:
            return ()
        wanted = {category.value for category in ANTIDOTE_PAGE_CATEGORIES}
        rows = [
            tile
            for tile in tiles
            if tile.code == _STOCK_VALID_QTY
            and tile.dimension_parts.get("category") in wanted
            and "item" in tile.dimension_parts
        ]
        if not rows:
            return ()
        minimum_of: list[float | None] = []
        for tile in rows:
            minimum = tile.context.get("minimum")
            minimum_of.append(None if minimum is None else float(minimum))
        return (
            ChartSpec(
                key=CHART_STOCK,
                categories=tuple(tile.dimension_parts["item"] for tile in rows),
                series=(
                    SeriesSpec("stock_valid", tuple(tile.value for tile in rows)),
                    SeriesSpec("stock_minimum", tuple(minimum_of)),
                ),
                unit=UnitKind.COUNT,
                parameters=_read_only({}),
            ),
        )

    def _budget_charts(self, as_of: date) -> tuple[ChartSpec, ...]:
        """One chart per currency of the as-of date's fiscal year; currencies never mix (D15)."""
        year = fiscal_year_of(as_of)
        by_currency: dict[str, list[BudgetTotal]] = {}
        for total in self._budget.totals_for_year(year, as_of):
            by_currency.setdefault(total.currency, []).append(total)
        charts: list[ChartSpec] = []
        for currency in sorted(by_currency):
            totals = sorted(by_currency[currency], key=lambda total: total.source_code)
            charts.append(
                ChartSpec(
                    key=f"{CHART_BUDGET_PREFIX}{currency}",
                    categories=tuple(total.source_code for total in totals),
                    series=(
                        SeriesSpec(
                            "allocated",
                            tuple(_major(total.allocated_minor, currency) for total in totals),
                        ),
                        SeriesSpec(
                            "executed",
                            tuple(_major(total.executed_minor, currency) for total in totals),
                        ),
                    ),
                    unit=UnitKind.CURRENCY,
                    parameters=_read_only({"currency": currency, "fiscal_year": str(year)}),
                )
            )
        return tuple(charts)
