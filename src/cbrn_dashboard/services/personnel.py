# SPDX-License-Identifier: GPL-3.0-or-later
"""Personnel service: staff, PPE certificates, courses, training records, degrees (PLAN.md T2.3).

Qt-free. All rules about *readiness* (activity interval, counting certificate, valid, expiring,
retraining, indicator values) live in ``domain/personnel.py`` and are only called from here; the
as-of summaries and lists load the rows, convert them (``storage/personnel_repo.py``) and call
those functions. The rules about *input* live here and are reported as
:class:`~cbrn_dashboard.services.errors.ServiceError` with a stable code and the name of the
offending field; the UI maps codes to texts. Every mutating method

* first refuses a read-only connection (``READ_ONLY``),
* validates and writes inside ONE transaction, so a refusal (or any later failure) leaves neither
  data rows nor ``change_log`` rows behind,
* writes only through ``storage/personnel_repo.py``, whose writes use the repository helpers (one
  ``change_log`` row per affected row, stamped with the injected clock and the current operator).

Personal data (D17): a person is identified by a LOCAL CODE (never a national ID), with an
optional short label; there are no notes fields. The free-text columns ``identifier``, ``label``,
``reference`` and ``field`` are never copied into ``change_log`` (the repository helper redacts
them). :meth:`PersonnelService.pseudonymise_staff` replaces them with random codes (or clears them)
and keeps the history.

A person has ONE active interval (A14). There is deliberately no "reactivate": someone who returns
is a new record. Clearing or moving ``active_until`` through :meth:`PersonnelService.update_staff`
is only a plain correction of the entry.
"""

from __future__ import annotations

import math
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain import personnel as rules
from cbrn_dashboard.domain.dates import InvalidDateError, format_iso_date, parse_iso_date
from cbrn_dashboard.domain.indicators import IndicatorValue, encode_dimension
from cbrn_dashboard.domain.personnel import (
    Certificate,
    CertStatus,
    DegreeLevel,
    DegreeStatus,
    PersonnelRules,
    PpeLevel,
    StaffLevelRow,
    StaffMember,
)
from cbrn_dashboard.services.errors import (
    CODE_IMMUTABLE,
    INVALID_CODE,
    INVALID_DATE,
    LABEL_PT_BR_REQUIRED,
    LIST_CODE_PATTERN,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
    ServiceError,
    require,
    translate_storage_error,
)
from cbrn_dashboard.storage import personnel_repo as repo
from cbrn_dashboard.storage import settings_repo
from cbrn_dashboard.storage.db import DatabaseConnection, ReadOnlyDatabaseError, transaction
from cbrn_dashboard.storage.personnel_repo import (
    CertificateRow,
    CourseRow,
    DegreeRow,
    StaffRow,
    TrainingRow,
)
from cbrn_dashboard.storage.repository import ForeignKeyError, RowNotFoundError, WriteContext

__all__ = [
    "ACTIVE_UNTIL_BEFORE_FROM",
    "COURSE_INACTIVE",
    "COURSE_IN_USE",
    "DUPLICATE_CERTIFICATE",
    "DUPLICATE_CODE",
    "DUPLICATE_DEGREE",
    "DUPLICATE_IDENTIFIER",
    "DUPLICATE_TRAINING",
    "IDENTIFIER_LOOKS_LIKE_NATIONAL_ID",
    "INVALID_DEGREE_LEVEL",
    "INVALID_DEGREE_STATUS",
    "INVALID_NO_RENEWAL_REASON",
    "INVALID_NUMBER",
    "INVALID_PPE_LEVEL",
    "INVALID_YEAR",
    "NEGATIVE_HOURS",
    "NO_RENEWAL_REASONS",
    "NO_RENEWAL_REASON_WITHOUT_DATE",
    "PSEUDONYM_COLLISION",
    "PSEUDONYM_PREFIX",
    "TEXT_TOO_LONG",
    "VALID_UNTIL_BEFORE_ISSUED",
    "CertificateInput",
    "CertificateView",
    "CourseInput",
    "CourseView",
    "DegreeInput",
    "DegreeView",
    "LevelSummary",
    "PersonnelAlertInputs",
    "PersonnelService",
    "StaffDetail",
    "StaffInput",
    "StaffView",
    "TrainingInput",
    "TrainingView",
    "course_label",
]

# Error codes of this service (the shared ones are in services/errors.py).
DUPLICATE_IDENTIFIER = "DUPLICATE_IDENTIFIER"
ACTIVE_UNTIL_BEFORE_FROM = "ACTIVE_UNTIL_BEFORE_FROM"
TEXT_TOO_LONG = "TEXT_TOO_LONG"
#: D17: the identifier is a local code, never a national ID (CPF-like value refused).
IDENTIFIER_LOOKS_LIKE_NATIONAL_ID = "IDENTIFIER_LOOKS_LIKE_NATIONAL_ID"
INVALID_PPE_LEVEL = "INVALID_PPE_LEVEL"
VALID_UNTIL_BEFORE_ISSUED = "VALID_UNTIL_BEFORE_ISSUED"
DUPLICATE_CERTIFICATE = "DUPLICATE_CERTIFICATE"
INVALID_NO_RENEWAL_REASON = "INVALID_NO_RENEWAL_REASON"
NO_RENEWAL_REASON_WITHOUT_DATE = "NO_RENEWAL_REASON_WITHOUT_DATE"
#: Same value as the code of ``services/exercises.py``; defined here to keep the services apart.
DUPLICATE_CODE = "DUPLICATE_CODE"
COURSE_IN_USE = "COURSE_IN_USE"
COURSE_INACTIVE = "COURSE_INACTIVE"
DUPLICATE_TRAINING = "DUPLICATE_TRAINING"
NEGATIVE_HOURS = "NEGATIVE_HOURS"
#: A number is NaN or infinite (same value as in ``services/exercises.py``).
INVALID_NUMBER = "INVALID_NUMBER"
INVALID_DEGREE_LEVEL = "INVALID_DEGREE_LEVEL"
INVALID_DEGREE_STATUS = "INVALID_DEGREE_STATUS"
INVALID_YEAR = "INVALID_YEAR"
DUPLICATE_DEGREE = "DUPLICATE_DEGREE"
#: No unused pseudonym could be drawn from ``id_factory`` (it keeps returning taken values).
PSEUDONYM_COLLISION = "PSEUDONYM_COLLISION"

#: The accepted values of ``ppe_certification.no_renewal_reason`` (D24).
NO_RENEWAL_REASONS: tuple[str, ...] = ("left_unit", "role_change", "other")
#: Prefix of the random codes that replace identifiers and degree fields (D17).
PSEUDONYM_PREFIX = "PSEUDO-"

_MAX_IDENTIFIER = 64
_MAX_LABEL = 120
_MAX_CATEGORY = 64
_MAX_FREE_TEXT = 200  # certificate reference, degree field
_MIN_YEAR = 1900
_MAX_YEAR = 2200
_PSEUDONYM_ATTEMPTS = 50

# A Brazilian CPF: 11 digits, optionally written 000.000.000-00.
_CPF_LIKE = re.compile(r"[0-9]{3}\.?[0-9]{3}\.?[0-9]{3}-?[0-9]{2}")


# --------------------------------------------------------------------------- input and output


@dataclass(frozen=True)
class StaffInput:
    """The editable fields of a person. Dates are strict ISO text (or ``date``)."""

    identifier: str
    active_from: str | date
    active_until: str | date | None = None
    label: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class CertificateInput:
    """The editable fields of a certificate; the no-renewal mark has its own methods."""

    level: str
    issued_on: str | date
    valid_until: str | date
    reference: str | None = None


@dataclass(frozen=True)
class CourseInput:
    """The editable fields of a course; only ``label_pt_br`` is required among the labels."""

    code: str
    label_pt_br: str | None
    label_en_us: str | None = None
    label_es_es: str | None = None
    active: bool = True


@dataclass(frozen=True)
class TrainingInput:
    """A completed course."""

    course_id: int
    completed_on: str | date
    hours: float | None = None


@dataclass(frozen=True)
class DegreeInput:
    """An academic degree; ``field`` is free text (no names, health or contact data)."""

    level: str
    status: str = "completed"
    year: int | None = None
    field: str | None = None


@dataclass(frozen=True)
class StaffView:
    """A stored person."""

    id: int
    identifier: str
    label: str | None
    category: str | None
    active_from: date
    active_until: date | None


@dataclass(frozen=True)
class CertificateView:
    """A stored certificate."""

    id: int
    staff_id: int
    level: PpeLevel
    issued_on: date
    valid_until: date
    no_renewal_from: date | None
    no_renewal_reason: str | None
    reference: str | None


@dataclass(frozen=True)
class CourseView:
    """A stored course."""

    id: int
    code: str
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    active: bool


@dataclass(frozen=True)
class TrainingView:
    """A stored training record together with the code of its course."""

    id: int
    staff_id: int
    course_id: int
    course_code: str
    completed_on: date
    hours: float | None


@dataclass(frozen=True)
class DegreeView:
    """A stored degree."""

    id: int
    staff_id: int
    level: DegreeLevel
    status: DegreeStatus
    year: int | None
    field: str | None


@dataclass(frozen=True)
class StaffDetail:
    """A person with all dependent records, for the detail view."""

    staff: StaffView
    certificates: tuple[CertificateView, ...]
    training: tuple[TrainingView, ...]
    degrees: tuple[DegreeView, ...]


@dataclass(frozen=True)
class LevelSummary:
    """Counts of active staff at one PPE level, taken from the domain indicator values."""

    level: PpeLevel
    valid: int
    expiring: int
    retraining_needed: int


@dataclass(frozen=True)
class PersonnelAlertInputs:
    """Domain objects and rules the certificate alerts are computed from (T6.2)."""

    staff: tuple[StaffMember, ...]
    certificates: tuple[Certificate, ...]
    rules: PersonnelRules


def course_label(course: CourseView, lang: str) -> str:
    """The label of ``course`` in ``lang`` (``pt_BR``/``en_US``/``es_ES``; ``-`` also accepted).

    Fallback (section 6): the language asked for, then pt-BR, then en-US, then the code.
    A blank label counts as missing.
    """
    labels = {
        "pt_BR": course.label_pt_br,
        "en_US": course.label_en_us,
        "es_ES": course.label_es_es,
    }
    for candidate in (lang.replace("-", "_"), "pt_BR", "en_US"):
        text = labels.get(candidate)
        if text is not None and text.strip():
            return text
    return course.code


# --------------------------------------------------------------------------- validation helpers


@dataclass(frozen=True)
class _StaffFields:
    identifier: str
    label: str | None
    category: str | None
    active_from: date
    active_until: date | None


@dataclass(frozen=True)
class _CertificateFields:
    level: PpeLevel
    issued_on: date
    valid_until: date
    reference: str | None


@dataclass(frozen=True)
class _CourseFields:
    code: str
    label_pt_br: str
    label_en_us: str | None
    label_es_es: str | None
    active: bool


@dataclass(frozen=True)
class _TrainingFields:
    course_id: int
    completed_on: date
    hours: float | None


@dataclass(frozen=True)
class _DegreeFields:
    level: DegreeLevel
    status: DegreeStatus
    year: int | None
    field: str | None


def _clean(text: str | None) -> str | None:
    """Strip a free-text field; blank becomes ``None``."""
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def _limited(text: str | None, limit: int, field: str) -> str | None:
    cleaned = _clean(text)
    require(cleaned is None or len(cleaned) <= limit, TEXT_TOO_LONG, field)
    return cleaned


def _check_code(code: str) -> str:
    require(bool(code.strip()), REQUIRED, "code")
    require(LIST_CODE_PATTERN.fullmatch(code) is not None, INVALID_CODE, "code")
    return code


def _parse_date(value: str | date, field: str) -> date:
    if isinstance(value, datetime):
        raise ServiceError(INVALID_DATE, field)
    if isinstance(value, date):
        return value
    require(bool(value.strip()), REQUIRED, field)
    try:
        return parse_iso_date(value)
    except InvalidDateError:
        raise ServiceError(INVALID_DATE, field) from None


def _parse_optional_date(value: str | date | None, field: str) -> date | None:
    """``None`` and blank text mean "no date"; anything else must be a strict ISO date."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _parse_date(value, field)


def _finite(value: float | None, field: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    require(math.isfinite(number), INVALID_NUMBER, field)
    return number


def _parse_ppe_level(value: str | None) -> PpeLevel:
    text = "" if value is None else str(value)
    require(bool(text.strip()), REQUIRED, "level")
    try:
        return PpeLevel(text)
    except ValueError:
        raise ServiceError(INVALID_PPE_LEVEL, "level") from None


def _parse_degree_level(value: str | None) -> DegreeLevel:
    text = "" if value is None else str(value)
    require(bool(text.strip()), REQUIRED, "level")
    try:
        return DegreeLevel(text)
    except ValueError:
        raise ServiceError(INVALID_DEGREE_LEVEL, "level") from None


def _parse_degree_status(value: str | None) -> DegreeStatus:
    text = "" if value is None else str(value)
    require(bool(text.strip()), REQUIRED, "status")
    try:
        return DegreeStatus(text)
    except ValueError:
        raise ServiceError(INVALID_DEGREE_STATUS, "status") from None


def _check_year(year: int | None) -> int | None:
    if year is None:
        return None
    require(
        isinstance(year, int) and not isinstance(year, bool) and _MIN_YEAR <= year <= _MAX_YEAR,
        INVALID_YEAR,
        "year",
    )
    return year


def _check_identifier(raw: str | None) -> str:
    """Trim and check a local identifier.

    D17: the identifier is a local code, never a national ID. The CPF guard only recognises the
    11-digit shape (with or without ``.``/``-``); it is a cheap safety net and cannot catch every
    case (other documents, a CPF with other separators or embedded in text).
    """
    identifier = "" if raw is None else raw.strip()
    require(bool(identifier), REQUIRED, "identifier")
    require(len(identifier) <= _MAX_IDENTIFIER, TEXT_TOO_LONG, "identifier")
    require(
        _CPF_LIKE.fullmatch(identifier) is None, IDENTIFIER_LOOKS_LIKE_NATIONAL_ID, "identifier"
    )
    return identifier


def _default_id_factory() -> str:
    return secrets.token_hex(6).upper()


@contextmanager
def _translated() -> Iterator[None]:
    """Turn the storage errors with a service meaning into service errors; re-raise the rest."""
    try:
        yield
    except (ReadOnlyDatabaseError, RowNotFoundError) as exc:
        raise translate_storage_error(exc) from exc


def _staff_view(row: StaffRow) -> StaffView:
    return StaffView(
        id=row.id,
        identifier=row.identifier,
        label=row.label,
        category=row.category,
        active_from=parse_iso_date(row.active_from),
        active_until=None if row.active_until is None else parse_iso_date(row.active_until),
    )


def _certificate_view(row: CertificateRow) -> CertificateView:
    no_renewal = None if row.no_renewal_from is None else parse_iso_date(row.no_renewal_from)
    return CertificateView(
        id=row.id,
        staff_id=row.staff_id,
        level=PpeLevel(row.ppe_level),
        issued_on=parse_iso_date(row.issued_on),
        valid_until=parse_iso_date(row.valid_until),
        no_renewal_from=no_renewal,
        no_renewal_reason=row.no_renewal_reason,
        reference=row.reference,
    )


def _course_view(row: CourseRow) -> CourseView:
    return CourseView(
        id=row.id,
        code=row.code,
        label_pt_br=row.label_pt_br,
        label_en_us=row.label_en_us,
        label_es_es=row.label_es_es,
        active=row.active,
    )


def _training_view(row: TrainingRow, course_codes: dict[int, str]) -> TrainingView:
    return TrainingView(
        id=row.id,
        staff_id=row.staff_id,
        course_id=row.course_id,
        course_code=course_codes.get(row.course_id, ""),
        completed_on=parse_iso_date(row.completed_on),
        hours=row.hours,
    )


def _degree_view(row: DegreeRow) -> DegreeView:
    return DegreeView(
        id=row.id,
        staff_id=row.staff_id,
        level=DegreeLevel(row.level),
        status=DegreeStatus(row.status),
        year=row.year,
        field=row.field,
    )


# --------------------------------------------------------------------------- the service


class PersonnelService:
    """Create, change, delete, pseudonymise and read personnel records and their summaries."""

    def __init__(
        self,
        conn: DatabaseConnection,
        clock: Clock,
        operator: Callable[[], str] = lambda: "",
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._operator = operator
        self._id_factory: Callable[[], str] = (
            _default_id_factory if id_factory is None else id_factory
        )

    # ----- plumbing

    def _ctx(self) -> WriteContext:
        return WriteContext(self._conn, self._clock, self._operator())

    def _require_writable(self) -> None:
        require(not self._conn.read_only, READ_ONLY)

    def _staff_row(self, staff_id: int) -> StaffRow:
        row = repo.get_staff(self._conn, staff_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "staff_id")
        return row

    def _certificate_row(self, cert_id: int) -> CertificateRow:
        row = repo.get_certificate(self._conn, cert_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "cert_id")
        return row

    def _course_row(self, course_id: int) -> CourseRow:
        row = repo.get_course(self._conn, course_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "course_id")
        return row

    def _training_row(self, training_id: int) -> TrainingRow:
        row = repo.get_training(self._conn, training_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "training_id")
        return row

    def _degree_row(self, degree_id: int) -> DegreeRow:
        row = repo.get_degree(self._conn, degree_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "degree_id")
        return row

    def _rules(self) -> PersonnelRules:
        """The rules object, built from the stored configuration on each call."""
        config = settings_repo.load_config(self._conn)
        return PersonnelRules(
            cert_warning_days=config.cert_warning_days,
            hierarchy_enabled=config.ppe_hierarchy_enabled,
            hierarchy=config.ppe_hierarchy,
            validity_months=config.ppe_validity_months,
        )

    # ----- staff: validation

    def _validate_staff(self, data: StaffInput, staff_id: int | None) -> _StaffFields:
        identifier = _check_identifier(data.identifier)
        active_from = _parse_date(data.active_from, "active_from")
        active_until = _parse_optional_date(data.active_until, "active_until")
        require(
            active_until is None or active_until >= active_from,
            ACTIVE_UNTIL_BEFORE_FROM,
            "active_until",
        )
        label = _limited(data.label, _MAX_LABEL, "label")
        category = _limited(data.category, _MAX_CATEGORY, "category")
        existing = repo.get_staff_by_identifier(self._conn, identifier)
        require(existing is None or existing.id == staff_id, DUPLICATE_IDENTIFIER, "identifier")
        return _StaffFields(
            identifier=identifier,
            label=label,
            category=category,
            active_from=active_from,
            active_until=active_until,
        )

    # ----- staff: writes

    def create_staff(self, data: StaffInput) -> int:
        """Create a person; returns the new id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_staff(data, None)
            return repo.insert_staff(
                self._ctx(),
                identifier=fields.identifier,
                label=fields.label,
                category=fields.category,
                active_from=format_iso_date(fields.active_from),
                active_until=(
                    None if fields.active_until is None else format_iso_date(fields.active_until)
                ),
            )

    def update_staff(self, staff_id: int, data: StaffInput) -> None:
        """Change a person (a plain correction of the entry; only differences are logged)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._staff_row(staff_id)
            fields = self._validate_staff(data, staff_id)
            repo.update_staff(
                self._ctx(),
                staff_id,
                identifier=fields.identifier,
                label=fields.label,
                category=fields.category,
                active_from=format_iso_date(fields.active_from),
                active_until=(
                    None if fields.active_until is None else format_iso_date(fields.active_until)
                ),
            )

    def deactivate_staff(self, staff_id: int, active_until: str | date) -> None:
        """End the active interval of a person; the history stays (distinct from delete).

        The person still counts on ``active_until`` itself and no longer the day after (A14).
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._staff_row(staff_id)
            until = _parse_date(active_until, "active_until")
            require(
                until >= parse_iso_date(row.active_from), ACTIVE_UNTIL_BEFORE_FROM, "active_until"
            )
            repo.update_staff(
                self._ctx(),
                staff_id,
                identifier=row.identifier,
                label=row.label,
                category=row.category,
                active_from=row.active_from,
                active_until=format_iso_date(until),
            )

    def delete_staff(self, staff_id: int) -> None:
        """Delete a person entered by mistake, with the certificates, training records and
        degrees (each deletion logged). To keep the history use :meth:`deactivate_staff`.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._staff_row(staff_id)
            repo.delete_staff(self._ctx(), staff_id)

    # ----- pseudonymisation

    def _draw_pseudonym(self, is_taken: Callable[[str], bool]) -> str:
        for _ in range(_PSEUDONYM_ATTEMPTS):
            code = f"{PSEUDONYM_PREFIX}{self._id_factory()}"
            if not is_taken(code):
                return code
        raise ServiceError(PSEUDONYM_COLLISION)

    def pseudonymise_staff(self, staff_id: int) -> str:
        """Pseudonymise a person (D17). IRREVERSIBLE; returns the new identifier.

        In one transaction: the identifier becomes a random ``PSEUDO-<code>``, the label and every
        certificate ``reference`` are cleared, and each degree ``field`` that is set is replaced by
        its own random code (per row, so the unique index of the degrees still holds). Certificates,
        training records, degrees, category and dates are kept. The change log records only THAT
        these columns changed. A person can be pseudonymised again (new codes).
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._staff_row(staff_id)
            ctx = self._ctx()
            identifier = self._draw_pseudonym(
                lambda code: repo.get_staff_by_identifier(self._conn, code) is not None
            )
            repo.set_staff_pseudonym(ctx, staff_id, identifier)
            for certificate in repo.list_certificates(self._conn, staff_id):
                repo.clear_certificate_reference(ctx, certificate.id)
            degrees = repo.list_degrees(self._conn, staff_id)
            used = {degree.field for degree in degrees if degree.field is not None}
            for degree in degrees:
                if degree.field is None:
                    continue
                code = self._draw_pseudonym(used.__contains__)
                used.add(code)
                repo.set_degree_field(ctx, degree.id, code)
            return identifier

    # ----- staff: reads

    def get_staff(self, staff_id: int) -> StaffView:
        """One person; ``NOT_FOUND`` when there is none."""
        return _staff_view(self._staff_row(staff_id))

    def list_staff(
        self,
        as_of: date | None = None,
        *,
        active_only: bool = False,
        level: PpeLevel | str | None = None,
        needs_retraining: bool = False,
    ) -> list[StaffView]:
        """The people ordered by identifier; with filters (they need ``as_of``) a subset.

        ``active_only``: active on ``as_of`` (domain rule). ``level``: active, with a counting
        certificate at that level on ``as_of``. ``needs_retraining``: active and in the domain
        retraining list (at ``level`` when given).
        """
        wanted_level = None if level is None else _parse_ppe_level(str(level))
        views = [_staff_view(row) for row in repo.list_staff(self._conn)]
        if not (active_only or wanted_level is not None or needs_retraining):
            return views
        if as_of is None:
            raise ServiceError(REQUIRED, "as_of")
        staff, certs = self._domain_staff(), self._domain_certificates()
        selected = {person.id for person in staff if rules.is_active(person, as_of)}
        if wanted_level is not None or needs_retraining:
            rows = (
                rules.retraining_list(staff, certs, as_of, self._rules())
                if needs_retraining
                else [
                    row
                    for row in rules.staff_level_rows(staff, certs, as_of, self._rules())
                    if row.status is not CertStatus.NONE
                ]
            )
            selected &= {
                row.staff_id for row in rows if wanted_level is None or row.level is wanted_level
            }
        return [view for view in views if view.id in selected]

    def staff_detail(self, staff_id: int) -> StaffDetail:
        """A person with certificates, training records and degrees (for the detail view)."""
        staff = _staff_view(self._staff_row(staff_id))
        course_codes = {course.id: course.code for course in repo.list_courses(self._conn)}
        training_rows = repo.list_training(self._conn, staff_id)
        return StaffDetail(
            staff=staff,
            certificates=tuple(
                _certificate_view(row) for row in repo.list_certificates(self._conn, staff_id)
            ),
            training=tuple(_training_view(row, course_codes) for row in training_rows),
            degrees=tuple(_degree_view(row) for row in repo.list_degrees(self._conn, staff_id)),
        )

    # ----- certificates

    def _validate_certificate(
        self, staff_id: int, data: CertificateInput, cert_id: int | None
    ) -> _CertificateFields:
        level = _parse_ppe_level(data.level)
        issued_on = _parse_date(data.issued_on, "issued_on")
        valid_until = _parse_date(data.valid_until, "valid_until")
        require(valid_until >= issued_on, VALID_UNTIL_BEFORE_ISSUED, "valid_until")
        reference = _limited(data.reference, _MAX_FREE_TEXT, "reference")
        existing = repo.get_certificate_by_key(
            self._conn, staff_id, level.value, format_iso_date(issued_on)
        )
        require(existing is None or existing.id == cert_id, DUPLICATE_CERTIFICATE, "issued_on")
        return _CertificateFields(
            level=level, issued_on=issued_on, valid_until=valid_until, reference=reference
        )

    def add_certificate(self, staff_id: int, data: CertificateInput) -> int:
        """Add a certificate to a person; returns its id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._staff_row(staff_id)
            fields = self._validate_certificate(staff_id, data, None)
            return repo.insert_certificate(
                self._ctx(),
                staff_id=staff_id,
                ppe_level=fields.level.value,
                issued_on=format_iso_date(fields.issued_on),
                valid_until=format_iso_date(fields.valid_until),
                reference=fields.reference,
            )

    def update_certificate(self, cert_id: int, data: CertificateInput) -> None:
        """Change a certificate; its no-renewal mark is left as it is."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._certificate_row(cert_id)
            fields = self._validate_certificate(current.staff_id, data, cert_id)
            repo.update_certificate(
                self._ctx(),
                cert_id,
                ppe_level=fields.level.value,
                issued_on=format_iso_date(fields.issued_on),
                valid_until=format_iso_date(fields.valid_until),
                reference=fields.reference,
            )

    def delete_certificate(self, cert_id: int) -> None:
        """Delete one certificate; ``NOT_FOUND`` when there is none."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._certificate_row(cert_id)
            repo.delete_certificate(self._ctx(), cert_id)

    def set_no_renewal(
        self, cert_id: int, from_date: str | date | None, reason: str | None = None
    ) -> None:
        """Mark a certificate "no renewal" from ``from_date`` on (D24), with an optional reason
        code (``left_unit``, ``role_change``, ``other``). A reason needs a date.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._certificate_row(cert_id)
            reason_code = _clean(reason)
            require(
                reason_code is None or reason_code in NO_RENEWAL_REASONS,
                INVALID_NO_RENEWAL_REASON,
                "no_renewal_reason",
            )
            start = _parse_optional_date(from_date, "no_renewal_from")
            if start is None:
                if reason_code is not None:
                    raise ServiceError(NO_RENEWAL_REASON_WITHOUT_DATE, "no_renewal_reason")
                raise ServiceError(REQUIRED, "no_renewal_from")
            repo.set_certificate_no_renewal(
                self._ctx(), cert_id, format_iso_date(start), reason_code
            )

    def clear_no_renewal(self, cert_id: int) -> None:
        """Remove the "no renewal" mark (date and reason) from a certificate."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._certificate_row(cert_id)
            repo.set_certificate_no_renewal(self._ctx(), cert_id, None, None)

    def propose_valid_until(self, level: str, issued_on: str | date) -> date | None:
        """The pre-filled ``valid_until`` (A04): ``issued_on`` plus the configured months for the
        level, or ``None`` when no validity is configured.
        """
        ppe_level = _parse_ppe_level(level)
        issued = _parse_date(issued_on, "issued_on")
        return rules.proposed_valid_until(issued, ppe_level, self._rules())

    def list_certificates(self, staff_id: int) -> list[CertificateView]:
        """The certificates of a person by level and issue date."""
        self._staff_row(staff_id)
        return [_certificate_view(row) for row in repo.list_certificates(self._conn, staff_id)]

    def get_certificate(self, cert_id: int) -> CertificateView:
        """One certificate; ``NOT_FOUND`` when there is none."""
        return _certificate_view(self._certificate_row(cert_id))

    # ----- courses

    def _validate_course(self, data: CourseInput, course_id: int | None) -> _CourseFields:
        code = _check_code(data.code)
        label_pt_br = _clean(data.label_pt_br)
        if label_pt_br is None:
            raise ServiceError(LABEL_PT_BR_REQUIRED, "label_pt_br")
        if course_id is not None:
            current = self._course_row(course_id)
            if code != current.code:
                require(not repo.course_in_use(self._conn, course_id), CODE_IMMUTABLE, "code")
        existing = repo.get_course_by_code(self._conn, code)
        require(existing is None or existing.id == course_id, DUPLICATE_CODE, "code")
        return _CourseFields(
            code=code,
            label_pt_br=label_pt_br,
            label_en_us=_clean(data.label_en_us),
            label_es_es=_clean(data.label_es_es),
            active=data.active,
        )

    def create_course(self, data: CourseInput) -> int:
        """Create a course; returns its id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_course(data, None)
            return repo.insert_course(
                self._ctx(),
                code=fields.code,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                active=fields.active,
            )

    def update_course(self, course_id: int, data: CourseInput) -> None:
        """Change a course; its code is frozen once a training record uses it."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._course_row(course_id)
            fields = self._validate_course(data, course_id)
            repo.update_course(
                self._ctx(),
                course_id,
                code=fields.code,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                active=fields.active,
            )

    def deactivate_course(self, course_id: int) -> None:
        """Mark a course inactive: it keeps its records but cannot receive new ones."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._course_row(course_id)
            repo.update_course(
                self._ctx(),
                course_id,
                code=row.code,
                label_pt_br=row.label_pt_br,
                label_en_us=row.label_en_us,
                label_es_es=row.label_es_es,
                active=False,
            )

    def delete_course(self, course_id: int) -> None:
        """Delete a course that no training record uses (``COURSE_IN_USE`` otherwise)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._course_row(course_id)
            require(not repo.course_in_use(self._conn, course_id), COURSE_IN_USE, "course_id")
            try:
                repo.delete_course(self._ctx(), course_id)
            except ForeignKeyError:
                raise ServiceError(COURSE_IN_USE, "course_id") from None

    def list_courses(self, include_inactive: bool = False) -> list[CourseView]:
        """The courses ordered by code; inactive ones only when asked for."""
        rows = repo.list_courses(self._conn, include_inactive=include_inactive)
        return [_course_view(row) for row in rows]

    # ----- training records

    def _validate_training(
        self, staff_id: int, data: TrainingInput, training_id: int | None
    ) -> _TrainingFields:
        course = self._course_row(data.course_id)
        if training_id is None:
            require(course.active, COURSE_INACTIVE, "course_id")
        else:
            current = self._training_row(training_id)
            require(course.active or course.id == current.course_id, COURSE_INACTIVE, "course_id")
        completed_on = _parse_date(data.completed_on, "completed_on")
        hours = _finite(data.hours, "hours")
        require(hours is None or hours >= 0, NEGATIVE_HOURS, "hours")
        existing = repo.get_training_by_key(
            self._conn, staff_id, course.id, format_iso_date(completed_on)
        )
        require(existing is None or existing.id == training_id, DUPLICATE_TRAINING, "completed_on")
        return _TrainingFields(course_id=course.id, completed_on=completed_on, hours=hours)

    def add_training(self, staff_id: int, data: TrainingInput) -> int:
        """Record a completed course of a person; returns the record id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._staff_row(staff_id)
            fields = self._validate_training(staff_id, data, None)
            return repo.insert_training(
                self._ctx(),
                staff_id=staff_id,
                course_id=fields.course_id,
                completed_on=format_iso_date(fields.completed_on),
                hours=fields.hours,
            )

    def update_training(self, training_id: int, data: TrainingInput) -> None:
        """Change a training record (not its person)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._training_row(training_id)
            fields = self._validate_training(current.staff_id, data, training_id)
            repo.update_training(
                self._ctx(),
                training_id,
                course_id=fields.course_id,
                completed_on=format_iso_date(fields.completed_on),
                hours=fields.hours,
            )

    def delete_training(self, training_id: int) -> None:
        """Delete one training record; ``NOT_FOUND`` when there is none."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._training_row(training_id)
            repo.delete_training(self._ctx(), training_id)

    def list_training(self, staff_id: int) -> list[TrainingView]:
        """The training records of a person by date."""
        self._staff_row(staff_id)
        course_codes = {course.id: course.code for course in repo.list_courses(self._conn)}
        return [
            _training_view(row, course_codes) for row in repo.list_training(self._conn, staff_id)
        ]

    # ----- degrees

    def _validate_degree(
        self, staff_id: int, data: DegreeInput, degree_id: int | None
    ) -> _DegreeFields:
        level = _parse_degree_level(data.level)
        status = _parse_degree_status(data.status)
        year = _check_year(data.year)
        field = _limited(data.field, _MAX_FREE_TEXT, "field")
        existing = repo.find_degree(self._conn, staff_id, level.value, field, year)
        require(existing is None or existing.id == degree_id, DUPLICATE_DEGREE, "level")
        return _DegreeFields(level=level, status=status, year=year, field=field)

    def add_degree(self, staff_id: int, data: DegreeInput) -> int:
        """Add a degree to a person; returns its id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._staff_row(staff_id)
            fields = self._validate_degree(staff_id, data, None)
            return repo.insert_degree(
                self._ctx(),
                staff_id=staff_id,
                level=fields.level.value,
                status=fields.status.value,
                year=fields.year,
                field=fields.field,
            )

    def update_degree(self, degree_id: int, data: DegreeInput) -> None:
        """Change a degree (not its person)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = self._degree_row(degree_id)
            fields = self._validate_degree(current.staff_id, data, degree_id)
            repo.update_degree(
                self._ctx(),
                degree_id,
                level=fields.level.value,
                status=fields.status.value,
                year=fields.year,
                field=fields.field,
            )

    def delete_degree(self, degree_id: int) -> None:
        """Delete one degree; ``NOT_FOUND`` when there is none."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._degree_row(degree_id)
            repo.delete_degree(self._ctx(), degree_id)

    def list_degrees(self, staff_id: int) -> list[DegreeView]:
        """The degrees of a person by level and year."""
        self._staff_row(staff_id)
        return [_degree_view(row) for row in repo.list_degrees(self._conn, staff_id)]

    # ----- as-of views (built with the domain functions)

    def _domain_staff(self) -> list[rules.StaffMember]:
        return [repo.staff_to_domain(row) for row in repo.list_staff(self._conn)]

    def _domain_certificates(self) -> list[rules.Certificate]:
        return [repo.certificate_to_domain(row) for row in repo.list_certificates(self._conn)]

    def alert_inputs(self) -> PersonnelAlertInputs:
        """The domain inputs of the certificate alerts (T6.2), with the configured rules.

        Built with the same loaders, converters and rules as the as-of views above.
        """
        return PersonnelAlertInputs(
            staff=tuple(self._domain_staff()),
            certificates=tuple(self._domain_certificates()),
            rules=self._rules(),
        )

    def level_rows(self, as_of: date) -> list[StaffLevelRow]:
        """One row per active person and level with the status on ``as_of`` (domain rule)."""
        return rules.staff_level_rows(
            self._domain_staff(), self._domain_certificates(), as_of, self._rules()
        )

    def retraining_list(self, as_of: date) -> list[StaffLevelRow]:
        """Active staff needing retraining on ``as_of`` (domain rule)."""
        return rules.retraining_list(
            self._domain_staff(), self._domain_certificates(), as_of, self._rules()
        )

    def expiring_list(self, as_of: date) -> list[StaffLevelRow]:
        """Active staff whose counting certificate is expiring on ``as_of`` (domain rule)."""
        return rules.expiring_list(
            self._domain_staff(), self._domain_certificates(), as_of, self._rules()
        )

    def indicator_values(self, as_of: date) -> list[IndicatorValue]:
        """The personnel indicator values as of ``as_of`` (input of ``services/indicators.py``)."""
        return rules.indicator_values(
            self._domain_staff(),
            self._domain_certificates(),
            [repo.training_to_domain(row) for row in repo.list_training(self._conn)],
            [repo.degree_to_domain(row) for row in repo.list_degrees(self._conn)],
            as_of,
            self._rules(),
        )

    def summary(self, as_of: date) -> list[LevelSummary]:
        """Counts per level (valid / expiring / retraining needed), from the indicator values."""
        values = {(item.code, item.dimension): item.value for item in self.indicator_values(as_of)}

        def count(code: str, level: PpeLevel) -> int:
            value = values.get((code, encode_dimension({"level": level.value})))
            return 0 if value is None else round(value)

        return [
            LevelSummary(
                level=level,
                valid=count("PERS_CERT_VALID", level),
                expiring=count("PERS_CERT_EXPIRING", level),
                retraining_needed=count("PERS_RETRAINING_NEEDED", level),
            )
            for level in PpeLevel
        ]
