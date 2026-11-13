# SPDX-License-Identifier: GPL-3.0-or-later
"""Personnel rules and indicators (PLAN T2.2, §3.5 A02/A03/A04/A09/A10/A14/P01, §5.4, D24).

Pure domain code: no Qt, no I/O, no clock. EVERY function that depends on "today" takes the as-of
date ``d`` explicitly, so a past as-of date gives the reading computed from the records as known
now for that date (I03). Only codes and numbers are produced; the UI maps codes to labels.

Each rule is implemented ONCE here and reused by the indicators, the lists and (later) the alert
rules, so the numbers on the dashboard, the lists and the alerts can never disagree.

Rules
-----
* Activity (A14): a person has ONE active interval ``[active_from, active_until]`` (both ends
  inclusive, ``active_until`` open when ``None``). Someone who returns is a new record. Only active
  staff are counted or listed.
* Counting certificate (A03, stated once, in :func:`counting_certificate`): among the person's
  certificates that count for a level and were issued on or before ``d``, the one with the latest
  ``valid_until`` (ties: later ``issued_on``, then higher ``id``). A certificate issued after ``d``
  therefore never hides the one that was valid on ``d``.
* Valid: ``valid_until >= d`` (the last day is still valid).
* Expiring (P01): valid on ``d``, ``valid_until <= d + cert_warning_days`` (inclusive), and not
  marked "no renewal" on ``d`` (D24).
* Needs retraining (A03): the counting certificate has expired or is expiring, and it is not marked
  "no renewal" on ``d``.
* Hierarchy (A02): off by default; levels are independent. When enabled, a certificate at level X
  also counts for every level listed in ``rules.hierarchy[X]``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from types import MappingProxyType

from cbrn_dashboard.domain.dates import add_months, days_between
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorDefinition,
    IndicatorValue,
    Module,
    UnitKind,
    encode_dimension,
)

_LEVEL_KEY = "level"
_STATUS_KEY = "status"
_TRAINING_WINDOW_MONTHS = 12


# --------------------------------------------------------------------------------------------
# Data objects
# --------------------------------------------------------------------------------------------


class PpeLevel(StrEnum):
    """Protection (PPE) level of a certificate; the stored value is the stable code."""

    A = "A"
    B = "B"
    C = "C"


class DegreeLevel(StrEnum):
    SPECIALISATION = "specialisation"
    MASTER = "master"
    DOCTORATE = "doctorate"


class DegreeStatus(StrEnum):
    COMPLETED = "completed"
    IN_PROGRESS = "in_progress"


class CertStatus(StrEnum):
    """Status of a person at one level, for the views.

    ``EXPIRED``: the counting certificate has ``valid_until < d`` (also when it is marked no
    renewal: the person is factually no longer certified). ``NO_RENEWAL``: still valid on ``d`` but
    marked "no renewal" from a date on or before ``d`` (D24). ``EXPIRING``: valid, inside the
    warning window and not no-renewal. ``VALID``: valid and outside the window. ``NONE``: no
    counting certificate at the level.
    """

    VALID = "VALID"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    NO_RENEWAL = "NO_RENEWAL"
    NONE = "NONE"


@dataclass(frozen=True)
class StaffMember:
    """A person with ONE active interval (A14); ``active_until`` is ``None`` while still active."""

    id: int
    identifier: str
    active_from: date
    active_until: date | None


@dataclass(frozen=True)
class Certificate:
    """A certificate at one PPE level; ``no_renewal_from`` is the D24 mark (``None`` = not set)."""

    id: int
    staff_id: int
    level: PpeLevel
    issued_on: date
    valid_until: date
    no_renewal_from: date | None = None


@dataclass(frozen=True)
class TrainingRecord:
    staff_id: int
    completed_on: date


@dataclass(frozen=True)
class Degree:
    """A degree; ``year`` (``None`` = not recorded) only matters for completed degrees."""

    staff_id: int
    level: DegreeLevel
    status: DegreeStatus
    year: int | None = None


def _empty_hierarchy() -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({})


def _empty_validity() -> Mapping[str, int | None]:
    return MappingProxyType({})


@dataclass(frozen=True)
class PersonnelRules:
    """Configuration of the personnel rules, passed explicitly (the service builds it).

    ``hierarchy[X]`` lists the levels that a certificate at level X ALSO counts for (A02); it only
    applies when ``hierarchy_enabled`` is true (an empty mapping behaves as "off").
    ``validity_months[L]`` is the configured validity in months of a level-L certificate, or
    ``None``/missing when not configured (A04).
    """

    cert_warning_days: int = 90
    hierarchy_enabled: bool = False
    hierarchy: Mapping[str, tuple[str, ...]] = field(default_factory=_empty_hierarchy)
    validity_months: Mapping[str, int | None] = field(default_factory=_empty_validity)


@dataclass(frozen=True)
class StaffLevelRow:
    """One (person, level) line for the views and lists; ``days_to_expiry`` is signed (R36)."""

    staff_id: int
    identifier: str
    level: PpeLevel
    certificate_id: int | None
    valid_until: date | None
    status: CertStatus
    days_to_expiry: int | None


# --------------------------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------------------------


def is_active(staff: StaffMember, d: date) -> bool:
    """Active on ``d``: ``active_from <= d`` and (open-ended or ``d <= active_until``)."""
    if staff.active_from > d:
        return False
    return staff.active_until is None or d <= staff.active_until


def counts_for_level(cert: Certificate, level: PpeLevel, rules: PersonnelRules) -> bool:
    """Whether ``cert`` counts for ``level``: same level, or (A02 on) listed in the hierarchy."""
    if cert.level == level:
        return True
    return rules.hierarchy_enabled and level in rules.hierarchy.get(cert.level, ())


def counting_certificate(
    certs: Iterable[Certificate],
    staff_id: int,
    level: PpeLevel,
    d: date,
    rules: PersonnelRules,
) -> Certificate | None:
    """THE certificate rule (A03): the certificate that counts for a person at a level on ``d``.

    Among the person's certificates that COUNT FOR ``level`` (their own level equals it or, only
    when ``rules.hierarchy_enabled``, ``level`` is in ``rules.hierarchy[cert.level]``) and have
    ``issued_on <= d``, the one with the LATEST ``valid_until``; ties: later ``issued_on``, then
    higher ``id``. ``None`` when there is none.
    """
    candidates = [
        c
        for c in certs
        if c.staff_id == staff_id and c.issued_on <= d and counts_for_level(c, level, rules)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda c: (c.valid_until, c.issued_on, c.id))


def is_valid(cert: Certificate, d: date) -> bool:
    """Valid on ``d``: ``valid_until >= d`` (the last day is still valid)."""
    return cert.valid_until >= d


def is_no_renewal(cert: Certificate, d: date) -> bool:
    """Marked "no renewal" on ``d`` (D24): ``no_renewal_from`` is set and ``<= d``."""
    return cert.no_renewal_from is not None and cert.no_renewal_from <= d


def _within_warning_window(cert: Certificate, d: date, rules: PersonnelRules) -> bool:
    return cert.valid_until <= d + timedelta(days=rules.cert_warning_days)


def is_expiring(cert: Certificate, d: date, rules: PersonnelRules) -> bool:
    """Expiring (P01): valid on ``d``, ``valid_until <= d + cert_warning_days`` (inclusive), and
    not no-renewal on ``d``. Apply it to the COUNTING certificate only.
    """
    if is_no_renewal(cert, d):
        return False
    return is_valid(cert, d) and _within_warning_window(cert, d, rules)


def needs_retraining(counting: Certificate | None, d: date, rules: PersonnelRules) -> bool:
    """Retraining needed (A03): the counting certificate has expired (``valid_until < d``) or is
    expiring within the window, AND it is not no-renewal on ``d``.

    A person with NO certificate at the level (``counting is None``) does not "need retraining" at
    that level: there is nothing to renew.
    """
    if counting is None or is_no_renewal(counting, d):
        return False
    return not is_valid(counting, d) or _within_warning_window(counting, d, rules)


def proposed_valid_until(issued_on: date, level: PpeLevel, rules: PersonnelRules) -> date | None:
    """Pre-filled ``valid_until`` (A04): ``issued_on`` plus the configured months for ``level``
    (day clamped to the month's end), or ``None`` (no proposal) when none is configured.
    """
    months = rules.validity_months.get(level)
    if months is None:
        return None
    return add_months(issued_on, months)


def level_status(counting: Certificate | None, d: date, rules: PersonnelRules) -> CertStatus:
    """Per-level status of a person from the counting certificate (see :class:`CertStatus`)."""
    if counting is None:
        return CertStatus.NONE
    if not is_valid(counting, d):
        return CertStatus.EXPIRED
    if is_no_renewal(counting, d):
        return CertStatus.NO_RENEWAL
    if _within_warning_window(counting, d, rules):
        return CertStatus.EXPIRING
    return CertStatus.VALID


# --------------------------------------------------------------------------------------------
# Lists
# --------------------------------------------------------------------------------------------


def _entries(
    staff: Iterable[StaffMember],
    certs: Iterable[Certificate],
    d: date,
    rules: PersonnelRules,
) -> list[tuple[StaffLevelRow, Certificate | None]]:
    """Rows of ACTIVE staff with their counting certificate, sorted by identifier, level, id."""
    pending = list(certs)
    entries: list[tuple[StaffLevelRow, Certificate | None]] = []
    for person in staff:
        if not is_active(person, d):
            continue
        for level in PpeLevel:
            counting = counting_certificate(pending, person.id, level, d, rules)
            row = StaffLevelRow(
                staff_id=person.id,
                identifier=person.identifier,
                level=level,
                certificate_id=None if counting is None else counting.id,
                valid_until=None if counting is None else counting.valid_until,
                status=level_status(counting, d, rules),
                days_to_expiry=None if counting is None else days_between(d, counting.valid_until),
            )
            entries.append((row, counting))
    entries.sort(key=lambda e: (e[0].identifier, e[0].level.value, e[0].staff_id))
    return entries


def staff_level_rows(
    staff: Iterable[StaffMember],
    certs: Iterable[Certificate],
    d: date,
    rules: PersonnelRules,
) -> list[StaffLevelRow]:
    """One row per ACTIVE person and level (A, B, C), sorted by identifier, level, then id."""
    return [row for row, _ in _entries(staff, certs, d, rules)]


def retraining_list(
    staff: Iterable[StaffMember],
    certs: Iterable[Certificate],
    d: date,
    rules: PersonnelRules,
) -> list[StaffLevelRow]:
    """Active staff needing retraining (R36), per level, sorted by identifier then level.

    Uses :func:`needs_retraining`, so a no-renewal certificate is never listed.
    """
    return [
        row
        for row, counting in _entries(staff, certs, d, rules)
        if needs_retraining(counting, d, rules)
    ]


def expiring_list(
    staff: Iterable[StaffMember],
    certs: Iterable[Certificate],
    d: date,
    rules: PersonnelRules,
) -> list[StaffLevelRow]:
    """Active staff whose counting certificate is expiring (R25), by identifier then level."""
    return [
        row
        for row, counting in _entries(staff, certs, d, rules)
        if counting is not None and is_expiring(counting, d, rules)
    ]


# --------------------------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------------------------


def indicator_definitions() -> tuple[IndicatorDefinition, ...]:
    """The personnel indicators (PLAN §5.4)."""
    return (
        IndicatorDefinition(
            code="PERS_CERT_VALID",
            module=Module.PERSONNEL,
            unit=UnitKind.COUNT,
            direction=Direction.HIGHER_IS_BETTER,
            dimension_keys=(_LEVEL_KEY,),
            source="R14",
        ),
        IndicatorDefinition(
            code="PERS_CERT_EXPIRING",
            module=Module.PERSONNEL,
            unit=UnitKind.COUNT,
            direction=Direction.LOWER_IS_BETTER,
            dimension_keys=(_LEVEL_KEY,),
            source="R15, R25",
        ),
        IndicatorDefinition(
            code="PERS_RETRAINING_NEEDED",
            module=Module.PERSONNEL,
            unit=UnitKind.COUNT,
            direction=Direction.LOWER_IS_BETTER,
            dimension_keys=(_LEVEL_KEY,),
            source="R15, R36",
        ),
        IndicatorDefinition(
            code="PERS_DEGREE",
            module=Module.PERSONNEL,
            unit=UnitKind.COUNT,
            direction=Direction.HIGHER_IS_BETTER,
            dimension_keys=(_LEVEL_KEY, _STATUS_KEY),
            source="R16",
        ),
        IndicatorDefinition(
            code="PERS_TRAINING_12M",
            module=Module.PERSONNEL,
            unit=UnitKind.COUNT,
            direction=Direction.HIGHER_IS_BETTER,
            source="R16, A09",
        ),
    )


def _degree_counts_on(degree: Degree, d: date) -> bool:
    """A completed degree with a recorded year after ``d.year`` was not completed on ``d``.

    Degrees without a year and in-progress degrees always count.
    """
    if degree.status != DegreeStatus.COMPLETED or degree.year is None:
        return True
    return degree.year <= d.year


def indicator_values(
    staff: Iterable[StaffMember],
    certs: Iterable[Certificate],
    training: Iterable[TrainingRecord],
    degrees: Iterable[Degree],
    d: date,
    rules: PersonnelRules,
) -> list[IndicatorValue]:
    """Values of the five indicators as of ``d``; counts are over ACTIVE staff, never ``None``.

    Order: ``PERS_CERT_VALID``, ``PERS_CERT_EXPIRING``, ``PERS_RETRAINING_NEEDED`` (each: level A,
    B, C), ``PERS_DEGREE`` (levels specialisation, master, doctorate; each: completed, in_progress),
    ``PERS_TRAINING_12M``. A person counts once per level even with several certificates, and
    once per (level, status) even with several degrees.

    ``PERS_TRAINING_12M`` counts training RECORDS of staff ACTIVE on ``d`` whose ``completed_on``
    lies in ``(add_months(d, -12), d]`` (exclusive start, inclusive end).

    ``PERS_DEGREE``: a COMPLETED degree whose ``year`` is set and greater than ``d.year`` is not
    counted on ``d``; degrees without a year and in-progress degrees are not affected.
    """
    active = [person for person in staff if is_active(person, d)]
    active_ids = {person.id for person in active}
    pending_certs = list(certs)

    valid_counts = dict.fromkeys(PpeLevel, 0)
    expiring_counts = dict.fromkeys(PpeLevel, 0)
    retraining_counts = dict.fromkeys(PpeLevel, 0)
    for person in active:
        for level in PpeLevel:
            counting = counting_certificate(pending_certs, person.id, level, d, rules)
            if counting is None:
                continue
            if is_valid(counting, d):
                valid_counts[level] += 1
            if is_expiring(counting, d, rules):
                expiring_counts[level] += 1
            if needs_retraining(counting, d, rules):
                retraining_counts[level] += 1

    degree_keys = {
        (degree.staff_id, degree.level, degree.status)
        for degree in degrees
        if degree.staff_id in active_ids and _degree_counts_on(degree, d)
    }
    window_start = add_months(d, -_TRAINING_WINDOW_MONTHS)
    training_count = sum(
        1
        for record in training
        if record.staff_id in active_ids and window_start < record.completed_on <= d
    )

    def level_dimension(level: PpeLevel) -> str:
        return encode_dimension({_LEVEL_KEY: level.value})

    values: list[IndicatorValue] = []
    for code, counts in (
        ("PERS_CERT_VALID", valid_counts),
        ("PERS_CERT_EXPIRING", expiring_counts),
        ("PERS_RETRAINING_NEEDED", retraining_counts),
    ):
        values.extend(
            IndicatorValue(code=code, value=float(counts[level]), dimension=level_dimension(level))
            for level in PpeLevel
        )
    for degree_level in DegreeLevel:
        for status in DegreeStatus:
            count = sum(1 for _, lvl, st in degree_keys if lvl == degree_level and st == status)
            values.append(
                IndicatorValue(
                    code="PERS_DEGREE",
                    value=float(count),
                    dimension=encode_dimension(
                        {_LEVEL_KEY: degree_level.value, _STATUS_KEY: status.value}
                    ),
                )
            )
    values.append(IndicatorValue(code="PERS_TRAINING_12M", value=float(training_count)))
    return values
