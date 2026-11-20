# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels of the codes the dashboard shows (PLAN.md section 6, T6.5, D23).

The dashboard service returns codes and numbers only. Here the codes become words:

* indicator names and units, module titles, status and severity texts, snapshot origins and the
  error codes of the "Record snapshot" action. An unknown code is shown as itself, never as an
  exception;
* the dimension of a tile (``level=A``, ``type=bay``, ``currency=BRL;source=DIRSA`` ...) and the
  categories of the charts. Asset types and funding sources follow the display rules of their own
  pages (``ui/infrastructure/labels.py`` and ``ui/budget/labels.py``): built-in ones are named by
  the UI, user-defined ones by their own labels. Edition codes are shown as they are;
* the status icon of D23: a SHAPE per status, drawn in a colour of the colour-blind-safe palette
  of the chart adapter, so a status is never conveyed by colour alone;
* :func:`chart_data`, the conversion of a ``ChartSpec`` (codes) to the chart adapter's
  ``ChartData`` (display text).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from PySide6.QtCore import QCoreApplication, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QPolygonF

from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.budget import is_valid_currency
from cbrn_dashboard.domain.indicators import IndicatorStatus, Module, UnitKind
from cbrn_dashboard.reports.message_keys import stock_type_key
from cbrn_dashboard.services.budget import SourceView
from cbrn_dashboard.services.config import CORRUPT_SETTING
from cbrn_dashboard.services.dashboard import (
    CHART_BUDGET_PREFIX,
    CHART_EXERCISES,
    CHART_INFRASTRUCTURE,
    CHART_PERSONNEL,
    CHART_STOCK,
    ChartSpec,
    Tile,
)
from cbrn_dashboard.services.errors import INVALID_DATE, NOT_FOUND, READ_ONLY
from cbrn_dashboard.services.infrastructure import AssetTypeView
from cbrn_dashboard.services.snapshots import AS_OF_IN_FUTURE, ORIGIN_NOT_ALLOWED
from cbrn_dashboard.services.stock import StockTypeView, stock_type_label
from cbrn_dashboard.ui.budget.labels import fill_placeholders, source_name
from cbrn_dashboard.ui.budget.models import money_text, rate_text
from cbrn_dashboard.ui.dashboard.models import NOT_RECORDED, count_text
from cbrn_dashboard.ui.exercises.labels import kind_label
from cbrn_dashboard.ui.infrastructure.labels import code_label, type_display
from cbrn_dashboard.ui.personnel.labels import (
    degree_level_label,
    degree_status_label,
    ppe_level_label,
)
from cbrn_dashboard.ui.shell.charts import PALETTE, ChartData, ChartKind, ChartSeries
from cbrn_dashboard.ui.shell.formatting import format_date
from cbrn_dashboard.ui.shell.widgets import device_pixel_ratio, label_for
from cbrn_dashboard.ui.stock.labels import code_label as stock_code_label

__all__ = [
    "ALL_ERROR_CODES",
    "INDICATOR_CODES",
    "ORIGINS",
    "STATUS_COLOURS",
    "DisplayNames",
    "alert_text",
    "as_of_text",
    "category_header",
    "category_label",
    "chart_data",
    "chart_title",
    "chart_unit",
    "context_text",
    "dimension_text",
    "error_label",
    "indicator_name",
    "join_texts",
    "module_title",
    "origin_label",
    "series_label",
    "severity_pixmap",
    "status_label",
    "status_pixmap",
    "thresholds_text",
    "unit_label",
    "value_text",
]

# --------------------------------------------------------------------------- display names


@dataclass(frozen=True)
class DisplayNames:
    """The language and the lookups the labels need (user-defined types and funding sources)."""

    lang: str
    types: Mapping[str, AssetTypeView] = field(default_factory=dict)
    sources: Mapping[str, SourceView] = field(default_factory=dict)
    stock_types: Mapping[str, StockTypeView] = field(default_factory=dict)


# The built-in stock type names are catalogued by the stock labels (context ``Stock``); the key
# table of the reports holds their source texts, so they are looked up through the class (this is
# not a literal translate call for the extraction guard, the texts are extracted elsewhere).

_STOCK_CATEGORIES: dict[str, Callable[[], str]] = {
    "antidote": lambda: QCoreApplication.translate("Dashboard", "Antidote"),
    "decontaminant": lambda: QCoreApplication.translate("Dashboard", "Decontaminant"),
    "detector": lambda: QCoreApplication.translate("Dashboard", "Detector"),
    "ppe": lambda: QCoreApplication.translate("Dashboard", "PPE"),
    "other": lambda: QCoreApplication.translate("Dashboard", "Other"),
}


def _stock_category_name(code: str) -> str:
    """The name of a stock category (the code itself when unknown)."""
    return label_for(_STOCK_CATEGORIES, code)


def _stock_type_name(code: str, names: DisplayNames) -> str:
    """The name of a stock item type: built-in ones are named by the UI, user-defined ones by
    their own labels with the usual fallback (the code when unknown)."""
    key = stock_type_key(code)
    view = names.stock_types.get(code)
    if key is not None and (view is None or view.built_in):
        return stock_code_label(code)
    return code if view is None else stock_type_label(view, names.lang)


def _type_name(code: str, names: DisplayNames) -> str:
    """The asset type name by the rule of the infrastructure page (the code when unknown)."""
    view = names.types.get(code)
    return code_label(code) if view is None else type_display(view, names.lang)


def _source_name(code: str, names: DisplayNames) -> str:
    """The funding source name by the rule of the budget page (the code when unknown)."""
    return source_name(code, names.lang, names.sources)


# --------------------------------------------------------------------------- indicators

_INDICATOR_NAMES: dict[str, Callable[[], str]] = {
    "PERS_CERT_VALID": lambda: QCoreApplication.translate(
        "Dashboard", "Staff with a valid PPE qualification"
    ),
    "PERS_CERT_EXPIRING": lambda: QCoreApplication.translate(
        "Dashboard", "PPE qualifications expiring soon"
    ),
    "PERS_RETRAINING_NEEDED": lambda: QCoreApplication.translate(
        "Dashboard", "Staff needing retraining"
    ),
    "PERS_DEGREE": lambda: QCoreApplication.translate("Dashboard", "Staff with a degree"),
    "PERS_TRAINING_12M": lambda: QCoreApplication.translate(
        "Dashboard", "Training records in the last 12 months"
    ),
    "INFRA_AVAILABLE": lambda: QCoreApplication.translate("Dashboard", "Available units"),
    "INFRA_MAINT_OVERDUE": lambda: QCoreApplication.translate(
        "Dashboard", "Units with overdue maintenance"
    ),
    "EX_LAST_PARTICIPANTS": lambda: QCoreApplication.translate(
        "Dashboard", "Participants in the latest exercise"
    ),
    "EX_LAST_COUNTRIES": lambda: QCoreApplication.translate(
        "Dashboard", "Countries in the latest exercise"
    ),
    "EX_DAYS_SINCE_LAST": lambda: QCoreApplication.translate(
        "Dashboard", "Days since the latest exercise"
    ),
    "BUD_EXEC_RATE": lambda: QCoreApplication.translate("Dashboard", "Budget execution rate"),
    "STOCK_VALID_QTY": lambda: QCoreApplication.translate("Dashboard", "Valid stock"),
    "STOCK_LOTS_EXPIRING": lambda: QCoreApplication.translate("Dashboard", "Lots expiring soon"),
    "STOCK_LOTS_EXPIRED": lambda: QCoreApplication.translate(
        "Dashboard", "Expired lots still in stock"
    ),
    "STOCK_TYPES_BELOW_MIN": lambda: QCoreApplication.translate(
        "Dashboard", "Item types below the minimum stock"
    ),
}

# The indicator codes that have a name (for the completeness test).
INDICATOR_CODES: tuple[str, ...] = tuple(_INDICATOR_NAMES)

_PERSON = (
    lambda: QCoreApplication.translate("Dashboard", "person"),
    lambda: QCoreApplication.translate("Dashboard", "people"),
)
_UNIT = (
    lambda: QCoreApplication.translate("Dashboard", "unit"),
    lambda: QCoreApplication.translate("Dashboard", "units"),
)
_LOT = (
    lambda: QCoreApplication.translate("Dashboard", "lot"),
    lambda: QCoreApplication.translate("Dashboard", "lots"),
)

# The unit noun of a tile: (singular, plural). The number itself stays in the value label, so the
# nouns are plain messages (a Qt numerus message must contain %n); the singular is for 1 in the
# three languages.
_INDICATOR_UNITS: dict[str, tuple[Callable[[], str], Callable[[], str]]] = {
    "PERS_CERT_VALID": _PERSON,
    "PERS_CERT_EXPIRING": (
        lambda: QCoreApplication.translate("Dashboard", "qualification"),
        lambda: QCoreApplication.translate("Dashboard", "qualifications"),
    ),
    "PERS_RETRAINING_NEEDED": _PERSON,
    "PERS_DEGREE": _PERSON,
    "PERS_TRAINING_12M": (
        lambda: QCoreApplication.translate("Dashboard", "record"),
        lambda: QCoreApplication.translate("Dashboard", "records"),
    ),
    "INFRA_AVAILABLE": _UNIT,
    "INFRA_MAINT_OVERDUE": _UNIT,
    "EX_LAST_PARTICIPANTS": (
        lambda: QCoreApplication.translate("Dashboard", "participant"),
        lambda: QCoreApplication.translate("Dashboard", "participants"),
    ),
    "EX_LAST_COUNTRIES": (
        lambda: QCoreApplication.translate("Dashboard", "country"),
        lambda: QCoreApplication.translate("Dashboard", "countries"),
    ),
    "EX_DAYS_SINCE_LAST": (
        lambda: QCoreApplication.translate("Dashboard", "day"),
        lambda: QCoreApplication.translate("Dashboard", "days"),
    ),
    "BUD_EXEC_RATE": (
        lambda: QCoreApplication.translate("Dashboard", "of the allocation"),
        lambda: QCoreApplication.translate("Dashboard", "of the allocation"),
    ),
    "STOCK_VALID_QTY": _UNIT,
    "STOCK_LOTS_EXPIRING": _LOT,
    "STOCK_LOTS_EXPIRED": _LOT,
    "STOCK_TYPES_BELOW_MIN": (
        lambda: QCoreApplication.translate("Dashboard", "item type"),
        lambda: QCoreApplication.translate("Dashboard", "item types"),
    ),
}

_UNIT_KIND_LABELS: dict[str, Callable[[], str]] = {
    UnitKind.COUNT.value: lambda: QCoreApplication.translate("Dashboard", "count"),
    UnitKind.RATIO.value: lambda: QCoreApplication.translate("Dashboard", "ratio"),
    UnitKind.CURRENCY.value: lambda: QCoreApplication.translate("Dashboard", "amount"),
    UnitKind.DAYS.value: lambda: QCoreApplication.translate("Dashboard", "days"),
}

_MODULE_TITLES: dict[str, Callable[[], str]] = {
    Module.PERSONNEL.value: lambda: QCoreApplication.translate("Dashboard", "Personnel"),
    Module.INFRASTRUCTURE.value: lambda: QCoreApplication.translate("Dashboard", "Infrastructure"),
    Module.EXERCISES.value: lambda: QCoreApplication.translate("Dashboard", "Exercises"),
    Module.BUDGET.value: lambda: QCoreApplication.translate("Dashboard", "Budget"),
    Module.STOCK.value: lambda: QCoreApplication.translate("Dashboard", "Stock"),
}

_STATUS_LABELS: dict[str, Callable[[], str]] = {
    IndicatorStatus.OK.value: lambda: QCoreApplication.translate("Dashboard", "OK"),
    IndicatorStatus.WARNING.value: lambda: QCoreApplication.translate("Dashboard", "Warning"),
    IndicatorStatus.CRITICAL.value: lambda: QCoreApplication.translate("Dashboard", "Critical"),
    IndicatorStatus.NO_TARGET.value: lambda: QCoreApplication.translate("Dashboard", "No target"),
    IndicatorStatus.NO_DATA.value: lambda: QCoreApplication.translate("Dashboard", "No data"),
}


def indicator_name(code: str) -> str:
    """The name of an indicator (the code itself when unknown)."""
    return label_for(_INDICATOR_NAMES, str(code))


def _plural_count(value: float | None) -> int:
    """The count that picks the number form of a unit: ``value`` when it is a whole number, else a
    count that selects the plural form (also for a missing value)."""
    if value is None or not float(value).is_integer():
        return 2
    return int(value)


def unit_label(code: str, unit: str, value: float | None = None) -> str:
    """The unit noun of an indicator ("person" for 1, "people" otherwise).

    ``value`` is the number shown next to the unit; a missing or non-integer value selects the
    plural. The kind of unit is returned when the code is unknown.
    """
    forms = _INDICATOR_UNITS.get(code)
    if forms is not None:
        singular, plural = forms
        return singular() if _plural_count(value) == 1 else plural()
    return label_for(_UNIT_KIND_LABELS, str(unit))


def module_title(module: str) -> str:
    """The title of the group of tiles of a module."""
    return label_for(_MODULE_TITLES, str(module))


def status_label(status: str) -> str:
    """The text of an indicator status (D14); No target and No data have their own texts."""
    return label_for(_STATUS_LABELS, str(status))


# --------------------------------------------------------------------------- tile texts


def _plain_number(value: float | None, unit: str, lang: str) -> str:
    if value is None:
        return NOT_RECORDED
    if unit == UnitKind.RATIO.value:
        return rate_text(value, lang)
    return count_text(value, lang)


def value_text(tile: Tile, lang: str) -> str:
    """The value of a tile in ``lang`` (a percentage for a ratio; ``-`` when there is none)."""
    return _plain_number(tile.value, tile.unit.value, lang)


def thresholds_text(tile: Tile, lang: str) -> str:
    """The thresholds in force (the pro-rated ones for the budget rate), or that there are none."""
    if tile.warning_value is None and tile.critical_value is None:
        return QCoreApplication.translate("Dashboard", "Thresholds in force: none")
    unit = tile.unit.value
    return (
        QCoreApplication.translate("Dashboard", "Thresholds in force: warning %1, critical %2")
        .replace("%1", _plain_number(tile.warning_value, unit, lang))
        .replace("%2", _plain_number(tile.critical_value, unit, lang))
    )


def context_text(tile: Tile, lang: str) -> str:
    """The extra figures of a tile (units in service, amounts); empty when it has none."""
    context = tile.context
    if tile.code == "INFRA_AVAILABLE" and "in_service" in context:
        return QCoreApplication.translate("Dashboard", "of %1 in service").replace(
            "%1", count_text(context["in_service"], lang)
        )
    if tile.code == "STOCK_VALID_QTY":
        if "minimum" in context:
            return QCoreApplication.translate("Dashboard", "minimum %1").replace(
                "%1", count_text(context["minimum"], lang)
            )
        return QCoreApplication.translate("Dashboard", "minimum not set")
    if tile.code == "BUD_EXEC_RATE" and {"allocated_minor", "executed_minor"} <= set(context):
        currency = tile.dimension_parts.get("currency", "")
        if is_valid_currency(currency):
            return (
                QCoreApplication.translate("Dashboard", "Executed %1 of %2 allocated")
                .replace("%1", money_text(int(context["executed_minor"]), currency, lang))
                .replace("%2", money_text(int(context["allocated_minor"]), currency, lang))
            )
    return ""


def _part_text(code: str, key: str, value: str, names: DisplayNames) -> str:
    """One part of a dimension. Data (a user-defined name) is placed INSIDE the translation."""
    if key == "level":
        if code == "PERS_DEGREE":
            return degree_level_label(value)
        return QCoreApplication.translate("Dashboard", "Level %1").replace(
            "%1", ppe_level_label(value)
        )
    if key == "status":
        return degree_status_label(value)
    if key == "type":
        return QCoreApplication.translate("Dashboard", "Type %1").replace(
            "%1", _type_name(value, names)
        )
    if key == "kind":
        return QCoreApplication.translate("Dashboard", "Kind %1").replace("%1", kind_label(value))
    if key == "category":
        return QCoreApplication.translate("Dashboard", "Category %1").replace(
            "%1", _stock_category_name(value)
        )
    if key == "item":
        return QCoreApplication.translate("Dashboard", "Item %1").replace(
            "%1", _stock_type_name(value, names)
        )
    if key == "currency":
        return QCoreApplication.translate("Dashboard", "Currency %1").replace("%1", value)
    if key == "source":
        return QCoreApplication.translate("Dashboard", "Source %1").replace(
            "%1", _source_name(value, names)
        )
    return fill_placeholders(QCoreApplication.translate("Dashboard", "%1: %2"), key, value)


def join_texts(texts: Sequence[str]) -> str:
    """``texts`` joined by the translated list pattern ``%1, %2``, each join in a single pass."""
    joined = ""
    for position, text in enumerate(texts):
        joined = (
            text
            if position == 0
            else fill_placeholders(QCoreApplication.translate("Dashboard", "%1, %2"), joined, text)
        )
    return joined


def dimension_text(code: str, parts: Mapping[str, str], names: DisplayNames) -> str:
    """The dimension of a tile as words (empty for an indicator without a dimension).

    The category of a stock tile is left out when the item is there: the item names its own type.
    """
    shown = [
        (key, value) for key, value in parts.items() if not (key == "category" and "item" in parts)
    ]
    return join_texts([_part_text(code, key, value, names) for key, value in shown])


def as_of_text(as_of: date, lang: str) -> str:
    """The caption naming the as-of date."""
    return QCoreApplication.translate("Dashboard", "Readiness as of %1").replace(
        "%1", format_date(as_of, lang)
    )


# --------------------------------------------------------------------------- alerts

_ALERT_TEMPLATES: dict[str, Callable[[], str]] = {
    Severity.CRITICAL.value: lambda: QCoreApplication.translate("Dashboard", "Critical alerts: %1"),
    Severity.WARNING.value: lambda: QCoreApplication.translate("Dashboard", "Warning alerts: %1"),
    Severity.INFO.value: lambda: QCoreApplication.translate("Dashboard", "Information alerts: %1"),
}


def alert_text(severity: str, count: int, lang: str) -> str:
    """The text of an alert counter ("Critical alerts: 3")."""
    template = label_for(_ALERT_TEMPLATES, str(severity))
    return template.replace("%1", count_text(float(count), lang))


# --------------------------------------------------------------------------- status icons (D23)

# Status -> colour, all from the Okabe-Ito palette of the chart adapter.
STATUS_COLOURS: dict[str, str] = {
    IndicatorStatus.OK.value: PALETTE[2],
    IndicatorStatus.WARNING.value: PALETTE[0],
    IndicatorStatus.CRITICAL.value: PALETTE[5],
    IndicatorStatus.NO_TARGET.value: PALETTE[1],
    IndicatorStatus.NO_DATA.value: PALETTE[7],
}

# Status -> (shape, filled). Every status has its own shape: colour is never the only cue.
_STATUS_SHAPES: dict[str, tuple[str, bool]] = {
    IndicatorStatus.OK.value: ("circle", True),
    IndicatorStatus.WARNING.value: ("triangle", True),
    IndicatorStatus.CRITICAL.value: ("square", True),
    IndicatorStatus.NO_TARGET.value: ("circle", False),
    IndicatorStatus.NO_DATA.value: ("diamond", False),
}

_SEVERITY_STATUS: dict[str, IndicatorStatus] = {
    Severity.CRITICAL.value: IndicatorStatus.CRITICAL,
    Severity.WARNING.value: IndicatorStatus.WARNING,
    Severity.INFO.value: IndicatorStatus.NO_TARGET,
}

_ICON_SIZE = 16


def status_pixmap(status: str) -> QPixmap:
    """The icon of a status: a shape in the colour of :data:`STATUS_COLOURS`."""
    key = str(status)
    shape, filled = _STATUS_SHAPES.get(key, ("diamond", False))
    colour = QColor(STATUS_COLOURS.get(key, PALETTE[7]))
    ratio = device_pixel_ratio()
    pixmap = QPixmap(round(_ICON_SIZE * ratio), round(_ICON_SIZE * ratio))
    pixmap.setDevicePixelRatio(ratio)  # the drawing below stays in logical coordinates
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#000000") if filled else colour)
        pen.setWidthF(1.0 if filled else 2.5)
        painter.setPen(pen)
        painter.setBrush(QBrush(colour) if filled else QBrush(Qt.BrushStyle.NoBrush))
        box = QRectF(2.0, 2.0, 12.0, 12.0)
        if shape == "circle":
            painter.drawEllipse(box)
        elif shape == "square":
            painter.drawRect(box)
        elif shape == "triangle":
            corners = [QPointF(8.0, 2.0), QPointF(14.5, 14.0), QPointF(1.5, 14.0)]
            painter.drawPolygon(QPolygonF(corners))
        else:
            corners = [QPointF(8.0, 1.5), QPointF(14.5, 8.0), QPointF(8.0, 14.5), QPointF(1.5, 8.0)]
            painter.drawPolygon(QPolygonF(corners))
    finally:
        painter.end()
    return pixmap


def severity_pixmap(severity: str) -> QPixmap:
    """The icon of an alert severity (the shapes of the matching statuses)."""
    return status_pixmap(_SEVERITY_STATUS.get(str(severity), IndicatorStatus.NO_DATA).value)


# --------------------------------------------------------------------------- charts

_SERIES_LABELS: dict[str, Callable[[], str]] = {
    "valid": lambda: QCoreApplication.translate("Dashboard", "Valid qualifications"),
    "available": lambda: QCoreApplication.translate("Dashboard", "Available"),
    "in_service": lambda: QCoreApplication.translate("Dashboard", "In service"),
    "participants": lambda: QCoreApplication.translate("Dashboard", "Participants"),
    "countries": lambda: QCoreApplication.translate("Dashboard", "Countries"),
    "allocated": lambda: QCoreApplication.translate("Dashboard", "Allocated"),
    "executed": lambda: QCoreApplication.translate("Dashboard", "Executed"),
    "stock_valid": lambda: QCoreApplication.translate("Dashboard", "Valid stock"),
    "stock_minimum": lambda: QCoreApplication.translate("Dashboard", "Minimum stock"),
}


def series_label(key: str) -> str:
    """The name of a chart series (the code itself when unknown)."""
    return label_for(_SERIES_LABELS, str(key))


def chart_title(spec: ChartSpec) -> str:
    """The translated title of a chart; a budget chart names its currency and fiscal year."""
    if spec.key == CHART_PERSONNEL:
        return QCoreApplication.translate(
            "Dashboard", "Staff with a valid PPE qualification, by level"
        )
    if spec.key == CHART_INFRASTRUCTURE:
        return QCoreApplication.translate("Dashboard", "Availability by asset type")
    if spec.key == CHART_EXERCISES:
        return QCoreApplication.translate("Dashboard", "Participants and countries by edition")
    if spec.key == CHART_STOCK:
        return QCoreApplication.translate(
            "Dashboard", "Valid stock and minimum of antidotes and decontaminants"
        )
    if spec.key.startswith(CHART_BUDGET_PREFIX):
        currency = spec.parameters.get("currency", spec.key[len(CHART_BUDGET_PREFIX) :])
        return (
            QCoreApplication.translate(
                "Dashboard", "Allocated and executed by funding source, %1, fiscal year %2"
            )
            .replace("%1", currency)
            .replace("%2", spec.parameters.get("fiscal_year", ""))
        )
    return spec.key


def category_header(chart_key: str) -> str:
    """The header of the category column in the table view of a chart."""
    if chart_key == CHART_PERSONNEL:
        return QCoreApplication.translate("Dashboard", "PPE level")
    if chart_key == CHART_INFRASTRUCTURE:
        return QCoreApplication.translate("Dashboard", "Asset type")
    if chart_key == CHART_EXERCISES:
        return QCoreApplication.translate("Dashboard", "Edition")
    if chart_key == CHART_STOCK:
        return QCoreApplication.translate("Dashboard", "Item type")
    if chart_key.startswith(CHART_BUDGET_PREFIX):
        return QCoreApplication.translate("Dashboard", "Funding source")
    return ""


def category_label(chart_key: str, code: str, names: DisplayNames) -> str:
    """The display name of a chart category; PPE levels and edition codes are shown as is."""
    if chart_key == CHART_INFRASTRUCTURE:
        return _type_name(code, names)
    if chart_key == CHART_STOCK:
        return _stock_type_name(code, names)
    if chart_key.startswith(CHART_BUDGET_PREFIX):
        return _source_name(code, names)
    if chart_key == CHART_PERSONNEL:
        return ppe_level_label(code)
    return code


def chart_unit(spec: ChartSpec) -> str:
    """The axis unit of a chart: the currency code of a budget chart, else "Count"."""
    if spec.unit is UnitKind.CURRENCY:
        return spec.parameters.get("currency", "")
    return QCoreApplication.translate("Dashboard", "Count")


def chart_data(spec: ChartSpec, names: DisplayNames) -> ChartData:
    """The chart adapter's data for ``spec``: the same numbers, with display text for the codes."""
    series = tuple(ChartSeries(series_label(item.key), item.values) for item in spec.series)
    return ChartData(
        title=chart_title(spec),
        categories=tuple(category_label(spec.key, code, names) for code in spec.categories),
        series=series,
        unit=chart_unit(spec),
        kind=ChartKind.GROUPED_BAR if len(series) > 1 else ChartKind.BAR,
    )


# --------------------------------------------------------------------------- snapshots

_ORIGIN_LABELS: dict[str, Callable[[], str]] = {
    "manual": lambda: QCoreApplication.translate("Dashboard", "manual"),
    "monthly": lambda: QCoreApplication.translate("Dashboard", "monthly"),
    "report": lambda: QCoreApplication.translate("Dashboard", "report"),
    "retroactive": lambda: QCoreApplication.translate("Dashboard", "retroactive"),
}

# The snapshot origins that have a label.
ORIGINS: tuple[str, ...] = tuple(_ORIGIN_LABELS)

_ERROR_LABELS: dict[str, Callable[[], str]] = {
    READ_ONLY: lambda: QCoreApplication.translate(
        "Dashboard", "The data is read-only: nothing was saved."
    ),
    INVALID_DATE: lambda: QCoreApplication.translate("Dashboard", "The date is not valid."),
    NOT_FOUND: lambda: QCoreApplication.translate("Dashboard", "The record no longer exists."),
    AS_OF_IN_FUTURE: lambda: QCoreApplication.translate(
        "Dashboard", "A snapshot cannot be recorded for a date in the future."
    ),
    ORIGIN_NOT_ALLOWED: lambda: QCoreApplication.translate(
        "Dashboard", "This snapshot origin is not allowed."
    ),
    CORRUPT_SETTING: lambda: QCoreApplication.translate(
        "Dashboard", "A stored setting cannot be read."
    ),
}

# Every error code the "Record snapshot" action can present (for the completeness test).
ALL_ERROR_CODES: tuple[str, ...] = tuple(_ERROR_LABELS)


def origin_label(origin: str) -> str:
    """The text of a snapshot origin (the code itself when unknown)."""
    return label_for(_ORIGIN_LABELS, str(origin))


def error_label(code: str) -> str:
    """The translated message of an error code (the code itself when unknown)."""
    return label_for(_ERROR_LABELS, code)
