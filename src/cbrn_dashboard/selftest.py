# SPDX-License-Identifier: GPL-3.0-or-later
"""Built-in self-test (``cbrn-dashboard --self-test``; PLAN.md task T0.7, section 8).

The self-test is a registry of checks. Each later task that creates a feature adds one check::

    @register("pdf")
    def _check_pdf(context: SelfTestContext) -> None: ...

A check passes by returning and fails by raising. The run never touches the real database: the
checks work in a throwaway ``<data>/tmp/selftest-XXXX`` folder that is always removed, and the only
file written beside it is ``<data>/selftest.json``. The windowed executable has no console, hence
the file. Only the exception *type name* of a failed check is recorded, never its message (D22),
and no timestamps are written.
"""

import contextlib
import gc
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent

from cbrn_dashboard import __version__
from cbrn_dashboard.app import ensure_application
from cbrn_dashboard.clock import SystemClock
from cbrn_dashboard.i18n import DEFAULT_LANGUAGE, LANGUAGES, to_bcp47
from cbrn_dashboard.paths import DataLocation
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager, app_display_name
from cbrn_dashboard.ui.shell.main_window import MainWindow
from cbrn_dashboard.ui.shell.prompts import QtPrompts

RESULT_FILE_NAME = "selftest.json"
TMP_DIR_NAME = "tmp"
WORK_DIR_PREFIX = "selftest-"

#: English source of the shell message used to prove that a catalogue is really loaded.
_APP_NAME_SOURCE = "CBRN Readiness Dashboard"


class SelfTestError(Exception):
    """A check found a problem. Its message is never written to the result file."""


@dataclass(frozen=True)
class SelfTestContext:
    """What a check may use."""

    location: DataLocation
    workdir: Path  # the throwaway folder; the only place a check may write to
    qm_dir: Path | None  # ``None``: the package's own i18n folder


type Check = Callable[[SelfTestContext], None]

CHECKS: list[tuple[str, Check]] = []
"""Registered checks in run order; extended by later tasks with one line each."""


def register(name: str) -> Callable[[Check], Check]:
    """Decorator that appends a check to :data:`CHECKS`."""

    def decorator(check: Check) -> Check:
        CHECKS.append((name, check))
        return check

    return decorator


def _require(condition: bool, what: str) -> None:
    if not condition:
        raise SelfTestError(what)


def _version_prefix(version: str) -> str | None:
    """The leading ``major.minor.patch`` of a version string, else ``None``."""
    match = re.match(r"\d+\.\d+\.\d+", version)
    return match.group(0) if match else None


# --------------------------------------------------------------------------- the checks


@register("python")
def _check_python(context: SelfTestContext) -> None:
    _require(sys.version_info >= (3, 12), "Python 3.12 or newer is required")


@register("qt")
def _check_qt(context: SelfTestContext) -> None:
    import PySide6
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QApplication

    binding = _version_prefix(PySide6.__version__)
    _require(binding is not None, "PySide6 has no usable version")
    ensure_application()
    _require(isinstance(QApplication.instance(), QApplication), "no QApplication")
    # A mismatched or half-collected Qt runtime in a frozen bundle fails here.
    _require(_version_prefix(qVersion()) == binding, "the Qt runtime and PySide6 versions differ")


@register("paths")
def _check_paths(context: SelfTestContext) -> None:
    _require(context.location.writable, "the data folder is not writable")
    _require(context.workdir.is_dir(), "the throwaway folder does not exist")
    probe = context.workdir / "probe.bin"
    payload = b"selftest"
    probe.write_bytes(payload)
    _require(probe.read_bytes() == payload, "the throwaway folder does not keep data")
    probe.unlink()


def _check_i18n(language: str, context: SelfTestContext) -> None:
    app = ensure_application()
    manager = TranslatorManager(app, context.qm_dir)
    try:
        manager.set_language(language)
        _require(not manager.missing_catalogues, "a compiled catalogue is missing")
        translated = app_display_name()
        if language == "en_US":
            _require(translated == _APP_NAME_SOURCE, "English text changed")
        else:
            _require(translated != _APP_NAME_SOURCE, "a known message is not translated")
    finally:
        manager.clear()
        manager.setParent(None)


for _language in LANGUAGES:
    CHECKS.append((f"i18n.{to_bcp47(_language)}", partial(_check_i18n, _language)))


@register("main_window")
def _check_main_window(context: SelfTestContext) -> None:
    app = ensure_application()
    manager = TranslatorManager(app, context.qm_dir)
    try:
        manager.set_language(DEFAULT_LANGUAGE)
        # No database, no lock: the window is built over an empty context (T1.9 owns start-up).
        app_context = AppContext(
            conn=None,
            clock=SystemClock(),
            location=context.location,
            prompts=QtPrompts(),
            preferences=PreferencesStore(context.workdir, writable=False),
            translator_manager=manager,
        )
        window = MainWindow(app_context)
        try:
            _require(bool(window.windowTitle().strip()), "the main window has no title")
        finally:
            window.close()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    finally:
        manager.clear()
        manager.setParent(None)


@register("database")
def _check_database(context: SelfTestContext) -> None:
    # Always inside the throwaway folder, never the real database.
    path = context.workdir / "selftest.sqlite3"
    conn = open_and_migrate(
        path, data_dir=context.workdir, identity=DatabaseIdentity.REAL, backup=False
    )
    with contextlib.closing(conn):
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        _require(version > 0, "the database has no schema version")
        tables = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='change_log'"
        ).fetchone()[0]
        _require(tables == 1, "the change_log table is missing")


# --------------------------------------------------------------------------- the runner


def _run_checks(context: SelfTestContext) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for name, check in list(CHECKS):
        error: str | None = None
        try:
            check(context)
        except Exception as exc:  # a failing check must not stop the others
            error = type(exc).__name__
        results.append({"name": name, "passed": error is None, "error": error})
    return results


def _remove_workdir(path: Path) -> str | None:
    """Remove the throwaway folder, retrying once after ``gc.collect()``.

    Returns ``None`` when the folder is gone, else the exception type name (never the message).
    """
    error: str | None = None
    for _attempt in range(2):
        try:
            shutil.rmtree(path)
        except OSError as exc:
            error = type(exc).__name__
            gc.collect()  # release handles left open by a check, then retry once
        else:
            return None
    return error if path.exists() else None


def run(location: DataLocation, *, qm_dir: Path | None = None) -> int:
    """Run every registered check; write ``selftest.json``; return 0 if all passed, else 1.

    ``qm_dir=None`` means the package's own ``i18n`` folder. Never raises for an unwritable data
    folder (it cannot write the result file then and returns 1).
    """
    data = location.path
    if not location.writable:
        return 1

    ensure_application()
    tmp_root = data / TMP_DIR_NAME
    created_tmp_root = not tmp_root.exists()
    workdir = tmp_root / (WORK_DIR_PREFIX + "unavailable")  # replaced when it can be created
    created_workdir: Path | None = None
    with contextlib.suppress(OSError):  # the "paths" check then fails with a clear name
        tmp_root.mkdir(exist_ok=True)
        created_workdir = Path(tempfile.mkdtemp(prefix=WORK_DIR_PREFIX, dir=tmp_root))
        workdir = created_workdir

    cleanup_error: str | None = None
    try:
        results = _run_checks(SelfTestContext(location, workdir, qm_dir))
    finally:
        if created_workdir is not None:
            cleanup_error = _remove_workdir(created_workdir)
        if created_tmp_root:
            with contextlib.suppress(OSError):
                tmp_root.rmdir()  # only succeeds when empty

    if cleanup_error is not None:
        results.append({"name": "cleanup", "passed": False, "error": cleanup_error})
    passed = all(result["passed"] for result in results)
    document = {"version": __version__, "passed": passed, "checks": results}
    try:
        (data / RESULT_FILE_NAME).write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        return 1
    return 0 if passed else 1
