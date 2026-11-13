# SPDX-License-Identifier: GPL-3.0-or-later
"""Small building blocks shared by every module page (PLAN.md T4.5, section 6, D20).

* language helpers: :func:`current_language`, :func:`follow_language`, :func:`label_for`;
* errors: :func:`show_service_error`, :func:`guarded`, :func:`apply_change` (a service call is run,
  a ``ServiceError`` is shown translated, and the pages are told when data changed);
* tables: :class:`Column` and :class:`ModuleTableModel` (headers are translated on EVERY
  ``headerData`` call; cells are formatted for the current language);
* dialogs: :class:`FormDialog` (OK/Cancel, ``submit()`` hook, ``retranslate()`` hook);
* edit actions: :class:`EditAction` / :func:`make_edit_action` (disabled in read-only mode) and
  :func:`action_row`, :func:`make_table_view`, :func:`mark_data`.

Widgets built on these re-apply their texts in ONE ``retranslate()`` called from ``__init__`` and
from ``changeEvent`` on ``QEvent.Type.LanguageChange``.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QCoreApplication,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
)
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.i18n import DEFAULT_LANGUAGE
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.ui.shell.context import AppContext

__all__ = [
    "DATA_PROPERTY",
    "Column",
    "EditAction",
    "FormDialog",
    "ModuleTableModel",
    "action_row",
    "apply_change",
    "current_language",
    "follow_language",
    "guarded",
    "label_for",
    "make_edit_action",
    "make_table_view",
    "mark_data",
    "show_service_error",
]

#: Dynamic property that exempts a widget's own texts from the pseudo-locale walk (user data).
DATA_PROPERTY = "i18nData"

_NO_INDEX = QModelIndex()


# --------------------------------------------------------------------------- language


def current_language(context: AppContext) -> str:
    """The catalogue code of the current UI language (``pt_BR`` while none is set)."""
    return context.translator_manager.current_language or DEFAULT_LANGUAGE


def follow_language(context: AppContext, retranslate: Callable[[], None]) -> None:
    """Also call ``retranslate`` when the manager announces a language (it is idempotent)."""
    context.translator_manager.language_changed.connect(retranslate)


def label_for(mapping: Mapping[str, Callable[[], str]], code: str) -> str:
    """The translated label of ``code``; the code itself when unknown. Never raises."""
    label = mapping.get(code)
    return code if label is None else label()


def mark_data(obj: QObject) -> None:
    """Flag a widget (or action) whose texts are user data, not UI text."""
    obj.setProperty(DATA_PROPERTY, True)


# --------------------------------------------------------------------------- errors


def show_service_error(
    context: AppContext,
    parent: QWidget | None,
    error: ServiceError,
    labels: Callable[[str], str],
) -> None:
    """Show the translated message of ``error`` through the prompts interface."""
    title = QCoreApplication.translate("Shell", "Cannot save")
    context.prompts.warning(parent, title, labels(error.code))


def guarded[T](
    context: AppContext,
    parent: QWidget | None,
    labels: Callable[[str], str],
    action: Callable[[], T],
) -> T | None:
    """Run a service call; a ``ServiceError`` is presented and gives ``None``, others propagate."""
    try:
        return action()
    except ServiceError as error:
        show_service_error(context, parent, error, labels)
        return None


def apply_change(
    context: AppContext,
    parent: QWidget | None,
    labels: Callable[[str], str],
    action: Callable[[], object],
) -> bool:
    """Run a service write; on success tell the pages (``data_changed``). ``False`` on an error."""

    def run() -> bool:
        action()
        return True

    if guarded(context, parent, labels, run) is True:
        context.notify_data_changed()
        return True
    return False


# --------------------------------------------------------------------------- tables


@dataclass(frozen=True)
class Column[Row]:
    """One table column: ``header()`` is the translated title, ``value(row, lang)`` a cell text."""

    key: str
    header: Callable[[], str]
    value: Callable[[Row, str], str]
    align_right: bool = False


class ModuleTableModel(QAbstractTableModel):
    """Read-only table model over a list of rows; subclasses declare ``COLUMNS``."""

    COLUMNS: tuple[Column[Any], ...] = ()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[Any] = []
        self._lang = DEFAULT_LANGUAGE

    def set_language(self, lang: str) -> None:
        """Format the cells for ``lang`` and refresh headers and cells."""
        self._lang = lang
        self.refresh_language()

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rows(self) -> list[Any]:
        return list(self._rows)

    def row_at(self, index: QModelIndex | QPersistentModelIndex) -> Any | None:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        return self._rows[index.row()]

    def selected_row(self, view: QAbstractItemView) -> Any | None:
        """The row selected in ``view`` (single selection), or ``None``."""
        selection = view.selectionModel()
        if selection is None:
            return None
        indexes = selection.selectedRows()
        return self.row_at(indexes[0]) if indexes else None

    def refresh_language(self) -> None:
        """Tell the views that headers and cell texts (dates, numbers) must be read again."""
        columns = len(self.COLUMNS)
        if columns:
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, columns - 1)
        if self._rows and columns:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._rows) - 1, columns - 1))

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _NO_INDEX) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _NO_INDEX) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        row = self.row_at(index)
        if row is None or not 0 <= index.column() < len(self.COLUMNS):
            return None
        column = self.COLUMNS[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return column.value(row, self._lang)
        if role == Qt.ItemDataRole.TextAlignmentRole and column.align_right:
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < len(self.COLUMNS)
        ):
            return self.COLUMNS[section].header()
        return super().headerData(section, orientation, role)


def make_table_view(model: QAbstractTableModel, parent: QWidget) -> QTableView:
    """A read-only table with whole-row single selection, no sorting and no row numbers."""
    view = QTableView(parent)
    view.setModel(model)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setSortingEnabled(False)
    view.verticalHeader().setVisible(False)
    view.horizontalHeader().setStretchLastSection(True)
    return view


# --------------------------------------------------------------------------- edit actions


class EditAction(QAction):
    """An action that edits data; its text is re-applied by :meth:`retranslate`."""

    def __init__(self, parent: QObject, text_fn: Callable[[], str]) -> None:
        super().__init__(parent)
        self._text_fn = text_fn
        self.retranslate()

    def retranslate(self) -> None:
        self.setText(self._text_fn())


def make_edit_action(
    context: AppContext,
    parent: QObject,
    text_fn: Callable[[], str],
    slot: Callable[[], None],
) -> EditAction:
    """An action registered with the context, so read-only mode disables it."""
    action = EditAction(parent, text_fn)
    action.triggered.connect(slot)
    context.register_edit_action(action)
    return action


def action_row(actions: Sequence[QAction], parent: QWidget) -> QHBoxLayout:
    """A row of text buttons, one per action (they follow the action's text and enabled state)."""
    row = QHBoxLayout()
    for action in actions:
        button = QToolButton(parent)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setDefaultAction(action)
        row.addWidget(button)
    row.addStretch(1)
    return row


# --------------------------------------------------------------------------- dialogs


class FormDialog(QDialog):
    """A dialog with a form, OK/Cancel and a ``submit()`` hook.

    Subclasses add rows with :meth:`add_field`, override :meth:`retranslate` (calling the parent
    version first) and :meth:`submit`, which returns ``False`` after showing an error so the dialog
    stays open. Subclasses call ``self.retranslate()`` at the end of their ``__init__``.
    """

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._fields: list[tuple[QLabel, Callable[[], str]]] = []
        root = QVBoxLayout(self)
        self.form = QFormLayout()
        root.addLayout(self.form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        root.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        follow_language(context, self.retranslate)

    @property
    def language(self) -> str:
        return current_language(self.context)

    def add_field(self, label_fn: Callable[[], str], widget: QWidget) -> QLabel:
        """Add a form row; the label text comes from ``label_fn`` and follows the language."""
        label = QLabel(self)
        label.setText(label_fn())
        label.setBuddy(widget)
        self._fields.append((label, label_fn))
        self.form.addRow(label, widget)
        return label

    def retranslate(self) -> None:
        """Re-apply the field labels; subclasses add their own texts after calling this."""
        for label, label_fn in self._fields:
            label.setText(label_fn())

    def submit(self) -> bool:
        """Store the input; ``False`` keeps the dialog open (the error was already shown)."""
        return True

    def accept(self) -> None:
        if self.submit():
            super().accept()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
