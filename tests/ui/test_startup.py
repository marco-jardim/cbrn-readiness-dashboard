# SPDX-License-Identifier: GPL-3.0-or-later
"""The start-up sequence under failure (Phase 1 QA round 2): findings P1B-01, 06, 07, 09, 15-18,
24, 25 and 29. Everything lives below ``tmp_path``; the event loop is never entered."""

import re
import shutil
import sqlite3
import stat
import sys
from collections.abc import Callable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QApplication

from cbrn_dashboard import app as app_module
from cbrn_dashboard.app import AppHandle, StartupHook, clock_is_suspect, main, start
from cbrn_dashboard.cli import CliOptions
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import demo_database_path
from cbrn_dashboard.paths import (
    DATABASE_FILE_NAME,
    DataLocation,
    LocationSource,
    LocationWarning,
)
from cbrn_dashboard.storage.db import DatabaseConnection, DatabaseError, open_database
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.instance_lock import LOCK_FILE_NAME
from tests.ui._fakes import FakePrompts, create_database, expect_handle, snapshot
from tests.ui.conftest import NOW, StartApp

pytestmark = pytest.mark.ui

MESSAGE = "DEMO-ZEBRA-7731"

CRASH_TEXT = re.compile(r"An unexpected error occurred\. Code: E-[0-9a-f]{8}")
GENERIC_OPEN_TEXT = re.compile(r"The database could not be opened\. Code: E-[0-9a-f]{8}")

NOT_APPLICATION_TEXT = "This file is not a database of this application."
OLDER_SCHEMA_TEXT = (
    "This database was written by an older version and cannot be upgraded while it is read-only."
)
NOT_DEMO_TEXT = "The file in the demo folder is not a demo database. It was left unchanged."
LOCK_UNAVAILABLE_TEXT = (
    "The data folder cannot be locked, so the application cannot make sure it is the only one "
    "using it."
)
LOCKED_TEXT = "Another instance is already using this data folder. Close it and start again."
NO_PROFILE_TEXT = "No user profile folder was found, so there is no default data folder."

MAPPED_CODES: dict[str, str] = {
    "NOT_A_DEMO_DATABASE": NOT_DEMO_TEXT,
    "SQLITE_TOO_OLD": "The SQLite library of this installation is too old for this database.",
    "NOT_A_DATABASE": NOT_APPLICATION_TEXT,
    "DATABASE_MOVED": "The database file was moved or replaced while it was being opened.",
    "MIGRATION_FAILED": "The database could not be upgraded. The failed step was rolled back.",
    "MIGRATION_SEQUENCE": "The upgrade steps of this installation are incomplete or damaged.",
    "BACKUP_VERIFY_FAILED": (
        "The safety copy could not be verified, so the database was not upgraded."
    ),
    "HOT_JOURNAL": "The database has an unfinished write and cannot be opened read-only.",
    "DATABASE_TOO_NEW": "The database was written by a newer version of this application.",
}


class _CodedError(DatabaseError):
    """A storage error with a chosen ``code`` and a message that must never reach the user."""

    def __init__(self, code: str) -> None:
        super().__init__(MESSAGE)
        self.code = code


def _error_text(prompts: FakePrompts) -> str:
    [call] = prompts.calls_of("error")
    return call.text


# --------------------------------------------------------------------------- P1B-01


@pytest.mark.parametrize(
    ("target", "demo"),
    [("AppContext", False), ("MainWindow", False), ("open_demo_database", True)],
)
def test_an_unexpected_exception_is_logged_shown_as_a_code_and_the_lock_is_released(
    started_app: StartApp,
    tmp_path: Path,
    fake_prompts: FakePrompts,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    demo: bool,
) -> None:
    hook_before = sys.excepthook

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError(MESSAGE)

    with monkeypatch.context() as patch:
        patch.setattr(app_module, target, boom)
        assert started_app(demo=demo) == 1

    [call] = fake_prompts.calls_of("error")
    assert call.title == "Unexpected error"
    assert CRASH_TEXT.fullmatch(call.text)
    assert MESSAGE not in call.text
    assert MESSAGE not in call.title
    log = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
    assert "APP.STARTUP_FAILED" in log
    assert "exc=RuntimeError" in log
    assert MESSAGE not in log
    assert sys.excepthook is hook_before  # the crash hook was uninstalled again
    expect_handle(started_app(demo=demo))  # the lock was released: a later start succeeds


def test_a_zero_byte_read_only_database_is_refused_without_a_crash(
    started_app: StartApp, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    (tmp_path / DATABASE_FILE_NAME).write_bytes(b"")
    before = snapshot(tmp_path)
    assert started_app(writable=False) == 1
    [call] = fake_prompts.calls_of("error")
    assert call.title == "Cannot start"
    assert call.text == NOT_APPLICATION_TEXT
    assert snapshot(tmp_path) == before


def test_main_reports_what_escapes_start_as_a_code(
    qapp: QApplication,
    qm_dir: Path,
    tmp_path: Path,
    fake_prompts: FakePrompts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> int:
        raise RuntimeError(MESSAGE)

    monkeypatch.setattr(app_module, "start", boom)
    monkeypatch.chdir(tmp_path)
    argv = ["--data-dir", str(tmp_path / "data"), "--lang", "en-US"]
    assert main(argv, qm_dir=qm_dir, prompts=fake_prompts) == 1
    [call] = fake_prompts.calls_of("error")
    assert CRASH_TEXT.fullmatch(call.text)
    assert MESSAGE not in call.text
    assert not (tmp_path / "data" / "logs").exists()


def test_main_lets_the_argument_parser_exit(qm_dir: Path, fake_prompts: FakePrompts) -> None:
    with pytest.raises(SystemExit):
        main(["--no-such-option"], qm_dir=qm_dir, prompts=fake_prompts)
    assert fake_prompts.calls == []


# --------------------------------------------------------------------------- P1B-06 and P1B-16


def test_an_older_schema_is_refused_read_only_and_left_untouched(
    started_app: StartApp, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    path = create_database(tmp_path)
    conn = open_database(path)
    conn.execute("PRAGMA user_version = 0")
    conn.close()
    before = snapshot(tmp_path)
    assert started_app(writable=False) == 1
    assert _error_text(fake_prompts) == OLDER_SCHEMA_TEXT
    assert snapshot(tmp_path) == before


def test_a_foreign_sqlite_file_is_refused_read_only(
    started_app: StartApp, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    with closing(sqlite3.connect(tmp_path / DATABASE_FILE_NAME)) as raw:
        raw.execute("CREATE TABLE unrelated (id INTEGER)")
        raw.commit()
    before = snapshot(tmp_path)
    assert started_app(writable=False) == 1
    assert _error_text(fake_prompts) == NOT_APPLICATION_TEXT
    assert snapshot(tmp_path) == before


def test_read_only_demo_over_a_real_database_is_refused(
    started_app: StartApp, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    demo_path = demo_database_path(tmp_path)
    demo_path.parent.mkdir(parents=True)
    shutil.copy(create_database(tmp_path / "source"), demo_path)  # a REAL database as demo.sqlite3
    before = snapshot(demo_path.parent)
    assert started_app(writable=False, demo=True) == 1
    assert _error_text(fake_prompts) == NOT_DEMO_TEXT
    assert snapshot(demo_path.parent) == before


def test_read_only_demo_over_a_demo_database_opens(started_app: StartApp, tmp_path: Path) -> None:
    demo_path = demo_database_path(tmp_path)
    demo_path.parent.mkdir(parents=True)
    shutil.copy(create_database(tmp_path / "source", is_demo=True), demo_path)
    handle = expect_handle(started_app(writable=False, demo=True))
    assert handle.context.read_only
    assert handle.context.is_demo


# --------------------------------------------------------------------------- P1B-07 and P1B-15


def test_a_lock_file_that_cannot_be_opened_gets_its_own_message(
    started_app: StartApp, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    (tmp_path / LOCK_FILE_NAME).mkdir()  # a directory where the lock file should be
    assert started_app() == 1
    text = _error_text(fake_prompts)
    assert text == LOCK_UNAVAILABLE_TEXT
    assert text != LOCKED_TEXT
    assert not (tmp_path / "logs").exists()


def test_a_refused_second_instance_leaves_the_log_folder_untouched(
    started_app: StartApp, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    first = expect_handle(started_app())
    first.logging.handler.flush()
    logs = tmp_path / "logs"
    assert (logs / "app.log").is_file()
    before = snapshot(logs)

    assert started_app() == 1
    assert _error_text(fake_prompts) == LOCKED_TEXT
    assert snapshot(logs) == before


def test_the_log_file_is_opened_only_after_the_lock_is_held(
    started_app: StartApp, tmp_path: Path
) -> None:
    handle = expect_handle(started_app())
    assert handle.logging.path == tmp_path / "logs" / "app.log"
    assert handle.instance_lock is not None
    assert handle.instance_lock.held


# --------------------------------------------------------------------------- P1B-09


def test_a_malformed_newest_change_time_makes_the_clock_suspect() -> None:
    raw = sqlite3.connect(":memory:")
    try:
        raw.execute("CREATE TABLE change_log (at_utc TEXT)")
        raw.execute("INSERT INTO change_log VALUES ('2026-01-01T00:00:00Z')")
        raw.execute("INSERT INTO change_log VALUES ('not-a-time')")  # sorts after the valid one
        conn = cast("DatabaseConnection", raw)
        assert clock_is_suspect(conn, FixedClock.at(NOW), lambda: None)
        raw.execute("DELETE FROM change_log WHERE at_utc = 'not-a-time'")
        assert not clock_is_suspect(conn, FixedClock.at(NOW), lambda: None)
    finally:
        raw.close()


def test_a_malformed_newest_change_time_raises_the_banner_and_skips_trusted_hooks(
    started_app: StartApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "_newest_change_text", lambda conn: "not-a-time")
    ran: list[str] = []

    def run(context: AppContext) -> None:
        ran.append("trusted")

    hooks = [StartupHook("trusted", run, needs_trusted_clock=True)]
    handle = expect_handle(started_app(hooks=hooks))
    assert handle.context.clock_suspect
    assert "CLOCK_SUSPECT" in handle.window.banners.visible_codes()
    assert ran == []


# --------------------------------------------------------------------------- P1B-17


def test_no_profile_dir_stops_without_touching_the_file_system(
    qapp: QApplication,
    qm_dir: Path,
    tmp_path: Path,
    fake_prompts: FakePrompts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = tmp_path / "cwd"
    empty.mkdir()
    monkeypatch.chdir(empty)

    def guard(name: str) -> None:
        original: Callable[..., Any] = getattr(Path, name)

        def checked(self: Path, *args: Any, **kwargs: Any) -> Any:
            if not self.is_absolute():
                raise AssertionError(f"Path.{name} was called on the placeholder {self}")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, checked)

    for name in ("exists", "is_file", "is_dir", "stat", "mkdir", "open", "read_text", "touch"):
        guard(name)

    location = DataLocation(
        path=Path("cbrn-dashboard"),
        source=LocationSource.DEFAULT,
        writable=False,
        warnings=(LocationWarning.NO_PROFILE_DIR,),
    )
    options = CliOptions(data_dir=None, lang="en-US", demo=False)
    result = start(
        options,
        location,
        clock=FixedClock.at(NOW),
        prompts=fake_prompts,
        qm_dir=qm_dir,
        hooks=(),
    )
    assert result == 1
    assert _error_text(fake_prompts) == NO_PROFILE_TEXT
    monkeypatch.undo()
    assert list(empty.iterdir()) == []


# --------------------------------------------------------------------------- P1B-18 and P1B-29


@pytest.mark.parametrize("code", sorted(MAPPED_CODES))
def test_a_known_storage_error_code_is_shown_as_a_sentence(
    started_app: StartApp,
    fake_prompts: FakePrompts,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise _CodedError(code)

    monkeypatch.setattr(app_module, "open_and_migrate", broken)
    assert started_app() == 1
    text = _error_text(fake_prompts)
    assert text == MAPPED_CODES[code]
    assert "Code:" not in text
    assert code not in text
    assert MESSAGE not in text


def test_an_unknown_storage_error_code_keeps_the_generic_text_with_a_crash_code(
    started_app: StartApp, fake_prompts: FakePrompts, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise _CodedError("SOMETHING_NEW")

    monkeypatch.setattr(app_module, "open_and_migrate", broken)
    assert started_app() == 1
    text = _error_text(fake_prompts)
    assert GENERIC_OPEN_TEXT.fullmatch(text)
    assert "SOMETHING_NEW" not in text


def test_the_demo_case_of_an_unusable_folder_has_its_own_wording(
    started_app: StartApp, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    create_database(tmp_path)  # the real database exists, only the demo one cannot be created
    assert started_app(writable=False, demo=True) == 1
    assert _error_text(fake_prompts) == (
        "The data folder is not writable, so the demo database cannot be created."
    )


# --------------------------------------------------------------------------- P1B-24 and P1B-25


def test_the_handle_has_no_database_setter() -> None:
    assert isinstance(AppHandle.database, property)
    assert AppHandle.database.fset is None


def test_the_default_start_up_hooks_run_when_none_are_passed(
    qapp: QApplication,
    qm_dir: Path,
    tmp_path: Path,
    fake_prompts: FakePrompts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[str] = []

    def run(context: AppContext) -> None:
        ran.append("registered")

    monkeypatch.setattr(app_module, "STARTUP_HOOKS", (StartupHook("recording", run),))
    location = DataLocation(path=tmp_path, source=LocationSource.CLI, writable=True)
    options = CliOptions(data_dir=str(tmp_path), lang="en-US", demo=False)
    result = start(
        options,
        location,
        clock=FixedClock.at(NOW),
        prompts=fake_prompts,
        qm_dir=qm_dir,
        hooks=None,
    )
    handle = expect_handle(result)
    try:
        assert handle.hooks_run == ("recording",)
        assert ran == ["registered"]
    finally:
        handle.close()


@pytest.fixture
def read_only_database_file(tmp_path: Path) -> Iterator[Path]:
    path = create_database(tmp_path)
    path.chmod(stat.S_IREAD)
    try:
        yield path
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_a_read_only_database_file_in_a_writable_folder_opens_read_only(
    started_app: StartApp, tmp_path: Path, read_only_database_file: Path
) -> None:
    before = snapshot(tmp_path)
    handle = expect_handle(started_app(writable=True))
    assert handle.context.read_only
    assert handle.instance_lock is None
    assert "READ_ONLY" in handle.window.banners.visible_codes()
    assert snapshot(tmp_path) == before
    assert not (tmp_path / LOCK_FILE_NAME).exists()
    assert not (tmp_path / "logs").exists()
