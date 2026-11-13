# SPDX-License-Identifier: GPL-3.0-or-later
"""Every modal interaction goes through this interface (PLAN.md T1.9, section 9 "Layering").

Message boxes, file and folder pickers and the single-line input dialog are created ONLY here, so
tests substitute a fake (``tests/ui/_fakes.py``) and no test ever blocks on a real dialog.

All callers pass ALREADY TRANSLATED strings (``QCoreApplication.translate("<Context>", ...)`` at the
call site); nothing in this module is translated, which keeps the file free of messages.
"""

from pathlib import Path
from typing import Protocol

from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox, QWidget

__all__ = ["Prompts", "QtPrompts"]


class Prompts(Protocol):
    """The modal interactions the application needs."""

    def info(self, parent: QWidget | None, title: str, text: str) -> None:
        """Show an informational message and wait for the user."""
        ...

    def warning(self, parent: QWidget | None, title: str, text: str) -> None:
        """Show a warning and wait for the user."""
        ...

    def error(self, parent: QWidget | None, title: str, text: str) -> None:
        """Show an error and wait for the user."""
        ...

    def confirm(self, parent: QWidget | None, title: str, text: str) -> bool:
        """Ask a yes/no question; ``True`` only for an explicit yes."""
        ...

    def open_file(self, parent: QWidget | None, title: str, file_filter: str) -> Path | None:
        """Pick an existing file; ``None`` when cancelled."""
        ...

    def save_file(
        self, parent: QWidget | None, title: str, suggested_name: str, file_filter: str
    ) -> Path | None:
        """Pick a file name to write; ``None`` when cancelled."""
        ...

    def choose_folder(self, parent: QWidget | None, title: str) -> Path | None:
        """Pick an existing folder; ``None`` when cancelled."""
        ...

    def text_input(
        self, parent: QWidget | None, title: str, label: str, *, password: bool = False
    ) -> str | None:
        """Ask for one line of text (masked when ``password``); ``None`` when cancelled."""
        ...


class QtPrompts:
    """The real implementation, on ``QMessageBox``, ``QFileDialog`` and ``QInputDialog``."""

    def info(self, parent: QWidget | None, title: str, text: str) -> None:
        QMessageBox.information(parent, title, text)

    def warning(self, parent: QWidget | None, title: str, text: str) -> None:
        QMessageBox.warning(parent, title, text)

    def error(self, parent: QWidget | None, title: str, text: str) -> None:
        QMessageBox.critical(parent, title, text)

    def confirm(self, parent: QWidget | None, title: str, text: str) -> bool:
        answer = QMessageBox.question(
            parent,
            title,
            text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def open_file(self, parent: QWidget | None, title: str, file_filter: str) -> Path | None:
        name, _selected = QFileDialog.getOpenFileName(parent, title, "", file_filter)
        return Path(name) if name else None

    def save_file(
        self, parent: QWidget | None, title: str, suggested_name: str, file_filter: str
    ) -> Path | None:
        name, _selected = QFileDialog.getSaveFileName(parent, title, suggested_name, file_filter)
        return Path(name) if name else None

    def choose_folder(self, parent: QWidget | None, title: str) -> Path | None:
        name = QFileDialog.getExistingDirectory(parent, title)
        return Path(name) if name else None

    def text_input(
        self, parent: QWidget | None, title: str, label: str, *, password: bool = False
    ) -> str | None:
        mode = QLineEdit.EchoMode.Password if password else QLineEdit.EchoMode.Normal
        text, accepted = QInputDialog.getText(parent, title, label, mode)
        return text if accepted else None
