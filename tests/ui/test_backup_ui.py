# SPDX-License-Identifier: GPL-3.0-or-later
"""The File-menu wiring of the backup actions and the open-folder helper (PLAN.md T7.4).

The dialogs and flows behind the actions are tested in ``test_backup_page.py``; here the main window
is checked: the three menu entries, their order, read-only mode, and the hand-off of the data folder
to the one helper that may open a folder (``ui/shell/folders.py``), which is tested with an
injected opener so no program is ever started.
"""

from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest
from PySide6.QtCore import QUrl
from pytestqt.qtbot import QtBot

from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.storage.db import open_database
from cbrn_dashboard.ui.shell import folders
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.folders import is_openable_folder, open_local_folder
from cbrn_dashboard.ui.shell.main_window import MainWindow
from tests.meta._ast_rules import check_source
from tests.ui._fakes import FakePrompts

pytestmark = pytest.mark.ui

MENU_NAMES = [
    "action_file_backup",
    "action_file_restore",
    "action_file_open_data_folder",
    "",  # the separator
    "action_quit",
]


@pytest.fixture
def read_only_context(app_context: AppContext, fake_prompts: FakePrompts) -> Iterator[AppContext]:
    """A context over a REAL read-only connection to the same database file."""
    conn = open_database(app_context.location.database_path, read_only=True)
    context = AppContext(
        conn=conn,
        clock=app_context.clock,
        location=app_context.location,
        prompts=fake_prompts,
        preferences=PreferencesStore(app_context.location.path, writable=False),
        translator_manager=app_context.translator_manager,
    )
    yield context
    conn.close()
    context.conn = None
    context.deleteLater()


def _window(qtbot: QtBot, context: AppContext) -> MainWindow:
    window = MainWindow(context)
    qtbot.addWidget(window)
    return window


# --------------------------------------------------------------------------- the File menu


def test_the_file_menu_holds_the_backup_actions_then_a_separator_then_quit(
    app_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, app_context)
    entries = window.file_menu.actions()
    assert [entry.objectName() for entry in entries] == MENU_NAMES
    assert [entry.isSeparator() for entry in entries] == [False, False, False, True, False]
    backup, restore, open_folder = entries[:3]
    assert backup is window.backup_actions.backup_action
    assert restore is window.backup_actions.restore_action
    assert open_folder is window.backup_actions.open_folder_action
    assert entries[4] is window.quit_action


def test_the_menu_texts_in_english(app_context: AppContext, qtbot: QtBot) -> None:
    window = _window(qtbot, app_context)
    texts = [entry.text() for entry in window.file_menu.actions() if not entry.isSeparator()]
    assert texts == ["Back up...", "Restore...", "Open data folder", "&Quit"]


def test_the_menu_actions_are_enabled_in_a_read_write_session(
    app_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, app_context)
    actions = window.backup_actions
    assert actions.backup_action.isEnabled()
    assert actions.restore_action.isEnabled()
    assert actions.open_folder_action.isEnabled()


def test_read_only_mode_disables_restore_but_still_allows_back_up(
    read_only_context: AppContext, qtbot: QtBot
) -> None:
    assert read_only_context.read_only
    window = _window(qtbot, read_only_context)
    actions = window.backup_actions
    assert actions.backup_action.isEnabled()
    assert not actions.restore_action.isEnabled()
    assert actions.open_folder_action.isEnabled()
    assert actions.restore_action in read_only_context.edit_targets()
    assert actions.backup_action not in read_only_context.edit_targets()
    actions.restore_action.setEnabled(True)  # read-only mode undoes it at once
    assert not actions.restore_action.isEnabled()


# --------------------------------------------------------------------------- Open data folder


def test_the_window_wires_the_one_allowed_helper(app_context: AppContext, qtbot: QtBot) -> None:
    window = _window(qtbot, app_context)
    assert window.backup_actions.open_folder is open_local_folder


def test_the_open_action_hands_the_local_data_folder_to_the_helper(
    app_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, app_context)
    opened: list[Path] = []
    window.backup_actions.open_folder = opened.append
    window.backup_actions.open_folder_action.trigger()
    assert opened == [app_context.location.path]


def test_the_open_action_works_in_read_only_mode(
    read_only_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, read_only_context)
    opened: list[Path] = []
    window.backup_actions.open_folder = opened.append
    window.backup_actions.open_folder_action.trigger()
    assert opened == [read_only_context.location.path]


# --------------------------------------------------------------------------- the helper


class _Opener:
    """Records the URLs it is given and answers with a scripted result."""

    def __init__(self, result: bool = True) -> None:
        self.urls: list[QUrl] = []
        self.result = result

    def __call__(self, url: QUrl) -> bool:
        self.urls.append(url)
        return self.result


def test_a_local_folder_is_opened_as_a_file_url(tmp_path: Path) -> None:
    opener = _Opener()
    open_local_folder(tmp_path, open_url=opener)
    assert len(opener.urls) == 1
    assert opener.urls[0].scheme() == "file"
    assert opener.urls[0].isLocalFile()
    assert Path(opener.urls[0].toLocalFile()) == tmp_path


def test_a_failing_opener_does_not_raise(tmp_path: Path) -> None:
    opener = _Opener(result=False)
    open_local_folder(tmp_path, open_url=opener)
    assert len(opener.urls) == 1


def test_a_file_is_not_opened(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("x", encoding="utf-8")
    opener = _Opener()
    open_local_folder(target, open_url=opener)
    assert opener.urls == []
    assert not is_openable_folder(target)


def test_a_missing_folder_is_not_opened(tmp_path: Path) -> None:
    opener = _Opener()
    open_local_folder(tmp_path / "missing", open_url=opener)
    assert opener.urls == []


@pytest.mark.parametrize(
    "text",
    [
        "\\\\server\\share\\data",
        "//server/share/data",
        "\\\\?\\UNC\\server\\share\\data",
        "https://example.org/data",
        "file:///C:/data",
    ],
)
def test_a_network_location_or_a_url_is_not_opened(text: str) -> None:
    opener = _Opener()
    open_local_folder(Path(text), open_url=opener)
    assert opener.urls == []
    assert not is_openable_folder(Path(text))


# --------------------------------------------------------------------------- the T0.4 guard


def test_the_helper_passes_the_guard_in_its_own_file_and_nowhere_else() -> None:
    source = Path(folders.__file__).read_text(encoding="utf-8")
    assert "QDesktopServices" in source  # non-vacuous: the allowed API is really used here
    assert check_source(source, PurePosixPath("ui/shell/folders.py")) == []
    elsewhere = check_source(source, PurePosixPath("ui/shell/other.py"))
    assert elsewhere
    assert {violation.rule for violation in elsewhere} == {"HANDOFF"}
