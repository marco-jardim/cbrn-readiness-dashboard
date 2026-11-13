# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures shared by the UI tests: fake prompts, an ``AppContext`` and a start-up factory."""

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest
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
    context.deleteLater()


@pytest.fixture
def started_app(
    qapp: QApplication, qm_dir: Path, tmp_path: Path, qtbot: QtBot, fake_prompts: FakePrompts
) -> Iterator[StartApp]:
    """Factory over ``cbrn_dashboard.app.start``; every handle it returns is closed at teardown.

    Keyword arguments: ``data_dir`` (default ``tmp_path``), ``demo``, ``lang`` (BCP-47, default
    ``en-US``), ``writable`` (the ``DataLocation`` flag), ``warnings``, ``clock``, ``prompts``,
    ``hooks`` (default none), ``qm_dir`` and ``lock_factory``. Returns what ``start`` returns.
    """
    handles: list[AppHandle] = []

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
    ) -> AppHandle | int:
        folder = tmp_path if data_dir is None else data_dir
        folder.mkdir(parents=True, exist_ok=True)  # the real resolver creates the folder too
        location = DataLocation(
            path=folder, source=LocationSource.CLI, writable=writable, warnings=warnings
        )
        options = CliOptions(data_dir=str(folder), lang=lang, demo=demo)
        result = start(
            options,
            location,
            clock=FixedClock.at(NOW) if clock is None else clock,
            prompts=fake_prompts if prompts is None else prompts,
            qm_dir=qm_dir if qm is None else qm,
            hooks=hooks,
            lock_factory=lock_factory,
        )
        if isinstance(result, AppHandle):
            qtbot.addWidget(result.window)
            handles.append(result)
        return result

    yield make
    for handle in reversed(handles):
        handle.close()
