# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the validation export (PLAN.md T8.2, R29, R31, K03, K13, A11, D04, D25).

All data is fictitious and is written through the module services on a migrated database. The
expected rows are written out by hand below; the snapshot ids, dates, ages and values follow from
the timeline in :func:`_world` and are worked out in the comments, never computed by the code under
test.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.errors import READ_ONLY, ServiceError
from cbrn_dashboard.services.exercises import (
    EditionInput,
    ExercisesService,
    MetricInput,
    ResultInput,
)
from cbrn_dashboard.services.export import EXPORT_FAILED
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import (
    CertificateInput,
    PersonnelService,
    StaffInput,
)
from cbrn_dashboard.services.snapshots import SnapshotOrigin, SnapshotService
from cbrn_dashboard.services.validation_export import (
    NO_PRIOR_SNAPSHOT,
    READINGS_ENTITY,
    RESULTS_ENTITY,
    SUPPRESSED_BANNER,
    UNSUPPRESSED_BANNER,
    ValidationExportError,
    ValidationExportService,
    readings_spec,
    results_spec,
)
from cbrn_dashboard.storage import app_meta, csv_io
from cbrn_dashboard.storage.csv_io import BelowThreshold
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import load_config, save_config

OPERATOR = "op-demo"
MANUAL = SnapshotOrigin.MANUAL

HEADER_READINGS = [
    "edition_code",
    "kind",
    "start_on",
    "snapshot_id",
    "snapshot_as_of",
    "taken_at_utc",
    "age_days",
    "origin",
    "indicator_code",
    "dimension",
    "value",
    "status",
    "reason_code",
]
HEADER_RESULTS = [
    "edition_code",
    "metric_code",
    "value",
    "respondents",
    "scale_min",
    "scale_max",
]
BOM = b"\xef\xbb\xbf"

#: Column positions in the readings file.
INDICATOR = 8
DIMENSION = 9
VALUE = 10
STATUS = 11

CERT_CODE = "PERS_CERT_VALID"
LEVEL_A = "level=A"
PARTICIPANTS_CODE = "EX_LAST_PARTICIPANTS"
CBRAMED_DIM = "kind=CBRAMED"


# --------------------------------------------------------------------------- the world


@dataclass
class Stack:
    """The module services, the snapshot service and the export over one connection."""

    conn: DatabaseConnection
    personnel: PersonnelService
    exercises: ExercisesService
    indicators: IndicatorService
    snapshots: SnapshotService
    export: ValidationExportService


def _stack(conn: DatabaseConnection, clock: FixedClock) -> Stack:
    def operator() -> str:
        return OPERATOR

    personnel = PersonnelService(conn, clock, operator)
    infrastructure = InfrastructureService(conn, clock, operator)
    exercises = ExercisesService(conn, clock, operator)
    budget = BudgetService(conn, clock, operator)
    indicators = IndicatorService(
        conn,
        clock,
        operator,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
    )
    snapshots = SnapshotService(
        conn, clock, operator, indicators=indicators, infrastructure=infrastructure
    )
    export = ValidationExportService(
        conn, clock, snapshots=snapshots, exercises=exercises, indicators=indicators
    )
    return Stack(conn, personnel, exercises, indicators, snapshots, export)


def _at(day: str) -> FixedClock:
    return FixedClock.at(f"{day}T12:00:00Z")


def _add_person(stack: Stack, identifier: str, active_from: str, issued: str, until: str) -> None:
    person = stack.personnel.create_staff(StaffInput(identifier, active_from))
    stack.personnel.add_certificate(person, CertificateInput("A", issued, until))


def _world(conn: DatabaseConnection) -> Stack:
    """The fictitious dataset; returns the stack at the final clock, 2026-03-05.

    Timeline (every clock reads 12:00 UTC, offset 0, so the taken date is the day itself):

    * 2026-01-10: editions, metrics, results, the first person and the target of level A;
    * 2026-01-15 snapshot 1 (manual, A = 1 valid certificate);
    * 2026-02-01 second person; snapshot 2 (manual, A = 2);
    * 2026-02-20 third person; snapshot 3 (manual, A = 3), AFTER DEMO-EX-01 started;
    * 2026-03-05 snapshot 4 (manual, A = 3) and snapshot 5, a reading as of 2026-02-09 that the
      service stores as ``retroactive`` (A = 3 with today's data).

    Editions are created out of code order on purpose: DEMO-EX-02, DEMO-EX-00, DEMO-EX-01.
    """
    first = _stack(conn, _at("2026-01-10"))
    first.exercises.create_edition(
        EditionInput(
            code="DEMO-EX-02",
            kind="EXBRAMED",
            start_on="2026-04-01",
            end_on="2026-04-03",
            participants=20,
        )
    )
    old = first.exercises.create_edition(
        EditionInput(
            code="DEMO-EX-00",
            kind="CBRAMED",
            start_on="2025-10-01",
            end_on="2025-10-05",
            participants=1,
            title="DEMO-TITLE-SECRET",
            notes="DEMO-NOTE-SECRET",
        )
    )
    mid = first.exercises.create_edition(
        EditionInput(
            code="DEMO-EX-01",
            kind="CBRAMED",
            start_on="2026-02-10",
            end_on="2026-02-14",
            participants=40,
        )
    )
    m1 = first.exercises.create_metric(
        MetricInput("DEMO-M1", "Metrica 1", scale_min=0.0, scale_max=10.0)
    )
    m2 = first.exercises.create_metric(
        MetricInput("DEMO-M2", "Metrica 2", scale_min=1.0, scale_max=5.0)
    )
    m3 = first.exercises.create_metric(
        MetricInput("DEMO-M3", "Metrica 3", scale_min=-5.0, scale_max=5.0)
    )
    first.exercises.set_result(old, ResultInput(m1, 6.0, 3, "DEMO-RESULT-NOTE"))
    first.exercises.set_result(mid, ResultInput(m1, 7.5, 12))
    first.exercises.set_result(mid, ResultInput(m2, 4.0))
    first.exercises.set_result(mid, ResultInput(m3, -2.5))
    _add_person(first, "DEMO-P001", "2020-01-01", "2025-01-10", "2027-01-10")
    first.indicators.set_target(CERT_CODE, LEVEL_A, warning_value=2, critical_value=1)

    _stack(conn, _at("2026-01-15")).snapshots.record(date(2026, 1, 15), origin=MANUAL)

    second = _stack(conn, _at("2026-02-01"))
    _add_person(second, "DEMO-P002", "2020-01-01", "2025-02-10", "2027-02-10")
    second.snapshots.record(date(2026, 2, 1), origin=MANUAL, note="DEMO-SNAP-NOTE")

    third = _stack(conn, _at("2026-02-20"))
    _add_person(third, "DEMO-P003", "2021-01-01", "2025-03-01", "2027-03-01")
    third.snapshots.record(date(2026, 2, 20), origin=MANUAL)

    last = _stack(conn, _at("2026-03-05"))
    last.snapshots.record(date(2026, 3, 5), origin=MANUAL)
    retro = last.snapshots.record(date(2026, 2, 9), origin=MANUAL)
    assert retro.origin is SnapshotOrigin.RETROACTIVE
    assert retro.id == 5
    return last


@pytest.fixture
def world(db: DatabaseConnection) -> Stack:
    return _world(db)


# --------------------------------------------------------------------------- helpers


def _table(path: Path) -> list[list[str]]:
    text = path.read_bytes().decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=";", quotechar='"'))


def _data(path: Path, banner: str = UNSUPPRESSED_BANNER) -> list[list[str]]:
    """The records after the banner and the header row (both checked here)."""
    table = _table(path)
    assert table[0] == [banner]
    assert table[1] in (HEADER_READINGS, HEADER_RESULTS)
    return table[2:]


def _readings(stack: Stack, out: Path, **options: bool) -> list[list[str]]:
    result = stack.export.export(out, **options)
    banner = SUPPRESSED_BANNER if options.get("suppress_small_counts") else UNSUPPRESSED_BANNER
    return _data(result.readings.path, banner)


def _only(rows: list[list[str]], *codes: str) -> list[list[str]]:
    """The rows of the given indicator codes, plus the rows that carry a reason code."""
    return [r for r in rows if r[INDICATOR] in codes or r[12] != ""]


def _cert_rows(
    edition: str,
    kind: str,
    start: str,
    snapshot: tuple[str, str, str, str, str],
    values: list[str],
) -> list[list[str]]:
    """The three PERS_CERT_VALID rows (levels A, B, C) of an edition.

    ``snapshot`` is ``(id, as_of, taken_at_utc, age_days, origin)``; ``values`` is
    ``[value A, status A, value B, status B, value C, status C]``.
    """
    rows: list[list[str]] = []
    for level, at in (("A", 0), ("B", 2), ("C", 4)):
        head = [edition, kind, start, *snapshot]
        rows.append([*head, CERT_CODE, f"level={level}", values[at], values[at + 1], ""])
    return rows


NO_PRIOR_00 = ["DEMO-EX-00", "CBRAMED", "2025-10-01", *[""] * 9, NO_PRIOR_SNAPSHOT]
NO_PRIOR_01 = ["DEMO-EX-01", "CBRAMED", "2026-02-10", *[""] * 9, NO_PRIOR_SNAPSHOT]
ZERO_BC = ["0.0", "NO_TARGET", "0.0", "NO_TARGET"]

# Snapshot 2: 2026-02-01, 9 days before 2026-02-10, A = 2 -> WARNING (warning 2, critical 1).
SNAP_2 = ("2", "2026-02-01", "2026-02-01T12:00:00Z", "9", "manual")
# Snapshot 1: 2026-01-15, 26 days before 2026-02-10, A = 1 -> CRITICAL.
SNAP_1 = ("1", "2026-01-15", "2026-01-15T12:00:00Z", "26", "manual")
# Snapshot 4: 2026-03-05, 27 days before 2026-04-01, A = 3 -> OK.
SNAP_4 = ("4", "2026-03-05", "2026-03-05T12:00:00Z", "27", "manual")
# Snapshot 3: 2026-02-20, 40 days before 2026-04-01, A = 3 -> OK.
SNAP_3 = ("3", "2026-02-20", "2026-02-20T12:00:00Z", "40", "manual")
# Snapshot 5: as of 2026-02-09, taken 2026-03-05: 23 days AFTER 2026-02-10 (negative age).
SNAP_5 = ("5", "2026-02-09", "2026-03-05T12:00:00Z", "-23", "retroactive")


# --------------------------------------------------------------------------- the right snapshot


def test_the_latest_snapshot_before_each_edition_is_chosen(world: Stack, tmp_path: Path) -> None:
    rows = _only(_readings(world, tmp_path / "out"), CERT_CODE)
    assert rows == [
        NO_PRIOR_00,
        *_cert_rows("DEMO-EX-01", "CBRAMED", "2026-02-10", SNAP_2, ["2.0", "WARNING", *ZERO_BC]),
        *_cert_rows("DEMO-EX-02", "EXBRAMED", "2026-04-01", SNAP_4, ["3.0", "OK", *ZERO_BC]),
    ]


def test_snapshots_taken_after_the_start_are_not_used(world: Stack, tmp_path: Path) -> None:
    rows = _readings(world, tmp_path / "out")
    ids = {r[0]: r[3] for r in rows}
    assert ids == {"DEMO-EX-00": "", "DEMO-EX-01": "2", "DEMO-EX-02": "4"}
    # Snapshot 3 (2026-02-20) was taken after DEMO-EX-01 started, and is not the latest before
    # DEMO-EX-02 either (snapshot 4 is).
    assert "3" not in {r[3] for r in rows}


def test_withdrawn_snapshots_are_not_preferred(world: Stack, tmp_path: Path) -> None:
    world.snapshots.withdraw(2, "DEMO reason")
    world.snapshots.withdraw(4, "DEMO reason")
    rows = _only(_readings(world, tmp_path / "out"), CERT_CODE)
    assert rows == [
        NO_PRIOR_00,
        *_cert_rows("DEMO-EX-01", "CBRAMED", "2026-02-10", SNAP_1, ["1.0", "CRITICAL", *ZERO_BC]),
        *_cert_rows("DEMO-EX-02", "EXBRAMED", "2026-04-01", SNAP_3, ["3.0", "OK", *ZERO_BC]),
    ]


def test_a_retroactive_snapshot_is_not_preferred_over_an_earlier_valid_one(
    world: Stack, tmp_path: Path
) -> None:
    # Snapshot 5 is as of 2026-02-09, the closest to DEMO-EX-01, but it is retroactive.
    result = world.export.export(tmp_path / "out")
    rows = _data(result.readings.path)
    assert "retroactive" not in {r[7] for r in rows}
    assert {r[3] for r in rows if r[0] == "DEMO-EX-01"} == {"2"}
    assert result.recorded_snapshot_ids == ()


def test_the_reason_code_appears_when_no_reading_exists(world: Stack, tmp_path: Path) -> None:
    result = world.export.export(tmp_path / "out")
    rows = _data(result.readings.path)
    assert [r for r in rows if r[0] == "DEMO-EX-00"] == [NO_PRIOR_00]
    assert result.editions_without_reading == ("DEMO-EX-00",)
    assert world.export.editions_without_prior_snapshot() == ["DEMO-EX-00"]


def test_each_row_carries_taken_at_utc_and_age_days(world: Stack, tmp_path: Path) -> None:
    rows = _data(world.export.export(tmp_path / "out").readings.path)
    chosen = [r for r in rows if r[0] == "DEMO-EX-01"]
    assert chosen
    assert {(r[3], r[4], r[5], r[6], r[7]) for r in chosen} == {
        ("2", "2026-02-01", "2026-02-01T12:00:00Z", "9", "manual")
    }


def test_one_row_per_indicator_and_dimension_of_the_chosen_snapshot(
    world: Stack, tmp_path: Path
) -> None:
    rows = _data(world.export.export(tmp_path / "out").readings.path)
    stored = world.snapshots.values(2)
    exported = [(r[INDICATOR], r[DIMENSION]) for r in rows if r[0] == "DEMO-EX-01"]
    assert len(stored) > 3
    assert exported == [(v.indicator_code, v.dimension) for v in stored]


# --------------------------------------------------------------------------- retroactive readings


def test_without_the_request_a_withdrawn_range_gives_the_reason_code(
    world: Stack, tmp_path: Path
) -> None:
    world.snapshots.withdraw(1, "DEMO reason")
    world.snapshots.withdraw(2, "DEMO reason")
    rows = _only(_readings(world, tmp_path / "out"), CERT_CODE)
    assert NO_PRIOR_01 in rows
    assert "retroactive" not in {r[7] for r in rows}
    assert world.export.editions_without_prior_snapshot() == ["DEMO-EX-00", "DEMO-EX-01"]


def test_the_request_uses_an_existing_retroactive_reading_and_records_the_missing_one(
    world: Stack, tmp_path: Path
) -> None:
    world.snapshots.withdraw(1, "DEMO reason")
    world.snapshots.withdraw(2, "DEMO reason")
    result = world.export.export(tmp_path / "out", record_retroactive=True)
    rows = _only(_data(result.readings.path), CERT_CODE)
    # DEMO-EX-01: the existing snapshot 5. DEMO-EX-00: snapshot 6, recorded now for 2025-09-30
    # (all three certificates were already issued then), 155 days AFTER 2025-10-01.
    snap_6 = ("6", "2025-09-30", "2026-03-05T12:00:00Z", "-155", "retroactive")
    assert rows == [
        *_cert_rows("DEMO-EX-00", "CBRAMED", "2025-10-01", snap_6, ["3.0", "OK", *ZERO_BC]),
        *_cert_rows("DEMO-EX-01", "CBRAMED", "2026-02-10", SNAP_5, ["3.0", "OK", *ZERO_BC]),
        *_cert_rows("DEMO-EX-02", "EXBRAMED", "2026-04-01", SNAP_4, ["3.0", "OK", *ZERO_BC]),
    ]
    assert result.recorded_snapshot_ids == (6,)
    assert result.editions_without_reading == ()
    stored = world.snapshots.get(6).snapshot
    assert stored.origin is SnapshotOrigin.RETROACTIVE
    assert stored.as_of == date(2025, 9, 30)


def test_asking_twice_records_nothing_new(world: Stack, tmp_path: Path) -> None:
    first = world.export.export(tmp_path / "a", record_retroactive=True)
    second = world.export.export(tmp_path / "b", record_retroactive=True)
    assert first.recorded_snapshot_ids == (6,)
    assert second.recorded_snapshot_ids == ()
    assert len(world.snapshots.list_snapshots()) == 6
    assert first.readings.path.read_bytes() == second.readings.path.read_bytes()


def test_a_failure_after_recording_names_the_recorded_snapshots(
    world: Stack, tmp_path: Path
) -> None:
    # P8-08: the snapshot id is written into the files, so the snapshot is recorded first; when
    # the files then fail, the error says which snapshots stay recorded.
    out = tmp_path / "out"
    out.mkdir()
    (out / "validation_results_unsuppressed_internal.csv").mkdir()
    with pytest.raises(ValidationExportError) as caught:
        world.export.export(out, record_retroactive=True)
    assert (caught.value.code, caught.value.field) == (EXPORT_FAILED, RESULTS_ENTITY)
    assert caught.value.recorded_snapshot_ids == (6,)
    assert isinstance(caught.value, ServiceError)
    assert len(world.snapshots.list_snapshots()) == 6  # the snapshot stays (never deleted)


def test_a_failure_with_nothing_recorded_is_the_plain_service_error(
    world: Stack, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "validation_results_unsuppressed_internal.csv").mkdir()
    with pytest.raises(ServiceError) as without_request:
        world.export.export(out)
    assert not isinstance(without_request.value, ValidationExportError)

    world.export.export(tmp_path / "first", record_retroactive=True)  # records snapshot 6
    with pytest.raises(ServiceError) as reused:
        world.export.export(out, record_retroactive=True)  # reuses it: nothing new
    assert not isinstance(reused.value, ValidationExportError)
    assert reused.value.code == EXPORT_FAILED


# --------------------------------------------------------------------------- the day boundaries


def _edition(stack: Stack) -> None:
    stack.exercises.create_edition(
        EditionInput(code="DEMO-EX-09", kind="OTHER", start_on="2026-02-10", end_on="2026-02-11")
    )


def test_a_snapshot_taken_on_the_start_day_is_not_a_prior_reading(
    db: DatabaseConnection, tmp_path: Path
) -> None:
    before = _stack(db, _at("2026-02-09"))
    _edition(before)
    before.snapshots.record(date(2026, 2, 9), origin=MANUAL)
    on_day = _stack(db, _at("2026-02-10"))
    on_day.snapshots.record(date(2026, 2, 10), origin=MANUAL)

    rows = _data(on_day.export.export(tmp_path / "out").readings.path)

    assert {(r[3], r[4], r[6]) for r in rows} == {("1", "2026-02-09", "1")}


def test_the_local_date_of_a_west_of_utc_clock_decides_the_pairing(
    db: DatabaseConnection, tmp_path: Path
) -> None:
    # UTC-3: 01:00Z on 10 February is 22:00 on 9 February locally, the day BEFORE the start,
    # although the UTC date is the start day itself.
    stack = _stack(db, FixedClock.at("2026-02-10T01:00:00Z", utc_offset_hours=-3))
    _edition(stack)
    stack.snapshots.record(date(2026, 2, 9), origin=MANUAL)

    rows = _data(stack.export.export(tmp_path / "out").readings.path)

    paired = {(r[3], r[4], r[5], r[6]) for r in rows}
    assert paired == {("1", "2026-02-09", "2026-02-10T01:00:00Z", "1")}


def test_the_local_date_of_an_east_of_utc_clock_decides_the_pairing(
    db: DatabaseConnection, tmp_path: Path
) -> None:
    # UTC+3: 22:00Z on 9 February is 01:00 on 10 February locally, the start day itself,
    # although the UTC date is the day before: the snapshot is not a prior reading.
    stack = _stack(db, FixedClock.at("2026-02-09T22:00:00Z", utc_offset_hours=3))
    _edition(stack)
    stack.snapshots.record(date(2026, 2, 10), origin=MANUAL)

    rows = _data(stack.export.export(tmp_path / "out").readings.path)

    assert rows == [["DEMO-EX-09", "OTHER", "2026-02-10", *[""] * 9, NO_PRIOR_SNAPSHOT]]


def test_a_retroactive_snapshot_of_another_day_is_not_used(world: Stack, tmp_path: Path) -> None:
    # Only the day before start_on counts: for DEMO-EX-00 nothing exists, so one is recorded.
    result = world.export.export(tmp_path / "out", record_retroactive=True)
    assert result.recorded_snapshot_ids == (6,)
    assert {r[3] for r in _data(result.readings.path) if r[0] == "DEMO-EX-00"} == {"6"}


def test_the_day_before_today_is_recorded_as_a_regular_reading(
    db: DatabaseConnection, tmp_path: Path
) -> None:
    stack = _stack(db, _at("2026-03-05"))
    stack.exercises.create_edition(
        EditionInput(code="DEMO-EX-09", kind="OTHER", start_on="2026-03-06", end_on="2026-03-07")
    )
    result = stack.export.export(tmp_path / "out", record_retroactive=True)
    rows = _only(_data(result.readings.path), CERT_CODE)
    snap = ("1", "2026-03-05", "2026-03-05T12:00:00Z", "1", "manual")
    zeros = ["0.0", "NO_TARGET"] * 3
    assert rows == _cert_rows("DEMO-EX-09", "OTHER", "2026-03-06", snap, zeros)
    assert result.recorded_snapshot_ids == (1,)


def test_a_reading_cannot_be_recorded_in_advance(db: DatabaseConnection, tmp_path: Path) -> None:
    stack = _stack(db, _at("2026-03-05"))
    stack.exercises.create_edition(
        EditionInput(code="DEMO-EX-09", kind="OTHER", start_on="2026-04-01", end_on="2026-04-02")
    )
    result = stack.export.export(tmp_path / "out", record_retroactive=True)
    assert _data(result.readings.path) == [
        ["DEMO-EX-09", "OTHER", "2026-04-01", *[""] * 9, NO_PRIOR_SNAPSHOT]
    ]
    assert result.recorded_snapshot_ids == ()
    assert stack.snapshots.list_snapshots(include_withdrawn=True) == []


# --------------------------------------------------------------------------- results file


def test_the_results_file(world: Stack, tmp_path: Path) -> None:
    result = world.export.export(tmp_path / "out")
    assert _data(result.results.path) == [
        ["DEMO-EX-00", "DEMO-M1", "6.0", "3", "0.0", "10.0"],
        ["DEMO-EX-01", "DEMO-M1", "7.5", "12", "0.0", "10.0"],
        ["DEMO-EX-01", "DEMO-M2", "4.0", "", "1.0", "5.0"],
        # A negative number is a number, not a formula: it is not given the guard prefix.
        ["DEMO-EX-01", "DEMO-M3", "-2.5", "", "-5.0", "5.0"],
    ]
    assert result.results.rows == 4
    assert result.results.entity == RESULTS_ENTITY


def test_results_are_not_suppressed(world: Stack, tmp_path: Path) -> None:
    # Respondents (3) are below the default threshold (5), but exercise figures are not suppressed.
    result = world.export.export(tmp_path / "out", suppress_small_counts=True)
    assert _data(result.results.path, SUPPRESSED_BANNER)[0] == [
        "DEMO-EX-00",
        "DEMO-M1",
        "6.0",
        "3",
        "0.0",
        "10.0",
    ]


# --------------------------------------------------------------------------- format and labels


def test_file_names_header_and_bytes(world: Stack, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = world.export.export(out)
    assert sorted(p.name for p in out.iterdir()) == [
        "validation_readings_unsuppressed_internal.csv",
        "validation_results_unsuppressed_internal.csv",
    ]
    assert result.readings.entity == READINGS_ENTITY
    for path in (result.readings.path, result.results.path):
        raw = path.read_bytes()
        assert raw.startswith(BOM + UNSUPPRESSED_BANNER.encode() + b"\r\n")
        assert raw.endswith(b"\r\n")
    raw_readings = result.readings.path.read_bytes()
    header = ";".join(HEADER_READINGS).encode() + b"\r\n"
    assert raw_readings.startswith(BOM + b"UNSUPPRESSED_INTERNAL_DATA\r\n" + header)
    assert result.readings.rows == len(_data(result.readings.path))
    assert readings_spec(suppressed=False).column_codes == tuple(HEADER_READINGS)
    assert results_spec(suppressed=False).column_codes == tuple(HEADER_RESULTS)


def test_the_files_hold_codes_and_numbers_only(world: Stack, tmp_path: Path) -> None:
    result = world.export.export(tmp_path / "out")
    for path in (result.readings.path, result.results.path):
        text = path.read_bytes().decode("utf-8-sig")
        for secret in (
            "DEMO-P00",  # staff identifiers
            "DEMO-TITLE-SECRET",
            "DEMO-NOTE-SECRET",
            "DEMO-RESULT-NOTE",
            "DEMO-SNAP-NOTE",
            OPERATOR,
            "Metrica",
        ):
            assert secret not in text


def test_dates_are_iso_and_numbers_use_a_point(world: Stack, tmp_path: Path) -> None:
    rows = _data(world.export.export(tmp_path / "out").readings.path)
    for row in rows:
        assert len(row) == 13
        assert row[2].count("-") == 2
        if row[VALUE]:
            assert "," not in row[VALUE]
    assert any("." in r[VALUE] for r in rows)


def test_the_export_writes_nothing_to_the_database(world: Stack, tmp_path: Path) -> None:
    before = [
        int(world.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in ("change_log", "readiness_snapshot", "readiness_snapshot_value")
    ]
    world.export.export(tmp_path / "out")
    world.export.export(tmp_path / "out2", suppress_small_counts=True)
    after = [
        int(world.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in ("change_log", "readiness_snapshot", "readiness_snapshot_value")
    ]
    assert after == before


def test_an_empty_database_gives_banner_and_header_only(
    db: DatabaseConnection, tmp_path: Path
) -> None:
    stack = _stack(db, _at("2026-03-05"))
    result = stack.export.export(tmp_path / "out")
    assert result.readings.rows == 0
    assert result.results.rows == 0
    assert result.editions_without_reading == ()
    assert result.readings.path.read_bytes() == (
        BOM + b"UNSUPPRESSED_INTERNAL_DATA\r\n" + ";".join(HEADER_READINGS).encode() + b"\r\n"
    )
    assert result.results.path.read_bytes() == (
        BOM + b"UNSUPPRESSED_INTERNAL_DATA\r\n" + ";".join(HEADER_RESULTS).encode() + b"\r\n"
    )


def test_formula_injection_is_escaped_in_the_code_columns(tmp_path: Path) -> None:
    path = tmp_path / "guard.csv"
    row = {
        "edition_code": "=1+1",
        "kind": "@x",
        "start_on": date(2026, 2, 10),
        "indicator_code": "+x",
        "dimension": "-x",
        "reason_code": "\tx",
    }
    csv_io.write_entity(path, readings_spec(suppressed=False), [row], banner=UNSUPPRESSED_BANNER)
    cells = _table(path)[2]
    assert cells[:3] == ["'=1+1", "'@x", "2026-02-10"]
    assert cells[INDICATOR : DIMENSION + 1] == ["'+x", "'-x"]
    assert cells[12] == "'\tx"


# --------------------------------------------------------------------------- suppression (A11)


def test_suppression_replaces_small_personnel_counts(world: Stack, tmp_path: Path) -> None:
    rows = _readings(world, tmp_path / "out", suppress_small_counts=True)
    chosen = [r for r in rows if r[0] == "DEMO-EX-01" and r[INDICATOR] == CERT_CODE]
    # The default threshold is 5: the counts 2, 0 and 0 are replaced, and their status with them.
    assert [(r[DIMENSION], r[VALUE], r[STATUS]) for r in chosen] == [
        ("level=A", "< 5", "NO_DATA"),
        ("level=B", "< 5", "NO_DATA"),
        ("level=C", "< 5", "NO_DATA"),
    ]
    personnel = [r for r in rows if r[INDICATOR].startswith("PERS_")]
    assert personnel
    assert {r[VALUE] for r in personnel} == {"< 5"}


def test_suppression_does_not_touch_exercise_figures(world: Stack, tmp_path: Path) -> None:
    rows = _readings(world, tmp_path / "out", suppress_small_counts=True)
    # Snapshot 2 sees DEMO-EX-00 (one participant) as the latest finished CBRAMED edition: 1 < 5,
    # but an exercise figure is not personnel-derived.
    cbramed = [
        r
        for r in rows
        if r[0] == "DEMO-EX-01" and (r[INDICATOR], r[DIMENSION]) == (PARTICIPANTS_CODE, CBRAMED_DIM)
    ]
    assert [(r[VALUE], r[STATUS]) for r in cbramed] == [("1.0", "NO_TARGET")]


def test_the_threshold_comes_from_the_configuration(world: Stack, tmp_path: Path) -> None:
    save_config(
        WriteContext(world.conn, _at("2026-03-05"), OPERATOR),
        load_config(world.conn).with_changes(small_count_threshold=2),
    )
    rows = _readings(world, tmp_path / "out", suppress_small_counts=True)
    chosen = [r for r in rows if r[0] == "DEMO-EX-01" and r[INDICATOR] == CERT_CODE]
    # A = 2 is not below 2 and stays; the zeros are replaced.
    assert [(r[DIMENSION], r[VALUE], r[STATUS]) for r in chosen] == [
        ("level=A", "2.0", "WARNING"),
        ("level=B", "< 2", "NO_DATA"),
        ("level=C", "< 2", "NO_DATA"),
    ]


def test_suppressed_files_say_so_in_name_and_banner(world: Stack, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = world.export.export(out, suppress_small_counts=True)
    assert sorted(p.name for p in out.iterdir()) == [
        "validation_readings_suppressed_internal.csv",
        "validation_results_suppressed_internal.csv",
    ]
    assert _table(result.readings.path)[0] == ["SUPPRESSED_INTERNAL_DATA"]
    assert _table(result.results.path)[0] == ["SUPPRESSED_INTERNAL_DATA"]


def test_unsuppressed_counts_are_exact(world: Stack, tmp_path: Path) -> None:
    rows = _readings(world, tmp_path / "out")
    assert not any(r[VALUE].startswith("<") for r in rows)


# --------------------------------------------------------------------------- determinism, order


def test_two_runs_give_identical_bytes(world: Stack, tmp_path: Path) -> None:
    first = world.export.export(tmp_path / "a")
    second = world.export.export(tmp_path / "b")
    again = world.export.export(tmp_path / "a")
    assert first.readings.path.read_bytes() == second.readings.path.read_bytes()
    assert first.results.path.read_bytes() == second.results.path.read_bytes()
    assert again.readings.path.read_bytes() == first.readings.path.read_bytes()


def test_row_order_is_by_edition_indicator_and_dimension(world: Stack, tmp_path: Path) -> None:
    rows = _data(world.export.export(tmp_path / "out").readings.path)
    keys = [(r[0], r[INDICATOR], r[DIMENSION]) for r in rows]
    assert keys == sorted(keys)
    assert rows[0][0] == "DEMO-EX-00"
    assert rows[-1][0] == "DEMO-EX-02"


# --------------------------------------------------------------------------- demo and real names


def test_demo_database_file_names_start_with_demo(tmp_path: Path) -> None:
    conn = open_and_migrate(
        tmp_path / "demo.sqlite3",
        data_dir=tmp_path,
        identity=DatabaseIdentity.DEMO,
        backup=False,
    )
    try:
        app_meta.initialise(conn, is_demo=True, created_with="test")
        stack = _stack(conn, _at("2026-03-05"))
        out = tmp_path / "demo_out"
        stack.export.export(out)
        stack.export.export(out, suppress_small_counts=True)
    finally:
        conn.close()
    assert sorted(p.name for p in out.iterdir()) == [
        "DEMO-validation_readings_suppressed_internal.csv",
        "DEMO-validation_readings_unsuppressed_internal.csv",
        "DEMO-validation_results_suppressed_internal.csv",
        "DEMO-validation_results_unsuppressed_internal.csv",
    ]


def test_real_database_file_names_do_not_start_with_demo(world: Stack, tmp_path: Path) -> None:
    world.export.export(tmp_path / "out")
    assert not any(p.name.startswith("DEMO-") for p in (tmp_path / "out").iterdir())


# --------------------------------------------------------------------------- failures


def test_a_target_that_is_not_a_folder_fails_with_a_coded_error(
    world: Stack, tmp_path: Path
) -> None:
    target = tmp_path / "not_a_folder"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(ServiceError) as caught:
        world.export.export(target)
    assert caught.value.code == EXPORT_FAILED
    assert caught.value.field == "out_dir"
    assert target.read_text(encoding="utf-8") == "x"


def test_a_failing_second_file_leaves_no_partial_file(world: Stack, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    # A folder where the results file must go: the rename fails after the readings file is done.
    (out / "validation_results_unsuppressed_internal.csv").mkdir()
    with pytest.raises(ServiceError) as caught:
        world.export.export(out)
    assert caught.value.code == EXPORT_FAILED
    assert caught.value.field == RESULTS_ENTITY
    assert sorted(p.name for p in out.iterdir()) == ["validation_results_unsuppressed_internal.csv"]


def test_a_failing_first_file_leaves_no_temporary_file(world: Stack, tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "validation_readings_unsuppressed_internal.csv").mkdir()
    with pytest.raises(ServiceError) as caught:
        world.export.export(out)
    assert (caught.value.code, caught.value.field) == (EXPORT_FAILED, READINGS_ENTITY)
    assert not any(p.name.endswith(".part") for p in out.iterdir())
    assert not (out / "validation_results_unsuppressed_internal.csv").exists()


def test_a_value_that_cannot_be_written_is_a_coded_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    spec = results_spec(suppressed=False)
    with pytest.raises(csv_io.CsvFormatError):
        csv_io.write_entity(path, spec, [{"edition_code": "A", "metric_code": "B", "value": "x"}])
    assert not path.exists()
    assert not any(tmp_path.iterdir())


# --------------------------------------------------------------------------- read-only


def test_a_read_only_connection_can_export(
    world: Stack, read_only_db: DatabaseConnection, tmp_path: Path
) -> None:
    assert read_only_db.read_only
    expected = world.export.export(tmp_path / "rw")
    reader = _stack(read_only_db, _at("2026-03-05"))
    result = reader.export.export(tmp_path / "ro", suppress_small_counts=True)
    plain = reader.export.export(tmp_path / "ro_plain")
    assert plain.readings.path.read_bytes() == expected.readings.path.read_bytes()
    assert plain.results.path.read_bytes() == expected.results.path.read_bytes()
    assert result.readings.rows == expected.readings.rows


def test_the_retroactive_request_needs_a_writable_connection(
    world: Stack, read_only_db: DatabaseConnection, tmp_path: Path
) -> None:
    reader = _stack(read_only_db, _at("2026-03-05"))
    out = tmp_path / "ro_out"
    with pytest.raises(ServiceError) as caught:
        reader.export.export(out, record_retroactive=True)
    assert caught.value.code == READ_ONLY
    assert not out.exists()
    assert len(world.snapshots.list_snapshots()) == 5


# --------------------------------------------------------------------------- csv_io additions


def test_a_suppressed_count_is_written_as_less_than_the_threshold(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    base = {"kind": "OTHER", "start_on": "2026-01-01"}
    csv_io.write_entity(
        path,
        readings_spec(suppressed=True),
        [
            {**base, "edition_code": "A", "value": BelowThreshold(5)},
            {**base, "edition_code": "B", "value": 0.0},
        ],
        banner=SUPPRESSED_BANNER,
    )
    assert [r[VALUE] for r in _table(path)[2:]] == ["< 5", "0.0"]


def test_without_a_banner_the_module_export_format_is_unchanged(tmp_path: Path) -> None:
    spec = results_spec(suppressed=False)
    plain = tmp_path / "plain.csv"
    labelled = tmp_path / "labelled.csv"
    csv_io.write_entity(plain, spec, [])
    csv_io.write_entity(labelled, spec, [], banner="LABEL")
    header = ";".join(HEADER_RESULTS).encode() + b"\r\n"
    assert plain.read_bytes() == BOM + header
    assert labelled.read_bytes() == BOM + b"LABEL\r\n" + header
