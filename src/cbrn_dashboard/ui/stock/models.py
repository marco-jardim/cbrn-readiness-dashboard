# SPDX-License-Identifier: GPL-3.0-or-later
"""Table models of the stock UI: lots, movements, summary, expiry schedule, item types (T11.9).

Headers are translated on every ``headerData`` call; dates, numbers and money are formatted for the
current language with the shared formatting functions. A status is TEXT plus an icon whose shape
and palette colour belong to it (D23): a lot status uses the look of the indicator status it
matches (:data:`LOT_STATUS_LOOK`), and so does the "below the minimum" column. Lot codes,
references, notes and user-defined type labels in cells are data.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QIcon

from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.domain.stock import (
    LotRow,
    LotStatus,
    ScheduleBucket,
    ScheduleBucketKind,
    TypeSummary,
)
from cbrn_dashboard.services.stock import MovementView, StockTypeView
from cbrn_dashboard.ui.budget.models import money_text
from cbrn_dashboard.ui.dashboard.labels import status_pixmap
from cbrn_dashboard.ui.shell.formatting import format_date, format_number, locale_for, to_qdate
from cbrn_dashboard.ui.shell.widgets import Column, ModuleTableModel
from cbrn_dashboard.ui.stock.labels import (
    category_label,
    join_texts,
    kind_label,
    lot_status_label,
    stock_type_display,
    type_name,
)

__all__ = [
    "LOT_STATUS_LOOK",
    "LotTableRow",
    "LotsModel",
    "MovementsModel",
    "ScheduleModel",
    "ScheduleRow",
    "StockTypesModel",
    "SummaryModel",
    "SummaryRow",
    "below_minimum_look",
    "below_minimum_text",
    "minimum_text",
    "month_text",
    "period_text",
    "signed_text",
]

#: A missing value in a cell (data, not a translatable text).
NOT_RECORDED = "-"

#: The icon shape and palette colour of a lot status (D23): the look of the dashboard status it
#: matches, so one vocabulary of shapes and colours is used everywhere.
LOT_STATUS_LOOK: dict[LotStatus, IndicatorStatus] = {
    LotStatus.VALID: IndicatorStatus.OK,
    LotStatus.EXPIRING: IndicatorStatus.WARNING,
    LotStatus.EXPIRED: IndicatorStatus.CRITICAL,
    LotStatus.EMPTY: IndicatorStatus.NO_TARGET,
    LotStatus.NOT_RECEIVED: IndicatorStatus.NO_DATA,
}

#: The statuses whose quantity counts as valid stock (an expiring lot is still valid).
_VALID_STATUSES = frozenset({LotStatus.VALID, LotStatus.EXPIRING})


def _icon(look: IndicatorStatus) -> QIcon:
    return QIcon(status_pixmap(look.value))


def _lot_status_icon(status: LotStatus) -> QIcon | None:
    look = LOT_STATUS_LOOK.get(status)
    return None if look is None else _icon(look)


def below_minimum_look(below: bool | None) -> IndicatorStatus:
    """The look of the "below minimum" column: below is critical, not below OK, none no target."""
    if below is None:
        return IndicatorStatus.NO_TARGET
    return IndicatorStatus.CRITICAL if below else IndicatorStatus.OK


def below_minimum_text(below: bool | None) -> str:
    """The text of the "below the minimum" column (never colour alone, D23)."""
    if below is None:
        return QCoreApplication.translate("Stock", "Not set")
    if below:
        return QCoreApplication.translate("Stock", "Below the minimum")
    return QCoreApplication.translate("Stock", "At or above the minimum")


def minimum_text(minimum: int | None, lang: str) -> str:
    """A minimum stock: "Not set" (``None``) or the number (0 is a minimum that is never below)."""
    if minimum is None:
        return QCoreApplication.translate("Stock", "Not set")
    return format_number(minimum, lang)


def signed_text(value: int, lang: str) -> str:
    """A signed quantity: ``+50`` for an inflow, ``-5`` for an outflow (0 has no sign)."""
    if value > 0:
        return "+" + format_number(value, lang)
    if value < 0:
        return "-" + format_number(-value, lang)
    return format_number(0, lang)


def month_text(month: date, lang: str) -> str:
    """The month and year of ``month`` in the language, capitalised ("March 2026").

    The month name comes from the locale data of Qt. T11.11 may replace it with a shared
    ``format_month`` without changing the models.
    """
    text = locale_for(lang).toString(to_qdate(month), "MMMM yyyy")
    return text[:1].upper() + text[1:]


def period_text(kind: ScheduleBucketKind, month: date | None, lang: str) -> str:
    """The period of an expiry-schedule bucket."""
    if kind is ScheduleBucketKind.EXPIRED:
        return QCoreApplication.translate("Stock", "Expired (still in stock)")
    if kind is ScheduleBucketKind.LATER:
        return QCoreApplication.translate("Stock", "Later")
    if kind is ScheduleBucketKind.NO_EXPIRY:
        return QCoreApplication.translate("Stock", "No expiry date")
    return NOT_RECORDED if month is None else month_text(month, lang)


def _date_text(value: date | None, lang: str) -> str:
    return NOT_RECORDED if value is None else format_date(value, lang)


def _expiry_text(value: date | None, lang: str) -> str:
    if value is None:
        return QCoreApplication.translate("Stock", "No expiry date")
    return format_date(value, lang)


def _price_text(minor: int | None, currency: str | None, lang: str) -> str:
    if minor is None or currency is None:
        return NOT_RECORDED
    return money_text(minor, currency, lang)


# --------------------------------------------------------------------------- the lots


@dataclass(frozen=True)
class LotTableRow:
    """A lot as read on the as-of date, with the types (to name its type in the language)."""

    row: LotRow
    types: Mapping[str, StockTypeView]


class LotsModel(ModuleTableModel):
    """The lots by category, type and expiry: quantity, status, days to expiry, price and value."""

    COLUMNS = (
        Column[Any](
            "type",
            lambda: QCoreApplication.translate("Stock", "Type"),
            lambda row, lang: type_name(row.row.type_code, lang, row.types),
        ),
        Column[Any](
            "lot",
            lambda: QCoreApplication.translate("Stock", "Lot"),
            lambda row, lang: row.row.lot_code,
        ),
        Column[Any](
            "received",
            lambda: QCoreApplication.translate("Stock", "Received"),
            lambda row, lang: _date_text(row.row.received_on, lang),
        ),
        Column[Any](
            "expiry",
            lambda: QCoreApplication.translate("Stock", "Expiry"),
            lambda row, lang: _expiry_text(row.row.expires_on, lang),
        ),
        Column[Any](
            "on_hand",
            lambda: QCoreApplication.translate("Stock", "On hand"),
            lambda row, lang: format_number(row.row.on_hand, lang),
            align_right=True,
        ),
        Column[Any](
            "status",
            lambda: QCoreApplication.translate("Stock", "Status"),
            lambda row, lang: lot_status_label(row.row.status.value),
            icon=lambda row: _lot_status_icon(row.row.status),
        ),
        Column[Any](
            "days_to_expiry",
            lambda: QCoreApplication.translate("Stock", "Days to expiry"),
            lambda row, lang: (
                NOT_RECORDED
                if row.row.days_to_expiry is None
                else format_number(row.row.days_to_expiry, lang)
            ),
            align_right=True,
        ),
        Column[Any](
            "unit_price",
            lambda: QCoreApplication.translate("Stock", "Unit price"),
            lambda row, lang: _price_text(row.row.unit_price_minor, row.row.currency, lang),
            align_right=True,
        ),
        Column[Any](
            "value",
            lambda: QCoreApplication.translate("Stock", "Value"),
            lambda row, lang: _price_text(row.row.value_minor, row.row.currency, lang),
            align_right=True,
        ),
    )

    def set_lots(self, rows: Sequence[LotRow], types: Mapping[str, StockTypeView]) -> None:
        self.set_rows([LotTableRow(row, types) for row in rows])


# --------------------------------------------------------------------------- the movements


class MovementsModel(ModuleTableModel):
    """The movements of one lot: date, kind, signed quantity, balance after, reference, note."""

    COLUMNS = (
        Column[Any](
            "date",
            lambda: QCoreApplication.translate("Stock", "Date"),
            lambda row, lang: format_date(row.moved_on, lang),
        ),
        Column[Any](
            "kind",
            lambda: QCoreApplication.translate("Stock", "Kind"),
            lambda row, lang: kind_label(row.kind.value),
        ),
        Column[Any](
            "quantity",
            lambda: QCoreApplication.translate("Stock", "Quantity"),
            lambda row, lang: signed_text(row.signed_quantity, lang),
            align_right=True,
        ),
        Column[Any](
            "balance_after",
            lambda: QCoreApplication.translate("Stock", "Balance after"),
            lambda row, lang: format_number(row.balance_after, lang),
            align_right=True,
        ),
        Column[Any](
            "reference",
            lambda: QCoreApplication.translate("Stock", "Reference"),
            lambda row, lang: row.reference,
        ),
        Column[Any](
            "note",
            lambda: QCoreApplication.translate("Stock", "Note"),
            lambda row, lang: row.note or "",
        ),
    )

    def set_movements(self, movements: Iterable[MovementView]) -> None:
        self.set_rows(list(movements))


# --------------------------------------------------------------------------- the summary


@dataclass(frozen=True)
class SummaryRow:
    """One item type as read on the as-of date.

    ``valid_value`` holds the value of the valid lots per currency as sorted ``(currency, minor
    units)`` pairs: currencies are never added together (D15).
    """

    summary: TypeSummary
    types: Mapping[str, StockTypeView]
    valid_value: tuple[tuple[str, int], ...] = ()


def _valid_value_text(row: SummaryRow, lang: str) -> str:
    if not row.valid_value:
        return NOT_RECORDED
    return join_texts([money_text(minor, currency, lang) for currency, minor in row.valid_value])


class SummaryModel(ModuleTableModel):
    """The summary per item type: valid, expired and expiring quantities, minimum, value."""

    COLUMNS = (
        Column[Any](
            "type",
            lambda: QCoreApplication.translate("Stock", "Type"),
            lambda row, lang: type_name(row.summary.type_code, lang, row.types),
        ),
        Column[Any](
            "category",
            lambda: QCoreApplication.translate("Stock", "Category"),
            lambda row, lang: category_label(row.summary.category.value),
        ),
        Column[Any](
            "valid",
            lambda: QCoreApplication.translate("Stock", "Valid"),
            lambda row, lang: format_number(row.summary.valid, lang),
            align_right=True,
        ),
        Column[Any](
            "expired",
            lambda: QCoreApplication.translate("Stock", "Expired in stock"),
            lambda row, lang: format_number(row.summary.expired_qty, lang),
            align_right=True,
        ),
        Column[Any](
            "expiring",
            lambda: QCoreApplication.translate("Stock", "Expiring soon"),
            lambda row, lang: format_number(row.summary.expiring_qty, lang),
            align_right=True,
        ),
        Column[Any](
            "minimum",
            lambda: QCoreApplication.translate("Stock", "Minimum"),
            lambda row, lang: minimum_text(row.summary.minimum, lang),
            align_right=True,
        ),
        Column[Any](
            "below_minimum",
            lambda: QCoreApplication.translate("Stock", "Below minimum"),
            lambda row, lang: below_minimum_text(row.summary.below_minimum),
            icon=lambda row: _icon(below_minimum_look(row.summary.below_minimum)),
        ),
        Column[Any](
            "valid_value",
            lambda: QCoreApplication.translate("Stock", "Value of valid stock"),
            _valid_value_text,
            align_right=True,
        ),
    )

    def set_summaries(
        self,
        summaries: Sequence[TypeSummary],
        lots: Iterable[LotRow],
        types: Mapping[str, StockTypeView],
    ) -> None:
        """Show ``summaries``; ``lots`` (rows of the same date) give the value of valid stock."""
        totals: dict[str, dict[str, int]] = {}
        for lot in lots:
            if lot.status not in _VALID_STATUSES or lot.value_minor is None or lot.currency is None:
                continue
            per_currency = totals.setdefault(lot.type_code, {})
            per_currency[lot.currency] = per_currency.get(lot.currency, 0) + lot.value_minor
        self.set_rows(
            [
                SummaryRow(
                    summary,
                    types,
                    tuple(sorted(totals.get(summary.type_code, {}).items())),
                )
                for summary in summaries
            ]
        )


# --------------------------------------------------------------------------- expiry schedule


@dataclass(frozen=True)
class ScheduleRow:
    """One lot of the expiry schedule with the period (bucket) it falls in."""

    kind: ScheduleBucketKind
    month: date | None
    lot: LotRow
    types: Mapping[str, StockTypeView]


class ScheduleModel(ModuleTableModel):
    """The lots with stock by period of expiry: period, type, lot, expiry, quantity, status."""

    COLUMNS = (
        Column[Any](
            "period",
            lambda: QCoreApplication.translate("Stock", "Period"),
            lambda row, lang: period_text(row.kind, row.month, lang),
        ),
        Column[Any](
            "type",
            lambda: QCoreApplication.translate("Stock", "Type"),
            lambda row, lang: type_name(row.lot.type_code, lang, row.types),
        ),
        Column[Any](
            "lot",
            lambda: QCoreApplication.translate("Stock", "Lot"),
            lambda row, lang: row.lot.lot_code,
        ),
        Column[Any](
            "expiry",
            lambda: QCoreApplication.translate("Stock", "Expiry"),
            lambda row, lang: _expiry_text(row.lot.expires_on, lang),
        ),
        Column[Any](
            "on_hand",
            lambda: QCoreApplication.translate("Stock", "On hand"),
            lambda row, lang: format_number(row.lot.on_hand, lang),
            align_right=True,
        ),
        Column[Any](
            "status",
            lambda: QCoreApplication.translate("Stock", "Status"),
            lambda row, lang: lot_status_label(row.lot.status.value),
            icon=lambda row: _lot_status_icon(row.lot.status),
        ),
    )

    def set_buckets(
        self, buckets: Iterable[ScheduleBucket], types: Mapping[str, StockTypeView]
    ) -> None:
        """One row per lot, bucket by bucket; a bucket without lots has no row."""
        self.set_rows(
            [
                ScheduleRow(bucket.kind, bucket.month, lot, types)
                for bucket in buckets
                for lot in bucket.lots
            ]
        )


# --------------------------------------------------------------------------- item types


class StockTypesModel(ModuleTableModel):
    """The item types (inactive and built-in ones too) for the settings section."""

    COLUMNS = (
        Column[Any](
            "code",
            lambda: QCoreApplication.translate("Stock", "Code"),
            lambda row, lang: row.code,
        ),
        Column[Any](
            "name",
            lambda: QCoreApplication.translate("Stock", "Name"),
            lambda row, lang: stock_type_display(row, lang),
        ),
        Column[Any](
            "category",
            lambda: QCoreApplication.translate("Stock", "Category"),
            lambda row, lang: category_label(row.category.value),
        ),
        Column[Any](
            "minimum",
            lambda: QCoreApplication.translate("Stock", "Minimum"),
            lambda row, lang: minimum_text(row.minimum_quantity, lang),
            align_right=True,
        ),
        Column[Any](
            "origin",
            lambda: QCoreApplication.translate("Stock", "Origin"),
            lambda row, lang: (
                QCoreApplication.translate("Stock", "Built-in")
                if row.built_in
                else QCoreApplication.translate("Stock", "User-defined")
            ),
        ),
        Column[Any](
            "status",
            lambda: QCoreApplication.translate("Stock", "Status"),
            lambda row, lang: (
                QCoreApplication.translate("Stock", "Active")
                if row.active
                else QCoreApplication.translate("Stock", "Inactive")
            ),
        ),
    )
