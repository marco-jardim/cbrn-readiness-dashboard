# SPDX-License-Identifier: GPL-3.0-or-later
"""CSV export of the module data, one file per entity (PLAN.md T8.3, D04, D15, D25).

Qt-free and read-only: the service only reads, so it also works on a read-only connection. The rows
are loaded through the ``list_*`` functions of the repositories and joined to the natural keys of
their parents in ONE place (:data:`_LOADERS`); internal ids never reach the files. The file format
itself (encoding, delimiter, guard, column codes) lives in ``storage/csv_io.py``.

Whether the file names carry the ``DEMO-`` prefix comes from ``app_meta.is_demo`` of the open
database, never from a parameter (D25). The service shows no prompt and no path warning: warning
about network, cloud or removable-media folders is the job of the UI (T8.7). The files contain
internal data (staff qualifications, infrastructure status, budget); they stay where the operator
puts them.

An existing file of the same name is overwritten (the UI asks first, using
:meth:`ExportService.existing_files`). :meth:`ExportService.export_all` writes every file into a
staging folder inside the target and moves the files into place only after ALL were written. If
writing fails (``EXPORT_FAILED``, with the entity in ``field``; a ``CsvFormatError`` is mapped to
it too) the staging folder is removed and the files already in the folder are untouched, so a
failed export never leaves a mix of this run's files and older ones. (This replaces the earlier
rule that finished files stay after a failure, P8-07.)
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.storage import (
    app_meta,
    budget_repo,
    csv_io,
    exercises_repo,
    infrastructure_repo,
    personnel_repo,
)
from cbrn_dashboard.storage.csv_io import EntitySpec
from cbrn_dashboard.storage.db import DatabaseConnection

__all__ = [
    "EXPORT_FAILED",
    "UNKNOWN_ENTITY",
    "ExportService",
    "ExportedFile",
]

#: The entity name is not one of :meth:`ExportService.entity_names`.
UNKNOWN_ENTITY = "UNKNOWN_ENTITY"
#: A file or the folder could not be written (or a row refers to a parent that does not exist).
EXPORT_FAILED = "EXPORT_FAILED"

type _Row = dict[str, object]

_STAGING_PREFIX = ".export-"


@dataclass(frozen=True)
class ExportedFile:
    """One file written by an export."""

    entity: str
    path: Path
    rows: int


def _parent(names: Mapping[int, str], parent_id: int, entity: str) -> str:
    """The natural key of a parent row; a dangling reference makes the export fail."""
    name = names.get(parent_id)
    if name is None:
        raise ServiceError(EXPORT_FAILED, entity)
    return name


# --------------------------------------------------------------------------- loaders (the join)


def _load_courses(conn: DatabaseConnection) -> list[_Row]:
    return [
        {
            "code": row.code,
            "label_pt_br": row.label_pt_br,
            "label_en_us": row.label_en_us,
            "label_es_es": row.label_es_es,
            "active": row.active,
        }
        for row in personnel_repo.list_courses(conn)
    ]


def _load_asset_types(conn: DatabaseConnection) -> list[_Row]:
    return [
        {
            "code": row.code,
            "built_in": row.built_in,
            "label_pt_br": row.label_pt_br,
            "label_en_us": row.label_en_us,
            "label_es_es": row.label_es_es,
            "default_maintenance_interval_days": row.default_maintenance_interval_days,
            "active": row.active,
        }
        for row in infrastructure_repo.list_types(conn)
    ]


def _load_metrics(conn: DatabaseConnection) -> list[_Row]:
    return [
        {
            "code": row.code,
            "label_pt_br": row.label_pt_br,
            "label_en_us": row.label_en_us,
            "label_es_es": row.label_es_es,
            "unit": row.unit,
            "scale_min": row.scale_min,
            "scale_max": row.scale_max,
            "higher_is_better": row.higher_is_better,
            "active": row.active,
        }
        for row in exercises_repo.list_metrics(conn)
    ]


def _load_sources(conn: DatabaseConnection) -> list[_Row]:
    return [
        {
            "code": row.code,
            "built_in": row.built_in,
            "label_pt_br": row.label_pt_br,
            "label_en_us": row.label_en_us,
            "label_es_es": row.label_es_es,
            "active": row.active,
        }
        for row in budget_repo.list_sources(conn)
    ]


def _load_staff(conn: DatabaseConnection) -> list[_Row]:
    return [
        {
            "identifier": row.identifier,
            "label": row.label,
            "category": row.category,
            "active_from": row.active_from,
            "active_until": row.active_until,
        }
        for row in personnel_repo.list_staff(conn)
    ]


def _staff_identifiers(conn: DatabaseConnection) -> dict[int, str]:
    return {row.id: row.identifier for row in personnel_repo.list_staff(conn)}


def _load_certificates(conn: DatabaseConnection) -> list[_Row]:
    staff = _staff_identifiers(conn)
    return [
        {
            "staff_identifier": _parent(staff, row.staff_id, "ppe_certification"),
            "ppe_level": row.ppe_level,
            "issued_on": row.issued_on,
            "valid_until": row.valid_until,
            "no_renewal_from": row.no_renewal_from,
            "no_renewal_reason": row.no_renewal_reason,
            "reference": row.reference,
        }
        for row in personnel_repo.list_certificates(conn)
    ]


def _load_training(conn: DatabaseConnection) -> list[_Row]:
    staff = _staff_identifiers(conn)
    courses = {row.id: row.code for row in personnel_repo.list_courses(conn)}
    return [
        {
            "staff_identifier": _parent(staff, row.staff_id, "training_record"),
            "course_code": _parent(courses, row.course_id, "training_record"),
            "completed_on": row.completed_on,
            "hours": row.hours,
        }
        for row in personnel_repo.list_training(conn)
    ]


def _load_degrees(conn: DatabaseConnection) -> list[_Row]:
    staff = _staff_identifiers(conn)
    return [
        {
            "staff_identifier": _parent(staff, row.staff_id, "academic_degree"),
            "level": row.level,
            "status": row.status,
            "year": row.year,
            "field": row.field,
        }
        for row in personnel_repo.list_degrees(conn)
    ]


def _asset_tags(conn: DatabaseConnection) -> dict[int, str]:
    return {row.id: row.tag for row in infrastructure_repo.list_assets(conn)}


def _load_assets(conn: DatabaseConnection) -> list[_Row]:
    types = {row.id: row.code for row in infrastructure_repo.list_types(conn)}
    return [
        {
            "tag": row.tag,
            "type_code": _parent(types, row.type_id, "asset"),
            "description": row.description,
            "location": row.location,
            "in_service_from": row.in_service_from,
            "in_service_until": row.in_service_until,
            "maintenance_interval_days": row.maintenance_interval_days,
            "notes": row.notes,
        }
        for row in infrastructure_repo.list_assets(conn)
    ]


def _load_status_events(conn: DatabaseConnection) -> list[_Row]:
    tags = _asset_tags(conn)
    return [
        {
            "asset_tag": _parent(tags, row.asset_id, "asset_status_event"),
            "effective_on": row.effective_on,
            "status": row.status,
            "note": row.note,
        }
        for row in infrastructure_repo.list_status_events(conn)
    ]


def _load_maintenance(conn: DatabaseConnection) -> list[_Row]:
    tags = _asset_tags(conn)
    return [
        {
            "asset_tag": _parent(tags, row.asset_id, "maintenance_event"),
            "performed_on": row.performed_on,
            "kind": row.kind,
            "next_due_on": row.next_due_on,
            "note": row.note,
        }
        for row in infrastructure_repo.list_maintenance(conn)
    ]


def _load_editions(conn: DatabaseConnection) -> list[_Row]:
    return [
        {
            "code": row.code,
            "kind": row.kind,
            "title": row.title,
            "start_on": row.start_on,
            "end_on": row.end_on,
            "participants": row.participants,
            "notes": row.notes,
        }
        for row in exercises_repo.list_editions(conn)
    ]


def _load_countries(conn: DatabaseConnection) -> list[_Row]:
    countries = exercises_repo.countries_by_edition(conn)
    return [
        {"edition_code": edition.code, "country_code": country}
        for edition in exercises_repo.list_editions(conn)
        for country in sorted(countries.get(edition.id, frozenset()))
    ]


def _load_results(conn: DatabaseConnection) -> list[_Row]:
    editions = {row.id: row.code for row in exercises_repo.list_editions(conn)}
    metrics = {row.id: row.code for row in exercises_repo.list_metrics(conn)}
    return [
        {
            "edition_code": _parent(editions, row.edition_id, "evaluation_result"),
            "metric_code": _parent(metrics, row.metric_id, "evaluation_result"),
            "value": row.value,
            "respondents": row.respondents,
            "note": row.note,
        }
        for row in exercises_repo.list_results(conn)
    ]


def _load_entries(conn: DatabaseConnection) -> list[_Row]:
    sources = budget_repo.source_codes(conn)
    return [
        {
            "fiscal_year": row.fiscal_year,
            "source_code": _parent(sources, row.source_id, "budget_entry"),
            "currency": row.currency,
            "description": row.description,
            "allocated": row.allocated_minor,
            "notes": row.notes,
        }
        for row in budget_repo.list_entries(conn)
    ]


def _load_executions(conn: DatabaseConnection) -> list[_Row]:
    sources = budget_repo.source_codes(conn)
    entries = {row.id: row for row in budget_repo.list_entries(conn)}
    rows: list[_Row] = []
    for execution in budget_repo.list_executions(conn):
        entry = entries.get(execution.entry_id)
        if entry is None:
            raise ServiceError(EXPORT_FAILED, "budget_execution")
        rows.append(
            {
                "fiscal_year": entry.fiscal_year,
                "source_code": _parent(sources, entry.source_id, "budget_execution"),
                "currency": entry.currency,
                "description": entry.description,
                "executed_on": execution.executed_on,
                "amount": execution.amount_minor,
                "note": execution.note,
            }
        )
    return rows


_LOADERS: dict[str, Callable[[DatabaseConnection], list[_Row]]] = {
    "training_course": _load_courses,
    "asset_type": _load_asset_types,
    "evaluation_metric": _load_metrics,
    "funding_source": _load_sources,
    "staff_member": _load_staff,
    "ppe_certification": _load_certificates,
    "training_record": _load_training,
    "academic_degree": _load_degrees,
    "asset": _load_assets,
    "asset_status_event": _load_status_events,
    "maintenance_event": _load_maintenance,
    "exercise_edition": _load_editions,
    "exercise_country": _load_countries,
    "evaluation_result": _load_results,
    "budget_entry": _load_entries,
    "budget_execution": _load_executions,
}


# --------------------------------------------------------------------------- the service


class ExportService:
    """Write the module data of the open database as CSV files (read-only use)."""

    def __init__(self, conn: DatabaseConnection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def entity_names(self) -> tuple[str, ...]:
        """The exportable entities in import order (list entities first)."""
        return tuple(spec.name for spec in csv_io.ENTITIES)

    def export_all(self, out_dir: Path) -> list[ExportedFile]:
        """Write one file per entity into ``out_dir`` (created if missing, files overwritten).

        All rows are read before the first file is written, so the files describe one state of
        the database. ``EXPORT_FAILED`` when the folder or a file cannot be written.
        """
        loaded = [(spec, _LOADERS[spec.name](self._conn)) for spec in csv_io.ENTITIES]
        is_demo = app_meta.read_is_demo(self._conn)
        _make_folder(out_dir)
        return _write_all(out_dir, loaded, is_demo=is_demo)

    def existing_files(self, out_dir: Path) -> list[Path]:
        """The files of :meth:`export_all` that already exist in ``out_dir`` (the UI asks first)."""
        is_demo = app_meta.read_is_demo(self._conn)
        names = (csv_io.export_file_name(spec, is_demo=is_demo) for spec in csv_io.ENTITIES)
        return [out_dir / name for name in names if (out_dir / name).exists()]

    def export_entity(self, name: str, out_dir: Path) -> ExportedFile:
        """Write the file of one entity; ``UNKNOWN_ENTITY`` for a name that is not an entity."""
        spec = csv_io.entity_spec(name)
        if spec is None:
            raise ServiceError(UNKNOWN_ENTITY, "entity")
        rows = _LOADERS[spec.name](self._conn)
        is_demo = app_meta.read_is_demo(self._conn)
        _make_folder(out_dir)
        return _write(out_dir, spec, rows, is_demo=is_demo)


def _make_folder(out_dir: Path) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise ServiceError(EXPORT_FAILED, "out_dir") from None


def _write(out_dir: Path, spec: EntitySpec, rows: list[_Row], *, is_demo: bool) -> ExportedFile:
    path = out_dir / csv_io.export_file_name(spec, is_demo=is_demo)
    try:
        count = csv_io.write_entity(path, spec, rows)
    except (OSError, csv_io.CsvFormatError):
        raise ServiceError(EXPORT_FAILED, spec.name) from None
    return ExportedFile(entity=spec.name, path=path, rows=count)


def _write_all(
    out_dir: Path, loaded: list[tuple[EntitySpec, list[_Row]]], *, is_demo: bool
) -> list[ExportedFile]:
    """Write every file into a staging folder, then move them all into ``out_dir``.

    A failure while writing removes the staging folder and leaves ``out_dir`` as it was.
    """
    try:
        staging = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=out_dir))
    except OSError:
        raise ServiceError(EXPORT_FAILED, "out_dir") from None
    try:
        staged = [(spec, _write(staging, spec, rows, is_demo=is_demo)) for spec, rows in loaded]
        for spec, item in staged:
            target = out_dir / item.path.name
            if target.exists() and not target.is_file():  # nothing is moved before all can be
                raise ServiceError(EXPORT_FAILED, spec.name)
        files: list[ExportedFile] = []
        for spec, item in staged:
            final = out_dir / item.path.name
            try:
                item.path.replace(final)
            except OSError:
                raise ServiceError(EXPORT_FAILED, spec.name) from None
            files.append(ExportedFile(entity=spec.name, path=final, rows=item.rows))
        return files
    finally:
        shutil.rmtree(staging, ignore_errors=True)
