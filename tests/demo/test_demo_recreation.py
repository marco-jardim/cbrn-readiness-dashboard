# SPDX-License-Identifier: GPL-3.0-or-later
"""A demo database from another day: its creation day is stored; recreating is asked (P10-02).

The demo data is placed relative to the day it is created and then only ages. ``--demo`` on an
existing demo database created on another day asks once, through the prompts, whether to create the
data again for today: yes replaces the demo database (and only it), no leaves it as it is, and in
read-only mode nothing is asked or written. The expectations are written by hand: the fixed cases
of ``demo/personnel.py`` put the level A certificate of ``DEMO-P002`` 30 days after the creation
day.
"""

from collections.abc import Iterator
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Protocol

import pytest
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from cbrn_dashboard.app import AppHandle, start
from cbrn_dashboard.cli import CliOptions
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import (
    DEMO_CREATED_ON_KEY,
    NOT_A_DEMO_DATABASE,
    DemoDataError,
    creation_day,
    demo_database_path,
    open_demo_database,
    recreate_demo_database,
)
from cbrn_dashboard.domain.alerts import AlertKind
from cbrn_dashboard.paths import DATABASE_FILE_NAME, DataLocation, LocationSource
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from tests.ui._fakes import FakePrompts, create_database, expect_handle

pytestmark = pytest.mark.ui

DAY_ONE = FixedClock.at("2026-03-05T12:00:00Z")
DAY_THREE = FixedClock.at("2026-03-07T12:00:00Z")

TITLE = "Demo data from another day"
QUESTION = (
    "The demo data was created on 2026-03-05 and today is 2026-03-07. Its dates were fitted to the "
    "day it was created, so the situations it shows are those of that day. Do you want to create "
    "the demo data again for today? Any change you made to the demo data will be lost. Your real "
    "data is not touched."
)

_P002_LEVEL_A = (
    "SELECT c.valid_until FROM ppe_certification AS c JOIN staff_member AS s ON s.id = c.staff_id"
    " WHERE s.identifier = 'DEMO-P002' AND c.ppe_level = 'A'"
)


class Launch(Protocol):
    """Starts the application like ``main`` does (without ``exec``) and returns the handle."""

    def __call__(
        self,
        data_dir: Path,
        clock: FixedClock,
        prompts: FakePrompts,
        *,
        writable: bool = True,
    ) -> AppHandle: ...


@pytest.fixture
def launch(qapp: QApplication, qm_dir: Path, qtbot: QtBot) -> Iterator[Launch]:
    handles: list[AppHandle] = []

    def make(
        data_dir: Path, clock: FixedClock, prompts: FakePrompts, *, writable: bool = True
    ) -> AppHandle:
        data_dir.mkdir(parents=True, exist_ok=True)
        location = DataLocation(path=data_dir, source=LocationSource.CLI, writable=writable)
        options = CliOptions(data_dir=str(data_dir), lang="en-US", demo=True)
        result = start(options, location, clock=clock, prompts=prompts, qm_dir=qm_dir, hooks=())
        handle = expect_handle(result)
        qtbot.addWidget(handle.window)
        handles.append(handle)
        return handle

    yield make
    for handle in reversed(handles):
        handle.close()


def _database(handle: AppHandle) -> DatabaseConnection:
    conn = handle.database
    assert conn is not None
    return conn


def _valid_until(conn: DatabaseConnection) -> str:
    value: object = conn.execute(_P002_LEVEL_A).fetchone()[0]
    assert isinstance(value, str)
    return value


def _days_remaining(handle: AppHandle, today: date) -> int | None:
    alerts = handle.context.services.alerts
    assert alerts is not None
    found = [
        alert.days_remaining
        for alert in alerts.alerts(today)
        if alert.kind is AlertKind.CERT_EXPIRING and alert.subject_ref == "DEMO-P002"
    ]
    assert len(found) == 1
    return found[0]


def _create_on_day_one(launch: Launch, data_dir: Path) -> None:
    prompts = FakePrompts()
    handle = launch(data_dir, DAY_ONE, prompts)
    assert prompts.calls_of("confirm") == []  # a new demo database asks nothing
    conn = _database(handle)
    assert creation_day(conn) == date(2026, 3, 5)
    assert app_meta.get(conn, DEMO_CREATED_ON_KEY) == "2026-03-05"
    assert _valid_until(conn) == "2026-04-04"  # the creation day plus 30 days
    handle.close()


def test_the_same_day_asks_nothing(launch: Launch, tmp_path: Path) -> None:
    _create_on_day_one(launch, tmp_path)
    prompts = FakePrompts()
    handle = launch(tmp_path, DAY_ONE, prompts)
    assert prompts.calls_of("confirm") == []
    assert _valid_until(_database(handle)) == "2026-04-04"


def test_another_day_asks_once_with_the_two_days_in_the_text(
    launch: Launch, tmp_path: Path
) -> None:
    _create_on_day_one(launch, tmp_path)
    prompts = FakePrompts()
    launch(tmp_path, DAY_THREE, prompts)
    [call] = prompts.calls_of("confirm")
    assert call.parent is None
    assert call.title == TITLE
    assert call.text == QUESTION
    assert prompts.calls_of("error") == []


def test_no_keeps_the_demo_database_byte_for_byte(launch: Launch, tmp_path: Path) -> None:
    _create_on_day_one(launch, tmp_path)
    path = demo_database_path(tmp_path)
    launch(tmp_path, DAY_ONE, FakePrompts()).close()  # what a normal start on the same day writes
    normal = path.read_bytes()

    prompts = FakePrompts()  # confirm answers no
    handle = launch(tmp_path, DAY_THREE, prompts)
    assert len(prompts.calls_of("confirm")) == 1
    conn = _database(handle)
    assert creation_day(conn) == date(2026, 3, 5)  # still the data of day one
    assert _valid_until(conn) == "2026-04-04"
    assert _days_remaining(handle, date(2026, 3, 7)) == 28  # it aged by two days
    assert handle.is_demo
    handle.close()
    assert path.read_bytes() == normal


def test_yes_recreates_the_demo_data_for_the_new_day(launch: Launch, tmp_path: Path) -> None:
    _create_on_day_one(launch, tmp_path)
    prompts = FakePrompts()
    prompts.script("confirm", True)
    handle = launch(tmp_path, DAY_THREE, prompts)
    assert len(prompts.calls_of("confirm")) == 1

    conn = _database(handle)
    assert handle.is_demo
    assert creation_day(conn) == date(2026, 3, 7)
    assert _valid_until(conn) == "2026-04-06"  # the new creation day plus 30 days
    assert _days_remaining(handle, date(2026, 3, 7)) == 30
    taken = conn.execute("SELECT DISTINCT substr(taken_at_utc, 1, 19) FROM readiness_snapshot")
    assert [row[0] for row in taken.fetchall()] == ["2026-03-07T12:00:00"]
    handle.close()

    again = FakePrompts()
    launch(tmp_path, DAY_THREE, again)
    assert again.calls_of("confirm") == []  # asked once: now the data is from today


def test_read_only_asks_nothing_and_writes_nothing(launch: Launch, tmp_path: Path) -> None:
    _create_on_day_one(launch, tmp_path)
    path = demo_database_path(tmp_path)
    before = path.read_bytes()
    prompts = FakePrompts()
    prompts.script("confirm", True)  # would recreate, if it were asked
    handle = launch(tmp_path, DAY_THREE, prompts, writable=False)
    assert handle.context.read_only
    assert prompts.calls_of("confirm") == []
    assert creation_day(_database(handle)) == date(2026, 3, 5)
    handle.close()
    assert path.read_bytes() == before


def test_the_real_database_of_the_same_folder_is_never_touched(
    launch: Launch, tmp_path: Path
) -> None:
    real = create_database(tmp_path)  # <data>/cbrn-dashboard.sqlite3, a REAL database
    real_bytes = real.read_bytes()
    _create_on_day_one(launch, tmp_path)
    prompts = FakePrompts()
    prompts.script("confirm", True)
    launch(tmp_path, DAY_THREE, prompts).close()  # a recreation

    assert real == tmp_path / DATABASE_FILE_NAME
    assert real.read_bytes() == real_bytes
    with closing(open_database(real, read_only=True)) as conn:
        assert not app_meta.read_is_demo(conn)
        assert app_meta.get(conn, DEMO_CREATED_ON_KEY) is None
        for table in (
            "indicator_target",
            "readiness_snapshot",
            "readiness_snapshot_value",
            "snapshot_withdrawal",
            "staff_member",
            "asset",
            "exercise_edition",
            "budget_entry",
            "change_log",
        ):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


def test_recreating_never_deletes_a_file_that_is_not_a_demo_database(tmp_path: Path) -> None:
    path = demo_database_path(tmp_path)
    path.parent.mkdir(parents=True)
    source = create_database(tmp_path / "source")  # a REAL database copied to the demo location
    path.write_bytes(source.read_bytes())
    before = path.read_bytes()
    with pytest.raises(DemoDataError) as excinfo:
        recreate_demo_database(tmp_path, DAY_THREE)
    assert excinfo.value.code == NOT_A_DEMO_DATABASE
    assert path.read_bytes() == before


def test_recreating_gives_a_database_equal_to_a_first_creation_on_that_day(tmp_path: Path) -> None:
    first = open_demo_database(tmp_path / "old", DAY_ONE)
    first.close()
    recreated = recreate_demo_database(tmp_path / "old", DAY_THREE)
    fresh = open_demo_database(tmp_path / "new", DAY_THREE)
    try:
        for table in ("staff_member", "ppe_certification", "asset", "budget_execution"):
            sql = f"SELECT * FROM {table} ORDER BY id"
            assert recreated.execute(sql).fetchall() == fresh.execute(sql).fetchall(), table
    finally:
        recreated.close()
        fresh.close()
