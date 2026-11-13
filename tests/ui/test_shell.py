# SPDX-License-Identifier: GPL-3.0-or-later
"""The shell (T1.9): start-up sequence, registries, as-of date, read-only mode, banners, prompts.

Every Accept bullet of T1.9 has a test here. The event loop is never entered; every application
started here is closed again by the ``started_app`` fixture.
"""

import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QDate
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard import app as app_module
from cbrn_dashboard.app import AppHandle, StartupHook, clock_is_suspect
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.paths import DATABASE_FILE_NAME, LocationWarning
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.services.backup import daily_backup_startup
from cbrn_dashboard.services.personnel import CourseInput, StaffInput
from cbrn_dashboard.storage import repository
from cbrn_dashboard.storage.backup import BackupKind, DatabaseIdentity, list_backups
from cbrn_dashboard.storage.db import HotJournalError, open_database
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.banners import BannerCode
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import to_qdate
from cbrn_dashboard.ui.shell.instance_lock import LOCK_FILE_NAME, InstanceLock, LockReason
from cbrn_dashboard.ui.shell.main_window import MainWindow
from cbrn_dashboard.ui.shell.registry import DialogSpec, PageSpec, SettingsSectionSpec
from tests.ui._fakes import FakePrompts, create_database, expect_handle, snapshot
from tests.ui.conftest import NOW, StartApp

pytestmark = pytest.mark.ui

PRELIMINARY = "Preliminary version \u2014 indicators not institutionally validated."
PRELIMINARY_BY_LANGUAGE = {
    "en-US": PRELIMINARY,
    "pt-BR": "Vers\u00e3o preliminar \u2014 indicadores n\u00e3o validados institucionalmente.",
    "es-ES": "Versi\u00f3n preliminar \u2014 indicadores no validados institucionalmente.",
}
DEMO_TEXT = "DEMO \u2014 fictitious data"
LOCKED_TEXT = "Another instance is already using this data folder. Close it and start again."
TOO_NEW_TEXT = "The database was written by a newer version of this application."
HOT_JOURNAL_TEXT = "The database has an unfinished write and cannot be opened read-only."
NO_DATABASE_TEXT = "The data folder is not writable and has no database, so nothing can be opened."
REAL_HOOKS = app_module.STARTUP_HOOKS


# --------------------------------------------------------------------------- helpers


def _navigation_title() -> str:
    return QCoreApplication.translate("Shell", "Navigation")


def _label_page(context: AppContext) -> QWidget:
    return QLabel("test page")


def _page(key: str, order: int = 10) -> PageSpec:
    return PageSpec(key=key, order=order, title=_navigation_title, factory=_label_page)


def _section(key: str, group: str) -> SettingsSectionSpec:
    return SettingsSectionSpec(key=key, group=group, title=_navigation_title, factory=_label_page)


def _dialog_factory(context: AppContext, parent: QWidget | None) -> QDialog:
    return QDialog(parent)


def _dialog(key: str) -> DialogSpec:
    return DialogSpec(key=key, factory=_dialog_factory)


def _hook(log: list[str], name: str, **flags: bool) -> StartupHook:
    def run(context: AppContext) -> None:
        log.append(name)

    return StartupHook(name, run, **flags)


def _banners(handle: AppHandle) -> tuple[str, ...]:
    return handle.window.banners.visible_codes()


def _read_only_app(started_app: StartApp, tmp_path: Path, **kwargs: object) -> AppHandle:
    """An app over an existing database in a folder reported as not writable."""
    create_database(tmp_path)
    return expect_handle(started_app(writable=False, **kwargs))


def _write_change_row(path: Path, iso_utc: str) -> None:
    """Add one ``change_log`` row stamped by a clock at ``iso_utc`` (through the helpers)."""
    conn = open_database(path)
    try:
        context = WriteContext(conn, FixedClock.at(iso_utc), "")
        repository.insert(context, "setting", {"key": "probe", "value_json": "1"})
    finally:
        conn.close()


# --------------------------------------------------------------------------- pages


def test_a_registered_page_appears_in_the_navigation(started_app: StartApp) -> None:
    with registry.registered(_page("beta", order=20), _page("alpha", order=10)):
        handle = expect_handle(started_app())
    window = handle.window
    assert window.page_keys() == ("alpha", "beta")
    assert window.navigation.count() == 2
    assert window.pages.count() == 2
    assert window.navigation.item(0).text() == "Navigation"
    assert window.pages.currentWidget() is window.page_widget("alpha")
    window.navigation.setCurrentRow(1)
    assert window.pages.currentWidget() is window.page_widget("beta")


def test_the_navigation_title_follows_a_language_switch(started_app: StartApp) -> None:
    with registry.registered(_page("alpha")):
        handle = expect_handle(started_app(lang="en-US"))
    item = handle.window.navigation.item(0)
    assert item.text() == "Navigation"
    handle.window.language_actions["pt_BR"].trigger()
    assert item.text() == "Navega\u00e7\u00e3o"
    handle.window.language_actions["es_ES"].trigger()
    assert item.text() == "Navegaci\u00f3n"


def test_pages_are_registered_temporarily_only() -> None:
    before = registry.pages()
    with registry.registered(_page("temporary")):
        keys = [spec.key for spec in registry.pages()]
        assert "temporary" in keys
        assert len(keys) == len(before) + 1
    assert registry.pages() == before


# --------------------------------------------------------------------------- registries


def test_settings_sections_and_dialogs_are_returned_by_their_registries() -> None:
    backup = _section("backup_section", "backup")
    personnel = _section("personnel_section", "personnel")
    dialog = _dialog("test_dialog")
    sections_before = registry.settings_sections()
    dialogs_before = registry.dialogs()
    with registry.registered(backup, personnel, dialog):
        assert registry.settings_sections() == (*sections_before, backup, personnel)
        assert registry.settings_sections("backup") == (backup,)
        assert registry.settings_sections("personnel") == (personnel,)
        assert registry.settings_sections("reports") == ()
        assert registry.dialogs() == (*dialogs_before, dialog)
    assert registry.settings_sections() == sections_before
    assert registry.dialogs() == dialogs_before


def test_duplicate_keys_are_rejected_in_every_registry() -> None:
    with registry.registered(_page("same"), _section("same", "general"), _dialog("same")):
        with pytest.raises(registry.DuplicateKeyError):
            registry.register_page(_page("same", order=99))
        with pytest.raises(registry.DuplicateKeyError):
            registry.register_settings_section(_section("same", "backup"))
        with pytest.raises(registry.DuplicateKeyError):
            registry.register_dialog(_dialog("same"))
        # A rejected registration leaves nothing behind.
        assert [spec.key for spec in registry.pages()].count("same") == 1
    with pytest.raises(registry.DuplicateKeyError), registry.registered(_page("x"), _page("x")):
        pass
    assert "x" not in [spec.key for spec in registry.pages()]


def test_a_dialog_factory_builds_a_dialog(app_context: AppContext, qtbot: QtBot) -> None:
    with registry.registered(_dialog("built")):
        spec = next(spec for spec in registry.dialogs() if spec.key == "built")
        dialog = spec.factory(app_context, None)
        qtbot.addWidget(dialog)
        assert isinstance(dialog, QDialog)


# --------------------------------------------------------------------------- start-up hooks


def test_hooks_run_once_in_order(started_app: StartApp) -> None:
    log: list[str] = []
    handle = expect_handle(
        started_app(hooks=[_hook(log, "first"), _hook(log, "second"), _hook(log, "third")])
    )
    assert log == ["first", "second", "third"]
    assert handle.hooks_run == ("first", "second", "third")


def test_a_hook_receives_the_context(started_app: StartApp) -> None:
    seen: list[AppContext] = []
    hook = StartupHook("probe", seen.append)
    handle = expect_handle(started_app(hooks=[hook]))
    assert seen == [handle.context]


def test_a_hook_that_does_not_run_read_only_is_skipped(
    started_app: StartApp, tmp_path: Path
) -> None:
    log: list[str] = []
    hooks = [
        _hook(log, "writes"),
        _hook(log, "reads", runs_read_only=True),
    ]
    handle = _read_only_app(started_app, tmp_path, hooks=hooks)
    assert handle.context.read_only
    assert log == ["reads"]
    assert handle.hooks_run == ("reads",)


def test_a_hook_that_does_not_run_in_demo_is_skipped(started_app: StartApp) -> None:
    log: list[str] = []
    hooks = [_hook(log, "real_only"), _hook(log, "also_demo", runs_in_demo=True)]
    handle = expect_handle(started_app(demo=True, hooks=hooks))
    assert handle.context.is_demo
    assert log == ["also_demo"]


def test_all_hooks_run_in_a_plain_read_write_session(started_app: StartApp) -> None:
    log: list[str] = []
    hooks = [_hook(log, "a"), _hook(log, "b", runs_read_only=True, runs_in_demo=True)]
    expect_handle(started_app(hooks=hooks))
    assert log == ["a", "b"]


def test_a_failing_hook_is_logged_and_does_not_stop_start_up(started_app: StartApp) -> None:
    log: list[str] = []

    def fail(context: AppContext) -> None:
        raise ValueError("DEMO-ZEBRA-7731")

    handle = expect_handle(
        started_app(hooks=[StartupHook("bad", fail), _hook(log, "after")]),
    )
    assert log == ["after"]
    assert "after" in handle.hooks_run
    handle.logging.handler.flush()
    assert handle.logging.path is not None
    text = handle.logging.path.read_text(encoding="utf-8")
    assert "APP.STARTUP_HOOK_FAILED" in text
    assert "ValueError" in text
    assert "ZEBRA" not in text


def test_the_hook_registry_is_a_plain_tuple_of_hooks() -> None:
    assert isinstance(app_module.STARTUP_HOOKS, tuple)
    assert all(isinstance(hook, StartupHook) for hook in app_module.STARTUP_HOOKS)


# --------------------------------------------------------------------------- the daily backup hook
#
# The ``started_app`` factory always passes ``hooks=`` (default: none) to ``start``, so these tests
# hand it the REAL registry explicitly instead of relying on ``start``'s own default.


def _daily_files(folder: Path) -> list[Path]:
    return sorted((folder / "backups").glob("daily-*.sqlite3"))


def test_the_daily_backup_is_the_only_registered_hook_and_declares_its_modes() -> None:
    [hook] = app_module.STARTUP_HOOKS
    assert hook.name == "daily-backup"
    assert hook.run is daily_backup_startup
    assert hook.runs_read_only is False
    assert hook.runs_in_demo is False
    assert hook.needs_trusted_clock is False


def test_a_normal_start_makes_one_daily_backup(started_app: StartApp, tmp_path: Path) -> None:
    handle = expect_handle(started_app(hooks=REAL_HOOKS))
    assert handle.hooks_run == ("daily-backup",)
    # The database was created and migrated by this very start (so the pre-migration helper had
    # nothing to copy), yet the daily backup is made: it does not skip a database without rows.
    [backup] = _daily_files(tmp_path)
    assert backup.name.startswith("daily-20260305T120000Z-v")
    assert [entry.name for entry in (tmp_path / "backups").iterdir()] == [backup.name]
    [info] = list_backups(tmp_path, DatabaseIdentity.REAL, BackupKind.DAILY)
    assert info.path == backup


def test_several_starts_on_the_same_local_day_make_one_daily_backup(
    started_app: StartApp, tmp_path: Path
) -> None:
    expect_handle(started_app(hooks=REAL_HOOKS)).close()
    expect_handle(
        started_app(hooks=REAL_HOOKS, clock=FixedClock.at("2026-03-05T20:30:00Z"))
    ).close()
    expect_handle(started_app(hooks=REAL_HOOKS))
    assert len(_daily_files(tmp_path)) == 1


def test_a_start_on_the_next_local_day_makes_a_second_daily_backup(
    started_app: StartApp, tmp_path: Path
) -> None:
    expect_handle(started_app(hooks=REAL_HOOKS)).close()
    tomorrow = FixedClock.at(NOW).advanced(timedelta(days=1))
    expect_handle(started_app(hooks=REAL_HOOKS, clock=tomorrow))
    names = [path.name for path in _daily_files(tmp_path)]
    assert len(names) == 2
    assert names[0].startswith("daily-20260305T120000Z-v")
    assert names[1].startswith("daily-20260306T120000Z-v")


def test_a_read_only_start_makes_no_daily_backup_and_writes_nothing(
    started_app: StartApp, tmp_path: Path
) -> None:
    create_database(tmp_path)
    before = snapshot(tmp_path)
    handle = expect_handle(started_app(writable=False, hooks=REAL_HOOKS))
    assert handle.context.read_only
    assert handle.hooks_run == ()
    assert not (tmp_path / "backups").exists()
    assert snapshot(tmp_path) == before
    handle.close()
    assert snapshot(tmp_path) == before


def test_a_demo_start_makes_no_daily_backup_anywhere(started_app: StartApp, tmp_path: Path) -> None:
    handle = expect_handle(started_app(demo=True, hooks=REAL_HOOKS))
    assert handle.context.is_demo
    assert handle.hooks_run == ()
    assert not (tmp_path / "backups").exists()
    assert not (tmp_path / "demo" / "backups").exists()
    assert list(tmp_path.rglob("daily-*")) == []


def test_a_database_flagged_demo_gets_no_daily_backup_either(
    started_app: StartApp, tmp_path: Path
) -> None:
    create_database(tmp_path, is_demo=True)  # opened through the NORMAL path (no --demo)
    handle = expect_handle(started_app(hooks=REAL_HOOKS))
    assert handle.context.is_demo
    assert handle.hooks_run == ()
    assert list(tmp_path.rglob("daily-*")) == []


def _old_daily_files(folder: Path, count: int) -> list[Path]:
    """``count`` daily backups dated on earlier days (February 2026), with parseable names."""
    pool = folder / "backups"
    pool.mkdir(parents=True, exist_ok=True)
    paths = [pool / f"daily-202602{day:02d}T120000Z-v0001.sqlite3" for day in range(1, count + 1)]
    for path in paths:
        path.write_bytes(b"old copy")
    return paths


def test_a_suspect_clock_still_makes_the_daily_backup_but_does_not_rotate(
    started_app: StartApp, tmp_path: Path
) -> None:
    path = create_database(tmp_path)
    _write_change_row(path, "2026-06-01T00:00:00Z")  # newer than the clock: the clock is suspect
    old = _old_daily_files(tmp_path, 9)

    handle = expect_handle(started_app(hooks=REAL_HOOKS))

    assert handle.context.clock_suspect
    assert handle.hooks_run == ("daily-backup",)
    files = _daily_files(tmp_path)
    assert len(files) == 10
    assert all(kept in files for kept in old)
    assert any(f.name.startswith("daily-20260305T120000Z-v") for f in files)


def test_a_trusted_clock_rotates_the_daily_backups(started_app: StartApp, tmp_path: Path) -> None:
    create_database(tmp_path)  # no change_log row: the clock is trusted
    old = _old_daily_files(tmp_path, 9)

    handle = expect_handle(started_app(hooks=REAL_HOOKS))

    assert not handle.context.clock_suspect
    files = _daily_files(tmp_path)
    assert len(files) == ReadinessConfig().daily_backups_kept
    assert any(f.name.startswith("daily-20260305T120000Z-v") for f in files)  # the new one stays
    assert not old[0].exists()  # the oldest went


# --------------------------------------------------------------------------- the as-of date


def test_the_as_of_date_defaults_to_the_local_date(app_context: AppContext) -> None:
    assert app_context.as_of == date(2026, 3, 5)


def test_changing_the_as_of_date_emits_exactly_one_signal(app_context: AppContext) -> None:
    seen: list[date] = []
    app_context.as_of_changed.connect(seen.append)

    app_context.set_as_of(date(2026, 4, 1))
    assert seen == [date(2026, 4, 1)]
    assert app_context.as_of == date(2026, 4, 1)

    app_context.set_as_of(date(2026, 4, 1))  # the same date: nothing
    assert seen == [date(2026, 4, 1)]

    app_context.reset_as_of()
    assert seen == [date(2026, 4, 1), date(2026, 3, 5)]
    assert app_context.as_of == date(2026, 3, 5)

    app_context.reset_as_of()  # already today: nothing
    app_context.set_as_of(date(2026, 3, 5))  # the effective value does not change: nothing
    assert len(seen) == 2


def test_the_as_of_date_must_be_a_date(app_context: AppContext) -> None:
    with pytest.raises(TypeError):
        app_context.set_as_of(datetime(2026, 4, 1, tzinfo=UTC))


def test_the_toolbar_selector_and_the_context_stay_in_sync(started_app: StartApp) -> None:
    handle = expect_handle(started_app())
    context, window = handle.context, handle.window
    seen: list[date] = []
    context.as_of_changed.connect(seen.append)
    assert window.as_of_edit.date() == QDate(2026, 3, 5)
    assert window.as_of_edit.calendarPopup()

    context.set_as_of(date(2026, 5, 17))  # context -> selector, one signal
    assert window.as_of_edit.date() == QDate(2026, 5, 17)
    assert seen == [date(2026, 5, 17)]

    window.as_of_edit.setDate(QDate(2026, 6, 2))  # selector -> context, one signal
    assert context.as_of == date(2026, 6, 2)
    assert seen == [date(2026, 5, 17), date(2026, 6, 2)]

    window.today_action.trigger()  # the "Today" action
    assert context.as_of == date(2026, 3, 5)
    assert window.as_of_edit.date() == to_qdate(date(2026, 3, 5))
    assert seen[-1] == date(2026, 3, 5)
    assert len(seen) == 3


def test_the_selector_follows_the_language(started_app: StartApp) -> None:
    handle = expect_handle(started_app(lang="en-US"))
    edit = handle.window.as_of_edit
    assert edit.displayFormat() == "MM/dd/yyyy"
    handle.window.language_actions["pt_BR"].trigger()
    assert edit.displayFormat() == "dd/MM/yyyy"
    assert edit.locale().name() == "pt_BR"
    assert handle.window.today_action.text() == "Hoje"


# --------------------------------------------------------------------------- read-only mode


def test_read_only_mode_disables_every_registered_edit_action(
    started_app: StartApp, tmp_path: Path
) -> None:
    handle = _read_only_app(started_app, tmp_path)
    context = handle.context
    action = QAction("edit", handle.window)
    button = QPushButton("edit", handle.window)
    context.register_edit_action(action)
    context.register_edit_action(button)
    assert context.read_only
    assert not action.isEnabled()
    assert not button.isEnabled()

    context.set_edit_enabled(action, True)  # asking to enable it changes nothing
    context.set_edit_enabled(button, True)
    assert not action.isEnabled()
    assert not button.isEnabled()
    assert context.edit_targets() == (action, button)


def test_edit_actions_work_in_read_write_mode(started_app: StartApp) -> None:
    handle = expect_handle(started_app())
    context = handle.context
    action = QAction("edit", handle.window)
    context.register_edit_action(action)
    assert not context.read_only
    assert action.isEnabled()
    context.set_edit_enabled(action, False)
    assert not action.isEnabled()
    context.set_edit_enabled(action, True)
    assert action.isEnabled()


def test_read_only_mode_shows_the_banner_takes_no_lock_and_writes_nothing(
    started_app: StartApp, tmp_path: Path
) -> None:
    create_database(tmp_path)
    before = snapshot(tmp_path)
    handle = expect_handle(started_app(writable=False, lang="en-US"))

    assert handle.context.read_only
    assert handle.context.conn is not None
    assert handle.context.conn.read_only
    assert BannerCode.READ_ONLY.value in _banners(handle)
    assert handle.window.banners.text("READ_ONLY").startswith("Read-only mode")
    assert handle.instance_lock is None
    assert not (tmp_path / LOCK_FILE_NAME).exists()
    assert handle.logging.in_memory
    assert handle.logging.path is None
    assert snapshot(tmp_path) == before

    handle.window.language_actions["es_ES"].trigger()  # preferences stay in memory too
    assert handle.preferences.current.language == "es_ES"
    assert not handle.preferences.persisted
    assert snapshot(tmp_path) == before

    handle.close()
    assert snapshot(tmp_path) == before


def test_a_read_write_start_takes_the_lock(started_app: StartApp, tmp_path: Path) -> None:
    handle = expect_handle(started_app())
    assert handle.instance_lock is not None
    assert handle.instance_lock.held
    assert (tmp_path / LOCK_FILE_NAME).is_file()
    assert BannerCode.READ_ONLY.value not in _banners(handle)
    handle.close()
    assert not handle.instance_lock.held


def test_an_unwritable_folder_without_a_database_is_explained(
    started_app: StartApp, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    assert started_app(writable=False) == 1
    [call] = fake_prompts.calls_of("error")
    assert call.title == "Cannot start"
    assert call.text == NO_DATABASE_TEXT
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- the instance lock


def test_a_second_instance_is_refused_without_opening_the_database(
    started_app: StartApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = expect_handle(started_app())
    database = tmp_path / DATABASE_FILE_NAME
    before_bytes = database.read_bytes()
    before_mtime = database.stat().st_mtime_ns
    opened: list[str] = []

    def spy(*args: object, **kwargs: object) -> None:
        opened.append("opened")
        raise AssertionError("the database must not be opened")

    monkeypatch.setattr(app_module, "open_and_migrate", spy)
    monkeypatch.setattr(app_module, "open_database", spy)
    monkeypatch.setattr(app_module, "open_demo_database", spy)

    second_prompts = FakePrompts()
    assert started_app(prompts=second_prompts) == 1

    [call] = second_prompts.calls_of("error")
    assert call.title == "Cannot start"
    assert call.text == LOCKED_TEXT
    assert opened == []
    assert database.read_bytes() == before_bytes
    assert database.stat().st_mtime_ns == before_mtime
    assert first.instance_lock is not None
    assert first.instance_lock.held  # the first instance keeps working


def test_the_lock_is_translated(started_app: StartApp) -> None:
    expect_handle(started_app())
    prompts = FakePrompts()
    assert started_app(prompts=prompts, lang="pt-BR") == 1
    assert prompts.calls_of("error")[0].text == (
        "Outra inst\u00e2ncia j\u00e1 est\u00e1 usando esta pasta de dados. "
        "Feche-a e inicie novamente."
    )


def test_the_lock_is_released_by_close(started_app: StartApp) -> None:
    first = expect_handle(started_app())
    first.close()
    second = expect_handle(started_app())
    assert second.instance_lock is not None
    assert second.instance_lock.held


def test_close_can_be_called_twice(started_app: StartApp) -> None:
    handle = expect_handle(started_app())
    handle.close()
    handle.close()
    assert handle.context.conn is None


class TestInstanceLock:
    def test_acquire_twice_the_second_is_refused(self, tmp_path: Path) -> None:
        first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
        assert first.acquire()
        assert first.held
        assert first.reason is None
        assert not second.acquire()
        assert not second.held
        assert second.reason is LockReason.LOCKED
        first.release()

    def test_release_makes_it_acquirable_again(self, tmp_path: Path) -> None:
        first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
        assert first.acquire()
        first.release()
        assert not first.held
        assert (tmp_path / LOCK_FILE_NAME).is_file()  # the file stays; it holds no data
        assert second.acquire()
        second.release()
        assert first.acquire()
        first.release()

    def test_acquire_is_idempotent_and_release_harmless(self, tmp_path: Path) -> None:
        lock = InstanceLock(tmp_path)
        lock.release()  # not held
        assert lock.acquire()
        assert lock.acquire()
        lock.release()
        lock.release()
        assert not lock.held

    def test_context_manager(self, tmp_path: Path) -> None:
        with InstanceLock(tmp_path) as lock:
            assert lock.held
            assert not InstanceLock(tmp_path).acquire()
        assert not lock.held
        with InstanceLock(tmp_path) as again:
            assert again.held

    def test_an_unusable_folder_reports_unavailable(self, tmp_path: Path) -> None:
        lock = InstanceLock(tmp_path / "missing")
        assert not lock.acquire()
        assert lock.reason is LockReason.UNAVAILABLE
        assert not lock.held


# --------------------------------------------------------------------------- the clock check


def test_a_clock_earlier_than_the_newest_change_raises_the_banner(
    started_app: StartApp, tmp_path: Path
) -> None:
    path = create_database(tmp_path)
    _write_change_row(path, "2026-06-01T00:00:00Z")
    log: list[str] = []
    hooks = [
        _hook(log, "snapshot", needs_trusted_clock=True),
        _hook(log, "rotation", needs_trusted_clock=True),
        _hook(log, "plain"),
    ]
    handle = expect_handle(started_app(clock=FixedClock.at("2026-03-05T12:00:00Z"), hooks=hooks))
    assert handle.context.clock_suspect
    assert BannerCode.CLOCK_SUSPECT.value in _banners(handle)
    assert log == ["plain"]


def test_a_trusted_clock_runs_every_hook(started_app: StartApp, tmp_path: Path) -> None:
    path = create_database(tmp_path)
    _write_change_row(path, "2026-03-01T00:00:00Z")
    log: list[str] = []
    hooks = [_hook(log, "snapshot", needs_trusted_clock=True), _hook(log, "plain")]
    handle = expect_handle(started_app(clock=FixedClock.at("2026-03-05T12:00:00Z"), hooks=hooks))
    assert not handle.context.clock_suspect
    assert BannerCode.CLOCK_SUSPECT.value not in _banners(handle)
    assert log == ["snapshot", "plain"]


def test_a_clock_earlier_than_the_build_time_is_suspect(tmp_path: Path) -> None:
    conn = open_database(create_database(tmp_path))
    try:
        clock = FixedClock.at("2026-03-05T12:00:00Z")
        later = datetime(2026, 4, 1, tzinfo=UTC)
        earlier = datetime(2026, 1, 1, tzinfo=UTC)
        assert clock_is_suspect(conn, clock, lambda: later)
        assert not clock_is_suspect(conn, clock, lambda: earlier)
        assert not clock_is_suspect(conn, clock, lambda: None)  # running from source
    finally:
        conn.close()


# --------------------------------------------------------------------------- demo and notice


def test_a_database_flagged_demo_shows_the_banner_whatever_the_command_line(
    started_app: StartApp, tmp_path: Path
) -> None:
    create_database(tmp_path, is_demo=True)  # opened through the NORMAL path (no --demo)
    handle = expect_handle(started_app(demo=False))
    assert handle.context.is_demo
    assert handle.is_demo
    assert BannerCode.DEMO.value in _banners(handle)
    assert handle.window.banners.text("DEMO") == DEMO_TEXT


def test_the_demo_option_shows_the_banner_and_leaves_the_real_database_alone(
    started_app: StartApp, tmp_path: Path
) -> None:
    handle = expect_handle(started_app(demo=True))
    assert handle.context.is_demo
    assert BannerCode.DEMO.value in _banners(handle)
    assert not (tmp_path / DATABASE_FILE_NAME).exists()


def test_a_real_database_has_no_demo_banner(started_app: StartApp) -> None:
    handle = expect_handle(started_app(demo=False))
    assert not handle.context.is_demo
    assert BannerCode.DEMO.value not in _banners(handle)


@pytest.mark.parametrize("mode", ["real", "demo", "read_only"])
def test_the_preliminary_notice_is_always_visible_and_cannot_be_hidden(
    started_app: StartApp, tmp_path: Path, mode: str
) -> None:
    if mode == "read_only":
        handle = _read_only_app(started_app, tmp_path)
    else:
        handle = expect_handle(started_app(demo=mode == "demo"))
    banners = handle.window.banners
    assert "PRELIMINARY" in banners.visible_codes()
    assert banners.text("PRELIMINARY") == PRELIMINARY
    banners.hide_banner("PRELIMINARY")
    assert "PRELIMINARY" in banners.visible_codes()
    assert banners.findChild(QLabel, "banner_text_PRELIMINARY") is not None


@pytest.mark.parametrize("lang", sorted(PRELIMINARY_BY_LANGUAGE))
def test_the_preliminary_wording_in_three_languages(started_app: StartApp, lang: str) -> None:
    handle = expect_handle(started_app(lang=lang))
    assert handle.window.banners.text("PRELIMINARY") == PRELIMINARY_BY_LANGUAGE[lang]


def test_the_preliminary_notice_follows_a_language_switch(started_app: StartApp) -> None:
    handle = expect_handle(started_app(lang="en-US"))
    handle.window.language_actions["pt_BR"].trigger()
    assert handle.window.banners.text("PRELIMINARY") == PRELIMINARY_BY_LANGUAGE["pt-BR"]


def test_location_warnings_get_a_banner_each(started_app: StartApp) -> None:
    warnings = (
        LocationWarning.NETWORK_PATH,
        LocationWarning.ONEDRIVE,
        LocationWarning.POINTER_INVALID,
        LocationWarning.NO_PROFILE_DIR,
    )
    handle = expect_handle(started_app(warnings=warnings))
    visible = _banners(handle)
    for code in ("NETWORK_PATH", "ONEDRIVE", "POINTER_INVALID", "NO_PROFILE_DIR"):
        assert code in visible
        assert handle.window.banners.text(code)
    assert visible[-1] == "PRELIMINARY"


def test_banners_can_be_shown_and_hidden(started_app: StartApp) -> None:
    banners = expect_handle(started_app()).window.banners
    assert banners.visible_codes() == ("PRELIMINARY",)
    banners.show_banner("CLOCK_SUSPECT")
    assert banners.visible_codes() == ("CLOCK_SUSPECT", "PRELIMINARY")
    banners.hide_banner("CLOCK_SUSPECT")
    assert banners.visible_codes() == ("PRELIMINARY",)
    with pytest.raises(ValueError, match="NOPE"):
        banners.show_banner("NOPE")


def test_missing_translations_are_shown_once_in_the_banner_area(
    started_app: StartApp, tmp_path: Path
) -> None:
    handle = expect_handle(started_app(qm=tmp_path / "no-qm", data_dir=tmp_path / "data"))
    assert "TRANSLATIONS_MISSING" in _banners(handle)
    assert handle.window.banners.text("TRANSLATIONS_MISSING") == (
        "Translations are not compiled: the English source text is shown."
    )
    assert handle.window.findChild(QLabel, "translations_warning_label") is None


def test_compiled_translations_show_no_warning(started_app: StartApp) -> None:
    handle = expect_handle(started_app())
    assert "TRANSLATIONS_MISSING" not in _banners(handle)


# --------------------------------------------------------------------------- database problems


@pytest.mark.parametrize("writable", [True, False])
def test_a_newer_schema_is_explained_and_the_file_is_untouched(
    started_app: StartApp, tmp_path: Path, fake_prompts: FakePrompts, writable: bool
) -> None:
    path = create_database(tmp_path)
    conn = open_database(path)
    conn.execute("PRAGMA user_version = 9999")
    conn.close()
    before_bytes = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    assert started_app(writable=writable) == 1

    [call] = fake_prompts.calls_of("error")
    assert call.text == TOO_NEW_TEXT
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime
    assert not (tmp_path / "backups").exists()


def test_a_hot_journal_in_read_only_mode_is_explained(
    started_app: StartApp,
    tmp_path: Path,
    fake_prompts: FakePrompts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_database(tmp_path)
    before = snapshot(tmp_path)

    def hot(*args: object, **kwargs: object) -> None:
        raise HotJournalError("hot")

    monkeypatch.setattr(app_module, "open_database", hot)
    assert started_app(writable=False) == 1
    [call] = fake_prompts.calls_of("error")
    assert call.title == "Cannot start"
    assert call.text == HOT_JOURNAL_TEXT
    assert snapshot(tmp_path) == before


def test_another_database_failure_shows_a_code_only(
    started_app: StartApp,
    tmp_path: Path,
    fake_prompts: FakePrompts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise OSError("DEMO-ZEBRA-7731")

    monkeypatch.setattr(app_module, "open_and_migrate", broken)
    assert started_app() == 1
    [call] = fake_prompts.calls_of("error")
    assert re.fullmatch(r"The database could not be opened\. Code: E-[0-9a-f]{8}", call.text)
    assert "ZEBRA" not in call.text


# --------------------------------------------------------------------------- the crash callback


def test_the_crash_callback_shows_a_code_and_never_the_message(
    started_app: StartApp, fake_prompts: FakePrompts
) -> None:
    handle = expect_handle(started_app())
    sys.excepthook(ValueError, ValueError("DEMO-ZEBRA-7731"), None)

    [call] = fake_prompts.calls_of("error")
    assert call.title == "Unexpected error"
    assert re.fullmatch(r"An unexpected error occurred\. Code: E-[0-9a-f]{8}", call.text)
    assert "ZEBRA" not in call.text
    assert "ZEBRA" not in call.title
    handle.logging.handler.flush()
    assert handle.logging.path is not None
    log = handle.logging.path.read_text(encoding="utf-8")
    assert "APP.UNHANDLED_EXCEPTION" in log
    assert "ZEBRA" not in log


def test_close_uninstalls_the_exception_hook(started_app: StartApp) -> None:
    before = sys.excepthook
    handle = expect_handle(started_app())
    assert sys.excepthook is not before
    handle.close()
    assert sys.excepthook is before


# --------------------------------------------------------------------------- context and window


def test_the_context_has_the_services_over_the_open_database(app_context: AppContext) -> None:
    services = app_context.services
    assert services.personnel is not None
    assert services.infrastructure is not None
    assert services.exercises is not None
    assert services.budget is not None
    assert services.indicators is not None
    assert services.alerts is not None
    assert not app_context.read_only
    assert not app_context.is_demo
    assert not app_context.clock_suspect
    app_context.set_operator_label("operator")
    assert app_context.operator_label() == "operator"


def test_the_services_share_the_connection_and_the_clock_of_the_context(
    app_context: AppContext,
) -> None:
    services = app_context.services
    assert services.personnel is not None
    assert services.infrastructure is not None
    assert services.exercises is not None
    assert services.budget is not None
    assert services.indicators is not None
    for service in (
        services.personnel,
        services.infrastructure,
        services.exercises,
        services.budget,
        services.indicators,
    ):
        assert service._conn is app_context.conn
        assert service._clock is app_context.clock

    # the indicator and alert services read what the module services wrote
    services.personnel.create_staff(StaffInput("DEMO-P001", "2020-01-01"))
    assert services.alerts is not None
    assert services.alerts.alerts(date(2026, 3, 5)) == []
    assert services.indicators.evaluate(date(2026, 3, 5))


def test_the_operator_label_reaches_the_writes_of_the_services(app_context: AppContext) -> None:
    assert app_context.conn is not None
    assert app_context.services.personnel is not None

    def last_operator() -> object:
        assert app_context.conn is not None
        row = app_context.conn.execute(
            "SELECT operator, at_utc FROM change_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row[1] == NOW
        return row[0]

    app_context.services.personnel.create_course(CourseInput("DEMO-C1", "Curso Demo"))
    assert last_operator() == ""
    # the label is read when a write happens, not when the services are built
    app_context.set_operator_label("op-demo")
    app_context.services.personnel.create_course(CourseInput("DEMO-C2", "Curso Demo 2"))
    assert last_operator() == "op-demo"


def test_data_changed_is_emitted_by_notify(app_context: AppContext) -> None:
    seen: list[bool] = []
    app_context.data_changed.connect(lambda: seen.append(True))
    app_context.notify_data_changed()
    assert seen == [True]


def test_a_context_without_a_database_has_no_services(
    qapp: QApplication,
    qtbot: QtBot,
    app_context: AppContext,
    tmp_path: Path,
    fake_prompts: FakePrompts,
) -> None:
    """The self-test builds the window like this: no database, no lock, no services."""
    bare = AppContext(
        conn=None,
        clock=FixedClock.at("2026-03-05T12:00:00Z"),
        location=app_context.location,
        prompts=fake_prompts,
        preferences=PreferencesStore(tmp_path, writable=False),
        translator_manager=app_context.translator_manager,
    )
    services = bare.services
    assert services.personnel is None
    assert services.infrastructure is None
    assert services.exercises is None
    assert services.budget is None
    assert services.indicators is None
    assert services.alerts is None
    assert not bare.is_demo
    assert not bare.read_only
    window = MainWindow(bare)
    qtbot.addWidget(window)
    assert window.windowTitle() == "CBRN Readiness Dashboard"
    assert window.banners.visible_codes() == ("PRELIMINARY",)


def test_fake_prompts_record_calls_and_use_scripted_answers(fake_prompts: FakePrompts) -> None:
    assert fake_prompts.confirm(None, "t", "q") is False
    assert fake_prompts.open_file(None, "t", "*.db") is None
    assert fake_prompts.save_file(None, "t", "name", "*.db") is None
    assert fake_prompts.choose_folder(None, "t") is None
    assert fake_prompts.text_input(None, "t", "label", password=True) is None
    fake_prompts.script("confirm", True)
    fake_prompts.script("choose_folder", Path("somewhere"))
    assert fake_prompts.confirm(None, "t", "q") is True
    assert fake_prompts.confirm(None, "t", "q") is False
    assert fake_prompts.choose_folder(None, "t") == Path("somewhere")
    fake_prompts.info(None, "title", "text")
    assert [call.method for call in fake_prompts.calls][-1] == "info"
    assert fake_prompts.calls_of("info")[0].text == "text"
