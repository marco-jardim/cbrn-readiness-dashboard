# SPDX-License-Identifier: GPL-3.0-or-later
"""Text formatting and the table alternative of the dashboard charts (PLAN.md T6.5, D08, D15).

Every chart offers the same numbers as a table (D08, K09): :class:`ChartTableModel` holds the
category names and the raw series values of a chart and formats the cells for the current
language, with the shared formatting functions. Headers are translated on every ``headerData``
call. The raw value of a cell (``None`` when not recorded) is also served under
``Qt.ItemDataRole.UserRole``, so a test or a caller can compare numbers instead of text.

Budget amounts of a chart are MAJOR units as floats (display only, see ``services/dashboard.py``);
they are turned back into whole minor units here, exactly, before the money formatter is used.
"""

from collections.abc import Callable, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)

from cbrn_dashboard.domain.budget import currency_decimals, is_valid_currency
from cbrn_dashboard.i18n import DEFAULT_LANGUAGE
from cbrn_dashboard.ui.budget.models import money_text
from cbrn_dashboard.ui.shell.formatting import format_number

__all__ = [
    "NOT_RECORDED",
    "ChartTableModel",
    "SeriesColumn",
    "ValueFormatter",
    "count_text",
    "major_money_text",
]

#: A missing value in a cell (data, not a translatable text).
NOT_RECORDED = "-"

_NO_INDEX = QModelIndex()

type ValueFormatter = Callable[[float | None, str], str]
type SeriesColumn = tuple[Callable[[], str], tuple[float | None, ...]]


def count_text(value: float | None, lang: str) -> str:
    """A count (or any plain number) in ``lang``; whole numbers have no decimals."""
    if value is None:
        return NOT_RECORDED
    return format_number(value, lang, decimals=0 if float(value).is_integer() else None)


def major_money_text(value: float | None, currency: str, lang: str) -> str:
    """An amount given in MAJOR units (a float, display only) as money of ``currency``."""
    if value is None:
        return NOT_RECORDED
    if not is_valid_currency(currency):
        return f"{count_text(value, lang)} {currency}"
    exact = Decimal(repr(value)).scaleb(currency_decimals(currency))
    return money_text(int(exact.to_integral_value(ROUND_HALF_UP)), currency, lang)


class ChartTableModel(QAbstractTableModel):
    """The numbers of one chart as a table: a category column and one column per series."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._category_header: Callable[[], str] = lambda: ""
        self._categories: list[str] = []
        self._headers: list[Callable[[], str]] = []
        self._values: list[tuple[float | None, ...]] = []
        self._format: ValueFormatter = count_text
        self._lang = DEFAULT_LANGUAGE

    # ----- content

    def set_content(
        self,
        category_header: Callable[[], str],
        categories: Sequence[str],
        series: Sequence[SeriesColumn],
        formatter: ValueFormatter,
    ) -> None:
        """Replace the table: ``categories`` are display names, ``series`` pairs of
        (header function, raw values)."""
        self.beginResetModel()
        self._category_header = category_header
        self._categories = list(categories)
        self._headers = [header for header, _values in series]
        self._values = [values for _header, values in series]
        self._format = formatter
        self.endResetModel()

    def set_language(self, lang: str) -> None:
        """Format the cells for ``lang`` and refresh headers and cells."""
        self._lang = lang
        columns = self.columnCount()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, columns - 1)
        if self._categories:
            last = self.index(len(self._categories) - 1, columns - 1)
            self.dataChanged.emit(self.index(0, 0), last)

    def categories(self) -> tuple[str, ...]:
        """The category names as shown in the first column."""
        return tuple(self._categories)

    def values(self) -> tuple[tuple[float | None, ...], ...]:
        """The raw values, one tuple per series (``None``: not recorded)."""
        return tuple(self._values)

    # ----- the Qt model

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _NO_INDEX) -> int:
        return 0 if parent.isValid() else len(self._categories)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _NO_INDEX) -> int:
        return 0 if parent.isValid() else 1 + len(self._values)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        row, column = index.row(), index.column()
        if not index.isValid() or not 0 <= row < len(self._categories):
            return None
        if column == 0:
            return self._categories[row] if role == Qt.ItemDataRole.DisplayRole else None
        if not 0 < column <= len(self._values):
            return None
        value = self._values[column - 1][row]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._format(value, self._lang)
        if role == Qt.ItemDataRole.UserRole:
            return value
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == 0:
                return self._category_header()
            if 0 < section <= len(self._headers):
                return self._headers[section - 1]()
        return super().headerData(section, orientation, role)
