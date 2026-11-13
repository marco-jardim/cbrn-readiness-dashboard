# SPDX-License-Identifier: GPL-3.0-or-later
"""Infrastructure demo generator (T3.5): statuses, maintenance cases, DEMO prefix, determinism."""

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

from cbrn_dashboard import demo
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import (
    DEFAULT_SEED,
    DEMO_SEED_KEY,
    GENERATORS,
    DemoGenerator,
    is_demo_identifier,
    open_demo_database,
)
from cbrn_dashboard.demo import infrastructure as demo_infrastructure
from cbrn_dashboard.domain.infrastructure import (
    AssetRow,
    AssetStatus,
    MaintenanceKind,
    ScheduleBasis,
)
from cbrn_dashboard.paths import DATABASE_FILE_NAME
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")
LATER = FixedClock.at("2026-04-04T12:00:00Z")  # 30 days after CLOCK
TODAY = date(2026, 3, 5)
INFRASTRUCTURE = DemoGenerator("infrastructure", demo_infrastructure.generate)

BUILT_IN_TYPES = ("bed", "bay", "neg_pressure_filtration", "decon_tent")
INFRASTRUCTURE_TABLES = ("asset_type", "asset", "asset_status_event", "maintenance_event")

type Rows = list[tuple[object, ...]]


# --------------------------------------------------------------------------- helpers


class Databases:
    """Builds and tracks demo databases so every connection is closed at teardown."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._open: list[DatabaseConnection] = []
        self._count = 0

    def build(self, *, clock: FixedClock = CLOCK, seed: int = DEFAULT_SEED) -> DatabaseConnection:
        """A migrated database filled by the infrastructure generator alone."""
        self._count += 1
        folder = self._root / f"db{self._count}"
        folder.mkdir()
        conn = open_and_migrate(
            folder / "demo.sqlite3", data_dir=folder, identity=DatabaseIdentity.REAL
        )
        self._open.append(conn)
        app_meta.initialise(conn, is_demo=True, created_with="0.0.1")
        assert demo.generate(conn, clock, seed=seed, generators=[INFRASTRUCTURE]) is True
        return conn

    def track(self, conn: DatabaseConnection) -> DatabaseConnection:
        self._open.append(conn)
        return conn

    def close_all(self) -> None:
        for conn in self._open:
            conn.close()


@pytest.fixture
def databases(tmp_path: Path) -> Iterator[Databases]:
    registry = Databases(tmp_path)
    yield registry
    registry.close_all()


@pytest.fixture
def conn(databases: Databases) -> DatabaseConnection:
    return databases.build()


def _service(conn: DatabaseConnection, clock: FixedClock = CLOCK) -> InfrastructureService:
    return InfrastructureService(conn, clock)


def _rows(conn: DatabaseConnection, table: str) -> Rows:
    return [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]


def _by_tag(conn: DatabaseConnection, as_of: date = TODAY) -> dict[str, AssetRow]:
    return {row.tag: row for row in _service(conn).asset_rows(as_of)}


def _in_service(conn: DatabaseConnection, as_of: date = TODAY) -> list[AssetRow]:
    return [row for row in _service(conn).asset_rows(as_of) if row.in_service]


# --------------------------------------------------------------------------- assets and types


def test_assets_are_demo_a001_onwards(conn: DatabaseConnection) -> None:
    tags = sorted(_by_tag(conn))
    assert len(tags) == 20
    assert tags == [f"DEMO-A{number:03d}" for number in range(1, 21)]


def test_every_built_in_type_has_assets(conn: DatabaseConnection) -> None:
    types = {row.type_code for row in _by_tag(conn).values()}
    assert set(BUILT_IN_TYPES) <= types
    for code in BUILT_IN_TYPES:
        assert any(row.type_code == code for row in _by_tag(conn).values())


def test_exactly_one_user_defined_type_whose_code_starts_with_demo(
    conn: DatabaseConnection,
) -> None:
    user_defined = [view for view in _service(conn).list_types(True) if not view.built_in]
    assert len(user_defined) == 1
    only = user_defined[0]
    assert only.code.startswith("DEMO")
    assert only.default_maintenance_interval_days is not None
    assert only.default_maintenance_interval_days > 0
    for label in (only.label_pt_br, only.label_en_us, only.label_es_es):
        assert label is not None
        assert label.startswith("DEMO")
    assert any(row.type_code == only.code for row in _by_tag(conn).values())
    built_in = sorted(view.code for view in _service(conn).list_types(True) if view.built_in)
    assert built_in == sorted(BUILT_IN_TYPES)


# --------------------------------------------------------------------------- statuses


def test_every_status_occurs_among_in_service_assets(conn: DatabaseConnection) -> None:
    statuses = {row.status for row in _in_service(conn)}
    assert {AssetStatus.OPERATIONAL, AssetStatus.DEGRADED, AssetStatus.OUT_OF_SERVICE} <= statuses
    assert AssetStatus.UNKNOWN not in statuses  # every asset has a status on the date (D26)
    assert _service(conn).data_quality(TODAY) == []

    rows = _by_tag(conn)
    assert rows["DEMO-A001"].status is AssetStatus.OPERATIONAL
    assert rows["DEMO-A002"].status is AssetStatus.DEGRADED
    assert rows["DEMO-A003"].status is AssetStatus.OUT_OF_SERVICE


def test_the_out_of_service_asset_has_a_status_history(conn: DatabaseConnection) -> None:
    service = _service(conn)
    asset = next(view for view in service.list_assets() if view.tag == "DEMO-A003")
    history = service.asset_history(asset.id)
    statuses = [event.status for event in history.status_events]
    assert statuses == [
        AssetStatus.OPERATIONAL,
        AssetStatus.DEGRADED,
        AssetStatus.OUT_OF_SERVICE,
    ]
    dates = [event.effective_on for event in history.status_events]
    assert dates == sorted(dates)
    assert dates[0] == asset.in_service_from
    assert dates[-1] < TODAY


# --------------------------------------------------------------------------- maintenance


def test_an_asset_is_overdue_and_one_is_due_soon(conn: DatabaseConnection) -> None:
    rows = _by_tag(conn)
    overdue = rows["DEMO-A001"]
    assert overdue.overdue is True
    assert overdue.due_soon is False
    assert overdue.due_on is not None
    assert overdue.due_on < TODAY
    assert overdue.days_to_due == -20
    assert overdue.basis is ScheduleBasis.RECORDED_NEXT_DUE

    soon = rows["DEMO-A002"]
    assert soon.due_soon is True
    assert soon.overdue is False
    assert soon.days_to_due == 10  # inside the default 30-day window

    lists = _service(conn).maintenance_due_lists(TODAY)
    assert "DEMO-A001" in {row.tag for row in lists.overdue}
    assert "DEMO-A002" in {row.tag for row in lists.due_soon}


def test_an_asset_has_an_unknown_schedule(conn: DatabaseConnection) -> None:
    rows = _by_tag(conn)
    unknown = rows["DEMO-A003"]
    assert unknown.basis is ScheduleBasis.UNKNOWN
    assert unknown.schedule_unknown is True
    assert unknown.due_on is None
    assert unknown.type_code in BUILT_IN_TYPES  # built-in types have no default interval
    assert unknown.last_maintenance_on is not None  # it has records, but none sets a due date


def test_an_asset_has_no_scheduled_maintenance(conn: DatabaseConnection) -> None:
    row = _by_tag(conn)["DEMO-A004"]
    assert row.basis is ScheduleBasis.NO_SCHEDULED_MAINTENANCE
    assert row.due_on is None
    assert row.overdue is False
    assert row.due_soon is False
    assert row.schedule_unknown is False


def test_due_dates_from_preventive_plus_interval_and_the_type_default(
    conn: DatabaseConnection,
) -> None:
    service = _service(conn)
    rows = _by_tag(conn)
    own = rows["DEMO-A005"]
    assert own.basis is ScheduleBasis.PREVENTIVE_PLUS_INTERVAL
    assert own.due_on == TODAY - timedelta(days=30) + timedelta(days=90)

    default = rows["DEMO-A006"]
    assert default.basis is ScheduleBasis.PREVENTIVE_PLUS_INTERVAL
    asset = next(view for view in service.list_assets() if view.tag == "DEMO-A006")
    assert asset.maintenance_interval_days is None  # no override: the type default applies
    demo_type = next(view for view in service.list_types(True) if not view.built_in)
    assert default.due_on == TODAY - timedelta(days=100) + timedelta(
        days=demo_type.default_maintenance_interval_days or 0
    )

    fresh = rows["DEMO-A007"]
    assert fresh.basis is ScheduleBasis.IN_SERVICE_PLUS_INTERVAL
    assert fresh.last_maintenance_on is None


def test_all_three_maintenance_kinds_are_recorded(conn: DatabaseConnection) -> None:
    kinds = {str(row[0]) for row in conn.execute("SELECT kind FROM maintenance_event")}
    assert kinds == {kind.value for kind in MaintenanceKind}
    performed = [
        date.fromisoformat(str(row[0]))
        for row in conn.execute("SELECT performed_on FROM maintenance_event")
    ]
    assert all(day <= TODAY for day in performed)


# --------------------------------------------------------------------------- retired, future


def test_a_retired_asset_keeps_its_history_and_is_excluded(conn: DatabaseConnection) -> None:
    service = _service(conn)
    retired = [view for view in service.list_assets() if view.in_service_until is not None]
    assert len(retired) == 1
    asset = retired[0]
    assert asset.tag == "DEMO-A008"
    assert asset.in_service_until is not None
    assert asset.in_service_until < TODAY
    history = service.asset_history(asset.id)
    assert len(history.status_events) >= 2
    assert history.maintenance_events

    row = _by_tag(conn)["DEMO-A008"]
    assert row.in_service is False
    assert row.tag not in {r.tag for r in service.maintenance_due_lists(TODAY).overdue}

    availability = {item.type_code: item for item in service.availability(TODAY)}
    in_service = _in_service(conn)
    for code, item in availability.items():
        assert item.in_service == sum(1 for r in in_service if r.type_code == code)
        assert item.available == sum(1 for r in in_service if r.type_code == code and r.available)
    all_of_type = [r for r in _by_tag(conn).values() if r.type_code == row.type_code]
    assert availability[row.type_code].in_service < len(all_of_type)


def test_an_asset_is_not_yet_in_service(conn: DatabaseConnection) -> None:
    service = _service(conn)
    future = [view for view in service.list_assets() if view.in_service_from > TODAY]
    assert [view.tag for view in future] == ["DEMO-A009"]
    row = _by_tag(conn)["DEMO-A009"]
    assert row.in_service is False
    assert row.status is AssetStatus.UNKNOWN  # its first status event lies in the future
    assert "DEMO-A009" not in service.data_quality(TODAY)


# --------------------------------------------------------------------------- DEMO prefix


def test_every_written_text_starts_with_demo(conn: DatabaseConnection) -> None:
    checks = {
        "asset": ("tag", "description", "location"),
        "asset_type": ("code", "label_pt_br", "label_en_us", "label_es_es"),
    }
    checked = 0
    for table, columns in checks.items():
        for column in columns:
            where = " WHERE built_in = 0" if table == "asset_type" else ""
            for (value,) in conn.execute(f"SELECT {column} FROM {table}{where}").fetchall():
                assert isinstance(value, str), (table, column)
                assert is_demo_identifier(value), (table, column, value)
                checked += 1
    assert checked >= 20 * 3 + 4

    # The built-in types are not written by the generator: their labels stay empty.
    for row in conn.execute(
        "SELECT code, label_pt_br, label_en_us, label_es_es, default_maintenance_interval_days "
        "FROM asset_type WHERE built_in = 1"
    ):
        assert row[0] in BUILT_IN_TYPES
        assert tuple(row)[1:] == (None, None, None, None)


# --------------------------------------------------------------------------- determinism


def test_same_seed_gives_identical_rows(databases: Databases) -> None:
    first = databases.build(seed=7)
    second = databases.build(seed=7)
    for table in INFRASTRUCTURE_TABLES:
        rows = _rows(first, table)
        assert rows
        assert rows == _rows(second, table)


def test_a_different_seed_changes_the_filler(databases: Databases) -> None:
    first = databases.build(seed=7)
    second = databases.build(seed=8)
    assert any(_rows(first, table) != _rows(second, table) for table in INFRASTRUCTURE_TABLES)
    # The guaranteed cases do not depend on the seed.
    for conn in (first, second):
        rows = _by_tag(conn)
        assert rows["DEMO-A001"].overdue is True
        assert rows["DEMO-A002"].due_soon is True
        assert rows["DEMO-A003"].schedule_unknown is True
        assert rows["DEMO-A004"].basis is ScheduleBasis.NO_SCHEDULED_MAINTENANCE
        assert rows["DEMO-A008"].in_service is False
    assert sorted(_by_tag(first)) == sorted(_by_tag(second))


def test_the_default_seed_is_stable_between_runs(databases: Databases) -> None:
    first = databases.build()
    second = databases.build()
    assert _rows(first, "maintenance_event") == _rows(second, "maintenance_event")


# --------------------------------------------------------------------------- relative to the clock


def test_data_is_relative_to_the_clock(databases: Databases) -> None:
    now = databases.build(clock=CLOCK)
    later = databases.build(clock=LATER)
    shift = timedelta(days=30)

    def next_due(conn: DatabaseConnection) -> date:
        asset = next(view for view in _service(conn).list_assets() if view.tag == "DEMO-A001")
        due = [
            event.next_due_on
            for event in _service(conn).asset_history(asset.id).maintenance_events
            if event.next_due_on is not None
        ]
        assert len(due) == 1
        return due[0]

    assert next_due(later) - next_due(now) == shift

    rows = _by_tag(later, LATER.local_date())
    assert rows["DEMO-A001"].overdue is True
    assert rows["DEMO-A001"].days_to_due == -20
    assert rows["DEMO-A002"].due_soon is True
    assert rows["DEMO-A002"].days_to_due == 10
    assert rows["DEMO-A003"].schedule_unknown is True
    assert rows["DEMO-A008"].in_service is False
    assert rows["DEMO-A009"].in_service is False


# --------------------------------------------------------------------------- framework


def test_is_registered_second_in_the_default_registry() -> None:
    names = [generator.name for generator in GENERATORS]
    assert names[:2] == ["personnel", "infrastructure"]
    assert names == ["personnel", "infrastructure", "exercises", "budget"]
    registered = next(generator for generator in GENERATORS if generator.name == "infrastructure")
    assert registered.run is demo_infrastructure.generate


def test_runs_inside_the_framework_once(tmp_path: Path, databases: Databases) -> None:
    first = databases.track(open_demo_database(tmp_path, CLOCK))
    assert app_meta.get(first, DEMO_SEED_KEY) == str(DEFAULT_SEED)
    rows = {table: _rows(first, table) for table in INFRASTRUCTURE_TABLES}
    assert len(rows["asset"]) == 20
    assert len(rows["asset_type"]) == 5
    first.close()

    again = databases.track(open_demo_database(tmp_path, CLOCK))
    for table in INFRASTRUCTURE_TABLES:
        assert _rows(again, table) == rows[table]
    assert not (tmp_path / DATABASE_FILE_NAME).exists()
    assert {entry.name for entry in tmp_path.iterdir()} == {"demo"}


# --------------------------------------------------------------------------- change log


def test_change_log_has_the_demo_operator(conn: DatabaseConnection) -> None:
    log = conn.execute("SELECT operator, entity FROM change_log").fetchall()
    assert log
    assert {row[0] for row in log} == {"DEMO"}
    assert len(log) > 20
