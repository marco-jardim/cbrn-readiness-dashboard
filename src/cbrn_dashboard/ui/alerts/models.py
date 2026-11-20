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
from cbrn_dashboard.domain.indicators import InvalidDimensionError, Module, decode_dimension
from cbrn_dashboard.domain.stock import ANTIDOTE_PAGE_CATEGORIES
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
    Module.STOCK.value: "infrastructure",
}

#: The page of the antidotes and decontaminants (T11.11); every other stock category stays on
#: the Infrastructure page.
ANTIDOTES_PAGE = "antidotes"

_ANTIDOTE_CATEGORIES = frozenset(category.value for category in ANTIDOTE_PAGE_CATEGORIES)


def _stock_page_key(alert: Alert) -> str:
    """The page of a stock alert: by the category of its dimension (antidote or decontaminant)."""
    try:
        parts = decode_dimension(alert.dimension)
    except InvalidDimensionError:
        return _MODULE_PAGES[Module.STOCK.value]
    if parts.get("category") in _ANTIDOTE_CATEGORIES:
        return ANTIDOTES_PAGE
    return _MODULE_PAGES[Module.STOCK.value]


def page_key_for(alert: Alert) -> str:
    """The registry key of the page of the record an alert refers to.

    A staff member opens Personnel, an asset opens Infrastructure and an indicator opens the page
    of its module. A lot, an item type and an indicator of the stock module open the page
    ``antidotes`` for the categories antidote and decontaminant and Infrastructure for any other
    category. ``""`` when no page is known.
    """
    if alert.subject_kind is SubjectKind.STAFF:
        return _MODULE_PAGES[Module.PERSONNEL.value]
    if alert.subject_kind is SubjectKind.ASSET:
        return _MODULE_PAGES[Module.INFRASTRUCTURE.value]
    stock_subject = alert.subject_kind in (SubjectKind.LOT, SubjectKind.ITEM_TYPE)
    if stock_subject or alert.module is Module.STOCK:
        return _stock_page_key(alert)
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
