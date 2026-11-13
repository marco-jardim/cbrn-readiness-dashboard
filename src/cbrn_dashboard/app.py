# SPDX-License-Identifier: GPL-3.0-or-later
"""Application bootstrap (PLAN.md task T0.7).

``main`` parses the command line, resolves the data folder and either runs the self-test or opens
the main window. ``build_application`` does everything except entering the event loop, so tests
(and the self-test) can create the real window without blocking.

No database is opened here; preferences (and therefore a saved language) arrive with T1.5, so the
language is ``--lang`` or the default, Brazilian Portuguese.
"""

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import QApplication

from cbrn_dashboard import __version__, cli
from cbrn_dashboard.i18n import DEFAULT_LANGUAGE
from cbrn_dashboard.paths import DataLocation, resolve_data_location
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.main_window import MainWindow

APPLICATION_NAME = "cbrn-dashboard"


@dataclass
class AppHandle:
    """What ``build_application`` created."""

    app: QApplication
    translator_manager: TranslatorManager
    window: MainWindow


def ensure_application() -> QApplication:
    """Return the running ``QApplication``, creating one if there is none."""
    instance = QApplication.instance()
    if instance is None:
        return QApplication(sys.argv[:1])
    if not isinstance(instance, QApplication):
        raise RuntimeError("A QCoreApplication without widgets support already exists")
    return instance


def build_application(
    options: cli.CliOptions, location: DataLocation, qm_dir: Path | None = None
) -> AppHandle:
    """Create (or reuse) the application, install the language and build the main window.

    The window is not shown and the event loop is not entered. ``qm_dir=None`` means the package's
    own ``i18n`` folder.
    """
    app = ensure_application()
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(__version__)
    manager = TranslatorManager(app, qm_dir)
    manager.set_language(DEFAULT_LANGUAGE if options.lang is None else options.lang)
    window = MainWindow(manager, location)
    return AppHandle(app=app, translator_manager=manager, window=window)


def main(argv: Sequence[str] | None = None, *, qm_dir: Path | None = None) -> int:
    """Run the application; returns the process exit code."""
    options = cli.parse_args(argv)
    location = resolve_data_location(cli_data_dir=options.data_dir)
    if options.self_test:
        from cbrn_dashboard import selftest

        return selftest.run(location, qm_dir=qm_dir)
    handle = build_application(options, location, qm_dir)
    handle.window.show()
    return handle.app.exec()
