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
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import (
    DEFAULT_SEED,
    DEMO_SEED_KEY,
    GENERATORS,
    open_demo_database,
)
from cbrn_dashboard.domain.alerts import AlertKind, Severity
from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.domain.registry import build_registry
from cbrn_dashboard.paths import DATABASE_FILE_NAME
from cbrn_dashboard.services.alerts import AlertService
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.dashboard import DashboardService
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.services.snapshots import SnapshotOrigin, SnapshotService
from cbrn_dashboard.services.validation_export import (
    NO_PRIOR_SNAPSHOT,
    UNSUPPRESSED_BANNER,
    ValidationExportService,
)
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")
TODAY = date(2026, 3, 5)
DOCUMENT = Path(__file__).resolve().parents[2] / "docs" / "demo-walkthrough.md"

OK = IndicatorStatus.OK
WARN = IndicatorStatus.WARNING
CRIT = IndicatorStatus.CRITICAL
NO_TARGET = IndicatorStatus.NO_TARGET
NO_DATA = IndicatorStatus.NO_DATA

#: (indicator code, dimension, status) on TODAY, worked out by hand from demo/targets.py.
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
    ("BUD_EXEC_RATE", "currency=BRL;source=DIRSA", CRIT),
    ("BUD_EXEC_RATE", "currency=USD;source=OPCW_TRUST_FUND", OK),
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
    exercises: ExercisesService
    indicators: IndicatorService
    alerts: AlertService
    dashboard: DashboardService
    snapshots: SnapshotService


def _services(conn: DatabaseConnection) -> Demo:
    personnel = PersonnelService(conn, CLOCK)
    infrastructure = InfrastructureService(conn, CLOCK)
    exercises = ExercisesService(conn, CLOCK)
    budget = BudgetService(conn, CLOCK)
    indicators = IndicatorService(
        conn,
        CLOCK,
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
    snapshots = SnapshotService(conn, CLOCK, indicators=indicators, infrastructure=infrastructure)
    return Demo(conn, exercises, indicators, alerts, dashboard, snapshots)


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Demo]:
    folder = tmp_path_factory.mktemp("demo-complete")
    conn = open_demo_database(folder, CLOCK)
    try:
        yield _services(conn)
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


def test_the_dashboard_shows_the_hand_written_statuses(demo: Demo) -> None:
    tiles = {(tile.code, tile.dimension): tile.status for tile in demo.dashboard.data(TODAY).tiles}
    for code, dimension, status in EXPECTED_STATUSES:
        assert tiles[(code, dimension)] is status, (code, dimension)


def test_every_status_appears_on_the_dashboard(demo: Demo) -> None:
    statuses = {tile.status for tile in demo.dashboard.data(TODAY).tiles}
    assert statuses == set(IndicatorStatus)


def test_there_are_exactly_the_planned_targets_and_all_are_enabled(demo: Demo) -> None:
    targets = demo.indicators.list_targets()
    assert len(targets) == TARGET_COUNT
    assert all(target.enabled for target in targets)
    registry = build_registry()
    assert all(target.indicator_code in registry for target in targets)


def test_a_stored_budget_target_is_a_year_end_ratio_below_one(demo: Demo) -> None:
    target = demo.indicators.get_target("BUD_EXEC_RATE", "currency=BRL;source=DIRSA")
    assert target.warning_value is not None
    assert target.critical_value is not None
    assert 0.0 < target.critical_value <= target.warning_value < 1.0


# --------------------------------------------------------------------------- alerts


def test_the_alerts_show_every_kind_and_every_severity(demo: Demo) -> None:
    alerts = demo.alerts.alerts(TODAY)
    assert {alert.kind for alert in alerts} == set(AlertKind)
    assert {alert.severity for alert in alerts} == set(Severity)
    counts = demo.dashboard.data(TODAY).alert_counts
    assert all(counts[severity] > 0 for severity in Severity)


def test_the_fixed_cases_raise_their_alerts(demo: Demo) -> None:
    alerts = demo.alerts.alerts(TODAY)
    found = {(a.kind, a.subject_ref, a.severity, a.days_remaining) for a in alerts}
    for expected in EXPECTED_ALERTS:
        assert expected in found, expected
    unknown = [a for a in alerts if a.kind is AlertKind.MAINT_SCHEDULE_UNKNOWN]
    assert "DEMO-A003" in {a.subject_ref for a in unknown}
    assert all(a.severity is Severity.INFO for a in unknown)


def test_a_person_without_renewal_and_an_unscheduled_asset_raise_nothing(demo: Demo) -> None:
    subjects = {alert.subject_ref for alert in demo.alerts.alerts(TODAY)}
    assert "DEMO-P004" not in subjects  # certificate valid, marked "no renewal"
    assert "DEMO-A004" not in subjects  # interval 0: no scheduled maintenance
    assert "DEMO-A008" not in subjects  # retired
    assert "DEMO-A009" not in subjects  # not yet in service


def test_the_alerts_are_sorted_by_severity(demo: Demo) -> None:
    ranks = [alert.severity.rank for alert in demo.alerts.alerts(TODAY)]
    assert ranks == sorted(ranks)


# --------------------------------------------------------------------------- snapshots


def test_one_retroactive_snapshot_exists_for_every_started_edition(demo: Demo) -> None:
    editions = demo.exercises.list_editions()
    assert len(editions) == 9  # DEMO-EX-01 .. DEMO-EX-09
    started = [edition for edition in editions if edition.start_on < TODAY]
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
    assert all(snapshot.taken_at_utc.startswith("2026-03-05T12:00:00") for snapshot in snapshots)
    assert all(snapshot.note and snapshot.note.startswith("DEMO") for snapshot in snapshots)
    assert not any(snapshot.withdrawn for snapshot in snapshots)
    assert len(demo.snapshots.list_snapshots(include_withdrawn=True)) == 8


def test_the_future_edition_has_no_snapshot(demo: Demo) -> None:
    future = [e for e in demo.exercises.list_editions() if e.start_on > TODAY]
    assert [edition.code for edition in future] == ["DEMO-EX-09"]
    latest_as_of = max(snapshot.as_of for snapshot in demo.snapshots.list_snapshots())
    assert latest_as_of < TODAY


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
        CLOCK,
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
    other = open_demo_database(tmp_path, CLOCK)
    try:
        assert _dump(other) == _dump(demo.conn)
    finally:
        other.close()


# --------------------------------------------------------------------------- the real database


def test_a_real_database_in_another_folder_has_no_targets_and_no_snapshots(
    demo: Demo, tmp_path: Path
) -> None:
    assert demo.indicators.list_targets()  # the demo run happened and wrote targets
    real_folder = tmp_path / "real"
    real_folder.mkdir()
    real = open_and_migrate(
        real_folder / DATABASE_FILE_NAME, data_dir=real_folder, identity=DatabaseIdentity.REAL
    )
    try:
        for table in (
            "indicator_target",
            "readiness_snapshot",
            "readiness_snapshot_value",
            "snapshot_withdrawal",
        ):
            assert _rows(real, f"SELECT count(*) FROM {table}") == [(0,)], table
        assert not app_meta.read_is_demo(real)
    finally:
        real.close()


def test_the_demo_run_creates_no_real_database(tmp_path: Path) -> None:
    conn = open_demo_database(tmp_path, CLOCK)
    conn.close()
    assert not (tmp_path / DATABASE_FILE_NAME).exists()


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
    assert [code for code in codes if code not in known and code != "OPCW_TRUST_FUND"] == []
