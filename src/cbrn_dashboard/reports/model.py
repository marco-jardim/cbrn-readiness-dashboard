# SPDX-License-Identifier: GPL-3.0-or-later
"""Report model: the content of a report for an as-of date (PLAN.md T8.5; D09, A11, R11-R13).

Qt-free and read-only. The model is codes and numbers only: no translated text (T8.6 renders the
document to PDF and translates the codes; the wording of the preliminary notice, P07, lives in the
translations). Two variants are built from the same figures:

* ``INTERNAL`` - the full report for the committee, DIRSA and the Air Force Command (R11, R12):
  header with the institution and unit names, the locally set handling notice, key figures, the
  indicator table, the alert summary and the three lists (staff identifiers needing retraining,
  overdue asset tags, expired and expiring stock lots with stock on hand);
* ``ANONYMISED`` - the aggregated report (R13) for internal use, made by
  :func:`cbrn_dashboard.reports.anonymise.anonymise` from the internal document: counts only, with
  small-count suppression (A11).

Every figure is a :class:`Cell`: a value, a stable key, a flag for figures computed from staff
records (``personnel_derived``; only those are suppressed) and, for totals, the keys of the cells
they are the sum of (``total_of``; the input of the secondary suppression). Charts hold the cells
of the document (the same keys), so that they can be rebuilt from the suppressed cells alone.

The alert summary is split by source (P8-01): per severity a total and the personnel (certificate),
infrastructure (maintenance) and indicator parts. Each cell that sums staff-derived counts declares
them in ``total_of``, so that no cell printed in the anonymised report is the difference of two
others that hides a small count.

The threshold of the small-count suppression is read from the configuration and carried on the
document (``small_count_threshold``); the renderer prints "< threshold" for a suppressed cell.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from cbrn_dashboard import __version__
from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain.alerts import (
    AlertKind,
    Severity,
    certificate_alerts,
    maintenance_alerts,
    stock_alerts,
)
from cbrn_dashboard.domain.budget import (
    BudgetTotal,
    InvalidCurrencyError,
    currency_decimals,
    fiscal_year_of,
)
from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.dates import format_utc_timestamp
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorStatus,
    Module,
    UnitKind,
    encode_dimension,
)
from cbrn_dashboard.domain.personnel import CertStatus, PpeLevel, is_active
from cbrn_dashboard.domain.stock import LotRow, LotStatus, StockValue, TypeSummary
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.dashboard import (
    CHART_BUDGET_PREFIX,
    CHART_PERSONNEL,
    CHART_STOCK,
    ChartSpec,
    DashboardData,
    DashboardService,
    Tile,
)
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.services.stock import StockService
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection

__all__ = [
    "PRELIMINARY_NOTICE_CODE",
    "AlertCountRow",
    "AlertSource",
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
    "StockLotListRow",
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
_STOCK_VALID_QTY = "STOCK_VALID_QTY"
_DEFAULT_CURRENCY_DECIMALS = 2
_EXPIRING_KEYS = tuple(f"kf:PERSONNEL:expiring:{level.value}" for level in PpeLevel)


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
    #: Internal report only (D37): the anonymised variant drops the cell, and the row or chart
    #: that holds it, instead of suppressing it. No ``total_of`` may name such a cell.
    internal_only: bool = False


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


class AlertSource(StrEnum):
    """Where the alerts of a count come from (P8-01): all sources, or one of the four."""

    ALL = "ALL"
    PERSONNEL = "PERSONNEL"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    INDICATORS = "INDICATORS"
    STOCK = "STOCK"


@dataclass(frozen=True)
class AlertCountRow:
    """The number of open alerts of one severity, in total or from one source."""

    severity: Severity
    cell: Cell
    source: AlertSource = AlertSource.ALL


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
    #: Internal report only (D37): the anonymised variant leaves the whole chart out.
    internal_only: bool = False


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
class StockLotListRow:
    """An expired or expiring lot with stock on hand (internal variant only, D37)."""

    type_code: str
    lot_code: str
    expires_on: date | None
    on_hand: int
    status: LotStatus


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
    #: The expired and expiring lots with stock (internal variant only; empty when anonymised).
    stock_lots: tuple[StockLotListRow, ...] = ()


# --------------------------------------------------------------------------- builder helpers


def _indicator_key(code: str, dimension: str) -> str:
    return f"indicator:{code}:{dimension}"


def _tile_value(tiles: tuple[Tile, ...], code: str, **parts: str) -> float | None:
    """The value of the first tile of ``code`` whose dimension parts include ``parts``."""
    for tile in tiles:
        if tile.code == code and all(tile.dimension_parts.get(k) == v for k, v in parts.items()):
            return tile.value
    return None


def _retraining_parts(level: str) -> tuple[str, str]:
    """Retraining needed = expiring + expired at a level (A03); the cells it is the sum of."""
    return (f"kf:PERSONNEL:expiring:{level}", f"kf:PERSONNEL:expired:{level}")


def _indicator_cell(tile: Tile) -> Cell:
    level = tile.dimension_parts.get("level")
    declared = tile.code == _PERS_RETRAINING and level is not None
    return Cell(
        key=_indicator_key(tile.code, tile.dimension),
        value=tile.value,
        personnel_derived=tile.module is Module.PERSONNEL,
        is_count=tile.unit is UnitKind.COUNT,
        total_of=_retraining_parts(level) if declared and level is not None else (),
        # per-type stock quantities stay out of the anonymised report until Q27 (D37)
        internal_only=tile.code == _STOCK_VALID_QTY,
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


def _personnel_figures(
    tiles: tuple[Tile, ...], active_staff: int, expired: Mapping[PpeLevel, int]
) -> KeyFigureGroup:
    """The personnel key figures; ``expired`` is the number of expired certificates per level.

    Retraining needed is expiring plus expired at each level (A03), so the retraining cell declares
    both and is hidden whenever one of them is (P8-01).
    """
    cells: list[Cell] = [
        Cell(key="kf:PERSONNEL:active_staff", value=float(active_staff), personnel_derived=True)
    ]
    for prefix, code in (
        ("valid", _PERS_CERT_VALID),
        ("expiring", _PERS_CERT_EXPIRING),
        ("expired", None),
        ("retraining", _PERS_RETRAINING),
    ):
        for level in PpeLevel:
            cells.append(
                Cell(
                    key=f"kf:PERSONNEL:{prefix}:{level.value}",
                    value=(
                        float(expired.get(level, 0))
                        if code is None
                        else _tile_value(tiles, code, level=level.value)
                    ),
                    personnel_derived=True,
                    total_of=_retraining_parts(level.value) if prefix == "retraining" else (),
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


def _to_minor(amount: float, decimals: int) -> int:
    """The whole minor units of a displayed amount, read from its shortest decimal form."""
    scaled = Decimal(repr(amount)).scaleb(decimals)
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def _exact_minor(totals: Sequence[BudgetTotal], currency: str, series_key: str) -> int | None:
    """The exact sum of the minor units of a series from the budget totals, if it is known."""
    group = [total for total in totals if total.currency == currency]
    if series_key == "allocated":
        return sum(t.allocated_minor for t in group if t.allocated_minor is not None)
    if series_key == "executed":
        return sum(t.executed_minor for t in group)
    return None


def _budget_figures(
    charts: tuple[ChartSpec, ...], totals: Sequence[BudgetTotal] | None = None
) -> KeyFigureGroup:
    """Allocated and executed amounts (major units, display only) per currency.

    With the budget ``totals`` the whole minor units are added as integers (D15) and converted
    once for display. Without them (no budget service) each charted amount is turned back into the
    whole minor units of its currency from its shortest decimal form and the integers are added.
    """
    cells: list[Cell] = []
    for chart in charts:
        if not chart.key.startswith(CHART_BUDGET_PREFIX):
            continue
        currency = chart.parameters.get("currency", "")
        try:
            decimals = currency_decimals(currency)
        except InvalidCurrencyError:
            decimals = _DEFAULT_CURRENCY_DECIMALS
        for series in chart.series:
            exact = None if totals is None else _exact_minor(totals, currency, series.key)
            minor = (
                exact
                if exact is not None
                else sum(_to_minor(v, decimals) for v in series.values if v is not None)
            )
            cells.append(
                Cell(
                    key=f"kf:BUDGET:{series.key}:{currency}",
                    value=float(Decimal(minor).scaleb(-decimals)),
                    is_count=False,
                )
            )
    return KeyFigureGroup(Module.BUDGET, tuple(cells))


def _stock_figures(summaries: Sequence[TypeSummary], value: StockValue) -> KeyFigureGroup:
    """The stock key figures: the three counts, then the value per currency (never added up).

    The counts are kept in the anonymised report (D37). The valid and the expired value are
    internal only and not counts: the exact minor units of the domain value are converted once for
    display, like the budget figures.
    """
    cells: list[Cell] = [
        Cell(key="kf:STOCK:lots_expired", value=float(sum(s.lots_expired for s in summaries))),
        Cell(key="kf:STOCK:lots_expiring", value=float(sum(s.lots_expiring for s in summaries))),
        Cell(
            key="kf:STOCK:types_below_min",
            value=float(sum(1 for s in summaries if s.active and s.below_minimum)),
        ),
    ]
    for currency, amount in value.by_currency.items():
        try:
            decimals = currency_decimals(currency)
        except InvalidCurrencyError:
            decimals = _DEFAULT_CURRENCY_DECIMALS
        for name, minor in (("valid", amount.valid_minor), ("expired", amount.expired_minor)):
            cells.append(
                Cell(
                    key=f"kf:STOCK:value_{name}:{currency}",
                    value=float(Decimal(minor).scaleb(-decimals)),
                    is_count=False,
                    internal_only=True,
                )
            )
    return KeyFigureGroup(Module.STOCK, tuple(cells))


def _stock_lot_list(rows: Sequence[LotRow]) -> tuple[StockLotListRow, ...]:
    """The expired and expiring lots with stock on hand, by expiry date, type and lot code."""
    listed = [
        row
        for row in rows
        if row.on_hand > 0 and row.status in (LotStatus.EXPIRED, LotStatus.EXPIRING)
    ]
    listed.sort(key=lambda row: (row.expires_on or date.max, row.type_code, row.lot_code))
    return tuple(
        StockLotListRow(row.type_code, row.lot_code, row.expires_on, row.on_hand, row.status)
        for row in listed
    )


def _alert_summary(
    *,
    expiring: int,
    expired: int,
    expired_keys: tuple[str, ...],
    maintenance: list[Severity],
    tiles: tuple[Tile, ...],
    indicator_cells: dict[str, Cell],
    stock: Sequence[Severity] = (),
) -> tuple[AlertCountRow, ...]:
    """The alert counts per severity, split by source (P8-01).

    A count that sums certificate alerts is personnel-derived and declares the per-level cells it
    sums; a count of indicator alerts declares the personnel count rows that can carry a status, so
    that it is hidden whenever one of them is; the total declares its four parts. The stock part
    counts the lot and low-stock alerts (``stock`` holds their severities, T11.8) and is not
    personnel-derived. The INFO count is maintenance only (``MAINT_SCHEDULE_UNKNOWN``) and is not
    personnel-derived.
    """
    watched = tuple(
        _indicator_key(tile.code, tile.dimension)
        for tile in tiles
        if tile.module is Module.PERSONNEL
        and tile.unit is UnitKind.COUNT
        and tile.status in (IndicatorStatus.OK, IndicatorStatus.WARNING, IndicatorStatus.CRITICAL)
        and _indicator_key(tile.code, tile.dimension) in indicator_cells
    )
    rows: list[AlertCountRow] = []
    for severity in Severity:
        if severity is Severity.INFO:
            count = maintenance.count(Severity.INFO)
            rows.append(AlertCountRow(severity, Cell(key="alert:INFO", value=float(count))))
            continue
        warning = severity is Severity.WARNING
        indicator_status = IndicatorStatus.WARNING if warning else IndicatorStatus.CRITICAL
        parts = (
            AlertCountRow(
                severity,
                Cell(
                    key=f"alert:{severity.value}:personnel",
                    value=float(expiring if warning else expired),
                    personnel_derived=True,
                    total_of=_EXPIRING_KEYS if warning else expired_keys,
                ),
                AlertSource.PERSONNEL,
            ),
            AlertCountRow(
                severity,
                Cell(
                    key=f"alert:{severity.value}:infrastructure",
                    value=float(maintenance.count(severity)),
                ),
                AlertSource.INFRASTRUCTURE,
            ),
            AlertCountRow(
                severity,
                Cell(
                    key=f"alert:{severity.value}:indicators",
                    value=float(sum(1 for tile in tiles if tile.status is indicator_status)),
                    total_of=watched,
                ),
                AlertSource.INDICATORS,
            ),
            AlertCountRow(
                severity,
                Cell(
                    key=f"alert:{severity.value}:stock",
                    value=float(sum(1 for item in stock if item is severity)),
                ),
                AlertSource.STOCK,
            ),
        )
        total = Cell(
            key=f"alert:{severity.value}",
            value=sum(part.cell.value or 0.0 for part in parts),
            total_of=tuple(part.cell.key for part in parts),
        )
        rows.append(AlertCountRow(severity, total))
        rows.extend(parts)
    return tuple(rows)


def _chart(spec: ChartSpec, indicator_cells: dict[str, Cell]) -> ReportChart:
    """A report chart whose cells are the document's cells (new ones only for chart-only data)."""
    series: list[ReportSeries] = []
    stock = spec.key == CHART_STOCK
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
                    internal_only=stock,
                )
            )
        series.append(ReportSeries(source.key, tuple(cells)))
    return ReportChart(
        key=spec.key,
        categories=spec.categories,
        series=tuple(series),
        unit=spec.unit,
        parameters=tuple(sorted(spec.parameters.items())),
        internal_only=stock,
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
        budget: BudgetService | None = None,
        stock: StockService | None = None,
    ) -> None:
        self._budget = budget
        self._stock = stock
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

    def _budget_totals(self, as_of: date) -> list[BudgetTotal] | None:
        """The exact budget totals of the as-of fiscal year (``None`` without a budget service)."""
        if self._budget is None:
            return None
        return self._budget.totals_for_year(fiscal_year_of(as_of), as_of)

    def _stock_severities(self, as_of: date) -> list[Severity]:
        """The severities of the stock alerts on ``as_of`` (none without a stock service)."""
        if self._stock is None:
            return []
        types, lots, movements = self._stock.alert_inputs()
        found = stock_alerts(types, lots, movements, as_of, self._stock.stock_rules())
        return [alert.severity for alert in found]

    def _stock_content(
        self, as_of: date
    ) -> tuple[tuple[KeyFigureGroup, ...], tuple[StockLotListRow, ...]]:
        """The stock key figures and the lot list (nothing without a stock service)."""
        if self._stock is None:
            return (), ()
        group = _stock_figures(self._stock.type_summaries(as_of), self._stock.stock_value(as_of))
        return (group,), _stock_lot_list(self._stock.lot_rows(as_of))

    def _internal(self, as_of: date) -> ReportDocument:
        config = self._config_loader()
        data: DashboardData = self._dashboard.data(as_of)
        tiles = data.tiles
        lists = self._infrastructure.maintenance_due_lists(as_of)
        people = self._personnel.alert_inputs()
        active_staff = sum(1 for p in people.staff if is_active(p, as_of))

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
        assets = self._infrastructure.alert_inputs()
        certificates = certificate_alerts(people.staff, people.certificates, as_of, people.rules)
        certificate_kinds = [alert.kind for alert in certificates]
        expired_by_level = {
            level: sum(
                1
                for alert in certificates
                if alert.kind is AlertKind.CERT_EXPIRED
                and alert.dimension == encode_dimension({"level": level.value})
            )
            for level in PpeLevel
        }
        maintenance_severities = [
            alert.severity
            for alert in maintenance_alerts(
                assets.assets,
                assets.types,
                assets.status_events,
                assets.maintenance,
                as_of,
                assets.rules,
            )
        ]
        alerts = _alert_summary(
            expiring=certificate_kinds.count(AlertKind.CERT_EXPIRING),
            expired=certificate_kinds.count(AlertKind.CERT_EXPIRED),
            expired_keys=tuple(f"kf:PERSONNEL:expired:{level.value}" for level in PpeLevel),
            maintenance=maintenance_severities,
            tiles=tiles,
            indicator_cells=indicator_cells,
            stock=self._stock_severities(as_of),
        )
        stock_figures, stock_lots = self._stock_content(as_of)
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
                _personnel_figures(tiles, active_staff, expired_by_level),
                infrastructure,
                _exercise_figures(tiles),
                _budget_figures(data.charts, self._budget_totals(as_of)),
                *stock_figures,
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
            stock_lots=stock_lots,
        )
