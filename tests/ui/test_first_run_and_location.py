# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only mode, location warnings and the first-run notice (PLAN.md T7.5).

Every application started here gets a FAKE user profile (``tmp_path / "profile"`` through the
``environ`` argument of ``start``), so the real ``%LOCALAPPDATA%`` is never read or written. The
event loop is never entered. Expected sentences are written out by hand (English catalogue).

Bullets of T7.5 that were already met by T1.9 are tested in ``test_shell.py`` (read-only banner,
disabled edit actions, no writes in read-only mode, the hot-journal explanation) and are not
repeated here.
"""

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from cbrn_dashboard import app as app_module
from cbrn_dashboard.app import AppHandle, StartupHook, start
from cbrn_dashboard.cli import CliOptions
from cbrn_dashboard.clock import Clock, FixedClock
from cbrn_dashboard.paths import (
    APP_DIR_NAME,
    DATABASE_FILE_NAME,
    POINTER_FILE_NAME,
    DataLocation,
    LocationSource,
    LocationWarning,
    Probes,
    resolve_data_location,
    write_location_pointer,
)
from cbrn_dashboard.prefs import PREFS_FILE_NAME, PreferencesStore
from cbrn_dashboard.services.backup import LAST_ENCRYPTED_KEY, BackupService
from cbrn_dashboard.storage import repository
from cbrn_dashboard.storage.backup import (
    BackupKind,
    DatabaseIdentity,
    create_backup,
    list_backups,
)
from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from cbrn_dashboard.storage.migrate import load_migrations, migrate
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import set_value
from cbrn_dashboard.ui.backup.page import BackupSettingsSection
from cbrn_dashboard.ui.shell import first_run
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.first_run import refresh_backup_reminder
from tests.ui._fakes import FakePrompts, create_database, expect_handle, snapshot
from tests.ui._walk import CLOSE_MARK, OPEN_MARK
from tests.ui.conftest import NOW

pytestmark = pytest.mark.ui

type Launcher = Callable[..., AppHandle | int]

_BY_NAME = {hook.name: hook for hook in app_module.STARTUP_HOOKS}
T75_HOOKS: tuple[StartupHook, ...] = (_BY_NAME["backup-reminder"], _BY_NAME["first-run-notice"])

NO_DATABASE_TEXT = "The data folder is not writable and has no database, so nothing can be opened."
OFFER_TEXT = (
    "Do you want to choose another folder for the data? The choice is remembered in your user "
    "profile for the next start."
)
CHOOSE_TITLE = "Choose the data folder"
SESSION_ONLY_OFFER_TEXT = (
    "Do you want to choose another folder for the data? The folder was set by --data-dir or by "
    "an environment variable, so the choice is used for this session only."
)
UNUSABLE_CHOICE_TEXT = "The chosen folder is not writable and has no database. Choose another one."
NOT_REMEMBERED_TEXT = "The choice could not be remembered, so it is used for this session only."
NETWORK_TEXT = "The data folder is on a network share, where database locking is unreliable."
ONEDRIVE_TEXT = "The data folder is inside a OneDrive-synchronised folder."
REMINDER_TEXT = (
    "The last encrypted backup is old or missing: make a new one and keep it on separate media."
)
NOTICE_TITLE = "Data protection notice"


@pytest.fixture
def profile_root(tmp_path: Path) -> Path:
    """The fake ``%LOCALAPPDATA%``; the application folder below it is not created up front."""
    return tmp_path / "profile"


@pytest.fixture
def launch(
    qapp: QApplication, qm_dir: Path, qtbot: QtBot, tmp_path: Path, profile_root: Path
) -> Iterator[Launcher]:
    """``start`` over a folder, with a fake profile; every handle is closed at teardown.

    ``environ`` defaults to the fake profile; ``{}`` stands for "no profile folder".
    """
    handles: list[AppHandle] = []

    def make(
        folder: Path,
        *,
        prompts: FakePrompts,
        environ: Mapping[str, str] | None = None,
        location: DataLocation | None = None,
        writable: bool = True,
        demo: bool = False,
        hooks: Sequence[StartupHook] = T75_HOOKS,
        qm: Path | None = None,
        lang: str = "en-US",
    ) -> AppHandle | int:
        folder.mkdir(parents=True, exist_ok=True)
        used = location or DataLocation(path=folder, source=LocationSource.CLI, writable=writable)
        result = start(
            CliOptions(data_dir=str(folder), lang=lang, demo=demo),
            used,
            clock=FixedClock.at(NOW),
            prompts=prompts,
            qm_dir=qm_dir if qm is None else qm,
            hooks=hooks,
            environ={"LOCALAPPDATA": str(profile_root)} if environ is None else environ,
        )
        if isinstance(result, AppHandle):
            qtbot.addWidget(result.window)
            handles.append(result)
        return result

    yield make
    for handle in reversed(handles):
        handle.close()


def _pointer_file(profile_root: Path) -> Path:
    return profile_root / APP_DIR_NAME / POINTER_FILE_NAME


def _unusable(folder: Path, source: LocationSource = LocationSource.DEFAULT) -> DataLocation:
    """An unwritable location that came from ``source`` (``launch`` defaults to ``--data-dir``)."""
    folder.mkdir(parents=True, exist_ok=True)
    return DataLocation(path=folder, source=source, writable=False)


def _banners(handle: AppHandle) -> tuple[str, ...]:
    return handle.window.banners.visible_codes()


# --------------------------------------------------------------------------- the pointer file


def test_the_pointer_is_written_and_read_back_by_the_resolver(
    tmp_path: Path, profile_root: Path
) -> None:
    target = tmp_path / "chosen"
    environ = {"LOCALAPPDATA": str(profile_root)}
    assert write_location_pointer(target, environ=environ)
    written = json.loads(_pointer_file(profile_root).read_text(encoding="utf-8"))
    assert written == {"data_dir": str(target)}
    assert [entry.name for entry in (profile_root / APP_DIR_NAME).iterdir()] == [POINTER_FILE_NAME]

    other = tmp_path / "other"
    assert write_location_pointer(other, environ=environ)  # replaced, not appended
    assert json.loads(_pointer_file(profile_root).read_text(encoding="utf-8")) == {
        "data_dir": str(other)
    }

    resolved = resolve_data_location(environ=environ, frozen=False, executable=tmp_path / "x.exe")
    assert resolved.source is LocationSource.POINTER
    assert resolved.path == other
    assert resolved.writable
    assert LocationWarning.POINTER_INVALID not in resolved.warnings


def test_the_pointer_is_refused_without_a_usable_profile(tmp_path: Path) -> None:
    assert not write_location_pointer(tmp_path / "chosen", environ={})
    not_a_folder = tmp_path / "profile-is-a-file"
    not_a_folder.write_text("x", encoding="utf-8")
    blocked = {"LOCALAPPDATA": str(not_a_folder)}
    assert not write_location_pointer(tmp_path / "chosen", environ=blocked)
    assert not_a_folder.read_text(encoding="utf-8") == "x"
    profile = tmp_path / "profile"
    assert not write_location_pointer("bad\x00path", environ={"LOCALAPPDATA": str(profile)})
    assert not profile.exists()


# --------------------------------------------------------------------------- unusable folder


def test_an_unusable_folder_offers_a_choice_and_remembers_it(
    launch: Launcher, tmp_path: Path, profile_root: Path, fake_prompts: FakePrompts
) -> None:
    locked = tmp_path / "locked"
    chosen = tmp_path / "chosen"
    fake_prompts.script("confirm", True)
    fake_prompts.script("choose_folder", chosen)

    handle = expect_handle(
        launch(locked, location=_unusable(locked), prompts=fake_prompts, hooks=())
    )

    [explanation] = fake_prompts.calls_of("error")
    assert explanation.title == "Cannot start"
    assert explanation.text == NO_DATABASE_TEXT
    [offer] = fake_prompts.calls_of("confirm")
    assert offer.text == OFFER_TEXT
    [picker] = fake_prompts.calls_of("choose_folder")
    assert picker.title == CHOOSE_TITLE

    assert handle.context.location.path == chosen
    assert handle.context.location.source is LocationSource.POINTER
    assert not handle.context.read_only
    assert (chosen / DATABASE_FILE_NAME).is_file()
    # Nothing outside the chosen folder, except the pointer in the profile.
    assert list(locked.iterdir()) == []
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["chosen", "locked", "profile"]
    assert [entry.name for entry in (profile_root / APP_DIR_NAME).iterdir()] == [POINTER_FILE_NAME]
    assert json.loads(_pointer_file(profile_root).read_text(encoding="utf-8")) == {
        "data_dir": str(chosen)
    }

    handle.close()
    again = resolve_data_location(
        environ={"LOCALAPPDATA": str(profile_root)}, frozen=False, executable=tmp_path / "x.exe"
    )
    assert again.source is LocationSource.POINTER  # the next start uses the chosen folder
    assert again.path == chosen
    assert again.writable


@pytest.mark.parametrize("cancel_at", ["confirm", "picker"])
def test_declining_or_cancelling_the_choice_ends_the_start_and_writes_nothing(
    launch: Launcher,
    tmp_path: Path,
    profile_root: Path,
    fake_prompts: FakePrompts,
    cancel_at: str,
) -> None:
    locked = tmp_path / "locked"
    if cancel_at == "picker":
        fake_prompts.script("confirm", True)  # the picker then answers None (cancelled)
    assert launch(locked, writable=False, prompts=fake_prompts, hooks=()) == 1
    [explanation] = fake_prompts.calls_of("error")
    assert explanation.text == NO_DATABASE_TEXT
    assert len(fake_prompts.calls_of("choose_folder")) == (1 if cancel_at == "picker" else 0)
    assert list(locked.iterdir()) == []
    assert not profile_root.exists()
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["locked"]


def test_an_unusable_choice_is_refused_and_the_user_may_choose_again(
    launch: Launcher, tmp_path: Path, profile_root: Path, fake_prompts: FakePrompts
) -> None:
    locked = tmp_path / "locked"
    a_file = tmp_path / "a-file"
    a_file.write_text("not a folder", encoding="utf-8")
    good = tmp_path / "good"
    fake_prompts.script("confirm", True, True)
    fake_prompts.script("choose_folder", a_file, good)

    handle = expect_handle(
        launch(locked, location=_unusable(locked), prompts=fake_prompts, hooks=())
    )

    first, second = fake_prompts.calls_of("error")
    assert first.text == NO_DATABASE_TEXT
    assert second.title == CHOOSE_TITLE
    assert second.text == UNUSABLE_CHOICE_TEXT
    assert handle.context.location.path == good
    assert a_file.read_text(encoding="utf-8") == "not a folder"
    assert json.loads(_pointer_file(profile_root).read_text(encoding="utf-8")) == {
        "data_dir": str(good)
    }


def test_a_choice_that_cannot_be_remembered_is_used_for_the_session_only(
    launch: Launcher, tmp_path: Path, profile_root: Path, fake_prompts: FakePrompts
) -> None:
    chosen = tmp_path / "chosen"
    fake_prompts.script("confirm", True)
    fake_prompts.script("choose_folder", chosen)

    locked = tmp_path / "locked"
    handle = expect_handle(
        launch(locked, location=_unusable(locked), prompts=fake_prompts, hooks=(), environ={})
    )

    [warning] = fake_prompts.calls_of("warning")
    assert warning.title == CHOOSE_TITLE
    assert warning.text == NOT_REMEMBERED_TEXT
    assert handle.context.location.path == chosen
    assert not profile_root.exists()


@pytest.mark.parametrize("source", [LocationSource.CLI, LocationSource.ENV])
def test_a_folder_set_by_an_option_is_replaced_for_the_session_only(
    launch: Launcher,
    tmp_path: Path,
    profile_root: Path,
    fake_prompts: FakePrompts,
    source: LocationSource,
) -> None:
    # --data-dir and the environment variable rank above the pointer (D02): a pointer written now
    # would be ignored by the next run with the same option and silently followed by a later one.
    locked = tmp_path / "locked"
    chosen = tmp_path / "chosen"
    fake_prompts.script("confirm", True)
    fake_prompts.script("choose_folder", chosen)

    handle = expect_handle(
        launch(locked, location=_unusable(locked, source), prompts=fake_prompts, hooks=())
    )

    [offer] = fake_prompts.calls_of("confirm")
    assert offer.text == SESSION_ONLY_OFFER_TEXT
    assert fake_prompts.calls_of("warning") == []
    assert handle.context.location.path == chosen
    assert handle.context.location.source is source
    assert not _pointer_file(profile_root).exists()
    assert not profile_root.exists()
    handle.close()
    again = resolve_data_location(
        environ={"LOCALAPPDATA": str(profile_root)}, frozen=False, executable=tmp_path / "x.exe"
    )
    assert again.source is LocationSource.DEFAULT  # a plain start does not move to the choice
    assert again.path != chosen


@pytest.mark.parametrize("source", [LocationSource.PORTABLE, LocationSource.POINTER])
def test_an_unusable_portable_or_pointer_folder_is_replaced_through_the_pointer(
    launch: Launcher,
    tmp_path: Path,
    profile_root: Path,
    fake_prompts: FakePrompts,
    source: LocationSource,
) -> None:
    locked = tmp_path / "locked"
    chosen = tmp_path / "chosen"
    fake_prompts.script("confirm", True)
    fake_prompts.script("choose_folder", chosen)

    location = _unusable(locked, source)
    expect_handle(launch(locked, location=location, prompts=fake_prompts, hooks=()))

    [offer] = fake_prompts.calls_of("confirm")
    assert offer.text == OFFER_TEXT
    assert json.loads(_pointer_file(profile_root).read_text(encoding="utf-8")) == {
        "data_dir": str(chosen)
    }


def test_the_demo_case_of_an_unusable_folder_is_only_explained(
    launch: Launcher, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    assert launch(tmp_path / "locked", writable=False, demo=True, prompts=fake_prompts) == 1
    assert fake_prompts.calls_of("confirm") == []
    assert fake_prompts.calls_of("choose_folder") == []


# --------------------------------------------------------------------------- location warnings


@pytest.mark.parametrize(
    ("network", "onedrive", "expected"),
    [
        (True, False, (LocationWarning.NETWORK_PATH,)),
        (False, True, (LocationWarning.ONEDRIVE,)),
        (True, True, (LocationWarning.NETWORK_PATH, LocationWarning.ONEDRIVE)),
    ],
)
def test_network_and_onedrive_probes_end_up_as_banners(
    launch: Launcher,
    tmp_path: Path,
    fake_prompts: FakePrompts,
    network: bool,
    onedrive: bool,
    expected: tuple[LocationWarning, ...],
) -> None:
    mount = tmp_path / "OneDrive"
    folder = mount / "data"
    folder.mkdir(parents=True)
    probes = Probes(
        writable=lambda path: True,
        network_drive=lambda path: network,
        onedrive_mounts=lambda: (mount,) if onedrive else (),
        attributes=lambda path: 0,
        ensure_directory=lambda path: True,
    )
    location = resolve_data_location(cli_data_dir=folder, environ={}, probes=probes)
    assert location.warnings == expected

    handle = expect_handle(launch(folder, location=location, prompts=fake_prompts, hooks=()))

    texts = {"NETWORK_PATH": NETWORK_TEXT, "ONEDRIVE": ONEDRIVE_TEXT}
    shown = tuple(code for code in _banners(handle) if code in texts)
    assert shown == tuple(warning.name for warning in expected)
    for code in shown:
        assert handle.window.banners.text(code) == texts[code]


# --------------------------------------------------------------------------- backup reminder


def _record_backup(path: Path, stamp: str) -> None:
    conn = open_database(path)
    try:
        set_value(WriteContext(conn, FixedClock.at(NOW), ""), LAST_ENCRYPTED_KEY, stamp)
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("stamp", "due"),
    [
        (None, True),  # never backed up
        ("2026-03-01T12:00:00Z", False),  # 4 days
        ("2026-02-03T12:00:00Z", False),  # exactly P09 (30) days: not yet due
        ("2026-02-02T12:00:00Z", True),  # 31 days
    ],
)
def test_the_reminder_banner_follows_the_age_of_the_last_encrypted_backup(
    launch: Launcher, tmp_path: Path, fake_prompts: FakePrompts, stamp: str | None, due: bool
) -> None:
    path = create_database(tmp_path)
    if stamp is not None:
        _record_backup(path, stamp)

    handle = expect_handle(launch(tmp_path, prompts=fake_prompts))

    assert handle.hooks_run == ("backup-reminder", "first-run-notice")
    assert handle.context.backup_reminder_due is due
    assert ("BACKUP_REMINDER" in _banners(handle)) is due
    if due:
        assert handle.window.banners.text("BACKUP_REMINDER") == REMINDER_TEXT


def test_a_new_backup_hides_the_reminder(
    launch: Launcher, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    handle = expect_handle(launch(tmp_path, prompts=fake_prompts))
    assert "BACKUP_REMINDER" in _banners(handle)
    conn = handle.context.conn
    assert conn is not None
    set_value(WriteContext(conn, FixedClock.at(NOW), ""), LAST_ENCRYPTED_KEY, NOW)

    refresh_backup_reminder(handle.context)

    assert not handle.context.backup_reminder_due
    assert "BACKUP_REMINDER" not in _banners(handle)


def test_the_reminder_follows_data_changed_without_a_direct_refresh(
    launch: Launcher, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    handle = expect_handle(launch(tmp_path, prompts=fake_prompts))
    assert "BACKUP_REMINDER" in _banners(handle)
    conn = handle.context.conn
    assert conn is not None
    set_value(WriteContext(conn, FixedClock.at(NOW), ""), LAST_ENCRYPTED_KEY, NOW)

    handle.context.notify_data_changed()

    assert not handle.context.backup_reminder_due
    assert "BACKUP_REMINDER" not in _banners(handle)


def test_a_change_of_p09_in_the_backup_section_updates_the_banner(
    launch: Launcher, tmp_path: Path, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    create_database(tmp_path)
    _record_backup(tmp_path / DATABASE_FILE_NAME, "2026-02-23T12:00:00Z")  # 10 days before NOW
    handle = expect_handle(launch(tmp_path, prompts=fake_prompts))
    assert "BACKUP_REMINDER" not in _banners(handle)  # P09 is 30 days
    section = BackupSettingsSection(handle.context)
    qtbot.addWidget(section)

    section.reminder_row.spin.setValue(5)
    section.save_action.trigger()

    assert handle.context.backup_reminder_due
    assert "BACKUP_REMINDER" in _banners(handle)


@pytest.mark.parametrize("demo", [False, True])
def test_the_reminder_reads_the_identity_from_the_context(
    app_context: AppContext, monkeypatch: pytest.MonkeyPatch, demo: bool
) -> None:
    seen: list[DatabaseIdentity] = []
    real = first_run.BackupService

    def spy(
        conn: DatabaseConnection, clock: Clock, *, data_dir: Path, identity: DatabaseIdentity
    ) -> BackupService:
        seen.append(identity)
        return real(conn, clock, data_dir=data_dir, identity=identity)

    monkeypatch.setattr(first_run, "BackupService", spy)
    app_context.is_demo = demo

    refresh_backup_reminder(app_context)

    assert seen == [DatabaseIdentity.DEMO if demo else DatabaseIdentity.REAL]


def test_the_reminder_is_shown_read_only_and_writes_nothing(
    launch: Launcher, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    create_database(tmp_path)
    before = snapshot(tmp_path)

    handle = expect_handle(launch(tmp_path, writable=False, prompts=fake_prompts))

    assert handle.context.read_only
    assert "READ_ONLY" in _banners(handle)
    assert "BACKUP_REMINDER" in _banners(handle)
    handle.close()
    assert snapshot(tmp_path) == before


def test_there_is_no_reminder_for_a_demo_database(
    launch: Launcher, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    handle = expect_handle(launch(tmp_path, demo=True, prompts=fake_prompts))
    assert handle.context.is_demo
    assert handle.hooks_run == ()
    assert "BACKUP_REMINDER" not in _banners(handle)


# --------------------------------------------------------------------------- first-run notice


def test_the_first_run_notice_appears_exactly_once_with_its_content(
    launch: Launcher, tmp_path: Path
) -> None:
    prompts = FakePrompts()
    first = expect_handle(launch(tmp_path, prompts=prompts))
    [call] = prompts.calls_of("info")
    assert call.title == NOTICE_TITLE
    paragraphs = call.text.split("\n\n")
    assert paragraphs == [
        f"Your data is stored only on this computer, in this folder: {tmp_path}",
        "Disk encryption: the documentation requires full-disk encryption of this computer "
        "(for example BitLocker). This application cannot check whether it is on, and it does "
        "not protect files that you export or copy to removable media.",
        "Backups: a plain copy of the database is made automatically once a day in the backups "
        "folder of the data folder. Encrypted backups are made by hand to a place that you "
        "choose; keep them on separate media. A lost passphrase cannot be recovered.",
        'Classification: "sensitive" is only a working label for data that stays on this '
        "computer; it is not a formal classification.",
        "Shared computer: several people can take turns on one computer only with one shared "
        "Windows account, or with --data-dir pointing to a local folder restricted to the "
        "committee. With separate Windows accounts each person gets a separate database.",
    ]
    # T12.5 (D39): the real-data gate is gone from the notice.
    assert "Q19" not in call.text
    assert "real data" not in call.text
    saved = json.loads((tmp_path / PREFS_FILE_NAME).read_text(encoding="utf-8"))
    assert saved["first_run_notice_shown"] is True
    first.close()

    second_prompts = FakePrompts()
    second = expect_handle(launch(tmp_path, prompts=second_prompts))
    assert second_prompts.calls_of("info") == []
    assert "first-run-notice" in second.hooks_run  # the hook ran, and found the flag set


def test_in_read_only_mode_the_notice_is_shown_but_nothing_is_written(
    launch: Launcher, tmp_path: Path
) -> None:
    create_database(tmp_path)
    before = snapshot(tmp_path)
    prompts = FakePrompts()

    handle = expect_handle(launch(tmp_path, writable=False, prompts=prompts))

    assert len(prompts.calls_of("info")) == 1
    assert handle.preferences.current.first_run_notice_shown
    assert not handle.preferences.persisted  # kept in memory only
    assert snapshot(tmp_path) == before
    handle.close()

    # The flag could not be saved, so the notice comes back at the next read-only start.
    again_prompts = FakePrompts()
    expect_handle(launch(tmp_path, writable=False, prompts=again_prompts))
    assert len(again_prompts.calls_of("info")) == 1
    assert snapshot(tmp_path) == before


def test_the_notice_is_not_shown_for_a_demo_database_and_the_flag_stays_unset(
    launch: Launcher, tmp_path: Path, fake_prompts: FakePrompts
) -> None:
    handle = expect_handle(launch(tmp_path, demo=True, prompts=fake_prompts))
    assert handle.context.is_demo
    assert fake_prompts.calls_of("info") == []
    assert not (tmp_path / PREFS_FILE_NAME).exists()
    assert not PreferencesStore(tmp_path).load().first_run_notice_shown


def test_the_registered_hooks_run_the_notice_after_the_other_start_up_work(
    launch: Launcher, tmp_path: Path
) -> None:
    prompts = FakePrompts()
    handle = expect_handle(launch(tmp_path, prompts=prompts, hooks=app_module.STARTUP_HOOKS))
    assert handle.hooks_run[-2:] == ("backup-reminder", "first-run-notice")
    assert len(prompts.calls_of("info")) == 1


def test_the_notice_and_the_reminder_follow_the_pseudo_locale(
    launch: Launcher, tmp_path: Path, pseudo_qm_dir: Path
) -> None:
    # Needs the new strings in the shell catalogues (the pseudo catalogue is built from them).
    prompts = FakePrompts()
    handle = expect_handle(launch(tmp_path, prompts=prompts, qm=pseudo_qm_dir, lang="pt-BR"))
    [call] = prompts.calls_of("info")
    assert call.title.startswith(OPEN_MARK)
    assert call.title.endswith(CLOSE_MARK)
    paragraphs = call.text.split("\n\n")
    assert len(paragraphs) == 5
    for paragraph in paragraphs:
        assert paragraph.startswith(OPEN_MARK)
        assert paragraph.endswith(CLOSE_MARK)
    reminder = handle.window.banners.text("BACKUP_REMINDER")
    assert reminder.startswith(OPEN_MARK)
    assert reminder.endswith(CLOSE_MARK)


# --------------------------------------------------------------------------- pre-migration copy


@pytest.mark.parametrize(
    ("clock_text", "kept"),
    [
        ("2026-03-05T12:00:00Z", 4),  # earlier than the newest change record: no rotation
        ("2026-04-02T12:00:00Z", 3),  # a plausible clock: the pool keeps the last three
    ],
)
def test_the_pre_migration_copy_uses_the_injected_clock_and_a_suspect_clock_skips_rotation(
    tmp_path: Path, clock_text: str, kept: int
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    path = data / DATABASE_FILE_NAME
    conn = open_database(path)
    try:
        migrate(conn, migrations=load_migrations()[:-1])  # one step behind: a migration is due
        repository.log_event(
            WriteContext(conn, FixedClock.at("2026-04-01T12:00:00Z"), ""),
            "database",
            "restore",
            after={},
        )
        for day in (1, 2, 3):
            create_backup(
                conn,
                data_dir=data,
                identity=DatabaseIdentity.REAL,
                kind=BackupKind.PRE_MIGRATION,
                clock=FixedClock.at(f"2026-03-0{day}T12:00:00Z"),
            )
    finally:
        conn.close()
    clock = FixedClock.at(clock_text)
    location = DataLocation(path=data, source=LocationSource.DEFAULT, writable=True)

    opened = app_module._open_database(
        CliOptions(data_dir=str(data)),
        location,
        clock,
        path,
        app_module._Mode.READ_WRITE,
        lambda: None,  # no build time: only the change log decides
    )
    opened.close()

    pool = list_backups(data, DatabaseIdentity.REAL, BackupKind.PRE_MIGRATION)
    assert len(pool) == kept
    assert pool[0].created_utc == clock.utc_now()  # named by the injected clock, not the system's


# --------------------------------------------------------------------------- the guide


def test_the_data_protection_guide_exists_and_names_the_default_folder() -> None:
    guide = Path(__file__).resolve().parents[2] / "docs" / "data-protection.md"
    text = guide.read_text(encoding="utf-8")
    assert "%LOCALAPPDATA%\\cbrn-readiness-dashboard\\" in text
    assert "full-disk encryption" in text
    assert "Values already written to backups persist until those backups are deleted." in text
    assert "non-persistent Windows profile" in text
    assert "one shared Windows account" in text
