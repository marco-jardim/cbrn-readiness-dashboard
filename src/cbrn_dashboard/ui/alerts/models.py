# SPDX-License-Identifier: GPL-3.0-or-later
"""Table model of the alerts page and the page an alert refers to (PLAN.md T6.3).

Headers are translated on every ``headerData`` call; the severity column shows its text and an icon;
the due date and the message are formatted for the current language. Subjects are data.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.domain.alerts import Alert, SubjectKind
from cbrn_dashboard.domain.indicators import Module
from cbrn_dashboard.ui.alerts.labels import (
    alert_message,
    module_label,
    severity_icon,
    severity_label,
    subject_text,
)
from cbrn_dashboard.ui.shell.formatting import format_date
from cbrn_dashboard.ui.shell.widgets import Column, ModuleTableModel

__all__ = ["SEVERITY_COLUMN", "AlertsModel", "page_key_for"]

#: A missing value in a cell (data, not a translatable text).
NOT_RECORDED = "-"

#: The column that shows the severity icon next to its text.
SEVERITY_COLUMN = 0

_MODULE_PAGES: dict[str, str] = {
    Module.PERSONNEL.value: "personnel",
    Module.INFRASTRUCTURE.value: "infrastructure",
    Module.EXERCISES.value: "exercises",
    Module.BUDGET.value: "budget",
}


def page_key_for(alert: Alert) -> str:
    """The registry key of the page of the record an alert refers to.

    A staff member opens Personnel, an asset opens Infrastructure and an indicator opens the page
    of its module. ``""`` when no page is known.
    """
    if alert.subject_kind is SubjectKind.STAFF:
        return _MODULE_PAGES[Module.PERSONNEL.value]
    if alert.subject_kind is SubjectKind.ASSET:
        return _MODULE_PAGES[Module.INFRASTRUCTURE.value]
    return _MODULE_PAGES.get(alert.module.value, "")


def _due_text(value: date | None, lang: str) -> str:
    return NOT_RECORDED if value is None else format_date(value, lang)


class AlertsModel(ModuleTableModel):
    """The alerts: severity (text and icon), module, subject, due date and message."""

    COLUMNS = (
        Column[Any](
            "severity",
            lambda: QCoreApplication.translate("Alerts", "Severity"),
            lambda row, lang: severity_label(row.severity.value),
            icon=lambda row: severity_icon(row.severity.value),
        ),
        Column[Any](
            "module",
            lambda: QCoreApplication.translate("Alerts", "Module"),
            lambda row, lang: module_label(row.module.value),
        ),
        Column[Any](
            "subject",
            lambda: QCoreApplication.translate("Alerts", "Subject"),
            lambda row, lang: subject_text(row),
        ),
        Column[Any](
            "due",
            lambda: QCoreApplication.translate("Alerts", "Due date"),
            lambda row, lang: _due_text(row.due_on, lang),
        ),
        Column[Any](
            "message",
            lambda: QCoreApplication.translate("Alerts", "Message"),
            lambda row, lang: alert_message(row, lang),
        ),
    )

    def set_alerts(self, alerts: Sequence[Alert]) -> None:
        self.set_rows(alerts)
