# SPDX-License-Identifier: GPL-3.0-or-later
"""The stock panel: summary, lots and movements of the selected lot (PLAN.md T11.10, D38).

One panel serves the "Stock (lots)" tab of the Infrastructure page (every category) and the
antidotes page (two categories). It reads and writes ONLY through ``context.services.stock``;
the dialogs of ``ui/stock/dialogs.py`` are opened non-modally (``open()`` and delete on close) so
tests can drive them, and every confirmation goes through ``context.prompts``. Every edit action is
made with ``make_edit_action``, so read-only mode disables it, and every write goes through
``apply_change``, so a refusal of the service is shown as translated text and changes nothing.

The panel shows the item types that have lots (or a minimum) on the as-of date, so a database
without stock shows empty tables. A type filter (:meth:`StockPanel.set_type_filter`) limits the
summary and the lots to one item type; :meth:`StockPanel.set_no_match` shows the empty state used
when the page filter names something that is not an item type.
"""

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cbrn_dashboard.domain.stock import LotRow, LotStatus, StockCategory, TypeSummary
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.stock import LotView, MovementView, StockTypeView
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_change,
    apply_tab_order,
    current_language,
    follow_language,
    guarded,
    make_edit_action,
    make_table_view,
)
from cbrn_dashboard.ui.stock.dialogs import LotDialog, MovementDialog
from cbrn_dashboard.ui.stock.labels import error_label, fill_placeholders
from cbrn_dashboard.ui.stock.models import (
    LotsModel,
    LotTableRow,
    MovementsModel,
    SummaryModel,
)

__all__ = ["StockPanel"]


def _open(dialog: QDialog) -> None:
    """Show ``dialog`` without blocking; it deletes itself when closed."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


def _shows_in_summary(summary: TypeSummary) -> bool:
    """A type is summarised when it has stock, lots in use or a minimum on the as-of date."""
    return summary.in_use or summary.on_hand > 0 or summary.minimum is not None


class StockPanel(QWidget):
    """Stock by item type and lot for the as-of date, and the movements of the selected lot."""

    def __init__(
        self,
        context: AppContext,
        categories: frozenset[StockCategory] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("stock_panel")
        self.context = context
        self._categories = categories
        self._type_filter: str | None = None
        self._no_match = False
        self._types: dict[str, StockTypeView] = {}
        self.summary_model = SummaryModel(self)
        self.lots_model = LotsModel(self)
        self.movements_model = MovementsModel(self)

        self.summary_caption = QLabel(self)
        self.summary_view = make_table_view(self.summary_model, self)
        self.summary_view.setObjectName("stock_summary_view")
        self.summary_caption.setBuddy(self.summary_view)
        self.show_empty_check = QCheckBox(self)
        self.show_empty_check.setObjectName("show_empty_check")
        self.empty_label = QLabel(self)
        self.empty_label.setObjectName("stock_empty_label")
        self.empty_label.setWordWrap(True)
        self.empty_label.setVisible(False)
        self.lots_view = make_table_view(self.lots_model, self)
        self.lots_view.setObjectName("stock_lots_view")
        self.count_label = QLabel(self)
        self.movements_caption = QLabel(self)
        self.movements_view = make_table_view(self.movements_model, self)
        self.movements_view.setObjectName("stock_movements_view")
        self.movements_caption.setBuddy(self.movements_view)

        def action(text_fn: Callable[[], str], slot: Callable[[], None]) -> EditAction:
            return make_edit_action(context, self, text_fn, slot)

        self.add_lot_action = action(
            lambda: QCoreApplication.translate("Stock", "Add lot"), self.add_lot
        )
        self.edit_lot_action = action(
            lambda: QCoreApplication.translate("Stock", "Edit lot"), self.edit_lot
        )
        self.delete_lot_action = action(
            lambda: QCoreApplication.translate("Stock", "Delete lot"), self.delete_lot
        )
        self.record_action = action(
            lambda: QCoreApplication.translate("Stock", "Record movement"), self.record_movement
        )
        self.edit_movement_action = action(
            lambda: QCoreApplication.translate("Stock", "Edit movement"), self.edit_movement
        )
        self.delete_movement_action = action(
            lambda: QCoreApplication.translate("Stock", "Delete movement"), self.delete_movement
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_lot_action,
            self.edit_lot_action,
            self.delete_lot_action,
            self.record_action,
            self.edit_movement_action,
            self.delete_movement_action,
        )

        options = QHBoxLayout()
        options.addWidget(self.show_empty_check)
        options.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_caption)
        layout.addWidget(self.summary_view, 1)
        layout.addLayout(options)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.lots_view, 3)
        layout.addWidget(self.count_label)
        layout.addLayout(
            action_row(
                (
                    self.add_lot_action,
                    self.edit_lot_action,
                    self.delete_lot_action,
                    self.record_action,
                ),
                self,
            )
        )
        layout.addWidget(self.movements_caption)
        layout.addWidget(self.movements_view, 2)
        layout.addLayout(action_row((self.edit_movement_action, self.delete_movement_action), self))
        apply_tab_order(self)

        self.show_empty_check.toggled.connect(self.refresh)
        selection = self.lots_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._lot_selected)
        selection = self.movements_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        context.data_changed.connect(self.refresh)
        context.as_of_changed.connect(self._as_of_changed)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        """Re-apply every text of the panel in the current language."""
        self.summary_caption.setText(
            QCoreApplication.translate("Stock", "Stock by item type at the as-of date")
        )
        self.show_empty_check.setText(QCoreApplication.translate("Stock", "Show empty lots"))
        self.empty_label.setText(
            QCoreApplication.translate(
                "Stock", "The selected type is not a stock item type, so it has no lots."
            )
        )
        self.lots_view.setAccessibleName(QCoreApplication.translate("Stock", "Lots"))
        self.movements_caption.setText(
            QCoreApplication.translate("Stock", "Movements of the selected lot")
        )
        for action in self._actions:
            action.retranslate()
        self._update_count()
        lang = current_language(self.context)
        self.summary_model.set_language(lang)
        self.lots_model.set_language(lang)
        self.movements_model.set_language(lang)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def _update_count(self) -> None:
        self.count_label.setText(
            QCoreApplication.translate("Stock", "%n lot(s) shown", None, self.lots_model.rowCount())
        )

    # ----- the filter

    @property
    def type_filter(self) -> str | None:
        """The code of the item type the panel is limited to (``None``: every type)."""
        return self._type_filter

    @property
    def no_match(self) -> bool:
        """Whether the panel shows its empty state (the page filter is not an item type)."""
        return self._no_match

    def set_type_filter(self, code: str | None) -> None:
        """Limit the summary and the lots to the item type ``code`` (``None``: every type)."""
        if code == self._type_filter and not self._no_match:
            return
        self._type_filter = code
        self._no_match = False
        self.refresh()

    def set_no_match(self) -> None:
        """Show the empty state: no summary rows, no lots, and no edit while it lasts."""
        if self._no_match:
            return
        self._no_match = True
        self.refresh()

    # ----- data

    def selected_lot(self) -> LotRow | None:
        row = self.lots_model.selected_row(self.lots_view)
        return row.row if isinstance(row, LotTableRow) else None

    def selected_movement(self) -> MovementView | None:
        row = self.movements_model.selected_row(self.movements_view)
        return row if isinstance(row, MovementView) else None

    def refresh(self) -> None:
        """Read the stock as of the as-of date (and the movements of the selected lot) again."""
        service = self.context.services.stock
        previous = self.selected_lot()
        types: dict[str, StockTypeView] = {}
        rows: list[LotRow] = []
        summaries: list[TypeSummary] = []
        if service is not None and not self._no_match:
            wanted = self._type_filter
            try:
                as_of = self.context.as_of
                types = {item.code: item for item in service.list_types(include_inactive=True)}
                rows = [
                    row
                    for row in service.lot_rows(as_of, self._categories)
                    if wanted is None or row.type_code == wanted
                ]
                summaries = [
                    summary
                    for summary in service.type_summaries(as_of, self._categories)
                    if (wanted is None or summary.type_code == wanted)
                    and _shows_in_summary(summary)
                ]
            except ServiceError:
                types, rows, summaries = {}, [], []
        shown = (
            rows
            if self.show_empty_check.isChecked()
            else [row for row in rows if row.status is not LotStatus.EMPTY]
        )
        self._types = types
        self.empty_label.setVisible(self._no_match)
        self.summary_model.set_summaries(summaries, rows, types)
        self.lots_model.set_lots(shown, types)
        if previous is not None:
            self._select_lot(previous.lot_id)
        self._update_count()
        self._refresh_movements()

    def _refresh_movements(self) -> None:
        service = self.context.services.stock
        lot = self.selected_lot()
        previous = self.selected_movement()
        movements: list[MovementView] = []
        if service is not None and lot is not None:
            try:
                movements = service.movements(lot.lot_id)
            except ServiceError:
                movements = []
        self.movements_model.set_movements(movements)
        if previous is not None:
            self._select_movement(previous.id)
        self._update_actions()

    def _dialog_saved(self) -> None:
        # Connected as a bound method, never as a lambda holding the dialog: a closure over a
        # dialog that deletes itself on close crashed Qt (access violation) when it was closed.
        dialog = self.sender()
        if isinstance(dialog, LotDialog):
            self._select_lot(dialog.saved_lot_id)
        elif isinstance(dialog, MovementDialog):
            self._select_movement(dialog.saved_movement_id)

    def _select_lot(self, lot_id: int | None) -> None:
        if lot_id is None:
            return
        for index, row in enumerate(self.lots_model.rows()):
            if row.row.lot_id == lot_id:
                self.lots_view.selectRow(index)
                return

    def _select_movement(self, movement_id: int | None) -> None:
        if movement_id is None:
            return
        for index, row in enumerate(self.movements_model.rows()):
            if row.id == movement_id:
                self.movements_view.selectRow(index)
                return

    def _lot_selected(self, *_args: object) -> None:
        self._refresh_movements()

    def _as_of_changed(self, *_args: object) -> None:
        self.refresh()

    def _update_actions(self, *_args: object) -> None:
        usable = self.context.services.stock is not None and not self._no_match
        lot = self.selected_lot() is not None
        movement = self.selected_movement() is not None
        enable = self.context.set_edit_enabled
        enable(self.add_lot_action, usable)
        enable(self.edit_lot_action, usable and lot)
        enable(self.delete_lot_action, usable and lot)
        enable(self.record_action, usable and lot)
        enable(self.edit_movement_action, usable and lot and movement)
        enable(self.delete_movement_action, usable and lot and movement)

    # ----- lots

    def _lot_view(self, lot_id: int) -> LotView | None:
        """The stored lot (a refusal such as "no longer exists" is shown and gives ``None``)."""
        service = self.context.services.stock
        if service is None:
            return None
        return guarded(self.context, self, error_label, lambda: service.get_lot(lot_id))

    def add_lot(self) -> None:
        code = None if self._no_match else self._type_filter
        dialog = LotDialog(self.context, self, None, self._categories, code)
        dialog.accepted.connect(self._dialog_saved)
        _open(dialog)

    def edit_lot(self) -> None:
        selected = self.selected_lot()
        if selected is None:
            return
        lot = self._lot_view(selected.lot_id)
        if lot is not None:
            dialog = LotDialog(self.context, self, lot, self._categories)
            dialog.accepted.connect(self._dialog_saved)
            _open(dialog)

    def delete_lot(self) -> None:
        selected = self.selected_lot()
        service = self.context.services.stock
        if selected is None or service is None:
            return
        lot_id = selected.lot_id
        title = QCoreApplication.translate("Stock", "Delete lot")
        question = fill_placeholders(
            QCoreApplication.translate(
                "Stock",
                "Delete lot %1 together with all its movements? "
                "A lot that existed is closed with a disposal or a loss instead.",
            ),
            selected.lot_code,
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(self.context, self, error_label, lambda: service.delete_lot(lot_id))

    # ----- movements

    def record_movement(self) -> None:
        selected = self.selected_lot()
        if selected is None:
            return
        lot = self._lot_view(selected.lot_id)
        if lot is not None:
            dialog = MovementDialog(self.context, self, lot)
            dialog.accepted.connect(self._dialog_saved)
            _open(dialog)

    def edit_movement(self) -> None:
        selected = self.selected_lot()
        movement = self.selected_movement()
        if selected is None or movement is None:
            return
        lot = self._lot_view(selected.lot_id)
        if lot is not None:
            dialog = MovementDialog(self.context, self, lot, movement)
            dialog.accepted.connect(self._dialog_saved)
            _open(dialog)

    def delete_movement(self) -> None:
        selected = self.selected_lot()
        movement = self.selected_movement()
        service = self.context.services.stock
        if selected is None or movement is None or service is None:
            return
        movement_id = movement.id
        title = QCoreApplication.translate("Stock", "Delete movement")
        question = fill_placeholders(
            QCoreApplication.translate("Stock", "Delete the selected movement of lot %1?"),
            selected.lot_code,
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context, self, error_label, lambda: service.delete_movement(movement_id)
            )
