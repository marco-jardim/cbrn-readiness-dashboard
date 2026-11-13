# SPDX-License-Identifier: GPL-3.0-or-later
"""Table models of the exercises page and of the metric editor (PLAN.md T4.5).

Headers are translated on every ``headerData`` call; cells are formatted for the current language
with the shared formatting functions (dates, numbers). Cell contents are data.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.services.exercises import EditionView, MetricView, ResultView, metric_label
from cbrn_dashboard.ui.exercises.labels import kind_label
from cbrn_dashboard.ui.shell.formatting import format_date, format_number
from cbrn_dashboard.ui.shell.widgets import Column, ModuleTableModel

__all__ = [
    "EditionsModel",
    "MetricsModel",
    "ResultsModel",
    "ResultsRow",
    "format_value",
    "scale_text",
]

#: A missing value in a cell (data, not a translatable text).
NOT_RECORDED = "-"


def format_value(value: float, lang: str) -> str:
    """A metric value or scale bound: whole numbers without decimals, locale separators."""
    number: float | int = int(value) if float(value).is_integer() else value
    return format_number(number, lang)


def _count(value: int | None, lang: str) -> str:
    return NOT_RECORDED if value is None else format_number(value, lang)


def scale_text(metric: MetricView | None, lang: str) -> str:
    """The scale of a metric as text (``0 - 5``, ``>= 0``, ``<= 5``, ``-``) with its unit."""
    if metric is None:
        return NOT_RECORDED
    low = None if metric.scale_min is None else format_value(metric.scale_min, lang)
    high = None if metric.scale_max is None else format_value(metric.scale_max, lang)
    if low is None and high is None:
        return NOT_RECORDED
    if high is None:
        text = f">= {low}"
    elif low is None:
        text = f"<= {high}"
    else:
        text = f"{low} - {high}"
    return f"{text} {metric.unit}" if metric.unit else text


class EditionsModel(ModuleTableModel):
    """The editions: code, kind, title, start, end, participants, number of countries."""

    COLUMNS = (
        Column[Any](
            "code",
            lambda: QCoreApplication.translate("Exercises", "Code"),
            lambda row, lang: row.code,
        ),
        Column[Any](
            "kind",
            lambda: QCoreApplication.translate("Exercises", "Kind"),
            lambda row, lang: kind_label(row.kind),
        ),
        Column[Any](
            "title",
            lambda: QCoreApplication.translate("Exercises", "Title"),
            lambda row, lang: row.title or "",
        ),
        Column[Any](
            "start",
            lambda: QCoreApplication.translate("Exercises", "Start"),
            lambda row, lang: format_date(row.start_on, lang),
        ),
        Column[Any](
            "end",
            lambda: QCoreApplication.translate("Exercises", "End"),
            lambda row, lang: format_date(row.end_on, lang),
        ),
        Column[Any](
            "participants",
            lambda: QCoreApplication.translate("Exercises", "Participants"),
            lambda row, lang: _count(row.participants, lang),
            align_right=True,
        ),
        Column[Any](
            "countries",
            lambda: QCoreApplication.translate("Exercises", "Countries"),
            lambda row, lang: format_number(len(row.countries), lang),
            align_right=True,
        ),
    )

    def set_editions(self, editions: list[EditionView]) -> None:
        self.set_rows(editions)


@dataclass(frozen=True)
class ResultsRow:
    """A stored result with its metric (``None`` when the metric is unknown)."""

    result: ResultView
    metric: MetricView | None


class ResultsModel(ModuleTableModel):
    """The evaluation results of one edition: metric, value, respondents, scale."""

    COLUMNS = (
        Column[Any](
            "metric",
            lambda: QCoreApplication.translate("Exercises", "Metric"),
            lambda row, lang: (
                row.result.metric_code if row.metric is None else metric_label(row.metric, lang)
            ),
        ),
        Column[Any](
            "value",
            lambda: QCoreApplication.translate("Exercises", "Value"),
            lambda row, lang: format_value(row.result.value, lang),
            align_right=True,
        ),
        Column[Any](
            "respondents",
            lambda: QCoreApplication.translate("Exercises", "Respondents"),
            lambda row, lang: _count(row.result.respondents, lang),
            align_right=True,
        ),
        Column[Any](
            "scale",
            lambda: QCoreApplication.translate("Exercises", "Scale"),
            lambda row, lang: scale_text(row.metric, lang),
        ),
    )

    def set_results(self, results: list[ResultView], metrics: Mapping[int, MetricView]) -> None:
        self.set_rows([ResultsRow(result, metrics.get(result.metric_id)) for result in results])


class MetricsModel(ModuleTableModel):
    """The evaluation metrics (including inactive ones) for the settings section."""

    COLUMNS = (
        Column[Any](
            "code",
            lambda: QCoreApplication.translate("Exercises", "Code"),
            lambda row, lang: row.code,
        ),
        Column[Any](
            "label",
            lambda: QCoreApplication.translate("Exercises", "Label"),
            lambda row, lang: metric_label(row, lang),
        ),
        Column[Any](
            "unit",
            lambda: QCoreApplication.translate("Exercises", "Unit"),
            lambda row, lang: row.unit or "",
        ),
        Column[Any](
            "scale",
            lambda: QCoreApplication.translate("Exercises", "Scale"),
            lambda row, lang: scale_text(row, lang),
        ),
        Column[Any](
            "direction",
            lambda: QCoreApplication.translate("Exercises", "Direction"),
            lambda row, lang: (
                QCoreApplication.translate("Exercises", "Higher is better")
                if row.higher_is_better
                else QCoreApplication.translate("Exercises", "Lower is better")
            ),
        ),
        Column[Any](
            "status",
            lambda: QCoreApplication.translate("Exercises", "Status"),
            lambda row, lang: (
                QCoreApplication.translate("Exercises", "Active")
                if row.active
                else QCoreApplication.translate("Exercises", "Inactive")
            ),
        ),
    )
