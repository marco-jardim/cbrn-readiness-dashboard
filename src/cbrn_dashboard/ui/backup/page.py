# SPDX-License-Identifier: GPL-3.0-or-later
"""The Backup settings section and the dialog factories (PLAN.md T7.4, P05, P06, P09, K06).

The section (Settings -> Backup) holds the three backup settings with their hard floors (T1.5): the
minimum passphrase length P05 (never below 12), the number of daily local backups kept P06 (never
below 2) and the age in days after which the reminder appears P09. Each carries the "to be
confirmed" badge of its placeholder. It also shows the time of the last encrypted backup and offers
"Back up..." and "Restore..." (the same :class:`~cbrn_dashboard.ui.backup.actions.BackupActions`
the File menu uses). Settings are read and written ONLY through ``context.services.config``.

There is no navigation page. The module-level factories are what the registries of the shell call;
they build without services and never prompt, open a dialog or touch the database.
"""

from dataclasses import dataclass

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.domain.config import (
    DAILY_BACKUPS_FLOOR,
    MAX_DAILY_BACKUPS,
    MAX_PASSPHRASE_LENGTH,
    MAX_WARNING_DAYS,
    PASSPHRASE_LENGTH_FLOOR,
    ReadinessConfig,
)
from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.ui.backup.actions import BackupActions
from cbrn_dashboard.ui.backup.dialogs import PassphraseDialog
from cbrn_dashboard.ui.backup.labels import error_label
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import format_date
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_change,
    current_language,
    follow_language,
    make_edit_action,
)

__all__ = [
    "BackupSettingsSection",
    "create_settings_section",
    "demo_backup_dialog",
    "demo_restore_dialog",
    "settings_section_title",
]


@dataclass
class _Row:
    """One setting: its caption, spin box, placeholder badge and confirm button."""

    field: str
    caption: QLabel
    spin: QSpinBox
    badge: QLabel
    confirm: QPushButton
    placeholder: str | None = None


class BackupSettingsSection(QWidget):
    """Settings -> Backup: P05, P06 and P09 with their floors, the last backup, Back up, Restore."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("backup_section")
        self.context = context
        self.backup_actions = BackupActions(context, self)
        self.passphrase_row = self._make_row(
            "min_passphrase_length",
            "passphrase_spin",
            PASSPHRASE_LENGTH_FLOOR,
            MAX_PASSPHRASE_LENGTH,
        )
        self.daily_row = self._make_row(
            "daily_backups_kept", "daily_spin", DAILY_BACKUPS_FLOOR, MAX_DAILY_BACKUPS
        )
        self.reminder_row = self._make_row(
            "backup_reminder_days", "reminder_spin", 0, MAX_WARNING_DAYS
        )
        self._rows = (self.passphrase_row, self.daily_row, self.reminder_row)
        #: The three values as last loaded into the spin boxes (``None`` before the first load).
        self._loaded: tuple[int, int, int] | None = None
        #: The error code of a configuration that cannot be read (``None`` while it can be).
        self._config_error: str | None = None
        self.config_error_label = QLabel(self)
        self.config_error_label.setObjectName("config_error_label")
        self.config_error_label.setWordWrap(True)
        self.config_error_label.setVisible(False)
        self.floors_label = QLabel(self)
        self.floors_label.setWordWrap(True)
        self.last_label = QLabel(self)
        self.last_label.setObjectName("last_backup_label")
        self.save_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Backup", "Save settings"),
            self.save_settings,
        )
        self._edit_actions: tuple[EditAction, ...] = (self.save_action,)

        layout = QVBoxLayout(self)
        layout.addWidget(self.config_error_label)
        for row in self._rows:
            line = QHBoxLayout()
            line.addWidget(row.caption)
            line.addWidget(row.spin)
            line.addWidget(row.badge)
            line.addWidget(row.confirm)
            line.addStretch(1)
            layout.addLayout(line)
        layout.addWidget(self.floors_label)
        layout.addLayout(action_row((self.save_action,), self))
        layout.addWidget(self.last_label)
        layout.addLayout(
            action_row(
                (self.backup_actions.backup_action, self.backup_actions.restore_action), self
            )
        )
        layout.addStretch(1)

        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    def _make_row(self, field: str, name: str, minimum: int, maximum: int) -> _Row:
        spin = QSpinBox(self)
        spin.setObjectName(name)
        spin.setRange(minimum, maximum)
        badge = QLabel(self)
        badge.setObjectName(f"{name}_badge")
        confirm = QPushButton(self)
        confirm.setObjectName(f"{name}_confirm")
        badge.setVisible(False)
        confirm.setVisible(False)
        row = _Row(field, QLabel(self), spin, badge, confirm)
        for target in (spin, confirm):
            self.context.register_edit_action(target)
        confirm.clicked.connect(lambda: self._confirm(row))
        return row

    # ----- texts

    def retranslate(self) -> None:
        self.passphrase_row.caption.setText(
            QCoreApplication.translate("Backup", "Minimum passphrase length (characters)")
        )
        self.daily_row.caption.setText(
            QCoreApplication.translate("Backup", "Daily local backups to keep")
        )
        self.reminder_row.caption.setText(
            QCoreApplication.translate(
                "Backup", "Remind me when the last encrypted backup is older than (days)"
            )
        )
        badge = QCoreApplication.translate("Backup", "Placeholder - to be confirmed")
        confirm = QCoreApplication.translate("Backup", "Confirm")
        for row in self._rows:
            row.badge.setText(badge)
            row.confirm.setText(confirm)
        floors = QCoreApplication.translate(
            "Backup", "Minimums that cannot be lowered: %1 passphrase characters, %2 daily backups."
        )
        self.floors_label.setText(
            floors.replace("%1", str(PASSPHRASE_LENGTH_FLOOR)).replace(
                "%2", str(DAILY_BACKUPS_FLOOR)
            )
        )
        for action in self._edit_actions:
            action.retranslate()
        self.backup_actions.retranslate()
        self._show_config_error()
        self._show_last_backup()

    def _show_config_error(self) -> None:
        """Show why the settings inputs are off (a configuration that cannot be read)."""
        code = self._config_error
        self.config_error_label.setVisible(code is not None)
        self.config_error_label.setText("" if code is None else error_label(code))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def _show_last_backup(self) -> None:
        service = self.backup_actions.backup_service()
        last = None if service is None else service.last_encrypted_backup()
        if last is None:
            value = QCoreApplication.translate("Backup", "never")
        else:
            day = self.context.clock.local_date_of(last)
            value = format_date(day, current_language(self.context))
        text = QCoreApplication.translate("Backup", "Last encrypted backup: %1")
        self.last_label.setText(text.replace("%1", value))

    # ----- data

    def _config(self) -> ConfigService | None:
        found: object = getattr(self.context.services, "config", None)
        return found if isinstance(found, ConfigService) else None

    def _typed(self) -> tuple[int, int, int]:
        return (
            self.passphrase_row.spin.value(),
            self.daily_row.spin.value(),
            self.reminder_row.spin.value(),
        )

    def is_dirty(self) -> bool:
        """Whether the spin boxes differ from what was last loaded into them (unsaved edits)."""
        return self._loaded is not None and self._typed() != self._loaded

    def refresh(self) -> None:
        """Show the stored settings with their badges, and the time of the last backup.

        The values are loaded into the spin boxes the first time and when they hold no unsaved
        edit: a ``data_changed`` of another page must not discard what was typed.
        """
        config = self._config()
        stored = ReadinessConfig()
        self._config_error = None
        if config is not None:
            try:
                stored = config.load()
            except ServiceError as error:
                self._config_error = error.code
                config = None
        self._show_config_error()
        values = {
            "min_passphrase_length": stored.min_passphrase_length,
            "daily_backups_kept": stored.daily_backups_kept,
            "backup_reminder_days": stored.backup_reminder_days,
        }
        load_values = not self.is_dirty()
        for row in self._rows:
            row.placeholder = None
            if config is not None:
                try:
                    row.placeholder = config.badge_for_field(row.field)
                except ServiceError:
                    row.placeholder = None
            if load_values:
                row.spin.setValue(values[row.field])
            row.badge.setVisible(row.placeholder is not None)
            row.confirm.setVisible(row.placeholder is not None)
            self.context.set_edit_enabled(row.spin, config is not None)
            self.context.set_edit_enabled(row.confirm, config is not None)
        self.context.set_edit_enabled(self.save_action, config is not None)
        if load_values:
            self._loaded = self._typed()
        self.backup_actions.update_enabled()
        self._show_last_backup()

    # ----- changes

    def save_settings(self) -> None:
        """Store the three values; a refused value is shown translated and the typed ones stay."""
        config = self._config()
        if config is None:
            return
        passphrase = self.passphrase_row.spin.value()
        daily = self.daily_row.spin.value()
        reminder = self.reminder_row.spin.value()

        def save() -> object:
            return config.save(
                config.load().with_changes(
                    min_passphrase_length=passphrase,
                    daily_backups_kept=daily,
                    backup_reminder_days=reminder,
                )
            )

        if apply_change(self.context, self, error_label, save):
            self._loaded = None  # what is typed is now what is stored
            self.refresh()

    def _confirm(self, row: _Row) -> None:
        config = self._config()
        placeholder = row.placeholder
        if config is None or placeholder is None:
            return
        apply_change(self.context, self, error_label, lambda: config.confirm(placeholder))


# --------------------------------------------------------------------------- registry factories


def settings_section_title() -> str:
    return QCoreApplication.translate("Backup", "Backup and restore")


def create_settings_section(context: AppContext) -> QWidget:
    return BackupSettingsSection(context)


def demo_backup_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """The passphrase dialog of a backup (two fields); it does nothing when accepted."""
    return PassphraseDialog(context, parent, repeat=True)


def demo_restore_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """The passphrase dialog of a restore (one field); it does nothing when accepted."""
    return PassphraseDialog(context, parent, repeat=False)
