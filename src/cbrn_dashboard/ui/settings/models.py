# SPDX-License-Identifier: GPL-3.0-or-later
"""Table model of the indicator targets (PLAN.md T6.1, P03).

Headers are translated on every ``headerData`` call; threshold numbers are formatted for the
current language with the shared formatting functions. The thresholds of an indicator whose unit is
a ratio (the budget execution rate) are stored as ratios and shown and typed as PERCENT. Cell
contents are data.
"""

from dataclasses import dataclass
from decimal import Decimal

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.domain.indicators import IndicatorDefinition, UnitKind
from cbrn_dashboard.services.indicators import TargetView
from cbrn_dashboard.ui.settings.labels import dimension_text, indicator_label, unit_label
from cbrn_dashboard.ui.shell.formatting import FormatError, format_number, format_percent
from cbrn_dashboard.ui.shell.widgets import Column, ModuleTableModel

__all__ = [
    "TargetRow",
    "TargetsModel",
    "is_ratio",
    "number_text",
    "percent_input_text",
    "threshold_text",
]

# A missing value in a cell (data, not a translatable text).
NOT_SET = "-"


def number_text(value: float | None, lang: str) -> str:
    """A threshold in the number format of ``lang``; ``-`` when it is not set."""
    if value is None:
        return NOT_SET
    try:
        # A whole threshold is shown without decimals ("10", not "10.0").
        return format_number(int(value) if value.is_integer() else value, lang)
    except FormatError:
        return str(value)


def is_ratio(definition: IndicatorDefinition | None) -> bool:
    """Whether the thresholds of ``definition`` are ratios (shown as percent)."""
    return definition is not None and definition.unit is UnitKind.RATIO


def threshold_text(value: float | None, lang: str, *, ratio: bool) -> str:
    """A threshold as shown in a table: a percentage for a ratio, else a plain number."""
    if value is None:
        return NOT_SET
    if not ratio:
        return number_text(value, lang)
    try:
        return format_percent(value, lang)
    except FormatError:
        return str(value)


def percent_input_text(ratio: float | None, lang: str) -> str:
    """A stored ratio as the percent number typed in ``lang`` (0.9 -> ``90``); empty if unset."""
    if ratio is None:
        return ""
    try:
        percent = (Decimal(repr(ratio)) * 100).normalize()
        return format_number(percent, lang)
    except FormatError:
        return str(ratio)


@dataclass(frozen=True)
class TargetRow:
    """A stored target with the definition of its indicator (``None`` when no longer registered).

    ``in_use`` is ``False`` when the dimension of the target is not among the dimensions that
    currently have a value; ``None`` when that is not known.
    """

    view: TargetView
    definition: IndicatorDefinition | None
    in_use: bool | None = None


def _unit(row: TargetRow) -> str:
    return "" if row.definition is None else unit_label(row.definition.unit.value)


def _status(row: TargetRow) -> str:
    if row.view.enabled:
        return QCoreApplication.translate("Settings", "Enabled")
    return QCoreApplication.translate("Settings", "Disabled")


def _use(row: TargetRow) -> str:
    if row.in_use is False:
        return QCoreApplication.translate("Settings", "Not in use")
    if row.in_use is True:
        return QCoreApplication.translate("Settings", "In use")
    return NOT_SET


class TargetsModel(ModuleTableModel):
    """The stored targets: indicator, dimension, unit, warning and critical values, switch."""

    COLUMNS = (
        Column[TargetRow](
            "indicator",
            lambda: QCoreApplication.translate("Settings", "Indicator"),
            lambda row, lang: indicator_label(row.view.indicator_code),
        ),
        Column[TargetRow](
            "dimension",
            lambda: QCoreApplication.translate("Settings", "Dimension"),
            lambda row, lang: dimension_text(row.view.dimension),
        ),
        Column[TargetRow](
            "unit",
            lambda: QCoreApplication.translate("Settings", "Unit"),
            lambda row, lang: _unit(row),
        ),
        Column[TargetRow](
            "warning",
            lambda: QCoreApplication.translate("Settings", "Warning"),
            lambda row, lang: threshold_text(
                row.view.warning_value, lang, ratio=is_ratio(row.definition)
            ),
            align_right=True,
        ),
        Column[TargetRow](
            "critical",
            lambda: QCoreApplication.translate("Settings", "Critical"),
            lambda row, lang: threshold_text(
                row.view.critical_value, lang, ratio=is_ratio(row.definition)
            ),
            align_right=True,
        ),
        Column[TargetRow](
            "status",
            lambda: QCoreApplication.translate("Settings", "Status"),
            lambda row, lang: _status(row),
        ),
        Column[TargetRow](
            "use",
            lambda: QCoreApplication.translate("Settings", "Use"),
            lambda row, lang: _use(row),
        ),
    )

    def set_targets(
        self,
        targets: list[TargetView],
        definitions: dict[str, IndicatorDefinition],
        known: dict[str, list[str]] | None = None,
    ) -> None:
        """Show ``targets``; with ``known`` (the dimensions that have a value, per indicator) a
        target whose dimension is not among them is marked "Not in use"."""
        rows: list[TargetRow] = []
        for view in targets:
            in_use: bool | None = None
            if known is not None:
                in_use = view.dimension in known.get(view.indicator_code, [])
            rows.append(TargetRow(view, definitions.get(view.indicator_code), in_use))
        self.set_rows(rows)
