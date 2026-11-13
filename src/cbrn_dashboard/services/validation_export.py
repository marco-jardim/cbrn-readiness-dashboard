# SPDX-License-Identifier: GPL-3.0-or-later
"""Validation export for the predictive-validity comparison (PLAN.md T8.2, R29, R31, K03, K13).

Qt-free. The service reads the recorded snapshots (T8.1) and the exercise editions and results
(T4.4) and writes two CSV files in the D04 format (``storage/csv_io.py``: UTF-8 with BOM, ``;``,
ISO dates, ``.`` as decimal point, formula guard, temporary file then rename). The statistical
analysis is outside the application (section 2.2): nothing is computed here, the data is only
joined and written. The files hold codes and numbers only: no names, no free text, no staff
identifiers.

Which snapshot belongs to which edition. For each edition the service takes the LATEST snapshot
(by ``taken_at_utc``, then id) that is not withdrawn, whose origin is not ``retroactive``, whose
``as_of`` is before the edition's ``start_on`` and which was taken, on the local calendar date,
before ``start_on``. Retroactive and withdrawn snapshots are therefore never preferred over an
earlier valid one. When there is none, the operator may ask for a retroactive reading
(``record_retroactive=True``): an existing non-withdrawn ``retroactive`` snapshot whose ``as_of`` is
the day before ``start_on`` is used, else one is recorded through the snapshot service for that day
(which needs a writable connection: ``READ_ONLY`` otherwise, and nothing is written; a day in the
future cannot be recorded). Without the request, or when none can be had, the edition has ONE
readings row that carries the reason code ``NO_PRIOR_SNAPSHOT`` and nothing else. A retroactive
reading keeps its origin ``retroactive`` in the file.

Readings file, one row per (edition, indicator, dimension) of the chosen snapshot; columns in order:
``edition_code``, ``kind``, ``start_on``, ``snapshot_id``, ``snapshot_as_of``, ``taken_at_utc``,
``age_days`` (days from the local calendar date on which the snapshot was taken to ``start_on``;
negative when the snapshot was taken after it), ``origin``, ``indicator_code``, ``dimension``,
``value``, ``status`` and ``reason_code``. Rows are sorted by edition code, indicator code and
dimension (code point order), so two runs over the same data give identical bytes.

Results file, one row per stored result: ``edition_code``, ``metric_code``, ``value``,
``respondents``, ``scale_min``, ``scale_max`` (the scale of the metric; empty when it has none).
Sorted by edition code and metric code. Exercise results are not personnel-derived and are never
suppressed.

Labelling (K03). The file names (``validation_readings_unsuppressed_internal.csv``) and a first
banner record before the column codes say that the data is unsuppressed internal data. With
``suppress_small_counts=True`` the same suppression as the anonymised report (A11) applies to the
readings: a PERSONNEL indicator that is a COUNT and whose value is in ``0 .. threshold - 1`` (zero
included) is written as ``< threshold`` and its status as ``NO_DATA`` (a status bounds the value);
infrastructure, exercise and budget figures are never suppressed. The names and the banner then say
``suppressed``. The snapshots hold no totals, so there is no secondary suppression to apply, and
differencing between two exports is not prevented (residual risk Q10). The threshold comes from the
configuration. Whether the names start with ``DEMO-`` comes from ``app_meta.is_demo`` (D25).

Failures. ``EXPORT_FAILED`` with the failing entity in ``field`` (``out_dir`` when the folder
cannot be made): a file that did not exist before is removed when a later file fails, and no
temporary file is left. A file that was overwritten before the failure stays as it was written.
Log lines carry event codes only. The service only reads (apart from the optional retroactive
snapshot), so it also works on a read-only connection.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain.dates import parse_utc_timestamp
from cbrn_dashboard.domain.indicators import IndicatorDefinition, IndicatorStatus, Module, UnitKind
from cbrn_dashboard.logging_setup import log_event
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.exercises import EditionView, ExercisesService
from cbrn_dashboard.services.export import EXPORT_FAILED, ExportedFile
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.snapshots import SnapshotOrigin, SnapshotService, SnapshotView
from cbrn_dashboard.storage import app_meta, csv_io
from cbrn_dashboard.storage.csv_io import (
    BelowThreshold,
    ColumnKind,
    ColumnSpec,
    CsvFormatError,
    EntitySpec,
)
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.settings_repo import load_config

__all__ = [
    "NO_PRIOR_SNAPSHOT",
    "READINGS_ENTITY",
    "RESULTS_ENTITY",
    "SUPPRESSED_BANNER",
    "UNSUPPRESSED_BANNER",
    "ValidationExportResult",
    "ValidationExportService",
    "readings_spec",
    "results_spec",
]

#: The reason code of the rows of an edition that has no snapshot taken before it started.
NO_PRIOR_SNAPSHOT = "NO_PRIOR_SNAPSHOT"
#: Entity names (the ``field`` of ``EXPORT_FAILED``) of the two files.
READINGS_ENTITY = "validation_readings"
RESULTS_ENTITY = "validation_results"
#: The first record of every file (before the column codes).
UNSUPPRESSED_BANNER = "UNSUPPRESSED_INTERNAL_DATA"
SUPPRESSED_BANNER = "SUPPRESSED_INTERNAL_DATA"

type _Row = dict[str, object]


def _code(code: str, *, required: bool = False) -> ColumnSpec:
    return ColumnSpec(code, ColumnKind.CODE, required)


def _label(*, suppressed: bool) -> str:
    return "suppressed_internal" if suppressed else "unsuppressed_internal"


def readings_spec(*, suppressed: bool) -> EntitySpec:
    """The columns of the readings file; the file stem says whether small counts are suppressed."""
    return EntitySpec(
        READINGS_ENTITY,
        f"validation_readings_{_label(suppressed=suppressed)}",
        (
            _code("edition_code", required=True),
            _code("kind", required=True),
            ColumnSpec("start_on", ColumnKind.DATE, True),
            ColumnSpec("snapshot_id", ColumnKind.INTEGER),
            ColumnSpec("snapshot_as_of", ColumnKind.DATE),
            _code("taken_at_utc"),
            ColumnSpec("age_days", ColumnKind.INTEGER),
            _code("origin"),
            _code("indicator_code"),
            _code("dimension"),
            ColumnSpec("value", ColumnKind.REAL),
            _code("status"),
            _code("reason_code"),
        ),
        ("edition_code", "indicator_code", "dimension"),
    )


def results_spec(*, suppressed: bool) -> EntitySpec:
    """The columns of the results file; the file stem follows the readings file."""
    return EntitySpec(
        RESULTS_ENTITY,
        f"validation_results_{_label(suppressed=suppressed)}",
        (
            _code("edition_code", required=True),
            _code("metric_code", required=True),
            ColumnSpec("value", ColumnKind.REAL, True),
            ColumnSpec("respondents", ColumnKind.INTEGER),
            ColumnSpec("scale_min", ColumnKind.REAL),
            ColumnSpec("scale_max", ColumnKind.REAL),
        ),
        ("edition_code", "metric_code"),
    )


@dataclass(frozen=True)
class ValidationExportResult:
    """What an export wrote: the two files, the snapshots recorded for it and the editions that
    have no reading (their rows carry ``NO_PRIOR_SNAPSHOT``)."""

    readings: ExportedFile
    results: ExportedFile
    recorded_snapshot_ids: tuple[int, ...]
    editions_without_reading: tuple[str, ...]


class ValidationExportService:
    """Join the snapshots to the exercise editions and write the validation export."""

    def __init__(
        self,
        conn: DatabaseConnection,
        clock: Clock,
        *,
        snapshots: SnapshotService,
        exercises: ExercisesService,
        indicators: IndicatorService,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._snapshots = snapshots
        self._exercises = exercises
        self._indicators = indicators

    # ----- choosing the snapshot of an edition

    def _taken_on(self, snapshot: SnapshotView) -> date:
        return self._clock.local_date_of(parse_utc_timestamp(snapshot.taken_at_utc))

    def _regular(self, edition: EditionView, snapshots: list[SnapshotView]) -> SnapshotView | None:
        """The latest non-retroactive snapshot as of and taken before ``start_on``."""
        start = edition.start_on
        candidates = [
            s
            for s in snapshots
            if s.origin is not SnapshotOrigin.RETROACTIVE
            and s.as_of < start
            and self._taken_on(s) < start
        ]
        return max(candidates, key=lambda s: (s.taken_at_utc, s.id), default=None)

    @staticmethod
    def _existing_retroactive(
        edition: EditionView, snapshots: list[SnapshotView]
    ) -> SnapshotView | None:
        """The latest retroactive snapshot as of the day before ``start_on``."""
        day_before = edition.start_on - timedelta(days=1)
        candidates = [
            s for s in snapshots if s.origin is SnapshotOrigin.RETROACTIVE and s.as_of == day_before
        ]
        return max(candidates, key=lambda s: (s.taken_at_utc, s.id), default=None)

    def editions_without_prior_snapshot(self) -> list[str]:
        """The codes of the editions with no regular snapshot before them, by start date.

        The user interface offers the retroactive reading for these (T8.7).
        """
        snapshots = self._snapshots.list_snapshots()
        return [
            edition.code
            for edition in self._exercises.list_editions()
            if self._regular(edition, snapshots) is None
        ]

    def _record_retroactive(self, edition: EditionView) -> SnapshotView | None:
        as_of = edition.start_on - timedelta(days=1)
        if as_of > self._clock.local_date():
            return None  # a reading cannot be recorded in advance
        # The service decides the stored origin: retroactive whenever as_of is before today.
        return self._snapshots.record(as_of, origin=SnapshotOrigin.MANUAL)

    def _choose(
        self, editions: list[EditionView], *, record_retroactive: bool
    ) -> tuple[dict[str, SnapshotView | None], list[int]]:
        snapshots = self._snapshots.list_snapshots()
        chosen: dict[str, SnapshotView | None] = {}
        recorded: list[int] = []
        for edition in editions:
            pick = self._regular(edition, snapshots)
            if pick is None and record_retroactive:
                pick = self._existing_retroactive(edition, snapshots)
                if pick is None:
                    pick = self._record_retroactive(edition)
                    if pick is not None:
                        snapshots.append(pick)
                        recorded.append(pick.id)
            chosen[edition.code] = pick
        return chosen, recorded

    # ----- the rows

    def _readings_rows(
        self,
        editions: list[EditionView],
        chosen: dict[str, SnapshotView | None],
        threshold: int | None,
    ) -> list[_Row]:
        definitions = {definition.code: definition for definition in self._indicators.definitions()}
        rows: list[_Row] = []
        for edition in editions:
            snapshot = chosen[edition.code]
            head: _Row = {
                "edition_code": edition.code,
                "kind": edition.kind.value,
                "start_on": edition.start_on,
            }
            if snapshot is None:
                rows.append({**head, "reason_code": NO_PRIOR_SNAPSHOT})
                continue
            age_days = (edition.start_on - self._taken_on(snapshot)).days
            for item in self._snapshots.values(snapshot.id):
                value: float | BelowThreshold | None = item.value
                status = item.status
                if threshold is not None and _is_small_count(
                    definitions.get(item.indicator_code), item.value, threshold
                ):
                    value = BelowThreshold(threshold)
                    status = IndicatorStatus.NO_DATA
                rows.append(
                    {
                        **head,
                        "snapshot_id": snapshot.id,
                        "snapshot_as_of": snapshot.as_of,
                        "taken_at_utc": snapshot.taken_at_utc,
                        "age_days": age_days,
                        "origin": snapshot.origin.value,
                        "indicator_code": item.indicator_code,
                        "dimension": item.dimension,
                        "value": value,
                        "status": status.value,
                    }
                )
        return rows

    def _results_rows(self, editions: list[EditionView]) -> list[_Row]:
        metrics = {m.id: m for m in self._exercises.list_metrics(include_inactive=True)}
        rows: list[_Row] = []
        for edition in editions:
            for result in edition.results:
                metric = metrics.get(result.metric_id)
                rows.append(
                    {
                        "edition_code": edition.code,
                        "metric_code": result.metric_code,
                        "value": result.value,
                        "respondents": result.respondents,
                        "scale_min": None if metric is None else metric.scale_min,
                        "scale_max": None if metric is None else metric.scale_max,
                    }
                )
        return rows

    # ----- the export

    def export(
        self,
        out_dir: Path,
        *,
        suppress_small_counts: bool = False,
        record_retroactive: bool = False,
    ) -> ValidationExportResult:
        """Write the two files into ``out_dir`` (created if missing, files overwritten).

        All rows are built before the first file is written. Refusals: ``READ_ONLY`` when
        ``record_retroactive`` needs a snapshot to be recorded on a read-only connection (nothing
        is written); ``EXPORT_FAILED`` when a folder or a file cannot be written.
        """
        editions = self._exercises.list_editions()
        chosen, recorded = self._choose(editions, record_retroactive=record_retroactive)
        threshold: int | None = None
        if suppress_small_counts:
            threshold = load_config(self._conn).small_count_threshold
        readings_rows = self._readings_rows(editions, chosen, threshold)
        results_rows = self._results_rows(editions)
        banner = SUPPRESSED_BANNER if suppress_small_counts else UNSUPPRESSED_BANNER
        jobs = (
            (readings_spec(suppressed=suppress_small_counts), readings_rows),
            (results_spec(suppressed=suppress_small_counts), results_rows),
        )
        is_demo = app_meta.read_is_demo(self._conn)
        _make_folder(out_dir)
        written = _write_all(out_dir, jobs, banner, is_demo=is_demo)
        log_event("VALIDATION_EXPORT.WRITTEN", count=sum(f.rows for f in written))
        return ValidationExportResult(
            readings=written[0],
            results=written[1],
            recorded_snapshot_ids=tuple(recorded),
            editions_without_reading=tuple(e.code for e in editions if chosen[e.code] is None),
        )


# --------------------------------------------------------------------------- helpers


def _is_small_count(
    definition: IndicatorDefinition | None, value: float | None, threshold: int
) -> bool:
    """A11: a personnel-derived COUNT in ``0 .. threshold - 1`` (zero included)."""
    return (
        definition is not None
        and definition.module is Module.PERSONNEL
        and definition.unit is UnitKind.COUNT
        and value is not None
        and 0 <= value < threshold
    )


def _make_folder(out_dir: Path) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise ServiceError(EXPORT_FAILED, "out_dir") from None


def _write_all(
    out_dir: Path,
    jobs: tuple[tuple[EntitySpec, list[_Row]], ...],
    banner: str,
    *,
    is_demo: bool,
) -> list[ExportedFile]:
    created: list[Path] = []
    written: list[ExportedFile] = []
    entity = ""
    try:
        for spec, rows in jobs:
            entity = spec.name
            path = out_dir / csv_io.export_file_name(spec, is_demo=is_demo)
            existed = path.exists()
            count = csv_io.write_entity(path, spec, rows, banner=banner)
            if not existed:
                created.append(path)
            written.append(ExportedFile(entity=spec.name, path=path, rows=count))
    except (OSError, CsvFormatError):
        for path in created:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)
        raise ServiceError(EXPORT_FAILED, entity) from None
    return written
