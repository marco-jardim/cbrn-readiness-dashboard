# SPDX-License-Identifier: GPL-3.0-or-later
"""Chart adapter over Qt Charts (PLAN.md task T6.4, D08, D23, risk K09).

This is the ONLY module that imports ``PySide6.QtCharts`` (an AST test enforces it). Qt Charts is
deprecated since Qt 6.10 (K09) and is kept because it ships with PySide6; the rest of the program
talks to :class:`ChartData` / :class:`ChartView` / :func:`render_to_image` only, so this adapter is
the single touch point for a backend change (deferred item X9).

What it offers:

* plain, frozen chart data (:class:`ChartData`, :class:`ChartSeries`, :class:`ChartKind`) that
  carry no Qt type: ``services/`` must not import THIS module (it imports Qt), but the dataclasses
  are Qt-free and T6.5 moves or re-exports them as needed;
* one colour-blind-safe palette, :data:`PALETTE` (Okabe-Ito), used in order for the series;
* :func:`build_chart` (a bar or grouped-bar ``QChart``), :func:`read_back` (what the chart really
  stores, for tests and the "show as table" toggle), :func:`render_to_image` (offscreen, for PDFs)
  and :class:`ChartView` (the widget pages use; it shows a translated "No data" text instead of
  an empty chart).

Charts are secondary: every number drawn here also appears in a tile or a table (D23). A ``None``
value (not recorded) is NOT drawn as a bar (its bar has no height) and the chart says so: the
legend entry of the bar set names the categories that are not recorded, and :func:`read_back`
returns ``None`` for them. Titles, categories, series names and the unit are already-translated or
data strings supplied by the caller; the texts of this module that need a translation are the
"No data" message and the "not recorded" note of a legend entry.
"""

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QValueAxis,
)
from PySide6.QtCore import QCoreApplication, QEvent, QLocale, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QLabel, QVBoxLayout, QWidget
from shiboken6 import isValid

__all__ = [
    "PALETTE",
    "ChartData",
    "ChartKind",
    "ChartSeries",
    "ChartView",
    "build_chart",
    "read_back",
    "render_to_image",
]

#: Okabe-Ito colour-blind-safe palette; series take their colours from it in order (cycling).
PALETTE: tuple[str, ...] = (
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#000000",
)

#: The property the pseudo-locale walker looks for: the widget's own texts are data.
_DATA_PROPERTY = "i18nData"
#: The property of a bar set that lists (comma separated) the positions of its missing values.
_MISSING_PROPERTY = "missingValues"

_PLACEHOLDER = re.compile(r"%([1-9])")

_MAX_TICK_INTERVALS = 6
_STEP_FACTORS: tuple[float, ...] = (0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0)
_MIN_VIEW_WIDTH = 240
_MIN_VIEW_HEIGHT = 160

# --------------------------------------------------------------------------- plain data (no Qt)


class ChartKind(StrEnum):
    """The chart shapes the plan needs."""

    BAR = "BAR"
    GROUPED_BAR = "GROUPED_BAR"


@dataclass(frozen=True)
class ChartSeries:
    """One named row of values, one per category (``None``: not recorded, no bar is drawn)."""

    name: str
    values: tuple[float | None, ...]


@dataclass(frozen=True)
class ChartData:
    """Everything a chart shows. No Qt type; all strings are translated or data strings.

    ``BAR`` takes at most one series; ``GROUPED_BAR`` any number. Every series has exactly one
    value per category; values are finite and not negative (the axis starts at 0).
    """

    title: str
    categories: tuple[str, ...]
    series: tuple[ChartSeries, ...]
    unit: str = ""
    kind: ChartKind = ChartKind.BAR

    def __post_init__(self) -> None:
        if self.kind is ChartKind.BAR and len(self.series) > 1:
            msg = "a BAR chart takes at most one series"
            raise ValueError(msg)
        for series in self.series:
            if len(series.values) != len(self.categories):
                msg = (
                    f"series {series.name!r} has {len(series.values)} value(s) "
                    f"for {len(self.categories)} category(ies)"
                )
                raise ValueError(msg)
            for value in series.values:
                if value is not None and (not math.isfinite(value) or value < 0):
                    msg = f"series {series.name!r} has a value that is negative or not finite"
                    raise ValueError(msg)

    @property
    def is_empty(self) -> bool:
        """No categories, no series, or no value at all."""
        return (
            not self.categories
            or not self.series
            or all(value is None for series in self.series for value in series.values)
        )


# --------------------------------------------------------------------------- axis helpers


def _nice_axis(maximum: float) -> tuple[float, int, int]:
    """``(axis maximum, tick count, decimals)`` for an axis from 0 to a round number >= maximum."""
    if maximum <= 0:
        return 1.0, 2, 0
    base = 10.0 ** math.floor(math.log10(maximum))
    step = base
    intervals = 1
    for factor in _STEP_FACTORS:
        step = base * factor
        intervals = max(1, math.ceil(maximum / step - 1e-9))
        if intervals <= _MAX_TICK_INTERVALS:
            break
    decimals = 0
    while decimals < 6 and abs(step * 10**decimals - round(step * 10**decimals)) > 1e-9:
        decimals += 1
    return round(intervals * step, 9), intervals + 1, decimals


def _drawn(value: float | None) -> float:
    """The height of a bar: a value that is not recorded has none."""
    return 0.0 if value is None else float(value)


def _fill(text: str, *values: str) -> str:
    """Replace ``%1``..``%9`` by ``values`` in ONE pass (a translation may reorder them)."""

    def substitute(match: re.Match[str]) -> str:
        position = int(match.group(1)) - 1
        return values[position] if position < len(values) else match.group(0)

    return _PLACEHOLDER.sub(substitute, text)


def _legend_label(name: str, categories: tuple[str, ...], missing: list[int]) -> str:
    """The name of a bar set; with missing values it also names the categories not recorded."""
    if not missing:
        return name
    note = QCoreApplication.translate("Shell", "%1 (not recorded: %2)")
    return _fill(note, name, ", ".join(categories[position] for position in missing))


def _bar_set(
    label: str, values: tuple[float | None, ...], index: int, categories: tuple[str, ...]
) -> QBarSet:
    missing = [position for position, value in enumerate(values) if value is None]
    bar_set = QBarSet(_legend_label(label, categories, missing))
    if missing:
        bar_set.setProperty(_MISSING_PROPERTY, ",".join(str(position) for position in missing))
    bar_set.append([_drawn(value) for value in values])
    colour = QColor(PALETTE[index % len(PALETTE)])
    bar_set.setBrush(QBrush(colour))
    bar_set.setPen(QPen(QColor("#000000")))  # an outline, so bars never rely on colour alone
    return bar_set


# --------------------------------------------------------------------------- the chart


def build_chart(data: ChartData, *, locale: QLocale | None = None) -> QChart:
    """A bar chart (one ``QBarSeries``); ``GROUPED_BAR`` gets one bar set per series.

    The axis numbers follow ``locale`` (the application's default locale, which the translator
    manager sets to the active language, when not given).
    """
    chart = QChart()
    chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
    chart.setBackgroundBrush(QBrush(QColor("#FFFFFF")))
    chart.setTitle(data.title)
    chart.setLocale(QLocale() if locale is None else locale)
    chart.setLocalizeNumbers(True)

    series = QBarSeries()
    any_missing = False
    for index, row in enumerate(data.series):
        series.append(_bar_set(row.name, row.values, index, data.categories))
        any_missing = any_missing or any(value is None for value in row.values)
    chart.addSeries(series)

    category_axis = QBarCategoryAxis()
    category_axis.append(list(data.categories))
    chart.addAxis(category_axis, Qt.AlignmentFlag.AlignBottom)
    series.attachAxis(category_axis)

    highest = max((_drawn(v) for row in data.series for v in row.values), default=0.0)
    axis_max, ticks, decimals = _nice_axis(highest)
    value_axis = QValueAxis()
    value_axis.setTickCount(ticks)
    value_axis.setRange(0.0, axis_max)
    value_axis.setLabelFormat(f"%.{decimals}f")
    value_axis.setTitleText(data.unit)
    chart.addAxis(value_axis, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(value_axis)

    legend = chart.legend()
    # The legend also carries the "not recorded" note, so it is shown whenever a value is missing.
    legend.setVisible(data.kind is ChartKind.GROUPED_BAR or any_missing)
    legend.setAlignment(Qt.AlignmentFlag.AlignBottom)
    return chart


def _missing_positions(bar_set: QBarSet) -> set[int]:
    raw = bar_set.property(_MISSING_PROPERTY)
    if not isinstance(raw, str):
        return set()
    return {int(part) for part in raw.split(",") if part.isdigit()}


def read_back(
    chart: QChart,
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[float | None, ...]], ...]]:
    """The categories and, per bar set, ``(label, values)`` as actually stored in ``chart``.

    A value that was not recorded (``None`` in the data) is ``None`` here too; its bar has no
    height and the label names the category.
    """
    categories: tuple[str, ...] = ()
    bar_sets: list[tuple[str, tuple[float | None, ...]]] = []
    for series in chart.series():
        if not isinstance(series, QBarSeries):
            continue
        for axis in chart.axes(Qt.Orientation.Horizontal, series):
            if isinstance(axis, QBarCategoryAxis):
                categories = tuple(axis.categories())
        for bar_set in series.barSets():
            missing = _missing_positions(bar_set)
            values = tuple(
                None if position in missing else bar_set.at(position)
                for position in range(bar_set.count())
            )
            bar_sets.append((bar_set.label(), values))
    return categories, tuple(bar_sets)


def _no_data_text() -> str:
    return QCoreApplication.translate("Shell", "No data")


def render_to_image(
    data: ChartData, width: int, height: int, *, locale: QLocale | None = None
) -> QImage:
    """Render ``data`` offscreen (no window) to a white ``width`` x ``height`` image.

    Empty data renders the translated "No data" text, centred. The axis numbers follow ``locale``
    (the application's default locale when not given). Used for PDFs (T8.6).
    """
    if width <= 0 or height <= 0:
        msg = "the image size must be positive"
        raise ValueError(msg)
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("#FFFFFF"))
    target = QRectF(0.0, 0.0, float(width), float(height))
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        if data.is_empty:
            painter.setPen(QColor("#000000"))
            painter.drawText(target, int(Qt.AlignmentFlag.AlignCenter), _no_data_text())
        else:
            scene = QGraphicsScene()
            chart = build_chart(data, locale=locale)
            scene.addItem(chart)  # the scene owns the chart from here on
            chart.setGeometry(target)
            scene.setSceneRect(target)
            scene.render(painter, target, target)
    finally:
        painter.end()
    return image


# --------------------------------------------------------------------------- the widget


class ChartView(QWidget):
    """A chart, or a centred translated "No data" text when there is nothing to draw."""

    def __init__(self, data: ChartData | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data = ChartData("", (), ())
        self._chart: QChart | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._view = QChartView(self)
        self._view.setObjectName("chart_view")
        self._view.setProperty(_DATA_PROPERTY, True)  # title, categories and names are data
        self._view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._view.setMinimumSize(_MIN_VIEW_WIDTH, _MIN_VIEW_HEIGHT)
        layout.addWidget(self._view, 1)

        self._label = QLabel(self)
        self._label.setObjectName("chart_no_data")
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label, 1)

        self.set_data(self._data if data is None else data)

    # ------------------------------------------------------------------ API

    def set_data(self, data: ChartData) -> None:
        """Show ``data``: a chart, or the "No data" text when ``data.is_empty``."""
        self._data = data
        self._view.setAccessibleName(data.title)
        if data.is_empty:
            self._view.setVisible(False)
            self._label.setVisible(True)
            self.retranslate()
            return
        old = self._chart
        chart = build_chart(data)
        self._chart = chart
        self._view.setChart(chart)
        _discard(old)
        self._label.setVisible(False)
        self._view.setVisible(True)

    def data(self) -> ChartData:
        """The data last given to :meth:`set_data` (``None`` values are kept)."""
        return self._data

    def chart(self) -> QChart | None:
        """The chart being shown, ``None`` while the "No data" text is shown."""
        return None if self._data.is_empty else self._chart

    def retranslate(self) -> None:
        """Apply the "No data" text and the number locale of the current language."""
        self._label.setText(_no_data_text())
        if self._chart is not None and isValid(self._chart):
            self._chart.setLocale(QLocale())
            self._chart.setLocalizeNumbers(True)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()


def _discard(chart: QChart | None) -> None:
    """Release a chart that was replaced in the view (no-op when Qt already deleted it)."""
    if chart is not None and isValid(chart):
        chart.deleteLater()
