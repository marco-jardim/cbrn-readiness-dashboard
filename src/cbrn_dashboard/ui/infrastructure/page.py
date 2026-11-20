# SPDX-License-Identifier: GPL-3.0-or-later
"""The Infrastructure page and its asset-type editor (PLAN.md T3.4, A05, A06, D23, D26).

The page lists the assets by type and tag as of ``context.as_of`` (status, last maintenance, next
due date and the overdue / due soon / schedule unknown flags, all as TEXT), the availability per
type and the history of the selected asset. It reads and writes ONLY through
``context.services.infrastructure``; dialogs are opened non-modally with ``open()`` so tests can
drive them. The settings section edits the asset types and the A05 switch (through the
configuration service when the context has one). The module-level factories are what the
registries of the shell call.

The page has two tabs under one "Type" filter (PLAN.md T11.10): the units (assets, availability and
history) and the stock (``StockPanel``, lots and movements). The filter lists "All types", the asset
types, a separator and the stock types (data ``stock:<code>``). Choosing an asset type shows the
units tab, filters the assets and gives the stock panel its empty state; choosing a stock type shows
the stock tab, filters the lots and leaves the asset list empty; "All types" filters nothing and
keeps the tab. Switching tabs by hand never changes the filter.
"""

from datetime import date
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.domain.infrastructure import AssetStatus, MaintenanceKind
from cbrn_dashboard.domain.stock import CATEGORY_ORDER
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.infrastructure import (
    AssetTypeView,
    MaintenanceView,
    StatusEventView,
)
from cbrn_dashboard.services.stock import StockTypeView
from cbrn_dashboard.ui.infrastructure.dialogs import (
    AssetDialog,
    MaintenanceDialog,
    StatusDialog,
    TypeDialog,
)
from cbrn_dashboard.ui.infrastructure.labels import error_label, type_display
from cbrn_dashboard.ui.infrastructure.models import (
    AssetsModel,
    AssetTableRow,
    AvailabilityModel,
    AvailabilityRow,
    HistoryModel,
    HistoryRow,
    TypesModel,
)
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import format_date
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_change,
    apply_tab_order,
    current_language,
    follow_language,
    make_edit_action,
    make_table_view,
    mark_data,
)
from cbrn_dashboard.ui.stock.labels import stock_type_display
from cbrn_dashboard.ui.stock.panel import StockPanel

__all__ = [
    "InfrastructurePage",
    "InfrastructureSettingsSection",
    "create_page",
    "create_settings_section",
    "demo_asset_dialog",
    "demo_maintenance_dialog",
    "demo_status_dialog",
    "demo_type_dialog",
    "page_title",
    "settings_section_title",
]

#: The configuration field of the A05 switch.
DEGRADED_FIELD = "degraded_counts_as_available"

#: The data of a stock type in the type filter is this prefix and the code of the type. An asset
#: type code never has a colon (list codes allow letters, digits, dot, hyphen and underscore).
STOCK_FILTER_PREFIX = "stock:"

#: The positions of the two tabs.
UNITS_TAB = 0
STOCK_TAB = 1


def _open(dialog: QDialog) -> None:
    """Show ``dialog`` window-modally without blocking; it deletes itself when closed."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


def _config_service(context: AppContext) -> Any:
    """The configuration service of the context, or ``None`` while there is none."""
    return getattr(context.services, "config", None)


# --------------------------------------------------------------------------- the page


class InfrastructurePage(QWidget):
    """Assets by type for the as-of date, the availability per type and the asset history."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("infrastructure_page")
        self.context = context
        self._types: dict[str, AssetTypeView] = {}
        self._stock_types: dict[str, StockTypeView] = {}
        self.assets_model = AssetsModel(self)
        self.availability_model = AvailabilityModel(self)
        self.history_model = HistoryModel(self)
        self.type_caption = QLabel(self)
        self.type_combo = QComboBox(self)
        mark_data(self.type_combo)
        self.type_caption.setBuddy(self.type_combo)
        self.type_combo.addItem("", None)
        self.assets_view = make_table_view(self.assets_model, self)
        self.assets_view.setObjectName("assets_view")
        self.count_label = QLabel(self)
        self.availability_caption = QLabel(self)
        self.availability_note = QLabel(self)
        self.availability_view = make_table_view(self.availability_model, self)
        self.availability_view.setObjectName("availability_view")
        self.availability_caption.setBuddy(self.availability_view)
        self.history_caption = QLabel(self)
        self.history_view = make_table_view(self.history_model, self)
        self.history_view.setObjectName("history_view")
        self.history_caption.setBuddy(self.history_view)

        def action(text_fn: Any, slot: Any) -> EditAction:
            return make_edit_action(context, self, text_fn, slot)

        self.add_action = action(
            lambda: QCoreApplication.translate("Infrastructure", "Add asset"), self.add_asset
        )
        self.edit_action = action(
            lambda: QCoreApplication.translate("Infrastructure", "Edit asset"), self.edit_asset
        )
        self.retire_action = action(
            lambda: QCoreApplication.translate("Infrastructure", "Retire asset"),
            self.retire_asset,
        )
        self.delete_action = action(
            lambda: QCoreApplication.translate("Infrastructure", "Delete asset"),
            self.delete_asset,
        )
        self.status_action = action(
            lambda: QCoreApplication.translate("Infrastructure", "Change status"),
            self.change_status,
        )
        self.maintenance_action = action(
            lambda: QCoreApplication.translate("Infrastructure", "Record maintenance"),
            self.record_maintenance,
        )
        self.edit_entry_action = action(
            lambda: QCoreApplication.translate("Infrastructure", "Edit history entry"),
            self.edit_entry,
        )
        self.delete_entry_action = action(
            lambda: QCoreApplication.translate("Infrastructure", "Delete history entry"),
            self.delete_entry,
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_action,
            self.edit_action,
            self.retire_action,
            self.delete_action,
            self.status_action,
            self.maintenance_action,
            self.edit_entry_action,
            self.delete_entry_action,
        )

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("infrastructure_tabs")
        self.units_tab = QWidget(self.tabs)
        self.units_tab.setObjectName("units_tab")
        units = QVBoxLayout(self.units_tab)
        units.addWidget(self.assets_view, 3)
        units.addWidget(self.count_label)
        units.addLayout(
            action_row(
                (
                    self.add_action,
                    self.edit_action,
                    self.retire_action,
                    self.delete_action,
                    self.status_action,
                    self.maintenance_action,
                ),
                self.units_tab,
            )
        )
        units.addWidget(self.availability_caption)
        units.addWidget(self.availability_view, 1)
        units.addWidget(self.availability_note)
        units.addWidget(self.history_caption)
        units.addWidget(self.history_view, 2)
        units.addLayout(
            action_row((self.edit_entry_action, self.delete_entry_action), self.units_tab)
        )
        self.stock_panel = StockPanel(context, None, self.tabs)
        self.tabs.addTab(self.units_tab, "")
        self.tabs.addTab(self.stock_panel, "")

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.type_caption)
        filter_row.addWidget(self.type_combo)
        filter_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(filter_row)
        layout.addWidget(self.tabs, 1)
        apply_tab_order(self)

        self.type_combo.currentIndexChanged.connect(self._filter_changed)
        selection = self.assets_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._asset_selected)
        selection = self.history_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        context.data_changed.connect(self.refresh)
        context.as_of_changed.connect(self._as_of_changed)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        """Re-apply every text of the page in the current language."""
        self.type_caption.setText(QCoreApplication.translate("Infrastructure", "Type"))
        self.assets_view.setAccessibleName(QCoreApplication.translate("Infrastructure", "Assets"))
        self.availability_caption.setText(
            QCoreApplication.translate("Infrastructure", "Availability by type at the as-of date")
        )
        self.availability_note.setText(
            QCoreApplication.translate(
                "Infrastructure", "Available means operational; occupancy is not tracked."
            )
        )
        self.history_caption.setText(
            QCoreApplication.translate("Infrastructure", "History of the selected asset")
        )
        self.tabs.setTabText(
            UNITS_TAB,
            QCoreApplication.translate("Infrastructure", "Equipment and facilities (units)"),
        )
        self.tabs.setTabText(
            STOCK_TAB, QCoreApplication.translate("Infrastructure", "Stock (lots)")
        )
        for action in self._actions:
            action.retranslate()
        self._type_texts()
        self._update_count()
        lang = current_language(self.context)
        self.assets_model.set_language(lang)
        self.availability_model.set_language(lang)
        self.history_model.set_language(lang)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def _type_texts(self) -> None:
        """Rebuild the type filter when its entries changed, then name every entry."""
        self._sync_type_filter()
        self.type_combo.setItemText(0, QCoreApplication.translate("Infrastructure", "All types"))
        lang = current_language(self.context)
        for index in range(1, self.type_combo.count()):
            data = self.type_combo.itemData(index)
            if not isinstance(data, str):
                continue  # the separator
            if data.startswith(STOCK_FILTER_PREFIX):
                stock_type = self._stock_types.get(data[len(STOCK_FILTER_PREFIX) :])
                if stock_type is not None:
                    self.type_combo.setItemText(index, stock_type_display(stock_type, lang))
                continue
            asset_type = self._types.get(data)
            if asset_type is not None:
                self.type_combo.setItemText(index, type_display(asset_type, lang))

    def _update_count(self) -> None:
        self.count_label.setText(
            QCoreApplication.translate(
                "Infrastructure", "%n asset(s) shown", None, self.assets_model.rowCount()
            )
        )

    # ----- data

    def selected_asset(self) -> AssetTableRow | None:
        row = self.assets_model.selected_row(self.assets_view)
        return row if isinstance(row, AssetTableRow) else None

    def selected_entry(self) -> HistoryRow | None:
        row = self.history_model.selected_row(self.history_view)
        return row if isinstance(row, HistoryRow) else None

    def _filter_data(self) -> list[str | None]:
        """The data of the entries after "All types": asset types, a separator, stock types.

        The separator is ``None`` and only there when both groups exist. Stock types are ordered by
        category and then by the name in the current language, so a language switch can reorder
        them.
        """
        lang = current_language(self.context)
        stock_types = sorted(
            self._stock_types.values(),
            key=lambda item: (
                CATEGORY_ORDER.index(item.category),
                stock_type_display(item, lang).casefold(),
                item.code,
            ),
        )
        data: list[str | None] = list(self._types)
        if data and stock_types:
            data.append(None)
        data.extend(STOCK_FILTER_PREFIX + item.code for item in stock_types)
        return data

    def _sync_type_filter(self) -> None:
        """Rebuild the type filter when its entries changed (no refresh while doing so).

        The whole list of entries is compared, so a new stock type, a renamed order or a type that
        moved between groups all rebuild it; the choice is kept when it still exists.
        """
        wanted = self._filter_data()
        current = [self.type_combo.itemData(i) for i in range(1, self.type_combo.count())]
        if wanted == current:
            return
        previous = self.type_combo.currentData()
        self.type_combo.blockSignals(True)
        while self.type_combo.count() > 1:
            self.type_combo.removeItem(1)
        for entry in wanted:
            if entry is None:
                self.type_combo.insertSeparator(self.type_combo.count())
            else:
                self.type_combo.addItem("", entry)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(previous)))
        self.type_combo.blockSignals(False)

    def _filter_changed(self, *_args: object) -> None:
        """The user chose an entry: an asset type shows the units tab, a stock type the lots tab.

        "All types" keeps the current tab. Switching tabs by hand never comes back here.
        """
        data = self.type_combo.currentData()
        if isinstance(data, str):
            stock = data.startswith(STOCK_FILTER_PREFIX)
            self.tabs.setCurrentIndex(STOCK_TAB if stock else UNITS_TAB)
        self.refresh()

    def show_stock_item(self, code: str) -> bool:
        """Show the "Stock (lots)" tab with the "Type" filter on the stock type ``code``.

        The hook of "Open record" for a stock alert. ``False`` (nothing changes) when no stock type
        with that code is in the filter.
        """
        index = self.type_combo.findData(STOCK_FILTER_PREFIX + code)
        if index < 0:
            return False
        self.type_combo.setCurrentIndex(index)  # _filter_changed shows the tab and refreshes
        self.tabs.setCurrentIndex(STOCK_TAB)
        return True

    def _apply_stock_filter(self, wanted: object) -> None:
        """Give the stock panel the chosen filter: all, one stock type, or the empty state."""
        if wanted is None:
            self.stock_panel.set_type_filter(None)
        elif isinstance(wanted, str) and wanted.startswith(STOCK_FILTER_PREFIX):
            self.stock_panel.set_type_filter(wanted[len(STOCK_FILTER_PREFIX) :])
        else:
            self.stock_panel.set_no_match()

    def refresh(self) -> None:
        """Read the assets as of the as-of date (and the history of the selected one) again."""
        service = self.context.services.infrastructure
        stock_service = self.context.services.stock
        previous = self.selected_asset()
        self._types = (
            {}
            if service is None
            else {t.code: t for t in service.list_types(include_inactive=True)}
        )
        self._stock_types = (
            {}
            if stock_service is None
            else {t.code: t for t in stock_service.list_types(include_inactive=True)}
        )
        self._type_texts()
        wanted = self.type_combo.currentData()
        self._apply_stock_filter(wanted)
        if service is None:
            self.assets_model.set_rows([])
            self.availability_model.set_rows([])
        else:
            as_of = self.context.as_of
            stock_chosen = isinstance(wanted, str) and wanted.startswith(STOCK_FILTER_PREFIX)
            stored = {asset.id: asset for asset in service.list_assets()}
            rows = [
                AssetTableRow(row, stored.get(row.asset_id), self._types.get(row.type_code))
                for row in service.asset_rows(as_of)
                if not stock_chosen and (wanted is None or row.type_code == wanted)
            ]
            self.assets_model.set_rows(rows)
            self.availability_model.set_rows(
                [
                    AvailabilityRow(
                        item.type_code,
                        self._types.get(item.type_code),
                        item.available,
                        item.in_service,
                    )
                    for item in service.availability(as_of)
                ]
            )
            if previous is not None:
                for index, row in enumerate(rows):
                    if row.row.asset_id == previous.row.asset_id:
                        self.assets_view.selectRow(index)
        self._update_count()
        self._refresh_history()

    def _refresh_history(self) -> None:
        service = self.context.services.infrastructure
        selected = self.selected_asset()
        if service is None or selected is None:
            self.history_model.set_rows([])
        else:
            history = service.asset_history(selected.row.asset_id)
            entries = [HistoryRow(on=e.effective_on, status=e) for e in history.status_events]
            entries += [
                HistoryRow(on=m.performed_on, maintenance=m) for m in history.maintenance_events
            ]
            entries.sort(key=lambda entry: (entry.on, entry.maintenance is not None))
            self.history_model.set_rows(entries)
        self._update_actions()

    def _asset_selected(self, *_args: object) -> None:
        self._refresh_history()

    def _as_of_changed(self, *_args: object) -> None:
        self.refresh()

    def _update_actions(self, *_args: object) -> None:
        has_service = self.context.services.infrastructure is not None
        selected = self.selected_asset()
        asset = None if selected is None else selected.asset
        entry = self.selected_entry() is not None
        enable = self.context.set_edit_enabled
        enable(self.add_action, has_service)
        enable(self.edit_action, has_service and asset is not None)
        active = asset is not None and asset.in_service_until is None
        enable(self.retire_action, has_service and active)
        enable(self.delete_action, has_service and asset is not None)
        enable(self.status_action, has_service and asset is not None)
        enable(self.maintenance_action, has_service and asset is not None)
        enable(self.edit_entry_action, has_service and entry)
        enable(self.delete_entry_action, has_service and entry)

    # ----- assets

    def add_asset(self) -> None:
        _open(AssetDialog(self.context, self))

    def edit_asset(self) -> None:
        selected = self.selected_asset()
        if selected is not None and selected.asset is not None:
            _open(AssetDialog(self.context, self, selected.asset))

    def retire_asset(self) -> None:
        selected = self.selected_asset()
        service = self.context.services.infrastructure
        if selected is None or selected.asset is None or service is None:
            return
        asset_id = selected.asset.id
        title = QCoreApplication.translate("Infrastructure", "Retire asset")
        question = (
            QCoreApplication.translate(
                "Infrastructure",
                "Retire asset %1 as of %2? It stays in the database with its history.",
            )
            .replace("%1", selected.asset.tag)
            .replace("%2", format_date(self.context.as_of, current_language(self.context)))
        )
        if self.context.prompts.confirm(self, title, question):
            until = self.context.as_of
            apply_change(
                self.context, self, error_label, lambda: service.retire_asset(asset_id, until)
            )

    def delete_asset(self) -> None:
        selected = self.selected_asset()
        service = self.context.services.infrastructure
        if selected is None or selected.asset is None or service is None:
            return
        asset_id = selected.asset.id
        title = QCoreApplication.translate("Infrastructure", "Delete asset")
        question = QCoreApplication.translate(
            "Infrastructure",
            "Delete asset %1 together with its history? Use Retire for an asset that existed.",
        ).replace("%1", selected.asset.tag)
        if self.context.prompts.confirm(self, title, question):
            apply_change(self.context, self, error_label, lambda: service.delete_asset(asset_id))

    def change_status(self) -> None:
        selected = self.selected_asset()
        if selected is not None:
            _open(StatusDialog(self.context, self, selected.row.asset_id, selected.row.tag))

    def record_maintenance(self) -> None:
        selected = self.selected_asset()
        if selected is not None:
            _open(MaintenanceDialog(self.context, self, selected.row.asset_id, selected.row.tag))

    # ----- history entries

    def edit_entry(self) -> None:
        selected = self.selected_asset()
        entry = self.selected_entry()
        if selected is None or entry is None:
            return
        asset_id, tag = selected.row.asset_id, selected.row.tag
        if entry.status is not None:
            _open(StatusDialog(self.context, self, asset_id, tag, entry.status))
        elif entry.maintenance is not None:
            _open(MaintenanceDialog(self.context, self, asset_id, tag, entry.maintenance))

    def delete_entry(self) -> None:
        selected = self.selected_asset()
        entry = self.selected_entry()
        service = self.context.services.infrastructure
        if selected is None or entry is None or service is None:
            return
        title = QCoreApplication.translate("Infrastructure", "Delete history entry")
        question = QCoreApplication.translate(
            "Infrastructure", "Delete the selected history entry of asset %1?"
        ).replace("%1", selected.row.tag)
        if not self.context.prompts.confirm(self, title, question):
            return
        if entry.status is not None:
            event_id = entry.status.id
            apply_change(
                self.context, self, error_label, lambda: service.delete_status_event(event_id)
            )
        elif entry.maintenance is not None:
            record_id = entry.maintenance.id
            apply_change(
                self.context, self, error_label, lambda: service.delete_maintenance(record_id)
            )


# --------------------------------------------------------------------------- the type editor


class InfrastructureSettingsSection(QWidget):
    """Settings -> Infrastructure: the asset types (A06) and the A05 availability switch."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("infrastructure_section")
        self.context = context
        self.model = TypesModel(self)
        self.types_caption = QLabel(self)
        self.view = make_table_view(self.model, self)
        self.view.setObjectName("types_view")
        self.types_caption.setBuddy(self.view)
        self.add_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Infrastructure", "Add asset type"),
            self.add_type,
        )
        self.edit_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Infrastructure", "Edit asset type"),
            self.edit_type,
        )
        self.deactivate_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Infrastructure", "Deactivate asset type"),
            self.deactivate_type,
        )
        self.delete_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Infrastructure", "Delete asset type"),
            self.delete_type,
        )
        self.confirm_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Infrastructure", "Confirm"),
            self.confirm_placeholder,
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_action,
            self.edit_action,
            self.deactivate_action,
            self.delete_action,
            self.confirm_action,
        )
        #: The placeholder whose badge is due, and the error code of a configuration that
        #: cannot be read (both ``None`` while there is nothing to show).
        self._badge_id: str | None = None
        self._config_error: str | None = None
        self.config_error_label = QLabel(self)
        self.config_error_label.setObjectName("config_error_label")
        self.config_error_label.setWordWrap(True)
        self.config_error_label.setVisible(False)
        self.rule_caption = QLabel(self)
        self.degraded_check = QCheckBox(self)
        self.degraded_check.setObjectName("degraded_check")
        context.register_edit_action(self.degraded_check)
        self.badge_label = QLabel(self)
        self.badge_label.setObjectName("degraded_badge")
        self.confirm_button = QToolButton(self)
        self.confirm_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.confirm_button.setDefaultAction(self.confirm_action)

        layout = QVBoxLayout(self)
        layout.addWidget(self.types_caption)
        layout.addWidget(self.view, 1)
        layout.addLayout(action_row(self._actions[:4], self))
        layout.addWidget(self.rule_caption)
        layout.addWidget(self.config_error_label)
        rule_row = QHBoxLayout()
        rule_row.addWidget(self.degraded_check)
        rule_row.addWidget(self.badge_label)
        rule_row.addWidget(self.confirm_button)
        rule_row.addStretch(1)
        layout.addLayout(rule_row)

        selection = self.view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        self.degraded_check.toggled.connect(self._degraded_toggled)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        self.types_caption.setText(QCoreApplication.translate("Infrastructure", "Asset types"))
        self.rule_caption.setText(QCoreApplication.translate("Infrastructure", "Availability rule"))
        self.degraded_check.setText(
            QCoreApplication.translate("Infrastructure", "Count degraded units as available")
        )
        self.badge_label.setText(
            QCoreApplication.translate("Infrastructure", "Placeholder - to be confirmed")
        )
        for action in self._actions:
            action.retranslate()
        self._show_config_error()
        self.model.set_language(current_language(self.context))

    def _show_config_error(self) -> None:
        """Show why the A05 switch is off (a configuration that cannot be read)."""
        code = self._config_error
        self.config_error_label.setVisible(code is not None)
        self.config_error_label.setText("" if code is None else error_label(code))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def selected_type(self) -> AssetTypeView | None:
        row = self.model.selected_row(self.view)
        return row if isinstance(row, AssetTypeView) else None

    def _badge(self) -> str | None:
        config = _config_service(self.context)
        if config is None:
            return None
        badge = config.badge_for_field(DEGRADED_FIELD)
        return None if badge is None else str(badge)

    def refresh(self) -> None:
        service = self.context.services.infrastructure
        previous = self.selected_type()
        types = [] if service is None else service.list_types(include_inactive=True)
        self.model.set_rows(types)
        if previous is not None:
            for row, asset_type in enumerate(types):
                if asset_type.id == previous.id:
                    self.view.selectRow(row)
        config = _config_service(self.context)
        checked: bool | None = None
        self._badge_id = None
        self._config_error = None
        if config is not None:
            try:
                checked = bool(config.load().degraded_counts_as_available)
                self._badge_id = self._badge()
            except ServiceError as error:
                checked = None
                self._badge_id = None
                self._config_error = error.code
        self._show_config_error()
        self.degraded_check.blockSignals(True)
        if checked is not None:
            self.degraded_check.setChecked(checked)
        self.degraded_check.blockSignals(False)
        self.badge_label.setVisible(self._badge_id is not None)
        self.confirm_button.setVisible(self._badge_id is not None)
        self._update_actions()

    def _update_actions(self, *_args: object) -> None:
        has_service = self.context.services.infrastructure is not None
        asset_type = self.selected_type()
        enable = self.context.set_edit_enabled
        enable(self.add_action, has_service)
        enable(self.edit_action, has_service and asset_type is not None)
        enable(self.deactivate_action, has_service and asset_type is not None and asset_type.active)
        enable(self.delete_action, has_service and asset_type is not None)
        config = _config_service(self.context) is not None and self._config_error is None
        enable(self.degraded_check, config)
        enable(self.confirm_action, config and self._badge_id is not None)

    # ----- the A05 switch

    def _degraded_toggled(self, checked: bool) -> None:
        config = _config_service(self.context)
        if config is None:
            return

        def save() -> None:
            config.save(config.load().with_changes(degraded_counts_as_available=checked))

        if not apply_change(self.context, self, error_label, save):
            self.refresh()

    def confirm_placeholder(self) -> None:
        config = _config_service(self.context)
        badge = self._badge_id
        if config is not None and badge is not None and self._config_error is None:
            apply_change(self.context, self, error_label, lambda: config.confirm(badge))

    # ----- the types

    def add_type(self) -> None:
        _open(TypeDialog(self.context, self))

    def edit_type(self) -> None:
        asset_type = self.selected_type()
        if asset_type is not None:
            _open(TypeDialog(self.context, self, asset_type))

    def deactivate_type(self) -> None:
        asset_type = self.selected_type()
        service = self.context.services.infrastructure
        if asset_type is not None and service is not None:
            apply_change(
                self.context, self, error_label, lambda: service.deactivate_type(asset_type.id)
            )

    def delete_type(self) -> None:
        asset_type = self.selected_type()
        service = self.context.services.infrastructure
        if asset_type is None or service is None:
            return
        title = QCoreApplication.translate("Infrastructure", "Delete asset type")
        question = QCoreApplication.translate("Infrastructure", "Delete asset type %1?").replace(
            "%1", asset_type.code
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context, self, error_label, lambda: service.delete_type(asset_type.id)
            )


# --------------------------------------------------------------------------- registry factories


def page_title() -> str:
    return QCoreApplication.translate("Infrastructure", "Infrastructure")


def create_page(context: AppContext) -> QWidget:
    return InfrastructurePage(context)


def settings_section_title() -> str:
    return QCoreApplication.translate("Infrastructure", "Asset types and availability")


def create_settings_section(context: AppContext) -> QWidget:
    return InfrastructureSettingsSection(context)


def demo_asset_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """An add-asset dialog filled with a fictitious asset (it writes nothing unless accepted)."""
    dialog = AssetDialog(context, parent)
    dialog.tag_edit.setText("DEMO-A001")
    dialog.location_edit.setText("DEMO ward")
    return dialog


def demo_status_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A status dialog filled with a fictitious status event."""
    event = StatusEventView(
        id=0,
        asset_id=0,
        effective_on=date(2026, 3, 2),
        status=AssetStatus.DEGRADED,
        note="Demo note",
    )
    return StatusDialog(context, parent, 0, "DEMO-A001", event)


def demo_maintenance_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A maintenance dialog filled with a fictitious maintenance record."""
    record = MaintenanceView(
        id=0,
        asset_id=0,
        performed_on=date(2026, 3, 2),
        kind=MaintenanceKind.PREVENTIVE,
        next_due_on=date(2026, 9, 2),
        note="Demo note",
    )
    return MaintenanceDialog(context, parent, 0, "DEMO-A001", record)


def demo_type_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A type dialog filled with a fictitious user-defined type."""
    asset_type = AssetTypeView(
        id=0,
        code="DEMO-TENT",
        built_in=False,
        label_pt_br="Tenda de demonstracao",
        label_en_us="Demo tent",
        label_es_es=None,
        default_maintenance_interval_days=180,
        active=True,
    )
    return TypeDialog(context, parent, asset_type)
