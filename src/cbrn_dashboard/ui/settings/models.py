# SPDX-License-Identifier: GPL-3.0-or-later
"""Table model of the indicator targets (PLAN.md T6.1, P03).

Headers are translated on every ``headerData`` call; threshold numbers are formatted for the
current language with the shared formatting functions. Cell contents are data.
"""

from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.domain.indicators import IndicatorDefinition
from cbrn_dashboard.services.indicators import TargetView
from cbrn_dashboard.ui.settings.labels import dimension_text, indicator_label, unit_label
from cbrn_dashboard.ui.shell.formatting import FormatError, format_number
from cbrn_dashboard.ui.shell.widgets import Column, ModuleTableModel

__all__ = ["TargetRow", "TargetsModel", "number_text"]

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


@dataclass(frozen=True)
class TargetRow:
    """A stored target with the definition of its indicator (``None`` when no longer registered)."""

    view: TargetView
    definition: IndicatorDefinition | None


def _unit(row: TargetRow) -> str:
    return "" if row.definition is None else unit_label(row.definition.unit.value)


def _status(row: TargetRow) -> str:
    if row.view.enabled:
        return QCoreApplication.translate("Settings", "Enabled")
    return QCoreApplication.translate("Settings", "Disabled")


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
            lambda row, lang: number_text(row.view.warning_value, lang),
            align_right=True,
        ),
        Column[TargetRow](
            "critical",
            lambda: QCoreApplication.translate("Settings", "Critical"),
            lambda row, lang: number_text(row.view.critical_value, lang),
            align_right=True,
        ),
        Column[TargetRow](
            "status",
            lambda: QCoreApplication.translate("Settings", "Status"),
            lambda row, lang: _status(row),
        ),
    )

    def set_targets(
        self, targets: list[TargetView], definitions: dict[str, IndicatorDefinition]
    ) -> None:
        self.set_rows([TargetRow(view, definitions.get(view.indicator_code)) for view in targets])
