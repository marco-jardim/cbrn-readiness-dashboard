# SPDX-License-Identifier: GPL-3.0-or-later
"""Pseudo-locale walk (PLAN.md section 6, check 6; task T1.9).

With the pseudo catalogue installed as the active language, the main window is built through the
real start path, every registered page, settings section and dialog is opened, and the walker
(``tests/ui/_walk.py``) reports every visible non-data text that lacks the ``⟦ ⟧`` markers. The
walk covers whatever later tasks register, automatically. The negative self-tests prove that the
walker really catches a hard-coded string and honours the ``i18nData`` exemption.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QAction, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QMenu,
    QPushButton,
    QStatusBar,
    QTableView,
    QToolBox,
    QVBoxLayout,
    QWidget,
)
from pytestqt.qtbot import QtBot

from cbrn_dashboard.app import AppHandle
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.banners import BannerCode
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.registry import DialogSpec, PageSpec, SettingsSectionSpec
from tests.conftest import PSEUDO_PREFIX
from tests.ui._fakes import expect_handle
from tests.ui._walk import (
    CLOSE_MARK,
    DATA_PROPERTY,
    OPEN_MARK,
    TextItem,
    assert_fully_translated,
    clean,
    collect_texts,
    find_untranslated,
)
from tests.ui.conftest import StartApp

pytestmark = pytest.mark.ui


def _t(text: str) -> str:
    """The pseudo-locale form of ``text``."""
    return f"{OPEN_MARK}{text}{CLOSE_MARK}"


def _translate(source: str) -> str:
    # Only used with sources that exist in the shell catalogue (the test pages are not extracted).
    return QCoreApplication.translate("Shell", source)


def _set_header(model: QStandardItemModel, section: int, text: str) -> None:
    model.setHeaderData(section, Qt.Orientation.Horizontal, text, Qt.ItemDataRole.DisplayRole)


def _title_misses(owner: str, kind: str, text: str) -> list[TextItem]:
    """``[item]`` when a title or navigation text lacks the markers, else ``[]``."""
    item = TextItem(owner, kind, text)
    return [] if item.translated else [item]


def _walk_everything(handle: AppHandle, qtbot: QtBot) -> list[TextItem]:
    """Walk the window, every page, every settings section and every dialog; return the misses.

    The navigation labels (list items, otherwise exempt as data cells) and the titles of every
    registered page and settings section are checked explicitly.
    """
    missing = list(find_untranslated(handle.window))
    navigation = handle.window.navigation
    for row in range(navigation.count()):
        item = navigation.item(row)
        text = "" if item is None else item.text()
        missing += _title_misses(f"navigation row {row}", "navigation item", text)
    for page_spec in registry.pages():
        missing += _title_misses(page_spec.key, "page title", page_spec.title())
        missing += find_untranslated(handle.window.page_widget(page_spec.key))
    for section_spec in registry.settings_sections():
        missing += _title_misses(section_spec.key, "section title", section_spec.title())
        section = section_spec.factory(handle.context)
        qtbot.addWidget(section)
        missing += find_untranslated(section)
    for dialog_spec in registry.dialogs():
        dialog = dialog_spec.factory(handle.context, handle.window)
        try:
            missing += find_untranslated(dialog)
        finally:
            dialog.close()
            dialog.deleteLater()
    return missing


@pytest.fixture
def pseudo_app(started_app: StartApp, pseudo_qm_dir: Path) -> AppHandle:
    """The real start path with the pseudo-locale catalogue active (Portuguese slot)."""
    return expect_handle(started_app(qm=pseudo_qm_dir, lang="pt-BR"))


# --------------------------------------------------------------------------- test pages


def _translated_page(context: AppContext) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(QLabel(_translate("Navigation")))
    box = QGroupBox(_translate("Today"))
    box.setToolTip(_translate("Main toolbar"))
    layout.addWidget(box)
    button = QPushButton(_translate("&Quit"))
    layout.addWidget(button)
    combo = QComboBox()
    combo.addItem(_translate("As-of date"))
    layout.addWidget(combo)
    table = QTableView()
    model = QStandardItemModel(1, 2, table)
    _set_header(model, 0, _translate("Today"))
    _set_header(model, 1, _translate("As-of date"))
    table.setModel(model)
    layout.addWidget(table)
    data = QLabel("DEMO-P001 Fictitious Person")
    data.setProperty(DATA_PROPERTY, True)
    layout.addWidget(data)
    layout.addWidget(QLabel("12 / 3.5"))  # no letters: not text to translate
    return page


def _translated_dialog(context: AppContext, parent: QWidget | None) -> QDialog:
    dialog = QDialog(parent)
    dialog.setWindowTitle(_translate("Cannot start"))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(_translate("Navigation")))
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )  # standard buttons are translated by Qt itself
    layout.addWidget(buttons)
    return dialog


def _translated_section(context: AppContext) -> QWidget:
    return QLabel(_translate("Navigation"))


def _hardcoded_page(context: AppContext) -> QWidget:
    return QLabel("Hard-coded")


def _data_page(context: AppContext) -> QWidget:
    label = QLabel("Hard-coded")
    label.setProperty(DATA_PROPERTY, True)
    return label


def _hardcoded_dialog(context: AppContext, parent: QWidget | None) -> QDialog:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Hard-coded title")
    return dialog


def _hardcoded_section(context: AppContext) -> QWidget:
    return QPushButton("Hard-coded button")


def _title() -> str:
    return _translate("Navigation")


GOOD_PAGE = PageSpec("good_page", 10, _title, _translated_page)
GOOD_DIALOG = DialogSpec("good_dialog", _translated_dialog)
GOOD_SECTION = SettingsSectionSpec("good_section", "general", _title, _translated_section)


# --------------------------------------------------------------------------- the shell walk


def test_the_shell_is_fully_translated(pseudo_app: AppHandle, qtbot: QtBot) -> None:
    for code in BannerCode:  # show every banner so that every banner text is walked
        pseudo_app.window.banners.show_banner(code)
    assert_fully_translated(pseudo_app.window)
    assert _walk_everything(pseudo_app, qtbot) == []


def test_the_shell_walk_is_not_vacuous(pseudo_app: AppHandle) -> None:
    for code in BannerCode:
        pseudo_app.window.banners.show_banner(code)
    texts = {item.text for item in collect_texts(pseudo_app.window)}
    expected = {
        _t("&File"),
        _t("&Quit"),
        _t("&Language"),
        _t("Portuguese (Brazil)"),
        _t("Today"),
        _t("&As-of date:"),
        _t("Main toolbar"),
        _t("Navigation"),
        _t("DEMO \u2014 fictitious data"),
        _t("Preliminary version \u2014 indicators not institutionally validated."),
    }
    assert expected <= texts
    assert any(text.startswith(_t("Data folder: ")[:-1]) for text in texts)


def test_registered_pages_settings_sections_and_dialogs_are_walked(
    started_app: StartApp, pseudo_qm_dir: Path, qtbot: QtBot
) -> None:
    with registry.registered(GOOD_PAGE, GOOD_DIALOG, GOOD_SECTION):
        handle = expect_handle(started_app(qm=pseudo_qm_dir, lang="pt-BR"))
        assert "good_page" in handle.window.page_keys()
        navigation = handle.window.navigation
        assert _t("Navigation") in [navigation.item(r).text() for r in range(navigation.count())]
        assert _walk_everything(handle, qtbot) == []
        page_texts = {item.text for item in collect_texts(handle.window.page_widget("good_page"))}
        assert {_t("Navigation"), _t("Today"), _t("&Quit"), _t("As-of date")} <= page_texts
        assert "DEMO-P001 Fictitious Person" not in page_texts  # data is exempt, not walked


def test_the_shell_stays_translated_after_a_language_switch(
    pseudo_app: AppHandle, qtbot: QtBot
) -> None:
    # Each language has its own pseudo marker (PSEUDO_PREFIX): a text that is not re-applied by
    # retranslate() still carries the marker of the language the app started in, and fails.
    window = pseudo_app.window
    for banner in BannerCode:
        window.banners.show_banner(banner)
    assert_fully_translated(window, "pt_BR")
    for lang in ("es_ES", "en_US", "pt_BR"):
        window.language_actions[lang].trigger()
        assert_fully_translated(window, lang)
        for row in range(window.navigation.count()):
            item = window.navigation.item(row)
            assert item is not None
            assert TextItem("navigation", "navigation item", item.text()).translated_in(lang)


# --------------------------------------------------------------------------- negative self-tests


def test_a_hardcoded_label_on_a_registered_page_is_reported(
    started_app: StartApp, pseudo_qm_dir: Path, qtbot: QtBot
) -> None:
    bad = PageSpec("bad_page", 10, _title, _hardcoded_page)
    with registry.registered(bad):
        handle = expect_handle(started_app(qm=pseudo_qm_dir, lang="pt-BR"))
        missing = _walk_everything(handle, qtbot)
    assert missing
    assert {item.text for item in missing} == {"Hard-coded"}
    assert all(item.kind == "label" for item in missing)
    with pytest.raises(AssertionError, match="Hard-coded"):
        assert_fully_translated(handle.window.page_widget("bad_page"))


def test_a_hardcoded_text_in_a_registered_dialog_or_section_is_reported(
    started_app: StartApp, pseudo_qm_dir: Path, qtbot: QtBot
) -> None:
    bad_dialog = DialogSpec("bad_dialog", _hardcoded_dialog)
    bad_section = SettingsSectionSpec("bad_section", "general", _title, _hardcoded_section)
    with registry.registered(bad_dialog, bad_section):
        handle = expect_handle(started_app(qm=pseudo_qm_dir, lang="pt-BR"))
        missing = _walk_everything(handle, qtbot)
    assert {item.text for item in missing} == {"Hard-coded title", "Hard-coded button"}


def test_the_i18n_data_property_exempts_a_widget(
    started_app: StartApp, pseudo_qm_dir: Path, qtbot: QtBot
) -> None:
    data = PageSpec("data_page", 10, _title, _data_page)
    with registry.registered(data):
        handle = expect_handle(started_app(qm=pseudo_qm_dir, lang="pt-BR"))
        assert _walk_everything(handle, qtbot) == []


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


def test_the_walker_catches_each_kind_of_text(bare: QWidget) -> None:
    label = QLabel(_t("fine"))
    label.setToolTip("Hard tooltip")
    _add(bare, label)
    _add(bare, QGroupBox("Hard group"))
    _add(bare, QPushButton("&Hard button"))
    combo = QComboBox()
    combo.addItem("Hard item")
    _add(bare, combo)
    table = QTableView()
    model = QStandardItemModel(1, 1, table)
    _set_header(model, 0, "Hard header")
    table.setModel(model)
    _add(bare, table)
    action = QAction("Hard action", bare)
    bare.addAction(action)
    menu = QMenu("Hard menu", bare)
    menu.addAction(QAction("Hard menu entry", menu))
    button_with_menu = QPushButton(_t("menu button"))
    button_with_menu.setMenu(menu)
    _add(bare, button_with_menu)

    found = {(item.kind, item.text) for item in find_untranslated(bare)}
    assert found >= {
        ("tooltip", "Hard tooltip"),
        ("group box", "Hard group"),
        ("button", "&Hard button"),
        ("combo item 0", "Hard item"),
        ("header horizontal 0", "Hard header"),
        ("action text", "Hard action"),
        ("action text", "Hard menu entry"),
    }


def test_the_walker_exemptions(bare: QWidget) -> None:
    flagged = QLabel("Hard-coded")
    flagged.setProperty(DATA_PROPERTY, True)
    _add(bare, flagged)
    hidden = QLabel("Hidden hard-coded")
    _add(bare, hidden)
    hidden.hide()
    _add(bare, QLabel("2026-03-05 12:30 (3)"))  # no letters
    flagged_action = QAction("Hard action", bare)
    flagged_action.setProperty(DATA_PROPERTY, True)
    bare.addAction(flagged_action)
    flagged_combo = QComboBox()
    flagged_combo.setProperty(DATA_PROPERTY, True)
    flagged_combo.addItem("DEMO-P001")
    _add(bare, flagged_combo)
    table = QTableView()
    cells = QStandardItemModel(1, 1, table)
    cells.setItem(0, 0, QStandardItem("Cell content is data"))
    table.setModel(cells)
    _add(bare, table)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    _add(bare, buttons)
    _add(bare, QLabel(_t("&Save\tCtrl+S")))  # mnemonic and shortcut suffix are stripped

    assert find_untranslated(bare) == []


def test_the_walker_strips_mnemonics_and_shortcuts() -> None:
    assert clean("&Save\tCtrl+S") == "Save"
    assert clean("Fish && Chips") == "Fish & Chips"
    assert clean("<b>Bold</b>") == "Bold"


# --------------------------------------------------------------------------- titles and switches


def test_a_hardcoded_page_or_section_title_is_reported(
    started_app: StartApp, pseudo_qm_dir: Path, qtbot: QtBot
) -> None:
    bad_page = PageSpec("bad_title_page", 10, lambda: "Hard-coded", _translated_page)
    bad_section = SettingsSectionSpec(
        "bad_title_section", "general", lambda: "Hard-coded section", _translated_section
    )
    with registry.registered(bad_page, bad_section):
        handle = expect_handle(started_app(qm=pseudo_qm_dir, lang="pt-BR"))
        missing = _walk_everything(handle, qtbot)
    found = {(item.kind, item.text) for item in missing}
    assert found == {
        ("navigation item", "Hard-coded"),
        ("page title", "Hard-coded"),
        ("section title", "Hard-coded section"),
    }


def _set_once_page(context: AppContext) -> QWidget:
    # The label text is set in __init__ only and never re-applied on a language change.
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(QLabel(_translate("Navigation")))
    return page


def test_a_text_not_reapplied_after_a_switch_is_reported(
    started_app: StartApp, pseudo_qm_dir: Path
) -> None:
    with registry.registered(PageSpec("set_once", 10, _title, _set_once_page)):
        handle = expect_handle(started_app(qm=pseudo_qm_dir, lang="pt-BR"))
    page = handle.window.page_widget("set_once")
    assert_fully_translated(page, "pt_BR")
    handle.window.language_actions["es_ES"].trigger()
    label = page.findChild(QLabel)
    assert label is not None
    assert label.text() == _t("Navigation")  # still the pt_BR form
    assert_fully_translated(page)  # the markers alone would not notice ...
    with pytest.raises(AssertionError, match="Navigation"):
        assert_fully_translated(page, "es_ES")  # ... the es_ES marker does
    [item] = find_untranslated(page, "es_ES")
    assert item.kind == "label"


# --------------------------------------------------------------------------- mixed and data texts


def test_a_mixed_text_is_reported(bare: QWidget) -> None:
    _add(bare, QLabel(_t("Navigation") + " hard-coded"))
    _add(bare, QLabel("Hard-coded " + _t("Today")))
    _add(bare, QLabel(OPEN_MARK + "unclosed"))
    _add(bare, QLabel(_t("Data folder: " + _t("Today")) + " 12"))  # nested and digits: fine
    _add(bare, QLabel(_t("&Save") + "\tCtrl+S"))  # the shortcut suffix is stripped: fine
    found = {item.text for item in find_untranslated(bare)}
    assert found == {
        _t("Navigation") + " hard-coded",
        "Hard-coded " + _t("Today"),
        OPEN_MARK + "unclosed",
    }


def test_the_wrong_language_marker_is_reported(bare: QWidget) -> None:
    _add(bare, QLabel(f"{OPEN_MARK}{PSEUDO_PREFIX['es_ES']}Today{CLOSE_MARK}"))
    assert find_untranslated(bare) == []
    assert find_untranslated(bare, "es_ES") == []
    assert [item.kind for item in find_untranslated(bare, "pt_BR")] == ["label"]
    assert [item.kind for item in find_untranslated(bare, "en_US")] == ["label"]


def test_a_data_widget_still_has_its_tooltips_headers_and_actions_checked(
    bare: QWidget,
) -> None:
    label = QLabel("DEMO-P001 Fictitious Person")
    label.setProperty(DATA_PROPERTY, True)
    label.setToolTip("Hard tooltip")
    label.setStatusTip("Hard status tip")
    label.setAccessibleName("Hard name")
    label.addAction(QAction("Hard action", label))
    _add(bare, label)
    table = QTableView()
    table.setProperty(DATA_PROPERTY, True)
    model = QStandardItemModel(1, 1, table)
    model.setItem(0, 0, QStandardItem("Cell content is data"))
    _set_header(model, 0, "Hard header")
    table.setModel(model)
    _add(bare, table)
    combo = QComboBox()
    combo.setProperty(DATA_PROPERTY, True)
    combo.addItem("DEMO-C001")
    combo.setToolTip("Hard combo tooltip")
    _add(bare, combo)

    found = {(item.kind, item.text) for item in find_untranslated(bare)}
    assert found >= {
        ("tooltip", "Hard tooltip"),
        ("status tip", "Hard status tip"),
        ("accessible name", "Hard name"),
        ("action text", "Hard action"),
        ("header horizontal 0", "Hard header"),
        ("tooltip", "Hard combo tooltip"),
    }
    texts = {text for _kind, text in found}
    assert "DEMO-P001 Fictitious Person" not in texts  # the data itself stays exempt
    assert "DEMO-C001" not in texts
    assert "Cell content is data" not in texts


def test_the_walker_catches_the_newer_kinds(bare: QWidget) -> None:
    label = QLabel(_t("fine"))
    label.setWhatsThis("Hard whats this")
    _add(bare, label)
    toolbox = QToolBox()
    toolbox.addItem(QWidget(), "Hard tool box item")
    _add(bare, toolbox)
    table = QTableView()
    model = QStandardItemModel(1, 1, table)
    _set_header(model, 0, _t("fine header"))
    tip_role = Qt.ItemDataRole.ToolTipRole
    model.setHeaderData(0, Qt.Orientation.Horizontal, "Hard header tip", tip_role)
    table.setModel(model)
    _add(bare, table)
    edit = QDateEdit()
    edit.setSpecialValueText("Hard special value")
    _add(bare, edit)
    status = QStatusBar()
    status.showMessage("Hard message")
    _add(bare, status)

    found = {(item.kind, item.text) for item in find_untranslated(bare)}
    assert found >= {
        ("whats this", "Hard whats this"),
        ("tool box item 0", "Hard tool box item"),
        ("header tooltip horizontal 0", "Hard header tip"),
        ("special value", "Hard special value"),
        ("status bar message", "Hard message"),
    }
