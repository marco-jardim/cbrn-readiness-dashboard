# SPDX-License-Identifier: GPL-3.0-or-later
"""The page "Antidotes and decontaminants" (PLAN.md T11.11, D19, D38).

The page shows the stock of the item types of the categories antidote and decontaminant as of
``context.as_of``. It is MANAGEMENT data only: quantities, lots, expiry dates, prices and movements.
Under a header (the as-of date and a note saying so) and a type filter of its own there are three
tabs:

* "Lots and movements": the shared :class:`~cbrn_dashboard.ui.stock.panel.StockPanel` limited to the
  two categories (it edits through the stock service and is read-only in read-only mode);
* "Expiry schedule": the lots with stock by period of expiry (expired, one row group per month of
  the horizon of 6, 12 or 24 months, later, no expiry date), from ``StockService.expiry_schedule``;
* "Alerts": the stock alerts of these two categories from ``AlertService.alerts``. "Open record"
  (or activating a row) selects the lot in the first tab for a lot alert and sets the type filter
  for an item-type or indicator alert.

The type filter limits the lots and the schedule; the alerts tab always lists every alert of the
two categories. Nothing here writes data, and the page reads again on every as-of, data and language
change. The module-level factories are what the registry of the shell calls.
"""

from dataclasses import replace

from PySide6.QtCore import QCoreApplication, QEvent, QModelIndex
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from cbrn_dashboard.domain.alerts import Alert, SubjectKind
from cbrn_dashboard.domain.indicators import InvalidDimensionError, Module, decode_dimension
from cbrn_dashboard.domain.stock import ANTIDOTE_PAGE_CATEGORIES, CATEGORY_ORDER, ScheduleBucket
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.stock import StockTypeView
from cbrn_dashboard.ui.alerts.labels import error_label as alert_error_label
from cbrn_dashboard.ui.alerts.models import ANTIDOTES_PAGE, AlertsModel, page_key_for
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import format_date
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_tab_order,
    current_language,
    follow_language,
    make_table_view,
    mark_data,
)
from cbrn_dashboard.ui.stock.labels import error_label as stock_error_label
from cbrn_dashboard.ui.stock.labels import fill_placeholders, stock_type_display
from cbrn_dashboard.ui.stock.models import ScheduleModel
from cbrn_dashboard.ui.stock.panel import StockPanel

__all__ = ["AntidotesPage", "create_page", "page_title"]

# The positions of the three tabs.
LOTS_TAB = 0
SCHEDULE_TAB = 1
ALERTS_TAB = 2

# The horizons of the expiry schedule in months, and the one shown first.
HORIZONS: tuple[int, ...] = (6, 12, 24)
DEFAULT_HORIZON = 12


def _dimension_part(alert: Alert, key: str) -> str | None:
    """One key of the dimension of ``alert`` (``category`` or ``item``), ``None`` when absent."""
    try:
        return decode_dimension(alert.dimension).get(key)
    except InvalidDimensionError:
        return None


class AntidotesPage(QWidget):
    """Lots, expiry schedule and alerts of the antidote and decontaminant item types."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("antidotes_page")
        self.context = context
        self._types: dict[str, StockTypeView] = {}
        self._alerts: list[Alert] = []
        self._schedule_problem: str | None = None
        self._alerts_problem: str | None = None
        self.schedule_model = ScheduleModel(self)
        self.alerts_model = AlertsModel(self)

        self.as_of_label = QLabel(self)
        self.as_of_label.setObjectName("as_of_label")
        font = self.as_of_label.font()
        font.setBold(True)
        self.as_of_label.setFont(font)
        self.note_label = QLabel(self)
        self.note_label.setObjectName("note_label")
        self.note_label.setWordWrap(True)
        self.type_caption = QLabel(self)
        self.type_combo = QComboBox(self)
        self.type_combo.setObjectName("type_filter")
        mark_data(self.type_combo)
        self.type_caption.setBuddy(self.type_combo)
        self.type_combo.addItem("", None)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("antidotes_tabs")
        self.panel = StockPanel(context, ANTIDOTE_PAGE_CATEGORIES, self.tabs)

        self.schedule_tab = QWidget(self.tabs)
        self.schedule_tab.setObjectName("schedule_tab")
        self.horizon_caption = QLabel(self.schedule_tab)
        self.horizon_combo = QComboBox(self.schedule_tab)
        self.horizon_combo.setObjectName("horizon_combo")
        self.horizon_caption.setBuddy(self.horizon_combo)
        for months in HORIZONS:
            self.horizon_combo.addItem("", months)
        self.horizon_combo.setCurrentIndex(HORIZONS.index(DEFAULT_HORIZON))
        self.schedule_view = make_table_view(self.schedule_model, self.schedule_tab)
        self.schedule_view.setObjectName("schedule_view")
        self.schedule_empty_label = QLabel(self.schedule_tab)
        self.schedule_empty_label.setObjectName("schedule_empty_label")
        self.schedule_empty_label.setWordWrap(True)
        horizon_row = QHBoxLayout()
        horizon_row.addWidget(self.horizon_caption)
        horizon_row.addWidget(self.horizon_combo)
        horizon_row.addStretch(1)
        schedule_layout = QVBoxLayout(self.schedule_tab)
        schedule_layout.addLayout(horizon_row)
        schedule_layout.addWidget(self.schedule_view, 1)
        schedule_layout.addWidget(self.schedule_empty_label)

        self.alerts_tab = QWidget(self.tabs)
        self.alerts_tab.setObjectName("alerts_tab")
        self.alerts_count_label = QLabel(self.alerts_tab)
        self.alerts_count_label.setObjectName("alerts_count_label")
        self.alerts_view = make_table_view(self.alerts_model, self.alerts_tab)
        self.alerts_view.setObjectName("alerts_view")
        self.alerts_empty_label = QLabel(self.alerts_tab)
        self.alerts_empty_label.setObjectName("alerts_empty_label")
        self.alerts_empty_label.setWordWrap(True)
        # A navigation action: it never edits data, so it is not registered as an edit action.
        self.open_action = EditAction(
            self, lambda: QCoreApplication.translate("Antidotes", "Open record")
        )
        alerts_layout = QVBoxLayout(self.alerts_tab)
        alerts_layout.addWidget(self.alerts_count_label)
        alerts_layout.addWidget(self.alerts_view, 1)
        alerts_layout.addWidget(self.alerts_empty_label)
        alerts_layout.addLayout(action_row((self.open_action,), self.alerts_tab))

        self.tabs.addTab(self.panel, "")
        self.tabs.addTab(self.schedule_tab, "")
        self.tabs.addTab(self.alerts_tab, "")

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.type_caption)
        filter_row.addWidget(self.type_combo)
        filter_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.as_of_label)
        layout.addWidget(self.note_label)
        layout.addLayout(filter_row)
        layout.addWidget(self.tabs, 1)
        apply_tab_order(self)

        self.type_combo.currentIndexChanged.connect(self._filter_changed)
        self.horizon_combo.currentIndexChanged.connect(self._horizon_changed)
        selection = self.alerts_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        self.alerts_view.activated.connect(self._activated)
        self.open_action.triggered.connect(self.open_selected)
        context.data_changed.connect(self.refresh)
        context.as_of_changed.connect(self._as_of_changed)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        """Re-apply every text of the page in the current language."""
        lang = current_language(self.context)
        self._update_as_of()
        self.note_label.setText(
            QCoreApplication.translate(
                "Antidotes", "Management data: quantities, lots, expiry dates and prices."
            )
        )
        self.type_caption.setText(QCoreApplication.translate("Antidotes", "Type"))
        self.type_combo.setAccessibleName(QCoreApplication.translate("Antidotes", "Type"))
        self.horizon_caption.setText(QCoreApplication.translate("Antidotes", "Horizon"))
        self.horizon_combo.setAccessibleName(QCoreApplication.translate("Antidotes", "Horizon"))
        for position, months in enumerate(HORIZONS):
            self.horizon_combo.setItemText(
                position, QCoreApplication.translate("Antidotes", "%n month(s)", None, months)
            )
        self.schedule_view.setAccessibleName(
            QCoreApplication.translate("Antidotes", "Expiry schedule")
        )
        self.alerts_view.setAccessibleName(QCoreApplication.translate("Antidotes", "Alerts"))
        self.tabs.setTabText(
            LOTS_TAB, QCoreApplication.translate("Antidotes", "Lots and movements")
        )
        self.tabs.setTabText(
            SCHEDULE_TAB, QCoreApplication.translate("Antidotes", "Expiry schedule")
        )
        self.tabs.setTabText(ALERTS_TAB, QCoreApplication.translate("Antidotes", "Alerts"))
        self.open_action.retranslate()
        self._type_texts()
        self._update_empty_texts()
        self._update_count()
        self.schedule_model.set_language(lang)
        self.alerts_model.set_language(lang)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def _update_as_of(self) -> None:
        self.as_of_label.setText(
            fill_placeholders(
                QCoreApplication.translate("Antidotes", "As of %1"),
                format_date(self.context.as_of, current_language(self.context)),
            )
        )

    def _update_count(self) -> None:
        self.alerts_count_label.setText(
            QCoreApplication.translate(
                "Antidotes", "%n alert(s) shown", None, self.alerts_model.rowCount()
            )
        )

    def _update_empty_texts(self) -> None:
        if self._schedule_problem is None:
            schedule = QCoreApplication.translate(
                "Antidotes", "No lots with stock to schedule for this date."
            )
        else:
            schedule = stock_error_label(self._schedule_problem)
        self.schedule_empty_label.setText(schedule)
        if self._alerts_problem is None:
            alerts = QCoreApplication.translate("Antidotes", "No stock alerts for this date.")
        else:
            alerts = alert_error_label(self._alerts_problem)
        self.alerts_empty_label.setText(alerts)

    # ----- the type filter

    def type_code(self) -> str | None:
        """The code of the item type the page is limited to (``None``: every type)."""
        data = self.type_combo.currentData()
        return data if isinstance(data, str) else None

    def horizon_months(self) -> int:
        """The horizon of the expiry schedule in months (6, 12 or 24)."""
        data = self.horizon_combo.currentData()
        return data if isinstance(data, int) else DEFAULT_HORIZON

    def _filter_codes(self) -> list[str]:
        """The codes of the filter entries, ordered by category and then by name in the language.

        These are the active types of the two categories and the inactive ones that have lots.
        """
        service = self.context.services.stock
        if service is None:
            return []
        with_lots = {lot.type_code for lot in service.list_lots()}
        lang = current_language(self.context)
        wanted = [
            item
            for item in self._types.values()
            if item.category in ANTIDOTE_PAGE_CATEGORIES and (item.active or item.code in with_lots)
        ]
        wanted.sort(
            key=lambda item: (
                CATEGORY_ORDER.index(item.category),
                stock_type_display(item, lang).casefold(),
                item.code,
            )
        )
        return [item.code for item in wanted]

    def _sync_type_filter(self, wanted: list[str]) -> None:
        """Rebuild the filter when its entries changed (no refresh while doing so)."""
        current = [self.type_combo.itemData(i) for i in range(1, self.type_combo.count())]
        if wanted == current:
            return
        previous = self.type_combo.currentData()
        self.type_combo.blockSignals(True)
        while self.type_combo.count() > 1:
            self.type_combo.removeItem(1)
        for code in wanted:
            self.type_combo.addItem("", code)
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(previous)))
        self.type_combo.blockSignals(False)

    def _type_texts(self) -> None:
        """Rebuild the filter when needed, then name every entry in the current language."""
        try:
            wanted = self._filter_codes()
        except ServiceError:
            wanted = []
        self._sync_type_filter(wanted)
        self.type_combo.setItemText(
            0, QCoreApplication.translate("Antidotes", "All antidotes and decontaminants")
        )
        lang = current_language(self.context)
        for index in range(1, self.type_combo.count()):
            item = self._types.get(str(self.type_combo.itemData(index)))
            if item is not None:
                self.type_combo.setItemText(index, stock_type_display(item, lang))

    def set_type_filter(self, code: str | None) -> None:
        """Choose the entry of ``code`` (``None`` or an unknown code: every type)."""
        self.type_combo.setCurrentIndex(max(0, self.type_combo.findData(code)))

    def _filter_changed(self, _index: int) -> None:
        self._apply_filter()

    def _apply_filter(self) -> None:
        self.panel.set_type_filter(self.type_code())
        self._refresh_schedule()

    def _horizon_changed(self, _index: int) -> None:
        self._refresh_schedule()

    # ----- data

    def _as_of_changed(self, _value: object) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Read the types, the schedule and the alerts of the as-of date again.

        A service error leaves the table empty with the translated message in the empty-state
        label; nothing is raised from a slot.
        """
        service = self.context.services.stock
        self._types = {}
        if service is not None:
            try:
                listed = service.list_types(include_inactive=True)
                self._types = {item.code: item for item in listed}
            except ServiceError:
                self._types = {}
        self._type_texts()
        self._update_as_of()
        self.panel.set_type_filter(self.type_code())
        self._refresh_schedule()
        self._refresh_alerts()

    def _refresh_schedule(self) -> None:
        service = self.context.services.stock
        buckets: tuple[ScheduleBucket, ...] = ()
        self._schedule_problem = None
        if service is not None:
            try:
                buckets = service.expiry_schedule(
                    self.context.as_of, self.horizon_months(), ANTIDOTE_PAGE_CATEGORIES
                )
            except ServiceError as error:
                self._schedule_problem = error.code
        code = self.type_code()
        if code is not None:
            # Only the lots are shown; the per-type sums of a bucket are not used by this page.
            buckets = tuple(
                replace(bucket, lots=tuple(lot for lot in bucket.lots if lot.type_code == code))
                for bucket in buckets
            )
        self.schedule_model.set_buckets(buckets, self._types)
        self._update_empty_texts()
        self.schedule_empty_label.setVisible(self.schedule_model.rowCount() == 0)

    def selected_alert(self) -> Alert | None:
        row = self.alerts_model.selected_row(self.alerts_view)
        return row if isinstance(row, Alert) else None

    def shown_alerts(self) -> list[Alert]:
        """The alerts in the table: the stock alerts of the two categories, in service order."""
        return [row for row in self.alerts_model.rows() if isinstance(row, Alert)]

    def _refresh_alerts(self) -> None:
        service = self.context.services.alerts
        self._alerts = []
        self._alerts_problem = None
        if service is not None:
            try:
                self._alerts = [
                    alert
                    for alert in service.alerts(self.context.as_of)
                    if alert.module is Module.STOCK and page_key_for(alert) == ANTIDOTES_PAGE
                ]
            except ServiceError as error:
                self._alerts_problem = error.code
        previous = self.selected_alert()
        self.alerts_model.set_alerts(self._alerts)
        if previous is not None and previous in self._alerts:
            self.alerts_view.selectRow(self._alerts.index(previous))
        self._update_empty_texts()
        self.alerts_empty_label.setVisible(not self._alerts)
        self._update_count()
        self._update_actions()

    def _update_actions(self, *_args: object) -> None:
        self.open_action.setEnabled(self.selected_alert() is not None)

    # ----- open record

    def _activated(self, _index: QModelIndex) -> None:
        self.open_selected()

    def open_selected(self) -> bool:
        """Show the record of the selected alert in the first tab; ``False`` when none is selected.

        A lot alert selects the lot (the type filter is reset to "all" when it would hide the
        lot); an item-type or indicator alert sets the type filter to its type, or to every type
        when the alert names only a category.
        """
        alert = self.selected_alert()
        if alert is None:
            return False
        item = _dimension_part(alert, "item")
        if item is None and alert.subject_kind is SubjectKind.ITEM_TYPE:
            item = alert.subject_ref
        if alert.subject_kind is SubjectKind.LOT and alert.subject_id is not None:
            if self.type_code() not in (None, item):
                self.set_type_filter(None)
            self.tabs.setCurrentIndex(LOTS_TAB)
            self._select_lot(alert.subject_id)
            return True
        self.set_type_filter(item)
        self.tabs.setCurrentIndex(LOTS_TAB)
        return True

    def _select_lot(self, lot_id: int) -> bool:
        for index, row in enumerate(self.panel.lots_model.rows()):
            if row.row.lot_id == lot_id:
                self.panel.lots_view.selectRow(index)
                return True
        return False


# --------------------------------------------------------------------------- registry factories


def page_title() -> str:
    return QCoreApplication.translate("Antidotes", "Antidotes and decontaminants")


def create_page(context: AppContext) -> QWidget:
    return AntidotesPage(context)
