# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings -> Infrastructure: the stock item types and the minimum stock (PLAN.md T11.13, P12).

The section lists every item type (inactive and built-in ones too) and offers Add, Edit, Deactivate
or Activate, and Delete for a user-defined type that has no lots. A built-in type keeps its code,
category and name: only its minimum and its active flag change. The minimum stock of a type is the
placeholder P12 (local only, no configuration field): its "to be confirmed" badge and Confirm
button show until the operator confirms it or sets a minimum, as the infrastructure section does
for A06. A minimum is always written through ``StockService.set_minimum`` with the confirmation
of P12, so the minimum and the confirmation share one transaction.

The section reads and writes ONLY through ``context.services.stock`` and
``context.services.config`` (either may be ``None``: the actions are then disabled and the badge
hidden). The dialog is opened without blocking and deletes itself when closed; nothing here uses a
message box.
"""

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

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
    "PLACEHOLDER_MINIMUM",
    "StockTypeSettingsDialog",
    "StockTypesSection",
    "create_settings_section",
    "settings_section_title",
]

#: The placeholder of the minimum stock per item type (local only, no configuration field).
PLACEHOLDER_MINIMUM = "P12"


def _open(dialog: QDialog) -> None:
    """Show ``dialog`` window-modally without blocking; it deletes itself when closed."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


# --------------------------------------------------------------------------- the dialog


class StockTypeSettingsDialog(StockTypeDialog):
    """The item-type dialog of the settings: a changed minimum confirms P12 (same transaction).

    The other fields are stored first with the minimum the type already has (a refusal leaves
    everything as it was); the minimum then goes through ``StockService.set_minimum`` with the
    confirmation of P12, which writes the minimum and the confirmation in one transaction. A
    minimum that does not change confirms nothing.
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
            if current is None:
                type_id = service.create_type(data)
                self.saved_type_id = type_id
                # From here on the type exists: a retry (after a refused minimum) edits it.
                self._type = service.get_type(type_id)
                changed = minimum is not None
            else:
                type_id = current.id
                service.update_type(type_id, data)
                self.saved_type_id = type_id
                changed = minimum != current.minimum_quantity
            if changed:
                service.set_minimum(type_id, minimum, confirm_placeholder=PLACEHOLDER_MINIMUM)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- the section


class StockTypesSection(QWidget):
    """Settings -> Infrastructure: the stock item types, their minimum stock and the P12 badge."""

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
        self.confirm_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Stock", "Confirm"),
            self.confirm_placeholder,
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_action,
            self.edit_action,
            self.deactivate_action,
            self.activate_action,
            self.delete_action,
            self.confirm_action,
        )
        #: Whether the badge of P12 is due (hidden without a readable configuration).
        self._badge_due = False
        self.minimum_note = QLabel(self)
        self.minimum_note.setObjectName("stock_minimum_note")
        self.minimum_note.setWordWrap(True)
        self.badge_label = QLabel(self)
        self.badge_label.setObjectName("stock_minimum_badge")
        self.confirm_button = QToolButton(self)
        self.confirm_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.confirm_button.setDefaultAction(self.confirm_action)

        layout = QVBoxLayout(self)
        layout.addWidget(self.types_caption)
        layout.addWidget(self.view, 1)
        layout.addLayout(action_row(self._actions[:5], self))
        layout.addWidget(self.minimum_note)
        badge_row = QHBoxLayout()
        badge_row.addWidget(self.badge_label)
        badge_row.addWidget(self.confirm_button)
        badge_row.addStretch(1)
        layout.addLayout(badge_row)
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
        self.minimum_note.setText(
            QCoreApplication.translate(
                "Stock",
                "The minimum stock of the item types is a placeholder until you confirm it "
                "or set a minimum.",
            )
        )
        self.badge_label.setText(
            QCoreApplication.translate("Stock", "Placeholder - to be confirmed")
        )
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

    def _compute_badge(self) -> bool:
        """Whether the badge of P12 is due (never without a configuration service)."""
        config = self.context.services.config
        if config is None:
            return False
        try:
            return bool(config.needs_badge(PLACEHOLDER_MINIMUM))
        except ServiceError:
            return False

    def refresh(self) -> None:
        service = self.context.services.stock
        previous = self.selected_type()
        types = [] if service is None else service.list_types(include_inactive=True)
        self.model.set_rows(types)
        if previous is not None:
            self._select_type(previous.id)
        self._badge_due = self._compute_badge()
        self.badge_label.setVisible(self._badge_due)
        self.confirm_button.setVisible(self._badge_due)
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
        enable(self.confirm_action, self._badge_due)

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

    def confirm_placeholder(self) -> None:
        config = self.context.services.config
        if config is not None and self._badge_due:
            apply_change(
                self.context, self, error_label, lambda: config.confirm(PLACEHOLDER_MINIMUM)
            )


# --------------------------------------------------------------------------- registry factories


def settings_section_title() -> str:
    return QCoreApplication.translate("Stock", "Stock item types")


def create_settings_section(context: AppContext) -> QWidget:
    return StockTypesSection(context)
