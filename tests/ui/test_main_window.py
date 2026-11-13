# SPDX-License-Identifier: GPL-3.0-or-later
"""Main window (T0.7): translated title, menus, live language switch and status bar.

Pytest-qt fails any test that logs a Qt warning, so a window that closes cleanly proves the
"no Qt warnings" requirement. The event loop is never entered.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QRect, QSize, QTranslator
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QMenu, QStackedWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard import i18n
from cbrn_dashboard.app import AppHandle, start
from cbrn_dashboard.cli import CliOptions
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.paths import DataLocation, LocationSource
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.main_window import MINIMUM_HEIGHT, MINIMUM_WIDTH
from tests.ui._fakes import FakePrompts, expect_handle

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

type MakeApp = Callable[..., AppHandle]


def _location(folder: Path) -> DataLocation:
    return DataLocation(path=folder, source=LocationSource.CLI, writable=True)


@pytest.fixture
def make_app(qapp: QApplication, qm_dir: Path, tmp_path: Path, qtbot: QtBot) -> Iterator[MakeApp]:
    """Start the application like ``main`` does (without ``exec``); undo it on teardown."""
    handles: list[AppHandle] = []

    def make(lang: str | None, *, qm: Path | None = None) -> AppHandle:
        options = CliOptions(data_dir=str(tmp_path), lang=lang, self_test=False)
        result = start(
            options,
            _location(tmp_path),
            clock=FixedClock.at("2026-03-05T12:00:00Z"),
            prompts=FakePrompts(),
            qm_dir=qm_dir if qm is None else qm,
            hooks=(),
        )
        handle = expect_handle(result)
        qtbot.addWidget(handle.window)
        handles.append(handle)
        return handle

    yield make
    for handle in reversed(handles):
        handle.close()


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


def test_window_retranslates_on_a_qt_language_change_event(
    make_app: MakeApp, qapp: QApplication, qm_dir: Path, qtbot: QtBot
) -> None:
    """A translator installed behind the manager's back still retitles the window.

    This is the ``LanguageChange`` mechanism later pages rely on (plan section 6); it fails if
    ``MainWindow.changeEvent`` stops calling ``retranslate``.
    """
    handle = make_app("en-US")
    window = handle.window
    file_menu = _find(handle, QMenu, "menu_file")
    assert window.windowTitle() == TITLES["en_US"]

    translator = QTranslator()
    assert translator.load(str(qm_dir / i18n.qm_name("shell", "es_ES")))
    qapp.installTranslator(translator)
    try:
        qapp.processEvents()
        qtbot.waitUntil(lambda: window.windowTitle() == TITLES["es_ES"], timeout=2000)
        assert file_menu.title() == FILE_MENU["es_ES"]
        assert handle.translator_manager.current_language == "en_US"
    finally:
        qapp.removeTranslator(translator)
    qtbot.waitUntil(lambda: window.windowTitle() == TITLES["en_US"], timeout=2000)
    assert file_menu.title() == FILE_MENU["en_US"]


def test_language_entries_are_named_in_the_current_language(make_app: MakeApp) -> None:
    handle = make_app("es-ES")
    texts = [action.text() for action in handle.window.language_actions.values()]
    assert texts == ["Portugués (Brasil)", "Inglés (Estados Unidos)", "Español (España)"]


def test_navigation_holds_exactly_the_registered_pages(make_app: MakeApp) -> None:
    # No module has registered a page yet, so this is empty today; it follows the registry.
    expected = len(registry.pages())
    handle = make_app(None)
    assert _find(handle, QListWidget, "navigation_list").count() == expected
    assert _find(handle, QStackedWidget, "page_stack").count() == expected


def test_status_bar_shows_the_data_folder(make_app: MakeApp, tmp_path: Path) -> None:
    handle = make_app("en-US")
    label = _find(handle, QLabel, "data_folder_label")
    assert label.text() == f"Data folder: {tmp_path}"
    assert handle.window.statusBar().isAncestorOf(label)


def test_no_warning_when_catalogues_are_compiled(make_app: MakeApp) -> None:
    handle = make_app("pt-BR")
    assert handle.translator_manager.missing_catalogues == ()
    assert "TRANSLATIONS_MISSING" not in handle.window.banners.visible_codes()


def test_warning_when_catalogues_are_missing(make_app: MakeApp, tmp_path: Path) -> None:
    # The warning moved from the status bar into the banner area (T1.9); it is shown once.
    handle = make_app("en-US", qm=tmp_path / "no-qm")
    assert handle.translator_manager.missing_catalogues != ()
    banners = handle.window.banners
    assert "TRANSLATIONS_MISSING" in banners.visible_codes()
    assert banners.text("TRANSLATIONS_MISSING") == WARNING
    assert handle.window.findChild(QLabel, "translations_warning_label") is None
    assert handle.window.windowTitle() == TITLES["en_US"]


def test_quit_action_closes_the_window(make_app: MakeApp, qtbot: QtBot) -> None:
    handle = make_app(None)
    window = handle.window
    window.show()
    qtbot.waitExposed(window)
    assert window.findChild(QAction, "action_quit") is window.quit_action
    window.quit_action.trigger()
    assert not window.isVisible()


def test_oversized_window_is_fitted_to_the_available_area(
    make_app: MakeApp, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = make_app("en-US").window
    area = QRect(100, 80, 1000, 600)  # smaller than the window below, larger than the minimum
    monkeypatch.setattr(window, "available_area", lambda: area)
    window.resize(1600, 1200)
    window.move(900, 500)  # starts across the bottom right edge of the area
    window.show()
    qtbot.waitExposed(window)
    assert area.contains(window.frameGeometry())
    assert window.width() >= MINIMUM_WIDTH
    assert window.height() >= MINIMUM_HEIGHT


def test_window_fits_an_offset_available_area(
    make_app: MakeApp, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The offscreen screen is only 800 px wide, the minimum width, so a patched area is used.
    area = QRect(100, 50, 1200, 900)
    window = make_app("en-US").window
    monkeypatch.setattr(window, "available_area", lambda: area)
    window.resize(3000, 2000)  # taller and wider than the area
    window.show()
    qtbot.waitExposed(window)
    assert area.contains(window.frameGeometry())


def test_fitted_window_keeps_the_minimum_size(
    make_app: MakeApp, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = make_app("en-US").window
    monkeypatch.setattr(window, "available_area", lambda: QRect(0, 0, 640, 400))
    window.show()
    qtbot.waitExposed(window)
    assert (window.width(), window.height()) == (MINIMUM_WIDTH, MINIMUM_HEIGHT)
    assert window.minimumSize() == QSize(MINIMUM_WIDTH, MINIMUM_HEIGHT)


def test_window_is_fitted_only_on_the_first_show(
    make_app: MakeApp, qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = make_app("en-US").window
    monkeypatch.setattr(window, "available_area", lambda: QRect(0, 0, 1000, 600))
    window.resize(900, 560)
    window.show()
    qtbot.waitExposed(window)
    window.hide()
    window.resize(950, 580)
    window.show()
    qtbot.waitExposed(window)
    assert (window.width(), window.height()) == (950, 580)


def test_window_closes_cleanly(make_app: MakeApp, qtbot: QtBot) -> None:
    handle = make_app("pt-BR")
    handle.window.show()
    qtbot.waitExposed(handle.window)
    assert handle.window.close()
    assert not handle.window.isVisible()
