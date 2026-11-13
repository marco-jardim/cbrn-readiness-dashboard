# SPDX-License-Identifier: GPL-3.0-or-later
"""Personnel rules and indicators (PLAN T2.2): fictitious data only (``DEMO-P001`` ...)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorStatus,
    IndicatorValue,
    Module,
    UnitKind,
    evaluate_all,
)
from cbrn_dashboard.domain.personnel import (
    Certificate,
    CertStatus,
    Degree,
    DegreeLevel,
    DegreeStatus,
    PersonnelRules,
    PpeLevel,
    StaffMember,
    TrainingRecord,
    counting_certificate,
    expiring_list,
    indicator_definitions,
    indicator_values,
    is_active,
    is_expiring,
    is_no_renewal,
    is_valid,
    level_status,
    needs_retraining,
    proposed_valid_until,
    retraining_list,
    staff_level_rows,
)
from cbrn_dashboard.domain.registry import build_registry

D = date(2026, 6, 15)
RULES = PersonnelRules()
A, B, C = PpeLevel.A, PpeLevel.B, PpeLevel.C


def day(offset: int, base: date = D) -> date:
    return base + timedelta(days=offset)


def person(
    staff_id: int = 1,
    active_from: date = date(2020, 1, 1),
    active_until: date | None = None,
) -> StaffMember:
    return StaffMember(
        id=staff_id,
        identifier=f"DEMO-P{staff_id:03d}",
        active_from=active_from,
        active_until=active_until,
    )


def cert(
    cert_id: int,
    valid_until: date,
    *,
    staff_id: int = 1,
    level: PpeLevel = A,
    issued_on: date = date(2024, 1, 1),
    no_renewal_from: date | None = None,
) -> Certificate:
    return Certificate(
        id=cert_id,
        staff_id=staff_id,
        level=level,
        issued_on=issued_on,
        valid_until=valid_until,
        no_renewal_from=no_renewal_from,
    )


def values_by_key(values: list[IndicatorValue]) -> dict[tuple[str, str], float | None]:
    return {(v.code, v.dimension): v.value for v in values}


def level_counts(values: list[IndicatorValue], code: str) -> tuple[float | None, ...]:
    table = values_by_key(values)
    return tuple(table[(code, f"level={level.value}")] for level in PpeLevel)


def compute(
    staff: list[StaffMember],
    certs: list[Certificate],
    d: date = D,
    rules: PersonnelRules = RULES,
    training: list[TrainingRecord] | None = None,
    degrees: list[Degree] | None = None,
) -> list[IndicatorValue]:
    return indicator_values(staff, certs, training or [], degrees or [], d, rules)


# --------------------------------------------------------------------------------------------
# Activity (A14)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("active_from", "active_until", "expected"),
    [
        (day(1), None, False),  # starts tomorrow
        (D, None, True),  # starts today (inclusive)
        (day(-30), day(-1), False),  # ended yesterday
        (day(-30), D, True),  # ends today (inclusive)
        (day(-30), day(1), True),
        (day(-30), None, True),
    ],
)
def test_is_active_boundaries(active_from: date, active_until: date | None, expected: bool) -> None:
    assert is_active(person(1, active_from, active_until), D) is expected


def test_inactive_staff_are_never_counted() -> None:
    staff = [
        person(1, active_from=day(1)),  # not yet active
        person(2, active_from=date(2020, 1, 1), active_until=day(-1)),  # no longer active
        person(3, active_from=D),  # active from today
        person(4, active_until=D),  # active until today
    ]
    certs = [cert(i, day(30), staff_id=i) for i in (1, 2, 3, 4)]
    values = compute(
        staff,
        certs,
        training=[TrainingRecord(i, day(-5)) for i in (1, 2, 3, 4)],
        degrees=[Degree(i, DegreeLevel.MASTER, DegreeStatus.COMPLETED) for i in (1, 2, 3, 4)],
    )
    assert level_counts(values, "PERS_CERT_VALID") == (2.0, 0.0, 0.0)
    assert level_counts(values, "PERS_CERT_EXPIRING") == (2.0, 0.0, 0.0)
    assert level_counts(values, "PERS_RETRAINING_NEEDED") == (2.0, 0.0, 0.0)
    table = values_by_key(values)
    assert table[("PERS_DEGREE", "level=master;status=completed")] == 2.0
    assert table[("PERS_TRAINING_12M", "")] == 2.0
    assert [r.identifier for r in staff_level_rows(staff, certs, D, RULES) if r.level is A] == [
        "DEMO-P003",
        "DEMO-P004",
    ]


# --------------------------------------------------------------------------------------------
# Validity, expiring window, retraining (A03, P01)
# --------------------------------------------------------------------------------------------


def test_last_day_is_valid_and_expiring_and_next_day_is_expired() -> None:
    c = cert(1, D)
    assert is_valid(c, D)
    assert is_expiring(c, D, RULES)
    assert needs_retraining(c, D, RULES)
    assert level_status(c, D, RULES) is CertStatus.EXPIRING

    tomorrow = day(1)
    assert not is_valid(c, tomorrow)
    assert not is_expiring(c, tomorrow, RULES)
    assert needs_retraining(c, tomorrow, RULES)
    assert level_status(c, tomorrow, RULES) is CertStatus.EXPIRED


def test_expired_no_renewal_certificate_does_not_need_retraining() -> None:
    c = cert(1, D, no_renewal_from=D)
    assert not needs_retraining(c, day(1), RULES)
    assert not is_expiring(c, D, RULES)


@pytest.mark.parametrize(
    ("offset", "expiring"),
    [(89, True), (90, True), (91, False), (0, True), (-1, False)],
)
def test_expiring_window_boundary(offset: int, expiring: bool) -> None:
    c = cert(1, day(offset))
    assert is_expiring(c, D, RULES) is expiring
    assert needs_retraining(c, D, RULES) is (expiring or offset < 0)
    values = compute([person()], [c])
    assert level_counts(values, "PERS_CERT_EXPIRING") == (float(expiring), 0.0, 0.0)


def test_custom_warning_window() -> None:
    rules = PersonnelRules(cert_warning_days=30)
    assert is_expiring(cert(1, day(30)), D, rules)
    assert not is_expiring(cert(1, day(31)), D, rules)


def test_no_certificate_does_not_need_retraining() -> None:
    assert not needs_retraining(None, D, RULES)
    assert level_status(None, D, RULES) is CertStatus.NONE
    values = compute([person()], [])
    assert level_counts(values, "PERS_CERT_VALID") == (0.0, 0.0, 0.0)
    assert level_counts(values, "PERS_RETRAINING_NEEDED") == (0.0, 0.0, 0.0)


def test_two_certificates_at_same_level_count_once() -> None:
    certs = [cert(1, day(200)), cert(2, day(400), issued_on=date(2025, 1, 1))]
    values = compute([person()], certs)
    assert level_counts(values, "PERS_CERT_VALID") == (1.0, 0.0, 0.0)
    assert level_counts(values, "PERS_CERT_EXPIRING") == (0.0, 0.0, 0.0)


# --------------------------------------------------------------------------------------------
# THE certificate rule (A03): renewal and tie-break
# --------------------------------------------------------------------------------------------


def test_renewal_issued_after_d_does_not_hide_the_valid_certificate() -> None:
    old = cert(1, date(2026, 7, 1), issued_on=date(2024, 7, 1))
    new = cert(2, date(2028, 7, 1), issued_on=date(2026, 6, 20))
    certs = [new, old]
    at_d = counting_certificate(certs, 1, A, D, RULES)
    assert at_d is old
    assert is_valid(old, D)
    # Read at a later date, the NEW certificate counts.
    later = counting_certificate(certs, 1, A, date(2026, 6, 20), RULES)
    assert later is new
    # The indicator at D sees the old certificate (expiring); a later reading sees the new one.
    assert level_counts(compute([person()], certs, D), "PERS_CERT_EXPIRING") == (1.0, 0.0, 0.0)
    assert level_counts(compute([person()], certs, date(2026, 6, 20)), "PERS_CERT_EXPIRING") == (
        0.0,
        0.0,
        0.0,
    )


def test_renewal_before_expiry_has_no_gap() -> None:
    old = cert(1, date(2026, 7, 1), issued_on=date(2024, 7, 1))
    new = cert(2, date(2028, 7, 1), issued_on=date(2026, 6, 10))
    for offset in range(-10, 40):
        d = day(offset)
        counting = counting_certificate([old, new], 1, A, d, RULES)
        assert counting is not None
        assert is_valid(counting, d)
        assert counting is (new if d >= new.issued_on else old)


@pytest.mark.parametrize(
    ("first", "second", "winner_id"),
    [
        # same valid_until: later issued_on wins
        (
            cert(1, date(2027, 1, 1), issued_on=date(2025, 1, 1)),
            cert(2, date(2027, 1, 1), issued_on=date(2025, 6, 1)),
            2,
        ),
        (
            cert(1, date(2027, 1, 1), issued_on=date(2025, 6, 1)),
            cert(2, date(2027, 1, 1), issued_on=date(2025, 1, 1)),
            1,
        ),
        # same valid_until and issued_on: higher id wins
        (
            cert(7, date(2027, 1, 1), issued_on=date(2025, 1, 1)),
            cert(3, date(2027, 1, 1), issued_on=date(2025, 1, 1)),
            7,
        ),
        # latest valid_until beats a later issued_on
        (
            cert(1, date(2028, 1, 1), issued_on=date(2025, 1, 1)),
            cert(2, date(2027, 1, 1), issued_on=date(2026, 1, 1)),
            1,
        ),
    ],
)
def test_counting_certificate_tie_break(
    first: Certificate, second: Certificate, winner_id: int
) -> None:
    for order in ([first, second], [second, first]):
        chosen = counting_certificate(order, 1, A, D, RULES)
        assert chosen is not None
        assert chosen.id == winner_id


def test_counting_certificate_ignores_other_people_and_other_levels() -> None:
    certs = [cert(1, day(50), staff_id=2), cert(2, day(60), level=B)]
    assert counting_certificate(certs, 1, A, D, RULES) is None
    chosen = counting_certificate(certs, 1, B, D, RULES)
    assert chosen is not None
    assert chosen.id == 2


# --------------------------------------------------------------------------------------------
# No renewal (D24)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("no_renewal_from", "expected"),
    [(None, False), (day(-10), True), (D, True), (day(1), False)],
)
def test_is_no_renewal(no_renewal_from: date | None, expected: bool) -> None:
    assert is_no_renewal(cert(1, day(30), no_renewal_from=no_renewal_from), D) is expected


def test_no_renewal_excluded_from_expiring_and_retraining_even_when_expired() -> None:
    staff = [person(i) for i in (1, 2, 3, 4)]
    certs = [
        cert(1, day(30), staff_id=1, no_renewal_from=D),  # expiring, no-renewal today
        cert(2, day(30), staff_id=2, no_renewal_from=day(1)),  # mark not yet in effect
        cert(3, day(-20), staff_id=3, no_renewal_from=day(-40)),  # expired, no-renewal
        cert(4, day(-20), staff_id=4, no_renewal_from=day(5)),  # expired, mark in the future
    ]
    values = compute(staff, certs)
    assert level_counts(values, "PERS_CERT_EXPIRING") == (1.0, 0.0, 0.0)  # person 2 only
    assert level_counts(values, "PERS_RETRAINING_NEEDED") == (2.0, 0.0, 0.0)  # persons 2, 4
    # A still-valid no-renewal certificate DOES count as valid.
    assert level_counts(values, "PERS_CERT_VALID") == (2.0, 0.0, 0.0)  # persons 1, 2
    rows = {r.staff_id: r.status for r in staff_level_rows(staff, certs, D, RULES) if r.level is A}
    assert rows == {
        1: CertStatus.NO_RENEWAL,
        2: CertStatus.EXPIRING,
        3: CertStatus.EXPIRED,
        4: CertStatus.EXPIRED,
    }


# --------------------------------------------------------------------------------------------
# Hierarchy (A02)
# --------------------------------------------------------------------------------------------

HIERARCHY = PersonnelRules(hierarchy_enabled=True, hierarchy={"A": ("B", "C"), "B": ("C",)})


def test_hierarchy_off_levels_are_independent() -> None:
    rules = PersonnelRules(hierarchy_enabled=False, hierarchy={"A": ("B", "C"), "B": ("C",)})
    certs = [cert(1, day(300), level=A)]
    assert counting_certificate(certs, 1, B, D, rules) is None
    assert counting_certificate(certs, 1, C, D, rules) is None
    assert level_counts(compute([person()], certs, rules=rules), "PERS_CERT_VALID") == (
        1.0,
        0.0,
        0.0,
    )


def test_hierarchy_on_higher_certificate_counts_for_lower_levels() -> None:
    certs = [cert(1, day(300), level=A)]
    for level in (A, B, C):
        chosen = counting_certificate(certs, 1, level, D, HIERARCHY)
        assert chosen is not None
        assert chosen.id == 1
    assert level_counts(compute([person()], certs, rules=HIERARCHY), "PERS_CERT_VALID") == (
        1.0,
        1.0,
        1.0,
    )


def test_hierarchy_on_picks_the_counting_certificate_across_levels() -> None:
    a = cert(1, date(2027, 1, 1), level=A)
    b = cert(2, date(2027, 6, 1), level=B)
    c = cert(3, date(2026, 12, 1), level=C)
    certs = [a, b, c]
    picks = {level: counting_certificate(certs, 1, level, D, HIERARCHY) for level in (A, B, C)}
    assert picks[A] is a  # only the A certificate counts for A
    assert picks[B] is b  # A and B count for B; B has the later valid_until
    assert picks[C] is b  # A, B and C count for C; B has the latest valid_until


def test_hierarchy_on_with_empty_mapping_behaves_as_off() -> None:
    rules = PersonnelRules(hierarchy_enabled=True, hierarchy={})
    certs = [cert(1, day(300), level=A)]
    assert counting_certificate(certs, 1, B, D, rules) is None
    assert counting_certificate(certs, 1, A, D, rules) is not None


# --------------------------------------------------------------------------------------------
# Pre-fill (A04)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("issued_on", "level", "expected"),
    [
        (date(2026, 1, 15), A, date(2028, 1, 15)),
        (date(2026, 1, 31), A, date(2028, 1, 31)),
        (date(2024, 2, 29), B, date(2025, 2, 28)),  # month-end clamping
        (date(2025, 1, 31), PpeLevel.B, date(2026, 1, 31)),
        (date(2026, 1, 15), C, None),  # configured as None
    ],
)
def test_proposed_valid_until(issued_on: date, level: PpeLevel, expected: date | None) -> None:
    rules = PersonnelRules(validity_months={"A": 24, "B": 12, "C": None})
    assert proposed_valid_until(issued_on, level, rules) == expected


def test_proposed_valid_until_without_configuration_is_none() -> None:
    for level in PpeLevel:
        assert proposed_valid_until(date(2026, 1, 15), level, RULES) is None
    only_a = PersonnelRules(validity_months={"A": 12})
    assert proposed_valid_until(date(2026, 1, 15), B, only_a) is None


# --------------------------------------------------------------------------------------------
# Training window (A09) and degrees
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("completed_on", "counted"),
    [
        (date(2025, 6, 15), False),  # exactly 12 months before D: out
        (date(2025, 6, 16), True),  # one day later: in
        (D, True),  # on D: in
        (day(1), False),  # after D: out
    ],
)
def test_training_window_is_exclusive_start_inclusive_end(
    completed_on: date, counted: bool
) -> None:
    values = compute([person()], [], training=[TrainingRecord(1, completed_on)])
    assert values_by_key(values)[("PERS_TRAINING_12M", "")] == float(counted)


def test_training_counts_records_of_active_staff_only() -> None:
    staff = [person(1), person(2, active_until=day(-1))]
    training = [
        TrainingRecord(1, day(-10)),
        TrainingRecord(1, day(-20)),  # two records of the same person are two records
        TrainingRecord(2, day(-30)),  # inactive: not counted
        TrainingRecord(99, day(-30)),  # unknown person: not counted
    ]
    values = compute(staff, [], training=training)
    assert values_by_key(values)[("PERS_TRAINING_12M", "")] == 2.0


def test_degrees_counted_per_level_and_status_once_per_person() -> None:
    staff = [person(1), person(2), person(3, active_until=day(-1))]
    degrees = [
        Degree(1, DegreeLevel.MASTER, DegreeStatus.COMPLETED),
        Degree(1, DegreeLevel.MASTER, DegreeStatus.COMPLETED),  # same person, same level+status
        Degree(1, DegreeLevel.MASTER, DegreeStatus.IN_PROGRESS),
        Degree(2, DegreeLevel.MASTER, DegreeStatus.COMPLETED),
        Degree(2, DegreeLevel.SPECIALISATION, DegreeStatus.COMPLETED),
        Degree(3, DegreeLevel.DOCTORATE, DegreeStatus.COMPLETED),  # inactive
    ]
    values = compute(staff, [], degrees=degrees)
    degree_values = [(v.dimension, v.value) for v in values if v.code == "PERS_DEGREE"]
    assert degree_values == [
        ("level=specialisation;status=completed", 1.0),
        ("level=specialisation;status=in_progress", 0.0),
        ("level=master;status=completed", 2.0),
        ("level=master;status=in_progress", 1.0),
        ("level=doctorate;status=completed", 0.0),
        ("level=doctorate;status=in_progress", 0.0),
    ]


def _completed_master_count(degrees: list[Degree], d: date) -> float | None:
    values = compute([person()], [], d=d, degrees=degrees)
    return values_by_key(values)[("PERS_DEGREE", "level=master;status=completed")]


@pytest.mark.parametrize(
    ("clock", "status", "year", "counted"),
    [
        (FixedClock.at("2026-12-31T12:00:00Z"), DegreeStatus.COMPLETED, 2027, False),
        (FixedClock.at("2026-12-31T12:00:00Z"), DegreeStatus.COMPLETED, 2026, True),
        (FixedClock.at("2026-01-01T12:00:00Z"), DegreeStatus.COMPLETED, 2026, True),
        (FixedClock.at("2026-01-01T12:00:00Z"), DegreeStatus.COMPLETED, 2025, True),
        (FixedClock.at("2026-06-15T12:00:00Z"), DegreeStatus.COMPLETED, 2200, False),
        (FixedClock.at("2026-06-15T12:00:00Z"), DegreeStatus.COMPLETED, None, True),
        (FixedClock.at("2027-01-01T12:00:00Z"), DegreeStatus.COMPLETED, 2027, True),
        # the local date decides, not the UTC date: 2027-01-01T01:00Z is still 2026 at UTC-3
        (FixedClock.at("2027-01-01T01:00:00Z", -3), DegreeStatus.COMPLETED, 2027, False),
        # in-progress degrees are not affected by their (future) year
        (FixedClock.at("2026-06-15T12:00:00Z"), DegreeStatus.IN_PROGRESS, 2030, None),
    ],
)
def test_completed_degree_of_a_later_year_is_not_counted_on_an_earlier_date(
    clock: FixedClock, status: DegreeStatus, year: int | None, counted: bool | None
) -> None:
    d = clock.local_date()
    degrees = [Degree(1, DegreeLevel.MASTER, status, year)]
    values = values_by_key(compute([person()], [], d=d, degrees=degrees))
    completed = values[("PERS_DEGREE", "level=master;status=completed")]
    in_progress = values[("PERS_DEGREE", "level=master;status=in_progress")]
    if status is DegreeStatus.IN_PROGRESS:
        assert (completed, in_progress) == (0.0, 1.0)
    else:
        assert (completed, in_progress) == (float(bool(counted)), 0.0)


def test_degree_year_defaults_to_not_recorded() -> None:
    assert Degree(1, DegreeLevel.MASTER, DegreeStatus.COMPLETED).year is None


def test_degree_level_and_status_are_compared_by_value_not_identity() -> None:
    # Values that arrive as plain strings (not the enum members) must still be counted.
    degree = Degree(1, DegreeLevel.MASTER, DegreeStatus.COMPLETED)
    object.__setattr__(degree, "level", "master")
    object.__setattr__(degree, "status", "completed")
    assert degree.level is not DegreeLevel.MASTER
    assert _completed_master_count([degree], D) == 1.0


# --------------------------------------------------------------------------------------------
# As-of readings from a FixedClock (T2.2)
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("clock", "status"),
    [
        (FixedClock.at("2026-03-01T12:00:00Z"), CertStatus.VALID),  # 106 days left
        (FixedClock.at("2026-03-17T12:00:00Z"), CertStatus.EXPIRING),  # 90 days left
        (FixedClock.at("2026-03-16T12:00:00Z"), CertStatus.VALID),  # 91 days left
        (FixedClock.at("2026-06-14T12:00:00Z"), CertStatus.EXPIRING),  # the day before
        (FixedClock.at("2026-06-15T12:00:00Z"), CertStatus.EXPIRING),  # last valid day
        (FixedClock.at("2026-06-16T01:00:00Z", -3), CertStatus.EXPIRING),  # local date: 15th
        (FixedClock.at("2026-06-16T12:00:00Z"), CertStatus.EXPIRED),
        (FixedClock.at("2026-06-15T23:00:00Z", 3), CertStatus.EXPIRED),  # local date: 16th
    ],
)
def test_certificate_status_on_the_date_of_a_fixed_clock(
    clock: FixedClock, status: CertStatus
) -> None:
    d = clock.local_date()
    certificate = cert(1, date(2026, 6, 15))
    assert level_status(certificate, d, RULES) is status
    values = compute([person()], [certificate], d=d)
    assert level_counts(values, "PERS_CERT_VALID")[0] == float(status is not CertStatus.EXPIRED)
    assert level_counts(values, "PERS_CERT_EXPIRING")[0] == float(status is CertStatus.EXPIRING)
    assert level_counts(values, "PERS_RETRAINING_NEEDED")[0] == float(
        status in (CertStatus.EXPIRING, CertStatus.EXPIRED)
    )


# --------------------------------------------------------------------------------------------
# As-of readings (I03)
# --------------------------------------------------------------------------------------------


def test_past_as_of_dates_give_different_readings_from_the_same_data() -> None:
    staff = [person(1)]
    certs = [cert(1, date(2026, 1, 31))]
    training = [TrainingRecord(1, date(2025, 10, 1))]

    def reading(d: date) -> tuple[float | None, ...]:
        values = compute(staff, certs, d=d, training=training)
        table = values_by_key(values)
        return (
            level_counts(values, "PERS_CERT_VALID")[0],
            level_counts(values, "PERS_CERT_EXPIRING")[0],
            level_counts(values, "PERS_RETRAINING_NEEDED")[0],
            table[("PERS_TRAINING_12M", "")],
        )

    assert reading(date(2025, 6, 1)) == (1.0, 0.0, 0.0, 0.0)  # valid, far from expiry
    assert reading(date(2025, 12, 1)) == (1.0, 1.0, 1.0, 1.0)  # inside the warning window
    assert reading(date(2026, 3, 1)) == (0.0, 0.0, 1.0, 1.0)  # expired


# --------------------------------------------------------------------------------------------
# Lists
# --------------------------------------------------------------------------------------------


def _list_fixture() -> tuple[list[StaffMember], list[Certificate]]:
    staff = [
        person(4),
        person(2),
        person(3, active_until=day(-1)),  # inactive
        person(1),
    ]
    certs = [
        cert(1, day(-5), staff_id=1),  # expired
        cert(2, day(10), staff_id=2),  # expiring
        cert(3, day(-5), staff_id=3),  # inactive person
        cert(4, day(-5), staff_id=4, no_renewal_from=day(-100)),  # expired, no renewal
        cert(5, day(200), staff_id=1, level=C),  # valid, out of the window
    ]
    return staff, certs


def test_staff_level_rows_sorted_active_only_with_signed_days() -> None:
    staff, certs = _list_fixture()
    rows = staff_level_rows(staff, certs, D, RULES)
    assert [(r.identifier, r.level) for r in rows] == [
        (f"DEMO-P{n:03d}", level) for n in (1, 2, 4) for level in (A, B, C)
    ]
    by_key = {(r.staff_id, r.level): r for r in rows}
    expired = by_key[(1, A)]
    assert (expired.certificate_id, expired.valid_until) == (1, day(-5))
    assert expired.days_to_expiry == -5
    assert expired.status is CertStatus.EXPIRED
    assert by_key[(2, A)].days_to_expiry == 10
    assert by_key[(1, C)].status is CertStatus.VALID
    assert by_key[(1, C)].days_to_expiry == 200
    none_row = by_key[(1, B)]
    assert (none_row.certificate_id, none_row.valid_until, none_row.days_to_expiry) == (
        None,
        None,
        None,
    )
    assert none_row.status is CertStatus.NONE
    assert by_key[(4, A)].status is CertStatus.EXPIRED


def test_retraining_and_expiring_lists() -> None:
    staff, certs = _list_fixture()
    retraining = retraining_list(staff, certs, D, RULES)
    assert [(r.identifier, r.level, r.valid_until, r.days_to_expiry) for r in retraining] == [
        ("DEMO-P001", A, day(-5), -5),
        ("DEMO-P002", A, day(10), 10),
    ]  # P003 inactive, P004 no renewal
    expiring = expiring_list(staff, certs, D, RULES)
    assert [(r.identifier, r.level, r.valid_until) for r in expiring] == [("DEMO-P002", A, day(10))]


def test_lists_agree_with_the_indicators() -> None:
    staff, certs = _list_fixture()
    values = compute(staff, certs)
    for level_index, level in enumerate(PpeLevel):
        retraining = [r for r in retraining_list(staff, certs, D, RULES) if r.level is level]
        expiring = [r for r in expiring_list(staff, certs, D, RULES) if r.level is level]
        assert level_counts(values, "PERS_RETRAINING_NEEDED")[level_index] == len(retraining)
        assert level_counts(values, "PERS_CERT_EXPIRING")[level_index] == len(expiring)


# --------------------------------------------------------------------------------------------
# Indicator definitions and values
# --------------------------------------------------------------------------------------------


def test_one_value_per_level_in_fixed_order_even_without_data() -> None:
    values = compute([], [])
    assert [(v.code, v.dimension) for v in values] == [
        ("PERS_CERT_VALID", "level=A"),
        ("PERS_CERT_VALID", "level=B"),
        ("PERS_CERT_VALID", "level=C"),
        ("PERS_CERT_EXPIRING", "level=A"),
        ("PERS_CERT_EXPIRING", "level=B"),
        ("PERS_CERT_EXPIRING", "level=C"),
        ("PERS_RETRAINING_NEEDED", "level=A"),
        ("PERS_RETRAINING_NEEDED", "level=B"),
        ("PERS_RETRAINING_NEEDED", "level=C"),
        ("PERS_DEGREE", "level=specialisation;status=completed"),
        ("PERS_DEGREE", "level=specialisation;status=in_progress"),
        ("PERS_DEGREE", "level=master;status=completed"),
        ("PERS_DEGREE", "level=master;status=in_progress"),
        ("PERS_DEGREE", "level=doctorate;status=completed"),
        ("PERS_DEGREE", "level=doctorate;status=in_progress"),
        ("PERS_TRAINING_12M", ""),
    ]
    assert all(v.value == 0.0 for v in values)  # zero is a real count, never None


def test_definitions_are_in_the_real_registry() -> None:
    registry = build_registry()
    expected = {
        "PERS_CERT_VALID": (Direction.HIGHER_IS_BETTER, ("level",)),
        "PERS_CERT_EXPIRING": (Direction.LOWER_IS_BETTER, ("level",)),
        "PERS_RETRAINING_NEEDED": (Direction.LOWER_IS_BETTER, ("level",)),
        "PERS_DEGREE": (Direction.HIGHER_IS_BETTER, ("level", "status")),
        "PERS_TRAINING_12M": (Direction.HIGHER_IS_BETTER, ()),
    }
    assert {d.code for d in indicator_definitions()} == set(expected)
    assert registry.codes()[:5] == tuple(d.code for d in indicator_definitions())
    for code, (direction, keys) in expected.items():
        definition = registry.get(code)
        assert definition.module is Module.PERSONNEL
        assert definition.unit is UnitKind.COUNT
        assert definition.direction is direction
        assert definition.dimension_keys == keys
    assert registry.get("PERS_CERT_VALID").source == "R14"
    assert registry.get("PERS_CERT_EXPIRING").source == "R15, R25"
    assert registry.get("PERS_RETRAINING_NEEDED").source == "R15, R36"
    assert registry.get("PERS_DEGREE").source == "R16"
    assert registry.get("PERS_TRAINING_12M").source == "R16, A09"


def test_values_match_their_definitions_and_evaluate_to_no_target() -> None:
    registry = build_registry()
    staff, certs = _list_fixture()
    values = compute(staff, certs, training=[TrainingRecord(1, day(-3))])
    for value in values:
        registry.get(value.code).validate_dimension(value.dimension)
    readings = evaluate_all(registry, values, {})
    assert len(readings) == len(values)
    assert all(r.status is IndicatorStatus.NO_TARGET for r in readings)
