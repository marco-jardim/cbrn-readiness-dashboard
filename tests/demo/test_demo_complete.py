# SPDX-License-Identifier: GPL-3.0-or-later
"""The complete demo dataset (PLAN.md T10.1): targets, statuses, alerts, snapshots, the document.

The database is the default registry of ``cbrn_dashboard.demo`` generated on a fixed clock. The
expected statuses, alerts and dates below were worked out by hand from the fixed cases of the
module generators (see their docstrings) and from ``demo/targets.py``; they are not read back from
the code under test.
"""

import csv
import io
import json
import re
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import (
    DEFAULT_SEED,
    DEMO_CREATED_ON_KEY,
    DEMO_SEED_KEY,
    GENERATORS,
    NOT_A_DEMO_DATABASE,
    DemoDataError,
    creation_day,
    generate,
    is_outdated,
    open_demo_database,
)
from cbrn_dashboard.domain.alerts import AlertKind, Severity
from cbrn_dashboard.domain.indicators import IndicatorStatus, UnitKind
from cbrn_dashboard.domain.registry import build_registry
from cbrn_dashboard.paths import DATABASE_FILE_NAME
from cbrn_dashboard.services.alerts import AlertService
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.dashboard import DashboardService
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.indicators import MAX_RATIO_TARGET, IndicatorService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.services.snapshots import SnapshotOrigin, SnapshotService
from cbrn_dashboard.services.validation_export import (
    NO_PRIOR_SNAPSHOT,
    UNSUPPRESSED_BANNER,
    ValidationExportService,
)
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection, open_database, transaction
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

DOCUMENT = Path(__file__).resolve().parents[2] / "docs" / "demo-walkthrough.md"

OK = IndicatorStatus.OK
WARN = IndicatorStatus.WARNING
CRIT = IndicatorStatus.CRITICAL
NO_TARGET = IndicatorStatus.NO_TARGET
NO_DATA = IndicatorStatus.NO_DATA

DIRSA = ("BUD_EXEC_RATE", "currency=BRL;source=DIRSA")


@dataclass(frozen=True)
class Day:
    """A creation day of the demo database and what differs on it, written by hand.

    Only the budget group DIRSA depends on the day. Its executed share is 4 to 12 percent (the low
    band of demo/budget.py) and the year-end target is multiplied by day-of-year / days-in-year,
    so the group reads CRITICAL only when that fraction is at least the share, and OK before:

    * 1 January: 1/365 = 0.27 percent, below 4 percent -> OK, and the stored year-end target is
      capped at 1.0 (the quotient would be about 17 to 53);
    * 5 March 2026: 64/365 = 17.5 percent -> CRITICAL, stored warning value 1.2 x (4..12 percent)
      / 0.175, so between 0.27 and 0.83;
    * 29 February 2028: 60/366 = 16.4 percent -> CRITICAL, stored warning between 0.29 and 0.88;
    * 31 December 2026: 365/365 = 100 percent -> CRITICAL, stored warning 1.2 x (4..12 percent),
      so between 0.047 and 0.145 (no execution row can be dated after this day).
    """

    clock_text: str
    today: date
    dirsa: IndicatorStatus
    stored_warning: tuple[float, float]  # (lowest, highest) stored DIRSA warning value
    future_rows: bool  # an execution row dated after today exists


DAYS: tuple[Day, ...] = (
    Day("2026-01-01T12:00:00Z", date(2026, 1, 1), OK, (1.0, 1.0), True),
    Day("2026-03-05T12:00:00Z", date(2026, 3, 5), CRIT, (0.25, 0.9), True),
    Day("2028-02-29T12:00:00Z", date(2028, 2, 29), CRIT, (0.25, 0.9), True),
    Day("2026-12-31T12:00:00Z", date(2026, 12, 31), CRIT, (0.04, 0.15), False),
)

#: (indicator code, dimension, status), worked out by hand from demo/targets.py. They hold on
#: every day of DAYS except the DIRSA budget group (see Day).
EXPECTED_STATUSES: tuple[tuple[str, str, IndicatorStatus], ...] = (
    ("PERS_CERT_VALID", "level=A", OK),
    ("PERS_CERT_VALID", "level=B", WARN),
    ("PERS_CERT_VALID", "level=C", CRIT),
    ("PERS_CERT_EXPIRING", "level=A", WARN),
    ("PERS_RETRAINING_NEEDED", "level=B", OK),
    ("PERS_TRAINING_12M", "", OK),
    ("INFRA_AVAILABLE", "type=bed", OK),
    ("INFRA_AVAILABLE", "type=decon_tent", WARN),
    ("INFRA_MAINT_OVERDUE", "type=bed", CRIT),
    ("INFRA_MAINT_OVERDUE", "type=decon_tent", OK),
    ("EX_LAST_PARTICIPANTS", "kind=CBRAMED", OK),
    ("EX_LAST_PARTICIPANTS", "kind=OTHER", WARN),
    ("EX_DAYS_SINCE_LAST", "kind=CBRAMED", OK),
    ("EX_DAYS_SINCE_LAST", "kind=OTHER", CRIT),
    ("BUD_EXEC_RATE", "currency=USD;source=COMAER", OK),
    # No target (P03): the application invents no standard.
    ("PERS_CERT_EXPIRING", "level=B", NO_TARGET),
    ("INFRA_AVAILABLE", "type=neg_pressure_filtration", NO_TARGET),
    # No data: an edition without a participant count; an entry without an allocation.
    ("EX_LAST_PARTICIPANTS", "kind=EXBRAMED", NO_DATA),
    ("BUD_EXEC_RATE", "currency=USD;source=DEMO-SRC-A", NO_DATA),
)
TARGET_COUNT = 16

#: The editions in the order of ExercisesService.list_editions() (start date, then code).
EDITION_ORDER = [
    "DEMO-EX-01",
    "DEMO-EX-04",
    "DEMO-EX-07",
    "DEMO-EX-02",
    "DEMO-EX-05",
    "DEMO-EX-08",
    "DEMO-EX-03",
    "DEMO-EX-06",
    "DEMO-EX-09",
]

#: (kind, subject reference, severity, days remaining), from the fixed cases of the generators.
EXPECTED_ALERTS: tuple[tuple[AlertKind, str, Severity, int], ...] = (
    (AlertKind.CERT_EXPIRED, "DEMO-P003", Severity.CRITICAL, -45),
    (AlertKind.CERT_EXPIRING, "DEMO-P002", Severity.WARNING, 30),
    (AlertKind.MAINT_OVERDUE, "DEMO-A001", Severity.CRITICAL, -20),
    (AlertKind.MAINT_DUE_SOON, "DEMO-A002", Severity.WARNING, 10),
)


@dataclass
class Demo:
    """The complete demo database with the services needed to read it."""

    conn: DatabaseConnection
    day: Day
    clock: FixedClock
    exercises: ExercisesService
    indicators: IndicatorService
    alerts: AlertService
    dashboard: DashboardService
    snapshots: SnapshotService
    budget: BudgetService

    @property
    def today(self) -> date:
        return self.day.today


def _services(conn: DatabaseConnection, day: Day, clock: FixedClock) -> Demo:
    personnel = PersonnelService(conn, clock)
    infrastructure = InfrastructureService(conn, clock)
    exercises = ExercisesService(conn, clock)
    budget = BudgetService(conn, clock)
    indicators = IndicatorService(
        conn,
        clock,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
    )
    alerts = AlertService(personnel=personnel, infrastructure=infrastructure, indicators=indicators)
    dashboard = DashboardService(
        indicators=indicators,
        alerts=alerts,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
    )
    snapshots = SnapshotService(conn, clock, indicators=indicators, infrastructure=infrastructure)
    return Demo(conn, day, clock, exercises, indicators, alerts, dashboard, snapshots, budget)


@pytest.fixture(scope="module", params=DAYS, ids=lambda day: day.today.isoformat())
def demo(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Demo]:
    """The complete demo database created on each day of DAYS (every test runs once per day)."""
    day: Day = request.param
    clock = FixedClock.at(day.clock_text)
    folder = tmp_path_factory.mktemp("demo-complete")
    conn = open_demo_database(folder, clock)
    try:
        yield _services(conn, day, clock)
    finally:
        conn.close()


def _rows(conn: DatabaseConnection, sql: str) -> list[tuple[object, ...]]:
    return [tuple(row) for row in conn.execute(sql).fetchall()]


def _dump(conn: DatabaseConnection) -> dict[str, list[tuple[object, ...]]]:
    names = [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            " ORDER BY name"
        ).fetchall()
    ]
    return {name: _rows(conn, f"SELECT * FROM {name} ORDER BY rowid") for name in names}


# --------------------------------------------------------------------------- registry and flag


def test_the_cross_module_generators_come_after_the_module_generators() -> None:
    names = [generator.name for generator in GENERATORS]
    assert names == ["personnel", "infrastructure", "exercises", "budget", "targets", "snapshots"]


def test_the_demo_flag_and_the_seed_marker_are_set(demo: Demo) -> None:
    assert app_meta.read_is_demo(demo.conn) is True
    assert app_meta.get(demo.conn, DEMO_SEED_KEY) == str(DEFAULT_SEED)


# --------------------------------------------------------------------------- targets and statuses


def _tiles(demo: Demo) -> dict[tuple[str, str], IndicatorStatus]:
    tiles = demo.dashboard.data(demo.today).tiles
    return {(tile.code, tile.dimension): tile.status for tile in tiles}


def test_the_dashboard_shows_the_hand_written_statuses(demo: Demo) -> None:
    tiles = _tiles(demo)
    for code, dimension, status in EXPECTED_STATUSES:
        assert tiles[(code, dimension)] is status, (code, dimension)
    assert tiles[DIRSA] is demo.day.dirsa


def test_every_status_appears_on_the_dashboard_on_every_day(demo: Demo) -> None:
    # The CRITICAL tile of the DIRSA group is missing on 1 January (see Day), but PERS_CERT_VALID
    # level C is CRITICAL on every day, so each of the five statuses still appears.
    assert set(_tiles(demo).values()) == set(IndicatorStatus)


def test_the_dirsa_group_has_the_executed_share_the_walkthrough_states(demo: Demo) -> None:
    [reading] = [
        reading
        for reading in demo.indicators.evaluate(demo.today)
        if (reading.code, reading.dimension) == DIRSA
    ]
    assert reading.value is not None
    assert 0.039 <= reading.value <= 0.12  # "4 to 12 percent" (demo/budget.py, low band)
    # The walkthrough: CRITICAL once the elapsed share of the year is above 12 percent, from 13
    # February (day 44 of 365 is 12.05 percent, day 43 is 11.78 percent).
    assert 44 / 365 > 0.12 > 43 / 365


def test_there_are_exactly_the_planned_targets_and_all_are_enabled(demo: Demo) -> None:
    targets = demo.indicators.list_targets()
    assert len(targets) == TARGET_COUNT
    assert all(target.enabled for target in targets)
    registry = build_registry()
    assert all(target.indicator_code in registry for target in targets)


def test_a_stored_budget_target_is_a_year_end_ratio_within_zero_and_one(demo: Demo) -> None:
    for dimension in (DIRSA[1], "currency=USD;source=COMAER"):
        target = demo.indicators.get_target("BUD_EXEC_RATE", dimension)
        assert target.warning_value is not None
        assert target.critical_value is not None
        assert 0.0 < target.critical_value <= target.warning_value <= 1.0


def test_the_dirsa_target_is_the_hand_worked_year_end_value_of_the_day(demo: Demo) -> None:
    target = demo.indicators.get_target(*DIRSA)
    assert target.warning_value is not None
    low, high = demo.day.stored_warning
    assert low <= target.warning_value <= high


def test_every_stored_ratio_target_is_accepted_by_the_service(demo: Demo) -> None:
    # The service refuses a ratio target below 0 or above MAX_RATIO_TARGET (TARGET_OUT_OF_RANGE);
    # the demo database could not be created on 1 January while it stored 17 to 53.
    registry = build_registry()
    ratios = [
        target
        for target in demo.indicators.list_targets()
        if registry.get(target.indicator_code).unit is UnitKind.RATIO
    ]
    assert {target.indicator_code for target in ratios} == {"BUD_EXEC_RATE"}
    for target in ratios:
        for value in (target.warning_value, target.critical_value):
            assert value is not None
            assert 0.0 <= value <= MAX_RATIO_TARGET


def test_an_execution_row_dated_after_today_exists_except_on_the_last_day_of_the_year(
    demo: Demo,
) -> None:
    after = demo.conn.execute(
        "SELECT count(*) FROM budget_execution AS e JOIN budget_entry AS b ON b.id = e.entry_id"
        " WHERE b.fiscal_year = ? AND e.executed_on > ?",
        (demo.today.year, demo.today.isoformat()),
    ).fetchone()[0]
    assert (after > 0) is demo.day.future_rows
    # Rows dated on or before today exist on every day (even on 1 January).
    until = demo.conn.execute(
        "SELECT count(*) FROM budget_execution AS e JOIN budget_entry AS b ON b.id = e.entry_id"
        " WHERE b.fiscal_year = ? AND e.executed_on <= ?",
        (demo.today.year, demo.today.isoformat()),
    ).fetchone()[0]
    assert until > 0


# --------------------------------------------------------------------------- alerts


def test_the_alerts_show_every_kind_and_every_severity(demo: Demo) -> None:
    alerts = demo.alerts.alerts(demo.today)
    # the stock kinds join the demo with the stock demo data (T11.16)
    stock_kinds = {"LOT_EXPIRED", "LOT_EXPIRING", "LOW_STOCK"}
    assert {alert.kind for alert in alerts} >= {
        kind for kind in AlertKind if kind.value not in stock_kinds
    }
    assert {alert.severity for alert in alerts} == set(Severity)
    counts = demo.dashboard.data(demo.today).alert_counts
    assert all(counts[severity] > 0 for severity in Severity)


def test_the_fixed_cases_raise_their_alerts(demo: Demo) -> None:
    alerts = demo.alerts.alerts(demo.today)
    found = {(a.kind, a.subject_ref, a.severity, a.days_remaining) for a in alerts}
    for expected in EXPECTED_ALERTS:
        assert expected in found, expected
    unknown = [a for a in alerts if a.kind is AlertKind.MAINT_SCHEDULE_UNKNOWN]
    assert "DEMO-A003" in {a.subject_ref for a in unknown}
    assert all(a.severity is Severity.INFO for a in unknown)


def test_a_person_without_renewal_and_an_unscheduled_asset_raise_nothing(demo: Demo) -> None:
    subjects = {alert.subject_ref for alert in demo.alerts.alerts(demo.today)}
    assert "DEMO-P004" not in subjects  # certificate valid, marked "no renewal"
    assert "DEMO-A004" not in subjects  # interval 0: no scheduled maintenance
    assert "DEMO-A008" not in subjects  # retired
    assert "DEMO-A009" not in subjects  # not yet in service


def test_the_alerts_are_sorted_by_severity(demo: Demo) -> None:
    ranks = [alert.severity.rank for alert in demo.alerts.alerts(demo.today)]
    assert ranks == sorted(ranks)


# --------------------------------------------------------------------------- snapshots


def test_one_retroactive_snapshot_exists_for_every_started_edition(demo: Demo) -> None:
    editions = demo.exercises.list_editions()
    assert len(editions) == 9  # DEMO-EX-01 .. DEMO-EX-09
    started = [edition for edition in editions if edition.start_on < demo.today]
    # list_editions() orders by start date, then code. The plan of demo/exercises.py puts the
    # editions at 44 (01), 38 (04), 32 (07), 28 (02), 20 (05), 14 (08), 9 (03), 4 (06) months
    # before today and 09 five months after it.
    assert [edition.code for edition in started] == EDITION_ORDER[:8]
    assert [edition.code for edition in editions] == EDITION_ORDER

    snapshots = demo.snapshots.list_snapshots()
    assert len(snapshots) == 8
    assert {snapshot.as_of for snapshot in snapshots} == {
        edition.start_on - timedelta(days=1) for edition in started
    }
    assert {snapshot.origin for snapshot in snapshots} == {SnapshotOrigin.RETROACTIVE}
    assert min(snapshot.as_of for snapshot in snapshots) < min(e.start_on for e in editions)
    taken = demo.day.clock_text.removesuffix("Z")  # e.g. 2026-03-05T12:00:00
    assert all(snapshot.taken_at_utc.startswith(taken) for snapshot in snapshots)
    assert all(snapshot.note and snapshot.note.startswith("DEMO") for snapshot in snapshots)
    assert not any(snapshot.withdrawn for snapshot in snapshots)
    assert len(demo.snapshots.list_snapshots(include_withdrawn=True)) == 8


def test_the_future_edition_has_no_snapshot(demo: Demo) -> None:
    future = [e for e in demo.exercises.list_editions() if e.start_on > demo.today]
    assert [edition.code for edition in future] == ["DEMO-EX-09"]
    latest_as_of = max(snapshot.as_of for snapshot in demo.snapshots.list_snapshots())
    assert latest_as_of < demo.today


def test_each_snapshot_stores_the_readings_and_the_targets_in_force(demo: Demo) -> None:
    snapshots = demo.snapshots.list_snapshots()
    assert len({snapshot.config_hash for snapshot in snapshots}) == 1  # the configuration is stable
    for snapshot in snapshots:
        detail = demo.snapshots.get(snapshot.id)
        assert len(json.loads(detail.config_json)["targets"]) == TARGET_COUNT
        by_key = {(v.indicator_code, v.dimension): v for v in detail.values}
        valid_a = by_key[("PERS_CERT_VALID", "level=A")]
        assert valid_a.warning_value is not None  # the target of level A was in force
        assert valid_a.status in {OK, WARN, CRIT}
        assert by_key[("PERS_CERT_VALID", "level=B")].value is not None


# --------------------------------------------------------------------------- validation export


def _export_service(demo: Demo) -> ValidationExportService:
    return ValidationExportService(
        demo.conn,
        demo.clock,
        snapshots=demo.snapshots,
        exercises=demo.exercises,
        indicators=demo.indicators,
    )


def _csv_records(path: Path) -> tuple[list[str], list[list[str]]]:
    """``(header, data rows)`` of a validation file; the banner record comes first."""
    text = path.read_text(encoding="utf-8-sig")
    records = list(csv.reader(io.StringIO(text), delimiter=";"))
    assert records[0][0] == UNSUPPRESSED_BANNER
    return records[1], records[2:]


def test_no_edition_has_a_regular_snapshot_so_every_one_is_offered_a_retroactive_reading(
    demo: Demo,
) -> None:
    # All demo snapshots are retroactive, and a regular one has to be non-retroactive (T8.2).
    assert _export_service(demo).editions_without_prior_snapshot() == EDITION_ORDER


def test_the_validation_export_without_the_request_carries_only_the_reason_code(
    demo: Demo, tmp_path: Path
) -> None:
    result = _export_service(demo).export(tmp_path / "plain")
    header, rows = _csv_records(result.readings.path)
    column = {name: index for index, name in enumerate(header)}
    assert len(rows) == 9  # one row per edition
    assert {row[column["reason_code"]] for row in rows} == {NO_PRIOR_SNAPSHOT}
    assert result.recorded_snapshot_ids == ()
    assert result.editions_without_reading == tuple(EDITION_ORDER)


def test_the_validation_export_of_the_demo_database_produces_rows(
    demo: Demo, tmp_path: Path
) -> None:
    before = len(demo.snapshots.list_snapshots())
    result = _export_service(demo).export(tmp_path / "out", record_retroactive=True)

    # The eight retroactive snapshots of the demo database are reused: nothing new is recorded.
    assert result.recorded_snapshot_ids == ()
    assert len(demo.snapshots.list_snapshots()) == before == 8
    # Only DEMO-EX-09 starts in the future, so only it has no reading.
    assert result.editions_without_reading == ("DEMO-EX-09",)

    # Demo database: the file names start with DEMO- and say that the data is unsuppressed.
    for exported in (result.readings, result.results):
        assert exported.path.name.startswith("DEMO-")
        assert exported.path.is_file()
    assert "unsuppressed_internal" in result.readings.path.name
    assert "unsuppressed_internal" in result.results.path.name

    header, rows = _csv_records(result.readings.path)
    column = {name: index for index, name in enumerate(header)}
    started = EDITION_ORDER[:8]
    snapshot_rows = [row for row in rows if row[column["edition_code"]] in started]
    reason_rows = [row for row in rows if row[column["edition_code"]] == "DEMO-EX-09"]
    assert len(reason_rows) == 1
    assert reason_rows[0][column["reason_code"]] == NO_PRIOR_SNAPSHOT
    assert {row[column["edition_code"]] for row in snapshot_rows} == set(started)
    assert {row[column["origin"]] for row in snapshot_rows} == {"retroactive"}
    assert {row[column["reason_code"]] for row in snapshot_rows} == {""}
    # Every started edition has indicator readings of its own snapshot.
    per_edition = {code: 0 for code in started}
    for row in snapshot_rows:
        per_edition[row[column["edition_code"]]] += 1
    assert all(count > 0 for count in per_edition.values())
    assert any(row[column["indicator_code"]] == "PERS_CERT_VALID" for row in snapshot_rows)
    # Aggregates only: no staff identifier or asset tag in either file.
    for exported in (result.readings, result.results):
        assert "DEMO-P0" not in exported.path.read_text(encoding="utf-8-sig")
        assert "DEMO-A0" not in exported.path.read_text(encoding="utf-8-sig")

    # Results: two metrics for each of the eight past editions, none for the future one.
    result_header, result_rows = _csv_records(result.results.path)
    result_column = {name: index for index, name in enumerate(result_header)}
    assert len(result_rows) == 16
    assert {row[result_column["metric_code"]] for row in result_rows} == {"DEMO-M1", "DEMO-M2"}
    assert {row[result_column["edition_code"]] for row in result_rows} == set(started)


# --------------------------------------------------------------------------- demo marker


@pytest.mark.parametrize(
    ("table", "column", "where"),
    [
        ("staff_member", "identifier", "1"),
        ("staff_member", "label", "label IS NOT NULL"),
        ("staff_member", "category", "category IS NOT NULL"),
        ("training_course", "code", "1"),
        ("training_course", "label_pt_br", "label_pt_br IS NOT NULL"),
        ("academic_degree", "field", "field IS NOT NULL"),
        ("asset_type", "code", "built_in = 0"),
        ("asset_type", "label_pt_br", "built_in = 0"),
        ("asset", "tag", "1"),
        ("asset", "description", "description IS NOT NULL"),
        ("asset", "location", "location IS NOT NULL"),
        ("exercise_edition", "code", "1"),
        ("exercise_edition", "title", "title IS NOT NULL"),
        ("exercise_edition", "notes", "notes IS NOT NULL"),
        ("evaluation_metric", "code", "1"),
        ("evaluation_metric", "label_pt_br", "label_pt_br IS NOT NULL"),
        ("funding_source", "code", "built_in = 0"),
        ("funding_source", "label_pt_br", "built_in = 0"),
        ("budget_entry", "description", "1"),
        ("budget_entry", "notes", "notes IS NOT NULL"),
        ("budget_execution", "note", "note IS NOT NULL"),
        ("readiness_snapshot", "note", "1"),
    ],
)
def test_no_record_lacks_the_demo_marker(demo: Demo, table: str, column: str, where: str) -> None:
    values = [row[0] for row in _rows(demo.conn, f"SELECT {column} FROM {table} WHERE {where}")]
    assert values, (table, column)
    assert [value for value in values if not str(value).startswith("DEMO")] == []


def test_every_change_is_attributed_to_the_demo_operator(demo: Demo) -> None:
    assert _rows(demo.conn, "SELECT DISTINCT operator FROM change_log") == [("DEMO",)]


# --------------------------------------------------------------------------- determinism


def test_two_runs_give_identical_content(demo: Demo, tmp_path: Path) -> None:
    other = open_demo_database(tmp_path, demo.clock)
    try:
        assert _dump(other) == _dump(demo.conn)
    finally:
        other.close()


# --------------------------------------------------------------------------- the real database


def test_the_real_database_of_the_same_folder_has_no_demo_rows_targets_or_snapshots(
    demo: Demo, tmp_path: Path
) -> None:
    # The REAL database lives in the same data folder as the demo one (the case that matters:
    # a copy of the demo data in another folder could not show a leak).
    real = open_and_migrate(
        tmp_path / DATABASE_FILE_NAME, data_dir=tmp_path, identity=DatabaseIdentity.REAL
    )
    app_meta.initialise(real, is_demo=False, created_with="0.0.1")
    real.close()
    other = open_demo_database(tmp_path, demo.clock)
    other.close()
    assert demo.indicators.list_targets()  # the demo run happened and wrote targets

    with closing(open_database(tmp_path / DATABASE_FILE_NAME, read_only=True)) as reopened:
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
            assert _rows(reopened, f"SELECT count(*) FROM {table}") == [(0,)], table
        assert not app_meta.read_is_demo(reopened)
        assert app_meta.get(reopened, DEMO_SEED_KEY) is None
        assert app_meta.get(reopened, DEMO_CREATED_ON_KEY) is None


def test_the_demo_run_creates_no_real_database(demo: Demo, tmp_path: Path) -> None:
    conn = open_demo_database(tmp_path, demo.clock)
    conn.close()
    assert not (tmp_path / DATABASE_FILE_NAME).exists()


def test_the_creation_day_is_stored_next_to_the_demo_flag(demo: Demo) -> None:
    assert app_meta.get(demo.conn, DEMO_CREATED_ON_KEY) == demo.today.isoformat()
    assert creation_day(demo.conn) == demo.today
    assert is_outdated(demo.conn, demo.clock) is False
    assert is_outdated(demo.conn, FixedClock.at("2030-06-15T12:00:00Z")) is True


def test_demo_data_without_a_creation_day_is_outdated(demo: Demo, tmp_path: Path) -> None:
    # Demo data written before the creation day was stored: its day cannot be known (QA P10-09).
    other = open_demo_database(tmp_path, demo.clock)
    try:
        with transaction(other):
            other.execute("DELETE FROM app_meta WHERE key = ?", (DEMO_CREATED_ON_KEY,))
        assert creation_day(other) is None
        assert is_outdated(other, demo.clock) is True
        assert is_outdated(other, FixedClock.at("2030-06-15T12:00:00Z")) is True
    finally:
        other.close()


def test_generate_refuses_a_database_that_is_not_flagged_demo(demo: Demo, tmp_path: Path) -> None:
    real = open_and_migrate(
        tmp_path / DATABASE_FILE_NAME, data_dir=tmp_path, identity=DatabaseIdentity.REAL
    )
    try:
        app_meta.initialise(real, is_demo=False, created_with="0.0.1")
        with pytest.raises(DemoDataError) as excinfo:
            generate(real, demo.clock)
        assert excinfo.value.code == NOT_A_DEMO_DATABASE
        for table in ("indicator_target", "readiness_snapshot", "staff_member", "asset"):
            assert _rows(real, f"SELECT count(*) FROM {table}") == [(0,)], table
        assert app_meta.get(real, DEMO_SEED_KEY) is None
        assert app_meta.get(real, DEMO_CREATED_ON_KEY) is None
    finally:
        real.close()


def test_generate_refuses_a_database_without_an_is_demo_row(demo: Demo, tmp_path: Path) -> None:
    bare = open_and_migrate(
        tmp_path / "bare.sqlite3", data_dir=tmp_path, identity=DatabaseIdentity.REAL
    )
    try:
        with pytest.raises(DemoDataError) as excinfo:
            generate(bare, demo.clock)
        assert excinfo.value.code == NOT_A_DEMO_DATABASE
        assert _rows(bare, "SELECT count(*) FROM indicator_target") == [(0,)]
    finally:
        bare.close()


# --------------------------------------------------------------------------- the walkthrough


def _document_text() -> str:
    text = DOCUMENT.read_text(encoding="utf-8")
    return re.sub(r"(?s)```.*?```", "", text)  # fenced blocks hold commands, not record names


def _quoted(text: str) -> list[str]:
    return re.findall(r"`([^`\n]+)`", text)


def _dataset_names(conn: DatabaseConnection) -> set[str]:
    queries = (
        "SELECT identifier FROM staff_member",
        "SELECT code FROM training_course",
        "SELECT code FROM asset_type",
        "SELECT tag FROM asset",
        "SELECT code FROM exercise_edition",
        "SELECT code FROM evaluation_metric",
        "SELECT code FROM funding_source",
        "SELECT description FROM budget_entry",
    )
    return {str(row[0]) for query in queries for row in conn.execute(query).fetchall()}


def test_the_walkthrough_exists_and_is_ascii() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    assert text.isascii()
    assert "--demo" in text


def test_every_demo_record_quoted_in_the_walkthrough_exists(demo: Demo) -> None:
    names = [token for token in _quoted(_document_text()) if token.startswith("DEMO")]
    assert len(set(names)) >= 25
    known = _dataset_names(demo.conn)
    assert [name for name in names if name not in known] == []


def test_the_walkthrough_names_the_fixed_cases_it_describes(demo: Demo) -> None:
    quoted = set(_quoted(_document_text()))
    for required in ("DEMO-P003", "DEMO-A001", "DEMO-EX-06", "DEMO-EX-09", "DEMO-SRC-A"):
        assert required in quoted


def test_every_code_quoted_in_the_walkthrough_is_a_known_code(demo: Demo) -> None:
    known = (
        set(build_registry().codes())
        | {kind.value for kind in AlertKind}
        | {status.value for status in IndicatorStatus}
        | {NO_PRIOR_SNAPSHOT}
    )
    codes = [
        token
        for token in _quoted(_document_text())
        if re.fullmatch(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+", token)
    ]
    assert codes
    assert [code for code in codes if code not in known] == []


# The two tables of the walkthrough are tied to the dataset: they are parsed and compared with the
# statuses and the alerts the dataset gives on the day it was created.

_STATUS_WORDS = {"OK": OK, "Warning": WARN, "Critical": CRIT}


def _table_rows() -> list[list[str]]:
    """The cells of every Markdown table row whose first cell is a code in backquotes."""
    rows: list[list[str]] = []
    for line in _document_text().splitlines():
        if not line.startswith("| `"):
            continue
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _dimension(code: str, text: str) -> str:
    """The encoded dimension (PLAN.md 5.4) of a dimension as the walkthrough words it."""
    if text in ("none", ""):
        return ""
    if text.startswith("level "):
        return "level=" + text.removeprefix("level ")
    if code.startswith("INFRA_"):
        return f"type={text}"
    if code.startswith("EX_"):
        return f"kind={text}"
    currency, source = text.split(", ")
    return f"currency={currency};source={source}"


def _documented_statuses() -> dict[tuple[str, str], IndicatorStatus]:
    documented: dict[tuple[str, str], IndicatorStatus] = {}
    for cells in _table_rows():
        if len(cells) == 3 and cells[2] in _STATUS_WORDS:
            code = cells[0].strip("`")
            documented[(code, _dimension(code, cells[1]))] = _STATUS_WORDS[cells[2]]
    return documented


def test_the_walkthrough_status_table_is_the_statuses_of_the_dataset(demo: Demo) -> None:
    documented = _documented_statuses()
    assert len(documented) == TARGET_COUNT
    tiles = _tiles(demo)
    on_the_day = {key: status for key, status in tiles.items() if status in (OK, WARN, CRIT)}
    # The table is written for a database created from 13 February on; the walkthrough says that
    # the DIRSA group reads OK before (its executed share is above the elapsed part of the year).
    assert "13 February" in _document_text()
    if demo.day.dirsa is OK:
        documented[DIRSA] = OK
    assert documented == on_the_day


def test_the_walkthrough_alert_table_is_the_alerts_of_the_dataset(demo: Demo) -> None:
    alerts = demo.alerts.alerts(demo.today)
    rows = [cells for cells in _table_rows() if cells[0].strip("`") in AlertKind.__members__]
    # the stock kinds join the walkthrough with the stock demo data (T11.16)
    stock_kinds = {"LOT_EXPIRED", "LOT_EXPIRING", "LOW_STOCK"}
    assert {cells[0].strip("`") for cells in rows} == set(AlertKind.__members__) - stock_kinds
    for cells in rows:
        kind, severity, example = cells[0].strip("`"), cells[1], cells[2]
        reference, _, level = example.partition(", ")
        matching = [
            alert
            for alert in alerts
            if alert.kind.value == kind
            and alert.subject_ref == reference.strip("`")
            and alert.dimension == _dimension("", level)
        ]
        assert matching, (kind, example)
        assert {alert.severity.value.lower() for alert in matching} == {severity}, (kind, example)
