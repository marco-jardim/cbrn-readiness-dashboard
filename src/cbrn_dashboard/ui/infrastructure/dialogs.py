# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialogs of the infrastructure module: asset, status change, maintenance and type (T3.4).

Each dialog builds the service input in ``submit()``, calls the service through ``apply_change``
(a ``ServiceError`` is shown translated and the dialog stays open) and never touches storage.
Tags, locations, notes and user-defined type labels are data, flagged with ``i18nData``.
"""

from PySide6.QtCore import QCoreApplication, QDate, QEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from cbrn_dashboard.domain.infrastructure import MaintenanceKind
from cbrn_dashboard.services.infrastructure import (
    AssetInput,
    AssetTypeInput,
    AssetTypeView,
    AssetView,
    MaintenanceView,
    StatusEventView,
)
from cbrn_dashboard.ui.infrastructure.labels import (
    STORABLE_STATUSES,
    code_label,
    error_label,
    kind_label,
    status_label,
    type_display,
)
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import apply_locale, from_qdate, to_qdate
from cbrn_dashboard.ui.shell.widgets import (
    FormDialog,
    apply_change,
    current_language,
    follow_language,
    mark_data,
)

__all__ = [
    "AssetDialog",
    "IntervalEditor",
    "MaintenanceDialog",
    "StatusDialog",
    "TypeDialog",
]

_MAX_DAYS = 36_500
_MODE_NOT_SET = 0
_MODE_NONE = 1
_MODE_DAYS = 2


def _date_edit(parent: QWidget, value: QDate) -> QDateEdit:
    edit = QDateEdit(value, parent)
    edit.setCalendarPopup(True)
    return edit


# --------------------------------------------------------------------------- interval editor


class IntervalEditor(QWidget):
    """A maintenance interval: "not set", "no scheduled maintenance" (0) or a number of days.

    ``value()`` is ``None`` (not set), ``0`` (no scheduled maintenance) or a positive number of
    days (A06). No default interval is invented: a new editor starts in the "not set" state.
    """

    def __init__(
        self, context: AppContext, parent: QWidget | None = None, *, inherit: bool = False
    ) -> None:
        super().__init__(parent)
        self.setObjectName("interval_editor")
        self.context = context
        self._inherit = inherit
        self.mode_combo = QComboBox(self)
        self.mode_combo.addItem("", _MODE_NOT_SET)
        self.mode_combo.addItem("", _MODE_NONE)
        self.mode_combo.addItem("", _MODE_DAYS)
        self.days_spin = QSpinBox(self)
        self.days_spin.setRange(1, _MAX_DAYS)
        self.days_spin.setEnabled(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.mode_combo, 1)
        layout.addWidget(self.days_spin)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        follow_language(context, self.retranslate)
        self.retranslate()

    def value(self) -> int | None:
        mode = self.mode_combo.currentData()
        if mode == _MODE_NOT_SET:
            return None
        if mode == _MODE_NONE:
            return 0
        return self.days_spin.value()

    def set_value(self, days: int | None) -> None:
        if days is None:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(_MODE_NOT_SET))
        elif days == 0:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(_MODE_NONE))
        else:
            self.days_spin.setValue(days)
            self.mode_combo.setCurrentIndex(self.mode_combo.findData(_MODE_DAYS))

    def _mode_changed(self, *_args: object) -> None:
        self.days_spin.setEnabled(self.mode_combo.currentData() == _MODE_DAYS)

    def retranslate(self) -> None:
        if self._inherit:
            not_set = QCoreApplication.translate("Infrastructure", "Not set (use the type default)")
        else:
            not_set = QCoreApplication.translate("Infrastructure", "Not set")
        self.mode_combo.setItemText(_MODE_NOT_SET, not_set)
        self.mode_combo.setItemText(
            _MODE_NONE, QCoreApplication.translate("Infrastructure", "No scheduled maintenance")
        )
        self.mode_combo.setItemText(
            _MODE_DAYS, QCoreApplication.translate("Infrastructure", "Every number of days")
        )
        self.days_spin.setSuffix(" " + QCoreApplication.translate("Infrastructure", "days"))
        apply_locale(self.days_spin, current_language(self.context))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()


# --------------------------------------------------------------------------- asset


class AssetDialog(FormDialog):
    """Add or edit an asset; on creation also the REQUIRED initial status."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        asset: AssetView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("asset_dialog")
        self._asset = asset
        service = context.services.infrastructure
        types = [] if service is None else service.list_types(include_inactive=True)
        self._types: dict[int, AssetTypeView] = {
            t.id: t for t in types if t.active or (asset is not None and t.id == asset.type_id)
        }
        self.tag_edit = QLineEdit(self)
        self.type_combo = QComboBox(self)
        mark_data(self.type_combo)
        for type_id in self._types:
            self.type_combo.addItem("", type_id)
        if asset is not None and asset.type_id not in self._types:
            self.type_combo.addItem(code_label(asset.type_code), asset.type_id)
        self.description_edit = QLineEdit(self)
        self.location_edit = QLineEdit(self)
        self.from_edit = _date_edit(self, to_qdate(context.as_of))
        self.interval = IntervalEditor(context, self, inherit=True)
        self.status_combo = QComboBox(self)
        self.status_combo.addItem("", None)
        for status in STORABLE_STATUSES:
            self.status_combo.addItem("", status.value)
        self.add_field(lambda: QCoreApplication.translate("Infrastructure", "Tag"), self.tag_edit)
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Type"), self.type_combo
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Description"),
            self.description_edit,
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Location"), self.location_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "In service from"), self.from_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Maintenance interval"),
            self.interval,
        )
        if asset is None:
            self.add_field(
                lambda: QCoreApplication.translate("Infrastructure", "Initial status"),
                self.status_combo,
            )
        else:
            self.status_combo.setVisible(False)
            self._load(asset)
        self.retranslate()

    def _load(self, asset: AssetView) -> None:
        self.tag_edit.setText(asset.tag)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(asset.type_id)))
        self.description_edit.setText(asset.description or "")
        self.location_edit.setText(asset.location or "")
        self.from_edit.setDate(to_qdate(asset.in_service_from))
        self.interval.set_value(asset.maintenance_interval_days)

    def retranslate(self) -> None:
        super().retranslate()
        if self._asset is None:
            self.setWindowTitle(QCoreApplication.translate("Infrastructure", "Add asset"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Infrastructure", "Edit asset"))
        for index in range(self.type_combo.count()):
            item = self._types.get(int(self.type_combo.itemData(index)))
            if item is not None:
                self.type_combo.setItemText(index, type_display(item, self.language))
        self.status_combo.setItemText(
            0, QCoreApplication.translate("Infrastructure", "Choose a status")
        )
        for index in range(1, self.status_combo.count()):
            self.status_combo.setItemText(
                index, status_label(str(self.status_combo.itemData(index)))
            )
        apply_locale(self.from_edit, self.language)

    def submit(self) -> bool:
        service = self.context.services.infrastructure
        if service is None:
            return False
        type_data = self.type_combo.currentData()
        asset = self._asset
        data = AssetInput(
            tag=self.tag_edit.text(),
            type_id=None if type_data is None else int(type_data),
            in_service_from=from_qdate(self.from_edit.date()),
            in_service_until=None if asset is None else asset.in_service_until,
            description=self.description_edit.text(),
            location=self.location_edit.text(),
            maintenance_interval_days=self.interval.value(),
            notes=None if asset is None else asset.notes,
        )
        initial = self.status_combo.currentData()

        def save() -> None:
            if asset is None:
                service.create_asset(data, initial)
            else:
                service.update_asset(asset.id, data)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- status change


class StatusDialog(FormDialog):
    """Add (or correct) a status event of an asset: effective date, status and note."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        asset_id: int = 0,
        asset_tag: str = "",
        event: StatusEventView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("status_dialog")
        self._asset_id = asset_id
        self._event = event
        self.asset_label = QLabel(asset_tag, self)
        mark_data(self.asset_label)
        self.effective_edit = _date_edit(self, to_qdate(context.as_of))
        self.status_combo = QComboBox(self)
        for status in STORABLE_STATUSES:
            self.status_combo.addItem("", status.value)
        self.note_edit = QLineEdit(self)
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Asset"), self.asset_label
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Effective on"),
            self.effective_edit,
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Status"), self.status_combo
        )
        self.add_field(lambda: QCoreApplication.translate("Infrastructure", "Note"), self.note_edit)
        if event is not None:
            self.effective_edit.setDate(to_qdate(event.effective_on))
            self.status_combo.setCurrentIndex(
                max(0, self.status_combo.findData(event.status.value))
            )
            self.note_edit.setText(event.note or "")
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._event is None:
            self.setWindowTitle(QCoreApplication.translate("Infrastructure", "Change status"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Infrastructure", "Edit status entry"))
        for index in range(self.status_combo.count()):
            self.status_combo.setItemText(
                index, status_label(str(self.status_combo.itemData(index)))
            )
        apply_locale(self.effective_edit, self.language)

    def submit(self) -> bool:
        service = self.context.services.infrastructure
        if service is None:
            return False
        on = from_qdate(self.effective_edit.date())
        status = str(self.status_combo.currentData())
        note = self.note_edit.text()
        event = self._event
        asset_id = self._asset_id

        def save() -> None:
            if event is None:
                service.change_status(asset_id, on, status, note)
            else:
                service.update_status_event(event.id, on, status, note)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- maintenance


class MaintenanceDialog(FormDialog):
    """Record (or correct) a maintenance event: date, kind, optional next due date and note."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        asset_id: int = 0,
        asset_tag: str = "",
        record: MaintenanceView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("maintenance_dialog")
        self._asset_id = asset_id
        self._record = record
        self.asset_label = QLabel(asset_tag, self)
        mark_data(self.asset_label)
        self.performed_edit = _date_edit(self, to_qdate(context.as_of))
        self.kind_combo = QComboBox(self)
        for kind in MaintenanceKind:
            self.kind_combo.addItem("", kind.value)
        self.next_check = QCheckBox(self)
        self.next_edit = _date_edit(self, to_qdate(context.as_of))
        self.next_edit.setEnabled(False)
        self.note_edit = QLineEdit(self)
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Asset"), self.asset_label
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Performed on"),
            self.performed_edit,
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Kind"), self.kind_combo
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Next due"), self.next_edit
        )
        self.form.addRow(self.next_check)
        self.add_field(lambda: QCoreApplication.translate("Infrastructure", "Note"), self.note_edit)
        self.next_check.toggled.connect(self.next_edit.setEnabled)
        if record is not None:
            self.performed_edit.setDate(to_qdate(record.performed_on))
            self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(record.kind.value)))
            if record.next_due_on is not None:
                self.next_edit.setDate(to_qdate(record.next_due_on))
                self.next_check.setChecked(True)
            self.note_edit.setText(record.note or "")
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._record is None:
            self.setWindowTitle(QCoreApplication.translate("Infrastructure", "Record maintenance"))
        else:
            self.setWindowTitle(
                QCoreApplication.translate("Infrastructure", "Edit maintenance entry")
            )
        for index in range(self.kind_combo.count()):
            self.kind_combo.setItemText(index, kind_label(str(self.kind_combo.itemData(index))))
        self.next_check.setText(
            QCoreApplication.translate("Infrastructure", "Set the next due date")
        )
        apply_locale(self.performed_edit, self.language)
        apply_locale(self.next_edit, self.language)

    def submit(self) -> bool:
        service = self.context.services.infrastructure
        if service is None:
            return False
        performed = from_qdate(self.performed_edit.date())
        kind = str(self.kind_combo.currentData())
        due = from_qdate(self.next_edit.date()) if self.next_check.isChecked() else None
        note = self.note_edit.text()
        record = self._record
        asset_id = self._asset_id

        def save() -> None:
            if record is None:
                service.record_maintenance(asset_id, performed, kind, due, note)
            else:
                service.update_maintenance(record.id, performed, kind, due, note)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- asset type


class TypeDialog(FormDialog):
    """Add or edit an asset type (A06): code, three labels, default interval and active flag.

    A built-in type keeps its code and (empty) labels: those fields are read-only.
    """

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        asset_type: AssetTypeView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("type_dialog")
        self._type = asset_type
        self.code_edit = QLineEdit(self)
        self.label_pt_edit = QLineEdit(self)
        self.label_en_edit = QLineEdit(self)
        self.label_es_edit = QLineEdit(self)
        self.interval = IntervalEditor(context, self)
        self.active_check = QCheckBox(self)
        self.active_check.setChecked(True)
        self.add_field(lambda: QCoreApplication.translate("Infrastructure", "Code"), self.code_edit)
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Label (Portuguese)"),
            self.label_pt_edit,
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Label (English)"),
            self.label_en_edit,
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Label (Spanish)"),
            self.label_es_edit,
        )
        self.add_field(
            lambda: QCoreApplication.translate("Infrastructure", "Default interval"),
            self.interval,
        )
        self.form.addRow(self.active_check)
        if asset_type is not None:
            self._load(asset_type)
        self.retranslate()

    def _load(self, asset_type: AssetTypeView) -> None:
        self.code_edit.setText(asset_type.code)
        self.label_pt_edit.setText(asset_type.label_pt_br or "")
        self.label_en_edit.setText(asset_type.label_en_us or "")
        self.label_es_edit.setText(asset_type.label_es_es or "")
        self.interval.set_value(asset_type.default_maintenance_interval_days)
        self.active_check.setChecked(asset_type.active)
        if asset_type.built_in:
            labels = (self.label_pt_edit, self.label_en_edit, self.label_es_edit)
            for edit in (self.code_edit, *labels):
                edit.setReadOnly(True)
                edit.setEnabled(False)

    def retranslate(self) -> None:
        super().retranslate()
        if self._type is None:
            self.setWindowTitle(QCoreApplication.translate("Infrastructure", "Add asset type"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Infrastructure", "Edit asset type"))
        self.active_check.setText(QCoreApplication.translate("Infrastructure", "Active"))

    def submit(self) -> bool:
        service = self.context.services.infrastructure
        if service is None:
            return False
        data = AssetTypeInput(
            code=self.code_edit.text().strip(),
            label_pt_br=self.label_pt_edit.text(),
            label_en_us=self.label_en_edit.text(),
            label_es_es=self.label_es_edit.text(),
            default_maintenance_interval_days=self.interval.value(),
            active=self.active_check.isChecked(),
        )
        current = self._type

        def save() -> None:
            if current is None:
                service.create_type(data)
            else:
                service.update_type(current.id, data)

        return apply_change(self.context, self, error_label, save)
