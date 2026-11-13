# SPDX-License-Identifier: GPL-3.0-or-later
"""Table models of the snapshot list and of the import error report (PLAN.md T8.7, T8.4, T8.1).

Headers are translated on every ``headerData`` call; dates are formatted for the current language.
Cell contents are data: times, versions, the operator's reasons and the codes of the error report.
"""

from typing import Any

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.services.importer import ImportError as ImportIssue
from cbrn_dashboard.services.snapshots import SnapshotView
from cbrn_dashboard.ui.reports.labels import error_label, origin_label, state_label
from cbrn_dashboard.ui.shell.formatting import format_date, format_number
from cbrn_dashboard.ui.shell.widgets import Column, ModuleTableModel

__all__ = ["IssuesModel", "SnapshotsModel"]

#: A missing value in a cell (data, not a translatable text).
NOT_RECORDED = "-"


class SnapshotsModel(ModuleTableModel):
    """The recorded snapshots: as-of date, time taken, origin, version, state and reason."""

    COLUMNS = (
        Column[Any](
            "as_of",
            lambda: QCoreApplication.translate("ReportsUi", "As of"),
            lambda row, lang: format_date(row.as_of, lang),
        ),
        Column[Any](
            "taken",
            lambda: QCoreApplication.translate("ReportsUi", "Recorded at (UTC)"),
            lambda row, lang: row.taken_at_utc,
        ),
        Column[Any](
            "origin",
            lambda: QCoreApplication.translate("ReportsUi", "Origin"),
            lambda row, lang: origin_label(row.origin.value),
        ),
        Column[Any](
            "version",
            lambda: QCoreApplication.translate("ReportsUi", "Version"),
            lambda row, lang: row.app_version,
        ),
        Column[Any](
            "state",
            lambda: QCoreApplication.translate("ReportsUi", "State"),
            lambda row, lang: state_label(withdrawn=row.withdrawn),
        ),
        Column[Any](
            "reason",
            lambda: QCoreApplication.translate("ReportsUi", "Reason for withdrawal"),
            lambda row, lang: row.withdrawal_reason or NOT_RECORDED,
        ),
        Column[Any](
            "id",
            lambda: QCoreApplication.translate("ReportsUi", "Snapshot number"),
            lambda row, lang: format_number(row.id, lang, decimals=0),
            align_right=True,
        ),
    )

    def set_snapshots(self, snapshots: list[SnapshotView]) -> None:
        self.set_rows(snapshots)


class IssuesModel(ModuleTableModel):
    """The per-row error report of an import: line, column, the message and the raw code."""

    COLUMNS = (
        Column[Any](
            "line",
            lambda: QCoreApplication.translate("ReportsUi", "Line"),
            lambda row, lang: (
                format_number(row.line, lang, decimals=0) if row.line > 0 else NOT_RECORDED
            ),
            align_right=True,
        ),
        Column[Any](
            "column",
            lambda: QCoreApplication.translate("ReportsUi", "Column"),
            lambda row, lang: row.column or NOT_RECORDED,
        ),
        Column[Any](
            "problem",
            lambda: QCoreApplication.translate("ReportsUi", "Problem"),
            lambda row, lang: error_label(row.code),
        ),
        Column[Any](
            "code",
            lambda: QCoreApplication.translate("ReportsUi", "Code"),
            lambda row, lang: row.code,
        ),
    )

    def set_issues(self, issues: tuple[ImportIssue, ...]) -> None:
        self.set_rows(list(issues))
