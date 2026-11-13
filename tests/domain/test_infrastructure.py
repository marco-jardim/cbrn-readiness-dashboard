# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the infrastructure rules and indicators (PLAN T3.2). All data is fictitious."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorStatus,
    IndicatorValue,
    Module,
    UnitKind,
    evaluate,
)
from cbrn_dashboard.domain.infrastructure import (
    Asset,
    AssetStatus,
    AssetType,
    InfrastructureRules,
    MaintenanceEvent,
    MaintenanceKind,
    MaintenanceSchedule,
    ScheduleBasis,
    StatusEvent,
    asset_rows,
    data_quality,
    effective_interval,
    indicator_definitions,
    indicator_values,
    is_available,
    is_due_soon,
    is_in_service,
    is_overdue,
    is_schedule_unknown,
    maintenance_due_lists,
    maintenance_schedule,
    status_on,
)
from cbrn_dashboard.domain.registry import build_registry

D = date(2026, 6, 15)
IN_SERVICE = date(2025, 1, 1)
RULES = InfrastructureRules()
DEGRADED_OK = InfrastructureRules(degraded_counts_as_available=True)

OPERATIONAL = AssetStatus.OPERATIONAL
DEGRADED = AssetStatus.DEGRADED
OUT = AssetStatus.OUT_OF_SERVICE
UNKNOWN = AssetStatus.UNKNOWN

PREVENTIVE = MaintenanceKind.PREVENTIVE
CORRECTIVE = MaintenanceKind.CORRECTIVE
INSPECTION = MaintenanceKind.INSPECTION


def days(n: int) -> date:
    """``D`` shifted by ``n`` days."""
    return D + timedelta(days=n)


def make_asset(
    asset_id: int = 1,
    tag: str = "DEMO-A001",
    type_code: str = "bed",
    *,
    start: date = IN_SERVICE,
    until: date | None = None,
    interval: int | None = None,
) -> Asset:
    return Asset(
        id=asset_id,
        tag=tag,
        type_code=type_code,
        in_service_from=start,
        in_service_until=until,
        maintenance_interval_days=interval,
    )


def maint(
    performed_on: date,
    kind: MaintenanceKind = PREVENTIVE,
    next_due_on: date | None = None,
    asset_id: int = 1,
) -> MaintenanceEvent:
    return MaintenanceEvent(
        asset_id=asset_id, performed_on=performed_on, kind=kind, next_due_on=next_due_on
    )


def status_event(effective_on: date, status: AssetStatus, asset_id: int = 1) -> StatusEvent:
    return StatusEvent(asset_id=asset_id, effective_on=effective_on, status=status)


def schedule_on(due_on: date | None, basis: ScheduleBasis) -> MaintenanceSchedule:
    return MaintenanceSchedule(due_on=due_on, basis=basis, last_maintenance_on=None)


# --------------------------------------------------------------------------------------------
# In service
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "until", "expected"),
    [
        (days(-10), None, True),
        (days(0), None, True),  # first day is inclusive
        (days(1), None, False),  # not yet in service
        (days(-10), days(0), True),  # last day is inclusive
        (days(-10), days(-1), False),  # retired
        (days(-10), days(1), True),
        (days(0), days(0), True),
    ],
)
def test_is_in_service(start: date, until: date | None, expected: bool) -> None:
    assert is_in_service(make_asset(start=start, until=until), D) is expected


# --------------------------------------------------------------------------------------------
# Status on a date (D26) and availability (A05)
# --------------------------------------------------------------------------------------------

STATUS_EVENTS = [
    status_event(days(-10), DEGRADED),
    status_event(days(0), OUT),
    status_event(days(1), OPERATIONAL),
    status_event(days(-30), OPERATIONAL),
    status_event(days(0), OPERATIONAL, asset_id=2),  # another asset, never mixed in
]


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (days(-31), UNKNOWN),  # before the first event
        (days(-30), OPERATIONAL),  # an event dated d applies on d
        (days(-11), OPERATIONAL),
        (days(-10), DEGRADED),
        (days(-1), DEGRADED),  # before the change
        (days(0), OUT),  # on the day
        (days(1), OPERATIONAL),  # after: the event dated d + 1 applies on d + 1 only
    ],
)
def test_status_on_dates(as_of: date, expected: AssetStatus) -> None:
    assert status_on(STATUS_EVENTS, 1, as_of) is expected


def test_event_dated_after_d_does_not_apply() -> None:
    events = [status_event(days(-5), OUT), status_event(days(1), OPERATIONAL)]
    assert status_on(events, 1, D) is OUT


def test_no_event_is_unknown() -> None:
    assert status_on([], 1, D) is UNKNOWN
    assert status_on([status_event(days(0), OPERATIONAL, asset_id=2)], 1, D) is UNKNOWN


def test_same_day_events_are_order_independent() -> None:
    first = [status_event(D, OPERATIONAL), status_event(D, OUT)]
    assert status_on(first, 1, D) is OUT
    assert status_on(list(reversed(first)), 1, D) is OUT


@pytest.mark.parametrize(
    ("status", "rules", "expected"),
    [
        (OPERATIONAL, RULES, True),
        (DEGRADED, RULES, False),  # A05 switch off
        (OUT, RULES, False),
        (UNKNOWN, RULES, False),
        (OPERATIONAL, DEGRADED_OK, True),
        (DEGRADED, DEGRADED_OK, True),  # A05 switch on
        (OUT, DEGRADED_OK, False),
        (UNKNOWN, DEGRADED_OK, False),
    ],
)
def test_is_available(status: AssetStatus, rules: InfrastructureRules, expected: bool) -> None:
    assert is_available(status, rules) is expected


def test_default_rules() -> None:
    assert RULES.maintenance_warning_days == 30
    assert RULES.degraded_counts_as_available is False


def test_status_values_are_stable_codes() -> None:
    statuses = ["operational", "degraded", "out_of_service", "unknown"]
    assert [s.value for s in AssetStatus] == statuses
    assert [k.value for k in MaintenanceKind] == ["preventive", "corrective", "inspection"]


# --------------------------------------------------------------------------------------------
# Effective interval
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("own", "default", "expected"),
    [
        (None, None, None),
        (None, 365, 365),
        (None, 0, 0),
        (90, None, 90),
        (90, 365, 90),  # asset override wins
        (0, 365, 0),  # an override of 0 wins over a non-zero default
        (60, 0, 60),  # a non-zero override wins over a default of 0
    ],
)
def test_effective_interval(own: int | None, default: int | None, expected: int | None) -> None:
    asset_type = AssetType(code="DEMO-TYPE", default_maintenance_interval_days=default)
    assert effective_interval(make_asset(interval=own), asset_type) == expected


def test_effective_interval_without_type() -> None:
    assert effective_interval(make_asset(interval=None), None) is None
    assert effective_interval(make_asset(interval=7), None) == 7


# --------------------------------------------------------------------------------------------
# The due-date rule (A06)
# --------------------------------------------------------------------------------------------

MARCH_1 = date(2026, 3, 1)
MAY_1 = date(2026, 5, 1)

SCHEDULE_CASES = [
    pytest.param(
        None,
        None,
        [maint(days(-100), PREVENTIVE, next_due_on=days(10))],
        days(10),
        ScheduleBasis.RECORDED_NEXT_DUE,
        id="explicit-next-due",
    ),
    pytest.param(
        90,
        None,
        [maint(MARCH_1, PREVENTIVE)],
        date(2026, 5, 30),
        ScheduleBasis.PREVENTIVE_PLUS_INTERVAL,
        id="last-preventive-plus-interval",
    ),
    pytest.param(
        None,
        365,
        [maint(MARCH_1, PREVENTIVE)],
        date(2027, 3, 1),
        ScheduleBasis.PREVENTIVE_PLUS_INTERVAL,
        id="type-default-interval-from-preventive",
    ),
    pytest.param(
        None,
        365,
        [],
        date(2026, 1, 1),
        ScheduleBasis.IN_SERVICE_PLUS_INTERVAL,
        id="in-service-plus-type-default",
    ),
    pytest.param(
        90,
        None,
        [],
        date(2025, 4, 1),
        ScheduleBasis.IN_SERVICE_PLUS_INTERVAL,
        id="in-service-plus-own-interval",
    ),
    pytest.param(
        60,
        365,
        [],
        date(2025, 3, 2),
        ScheduleBasis.IN_SERVICE_PLUS_INTERVAL,
        id="override-60-over-default-365",
    ),
    pytest.param(
        0,
        365,
        [],
        None,
        ScheduleBasis.NO_SCHEDULED_MAINTENANCE,
        id="override-0-over-nonzero-default",
    ),
    pytest.param(
        0,
        365,
        [maint(MARCH_1, PREVENTIVE)],
        None,
        ScheduleBasis.NO_SCHEDULED_MAINTENANCE,
        id="override-0-with-preventive-record-but-no-next-due",
    ),
    pytest.param(
        None,
        0,
        [],
        None,
        ScheduleBasis.NO_SCHEDULED_MAINTENANCE,
        id="type-default-0",
    ),
    pytest.param(
        60,
        0,
        [],
        date(2025, 3, 2),
        ScheduleBasis.IN_SERVICE_PLUS_INTERVAL,
        id="nonzero-override-over-default-0",
    ),
    pytest.param(
        None,
        None,
        [],
        None,
        ScheduleBasis.UNKNOWN,
        id="no-interval-no-record-unknown",
    ),
    pytest.param(
        None,
        None,
        [maint(MARCH_1, PREVENTIVE)],
        None,
        ScheduleBasis.UNKNOWN,
        id="preventive-without-next-due-or-interval-unknown",
    ),
    pytest.param(
        0,
        None,
        [maint(MARCH_1, PREVENTIVE, next_due_on=date(2026, 9, 1))],
        date(2026, 9, 1),
        ScheduleBasis.RECORDED_NEXT_DUE,
        id="interval-0-with-recorded-next-due-still-due",
    ),
    pytest.param(
        0,
        365,
        [maint(MARCH_1, PREVENTIVE, next_due_on=date(2026, 9, 1))],
        date(2026, 9, 1),
        ScheduleBasis.RECORDED_NEXT_DUE,
        id="override-0-with-recorded-next-due-still-due",
    ),
    pytest.param(
        None,
        None,
        [
            maint(MARCH_1, PREVENTIVE, next_due_on=date(2026, 9, 1)),
            maint(MAY_1, CORRECTIVE),
        ],
        date(2026, 9, 1),
        ScheduleBasis.RECORDED_NEXT_DUE,
        id="corrective-after-recorded-does-not-move-due",
    ),
    pytest.param(
        None,
        None,
        [
            maint(MARCH_1, PREVENTIVE, next_due_on=date(2026, 9, 1)),
            maint(MAY_1, INSPECTION),
        ],
        date(2026, 9, 1),
        ScheduleBasis.RECORDED_NEXT_DUE,
        id="inspection-after-recorded-does-not-move-due",
    ),
    pytest.param(
        90,
        None,
        [maint(MARCH_1, PREVENTIVE), maint(MAY_1, CORRECTIVE)],
        date(2026, 5, 30),
        ScheduleBasis.PREVENTIVE_PLUS_INTERVAL,
        id="corrective-does-not-reset-preventive-plus-interval",
    ),
    pytest.param(
        90,
        None,
        [maint(MARCH_1, INSPECTION), maint(MAY_1, CORRECTIVE)],
        date(2025, 4, 1),
        ScheduleBasis.IN_SERVICE_PLUS_INTERVAL,
        id="only-corrective-and-inspection-keep-in-service-basis",
    ),
    pytest.param(
        None,
        None,
        [
            maint(date(2026, 1, 10), PREVENTIVE, next_due_on=date(2026, 7, 10)),
            maint(MAY_1, PREVENTIVE, next_due_on=date(2026, 10, 10)),
        ],
        date(2026, 10, 10),
        ScheduleBasis.RECORDED_NEXT_DUE,
        id="later-record-replaces-earlier-recorded",
    ),
    pytest.param(
        None,
        None,
        [
            maint(MAY_1, PREVENTIVE, next_due_on=date(2026, 7, 1)),
            maint(date(2026, 1, 10), PREVENTIVE, next_due_on=date(2026, 12, 1)),
        ],
        date(2026, 7, 1),
        ScheduleBasis.RECORDED_NEXT_DUE,
        id="latest-by-performed-on-not-by-next-due-or-input-order",
    ),
    pytest.param(
        90,
        None,
        [
            maint(MARCH_1, PREVENTIVE, next_due_on=date(2026, 9, 1)),
            maint(days(1), PREVENTIVE, next_due_on=days(200)),
        ],
        date(2026, 9, 1),
        ScheduleBasis.RECORDED_NEXT_DUE,
        id="record-performed-after-d-ignored",
    ),
    pytest.param(
        90,
        None,
        [
            maint(MARCH_1, PREVENTIVE),
            maint(days(1), PREVENTIVE),
            maint(days(2), PREVENTIVE, next_due_on=days(300), asset_id=2),
        ],
        date(2026, 5, 30),
        ScheduleBasis.PREVENTIVE_PLUS_INTERVAL,
        id="preventive-after-d-and-other-assets-ignored",
    ),
    pytest.param(
        90,
        None,
        [maint(D, PREVENTIVE)],
        days(90),
        ScheduleBasis.PREVENTIVE_PLUS_INTERVAL,
        id="maintenance-performed-on-d-counts",
    ),
]


@pytest.mark.parametrize(
    ("own", "default", "records", "due_on", "basis"),
    SCHEDULE_CASES,
)
def test_maintenance_schedule(
    own: int | None,
    default: int | None,
    records: list[MaintenanceEvent],
    due_on: date | None,
    basis: ScheduleBasis,
) -> None:
    asset_type = AssetType(code="bed", default_maintenance_interval_days=default)
    schedule = maintenance_schedule(make_asset(interval=own), asset_type, records, D)
    assert schedule.due_on == due_on
    assert schedule.basis is basis


def test_same_day_records_are_order_independent() -> None:
    a = maint(MARCH_1, PREVENTIVE, next_due_on=date(2026, 8, 1))
    b = maint(MARCH_1, PREVENTIVE, next_due_on=date(2026, 9, 1))
    asset_type = AssetType(code="bed", default_maintenance_interval_days=None)
    for records in ([a, b], [b, a]):
        schedule = maintenance_schedule(make_asset(), asset_type, records, D)
        assert schedule.due_on == date(2026, 9, 1)


def test_last_maintenance_is_latest_of_any_kind_up_to_d() -> None:
    asset_type = AssetType(code="bed", default_maintenance_interval_days=90)
    records = [
        maint(MARCH_1, PREVENTIVE),
        maint(MAY_1, CORRECTIVE),
        maint(days(-3), INSPECTION),
        maint(days(1), PREVENTIVE),  # after d
        maint(days(-1), CORRECTIVE, asset_id=2),  # another asset
    ]
    schedule = maintenance_schedule(make_asset(), asset_type, records, D)
    assert schedule.last_maintenance_on == days(-3)
    assert schedule.due_on == date(2026, 5, 30)
    empty = maintenance_schedule(make_asset(), asset_type, [], D)
    assert empty.last_maintenance_on is None


def test_missing_type_uses_asset_interval_only() -> None:
    assert maintenance_schedule(make_asset(interval=90), None, [], D).due_on == date(2025, 4, 1)
    assert maintenance_schedule(make_asset(), None, [], D).basis is ScheduleBasis.UNKNOWN


def test_interval_zero_raises_no_flag() -> None:
    asset_type = AssetType(code="bed", default_maintenance_interval_days=365)
    schedule = maintenance_schedule(make_asset(interval=0), asset_type, [], D)
    assert schedule.due_on is None
    assert not is_overdue(schedule, D)
    assert not is_due_soon(schedule, D, RULES)
    assert not is_schedule_unknown(schedule)


def test_unknown_schedule_flag() -> None:
    schedule = maintenance_schedule(make_asset(), None, [], D)
    assert is_schedule_unknown(schedule)
    assert not is_overdue(schedule, D)
    assert not is_due_soon(schedule, D, RULES)


@pytest.mark.parametrize(
    ("offset", "overdue", "due_soon"),
    [
        (-1, True, False),  # due_on == d - 1
        (0, False, True),  # due_on == d: due soon, not overdue
        (1, False, True),
        (30, False, True),  # d + 30 inclusive
        (31, False, False),  # d + 31 neither
        (-365, True, False),
    ],
)
def test_overdue_and_due_soon_boundaries(offset: int, overdue: bool, due_soon: bool) -> None:
    schedule = schedule_on(days(offset), ScheduleBasis.RECORDED_NEXT_DUE)
    assert is_overdue(schedule, D) is overdue
    assert is_due_soon(schedule, D, RULES) is due_soon


@pytest.mark.parametrize(
    ("warning_days", "offset", "due_soon"),
    [(7, 7, True), (7, 8, False), (0, 0, True), (0, 1, False), (60, 60, True), (60, 61, False)],
)
def test_warning_window_is_configurable(warning_days: int, offset: int, due_soon: bool) -> None:
    rules = InfrastructureRules(maintenance_warning_days=warning_days)
    schedule = schedule_on(days(offset), ScheduleBasis.RECORDED_NEXT_DUE)
    assert is_due_soon(schedule, D, rules) is due_soon


@pytest.mark.parametrize(
    ("as_of", "due_on", "last", "overdue", "unknown_basis"),
    [
        # Preventive of 2026-03-01 + 90 days = 2026-05-30.
        (date(2026, 5, 31), date(2026, 5, 30), MARCH_1, True, False),
        (date(2026, 4, 1), date(2026, 5, 30), MARCH_1, False, False),
        (date(2026, 3, 1), date(2026, 5, 30), MARCH_1, False, False),
        # Before the preventive record existed: in service + 90 days, no maintenance yet.
        (date(2026, 2, 28), date(2025, 4, 1), None, True, False),
    ],
)
def test_past_as_of_date_uses_records_known_for_that_date(
    as_of: date, due_on: date, last: date | None, overdue: bool, unknown_basis: bool
) -> None:
    asset_type = AssetType(code="bed", default_maintenance_interval_days=None)
    schedule = maintenance_schedule(
        make_asset(interval=90), asset_type, [maint(MARCH_1, PREVENTIVE)], as_of
    )
    assert schedule.due_on == due_on
    assert schedule.last_maintenance_on == last
    assert is_overdue(schedule, as_of) is overdue
    assert is_schedule_unknown(schedule) is unknown_basis


# --------------------------------------------------------------------------------------------
# Views: rows, due lists, data quality
# --------------------------------------------------------------------------------------------

BED = AssetType(code="bed", default_maintenance_interval_days=None)
BAY = AssetType(code="bay", default_maintenance_interval_days=30)
FILTRATION = AssetType(code="neg_pressure_filtration", default_maintenance_interval_days=None)
TENT = AssetType(code="decon_tent", default_maintenance_interval_days=30)
DEMO = AssetType(code="DEMO-TYPE", default_maintenance_interval_days=None)
ALL_TYPES = [BED, BAY, FILTRATION, TENT, DEMO]


def test_asset_rows_cover_all_assets_sorted_by_type_then_tag() -> None:
    assets = [
        make_asset(3, "DEMO-A003", "bed"),
        make_asset(2, "DEMO-A002", "bay"),
        make_asset(1, "DEMO-A001", "bed", start=days(5)),  # not yet in service
        make_asset(4, "DEMO-A004", "bed", until=days(-1)),  # retired
    ]
    events = [status_event(days(-3), OPERATIONAL, asset_id=3)]
    records = [
        maint(days(-40), CORRECTIVE, asset_id=3),
        maint(days(-20), PREVENTIVE, next_due_on=days(-2), asset_id=3),
    ]
    rows = asset_rows(assets, ALL_TYPES, events, records, D, RULES)
    assert [(r.type_code, r.tag) for r in rows] == [
        ("bay", "DEMO-A002"),
        ("bed", "DEMO-A001"),
        ("bed", "DEMO-A003"),
        ("bed", "DEMO-A004"),
    ]
    by_tag = {r.tag: r for r in rows}
    assert not by_tag["DEMO-A001"].in_service
    assert not by_tag["DEMO-A004"].in_service
    row = by_tag["DEMO-A003"]
    assert row.in_service
    assert row.status is OPERATIONAL
    assert row.available
    assert row.last_maintenance_on == days(-20)
    assert row.due_on == days(-2)
    assert row.basis is ScheduleBasis.RECORDED_NEXT_DUE
    assert row.overdue
    assert not row.due_soon
    assert not row.schedule_unknown
    assert row.days_to_due == -2
    bay = by_tag["DEMO-A002"]
    assert bay.status is UNKNOWN
    assert not bay.available
    assert bay.basis is ScheduleBasis.IN_SERVICE_PLUS_INTERVAL
    assert by_tag["DEMO-A001"].schedule_unknown
    assert by_tag["DEMO-A001"].days_to_due is None


def test_asset_rows_days_to_due_is_signed() -> None:
    assets = [make_asset(1, "DEMO-A001"), make_asset(2, "DEMO-A002"), make_asset(3, "DEMO-A003")]
    records = [
        maint(days(-5), PREVENTIVE, next_due_on=days(-1), asset_id=1),
        maint(days(-5), PREVENTIVE, next_due_on=days(0), asset_id=2),
        maint(days(-5), PREVENTIVE, next_due_on=days(12), asset_id=3),
    ]
    rows = asset_rows(assets, ALL_TYPES, [], records, D, RULES)
    assert [r.days_to_due for r in rows] == [-1, 0, 12]


def test_due_lists_by_tag_for_in_service_assets_only() -> None:
    assets = [
        make_asset(1, "DEMO-A009"),  # overdue
        make_asset(2, "DEMO-A003"),  # due_on == d: due soon
        make_asset(3, "DEMO-A005"),  # d + 30: due soon
        make_asset(4, "DEMO-A001"),  # d + 31: neither
        make_asset(5, "DEMO-A002", until=days(-1)),  # due soon, but retired
        make_asset(6, "DEMO-A004", start=days(1)),  # overdue, but not yet in service
        make_asset(7, "DEMO-A008", until=D),  # last day in service, overdue
        make_asset(8, "DEMO-A007", start=D),  # first day in service, due soon
        make_asset(9, "DEMO-A006"),  # no schedule at all
    ]
    due = {1: days(-1), 2: days(0), 3: days(30), 4: days(31), 5: days(5), 6: days(-9)}
    due.update({7: days(-2), 8: days(3)})
    records = [maint(days(-60), PREVENTIVE, next_due_on=v, asset_id=k) for k, v in due.items()]
    lists = maintenance_due_lists(assets, ALL_TYPES, [], records, D, RULES)
    assert [r.tag for r in lists.overdue] == ["DEMO-A008", "DEMO-A009"]
    assert [r.tag for r in lists.due_soon] == ["DEMO-A003", "DEMO-A005", "DEMO-A007"]
    assert all(r.in_service for r in (*lists.overdue, *lists.due_soon))


def test_data_quality_lists_in_service_assets_with_unknown_status() -> None:
    assets = [
        make_asset(1, "DEMO-A003"),  # no event
        make_asset(2, "DEMO-A001"),  # no event
        make_asset(3, "DEMO-A002"),  # operational
        make_asset(4, "DEMO-A004", until=days(-1)),  # retired, no event: not listed
        make_asset(5, "DEMO-A005", start=days(1)),  # not yet in service: not listed
        make_asset(6, "DEMO-A006"),  # first event after d
    ]
    events = [status_event(days(-1), OPERATIONAL, asset_id=3), status_event(days(1), OUT, 6)]
    assert data_quality(assets, events, D) == ["DEMO-A001", "DEMO-A003", "DEMO-A006"]
    # On d + 1: A005 enters service (first day inclusive) with no event, so it is listed;
    # A006's event dated d + 1 now applies, so it is no longer unknown.
    assert data_quality(assets, events, days(1)) == ["DEMO-A001", "DEMO-A003", "DEMO-A005"]


# --------------------------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------------------------


def _indicator_fixture() -> tuple[list[Asset], list[StatusEvent], list[MaintenanceEvent]]:
    assets = [
        make_asset(1, "DEMO-A001", "bed"),  # operational
        make_asset(2, "DEMO-A002", "bed"),  # degraded, overdue (recorded)
        make_asset(3, "DEMO-A003", "bed"),  # out of service, due on d (not overdue)
        make_asset(4, "DEMO-A004", "bed"),  # no status event
        make_asset(5, "DEMO-A005", "bed", until=days(-1)),  # retired
        make_asset(6, "DEMO-A006", "bed", start=days(1)),  # not yet in service
        make_asset(7, "DEMO-A007", "bed", until=D),  # last day in service
        make_asset(8, "DEMO-A008", "bed", start=D),  # first day in service
        make_asset(10, "DEMO-A010", "bay"),  # interval 30 from type: preventive d-40 -> d-10
        make_asset(20, "DEMO-A020", "decon_tent", interval=0),  # override 0 over default 30
    ]
    events = [
        status_event(days(-9), OPERATIONAL, 1),
        status_event(days(-9), DEGRADED, 2),
        status_event(days(-9), OUT, 3),
        status_event(days(-9), OPERATIONAL, 5),
        status_event(days(-9), OPERATIONAL, 6),
        status_event(days(-9), OPERATIONAL, 7),
        status_event(D, OPERATIONAL, 8),
        status_event(days(-9), OPERATIONAL, 10),
        status_event(days(-9), OPERATIONAL, 20),
    ]
    records = [
        maint(days(-30), PREVENTIVE, next_due_on=days(-1), asset_id=2),
        maint(days(-30), PREVENTIVE, next_due_on=days(0), asset_id=3),
        maint(days(-50), PREVENTIVE, next_due_on=days(-5), asset_id=5),
        maint(days(-50), PREVENTIVE, next_due_on=days(-5), asset_id=6),
        maint(days(-40), PREVENTIVE, asset_id=10),
    ]
    return assets, events, records


Reading = tuple[float | None, dict[str, float] | None]


def _as_map(values: list[IndicatorValue]) -> dict[tuple[str, str], Reading]:
    return {
        (v.code, v.dimension): (v.value, None if v.context is None else dict(v.context))
        for v in values
    }


@pytest.mark.parametrize(
    ("rules", "bed_available"),
    [(RULES, 3.0), (DEGRADED_OK, 4.0)],
)
def test_indicator_values(rules: InfrastructureRules, bed_available: float) -> None:
    assets, events, records = _indicator_fixture()
    values = indicator_values(assets, ALL_TYPES, events, records, D, rules)
    got = _as_map(values)
    # bed in service on D: 1, 2, 3, 4, 7, 8 -> 6. Available: 1, 7, 8 (+ 2 when degraded counts).
    assert got[("INFRA_AVAILABLE", "type=bed")] == (bed_available, {"in_service": 6.0})
    assert got[("INFRA_MAINT_OVERDUE", "type=bed")] == (1.0, None)
    assert got[("INFRA_AVAILABLE", "type=bay")] == (1.0, {"in_service": 1.0})
    assert got[("INFRA_MAINT_OVERDUE", "type=bay")] == (1.0, None)
    assert got[("INFRA_AVAILABLE", "type=decon_tent")] == (1.0, {"in_service": 1.0})
    assert got[("INFRA_MAINT_OVERDUE", "type=decon_tent")] == (0.0, None)
    # Types without assets still get a value.
    assert got[("INFRA_AVAILABLE", "type=DEMO-TYPE")] == (0.0, {"in_service": 0.0})
    assert got[("INFRA_AVAILABLE", "type=neg_pressure_filtration")] == (0.0, {"in_service": 0.0})
    assert got[("INFRA_MAINT_OVERDUE", "type=DEMO-TYPE")] == (0.0, None)
    assert len(values) == 2 * len(ALL_TYPES)
    assert all(v.value is not None for v in values)


def test_indicator_values_sorted_by_type_code() -> None:
    assets, events, records = _indicator_fixture()
    values = indicator_values(assets, list(reversed(ALL_TYPES)), events, records, D, RULES)
    expected_dims = [
        "type=DEMO-TYPE",
        "type=bay",
        "type=bed",
        "type=decon_tent",
        "type=neg_pressure_filtration",
    ]
    assert [v.code for v in values] == ["INFRA_AVAILABLE"] * 5 + ["INFRA_MAINT_OVERDUE"] * 5
    assert [v.dimension for v in values[:5]] == expected_dims
    assert [v.dimension for v in values[5:]] == expected_dims


def test_indicators_exclude_retired_and_not_yet_in_service_assets() -> None:
    assets = [
        make_asset(1, "DEMO-A001", until=days(-1)),
        make_asset(2, "DEMO-A002", start=days(1)),
    ]
    events = [status_event(days(-9), OPERATIONAL, 1), status_event(days(-9), OPERATIONAL, 2)]
    records = [
        maint(days(-9), PREVENTIVE, next_due_on=days(-3), asset_id=1),
        maint(days(-9), PREVENTIVE, next_due_on=days(-3), asset_id=2),
    ]
    got = _as_map(indicator_values(assets, [BED], events, records, D, RULES))
    assert got[("INFRA_AVAILABLE", "type=bed")] == (0.0, {"in_service": 0.0})
    assert got[("INFRA_MAINT_OVERDUE", "type=bed")] == (0.0, None)


def test_unknown_status_is_not_available_but_counts_as_in_service() -> None:
    assets = [make_asset(1, "DEMO-A001")]
    got = _as_map(indicator_values(assets, [BED], [], [], D, DEGRADED_OK))
    assert got[("INFRA_AVAILABLE", "type=bed")] == (0.0, {"in_service": 1.0})


def test_indicator_values_use_the_as_of_date() -> None:
    assets = [make_asset(1, "DEMO-A001")]
    events = [status_event(days(-10), OPERATIONAL), status_event(days(-2), OUT)]
    records = [maint(days(-20), PREVENTIVE, next_due_on=days(-5))]

    def read(as_of: date) -> tuple[float | None, float | None]:
        got = _as_map(indicator_values(assets, [BED], events, records, as_of, RULES))
        return got[("INFRA_AVAILABLE", "type=bed")][0], got[("INFRA_MAINT_OVERDUE", "type=bed")][0]

    assert read(days(-11)) == (0.0, 0.0)  # no status yet, due date still ahead
    assert read(days(-6)) == (1.0, 0.0)  # operational, due date still ahead
    assert read(days(-4)) == (1.0, 1.0)  # operational, overdue
    assert read(D) == (0.0, 1.0)  # out of service, still overdue


# --------------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------------


def test_definitions() -> None:
    available, overdue = indicator_definitions()
    assert available.code == "INFRA_AVAILABLE"
    assert available.direction is Direction.HIGHER_IS_BETTER
    assert overdue.code == "INFRA_MAINT_OVERDUE"
    assert overdue.direction is Direction.LOWER_IS_BETTER
    for definition in (available, overdue):
        assert definition.module is Module.INFRASTRUCTURE
        assert definition.unit is UnitKind.COUNT
        assert definition.dimension_keys == ("type",)
    assert available.source == "R17-R19, A01, A05"
    assert overdue.source == "R20, R26"


def test_definitions_are_in_the_real_registry_and_evaluate_to_no_target() -> None:
    registry = build_registry()
    assert registry.codes().index("INFRA_AVAILABLE") + 1 == registry.codes().index(
        "INFRA_MAINT_OVERDUE"
    )
    assert {d.code for d in registry.by_module(Module.INFRASTRUCTURE)} == {
        "INFRA_AVAILABLE",
        "INFRA_MAINT_OVERDUE",
    }
    assets, events, records = _indicator_fixture()
    for value in indicator_values(assets, ALL_TYPES, events, records, D, RULES):
        definition = registry.get(value.code)
        definition.validate_dimension(value.dimension)
        reading = evaluate(definition, value, {})
        assert reading.status is IndicatorStatus.NO_TARGET
