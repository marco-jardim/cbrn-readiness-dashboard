# SPDX-License-Identifier: GPL-3.0-or-later
"""Personnel demo generator (T2.5): states, degrees, training window, DEMO prefix, determinism."""

from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import pytest

from cbrn_dashboard import demo
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import (
    DEFAULT_SEED,
    DEMO_SEED_KEY,
    DemoGenerator,
    is_demo_identifier,
    open_demo_database,
)
from cbrn_dashboard.demo import personnel as demo_personnel
from cbrn_dashboard.domain.dates import add_months
from cbrn_dashboard.domain.personnel import CertStatus, DegreeLevel, DegreeStatus, PpeLevel
from cbrn_dashboard.paths import DATABASE_FILE_NAME
from cbrn_dashboard.services.personnel import PersonnelService, StaffView
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")
LATER = FixedClock.at("2026-04-04T12:00:00Z")  # 30 days after CLOCK
TODAY = date(2026, 3, 5)
PERSONNEL = DemoGenerator("personnel", demo_personnel.generate)

PERSONNEL_TABLES = (
    "staff_member",
    "ppe_certification",
    "training_course",
    "training_record",
    "academic_degree",
)

type Rows = list[tuple[object, ...]]


# --------------------------------------------------------------------------- helpers


class Databases:
    """Builds and tracks demo databases so every connection is closed at teardown."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._open: list[DatabaseConnection] = []
        self._count = 0

    def build(self, *, clock: FixedClock = CLOCK, seed: int = DEFAULT_SEED) -> DatabaseConnection:
        """A migrated database filled by the personnel generator alone."""
        self._count += 1
        folder = self._root / f"db{self._count}"
        folder.mkdir()
        conn = open_and_migrate(
            folder / "demo.sqlite3", data_dir=folder, identity=DatabaseIdentity.REAL
        )
        self._open.append(conn)
        app_meta.initialise(conn, is_demo=True, created_with="0.0.1")
        assert demo.generate(conn, clock, seed=seed, generators=[PERSONNEL]) is True
        return conn

    def track(self, conn: DatabaseConnection) -> DatabaseConnection:
        self._open.append(conn)
        return conn

    def close_all(self) -> None:
        for conn in self._open:
            conn.close()


@pytest.fixture
def databases(tmp_path: Path) -> Iterator[Databases]:
    registry = Databases(tmp_path)
    yield registry
    registry.close_all()


@pytest.fixture
def conn(databases: Databases) -> DatabaseConnection:
    return databases.build()


def _service(conn: DatabaseConnection, clock: FixedClock = CLOCK) -> PersonnelService:
    return PersonnelService(conn, clock)


def _rows(conn: DatabaseConnection, table: str) -> Rows:
    return [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]


def _staff(conn: DatabaseConnection) -> dict[str, StaffView]:
    return {view.identifier: view for view in _service(conn).list_staff()}


def _statuses(
    conn: DatabaseConnection, as_of: date = TODAY
) -> dict[tuple[str, PpeLevel], CertStatus]:
    return {(row.identifier, row.level): row.status for row in _service(conn).level_rows(as_of)}


# --------------------------------------------------------------------------- staff


def test_staff_identifiers_are_demo_p001_onwards(conn: DatabaseConnection) -> None:
    identifiers = sorted(_staff(conn))
    assert len(identifiers) == 24
    assert identifiers == [f"DEMO-P{number:03d}" for number in range(1, 25)]
    for view in _staff(conn).values():
        assert view.label is not None
        assert view.category is not None


# --------------------------------------------------------------------------- states


def test_each_state_is_present_in_the_service_views(conn: DatabaseConnection) -> None:
    service = _service(conn)
    statuses = _statuses(conn)

    assert statuses[("DEMO-P001", PpeLevel.A)] is CertStatus.VALID
    assert statuses[("DEMO-P002", PpeLevel.A)] is CertStatus.EXPIRING
    assert statuses[("DEMO-P003", PpeLevel.A)] is CertStatus.EXPIRED
    assert statuses[("DEMO-P004", PpeLevel.A)] is CertStatus.NO_RENEWAL
    assert {
        CertStatus.VALID,
        CertStatus.EXPIRING,
        CertStatus.EXPIRED,
        CertStatus.NO_RENEWAL,
    } <= set(statuses.values())

    expiring = {(row.identifier, row.level) for row in service.expiring_list(TODAY)}
    assert ("DEMO-P002", PpeLevel.A) in expiring
    retraining = {(row.identifier, row.level) for row in service.retraining_list(TODAY)}
    assert ("DEMO-P002", PpeLevel.A) in retraining
    assert ("DEMO-P003", PpeLevel.A) in retraining
    assert ("DEMO-P004", PpeLevel.A) not in retraining  # "no renewal" is never listed (D24)


def test_expiring_person_expires_inside_the_default_warning_window(
    conn: DatabaseConnection,
) -> None:
    rows = {
        (row.identifier, row.level): row
        for row in _service(conn).level_rows(TODAY)
        if row.identifier in {"DEMO-P002", "DEMO-P003"}
    }
    expiring = rows[("DEMO-P002", PpeLevel.A)]
    assert expiring.days_to_expiry is not None
    assert 0 <= expiring.days_to_expiry <= 90
    expired = rows[("DEMO-P003", PpeLevel.A)]
    assert expired.days_to_expiry is not None
    assert expired.days_to_expiry < 0


def test_no_renewal_certificate_is_marked_with_a_date_and_a_reason(
    conn: DatabaseConnection,
) -> None:
    service = _service(conn)
    person = _staff(conn)["DEMO-P004"]
    certificates = service.list_certificates(person.id)
    marked = [cert for cert in certificates if cert.no_renewal_from is not None]
    assert marked
    for cert in marked:
        assert cert.no_renewal_from is not None
        assert cert.no_renewal_from <= TODAY
        assert cert.no_renewal_reason in {"left_unit", "role_change", "other"}
        assert cert.valid_until >= TODAY


def test_an_inactive_person_still_has_certificates(conn: DatabaseConnection) -> None:
    service = _service(conn)
    inactive = [view for view in service.list_staff() if view.active_until is not None]
    assert inactive
    assert all(view.active_until is not None and view.active_until < TODAY for view in inactive)
    active_today = {view.identifier for view in service.list_staff(TODAY, active_only=True)}
    person = _staff(conn)["DEMO-P005"]
    assert person.identifier not in active_today
    assert service.list_certificates(person.id)
    # Not in the as-of views at all, although the certificates are still valid.
    assert all(identifier != "DEMO-P005" for identifier, _ in _statuses(conn))
    # While active (before the deactivation) the same certificates counted.
    earlier = _statuses(conn, TODAY - timedelta(days=100))
    assert earlier[("DEMO-P005", PpeLevel.A)] is CertStatus.VALID


def test_renewal_chain_counts_once(conn: DatabaseConnection) -> None:
    service = _service(conn)
    person = _staff(conn)["DEMO-P006"]
    level_b = [cert for cert in service.list_certificates(person.id) if cert.level is PpeLevel.B]
    assert len(level_b) == 2
    older, newer = sorted(level_b, key=lambda cert: cert.issued_on)
    assert older.valid_until < TODAY <= newer.valid_until

    rows = [
        row
        for row in service.level_rows(TODAY)
        if row.identifier == "DEMO-P006" and row.level is PpeLevel.B
    ]
    assert len(rows) == 1
    assert rows[0].status is CertStatus.VALID
    assert rows[0].certificate_id == newer.id

    valid_b = sum(
        1
        for (_, level), status in _statuses(conn).items()
        if level is PpeLevel.B and status is CertStatus.VALID
    )
    summary = {item.level: item for item in service.summary(TODAY)}
    # The summary counts each person once per level; the "valid" count includes "no renewal".
    assert summary[PpeLevel.B].valid >= valid_b >= 1


def test_certificates_exist_at_levels_a_b_and_c(conn: DatabaseConnection) -> None:
    levels = {
        str(row[0]) for row in conn.execute("SELECT DISTINCT ppe_level FROM ppe_certification")
    }
    assert levels == {"A", "B", "C"}
    held = {
        level for (_, level), status in _statuses(conn).items() if status is not CertStatus.NONE
    }
    assert held == set(PpeLevel)


# --------------------------------------------------------------------------- degrees, training


def test_degrees_exist_at_every_level_and_status(conn: DatabaseConnection) -> None:
    service = _service(conn)
    found = {
        (degree.level, degree.status)
        for person in service.list_staff()
        for degree in service.list_degrees(person.id)
    }
    assert found == {(level, status) for level in DegreeLevel for status in DegreeStatus}
    assert len(found) == 6
    counted = {
        item.dimension: item.value
        for item in service.indicator_values(TODAY)
        if item.code == "PERS_DEGREE"
    }
    assert len(counted) == 6
    assert all(value > 0 for value in counted.values())


def test_training_exists_inside_and_outside_the_twelve_month_window(
    conn: DatabaseConnection,
) -> None:
    service = _service(conn)
    start = add_months(TODAY, -12)
    dates = [
        record.completed_on
        for person in service.list_staff()
        for record in service.list_training(person.id)
    ]
    inside = [day for day in dates if start < day <= TODAY]
    outside = [day for day in dates if day <= start]
    assert inside
    assert outside
    assert all(day <= TODAY for day in dates)
    counted = [
        item.value for item in service.indicator_values(TODAY) if item.code == "PERS_TRAINING_12M"
    ]
    assert counted
    assert counted[0] > 0


def test_training_references_demo_courses(conn: DatabaseConnection) -> None:
    service = _service(conn)
    codes = {
        record.course_code
        for person in service.list_staff()
        for record in service.list_training(person.id)
    }
    assert codes
    assert all(code.startswith("DEMO") for code in codes)
    assert {course.code for course in service.list_courses()} >= codes


def test_every_course_code_starts_with_demo(conn: DatabaseConnection) -> None:
    courses = _service(conn).list_courses(include_inactive=True)
    assert len(courses) >= 3
    for course in courses:
        assert course.code.startswith("DEMO")
        for label in (course.label_pt_br, course.label_en_us, course.label_es_es):
            assert label is not None
            assert label.startswith("DEMO")


# --------------------------------------------------------------------------- DEMO prefix


def test_every_written_text_starts_with_demo(conn: DatabaseConnection) -> None:
    checks = {
        "staff_member": ("identifier", "label", "category"),
        "ppe_certification": ("reference",),
        "training_course": ("code", "label_pt_br", "label_en_us", "label_es_es"),
        "academic_degree": ("field",),
    }
    checked = 0
    for table, columns in checks.items():
        for column in columns:
            for (value,) in conn.execute(f"SELECT {column} FROM {table}").fetchall():
                if value is None and column == "reference":
                    continue  # the only optional column; the generator leaves it empty
                assert isinstance(value, str), (table, column)
                assert is_demo_identifier(value), (table, column)
                checked += 1
    assert checked > 80


def test_degree_fields_are_present_and_demo(conn: DatabaseConnection) -> None:
    fields = [row[0] for row in conn.execute("SELECT field FROM academic_degree")]
    assert fields
    assert all(isinstance(field, str) and field.startswith("DEMO") for field in fields)


# --------------------------------------------------------------------------- determinism


def test_same_seed_gives_identical_rows(databases: Databases) -> None:
    first = databases.build(seed=7)
    second = databases.build(seed=7)
    for table in PERSONNEL_TABLES:
        rows = _rows(first, table)
        assert rows
        assert rows == _rows(second, table)


def test_a_different_seed_changes_the_filler(databases: Databases) -> None:
    first = databases.build(seed=7)
    second = databases.build(seed=8)
    assert any(_rows(first, table) != _rows(second, table) for table in PERSONNEL_TABLES)
    # The guaranteed cases do not depend on the seed: the same states in both.
    assert _statuses(first)[("DEMO-P002", PpeLevel.A)] is CertStatus.EXPIRING
    assert _statuses(second)[("DEMO-P002", PpeLevel.A)] is CertStatus.EXPIRING
    assert sorted(_staff(first)) == sorted(_staff(second))


def test_the_default_seed_is_stable_between_runs(databases: Databases) -> None:
    first = databases.build()
    second = databases.build()
    assert _rows(first, "ppe_certification") == _rows(second, "ppe_certification")


# --------------------------------------------------------------------------- relative to the clock


def test_data_is_relative_to_the_clock(databases: Databases) -> None:
    now = databases.build(clock=CLOCK)
    later = databases.build(clock=LATER)
    shift = timedelta(days=30)

    def valid_until(conn: DatabaseConnection) -> date:
        service = _service(conn)
        person = _staff(conn)["DEMO-P002"]
        certs = [c for c in service.list_certificates(person.id) if c.level is PpeLevel.A]
        assert len(certs) == 1
        return certs[0].valid_until

    assert valid_until(later) - valid_until(now) == shift

    later_service = _service(later, LATER)
    expiring = [
        row
        for row in later_service.level_rows(LATER.local_date())
        if row.identifier == "DEMO-P002" and row.level is PpeLevel.A
    ]
    assert expiring[0].status is CertStatus.EXPIRING
    assert expiring[0].days_to_expiry == 30
    statuses = _statuses(later, LATER.local_date())
    assert statuses[("DEMO-P003", PpeLevel.A)] is CertStatus.EXPIRED
    assert statuses[("DEMO-P004", PpeLevel.A)] is CertStatus.NO_RENEWAL


# --------------------------------------------------------------------------- framework


def test_runs_inside_the_framework_once(tmp_path: Path, databases: Databases) -> None:
    first = databases.track(open_demo_database(tmp_path, CLOCK, generators=[PERSONNEL]))
    assert app_meta.get(first, DEMO_SEED_KEY) == str(DEFAULT_SEED)
    rows = {table: _rows(first, table) for table in PERSONNEL_TABLES}
    assert len(rows["staff_member"]) == 24
    first.close()

    again = databases.track(open_demo_database(tmp_path, CLOCK, generators=[PERSONNEL]))
    for table in PERSONNEL_TABLES:
        assert _rows(again, table) == rows[table]
    assert not (tmp_path / DATABASE_FILE_NAME).exists()
    assert {entry.name for entry in tmp_path.iterdir()} == {"demo"}


# --------------------------------------------------------------------------- change log


def test_change_log_has_the_demo_operator_and_no_identifiers(conn: DatabaseConnection) -> None:
    log = conn.execute(
        "SELECT operator, entity, entity_key, before_json, after_json FROM change_log"
    ).fetchall()
    assert log
    assert {row[0] for row in log} == {"DEMO"}

    redacted: set[str] = set()
    sources = (
        ("identifier", "staff_member"),
        ("label", "staff_member"),
        ("field", "academic_degree"),
    )
    for column, table in sources:
        for (value,) in conn.execute(f"SELECT {column} FROM {table}").fetchall():
            if value is not None:
                redacted.add(str(value))
    assert len(redacted) > 20

    for row in log:
        text = " ".join(str(part) for part in row[2:] if part is not None)
        for value in redacted:
            assert value not in text
