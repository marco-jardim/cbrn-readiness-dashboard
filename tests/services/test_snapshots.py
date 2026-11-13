# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the snapshot service (PLAN.md T8.1, D13, D21, P04, K13, R31).

All data is fictitious and is created through the module services.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest

from cbrn_dashboard import __version__
from cbrn_dashboard.clock import Clock, FixedClock
from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.domain.infrastructure import AssetStatus
from cbrn_dashboard.services import snapshots as snapshots_module
from cbrn_dashboard.services.budget import BudgetService, EntryInput
from cbrn_dashboard.services.errors import INVALID_DATE, NOT_FOUND, READ_ONLY, ServiceError
from cbrn_dashboard.services.exercises import EditionInput, ExercisesService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import (
    AssetInput,
    AssetTypeInput,
    InfrastructureService,
)
from cbrn_dashboard.services.personnel import (
    CertificateInput,
    CourseInput,
    PersonnelService,
    StaffInput,
    TrainingInput,
)
from cbrn_dashboard.services.snapshots import (
    ALREADY_WITHDRAWN,
    AS_OF_IN_FUTURE,
    HASHED_FIELDS,
    ORIGIN_NOT_ALLOWED,
    REASON_REQUIRED,
    SnapshotOrigin,
    SnapshotService,
    SnapshotView,
    monthly_snapshot_startup,
)
from cbrn_dashboard.storage import snapshots_repo
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import load_config, save_config
from tests.services.conftest import ChangeLogRows

OPERATOR = "op-demo"
AS_OF = date(2026, 3, 5)  # the date of the fixture clock
PAST = date(2026, 2, 1)
CERT_A = "PERS_CERT_VALID"
LEVEL_A = "level=A"
MAINT = "INFRA_MAINT_OVERDUE"
TYPE_DIM = "type=DEMO-TYPE"
BUDGET = "BUD_EXEC_RATE"
BUDGET_DIM = "currency=BRL;source=DIRSA"
INTERVALS = "asset_type_default_maintenance_interval_days"

#: The fields the hash covers, written out here on purpose (the contract of T8.1).
EXPECTED_KEYS = {
    "cert_warning_days",
    "maintenance_warning_days",
    "targets",
    "snapshot_monthly",
    "snapshot_on_report",
    "budget_prorate_target",
    "ppe_hierarchy_enabled",
    "ppe_hierarchy",
    "ppe_validity_months",
    "degraded_counts_as_available",
    INTERVALS,
}

MANUAL = SnapshotOrigin.MANUAL
MONTHLY = SnapshotOrigin.MONTHLY
REPORT = SnapshotOrigin.REPORT
RETROACTIVE = SnapshotOrigin.RETROACTIVE


@dataclass
class Stack:
    """The module services, the indicator service and the snapshot service over one connection."""

    personnel: PersonnelService
    infrastructure: InfrastructureService
    exercises: ExercisesService
    budget: BudgetService
    indicators: IndicatorService
    snapshots: SnapshotService


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
    return Stack(personnel, infrastructure, exercises, budget, indicators, snapshots)


def _seed(stack: Stack, conn: DatabaseConnection) -> None:
    people = stack.personnel
    first = people.create_staff(StaffInput("DEMO-P001", "2020-01-01"))
    second = people.create_staff(StaffInput("DEMO-P002", "2020-01-01"))
    third = people.create_staff(StaffInput("DEMO-P003", "2021-01-01"))
    people.add_certificate(first, CertificateInput("A", "2025-01-10", "2027-01-10"))
    people.add_certificate(second, CertificateInput("A", "2025-02-10", "2027-02-10"))
    people.add_certificate(second, CertificateInput("B", "2025-02-10", "2027-02-10"))
    people.add_certificate(third, CertificateInput("A", "2024-03-20", "2026-03-20"))
    course = people.create_course(CourseInput("DEMO-C1", "Curso Demo"))
    people.add_training(first, TrainingInput(course, "2026-01-10", 8))

    infra = stack.infrastructure
    type_id = infra.create_type(AssetTypeInput("DEMO-TYPE", "Tipo demo"))
    for tag in ("DEMO-A001", "DEMO-A002", "DEMO-A003"):
        asset = infra.create_asset(
            AssetInput(tag=tag, type_id=type_id, in_service_from="2025-01-01"),
            AssetStatus.OPERATIONAL,
        )
        if tag == "DEMO-A002":
            infra.change_status(asset, "2026-01-10", AssetStatus.DEGRADED)
        if tag == "DEMO-A003":
            infra.change_status(asset, "2026-01-10", AssetStatus.OUT_OF_SERVICE)

    stack.exercises.create_edition(
        EditionInput(
            code="DEMO-EX-01",
            kind="CBRAMED",
            start_on="2024-03-01",
            end_on="2024-03-05",
            participants=40,
            countries=("BR", "AR", "PT"),
        )
    )

    source = conn.execute("SELECT id FROM funding_source WHERE code = 'DIRSA'").fetchone()
    entry = stack.budget.create_entry(
        EntryInput(
            fiscal_year=2026, source_id=int(source[0]), allocated_minor=100_000, currency="BRL"
        )
    )
    stack.budget.add_execution(entry, "2026-01-10", 50_000)

    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=2, critical_value=1)
    stack.indicators.set_target(BUDGET, BUDGET_DIM, warning_value=0.9, critical_value=0.6)


@pytest.fixture
def stack(db: DatabaseConnection, clock: FixedClock) -> Stack:
    """The services over a database with a small fictitious dataset and two targets."""
    built = _stack(db, clock)
    _seed(built, db)
    return built


def _code(call: Callable[[], object]) -> str:
    """The code of the ServiceError that ``call`` raises."""
    with pytest.raises(ServiceError) as caught:
        call()
    return caught.value.code


def _count(db: DatabaseConnection, table: str) -> int:
    assert table in {"readiness_snapshot", "readiness_snapshot_value", "snapshot_withdrawal"}
    return int(db.execute(f"SELECT count(*) FROM {table}").fetchone()[0])


def _counts(db: DatabaseConnection) -> list[int]:
    tables = ("readiness_snapshot", "readiness_snapshot_value", "snapshot_withdrawal")
    return [_count(db, table) for table in tables]


def _key(row: dict[str, object]) -> dict[str, Any]:
    key = json.loads(str(row["entity_key"]))
    assert isinstance(key, dict)
    return key


def _stored_origin(db: DatabaseConnection, snapshot_id: int) -> str:
    row = db.execute("SELECT origin FROM readiness_snapshot WHERE id = ?", (snapshot_id,))
    return str(row.fetchone()[0])


# --------------------------------------------------------------------------- what is stored


def test_one_value_row_per_reading_with_status_and_targets(
    stack: Stack, db: DatabaseConnection
) -> None:
    readings = stack.indicators.evaluate(AS_OF)
    view = stack.snapshots.record(AS_OF, origin=MANUAL)
    stored = stack.snapshots.values(view.id)

    assert len(readings) > 1
    assert len(stored) == len(readings)
    assert _count(db, "readiness_snapshot_value") == len(readings)
    expected = {
        (r.code, r.dimension): (r.value, r.status, r.warning_value, r.critical_value)
        for r in readings
    }
    actual = {
        (v.indicator_code, v.dimension): (v.value, v.status, v.warning_value, v.critical_value)
        for v in stored
    }
    assert len(actual) == len(stored)  # one row per (code, dimension)
    assert actual == expected
    # The targets in force are stored: the plain one, the pro-rated budget one, and "no target".
    cert = next(v for v in stored if (v.indicator_code, v.dimension) == (CERT_A, LEVEL_A))
    assert (cert.warning_value, cert.critical_value) == (2.0, 1.0)
    budget = next(v for v in stored if (v.indicator_code, v.dimension) == (BUDGET, BUDGET_DIM))
    assert budget.warning_value is not None
    assert budget.warning_value < 0.9
    assert any(v.status is IndicatorStatus.NO_TARGET and v.warning_value is None for v in stored)


def test_header_holds_version_hash_and_configuration(stack: Stack) -> None:
    view = stack.snapshots.record(AS_OF, origin=MANUAL, note="first reading")
    detail = stack.snapshots.get(view.id)
    assert detail.snapshot == view
    assert view.app_version == __version__
    assert view.taken_at_utc == "2026-03-05T12:00:00Z"
    assert view.as_of == AS_OF
    assert view.note == "first reading"
    assert not view.withdrawn
    assert hashlib.sha256(detail.config_json.encode()).hexdigest() == view.config_hash
    assert detail.values == tuple(stack.snapshots.values(view.id))


def test_app_version_can_be_given(db: DatabaseConnection, clock: FixedClock) -> None:
    built = _stack(db, clock)
    other = SnapshotService(
        db,
        clock,
        indicators=built.indicators,
        infrastructure=built.infrastructure,
        app_version="9.9.9",
    )
    assert other.record(AS_OF, origin=MANUAL).app_version == "9.9.9"


def test_config_json_holds_exactly_the_hashed_fields(stack: Stack) -> None:
    view = stack.snapshots.record(AS_OF, origin=MANUAL)
    text = stack.snapshots.get(view.id).config_json
    structure = json.loads(text)
    assert set(structure) == EXPECTED_KEYS
    assert set(HASHED_FIELDS) == EXPECTED_KEYS
    assert hashlib.sha256(text.encode()).hexdigest() == view.config_hash
    # Canonical text: sorted keys, compact separators, ASCII only.
    assert text == json.dumps(structure, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert text.isascii()
    # The documented content: defaults of P01/P02/P04/P08/A05, the stored targets, A06 intervals.
    assert structure["cert_warning_days"] == 90
    assert structure["maintenance_warning_days"] == 30
    assert structure["snapshot_monthly"] is True
    assert structure["snapshot_on_report"] is True
    assert structure["budget_prorate_target"] is True
    assert structure["ppe_hierarchy_enabled"] is False
    assert structure["ppe_hierarchy"] == {}
    assert structure["ppe_validity_months"] == {"A": None, "B": None, "C": None}
    assert structure["degraded_counts_as_available"] is False
    assert [(t["indicator_code"], t["dimension"]) for t in structure["targets"]] == [
        (BUDGET, BUDGET_DIM),
        (CERT_A, LEVEL_A),
    ]
    assert structure["targets"][1] == {
        "indicator_code": CERT_A,
        "dimension": LEVEL_A,
        "warning_value": 2.0,
        "critical_value": 1.0,
        "enabled": True,
    }
    assert structure[INTERVALS]["DEMO-TYPE"] is None


def test_inactive_asset_types_are_part_of_the_configuration(stack: Stack) -> None:
    type_id = stack.infrastructure.create_type(
        AssetTypeInput("DEMO-OLD", "Tipo antigo", default_maintenance_interval_days=90)
    )
    stack.infrastructure.deactivate_type(type_id)
    view = stack.snapshots.record(AS_OF, origin=MANUAL)
    assert json.loads(stack.snapshots.get(view.id).config_json)[INTERVALS]["DEMO-OLD"] == 90


def test_the_hash_is_stable_when_nothing_changes(stack: Stack) -> None:
    first = stack.snapshots.record(AS_OF, origin=MANUAL)
    second = stack.snapshots.record(AS_OF, origin=MANUAL)
    assert first.id != second.id
    assert first.config_hash == second.config_hash
    assert stack.snapshots.get(first.id).config_json == stack.snapshots.get(second.id).config_json


# --------------------------------------------------------------------------- the hash

type Mutator = Callable[[Stack, DatabaseConnection, FixedClock], None]


def _config(**changes: Any) -> Mutator:
    def apply(stack: Stack, conn: DatabaseConnection, clock: FixedClock) -> None:
        current = load_config(conn)
        save_config(WriteContext(conn, clock, OPERATOR), current.with_changes(**changes))

    return apply


def _type_id(stack: Stack, code: str = "DEMO-TYPE") -> int:
    types = stack.infrastructure.list_types(include_inactive=True)
    return next(t.id for t in types if t.code == code)


def _set_target(code: str, dimension: str, warning: float, critical: float) -> Mutator:
    def apply(stack: Stack, conn: DatabaseConnection, clock: FixedClock) -> None:
        stack.indicators.set_target(code, dimension, warning_value=warning, critical_value=critical)

    return apply


def _disable_target(stack: Stack, conn: DatabaseConnection, clock: FixedClock) -> None:
    stack.indicators.set_target_enabled(CERT_A, LEVEL_A, False)


def _delete_target(stack: Stack, conn: DatabaseConnection, clock: FixedClock) -> None:
    stack.indicators.delete_target(CERT_A, LEVEL_A)


def _interval(days: int) -> Mutator:
    def apply(stack: Stack, conn: DatabaseConnection, clock: FixedClock) -> None:
        stack.infrastructure.update_type(
            _type_id(stack),
            AssetTypeInput("DEMO-TYPE", "Tipo demo", default_maintenance_interval_days=days),
        )

    return apply


def _new_type(stack: Stack, conn: DatabaseConnection, clock: FixedClock) -> None:
    stack.infrastructure.create_type(AssetTypeInput("DEMO-NEW", "Tipo novo"))


HASHED_CHANGES = [
    pytest.param(_config(cert_warning_days=60), id="P01-cert-warning-days"),
    pytest.param(_config(maintenance_warning_days=15), id="P02-maintenance-warning-days"),
    pytest.param(_set_target(CERT_A, LEVEL_A, 3, 1), id="P03-target-warning-value"),
    pytest.param(_set_target(CERT_A, LEVEL_A, 2, 0), id="P03-target-critical-value"),
    pytest.param(_disable_target, id="P03-target-enabled-flag"),
    pytest.param(_set_target(MAINT, TYPE_DIM, 1, 3), id="P03-target-added"),
    pytest.param(_delete_target, id="P03-target-removed"),
    pytest.param(_config(snapshot_monthly=False), id="P04-snapshot-monthly"),
    pytest.param(_config(snapshot_on_report=False), id="P04-snapshot-on-report"),
    pytest.param(_config(budget_prorate_target=False), id="P08-budget-prorate-target"),
    pytest.param(_config(ppe_hierarchy_enabled=True), id="A02-hierarchy-switch"),
    pytest.param(_config(ppe_hierarchy={"A": ("B",)}), id="A02-hierarchy-mapping"),
    pytest.param(
        _config(ppe_validity_months={"A": 12, "B": None, "C": None}), id="A04-validity-months"
    ),
    pytest.param(_config(degraded_counts_as_available=True), id="A05-degraded-counts"),
    pytest.param(_interval(180), id="A06-default-interval-changed"),
    pytest.param(_new_type, id="A06-asset-type-added"),
]

UNHASHED_CHANGES = [
    pytest.param(_config(operator_label="someone"), id="operator-label"),
    pytest.param(_config(institution_name="Demo Institution"), id="institution-name"),
    pytest.param(_config(unit_name="Demo Unit"), id="unit-name"),
    pytest.param(_config(report_handling_notice="Handle with care"), id="handling-notice"),
    pytest.param(_config(min_passphrase_length=20), id="P05-passphrase-length"),
    pytest.param(_config(daily_backups_kept=10), id="P06-daily-backups"),
    pytest.param(_config(backup_reminder_days=45), id="P09-backup-reminder"),
    pytest.param(_config(default_currency="USD"), id="default-currency"),
    pytest.param(_config(small_count_threshold=9), id="small-count-threshold"),
]


@pytest.mark.parametrize("mutate", HASHED_CHANGES)
def test_the_hash_changes_with_each_hashed_field(
    stack: Stack, db: DatabaseConnection, clock: FixedClock, mutate: Mutator
) -> None:
    before = stack.snapshots.record(AS_OF, origin=MANUAL)
    mutate(stack, db, clock)
    after = stack.snapshots.record(AS_OF, origin=MANUAL)
    assert after.config_hash != before.config_hash
    text = stack.snapshots.get(after.id).config_json
    assert hashlib.sha256(text.encode()).hexdigest() == after.config_hash
    assert text != stack.snapshots.get(before.id).config_json


@pytest.mark.parametrize("mutate", UNHASHED_CHANGES)
def test_the_hash_ignores_every_other_setting(
    stack: Stack, db: DatabaseConnection, clock: FixedClock, mutate: Mutator
) -> None:
    before = stack.snapshots.record(AS_OF, origin=MANUAL)
    mutate(stack, db, clock)
    after = stack.snapshots.record(AS_OF, origin=MANUAL)
    assert after.config_hash == before.config_hash
    assert stack.snapshots.get(after.id).config_json == stack.snapshots.get(before.id).config_json


def test_deactivating_a_type_does_not_change_the_hash(stack: Stack) -> None:
    before = stack.snapshots.record(AS_OF, origin=MANUAL)
    stack.infrastructure.deactivate_type(_type_id(stack))
    assert stack.snapshots.record(AS_OF, origin=MANUAL).config_hash == before.config_hash


# --------------------------------------------------------------------------- origin (K13)


@pytest.mark.parametrize("origin", [MANUAL, MONTHLY, REPORT])
def test_a_snapshot_for_today_keeps_its_origin(
    stack: Stack, db: DatabaseConnection, origin: SnapshotOrigin
) -> None:
    view = stack.snapshots.record(AS_OF, origin=origin)
    assert view.origin is origin
    assert _stored_origin(db, view.id) == origin.value


@pytest.mark.parametrize("origin", [MANUAL, MONTHLY, REPORT, RETROACTIVE])
def test_a_snapshot_for_a_past_date_is_retroactive_whatever_was_asked(
    stack: Stack, db: DatabaseConnection, origin: SnapshotOrigin
) -> None:
    view = stack.snapshots.record(PAST, origin=origin)
    assert view.origin is RETROACTIVE
    assert view.as_of == PAST
    assert _stored_origin(db, view.id) == "retroactive"


def test_retroactive_cannot_be_claimed_for_today(stack: Stack, db: DatabaseConnection) -> None:
    assert _code(lambda: stack.snapshots.record(AS_OF, origin=RETROACTIVE)) == ORIGIN_NOT_ALLOWED
    assert _count(db, "readiness_snapshot") == 0


def test_an_unknown_origin_or_date_is_refused(stack: Stack, db: DatabaseConnection) -> None:
    bogus: Any = "auto"
    assert _code(lambda: stack.snapshots.record(AS_OF, origin=bogus)) == ORIGIN_NOT_ALLOWED
    text: Any = "2026-03-05"
    assert _code(lambda: stack.snapshots.record(text, origin=MANUAL)) == INVALID_DATE
    assert _count(db, "readiness_snapshot") == 0


@pytest.mark.parametrize("origin", [MANUAL, MONTHLY, REPORT, RETROACTIVE])
def test_a_future_as_of_is_refused(
    stack: Stack, db: DatabaseConnection, origin: SnapshotOrigin
) -> None:
    tomorrow = AS_OF + timedelta(days=1)
    assert _code(lambda: stack.snapshots.record(tomorrow, origin=origin)) == AS_OF_IN_FUTURE
    assert _count(db, "readiness_snapshot") == 0


def test_the_local_date_decides_not_the_utc_date(db: DatabaseConnection) -> None:
    # 01:00 UTC on 6 March is still 5 March at UTC-3.
    clock = FixedClock.at("2026-03-06T01:00:00Z", utc_offset_hours=-3)
    built = _stack(db, clock)
    assert built.snapshots.record(date(2026, 3, 5), origin=MANUAL).origin is MANUAL
    assert built.snapshots.record(date(2026, 3, 4), origin=MANUAL).origin is RETROACTIVE
    future = date(2026, 3, 6)
    assert _code(lambda: built.snapshots.record(future, origin=MANUAL)) == AS_OF_IN_FUTURE


# --------------------------------------------------------------------------- monthly (P04)


def _starts(db: DatabaseConnection, *instants: str, offset: float = 0) -> list[bool]:
    """One program start per instant: fresh services, ``record_monthly_if_due``; True if taken."""
    taken: list[bool] = []
    for instant in instants:
        built = _stack(db, FixedClock.at(instant, utc_offset_hours=offset))
        taken.append(built.snapshots.record_monthly_if_due() is not None)
    return taken


def _monthly(stack: Stack, *, include_withdrawn: bool = False) -> list[SnapshotView]:
    return [
        v
        for v in stack.snapshots.list_snapshots(include_withdrawn=include_withdrawn)
        if v.origin is MONTHLY
    ]


def test_several_starts_in_one_month_make_exactly_one_snapshot(
    db: DatabaseConnection, clock: FixedClock
) -> None:
    taken = _starts(
        db,
        "2026-03-05T12:00:00Z",
        "2026-03-05T12:00:00Z",
        "2026-03-05T18:30:00Z",
        "2026-03-20T09:00:00Z",
        "2026-03-31T20:00:00Z",
    )
    assert taken == [True, False, False, False, False]
    view = _monthly(_stack(db, clock))[0]
    assert view.as_of == date(2026, 3, 5)
    assert view.taken_at_utc == "2026-03-05T12:00:00Z"
    assert _count(db, "readiness_snapshot") == 1


def test_the_next_month_makes_another(db: DatabaseConnection, clock: FixedClock) -> None:
    taken = _starts(db, "2026-03-05T12:00:00Z", "2026-04-02T12:00:00Z", "2026-04-20T12:00:00Z")
    assert taken == [True, True, False]
    assert [v.as_of for v in _monthly(_stack(db, clock))] == [date(2026, 4, 2), date(2026, 3, 5)]


def test_the_same_month_of_another_year_is_another_month(db: DatabaseConnection) -> None:
    assert _starts(db, "2026-03-05T12:00:00Z", "2027-03-05T12:00:00Z") == [True, True]


def test_with_the_monthly_switch_off_none_is_taken(
    stack: Stack, db: DatabaseConnection, clock: FixedClock
) -> None:
    _config(snapshot_monthly=False)(stack, db, clock)
    assert not stack.snapshots.monthly_due()
    assert stack.snapshots.record_monthly_if_due() is None
    assert _count(db, "readiness_snapshot") == 0


def test_a_withdrawn_monthly_snapshot_does_not_count(stack: Stack) -> None:
    first = stack.snapshots.record_monthly_if_due()
    assert first is not None
    assert not stack.snapshots.monthly_due()
    stack.snapshots.withdraw(first.id, "recorded with incomplete data")
    assert stack.snapshots.monthly_due()
    second = stack.snapshots.record_monthly_if_due()
    assert second is not None
    assert second.id != first.id
    assert [v.id for v in _monthly(stack)] == [second.id]
    assert [v.id for v in _monthly(stack, include_withdrawn=True)] == [second.id, first.id]
    assert stack.snapshots.record_monthly_if_due() is None


def test_other_snapshots_do_not_count_as_the_monthly_one(stack: Stack) -> None:
    stack.snapshots.record(AS_OF, origin=MANUAL)
    stack.snapshots.record(AS_OF, origin=REPORT)
    stack.snapshots.record(PAST, origin=MONTHLY)  # retroactive: not a monthly snapshot
    assert stack.snapshots.monthly_due()
    assert stack.snapshots.record_monthly_if_due() is not None


def test_the_local_month_is_what_counts(db: DatabaseConnection) -> None:
    # UTC-3. 01:00Z on 1 April is 22:00 on 31 March locally: the March snapshot. Still March at
    # 02:00Z (23:00 local), but 03:30Z is 00:30 on 1 April locally, which is a new month.
    taken = _starts(
        db,
        "2026-04-01T01:00:00Z",
        "2026-04-01T02:00:00Z",
        "2026-04-01T03:30:00Z",
        "2026-04-01T04:00:00Z",
        offset=-3,
    )
    assert taken == [True, False, True, False]
    clock = FixedClock.at("2026-04-02T12:00:00Z", utc_offset_hours=-3)
    assert [v.as_of for v in _monthly(_stack(db, clock))] == [date(2026, 4, 1), date(2026, 3, 31)]


def test_the_local_month_also_counts_east_of_utc(db: DatabaseConnection) -> None:
    # UTC+3. 20:00Z on 31 March is 23:00 local (March), 22:00Z is 01:00 on 1 April local (April):
    # two months locally although both instants are in March in UTC.
    taken = _starts(db, "2026-03-31T20:00:00Z", "2026-03-31T22:00:00Z", offset=3)
    assert taken == [True, True]


# --------------------------------------------------------------------------- never deleted


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE readiness_snapshot SET note = 'x'",
        "DELETE FROM readiness_snapshot",
        "UPDATE readiness_snapshot_value SET status = 'OK'",
        "DELETE FROM readiness_snapshot_value",
        "UPDATE snapshot_withdrawal SET reason = 'x'",
        "DELETE FROM snapshot_withdrawal",
    ],
)
def test_update_and_delete_raise_and_leave_the_rows(
    stack: Stack, db: DatabaseConnection, statement: str
) -> None:
    view = stack.snapshots.record(AS_OF, origin=MANUAL)
    stack.snapshots.withdraw(view.id, "wrong date")
    counts = _counts(db)
    assert counts[0] == 1
    assert counts[1] > 0
    assert counts[2] == 1
    with pytest.raises(sqlite3.DatabaseError):
        db.execute(statement)
    assert _counts(db) == counts
    assert stack.snapshots.get(view.id).snapshot.withdrawn_at_utc is not None


def test_there_is_no_delete_or_update_path() -> None:
    forbidden = ("delete", "remove", "update", "purge", "clear", "edit", "replace")
    names = [name for name in dir(SnapshotService) if not name.startswith("_")]
    names += snapshots_repo.__all__
    names += snapshots_module.__all__
    assert [n for n in names if any(word in n.lower() for word in forbidden)] == []


def test_a_failed_recording_leaves_nothing_behind(
    stack: Stack,
    db: DatabaseConnection,
    change_log_rows: ChangeLogRows,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError

    monkeypatch.setattr(snapshots_repo, "insert_values", boom)
    with pytest.raises(RuntimeError):
        stack.snapshots.record(AS_OF, origin=MANUAL)
    assert _count(db, "readiness_snapshot") == 0
    assert not [r for r in change_log_rows(db) if str(r["entity"]).startswith("readiness_snapshot")]


# --------------------------------------------------------------------------- withdrawing


def test_withdrawing_appends_a_row_and_keeps_the_snapshot(
    stack: Stack, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    keep = stack.snapshots.record(AS_OF, origin=MANUAL)
    view = stack.snapshots.record(AS_OF, origin=REPORT)
    values_before = stack.snapshots.values(view.id)
    stack.snapshots.withdraw(view.id, "  entered with the wrong data  ")

    row = db.execute(
        "SELECT snapshot_id, withdrawn_at_utc, reason, operator FROM snapshot_withdrawal"
    ).fetchone()
    assert tuple(row) == (view.id, "2026-03-05T12:00:00Z", "entered with the wrong data", OPERATOR)
    # Still stored, with its values, and unchanged.
    assert stack.snapshots.values(view.id) == values_before
    assert _count(db, "readiness_snapshot") == 2
    # Ignored by default, shown (flagged) when asked for.
    assert [v.id for v in stack.snapshots.list_snapshots()] == [keep.id]
    listed = stack.snapshots.list_snapshots(include_withdrawn=True)
    assert [v.id for v in listed] == [view.id, keep.id]
    assert [v.withdrawn for v in listed] == [True, False]
    assert listed[0].withdrawn_at_utc == "2026-03-05T12:00:00Z"
    assert listed[0].withdrawal_reason == "entered with the wrong data"
    assert listed[1].withdrawal_reason is None
    got = stack.snapshots.get(view.id).snapshot
    assert got.withdrawn
    assert got.origin is REPORT
    # The change log has the withdrawal.
    logged = [r for r in change_log_rows(db) if r["entity"] == "snapshot_withdrawal"]
    assert len(logged) == 1
    assert logged[0]["action"] == "insert"
    assert logged[0]["operator"] == OPERATOR
    assert logged[0]["at_utc"] == "2026-03-05T12:00:00Z"
    assert logged[0]["entity_id"] is not None
    after = json.loads(str(logged[0]["after_json"]))
    assert after["snapshot_id"] == view.id
    assert after["reason"] == "entered with the wrong data"


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_a_reason_is_required(stack: Stack, db: DatabaseConnection, reason: str) -> None:
    view = stack.snapshots.record(AS_OF, origin=MANUAL)
    assert _code(lambda: stack.snapshots.withdraw(view.id, reason)) == REASON_REQUIRED
    none_reason: Any = None
    assert _code(lambda: stack.snapshots.withdraw(view.id, none_reason)) == REASON_REQUIRED
    assert _count(db, "snapshot_withdrawal") == 0


def test_a_snapshot_is_withdrawn_only_once(stack: Stack, db: DatabaseConnection) -> None:
    view = stack.snapshots.record(AS_OF, origin=MANUAL)
    stack.snapshots.withdraw(view.id, "first reason")
    assert _code(lambda: stack.snapshots.withdraw(view.id, "second reason")) == ALREADY_WITHDRAWN
    assert _count(db, "snapshot_withdrawal") == 1
    assert stack.snapshots.get(view.id).snapshot.withdrawal_reason == "first reason"


def test_unknown_snapshots_are_not_found(stack: Stack, db: DatabaseConnection) -> None:
    assert _code(lambda: stack.snapshots.withdraw(999, "no such snapshot")) == NOT_FOUND
    assert _code(lambda: stack.snapshots.get(999)) == NOT_FOUND
    assert _code(lambda: stack.snapshots.values(999)) == NOT_FOUND
    assert _count(db, "snapshot_withdrawal") == 0


def test_lists_are_newest_first(db: DatabaseConnection) -> None:
    ids: list[int] = []
    for instant in ("2026-03-05T12:00:00Z", "2026-03-06T12:00:00Z", "2026-03-07T12:00:00Z"):
        built = _stack(db, FixedClock.at(instant))
        ids.append(built.snapshots.record(date(2026, 3, 5), origin=MANUAL).id)
    assert [v.id for v in built.snapshots.list_snapshots()] == ids[::-1]
    assert built.snapshots.list_snapshots()[0].origin is RETROACTIVE
    assert built.snapshots.list_snapshots()[-1].origin is MANUAL


# --------------------------------------------------------------------------- read-only


def test_read_only_refuses_recording_and_withdrawal_but_reads_work(
    stack: Stack, read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    view = stack.snapshots.record(AS_OF, origin=MANUAL)
    other = stack.snapshots.record(AS_OF, origin=MANUAL)
    stack.snapshots.withdraw(other.id, "duplicate")

    reader = _stack(read_only_db, clock).snapshots
    assert _code(lambda: reader.record(AS_OF, origin=MANUAL)) == READ_ONLY
    assert _code(lambda: reader.record(PAST, origin=MANUAL)) == READ_ONLY
    assert _code(lambda: reader.withdraw(view.id, "a reason")) == READ_ONLY
    assert _code(reader.record_monthly_if_due) == READ_ONLY
    # READ_ONLY comes first, also before the other refusals.
    assert _code(lambda: reader.withdraw(999, "")) == READ_ONLY

    assert [v.id for v in reader.list_snapshots()] == [view.id]
    assert [v.id for v in reader.list_snapshots(include_withdrawn=True)] == [other.id, view.id]
    assert reader.get(view.id).snapshot == view
    assert reader.values(view.id) == stack.snapshots.values(view.id)
    assert reader.monthly_due()


# --------------------------------------------------------------------------- start-up hook


@dataclass
class _FakeServices:
    indicators: IndicatorService | None
    infrastructure: InfrastructureService | None


@dataclass
class _FakeContext:
    conn: DatabaseConnection | None
    clock: Clock
    services: _FakeServices


def _context(stack: Stack, conn: DatabaseConnection | None, clock: Clock) -> _FakeContext:
    return _FakeContext(conn, clock, _FakeServices(stack.indicators, stack.infrastructure))


def test_the_startup_hook_records_once_a_month(
    stack: Stack, db: DatabaseConnection, clock: FixedClock
) -> None:
    context = _context(stack, db, clock)
    monthly_snapshot_startup(context)
    views = _monthly(stack)
    assert len(views) == 1
    assert views[0].as_of == AS_OF
    assert stack.snapshots.get(views[0].id).values
    monthly_snapshot_startup(context)
    monthly_snapshot_startup(_context(stack, db, clock.advanced(timedelta(days=10))))
    assert len(_monthly(stack)) == 1
    monthly_snapshot_startup(_context(stack, db, clock.advanced(timedelta(days=40))))
    assert len(_monthly(stack)) == 2


def test_the_startup_hook_does_nothing_without_a_database_or_a_service(
    stack: Stack, db: DatabaseConnection, clock: FixedClock
) -> None:
    monthly_snapshot_startup(_context(stack, None, clock))
    monthly_snapshot_startup(_FakeContext(db, clock, _FakeServices(None, stack.infrastructure)))
    monthly_snapshot_startup(_FakeContext(db, clock, _FakeServices(stack.indicators, None)))
    monthly_snapshot_startup(_FakeContext(db, clock, _FakeServices(None, None)))
    assert _count(db, "readiness_snapshot") == 0


def test_the_startup_hook_respects_the_monthly_switch(
    stack: Stack, db: DatabaseConnection, clock: FixedClock
) -> None:
    _config(snapshot_monthly=False)(stack, db, clock)
    monthly_snapshot_startup(_context(stack, db, clock))
    assert _count(db, "readiness_snapshot") == 0


# --------------------------------------------------------------------------- change log


def test_recording_writes_change_log_rows_with_operator_and_clock(
    stack: Stack, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    view = stack.snapshots.record(AS_OF, origin=REPORT)
    stored = stack.snapshots.values(view.id)
    rows = change_log_rows(db)

    headers = [r for r in rows if r["entity"] == "readiness_snapshot"]
    assert len(headers) == 1
    assert headers[0]["entity_id"] == view.id
    assert headers[0]["action"] == "insert"
    assert headers[0]["operator"] == OPERATOR
    assert headers[0]["at_utc"] == "2026-03-05T12:00:00Z"
    header = json.loads(str(headers[0]["after_json"]))
    assert header["config_hash"] == view.config_hash
    assert header["origin"] == "report"
    assert header["as_of"] == "2026-03-05"

    values = [r for r in rows if r["entity"] == "readiness_snapshot_value"]
    assert len(values) == len(stored) > 0
    keys = {(_key(r)["indicator_code"], _key(r)["dimension"]) for r in values}
    assert keys == {(v.indicator_code, v.dimension) for v in stored}
    assert {_key(r)["snapshot_id"] for r in values} == {view.id}
    assert {r["operator"] for r in values} == {OPERATOR}
    assert {r["at_utc"] for r in values} == {"2026-03-05T12:00:00Z"}
    assert {r["action"] for r in values} == {"insert"}
