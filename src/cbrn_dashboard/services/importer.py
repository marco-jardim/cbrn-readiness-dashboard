# SPDX-License-Identifier: GPL-3.0-or-later
"""CSV import of the module data, one file per entity (PLAN.md T8.4, D04, R29).

Qt-free. The files are the ones the export writes (``storage/csv_io.py`` reads them, leniently,
and reports every format problem with line, column and code). This module does the rest, per row:

* parents are found by natural key (staff identifier, course code, asset tag, type code, edition
  code, metric code, source code, budget-entry key); an unknown parent is ``UNKNOWN_REFERENCE`` on
  the referencing column;
* duplicates by natural key are refused, never merged: ``DUPLICATE_IN_FILE`` (reported on the later
  line) and ``DUPLICATE_KEY`` (the row exists in the database, whatever the service calls it);
* the row is written THROUGH THE MODULE SERVICE (:data:`_IMPORTERS`, the inverse of the loaders of
  ``services/export.py``), so every row gets exactly the validation the UI applies; the code of the
  service's own :class:`~cbrn_dashboard.services.errors.ServiceError` is reported on the offending
  row and column.

All-or-nothing: one outer transaction; every row runs in its own nested transaction (a SAVEPOINT)
whose ``ServiceError`` is caught and recorded, so ALL errors of a file are reported. If any error
was recorded, or if this is a dry run, an internal sentinel rolls the whole outer transaction
back. A dry run therefore executes exactly the real path and leaves the database unchanged.
Both need a write transaction, so both are refused on a read-only connection (``READ_ONLY``).

``change_log``: the services log every row they create as ``insert``. The importer adds ONE more
row per imported row with the action ``import`` (``repository.log_event``: the table, the id or
the natural key, and NO payload, so nothing personal can reach the log). This is the strategy for
every entity; no entity writes a row without it.

Entities that do not use the service's create method as it is:

* ``asset``: ``InfrastructureService.create_asset`` insists on an initial status and writes a
  status event dated ``in_service_from``, but the export holds the status events as their own file
  (``asset_status_event``, the initial event included). So the asset is validated by calling
  ``create_asset`` inside a SAVEPOINT that is always rolled back (the stored values are read back
  before the rollback), and the row is then written with ``infrastructure_repo.insert_asset``
  with those very values and NO status event. Importing ``asset_status_event`` adds the events.
* ``exercise_country``: countries belong to an edition; the row is added by
  ``ExercisesService.update_edition`` with the countries the edition has plus the new one.
* ``ppe_certification``: ``add_certificate`` followed by ``set_no_renewal`` when the row carries a
  no-renewal date or reason.

Rows of the built-in lists (``built_in = 1``) are never created: a built-in code that exists is a
duplicate (``DUPLICATE_KEY``), any other row with ``built_in = 1`` is ``BUILT_IN_NOT_ALLOWED``.
A row that refers to an inactive course, type, metric or source is refused as in the UI.

The service writes events by code only (``IMPORT.DONE`` with the count, ``IMPORT.FAILED``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from cbrn_dashboard import logging_setup
from cbrn_dashboard.clock import Clock
from cbrn_dashboard.services.budget import BudgetService, EntryInput, SourceInput
from cbrn_dashboard.services.errors import READ_ONLY, ServiceError
from cbrn_dashboard.services.exercises import (
    EditionInput,
    ExercisesService,
    MetricInput,
    ResultInput,
)
from cbrn_dashboard.services.export import UNKNOWN_ENTITY
from cbrn_dashboard.services.infrastructure import (
    AssetInput,
    AssetTypeInput,
    InfrastructureService,
)
from cbrn_dashboard.services.personnel import (
    CertificateInput,
    CourseInput,
    DegreeInput,
    PersonnelService,
    StaffInput,
    TrainingInput,
)
from cbrn_dashboard.storage import (
    budget_repo,
    csv_io,
    exercises_repo,
    infrastructure_repo,
    personnel_repo,
    repository,
)
from cbrn_dashboard.storage.csv_io import CsvFormatError, EntitySpec
from cbrn_dashboard.storage.db import DatabaseConnection, transaction
from cbrn_dashboard.storage.infrastructure_repo import AssetRow
from cbrn_dashboard.storage.repository import WriteContext

__all__ = [
    "BUILT_IN_NOT_ALLOWED",
    "DUPLICATE_IN_FILE",
    "DUPLICATE_KEY",
    "FILE_UNREADABLE",
    "UNKNOWN_REFERENCE",
    "ImportError",
    "ImportReport",
    "ImportService",
]

#: A parent (staff, course, asset, type, edition, metric, source, budget entry) does not exist.
UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
#: Two rows of the file have the same natural key (reported on the later one).
DUPLICATE_IN_FILE = "DUPLICATE_IN_FILE"
#: The natural key of the row already exists in the database.
DUPLICATE_KEY = "DUPLICATE_KEY"
#: A row of a built-in list (``built_in = 1``) whose code is not a built-in code of this version.
BUILT_IN_NOT_ALLOWED = "BUILT_IN_NOT_ALLOWED"
#: The file cannot be read (missing, a folder, no permission).
FILE_UNREADABLE = "FILE_UNREADABLE"

#: The codes the module services use for "this natural key exists"; reported as DUPLICATE_KEY.
_SERVICE_DUPLICATE_CODES = frozenset(
    {
        "DUPLICATE_IDENTIFIER",
        "DUPLICATE_CODE",
        "DUPLICATE_CERTIFICATE",
        "DUPLICATE_TRAINING",
        "DUPLICATE_DEGREE",
        "DUPLICATE_TAG",
        "STATUS_DATE_TAKEN",
        "DUPLICATE_MAINTENANCE",
        "DUPLICATE_ENTRY",
        "DUPLICATE_EXECUTION",
        DUPLICATE_KEY,
    }
)

#: Service input field -> CSV column, for fields whose name differs from the column.
_FIELD_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "level": "ppe_level",
        "type_id": "type_code",
        "source_id": "source_code",
        "course_id": "course_code",
        "metric_id": "metric_code",
        "countries": "country_code",
        "allocated_minor": "allocated",
        "amount_minor": "amount",
    }
)

type _Values = Mapping[str, object]


@dataclass(frozen=True)
class ImportError:
    """One problem of an import: the physical ``line`` (0 = the whole file), the CSV ``column``
    code (``""`` when the row or file is concerned) and a stable ``code``. No values, no text.

    The name is part of the specified API; it shadows the builtin only inside this module.
    """

    line: int
    column: str
    code: str


@dataclass(frozen=True)
class ImportReport:
    """The result of :meth:`ImportService.dry_run` or :meth:`ImportService.import_file`.

    ``imported`` is 0 for a dry run and for any failure. ``errors`` lists every problem of the
    file in line order.
    """

    entity: str
    total_rows: int
    imported: int
    errors: tuple[ImportError, ...]

    @property
    def ok(self) -> bool:
        """The file is valid (a dry run that is ``ok`` would import ``total_rows`` rows)."""
        return not self.errors


class _RollbackError(Exception):
    """Sentinel: roll the outer transaction back (a dry run or a file with errors)."""


class _ValidationOnlyError(Exception):
    """Sentinel: roll back the validation-only savepoint of an asset."""


@dataclass(frozen=True)
class _Target:
    """What a handler created: the table and the id or natural key for the ``import`` log row."""

    table: str
    entity_id: int | None = None
    entity_key: Mapping[str, object] | None = None


@dataclass(frozen=True)
class _Env:
    conn: DatabaseConnection
    personnel: PersonnelService
    infrastructure: InfrastructureService
    exercises: ExercisesService
    budget: BudgetService
    context: Callable[[], WriteContext]


# --------------------------------------------------------------------------- typed access


def _text(row: _Values, key: str) -> str | None:
    value = row.get(key)
    return value if isinstance(value, str) else None


def _required(row: _Values, key: str) -> str:
    value = _text(row, key)
    return "" if value is None else value


def _integer(row: _Values, key: str) -> int | None:
    value = row.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _real(row: _Values, key: str) -> float | None:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _flag(row: _Values, key: str) -> bool:
    return row.get(key) is True


def _unknown(field: str) -> ServiceError:
    return ServiceError(UNKNOWN_REFERENCE, field)


def _check_not_built_in(row: _Values, exists: bool) -> None:
    """Built-in rows are never created: an existing one is a duplicate, anything else refused."""
    if _flag(row, "built_in"):
        raise ServiceError(DUPLICATE_KEY if exists else BUILT_IN_NOT_ALLOWED, "built_in")


# --------------------------------------------------------------------------- parents by key


def _staff_id(env: _Env, row: _Values) -> int:
    found = personnel_repo.get_staff_by_identifier(env.conn, _required(row, "staff_identifier"))
    if found is None:
        raise _unknown("staff_identifier")
    return found.id


def _asset_id(env: _Env, row: _Values) -> int:
    found = infrastructure_repo.get_asset_by_tag(env.conn, _required(row, "asset_tag"))
    if found is None:
        raise _unknown("asset_tag")
    return found.id


def _edition_id(env: _Env, row: _Values) -> int:
    found = exercises_repo.get_edition_by_code(env.conn, _required(row, "edition_code"))
    if found is None:
        raise _unknown("edition_code")
    return found.id


def _source_id(env: _Env, row: _Values) -> int:
    found = budget_repo.get_source_by_code(env.conn, _required(row, "source_code"))
    if found is None:
        raise _unknown("source_code")
    return found.id


# --------------------------------------------------------------------------- the importers
# One function per entity: the inverse of the loader of the same entity in services/export.py.


def _import_course(env: _Env, row: _Values) -> _Target:
    new_id = env.personnel.create_course(
        CourseInput(
            code=_required(row, "code"),
            label_pt_br=_text(row, "label_pt_br"),
            label_en_us=_text(row, "label_en_us"),
            label_es_es=_text(row, "label_es_es"),
            active=_flag(row, "active"),
        )
    )
    return _Target("training_course", entity_id=new_id)


def _import_asset_type(env: _Env, row: _Values) -> _Target:
    code = _required(row, "code")
    _check_not_built_in(row, infrastructure_repo.get_type_by_code(env.conn, code) is not None)
    new_id = env.infrastructure.create_type(
        AssetTypeInput(
            code=code,
            label_pt_br=_text(row, "label_pt_br"),
            label_en_us=_text(row, "label_en_us"),
            label_es_es=_text(row, "label_es_es"),
            default_maintenance_interval_days=_integer(row, "default_maintenance_interval_days"),
            active=_flag(row, "active"),
        )
    )
    return _Target("asset_type", entity_id=new_id)


def _import_metric(env: _Env, row: _Values) -> _Target:
    new_id = env.exercises.create_metric(
        MetricInput(
            code=_required(row, "code"),
            label_pt_br=_text(row, "label_pt_br"),
            label_en_us=_text(row, "label_en_us"),
            label_es_es=_text(row, "label_es_es"),
            unit=_text(row, "unit"),
            scale_min=_real(row, "scale_min"),
            scale_max=_real(row, "scale_max"),
            higher_is_better=_flag(row, "higher_is_better"),
            active=_flag(row, "active"),
        )
    )
    return _Target("evaluation_metric", entity_id=new_id)


def _import_source(env: _Env, row: _Values) -> _Target:
    code = _required(row, "code")
    _check_not_built_in(row, budget_repo.get_source_by_code(env.conn, code) is not None)
    new_id = env.budget.create_source(
        SourceInput(
            code=code,
            label_pt_br=_text(row, "label_pt_br"),
            label_en_us=_text(row, "label_en_us"),
            label_es_es=_text(row, "label_es_es"),
            active=_flag(row, "active"),
        )
    )
    return _Target("funding_source", entity_id=new_id)


def _import_staff(env: _Env, row: _Values) -> _Target:
    new_id = env.personnel.create_staff(
        StaffInput(
            identifier=_required(row, "identifier"),
            active_from=_required(row, "active_from"),
            active_until=_text(row, "active_until"),
            label=_text(row, "label"),
            category=_text(row, "category"),
        )
    )
    return _Target("staff_member", entity_id=new_id)


def _import_certificate(env: _Env, row: _Values) -> _Target:
    staff_id = _staff_id(env, row)
    cert_id = env.personnel.add_certificate(
        staff_id,
        CertificateInput(
            level=_required(row, "ppe_level"),
            issued_on=_required(row, "issued_on"),
            valid_until=_required(row, "valid_until"),
            reference=_text(row, "reference"),
        ),
    )
    reason = _text(row, "no_renewal_reason")
    since = _text(row, "no_renewal_from")
    if since is not None or reason is not None:
        env.personnel.set_no_renewal(cert_id, since, reason)
    return _Target("ppe_certification", entity_id=cert_id)


def _import_training(env: _Env, row: _Values) -> _Target:
    staff_id = _staff_id(env, row)
    course = personnel_repo.get_course_by_code(env.conn, _required(row, "course_code"))
    if course is None:
        raise _unknown("course_code")
    new_id = env.personnel.add_training(
        staff_id,
        TrainingInput(
            course_id=course.id,
            completed_on=_required(row, "completed_on"),
            hours=_real(row, "hours"),
        ),
    )
    return _Target("training_record", entity_id=new_id)


def _import_degree(env: _Env, row: _Values) -> _Target:
    staff_id = _staff_id(env, row)
    new_id = env.personnel.add_degree(
        staff_id,
        DegreeInput(
            level=_required(row, "level"),
            status=_required(row, "status"),
            year=_integer(row, "year"),
            field=_text(row, "field"),
        ),
    )
    return _Target("academic_degree", entity_id=new_id)


def _validated_asset(env: _Env, data: AssetInput) -> AssetRow:
    """The asset as ``create_asset`` would store it; nothing stays written.

    The service validates and writes the asset (and its initial status event) inside a SAVEPOINT
    that is always rolled back; the stored row is read back first.
    """
    stored: list[AssetRow] = []
    try:
        with transaction(env.conn):
            asset_id = env.infrastructure.create_asset(data, "operational")
            found = infrastructure_repo.get_asset(env.conn, asset_id)
            if found is not None:
                stored.append(found)
            raise _ValidationOnlyError
    except _ValidationOnlyError:
        pass
    if not stored:  # pragma: no cover - create_asset returned an id that cannot be read back
        raise ServiceError("NOT_FOUND", "tag")
    return stored[0]


def _import_asset(env: _Env, row: _Values) -> _Target:
    type_row = infrastructure_repo.get_type_by_code(env.conn, _required(row, "type_code"))
    if type_row is None:
        raise _unknown("type_code")
    checked = _validated_asset(
        env,
        AssetInput(
            tag=_required(row, "tag"),
            type_id=type_row.id,
            in_service_from=_required(row, "in_service_from"),
            in_service_until=_text(row, "in_service_until"),
            description=_text(row, "description"),
            location=_text(row, "location"),
            maintenance_interval_days=_integer(row, "maintenance_interval_days"),
            notes=_text(row, "notes"),
        ),
    )
    new_id = infrastructure_repo.insert_asset(
        env.context(),
        type_id=checked.type_id,
        tag=checked.tag,
        description=checked.description,
        location=checked.location,
        in_service_from=checked.in_service_from,
        in_service_until=checked.in_service_until,
        maintenance_interval_days=checked.maintenance_interval_days,
        notes=checked.notes,
    )
    return _Target("asset", entity_id=new_id)


def _import_status_event(env: _Env, row: _Values) -> _Target:
    new_id = env.infrastructure.change_status(
        _asset_id(env, row),
        _required(row, "effective_on"),
        _required(row, "status"),
        note=_text(row, "note"),
    )
    return _Target("asset_status_event", entity_id=new_id)


def _import_maintenance(env: _Env, row: _Values) -> _Target:
    new_id = env.infrastructure.record_maintenance(
        _asset_id(env, row),
        _required(row, "performed_on"),
        _required(row, "kind"),
        next_due_on=_text(row, "next_due_on"),
        note=_text(row, "note"),
    )
    return _Target("maintenance_event", entity_id=new_id)


def _import_edition(env: _Env, row: _Values) -> _Target:
    new_id = env.exercises.create_edition(
        EditionInput(
            code=_required(row, "code"),
            kind=_required(row, "kind"),
            start_on=_required(row, "start_on"),
            end_on=_required(row, "end_on"),
            title=_text(row, "title"),
            participants=_integer(row, "participants"),
            notes=_text(row, "notes"),
        )
    )
    return _Target("exercise_edition", entity_id=new_id)


def _import_country(env: _Env, row: _Values) -> _Target:
    edition = exercises_repo.get_edition_by_code(env.conn, _required(row, "edition_code"))
    if edition is None:
        raise _unknown("edition_code")
    country = _required(row, "country_code").upper()
    existing = exercises_repo.list_edition_countries(env.conn, edition.id)
    if country in existing:
        raise ServiceError(DUPLICATE_KEY)
    env.exercises.update_edition(
        edition.id,
        EditionInput(
            code=edition.code,
            kind=edition.kind,
            start_on=edition.start_on,
            end_on=edition.end_on,
            title=edition.title,
            participants=edition.participants,
            notes=edition.notes,
            countries=(*existing, country),
        ),
    )
    return _Target(
        "exercise_country", entity_key={"edition_id": edition.id, "country_code": country}
    )


def _import_result(env: _Env, row: _Values) -> _Target:
    edition_id = _edition_id(env, row)
    metric = exercises_repo.get_metric_by_code(env.conn, _required(row, "metric_code"))
    if metric is None:
        raise _unknown("metric_code")
    if exercises_repo.get_result(env.conn, edition_id, metric.id) is not None:
        raise ServiceError(DUPLICATE_KEY)
    value = _real(row, "value")
    env.exercises.set_result(
        edition_id,
        ResultInput(
            metric_id=metric.id,
            value=0.0 if value is None else value,
            respondents=_integer(row, "respondents"),
            note=_text(row, "note"),
        ),
    )
    return _Target(
        "evaluation_result", entity_key={"edition_id": edition_id, "metric_id": metric.id}
    )


def _import_entry(env: _Env, row: _Values) -> _Target:
    new_id = env.budget.create_entry(
        EntryInput(
            fiscal_year=_integer(row, "fiscal_year"),
            source_id=_source_id(env, row),
            allocated_minor=_integer(row, "allocated"),
            currency=_text(row, "currency"),
            description=_text(row, "description"),
            notes=_text(row, "notes"),
        )
    )
    return _Target("budget_entry", entity_id=new_id)


def _import_execution(env: _Env, row: _Values) -> _Target:
    _source_id(env, row)
    year = _integer(row, "fiscal_year")
    entry = (
        None
        if year is None
        else budget_repo.get_entry_by_key(
            env.conn,
            year,
            _required(row, "source_code"),
            _required(row, "currency"),
            _required(row, "description").strip(),
        )
    )
    if entry is None:
        raise _unknown("description")
    new_id = env.budget.add_execution(
        entry.id,
        _required(row, "executed_on"),
        _integer(row, "amount") or 0,
        note=_text(row, "note"),
    )
    return _Target("budget_execution", entity_id=new_id)


#: The parsed row of each entity -> the module-service call (the inverse of ``export._LOADERS``).
_IMPORTERS: Mapping[str, Callable[[_Env, _Values], _Target]] = MappingProxyType(
    {
        "training_course": _import_course,
        "asset_type": _import_asset_type,
        "evaluation_metric": _import_metric,
        "funding_source": _import_source,
        "staff_member": _import_staff,
        "ppe_certification": _import_certificate,
        "training_record": _import_training,
        "academic_degree": _import_degree,
        "asset": _import_asset,
        "asset_status_event": _import_status_event,
        "maintenance_event": _import_maintenance,
        "exercise_edition": _import_edition,
        "exercise_country": _import_country,
        "evaluation_result": _import_result,
        "budget_entry": _import_entry,
        "budget_execution": _import_execution,
    }
)


# --------------------------------------------------------------------------- keys and errors


def _normalised(code: str, value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        return text.upper() if code == "country_code" else text
    return value


def _natural_key(spec: EntitySpec, values: _Values) -> tuple[object, ...]:
    """The natural key as the services compare it (text trimmed, NULL as the empty text)."""
    return tuple(_normalised(code, values.get(code)) for code in spec.natural_key)


def _column_of(spec: EntitySpec, field: str | None) -> str:
    if field is None:
        return ""
    if field in spec.column_codes:
        return field
    alias = _FIELD_ALIASES.get(field)
    return alias if alias is not None and alias in spec.column_codes else ""


def _issue(spec: EntitySpec, line: int, exc: ServiceError | CsvFormatError) -> ImportError:
    if isinstance(exc, CsvFormatError):
        return ImportError(line, exc.column or "", exc.code)
    if exc.code in _SERVICE_DUPLICATE_CODES:
        return ImportError(line, "", DUPLICATE_KEY)
    return ImportError(line, _column_of(spec, exc.field), exc.code)


# --------------------------------------------------------------------------- the service


class ImportService:
    """Validate and import the CSV files of the module entities, all or nothing."""

    def __init__(
        self,
        conn: DatabaseConnection,
        clock: Clock,
        operator: Callable[[], str],
        *,
        personnel: PersonnelService,
        infrastructure: InfrastructureService,
        exercises: ExercisesService,
        budget: BudgetService,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._operator = operator
        self._env = _Env(
            conn=conn,
            personnel=personnel,
            infrastructure=infrastructure,
            exercises=exercises,
            budget=budget,
            context=self._context,
        )

    def _context(self) -> WriteContext:
        return WriteContext(self._conn, self._clock, self._operator())

    # ----- templates

    def entity_names(self) -> tuple[str, ...]:
        """The importable entities in import order (list entities first)."""
        return tuple(spec.name for spec in csv_io.ENTITIES)

    def write_template(self, name: str, out_dir: Path) -> Path:
        """Write the header-only template of an entity; ``UNKNOWN_ENTITY`` for another name."""
        spec = self._spec(name)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / csv_io.template_file_name(spec)
            csv_io.write_template(path, spec)
        except OSError:
            raise ServiceError(FILE_UNREADABLE, "out_dir") from None
        return path

    def write_all_templates(self, out_dir: Path) -> list[Path]:
        """Write the templates of all entities, in import order."""
        return [self.write_template(name, out_dir) for name in self.entity_names()]

    # ----- import

    def dry_run(self, name: str, path: Path) -> ImportReport:
        """Check a file exactly as :meth:`import_file` would and write nothing.

        It needs a write transaction (rolled back at the end), so a read-only connection is
        refused with ``READ_ONLY``.
        """
        return self._run(name, path, commit=False)

    def import_file(self, name: str, path: Path) -> ImportReport:
        """Import a file: all rows or none. ``READ_ONLY`` on a read-only connection.

        A file with any problem writes nothing; the report lists every problem.
        """
        return self._run(name, path, commit=True)

    def _spec(self, name: str) -> EntitySpec:
        spec = csv_io.entity_spec(name)
        if spec is None:
            raise ServiceError(UNKNOWN_ENTITY, "entity")
        return spec

    def _run(self, name: str, path: Path, *, commit: bool) -> ImportReport:
        spec = self._spec(name)
        if self._conn.read_only:
            raise ServiceError(READ_ONLY)
        try:
            parsed = csv_io.read_import_file(path, spec)
        except OSError:
            raise ServiceError(FILE_UNREADABLE, "path") from None
        total = len(parsed.rows)
        if parsed.errors:
            errors = tuple(ImportError(e.line, e.column, e.code) for e in parsed.errors)
            return self._finish(spec, total, 0, errors, commit=commit)
        issues: list[ImportError] = []
        imported = 0
        try:
            with transaction(self._conn):
                imported = self._rows(spec, parsed, issues)
                if issues or not commit:
                    raise _RollbackError
        except _RollbackError:
            imported = 0
        return self._finish(spec, total, imported, tuple(issues), commit=commit)

    def _rows(self, spec: EntitySpec, parsed: csv_io.ImportFile, issues: list[ImportError]) -> int:
        handler = _IMPORTERS[spec.name]
        seen: set[tuple[object, ...]] = set()
        imported = 0
        for row in parsed.rows:
            if row.errors:
                issues.extend(ImportError(e.line, e.column, e.code) for e in row.errors)
                continue
            key = _natural_key(spec, row.values)
            if key in seen:
                issues.append(ImportError(row.line, "", DUPLICATE_IN_FILE))
                continue
            seen.add(key)
            try:
                with transaction(self._conn):
                    target = handler(self._env, row.values)
                    repository.log_event(
                        self._context(),
                        target.table,
                        "import",
                        entity_id=target.entity_id,
                        entity_key=target.entity_key,
                    )
            except (ServiceError, CsvFormatError) as exc:
                issues.append(_issue(spec, row.line, exc))
            else:
                imported += 1
        return imported

    def _finish(
        self,
        spec: EntitySpec,
        total: int,
        imported: int,
        errors: tuple[ImportError, ...],
        *,
        commit: bool,
    ) -> ImportReport:
        if commit:
            if errors:
                logging_setup.log_event("IMPORT.FAILED", level=logging.WARNING, count=len(errors))
            else:
                logging_setup.log_event("IMPORT.DONE", count=imported)
        return ImportReport(entity=spec.name, total_rows=total, imported=imported, errors=errors)
