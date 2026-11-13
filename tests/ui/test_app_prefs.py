# SPDX-License-Identifier: GPL-3.0-or-later
"""Application language and preferences (T1.5): saved language, ``--lang`` override, read-only.

The event loop is never entered; every application built here is torn down again.
"""

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from cbrn_dashboard.app import AppHandle, main, start
from cbrn_dashboard.cli import CliOptions
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.paths import DATABASE_FILE_NAME, DataLocation, LocationSource
from cbrn_dashboard.prefs import PREFS_FILE_NAME, PreferencesStore, PreferencesWarning
from cbrn_dashboard.ui.shell.instance_lock import LOCK_FILE_NAME
from tests.ui._fakes import FakePrompts, create_database, expect_handle, snapshot

pytestmark = pytest.mark.ui

type MakeApp = Callable[..., AppHandle]

#: What a read-write start legitimately creates in an empty data folder (T1.9): the database, the
#: instance lock file and the log folder. ``prefs.json`` is NOT among them.
STARTED_FILES = {DATABASE_FILE_NAME, LOCK_FILE_NAME, "logs"}


def _prefs_file(folder: Path) -> Path:
    return folder / PREFS_FILE_NAME


def _stored_language(folder: Path) -> object:
    return json.loads(_prefs_file(folder).read_text(encoding="utf-8"))["language"]


@pytest.fixture
def make_app(qapp: QApplication, qm_dir: Path, tmp_path: Path, qtbot: QtBot) -> Iterator[MakeApp]:
    """Start the application on ``tmp_path``; ``close_all`` tears every started one down.

    A start with ``writable=False`` needs a database to open read-only: it is created first when
    there is none (a start never creates one in a folder reported as not writable).
    """
    handles: list[AppHandle] = []

    def close_all() -> None:
        for handle in reversed(handles):
            handle.close()
        handles.clear()

    def make(lang: str | None = None, *, writable: bool = True, fresh: bool = True) -> AppHandle:
        if fresh:
            close_all()  # one application at a time, like a real start
        if not writable and not (tmp_path / DATABASE_FILE_NAME).exists():
            create_database(tmp_path)
        options = CliOptions(data_dir=str(tmp_path), lang=lang, self_test=False)
        location = DataLocation(path=tmp_path, source=LocationSource.CLI, writable=writable)
        result = start(
            options,
            location,
            clock=FixedClock.at("2026-03-05T12:00:00Z"),
            prompts=FakePrompts(),
            qm_dir=qm_dir,
            hooks=(),
        )
        handle = expect_handle(result)
        qtbot.addWidget(handle.window)
        handles.append(handle)
        return handle

    yield make
    close_all()


def test_no_preference_means_portuguese_and_no_preferences_file_is_written(
    make_app: MakeApp, tmp_path: Path
) -> None:
    handle = make_app()
    assert handle.translator_manager.current_language == "pt_BR"
    assert isinstance(handle.preferences, PreferencesStore)
    assert handle.preferences.current.language == "pt_BR"
    assert not _prefs_file(tmp_path).exists()
    # A read-write start creates the database, the lock file and the log folder, nothing else.
    assert {entry.name for entry in tmp_path.iterdir()} == STARTED_FILES


def test_menu_choice_is_saved_and_used_at_the_next_start(make_app: MakeApp, tmp_path: Path) -> None:
    first = make_app()
    first.window.language_actions["es_ES"].trigger()
    assert first.translator_manager.current_language == "es_ES"
    assert _stored_language(tmp_path) == "es_ES"
    assert first.preferences.current.language == "es_ES"
    assert first.preferences.persisted

    second = make_app()
    assert second.translator_manager.current_language == "es_ES"
    assert second.window.language_actions["es_ES"].isChecked()
    assert second.window.windowTitle() == "Panel de Preparación QBRN"


def test_every_later_switch_is_saved(make_app: MakeApp, tmp_path: Path) -> None:
    handle = make_app()
    for code in ("en_US", "pt_BR", "es_ES"):
        handle.window.language_actions[code].trigger()
        assert _stored_language(tmp_path) == code


def test_lang_option_overrides_for_one_run_without_saving(
    make_app: MakeApp, tmp_path: Path
) -> None:
    overridden = make_app("en-US")
    assert overridden.translator_manager.current_language == "en_US"
    assert overridden.window.windowTitle() == "CBRN Readiness Dashboard"
    assert not _prefs_file(tmp_path).exists()

    next_run = make_app()
    assert next_run.translator_manager.current_language == "pt_BR"
    assert not _prefs_file(tmp_path).exists()


def test_lang_option_does_not_replace_the_saved_language(make_app: MakeApp, tmp_path: Path) -> None:
    make_app().window.language_actions["es_ES"].trigger()
    before = _prefs_file(tmp_path).read_bytes()

    overridden = make_app("en-US")
    assert overridden.translator_manager.current_language == "en_US"
    assert _prefs_file(tmp_path).read_bytes() == before

    assert make_app().translator_manager.current_language == "es_ES"


def test_menu_switch_after_lang_option_is_saved(make_app: MakeApp, tmp_path: Path) -> None:
    handle = make_app("en-US")
    handle.window.language_actions["es_ES"].trigger()
    assert _stored_language(tmp_path) == "es_ES"
    assert make_app().translator_manager.current_language == "es_ES"


def test_corrupt_preferences_start_in_the_default_language(
    make_app: MakeApp, tmp_path: Path
) -> None:
    _prefs_file(tmp_path).write_text("{not json", encoding="utf-8")
    handle = make_app()
    assert handle.translator_manager.current_language == "pt_BR"
    assert PreferencesWarning.CORRUPT_FILE in handle.preferences.warnings


def test_read_only_folder_switches_without_error_and_writes_nothing(
    make_app: MakeApp, tmp_path: Path
) -> None:
    create_database(tmp_path)  # the database a read-only start opens
    before = snapshot(tmp_path)
    handle = make_app(writable=False)
    assert snapshot(tmp_path) == before  # starting writes nothing (no lock, no logs, no prefs)
    handle.window.language_actions["en_US"].trigger()
    assert handle.translator_manager.current_language == "en_US"
    assert handle.window.windowTitle() == "CBRN Readiness Dashboard"
    assert handle.preferences.current.language == "en_US"
    assert not handle.preferences.persisted
    assert PreferencesWarning.NOT_SAVED in handle.preferences.warnings
    assert snapshot(tmp_path) == before  # a menu switch writes nothing
    handle.close()
    assert snapshot(tmp_path) == before  # neither does closing


def test_read_only_folder_never_touches_an_existing_file(make_app: MakeApp, tmp_path: Path) -> None:
    make_app().window.language_actions["es_ES"].trigger()
    before = _prefs_file(tmp_path).read_bytes()

    handle = make_app(writable=False)
    assert handle.translator_manager.current_language == "es_ES"
    handle.window.language_actions["en_US"].trigger()
    assert handle.translator_manager.current_language == "en_US"
    assert _prefs_file(tmp_path).read_bytes() == before


def test_self_test_leaves_no_preferences_file(
    qapp: QApplication, qm_dir: Path, tmp_path: Path
) -> None:
    data = tmp_path / "selftest-data"
    assert main(["--self-test", "--data-dir", str(data)], qm_dir=qm_dir) == 0
    assert not _prefs_file(data).exists()
    assert (data / "selftest.json").is_file()
