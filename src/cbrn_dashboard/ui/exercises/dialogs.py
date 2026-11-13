# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialogs of the exercises module: edition, result and metric (PLAN.md T4.5, D20, A07, A13).

Each dialog builds the service input in ``submit()``, calls the service through ``apply_change``
(a ``ServiceError`` is shown translated and the dialog stays open) and never touches storage.
Country names, metric labels and codes shown in widgets are data, flagged with ``i18nData``.
"""

import unicodedata
from functools import cmp_to_key

from PySide6.QtCore import QCollator, QCoreApplication, QDate, QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.domain.exercises import ExerciseKind
from cbrn_dashboard.services.countries import load_countries
from cbrn_dashboard.services.errors import REQUIRED, ServiceError
from cbrn_dashboard.services.exercises import (
    INVALID_NUMBER,
    EditionInput,
    EditionView,
    MetricInput,
    MetricView,
    ResultInput,
    ResultView,
    metric_label,
)
from cbrn_dashboard.ui.exercises.labels import error_label, kind_label
from cbrn_dashboard.ui.exercises.models import format_value
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import (
    AMBIGUOUS_NUMBER,
    EMPTY,
    FormatError,
    apply_locale,
    from_qdate,
    locale_for,
    parse_number,
    to_qdate,
)
from cbrn_dashboard.ui.shell.widgets import (
    FormDialog,
    apply_change,
    current_language,
    follow_language,
    mark_data,
    show_service_error,
)

__all__ = ["CountryPicker", "EditionDialog", "MetricDialog", "ResultDialog"]

_MAX_COUNT = 10_000_000
_NOT_SET = -1


def _fold(text: str) -> str:
    """Case- and accent-insensitive form of ``text`` for the country filter."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _count_spin(parent: QWidget) -> QSpinBox:
    """An optional count: the lowest value (-1) means "not recorded"."""
    spin = QSpinBox(parent)
    spin.setRange(_NOT_SET, _MAX_COUNT)
    spin.setValue(_NOT_SET)
    return spin


def _count_value(spin: QSpinBox) -> int | None:
    return None if spin.value() < 0 else spin.value()


def _date_edit(parent: QWidget, value: QDate) -> QDateEdit:
    edit = QDateEdit(value, parent)
    edit.setCalendarPopup(True)
    return edit


def _number_error(error: FormatError, field: str) -> ServiceError:
    """The service-style error for a number the user typed wrongly."""
    if error.code == EMPTY:
        return ServiceError(REQUIRED, field)
    if error.code == AMBIGUOUS_NUMBER:
        return ServiceError(AMBIGUOUS_NUMBER, field)
    return ServiceError(INVALID_NUMBER, field)


def _reformat_number(edit: QLineEdit, old_lang: str, new_lang: str) -> None:
    """Show the number typed in ``old_lang`` again in the format of ``new_lang``.

    A text that does not parse in ``old_lang`` is cleared: read in ``new_lang`` it could mean
    something else (``1,5`` is refused in en-US but is 1.5 in pt-BR), so it is never re-parsed.
    """
    text = edit.text().strip()
    if not text:
        return
    try:
        edit.setText(format_value(float(parse_number(text, old_lang)), new_lang))
    except FormatError:
        edit.clear()


# --------------------------------------------------------------------------- country picker


class CountryPicker(QWidget):
    """A search box over a checkable list of countries, named and sorted in the UI language."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("country_picker")
        self.context = context
        self._selected: set[str] = set()
        self._language = ""
        self.filter_edit = QLineEdit(self)
        self.filter_edit.setObjectName("country_filter")
        self.filter_edit.setClearButtonEnabled(True)
        self.list_widget = QListWidget(self)
        self.list_widget.setObjectName("country_list")
        mark_data(self.list_widget)
        self.counter = QLabel(self)
        self.counter.setObjectName("country_counter")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.filter_edit)
        layout.addWidget(self.list_widget)
        layout.addWidget(self.counter)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.list_widget.itemChanged.connect(self._item_changed)
        follow_language(context, self.retranslate)
        self.retranslate()

    # ----- state

    def selected_codes(self) -> tuple[str, ...]:
        return tuple(sorted(self._selected))

    def set_selected(self, codes: tuple[str, ...] | list[str]) -> None:
        self._selected = set(codes)
        self._sync_checks()
        self._update_counter()

    def item_for(self, code: str) -> QListWidgetItem | None:
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == code:
                return item
        return None

    def all_names(self) -> list[str]:
        return [self.list_widget.item(i).text() for i in range(self.list_widget.count())]

    def visible_names(self) -> list[str]:
        items = (self.list_widget.item(i) for i in range(self.list_widget.count()))
        return [item.text() for item in items if not item.isHidden()]

    # ----- internals

    def _item_changed(self, item: QListWidgetItem) -> None:
        code = str(item.data(Qt.ItemDataRole.UserRole))
        if item.checkState() == Qt.CheckState.Checked:
            self._selected.add(code)
        else:
            self._selected.discard(code)
        self._update_counter()

    def _sync_checks(self) -> None:
        self.list_widget.blockSignals(True)
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            checked = str(item.data(Qt.ItemDataRole.UserRole)) in self._selected
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list_widget.blockSignals(False)

    def _rebuild(self, lang: str) -> None:
        collator = QCollator(locale_for(lang))
        collator.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        named = [(country.name(lang), country.code) for country in load_countries()]

        def by_name(a: tuple[str, str], b: tuple[str, str]) -> int:
            return collator.compare(a[0], b[0])

        named.sort(key=cmp_to_key(by_name))
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for name, code in named:
            item = QListWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole, code)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self._sync_checks()
        self._apply_filter(self.filter_edit.text())

    def _apply_filter(self, text: str) -> None:
        needle = _fold(text.strip())
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            code = str(item.data(Qt.ItemDataRole.UserRole))
            found = not needle or needle in _fold(item.text()) or needle == code.casefold()
            item.setHidden(not found)

    def _update_counter(self) -> None:
        self.counter.setText(
            QCoreApplication.translate(
                "Exercises", "%n country(ies) selected", None, len(self._selected)
            )
        )

    def retranslate(self) -> None:
        self.filter_edit.setPlaceholderText(
            QCoreApplication.translate("Exercises", "Search countries")
        )
        lang = current_language(self.context)
        if lang != self._language:
            self._language = lang
            self._rebuild(lang)
        self._update_counter()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()


# --------------------------------------------------------------------------- edition


class EditionDialog(FormDialog):
    """Add or edit an edition: code, kind, title, dates, participants, notes and countries."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        edition: EditionView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("edition_dialog")
        self._edition = edition
        today = to_qdate(context.as_of)
        self.code_edit = QLineEdit(self)
        self.kind_combo = QComboBox(self)
        mark_data(self.kind_combo)
        for kind in ExerciseKind:
            self.kind_combo.addItem("", kind.value)
        self.title_edit = QLineEdit(self)
        self.start_edit = _date_edit(self, today)
        self.end_edit = _date_edit(self, today)
        self.participants_edit = _count_spin(self)
        self.notes_edit = QPlainTextEdit(self)
        self.notes_edit.setMaximumHeight(70)
        self.picker = CountryPicker(context, self)
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Code"), self.code_edit)
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Kind"), self.kind_combo)
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Title"), self.title_edit)
        self.add_field(
            lambda: QCoreApplication.translate("Exercises", "Start date"), self.start_edit
        )
        self.add_field(lambda: QCoreApplication.translate("Exercises", "End date"), self.end_edit)
        self.add_field(
            lambda: QCoreApplication.translate("Exercises", "Participants"),
            self.participants_edit,
        )
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Notes"), self.notes_edit)
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Countries"), self.picker)
        if edition is not None:
            self._load(edition)
        self.retranslate()

    def _load(self, edition: EditionView) -> None:
        self.code_edit.setText(edition.code)
        self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(edition.kind.value)))
        self.title_edit.setText(edition.title or "")
        self.start_edit.setDate(to_qdate(edition.start_on))
        self.end_edit.setDate(to_qdate(edition.end_on))
        self.participants_edit.setValue(
            _NOT_SET if edition.participants is None else edition.participants
        )
        self.notes_edit.setPlainText(edition.notes or "")
        self.picker.set_selected(edition.countries)

    def retranslate(self) -> None:
        super().retranslate()
        if self._edition is None:
            self.setWindowTitle(QCoreApplication.translate("Exercises", "Add edition"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Exercises", "Edit edition"))
        for index in range(self.kind_combo.count()):
            self.kind_combo.setItemText(index, kind_label(str(self.kind_combo.itemData(index))))
        for edit in (self.start_edit, self.end_edit, self.participants_edit):
            apply_locale(edit, self.language)
        self.participants_edit.setSpecialValueText(
            QCoreApplication.translate("Exercises", "Not recorded")
        )

    def submit(self) -> bool:
        service = self.context.services.exercises
        if service is None:
            return False
        data = EditionInput(
            code=self.code_edit.text().strip(),
            kind=str(self.kind_combo.currentData()),
            start_on=from_qdate(self.start_edit.date()),
            end_on=from_qdate(self.end_edit.date()),
            title=self.title_edit.text(),
            participants=_count_value(self.participants_edit),
            notes=self.notes_edit.toPlainText(),
            countries=self.picker.selected_codes(),
        )
        edition = self._edition

        def save() -> None:
            if edition is None:
                service.create_edition(data)
            else:
                service.update_edition(edition.id, data)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- result


class ResultDialog(FormDialog):
    """Add or edit the value of one metric for an edition."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        edition_id: int = 0,
        result: ResultView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("result_dialog")
        self._edition_id = edition_id
        self._result = result
        self._number_lang = self.language
        service = context.services.exercises
        wanted = None if result is None else result.metric_id
        metrics = [] if service is None else service.list_metrics(include_inactive=True)
        # Adding must never silently replace a value: leave out the metrics that already have one.
        taken: set[int] = set()
        if service is not None and result is None:
            try:
                taken = {stored.metric_id for stored in service.list_results(edition_id)}
            except ServiceError:
                taken = set()
        self._metrics: dict[int, MetricView] = {
            metric.id: metric
            for metric in metrics
            if (metric.active or metric.id == wanted) and metric.id not in taken
        }
        self.metric_combo = QComboBox(self)
        mark_data(self.metric_combo)
        for metric_id in self._metrics:
            self.metric_combo.addItem("", metric_id)
        if result is not None and result.metric_id not in self._metrics:
            self.metric_combo.addItem(result.metric_code, result.metric_id)
        self.value_edit = QLineEdit(self)
        self.respondents_edit = _count_spin(self)
        self.note_edit = QLineEdit(self)
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Metric"), self.metric_combo)
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Value"), self.value_edit)
        self.add_field(
            lambda: QCoreApplication.translate("Exercises", "Respondents"),
            self.respondents_edit,
        )
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Note"), self.note_edit)
        if result is not None:
            self.metric_combo.setCurrentIndex(max(0, self.metric_combo.findData(result.metric_id)))
            self.metric_combo.setEnabled(False)
            self.value_edit.setText(format_value(result.value, self.language))
            self.respondents_edit.setValue(
                _NOT_SET if result.respondents is None else result.respondents
            )
            self.note_edit.setText(result.note or "")
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._result is None:
            self.setWindowTitle(QCoreApplication.translate("Exercises", "Add result"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Exercises", "Edit result"))
        for index in range(self.metric_combo.count()):
            metric = self._metrics.get(int(self.metric_combo.itemData(index)))
            if metric is not None:
                self.metric_combo.setItemText(index, metric_label(metric, self.language))
        if self.language != self._number_lang:
            _reformat_number(self.value_edit, self._number_lang, self.language)
            self._number_lang = self.language
        apply_locale(self.respondents_edit, self.language)
        self.respondents_edit.setSpecialValueText(
            QCoreApplication.translate("Exercises", "Not recorded")
        )

    def submit(self) -> bool:
        service = self.context.services.exercises
        metric_id = self.metric_combo.currentData()
        if service is None:
            return False
        if metric_id is None:
            show_service_error(self.context, self, ServiceError(REQUIRED, "metric_id"), error_label)
            return False
        try:
            value = float(parse_number(self.value_edit.text(), self.language))
        except FormatError as error:
            show_service_error(self.context, self, _number_error(error, "value"), error_label)
            return False
        data = ResultInput(
            metric_id=int(metric_id),
            value=value,
            respondents=_count_value(self.respondents_edit),
            note=self.note_edit.text(),
        )
        return apply_change(
            self.context, self, error_label, lambda: service.set_result(self._edition_id, data)
        )


# --------------------------------------------------------------------------- metric


class MetricDialog(FormDialog):
    """Add or edit an evaluation metric (A07): code, labels, unit, scale, direction, active."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        metric: MetricView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("metric_dialog")
        self._metric = metric
        self._number_lang = self.language
        self.code_edit = QLineEdit(self)
        self.label_pt_edit = QLineEdit(self)
        self.label_en_edit = QLineEdit(self)
        self.label_es_edit = QLineEdit(self)
        self.unit_edit = QLineEdit(self)
        self.scale_min_edit = QLineEdit(self)
        self.scale_max_edit = QLineEdit(self)
        self.direction_combo = QComboBox(self)
        self.direction_combo.addItem("", True)
        self.direction_combo.addItem("", False)
        self.active_check = QCheckBox(self)
        self.active_check.setChecked(True)
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Code"), self.code_edit)
        self.add_field(
            lambda: QCoreApplication.translate("Exercises", "Label (Portuguese)"),
            self.label_pt_edit,
        )
        self.add_field(
            lambda: QCoreApplication.translate("Exercises", "Label (English)"), self.label_en_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Exercises", "Label (Spanish)"), self.label_es_edit
        )
        self.add_field(lambda: QCoreApplication.translate("Exercises", "Unit"), self.unit_edit)
        self.add_field(
            lambda: QCoreApplication.translate("Exercises", "Scale minimum"), self.scale_min_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Exercises", "Scale maximum"), self.scale_max_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Exercises", "Direction"), self.direction_combo
        )
        self.form.addRow(self.active_check)
        if metric is not None:
            self._load(metric)
        self.retranslate()

    def _load(self, metric: MetricView) -> None:
        lang = self.language
        self.code_edit.setText(metric.code)
        self.label_pt_edit.setText(metric.label_pt_br or "")
        self.label_en_edit.setText(metric.label_en_us or "")
        self.label_es_edit.setText(metric.label_es_es or "")
        self.unit_edit.setText(metric.unit or "")
        if metric.scale_min is not None:
            self.scale_min_edit.setText(format_value(metric.scale_min, lang))
        if metric.scale_max is not None:
            self.scale_max_edit.setText(format_value(metric.scale_max, lang))
        self.direction_combo.setCurrentIndex(0 if metric.higher_is_better else 1)
        self.active_check.setChecked(metric.active)

    def retranslate(self) -> None:
        super().retranslate()
        if self._metric is None:
            self.setWindowTitle(QCoreApplication.translate("Exercises", "Add metric"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Exercises", "Edit metric"))
        if self.language != self._number_lang:
            for edit in (self.scale_min_edit, self.scale_max_edit):
                _reformat_number(edit, self._number_lang, self.language)
            self._number_lang = self.language
        optional = QCoreApplication.translate("Exercises", "Optional")
        self.scale_min_edit.setPlaceholderText(optional)
        self.scale_max_edit.setPlaceholderText(optional)
        self.direction_combo.setItemText(
            0, QCoreApplication.translate("Exercises", "Higher is better")
        )
        self.direction_combo.setItemText(
            1, QCoreApplication.translate("Exercises", "Lower is better")
        )
        self.active_check.setText(QCoreApplication.translate("Exercises", "Active"))

    def _optional_number(self, edit: QLineEdit, field: str) -> float | None:
        text = edit.text().strip()
        if not text:
            return None
        try:
            return float(parse_number(text, self.language))
        except FormatError as error:
            raise _NumberInputError(_number_error(error, field)) from error

    def submit(self) -> bool:
        service = self.context.services.exercises
        if service is None:
            return False
        try:
            scale_min = self._optional_number(self.scale_min_edit, "scale_min")
            scale_max = self._optional_number(self.scale_max_edit, "scale_max")
        except _NumberInputError as failure:
            show_service_error(self.context, self, failure.error, error_label)
            return False
        data = MetricInput(
            code=self.code_edit.text().strip(),
            label_pt_br=self.label_pt_edit.text(),
            label_en_us=self.label_en_edit.text(),
            label_es_es=self.label_es_edit.text(),
            unit=self.unit_edit.text(),
            scale_min=scale_min,
            scale_max=scale_max,
            higher_is_better=bool(self.direction_combo.currentData()),
            active=self.active_check.isChecked(),
        )
        metric = self._metric

        def save() -> None:
            if metric is None:
                service.create_metric(data)
            else:
                service.update_metric(metric.id, data)

        return apply_change(self.context, self, error_label, save)


class _NumberInputError(Exception):
    """A typed number was refused; carries the service-style error to present."""

    def __init__(self, error: ServiceError) -> None:
        super().__init__(error.code)
        self.error = error
