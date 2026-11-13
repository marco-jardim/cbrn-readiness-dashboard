# SPDX-License-Identifier: GPL-3.0-or-later
"""The Alerts page (PLAN.md T6.3, section 5.5, D13, D23).

The page lists the alerts of ``context.as_of`` read through ``context.services.alerts``: severity as
text and icon, module, subject, due date and a localized message. It can be filtered by module and
by severity. Activating an alert (double click, Enter, or the "Open record" button) asks the main
window to show the page of the record it refers to; the page is looked up in the page registry.
The page only reads: nothing here edits data, so nothing is registered as an edit action and the
page works in read-only mode. The module-level factories are what the registries of the shell call.
"""

from PySide6.QtCore import QCoreApplication, QEvent, QModelIndex, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cbrn_dashboard.domain.alerts import Alert
from cbrn_dashboard.ui.alerts.labels import (
    ALL_MODULE_CODES,
    ALL_SEVERITY_CODES,
    module_label,
    severity_label,
)
from cbrn_dashboard.ui.alerts.models import AlertsModel, page_key_for
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    current_language,
    follow_language,
    make_table_view,
)

__all__ = ["AlertsPage", "create_page", "page_title"]

#: The data of the "all" entry of both filter combo boxes (never a module or severity code).
_ALL = "ALL"


class AlertsPage(QWidget):
    """The alerts of the as-of date, filtered by module and severity."""

    #: Emitted with the registry key of the page to open when an alert is activated.
    page_requested = Signal(str)

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("alerts_page")
        self.context = context
        self._alerts: list[Alert] = []
        self.model = AlertsModel(self)

        self.module_caption = QLabel(self)
        self.module_combo = QComboBox(self)
        self.module_combo.setObjectName("module_filter")
        self.module_caption.setBuddy(self.module_combo)
        self.module_combo.addItem("", _ALL)
        for code in ALL_MODULE_CODES:
            self.module_combo.addItem("", code)
        self.severity_caption = QLabel(self)
        self.severity_combo = QComboBox(self)
        self.severity_combo.setObjectName("severity_filter")
        self.severity_caption.setBuddy(self.severity_combo)
        self.severity_combo.addItem("", _ALL)
        for code in ALL_SEVERITY_CODES:
            self.severity_combo.addItem("", code)

        self.view = make_table_view(self.model, self)
        self.view.setObjectName("alerts_view")
        self.count_label = QLabel(self)
        self.count_label.setObjectName("count_label")
        self.empty_label = QLabel(self)
        self.empty_label.setObjectName("empty_label")
        self.open_action = EditAction(
            self, lambda: QCoreApplication.translate("Alerts", "Open record")
        )

        filters = QHBoxLayout()
        filters.addWidget(self.module_caption)
        filters.addWidget(self.module_combo)
        filters.addWidget(self.severity_caption)
        filters.addWidget(self.severity_combo)
        filters.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self.count_label)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.empty_label)
        layout.addLayout(action_row((self.open_action,), self))

        self.module_combo.currentIndexChanged.connect(self._filter_changed)
        self.severity_combo.currentIndexChanged.connect(self._filter_changed)
        selection = self.view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        self.view.activated.connect(self._activated)
        self.open_action.triggered.connect(self.open_selected)
        context.as_of_changed.connect(self._as_of_changed)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        """Re-apply every text of the page in the current language."""
        self.module_caption.setText(QCoreApplication.translate("Alerts", "Module"))
        self.severity_caption.setText(QCoreApplication.translate("Alerts", "Severity"))
        self.module_combo.setAccessibleName(QCoreApplication.translate("Alerts", "Module"))
        self.severity_combo.setAccessibleName(QCoreApplication.translate("Alerts", "Severity"))
        self.view.setAccessibleName(QCoreApplication.translate("Alerts", "Alerts"))
        self.module_combo.setItemText(0, QCoreApplication.translate("Alerts", "All modules"))
        for position, code in enumerate(ALL_MODULE_CODES, start=1):
            self.module_combo.setItemText(position, module_label(code))
        self.severity_combo.setItemText(0, QCoreApplication.translate("Alerts", "All severities"))
        for position, code in enumerate(ALL_SEVERITY_CODES, start=1):
            self.severity_combo.setItemText(position, severity_label(code))
        self.empty_label.setText(QCoreApplication.translate("Alerts", "No alerts for this date."))
        self.open_action.retranslate()
        self.model.set_language(current_language(self.context))
        self._update_count()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- data

    def selected_alert(self) -> Alert | None:
        row = self.model.selected_row(self.view)
        return row if isinstance(row, Alert) else None

    def shown_alerts(self) -> list[Alert]:
        """The alerts in the table (after the filters), in the order of the service."""
        return [row for row in self.model.rows() if isinstance(row, Alert)]

    def _as_of_changed(self, _value: object) -> None:
        self.refresh()

    def refresh(self) -> None:
        """Read the alerts of the as-of date again and apply the filters."""
        service = self.context.services.alerts
        self._alerts = [] if service is None else service.alerts(self.context.as_of)
        self._apply_filters()

    def _filter_changed(self, _index: int) -> None:
        self._apply_filters()

    def _apply_filters(self) -> None:
        module = str(self.module_combo.currentData())
        severity = str(self.severity_combo.currentData())
        previous = self.selected_alert()
        shown = [
            alert
            for alert in self._alerts
            if (module == _ALL or alert.module.value == module)
            and (severity == _ALL or alert.severity.value == severity)
        ]
        self.model.set_alerts(shown)
        if previous is not None and previous in shown:
            self.view.selectRow(shown.index(previous))
        self.empty_label.setVisible(not shown)
        self._update_count()
        self._update_actions()

    def _update_count(self) -> None:
        self.count_label.setText(
            QCoreApplication.translate("Alerts", "%n alert(s) shown", None, self.model.rowCount())
        )

    def _update_actions(self, *_args: object) -> None:
        self.open_action.setEnabled(self.selected_alert() is not None)

    # ----- activation

    def _activated(self, _index: QModelIndex) -> None:
        self.open_selected()

    def open_selected(self) -> bool:
        """Show the page of the record of the selected alert; ``False`` when it cannot be shown.

        The page key must be one of the registered pages (looked up in the registry). The main
        window of the page (its top-level widget) switches to it; ``page_requested`` is emitted
        too, for any other listener.
        """
        alert = self.selected_alert()
        if alert is None:
            return False
        key = page_key_for(alert)
        # Imported here: the registry imports this module to register the page.
        from cbrn_dashboard.ui.shell import registry

        if key not in {spec.key for spec in registry.pages()}:
            return False
        self.page_requested.emit(key)
        show_page = getattr(self.window(), "show_page", None)
        if callable(show_page):
            show_page(key)
        return True


# --------------------------------------------------------------------------- registry factories


def page_title() -> str:
    return QCoreApplication.translate("Alerts", "Alerts")


def create_page(context: AppContext) -> QWidget:
    return AlertsPage(context)
