# SPDX-License-Identifier: GPL-3.0-or-later
"""The pseudo-locale walker (PLAN.md section 6, check 6; task T1.9).

With the pseudo catalogue installed, every translated text reads ``⟦<source text>⟧``. The walker
collects every VISIBLE, NON-DATA text of a widget tree and reports those that lack the markers:
a hard-coded string, or a text that was not re-applied on a language change.

What is looked at: window titles (windows, toolbars, dock widgets), ``QLabel`` texts, button,
check-box and radio texts, group-box titles, tab texts and tooltips, menu titles, ``QAction`` text,
tooltip and status tip, widget tooltips, status tips, accessible names and descriptions,
placeholder texts, spin-box prefix/suffix/special-value texts, the header texts of item views
(``model.headerData`` for every section, horizontal and vertical, when the header is shown) and
combo-box item texts.

Data exemptions, all explicit:

* a widget or action with the dynamic property ``i18nData`` set to true (its own texts only);
* the CELL contents of item views (data by definition);
* texts with no letters at all (numbers, dates, punctuation);
* the internals of ``QAbstractSpinBox`` and ``QCalendarWidget`` (their texts come from Qt and the
  locale, not from our catalogues) and the standard buttons of a ``QDialogButtonBox`` (translated
  by Qt's own ``qtbase`` catalogue, which the pseudo catalogue does not wrap).

"Visible" means "not explicitly hidden, and neither is any ancestor below the root". The root is
treated as visible (so an unshown dialog can be walked); the pages of a ``QStackedWidget`` or
``QTabWidget`` count as visible although only one is current, because the user can reach them.
Mnemonic ``&`` and shortcut suffixes after a tab character are stripped before checking.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractSpinBox,
    QCalendarWidget,
    QComboBox,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QGroupBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabBar,
    QTableView,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QToolButton,
    QTreeView,
    QWidget,
)

OPEN_MARK = "\u27e6"
CLOSE_MARK = "\u27e7"
DATA_PROPERTY = "i18nData"
MAX_HEADER_SECTIONS = 200

_TAG = re.compile(r"<[^>]*>")


@dataclass(frozen=True)
class TextItem:
    """One text found in the tree."""

    owner: str
    kind: str
    text: str

    @property
    def translated(self) -> bool:
        return OPEN_MARK in self.text and CLOSE_MARK in self.text

    def __str__(self) -> str:
        return f"{self.owner} [{self.kind}]: {self.text!r}"


def clean(text: str) -> str:
    """Strip rich-text tags, the shortcut suffix after a tab, and mnemonic ``&`` markers."""
    text = _TAG.sub("", text).split("\t", 1)[0]
    return text.replace("&&", "\x00").replace("&", "").replace("\x00", "&")


def has_letters(text: str) -> bool:
    return any(char.isalpha() for char in clean(text))


def _is_data(obj: QObject) -> bool:
    return bool(obj.property(DATA_PROPERTY))


def _describe(widget: QWidget, root: QWidget) -> str:
    names: list[str] = []
    node: QObject | None = widget
    while node is not None:
        names.append(f"{type(node).__name__}#{node.objectName()}")
        if node is root:
            break
        node = node.parent()
    return " > ".join(reversed(names))


def _is_visible(widget: QWidget, root: QWidget) -> bool:
    node: QWidget | None = widget
    while node is not None and node is not root:
        parent = node.parentWidget()
        # A widget placed with QToolBar.addWidget() stays hidden until the tool bar is first laid
        # out, i.e. until the window is shown; it is still part of what the user will see.
        if node.isHidden() and not isinstance(parent, QStackedWidget | QToolBar):
            return False
        node = parent
    return True


def _is_opaque(widget: QWidget) -> bool:
    return isinstance(widget, QAbstractSpinBox | QCalendarWidget)


def _walk_widgets(widget: QWidget, root: QWidget) -> Iterator[QWidget]:
    """``widget`` and its visible descendants, without the internals of opaque widgets."""
    if not _is_visible(widget, root):
        return
    yield widget
    if _is_opaque(widget):
        return
    for child in widget.children():
        if isinstance(child, QWidget) and not child.isWindow():
            yield from _walk_widgets(child, root)


def _header_texts(view: QAbstractItemView) -> Iterator[tuple[str, str]]:
    model = view.model()
    if model is None:
        return
    headers: list[tuple[QHeaderView, Qt.Orientation, int]] = []
    if isinstance(view, QTableView):
        headers.append((view.horizontalHeader(), Qt.Orientation.Horizontal, model.columnCount()))
        headers.append((view.verticalHeader(), Qt.Orientation.Vertical, model.rowCount()))
    elif isinstance(view, QTreeView):
        headers.append((view.header(), Qt.Orientation.Horizontal, model.columnCount()))
    for header, orientation, count in headers:
        if header.isHidden():
            continue
        for section in range(min(count, MAX_HEADER_SECTIONS)):
            value = model.headerData(section, orientation, Qt.ItemDataRole.DisplayRole)
            if isinstance(value, str):
                name = "horizontal" if orientation == Qt.Orientation.Horizontal else "vertical"
                yield f"header {name} {section}", value


def _widget_texts(widget: QWidget) -> Iterator[tuple[str, str]]:
    """``(kind, text)`` pairs of one widget (never of its children)."""
    if widget.isWindow() or isinstance(widget, QToolBar | QDockWidget):
        yield "window title", widget.windowTitle()
    yield "tooltip", widget.toolTip()
    yield "status tip", widget.statusTip()
    yield "accessible name", widget.accessibleName()
    yield "accessible description", widget.accessibleDescription()
    if isinstance(widget, QLabel):
        yield "label", widget.text()
    if isinstance(widget, QAbstractButton):
        parent = widget.parentWidget()
        standard = isinstance(parent, QDialogButtonBox) and (
            parent.standardButton(widget) != QDialogButtonBox.StandardButton.NoButton
        )
        if not standard:
            yield "button", widget.text()
    if isinstance(widget, QGroupBox):
        yield "group box", widget.title()
    is_free_tab_bar = isinstance(widget, QTabBar) and not isinstance(
        widget.parentWidget(), QTabWidget
    )
    if isinstance(widget, QTabWidget | QTabBar) and (
        isinstance(widget, QTabWidget) or is_free_tab_bar
    ):
        for index in range(widget.count()):
            yield f"tab {index}", widget.tabText(index)
            yield f"tab tooltip {index}", widget.tabToolTip(index)
    if isinstance(widget, QLineEdit | QTextEdit | QPlainTextEdit):
        yield "placeholder", widget.placeholderText()
    if isinstance(widget, QComboBox):
        yield "placeholder", widget.placeholderText()
        for index in range(widget.count()):
            yield f"combo item {index}", widget.itemText(index)
    if isinstance(widget, QSpinBox | QDoubleSpinBox):
        yield "prefix", widget.prefix()
        yield "suffix", widget.suffix()
        yield "special value", widget.specialValueText()
    if isinstance(widget, QAbstractItemView):
        yield from _header_texts(widget)


def _action_texts(action: QAction, seen: set[int]) -> Iterator[tuple[str, str]]:
    if id(action) in seen or action.isSeparator() or _is_data(action):
        return
    seen.add(id(action))
    yield "action text", action.text()
    yield "action tooltip", action.toolTip()
    yield "action status tip", action.statusTip()
    menu = action.menu()
    if menu is not None:
        yield "menu title", menu.title()
        for child in menu.actions():
            yield from _action_texts(child, seen)


def _menus_of(widget: QWidget) -> Iterator[QMenu]:
    if isinstance(widget, QPushButton | QToolButton):
        menu = widget.menu()
        if menu is not None:
            yield menu


def collect_texts(root: QWidget) -> list[TextItem]:
    """Every visible non-data text of the tree under ``root`` (translated or not)."""
    found: list[TextItem] = []
    seen_actions: set[int] = set()
    for widget in _walk_widgets(root, root):
        if _is_data(widget):
            continue
        owner = _describe(widget, root)
        for kind, text in _widget_texts(widget):
            found.append(TextItem(owner, kind, text))
        for action in widget.actions():
            for kind, text in _action_texts(action, seen_actions):
                found.append(TextItem(owner, kind, text))
        for menu in _menus_of(widget):
            for action in menu.actions():
                for kind, text in _action_texts(action, seen_actions):
                    found.append(TextItem(owner, kind, text))
    return [item for item in found if has_letters(item.text)]


def find_untranslated(root: QWidget) -> list[TextItem]:
    """The visible non-data texts under ``root`` that lack the ``⟦ ⟧`` markers."""
    return [item for item in collect_texts(root) if not item.translated]


def assert_fully_translated(root: QWidget) -> None:
    """Fail with a readable list of object names and texts when something is not translated."""
    missing = find_untranslated(root)
    if missing:
        lines = "\n".join(f"  {item}" for item in missing)
        msg = f"{len(missing)} visible text(s) without the pseudo-locale markers:\n{lines}"
        raise AssertionError(msg)
