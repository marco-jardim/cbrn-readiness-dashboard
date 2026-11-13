# SPDX-License-Identifier: GPL-3.0-or-later
"""The one helper that opens a LOCAL folder in the file manager (PLAN.md T7.4, T0.4).

``QDesktopServices`` (and ``os.startfile``) may be used only in this file: the layering guard of
``tests/meta`` allows them nowhere else. The helper accepts a local folder path and nothing else:
not a URL, not a file, not a folder that does not exist, and not a network location (a UNC path or
a mapped network drive). Opening Explorer on a folder is a local action; the application itself
makes no network connection.

The result is logged as an event code only (never the path). The opener is a parameter so tests can
check what would be opened without starting a program.
"""

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from cbrn_dashboard.logging_setup import log_event
from cbrn_dashboard.paths import is_network_drive, is_unc_path

__all__ = ["is_openable_folder", "open_local_folder"]


def is_openable_folder(path: Path) -> bool:
    """Whether ``path`` is an existing local folder (not a file, a URL or a network location)."""
    text = str(path)
    if "://" in text or is_unc_path(path):
        return False
    if is_network_drive(path):
        return False
    return path.is_dir()


def open_local_folder(path: Path, *, open_url: Callable[[QUrl], bool] | None = None) -> None:
    """Show the local folder ``path`` in the file manager; anything else is refused and logged.

    ``open_url`` defaults to ``QDesktopServices.openUrl``; it receives a ``file:`` URL.
    """
    if not is_openable_folder(path):
        log_event("UI.OPEN_FOLDER_REFUSED", level=logging.WARNING)
        return
    opener: Callable[[QUrl], bool] = QDesktopServices.openUrl if open_url is None else open_url
    if opener(QUrl.fromLocalFile(str(path.absolute()))):
        log_event("UI.OPEN_FOLDER")
    else:
        log_event("UI.OPEN_FOLDER_FAILED", level=logging.WARNING)
