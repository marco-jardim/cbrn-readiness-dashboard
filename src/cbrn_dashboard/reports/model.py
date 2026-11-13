# SPDX-License-Identifier: GPL-3.0-or-later
"""Report model: the content of a report for an as-of date (PLAN.md T8.5; D09, A11, R11-R13).

Qt-free and read-only. The model is codes and numbers only: no translated text (T8.6 renders the
document to PDF and translates the codes; the wording of the preliminary notice, P07, lives in the
translations). Two variants are built from the same figures:

* ``INTERNAL`` - the full report for the committee, DIRSA and the Air Force Command (R11, R12):
  header with the institution and unit names, the locally set handling notice, key figures, the
  indicator table, the alert summary and the two lists (staff identifiers needing retraining,
  overdue asset tags);
* ``ANONYMISED`` - the aggregated report for the OPCW Technical Secretariat (R13), made by
  :func:`cbrn_dashboard.reports.anonymise.anonymise` from the internal document: counts only, with
  small-count suppression (A11).

Every figure is a :class:`Cell`: a value, a stable key, a flag for figures computed from staff
records (``personnel_derived``; only those are suppressed) and, for totals, the keys of the cells
they are the sum of (``total_of``; the input of the secondary suppression). Charts hold the cells
of the document (the same keys), so that they can be rebuilt from the suppressed cells alone.

The threshold of the small-count suppression is read from the configuration and carried on the
document (``small_count_threshold``); the renderer prints "< threshold" for a suppressed cell.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from cbrn_dashboard import __version__
from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.dates import format_utc_timestamp
from cbrn_dashboard.domain.indicators import Direction, IndicatorStatus, Module, UnitKind
from cbrn_dashboard.domain.personnel import CertStatus, PpeLevel, is_active
from cbrn_dashboard.services.dashboard import (
    CHART_BUDGET_PREFIX,
    CHART_PERSONNEL,
    ChartSpec,
    DashboardData,
    DashboardService,
    Tile,
)
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection

__all__ = [
    "PRELIMINARY_NOTICE_CODE",
    "AlertCountRow",
    "AssetListRow",
    "Cell",
    "IndicatorRow",
    "KeyFigureGroup",
    "ReportBuilder",
    "ReportChart",
    "ReportDocument",
    "ReportHeader",
    "ReportSeries",
    "ReportVariant",
    "StaffListRow",
]

#: The code of the preliminary notice (I06, P07); the wording lives in the translations.
PRELIMINARY_NOTICE_CODE = "PRELIMINARY"

_PERS_CERT_VALID = "PERS_CERT_VALID"
_PERS_CERT_EXPIRING = "PERS_CERT_EXPIRING"
_PERS_RETRAINING = "PERS_RETRAINING_NEEDED"
_PERS_DEGREE = "PERS_DEGREE"
_EX_DAYS = "EX_DAYS_SINCE_LAST"
_EX_PARTICIPANTS = "EX_LAST_PARTICIPANTS"
_EX_COUNTRIES = "EX_LAST_COUNTRIES"


class ReportVariant(StrEnum):
    """The two variants of the report (R11-R13)."""

    INTERNAL = "INTERNAL"
    ANONYMISED = "ANONYMISED"


@dataclass(frozen=True)
class Cell:
    """One figure of the report.

    ``value`` is ``None`` when there is no figure OR when the cell is suppressed (a suppressed cell
    carries no value at all). ``personnel_derived`` marks figures computed from staff records;
    ``is_count`` marks counts (A11 suppresses personnel-derived COUNTS only). ``total_of`` lists
    the keys of the cells this one is the sum of.
    """

    key: str
    value: float | None
    personnel_derived: bool = False
    is_count: bool = True
    suppressed: bool = False
    total_of: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportHeader:
    """The header block; the anonymised variant blanks the names and the operator label."""

    institution_name: str
    unit_name: str
    as_of: date
    generated_at_utc: str
    app_version: str
    operator_label: str


@dataclass(frozen=True)
class KeyFigureGroup:
    """The key figures of one module."""

    module: Module
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class IndicatorRow:
    """One row of the indicator table; codes and numbers only."""

    code: str
    dimension: str
    dimension_parts: tuple[tuple[str, str], ...]
    module: Module
    unit: UnitKind
    direction: Direction
    value: Cell
    status: IndicatorStatus
    warning_value: float | None
    critical_value: float | None


@dataclass(frozen=True)
class AlertCountRow:
    """The number of open alerts of one severity."""

    severity: Severity
    cell: Cell


@dataclass(frozen=True)
class ReportSeries:
    """One series of a report chart: one cell per category."""

    key: str
    cells: tuple[Cell, ...]


@dataclass(frozen=True)
class ReportChart:
    """A chart built only from cells of the document; the keys are codes."""

    key: str
    categories: tuple[str, ...]
    series: tuple[ReportSeries, ...]
    unit: UnitKind
    parameters: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class StaffListRow:
    """A person needing retraining (internal variant only)."""

    identifier: str
    level: PpeLevel
    valid_until: date | None
    status: CertStatus


@dataclass(frozen=True)
class AssetListRow:
    """An asset with overdue maintenance (internal variant only)."""

    tag: str
    type_code: str
    due_on: date | None
    days_to_due: int | None


@dataclass(frozen=True)
class ReportDocument:
    """The report for one as-of date and variant."""

    variant: ReportVariant
    header: ReportHeader
    handling_notice: str
    is_demo: bool
    small_count_threshold: int
    key_figures: tuple[KeyFigureGroup, ...]
    indicators: tuple[IndicatorRow, ...]
    alert_summary: tuple[AlertCountRow, ...]
    charts: tuple[ReportChart, ...]
    retraining: tuple[StaffListRow, ...]
    overdue_assets: tuple[AssetListRow, ...]
    preliminary_notice_code: str = PRELIMINARY_NOTICE_CODE


# --------------------------------------------------------------------------- builder helpers


def _indicator_key(code: str, dimension: str) -> str:
    return f"indicator:{code}:{dimension}"


def _tile_value(tiles: tuple[Tile, ...], code: str, **parts: str) -> float | None:
    """The value of the first tile of ``code`` whose dimension parts include ``parts``."""
    for tile in tiles:
        if tile.code == code and all(tile.dimension_parts.get(k) == v for k, v in parts.items()):
            return tile.value
    return None


def _indicator_cell(tile: Tile) -> Cell:
    return Cell(
        key=_indicator_key(tile.code, tile.dimension),
        value=tile.value,
        personnel_derived=tile.module is Module.PERSONNEL,
        is_count=tile.unit is UnitKind.COUNT,
    )


def _indicator_row(tile: Tile, cell: Cell) -> IndicatorRow:
    return IndicatorRow(
        code=tile.code,
        dimension=tile.dimension,
        dimension_parts=tuple(sorted(tile.dimension_parts.items())),
        module=tile.module,
        unit=tile.unit,
        direction=tile.direction,
        value=cell,
        status=tile.status,
        warning_value=tile.warning_value,
        critical_value=tile.critical_value,
    )


def _personnel_figures(tiles: tuple[Tile, ...], active_staff: int) -> KeyFigureGroup:
    cells: list[Cell] = [
        Cell(key="kf:PERSONNEL:active_staff", value=float(active_staff), personnel_derived=True)
    ]
    for prefix, code in (
        ("valid", _PERS_CERT_VALID),
        ("expiring", _PERS_CERT_EXPIRING),
        ("retraining", _PERS_RETRAINING),
    ):
        for level in PpeLevel:
            cells.append(
                Cell(
                    key=f"kf:PERSONNEL:{prefix}:{level.value}",
                    value=_tile_value(tiles, code, level=level.value),
                    personnel_derived=True,
                )
            )
    parts: list[Cell] = [
        Cell(
            key=f"kf:PERSONNEL:degree_completed:{tile.dimension_parts['level']}",
            value=tile.value,
            personnel_derived=True,
        )
        for tile in tiles
        if tile.code == _PERS_DEGREE
        and tile.dimension_parts.get("status") == "completed"
        and "level" in tile.dimension_parts
    ]
    cells.extend(parts)
    if parts:
        known = [p.value for p in parts if p.value is not None]
        cells.append(
            Cell(
                key="kf:PERSONNEL:degree_completed_total",
                value=float(sum(known)) if len(known) == len(parts) else None,
                personnel_derived=True,
                total_of=tuple(p.key for p in parts),
            )
        )
    return KeyFigureGroup(Module.PERSONNEL, tuple(cells))


def _exercise_figures(tiles: tuple[Tile, ...]) -> KeyFigureGroup:
    """Days since the last edition, and the participants and countries of that edition's kind."""
    dated = [t for t in tiles if t.code == _EX_DAYS and t.value is not None]
    latest = min(dated, key=lambda t: t.value if t.value is not None else 0.0, default=None)
    kind = None if latest is None else latest.dimension_parts.get("kind")
    days = None if latest is None else latest.value
    participants = None if kind is None else _tile_value(tiles, _EX_PARTICIPANTS, kind=kind)
    countries = None if kind is None else _tile_value(tiles, _EX_COUNTRIES, kind=kind)
    return KeyFigureGroup(
        Module.EXERCISES,
        (
            Cell(key="kf:EXERCISES:days_since_last", value=days, is_count=False),
            Cell(key="kf:EXERCISES:last_participants", value=participants),
            Cell(key="kf:EXERCISES:last_countries", value=countries),
        ),
    )


def _budget_figures(charts: tuple[ChartSpec, ...]) -> KeyFigureGroup:
    """Allocated and executed amounts (major units, display only) per currency."""
    cells: list[Cell] = []
    for chart in charts:
        if not chart.key.startswith(CHART_BUDGET_PREFIX):
            continue
        currency = chart.parameters.get("currency", "")
        for series in chart.series:
            amounts = [v for v in series.values if v is not None]
            cells.append(
                Cell(
                    key=f"kf:BUDGET:{series.key}:{currency}",
                    value=round(sum(amounts), 2),
                    is_count=False,
                )
            )
    return KeyFigureGroup(Module.BUDGET, tuple(cells))


def _chart(spec: ChartSpec, indicator_cells: dict[str, Cell]) -> ReportChart:
    """A report chart whose cells are the document's cells (new ones only for chart-only data)."""
    series: list[ReportSeries] = []
    for source in spec.series:
        cells: list[Cell] = []
        for category, value in zip(spec.categories, source.values, strict=True):
            shared = None
            if spec.key == CHART_PERSONNEL and source.key == "valid":
                shared = indicator_cells.get(_indicator_key(_PERS_CERT_VALID, f"level={category}"))
            cells.append(
                shared
                if shared is not None
                else Cell(
                    key=f"chart:{spec.key}:{source.key}:{category}",
                    value=value,
                    personnel_derived=spec.key == CHART_PERSONNEL,
                    is_count=spec.unit is UnitKind.COUNT,
                )
            )
        series.append(ReportSeries(source.key, tuple(cells)))
    return ReportChart(
        key=spec.key,
        categories=spec.categories,
        series=tuple(series),
        unit=spec.unit,
        parameters=tuple(sorted(spec.parameters.items())),
    )


class ReportBuilder:
    """Builds the report document of an as-of date from the services (read-only)."""

    def __init__(
        self,
        *,
        conn: DatabaseConnection,
        clock: Clock,
        dashboard: DashboardService,
        personnel: PersonnelService,
        infrastructure: InfrastructureService,
        config_loader: Callable[[], ReadinessConfig],
        app_version: str | None = None,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._dashboard = dashboard
        self._personnel = personnel
        self._infrastructure = infrastructure
        self._config_loader = config_loader
        self._app_version = __version__ if app_version is None else app_version

    def build(self, as_of: date, variant: ReportVariant) -> ReportDocument:
        """The report for ``as_of``; the anonymised variant is the suppressed internal one."""
        document = self._internal(as_of)
        if variant is ReportVariant.INTERNAL:
            return document
        # Imported here: anonymise.py imports this module for the document types.
        from cbrn_dashboard.reports.anonymise import anonymise

        return anonymise(document)

    def _internal(self, as_of: date) -> ReportDocument:
        config = self._config_loader()
        data: DashboardData = self._dashboard.data(as_of)
        tiles = data.tiles
        lists = self._infrastructure.maintenance_due_lists(as_of)
        active_staff = sum(1 for p in self._personnel.alert_inputs().staff if is_active(p, as_of))

        indicator_cells = {_indicator_key(t.code, t.dimension): _indicator_cell(t) for t in tiles}
        indicators = tuple(
            _indicator_row(t, indicator_cells[_indicator_key(t.code, t.dimension)]) for t in tiles
        )
        infrastructure = KeyFigureGroup(
            Module.INFRASTRUCTURE,
            (
                Cell(key="kf:INFRASTRUCTURE:overdue", value=float(len(lists.overdue))),
                Cell(key="kf:INFRASTRUCTURE:due_soon", value=float(len(lists.due_soon))),
            ),
        )
        # Alert counts include the certificate alerts, so they are personnel-derived.
        alerts = tuple(
            AlertCountRow(
                severity,
                Cell(
                    key=f"alert:{severity.value}",
                    value=float(data.alert_counts.get(severity, 0)),
                    personnel_derived=True,
                ),
            )
            for severity in Severity
        )
        return ReportDocument(
            variant=ReportVariant.INTERNAL,
            header=ReportHeader(
                institution_name=config.institution_name,
                unit_name=config.unit_name,
                as_of=as_of,
                generated_at_utc=format_utc_timestamp(self._clock.utc_now()),
                app_version=self._app_version,
                operator_label=config.operator_label,
            ),
            handling_notice=config.report_handling_notice,
            is_demo=app_meta.read_is_demo(self._conn),
            small_count_threshold=config.small_count_threshold,
            key_figures=(
                _personnel_figures(tiles, active_staff),
                infrastructure,
                _exercise_figures(tiles),
                _budget_figures(data.charts),
            ),
            indicators=indicators,
            alert_summary=alerts,
            charts=tuple(_chart(spec, indicator_cells) for spec in data.charts),
            retraining=tuple(
                StaffListRow(row.identifier, row.level, row.valid_until, row.status)
                for row in self._personnel.retraining_list(as_of)
            ),
            overdue_assets=tuple(
                AssetListRow(row.tag, row.type_code, row.due_on, row.days_to_due)
                for row in lists.overdue
            ),
        )
