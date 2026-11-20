# SPDX-License-Identifier: GPL-3.0-or-later
"""The passphrase dialog of the backup and restore flows (PLAN.md T7.4, D04, K06).

One dialog class serves both flows. For a backup it asks for the passphrase TWICE and warns that a
lost passphrase cannot be recovered; for a restore it asks once. The dialog never judges the
passphrase itself: the callable it is given (``on_submit``) runs the service, which applies the
rules of P05 and the strength rule, and returns ``True`` when the work is done.

The passphrase is held only by the two password-mode line edits. It is never stored, logged or put
into a title, tooltip, accessible name or message, and both edits are emptied after every attempt
and when the dialog closes. The dialog is opened without blocking (``open_dialog``).
"""

import weakref
from collections.abc import Callable
from functools import partial

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QWidget

from cbrn_dashboard.domain.config import PASSPHRASE_LENGTH_FLOOR
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.widgets import FormDialog

__all__ = ["PassphraseDialog", "open_dialog"]

#: What the dialog hands to its callable: the passphrase and (for a backup) its confirmation.
type SubmitPassphrase = Callable[[str, str | None], bool]

_SECRET_HINTS = (
    Qt.InputMethodHint.ImhHiddenText
    | Qt.InputMethodHint.ImhNoAutoUppercase
    | Qt.InputMethodHint.ImhNoPredictiveText
    | Qt.InputMethodHint.ImhSensitiveData
)

_kept: list[QDialog] = []


def open_dialog(dialog: QDialog) -> None:
    """Show ``dialog`` window-modally without blocking; it deletes itself when closed.

    A dialog without a parent is kept alive here until it finishes.
    """
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    if dialog.parent() is None:
        _kept.append(dialog)
        # A weak reference, never a closure holding the dialog (it deletes itself on close).
        dialog.finished.connect(partial(_forget, weakref.ref(dialog)))
    dialog.open()


def _forget(reference: weakref.ref[QDialog], _result: int = 0) -> None:
    """Drop the finished dialog from the kept ones."""
    dialog = reference()
    if dialog is not None and dialog in _kept:
        _kept.remove(dialog)


def _secret_edit(parent: QWidget, name: str) -> QLineEdit:
    edit = QLineEdit(parent)
    edit.setObjectName(name)
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setInputMethodHints(_SECRET_HINTS)
    edit.setClearButtonEnabled(False)
    return edit


class PassphraseDialog(FormDialog):
    """Ask for the passphrase of a backup (``repeat=True``) or of a restore (``repeat=False``)."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        *,
        repeat: bool,
        min_length: int = PASSPHRASE_LENGTH_FLOOR,
        on_submit: SubmitPassphrase | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("backup_passphrase_dialog" if repeat else "restore_passphrase_dialog")
        self._repeat = repeat
        self._min_length = max(min_length, PASSPHRASE_LENGTH_FLOOR)
        self._on_submit = on_submit
        self.intro_label = QLabel(self)
        self.intro_label.setWordWrap(True)
        self.form.addRow(self.intro_label)
        self.passphrase_edit = _secret_edit(self, "passphrase_edit")
        self.add_field(
            lambda: QCoreApplication.translate("Backup", "Passphrase"), self.passphrase_edit
        )
        self.confirm_edit: QLineEdit | None = None
        self.rules_label: QLabel | None = None
        self.warning_label: QLabel | None = None
        if repeat:
            self.confirm_edit = _secret_edit(self, "confirm_edit")
            self.add_field(
                lambda: QCoreApplication.translate("Backup", "Repeat the passphrase"),
                self.confirm_edit,
            )
            self.rules_label = QLabel(self)
            self.rules_label.setWordWrap(True)
            self.warning_label = QLabel(self)
            self.warning_label.setWordWrap(True)
            self.form.addRow(self.rules_label)
            self.form.addRow(self.warning_label)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._repeat:
            self.setWindowTitle(QCoreApplication.translate("Backup", "Encrypted backup"))
            intro = QCoreApplication.translate("Backup", "Choose a passphrase for the backup file.")
        else:
            self.setWindowTitle(QCoreApplication.translate("Backup", "Restore from a backup"))
            intro = QCoreApplication.translate(
                "Backup", "Enter the passphrase that was used to make the backup file."
            )
        self.intro_label.setText(intro)
        if self.rules_label is not None:
            rules = QCoreApplication.translate(
                "Backup", "The passphrase needs at least %1 characters and is not a common word."
            )
            self.rules_label.setText(rules.replace("%1", str(self._min_length)))
        if self.warning_label is not None:
            self.warning_label.setText(
                QCoreApplication.translate(
                    "Backup", "Warning: a lost passphrase cannot be recovered."
                )
            )

    def clear_secrets(self) -> None:
        """Empty the passphrase fields."""
        self.passphrase_edit.clear()
        if self.confirm_edit is not None:
            self.confirm_edit.clear()

    def submit(self) -> bool:
        callback = self._on_submit
        if callback is None:
            return False
        passphrase = self.passphrase_edit.text()
        confirmation = None if self.confirm_edit is None else self.confirm_edit.text()
        try:
            return callback(passphrase, confirmation)
        finally:
            self.clear_secrets()

    def done(self, result: int) -> None:
        self.clear_secrets()
        super().done(result)
