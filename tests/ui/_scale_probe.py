# SPDX-License-Identifier: GPL-3.0-or-later
"""Child process of the ``QT_SCALE_FACTOR=2`` test (PLAN.md T10.4, ``test_accessibility.py``).

Run as ``python -m tests.ui._scale_probe <data folder> <compiled catalogue folder> [language]``
(language: ``en-US`` when omitted) with ``QT_QPA_PLATFORM=offscreen`` and ``QT_SCALE_FACTOR=2``
in the environment. The Qt scale factor is read when the application object is created, so the
test cannot change it in its own process.

The probe collects every Qt warning, critical and fatal message through ``qInstallMessageHandler``
(installed before the application object exists), starts the real window on the demo database,
makes every page current, shows every dialog of the dialog registry, and prints ONE line of JSON
with the keys ``pages`` and ``dialogs`` (counts), ``ratio`` (the device-pixel ratio of the primary
screen) and ``messages`` (the Qt warnings collected).
"""

import json
import sys
from pathlib import Path

from PySide6.QtCore import QMessageLogContext, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication

from cbrn_dashboard.app import AppHandle, start
from cbrn_dashboard.cli import CliOptions
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.paths import DataLocation, LocationSource
from cbrn_dashboard.ui.shell import registry
from tests.ui._fakes import FakePrompts

NOW = "2026-03-05T12:00:00Z"
_SERIOUS = (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg)
_messages: list[str] = []


def _collect(kind: QtMsgType, _context: QMessageLogContext, message: str) -> None:
    if kind in _SERIOUS:
        _messages.append(message)


def main(argv: list[str]) -> int:
    data_dir = Path(argv[1])
    qm_dir = Path(argv[2])
    lang = argv[3] if len(argv) > 3 else "en-US"
    qInstallMessageHandler(_collect)
    options = CliOptions(data_dir=str(data_dir), lang=lang, demo=True)
    location = DataLocation(path=data_dir, source=LocationSource.CLI, writable=True)
    result = start(
        options,
        location,
        clock=FixedClock.at(NOW),
        prompts=FakePrompts(),
        qm_dir=qm_dir,
        hooks=(),
    )
    if not isinstance(result, AppHandle):
        sys.stdout.write(json.dumps({"error": result, "messages": _messages}) + "\n")
        return 1
    window = result.window
    window.show()
    app = result.app
    app.processEvents()
    pages = 0
    for spec in registry.pages():
        window.show_page(spec.key)
        app.processEvents()
        pages += 1
    dialogs = 0
    for dialog_spec in registry.dialogs():
        dialog = dialog_spec.factory(result.context, window)
        dialog.show()
        app.processEvents()
        dialog.close()
        dialog.deleteLater()
        dialogs += 1
    screen = QGuiApplication.primaryScreen()
    ratio = 1.0 if screen is None else float(screen.devicePixelRatio())
    result.close()
    report = {"pages": pages, "dialogs": dialogs, "ratio": ratio, "messages": _messages}
    sys.stdout.write(json.dumps(report) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
