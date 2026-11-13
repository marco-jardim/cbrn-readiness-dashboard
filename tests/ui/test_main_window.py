# SPDX-License-Identifier: GPL-3.0-or-later
"""Main window (T0.7): translated title, menus, live language switch and status bar.

Pytest-qt fails any test that logs a Qt warning, so a window that closes cleanly proves the
"no Qt warnings" requirement. The event loop is never entered.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QMenu, QStackedWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard import i18n
from cbrn_dashboard.app import AppHandle, build_application
from cbrn_dashboard.cli import CliOptions
from cbrn_dashboard.paths import DataLocation, LocationSource
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.main_window import MainWindow

pytestmark = pytest.mark.ui

TITLES = {
    "pt_BR": "Painel de Prontidão QBRN",
    "en_US": "CBRN Readiness Dashboard",
    "es_ES": "Panel de Preparación QBRN",
}
FILE_MENU = {"pt_BR": "&Arquivo", "en_US": "&File", "es_ES": "&Archivo"}
LANGUAGE_MENU = {"pt_BR": "&Idioma", "en_US": "&Language", "es_ES": "&Idioma"}
FOLDER_TEXT = {
    "pt_BR": "Pasta de dados: ",
    "en_US": "Data folder: ",
    "es_ES": "Carpeta de datos: ",
}
WARNING = "Translations are not compiled: the English source text is shown."

type MakeApp = Callable[[str | None], AppHandle]


def _location(folder: Path) -> DataLocation:
    return DataLocation(path=folder, source=LocationSource.CLI, writable=True)


@pytest.fixture
def make_app(qapp: QApplication, qm_dir: Path, tmp_path: Path, qtbot: QtBot) -> Iterator[MakeApp]:
    """Build the application like ``main`` does (without ``exec``); undo it on teardown."""
    handles: list[AppHandle] = []

    def make(lang: str | None) -> AppHandle:
        options = CliOptions(data_dir=str(tmp_path), lang=lang, self_test=False)
        handle = build_application(options, _location(tmp_path), qm_dir)
        qtbot.addWidget(handle.window)
        handles.append(handle)
        return handle

    yield make
    for handle in reversed(handles):
        handle.window.close()
        handle.translator_manager.clear()
        handle.translator_manager.setParent(None)


def _find[T](handle: AppHandle, kind: type[T], name: str) -> T:
    found = handle.window.findChild(kind, name)
    assert found is not None, name
    return found


@pytest.mark.parametrize("code", i18n.LANGUAGES)
def test_window_opens_with_translated_title(make_app: MakeApp, qtbot: QtBot, code: str) -> None:
    handle = make_app(i18n.to_bcp47(code))
    handle.window.show()
    qtbot.waitExposed(handle.window)
    assert handle.window.windowTitle() == TITLES[code]
    assert handle.window.language_actions[code].isChecked()


def test_default_language_is_pt_br(make_app: MakeApp) -> None:
    handle = make_app(None)
    assert handle.translator_manager.current_language == "pt_BR"
    assert handle.window.windowTitle() == TITLES["pt_BR"]
    actions = handle.window.language_actions
    assert [code for code, action in actions.items() if action.isChecked()] == ["pt_BR"]


def test_language_menu_has_three_exclusive_entries(make_app: MakeApp) -> None:
    handle = make_app("en-US")
    menu = _find(handle, QMenu, "menu_language")
    assert list(handle.window.language_actions) == list(i18n.LANGUAGES)
    assert menu.actions() == list(handle.window.language_actions.values())
    assert [a.text() for a in menu.actions()] == [
        "Portuguese (Brazil)",
        "English (United States)",
        "Spanish (Spain)",
    ]
    assert all(action.isCheckable() for action in menu.actions())


def test_choosing_a_language_retitles_the_window_live(make_app: MakeApp, qtbot: QtBot) -> None:
    handle = make_app("pt-BR")
    window = handle.window
    window.show()
    qtbot.waitExposed(window)
    file_menu = _find(handle, QMenu, "menu_file")
    language_menu = _find(handle, QMenu, "menu_language")

    for code in ("en_US", "es_ES", "pt_BR", "es_ES"):
        window.language_actions[code].trigger()
        qtbot.waitUntil(lambda code=code: window.windowTitle() == TITLES[code], timeout=2000)
        assert handle.translator_manager.current_language == code
        assert file_menu.title() == FILE_MENU[code]
        assert language_menu.title() == LANGUAGE_MENU[code]
        assert [c for c, a in window.language_actions.items() if a.isChecked()] == [code]
        folder_label = _find(handle, QLabel, "data_folder_label")
        assert folder_label.text().startswith(FOLDER_TEXT[code])


def test_language_entries_are_named_in_the_current_language(make_app: MakeApp) -> None:
    handle = make_app("es-ES")
    texts = [action.text() for action in handle.window.language_actions.values()]
    assert texts == ["Portugués (Brasil)", "Inglés (Estados Unidos)", "Español (España)"]


def test_navigation_is_empty(make_app: MakeApp) -> None:
    handle = make_app(None)
    assert _find(handle, QListWidget, "navigation_list").count() == 0
    assert _find(handle, QStackedWidget, "page_stack").count() == 0


def test_status_bar_shows_the_data_folder(make_app: MakeApp, tmp_path: Path) -> None:
    handle = make_app("en-US")
    label = _find(handle, QLabel, "data_folder_label")
    assert label.text() == f"Data folder: {tmp_path}"
    assert handle.window.statusBar().isAncestorOf(label)


def test_no_warning_when_catalogues_are_compiled(make_app: MakeApp) -> None:
    handle = make_app("pt-BR")
    assert handle.translator_manager.missing_catalogues == ()
    assert _find(handle, QLabel, "translations_warning_label").text() == ""


def test_warning_when_catalogues_are_missing(
    translator_manager_factory: Callable[[Path | None], TranslatorManager],
    tmp_path: Path,
    qtbot: QtBot,
) -> None:
    manager = translator_manager_factory(tmp_path / "no-qm")
    manager.set_language("en_US")
    assert manager.missing_catalogues != ()
    window = MainWindow(manager, _location(tmp_path))
    qtbot.addWidget(window)
    label = window.findChild(QLabel, "translations_warning_label")
    assert label is not None
    assert label.text() == WARNING
    assert window.windowTitle() == TITLES["en_US"]


def test_quit_action_closes_the_window(make_app: MakeApp, qtbot: QtBot) -> None:
    handle = make_app(None)
    window = handle.window
    window.show()
    qtbot.waitExposed(window)
    assert window.findChild(QAction, "action_quit") is window.quit_action
    window.quit_action.trigger()
    assert not window.isVisible()


def test_window_closes_cleanly(make_app: MakeApp, qtbot: QtBot) -> None:
    handle = make_app("pt-BR")
    handle.window.show()
    qtbot.waitExposed(handle.window)
    assert handle.window.close()
    assert not handle.window.isVisible()
