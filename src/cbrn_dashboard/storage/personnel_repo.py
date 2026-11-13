# SPDX-License-Identifier: GPL-3.0-or-later
"""Storage of staff members, PPE certificates, courses, training records and degrees (T2.3).

Reads are plain parameterised ``SELECT`` statements. Every write goes through the repository
helpers (:func:`~cbrn_dashboard.storage.repository.insert`, ``update`` and ``delete``), so each
affected row gets its ``change_log`` row in the same transaction; the helpers also keep the personal
free-text columns (``staff_member.identifier``/``label``, ``ppe_certification.reference``,
``academic_degree.field``) out of the log (D17, section 5.1). This module checks no business rule:
that is the service's job (``services/personnel.py``). It also holds the one place where rows
become domain objects.

Dates are ISO text as stored; the converters parse them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cbrn_dashboard.domain.dates import parse_iso_date
from cbrn_dashboard.domain.personnel import (
    Certificate,
    Degree,
    DegreeLevel,
    DegreeStatus,
    PpeLevel,
    StaffMember,
    TrainingRecord,
)
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import RepositoryError, WriteContext, delete, insert, update

__all__ = [
    "CertificateRow",
    "CourseRow",
    "DegreeRow",
    "StaffRow",
    "TrainingRow",
    "certificate_to_domain",
    "clear_certificate_reference",
    "course_in_use",
    "degree_to_domain",
    "delete_certificate",
    "delete_course",
    "delete_degree",
    "delete_staff",
    "delete_training",
    "find_degree",
    "get_certificate",
    "get_certificate_by_key",
    "get_course",
    "get_course_by_code",
    "get_degree",
    "get_staff",
    "get_staff_by_identifier",
    "get_training",
    "get_training_by_key",
    "insert_certificate",
    "insert_course",
    "insert_degree",
    "insert_staff",
    "insert_training",
    "list_certificates",
    "list_courses",
    "list_degrees",
    "list_staff",
    "list_training",
    "set_certificate_no_renewal",
    "set_degree_field",
    "set_staff_pseudonym",
    "staff_to_domain",
    "training_to_domain",
    "update_certificate",
    "update_course",
    "update_degree",
    "update_staff",
    "update_training",
]

_STAFF = "staff_member"
_CERTIFICATE = "ppe_certification"
_COURSE = "training_course"
_TRAINING = "training_record"
_DEGREE = "academic_degree"

_STAFF_COLUMNS = "id, identifier, label, category, active_from, active_until"
_CERTIFICATE_COLUMNS = (
    "id, staff_id, ppe_level, issued_on, valid_until, no_renewal_from, no_renewal_reason, reference"
)
_COURSE_COLUMNS = "id, code, label_pt_br, label_en_us, label_es_es, active"
_TRAINING_COLUMNS = "id, staff_id, course_id, completed_on, hours"
_DEGREE_COLUMNS = "id, staff_id, level, status, year, field"


# --------------------------------------------------------------------------- rows


@dataclass(frozen=True)
class StaffRow:
    """A row of ``staff_member``; the dates are ISO text as stored."""

    id: int
    identifier: str
    label: str | None
    category: str | None
    active_from: str
    active_until: str | None


@dataclass(frozen=True)
class CertificateRow:
    """A row of ``ppe_certification``."""

    id: int
    staff_id: int
    ppe_level: str
    issued_on: str
    valid_until: str
    no_renewal_from: str | None
    no_renewal_reason: str | None
    reference: str | None


@dataclass(frozen=True)
class CourseRow:
    """A row of ``training_course``."""

    id: int
    code: str
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    active: bool


@dataclass(frozen=True)
class TrainingRow:
    """A row of ``training_record``."""

    id: int
    staff_id: int
    course_id: int
    completed_on: str
    hours: float | None


@dataclass(frozen=True)
class DegreeRow:
    """A row of ``academic_degree``."""

    id: int
    staff_id: int
    level: str
    status: str
    year: int | None
    field: str | None


def _text(value: object) -> str:
    return str(value)


def _opt_text(value: object) -> str | None:
    return None if value is None else str(value)


def _int(value: object) -> int:
    if isinstance(value, int):
        return value
    msg = "Expected an integer column."
    raise RepositoryError(msg, "UNEXPECTED_COLUMN_TYPE")


def _opt_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    msg = "Expected a numeric column."
    raise RepositoryError(msg, "UNEXPECTED_COLUMN_TYPE")


def _new_id(new_id: int | None) -> int:
    if new_id is None:
        msg = "The new row has no id."
        raise RepositoryError(msg, "INSERT_NOT_FOUND")
    return new_id


def _staff_row(row: sqlite3.Row) -> StaffRow:
    return StaffRow(
        id=_int(row["id"]),
        identifier=_text(row["identifier"]),
        label=_opt_text(row["label"]),
        category=_opt_text(row["category"]),
        active_from=_text(row["active_from"]),
        active_until=_opt_text(row["active_until"]),
    )


def _certificate_row(row: sqlite3.Row) -> CertificateRow:
    return CertificateRow(
        id=_int(row["id"]),
        staff_id=_int(row["staff_id"]),
        ppe_level=_text(row["ppe_level"]),
        issued_on=_text(row["issued_on"]),
        valid_until=_text(row["valid_until"]),
        no_renewal_from=_opt_text(row["no_renewal_from"]),
        no_renewal_reason=_opt_text(row["no_renewal_reason"]),
        reference=_opt_text(row["reference"]),
    )


def _course_row(row: sqlite3.Row) -> CourseRow:
    return CourseRow(
        id=_int(row["id"]),
        code=_text(row["code"]),
        label_pt_br=_opt_text(row["label_pt_br"]),
        label_en_us=_opt_text(row["label_en_us"]),
        label_es_es=_opt_text(row["label_es_es"]),
        active=_int(row["active"]) == 1,
    )


def _training_row(row: sqlite3.Row) -> TrainingRow:
    return TrainingRow(
        id=_int(row["id"]),
        staff_id=_int(row["staff_id"]),
        course_id=_int(row["course_id"]),
        completed_on=_text(row["completed_on"]),
        hours=_opt_float(row["hours"]),
    )


def _degree_row(row: sqlite3.Row) -> DegreeRow:
    return DegreeRow(
        id=_int(row["id"]),
        staff_id=_int(row["staff_id"]),
        level=_text(row["level"]),
        status=_text(row["status"]),
        year=_opt_int(row["year"]),
        field=_opt_text(row["field"]),
    )


# --------------------------------------------------------------------------- staff


def list_staff(conn: DatabaseConnection) -> list[StaffRow]:
    """All staff members ordered by identifier."""
    sql = f"SELECT {_STAFF_COLUMNS} FROM staff_member ORDER BY identifier, id"
    return [_staff_row(row) for row in conn.execute(sql).fetchall()]


def get_staff(conn: DatabaseConnection, staff_id: int) -> StaffRow | None:
    sql = f"SELECT {_STAFF_COLUMNS} FROM staff_member WHERE id = ?"
    row = conn.execute(sql, (staff_id,)).fetchone()
    return None if row is None else _staff_row(row)


def get_staff_by_identifier(conn: DatabaseConnection, identifier: str) -> StaffRow | None:
    """The person with this identifier (natural key for the CSV import, T8.4)."""
    sql = f"SELECT {_STAFF_COLUMNS} FROM staff_member WHERE identifier = ?"
    row = conn.execute(sql, (identifier,)).fetchone()
    return None if row is None else _staff_row(row)


def insert_staff(
    ctx: WriteContext,
    *,
    identifier: str,
    label: str | None,
    category: str | None,
    active_from: str,
    active_until: str | None,
) -> int:
    """Insert a staff member and return its id."""
    values: dict[str, object] = {
        "identifier": identifier,
        "label": label,
        "category": category,
        "active_from": active_from,
        "active_until": active_until,
    }
    return _new_id(insert(ctx, _STAFF, values))


def update_staff(
    ctx: WriteContext,
    staff_id: int,
    *,
    identifier: str,
    label: str | None,
    category: str | None,
    active_from: str,
    active_until: str | None,
) -> bool:
    """Set every editable column; returns whether anything changed (only then a log row)."""
    changes: dict[str, object] = {
        "identifier": identifier,
        "label": label,
        "category": category,
        "active_from": active_from,
        "active_until": active_until,
    }
    return update(ctx, _STAFF, staff_id, changes)


def set_staff_pseudonym(ctx: WriteContext, staff_id: int, identifier: str) -> bool:
    """Replace the identifier and clear the label (pseudonymisation); the log records only that
    these two columns changed.
    """
    changes: dict[str, object] = {"identifier": identifier, "label": None}
    return update(ctx, _STAFF, staff_id, changes)


def delete_staff(ctx: WriteContext, staff_id: int) -> int:
    """Delete a person; the certificates, training records and degrees go with it, each logged.

    Returns the number of rows deleted (the person and the dependent rows).
    """
    return delete(ctx, _STAFF, staff_id)


# --------------------------------------------------------------------------- certificates


def list_certificates(
    conn: DatabaseConnection, staff_id: int | None = None
) -> list[CertificateRow]:
    """The certificates of one person, or of everybody, ordered by person, level and issue date."""
    order = "ORDER BY staff_id, ppe_level, issued_on, id"
    if staff_id is None:
        sql = f"SELECT {_CERTIFICATE_COLUMNS} FROM ppe_certification {order}"
        rows = conn.execute(sql).fetchall()
    else:
        sql = f"SELECT {_CERTIFICATE_COLUMNS} FROM ppe_certification WHERE staff_id = ? {order}"
        rows = conn.execute(sql, (staff_id,)).fetchall()
    return [_certificate_row(row) for row in rows]


def get_certificate(conn: DatabaseConnection, cert_id: int) -> CertificateRow | None:
    sql = f"SELECT {_CERTIFICATE_COLUMNS} FROM ppe_certification WHERE id = ?"
    row = conn.execute(sql, (cert_id,)).fetchone()
    return None if row is None else _certificate_row(row)


def get_certificate_by_key(
    conn: DatabaseConnection, staff_id: int, ppe_level: str, issued_on: str
) -> CertificateRow | None:
    """The certificate with the natural key (staff, level, issued_on) (CSV import, T8.4)."""
    sql = (
        f"SELECT {_CERTIFICATE_COLUMNS} FROM ppe_certification"
        " WHERE staff_id = ? AND ppe_level = ? AND issued_on = ?"
    )
    row = conn.execute(sql, (staff_id, ppe_level, issued_on)).fetchone()
    return None if row is None else _certificate_row(row)


def insert_certificate(
    ctx: WriteContext,
    *,
    staff_id: int,
    ppe_level: str,
    issued_on: str,
    valid_until: str,
    reference: str | None,
    no_renewal_from: str | None = None,
    no_renewal_reason: str | None = None,
) -> int:
    """Insert a certificate and return its id."""
    values: dict[str, object] = {
        "staff_id": staff_id,
        "ppe_level": ppe_level,
        "issued_on": issued_on,
        "valid_until": valid_until,
        "no_renewal_from": no_renewal_from,
        "no_renewal_reason": no_renewal_reason,
        "reference": reference,
    }
    return _new_id(insert(ctx, _CERTIFICATE, values))


def update_certificate(
    ctx: WriteContext,
    cert_id: int,
    *,
    ppe_level: str,
    issued_on: str,
    valid_until: str,
    reference: str | None,
) -> bool:
    """Set the editable columns (the no-renewal mark is untouched); returns whether it changed."""
    changes: dict[str, object] = {
        "ppe_level": ppe_level,
        "issued_on": issued_on,
        "valid_until": valid_until,
        "reference": reference,
    }
    return update(ctx, _CERTIFICATE, cert_id, changes)


def set_certificate_no_renewal(
    ctx: WriteContext, cert_id: int, no_renewal_from: str | None, no_renewal_reason: str | None
) -> bool:
    """Set (or, with ``None`` values, clear) the D24 mark; returns whether anything changed."""
    changes: dict[str, object] = {
        "no_renewal_from": no_renewal_from,
        "no_renewal_reason": no_renewal_reason,
    }
    return update(ctx, _CERTIFICATE, cert_id, changes)


def clear_certificate_reference(ctx: WriteContext, cert_id: int) -> bool:
    """Set the free-text ``reference`` to NULL (pseudonymisation)."""
    changes: dict[str, object] = {"reference": None}
    return update(ctx, _CERTIFICATE, cert_id, changes)


def delete_certificate(ctx: WriteContext, cert_id: int) -> int:
    return delete(ctx, _CERTIFICATE, cert_id)


# --------------------------------------------------------------------------- courses


def list_courses(conn: DatabaseConnection, *, include_inactive: bool = True) -> list[CourseRow]:
    """Courses ordered by code; inactive ones are included unless excluded."""
    where = "" if include_inactive else " WHERE active = 1"
    sql = f"SELECT {_COURSE_COLUMNS} FROM training_course{where} ORDER BY code"
    return [_course_row(row) for row in conn.execute(sql).fetchall()]


def get_course(conn: DatabaseConnection, course_id: int) -> CourseRow | None:
    sql = f"SELECT {_COURSE_COLUMNS} FROM training_course WHERE id = ?"
    row = conn.execute(sql, (course_id,)).fetchone()
    return None if row is None else _course_row(row)


def get_course_by_code(conn: DatabaseConnection, code: str) -> CourseRow | None:
    sql = f"SELECT {_COURSE_COLUMNS} FROM training_course WHERE code = ?"
    row = conn.execute(sql, (code,)).fetchone()
    return None if row is None else _course_row(row)


def insert_course(
    ctx: WriteContext,
    *,
    code: str,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    active: bool,
) -> int:
    """Insert a course and return its id."""
    values: dict[str, object] = {
        "code": code,
        "label_pt_br": label_pt_br,
        "label_en_us": label_en_us,
        "label_es_es": label_es_es,
        "active": 1 if active else 0,
    }
    return _new_id(insert(ctx, _COURSE, values))


def update_course(
    ctx: WriteContext,
    course_id: int,
    *,
    code: str,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    active: bool,
) -> bool:
    """Set every editable column; returns whether anything changed."""
    changes: dict[str, object] = {
        "code": code,
        "label_pt_br": label_pt_br,
        "label_en_us": label_en_us,
        "label_es_es": label_es_es,
        "active": 1 if active else 0,
    }
    return update(ctx, _COURSE, course_id, changes)


def delete_course(ctx: WriteContext, course_id: int) -> int:
    """Delete a course; the database refuses (``ROW_IN_USE``) while training records use it."""
    return delete(ctx, _COURSE, course_id)


def course_in_use(conn: DatabaseConnection, course_id: int) -> bool:
    """Whether any training record uses the course."""
    sql = "SELECT 1 FROM training_record WHERE course_id = ? LIMIT 1"
    return conn.execute(sql, (course_id,)).fetchone() is not None


# --------------------------------------------------------------------------- training records


def list_training(conn: DatabaseConnection, staff_id: int | None = None) -> list[TrainingRow]:
    """The training records of one person, or of everybody, by person, date and id."""
    order = "ORDER BY staff_id, completed_on, id"
    if staff_id is None:
        sql = f"SELECT {_TRAINING_COLUMNS} FROM training_record {order}"
        rows = conn.execute(sql).fetchall()
    else:
        sql = f"SELECT {_TRAINING_COLUMNS} FROM training_record WHERE staff_id = ? {order}"
        rows = conn.execute(sql, (staff_id,)).fetchall()
    return [_training_row(row) for row in rows]


def get_training(conn: DatabaseConnection, training_id: int) -> TrainingRow | None:
    sql = f"SELECT {_TRAINING_COLUMNS} FROM training_record WHERE id = ?"
    row = conn.execute(sql, (training_id,)).fetchone()
    return None if row is None else _training_row(row)


def get_training_by_key(
    conn: DatabaseConnection, staff_id: int, course_id: int, completed_on: str
) -> TrainingRow | None:
    """The record with the natural key (staff, course, completed_on) (CSV import, T8.4)."""
    sql = (
        f"SELECT {_TRAINING_COLUMNS} FROM training_record"
        " WHERE staff_id = ? AND course_id = ? AND completed_on = ?"
    )
    row = conn.execute(sql, (staff_id, course_id, completed_on)).fetchone()
    return None if row is None else _training_row(row)


def insert_training(
    ctx: WriteContext, *, staff_id: int, course_id: int, completed_on: str, hours: float | None
) -> int:
    """Insert a training record and return its id."""
    values: dict[str, object] = {
        "staff_id": staff_id,
        "course_id": course_id,
        "completed_on": completed_on,
        "hours": hours,
    }
    return _new_id(insert(ctx, _TRAINING, values))


def update_training(
    ctx: WriteContext, training_id: int, *, course_id: int, completed_on: str, hours: float | None
) -> bool:
    """Set the editable columns; returns whether anything changed."""
    changes: dict[str, object] = {
        "course_id": course_id,
        "completed_on": completed_on,
        "hours": hours,
    }
    return update(ctx, _TRAINING, training_id, changes)


def delete_training(ctx: WriteContext, training_id: int) -> int:
    return delete(ctx, _TRAINING, training_id)


# --------------------------------------------------------------------------- degrees


def list_degrees(conn: DatabaseConnection, staff_id: int | None = None) -> list[DegreeRow]:
    """The degrees of one person, or of everybody, by person, level, year and id."""
    order = "ORDER BY staff_id, level, COALESCE(year, 0), id"
    if staff_id is None:
        sql = f"SELECT {_DEGREE_COLUMNS} FROM academic_degree {order}"
        rows = conn.execute(sql).fetchall()
    else:
        sql = f"SELECT {_DEGREE_COLUMNS} FROM academic_degree WHERE staff_id = ? {order}"
        rows = conn.execute(sql, (staff_id,)).fetchall()
    return [_degree_row(row) for row in rows]


def get_degree(conn: DatabaseConnection, degree_id: int) -> DegreeRow | None:
    sql = f"SELECT {_DEGREE_COLUMNS} FROM academic_degree WHERE id = ?"
    row = conn.execute(sql, (degree_id,)).fetchone()
    return None if row is None else _degree_row(row)


def find_degree(
    conn: DatabaseConnection, staff_id: int, level: str, field: str | None, year: int | None
) -> DegreeRow | None:
    """The degree with the natural key (staff, level, field, year); NULL equals NULL here, as in
    the unique index ``academic_degree_key`` (CSV import, T8.4).
    """
    sql = (
        f"SELECT {_DEGREE_COLUMNS} FROM academic_degree"
        " WHERE staff_id = ? AND level = ? AND COALESCE(field, '') = COALESCE(?, '')"
        " AND COALESCE(year, 0) = COALESCE(?, 0)"
    )
    row = conn.execute(sql, (staff_id, level, field, year)).fetchone()
    return None if row is None else _degree_row(row)


def insert_degree(
    ctx: WriteContext,
    *,
    staff_id: int,
    level: str,
    status: str,
    year: int | None,
    field: str | None,
) -> int:
    """Insert a degree and return its id."""
    values: dict[str, object] = {
        "staff_id": staff_id,
        "level": level,
        "status": status,
        "year": year,
        "field": field,
    }
    return _new_id(insert(ctx, _DEGREE, values))


def update_degree(
    ctx: WriteContext,
    degree_id: int,
    *,
    level: str,
    status: str,
    year: int | None,
    field: str | None,
) -> bool:
    """Set the editable columns; returns whether anything changed."""
    changes: dict[str, object] = {
        "level": level,
        "status": status,
        "year": year,
        "field": field,
    }
    return update(ctx, _DEGREE, degree_id, changes)


def set_degree_field(ctx: WriteContext, degree_id: int, field: str | None) -> bool:
    """Set only the free-text ``field`` (pseudonymisation)."""
    changes: dict[str, object] = {"field": field}
    return update(ctx, _DEGREE, degree_id, changes)


def delete_degree(ctx: WriteContext, degree_id: int) -> int:
    return delete(ctx, _DEGREE, degree_id)


# --------------------------------------------------------------------------- domain converters


def staff_to_domain(row: StaffRow) -> StaffMember:
    """The domain staff member (identifier, id and the active interval)."""
    return StaffMember(
        id=row.id,
        identifier=row.identifier,
        active_from=parse_iso_date(row.active_from),
        active_until=None if row.active_until is None else parse_iso_date(row.active_until),
    )


def certificate_to_domain(row: CertificateRow) -> Certificate:
    """The domain certificate."""
    no_renewal = None if row.no_renewal_from is None else parse_iso_date(row.no_renewal_from)
    return Certificate(
        id=row.id,
        staff_id=row.staff_id,
        level=PpeLevel(row.ppe_level),
        issued_on=parse_iso_date(row.issued_on),
        valid_until=parse_iso_date(row.valid_until),
        no_renewal_from=no_renewal,
    )


def training_to_domain(row: TrainingRow) -> TrainingRecord:
    """The domain training record."""
    return TrainingRecord(staff_id=row.staff_id, completed_on=parse_iso_date(row.completed_on))


def degree_to_domain(row: DegreeRow) -> Degree:
    """The domain degree."""
    return Degree(
        staff_id=row.staff_id,
        level=DegreeLevel(row.level),
        status=DegreeStatus(row.status),
    )
