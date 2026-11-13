# SPDX-License-Identifier: GPL-3.0-or-later
"""The actions "Back up...", "Restore..." and "Open data folder" (PLAN.md T7.4, D04, D25, K05).

:class:`BackupActions` owns the three ``QAction`` objects and the flows behind them, so the File
menu of the main window and the Settings section share one implementation. Every file choice and
every message goes through ``context.prompts``; the passphrase is asked for in
:class:`~cbrn_dashboard.ui.backup.dialogs.PassphraseDialog`, which is opened without blocking and
hands the passphrase straight to the service.

* Back up: choose the output file, check the place (network drive, cloud-synchronised folder, the
  data folder itself), ask for the passphrase twice, write the ``.cbrnbak`` file. It is NOT an edit
  action: in read-only mode the backup is still made (in memory) and only the chosen file is
  written.
* Restore: an edit action (disabled in read-only mode). Choose the file, confirm that ALL current
  data is replaced, ask for the passphrase, restore. A failure leaves the data as it was (T7.3);
  after a success ``data_changed`` is emitted so every page reads the restored data.
* Open data folder: hands ``context.location.path`` to ``open_folder``, the single allowed helper
  of ``ui/shell/folders.py`` (wired by the main window); nothing happens while none is set.

The services come from ``context.services.backup`` / ``.restore`` when the context has them,
otherwise they are built here (lazily, on first use) over ``context.conn``. The scrypt parameters
of a new backup and the allow-list of the reader are attributes, so tests can use cheap ones.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtWidgets import QWidget

from cbrn_dashboard.domain.config import PASSPHRASE_LENGTH_FLOOR
from cbrn_dashboard.paths import (
    CLOUD_PLACEHOLDER_MASK,
    ONEDRIVE_ENV_VARS,
    is_network_drive,
    is_unc_path,
    read_file_attributes,
    read_onedrive_mount_points,
)
from cbrn_dashboard.services.backup import BackupService, backup_target
from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.services.errors import READ_ONLY, ServiceError
from cbrn_dashboard.services.restore import RestoreService, RollbackFailedError
from cbrn_dashboard.storage.backup import DatabaseIdentity
from cbrn_dashboard.storage.crypto_backup import (
    ALLOWED_PARAMS,
    DEFAULT_PARAMS,
    FILE_EXTENSION,
    ScryptParams,
)
from cbrn_dashboard.ui.backup.dialogs import PassphraseDialog, open_dialog
from cbrn_dashboard.ui.backup.labels import error_label, fill_placeholders
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.first_run import refresh_backup_reminder
from cbrn_dashboard.ui.shell.widgets import EditAction, make_edit_action

__all__ = ["BackupActions", "DestinationChecks"]


# --------------------------------------------------------------------------- the output place


def _normalise(path: Path) -> Path:
    """Absolute and link-resolved (a junction or ``subst`` drive, ``..``); UNC paths unchanged."""
    absolute = path.absolute()
    if is_unc_path(absolute):
        return absolute
    try:
        return absolute.resolve()
    except (OSError, RuntimeError, ValueError):
        return absolute


def _is_inside(path: Path, root: Path) -> bool:
    """Component-wise, case-insensitive: is ``path`` equal to or below ``root``?

    Both sides are normalised like ``paths._normalise``, so a link does not hide the place.
    """
    folded = tuple(part.casefold() for part in _normalise(path).parts)
    base = tuple(part.casefold() for part in _normalise(root).parts)
    return bool(base) and folded[: len(base)] == base


def _is_network(folder: Path) -> bool:
    return is_unc_path(folder) or is_network_drive(folder)


def _is_cloud_synchronised(folder: Path) -> bool:
    for name in ONEDRIVE_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value and _is_inside(folder, Path(value)):
            return True
    if any(_is_inside(folder, mount) for mount in read_onedrive_mount_points()):
        return True
    return (read_file_attributes(folder) & CLOUD_PLACEHOLDER_MASK) != 0


def _media_unknown(_folder: Path) -> bool:
    """Whether the folder is on removable media: ``False`` always (T7.4 limitation).

    No API the T0.4 guard allows can tell removable from fixed drives: ``QStorageInfo`` has no
    removable flag (its file system type is no indicator: USB drives are often NTFS), and
    ``ctypes`` (``GetDriveType``) is forbidden in application code. The advice to keep a copy on
    separate media is therefore always given after a backup.
    """
    return False


@dataclass(frozen=True)
class DestinationChecks:
    """Probes for the folder of a new backup file (T0.5/T7.5); tests inject their own."""

    network_drive: Callable[[Path], bool]
    cloud_sync: Callable[[Path], bool]
    removable: Callable[[Path], bool]

    @classmethod
    def system(cls) -> Self:
        return cls(
            network_drive=_is_network, cloud_sync=_is_cloud_synchronised, removable=_media_unknown
        )


# --------------------------------------------------------------------------- the actions


class BackupActions(QObject):
    """The three backup actions and their flows; ``anchor`` is the parent of every dialog."""

    def __init__(
        self,
        context: AppContext,
        anchor: QWidget | None = None,
        *,
        open_folder: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(anchor)
        self.context = context
        self.anchor = anchor
        #: Scrypt parameters of a NEW backup, and the parameter sets a restore accepts.
        self.scrypt_params: ScryptParams = DEFAULT_PARAMS
        self.allowed_params: frozenset[ScryptParams] = ALLOWED_PARAMS
        self.checks: DestinationChecks = DestinationChecks.system()
        self.open_folder: Callable[[Path], None] | None = open_folder
        self._backup: BackupService | None = None
        self._restore: RestoreService | None = None

        self.backup_action = EditAction(
            self, lambda: QCoreApplication.translate("Backup", "Back up...")
        )
        self.backup_action.triggered.connect(self.back_up)
        self.restore_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Backup", "Restore..."),
            self.restore,
        )
        self.open_folder_action = EditAction(
            self, lambda: QCoreApplication.translate("Backup", "Open data folder")
        )
        self.open_folder_action.triggered.connect(self.open_data_folder)
        context.translator_manager.language_changed.connect(self.retranslate)
        self.update_enabled()

    # ----- state and texts

    def retranslate(self) -> None:
        for action in (self.backup_action, self.restore_action, self.open_folder_action):
            action.retranslate()

    def update_enabled(self) -> None:
        """Back up needs an open database; Restore also needs a writable one (edit action)."""
        has_data = self.context.conn is not None
        self.backup_action.setEnabled(has_data)
        self.context.set_edit_enabled(self.restore_action, has_data)

    # ----- the services

    def _identity(self) -> DatabaseIdentity:
        return DatabaseIdentity.DEMO if self.context.is_demo else DatabaseIdentity.REAL

    def backup_service(self) -> BackupService | None:
        """The backup service of the context, or one built over its connection; ``None`` without."""
        found: object = getattr(self.context.services, "backup", None)
        if isinstance(found, BackupService):
            return found
        conn = self.context.conn
        if conn is None:
            return None
        if self._backup is None:
            self._backup = BackupService(
                conn,
                self.context.clock,
                data_dir=self.context.location.path,
                identity=self._identity(),
                operator=self.context.operator_label,
            )
        return self._backup

    def restore_service(self) -> RestoreService | None:
        """The restore service of the context, or one built for its data folder."""
        found: object = getattr(self.context.services, "restore", None)
        if isinstance(found, RestoreService):
            return found
        if self.context.conn is None:
            return None
        if self._restore is None:
            self._restore = RestoreService(
                data_dir=self.context.location.path,
                identity=self._identity(),
                clock=self.context.clock,
                operator=self.context.operator_label,
                clock_suspect=lambda: self.context.clock_suspect,
            )
        return self._restore

    def _min_passphrase_length(self) -> int:
        config: object = getattr(self.context.services, "config", None)
        if isinstance(config, ConfigService):
            try:
                return config.load().min_passphrase_length
            except ServiceError:
                return PASSPHRASE_LENGTH_FLOOR
        return PASSPHRASE_LENGTH_FLOOR

    # ----- messages

    def _info(self, title: str, text: str) -> None:
        self.context.prompts.info(self.anchor, title, text)

    def _fail(self, title: str, error: ServiceError | str) -> None:
        """Show the message of a code; a failed put-back also names the safety copy (file name)."""
        if isinstance(error, RollbackFailedError):
            text = error_label(error.code, error.safety_copy_name)
        else:
            text = error_label(error if isinstance(error, str) else error.code)
        self.context.prompts.warning(self.anchor, title, text)

    def _refresh_reminder(self) -> None:
        """The time of the last encrypted backup changed (a backup, a restore): redo the banner."""
        if not self.context.is_demo:  # a demo database has no reminder
            refresh_backup_reminder(self.context)

    # ----- Back up

    def default_file_name(self) -> str:
        """The suggested name: ``cbrn-backup-<local date>.cbrnbak`` (``DEMO-`` first for demo)."""
        prefix = "DEMO-" if self.context.is_demo else ""
        day = self.context.clock.local_date().isoformat()
        return f"{prefix}cbrn-backup-{day}{FILE_EXTENSION}"

    def _destination_accepted(self, destination: Path, title: str) -> bool:
        """Warn about a network, cloud-synchronised or data-folder place; ``True`` to go on."""
        folder = destination.parent
        notes: list[str] = []
        if self.checks.network_drive(folder):
            notes.append(
                QCoreApplication.translate("Backup", "The chosen location is on a network drive.")
            )
        if self.checks.cloud_sync(folder):
            notes.append(
                QCoreApplication.translate(
                    "Backup", "The chosen location is synchronised with a cloud service."
                )
            )
        if _is_inside(folder, self.context.location.path):
            notes.append(
                QCoreApplication.translate(
                    "Backup", "The chosen location is inside the data folder."
                )
            )
        if not notes:
            return True
        question = fill_placeholders(
            QCoreApplication.translate(
                "Backup", "%1 Prefer removable media kept in a safe place. Continue anyway?"
            ),
            " ".join(notes),
        )
        return self.context.prompts.confirm(self.anchor, title, question)

    def _replacement_confirmed(self, destination: Path, title: str) -> bool:
        """``.cbrnbak`` is appended after the save dialog: ask before replacing that other file."""
        target = backup_target(destination)
        if target == destination or not (target.exists() or target.is_symlink()):
            return True
        question = fill_placeholders(
            QCoreApplication.translate("Backup", "The file %1 already exists. Replace it?"),
            target.name,
        )
        return self.context.prompts.confirm(self.anchor, title, question)

    def back_up(self) -> None:
        """Choose the output file, then ask for the passphrase (twice) and write the backup."""
        service = self.backup_service()
        if service is None:
            return
        title = QCoreApplication.translate("Backup", "Encrypted backup")
        file_filter = QCoreApplication.translate("Backup", "Encrypted backup (*.cbrnbak)")
        destination = self.context.prompts.save_file(
            self.anchor, title, self.default_file_name(), file_filter
        )
        if destination is None or not self._destination_accepted(destination, title):
            return
        if not self._replacement_confirmed(destination, title):
            return

        def write(passphrase: str, confirmation: str | None) -> bool:
            return self._write_backup(service, destination, passphrase, confirmation, title)

        open_dialog(
            PassphraseDialog(
                self.context,
                self.anchor,
                repeat=True,
                min_length=self._min_passphrase_length(),
                on_submit=write,
            )
        )

    def _write_backup(
        self,
        service: BackupService,
        destination: Path,
        passphrase: str,
        confirmation: str | None,
        title: str,
    ) -> bool:
        try:
            result = service.create_encrypted_backup(
                destination,
                passphrase,
                confirmation,
                params=self.scrypt_params,
                replace_extended=True,  # the user confirmed it in ``_replacement_confirmed``
            )
        except ServiceError as error:
            self._fail(title, error)
            return False
        if self.checks.removable(result.path.parent):
            pattern = QCoreApplication.translate(
                "Backup", "The encrypted backup was written to %1."
            )
        else:
            pattern = QCoreApplication.translate(
                "Backup",
                "The encrypted backup was written to %1. "
                "Keep another copy on separate media, away from this computer.",
            )
        self._info(title, fill_placeholders(pattern, str(result.path)))
        self._refresh_reminder()
        self.context.notify_data_changed()  # the time of the last encrypted backup changed
        return True

    # ----- Restore

    def restore(self) -> None:
        """Choose a backup file, confirm, ask for its passphrase and restore it."""
        title = QCoreApplication.translate("Backup", "Restore from a backup")
        if self.context.read_only:
            self._fail(title, READ_ONLY)
            return
        service = self.restore_service()
        conn = self.context.conn
        if service is None or conn is None:
            return
        file_filter = QCoreApplication.translate("Backup", "Encrypted backup (*.cbrnbak)")
        source = self.context.prompts.open_file(self.anchor, title, file_filter)
        if source is None:
            return
        question = fill_placeholders(
            QCoreApplication.translate(
                "Backup",
                "Restoring replaces ALL the data now in the application with %1. "
                "A safety copy of the current data is kept first. Continue?",
            ),
            source.name,
        )
        if not self.context.prompts.confirm(self.anchor, title, question):
            return

        def run(passphrase: str, _confirmation: str | None) -> bool:
            return self._run_restore(service, source, passphrase, title)

        open_dialog(PassphraseDialog(self.context, self.anchor, repeat=False, on_submit=run))

    def _run_restore(
        self, service: RestoreService, source: Path, passphrase: str, title: str
    ) -> bool:
        conn = self.context.conn
        if conn is None:
            return False
        try:
            result = service.restore(conn, source, passphrase, allowed_params=self.allowed_params)
        except ServiceError as error:
            self._fail(title, error)
            return False
        if result.migrated_from is None:
            text = fill_placeholders(
                QCoreApplication.translate(
                    "Backup", "The backup was restored. The previous data was kept as %1."
                ),
                result.safety_copy.name,
            )
        else:
            text = fill_placeholders(
                QCoreApplication.translate(
                    "Backup",
                    "The backup was restored. The previous data was kept as %1. "
                    "The backup was upgraded from schema version %2 to %3.",
                ),
                result.safety_copy.name,
                str(result.migrated_from),
                str(result.restored_schema_version),
            )
        self._info(title, text)
        self._refresh_reminder()
        self.context.notify_data_changed()
        return True

    # ----- Open data folder

    def open_data_folder(self) -> None:
        """Hand the local data folder to the single allowed helper (a local action)."""
        if self.open_folder is not None:
            self.open_folder(self.context.location.path)
