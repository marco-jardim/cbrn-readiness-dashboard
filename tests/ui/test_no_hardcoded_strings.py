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
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QMenu,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from pytestqt.qtbot import QtBot

from cbrn_dashboard.app import AppHandle
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.banners import BannerCode
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.registry import DialogSpec, PageSpec, SettingsSectionSpec
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


def _walk_everything(handle: AppHandle, qtbot: QtBot) -> list[TextItem]:
    """Walk the window, every page, every settings section and every dialog; return the misses."""
    missing = list(find_untranslated(handle.window))
    for page_spec in registry.pages():
        missing += find_untranslated(handle.window.page_widget(page_spec.key))
    for section_spec in registry.settings_sections():
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
    for code in ("en_US", "es_ES", "pt_BR"):
        pseudo_app.window.language_actions[code].trigger()
        assert_fully_translated(pseudo_app.window)


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
