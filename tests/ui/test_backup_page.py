# SPDX-License-Identifier: GPL-3.0-or-later
"""The backup and restore UI: actions, passphrase dialog, settings section, labels (T7.4).

Everything runs on a temporary data folder with real services and CHEAP scrypt parameters (the
production ones are far too slow for tests); the prompts are the fake of ``tests/ui/_fakes.py``.
"""

import ast
import inspect
import logging
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest
from PySide6.QtWidgets import QAbstractButton, QLabel, QLineEdit, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.services import backup as backup_service_module
from cbrn_dashboard.services import restore as restore_module
from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.backup import BackupInfo, BackupKind, DatabaseIdentity, list_backups
from cbrn_dashboard.storage.crypto_backup import (
    ScryptParams,
    database_snapshot_bytes,
    read_backup,
    write_backup,
)
from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from cbrn_dashboard.storage.migrate import open_and_migrate
from cbrn_dashboard.ui.backup.actions import BackupActions, DestinationChecks
from cbrn_dashboard.ui.backup.dialogs import PassphraseDialog
from cbrn_dashboard.ui.backup.labels import ALL_ERROR_CODES, error_label
from cbrn_dashboard.ui.backup.page import (
    BackupSettingsSection,
    create_settings_section,
    demo_backup_dialog,
    demo_restore_dialog,
    settings_section_title,
)
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.registry import DialogSpec, SettingsSectionSpec
from tests.ui._fakes import FakePrompts, snapshot
from tests.ui._walk import assert_fully_translated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")
#: Cheap scrypt parameters; the reader's allow-list is widened by keyword, never by patching.
CHEAP = ScryptParams(n=2**12, r=8, p=1)
ALLOWED = frozenset({CHEAP})
PASSPHRASE = "Zq7-distinctive-passphrase-\u00e9"
OTHER = "Another-Passphrase-4-tests!"
QUIET = DestinationChecks(
    network_drive=lambda _folder: False,
    cloud_sync=lambda _folder: False,
    removable=lambda _folder: True,
)

#: The English text of every code, written by hand.
EXPECTED_ENGLISH: dict[str, str] = {
    "WRONG_PASSPHRASE": "The passphrase is wrong. Nothing was changed.",
    "CORRUPT_BACKUP": "The backup file is damaged or is not a backup file. Nothing was changed.",
    "BACKUP_TOO_NEW": (
        "The backup was made by a newer version of the program. Nothing was changed."
    ),
    "BACKUP_UNREADABLE": "The backup file cannot be read. Check that it exists and is not in use.",
    "TEMP_FILE_FAILED": (
        "A temporary file could not be written in the data folder. Nothing was changed."
    ),
    "INTEGRITY_FAILED": "The backup failed its integrity check. Nothing was changed.",
    "DEMO_MISMATCH": "Demonstration data and real data cannot be exchanged. Nothing was changed.",
    "NOT_AN_APPLICATION_DATABASE": (
        "The file is not a backup of this application. Nothing was changed."
    ),
    "MIGRATION_FAILED": (
        "The backup could not be upgraded to the current version. Nothing was changed."
    ),
    "OTHER_CONNECTIONS_OPEN": (
        "Another part of the program is using the data. Close it and try again."
    ),
    "TRANSACTION_OPEN": "A change is still being saved. Try again in a moment.",
    "JOURNAL_PRESENT": "An unfinished write was found in the data folder. Restart the program.",
    "SAFETY_COPY_FAILED": (
        "A safety copy of the current data could not be made, so nothing was restored."
    ),
    "RESTORE_COPY_FAILED": "The restore failed while copying. The previous data was put back.",
    "READ_ONLY": "The data is read-only: nothing was changed.",
    "PASSPHRASE_MISMATCH": "The two passphrases are different.",
    "PASSPHRASE_TOO_SHORT": "The passphrase is too short.",
    "PASSPHRASE_TOO_FEW_DISTINCT": "The passphrase uses too few different characters.",
    "PASSPHRASE_BLOCKLISTED": "The passphrase is too easy to guess. Choose another one.",
    "BACKUP_WRITE_FAILED": "The backup file could not be written. Check the chosen location.",
    "BACKUP_VERIFY_FAILED": (
        "The backup file was written but could not be read back, so it was deleted."
    ),
    "BACKUP_FLOOR": "The number of daily backups is below the allowed minimum.",
    "PASSPHRASE_FLOOR": "The passphrase length is below the allowed minimum.",
    "NEGATIVE_DAYS": "The number of days cannot be negative.",
    "VALUE_TOO_LARGE": "The value is too large.",
    "INVALID_TYPE": "The value has the wrong type.",
    "CORRUPT_SETTING": "A stored setting cannot be read.",
    "UNKNOWN_PLACEHOLDER": "This placeholder is not known.",
}


# --------------------------------------------------------------------------- helpers


def _conn(context: AppContext) -> DatabaseConnection:
    assert context.conn is not None
    return context.conn


def _config(context: AppContext) -> ConfigService:
    config = context.services.config
    assert config is not None
    return config


def _db_bytes(context: AppContext) -> bytes:
    return context.location.database_path.read_bytes()


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


def _safety_copies(context: AppContext) -> list[BackupInfo]:
    return list_backups(context.location.path, DatabaseIdentity.REAL, BackupKind.BEFORE_RESTORE)


def _out(tmp_path: Path) -> Path:
    folder = tmp_path / "out"
    folder.mkdir(exist_ok=True)
    return folder


def _dialog(anchor: QWidget) -> PassphraseDialog:
    shown = [d for d in anchor.findChildren(PassphraseDialog) if d.isVisible()]
    assert len(shown) == 1
    return shown[0]


def _no_dialog(anchor: QWidget) -> bool:
    return not any(d.isVisible() for d in anchor.findChildren(PassphraseDialog))


def _fill(dialog: PassphraseDialog, passphrase: str, confirmation: str | None = None) -> None:
    dialog.passphrase_edit.setText(passphrase)
    if dialog.confirm_edit is not None:
        dialog.confirm_edit.setText(passphrase if confirmation is None else confirmation)


def _write_backup(conn: DatabaseConnection, dest: Path, passphrase: str = PASSPHRASE) -> Path:
    data, version = database_snapshot_bytes(conn)
    write_backup(dest, data, passphrase, app_version="test", schema_version=version, params=CHEAP)
    return dest


def _demo_backup(tmp_path: Path) -> Path:
    """An encrypted backup of a separate DEMO database."""
    folder = tmp_path / "demo-source"
    folder.mkdir()
    conn = open_and_migrate(
        folder / "source.sqlite3", data_dir=folder, identity=DatabaseIdentity.REAL
    )
    try:
        app_meta.initialise(conn, is_demo=True, created_with="0.0.1")
        return _write_backup(conn, _out(tmp_path) / "demo.cbrnbak")
    finally:
        conn.close()


def _back_up(
    actions: BackupActions,
    prompts: FakePrompts,
    anchor: QWidget,
    target: Path,
    passphrase: str = PASSPHRASE,
) -> None:
    prompts.script("save_file", target)
    actions.back_up()
    dialog = _dialog(anchor)
    _fill(dialog, passphrase)
    dialog.accept()


def _widget_texts(root: QWidget) -> list[str]:
    """Every text a widget tree shows or exposes, except the CONTENT of a password field."""
    found: list[str] = []
    for widget in [root, *root.findChildren(QWidget)]:
        found += [
            widget.windowTitle(),
            widget.toolTip(),
            widget.statusTip(),
            widget.whatsThis(),
            widget.accessibleName(),
            widget.accessibleDescription(),
        ]
        if isinstance(widget, QLabel | QAbstractButton):
            found.append(widget.text())
        if isinstance(widget, QLineEdit):
            found.append(widget.placeholderText())
            if widget.echoMode() == QLineEdit.EchoMode.Normal:
                found.append(widget.text())
    return found


@pytest.fixture
def anchor(qtbot: QtBot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def _cheap(actions: BackupActions) -> BackupActions:
    actions.scrypt_params = CHEAP
    actions.allowed_params = ALLOWED
    actions.checks = QUIET
    return actions


@pytest.fixture
def actions(app_context: AppContext, anchor: QWidget) -> BackupActions:
    return _cheap(BackupActions(app_context, anchor))


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
    context.deleteLater()


@pytest.fixture
def pseudo_context(
    app_context: AppContext,
    translator_manager_factory: Callable[[Path | None], TranslatorManager],
    pseudo_qm_dir: Path,
) -> AppContext:
    """The context with every translated text wrapped in the pseudo-locale markers."""
    app_context.translator_manager.clear()
    manager = translator_manager_factory(pseudo_qm_dir)
    manager.set_language("pt_BR")
    app_context.translator_manager = manager
    return app_context


# --------------------------------------------------------------------------- Back up


def test_a_backup_writes_the_cbrnbak_file_and_reports_success(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    target = _out(tmp_path) / "mine.cbrnbak"
    fake_prompts.script("save_file", target)
    actions.back_up()
    (picker,) = fake_prompts.calls_of("save_file")
    assert picker.args == (
        "Encrypted backup",
        "cbrn-backup-2026-03-05.cbrnbak",
        "Encrypted backup (*.cbrnbak)",
    )
    dialog = _dialog(anchor)
    assert dialog.confirm_edit is not None
    _fill(dialog, PASSPHRASE)
    dialog.accept()

    restored = read_backup(target, PASSPHRASE, allowed_params=ALLOWED)
    assert restored.database_bytes.startswith(b"SQLite format 3")
    (info,) = fake_prompts.calls_of("info")
    assert info.title == "Encrypted backup"
    assert info.text == f"The encrypted backup was written to {target}."
    assert _warnings(fake_prompts) == []


def test_the_extension_is_added_and_a_fixed_place_gets_the_separate_media_advice(
    fake_prompts: FakePrompts, actions: BackupActions, anchor: QWidget, tmp_path: Path
) -> None:
    actions.checks = replace(QUIET, removable=lambda _folder: False)
    _back_up(actions, fake_prompts, anchor, _out(tmp_path) / "plain")
    written = _out(tmp_path) / "plain.cbrnbak"
    assert written.is_file()
    (info,) = fake_prompts.calls_of("info")
    assert info.text == (
        f"The encrypted backup was written to {written}. "
        "Keep another copy on separate media, away from this computer."
    )


@pytest.mark.parametrize(
    ("first", "second", "code"),
    [
        (PASSPHRASE, OTHER, "PASSPHRASE_MISMATCH"),
        ("short", "short", "PASSPHRASE_TOO_SHORT"),
        ("a" * 14, "a" * 14, "PASSPHRASE_TOO_FEW_DISTINCT"),
        ("Password1234!", "Password1234!", "PASSPHRASE_BLOCKLISTED"),
    ],
)
def test_a_refused_passphrase_shows_the_translated_error_and_writes_no_file(
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
    first: str,
    second: str,
    code: str,
) -> None:
    target = _out(tmp_path) / "refused.cbrnbak"
    fake_prompts.script("save_file", target)
    actions.back_up()
    dialog = _dialog(anchor)
    _fill(dialog, first, second)
    dialog.accept()
    assert _warnings(fake_prompts) == [EXPECTED_ENGLISH[code]]
    assert dialog.isVisible()
    assert dialog.passphrase_edit.text() == ""  # emptied after use, kept open for a new try
    assert dialog.confirm_edit is not None
    assert dialog.confirm_edit.text() == ""
    assert list(_out(tmp_path).iterdir()) == []
    assert fake_prompts.calls_of("info") == []


def test_the_refusal_follows_the_language(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
    qtbot: QtBot,
) -> None:
    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: actions.backup_action.text() == "Fazer backup...")
    fake_prompts.script("save_file", _out(tmp_path) / "x.cbrnbak")
    actions.back_up()
    dialog = _dialog(anchor)
    _fill(dialog, PASSPHRASE, OTHER)
    dialog.accept()
    assert _warnings(fake_prompts) == ["As duas frases secretas s\u00e3o diferentes."]
    app_context.translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: dialog.windowTitle() == "Copia de seguridad cifrada")
    assert actions.restore_action.text() == "Restaurar..."


def test_cancelling_the_file_choice_does_nothing(
    fake_prompts: FakePrompts, actions: BackupActions, anchor: QWidget, tmp_path: Path
) -> None:
    actions.back_up()  # the fake picker answers "cancelled"
    assert len(fake_prompts.calls_of("save_file")) == 1
    assert _no_dialog(anchor)
    assert list(_out(tmp_path).iterdir()) == []


def test_a_network_or_cloud_place_or_the_data_folder_asks_before_going_on(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    actions.checks = DestinationChecks(
        network_drive=lambda _folder: True,
        cloud_sync=lambda _folder: True,
        removable=lambda _folder: False,
    )
    inside = app_context.location.path / "inside.cbrnbak"
    fake_prompts.script("save_file", inside, inside)
    actions.back_up()  # declined (the fake answers "no")
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == (
        "The chosen location is on a network drive. "
        "The chosen location is synchronised with a cloud service. "
        "The chosen location is inside the data folder. "
        "Prefer removable media kept in a safe place. Continue anyway?"
    )
    assert _no_dialog(anchor)

    fake_prompts.script("confirm", True)
    actions.back_up()
    assert _dialog(anchor).isVisible()
    assert not inside.exists()


def test_the_default_file_name_of_demo_data_starts_with_demo(
    app_context: AppContext, actions: BackupActions
) -> None:
    assert actions.default_file_name() == "cbrn-backup-2026-03-05.cbrnbak"
    app_context.is_demo = True
    assert actions.default_file_name() == "DEMO-cbrn-backup-2026-03-05.cbrnbak"


# --------------------------------------------------------------------------- Restore


def test_a_backup_exported_through_the_ui_is_restored_through_the_ui(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    config = _config(app_context)
    config.save(config.load().with_changes(daily_backups_kept=9))
    target = _out(tmp_path) / "mine.cbrnbak"
    _back_up(actions, fake_prompts, anchor, target)
    assert target.is_file()
    config.save(config.load().with_changes(daily_backups_kept=11))
    changed: list[int] = []
    app_context.data_changed.connect(lambda: changed.append(1))

    fake_prompts.script("open_file", target)
    fake_prompts.script("confirm", True)
    actions.restore()
    (picker,) = fake_prompts.calls_of("open_file")
    assert picker.args == ("Restore from a backup", "Encrypted backup (*.cbrnbak)")
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == (
        "Restoring replaces ALL the data now in the application with mine.cbrnbak. "
        "A safety copy of the current data is kept first. Continue?"
    )
    dialog = _dialog(anchor)
    assert dialog.confirm_edit is None  # a restore asks for the passphrase once
    _fill(dialog, PASSPHRASE)
    dialog.accept()

    assert config.load().daily_backups_kept == 9
    assert changed == [1]
    (safety,) = _safety_copies(app_context)
    infos = [call.text for call in fake_prompts.calls_of("info")]
    assert infos[-1] == (
        f"The backup was restored. The previous data was kept as {safety.path.name}."
    )
    assert _warnings(fake_prompts) == []
    assert list((app_context.location.path / "tmp").iterdir()) == []


def test_cancelling_the_confirmation_changes_nothing(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    source = _write_backup(_conn(app_context), _out(tmp_path) / "b.cbrnbak")
    config = _config(app_context)
    config.save(config.load().with_changes(daily_backups_kept=11))
    before = _db_bytes(app_context)
    changed: list[int] = []
    app_context.data_changed.connect(lambda: changed.append(1))

    fake_prompts.script("open_file", source)  # confirm: the fake answers "no"
    actions.restore()
    assert len(fake_prompts.calls_of("confirm")) == 1
    assert _no_dialog(anchor)
    assert _db_bytes(app_context) == before
    assert changed == []
    assert _safety_copies(app_context) == []


def test_cancelling_the_file_choice_of_a_restore_asks_nothing(
    fake_prompts: FakePrompts, actions: BackupActions, anchor: QWidget
) -> None:
    actions.restore()
    assert len(fake_prompts.calls_of("open_file")) == 1
    assert fake_prompts.calls_of("confirm") == []
    assert _no_dialog(anchor)


def _restore_expecting_failure(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    source: Path,
    passphrase: str,
) -> str:
    """Run a restore that must fail; return the one warning, with the database untouched."""
    before = _db_bytes(app_context)
    fake_prompts.script("open_file", source)
    fake_prompts.script("confirm", True)
    actions.restore()
    dialog = _dialog(anchor)
    _fill(dialog, passphrase)
    dialog.accept()
    (text,) = _warnings(fake_prompts)
    assert dialog.isVisible()  # kept open for a new try
    assert dialog.passphrase_edit.text() == ""
    assert _db_bytes(app_context) == before
    assert _safety_copies(app_context) == []
    assert fake_prompts.calls_of("info") == []
    return text


def test_a_wrong_passphrase_leaves_the_database_untouched_and_says_so(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    source = _write_backup(_conn(app_context), _out(tmp_path) / "b.cbrnbak")
    text = _restore_expecting_failure(
        app_context, fake_prompts, actions, anchor, source, "Wrong-passphrase-12345"
    )
    assert text == EXPECTED_ENGLISH["WRONG_PASSPHRASE"]


@pytest.mark.parametrize("damage", ["garbage", "truncated"])
def test_a_corrupt_file_leaves_the_database_untouched_and_says_so(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
    damage: str,
) -> None:
    source = _write_backup(_conn(app_context), _out(tmp_path) / "b.cbrnbak")
    if damage == "garbage":
        source.write_bytes(b"this is not a backup file" * 10)
    else:
        source.write_bytes(source.read_bytes()[:100])
    text = _restore_expecting_failure(
        app_context, fake_prompts, actions, anchor, source, PASSPHRASE
    )
    assert text == EXPECTED_ENGLISH["CORRUPT_BACKUP"]


def test_a_missing_file_is_reported_as_unreadable(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    text = _restore_expecting_failure(
        app_context, fake_prompts, actions, anchor, _out(tmp_path) / "missing.cbrnbak", PASSPHRASE
    )
    assert text == EXPECTED_ENGLISH["BACKUP_UNREADABLE"]


def test_a_demo_backup_is_refused_by_real_data_in_words(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    source = _demo_backup(tmp_path)
    text = _restore_expecting_failure(
        app_context, fake_prompts, actions, anchor, source, PASSPHRASE
    )
    assert text == "Demonstration data and real data cannot be exchanged. Nothing was changed."
    assert text == error_label("DEMO_MISMATCH")


def test_an_open_second_connection_stops_the_restore_with_its_message(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    source = _write_backup(_conn(app_context), _out(tmp_path) / "b.cbrnbak")
    other = open_database(app_context.location.database_path)
    try:
        text = _restore_expecting_failure(
            app_context, fake_prompts, actions, anchor, source, PASSPHRASE
        )
    finally:
        other.close()
    assert text == EXPECTED_ENGLISH["OTHER_CONNECTIONS_OPEN"]


# --------------------------------------------------------------------------- read-only mode


def test_read_only_mode_disables_restore_but_not_back_up(
    read_only_context: AppContext,
    fake_prompts: FakePrompts,
    anchor: QWidget,
) -> None:
    actions = _cheap(BackupActions(read_only_context, anchor))
    assert read_only_context.read_only
    assert actions.backup_action.isEnabled()
    assert not actions.restore_action.isEnabled()
    assert actions.restore_action in read_only_context.edit_targets()
    assert actions.backup_action not in read_only_context.edit_targets()
    actions.restore_action.setEnabled(True)  # read-only mode undoes it at once
    assert not actions.restore_action.isEnabled()

    actions.restore()  # called directly all the same: refused, nothing asked
    assert _warnings(fake_prompts) == [EXPECTED_ENGLISH["READ_ONLY"]]
    assert fake_prompts.calls_of("open_file") == []


def test_a_backup_in_read_only_mode_leaves_the_data_folder_byte_identical(
    read_only_context: AppContext,
    fake_prompts: FakePrompts,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    actions = _cheap(BackupActions(read_only_context, anchor))
    out = _out(tmp_path)
    before = snapshot(read_only_context.location.path)
    target = out / "readonly.cbrnbak"
    _back_up(actions, fake_prompts, anchor, target)
    assert target.is_file()
    assert read_backup(target, PASSPHRASE, allowed_params=ALLOWED).database_bytes
    assert snapshot(read_only_context.location.path) == before
    assert _warnings(fake_prompts) == []


def test_the_section_follows_read_only_mode(read_only_context: AppContext, qtbot: QtBot) -> None:
    section = BackupSettingsSection(read_only_context)
    qtbot.addWidget(section)
    for row in (section.passphrase_row, section.daily_row, section.reminder_row):
        assert not row.spin.isEnabled()
        assert not row.confirm.isEnabled()
    assert not section.save_action.isEnabled()
    assert not section.backup_actions.restore_action.isEnabled()
    assert section.backup_actions.backup_action.isEnabled()


# --------------------------------------------------------------------------- Open data folder


def test_open_data_folder_hands_the_local_data_folder_to_the_helper(
    app_context: AppContext, actions: BackupActions
) -> None:
    opened: list[Path] = []
    actions.open_folder = opened.append
    assert actions.open_folder_action.isEnabled()
    actions.open_folder_action.trigger()
    assert opened == [app_context.location.path]


def test_open_data_folder_without_a_helper_does_nothing(actions: BackupActions) -> None:
    actions.open_folder_action.trigger()  # must not raise


# --------------------------------------------------------------------------- the passphrase


def test_the_passphrase_is_masked_and_never_exposed(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    target = _out(tmp_path) / "secret.cbrnbak"
    fake_prompts.script("save_file", target)
    actions.back_up()
    dialog = _dialog(anchor)
    _fill(dialog, PASSPHRASE)
    assert dialog.confirm_edit is not None
    for edit in (dialog.passphrase_edit, dialog.confirm_edit):
        assert edit.echoMode() == QLineEdit.EchoMode.Password
    assert PASSPHRASE not in "\n".join(_widget_texts(anchor))
    dialog.accept()

    fake_prompts.script("open_file", target)
    fake_prompts.script("confirm", True)
    actions.restore()
    restore_dialog = _dialog(anchor)
    assert restore_dialog.passphrase_edit.echoMode() == QLineEdit.EchoMode.Password
    _fill(restore_dialog, OTHER)  # a wrong one first
    assert PASSPHRASE not in "\n".join(_widget_texts(anchor))
    restore_dialog.accept()
    _fill(restore_dialog, PASSPHRASE)
    restore_dialog.accept()

    assert PASSPHRASE not in "\n".join(_widget_texts(anchor))
    for call in fake_prompts.calls:
        assert PASSPHRASE not in str(call.args)
        assert OTHER not in str(call.args)
    assert PASSPHRASE not in caplog.text
    assert OTHER not in caplog.text
    for record in caplog.records:
        assert PASSPHRASE not in record.getMessage()
        assert PASSPHRASE not in str(record.args)


def test_the_passphrase_dialog_texts_and_the_minimum_length(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    actions: BackupActions,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    config = _config(app_context)
    config.save(config.load().with_changes(min_passphrase_length=16))
    fake_prompts.script("save_file", _out(tmp_path) / "x.cbrnbak")
    actions.back_up()
    dialog = _dialog(anchor)
    assert dialog.windowTitle() == "Encrypted backup"
    assert dialog.rules_label is not None
    assert dialog.rules_label.text() == (
        "The passphrase needs at least 16 characters and is not a common word."
    )
    assert dialog.warning_label is not None
    assert dialog.warning_label.text() == "Warning: a lost passphrase cannot be recovered."
    _fill(dialog, "Abcdefghij-1234")  # 15 characters: above the floor of 12, below the stored P05
    dialog.accept()
    assert _warnings(fake_prompts) == [EXPECTED_ENGLISH["PASSPHRASE_TOO_SHORT"]]


def test_the_dialog_never_shows_a_minimum_below_the_hard_floor(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = PassphraseDialog(app_context, None, repeat=True, min_length=3)
    qtbot.addWidget(dialog)
    assert dialog.rules_label is not None
    assert "at least 12 characters" in dialog.rules_label.text()


# --------------------------------------------------------------------------- settings section


def test_the_settings_section_is_reachable_through_the_registry(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    spec = SettingsSectionSpec(
        "backup.test", "backup", settings_section_title, create_settings_section
    )
    with registry.registered(spec):
        (found,) = [s for s in registry.settings_sections("backup") if s.key == "backup.test"]
        section = found.factory(app_context)
        assert found.title() == "Backup and restore"
    qtbot.addWidget(section)
    assert isinstance(section, BackupSettingsSection)
    assert fake_prompts.calls == []

    config = _config(app_context)
    assert (section.passphrase_row.spin.minimum(), section.daily_row.spin.minimum()) == (12, 2)
    assert section.reminder_row.spin.minimum() == 0
    assert [r.spin.value() for r in (section.passphrase_row, section.daily_row)] == [12, 7]
    assert section.reminder_row.spin.value() == 30

    section.passphrase_row.spin.setValue(16)
    section.daily_row.spin.setValue(5)
    section.reminder_row.spin.setValue(45)
    section.save_action.trigger()
    stored = config.load()
    assert (stored.min_passphrase_length, stored.daily_backups_kept) == (16, 5)
    assert stored.backup_reminder_days == 45

    config.save(stored.with_changes(daily_backups_kept=8))
    app_context.notify_data_changed()
    assert section.daily_row.spin.value() == 8


def test_a_value_below_a_hard_floor_is_refused_with_the_message(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = BackupSettingsSection(app_context)
    qtbot.addWidget(section)
    section.passphrase_row.spin.setMinimum(1)
    section.passphrase_row.spin.setValue(5)
    section.daily_row.spin.setMinimum(0)
    section.save_action.trigger()
    assert _warnings(fake_prompts) == [EXPECTED_ENGLISH["PASSPHRASE_FLOOR"]]
    assert _config(app_context).load().min_passphrase_length == 12
    assert section.passphrase_row.spin.value() == 12

    section.daily_row.spin.setValue(1)
    section.passphrase_row.spin.setValue(12)
    section.save_action.trigger()
    assert _warnings(fake_prompts)[-1] == EXPECTED_ENGLISH["BACKUP_FLOOR"]
    assert _config(app_context).load().daily_backups_kept == 7


def test_the_placeholder_badges_and_confirm_buttons_follow_the_configuration(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = BackupSettingsSection(app_context)
    qtbot.addWidget(section)
    config = _config(app_context)
    expected = (
        ("P05", section.passphrase_row),
        ("P06", section.daily_row),
        ("P09", section.reminder_row),
    )
    for placeholder, row in expected:
        assert row.placeholder == placeholder
        assert config.badge_for_field(row.field) == placeholder
        assert not row.badge.isHidden()
        assert row.badge.text() == "Placeholder - to be confirmed"
        assert row.confirm.text() == "Confirm"
    section.passphrase_row.confirm.click()
    assert config.badge_for_field("min_passphrase_length") is None
    assert section.passphrase_row.badge.isHidden()
    assert section.passphrase_row.confirm.isHidden()
    assert not section.daily_row.badge.isHidden()


def test_the_section_shows_the_last_encrypted_backup(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot, tmp_path: Path
) -> None:
    section = BackupSettingsSection(app_context)
    qtbot.addWidget(section)
    assert section.last_label.text() == "Last encrypted backup: never"
    _cheap(section.backup_actions)
    _back_up(section.backup_actions, fake_prompts, section, _out(tmp_path) / "s.cbrnbak")
    assert section.last_label.text() == "Last encrypted backup: 03/05/2026"
    portuguese = "\u00daltimo backup criptografado: 05/03/2026"
    spanish = "\u00daltima copia cifrada: 05/03/2026"
    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: section.last_label.text() == portuguese)
    app_context.translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: section.last_label.text() == spanish)


def test_the_section_texts_follow_a_language_switch(app_context: AppContext, qtbot: QtBot) -> None:
    section = BackupSettingsSection(app_context)
    qtbot.addWidget(section)
    assert section.save_action.text() == "Save settings"
    assert section.passphrase_row.caption.text() == "Minimum passphrase length (characters)"
    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: section.save_action.text() == "Salvar configura\u00e7\u00f5es")
    assert section.daily_row.caption.text() == "Backups locais di\u00e1rios a manter"
    assert section.backup_actions.restore_action.text() == "Restaurar..."


# --------------------------------------------------------------------------- no services


def test_the_factories_build_without_services_and_prompt_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot, tmp_path: Path
) -> None:
    empty = AppContext(
        conn=None,
        clock=app_context.clock,
        location=app_context.location,
        prompts=fake_prompts,
        preferences=PreferencesStore(tmp_path / "nodb", writable=False),
        translator_manager=app_context.translator_manager,
    )
    before = snapshot(app_context.location.path)
    section = create_settings_section(empty)
    qtbot.addWidget(section)
    assert isinstance(section, BackupSettingsSection)
    assert not section.save_action.isEnabled()
    assert not section.backup_actions.backup_action.isEnabled()
    assert not section.backup_actions.restore_action.isEnabled()
    assert section.last_label.text() == "Last encrypted backup: never"
    for dialog in (demo_backup_dialog(empty, None), demo_restore_dialog(empty, None)):
        qtbot.addWidget(dialog)
        assert dialog.windowTitle()
        dialog.show()
        dialog.accept()  # nothing to run: the dialog stays open
        assert dialog.isVisible()
    section.backup_actions.back_up()
    section.backup_actions.restore()
    assert fake_prompts.calls == []
    assert snapshot(app_context.location.path) == before
    empty.deleteLater()


def test_the_dialogs_are_registered_through_the_registry(
    app_context: AppContext, qtbot: QtBot
) -> None:
    specs = (
        DialogSpec("backup.test_backup", demo_backup_dialog),
        DialogSpec("backup.test_restore", demo_restore_dialog),
    )
    with registry.registered(*specs):
        found = [s for s in registry.dialogs() if s.key.startswith("backup.test_")]
        assert [s.key for s in found] == ["backup.test_backup", "backup.test_restore"]
        backup_dialog, restore_dialog = (s.factory(app_context, None) for s in found)
    for dialog in (backup_dialog, restore_dialog):
        qtbot.addWidget(dialog)
        assert isinstance(dialog, PassphraseDialog)
    assert isinstance(backup_dialog, PassphraseDialog)
    assert isinstance(restore_dialog, PassphraseDialog)
    assert backup_dialog.confirm_edit is not None
    assert restore_dialog.confirm_edit is None


# --------------------------------------------------------------------------- pseudo-locale walk

FACTORIES: dict[str, Callable[[AppContext], QWidget]] = {
    "settings_section": create_settings_section,
    "backup_dialog": lambda context: demo_backup_dialog(context, None),
    "restore_dialog": lambda context: demo_restore_dialog(context, None),
}


@pytest.mark.parametrize("name", list(FACTORIES))
def test_everything_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot, name: str
) -> None:
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    assert_fully_translated(widget)


def test_the_section_with_a_recorded_backup_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext,
    fake_prompts: FakePrompts,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    section = BackupSettingsSection(pseudo_context)
    qtbot.addWidget(section)
    _cheap(section.backup_actions)
    _back_up(section.backup_actions, fake_prompts, section, _out(tmp_path) / "p.cbrnbak")
    assert section.last_label.text() != "\u27e6Last encrypted backup: \u27e7"
    assert_fully_translated(section)


def test_the_titles_are_translated(pseudo_context: AppContext) -> None:
    assert settings_section_title() == "\u27e6Backup and restore\u27e7"


# --------------------------------------------------------------------------- labels


def test_every_code_has_a_label_in_all_languages(app_context: AppContext) -> None:
    texts: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        texts[lang] = {code: error_label(code) for code in ALL_ERROR_CODES}
    for lang in LANGUAGES:
        for code, text in texts[lang].items():
            assert text.strip(), (lang, code)
            assert text != code, (lang, code)
    for code, english in texts["en_US"].items():
        assert english == EXPECTED_ENGLISH[code], code
        assert texts["pt_BR"][code] != english, code
        assert texts["es_ES"][code] != english, code
    assert set(ALL_ERROR_CODES) == set(EXPECTED_ENGLISH)
    assert len(set(ALL_ERROR_CODES)) == len(ALL_ERROR_CODES)


def test_an_unknown_code_is_shown_as_itself() -> None:
    assert error_label("NOT_A_CODE") == "NOT_A_CODE"


def _own_constants(module: ModuleType) -> set[str]:
    """Upper-case names the module DEFINES as a string equal to the name (imports excluded)."""
    found: set[str] = set()
    for node in ast.parse(inspect.getsource(module)).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and value.value == target.id
        ):
            found.add(target.id)
    return found


def test_all_error_codes_lists_every_code_of_the_restore_and_backup_services() -> None:
    restore_codes = _own_constants(restore_module)
    assert restore_codes == {
        "WRONG_PASSPHRASE",
        "CORRUPT_BACKUP",
        "BACKUP_TOO_NEW",
        "BACKUP_UNREADABLE",
        "TEMP_FILE_FAILED",
        "INTEGRITY_FAILED",
        "DEMO_MISMATCH",
        "NOT_AN_APPLICATION_DATABASE",
        "MIGRATION_FAILED",
        "OTHER_CONNECTIONS_OPEN",
        "TRANSACTION_OPEN",
        "JOURNAL_PRESENT",
        "SAFETY_COPY_FAILED",
        "RESTORE_COPY_FAILED",
    }
    backup_codes = _own_constants(backup_service_module)
    assert {"PASSPHRASE_MISMATCH", "BACKUP_WRITE_FAILED", "BACKUP_VERIFY_FAILED"} <= backup_codes
    assert (restore_codes | backup_codes | {"READ_ONLY"}) <= set(ALL_ERROR_CODES)
