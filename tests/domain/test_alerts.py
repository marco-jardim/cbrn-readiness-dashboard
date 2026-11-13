# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the alert rules (PLAN T6.2, section 5.5): fictitious data, explicit dates, no clock."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from cbrn_dashboard.domain.alerts import (
    SEVERITY_OF,
    Alert,
    AlertKind,
    Severity,
    SubjectKind,
    all_alerts,
    certificate_alerts,
    count_by_severity,
    has_actionable,
    indicator_alerts,
    maintenance_alerts,
    sort_alerts,
)
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorDefinition,
    IndicatorReading,
    IndicatorRegistry,
    IndicatorStatus,
    IndicatorValue,
    Module,
    Target,
    TargetKey,
    UnitKind,
    UnknownIndicatorError,
    evaluate,
)
from cbrn_dashboard.domain.infrastructure import (
    Asset,
    AssetType,
    InfrastructureRules,
    MaintenanceEvent,
    MaintenanceKind,
)
from cbrn_dashboard.domain.personnel import Certificate, PersonnelRules, PpeLevel, StaffMember

D = date(2026, 6, 1)
PERSONNEL_RULES = PersonnelRules()
INFRA_RULES = InfrastructureRules()


def days(n: int, base: date = D) -> date:
    return base + timedelta(days=n)


# --------------------------------------------------------------------------------------------
# Builders
# --------------------------------------------------------------------------------------------


def person(
    staff_id: int = 1,
    identifier: str = "DEMO-P001",
    active_from: date = date(2020, 1, 1),
    active_until: date | None = None,
) -> StaffMember:
    return StaffMember(
        id=staff_id, identifier=identifier, active_from=active_from, active_until=active_until
    )


def cert(
    cert_id: int,
    level: PpeLevel,
    valid_until: date,
    *,
    staff_id: int = 1,
    issued_on: date | None = None,
    no_renewal_from: date | None = None,
) -> Certificate:
    return Certificate(
        id=cert_id,
        staff_id=staff_id,
        level=level,
        issued_on=days(-400) if issued_on is None else issued_on,
        valid_until=valid_until,
        no_renewal_from=no_renewal_from,
    )


def cert_alerts(
    certs: list[Certificate],
    *,
    d: date = D,
    staff: list[StaffMember] | None = None,
    rules: PersonnelRules = PERSONNEL_RULES,
) -> list[Alert]:
    return certificate_alerts([person()] if staff is None else staff, certs, d, rules)


def asset(
    asset_id: int = 1,
    tag: str = "DEMO-A001",
    *,
    type_code: str = "DEMO_TYPE",
    in_service_from: date = date(2020, 1, 1),
    in_service_until: date | None = None,
    interval: int | None = None,
) -> Asset:
    return Asset(
        id=asset_id,
        tag=tag,
        type_code=type_code,
        in_service_from=in_service_from,
        in_service_until=in_service_until,
        maintenance_interval_days=interval,
    )


def recorded_due(asset_id: int, due_on: date, performed_on: date | None = None) -> MaintenanceEvent:
    return MaintenanceEvent(
        asset_id=asset_id,
        performed_on=days(-100) if performed_on is None else performed_on,
        kind=MaintenanceKind.PREVENTIVE,
        next_due_on=due_on,
    )


def maint_alerts(
    assets: list[Asset],
    *,
    types: list[AssetType] | None = None,
    maintenance: list[MaintenanceEvent] | None = None,
    d: date = D,
) -> list[Alert]:
    return maintenance_alerts(
        assets,
        [] if types is None else types,
        [],
        [] if maintenance is None else maintenance,
        d,
        INFRA_RULES,
    )


def make_alert(
    kind: AlertKind,
    ref: str,
    *,
    due_on: date | None = None,
    module: Module = Module.PERSONNEL,
    dimension: str = "",
    subject_id: int | None = None,
) -> Alert:
    return Alert(
        kind=kind,
        severity=SEVERITY_OF[kind],
        module=module,
        subject_kind=SubjectKind.STAFF,
        subject_ref=ref,
        subject_id=subject_id,
        dimension=dimension,
        due_on=due_on,
        days_remaining=None if due_on is None else (due_on - D).days,
    )


def kinds(alerts: list[Alert]) -> list[AlertKind]:
    return [a.kind for a in alerts]


# Indicator fixtures: a lower-is-better and a higher-is-better fictitious indicator.
DIM_X = "type=X"
LOW_DEF = IndicatorDefinition(
    code="DEMO_LOW",
    module=Module.EXERCISES,
    unit=UnitKind.COUNT,
    direction=Direction.LOWER_IS_BETTER,
    dimension_keys=("type",),
)
HIGH_DEF = IndicatorDefinition(
    code="DEMO_HIGH",
    module=Module.BUDGET,
    unit=UnitKind.COUNT,
    direction=Direction.HIGHER_IS_BETTER,
)


def make_registry() -> IndicatorRegistry:
    registry = IndicatorRegistry()
    registry.register(LOW_DEF)
    registry.register(HIGH_DEF)
    return registry


def reading(
    definition: IndicatorDefinition,
    value: float | None,
    target: Target | None,
    dimension: str = "",
) -> IndicatorReading:
    targets: dict[TargetKey, Target] = {}
    if target is not None:
        targets[(definition.code, dimension)] = target
    return evaluate(definition, IndicatorValue(definition.code, value, dimension), targets)


LOW_TARGET = Target(warning_value=1.0, critical_value=3.0)
HIGH_TARGET = Target(warning_value=5.0, critical_value=2.0)


# --------------------------------------------------------------------------------------------
# Kinds and severities
# --------------------------------------------------------------------------------------------


def test_severity_table_matches_plan() -> None:
    assert dict(SEVERITY_OF) == {
        AlertKind.CERT_EXPIRED: Severity.CRITICAL,
        AlertKind.CERT_EXPIRING: Severity.WARNING,
        AlertKind.MAINT_OVERDUE: Severity.CRITICAL,
        AlertKind.MAINT_DUE_SOON: Severity.WARNING,
        AlertKind.MAINT_SCHEDULE_UNKNOWN: Severity.INFO,
        AlertKind.INDICATOR_WARNING: Severity.WARNING,
        AlertKind.INDICATOR_CRITICAL: Severity.CRITICAL,
    }
    assert set(SEVERITY_OF) == set(AlertKind)


def test_severity_rank_is_critical_first() -> None:
    assert Severity.CRITICAL.rank < Severity.WARNING.rank < Severity.INFO.rank


@dataclass(frozen=True)
class Scenario:
    staff: list[StaffMember]
    certs: list[Certificate]
    assets: list[Asset]
    maintenance: list[MaintenanceEvent]
    readings: list[IndicatorReading]


def full_scenario() -> Scenario:
    """One alert of every kind (and a person and asset with nothing to report)."""
    staff = [person(1, "DEMO-P001"), person(2, "DEMO-P002")]
    certs = [
        cert(1, PpeLevel.A, days(-5)),  # expired
        cert(2, PpeLevel.B, days(10)),  # expiring
        cert(3, PpeLevel.C, days(400)),  # valid, nothing
        cert(4, PpeLevel.A, days(400), staff_id=2),
        cert(5, PpeLevel.B, days(400), staff_id=2),
        cert(6, PpeLevel.C, days(400), staff_id=2),
    ]
    assets = [
        asset(1, "DEMO-A001"),  # overdue
        asset(2, "DEMO-A002"),  # due soon
        asset(3, "DEMO-A003"),  # unknown schedule
        asset(4, "DEMO-A004"),  # fine
    ]
    maintenance = [
        recorded_due(1, days(-3)),
        recorded_due(2, days(7)),
        recorded_due(4, days(200)),
    ]
    readings = [
        reading(LOW_DEF, 3.0, LOW_TARGET, DIM_X),  # critical
        reading(HIGH_DEF, 4.0, HIGH_TARGET),  # warning
    ]
    return Scenario(
        staff=staff, certs=certs, assets=assets, maintenance=maintenance, readings=readings
    )


def run_all(scenario: Scenario, d: date = D) -> list[Alert]:
    return all_alerts(
        staff=scenario.staff,
        certs=scenario.certs,
        personnel_rules=PERSONNEL_RULES,
        assets=scenario.assets,
        asset_types=[],
        status_events=[],
        maintenance=scenario.maintenance,
        infrastructure_rules=INFRA_RULES,
        readings=scenario.readings,
        registry=make_registry(),
        d=d,
    )


def test_every_kind_is_produced_with_its_severity() -> None:
    alerts = run_all(full_scenario())
    assert {a.kind for a in alerts} == set(AlertKind)
    assert len(alerts) == len(AlertKind)
    for alert in alerts:
        assert alert.severity is SEVERITY_OF[alert.kind]


def test_all_alerts_are_sorted_severity_then_due_date_then_undated() -> None:
    alerts = run_all(full_scenario())
    assert kinds(alerts) == [
        AlertKind.CERT_EXPIRED,  # critical, due D-5
        AlertKind.MAINT_OVERDUE,  # critical, due D-3
        AlertKind.INDICATOR_CRITICAL,  # critical, undated
        AlertKind.MAINT_DUE_SOON,  # warning, due D+7
        AlertKind.CERT_EXPIRING,  # warning, due D+10
        AlertKind.INDICATOR_WARNING,  # warning, undated
        AlertKind.MAINT_SCHEDULE_UNKNOWN,  # info
    ]


def test_alert_fields_for_each_subject_kind() -> None:
    by_kind = {a.kind: a for a in run_all(full_scenario())}

    expired = by_kind[AlertKind.CERT_EXPIRED]
    assert (expired.module, expired.subject_kind) == (Module.PERSONNEL, SubjectKind.STAFF)
    assert (expired.subject_ref, expired.subject_id) == ("DEMO-P001", 1)
    assert expired.dimension == "level=A"
    assert (expired.due_on, expired.days_remaining) == (days(-5), -5)
    assert (expired.value, expired.threshold) == (None, None)

    overdue = by_kind[AlertKind.MAINT_OVERDUE]
    assert (overdue.module, overdue.subject_kind) == (Module.INFRASTRUCTURE, SubjectKind.ASSET)
    assert (overdue.subject_ref, overdue.subject_id) == ("DEMO-A001", 1)
    assert overdue.dimension == ""
    assert (overdue.due_on, overdue.days_remaining) == (days(-3), -3)

    unknown = by_kind[AlertKind.MAINT_SCHEDULE_UNKNOWN]
    assert (unknown.subject_ref, unknown.due_on, unknown.days_remaining) == (
        "DEMO-A003",
        None,
        None,
    )

    critical = by_kind[AlertKind.INDICATOR_CRITICAL]
    assert (critical.module, critical.subject_kind) == (Module.EXERCISES, SubjectKind.INDICATOR)
    assert (critical.subject_ref, critical.subject_id, critical.dimension) == (
        "DEMO_LOW",
        None,
        DIM_X,
    )
    assert (critical.due_on, critical.days_remaining) == (None, None)
    assert (critical.value, critical.threshold) == (3.0, 3.0)

    warning = by_kind[AlertKind.INDICATOR_WARNING]
    assert warning.module is Module.BUDGET
    assert (warning.value, warning.threshold) == (4.0, 5.0)


# --------------------------------------------------------------------------------------------
# Sorting
# --------------------------------------------------------------------------------------------


def test_sort_order_is_independent_of_input_order() -> None:
    alerts = run_all(full_scenario())
    alerts += [
        make_alert(AlertKind.CERT_EXPIRING, "DEMO-P002", due_on=days(10), subject_id=2),
        make_alert(AlertKind.CERT_EXPIRING, "DEMO-P002", due_on=days(10), dimension="level=B"),
        make_alert(
            AlertKind.MAINT_DUE_SOON,
            "DEMO-A009",
            due_on=days(10),
            module=Module.INFRASTRUCTURE,
        ),
        make_alert(AlertKind.CERT_EXPIRED, "DEMO-P003", due_on=days(-5)),
    ]
    expected = sort_alerts(alerts)
    for seed in range(20):
        shuffled = list(alerts)
        random.Random(seed).shuffle(shuffled)
        assert sort_alerts(shuffled) == expected


def test_sort_dated_before_undated_within_a_severity() -> None:
    undated = make_alert(AlertKind.INDICATOR_CRITICAL, "DEMO_LOW", module=Module.EXERCISES)
    later = make_alert(AlertKind.CERT_EXPIRED, "DEMO-P001", due_on=days(-1))
    earlier = make_alert(AlertKind.CERT_EXPIRED, "DEMO-P001", due_on=days(-30))
    info = make_alert(AlertKind.MAINT_SCHEDULE_UNKNOWN, "DEMO-A001", module=Module.INFRASTRUCTURE)
    warning = make_alert(AlertKind.CERT_EXPIRING, "DEMO-P001", due_on=days(-100))
    expected = [earlier, later, undated, warning, info]
    assert sort_alerts([info, undated, warning, later, earlier]) == expected


def test_sort_tie_break_is_module_kind_subject_dimension() -> None:
    due = days(10)
    infra = make_alert(
        AlertKind.MAINT_DUE_SOON, "DEMO-A001", due_on=due, module=Module.INFRASTRUCTURE
    )
    p1_a = make_alert(AlertKind.CERT_EXPIRING, "DEMO-P001", due_on=due, dimension="level=A")
    p1_b = make_alert(AlertKind.CERT_EXPIRING, "DEMO-P001", due_on=due, dimension="level=B")
    p2_a = make_alert(AlertKind.CERT_EXPIRING, "DEMO-P002", due_on=due, dimension="level=A")
    ordered = [infra, p1_a, p1_b, p2_a]
    for seed in range(10):
        shuffled = list(ordered)
        random.Random(seed).shuffle(shuffled)
        assert sort_alerts(shuffled) == ordered


# --------------------------------------------------------------------------------------------
# Certificates
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "kind", "remaining"),
    [
        pytest.param(-1, AlertKind.CERT_EXPIRED, -1, id="expired-yesterday"),
        pytest.param(0, AlertKind.CERT_EXPIRING, 0, id="last-valid-day"),
        pytest.param(1, AlertKind.CERT_EXPIRING, 1, id="tomorrow"),
        pytest.param(90, AlertKind.CERT_EXPIRING, 90, id="window-edge"),
        pytest.param(91, None, None, id="outside-window"),
        pytest.param(-400, AlertKind.CERT_EXPIRED, -400, id="long-expired"),
    ],
)
def test_certificate_boundaries(offset: int, kind: AlertKind | None, remaining: int | None) -> None:
    alerts = cert_alerts([cert(1, PpeLevel.A, days(offset))])
    if kind is None:
        assert alerts == []
        return
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.kind is kind
    assert alert.severity is SEVERITY_OF[kind]
    assert alert.days_remaining == remaining
    assert alert.due_on == days(offset)
    assert alert.dimension == "level=A"


def test_certificate_window_follows_the_configured_days() -> None:
    rules = PersonnelRules(cert_warning_days=30)
    assert cert_alerts([cert(1, PpeLevel.A, days(30))], rules=rules)[0].kind is (
        AlertKind.CERT_EXPIRING
    )
    assert cert_alerts([cert(1, PpeLevel.A, days(31))], rules=rules) == []


def test_no_certificate_gives_no_alert() -> None:
    assert cert_alerts([]) == []
    assert cert_alerts([cert(1, PpeLevel.A, days(-5), staff_id=99)]) == []


@pytest.mark.parametrize(
    ("valid_offset", "no_renewal_offset", "expected"),
    [
        pytest.param(-5, 0, None, id="expired-no-renewal-today"),
        pytest.param(-5, -1, None, id="expired-no-renewal-before"),
        pytest.param(10, 0, None, id="expiring-no-renewal-today"),
        pytest.param(10, -30, None, id="expiring-no-renewal-before"),
        pytest.param(-5, 1, AlertKind.CERT_EXPIRED, id="expired-later-no-renewal"),
        pytest.param(10, 1, AlertKind.CERT_EXPIRING, id="expiring-later-no-renewal"),
        pytest.param(10, None, AlertKind.CERT_EXPIRING, id="expiring-not-set"),
        pytest.param(-5, None, AlertKind.CERT_EXPIRED, id="expired-not-set"),
    ],
)
def test_no_renewal_suppresses_certificate_alerts(
    valid_offset: int, no_renewal_offset: int | None, expected: AlertKind | None
) -> None:
    no_renewal = None if no_renewal_offset is None else days(no_renewal_offset)
    certs = [cert(1, PpeLevel.A, days(valid_offset), no_renewal_from=no_renewal)]
    assert kinds(cert_alerts(certs)) == ([] if expected is None else [expected])


def test_one_certificate_alert_per_person_and_level() -> None:
    certs = [
        cert(1, PpeLevel.A, days(-300), issued_on=days(-700)),
        cert(2, PpeLevel.A, days(-5), issued_on=days(-400)),
        cert(3, PpeLevel.A, days(-20), issued_on=days(-300)),
    ]
    alerts = cert_alerts(certs)
    assert len(alerts) == 1
    assert alerts[0].kind is AlertKind.CERT_EXPIRED
    assert alerts[0].due_on == days(-5)  # the counting certificate: latest valid_until


def test_person_with_two_levels_gets_two_alerts() -> None:
    certs = [
        cert(1, PpeLevel.A, days(-5)),
        cert(2, PpeLevel.B, days(10)),
        cert(3, PpeLevel.C, days(300)),
    ]
    alerts = cert_alerts(certs)
    assert [(a.dimension, a.kind) for a in alerts] == [
        ("level=A", AlertKind.CERT_EXPIRED),
        ("level=B", AlertKind.CERT_EXPIRING),
    ]


def test_each_person_is_reported_separately() -> None:
    staff = [person(1, "DEMO-P001"), person(2, "DEMO-P002")]
    certs = [
        cert(1, PpeLevel.A, days(-5), staff_id=1),
        cert(2, PpeLevel.A, days(10), staff_id=2),
    ]
    alerts = cert_alerts(certs, staff=staff)
    assert [(a.subject_ref, a.subject_id, a.kind) for a in alerts] == [
        ("DEMO-P001", 1, AlertKind.CERT_EXPIRED),
        ("DEMO-P002", 2, AlertKind.CERT_EXPIRING),
    ]


def test_certificate_issued_after_the_date_does_not_hide_the_valid_one() -> None:
    old = cert(1, PpeLevel.A, days(10), issued_on=days(-300))
    renewal = cert(2, PpeLevel.A, days(400), issued_on=days(10))
    certs = [old, renewal]

    at_d = cert_alerts(certs, d=D)
    assert [(a.kind, a.due_on) for a in at_d] == [(AlertKind.CERT_EXPIRING, days(10))]

    assert cert_alerts(certs, d=days(10)) == []  # renewal issued that day counts
    assert cert_alerts(certs, d=days(11)) == []  # and afterwards


def test_expired_certificate_is_not_hidden_by_a_future_renewal() -> None:
    old = cert(1, PpeLevel.A, days(-5), issued_on=days(-300))
    renewal = cert(2, PpeLevel.A, days(400), issued_on=days(3))
    alerts = cert_alerts([old, renewal])
    assert [(a.kind, a.days_remaining) for a in alerts] == [(AlertKind.CERT_EXPIRED, -5)]


def test_inactive_staff_get_no_certificate_alerts() -> None:
    certs = [cert(1, PpeLevel.A, days(-5))]
    left = person(active_until=days(-1))
    not_yet = person(active_from=days(1))
    assert cert_alerts(certs, staff=[left]) == []
    assert cert_alerts(certs, staff=[not_yet]) == []
    assert len(cert_alerts(certs, staff=[person(active_until=D)])) == 1  # last day still active
    assert len(cert_alerts(certs, staff=[person(active_from=D)])) == 1


def test_certificate_alerts_of_a_past_date() -> None:
    certs = [cert(1, PpeLevel.A, date(2026, 3, 1), issued_on=date(2024, 3, 1))]
    expected = {
        date(2025, 6, 1): [],
        date(2026, 1, 15): [(AlertKind.CERT_EXPIRING, 45)],
        date(2026, 3, 1): [(AlertKind.CERT_EXPIRING, 0)],
        date(2026, 3, 2): [(AlertKind.CERT_EXPIRED, -1)],
    }
    for as_of, wanted in expected.items():
        got = [(a.kind, a.days_remaining) for a in cert_alerts(certs, d=as_of)]
        assert got == wanted, as_of


def test_hierarchy_on_still_gives_one_alert_per_person_and_level() -> None:
    rules = PersonnelRules(hierarchy_enabled=True, hierarchy={"A": ("B", "C"), "B": ("C",)})
    certs = [
        cert(1, PpeLevel.A, days(10)),
        cert(2, PpeLevel.B, days(-5)),
        cert(3, PpeLevel.A, days(10), issued_on=days(-200)),
    ]
    alerts = cert_alerts(certs, rules=rules)
    levels = [a.dimension for a in alerts]
    assert levels == ["level=A", "level=B", "level=C"]  # exactly one per level
    # The level-A certificate (latest valid_until) also counts for B and C.
    assert {a.kind for a in alerts} == {AlertKind.CERT_EXPIRING}
    assert {a.due_on for a in alerts} == {days(10)}


def test_hierarchy_off_keeps_levels_independent() -> None:
    certs = [cert(1, PpeLevel.A, days(10))]
    alerts = cert_alerts(certs)
    assert [a.dimension for a in alerts] == ["level=A"]


def test_hierarchy_on_a_higher_certificate_can_replace_an_expired_one() -> None:
    rules = PersonnelRules(hierarchy_enabled=True, hierarchy={"A": ("B",)})
    certs = [cert(1, PpeLevel.B, days(-5)), cert(2, PpeLevel.A, days(300))]
    alerts = cert_alerts(certs, rules=rules)
    assert alerts == []  # level B is covered by the valid level-A certificate


# --------------------------------------------------------------------------------------------
# Maintenance
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("offset", "kind", "remaining"),
    [
        pytest.param(-1, AlertKind.MAINT_OVERDUE, -1, id="yesterday"),
        pytest.param(-60, AlertKind.MAINT_OVERDUE, -60, id="long-overdue"),
        pytest.param(0, AlertKind.MAINT_DUE_SOON, 0, id="due-today"),
        pytest.param(30, AlertKind.MAINT_DUE_SOON, 30, id="window-edge"),
        pytest.param(31, None, None, id="outside-window"),
    ],
)
def test_maintenance_boundaries(offset: int, kind: AlertKind | None, remaining: int | None) -> None:
    alerts = maint_alerts([asset()], maintenance=[recorded_due(1, days(offset))])
    if kind is None:
        assert alerts == []
        return
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.kind is kind
    assert alert.severity is SEVERITY_OF[kind]
    assert alert.days_remaining == remaining
    assert alert.due_on == days(offset)
    assert (alert.subject_ref, alert.subject_id, alert.dimension) == ("DEMO-A001", 1, "")
    assert alert.module is Module.INFRASTRUCTURE


def test_maintenance_window_follows_the_configured_days() -> None:
    rules = InfrastructureRules(maintenance_warning_days=10)
    maintenance = [recorded_due(1, days(10))]
    assert kinds(maintenance_alerts([asset()], [], [], maintenance, D, rules)) == [
        AlertKind.MAINT_DUE_SOON
    ]
    maintenance = [recorded_due(1, days(11))]
    assert maintenance_alerts([asset()], [], [], maintenance, D, rules) == []


def test_schedule_unknown_without_interval_or_next_due() -> None:
    types = [AssetType(code="DEMO_TYPE", default_maintenance_interval_days=None)]
    alerts = maint_alerts([asset()], types=types)
    assert len(alerts) == 1
    assert alerts[0].kind is AlertKind.MAINT_SCHEDULE_UNKNOWN
    assert alerts[0].severity is Severity.INFO
    assert (alerts[0].due_on, alerts[0].days_remaining) == (None, None)


def test_schedule_unknown_when_the_type_is_not_listed() -> None:
    assert kinds(maint_alerts([asset()], types=[])) == [AlertKind.MAINT_SCHEDULE_UNKNOWN]


def test_maintenance_without_next_due_does_not_fix_an_unknown_schedule() -> None:
    event = MaintenanceEvent(
        asset_id=1, performed_on=days(-5), kind=MaintenanceKind.CORRECTIVE, next_due_on=None
    )
    assert kinds(maint_alerts([asset()], maintenance=[event])) == [AlertKind.MAINT_SCHEDULE_UNKNOWN]


def test_interval_zero_raises_no_unknown_schedule_alert() -> None:
    # asset override 0 (even when the type default is positive)
    types = [AssetType(code="DEMO_TYPE", default_maintenance_interval_days=365)]
    assert maint_alerts([asset(interval=0)], types=types) == []
    # type default 0, no override
    types = [AssetType(code="DEMO_TYPE", default_maintenance_interval_days=0)]
    assert maint_alerts([asset()], types=types) == []


def test_interval_zero_with_recorded_next_due_in_the_past_is_overdue() -> None:
    types = [AssetType(code="DEMO_TYPE", default_maintenance_interval_days=0)]
    for asset_under_test in (asset(), asset(interval=0)):
        alerts = maint_alerts(
            [asset_under_test], types=types, maintenance=[recorded_due(1, days(-1))]
        )
        assert [(a.kind, a.days_remaining) for a in alerts] == [(AlertKind.MAINT_OVERDUE, -1)]


def test_interval_based_schedule_overdue_and_due_soon() -> None:
    # No maintenance: in_service_from + interval is the due date.
    start = days(-100)
    overdue = asset(1, "DEMO-A001", in_service_from=start, interval=60)  # due D-40
    soon = asset(2, "DEMO-A002", in_service_from=start, interval=110)  # due D+10
    fine = asset(3, "DEMO-A003", in_service_from=start, interval=500)
    alerts = maint_alerts([overdue, soon, fine])
    assert [(a.subject_ref, a.kind, a.days_remaining) for a in alerts] == [
        ("DEMO-A001", AlertKind.MAINT_OVERDUE, -40),
        ("DEMO-A002", AlertKind.MAINT_DUE_SOON, 10),
    ]


def test_at_most_one_maintenance_alert_per_asset() -> None:
    events = [
        recorded_due(1, days(-50), performed_on=days(-200)),
        recorded_due(1, days(-10), performed_on=days(-100)),
        recorded_due(1, days(5), performed_on=days(-90)),
    ]
    alerts = maint_alerts([asset()], maintenance=events)
    assert len(alerts) == 1
    assert alerts[0].kind is AlertKind.MAINT_DUE_SOON  # the latest record wins
    many = maint_alerts([asset(1, "DEMO-A001"), asset(2, "DEMO-A002")])
    assert sorted(a.subject_ref for a in many) == ["DEMO-A001", "DEMO-A002"]


def test_retired_and_not_yet_in_service_assets_give_no_alerts() -> None:
    overdue = [recorded_due(1, days(-10)), recorded_due(2, days(-10)), recorded_due(3, days(-10))]
    retired = asset(1, "DEMO-A001", in_service_until=days(-1))
    future = asset(2, "DEMO-A002", in_service_from=days(1))
    last_day = asset(3, "DEMO-A003", in_service_until=D)
    alerts = maint_alerts([retired, future, last_day], maintenance=overdue)
    assert [a.subject_ref for a in alerts] == ["DEMO-A003"]
    # also for the unknown-schedule alert
    assert maint_alerts([retired, future]) == []


def test_maintenance_alerts_of_a_past_date() -> None:
    events = [
        MaintenanceEvent(1, date(2026, 1, 1), MaintenanceKind.PREVENTIVE, date(2026, 3, 1)),
        MaintenanceEvent(1, date(2026, 3, 2), MaintenanceKind.PREVENTIVE, date(2026, 9, 1)),
    ]
    unit = asset(in_service_from=date(2025, 1, 1))
    expected = {
        date(2026, 2, 10): [(AlertKind.MAINT_DUE_SOON, 19)],
        date(2026, 3, 15): [],
        date(2026, 9, 5): [(AlertKind.MAINT_OVERDUE, -4)],
    }
    for as_of, wanted in expected.items():
        alerts = maint_alerts([unit], maintenance=events, d=as_of)
        assert [(a.kind, a.days_remaining) for a in alerts] == wanted, as_of


# --------------------------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------------------------


def test_no_target_gives_no_indicator_alert() -> None:
    readings = [reading(LOW_DEF, 99.0, None, DIM_X), reading(HIGH_DEF, 0.0, None)]
    assert [r.status for r in readings] == [IndicatorStatus.NO_TARGET] * 2
    assert indicator_alerts(readings, make_registry()) == []


def test_disabled_target_gives_no_indicator_alert() -> None:
    off = Target(warning_value=1.0, critical_value=3.0, enabled=False)
    readings = [reading(LOW_DEF, 99.0, off, DIM_X)]
    assert readings[0].status is IndicatorStatus.NO_TARGET
    assert indicator_alerts(readings, make_registry()) == []


def test_target_for_another_dimension_does_not_apply() -> None:
    other = {("DEMO_LOW", "type=Y"): LOW_TARGET}
    low = evaluate(LOW_DEF, IndicatorValue("DEMO_LOW", 99.0, DIM_X), other)
    assert indicator_alerts([low], make_registry()) == []


def test_no_data_and_ok_give_no_indicator_alert() -> None:
    readings = [
        reading(LOW_DEF, None, LOW_TARGET, DIM_X),
        reading(LOW_DEF, 0.0, LOW_TARGET, DIM_X),
        reading(HIGH_DEF, 6.0, HIGH_TARGET),
    ]
    assert [r.status for r in readings] == [
        IndicatorStatus.NO_DATA,
        IndicatorStatus.OK,
        IndicatorStatus.OK,
    ]
    assert indicator_alerts(readings, make_registry()) == []


WARN = AlertKind.INDICATOR_WARNING
CRIT = AlertKind.INDICATOR_CRITICAL


@pytest.mark.parametrize(
    ("definition", "value", "target", "kind", "threshold"),
    [
        pytest.param(LOW_DEF, 1.0, LOW_TARGET, WARN, 1.0, id="low-warn-edge"),
        pytest.param(LOW_DEF, 2.0, LOW_TARGET, WARN, 1.0, id="low-warn"),
        pytest.param(LOW_DEF, 3.0, LOW_TARGET, CRIT, 3.0, id="low-crit-edge"),
        pytest.param(LOW_DEF, 9.0, LOW_TARGET, CRIT, 3.0, id="low-crit"),
        pytest.param(HIGH_DEF, 5.0, HIGH_TARGET, WARN, 5.0, id="high-warn-edge"),
        pytest.param(HIGH_DEF, 3.0, HIGH_TARGET, WARN, 5.0, id="high-warn"),
        pytest.param(HIGH_DEF, 2.0, HIGH_TARGET, CRIT, 2.0, id="high-crit-edge"),
        pytest.param(HIGH_DEF, 0.0, HIGH_TARGET, CRIT, 2.0, id="high-crit"),
    ],
)
def test_crossed_target_gives_one_alert_with_the_crossed_threshold(
    definition: IndicatorDefinition,
    value: float,
    target: Target,
    kind: AlertKind,
    threshold: float,
) -> None:
    dimension = DIM_X if definition is LOW_DEF else ""
    alerts = indicator_alerts([reading(definition, value, target, dimension)], make_registry())
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.kind is kind
    assert alert.severity is SEVERITY_OF[kind]
    assert alert.module is definition.module
    assert alert.subject_kind is SubjectKind.INDICATOR
    assert (alert.subject_ref, alert.subject_id, alert.dimension) == (
        definition.code,
        None,
        dimension,
    )
    assert (alert.value, alert.threshold) == (value, threshold)
    assert (alert.due_on, alert.days_remaining) == (None, None)


def test_target_with_only_a_critical_value() -> None:
    only_critical = Target(warning_value=None, critical_value=3.0)
    assert indicator_alerts([reading(LOW_DEF, 2.0, only_critical, DIM_X)], make_registry()) == []
    alerts = indicator_alerts([reading(LOW_DEF, 3.0, only_critical, DIM_X)], make_registry())
    assert [(a.kind, a.threshold) for a in alerts] == [(AlertKind.INDICATOR_CRITICAL, 3.0)]


def test_unregistered_indicator_code_raises() -> None:
    unknown = IndicatorReading(
        code="DEMO_UNREGISTERED",
        dimension="",
        value=9.0,
        status=IndicatorStatus.CRITICAL,
        warning_value=None,
        critical_value=1.0,
    )
    with pytest.raises(UnknownIndicatorError):
        indicator_alerts([unknown], make_registry())


# --------------------------------------------------------------------------------------------
# Summaries
# --------------------------------------------------------------------------------------------


def test_count_by_severity_has_all_three_keys() -> None:
    assert dict(count_by_severity([])) == {
        Severity.CRITICAL: 0,
        Severity.WARNING: 0,
        Severity.INFO: 0,
    }
    alerts = run_all(full_scenario())
    assert dict(count_by_severity(alerts)) == {
        Severity.CRITICAL: 3,
        Severity.WARNING: 3,
        Severity.INFO: 1,
    }


def test_has_actionable_ignores_info_only() -> None:
    info = make_alert(AlertKind.MAINT_SCHEDULE_UNKNOWN, "DEMO-A001", module=Module.INFRASTRUCTURE)
    warning = make_alert(AlertKind.CERT_EXPIRING, "DEMO-P001", due_on=days(5))
    critical = make_alert(AlertKind.CERT_EXPIRED, "DEMO-P001", due_on=days(-5))
    assert has_actionable([]) is False
    assert has_actionable([info, info]) is False
    assert has_actionable([info, warning]) is True
    assert has_actionable([critical]) is True


def test_all_alerts_of_a_past_date_use_the_data_of_that_date() -> None:
    scenario = full_scenario()
    assert len(run_all(scenario, d=D)) == len(AlertKind)
    early = run_all(scenario, d=days(-1000))
    # The certificates were issued 400 days before D, so none counts that early; the maintenance
    # records are later too, so every asset in service has an unknown schedule.
    assert not any(a.subject_kind is SubjectKind.STAFF for a in early)
    maintenance_kinds = {a.kind for a in early if a.subject_kind is SubjectKind.ASSET}
    assert maintenance_kinds == {AlertKind.MAINT_SCHEDULE_UNKNOWN}
