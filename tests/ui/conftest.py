# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures shared by the UI tests: fake prompts, an ``AppContext`` and a start-up factory."""

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from cbrn_dashboard.app import AppHandle, StartupHook, start
from cbrn_dashboard.cli import CliOptions
from cbrn_dashboard.clock import Clock, FixedClock
from cbrn_dashboard.paths import (
    DATABASE_FILE_NAME,
    DataLocation,
    LocationSource,
    LocationWarning,
)
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.instance_lock import InstanceLock
from tests.ui._fakes import FakePrompts

NOW = "2026-03-05T12:00:00Z"

type StartApp = Callable[..., AppHandle | int]


@pytest.fixture
def fake_prompts() -> FakePrompts:
    """A prompts double that records every call (confirm -> False, pickers -> None)."""
    return FakePrompts()


@pytest.fixture
def app_context(
    qapp: QApplication,
    qm_dir: Path,
    tmp_path: Path,
    fake_prompts: FakePrompts,
    translator_manager_factory: Callable[[Path | None], TranslatorManager],
) -> Iterator[AppContext]:
    """An ``AppContext`` over a migrated real database below ``tmp_path/context``."""
    data_dir = tmp_path / "context"
    data_dir.mkdir()
    conn: DatabaseConnection = open_and_migrate(
        data_dir / DATABASE_FILE_NAME, data_dir=data_dir, identity=DatabaseIdentity.REAL
    )
    app_meta.initialise(conn, is_demo=False, created_with="0.0.1")
    manager = translator_manager_factory(qm_dir)
    manager.set_language("en_US")
    context = AppContext(
        conn=conn,
        clock=FixedClock.at(NOW),
        location=DataLocation(path=data_dir, source=LocationSource.CLI, writable=True),
        prompts=fake_prompts,
        preferences=PreferencesStore(data_dir),
        translator_manager=manager,
    )
    yield context
    conn.close()
    context.conn = None  # as ``AppHandle.close_database`` does: no service outlives the connection
    context.deleteLater()


@pytest.fixture
def started_app(
    qapp: QApplication, qm_dir: Path, tmp_path: Path, qtbot: QtBot, fake_prompts: FakePrompts
) -> Iterator[StartApp]:
    """Factory over ``cbrn_dashboard.app.start``; every handle it returns is closed at teardown.

    Keyword arguments: ``data_dir`` (default ``tmp_path``), ``demo``, ``lang`` (BCP-47, default
    ``en-US``), ``writable`` (the ``DataLocation`` flag), ``warnings``, ``clock``, ``prompts``,
    ``hooks`` (default none), ``qm_dir``, ``lock_factory`` and ``expect_errors``. Returns what
    ``start`` returns.

    While an app is open its exception hook replaces pytest-qt's: a slot that raises only
    becomes an ``error`` prompt. So at teardown the test FAILS when an app that started
    recorded an ``error`` prompt after start-up, unless the test passed ``expect_errors=True``.
    The error prompt of a REFUSED start (it returned an exit code) is its expected outcome and
    is not counted.
    """
    handles: list[AppHandle] = []
    watched: list[tuple[FakePrompts, int]] = []
    state = {"expect_errors": False}

    def make(
        *,
        data_dir: Path | None = None,
        demo: bool = False,
        lang: str | None = "en-US",
        writable: bool = True,
        warnings: tuple[LocationWarning, ...] = (),
        clock: Clock | None = None,
        prompts: FakePrompts | None = None,
        hooks: Sequence[StartupHook] = (),
        qm: Path | None = None,
        lock_factory: Callable[[Path], InstanceLock] = InstanceLock,
        expect_errors: bool = False,
    ) -> AppHandle | int:
        if expect_errors:
            state["expect_errors"] = True
        folder = tmp_path if data_dir is None else data_dir
        folder.mkdir(parents=True, exist_ok=True)  # the real resolver creates the folder too
        location = DataLocation(
            path=folder, source=LocationSource.CLI, writable=writable, warnings=warnings
        )
        options = CliOptions(data_dir=str(folder), lang=lang, demo=demo)
        used = fake_prompts if prompts is None else prompts
        result = start(
            options,
            location,
            clock=FixedClock.at(NOW) if clock is None else clock,
            prompts=used,
            qm_dir=qm_dir if qm is None else qm,
            hooks=hooks,
            lock_factory=lock_factory,
        )
        if isinstance(result, AppHandle):
            qtbot.addWidget(result.window)
            handles.append(result)
            watched.append((used, len(used.calls_of("error"))))
        else:  # a refused start: its error prompt is expected, so move the baseline past it
            for index, (other, _count) in enumerate(watched):
                if other is used:
                    watched[index] = (other, len(used.calls_of("error")))
        return result

    yield make
    for handle in reversed(handles):
        handle.close()
    # pytest-qt only schedules the deletion of the windows (deleteLater). Delete them now: a window
    # left pending would receive the language change of the next test's start-up.
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    if state["expect_errors"]:
        return
    for used, before in watched:
        errors = used.calls_of("error")[before:]
        assert not errors, (
            "an error prompt was shown while the app was open (a slot raised?); "
            "pass expect_errors=True if that is intended: "
            + "; ".join(f"{call.title}: {call.text}" for call in errors)
        )


@pytest.fixture(autouse=True)
def _no_leaked_registrations() -> Iterator[None]:
    """Fail a test that leaves a temporary page, settings section or dialog registered.

    Only the TEST-ADDED extras are compared with their state before the test; the built-in
    registrations (the ``PAGES``, ``SETTINGS_SECTIONS`` and ``DIALOGS`` tuples) are not involved.
    """
    extras_before = (
        list(registry._extra_pages),
        list(registry._extra_sections),
        list(registry._extra_dialogs),
    )
    yield
    extras_after = (
        list(registry._extra_pages),
        list(registry._extra_sections),
        list(registry._extra_dialogs),
    )
    leaked = [
        spec.key
        for old, new in zip(extras_before, extras_after, strict=True)
        for spec in new
        if spec not in old
    ]
    assert leaked == [], f"test registrations left behind: {leaked}"
