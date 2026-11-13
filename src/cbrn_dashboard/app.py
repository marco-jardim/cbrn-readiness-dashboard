# SPDX-License-Identifier: GPL-3.0-or-later
"""Application bootstrap and the start-up sequence (PLAN.md tasks T0.7 and T1.9).

``main`` parses the command line, resolves the data folder and either runs the self-test or starts
the application. ``start`` is the start-up sequence and does everything except entering the event
loop, so tests (and the self-test) can create the real window without blocking.

The sequence, in order:

1. the command line is parsed and the data location resolved (``--self-test`` short-circuits in
   ``main``: it never opens the real database, takes no lock and writes only ``selftest.json``);
2. the mode is decided: a writable folder means read-write; a folder that is not writable (or a
   database file that is not) with an existing database means READ-ONLY (D02); a folder that is
   not writable with no database is explained and ends with exit code 1;
3. the application, the translators and the preferences are set up (``--lang`` for this run only,
   else the saved language, else Brazilian Portuguese; later menu switches are saved);
4. logging is configured (in memory when read-only) and the crash hook is wired to a translated
   dialog that shows a code, never the exception message (D22);
5. in read-write mode the exclusive instance lock is taken BEFORE the database is opened; a second
   instance explains itself and ends with exit code 1 without touching the database;
6. the database is opened: the demo database for ``--demo``, a read-only connection in read-only
   mode, otherwise the real database, migrated; a database written by a newer version or with a
   hot journal is explained and ends with exit code 1;
7. the clock sanity check: a clock earlier than the newest ``change_log`` row or than the build
   timestamp marks the session ``clock_suspect``;
8. ``AppContext`` and the main window (with its banners) are built;
9. the registered start-up hooks run once, in order.

Whether the database is a demo database comes from ``app_meta.is_demo`` of the OPEN database,
never from the command line (D25).
"""

import json
import sqlite3
import sys
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from functools import partial
from importlib import resources
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from cbrn_dashboard import __version__, cli
from cbrn_dashboard.clock import Clock, SystemClock
from cbrn_dashboard.demo import demo_database_path, open_demo_database
from cbrn_dashboard.domain.dates import parse_utc_timestamp
from cbrn_dashboard.logging_setup import (
    CrashReport,
    LoggingHandle,
    configure_logging,
    crash_code,
    install_exception_hook,
    log_event,
    log_exception,
)
from cbrn_dashboard.paths import DataLocation, is_file_writable, resolve_data_location
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.services.backup import daily_backup_startup
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import (
    DatabaseConnection,
    DatabaseError,
    HotJournalError,
    open_database,
)
from cbrn_dashboard.storage.migrate import (
    DatabaseIdentity,
    DatabaseTooNewError,
    load_migrations,
    open_and_migrate,
)
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.instance_lock import InstanceLock
from cbrn_dashboard.ui.shell.main_window import MainWindow
from cbrn_dashboard.ui.shell.prompts import Prompts, QtPrompts

APPLICATION_NAME = "cbrn-dashboard"
BUILD_INFO_RESOURCE = "build_info.json"
EXIT_FAILED = 1


# --------------------------------------------------------------------------- start-up hooks


@dataclass(frozen=True)
class StartupHook:
    """Work to do once after start-up; each hook declares when it applies.

    ``runs_read_only`` and ``runs_in_demo`` say whether it runs in read-only mode and with a demo
    database. ``needs_trusted_clock`` hooks (automatic snapshot, backup rotation) are skipped for
    the session when the clock sanity check failed.
    """

    name: str
    run: Callable[[AppContext], None]
    runs_read_only: bool = False
    runs_in_demo: bool = False
    needs_trusted_clock: bool = False


#: The registered start-up hooks, one entry each, run in this order. T7.1 (daily backup) is
#: registered; T7.3 (tmp clean-up) and T8.1 (monthly snapshot) each still add one entry. The daily
#: backup is skipped in read-only and demo mode; it does not need a trusted clock because only its
#: rotation is skipped for a suspect clock (inside the service).
STARTUP_HOOKS: tuple[StartupHook, ...] = (
    StartupHook(
        "daily-backup",
        daily_backup_startup,
        runs_read_only=False,
        runs_in_demo=False,
        needs_trusted_clock=False,
    ),
)


def hook_applies(hook: StartupHook, context: AppContext) -> bool:
    """Whether ``hook`` runs in the mode of ``context`` (read-only, demo, clock trust)."""
    if context.read_only and not hook.runs_read_only:
        return False
    if context.is_demo and not hook.runs_in_demo:
        return False
    return not (hook.needs_trusted_clock and context.clock_suspect)


def run_startup_hooks(context: AppContext, hooks: Sequence[StartupHook]) -> tuple[str, ...]:
    """Run the hooks that apply, in order; return their names.

    A hook that raises is logged (type and frames only) and does not stop the others.
    """
    ran: list[str] = []
    for hook in hooks:
        if not hook_applies(hook, context):
            continue
        try:
            hook.run(context)
        except Exception as exc:
            log_exception("APP.STARTUP_HOOK_FAILED", exc)
        ran.append(hook.name)
    return tuple(ran)


# --------------------------------------------------------------------------- the handle


@dataclass
class AppHandle:
    """What ``start`` created. ``close()`` undoes it all (tests call it; ``main`` does too)."""

    app: QApplication
    translator_manager: TranslatorManager
    window: MainWindow
    preferences: PreferencesStore
    context: AppContext
    logging: LoggingHandle
    instance_lock: InstanceLock | None = None
    hooks_run: tuple[str, ...] = ()
    cleanup: ExitStack = field(default_factory=ExitStack, repr=False)

    @property
    def database(self) -> DatabaseConnection | None:
        """The open database connection, if any."""
        return self.context.conn

    @database.setter
    def database(self, conn: DatabaseConnection | None) -> None:
        self.context.conn = conn

    @property
    def is_demo(self) -> bool:
        """Whether the open database is a demo database, read from ``app_meta`` (D25).

        Never derived from the command line; ``False`` while no database is open.
        """
        conn = self.database
        return conn is not None and app_meta.read_is_demo(conn)

    def close_database(self) -> None:
        """Close the database connection, if any."""
        conn = self.context.conn
        if conn is not None:
            conn.close()
            self.context.conn = None

    def close(self) -> None:
        """Close the window and the database, release the lock, uninstall the exception hook,
        close logging and remove the translators. Safe to call more than once."""
        self.window.close()
        self.close_database()
        self.cleanup.close()


# --------------------------------------------------------------------------- helpers


def ensure_application() -> QApplication:
    """Return the running ``QApplication``, creating one if there is none."""
    instance = QApplication.instance()
    if instance is None:
        return QApplication(sys.argv[:1])
    if not isinstance(instance, QApplication):
        raise RuntimeError("A QCoreApplication without widgets support already exists")
    return instance


def _remember_language(preferences: PreferencesStore, code: str) -> None:
    """Store the language the user picked; a read-only folder keeps it for the session only."""
    preferences.update(language=code)


def read_build_timestamp() -> datetime | None:
    """The UTC build time from the optional resource ``cbrn_dashboard/build_info.json``.

    ``{"built_at_utc": "2026-03-05T12:00:00Z"}``. ``None`` when the file is absent (running from
    source) or unreadable: the build half of the clock check is then skipped.
    """
    try:
        text = resources.files("cbrn_dashboard").joinpath(BUILD_INFO_RESOURCE).read_text("utf-8")
        data: object = json.loads(text)
        if not isinstance(data, dict):
            return None
        return parse_utc_timestamp(data["built_at_utc"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def newest_change_time(conn: DatabaseConnection) -> datetime | None:
    """The newest ``change_log.at_utc`` as a UTC instant, or ``None`` (no rows, or unreadable)."""
    try:
        # Second-precision ISO text with a "Z" sorts like the instants it stands for.
        row = conn.execute("SELECT max(at_utc) FROM change_log").fetchone()
    except sqlite3.Error:
        return None
    value: object = None if row is None else row[0]
    if not isinstance(value, str):
        return None
    try:
        return parse_utc_timestamp(value)
    except ValueError:
        return None


def clock_is_suspect(
    conn: DatabaseConnection,
    clock: Clock,
    build_timestamp: Callable[[], datetime | None] = read_build_timestamp,
) -> bool:
    """Whether the clock is earlier than the newest change record or than the build time."""
    now = clock.utc_now()
    newest = newest_change_time(conn)
    if newest is not None and now < newest:
        return True
    built = build_timestamp()
    return built is not None and now < built


class _Mode(Enum):
    READ_WRITE = auto()
    READ_ONLY = auto()
    UNUSABLE = auto()


def _decide_mode(location: DataLocation, database_path: Path) -> _Mode:
    """D02: read-write only when the folder AND an existing database file can be written."""
    exists = database_path.is_file()
    if location.writable and (not exists or is_file_writable(database_path)):
        return _Mode.READ_WRITE
    return _Mode.READ_ONLY if exists else _Mode.UNUSABLE


def _open_database(
    options: cli.CliOptions,
    location: DataLocation,
    clock: Clock,
    database_path: Path,
    mode: _Mode,
) -> DatabaseConnection:
    if mode is _Mode.READ_ONLY:
        conn = open_database(database_path, read_only=True)
        # A read-only connection cannot migrate; only a database from the future is refused here.
        # (An older schema in a read-only folder is left to T7.5.)
        try:
            found = int(conn.execute("PRAGMA user_version").fetchone()[0])
            supported = len(load_migrations())
            if found > supported:
                raise DatabaseTooNewError(found, supported)
        except BaseException:
            conn.close()
            raise
        return conn
    if options.demo:
        return open_demo_database(location.path, clock)
    conn = open_and_migrate(
        location.database_path, data_dir=location.path, identity=DatabaseIdentity.REAL
    )
    try:
        app_meta.initialise(conn, is_demo=False, created_with=__version__)
    except BaseException:
        conn.close()
        raise
    return conn


def _dispose_manager(manager: TranslatorManager) -> None:
    manager.clear()
    manager.setParent(None)


# --------------------------------------------------------------------------- translated messages


def _title_cannot_start() -> str:
    return QCoreApplication.translate("Shell", "Cannot start")


def _text_no_database() -> str:
    return QCoreApplication.translate(
        "Shell",
        "The data folder is not writable and has no database, so nothing can be opened.",
    )


def _text_locked() -> str:
    return QCoreApplication.translate(
        "Shell",
        "Another instance is already using this data folder. Close it and start again.",
    )


def _text_hot_journal() -> str:
    return QCoreApplication.translate(
        "Shell", "The database has an unfinished write and cannot be opened read-only."
    )


def _text_too_new() -> str:
    return QCoreApplication.translate(
        "Shell", "The database was written by a newer version of this application."
    )


def _text_open_failed(code: str) -> str:
    template = QCoreApplication.translate("Shell", "The database could not be opened. Code: %1")
    return template.replace("%1", code)


def _show_crash(prompts: Prompts, report: CrashReport) -> None:
    """The crash callback: a translated dialog with the CODE only, never the message (D22)."""
    title = QCoreApplication.translate("Shell", "Unexpected error")
    template = QCoreApplication.translate("Shell", "An unexpected error occurred. Code: %1")
    prompts.error(None, title, template.replace("%1", report.code))


def _fail(stack: ExitStack, prompts: Prompts, text: str) -> int:
    """Explain the problem through the prompts, undo what was set up, give the exit code."""
    prompts.error(None, _title_cannot_start(), text)
    stack.close()
    return EXIT_FAILED


# --------------------------------------------------------------------------- the sequence


def start(
    options: cli.CliOptions,
    location: DataLocation,
    *,
    clock: Clock | None = None,
    prompts: Prompts | None = None,
    qm_dir: Path | None = None,
    hooks: Sequence[StartupHook] | None = None,
    lock_factory: Callable[[Path], InstanceLock] = InstanceLock,
    build_timestamp: Callable[[], datetime | None] = read_build_timestamp,
) -> AppHandle | int:
    """Run the start-up sequence (see the module docstring) without entering the event loop.

    Returns the :class:`AppHandle`, or the exit code 1 after explaining the problem through
    ``prompts``. The window is not shown. ``clock`` defaults to the system clock, ``prompts`` to
    the real dialogs, ``hooks`` to :data:`STARTUP_HOOKS` and ``qm_dir`` to the package's own
    ``i18n`` folder.
    """
    active_clock: Clock = SystemClock() if clock is None else clock
    active_prompts: Prompts = QtPrompts() if prompts is None else prompts
    active_hooks = STARTUP_HOOKS if hooks is None else tuple(hooks)

    database_path = demo_database_path(location.path) if options.demo else location.database_path
    mode = _decide_mode(location, database_path)
    read_only = mode is not _Mode.READ_WRITE

    preferences = PreferencesStore(location.path, writable=not read_only)
    saved = preferences.load()  # never raises; a damaged file gives defaults plus a warning
    app = ensure_application()
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(__version__)
    manager = TranslatorManager(app, qm_dir)

    stack = ExitStack()
    stack.callback(_dispose_manager, manager)
    try:
        # --lang overrides the saved language for this run only and is never stored by itself.
        manager.set_language(saved.language if options.lang is None else options.lang)

        logging_handle = configure_logging(location.path, read_only=read_only)
        stack.callback(logging_handle.close)
        stack.callback(install_exception_hook(partial(_show_crash, active_prompts)))
        log_event("APP.START")

        if mode is _Mode.UNUSABLE:
            # Choosing another folder is the read-only flow of T7.5; here the user is only told.
            log_event("APP.NO_DATABASE")
            return _fail(stack, active_prompts, _text_no_database())

        lock: InstanceLock | None = None
        if mode is _Mode.READ_WRITE:
            lock = lock_factory(location.path)
            if not lock.acquire():
                log_event("APP.INSTANCE_LOCKED")
                return _fail(stack, active_prompts, _text_locked())
            stack.callback(lock.release)

        try:
            conn = _open_database(options, location, active_clock, database_path, mode)
        except HotJournalError:
            log_event("APP.HOT_JOURNAL")
            return _fail(stack, active_prompts, _text_hot_journal())
        except DatabaseTooNewError:
            log_event("APP.DATABASE_TOO_NEW")
            return _fail(stack, active_prompts, _text_too_new())
        except (DatabaseError, OSError, sqlite3.Error) as exc:
            log_exception("APP.DATABASE_OPEN_FAILED", exc)
            code = (
                exc.code
                if isinstance(exc, DatabaseError)
                else crash_code(type(exc), exc.__traceback__)
            )
            return _fail(stack, active_prompts, _text_open_failed(code))
        stack.callback(conn.close)

        suspect = clock_is_suspect(conn, active_clock, build_timestamp)
        if suspect:
            log_event("APP.CLOCK_SUSPECT")

        context = AppContext(
            conn=conn,
            clock=active_clock,
            location=location,
            prompts=active_prompts,
            preferences=preferences,
            translator_manager=manager,
            read_only=read_only,
            clock_suspect=suspect,
        )
        window = MainWindow(context)
        # Connected after the start-up language is applied: only later (menu) switches are saved.
        manager.language_changed.connect(partial(_remember_language, preferences))
        ran = run_startup_hooks(context, active_hooks)
    except BaseException:
        stack.close()
        raise
    return AppHandle(
        app=app,
        translator_manager=manager,
        window=window,
        preferences=preferences,
        context=context,
        logging=logging_handle,
        instance_lock=lock,
        hooks_run=ran,
        cleanup=stack.pop_all(),
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    qm_dir: Path | None = None,
    prompts: Prompts | None = None,
) -> int:
    """Run the application; returns the process exit code."""
    options = cli.parse_args(argv)
    location = resolve_data_location(cli_data_dir=options.data_dir)
    if options.self_test:
        from cbrn_dashboard import selftest

        return selftest.run(location, qm_dir=qm_dir)
    started = start(options, location, qm_dir=qm_dir, prompts=prompts)
    if isinstance(started, int):
        return started
    try:
        started.window.show()
        return started.app.exec()
    finally:
        started.close()
