# SPDX-License-Identifier: GPL-3.0-or-later
"""Personnel demo generator (PLAN.md T2.5, D25, D17, I07).

Fills the demo database with FICTITIOUS people, certificates, courses, training records and
degrees. Every value comes from the seed (``ctx.rng``) or from the fixed cases below, never from
the thesis or from any real record. Every identifier, label, category, course code and degree field
starts with ``DEMO``; there are no names, ranks, roles, notes, health or contact data (D17).

All dates are placed RELATIVE TO ``ctx.today`` (the injected clock's date), so the sample always
shows the same situations whatever day the demo is opened. The data is written THROUGH
:class:`~cbrn_dashboard.services.personnel.PersonnelService`, so every row is validated and logged
(with the operator label ``DEMO``).

The first six people are built explicitly and do not use the random generator: they GUARANTEE one
person in each state (valid, expiring within the warning window, expired, "no renewal", inactive),
a renewal chain, degrees at every level and status, and training inside and outside the 12-month
window. The remaining people are random filler drawn from ``ctx.rng``.

Qt-free.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from cbrn_dashboard.domain.personnel import DegreeLevel, DegreeStatus, PpeLevel
from cbrn_dashboard.services.personnel import (
    CertificateInput,
    CourseInput,
    DegreeInput,
    PersonnelService,
    StaffInput,
    TrainingInput,
)

if TYPE_CHECKING:
    from cbrn_dashboard.demo import DemoContext

__all__ = ["generate"]

#: Label written to the change log for every change made by the generator.
OPERATOR = "DEMO"

_STAFF_TOTAL = 24
_NO_RENEWAL_REASON = "left_unit"
_CATEGORIES = ("DEMO-CAT-1", "DEMO-CAT-2", "DEMO-CAT-3")
_FIELDS = ("DEMO-FIELD-1", "DEMO-FIELD-2", "DEMO-FIELD-3", "DEMO-FIELD-4")
_HOURS = (8.0, 16.0, 24.0, 40.0)
_COURSE_COUNT = 3


def _on(today: date, offset: int) -> date:
    """The date ``offset`` days from ``today`` (negative: in the past)."""
    return today + timedelta(days=offset)


def _demo(value: str) -> str:
    """``value`` itself, after proving that it starts with ``DEMO``."""
    from cbrn_dashboard.demo import assert_demo_identifier

    assert_demo_identifier(value)
    return value


def _identifier(number: int) -> str:
    from cbrn_dashboard.demo import demo_identifier

    return _demo(demo_identifier("P", number))


def _course_code(number: int) -> str:
    from cbrn_dashboard.demo import demo_identifier

    return _demo(demo_identifier("C", number, width=1))


def _create_courses(service: PersonnelService) -> list[int]:
    ids: list[int] = []
    for number in range(1, _COURSE_COUNT + 1):
        ids.append(
            service.create_course(
                CourseInput(
                    code=_course_code(number),
                    label_pt_br=_demo(f"DEMO Curso {number}"),
                    label_en_us=_demo(f"DEMO Course {number}"),
                    label_es_es=_demo(f"DEMO Curso {number}"),
                )
            )
        )
    return ids


def _create_person(
    service: PersonnelService,
    number: int,
    active_from: date,
    category: str,
) -> int:
    return service.create_staff(
        StaffInput(
            identifier=_identifier(number),
            active_from=active_from,
            label=_demo(f"DEMO {number:03d}"),
            category=_demo(category),
        )
    )


def _certificate(
    service: PersonnelService,
    staff_id: int,
    today: date,
    level: PpeLevel,
    issued: int,
    until: int,
    *,
    no_renewal: int | None = None,
) -> int:
    """Add a certificate issued ``issued`` days and valid until ``until`` days from today."""
    cert_id = service.add_certificate(
        staff_id,
        CertificateInput(level=level, issued_on=_on(today, issued), valid_until=_on(today, until)),
    )
    if no_renewal is not None:
        service.set_no_renewal(cert_id, _on(today, no_renewal), _NO_RENEWAL_REASON)
    return cert_id


def _degree(
    service: PersonnelService,
    staff_id: int,
    level: DegreeLevel,
    status: DegreeStatus,
    year: int,
    field: str,
) -> None:
    service.add_degree(
        staff_id,
        DegreeInput(level=level, status=status, year=year, field=_demo(field)),
    )


def _training(
    service: PersonnelService,
    staff_id: int,
    course_id: int,
    today: date,
    offset: int,
    hours: float,
) -> None:
    service.add_training(
        staff_id,
        TrainingInput(course_id=course_id, completed_on=_on(today, offset), hours=hours),
    )


def _guaranteed(service: PersonnelService, today: date, courses: list[int]) -> None:
    """The fixed cases (people 1 to 6); they do not draw from the random generator."""
    c1, c2, c3 = courses
    a, b, c = PpeLevel.A, PpeLevel.B, PpeLevel.C
    year = today.year

    # 1: valid, far beyond the warning window; completed specialisation and master.
    person = _create_person(service, 1, _on(today, -1200), _CATEGORIES[0])
    _certificate(service, person, today, a, -300, 400)
    _certificate(service, person, today, b, -200, 500)
    _degree(
        service, person, DegreeLevel.SPECIALISATION, DegreeStatus.COMPLETED, year - 9, _FIELDS[0]
    )
    _degree(service, person, DegreeLevel.MASTER, DegreeStatus.COMPLETED, year - 6, _FIELDS[1])
    _training(service, person, c1, today, -30, 16.0)  # inside the 12-month window
    _training(service, person, c2, today, -200, 8.0)  # inside the 12-month window

    # 2: expiring (expires in 30 days, inside the default 90-day warning window).
    person = _create_person(service, 2, _on(today, -1500), _CATEGORIES[1])
    _certificate(service, person, today, a, -700, 30)
    _certificate(service, person, today, c, -100, 260)
    _degree(service, person, DegreeLevel.SPECIALISATION, DegreeStatus.IN_PROGRESS, year, _FIELDS[2])
    _training(service, person, c1, today, -500, 24.0)  # outside the window

    # 3: expired 45 days ago (level A); level C still valid.
    person = _create_person(service, 3, _on(today, -1800), _CATEGORIES[2])
    _certificate(service, person, today, a, -800, -45)
    _certificate(service, person, today, c, -300, 300)
    _degree(service, person, DegreeLevel.MASTER, DegreeStatus.IN_PROGRESS, year + 1, _FIELDS[3])
    _training(service, person, c3, today, -400, 40.0)  # outside the window
    _training(service, person, c2, today, -700, 8.0)  # outside the window

    # 4: still valid but marked "no renewal" from 10 days ago (D24).
    person = _create_person(service, 4, _on(today, -1000), _CATEGORIES[0])
    _certificate(service, person, today, a, -400, 200, no_renewal=-10)
    _degree(service, person, DegreeLevel.DOCTORATE, DegreeStatus.COMPLETED, year - 3, _FIELDS[0])
    _training(service, person, c3, today, -90, 16.0)  # inside the window

    # 5: inactive (deactivated 60 days ago) but with certificates that are still valid.
    person = _create_person(service, 5, _on(today, -1500), _CATEGORIES[1])
    _certificate(service, person, today, a, -500, 120)
    _certificate(service, person, today, c, -300, 300)
    _training(service, person, c1, today, -100, 8.0)
    service.deactivate_staff(person, _on(today, -60))

    # 6: renewal chain at level B: an older expired certificate and a newer valid one (counts once).
    person = _create_person(service, 6, _on(today, -1600), _CATEGORIES[2])
    _certificate(service, person, today, b, -1100, -400)
    _certificate(service, person, today, b, -35, 330)
    _degree(service, person, DegreeLevel.DOCTORATE, DegreeStatus.IN_PROGRESS, year + 1, _FIELDS[1])
    _training(service, person, c2, today, -20, 24.0)  # inside the window


def _filler(
    ctx: DemoContext, service: PersonnelService, today: date, courses: list[int], first: int
) -> None:
    """Random people ``first`` to ``_STAFF_TOTAL``; every choice comes from ``ctx.rng``."""
    rng = ctx.rng
    for number in range(first, _STAFF_TOTAL + 1):
        person = _create_person(
            service, number, _on(today, -rng.randint(1000, 2500)), rng.choice(_CATEGORIES)
        )

        levels = [level for level in PpeLevel if rng.random() < 0.6]
        if not levels:
            levels = [rng.choice(list(PpeLevel))]
        for level in levels:
            issued = -rng.randint(30, 900)
            _certificate(service, person, today, level, issued, issued + rng.randint(300, 1100))

        if rng.random() < 0.3:
            status = rng.choice(list(DegreeStatus))
            year = today.year - rng.randint(0, 15)
            if status is DegreeStatus.IN_PROGRESS:
                year = today.year + rng.randint(0, 2)
            degree_level = rng.choice(list(DegreeLevel))
            _degree(service, person, degree_level, status, year, rng.choice(_FIELDS))

        taken: set[tuple[int, int]] = set()
        for _ in range(rng.randint(0, 3)):
            course = rng.choice(courses)
            offset = -rng.randint(0, 700)
            if (course, offset) in taken:
                continue
            taken.add((course, offset))
            _training(service, person, course, today, offset, rng.choice(_HOURS))

        if rng.random() < 0.15:
            service.deactivate_staff(person, _on(today, -rng.randint(10, 300)))


def generate(ctx: DemoContext) -> None:
    """Create the fictitious personnel data of the demo database (runs once, inside the seeding
    transaction of :func:`cbrn_dashboard.demo.generate`).
    """
    service = PersonnelService(ctx.conn, ctx.clock, operator=lambda: OPERATOR)
    courses = _create_courses(service)
    _guaranteed(service, ctx.today, courses)
    _filler(ctx, service, ctx.today, courses, first=7)
