# SPDX-License-Identifier: GPL-3.0-or-later
"""Table models of the budget page and of the funding-source editor (PLAN.md T5.4, D15).

Headers are translated on every ``headerData`` call; money, dates and percentages are formatted
for the current language with the shared formatting functions. Amounts are whole minor units; the
currencies are shown on separate rows and never added (D15). Cell contents are data.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.domain.budget import BudgetTotal
from cbrn_dashboard.services.budget import EntryView, ExecutionView, SourceView
from cbrn_dashboard.ui.budget.labels import source_display, source_name
from cbrn_dashboard.ui.shell.formatting import (
    FormatError,
    format_date,
    format_money,
    format_percent,
)
from cbrn_dashboard.ui.shell.widgets import Column, ModuleTableModel

__all__ = [
    "EntriesModel",
    "EntryRow",
    "ExecutionRow",
    "ExecutionsModel",
    "SourcesModel",
    "SummaryModel",
    "SummaryRow",
    "money_text",
    "rate_text",
]

#: A missing value in a cell (data, not a translatable text).
NOT_RECORDED = "-"


def money_text(minor: int | None, currency: str, lang: str) -> str:
    """``minor`` units of ``currency`` as money in ``lang``.

    ``-`` when there is no amount or it cannot be shown (a currency outside the allow-list, or an
    amount too large): raw minor units would read as 100 times the amount.
    """
    if minor is None:
        return NOT_RECORDED
    try:
        return format_money(minor, currency, lang)
    except FormatError:
        return NOT_RECORDED


def rate_text(rate: float | None, lang: str) -> str:
    """The execution rate as a percentage; ``-`` when there is no rate or it cannot be shown."""
    if rate is None:
        return NOT_RECORDED
    try:
        return format_percent(rate, lang)
    except FormatError:
        return NOT_RECORDED


# --------------------------------------------------------------------------- summary


@dataclass(frozen=True)
class SummaryRow:
    """The totals of one (source, currency) group of the selected year."""

    total: BudgetTotal
    sources: Mapping[str, SourceView]


class SummaryModel(ModuleTableModel):
    """Allocated, executed (as of the as-of date) and execution rate per source and currency."""

    COLUMNS = (
        Column[Any](
            "source",
            lambda: QCoreApplication.translate("Budget", "Source"),
            lambda row, lang: source_name(row.total.source_code, lang, row.sources),
        ),
        Column[Any](
            "currency",
            lambda: QCoreApplication.translate("Budget", "Currency"),
            lambda row, lang: row.total.currency,
        ),
        Column[Any](
            "allocated",
            lambda: QCoreApplication.translate("Budget", "Allocated"),
            lambda row, lang: money_text(row.total.allocated_minor, row.total.currency, lang),
            align_right=True,
        ),
        Column[Any](
            "executed",
            lambda: QCoreApplication.translate("Budget", "Executed"),
            lambda row, lang: money_text(row.total.executed_minor, row.total.currency, lang),
            align_right=True,
        ),
        Column[Any](
            "rate",
            lambda: QCoreApplication.translate("Budget", "Execution rate"),
            lambda row, lang: rate_text(row.total.rate, lang),
            align_right=True,
        ),
    )

    def set_totals(self, totals: list[BudgetTotal], sources: Mapping[str, SourceView]) -> None:
        self.set_rows([SummaryRow(total, sources) for total in totals])


# --------------------------------------------------------------------------- entries


@dataclass(frozen=True)
class EntryRow:
    """A stored entry with the sources (to name its source in the current language)."""

    entry: EntryView
    sources: Mapping[str, SourceView]


class EntriesModel(ModuleTableModel):
    """The entries of the selected year: source, currency, description, allocated amount."""

    COLUMNS = (
        Column[Any](
            "source",
            lambda: QCoreApplication.translate("Budget", "Source"),
            lambda row, lang: source_name(row.entry.source_code, lang, row.sources),
        ),
        Column[Any](
            "currency",
            lambda: QCoreApplication.translate("Budget", "Currency"),
            lambda row, lang: row.entry.currency,
        ),
        Column[Any](
            "description",
            lambda: QCoreApplication.translate("Budget", "Description"),
            lambda row, lang: row.entry.description,
        ),
        Column[Any](
            "allocated",
            lambda: QCoreApplication.translate("Budget", "Allocated"),
            lambda row, lang: money_text(row.entry.allocated_minor, row.entry.currency, lang),
            align_right=True,
        ),
    )

    def set_entries(self, entries: list[EntryView], sources: Mapping[str, SourceView]) -> None:
        self.set_rows([EntryRow(entry, sources) for entry in entries])


# --------------------------------------------------------------------------- execution rows


@dataclass(frozen=True)
class ExecutionRow:
    """An execution row with the currency of its entry."""

    execution: ExecutionView
    currency: str


class ExecutionsModel(ModuleTableModel):
    """The dated execution rows of the selected entry: date, amount, note."""

    COLUMNS = (
        Column[Any](
            "date",
            lambda: QCoreApplication.translate("Budget", "Date"),
            lambda row, lang: format_date(row.execution.executed_on, lang),
        ),
        Column[Any](
            "amount",
            lambda: QCoreApplication.translate("Budget", "Amount"),
            lambda row, lang: money_text(row.execution.amount_minor, row.currency, lang),
            align_right=True,
        ),
        Column[Any](
            "note",
            lambda: QCoreApplication.translate("Budget", "Note"),
            lambda row, lang: row.execution.note or "",
        ),
    )

    def set_executions(self, executions: tuple[ExecutionView, ...], currency: str) -> None:
        self.set_rows([ExecutionRow(execution, currency) for execution in executions])


# --------------------------------------------------------------------------- funding sources


class SourcesModel(ModuleTableModel):
    """The funding sources, including the inactive and the built-in ones (settings section)."""

    COLUMNS = (
        Column[Any](
            "code",
            lambda: QCoreApplication.translate("Budget", "Code"),
            lambda row, lang: row.code,
        ),
        Column[Any](
            "name",
            lambda: QCoreApplication.translate("Budget", "Name"),
            lambda row, lang: source_display(row, lang),
        ),
        Column[Any](
            "kind",
            lambda: QCoreApplication.translate("Budget", "Type"),
            lambda row, lang: (
                QCoreApplication.translate("Budget", "Built-in")
                if row.built_in
                else QCoreApplication.translate("Budget", "User-defined")
            ),
        ),
        Column[Any](
            "status",
            lambda: QCoreApplication.translate("Budget", "Status"),
            lambda row, lang: (
                QCoreApplication.translate("Budget", "Active")
                if row.active
                else QCoreApplication.translate("Budget", "Inactive")
            ),
        ),
    )
