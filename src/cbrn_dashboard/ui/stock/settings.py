# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings -> Infrastructure: the stock item types and the minimum stock (PLAN.md T11.13, P12).

The section lists every item type (inactive and built-in ones too) and offers Add, Edit, Deactivate
or Activate, and Delete for a user-defined type that has no lots. A built-in type keeps its code,
category and name: only its minimum and its active flag change. The minimum stock of a type is
local only (no configuration field) and has an empty code default; it is not a placeholder. A type
and its minimum are written through ``StockService.save_type_with_minimum``, so both share one
transaction.

The section reads and writes ONLY through ``context.services.stock`` (it may be ``None``: the
actions are then disabled). The dialog is opened without blocking and deletes itself when closed;
nothing here uses a message box.
"""

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.stock import StockTypeInput, StockTypeView
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_change,
    apply_tab_order,
    current_language,
    follow_language,
    make_edit_action,
    make_table_view,
)
from cbrn_dashboard.ui.stock.dialogs import StockTypeDialog
from cbrn_dashboard.ui.stock.labels import error_label, fill_placeholders
from cbrn_dashboard.ui.stock.models import StockTypesModel

__all__ = [
    "StockTypeSettingsDialog",
    "StockTypesSection",
    "create_settings_section",
    "settings_section_title",
]


def _open(dialog: QDialog) -> None:
    """Show ``dialog`` window-modally without blocking; it deletes itself when closed."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


# --------------------------------------------------------------------------- the dialog


class StockTypeSettingsDialog(StockTypeDialog):
    """The item-type dialog of the settings: the type and its minimum are saved together.

    ``StockService.save_type_with_minimum`` writes the fields and the minimum in ONE transaction:
    a refusal leaves everything as it was and creates no type.
    """

    def submit(self) -> bool:
        service = self.context.services.stock
        if service is None:
            return False
        minimum = self.minimum()
        current = self._type
        data = StockTypeInput(
            code=self.code_edit.text().strip(),
            category=str(self.category_combo.currentData()),
            label_pt_br=self.label_pt_edit.text(),
            label_en_us=self.label_en_edit.text(),
            label_es_es=self.label_es_edit.text(),
            minimum_quantity=None if current is None else current.minimum_quantity,
            active=self.active_check.isChecked(),
        )

        def save() -> None:
            # One transaction: a refusal leaves the type as it was (or not created at all).
            self.saved_type_id = service.save_type_with_minimum(
                None if current is None else current.id, data, minimum
            )

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- the section


class StockTypesSection(QWidget):
    """Settings -> Infrastructure: the stock item types, their minimum stock."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stock_types_section")
        self.context = context
        self.model = StockTypesModel(self)
        self.types_caption = QLabel(self)
        self.view = make_table_view(self.model, self)
        self.view.setObjectName("stock_types_view")
        self.types_caption.setBuddy(self.view)
        self.add_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Stock", "Add item type"),
            self.add_type,
        )
        self.edit_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Stock", "Edit item type"),
            self.edit_type,
        )
        self.deactivate_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Stock", "Deactivate"),
            self.deactivate_type,
        )
        self.activate_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Stock", "Activate"),
            self.activate_type,
        )
        self.delete_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Stock", "Delete item type"),
            self.delete_type,
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_action,
            self.edit_action,
            self.deactivate_action,
            self.activate_action,
            self.delete_action,
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self.types_caption)
        layout.addWidget(self.view, 1)
        layout.addLayout(action_row(self._actions, self))
        apply_tab_order(self)

        selection = self.view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        self.types_caption.setText(QCoreApplication.translate("Stock", "Stock item types"))
        for action in self._actions:
            action.retranslate()
        self.model.set_language(current_language(self.context))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- data

    def selected_type(self) -> StockTypeView | None:
        row = self.model.selected_row(self.view)
        return row if isinstance(row, StockTypeView) else None

    def refresh(self) -> None:
        service = self.context.services.stock
        previous = self.selected_type()
        types = [] if service is None else service.list_types(include_inactive=True)
        self.model.set_rows(types)
        if previous is not None:
            self._select_type(previous.id)
        self._update_actions()

    def _select_type(self, type_id: int | None) -> None:
        if type_id is None:
            return
        for index, row in enumerate(self.model.rows()):
            if row.id == type_id:
                self.view.selectRow(index)
                return

    def _has_lots(self, type_id: int) -> bool:
        service = self.context.services.stock
        if service is None:
            return False
        try:
            return bool(service.list_lots(type_id))
        except ServiceError:
            return True  # when in doubt the type is not offered for deletion

    def _update_actions(self, *_args: object) -> None:
        has_service = self.context.services.stock is not None
        selected = self.selected_type()
        enable = self.context.set_edit_enabled
        enable(self.add_action, has_service)
        enable(self.edit_action, has_service and selected is not None)
        enable(self.deactivate_action, has_service and selected is not None and selected.active)
        enable(self.activate_action, has_service and selected is not None and not selected.active)
        deletable = (
            has_service
            and selected is not None
            and not selected.built_in
            and not self._has_lots(selected.id)
        )
        enable(self.delete_action, deletable)

    # ----- the types

    def _dialog_saved(self) -> None:
        # Connected as a bound method, never as a lambda holding the dialog: a closure over a
        # dialog that deletes itself on close crashed Qt (access violation) when it was closed.
        dialog = self.sender()
        if isinstance(dialog, StockTypeSettingsDialog):
            self._select_type(dialog.saved_type_id)

    def add_type(self) -> None:
        dialog = StockTypeSettingsDialog(self.context, self)
        dialog.accepted.connect(self._dialog_saved)
        _open(dialog)

    def edit_type(self) -> None:
        stock_type = self.selected_type()
        if stock_type is None:
            return
        dialog = StockTypeSettingsDialog(self.context, self, stock_type)
        dialog.accepted.connect(self._dialog_saved)
        _open(dialog)

    def deactivate_type(self) -> None:
        stock_type = self.selected_type()
        service = self.context.services.stock
        if stock_type is not None and service is not None:
            type_id = stock_type.id
            apply_change(self.context, self, error_label, lambda: service.deactivate_type(type_id))

    def activate_type(self) -> None:
        stock_type = self.selected_type()
        service = self.context.services.stock
        if stock_type is not None and service is not None:
            type_id = stock_type.id
            apply_change(self.context, self, error_label, lambda: service.activate_type(type_id))

    def delete_type(self) -> None:
        stock_type = self.selected_type()
        service = self.context.services.stock
        if stock_type is None or service is None:
            return
        type_id = stock_type.id
        title = QCoreApplication.translate("Stock", "Delete item type")
        question = fill_placeholders(
            QCoreApplication.translate("Stock", "Delete item type %1?"), stock_type.code
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(self.context, self, error_label, lambda: service.delete_type(type_id))


# --------------------------------------------------------------------------- registry factories


def settings_section_title() -> str:
    return QCoreApplication.translate("Stock", "Stock item types")


def create_settings_section(context: AppContext) -> QWidget:
    return StockTypesSection(context)
