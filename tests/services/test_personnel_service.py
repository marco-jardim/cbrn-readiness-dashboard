# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the personnel service and repository (PLAN.md T2.3); fictitious data only."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import personnel as domain
from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.dates import parse_iso_date
from cbrn_dashboard.domain.indicators import encode_dimension
from cbrn_dashboard.domain.personnel import CertStatus, DegreeLevel, DegreeStatus, PpeLevel
from cbrn_dashboard.services.errors import (
    CODE_IMMUTABLE,
    INVALID_CODE,
    INVALID_DATE,
    LABEL_PT_BR_REQUIRED,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
    ServiceError,
)
from cbrn_dashboard.services.personnel import (
    ACTIVE_UNTIL_BEFORE_FROM,
    COURSE_IN_USE,
    COURSE_INACTIVE,
    DUPLICATE_CERTIFICATE,
    DUPLICATE_CODE,
    DUPLICATE_DEGREE,
    DUPLICATE_IDENTIFIER,
    DUPLICATE_TRAINING,
    IDENTIFIER_LOOKS_LIKE_NATIONAL_ID,
    INVALID_DEGREE_LEVEL,
    INVALID_DEGREE_STATUS,
    INVALID_NO_RENEWAL_REASON,
    INVALID_NUMBER,
    INVALID_PPE_LEVEL,
    INVALID_YEAR,
    NEGATIVE_HOURS,
    NO_RENEWAL_REASON_WITHOUT_DATE,
    PSEUDONYM_COLLISION,
    TEXT_TOO_LONG,
    VALID_UNTIL_BEFORE_ISSUED,
    CertificateInput,
    CourseInput,
    CourseView,
    DegreeInput,
    NoRenewalMark,
    PersonnelService,
    StaffInput,
    TrainingInput,
    course_label,
)
from cbrn_dashboard.storage import settings_repo
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import WriteContext
from tests.services.conftest import ChangeLogRows

AS_OF = date(2026, 3, 5)
NOW_TEXT = "2026-03-05T12:00:00Z"
OPERATOR = "op-demo"

# Distinctive fictitious personal values for the redaction tests.
SECRET_IDENTIFIER = "DEMO-ZEBRA-7731"
SECRET_LABEL = "Fictitious Label QX"
SECRET_REFERENCE = "DEMO-REF-9917"
SECRET_REFERENCE_2 = "DEMO-REF-9918"
SECRET_FIELD = "Fictitious Field KW"
SECRET_FIELD_2 = "Fictitious Field ZV"
SECRET_CATEGORY = "Fictitious Category HJ"
SECRET_CATEGORY_2 = "Fictitious Category MP"
SECRETS_ALL = (
    SECRET_IDENTIFIER,
    SECRET_LABEL,
    SECRET_CATEGORY,
    SECRET_CATEGORY_2,
    SECRET_REFERENCE,
    SECRET_REFERENCE_2,
    SECRET_FIELD,
    SECRET_FIELD_2,
)


class _Ids:
    """A deterministic ``id_factory``: 000001, 000002, ..."""

    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> str:
        self.count += 1
        return f"{self.count:06d}"


@pytest.fixture
def ids() -> _Ids:
    return _Ids()


@pytest.fixture
def service(db: DatabaseConnection, clock: FixedClock, ids: _Ids) -> PersonnelService:
    return PersonnelService(db, clock, lambda: OPERATOR, ids)


def _staff(
    identifier: str = "DEMO-P001",
    *,
    active_from: str = "2020-01-01",
    active_until: str | None = None,
    label: str | None = None,
    category: str | None = None,
) -> StaffInput:
    return StaffInput(
        identifier=identifier,
        active_from=active_from,
        active_until=active_until,
        label=label,
        category=category,
    )


def _cert(
    level: str = "A",
    issued_on: str = "2025-01-10",
    valid_until: str = "2027-01-10",
    reference: str | None = None,
) -> CertificateInput:
    return CertificateInput(
        level=level, issued_on=issued_on, valid_until=valid_until, reference=reference
    )


def _course(code: str = "DEMO-C1", label: str | None = "Curso Demo") -> CourseInput:
    return CourseInput(code=code, label_pt_br=label)


def _error(call: Callable[[], object]) -> ServiceError:
    with pytest.raises(ServiceError) as info:
        call()
    return info.value


def _d(text: str) -> date:
    return parse_iso_date(text)


def _count(conn: DatabaseConnection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0])


def _logged(
    conn: DatabaseConnection, change_log_rows: ChangeLogRows, action: Callable[[], object]
) -> list[dict[str, object]]:
    """The change_log rows written by ``action``."""
    before = len(change_log_rows(conn))
    action()
    return change_log_rows(conn)[before:]


def _tables(conn: DatabaseConnection) -> list[str]:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        " ORDER BY name"
    )
    return [str(row[0]) for row in cursor.fetchall()]


def _dump(conn: DatabaseConnection) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every table (change_log included)."""
    return {
        table: [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}"').fetchall()]
        for table in _tables(conn)
    }


def _text_of(conn: DatabaseConnection, *, change_log: bool) -> str:
    """All values of all columns of the change_log (or of every other table) as one text."""
    parts: list[str] = []
    for table, rows in _dump(conn).items():
        if (table == "change_log") is change_log:
            parts.extend(str(value) for row in rows for value in row if value is not None)
    return "\n".join(parts)


def _entities(rows: list[dict[str, object]]) -> Counter[tuple[object, object]]:
    return Counter((row["entity"], row["action"]) for row in rows)


def _save_config(db: DatabaseConnection, clock: FixedClock, config: ReadinessConfig) -> None:
    settings_repo.save_config(WriteContext(db, clock, ""), config)


_CUSTOM_CONFIG = ReadinessConfig().with_changes(
    cert_warning_days=30,
    ppe_hierarchy_enabled=True,
    ppe_hierarchy={"A": ("B", "C"), "B": ("C",)},
)


def _domain_rules(config: ReadinessConfig) -> domain.PersonnelRules:
    return domain.PersonnelRules(
        cert_warning_days=config.cert_warning_days,
        hierarchy_enabled=config.ppe_hierarchy_enabled,
        hierarchy=config.ppe_hierarchy,
        validity_months=config.ppe_validity_months,
    )


# --------------------------------------------------------------------------- change log


def test_every_write_logs_one_row_stamped_with_operator_and_clock(
    service: PersonnelService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    def one(entity: str, action: str, call: Callable[[], object]) -> None:
        rows = _logged(db, change_log_rows, call)
        assert [(row["entity"], row["action"]) for row in rows] == [(entity, action)]
        assert rows[0]["operator"] == OPERATOR
        assert rows[0]["at_utc"] == NOW_TEXT

    staff_id = service.create_staff(_staff())
    assert service.get_staff(staff_id).identifier == "DEMO-P001"
    one("staff_member", "update", lambda: service.update_staff(staff_id, _staff(category="RES")))
    one("staff_member", "update", lambda: service.deactivate_staff(staff_id, "2030-12-31"))

    cert_id = service.add_certificate(staff_id, _cert())
    one("ppe_certification", "update", lambda: service.update_certificate(cert_id, _cert("B")))
    one("ppe_certification", "update", lambda: service.set_no_renewal(cert_id, "2026-01-01"))
    one("ppe_certification", "update", lambda: service.clear_no_renewal(cert_id))

    course_id = service.create_course(_course())
    one("training_course", "update", lambda: service.update_course(course_id, _course(label="X")))
    training_id = service.add_training(staff_id, TrainingInput(course_id, "2025-06-01", 8))
    one(
        "training_record",
        "update",
        lambda: service.update_training(training_id, TrainingInput(course_id, "2025-06-02")),
    )
    degree_id = service.add_degree(staff_id, DegreeInput("master", year=2018))
    one(
        "academic_degree",
        "update",
        lambda: service.update_degree(degree_id, DegreeInput("doctorate", year=2020)),
    )
    one("academic_degree", "delete", lambda: service.delete_degree(degree_id))
    one("training_record", "delete", lambda: service.delete_training(training_id))
    one("training_course", "update", lambda: service.deactivate_course(course_id))
    one("training_course", "delete", lambda: service.delete_course(course_id))
    one("ppe_certification", "delete", lambda: service.delete_certificate(cert_id))
    one("staff_member", "delete", lambda: service.delete_staff(staff_id))


def test_inserts_are_logged(
    service: PersonnelService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    staff_id = service.create_staff(_staff())
    course_id = service.create_course(_course())
    service.add_certificate(staff_id, _cert())
    service.add_training(staff_id, TrainingInput(course_id, "2025-06-01"))
    service.add_degree(staff_id, DegreeInput("master"))
    rows = change_log_rows(db)
    assert _entities(rows) == Counter(
        {
            ("staff_member", "insert"): 1,
            ("training_course", "insert"): 1,
            ("ppe_certification", "insert"): 1,
            ("training_record", "insert"): 1,
            ("academic_degree", "insert"): 1,
        }
    )
    assert rows[0]["entity_id"] == staff_id
    assert all(row["operator"] == OPERATOR and row["at_utc"] == NOW_TEXT for row in rows)


def test_unchanged_update_logs_nothing(
    service: PersonnelService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    staff_id = service.create_staff(_staff(category="RES"))
    assert _logged(db, change_log_rows, lambda: service.update_staff(staff_id, _staff())) != []
    assert _logged(db, change_log_rows, lambda: service.update_staff(staff_id, _staff())) == []


def test_operator_is_read_for_each_write(
    db: DatabaseConnection, clock: FixedClock, change_log_rows: ChangeLogRows
) -> None:
    current = ["first"]
    service = PersonnelService(db, clock, lambda: current[0])
    service.create_staff(_staff("DEMO-P001"))
    current[0] = "second"
    service.create_staff(_staff("DEMO-P002"))
    assert [row["operator"] for row in change_log_rows(db)] == ["first", "second"]
    other = PersonnelService(db, clock)
    other.create_staff(_staff("DEMO-P003"))
    assert change_log_rows(db)[-1]["operator"] == ""


def test_personal_text_never_reaches_the_change_log(
    service: PersonnelService, db: DatabaseConnection
) -> None:
    staff_id = service.create_staff(
        _staff(SECRET_IDENTIFIER, label=SECRET_LABEL, category=SECRET_CATEGORY)
    )
    service.update_staff(
        staff_id, _staff(SECRET_IDENTIFIER, label=SECRET_LABEL, category=SECRET_CATEGORY_2)
    )
    cert_id = service.add_certificate(staff_id, _cert(reference=SECRET_REFERENCE))
    service.update_certificate(cert_id, _cert(reference=SECRET_REFERENCE_2))
    degree_id = service.add_degree(staff_id, DegreeInput("master", field=SECRET_FIELD))
    service.update_degree(degree_id, DegreeInput("master", field=SECRET_FIELD_2))
    log_text = _text_of(db, change_log=True)
    table_text = _text_of(db, change_log=False)
    for secret in SECRETS_ALL:
        assert secret not in log_text
    assert SECRET_IDENTIFIER in table_text
    assert SECRET_FIELD_2 in table_text
    assert SECRET_CATEGORY_2 in table_text


# --------------------------------------------------------------------------- staff lifecycle


def test_identifier_is_trimmed_and_stored(service: PersonnelService) -> None:
    staff_id = service.create_staff(_staff("  DEMO-P009  ", label="  ", category=" RES "))
    view = service.get_staff(staff_id)
    assert view.identifier == "DEMO-P009"
    assert view.label is None
    assert view.category == "RES"
    assert view.active_from == date(2020, 1, 1)
    assert view.active_until is None
    assert _error(lambda: service.create_staff(_staff(" DEMO-P009"))).code == DUPLICATE_IDENTIFIER


def test_update_staff_keeps_own_identifier(service: PersonnelService) -> None:
    staff_id = service.create_staff(_staff())
    service.update_staff(staff_id, _staff(label="Short", category="RES"))
    view = service.get_staff(staff_id)
    assert (view.label, view.category) == ("Short", "RES")


def test_deactivated_person_keeps_records_and_drops_out_after_active_until(
    service: PersonnelService, db: DatabaseConnection
) -> None:
    staff_id = service.create_staff(_staff())
    course_id = service.create_course(_course())
    service.add_certificate(staff_id, _cert("A", "2025-01-10", "2028-01-10"))
    service.add_training(staff_id, TrainingInput(course_id, "2026-01-10"))
    service.add_degree(staff_id, DegreeInput("master"))

    def valid_a(as_of: date) -> int:
        return next(s.valid for s in service.summary(as_of) if s.level is PpeLevel.A)

    assert valid_a(date(2026, 3, 6)) == 1
    service.deactivate_staff(staff_id, "2026-03-05")
    assert service.get_staff(staff_id).active_until == date(2026, 3, 5)
    assert valid_a(date(2026, 3, 5)) == 1  # still counted on the last day
    assert valid_a(date(2026, 3, 6)) == 0  # not the day after
    assert [row.identifier for row in service.level_rows(date(2026, 3, 5))] != []
    assert service.level_rows(date(2026, 3, 6)) == []
    detail = service.staff_detail(staff_id)
    assert (len(detail.certificates), len(detail.training), len(detail.degrees)) == (1, 1, 1)
    assert _count(db, "ppe_certification") == 1
    assert _count(db, "training_record") == 1


def test_returning_person_is_a_new_record_and_active_until_can_be_corrected(
    service: PersonnelService,
) -> None:
    assert not hasattr(PersonnelService, "reactivate")
    staff_id = service.create_staff(_staff())
    service.deactivate_staff(staff_id, "2024-06-30")
    # A plain correction through update_staff is allowed; there is no special rule (A14).
    service.update_staff(staff_id, _staff(active_until=None))
    assert service.get_staff(staff_id).active_until is None


def test_delete_staff_removes_dependents_and_logs_each(
    service: PersonnelService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    staff_id = service.create_staff(_staff())
    keep_id = service.create_staff(_staff("DEMO-P002"))
    course_id = service.create_course(_course())
    service.add_certificate(staff_id, _cert("A", "2025-01-10", "2027-01-10"))
    service.add_certificate(staff_id, _cert("B", "2025-01-10", "2027-01-10"))
    for day in ("2025-06-01", "2025-07-01", "2025-08-01"):
        service.add_training(staff_id, TrainingInput(course_id, day))
    service.add_degree(staff_id, DegreeInput("master", year=2018))
    service.add_degree(staff_id, DegreeInput("doctorate", year=2022))
    service.add_certificate(keep_id, _cert())

    rows = _logged(db, change_log_rows, lambda: service.delete_staff(staff_id))
    assert len(rows) == 1 + 2 + 3 + 2
    assert _entities(rows) == Counter(
        {
            ("staff_member", "delete"): 1,
            ("ppe_certification", "delete"): 2,
            ("training_record", "delete"): 3,
            ("academic_degree", "delete"): 2,
        }
    )
    assert _count(db, "staff_member") == 1
    assert _count(db, "ppe_certification") == 1
    assert _count(db, "training_record") == 0
    assert _count(db, "academic_degree") == 0
    assert _count(db, "training_course") == 1
    assert _error(lambda: service.get_staff(staff_id)).code == NOT_FOUND


def test_list_staff_and_filters(service: PersonnelService) -> None:
    by_identifier = _load_fixture(service).ids
    assert [view.identifier for view in service.list_staff()] == sorted(by_identifier)
    assert [v.identifier for v in service.list_staff(AS_OF, active_only=True)] == [
        "DEMO-P001",
        "DEMO-P002",
        "DEMO-P005",
        "DEMO-P006",
    ]
    assert [v.identifier for v in service.list_staff(AS_OF, level="B")] == [
        "DEMO-P001",
        "DEMO-P005",
    ]
    assert [v.identifier for v in service.list_staff(AS_OF, level=PpeLevel.C)] == ["DEMO-P002"]
    assert [v.identifier for v in service.list_staff(AS_OF, needs_retraining=True)] == [
        "DEMO-P001",
        "DEMO-P002",
        "DEMO-P006",
    ]
    assert [v.identifier for v in service.list_staff(AS_OF, level="C", needs_retraining=True)] == []
    assert _error(lambda: service.list_staff(active_only=True)).code == REQUIRED
    assert _error(lambda: service.list_staff(AS_OF, level="D")).code == INVALID_PPE_LEVEL


def test_staff_detail(service: PersonnelService) -> None:
    staff_id = service.create_staff(_staff(label="Short", category="RES"))
    course_id = service.create_course(_course())
    cert_id = service.add_certificate(staff_id, _cert(reference="ref"))
    service.add_training(staff_id, TrainingInput(course_id, "2025-06-01", 12.5))
    service.add_degree(staff_id, DegreeInput("master", year=2018, field="fld"))
    detail = service.staff_detail(staff_id)
    assert detail.staff.identifier == "DEMO-P001"
    assert detail.certificates[0].id == cert_id
    assert detail.certificates[0].level is PpeLevel.A
    assert detail.certificates[0].reference == "ref"
    assert (detail.training[0].course_code, detail.training[0].hours) == ("DEMO-C1", 12.5)
    assert detail.degrees[0].level is DegreeLevel.MASTER
    assert detail.degrees[0].status is DegreeStatus.COMPLETED
    assert service.list_certificates(staff_id) == list(detail.certificates)
    assert service.list_training(staff_id) == list(detail.training)
    assert service.list_degrees(staff_id) == list(detail.degrees)
    assert service.get_certificate(cert_id) == detail.certificates[0]
    assert _error(lambda: service.staff_detail(9999)).code == NOT_FOUND
    assert _error(lambda: service.get_certificate(9999)).code == NOT_FOUND


# --------------------------------------------------------------------------- identifier guard


@pytest.mark.parametrize(
    "value", ["123.456.789-09", "12345678909", "123456789-09", " 12345678909 "]
)
def test_cpf_looking_identifier_is_rejected(service: PersonnelService, value: str) -> None:
    error = _error(lambda: service.create_staff(_staff(value)))
    assert (error.code, error.field) == (IDENTIFIER_LOOKS_LIKE_NATIONAL_ID, "identifier")
    staff_id = service.create_staff(_staff("DEMO-P001"))
    assert _error(lambda: service.update_staff(staff_id, _staff(value))).code == (
        IDENTIFIER_LOOKS_LIKE_NATIONAL_ID
    )


@pytest.mark.parametrize("value", ["DEMO-P001", "1234567890", "P-123.456.789", "A12345678909"])
def test_local_code_is_accepted(service: PersonnelService, value: str) -> None:
    staff_id = service.create_staff(_staff(value))
    assert service.get_staff(staff_id).identifier == value


# --------------------------------------------------------------------------- certificate + mark


def test_add_certificate_with_a_mark_is_one_insert_row(
    service: PersonnelService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    staff_id = service.create_staff(_staff())
    holder: list[int] = []
    rows = _logged(
        db,
        change_log_rows,
        lambda: holder.append(
            service.add_certificate(
                staff_id, _cert(), no_renewal=NoRenewalMark("2026-01-01", "left_unit")
            )
        ),
    )
    assert [(row["entity"], row["action"]) for row in rows] == [("ppe_certification", "insert")]
    certificate = service.get_certificate(holder[0])
    assert (certificate.no_renewal_from, certificate.no_renewal_reason) == (
        date(2026, 1, 1),
        "left_unit",
    )


@pytest.mark.parametrize(
    ("mark", "code"),
    [
        (NoRenewalMark("2026-01-01", "retired"), INVALID_NO_RENEWAL_REASON),
        (NoRenewalMark(None, "other"), NO_RENEWAL_REASON_WITHOUT_DATE),
        (NoRenewalMark(None), REQUIRED),
        (NoRenewalMark("not-a-date"), INVALID_DATE),
    ],
)
def test_a_refused_mark_stores_no_certificate_and_no_log_row(
    service: PersonnelService,
    db: DatabaseConnection,
    change_log_rows: ChangeLogRows,
    mark: NoRenewalMark,
    code: str,
) -> None:
    staff_id = service.create_staff(_staff())
    before = _dump(db)
    log_before = len(change_log_rows(db))
    assert _error(lambda: service.add_certificate(staff_id, _cert(), no_renewal=mark)).code == code
    assert _count(db, "ppe_certification") == 0
    assert len(change_log_rows(db)) == log_before
    assert _dump(db) == before


def test_update_certificate_with_a_refused_mark_changes_nothing(
    service: PersonnelService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    staff_id = service.create_staff(_staff())
    cert_id = service.add_certificate(staff_id, _cert())
    before = _dump(db)
    log_before = len(change_log_rows(db))
    bad = NoRenewalMark("2026-01-01", "retired")
    changed = _cert(valid_until="2030-01-01")
    error = _error(lambda: service.update_certificate(cert_id, changed, no_renewal=bad))
    assert error.code == INVALID_NO_RENEWAL_REASON
    assert service.get_certificate(cert_id).valid_until == date(2027, 1, 10)
    assert len(change_log_rows(db)) == log_before
    assert _dump(db) == before


def test_update_certificate_sets_keeps_and_clears_the_mark(service: PersonnelService) -> None:
    staff_id = service.create_staff(_staff())
    cert_id = service.add_certificate(staff_id, _cert())
    service.update_certificate(
        cert_id, _cert(), no_renewal=NoRenewalMark("2026-02-01", "role_change")
    )
    marked = service.get_certificate(cert_id)
    assert (marked.no_renewal_from, marked.no_renewal_reason) == (date(2026, 2, 1), "role_change")
    service.update_certificate(cert_id, _cert(reference="r"))  # default: the mark is kept
    assert service.get_certificate(cert_id).no_renewal_from == date(2026, 2, 1)
    service.update_certificate(cert_id, _cert(), no_renewal=None)
    cleared = service.get_certificate(cert_id)
    assert (cleared.no_renewal_from, cleared.no_renewal_reason) == (None, None)


# --------------------------------------------------------------------------- pseudonymisation


def _pseudonym_fixture(service: PersonnelService) -> tuple[int, int, int]:
    """A person with distinctive personal text, two certificates, two trainings, three degrees."""
    staff_id = service.create_staff(
        _staff(SECRET_IDENTIFIER, label=SECRET_LABEL, category=SECRET_CATEGORY)
    )
    service.update_staff(
        staff_id, _staff(SECRET_IDENTIFIER, label=SECRET_LABEL, category=SECRET_CATEGORY_2)
    )
    course_id = service.create_course(_course())
    service.add_certificate(staff_id, _cert("A", "2025-01-10", "2026-04-10", SECRET_REFERENCE))
    service.add_certificate(staff_id, _cert("B", "2025-01-10", "2027-01-10", SECRET_REFERENCE_2))
    service.add_training(staff_id, TrainingInput(course_id, "2025-09-01", 4))
    service.add_training(staff_id, TrainingInput(course_id, "2025-10-01", 6))
    service.add_degree(staff_id, DegreeInput("master", year=2018, field=SECRET_FIELD))
    service.add_degree(staff_id, DegreeInput("master", year=2018, field=SECRET_FIELD_2))
    service.add_degree(staff_id, DegreeInput("doctorate", status="in_progress"))
    other = service.create_staff(_staff("DEMO-P002"))
    service.add_certificate(other, _cert("A", "2025-01-10", "2027-01-10"))
    return staff_id, other, course_id


def test_pseudonymise_leaves_no_old_value_anywhere_and_keeps_history(
    service: PersonnelService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    staff_id, other_id, _ = _pseudonym_fixture(service)
    before_detail = service.staff_detail(staff_id)
    before_summary = service.summary(AS_OF)
    before_values = service.indicator_values(AS_OF)
    before_levels = service.level_rows(AS_OF)
    before_other = service.staff_detail(other_id)
    assert SECRET_IDENTIFIER in _text_of(db, change_log=False)
    assert all(secret not in _text_of(db, change_log=True) for secret in SECRETS_ALL)

    rows = _logged(db, change_log_rows, lambda: service.pseudonymise_staff(staff_id))

    # one update row per changed row: person + 2 certificates + 2 degrees with a field
    assert _entities(rows) == Counter(
        {
            ("staff_member", "update"): 1,
            ("ppe_certification", "update"): 2,
            ("academic_degree", "update"): 2,
        }
    )
    assert all(row["operator"] == OPERATOR and row["at_utc"] == NOW_TEXT for row in rows)
    staff_row = next(row for row in rows if row["entity"] == "staff_member")
    assert json.loads(str(staff_row["before_json"]))["identifier"] == {"redacted": True}
    assert json.loads(str(staff_row["after_json"]))["identifier"] == {
        "redacted": True,
        "changed": True,
    }
    assert json.loads(str(staff_row["after_json"]))["label"] == {"redacted": True, "changed": True}
    assert json.loads(str(staff_row["after_json"]))["category"] == {
        "redacted": True,
        "changed": True,
    }

    for secret in SECRETS_ALL:
        assert secret not in _text_of(db, change_log=False)
        assert secret not in _text_of(db, change_log=True)

    after_detail = service.staff_detail(staff_id)
    assert after_detail.staff.identifier.startswith("PSEUDO-")
    assert after_detail.staff.label is None
    assert after_detail.staff.category is None  # P2-01: category is personal free text
    assert after_detail.staff.active_from == before_detail.staff.active_from
    assert [c.reference for c in after_detail.certificates] == [None, None]
    assert [(c.id, c.level, c.issued_on, c.valid_until) for c in after_detail.certificates] == [
        (c.id, c.level, c.issued_on, c.valid_until) for c in before_detail.certificates
    ]
    assert after_detail.training == before_detail.training
    assert [(d.id, d.level, d.status, d.year) for d in after_detail.degrees] == [
        (d.id, d.level, d.status, d.year) for d in before_detail.degrees
    ]
    # the degree that had no field gets none; the two that had one get different codes
    assert [d.field for d in after_detail.degrees if d.level is DegreeLevel.DOCTORATE] == [None]
    masters = [d.field for d in after_detail.degrees if d.level is DegreeLevel.MASTER]
    assert len(masters) == 2
    assert all(f is not None and f.startswith("PSEUDO-") for f in masters)
    assert masters[0] != masters[1]
    # nobody else is touched, and the readiness picture is unchanged
    assert service.staff_detail(other_id) == before_other
    assert service.summary(AS_OF) == before_summary
    assert service.indicator_values(AS_OF) == before_values
    assert [(r.level, r.status, r.valid_until) for r in service.level_rows(AS_OF)] == [
        (r.level, r.status, r.valid_until) for r in before_levels
    ]


def test_pseudonymise_uses_the_id_factory_and_returns_the_identifier(
    service: PersonnelService,
) -> None:
    staff_id = service.create_staff(_staff(SECRET_IDENTIFIER))
    service.add_degree(staff_id, DegreeInput("master", year=2018, field=SECRET_FIELD))
    assert service.pseudonymise_staff(staff_id) == "PSEUDO-000001"
    assert service.get_staff(staff_id).identifier == "PSEUDO-000001"
    assert service.list_degrees(staff_id)[0].field == "PSEUDO-000002"
    # twice: new codes again
    assert service.pseudonymise_staff(staff_id) == "PSEUDO-000003"
    assert service.list_degrees(staff_id)[0].field == "PSEUDO-000004"


def test_default_id_factory_gives_random_hex_codes(
    db: DatabaseConnection, clock: FixedClock
) -> None:
    service = PersonnelService(db, clock)
    first = service.create_staff(_staff("DEMO-P001"))
    second = service.create_staff(_staff("DEMO-P002"))
    code_a = service.pseudonymise_staff(first)
    code_b = service.pseudonymise_staff(second)
    pattern = re.compile(r"PSEUDO-[0-9A-F]{12}")
    assert pattern.fullmatch(code_a) is not None
    assert pattern.fullmatch(code_b) is not None
    assert code_a != code_b


def test_two_degrees_differing_only_in_field_survive_pseudonymisation(
    service: PersonnelService, db: DatabaseConnection
) -> None:
    staff_id = service.create_staff(_staff())
    service.add_degree(staff_id, DegreeInput("master", year=2018, field=SECRET_FIELD))
    service.add_degree(staff_id, DegreeInput("master", year=2018, field=SECRET_FIELD_2))
    service.pseudonymise_staff(staff_id)
    degrees = service.list_degrees(staff_id)
    assert len(degrees) == 2
    assert degrees[0].field != degrees[1].field
    assert {(d.level, d.year) for d in degrees} == {(DegreeLevel.MASTER, 2018)}
    assert _count(db, "academic_degree") == 2


def test_pseudonym_collision_is_retried(db: DatabaseConnection, clock: FixedClock) -> None:
    pool = iter(["DUP", "NEW"])
    service = PersonnelService(db, clock, id_factory=lambda: next(pool))
    taken = service.create_staff(_staff("PSEUDO-DUP"))
    person = service.create_staff(_staff("DEMO-P002"))
    assert service.pseudonymise_staff(person) == "PSEUDO-NEW"
    assert service.get_staff(taken).identifier == "PSEUDO-DUP"


def test_pseudonym_collision_that_cannot_be_resolved_changes_nothing(
    db: DatabaseConnection, clock: FixedClock
) -> None:
    service = PersonnelService(db, clock, lambda: OPERATOR, lambda: "A")
    staff_id = service.create_staff(_staff(SECRET_IDENTIFIER, label=SECRET_LABEL))
    service.add_degree(staff_id, DegreeInput("master", year=2018, field=SECRET_FIELD))
    service.add_degree(staff_id, DegreeInput("master", year=2019, field=SECRET_FIELD_2))
    before = _dump(db)
    # The identifier and the first degree get "PSEUDO-A"; the second degree finds it taken.
    assert _error(lambda: service.pseudonymise_staff(staff_id)).code == PSEUDONYM_COLLISION
    assert _dump(db) == before


def test_pseudonymise_unknown_person(service: PersonnelService) -> None:
    assert _error(lambda: service.pseudonymise_staff(9999)).code == NOT_FOUND


# --------------------------------------------------------------------------- domain equivalence


@dataclass(frozen=True)
class _Fixture:
    staff: list[domain.StaffMember]
    certs: list[domain.Certificate]
    training: list[domain.TrainingRecord]
    degrees: list[domain.Degree]
    ids: dict[str, int]


_STAFF_SPECS: list[tuple[str, str, str | None]] = [
    ("DEMO-P001", "2020-01-01", None),
    ("DEMO-P002", "2020-01-01", None),
    ("DEMO-P003", "2019-01-01", "2026-02-28"),  # left before the as-of date
    ("DEMO-P004", "2026-06-01", None),  # starts after the as-of date
    ("DEMO-P005", "2020-01-01", None),
    ("DEMO-P006", "2021-01-01", None),
]
# identifier, level, issued_on, valid_until, no_renewal_from
_CERT_SPECS: list[tuple[str, str, str, str, str | None]] = [
    ("DEMO-P001", "A", "2024-06-01", "2026-03-20", None),
    ("DEMO-P001", "B", "2025-01-10", "2027-01-10", None),
    ("DEMO-P002", "A", "2023-01-01", "2026-01-31", None),
    ("DEMO-P002", "C", "2025-04-01", "2026-04-01", "2026-02-01"),
    ("DEMO-P003", "A", "2025-01-01", "2027-01-01", None),
    ("DEMO-P004", "A", "2025-01-01", "2027-01-01", None),
    ("DEMO-P005", "B", "2025-12-31", "2026-12-31", None),
    ("DEMO-P006", "A", "2025-05-01", "2026-05-01", None),
    ("DEMO-P006", "B", "2026-04-01", "2028-04-01", None),  # issued after the as-of date
]
# identifier, completed_on
_TRAINING_SPECS: list[tuple[str, str]] = [
    ("DEMO-P001", "2025-10-01"),
    ("DEMO-P001", "2024-01-01"),  # outside the 12-month window
    ("DEMO-P002", "2026-01-15"),
    ("DEMO-P003", "2026-01-10"),  # not active
]
# identifier, level, status
_DEGREE_SPECS: list[tuple[str, str, str]] = [
    ("DEMO-P001", "master", "completed"),
    ("DEMO-P002", "doctorate", "in_progress"),
    ("DEMO-P003", "master", "completed"),
]


def _load_fixture(service: PersonnelService) -> _Fixture:
    ids: dict[str, int] = {}
    staff: list[domain.StaffMember] = []
    for identifier, active_from, active_until in _STAFF_SPECS:
        staff_id = service.create_staff(
            _staff(identifier, active_from=active_from, active_until=active_until)
        )
        ids[identifier] = staff_id
        staff.append(
            domain.StaffMember(
                id=staff_id,
                identifier=identifier,
                active_from=_d(active_from),
                active_until=None if active_until is None else _d(active_until),
            )
        )
    certs: list[domain.Certificate] = []
    for identifier, level, issued_on, valid_until, no_renewal in _CERT_SPECS:
        cert_id = service.add_certificate(ids[identifier], _cert(level, issued_on, valid_until))
        if no_renewal is not None:
            service.set_no_renewal(cert_id, no_renewal, "role_change")
        certs.append(
            domain.Certificate(
                id=cert_id,
                staff_id=ids[identifier],
                level=PpeLevel(level),
                issued_on=_d(issued_on),
                valid_until=_d(valid_until),
                no_renewal_from=None if no_renewal is None else _d(no_renewal),
            )
        )
    course_id = service.create_course(_course())
    training: list[domain.TrainingRecord] = []
    for identifier, completed_on in _TRAINING_SPECS:
        service.add_training(ids[identifier], TrainingInput(course_id, completed_on, 8))
        training.append(domain.TrainingRecord(ids[identifier], _d(completed_on)))
    degrees: list[domain.Degree] = []
    for identifier, level, status in _DEGREE_SPECS:
        service.add_degree(ids[identifier], DegreeInput(level, status))
        degrees.append(domain.Degree(ids[identifier], DegreeLevel(level), DegreeStatus(status)))
    return _Fixture(staff=staff, certs=certs, training=training, degrees=degrees, ids=ids)


@pytest.mark.parametrize(
    ("config", "expected_retraining"),
    [
        (ReadinessConfig(), {"DEMO-P001", "DEMO-P002", "DEMO-P006"}),
        (_CUSTOM_CONFIG, {"DEMO-P001", "DEMO-P002"}),
    ],
    ids=["default-config", "custom-config"],
)
def test_service_views_equal_the_domain_results(
    db: DatabaseConnection,
    clock: FixedClock,
    service: PersonnelService,
    config: ReadinessConfig,
    expected_retraining: set[str],
) -> None:
    if config != ReadinessConfig():
        _save_config(db, clock, config)
    fixture = _load_fixture(service)
    rules = _domain_rules(config)

    level_rows = domain.staff_level_rows(fixture.staff, fixture.certs, AS_OF, rules)
    retraining = domain.retraining_list(fixture.staff, fixture.certs, AS_OF, rules)
    expiring = domain.expiring_list(fixture.staff, fixture.certs, AS_OF, rules)
    values = domain.indicator_values(
        fixture.staff, fixture.certs, fixture.training, fixture.degrees, AS_OF, rules
    )

    assert service.level_rows(AS_OF) == level_rows
    assert service.retraining_list(AS_OF) == retraining
    assert service.expiring_list(AS_OF) == expiring
    assert service.indicator_values(AS_OF) == values

    assert level_rows != []
    assert {row.identifier for row in retraining} == expected_retraining
    assert any(row.status is CertStatus.NO_RENEWAL for row in level_rows)

    by_key = {(value.code, value.dimension): value.value for value in values}
    summary = service.summary(AS_OF)
    assert [item.level for item in summary] == list(PpeLevel)
    for item in summary:
        dimension = encode_dimension({"level": item.level.value})
        assert item.valid == by_key[("PERS_CERT_VALID", dimension)]
        assert item.expiring == by_key[("PERS_CERT_EXPIRING", dimension)]
        assert item.retraining_needed == by_key[("PERS_RETRAINING_NEEDED", dimension)]
    assert sum(item.valid for item in summary) > 0
    assert sum(item.retraining_needed for item in summary) > 0


def test_configuration_is_read_on_each_call(
    db: DatabaseConnection, clock: FixedClock, service: PersonnelService
) -> None:
    _load_fixture(service)
    default_expiring = {row.identifier for row in service.expiring_list(AS_OF)}
    _save_config(db, clock, ReadinessConfig().with_changes(cert_warning_days=10))
    narrow_expiring = {row.identifier for row in service.expiring_list(AS_OF)}
    assert "DEMO-P006" in default_expiring
    assert narrow_expiring == set()


def test_alert_inputs_are_the_domain_objects_and_the_stored_rules(
    db: DatabaseConnection, clock: FixedClock, service: PersonnelService
) -> None:
    staff_id = service.create_staff(_staff())
    cert_id = service.add_certificate(staff_id, _cert("A", "2025-01-10", "2026-03-20"))
    service.set_no_renewal(cert_id, "2026-03-10")

    inputs = service.alert_inputs()
    assert [(person.id, person.identifier) for person in inputs.staff] == [(staff_id, "DEMO-P001")]
    [cert] = inputs.certificates
    assert (cert.id, cert.staff_id, cert.level) == (cert_id, staff_id, PpeLevel.A)
    assert (cert.valid_until, cert.no_renewal_from) == (date(2026, 3, 20), date(2026, 3, 10))
    assert inputs.rules == _domain_rules(ReadinessConfig())
    # the same objects feed the page's own views
    assert domain.expiring_list(inputs.staff, inputs.certificates, AS_OF, inputs.rules) == (
        service.expiring_list(AS_OF)
    )

    config = ReadinessConfig().with_changes(cert_warning_days=10)
    _save_config(db, clock, config)
    assert service.alert_inputs().rules == _domain_rules(config)


# --------------------------------------------------------------------------- certificates


def test_no_renewal_round_trip(service: PersonnelService, db: DatabaseConnection) -> None:
    staff_id = service.create_staff(_staff())
    cert_id = service.add_certificate(staff_id, _cert("A", "2025-01-10", "2026-03-20"))
    assert service.get_certificate(cert_id).no_renewal_from is None
    assert [row.identifier for row in service.retraining_list(AS_OF)] == ["DEMO-P001"]

    service.set_no_renewal(cert_id, "2026-02-01", "left_unit")
    view = service.get_certificate(cert_id)
    assert (view.no_renewal_from, view.no_renewal_reason) == (date(2026, 2, 1), "left_unit")
    assert service.retraining_list(AS_OF) == []
    assert service.expiring_list(AS_OF) == []

    service.set_no_renewal(cert_id, date(2026, 2, 2))  # no reason is fine; a date object too
    view = service.get_certificate(cert_id)
    assert (view.no_renewal_from, view.no_renewal_reason) == (date(2026, 2, 2), None)
    for reason in ("role_change", "other"):
        service.set_no_renewal(cert_id, "2026-02-01", reason)
        assert service.get_certificate(cert_id).no_renewal_reason == reason

    service.clear_no_renewal(cert_id)
    view = service.get_certificate(cert_id)
    assert (view.no_renewal_from, view.no_renewal_reason) == (None, None)
    assert [row.identifier for row in service.retraining_list(AS_OF)] == ["DEMO-P001"]
    assert _count(db, "ppe_certification") == 1


def test_update_certificate_keeps_the_no_renewal_mark(service: PersonnelService) -> None:
    staff_id = service.create_staff(_staff())
    cert_id = service.add_certificate(staff_id, _cert())
    service.set_no_renewal(cert_id, "2026-02-01", "other")
    service.update_certificate(cert_id, _cert("A", "2025-01-10", "2028-01-10", "ref"))
    view = service.get_certificate(cert_id)
    assert view.valid_until == date(2028, 1, 10)
    assert (view.no_renewal_from, view.no_renewal_reason) == (date(2026, 2, 1), "other")


def test_update_certificate_may_keep_its_own_key(service: PersonnelService) -> None:
    staff_id = service.create_staff(_staff())
    cert_id = service.add_certificate(staff_id, _cert())
    service.update_certificate(cert_id, _cert("A", "2025-01-10", "2029-01-10"))
    assert service.get_certificate(cert_id).valid_until == date(2029, 1, 10)


def test_propose_valid_until_with_and_without_configured_months(
    db: DatabaseConnection, clock: FixedClock, service: PersonnelService
) -> None:
    assert service.propose_valid_until("A", "2025-01-10") is None
    assert service.propose_valid_until("B", date(2025, 1, 10)) is None
    _save_config(
        db,
        clock,
        ReadinessConfig().with_changes(ppe_validity_months={"A": 24, "B": None, "C": 12}),
    )
    assert service.propose_valid_until("A", "2025-01-10") == date(2027, 1, 10)
    assert service.propose_valid_until("B", "2025-01-10") is None
    assert service.propose_valid_until("C", "2024-02-29") == date(2025, 2, 28)
    assert _error(lambda: service.propose_valid_until("D", "2025-01-10")).code == INVALID_PPE_LEVEL
    assert _error(lambda: service.propose_valid_until("A", "x")).code == INVALID_DATE


# --------------------------------------------------------------------------- courses


def test_course_rules(
    service: PersonnelService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    course_id = service.create_course(
        CourseInput("DEMO-C1", "Curso Demo", label_en_us="Demo course", label_es_es=" ")
    )
    view = service.list_courses()[0]
    assert (view.id, view.code, view.label_es_es, view.active) == (course_id, "DEMO-C1", None, True)

    # the code can change while no record uses the course ...
    service.update_course(course_id, _course("DEMO-C1B"))
    assert service.list_courses()[0].code == "DEMO-C1B"
    # ... and is frozen once one does
    staff_id = service.create_staff(_staff())
    training_id = service.add_training(staff_id, TrainingInput(course_id, "2025-06-01"))
    assert _error(lambda: service.update_course(course_id, _course("DEMO-C1"))).code == (
        CODE_IMMUTABLE
    )
    service.update_course(course_id, _course("DEMO-C1B", label="Novo nome"))  # label change is ok
    assert _error(lambda: service.delete_course(course_id)).code == COURSE_IN_USE
    assert _count(db, "training_course") == 1

    # an unused course can be deleted
    spare = service.create_course(_course("DEMO-C2"))
    rows = _logged(db, change_log_rows, lambda: service.delete_course(spare))
    assert [(row["entity"], row["action"]) for row in rows] == [("training_course", "delete")]
    service.delete_training(training_id)
    service.delete_course(course_id)
    assert service.list_courses(include_inactive=True) == []


def test_inactive_course_refuses_new_records_but_keeps_old_ones(
    service: PersonnelService,
) -> None:
    staff_id = service.create_staff(_staff())
    course_id = service.create_course(_course())
    other_id = service.create_course(_course("DEMO-C2"))
    training_id = service.add_training(staff_id, TrainingInput(course_id, "2025-06-01"))
    service.deactivate_course(course_id)
    assert [c.code for c in service.list_courses()] == ["DEMO-C2"]
    assert [c.code for c in service.list_courses(include_inactive=True)] == ["DEMO-C1", "DEMO-C2"]
    late = TrainingInput(course_id, "2025-07-01")
    assert _error(lambda: service.add_training(staff_id, late)).code == COURSE_INACTIVE
    # the existing record can still be corrected without changing its course
    service.update_training(training_id, TrainingInput(course_id, "2025-06-15", 3))
    assert service.list_training(staff_id)[0].completed_on == date(2025, 6, 15)
    # but cannot be moved to an inactive course
    moved = service.add_training(staff_id, TrainingInput(other_id, "2025-08-01"))
    back = TrainingInput(course_id, "2025-08-01")
    assert _error(lambda: service.update_training(moved, back)).code == COURSE_INACTIVE
    # reactivating through update_course makes it usable again
    service.update_course(course_id, CourseInput("DEMO-C1", "Curso Demo", active=True))
    service.add_training(staff_id, TrainingInput(course_id, "2025-07-01"))


def test_course_label_fallback() -> None:
    full = CourseView(1, "DEMO-C1", "Curso", "Course", "Curso ES", True)
    assert course_label(full, "pt_BR") == "Curso"
    assert course_label(full, "en-US") == "Course"
    assert course_label(full, "es_ES") == "Curso ES"
    no_es = CourseView(1, "DEMO-C1", "Curso", "Course", None, True)
    assert course_label(no_es, "es_ES") == "Curso"
    only_en = CourseView(1, "DEMO-C1", None, "Course", " ", True)
    assert course_label(only_en, "es_ES") == "Course"
    nothing = CourseView(1, "DEMO-C1", None, None, None, True)
    assert course_label(nothing, "pt_BR") == "DEMO-C1"


def test_degree_duplicates_treat_null_field_and_year_as_equal(
    service: PersonnelService,
) -> None:
    staff_id = service.create_staff(_staff())
    first = service.add_degree(staff_id, DegreeInput("master"))
    in_progress = DegreeInput("master", "in_progress")
    blank_field = DegreeInput("master", field="  ")
    assert _error(lambda: service.add_degree(staff_id, in_progress)).code == DUPLICATE_DEGREE
    assert _error(lambda: service.add_degree(staff_id, blank_field)).code == DUPLICATE_DEGREE
    service.add_degree(staff_id, DegreeInput("master", year=2020))  # a year makes it distinct
    service.update_degree(first, DegreeInput("master", "in_progress"))  # its own key is fine
    assert service.list_degrees(staff_id)[0].status is DegreeStatus.IN_PROGRESS


def test_nan_hours_are_refused(service: PersonnelService) -> None:
    staff_id = service.create_staff(_staff())
    course_id = service.create_course(_course())
    nan = float("nan")
    bad = TrainingInput(course_id, "2025-06-01", nan)
    assert _error(lambda: service.add_training(staff_id, bad)).code == INVALID_NUMBER
    assert service.add_training(staff_id, TrainingInput(course_id, "2025-06-01", 0)) > 0


# --------------------------------------------------------------------------- validation codes


@dataclass(frozen=True)
class _World:
    staff_id: int
    other_id: int
    course_id: int
    inactive_course_id: int
    cert_id: int
    cert2_id: int
    training_id: int
    training2_id: int
    degree_id: int
    degree2_id: int


@pytest.fixture
def world(service: PersonnelService) -> _World:
    staff_id = service.create_staff(_staff("DEMO-P001"))
    other_id = service.create_staff(_staff("DEMO-P002"))
    course_id = service.create_course(_course("DEMO-C1"))
    inactive_course_id = service.create_course(_course("DEMO-C2"))
    service.deactivate_course(inactive_course_id)
    return _World(
        staff_id=staff_id,
        other_id=other_id,
        course_id=course_id,
        inactive_course_id=inactive_course_id,
        cert_id=service.add_certificate(staff_id, _cert("A", "2025-01-10", "2027-01-10")),
        cert2_id=service.add_certificate(staff_id, _cert("A", "2025-02-10", "2027-02-10")),
        training_id=service.add_training(staff_id, TrainingInput(course_id, "2025-06-01", 8)),
        training2_id=service.add_training(staff_id, TrainingInput(course_id, "2025-07-01", 8)),
        degree_id=service.add_degree(staff_id, DegreeInput("master", year=2018, field="Field")),
        degree2_id=service.add_degree(staff_id, DegreeInput("master", year=2019, field="Field")),
    )


type _Call = Callable[[PersonnelService, _World], object]

_CASES: list[tuple[str, _Call]] = [
    # staff
    (REQUIRED, lambda s, w: s.create_staff(_staff("  "))),
    (REQUIRED, lambda s, w: s.create_staff(_staff("DEMO-P9", active_from=""))),
    (DUPLICATE_IDENTIFIER, lambda s, w: s.create_staff(_staff("DEMO-P001"))),
    (DUPLICATE_IDENTIFIER, lambda s, w: s.update_staff(w.other_id, _staff("DEMO-P001"))),
    (INVALID_DATE, lambda s, w: s.create_staff(_staff("DEMO-P9", active_from="2020-13-01"))),
    (INVALID_DATE, lambda s, w: s.create_staff(_staff("DEMO-P9", active_until="05/03/2026"))),
    (INVALID_DATE, lambda s, w: s.deactivate_staff(w.staff_id, "yesterday")),
    (
        ACTIVE_UNTIL_BEFORE_FROM,
        lambda s, w: s.create_staff(_staff("DEMO-P9", active_until="2019-12-31")),
    ),
    (ACTIVE_UNTIL_BEFORE_FROM, lambda s, w: s.deactivate_staff(w.staff_id, "2019-12-31")),
    (TEXT_TOO_LONG, lambda s, w: s.create_staff(_staff("D" * 65))),
    (TEXT_TOO_LONG, lambda s, w: s.create_staff(_staff("DEMO-P9", label="L" * 121))),
    (TEXT_TOO_LONG, lambda s, w: s.create_staff(_staff("DEMO-P9", category="C" * 65))),
    (TEXT_TOO_LONG, lambda s, w: s.add_certificate(w.other_id, _cert(reference="R" * 201))),
    (TEXT_TOO_LONG, lambda s, w: s.add_degree(w.other_id, DegreeInput("master", field="F" * 201))),
    (
        IDENTIFIER_LOOKS_LIKE_NATIONAL_ID,
        lambda s, w: s.create_staff(_staff("123.456.789-09")),
    ),
    (NOT_FOUND, lambda s, w: s.update_staff(9999, _staff("DEMO-P9"))),
    (NOT_FOUND, lambda s, w: s.deactivate_staff(9999, "2026-01-01")),
    (NOT_FOUND, lambda s, w: s.delete_staff(9999)),
    # certificates
    (REQUIRED, lambda s, w: s.add_certificate(w.other_id, _cert(level=""))),
    (REQUIRED, lambda s, w: s.add_certificate(w.other_id, _cert(issued_on=""))),
    (REQUIRED, lambda s, w: s.set_no_renewal(w.cert_id, None, None)),
    (INVALID_PPE_LEVEL, lambda s, w: s.add_certificate(w.other_id, _cert("D"))),
    (INVALID_PPE_LEVEL, lambda s, w: s.update_certificate(w.cert_id, _cert("a"))),
    (INVALID_DATE, lambda s, w: s.add_certificate(w.other_id, _cert(valid_until="2027-02-30"))),
    (
        VALID_UNTIL_BEFORE_ISSUED,
        lambda s, w: s.add_certificate(w.other_id, _cert("B", "2025-03-01", "2025-02-28")),
    ),
    (
        VALID_UNTIL_BEFORE_ISSUED,
        lambda s, w: s.update_certificate(w.cert_id, _cert("A", "2025-01-10", "2025-01-09")),
    ),
    (
        DUPLICATE_CERTIFICATE,
        lambda s, w: s.add_certificate(w.staff_id, _cert("A", "2025-01-10", "2026-01-10")),
    ),
    (
        DUPLICATE_CERTIFICATE,
        lambda s, w: s.update_certificate(w.cert2_id, _cert("A", "2025-01-10", "2027-02-10")),
    ),
    (NOT_FOUND, lambda s, w: s.add_certificate(9999, _cert())),
    (NOT_FOUND, lambda s, w: s.update_certificate(9999, _cert())),
    (NOT_FOUND, lambda s, w: s.delete_certificate(9999)),
    (NOT_FOUND, lambda s, w: s.set_no_renewal(9999, "2026-01-01")),
    (NOT_FOUND, lambda s, w: s.clear_no_renewal(9999)),
    (INVALID_NO_RENEWAL_REASON, lambda s, w: s.set_no_renewal(w.cert_id, "2026-01-01", "x")),
    (INVALID_NO_RENEWAL_REASON, lambda s, w: s.set_no_renewal(w.cert_id, None, "x")),
    (NO_RENEWAL_REASON_WITHOUT_DATE, lambda s, w: s.set_no_renewal(w.cert_id, None, "other")),
    (INVALID_DATE, lambda s, w: s.set_no_renewal(w.cert_id, "soon")),
    # courses
    (REQUIRED, lambda s, w: s.create_course(_course(" "))),
    (INVALID_CODE, lambda s, w: s.create_course(_course("bad code!"))),
    (DUPLICATE_CODE, lambda s, w: s.create_course(_course("DEMO-C1"))),
    (DUPLICATE_CODE, lambda s, w: s.update_course(w.inactive_course_id, _course("DEMO-C1"))),
    (LABEL_PT_BR_REQUIRED, lambda s, w: s.create_course(CourseInput("DEMO-C9", "  ", "English"))),
    (LABEL_PT_BR_REQUIRED, lambda s, w: s.update_course(w.course_id, _course("DEMO-C1", None))),
    (COURSE_IN_USE, lambda s, w: s.delete_course(w.course_id)),
    (CODE_IMMUTABLE, lambda s, w: s.update_course(w.course_id, _course("DEMO-C1X"))),
    (NOT_FOUND, lambda s, w: s.update_course(9999, _course())),
    (NOT_FOUND, lambda s, w: s.deactivate_course(9999)),
    (NOT_FOUND, lambda s, w: s.delete_course(9999)),
    # training records
    (
        COURSE_INACTIVE,
        lambda s, w: s.add_training(w.staff_id, TrainingInput(w.inactive_course_id, "2025-08-01")),
    ),
    (
        COURSE_INACTIVE,
        lambda s, w: s.update_training(
            w.training_id, TrainingInput(w.inactive_course_id, "2025-06-01")
        ),
    ),
    (
        DUPLICATE_TRAINING,
        lambda s, w: s.add_training(w.staff_id, TrainingInput(w.course_id, "2025-06-01")),
    ),
    (
        DUPLICATE_TRAINING,
        lambda s, w: s.update_training(w.training2_id, TrainingInput(w.course_id, "2025-06-01")),
    ),
    (
        NEGATIVE_HOURS,
        lambda s, w: s.add_training(w.staff_id, TrainingInput(w.course_id, "2025-08-01", -0.5)),
    ),
    (
        INVALID_NUMBER,
        lambda s, w: s.add_training(
            w.staff_id, TrainingInput(w.course_id, "2025-08-01", float("inf"))
        ),
    ),
    (
        INVALID_NUMBER,
        lambda s, w: s.update_training(
            w.training_id, TrainingInput(w.course_id, "2025-06-01", float("nan"))
        ),
    ),
    (INVALID_DATE, lambda s, w: s.add_training(w.staff_id, TrainingInput(w.course_id, "2025-6-1"))),
    (NOT_FOUND, lambda s, w: s.add_training(w.staff_id, TrainingInput(9999, "2025-08-01"))),
    (NOT_FOUND, lambda s, w: s.add_training(9999, TrainingInput(w.course_id, "2025-08-01"))),
    (NOT_FOUND, lambda s, w: s.update_training(9999, TrainingInput(w.course_id, "2025-08-01"))),
    (NOT_FOUND, lambda s, w: s.delete_training(9999)),
    # degrees
    (INVALID_DEGREE_LEVEL, lambda s, w: s.add_degree(w.other_id, DegreeInput("bachelor"))),
    (REQUIRED, lambda s, w: s.add_degree(w.other_id, DegreeInput(""))),
    (INVALID_DEGREE_STATUS, lambda s, w: s.add_degree(w.other_id, DegreeInput("master", "done"))),
    (INVALID_YEAR, lambda s, w: s.add_degree(w.other_id, DegreeInput("master", year=1899))),
    (INVALID_YEAR, lambda s, w: s.add_degree(w.other_id, DegreeInput("master", year=2201))),
    (INVALID_YEAR, lambda s, w: s.update_degree(w.degree_id, DegreeInput("master", year=0))),
    (
        DUPLICATE_DEGREE,
        lambda s, w: s.add_degree(w.staff_id, DegreeInput("master", year=2018, field="Field")),
    ),
    (
        DUPLICATE_DEGREE,
        lambda s, w: s.update_degree(w.degree2_id, DegreeInput("master", year=2018, field="Field")),
    ),
    (NOT_FOUND, lambda s, w: s.add_degree(9999, DegreeInput("master"))),
    (NOT_FOUND, lambda s, w: s.update_degree(9999, DegreeInput("master"))),
    (NOT_FOUND, lambda s, w: s.delete_degree(9999)),
]

_EXPECTED_CODES = {
    REQUIRED,
    DUPLICATE_IDENTIFIER,
    INVALID_DATE,
    ACTIVE_UNTIL_BEFORE_FROM,
    TEXT_TOO_LONG,
    IDENTIFIER_LOOKS_LIKE_NATIONAL_ID,
    INVALID_PPE_LEVEL,
    VALID_UNTIL_BEFORE_ISSUED,
    DUPLICATE_CERTIFICATE,
    NOT_FOUND,
    INVALID_NO_RENEWAL_REASON,
    NO_RENEWAL_REASON_WITHOUT_DATE,
    INVALID_CODE,
    DUPLICATE_CODE,
    LABEL_PT_BR_REQUIRED,
    COURSE_IN_USE,
    CODE_IMMUTABLE,
    COURSE_INACTIVE,
    DUPLICATE_TRAINING,
    NEGATIVE_HOURS,
    INVALID_NUMBER,
    INVALID_DEGREE_LEVEL,
    INVALID_DEGREE_STATUS,
    INVALID_YEAR,
    DUPLICATE_DEGREE,
}


def test_every_validation_code_is_covered() -> None:
    assert {code for code, _ in _CASES} >= _EXPECTED_CODES


@pytest.mark.parametrize(
    ("code", "call"), _CASES, ids=[f"{code}-{index}" for index, (code, _) in enumerate(_CASES)]
)
def test_validation_failure_returns_a_code_and_writes_nothing(
    service: PersonnelService, db: DatabaseConnection, world: _World, code: str, call: _Call
) -> None:
    before = _dump(db)
    error = _error(lambda: call(service, world))
    assert error.code == code
    assert _dump(db) == before  # no data row, no change_log row


def test_error_names_the_field_and_has_no_values(service: PersonnelService) -> None:
    error = _error(lambda: service.create_staff(_staff(SECRET_IDENTIFIER, active_from="nope")))
    assert (error.code, error.field) == (INVALID_DATE, "active_from")
    assert SECRET_IDENTIFIER not in str(error)


# --------------------------------------------------------------------------- read-only


_MUTATIONS: list[Callable[[PersonnelService], object]] = [
    lambda s: s.create_staff(_staff()),
    lambda s: s.update_staff(1, _staff()),
    lambda s: s.deactivate_staff(1, "2026-01-01"),
    lambda s: s.delete_staff(1),
    lambda s: s.pseudonymise_staff(1),
    lambda s: s.add_certificate(1, _cert()),
    lambda s: s.update_certificate(1, _cert()),
    lambda s: s.delete_certificate(1),
    lambda s: s.set_no_renewal(1, "2026-01-01", "other"),
    lambda s: s.clear_no_renewal(1),
    lambda s: s.create_course(_course()),
    lambda s: s.update_course(1, _course()),
    lambda s: s.deactivate_course(1),
    lambda s: s.delete_course(1),
    lambda s: s.add_training(1, TrainingInput(1, "2026-01-01")),
    lambda s: s.update_training(1, TrainingInput(1, "2026-01-01")),
    lambda s: s.delete_training(1),
    lambda s: s.add_degree(1, DegreeInput("master")),
    lambda s: s.update_degree(1, DegreeInput("master")),
    lambda s: s.delete_degree(1),
]


@pytest.mark.parametrize("index", range(len(_MUTATIONS)))
def test_read_only_connection_refuses_every_mutation(
    read_only_db: DatabaseConnection, clock: FixedClock, index: int
) -> None:
    readonly = PersonnelService(read_only_db, clock, lambda: OPERATOR, _Ids())
    assert _error(lambda: _MUTATIONS[index](readonly)).code == READ_ONLY


def test_reads_work_on_a_read_only_connection(
    service: PersonnelService, read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    fixture = _load_fixture(service)
    readonly = PersonnelService(read_only_db, clock)
    staff_id = fixture.ids["DEMO-P001"]
    assert len(readonly.list_staff()) == len(_STAFF_SPECS)
    assert readonly.get_staff(staff_id).identifier == "DEMO-P001"
    assert readonly.staff_detail(staff_id).certificates != ()
    assert readonly.list_courses()[0].code == "DEMO-C1"
    assert readonly.summary(AS_OF) == service.summary(AS_OF)
    assert readonly.level_rows(AS_OF) == service.level_rows(AS_OF)
    assert readonly.retraining_list(AS_OF) == service.retraining_list(AS_OF)
    assert readonly.expiring_list(AS_OF) == service.expiring_list(AS_OF)
    assert readonly.indicator_values(AS_OF) == service.indicator_values(AS_OF)
    assert readonly.propose_valid_until("A", "2025-01-10") is None
