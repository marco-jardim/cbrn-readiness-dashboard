# SPDX-License-Identifier: GPL-3.0-or-later
"""Table models of the infrastructure page and of the asset-type editor (PLAN.md T3.4).

Headers are translated on every ``headerData`` call; cells are formatted for the current language
with the shared formatting functions (dates, numbers). Statuses and schedule flags are TEXT (D23).
Tags, locations and user-defined type labels in cells are data.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon

from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.domain.infrastructure import AssetRow, AssetStatus
from cbrn_dashboard.services.infrastructure import (
    AssetTypeView,
    AssetView,
    MaintenanceView,
    StatusEventView,
)
from cbrn_dashboard.ui.dashboard.labels import status_pixmap
from cbrn_dashboard.ui.infrastructure.labels import (
    basis_label,
    code_label,
    flag_labels,
    join_labels,
    kind_label,
    status_label,
    type_display,
)
from cbrn_dashboard.ui.shell.formatting import format_date, format_number
from cbrn_dashboard.ui.shell.widgets import Column, ModuleTableModel

__all__ = [
    "ASSET_STATUS_LOOK",
    "AssetTableRow",
    "AssetsModel",
    "AvailabilityModel",
    "AvailabilityRow",
    "HistoryModel",
    "HistoryRow",
    "TypesModel",
    "interval_text",
]

#: A missing value in a cell (data, not a translatable text).
NOT_RECORDED = "-"

#: The icon shape and palette colour of an asset status (D23): the look of the dashboard status
#: it matches, so one vocabulary of shapes and colours is used everywhere.
ASSET_STATUS_LOOK: dict[AssetStatus, IndicatorStatus] = {
    AssetStatus.OPERATIONAL: IndicatorStatus.OK,
    AssetStatus.DEGRADED: IndicatorStatus.WARNING,
    AssetStatus.OUT_OF_SERVICE: IndicatorStatus.CRITICAL,
    AssetStatus.UNKNOWN: IndicatorStatus.NO_DATA,
}


def _asset_status_icon(row: "AssetTableRow") -> QIcon | None:
    look = ASSET_STATUS_LOOK.get(row.row.status)
    return None if look is None else QIcon(status_pixmap(look.value))


def _date_text(value: date | None, lang: str) -> str:
    return NOT_RECORDED if value is None else format_date(value, lang)


def interval_text(days: int | None) -> str:
    """A maintenance interval: not set (``None``), no scheduled maintenance (0) or N days."""
    if days is None:
        return QCoreApplication.translate("Infrastructure", "Not set")
    if days == 0:
        return QCoreApplication.translate("Infrastructure", "No scheduled maintenance")
    return QCoreApplication.translate("Infrastructure", "%n day(s)", None, days)


def _type_text(asset_type: AssetTypeView | None, type_code: str, lang: str) -> str:
    if asset_type is None:
        return code_label(type_code)
    return type_display(asset_type, lang)


# --------------------------------------------------------------------------- the assets


@dataclass(frozen=True)
class AssetTableRow:
    """An asset as of the as-of date, with its stored record and its type (when known)."""

    row: AssetRow
    asset: AssetView | None
    asset_type: AssetTypeView | None


class AssetsModel(ModuleTableModel):
    """Assets sorted by type and tag: status, last maintenance, next due date and flags."""

    COLUMNS = (
        Column[Any](
            "tag",
            lambda: QCoreApplication.translate("Infrastructure", "Tag"),
            lambda row, lang: row.row.tag,
        ),
        Column[Any](
            "type",
            lambda: QCoreApplication.translate("Infrastructure", "Type"),
            lambda row, lang: _type_text(row.asset_type, row.row.type_code, lang),
        ),
        Column[Any](
            "status",
            lambda: QCoreApplication.translate("Infrastructure", "Status"),
            lambda row, lang: status_label(row.row.status.value),
            icon=_asset_status_icon,
        ),
        Column[Any](
            "last_maintenance",
            lambda: QCoreApplication.translate("Infrastructure", "Last maintenance"),
            lambda row, lang: _date_text(row.row.last_maintenance_on, lang),
        ),
        Column[Any](
            "next_due",
            lambda: QCoreApplication.translate("Infrastructure", "Next due"),
            lambda row, lang: _date_text(row.row.due_on, lang),
        ),
        Column[Any](
            "basis",
            lambda: QCoreApplication.translate("Infrastructure", "Schedule basis"),
            lambda row, lang: basis_label(row.row.basis.value),
        ),
        Column[Any](
            "flags",
            lambda: QCoreApplication.translate("Infrastructure", "Flags"),
            lambda row, lang: join_labels(flag_labels(row.row)),
        ),
    )


# --------------------------------------------------------------------------- availability


@dataclass(frozen=True)
class AvailabilityRow:
    """Assets of one type in service and available on the as-of date."""

    type_code: str
    asset_type: AssetTypeView | None
    available: int
    in_service: int


class AvailabilityModel(ModuleTableModel):
    """The availability summary per type (available is not free: no occupancy, A01)."""

    COLUMNS = (
        Column[Any](
            "type",
            lambda: QCoreApplication.translate("Infrastructure", "Type"),
            lambda row, lang: _type_text(row.asset_type, row.type_code, lang),
        ),
        Column[Any](
            "available",
            lambda: QCoreApplication.translate("Infrastructure", "Available"),
            lambda row, lang: format_number(row.available, lang),
            align_right=True,
        ),
        Column[Any](
            "in_service",
            lambda: QCoreApplication.translate("Infrastructure", "In service"),
            lambda row, lang: format_number(row.in_service, lang),
            align_right=True,
        ),
    )


# --------------------------------------------------------------------------- history


@dataclass(frozen=True)
class HistoryRow:
    """One entry of the history of an asset: a status event or a maintenance record."""

    on: date
    status: StatusEventView | None = None
    maintenance: MaintenanceView | None = None


def _history_entry(row: HistoryRow) -> str:
    if row.status is not None:
        return QCoreApplication.translate("Infrastructure", "Status change")
    return QCoreApplication.translate("Infrastructure", "Maintenance")


def _history_details(row: HistoryRow, lang: str) -> str:
    if row.status is not None:
        return status_label(row.status.status.value)
    record = row.maintenance
    if record is None:
        return ""
    kind = kind_label(record.kind.value)
    if record.next_due_on is None:
        return kind
    return (
        QCoreApplication.translate("Infrastructure", "%1, next due %2")
        .replace("%1", kind)
        .replace("%2", format_date(record.next_due_on, lang))
    )


def _history_note(row: HistoryRow) -> str:
    event = row.status if row.status is not None else row.maintenance
    return "" if event is None else (event.note or "")


class HistoryModel(ModuleTableModel):
    """Status events and maintenance records of the selected asset, by date."""

    COLUMNS = (
        Column[Any](
            "date",
            lambda: QCoreApplication.translate("Infrastructure", "Date"),
            lambda row, lang: format_date(row.on, lang),
        ),
        Column[Any](
            "entry",
            lambda: QCoreApplication.translate("Infrastructure", "Entry"),
            lambda row, lang: _history_entry(row),
        ),
        Column[Any](
            "details",
            lambda: QCoreApplication.translate("Infrastructure", "Details"),
            lambda row, lang: _history_details(row, lang),
        ),
        Column[Any](
            "note",
            lambda: QCoreApplication.translate("Infrastructure", "Note"),
            lambda row, lang: _history_note(row),
        ),
    )


# --------------------------------------------------------------------------- asset types


class TypesModel(ModuleTableModel):
    """The asset types (including inactive and built-in ones) for the settings section."""

    COLUMNS = (
        Column[Any](
            "code",
            lambda: QCoreApplication.translate("Infrastructure", "Code"),
            lambda row, lang: row.code,
        ),
        Column[Any](
            "name",
            lambda: QCoreApplication.translate("Infrastructure", "Name"),
            lambda row, lang: type_display(row, lang),
        ),
        Column[Any](
            "interval",
            lambda: QCoreApplication.translate("Infrastructure", "Default interval"),
            lambda row, lang: interval_text(row.default_maintenance_interval_days),
        ),
        Column[Any](
            "origin",
            lambda: QCoreApplication.translate("Infrastructure", "Origin"),
            lambda row, lang: (
                QCoreApplication.translate("Infrastructure", "Built-in")
                if row.built_in
                else QCoreApplication.translate("Infrastructure", "User-defined")
            ),
        ),
        Column[Any](
            "status",
            lambda: QCoreApplication.translate("Infrastructure", "Status"),
            lambda row, lang: (
                QCoreApplication.translate("Infrastructure", "Active")
                if row.active
                else QCoreApplication.translate("Infrastructure", "Inactive")
            ),
        ),
    )
