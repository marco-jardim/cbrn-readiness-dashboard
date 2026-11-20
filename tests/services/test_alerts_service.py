# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the alert service (PLAN.md T6.2, section 5.5, A03, A06, P01, P02, D24).

All data is fictitious (``DEMO-...``) and is written THROUGH the module services. The expected
values are the domain rule functions called directly on the services' inputs, plus the explicit
dates and severities of section 5.5.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import alerts as rules
from cbrn_dashboard.domain.alerts import SEVERITY_OF, Alert, AlertKind, Severity, SubjectKind
from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.indicators import IndicatorReading, Module
from cbrn_dashboard.domain.infrastructure import AssetStatus, MaintenanceKind
from cbrn_dashboard.services.alerts import AlertService
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import (
    AssetInput,
    AssetTypeInput,
    InfrastructureService,
)
from cbrn_dashboard.services.personnel import (
    CertificateInput,
    PersonnelService,
    StaffInput,
)
from cbrn_dashboard.services.stock import InitialReceipt, LotInput, MovementInput, StockService
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import load_config, save_config

AS_OF = date(2026, 3, 5)
OPERATOR = "op-demo"
CERT_VALID = "PERS_CERT_VALID"
MAINT_OVERDUE = "INFRA_MAINT_OVERDUE"
LEVEL_A = "level=A"
LEVEL_B = "level=B"
TYPE_DIM = "type=DEMO-TYPE"
STOCK_KINDS = {AlertKind.LOT_EXPIRED, AlertKind.LOT_EXPIRING, AlertKind.LOW_STOCK}
NON_STOCK_KINDS = set(AlertKind) - STOCK_KINDS


@dataclass
class Stack:
    """The services over one connection, with the ids of the seeded records."""

    personnel: PersonnelService
    infrastructure: InfrastructureService
    indicators: IndicatorService
    alerts: AlertService
    type_id: int = 0
    cert_expired: int = 0  # certificate of DEMO-P001 (expired on AS_OF)
    cert_expiring: int = 0  # certificate of DEMO-P002 (expiring on AS_OF)
    staff_expired: int = 0


def _stack(conn: DatabaseConnection, clock: FixedClock) -> Stack:
    def operator() -> str:
        return OPERATOR

    personnel = PersonnelService(conn, clock, operator)
    infrastructure = InfrastructureService(conn, clock, operator)
    indicators = IndicatorService(
        conn,
        clock,
        operator,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=ExercisesService(conn, clock, operator),
        budget=BudgetService(conn, clock, operator),
    )
    alerts = AlertService(personnel=personnel, infrastructure=infrastructure, indicators=indicators)
    return Stack(personnel, infrastructure, indicators, alerts)


def _seed(stack: Stack) -> None:
    """Section 5.5 in one dataset; with the default P01 = 90 and P02 = 30 days on AS_OF.

    Staff: P001 expired (2026-01-10), P002 expiring (2026-04-01), P003 valid to 2027, P004
    deactivated with an expired certificate. Assets of DEMO-TYPE (no default interval): A001
    overdue, A002 due soon, A003 unknown schedule, A004 interval 0, A005 due far ahead, A006
    retired.
    """
    people = stack.personnel
    first = people.create_staff(StaffInput("DEMO-P001", "2020-01-01"))
    second = people.create_staff(StaffInput("DEMO-P002", "2020-01-01"))
    third = people.create_staff(StaffInput("DEMO-P003", "2021-01-01"))
    fourth = people.create_staff(StaffInput("DEMO-P004", "2020-01-01"))
    stack.staff_expired = first
    stack.cert_expired = people.add_certificate(
        first, CertificateInput("A", "2024-01-10", "2026-01-10")
    )
    stack.cert_expiring = people.add_certificate(
        second, CertificateInput("A", "2025-04-01", "2026-04-01")
    )
    people.add_certificate(third, CertificateInput("A", "2026-01-10", "2027-01-10"))
    people.add_certificate(fourth, CertificateInput("A", "2025-01-01", "2025-12-31"))
    people.deactivate_staff(fourth, "2026-01-31")

    infra = stack.infrastructure
    stack.type_id = infra.create_type(AssetTypeInput("DEMO-TYPE", "Tipo demo"))

    def asset(tag: str, interval: int | None = None) -> int:
        return infra.create_asset(
            AssetInput(
                tag=tag,
                type_id=stack.type_id,
                in_service_from="2025-01-01",
                maintenance_interval_days=interval,
            ),
            AssetStatus.OPERATIONAL,
        )

    overdue = asset("DEMO-A001", 30)
    # several records: the latest recorded next-due date (2025-03-10) rules, one alert only
    infra.record_maintenance(overdue, "2025-02-10", MaintenanceKind.PREVENTIVE, "2025-03-10")
    infra.record_maintenance(overdue, "2025-02-05", MaintenanceKind.CORRECTIVE, "2025-02-20")
    infra.record_maintenance(overdue, "2025-02-20", MaintenanceKind.INSPECTION)
    soon = asset("DEMO-A002", 30)
    infra.record_maintenance(soon, "2026-02-20", MaintenanceKind.PREVENTIVE, "2026-03-25")
    asset("DEMO-A003")
    asset("DEMO-A004", 0)
    far = asset("DEMO-A005")
    infra.record_maintenance(far, "2026-02-01", MaintenanceKind.PREVENTIVE, "2026-12-01")
    retired = asset("DEMO-A006", 30)
    infra.retire_asset(retired, "2025-06-01")


@pytest.fixture
def bare(db: DatabaseConnection, clock: FixedClock) -> Stack:
    """The services over a fresh database with no records at all."""
    return _stack(db, clock)


@pytest.fixture
def stack(bare: Stack) -> Stack:
    """The services over the fictitious dataset, with NO target stored."""
    _seed(bare)
    return bare


# --------------------------------------------------------------------------- helpers


def _set_indicator_targets(stack: Stack) -> None:
    """A WARNING on PERS_CERT_VALID (level A) and a CRITICAL on INFRA_MAINT_OVERDUE.

    On AS_OF two people hold a valid level A certificate (DEMO-P002 and DEMO-P003; DEMO-P001's has
    expired and DEMO-P004 is deactivated), so the targets 3 / 1 make 2 a warning.
    """
    stack.indicators.set_target(CERT_VALID, LEVEL_A, warning_value=3, critical_value=1)
    stack.indicators.set_target(MAINT_OVERDUE, TYPE_DIM, warning_value=0, critical_value=0)


@pytest.fixture
def full(stack: Stack) -> Stack:
    """The dataset plus the two targets: every alert kind is present (the SAME stack object)."""
    _set_indicator_targets(stack)
    return stack


def _refs(alerts: Iterable[Alert]) -> list[tuple[AlertKind, str]]:
    return [(a.kind, a.subject_ref) for a in alerts]


def _of_kind(alerts: Iterable[Alert], kind: AlertKind) -> list[Alert]:
    return [a for a in alerts if a.kind is kind]


def _save_config(db: DatabaseConnection, clock: FixedClock, config: ReadinessConfig) -> None:
    save_config(WriteContext(db, clock, OPERATOR), config)


# --------------------------------------------------------------------------- kinds and order


def test_every_alert_kind_is_produced_with_its_severity(full: Stack) -> None:
    alerts = full.alerts.alerts(AS_OF)
    # no stock service is wired in this stack: the stock kinds are tested further down
    assert {a.kind for a in alerts} == NON_STOCK_KINDS
    for alert in alerts:
        assert alert.severity is SEVERITY_OF[alert.kind]
    severities = {a.kind: a.severity for a in alerts}
    assert severities == {
        AlertKind.CERT_EXPIRED: Severity.CRITICAL,
        AlertKind.CERT_EXPIRING: Severity.WARNING,
        AlertKind.MAINT_OVERDUE: Severity.CRITICAL,
        AlertKind.MAINT_DUE_SOON: Severity.WARNING,
        AlertKind.MAINT_SCHEDULE_UNKNOWN: Severity.INFO,
        AlertKind.INDICATOR_WARNING: Severity.WARNING,
        AlertKind.INDICATOR_CRITICAL: Severity.CRITICAL,
    }


def test_the_alerts_carry_the_subject_dates_and_numbers(full: Stack) -> None:
    alerts = full.alerts.alerts(AS_OF)

    [expired] = _of_kind(alerts, AlertKind.CERT_EXPIRED)
    assert (expired.module, expired.subject_kind) == (Module.PERSONNEL, SubjectKind.STAFF)
    assert (expired.subject_ref, expired.subject_id) == ("DEMO-P001", full.staff_expired)
    assert (expired.dimension, expired.due_on) == (LEVEL_A, date(2026, 1, 10))
    assert expired.days_remaining == -54

    [expiring] = _of_kind(alerts, AlertKind.CERT_EXPIRING)
    assert (expiring.subject_ref, expiring.due_on) == ("DEMO-P002", date(2026, 4, 1))
    assert expiring.days_remaining == 27

    [overdue] = _of_kind(alerts, AlertKind.MAINT_OVERDUE)
    assert (overdue.module, overdue.subject_kind) == (Module.INFRASTRUCTURE, SubjectKind.ASSET)
    assert (overdue.subject_ref, overdue.due_on) == ("DEMO-A001", date(2025, 3, 10))
    assert overdue.days_remaining == -360

    [soon] = _of_kind(alerts, AlertKind.MAINT_DUE_SOON)
    assert (soon.subject_ref, soon.due_on, soon.days_remaining) == (
        "DEMO-A002",
        date(2026, 3, 25),
        20,
    )

    [unknown] = _of_kind(alerts, AlertKind.MAINT_SCHEDULE_UNKNOWN)
    assert (unknown.subject_ref, unknown.due_on, unknown.days_remaining) == (
        "DEMO-A003",
        None,
        None,
    )

    [warning] = _of_kind(alerts, AlertKind.INDICATOR_WARNING)
    assert (warning.subject_kind, warning.subject_ref) == (SubjectKind.INDICATOR, CERT_VALID)
    assert (warning.module, warning.subject_id, warning.dimension) == (
        Module.PERSONNEL,
        None,
        LEVEL_A,
    )
    assert (warning.value, warning.threshold) == (2.0, 3.0)

    [critical] = _of_kind(alerts, AlertKind.INDICATOR_CRITICAL)
    assert (critical.module, critical.subject_ref, critical.dimension) == (
        Module.INFRASTRUCTURE,
        MAINT_OVERDUE,
        TYPE_DIM,
    )
    assert (critical.value, critical.threshold) == (1.0, 0.0)


def test_alerts_are_sorted_by_severity_then_due_date(full: Stack) -> None:
    alerts = full.alerts.alerts(AS_OF)
    assert _refs(alerts) == [
        (AlertKind.MAINT_OVERDUE, "DEMO-A001"),  # critical, 2025-03-10
        (AlertKind.CERT_EXPIRED, "DEMO-P001"),  # critical, 2026-01-10
        (AlertKind.INDICATOR_CRITICAL, MAINT_OVERDUE),  # critical, no date
        (AlertKind.MAINT_DUE_SOON, "DEMO-A002"),  # warning, 2026-03-25
        (AlertKind.CERT_EXPIRING, "DEMO-P002"),  # warning, 2026-04-01
        (AlertKind.INDICATOR_WARNING, CERT_VALID),  # warning, no date
        (AlertKind.MAINT_SCHEDULE_UNKNOWN, "DEMO-A003"),  # info
    ]
    keys = [(a.severity.rank, a.due_on is None, a.due_on or date.min) for a in alerts]
    assert keys == sorted(keys)


def test_the_alert_list_is_the_hand_worked_one(stack: Stack) -> None:
    """P6-12: written out from section 5.5, not computed again by the rule functions."""
    assert _refs(stack.alerts.alerts(AS_OF)) == [
        (AlertKind.MAINT_OVERDUE, "DEMO-A001"),
        (AlertKind.CERT_EXPIRED, "DEMO-P001"),
        (AlertKind.MAINT_DUE_SOON, "DEMO-A002"),
        (AlertKind.CERT_EXPIRING, "DEMO-P002"),
        (AlertKind.MAINT_SCHEDULE_UNKNOWN, "DEMO-A003"),
    ]
    _set_indicator_targets(stack)
    assert _refs(stack.alerts.alerts(AS_OF)) == [
        (AlertKind.MAINT_OVERDUE, "DEMO-A001"),
        (AlertKind.CERT_EXPIRED, "DEMO-P001"),
        (AlertKind.INDICATOR_CRITICAL, MAINT_OVERDUE),
        (AlertKind.MAINT_DUE_SOON, "DEMO-A002"),
        (AlertKind.CERT_EXPIRING, "DEMO-P002"),
        (AlertKind.INDICATOR_WARNING, CERT_VALID),
        (AlertKind.MAINT_SCHEDULE_UNKNOWN, "DEMO-A003"),
    ]


def test_the_readings_of_the_caller_are_used_instead_of_a_second_evaluation(
    full: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P6-13: the dashboard passes the readings it just evaluated; none is evaluated again."""
    readings = full.indicators.evaluate(AS_OF)
    calls: list[date] = []

    def counting(as_of: date) -> list[IndicatorReading]:
        calls.append(as_of)
        return readings

    monkeypatch.setattr(full.indicators, "evaluate", counting)

    counts = full.alerts.counts(AS_OF, readings=readings)

    assert calls == []
    assert dict(counts) == {Severity.CRITICAL: 3, Severity.WARNING: 3, Severity.INFO: 1}
    assert len(full.alerts.alerts(AS_OF, readings=readings)) == 7


def test_the_alerts_agree_with_the_pages_of_the_modules(full: Stack) -> None:
    alerts = full.alerts.alerts(AS_OF)
    rows = full.infrastructure.asset_rows(AS_OF)
    assert sorted(a.subject_ref for a in _of_kind(alerts, AlertKind.MAINT_OVERDUE)) == sorted(
        row.tag for row in rows if row.in_service and row.overdue
    )
    assert sorted(a.subject_ref for a in _of_kind(alerts, AlertKind.MAINT_DUE_SOON)) == sorted(
        row.tag for row in rows if row.in_service and row.due_soon
    )
    expiring = full.personnel.expiring_list(AS_OF)
    assert sorted(a.subject_id or 0 for a in _of_kind(alerts, AlertKind.CERT_EXPIRING)) == sorted(
        row.staff_id for row in expiring
    )


def test_an_empty_database_has_no_alerts(bare: Stack) -> None:
    assert bare.alerts.alerts(AS_OF) == []
    assert dict(bare.alerts.counts(AS_OF)) == dict.fromkeys(Severity, 0)
    assert bare.alerts.has_actionable(AS_OF) is False


def test_the_service_stores_nothing(full: Stack, db: DatabaseConnection) -> None:
    def state() -> tuple[int, int]:
        log = int(db.execute("SELECT count(*) FROM change_log").fetchone()[0])
        tables = int(db.execute("SELECT count(*) FROM sqlite_master").fetchone()[0])
        return log, tables

    before = state()
    full.alerts.alerts(AS_OF)
    full.alerts.counts(AS_OF)
    assert state() == before


# --------------------------------------------------------------------------- one per subject


def test_one_certificate_alert_per_person_and_level(stack: Stack) -> None:
    people = stack.personnel
    person = people.create_staff(StaffInput("DEMO-P010", "2020-01-01"))
    people.add_certificate(person, CertificateInput("A", "2021-01-01", "2022-01-01"))
    people.add_certificate(person, CertificateInput("A", "2022-06-01", "2023-06-01"))
    people.add_certificate(person, CertificateInput("B", "2022-06-01", "2023-06-01"))

    mine = [a for a in stack.alerts.alerts(AS_OF) if a.subject_ref == "DEMO-P010"]
    assert sorted(a.dimension for a in mine) == [LEVEL_A, LEVEL_B]
    assert all(a.kind is AlertKind.CERT_EXPIRED for a in mine)
    # the counting certificate of level A is the one valid the longest (A03)
    [level_a] = [a for a in mine if a.dimension == LEVEL_A]
    assert level_a.due_on == date(2023, 6, 1)


def test_a_renewed_certificate_replaces_the_expired_one(stack: Stack) -> None:
    people = stack.personnel
    before = stack.alerts.alerts(AS_OF)
    assert ("DEMO-P001", AlertKind.CERT_EXPIRED) in {(a.subject_ref, a.kind) for a in before}
    people.add_certificate(stack.staff_expired, CertificateInput("A", "2026-02-01", "2028-02-01"))
    after = stack.alerts.alerts(AS_OF)
    assert "DEMO-P001" not in {a.subject_ref for a in after}


def test_one_maintenance_alert_per_asset(full: Stack) -> None:
    alerts = [a for a in full.alerts.alerts(AS_OF) if a.subject_kind is SubjectKind.ASSET]
    counted = Counter(a.subject_id for a in alerts)
    assert set(counted.values()) == {1}
    assert len(alerts) == 3  # overdue, due soon, unknown


# --------------------------------------------------------------------------- D24 and A06


def test_no_renewal_from_on_or_before_the_date_suppresses_the_certificate_alert(
    stack: Stack,
) -> None:
    people = stack.personnel

    def refs() -> set[tuple[str, AlertKind]]:
        return {(a.subject_ref, a.kind) for a in stack.alerts.alerts(AS_OF)}

    assert ("DEMO-P001", AlertKind.CERT_EXPIRED) in refs()
    assert ("DEMO-P002", AlertKind.CERT_EXPIRING) in refs()

    # later than the as-of date: no effect yet
    people.set_no_renewal(stack.cert_expired, "2026-03-06")
    people.set_no_renewal(stack.cert_expiring, "2026-03-06")
    assert ("DEMO-P001", AlertKind.CERT_EXPIRED) in refs()
    assert ("DEMO-P002", AlertKind.CERT_EXPIRING) in refs()

    # on the as-of date: both gone, an expired certificate included
    people.set_no_renewal(stack.cert_expired, AS_OF, "left_unit")
    people.set_no_renewal(stack.cert_expiring, "2026-01-01")
    assert not {"DEMO-P001", "DEMO-P002"} & {ref for ref, _ in refs()}

    # the mark applies from its date on: the day before it, the alert is still there
    assert ("DEMO-P001", AlertKind.CERT_EXPIRED) in {
        (a.subject_ref, a.kind) for a in stack.alerts.alerts(date(2026, 3, 4))
    }

    people.clear_no_renewal(stack.cert_expired)
    assert ("DEMO-P001", AlertKind.CERT_EXPIRED) in refs()


def test_interval_zero_without_a_next_due_date_raises_no_alert(stack: Stack) -> None:
    refs = {a.subject_ref for a in stack.alerts.alerts(AS_OF)}
    assert "DEMO-A004" not in refs  # interval 0: no scheduled maintenance (A06)
    assert "DEMO-A003" in refs  # no interval at all: unknown schedule
    assert "DEMO-A005" not in refs  # next due far ahead


# --------------------------------------------------------------------------- indicators


def test_without_a_target_there_is_no_indicator_alert(stack: Stack) -> None:
    alerts = stack.alerts.alerts(AS_OF)
    assert not _of_kind(alerts, AlertKind.INDICATOR_WARNING)
    assert not _of_kind(alerts, AlertKind.INDICATOR_CRITICAL)
    assert len(alerts) == 5  # 2 certificates, 3 assets


def test_a_disabled_target_behaves_as_if_it_were_absent(full: Stack) -> None:
    def indicator_refs() -> list[tuple[AlertKind, str]]:
        return [
            ref
            for ref in _refs(full.alerts.alerts(AS_OF))
            if ref[0] in {AlertKind.INDICATOR_WARNING, AlertKind.INDICATOR_CRITICAL}
        ]

    assert indicator_refs() == [
        (AlertKind.INDICATOR_CRITICAL, MAINT_OVERDUE),
        (AlertKind.INDICATOR_WARNING, CERT_VALID),
    ]
    full.indicators.set_target_enabled(CERT_VALID, LEVEL_A, False)
    assert indicator_refs() == [(AlertKind.INDICATOR_CRITICAL, MAINT_OVERDUE)]
    full.indicators.set_target_enabled(MAINT_OVERDUE, TYPE_DIM, False)
    assert indicator_refs() == []
    full.indicators.set_target_enabled(CERT_VALID, LEVEL_A, True)
    full.indicators.set_target_enabled(MAINT_OVERDUE, TYPE_DIM, True)
    assert len(indicator_refs()) == 2
    full.indicators.delete_target(MAINT_OVERDUE, TYPE_DIM)
    assert indicator_refs() == [(AlertKind.INDICATOR_WARNING, CERT_VALID)]


# --------------------------------------------------------------------------- inactive and dates


def test_deactivated_staff_and_retired_assets_give_no_alerts(stack: Stack) -> None:
    refs = {a.subject_ref for a in stack.alerts.alerts(AS_OF)}
    assert "DEMO-P004" not in refs  # active until 2026-01-31, expired certificate
    assert "DEMO-A006" not in refs  # retired on 2025-06-01, interval 30

    # ...but they did count while they were active / in service
    assert "DEMO-P004" in {a.subject_ref for a in stack.alerts.alerts(date(2026, 1, 15))}
    assert "DEMO-A006" in {a.subject_ref for a in stack.alerts.alerts(date(2025, 5, 1))}


def test_a_past_as_of_date_gives_the_alerts_of_that_date(full: Stack) -> None:
    past = date(2026, 1, 5)
    alerts = full.alerts.alerts(past)
    [first] = [a for a in alerts if a.subject_ref == "DEMO-P001"]
    assert first.kind is AlertKind.CERT_EXPIRING  # valid until 2026-01-10: five days left
    assert first.days_remaining == 5
    assert (AlertKind.MAINT_DUE_SOON, "DEMO-A002") not in _refs(alerts)  # no record yet
    assert full.alerts.alerts(AS_OF) != alerts


# --------------------------------------------------------------------------- configuration


def test_the_stored_certificate_warning_days_are_honoured(
    stack: Stack, db: DatabaseConnection, clock: FixedClock
) -> None:
    def expiring() -> set[str]:
        alerts = _of_kind(stack.alerts.alerts(AS_OF), AlertKind.CERT_EXPIRING)
        return {a.subject_ref for a in alerts}

    assert expiring() == {"DEMO-P002"}  # 27 days left, window 90
    _save_config(db, clock, load_config(db).with_changes(cert_warning_days=10))
    assert expiring() == set()
    _save_config(db, clock, load_config(db).with_changes(cert_warning_days=330))
    assert expiring() == {"DEMO-P002", "DEMO-P003"}  # P003 has 311 days left
    # the service and the page of the personnel module use the same rule
    assert {row.staff_id for row in stack.personnel.expiring_list(AS_OF)} == {
        a.subject_id for a in _of_kind(stack.alerts.alerts(AS_OF), AlertKind.CERT_EXPIRING)
    }


def test_the_stored_maintenance_warning_days_are_honoured(
    stack: Stack, db: DatabaseConnection, clock: FixedClock
) -> None:
    def soon() -> set[str]:
        alerts = _of_kind(stack.alerts.alerts(AS_OF), AlertKind.MAINT_DUE_SOON)
        return {a.subject_ref for a in alerts}

    assert soon() == {"DEMO-A002"}  # 20 days left, window 30
    _save_config(db, clock, load_config(db).with_changes(maintenance_warning_days=10))
    assert soon() == set()
    _save_config(db, clock, load_config(db).with_changes(maintenance_warning_days=300))
    assert soon() == {"DEMO-A002", "DEMO-A005"}  # A005 is due in 271 days


# --------------------------------------------------------------------------- summaries, filters


def test_counts_by_severity(stack: Stack) -> None:
    before = stack.alerts.counts(AS_OF)
    assert set(before) == set(Severity)
    assert dict(before) == {Severity.CRITICAL: 2, Severity.WARNING: 2, Severity.INFO: 1}
    _set_indicator_targets(stack)
    after = stack.alerts.counts(AS_OF)
    assert set(after) == set(Severity)
    assert dict(after) == {Severity.CRITICAL: 3, Severity.WARNING: 3, Severity.INFO: 1}
    assert after == rules.count_by_severity(stack.alerts.alerts(AS_OF))


def test_has_actionable_ignores_info_alerts(bare: Stack) -> None:
    type_id = bare.infrastructure.create_type(AssetTypeInput("DEMO-TYPE", "Tipo demo"))
    bare.infrastructure.create_asset(
        AssetInput(tag="DEMO-A100", type_id=type_id, in_service_from="2025-01-01"),
        AssetStatus.OPERATIONAL,
    )
    alerts = bare.alerts.alerts(AS_OF)
    assert [a.severity for a in alerts] == [Severity.INFO]
    assert bare.alerts.has_actionable(AS_OF) is False

    person = bare.personnel.create_staff(StaffInput("DEMO-P100", "2020-01-01"))
    bare.personnel.add_certificate(person, CertificateInput("A", "2025-01-01", "2026-03-20"))
    assert bare.alerts.has_actionable(AS_OF) is True


def test_has_actionable_on_the_full_dataset(full: Stack) -> None:
    assert full.alerts.has_actionable(AS_OF) is True


def test_filters_by_module_and_severity(full: Stack) -> None:
    everything = full.alerts.alerts(AS_OF)
    assert full.alerts.alerts_filtered(AS_OF) == everything

    personnel = full.alerts.alerts_filtered(AS_OF, module=Module.PERSONNEL)
    assert personnel == [a for a in everything if a.module is Module.PERSONNEL]
    assert _refs(personnel) == [
        (AlertKind.CERT_EXPIRED, "DEMO-P001"),
        (AlertKind.CERT_EXPIRING, "DEMO-P002"),
        (AlertKind.INDICATOR_WARNING, CERT_VALID),
    ]

    infra = full.alerts.alerts_filtered(AS_OF, module=Module.INFRASTRUCTURE)
    assert infra == [a for a in everything if a.module is Module.INFRASTRUCTURE]
    assert len(infra) == 4

    assert full.alerts.alerts_filtered(AS_OF, module=Module.BUDGET) == []
    assert full.alerts.alerts_filtered(AS_OF, module=Module.EXERCISES) == []

    critical = full.alerts.alerts_filtered(AS_OF, severity=Severity.CRITICAL)
    assert [a.severity for a in critical] == [Severity.CRITICAL] * 3
    info = full.alerts.alerts_filtered(AS_OF, severity=Severity.INFO)
    assert _refs(info) == [(AlertKind.MAINT_SCHEDULE_UNKNOWN, "DEMO-A003")]

    both = full.alerts.alerts_filtered(AS_OF, module=Module.PERSONNEL, severity=Severity.WARNING)
    assert _refs(both) == [
        (AlertKind.CERT_EXPIRING, "DEMO-P002"),
        (AlertKind.INDICATOR_WARNING, CERT_VALID),
    ]


# --------------------------------------------------------------------------- read-only


def test_a_read_only_connection_still_computes_the_alerts(
    full: Stack, read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    frozen = _stack(read_only_db, clock)
    expected = full.alerts.alerts(AS_OF)
    assert expected
    assert frozen.alerts.alerts(AS_OF) == expected
    assert frozen.alerts.counts(AS_OF) == full.alerts.counts(AS_OF)
    assert frozen.alerts.has_actionable(AS_OF) is True


# --------------------------------------------------------------------------- stock (T11.8)

CHEMICAL = "ANTIDOTE_CHEMICAL"
BIOLOGICAL = "ANTIDOTE_BIOLOGICAL"
GLOVE = "GLOVE"


def _operator() -> str:
    return OPERATOR


@dataclass
class StockStack:
    stock: StockService
    alerts: AlertService
    without: AlertService


@pytest.fixture
def stocked(bare: Stack, db: DatabaseConnection, clock: FixedClock) -> StockStack:
    """Stock written through the service; P11 = 90 days, so the window ends on 2026-06-03.

    CHEMICAL: DEMO-L001 expires 2026-06-03 (10, last day of the window), DEMO-L002 expired
    2026-03-04 (4), DEMO-L003 expires 2026-06-04 (7, valid). BIOLOGICAL has a minimum of 20 and no
    lot. GLOVE has a lot without expiry date.
    """
    stock = StockService(db, clock, _operator)

    def lot(code: str, lot_code: str, expires_on: str | None, quantity: int) -> None:
        found = stock.get_type_by_code(code)
        assert found is not None
        stock.create_lot(
            LotInput(type_id=found.id, lot_code=lot_code, expires_on=expires_on),
            InitialReceipt(moved_on="2026-01-01", quantity=quantity),
        )

    lot(CHEMICAL, "DEMO-L001", "2026-06-03", 10)
    lot(CHEMICAL, "DEMO-L002", "2026-03-04", 4)
    lot(CHEMICAL, "DEMO-L003", "2026-06-04", 7)
    lot(GLOVE, "DEMO-L004", None, 100)
    biological = stock.get_type_by_code(BIOLOGICAL)
    assert biological is not None
    stock.set_minimum(biological.id, 20)
    wired = AlertService(
        personnel=bare.personnel,
        infrastructure=bare.infrastructure,
        indicators=bare.indicators,
        stock=stock,
    )
    return StockStack(stock, wired, bare.alerts)


def test_the_stock_alerts_are_in_the_service_with_hand_computed_fields(stocked: StockStack) -> None:
    alerts = stocked.alerts.alerts(AS_OF)

    assert [(a.kind, a.subject_ref, a.severity) for a in alerts] == [
        (AlertKind.LOT_EXPIRED, "DEMO-L002", Severity.CRITICAL),
        (AlertKind.LOW_STOCK, BIOLOGICAL, Severity.CRITICAL),
        (AlertKind.LOT_EXPIRING, "DEMO-L001", Severity.WARNING),
    ]
    expired, low, expiring = alerts
    assert (expired.module, expired.subject_kind) == (Module.STOCK, SubjectKind.LOT)
    assert expired.dimension == f"category=antidote;item={CHEMICAL}"
    assert (expired.due_on, expired.days_remaining, expired.value) == (date(2026, 3, 4), -1, 4.0)
    assert (low.subject_kind, low.due_on, low.days_remaining) == (SubjectKind.ITEM_TYPE, None, None)
    assert (low.value, low.threshold) == (0.0, 20.0)
    assert (expiring.due_on, expiring.days_remaining, expiring.value) == (
        date(2026, 6, 3),
        90,
        10.0,
    )


def test_without_a_stock_service_there_are_no_stock_alerts(stocked: StockStack) -> None:
    assert not [a for a in stocked.without.alerts(AS_OF) if a.module is Module.STOCK]
    assert stocked.without.counts(AS_OF)[Severity.CRITICAL] == 0


def test_the_counts_and_the_filters_include_the_stock_alerts(stocked: StockStack) -> None:
    counts = stocked.alerts.counts(AS_OF)

    assert dict(counts) == {Severity.CRITICAL: 2, Severity.WARNING: 1, Severity.INFO: 0}
    assert len(stocked.alerts.alerts_filtered(AS_OF, module=Module.STOCK)) == 3
    assert stocked.alerts.has_actionable(AS_OF) is True


def test_the_p11_window_of_the_settings_is_honoured(
    stocked: StockStack, db: DatabaseConnection, clock: FixedClock
) -> None:
    def expiring() -> set[str]:
        found = _of_kind(stocked.alerts.alerts(AS_OF), AlertKind.LOT_EXPIRING)
        return {a.subject_ref for a in found}

    assert expiring() == {"DEMO-L001"}
    _save_config(db, clock, load_config(db).with_changes(stock_expiry_warning_days=89))
    assert expiring() == set()
    _save_config(db, clock, load_config(db).with_changes(stock_expiry_warning_days=91))
    assert expiring() == {"DEMO-L001", "DEMO-L003"}


def test_a_past_as_of_date_gives_the_stock_alerts_of_that_date(stocked: StockStack) -> None:
    # before the first receipt nothing is on hand: only the type below its minimum remains
    before = stocked.alerts.alerts(date(2025, 12, 31))
    assert [(a.kind, a.subject_ref) for a in before] == [(AlertKind.LOW_STOCK, BIOLOGICAL)]
    # on 2026-02-01 DEMO-L002 (2026-03-04) is inside the window; DEMO-L001 is 122 days away
    early = stocked.alerts.alerts(date(2026, 2, 1))
    assert [(a.kind, a.subject_ref) for a in _of_kind(early, AlertKind.LOT_EXPIRING)] == [
        (AlertKind.LOT_EXPIRING, "DEMO-L002")
    ]
    assert not _of_kind(early, AlertKind.LOT_EXPIRED)


def test_an_empty_lot_stops_alerting_after_a_disposal(stocked: StockStack) -> None:
    [lot] = [row for row in stocked.stock.list_lots() if row.lot_code == "DEMO-L002"]
    stocked.stock.record_movement(
        lot.id, MovementInput(moved_on="2026-03-05", kind="disposal", quantity=4)
    )

    assert not _of_kind(stocked.alerts.alerts(AS_OF), AlertKind.LOT_EXPIRED)
