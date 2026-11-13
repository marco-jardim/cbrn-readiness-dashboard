# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialogs of the budget module: entry, execution row and funding source (PLAN.md T5.4, D15).

Amounts are TYPED in the locale's format in a line edit and parsed with ``parse_amount`` into minor
units; the service only ever receives minor units. A ``FormatError`` (and a ``ServiceError``) is
shown translated and keeps the dialog open; nothing is written. Source labels, codes and currency
codes shown in widgets are data, flagged with ``i18nData``.
"""

from datetime import date
from typing import Any

from PySide6.QtCore import QCoreApplication, QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from cbrn_dashboard.domain.budget import CURRENCY_DECIMALS, DEFAULT_CURRENCY, fiscal_year_of
from cbrn_dashboard.services.budget import (
    CURRENCY_IN_USE,
    EntryInput,
    EntryView,
    ExecutionView,
    SourceInput,
    SourceView,
)
from cbrn_dashboard.services.errors import REQUIRED, ServiceError
from cbrn_dashboard.ui.budget.labels import error_label, source_display
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import (
    EMPTY,
    FormatError,
    apply_locale,
    format_amount,
    from_qdate,
    parse_amount,
    to_qdate,
)
from cbrn_dashboard.ui.shell.widgets import (
    FormDialog,
    apply_change,
    mark_data,
    show_service_error,
)

__all__ = [
    "EntryDialog",
    "ExecutionDialog",
    "SourceDialog",
    "configured_currency",
    "show_format_error",
]

_MIN_YEAR = 1900
_MAX_YEAR = 2200


def configured_currency(context: AppContext) -> str:
    """The default currency of the configuration (A08); the built-in default without it."""
    config: Any = getattr(context.services, "config", None)
    if config is None:
        return DEFAULT_CURRENCY
    try:
        return str(config.load().default_currency)
    except ServiceError:
        return DEFAULT_CURRENCY


def show_format_error(
    context: AppContext, parent: QWidget | None, error: FormatError, field: str
) -> None:
    """Show a number the user typed wrongly, translated (an empty required value is REQUIRED)."""
    code = REQUIRED if error.code == EMPTY else error.code
    show_service_error(context, parent, ServiceError(code, field), error_label)


def _reformat_amount(edit: QLineEdit, currency: str, old_lang: str, new_lang: str) -> None:
    """Show the amount typed in ``old_lang`` again in the format of ``new_lang``.

    Text that did not parse in ``old_lang`` is cleared: left as typed it would be read in
    ``new_lang`` and could silently become another amount (``1.234`` refused in en-US is 1234 in
    pt-BR).
    """
    text = edit.text().strip()
    if not text:
        return
    try:
        edit.setText(format_amount(parse_amount(text, currency, old_lang), currency, new_lang))
    except FormatError:
        edit.clear()


def _date_edit(parent: QWidget, value: QDate) -> QDateEdit:
    edit = QDateEdit(value, parent)
    edit.setCalendarPopup(True)
    return edit


# --------------------------------------------------------------------------- entry


class EntryDialog(FormDialog):
    """Add or edit a budget entry: year, source, currency, allocated amount, description, notes."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        entry: EntryView | None = None,
        fiscal_year: int | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("entry_dialog")
        self._entry = entry
        self._amount_lang = self.language
        service = context.services.budget
        wanted = None if entry is None else entry.source_id
        sources = [] if service is None else service.list_sources(include_inactive=True)
        self._sources: dict[int, SourceView] = {
            source.id: source for source in sources if source.active or source.id == wanted
        }
        year = fiscal_year_of(context.as_of) if fiscal_year is None else fiscal_year
        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(_MIN_YEAR, _MAX_YEAR)
        self.year_spin.setValue(year if entry is None else entry.fiscal_year)
        self.source_combo = QComboBox(self)
        mark_data(self.source_combo)
        for source_id in self._sources:
            self.source_combo.addItem("", source_id)
        if entry is not None and entry.source_id not in self._sources:
            self.source_combo.addItem(entry.source_code, entry.source_id)
        self.currency_combo = QComboBox(self)
        mark_data(self.currency_combo)
        for code in CURRENCY_DECIMALS:
            self.currency_combo.addItem(code, code)
        currency = configured_currency(context) if entry is None else entry.currency
        self.currency_combo.setCurrentIndex(max(0, self.currency_combo.findData(currency)))
        # D15: the stored minor units of the rows would be read in another currency.
        self._currency_locked = entry is not None and bool(entry.executions)
        self.currency_combo.setEnabled(not self._currency_locked)
        self.allocated_edit = QLineEdit(self)
        self.description_edit = QLineEdit(self)
        self.notes_edit = QPlainTextEdit(self)
        self.notes_edit.setMaximumHeight(70)
        self.add_field(lambda: QCoreApplication.translate("Budget", "Fiscal year"), self.year_spin)
        self.add_field(lambda: QCoreApplication.translate("Budget", "Source"), self.source_combo)
        self.add_field(
            lambda: QCoreApplication.translate("Budget", "Currency"), self.currency_combo
        )
        self.add_field(
            lambda: QCoreApplication.translate("Budget", "Allocated amount"), self.allocated_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Budget", "Description"), self.description_edit
        )
        self.add_field(lambda: QCoreApplication.translate("Budget", "Notes"), self.notes_edit)
        if entry is not None:
            self._load(entry)
        self.retranslate()

    def _load(self, entry: EntryView) -> None:
        self.source_combo.setCurrentIndex(max(0, self.source_combo.findData(entry.source_id)))
        if entry.allocated_minor is not None:
            self.allocated_edit.setText(
                format_amount(entry.allocated_minor, entry.currency, self.language)
            )
        self.description_edit.setText(entry.description)
        self.notes_edit.setPlainText(entry.notes or "")

    def selected_currency(self) -> str:
        return str(self.currency_combo.currentData())

    def retranslate(self) -> None:
        super().retranslate()
        if self._entry is None:
            self.setWindowTitle(QCoreApplication.translate("Budget", "Add entry"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Budget", "Edit entry"))
        lang = self.language
        locked_reason = error_label(CURRENCY_IN_USE) if self._currency_locked else ""
        self.currency_combo.setToolTip(locked_reason)
        for index in range(self.source_combo.count()):
            source = self._sources.get(int(self.source_combo.itemData(index)))
            if source is not None:
                self.source_combo.setItemText(index, source_display(source, lang))
        if lang != self._amount_lang:
            _reformat_amount(self.allocated_edit, self.selected_currency(), self._amount_lang, lang)
            self._amount_lang = lang
        self.allocated_edit.setPlaceholderText(QCoreApplication.translate("Budget", "Not set"))

    def submit(self) -> bool:
        service = self.context.services.budget
        if service is None:
            return False
        currency = self.selected_currency()
        text = self.allocated_edit.text().strip()
        allocated: int | None = None
        if text:
            try:
                allocated = parse_amount(text, currency, self.language)
            except FormatError as error:
                show_format_error(self.context, self, error, "allocated_minor")
                return False
        source_id = self.source_combo.currentData()
        data = EntryInput(
            fiscal_year=self.year_spin.value(),
            source_id=None if source_id is None else int(source_id),
            allocated_minor=allocated,
            currency=currency,
            description=self.description_edit.text(),
            notes=self.notes_edit.toPlainText(),
        )
        entry = self._entry

        def save() -> None:
            if entry is None:
                service.create_entry(data)
            else:
                service.update_entry(entry.id, data)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- execution row


class ExecutionDialog(FormDialog):
    """Add or edit a dated execution row of an entry; the amount is typed in the locale's format."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None,
        entry: EntryView,
        execution: ExecutionView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("execution_dialog")
        self._entry = entry
        self._execution = execution
        self._amount_lang = self.language
        self.currency_label = QLabel(entry.currency, self)
        mark_data(self.currency_label)
        if execution is not None:
            start = execution.executed_on
        elif fiscal_year_of(context.as_of) == entry.fiscal_year:
            start = context.as_of
        else:
            start = date(entry.fiscal_year, 1, 1)
        self.date_edit = _date_edit(self, to_qdate(start))
        # A08: the fiscal year is the calendar year; the service refuses a date outside it.
        self.date_edit.setDateRange(
            to_qdate(date(entry.fiscal_year, 1, 1)), to_qdate(date(entry.fiscal_year, 12, 31))
        )
        self.amount_edit = QLineEdit(self)
        self.note_edit = QLineEdit(self)
        self.add_field(
            lambda: QCoreApplication.translate("Budget", "Currency"), self.currency_label
        )
        self.add_field(lambda: QCoreApplication.translate("Budget", "Date"), self.date_edit)
        self.add_field(lambda: QCoreApplication.translate("Budget", "Amount"), self.amount_edit)
        self.add_field(lambda: QCoreApplication.translate("Budget", "Note"), self.note_edit)
        if execution is not None:
            self.amount_edit.setText(
                format_amount(execution.amount_minor, entry.currency, self.language)
            )
            self.note_edit.setText(execution.note or "")
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._execution is None:
            self.setWindowTitle(QCoreApplication.translate("Budget", "Add execution"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Budget", "Edit execution"))
        lang = self.language
        apply_locale(self.date_edit, lang)
        if lang != self._amount_lang:
            _reformat_amount(self.amount_edit, self._entry.currency, self._amount_lang, lang)
            self._amount_lang = lang

    def submit(self) -> bool:
        service = self.context.services.budget
        if service is None:
            return False
        try:
            day = from_qdate(self.date_edit.date())
        except FormatError as error:
            show_format_error(self.context, self, error, "executed_on")
            return False
        try:
            amount = parse_amount(self.amount_edit.text(), self._entry.currency, self.language)
        except FormatError as error:
            show_format_error(self.context, self, error, "amount_minor")
            return False
        note = self.note_edit.text()
        entry_id = self._entry.id
        execution = self._execution

        def save() -> None:
            if execution is None:
                service.add_execution(entry_id, day, amount, note)
            else:
                service.update_execution(execution.id, day, amount, note)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- funding source


class SourceDialog(FormDialog):
    """Add or edit a funding source (D16); a built-in source keeps its code and its labels."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        source: SourceView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("source_dialog")
        self._source = source
        self.code_edit = QLineEdit(self)
        self.label_pt_edit = QLineEdit(self)
        self.label_en_edit = QLineEdit(self)
        self.label_es_edit = QLineEdit(self)
        self.active_check = QCheckBox(self)
        self.active_check.setChecked(True)
        self.add_field(lambda: QCoreApplication.translate("Budget", "Code"), self.code_edit)
        self.add_field(
            lambda: QCoreApplication.translate("Budget", "Label (Portuguese)"),
            self.label_pt_edit,
        )
        self.add_field(
            lambda: QCoreApplication.translate("Budget", "Label (English)"), self.label_en_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Budget", "Label (Spanish)"), self.label_es_edit
        )
        self.form.addRow(self.active_check)
        if source is not None:
            self.code_edit.setText(source.code)
            self.label_pt_edit.setText(source.label_pt_br or "")
            self.label_en_edit.setText(source.label_en_us or "")
            self.label_es_edit.setText(source.label_es_es or "")
            self.active_check.setChecked(source.active)
            if source.built_in:
                for edit in (
                    self.code_edit,
                    self.label_pt_edit,
                    self.label_en_edit,
                    self.label_es_edit,
                ):
                    edit.setReadOnly(True)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._source is None:
            self.setWindowTitle(QCoreApplication.translate("Budget", "Add funding source"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Budget", "Edit funding source"))
        self.active_check.setText(QCoreApplication.translate("Budget", "Active"))

    def submit(self) -> bool:
        service = self.context.services.budget
        if service is None:
            return False
        source = self._source
        code = self.code_edit.text().strip()
        if source is not None and source.built_in:
            code = source.code
        data = SourceInput(
            code=code,
            label_pt_br=self.label_pt_edit.text(),
            label_en_us=self.label_en_edit.text(),
            label_es_es=self.label_es_edit.text(),
            active=self.active_check.isChecked(),
        )

        def save() -> None:
            if source is None:
                service.create_source(data)
            else:
                service.update_source(source.id, data)

        return apply_change(self.context, self, error_label, save)
