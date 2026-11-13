# SPDX-License-Identifier: GPL-3.0-or-later
"""Application bootstrap (PLAN.md task T0.7).

``main`` parses the command line, resolves the data folder and either runs the self-test or opens
the main window. ``build_application`` does everything except entering the event loop, so tests
(and the self-test) can create the real window without blocking.

The only database opened here is the demo database of ``--demo`` (T1.7); the start-up sequence that
opens the real database arrives with T1.9. The start-up language is ``--lang`` (this run only),
else the saved preference, else Brazilian Portuguese; a later switch is saved in ``prefs.json``.
"""

import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtWidgets import QApplication

from cbrn_dashboard import __version__, cli
from cbrn_dashboard.clock import SystemClock
from cbrn_dashboard.demo import open_demo_database
from cbrn_dashboard.paths import DataLocation, resolve_data_location
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection, DatabaseError
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.main_window import MainWindow

APPLICATION_NAME = "cbrn-dashboard"


@dataclass
class AppHandle:
    """What ``build_application`` created."""

    app: QApplication
    translator_manager: TranslatorManager
    window: MainWindow
    preferences: PreferencesStore
    database: DatabaseConnection | None = None

    @property
    def is_demo(self) -> bool:
        """Whether the open database is a demo database, read from ``app_meta`` (D25).

        Never derived from the command line; ``False`` while no database is open.
        """
        return self.database is not None and app_meta.read_is_demo(self.database)

    def close_database(self) -> None:
        """Close the database connection, if any."""
        if self.database is not None:
            self.database.close()
            self.database = None


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
    own ``i18n`` folder. With ``options.demo`` the demo database is opened (and seeded on first
    use) before the window is built and kept on the handle; without it no database is opened.
    """
    # Opening the real database belongs to the start-up sequence of T1.9.
    database = open_demo_database(location.path, SystemClock()) if options.demo else None
    preferences = PreferencesStore(location.path, writable=location.writable)
    saved = preferences.load()  # never raises; a damaged file gives defaults plus a warning
    try:
        app = ensure_application()
        app.setApplicationName(APPLICATION_NAME)
        app.setApplicationVersion(__version__)
        manager = TranslatorManager(app, qm_dir)
        # --lang overrides the saved language for this run only and is never stored by itself.
        manager.set_language(saved.language if options.lang is None else options.lang)
        window = MainWindow(manager, location)
        # Connected after the start-up language is applied: only later (menu) switches are saved.
        manager.language_changed.connect(partial(_remember_language, preferences))
    except BaseException:
        if database is not None:
            database.close()
        raise
    return AppHandle(
        app=app,
        translator_manager=manager,
        window=window,
        preferences=preferences,
        database=database,
    )


def _remember_language(preferences: PreferencesStore, code: str) -> None:
    """Store the language the user picked; a read-only folder keeps it for the session only."""
    preferences.update(language=code)


def main(argv: Sequence[str] | None = None, *, qm_dir: Path | None = None) -> int:
    """Run the application; returns the process exit code."""
    options = cli.parse_args(argv)
    location = resolve_data_location(cli_data_dir=options.data_dir)
    if options.self_test:
        from cbrn_dashboard import selftest

        return selftest.run(location, qm_dir=qm_dir)
    if options.demo and not location.writable:
        return 1  # a translated message arrives with T1.9 / T7.5
    try:
        handle = build_application(options, location, qm_dir)
    except (OSError, sqlite3.Error, DatabaseError):
        if options.demo:
            return 1  # a translated message arrives with T1.9 / T7.5
        raise
    try:
        handle.window.show()
        return handle.app.exec()
    finally:
        handle.close_database()
