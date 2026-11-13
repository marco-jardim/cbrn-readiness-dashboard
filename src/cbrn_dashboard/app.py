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
   not writable with no database is explained and the user is offered another folder through the
   prompts (T7.5): a usable choice is remembered in the profile pointer file ``location.json`` and
   the sequence starts again with it, otherwise the start ends with exit code 1 (so does the demo
   case and a missing profile folder, which are only explained);
3. the application, the translators and the preferences are set up (``--lang`` for this run only,
   else the saved language, else Brazilian Portuguese; later menu switches are saved);
4. logging is configured in memory and the crash hook is wired to a translated dialog that shows
   a code, never the exception message (D22); an unexpected failure anywhere in the sequence is
   logged as ``APP.STARTUP_FAILED``, shown the same way and ends with exit code 1;
5. in read-write mode the exclusive instance lock is taken BEFORE the database is opened and
   before the log file is opened; a second instance explains itself and ends with exit code 1
   without touching the database or the log folder;
6. the database is opened: the demo database for ``--demo``, a read-only connection in read-only
   mode (refused unless it has the current schema, belongs to this application and, for
   ``--demo``, is a demo database), otherwise the real database, migrated; a refused or unusable
   database is explained and ends with exit code 1. A read-write ``--demo`` start of a demo
   database created on another day asks once whether to create the demo data again for today
   (nothing is asked or written in read-only mode);
7. the clock sanity check: a clock earlier than the newest ``change_log`` row or than the build
   timestamp marks the session ``clock_suspect``;
8. ``AppContext`` and the main window (with its banners) are built;
9. the registered start-up hooks run once, in order (the first-run notice and the backup reminder
   of T7.5 are the last two).

Whether the database is a demo database comes from ``app_meta.is_demo`` of the OPEN database,
never from the command line (D25).
"""

import json
import logging
import sqlite3
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack, suppress
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum, auto
from functools import partial
from importlib import resources
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from cbrn_dashboard import __version__, cli
from cbrn_dashboard.clock import Clock, SystemClock
from cbrn_dashboard.demo import (
    creation_day,
    demo_database_path,
    is_outdated,
    open_demo_database,
    recreate_demo_database,
)
from cbrn_dashboard.domain.dates import parse_utc_timestamp
from cbrn_dashboard.i18n import DEFAULT_LANGUAGE
from cbrn_dashboard.logging_setup import (
    CrashReport,
    LoggingHandle,
    configure_logging,
    crash_code,
    install_exception_hook,
    log_event,
    log_exception,
)
from cbrn_dashboard.paths import (
    DataLocation,
    LocationSource,
    LocationWarning,
    is_file_writable,
    resolve_data_location,
    write_location_pointer,
)
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.services.backup import daily_backup_startup
from cbrn_dashboard.services.restore import tmp_cleanup_startup
from cbrn_dashboard.services.snapshots import monthly_snapshot_startup
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
from cbrn_dashboard.ui.shell.first_run import backup_reminder_startup, first_run_startup
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.instance_lock import InstanceLock, LockReason
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


# The registered start-up hooks, one entry each, run in this order: T7.3 (tmp clean-up), T7.1
# (daily backup), T8.1 (monthly snapshot), T7.5 (backup reminder, first-run notice). The first
# three do not run in read-only mode (nothing may be written or deleted in the data folder). The
# two T7.5 hooks write nothing to the data folder (the reminder only reads; the notice keeps its
# flag in memory when the folder is read-only), so they run in read-only mode, and not with a demo
# database. The daily backup does not need a trusted clock because only its rotation is skipped
# for a suspect clock (inside the service); the automatic snapshot does.
STARTUP_HOOKS: tuple[StartupHook, ...] = (
    StartupHook(
        "tmp-cleanup",
        tmp_cleanup_startup,
        runs_read_only=False,
        runs_in_demo=True,
        needs_trusted_clock=False,
    ),
    StartupHook(
        "daily-backup",
        daily_backup_startup,
        runs_read_only=False,
        runs_in_demo=False,
        needs_trusted_clock=False,
    ),
    StartupHook(
        "monthly-snapshot",
        monthly_snapshot_startup,
        runs_read_only=False,
        runs_in_demo=False,
        needs_trusted_clock=True,
    ),
    StartupHook(
        "backup-reminder",
        backup_reminder_startup,
        runs_read_only=True,
        runs_in_demo=False,
        needs_trusted_clock=False,
    ),
    StartupHook(
        "first-run-notice",
        first_run_startup,
        runs_read_only=True,
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
        """The open database connection, if any (read-only: the context owns the connection)."""
        return self.context.conn

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


def _newest_change_text(conn: DatabaseConnection) -> str | None:
    """The text of the newest ``change_log.at_utc``, or ``None`` (no rows, or unreadable)."""
    try:
        # Second-precision ISO text with a "Z" sorts like the instants it stands for.
        row = conn.execute("SELECT max(at_utc) FROM change_log").fetchone()
    except sqlite3.Error:
        return None
    value: object = None if row is None else row[0]
    return value if isinstance(value, str) else None


def newest_change_time(conn: DatabaseConnection) -> datetime | None:
    """The newest ``change_log.at_utc`` as a UTC instant, or ``None`` (no rows, or unreadable)."""
    value = _newest_change_text(conn)
    if value is None:
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
    """Whether the clock is earlier than the newest change record or than the build time.

    A newest change time that cannot be parsed makes the clock suspect (the safe direction).
    """
    now = clock.utc_now()
    newest_text = _newest_change_text(conn)
    if newest_text is not None:
        try:
            newest = parse_utc_timestamp(newest_text)
        except ValueError:
            return True
        if now < newest:
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


class _RefusedError(Exception):
    """A database is refused with a translated explanation; ``event`` is the log code."""

    def __init__(self, event: str, text: str) -> None:
        super().__init__(event)
        self.event = event
        self.text = text


def _check_read_only_database(conn: DatabaseConnection, *, demo: bool) -> None:
    """Refuse (``_RefusedError``) a read-only database that cannot be used as it is.

    Nothing is written. A database from the future raises ``DatabaseTooNewError``.
    """
    found = int(conn.execute("PRAGMA user_version").fetchone()[0])
    supported = max(migration.number for migration in load_migrations())
    if found > supported:
        raise DatabaseTooNewError(found, supported)
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'app_meta'"
    ).fetchone()
    if has_meta is None:
        raise _RefusedError("APP.NOT_AN_APPLICATION_DATABASE", _text_not_application_database())
    if found != supported:
        raise _RefusedError("APP.DATABASE_OLDER_SCHEMA", _text_older_schema())
    if demo and not app_meta.read_is_demo(conn):
        raise _RefusedError("APP.NOT_A_DEMO_DATABASE", _text_not_demo_database())


def _open_database(
    options: cli.CliOptions,
    location: DataLocation,
    clock: Clock,
    database_path: Path,
    mode: _Mode,
    build_timestamp: Callable[[], datetime | None] = read_build_timestamp,
    prompts: Prompts | None = None,
) -> DatabaseConnection:
    if mode is _Mode.READ_ONLY:
        conn = open_database(database_path, read_only=True)
        # A read-only connection cannot migrate, so only a database of exactly the current schema
        # that belongs to this application (and, for --demo, is a demo database) is opened.
        try:
            _check_read_only_database(conn, demo=options.demo)
        except BaseException:
            conn.close()
            raise
        return conn
    if options.demo:
        return _open_demo(location.path, clock, prompts)
    # The injected clock stamps the pre-migration copy; with a suspect clock (T7.1, D04) the pool
    # is not rotated, because the time in the name could push out newer, good copies.
    conn = open_and_migrate(
        location.database_path,
        data_dir=location.path,
        identity=DatabaseIdentity.REAL,
        clock=clock,
        rotate_if=lambda opened: not clock_is_suspect(opened, clock, build_timestamp),
    )
    try:
        app_meta.initialise(conn, is_demo=False, created_with=__version__)
    except BaseException:
        conn.close()
        raise
    return conn


def _open_demo(data_dir: Path, clock: Clock, prompts: Prompts | None) -> DatabaseConnection:
    """Open the demo database read-write; offer to create it again when it is from another day.

    The demo data is placed relative to the day it was created and then only ages, so when that day
    is not today the user is asked once (through ``prompts``) whether to create the demo data again
    for today. Yes replaces the demo database file (the real database is never touched, see
    :func:`~cbrn_dashboard.demo.recreate_demo_database`); no keeps it exactly as it is.
    """
    conn = open_demo_database(data_dir, clock)
    try:
        created = creation_day(conn)
        if prompts is None or created is None or not is_outdated(conn, clock):
            return conn
        wanted = prompts.confirm(
            None,
            _title_demo_outdated(),
            _text_demo_outdated(created.isoformat(), clock.local_date().isoformat()),
        )
    except BaseException:
        conn.close()
        raise
    if not wanted:
        return conn
    conn.close()
    return recreate_demo_database(data_dir, clock)


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


def _text_no_demo_database() -> str:
    return QCoreApplication.translate(
        "Shell",
        "The data folder is not writable, so the demo database cannot be created.",
    )


def _title_demo_outdated() -> str:
    return QCoreApplication.translate("Shell", "Demo data from another day")


def _text_demo_outdated(created: str, today: str) -> str:
    template = QCoreApplication.translate(
        "Shell",
        "The demo data was created on %1 and today is %2. Its dates were fitted to the day it was "
        "created, so the situations it shows are those of that day. Do you want to create the "
        "demo data again for today? Any change you made to the demo data will be lost. Your real "
        "data is not touched.",
    )
    return template.replace("%1", created).replace("%2", today)


def _text_no_profile_folder() -> str:
    return QCoreApplication.translate(
        "Shell",
        "No user profile folder was found, so there is no default data folder.",
    )


def _title_choose_folder() -> str:
    return QCoreApplication.translate("Shell", "Choose the data folder")


def _text_offer_other_folder() -> str:
    return QCoreApplication.translate(
        "Shell",
        "Do you want to choose another folder for the data? The choice is remembered in your "
        "user profile for the next start.",
    )


def _text_offer_session_only() -> str:
    return QCoreApplication.translate(
        "Shell",
        "Do you want to choose another folder for the data? The folder was set by --data-dir or "
        "by an environment variable, so the choice is used for this session only.",
    )


def _text_chosen_folder_unusable() -> str:
    return QCoreApplication.translate(
        "Shell", "The chosen folder is not writable and has no database. Choose another one."
    )


def _text_choice_not_remembered() -> str:
    return QCoreApplication.translate(
        "Shell", "The choice could not be remembered, so it is used for this session only."
    )


def _text_locked() -> str:
    return QCoreApplication.translate(
        "Shell",
        "Another instance is already using this data folder. Close it and start again.",
    )


def _text_lock_unavailable() -> str:
    return QCoreApplication.translate(
        "Shell",
        "The data folder cannot be locked, so the application cannot make sure it is the only "
        "one using it.",
    )


def _text_older_schema() -> str:
    return QCoreApplication.translate(
        "Shell",
        "This database was written by an older version and cannot be upgraded while it is "
        "read-only.",
    )


def _text_not_application_database() -> str:
    return QCoreApplication.translate("Shell", "This file is not a database of this application.")


def _text_not_demo_database() -> str:
    return QCoreApplication.translate(
        "Shell", "The file in the demo folder is not a demo database. It was left unchanged."
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


def _text_for_code(code: str) -> str | None:
    """The translated sentence for a known storage error code, else ``None``."""
    match code:
        case "NOT_A_DEMO_DATABASE":
            return _text_not_demo_database()
        case "SQLITE_TOO_OLD":
            return QCoreApplication.translate(
                "Shell", "The SQLite library of this installation is too old for this database."
            )
        case "NOT_A_DATABASE":
            return _text_not_application_database()
        case "DATABASE_MOVED":
            return QCoreApplication.translate(
                "Shell", "The database file was moved or replaced while it was being opened."
            )
        case "MIGRATION_FAILED":
            return QCoreApplication.translate(
                "Shell", "The database could not be upgraded. The failed step was rolled back."
            )
        case "MIGRATION_SEQUENCE":
            return QCoreApplication.translate(
                "Shell", "The upgrade steps of this installation are incomplete or damaged."
            )
        case "BACKUP_VERIFY_FAILED":
            return QCoreApplication.translate(
                "Shell", "The safety copy could not be verified, so the database was not upgraded."
            )
        case "HOT_JOURNAL":
            return _text_hot_journal()
        case "DATABASE_TOO_NEW":
            return _text_too_new()
        case _:
            return None


def _text_for_open_error(exc: BaseException) -> str:
    """A known code gets its own sentence; anything else the generic text with an ``E-`` code."""
    if isinstance(exc, DatabaseError):
        known = _text_for_code(exc.code)
        if known is not None:
            return known
    return _text_open_failed(crash_code(type(exc), exc.__traceback__))


def _show_crash(prompts: Prompts, report: CrashReport) -> None:
    """The crash callback: a translated dialog with the CODE only, never the message (D22)."""
    title = QCoreApplication.translate("Shell", "Unexpected error")
    template = QCoreApplication.translate("Shell", "An unexpected error occurred. Code: %1")
    prompts.error(None, title, template.replace("%1", report.code))


def _show_unexpected(prompts: Prompts, exc: Exception) -> None:
    """Log an unexpected failure (type and frames) and show its code, never its message."""
    log_exception("APP.STARTUP_FAILED", exc)
    report = CrashReport(
        code=crash_code(type(exc), exc.__traceback__), exception_type=type(exc).__name__
    )
    _show_crash(prompts, report)


def _report_main_failure(exc: Exception, prompts: Prompts | None) -> int:
    """The last line of defence in ``main``: log in memory, show a code, give the exit code."""
    handle = configure_logging(Path(APPLICATION_NAME), read_only=True)  # memory: writes nothing
    try:
        with suppress(Exception):  # nothing more can be done when even the dialog fails
            ensure_application()
            _show_unexpected(QtPrompts() if prompts is None else prompts, exc)
    finally:
        handle.close()
    return EXIT_FAILED


#: The unusable folder came from these sources: they rank above the pointer file (D02), so a
#: pointer written now would be ignored by the next run with the same option and honoured only by
#: a later plain start, which would move silently. The choice is then used for this session only.
_SESSION_ONLY_SOURCES = frozenset({LocationSource.CLI, LocationSource.ENV})


def _offer_other_folder(
    prompts: Prompts,
    explanation: str,
    environ: Mapping[str, str] | None,
    source: LocationSource = LocationSource.DEFAULT,
) -> DataLocation | None:
    """D02, T7.5: explain an unusable folder and let the user choose another one.

    Every interaction goes through ``prompts``. The chosen folder must be writable or already hold
    a database; it is remembered in the pointer file of the user profile (never in the unusable
    folder) and returned as the new location. ``None`` when the user declines or cancels. When the
    pointer cannot be written the folder is still used, for this session only, and the user is
    told so. When ``source`` is ``--data-dir`` or the environment variable (they rank above the
    pointer) nothing is written at all: the offer says so and the choice is for this session only.
    """
    session_only = source in _SESSION_ONLY_SOURCES
    prompts.error(None, _title_cannot_start(), explanation)
    offer = _text_offer_session_only() if session_only else _text_offer_other_folder()
    while prompts.confirm(None, _title_cannot_start(), offer):
        folder = prompts.choose_folder(None, _title_choose_folder())
        if folder is None:
            return None
        chosen = resolve_data_location(cli_data_dir=folder, environ=environ)
        if not (chosen.writable or chosen.database_exists):
            prompts.error(None, _title_choose_folder(), _text_chosen_folder_unusable())
            continue
        if session_only:
            log_event("APP.LOCATION_SESSION_ONLY")
            return replace(chosen, source=source)
        if write_location_pointer(chosen.path, environ=environ):
            log_event("APP.LOCATION_REMEMBERED")
        else:
            log_event("APP.LOCATION_NOT_REMEMBERED", level=logging.WARNING)
            prompts.warning(None, _title_choose_folder(), _text_choice_not_remembered())
        return replace(chosen, source=LocationSource.POINTER)
    return None


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
    environ: Mapping[str, str] | None = None,
) -> AppHandle | int:
    """Run the start-up sequence (see the module docstring) without entering the event loop.

    Returns the :class:`AppHandle`, or the exit code 1 after explaining the problem through
    ``prompts``. The window is not shown. ``clock`` defaults to the system clock, ``prompts`` to
    the real dialogs, ``hooks`` to :data:`STARTUP_HOOKS` and ``qm_dir`` to the package's own
    ``i18n`` folder. ``environ`` (default ``os.environ``) names the user profile whose pointer
    file remembers a folder chosen after an unusable one (tests inject it).
    """
    active_clock: Clock = SystemClock() if clock is None else clock
    active_prompts: Prompts = QtPrompts() if prompts is None else prompts
    active_hooks = STARTUP_HOOKS if hooks is None else tuple(hooks)

    # The unusable placeholder of a missing profile folder is a RELATIVE path: nothing may touch
    # it (it would resolve against the current directory), so it is decided before any access.
    no_profile = LocationWarning.NO_PROFILE_DIR in location.warnings and not location.writable
    if no_profile:
        database_path = location.database_path
        mode = _Mode.UNUSABLE
        preferences = PreferencesStore(location.path, writable=False)  # never loaded
        saved_language = DEFAULT_LANGUAGE
    else:
        database_path = (
            demo_database_path(location.path) if options.demo else location.database_path
        )
        mode = _decide_mode(location, database_path)
        preferences = PreferencesStore(location.path, writable=mode is _Mode.READ_WRITE)
        saved_language = preferences.load().language  # never raises; damaged file -> defaults
    read_only = mode is not _Mode.READ_WRITE

    app = ensure_application()
    app.setApplicationName(APPLICATION_NAME)
    app.setApplicationVersion(__version__)
    manager = TranslatorManager(app, qm_dir)

    stack = ExitStack()
    stack.callback(_dispose_manager, manager)
    try:
        # Until the instance lock is held the log stays in memory: a refused second instance must
        # not write into the running instance's rotating app.log.
        logging_handle = configure_logging(location.path, read_only=True)
        stack.callback(logging_handle.close)
        stack.callback(install_exception_hook(partial(_show_crash, active_prompts)))
        # --lang overrides the saved language for this run only and is never stored by itself.
        manager.set_language(saved_language if options.lang is None else options.lang)
        log_event("APP.START")

        if mode is _Mode.UNUSABLE:
            log_event("APP.NO_DATABASE")
            if no_profile:
                return _fail(stack, active_prompts, _text_no_profile_folder())
            if options.demo:
                return _fail(stack, active_prompts, _text_no_demo_database())
            # D02, T7.5: explain, then offer another folder (remembered in the profile pointer).
            chosen = _offer_other_folder(
                active_prompts, _text_no_database(), environ, location.source
            )
            stack.close()
            if chosen is None:
                return EXIT_FAILED
            return start(
                options,
                chosen,
                clock=active_clock,
                prompts=active_prompts,
                qm_dir=qm_dir,
                hooks=active_hooks,
                lock_factory=lock_factory,
                build_timestamp=build_timestamp,
                environ=environ,
            )

        lock: InstanceLock | None = None
        if mode is _Mode.READ_WRITE:
            lock = lock_factory(location.path)
            if not lock.acquire():
                if lock.reason is LockReason.UNAVAILABLE:
                    log_event("APP.LOCK_UNAVAILABLE")
                    return _fail(stack, active_prompts, _text_lock_unavailable())
                log_event("APP.INSTANCE_LOCKED")
                return _fail(stack, active_prompts, _text_locked())
            stack.callback(lock.release)
            # The lock is held: only now may the log file be opened (this call replaces the
            # in-memory handler).
            logging_handle = configure_logging(location.path, read_only=False)
            stack.callback(logging_handle.close)
            log_event("APP.START")

        try:
            conn = _open_database(
                options,
                location,
                active_clock,
                database_path,
                mode,
                build_timestamp,
                active_prompts,
            )
        except _RefusedError as refused:
            log_event(refused.event)
            return _fail(stack, active_prompts, refused.text)
        except HotJournalError:
            log_event("APP.HOT_JOURNAL")
            return _fail(stack, active_prompts, _text_hot_journal())
        except DatabaseTooNewError:
            log_event("APP.DATABASE_TOO_NEW")
            return _fail(stack, active_prompts, _text_too_new())
        except (DatabaseError, OSError, sqlite3.Error) as exc:
            log_exception("APP.DATABASE_OPEN_FAILED", exc)
            return _fail(stack, active_prompts, _text_for_open_error(exc))
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
    except Exception as exc:
        # D22: an unexpected failure is logged as an event code and shown as a crash code, never
        # with its message; only then are the hook and the log undone (and the lock released).
        try:
            _show_unexpected(active_prompts, exc)
        finally:
            stack.close()
        return EXIT_FAILED
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
    options = cli.parse_args(argv)  # argparse's SystemExit must pass
    try:
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
    except Exception as exc:
        # D22 (and the windowed build): nothing may escape with its message; a code is shown.
        return _report_main_failure(exc, prompts)
