# SPDX-License-Identifier: GPL-3.0-or-later
"""Accessibility and usability walk (PLAN.md task T10.4, D23, section 6).

The application is started in demo mode (so every table and tile has content) and the walk covers
every registered page, every settings section and every dialog of the dialog registry, the same
way ``test_no_hardcoded_strings.py`` does. It asserts that

* every interactive widget has an accessible name, a buddy label or a text of its own, and can be
  reached with the Tab key, in the order the layouts show it;
* every status display (tile, alert, asset status, certificate status) has a text, an icon of its
  own shape and a colour of the colour-blind-safe palette;
* every menu action has a mnemonic or a shortcut, and no shortcut of a window is used twice;
* the window has a minimum size and fonts are never fixed in pixels (so the OS font scale and the
  high-DPI scale are respected), and every page and dialog opens at ``QT_SCALE_FACTOR=2`` without
  a Qt warning (checked in a child process, see ``_scale_probe.py``).

A widget that legitimately breaks a rule is named in an explicit, commented exemption below; the
rule itself is not weakened. What only a person can judge (a real screen reader, a real display
scale, the feel of the tab order) is listed in the task report, not here.
"""

import json
import os
import re
import subprocess
import sys
import tomllib
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QFrame,
    QGraphicsView,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QSlider,
    QTabBar,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)
from pytestqt.qtbot import QtBot

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.domain.infrastructure import AssetStatus, MaintenanceKind
from cbrn_dashboard.domain.personnel import CertStatus
from cbrn_dashboard.services.infrastructure import MaintenanceView, StatusEventView
from cbrn_dashboard.ui.alerts.labels import severity_icon
from cbrn_dashboard.ui.dashboard.labels import STATUS_COLOURS, status_pixmap
from cbrn_dashboard.ui.dashboard.page import DashboardPage
from cbrn_dashboard.ui.infrastructure.models import ASSET_STATUS_LOOK, HistoryModel, HistoryRow
from cbrn_dashboard.ui.personnel.models import CERT_STATUS_LOOK
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.banners import BannerArea, BannerCode
from cbrn_dashboard.ui.shell.charts import PALETTE
from cbrn_dashboard.ui.shell.main_window import MINIMUM_HEIGHT, MINIMUM_WIDTH, MainWindow
from cbrn_dashboard.ui.shell.widgets import ModuleTableModel, apply_tab_order, layout_tab_order
from tests.ui._fakes import expect_handle
from tests.ui._walk import describe, has_letters, visible_widgets
from tests.ui.conftest import StartApp

pytestmark = pytest.mark.ui

REPO_ROOT = Path(__file__).resolve().parents[2]
CLOCK = FixedClock.at("2026-03-05T12:00:00Z")

# --------------------------------------------------------------------------- the rules

#: The widgets a person operates (every one of them must be named and reachable by Tab).
INTERACTIVE = (
    QAbstractButton,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QTextEdit,
    QPlainTextEdit,
    QAbstractItemView,
    QGraphicsView,  # the chart view
    QSlider,
    QTabBar,
)

#: The focus policies that put a widget in the Tab chain.
TAB_POLICIES = (
    Qt.FocusPolicy.TabFocus,
    Qt.FocusPolicy.StrongFocus,
    Qt.FocusPolicy.WheelFocus,
)

_MNEMONIC = re.compile(r"&[^&\s]")
_PIXEL_FONT = re.compile(r"font(-size)?\s*:[^;}]*px")

type Rule = Callable[[QWidget], list[str]]


def is_internal(widget: QWidget) -> bool:
    """A part of a Qt compound widget (a combo box's editor, a table's corner button, the scroll
    buttons of a tab bar, the clear button of a line edit): its owner is what a person operates
    and what must be named."""
    parent = widget.parentWidget()
    return isinstance(
        parent,
        QAbstractSpinBox | QComboBox | QTabBar | QHeaderView | QAbstractScrollArea | QLineEdit,
    )


def buddies_of(root: QWidget) -> set[QWidget]:
    """The widgets named by a label with a text: ``QLabel.setBuddy`` points at them."""
    found: set[QWidget] = set()
    for label in root.findChildren(QLabel):
        buddy = label.buddy()
        if buddy is not None and has_letters(label.text()):
            found.add(buddy)
    return found


def is_named(widget: QWidget, buddies: set[QWidget]) -> bool:
    """An accessible name, a buddy label, or a text of its own (a button, the tabs of a tab bar)."""
    if has_letters(widget.accessibleName()) or widget in buddies:
        return True
    if isinstance(widget, QAbstractButton):
        return has_letters(widget.text())
    if isinstance(widget, QTabBar):
        titles = [widget.tabText(index) for index in range(widget.count())]
        return bool(titles) and all(has_letters(title) for title in titles)
    return False


def operated_widgets(root: QWidget) -> list[QWidget]:
    """The visible interactive widgets of ``root`` (without the internals of Qt widgets).

    Exempt on purpose: ``QScrollArea`` and the plain containers. A scroll area takes the focus only
    to scroll; what it holds is what a person operates and is checked here.
    """
    return [
        widget
        for widget in visible_widgets(root)
        if isinstance(widget, INTERACTIVE) and not is_internal(widget)
    ]


def unnamed_widgets(root: QWidget) -> list[str]:
    buddies = buddies_of(root)
    return [
        describe(widget, root) for widget in operated_widgets(root) if not is_named(widget, buddies)
    ]


def not_tab_reachable(root: QWidget) -> list[str]:
    return [
        describe(widget, root)
        for widget in operated_widgets(root)
        if widget.focusPolicy() not in TAB_POLICIES
    ]


def unexplained_icons(root: QWidget) -> list[str]:
    """Labels that show only a picture and have neither a name nor a text label beside them."""
    found: list[str] = []
    for widget in visible_widgets(root):
        if not isinstance(widget, QLabel) or widget.pixmap().isNull() or has_letters(widget.text()):
            continue
        parent = widget.parentWidget()
        siblings: list[QLabel] = []
        if parent is not None:
            siblings = parent.findChildren(
                QLabel, options=Qt.FindChildOption.FindDirectChildrenOnly
            )
        beside = any(has_letters(other.text()) for other in siblings if other is not widget)
        if not has_letters(widget.accessibleName()) and not beside:
            found.append(describe(widget, root))
    return found


def mnemonic_of(text: str) -> str | None:
    """The mnemonic letter of an action or button text (lower case), or ``None``."""
    match = _MNEMONIC.search(text.replace("&&", ""))
    return None if match is None else match.group(0)[1].lower()


def has_mnemonic(text: str) -> bool:
    return mnemonic_of(text) is not None


def menu_actions(menu: QMenu) -> Iterator[QAction]:
    """The leaf actions of a menu (sub-menus are followed, separators skipped)."""
    for action in menu.actions():
        if action.isSeparator():
            continue
        submenu = action.menu()
        if isinstance(submenu, QMenu):  # the stubs type ``QAction.menu()`` as a ``QObject``
            yield from menu_actions(submenu)
        else:
            yield action


def top_menus(window: MainWindow) -> list[QMenu]:
    menus: list[QMenu] = []
    for action in window.menuBar().actions():
        menu = action.menu()
        if isinstance(menu, QMenu):
            menus.append(menu)
    return menus


def actions_without_access(window: MainWindow) -> list[str]:
    """Menu and toolbar actions that have neither a mnemonic nor a shortcut."""
    found: list[str] = []
    for menu in top_menus(window):
        if not has_mnemonic(menu.title()):
            found.append(f"menu {menu.title()!r}")
        for action in menu_actions(menu):
            if not has_mnemonic(action.text()) and not action.shortcuts():
                found.append(f"{menu.title()} > {action.text()!r}")
    for action in window.toolbar.actions():
        if isinstance(action, QWidgetAction):
            continue  # holds a widget (the date editor), named by its buddy label
        if not has_mnemonic(action.text()) and not action.shortcuts():
            found.append(f"toolbar > {action.text()!r}")
    return found


def _owner_window(obj: QObject) -> QWidget | None:
    node: QObject | None = obj
    while node is not None:
        if isinstance(node, QWidget) and node.isWindow():
            return node
        node = node.parent()
    return None


def _sequences(source: QObject) -> list[QKeySequence]:
    if isinstance(source, QAction):
        return list(source.shortcuts())
    if isinstance(source, QShortcut):
        return [source.key()]
    return []


def duplicate_shortcuts(root: QWidget) -> list[str]:
    """Shortcuts used twice inside one window (every action and ``QShortcut`` below ``root``).

    Standard keys an action already carries (Quit, Help) are counted like any other. Other windows
    (the help and About dialogs) have their own shortcuts and may repeat those of the main window.
    """
    found: dict[tuple[int, str], list[str]] = defaultdict(list)
    sources: list[QObject] = [*root.findChildren(QAction), *root.findChildren(QShortcut)]
    for source in sources:
        owner = _owner_window(source)
        for sequence in _sequences(source):
            key = sequence.toString(QKeySequence.SequenceFormat.PortableText)
            if key:
                name = source.text() if isinstance(source, QAction) else type(source).__name__
                found[(id(owner), key)].append(name)
    return [f"{key}: {names}" for (_owner, key), names in found.items() if len(names) > 1]


#: The keys a text field, a date editor or a table handles itself. No action may take them over.
_EDITING_KEYS = (
    QKeySequence.StandardKey.Copy,
    QKeySequence.StandardKey.Cut,
    QKeySequence.StandardKey.Paste,
    QKeySequence.StandardKey.Undo,
    QKeySequence.StandardKey.Redo,
    QKeySequence.StandardKey.SelectAll,
    QKeySequence.StandardKey.Delete,
    QKeySequence.StandardKey.Cancel,
    QKeySequence.StandardKey.Refresh,
)


def editing_key_clashes(root: QWidget) -> list[str]:
    taken = {
        binding.toString(QKeySequence.SequenceFormat.PortableText)
        for key in _EDITING_KEYS
        for binding in QKeySequence.keyBindings(key)
    }
    found: list[str] = []
    for action in root.findChildren(QAction):
        for sequence in action.shortcuts():
            text = sequence.toString(QKeySequence.SequenceFormat.PortableText)
            if text in taken:
                found.append(f"{action.text()!r}: {text}")
    return found


def tab_chain(first: QWidget, wanted: list[QWidget]) -> list[QWidget]:
    """The widgets of ``wanted`` in the order Tab visits them, starting at ``first``."""
    chain: list[QWidget] = []
    node: QWidget | None = first
    while node is not None:
        if node in wanted:
            chain.append(node)
        node = node.nextInFocusChain()
        if node == first:
            break
    return chain


def tab_order_mismatch(root: QWidget) -> list[str]:
    """Empty when Tab visits the widgets of ``root`` in the order its layouts show them."""
    wanted = layout_tab_order(root)
    if len(wanted) < 2:
        return []
    chain = tab_chain(wanted[0], wanted)
    if chain == wanted:
        return []
    shown = [describe(widget, root) for widget in wanted]
    visited = [describe(widget, root) for widget in chain]
    return [f"layout order {shown}, Tab order {visited}"]


def pixel_font_users(root: QWidget) -> list[str]:
    """Widgets whose font is set in pixels (unlike the application font) or whose style sheet sets
    a pixel font size."""
    default_pixels = QApplication.font().pixelSize()
    found: list[str] = []
    for widget in [root, *root.findChildren(QWidget)]:
        if widget.font().pixelSize() != default_pixels:
            found.append(f"{describe(widget, root)}: font in pixels")
        elif _PIXEL_FONT.search(widget.styleSheet()):
            found.append(f"{describe(widget, root)}: style sheet font in pixels")
    return found


def table_models(root: QWidget) -> list[ModuleTableModel]:
    models: list[ModuleTableModel] = []
    for view in root.findChildren(QAbstractItemView):
        model = view.model()
        if isinstance(model, ModuleTableModel) and model not in models:
            models.append(model)
    return models


# --------------------------------------------------------------------------- the status columns

#: (model class, column key) pairs that show a READINESS status: each must have its icon.
STATUS_COLUMNS = frozenset(
    {
        ("AlertsModel", "severity"),
        ("AssetsModel", "status"),
        ("HistoryModel", "details"),
        ("LotsModel", "status"),
        ("ScheduleModel", "status"),
        ("SummaryModel", "below_minimum"),
        ("StaffModel", "level_a"),
        ("StaffModel", "level_b"),
        ("StaffModel", "level_c"),
    }
)

#: Status columns that hold a status in only some rows (the asset history: a status event shows
#: its status, a maintenance record shows its kind). The icon belongs to the status rows only.
MIXED_STATUS_COLUMNS = frozenset({("HistoryModel", "details")})

#: Columns named "status" that are NOT a readiness status: a switch (active / inactive, enabled /
#: disabled) or the progress of a degree. Their text says everything; an icon would suggest a
#: severity that does not exist. Exempt on purpose (D23 concerns readiness statuses).
NOT_A_READINESS_STATUS = frozenset(
    {
        ("DegreesModel", "status"),
        ("TypesModel", "status"),
        ("StockTypesModel", "status"),
        ("CoursesModel", "status"),
        ("SourcesModel", "status"),
        ("MetricsModel", "status"),
        ("TargetsModel", "status"),
    }
)


def looks_like_status(key: str) -> bool:
    return key in {"status", "severity"} or key.startswith("level_")


# --------------------------------------------------------------------------- the walk


@dataclass(frozen=True)
class Root:
    name: str
    widget: QWidget
    kind: str  # "page", "section" or "dialog"


@dataclass(frozen=True)
class Walk:
    window: MainWindow
    roots: tuple[Root, ...]

    def of_kind(self, *kinds: str) -> list[Root]:
        return [root for root in self.roots if root.kind in kinds]


@pytest.fixture
def walk(started_app: StartApp, qtbot: QtBot) -> Iterator[Walk]:
    """The demo app with every page, settings section and registry dialog built (dialogs shown)."""
    handle = expect_handle(started_app(demo=True, clock=CLOCK))
    window = handle.window
    roots: list[Root] = []
    for page in registry.pages():
        roots.append(Root(f"page {page.key}", window.page_widget(page.key), "page"))
    built: list[QWidget] = []
    for section_spec in registry.settings_sections():
        section = section_spec.factory(handle.context)
        built.append(section)
        roots.append(Root(f"section {section_spec.key}", section, "section"))
    for dialog_spec in registry.dialogs():
        dialog = dialog_spec.factory(handle.context, window)
        dialog.show()  # a FormDialog puts its fields into Tab order when it is shown
        built.append(dialog)
        roots.append(Root(f"dialog {dialog_spec.key}", dialog, "dialog"))
    yield Walk(window, tuple(roots))
    # Delete the sections and dialogs now, and only them. Left alive, they would receive the
    # language change that the teardown of the app sends (its translators are removed) after
    # their context is gone.
    for widget in built:
        widget.close()
        shiboken6.delete(widget)


def _failures(walked: Walk, kinds: tuple[str, ...], rule: Rule) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for root in walked.of_kind(*kinds):
        problems = rule(root.widget)
        if problems:
            found[root.name] = problems
    return found


ALL_KINDS = ("page", "section", "dialog")

# --------------------------------------------------------------------------- the walk is not empty


def test_the_walk_covers_the_registries(walk: Walk) -> None:
    pages = {root.name for root in walk.of_kind("page")}
    assert pages == {f"page {spec.key}" for spec in registry.pages()}
    assert len(walk.of_kind("section")) == len(registry.settings_sections()) > 0
    assert len(walk.of_kind("dialog")) == len(registry.dialogs()) > 0
    interactive = sum(len(operated_widgets(root.widget)) for root in walk.roots)
    assert interactive > 100  # tables, combo boxes, inputs, buttons: a vacuous walk finds few


# --------------------------------------------------------------------------- names and keyboard


def test_every_interactive_widget_has_an_accessible_name_or_a_buddy(walk: Walk) -> None:
    assert _failures(walk, ALL_KINDS, unnamed_widgets) == {}


def test_every_interactive_widget_is_reachable_with_the_tab_key(walk: Walk) -> None:
    assert _failures(walk, ALL_KINDS, not_tab_reachable) == {}


def test_tab_visits_the_widgets_in_the_order_the_layouts_show_them(walk: Walk) -> None:
    # Sections are checked inside the Settings page (the page puts them in order); a section built
    # on its own is not part of any window.
    assert _failures(walk, ("page", "dialog"), tab_order_mismatch) == {}


def test_every_picture_beside_no_text_has_a_name(walk: Walk) -> None:
    assert _failures(walk, ALL_KINDS, unexplained_icons) == {}


def test_the_main_window_widgets_are_named_and_the_banner_icons_have_text(walk: Walk) -> None:
    window = walk.window
    for code in BannerCode:
        window.banners.show_banner(code)
    assert has_letters(window.navigation.accessibleName())
    assert has_letters(window.as_of_edit.accessibleName())
    assert window.as_of_label.buddy() is window.as_of_edit
    assert unexplained_icons(window.banners) == []
    for code in BannerCode:
        assert has_letters(window.banners.text(code)), code
    assert window.navigation.focusPolicy() in TAB_POLICIES
    assert window.as_of_edit.focusPolicy() in TAB_POLICIES


# --------------------------------------------------------------------------- status (D23)


def test_every_tile_shows_its_status_as_text_icon_and_palette_colour(walk: Walk) -> None:
    page = walk.window.page_widget("dashboard")
    assert isinstance(page, DashboardPage)
    assert len(page.tile_widgets) >= 20
    seen: set[IndicatorStatus] = set()
    for tile in page.tile_widgets:
        status = tile.tile.status
        assert has_letters(tile.status_label.text()), (tile.tile.code, status)
        assert not tile.status_icon.pixmap().isNull(), (tile.tile.code, status)
        assert has_letters(tile.status_icon.accessibleName()), (tile.tile.code, status)
        assert STATUS_COLOURS[status.value] in PALETTE, status
        assert STATUS_COLOURS[status.value] in tile.styleSheet(), (tile.tile.code, status)
        seen.add(status)
    assert seen == set(IndicatorStatus)  # the demo shows every status
    for severity in Severity:
        assert has_letters(page.alert_labels[severity].text()), severity
        assert not page.alert_icons[severity].pixmap().isNull(), severity
        assert has_letters(page.alert_icons[severity].accessibleName()), severity


def test_the_status_icons_differ_in_shape_and_colour(qapp: QApplication) -> None:
    images = {status: status_pixmap(status.value).toImage() for status in IndicatorStatus}
    for first in IndicatorStatus:
        assert STATUS_COLOURS[first.value] in PALETTE
        for second in IndicatorStatus:
            if first is not second:
                assert images[first] != images[second], (first, second)
                assert STATUS_COLOURS[first.value] != STATUS_COLOURS[second.value]


def test_every_asset_certificate_and_alert_status_has_its_own_icon(qapp: QApplication) -> None:
    assert set(ASSET_STATUS_LOOK) == set(AssetStatus)
    assert set(CERT_STATUS_LOOK) == set(CertStatus)
    for looks in (ASSET_STATUS_LOOK, CERT_STATUS_LOOK):
        assert len(set(looks.values())) == len(looks)  # no two statuses share an icon
    icons = [severity_icon(severity.value) for severity in Severity]
    assert all(not icon.isNull() for icon in icons)
    images = [icon.pixmap(16, 16).toImage() for icon in icons]
    assert all(a != b for index, a in enumerate(images) for b in images[index + 1 :])
    assert severity_icon("NOT_A_SEVERITY").isNull()


def test_status_columns_have_text_and_an_icon_and_nothing_else_does(walk: Walk) -> None:
    found: set[tuple[str, str]] = set()
    for root in walk.of_kind("page", "section"):
        for model in table_models(root.widget):
            for column_index, column in enumerate(model.COLUMNS):
                pair = (type(model).__name__, column.key)
                has_icon_column = column.icon is not None
                if looks_like_status(column.key) and pair not in NOT_A_READINESS_STATUS:
                    assert has_icon_column, f"{pair}: a status column without an icon"
                if has_icon_column:
                    found.add(pair)
                    assert pair in STATUS_COLUMNS, f"{pair}: an icon on a column not listed"
                for row in range(model.rowCount()):
                    index = model.index(row, column_index)
                    text = str(index.data(Qt.ItemDataRole.DisplayRole))
                    icon = index.data(Qt.ItemDataRole.DecorationRole)
                    if pair in MIXED_STATUS_COLUMNS:
                        # status rows show text plus icon, the other rows text only
                        shown = isinstance(icon, QIcon) and not icon.isNull()
                        status_row = model.rows()[row].status is not None
                        assert shown == status_row, (pair, row, text)
                        assert has_letters(text) or not status_row, (pair, row, text)
                    elif has_icon_column:
                        # text plus icon, or neither (a person with no status shows a dash)
                        shown = isinstance(icon, QIcon) and not icon.isNull()
                        assert shown == has_letters(text), (pair, row, text)
                    else:
                        assert icon is None, (pair, row)
    assert found == STATUS_COLUMNS  # the walk reached every status table


def test_the_asset_history_shows_an_icon_with_each_status_event(qapp: QApplication) -> None:
    day = date(2026, 3, 1)
    rows = [
        HistoryRow(day, status=StatusEventView(1, 1, day, status, None)) for status in AssetStatus
    ]
    service = MaintenanceView(1, 1, day, MaintenanceKind.PREVENTIVE, None, None)
    rows.append(HistoryRow(day, maintenance=service))
    model = HistoryModel()
    model.set_rows(rows)
    column = [c.key for c in model.COLUMNS].index("details")
    icons = []
    for row in range(model.rowCount()):
        index = model.index(row, column)
        assert has_letters(str(index.data(Qt.ItemDataRole.DisplayRole))), row
        icons.append(index.data(Qt.ItemDataRole.DecorationRole))
    status_icons = icons[:-1]
    assert all(isinstance(icon, QIcon) and not icon.isNull() for icon in status_icons)
    images = [icon.pixmap(16, 16).toImage() for icon in status_icons]
    assert all(a != b for index, a in enumerate(images) for b in images[index + 1 :])
    assert icons[-1] is None  # a maintenance record has no status


def test_the_demo_status_tables_have_rows_to_check(walk: Walk) -> None:
    rows = {
        type(model).__name__: model.rowCount()
        for root in walk.of_kind("page")
        for model in table_models(root.widget)
    }
    assert rows["AlertsModel"] >= 7
    assert rows["AssetsModel"] >= 7
    assert rows["StaffModel"] >= 5


# --------------------------------------------------------------------------- banner contrast

MINIMUM_CONTRAST = 4.5  # WCAG 2.x, normal-size text


def _luminance(colour: QColor) -> float:
    def linear(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return (
        0.2126 * linear(colour.redF())
        + 0.7152 * linear(colour.greenF())
        + 0.0722 * linear(colour.blueF())
    )


def contrast_ratio(first: QColor, second: QColor) -> float:
    """The WCAG contrast ratio of two colours (1.0 for equal colours, 21.0 for black on white)."""
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.fixture
def dark_palette(qapp: QApplication) -> Iterator[None]:
    """A dark application palette (a dark system theme), restored after the test."""
    original = QPalette(QApplication.palette())
    dark = QPalette()
    colours = {
        QPalette.ColorRole.Window: "#202020",
        QPalette.ColorRole.WindowText: "#f0f0f0",
        QPalette.ColorRole.Base: "#1a1a1a",
        QPalette.ColorRole.AlternateBase: "#262626",
        QPalette.ColorRole.Text: "#f0f0f0",
        QPalette.ColorRole.Button: "#353535",
        QPalette.ColorRole.ButtonText: "#f0f0f0",
        QPalette.ColorRole.BrightText: "#ffffff",
    }
    for role, colour in colours.items():
        dark.setColor(role, QColor(colour))
    QApplication.setPalette(dark)
    try:
        yield
    finally:
        QApplication.setPalette(original)


def test_the_contrast_ratio_is_the_wcag_one() -> None:
    assert contrast_ratio(QColor("#000000"), QColor("#ffffff")) == pytest.approx(21.0)
    assert contrast_ratio(QColor("#777777"), QColor("#777777")) == pytest.approx(1.0)
    assert contrast_ratio(QColor("#ffffff"), QColor("#fff4d6")) < MINIMUM_CONTRAST


def test_the_banner_text_and_button_are_readable_under_a_dark_palette(
    dark_palette: None, qtbot: QtBot
) -> None:
    # The window palette is dark, the banners keep their own light colours: the text of the labels
    # and of the "Open alerts" button must not come from the dark palette (light text on light).
    area = BannerArea()
    qtbot.addWidget(area)
    for code in BannerCode:
        area.show_banner(code)
    button = area.summary_button
    summary = area.findChild(QFrame, f"banner_{BannerCode.ALERT_SUMMARY.value}")
    assert isinstance(summary, QFrame)
    button.ensurePolished()  # applies the style sheet, which sets the palette of the widget
    button_text = button.palette().color(QPalette.ColorRole.ButtonText)
    button_background = button.palette().color(QPalette.ColorRole.Button)
    banner_background = summary.palette().color(QPalette.ColorRole.Window)
    assert contrast_ratio(button_text, button_background) >= MINIMUM_CONTRAST
    assert contrast_ratio(button_text, banner_background) >= MINIMUM_CONTRAST
    for code in BannerCode:
        frame = area.findChild(QFrame, f"banner_{code.value}")
        label = area.findChild(QLabel, f"banner_text_{code.value}")
        assert isinstance(frame, QFrame)
        assert isinstance(label, QLabel)
        label.ensurePolished()
        text = label.palette().color(QPalette.ColorRole.WindowText)
        background = frame.palette().color(QPalette.ColorRole.Window)
        assert contrast_ratio(text, background) >= MINIMUM_CONTRAST, code


# --------------------------------------------------------------------------- menus and shortcuts


def test_every_menu_action_has_a_mnemonic_or_a_shortcut(walk: Walk) -> None:
    assert actions_without_access(walk.window) == []


def test_the_menu_walk_reaches_every_menu_entry(walk: Walk) -> None:
    menus = top_menus(walk.window)
    assert len(menus) == 3  # File, Language, Help
    names = {action.objectName() for menu in menus for action in menu_actions(menu)}
    assert {
        "action_file_backup",
        "action_file_restore",
        "action_file_open_data_folder",
        "action_quit",
        "action_help",
        "action_about",
        "action_language_pt_BR",
        "action_language_en_US",
        "action_language_es_ES",
    } <= names


def test_no_shortcut_of_the_window_is_used_twice(walk: Walk) -> None:
    window = walk.window
    assert duplicate_shortcuts(window) == []
    # The standard keys the actions carry are part of the check, and the new ones are really set.
    assert window.quit_action.shortcuts()
    assert window.help_action.shortcuts()
    assert window.today_action.shortcuts()
    assert window.backup_actions.backup_action.shortcuts()
    assert all(action.shortcuts() for action in window.language_actions.values())


def test_no_action_takes_over_an_editing_key(walk: Walk) -> None:
    assert editing_key_clashes(walk.window) == []


def test_mnemonics_are_unique_in_the_menu_bar_and_in_every_menu(walk: Walk) -> None:
    window = walk.window
    keys = [mnemonic_of(menu.title()) for menu in top_menus(window)]
    keys.append(mnemonic_of(window.as_of_label.text()))  # the date label shares the menu bar's keys
    assert None not in keys
    assert len(keys) == len(set(keys)), keys
    for menu in top_menus(window):
        own = [mnemonic_of(entry.text()) for entry in menu_actions(menu)]
        used = [key for key in own if key is not None]
        assert len(used) == len(set(used)), (menu.title(), used)


def test_the_buttons_and_boxes_of_a_page_or_dialog_have_unique_mnemonics(walk: Walk) -> None:
    for root in walk.of_kind(*ALL_KINDS):
        keys: list[str] = []
        for widget in visible_widgets(root.widget):
            if isinstance(widget, QAbstractButton | QLabel):
                key = mnemonic_of(widget.text())
                if key is not None:
                    keys.append(key)
        assert len(keys) == len(set(keys)), (root.name, keys)


# --------------------------------------------------------------------------- size and scaling


def test_the_window_has_a_minimum_size(walk: Walk) -> None:
    window = walk.window
    assert window.minimumWidth() == MINIMUM_WIDTH
    assert window.minimumHeight() == MINIMUM_HEIGHT
    assert 0 < MINIMUM_WIDTH <= 960
    assert 0 < MINIMUM_HEIGHT <= 540  # a 1920 x 1080 display at 200 % is 960 x 540 logical pixels


def test_no_font_is_fixed_in_pixels_so_the_os_font_scale_is_respected(walk: Walk) -> None:
    problems: dict[str, list[str]] = {}
    for root in walk.roots:
        found = pixel_font_users(root.widget)
        if found:
            problems[root.name] = found
    found_window = pixel_font_users(walk.window)
    if found_window:
        problems["main window"] = found_window
    assert problems == {}


@pytest.mark.parametrize("lang", ["en-US", "pt-BR"])
def test_every_page_and_dialog_opens_at_scale_factor_2_without_a_qt_warning(
    qm_dir: Path, tmp_path: Path, lang: str
) -> None:
    """A child process with ``QT_SCALE_FACTOR=2`` opens the window, every page and every dialog.

    The scale factor is read when the application object is created, so it cannot be changed in
    this process. The child collects every Qt warning, critical and fatal message through
    ``qInstallMessageHandler``; those that ``qt_log_ignore`` of ``pyproject.toml`` lists (benign
    offscreen-platform messages) are dropped, as pytest-qt does.
    """
    ini = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns: list[str] = ini["tool"]["pytest"]["ini_options"]["qt_log_ignore"]
    ignore = [re.compile(pattern) for pattern in patterns]
    assert ignore  # the list is read, not assumed
    data_dir = tmp_path / "scale_data"
    data_dir.mkdir()
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": "2"}
    done = subprocess.run(
        [sys.executable, "-m", "tests.ui._scale_probe", str(data_dir), str(qm_dir), lang],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout.strip().splitlines()[-1])
    assert report["pages"] == len(registry.pages())
    assert report["dialogs"] == len(registry.dialogs())
    assert report["ratio"] == 2.0  # the offscreen screen applies QT_SCALE_FACTOR
    unexpected = [
        message
        for message in report["messages"]
        if not any(pattern.search(message) for pattern in ignore)
    ]
    assert unexpected == []


# --------------------------------------------------------------------------- the rules catch faults


@pytest.fixture
def bare(qtbot: QtBot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    QVBoxLayout(widget)
    return widget


def _add(widget: QWidget, child: QWidget) -> None:
    layout = widget.layout()
    assert layout is not None
    layout.addWidget(child)


def test_an_unnamed_input_is_reported_and_a_buddy_or_a_name_fixes_it(bare: QWidget) -> None:
    edit = QLineEdit()
    _add(bare, edit)
    assert unnamed_widgets(bare) == [describe(edit, bare)]
    caption = QLabel("&Name")
    caption.setBuddy(edit)
    _add(bare, caption)
    assert unnamed_widgets(bare) == []
    other = QLineEdit()
    other.setAccessibleName("Other")
    _add(bare, other)
    assert unnamed_widgets(bare) == []


def test_an_icon_only_button_is_reported(bare: QWidget) -> None:
    button = QToolButton()
    button.setIcon(QIcon(QPixmap(8, 8)))
    _add(bare, button)
    assert unnamed_widgets(bare) == [describe(button, bare)]
    button.setAccessibleName("Close")
    assert unnamed_widgets(bare) == []


def test_a_picture_without_text_or_name_is_reported(bare: QWidget) -> None:
    icon = QLabel()
    icon.setPixmap(QPixmap(8, 8))
    _add(bare, icon)
    assert unexplained_icons(bare) == [describe(icon, bare)]
    icon.setAccessibleName("Warning")
    assert unexplained_icons(bare) == []


def test_a_widget_that_cannot_take_the_tab_focus_is_reported(bare: QWidget) -> None:
    edit = QLineEdit()
    edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    _add(bare, edit)
    assert not_tab_reachable(bare) == [describe(edit, bare)]


def test_mnemonics_are_recognised() -> None:
    assert has_mnemonic("&Save")
    assert has_mnemonic("Sa&ve...")
    assert not has_mnemonic("Save")
    assert not has_mnemonic("Fish && Chips")
    assert mnemonic_of("&Save") == "s"


def test_a_repeated_shortcut_is_reported(bare: QWidget) -> None:
    first = QAction("First", bare)
    second = QAction("Second", bare)
    for action in (first, second):
        action.setShortcut(QKeySequence("Ctrl+K"))
        bare.addAction(action)
    assert len(duplicate_shortcuts(bare)) == 1
    second.setShortcut(QKeySequence("Ctrl+J"))
    assert duplicate_shortcuts(bare) == []


def test_an_action_on_an_editing_key_is_reported(bare: QWidget) -> None:
    action = QAction("Paste it", bare)
    action.setShortcut(QKeySequence(QKeySequence.StandardKey.Paste))
    bare.addAction(action)
    assert len(editing_key_clashes(bare)) == 1


def test_a_tab_order_that_differs_from_the_layout_is_found_and_fixed(bare: QWidget) -> None:
    # Three widgets: with two, every order is the same cycle.
    first = QLineEdit(bare)
    second = QLineEdit(bare)  # created second ...
    third = QLineEdit(bare)
    _add(bare, first)
    _add(bare, third)
    _add(bare, second)  # ... but laid out third
    assert layout_tab_order(bare) == [first, third, second]
    assert tab_order_mismatch(bare) != []
    apply_tab_order(bare)
    assert tab_order_mismatch(bare) == []


def test_a_pixel_font_is_reported(bare: QWidget) -> None:
    label = QLabel("x")
    font = label.font()
    font.setPixelSize(14)
    label.setFont(font)
    _add(bare, label)
    assert len(pixel_font_users(bare)) == 1
    plain = QLabel("y")
    plain.setStyleSheet("QLabel { font-size: 12px; }")
    _add(bare, plain)
    assert len(pixel_font_users(bare)) == 2
