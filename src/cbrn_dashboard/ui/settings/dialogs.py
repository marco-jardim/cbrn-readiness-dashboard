# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialog of the Settings page: add or edit an indicator target (PLAN.md T6.1, P03) and the small
helpers the sections share.

Thresholds are TYPED in the locale's format and parsed with ``parse_number``; the service only ever
receives floats. A ``FormatError`` or a ``ServiceError`` is shown translated and keeps the dialog
open; nothing is written. Indicator and dimension texts shown in combo boxes are data, flagged with
``i18nData``.
"""

from decimal import Decimal

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QLineEdit, QWidget

from cbrn_dashboard.domain.indicators import IndicatorDefinition
from cbrn_dashboard.domain.registry import build_registry
from cbrn_dashboard.services.errors import REQUIRED, ServiceError
from cbrn_dashboard.services.indicators import TargetView
from cbrn_dashboard.ui.settings.labels import (
    direction_label,
    error_label,
    indicator_label,
    unit_label,
)
from cbrn_dashboard.ui.settings.models import is_ratio, number_text, percent_input_text
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import (
    INVALID_NUMBER,
    FormatError,
    format_number,
    parse_number,
)
from cbrn_dashboard.ui.shell.widgets import (
    FormDialog,
    apply_change,
    mark_data,
    show_service_error,
)

__all__ = [
    "TargetDialog",
    "input_text",
    "parse_whole",
    "reformat_number",
    "show_error",
]


def show_error(
    context: AppContext, parent: QWidget | None, code: str, field: str | None = None
) -> None:
    """Show the translated message of ``code`` through the prompts interface."""
    show_service_error(context, parent, ServiceError(code, field), error_label)


def parse_whole(text: str, lang: str) -> int:
    """A whole number typed in ``lang``; ``FormatError`` (``INVALID_NUMBER``) for a fraction."""
    value = parse_number(text, lang)
    if value != value.to_integral_value():
        raise FormatError(INVALID_NUMBER, "not a whole number")
    return int(value)


def input_text(value: float | None, lang: str) -> str:
    """A threshold as it is typed in ``lang`` (empty when it is not set)."""
    return "" if value is None else number_text(value, lang)


def reformat_number(edit: QLineEdit, old_lang: str, new_lang: str) -> None:
    """Show the number typed in ``old_lang`` again in the format of ``new_lang`` (if it parses)."""
    text = edit.text().strip()
    if not text:
        return
    try:
        edit.setText(format_number(parse_number(text, old_lang), new_lang))
    except FormatError:
        return


class TargetDialog(FormDialog):
    """Add or edit the target of one (indicator, dimension): thresholds and the enable switch."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        target: TargetView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("target_dialog")
        self._target = target
        self._value_lang = self.language
        service = context.services.indicators
        found = service.definitions() if service is not None else list(build_registry())
        self._definitions: dict[str, IndicatorDefinition] = {item.code: item for item in found}
        self._known = self._known_dimensions()

        self.indicator_combo = QComboBox(self)
        self.indicator_combo.setObjectName("indicator_combo")
        mark_data(self.indicator_combo)
        for code in self._definitions:
            self.indicator_combo.addItem("", code)
        if target is not None and target.indicator_code not in self._definitions:
            self.indicator_combo.addItem("", target.indicator_code)
        self.dimension_combo = QComboBox(self)
        self.dimension_combo.setObjectName("dimension_combo")
        self.dimension_combo.setEditable(True)
        mark_data(self.dimension_combo)
        self.unit_value = QLabel(self)
        self.unit_value.setObjectName("unit_value")
        self.direction_value = QLabel(self)
        self.direction_value.setObjectName("direction_value")
        self.keys_hint = QLabel(self)
        self.keys_hint.setObjectName("keys_hint")
        self.warning_edit = QLineEdit(self)
        self.warning_edit.setObjectName("warning_edit")
        self.critical_edit = QLineEdit(self)
        self.critical_edit.setObjectName("critical_edit")
        self.enabled_check = QCheckBox(self)
        self.enabled_check.setObjectName("enabled_check")
        self.enabled_check.setChecked(True)

        self.add_field(
            lambda: QCoreApplication.translate("Settings", "Indicator"), self.indicator_combo
        )
        self.add_field(
            lambda: QCoreApplication.translate("Settings", "Dimension"), self.dimension_combo
        )
        self.form.addRow(self.keys_hint)
        self.add_field(lambda: QCoreApplication.translate("Settings", "Unit"), self.unit_value)
        self.add_field(
            lambda: QCoreApplication.translate("Settings", "Direction"), self.direction_value
        )
        self.add_field(
            lambda: QCoreApplication.translate("Settings", "Warning value"), self.warning_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Settings", "Critical value"), self.critical_edit
        )
        self.form.addRow(self.enabled_check)

        if target is not None:
            index = self.indicator_combo.findData(target.indicator_code)
            self.indicator_combo.setCurrentIndex(max(0, index))
            self.warning_edit.setText(self._input(target.warning_value))
            self.critical_edit.setText(self._input(target.critical_value))
            self.enabled_check.setChecked(target.enabled)
            # The key of a stored target (indicator and dimension) is not edited.
            self.indicator_combo.setEnabled(False)
        self.indicator_combo.currentIndexChanged.connect(self._indicator_changed)
        self._fill_dimensions()
        self.retranslate()

    # ----- the indicator and its dimensions

    def _known_dimensions(self) -> dict[str, list[str]]:
        """The dimensions that currently have a value, per indicator (none without a service)."""
        service = self.context.services.indicators
        if service is None:
            return {}
        try:
            return service.known_dimensions(self.context.as_of)
        except ServiceError:
            return {}

    def selected_code(self) -> str:
        """The code of the selected indicator (empty when there is none)."""
        data = self.indicator_combo.currentData()
        return data if isinstance(data, str) else ""

    def _definition(self) -> IndicatorDefinition | None:
        return self._definitions.get(self.selected_code())

    def _indicator_changed(self, _index: int) -> None:
        self._fill_dimensions()
        self._show_definition()

    def _fill_dimensions(self) -> None:
        definition = self._definition()
        keys = () if definition is None else definition.dimension_keys
        self.dimension_combo.clear()
        if self._target is not None:
            self.dimension_combo.addItem(self._target.dimension)
            self.dimension_combo.setCurrentIndex(0)
            self.dimension_combo.setEnabled(False)
            return
        self.dimension_combo.addItems(self._known.get(self.selected_code(), []))
        self.dimension_combo.setCurrentIndex(-1)
        self.dimension_combo.setEditText("")
        self.dimension_combo.setEnabled(bool(keys))

    def _show_definition(self) -> None:
        definition = self._definition()
        if definition is None:
            self.unit_value.setText("")
            self.direction_value.setText("")
            self.keys_hint.setText("")
            return
        self.unit_value.setText(unit_label(definition.unit.value))
        self.direction_value.setText(direction_label(definition.direction.value))
        if definition.dimension_keys:
            self.keys_hint.setText(
                QCoreApplication.translate("Settings", "Dimension keys: %1").replace(
                    "%1", ", ".join(definition.dimension_keys)
                )
            )
        else:
            self.keys_hint.setText(
                QCoreApplication.translate("Settings", "This indicator has no dimension.")
            )

    def dimension(self) -> str:
        """The dimension text to store: the fixed one of a stored target, else the typed one."""
        if self._target is not None:
            return self._target.dimension
        definition = self._definition()
        if definition is None or not definition.dimension_keys:
            return ""
        return self.dimension_combo.currentText().strip()

    # ----- texts

    def retranslate(self) -> None:
        super().retranslate()
        if self._target is None:
            self.setWindowTitle(QCoreApplication.translate("Settings", "Add target"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Settings", "Edit target"))
        self.enabled_check.setText(QCoreApplication.translate("Settings", "Enabled"))
        for index in range(self.indicator_combo.count()):
            self.indicator_combo.setItemText(
                index, indicator_label(str(self.indicator_combo.itemData(index)))
            )
        self._show_definition()
        lang = self.language
        if lang != self._value_lang:
            reformat_number(self.warning_edit, self._value_lang, lang)
            reformat_number(self.critical_edit, self._value_lang, lang)
            self._value_lang = lang

    # ----- saving

    def _ratio(self) -> bool:
        """Whether the thresholds of the selected indicator are typed as percent (ratio unit)."""
        return is_ratio(self._definition())

    def _input(self, value: float | None) -> str:
        """A stored threshold as typed: a percent number for a ratio indicator."""
        if self._ratio():
            return percent_input_text(value, self.language)
        return input_text(value, self.language)

    def _threshold(self, edit: QLineEdit) -> float | None:
        """The stored value of a typed threshold: percent / 100 for a ratio indicator."""
        text = edit.text().strip()
        if not text:
            return None
        number = parse_number(text, self.language)
        if self._ratio():
            return float(number / Decimal(100))
        return float(number)

    def submit(self) -> bool:
        service = self.context.services.indicators
        if service is None:
            return False
        code = self.selected_code()
        if not code:
            show_error(self.context, self, REQUIRED, "indicator_code")
            return False
        try:
            warning = self._threshold(self.warning_edit)
            critical = self._threshold(self.critical_edit)
        except FormatError as error:
            show_error(self.context, self, error.code, "threshold")
            return False
        dimension = self.dimension()
        enabled = self.enabled_check.isChecked()

        def save() -> None:
            service.set_target(
                code,
                dimension,
                warning_value=warning,
                critical_value=critical,
                enabled=enabled,
            )

        return apply_change(self.context, self, error_label, save)
