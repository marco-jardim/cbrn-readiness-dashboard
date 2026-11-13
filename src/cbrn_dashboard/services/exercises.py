# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercises service: editions, countries, evaluation metrics and results (PLAN.md T4.4).

Qt-free. All rules about *values* (scale, "finished" editions, indicators) live in
``domain/exercises.py`` and are only called from here. The rules about *input* live here and are
reported as :class:`~cbrn_dashboard.services.errors.ServiceError` with a stable code and the name
of the offending field; the UI maps codes to texts. Every mutating method

* first refuses a read-only connection (``READ_ONLY``),
* validates everything it needs inside ONE transaction, so a refusal (or any later failure) leaves
  neither data rows nor ``change_log`` rows behind,
* writes only through ``storage/exercises_repo.py``, whose writes use the repository helpers (one
  ``change_log`` row per affected row, stamped with the injected clock and the current operator).

Metrics are user-defined list entries (section 5.1, D16): only the pt-BR label is mandatory, and the
code cannot change once a result uses the metric. Participants are counted, never identified (D20).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain import exercises as rules
from cbrn_dashboard.domain.dates import InvalidDateError, format_iso_date, parse_iso_date
from cbrn_dashboard.domain.exercises import (
    Edition,
    EvaluationResult,
    EvaluationSummaryRow,
    ExerciseKind,
    Metric,
)
from cbrn_dashboard.domain.indicators import IndicatorValue
from cbrn_dashboard.services.countries import is_known_country
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
from cbrn_dashboard.storage import exercises_repo as repo
from cbrn_dashboard.storage.db import DatabaseConnection, ReadOnlyDatabaseError, transaction
from cbrn_dashboard.storage.exercises_repo import EditionRow, MetricRow, ResultRow
from cbrn_dashboard.storage.repository import ForeignKeyError, RowNotFoundError, WriteContext

__all__ = [
    "DUPLICATE_CODE",
    "END_BEFORE_START",
    "INVALID_KIND",
    "INVALID_NUMBER",
    "METRIC_INACTIVE",
    "METRIC_IN_USE",
    "NEGATIVE_PARTICIPANTS",
    "NEGATIVE_RESPONDENTS",
    "ORPHAN_RESULT",
    "SCALE_MAX_BELOW_MIN",
    "UNKNOWN_COUNTRY",
    "VALUE_OUT_OF_SCALE",
    "DataQualityIssue",
    "EditionInput",
    "EditionView",
    "ExercisesService",
    "MetricInput",
    "MetricView",
    "ResultInput",
    "ResultView",
    "metric_label",
]

# Error codes of this service (the shared ones are in services/errors.py).
DUPLICATE_CODE = "DUPLICATE_CODE"
INVALID_KIND = "INVALID_KIND"
END_BEFORE_START = "END_BEFORE_START"
NEGATIVE_PARTICIPANTS = "NEGATIVE_PARTICIPANTS"
UNKNOWN_COUNTRY = "UNKNOWN_COUNTRY"
VALUE_OUT_OF_SCALE = "VALUE_OUT_OF_SCALE"
SCALE_MAX_BELOW_MIN = "SCALE_MAX_BELOW_MIN"
NEGATIVE_RESPONDENTS = "NEGATIVE_RESPONDENTS"
METRIC_IN_USE = "METRIC_IN_USE"
METRIC_INACTIVE = "METRIC_INACTIVE"
#: A number is NaN or infinite.
INVALID_NUMBER = "INVALID_NUMBER"

#: Data-quality code: a result whose edition or metric does not exist.
ORPHAN_RESULT = "ORPHAN_RESULT"


# --------------------------------------------------------------------------- input and output


@dataclass(frozen=True)
class EditionInput:
    """The editable fields of an edition. Dates are strict ISO text (or ``date``)."""

    code: str
    kind: str
    start_on: str | date
    end_on: str | date
    title: str | None = None
    participants: int | None = None
    notes: str | None = None
    countries: Sequence[str] = ()


@dataclass(frozen=True)
class MetricInput:
    """The editable fields of a metric; only ``label_pt_br`` is required among the labels."""

    code: str
    label_pt_br: str | None
    label_en_us: str | None = None
    label_es_es: str | None = None
    unit: str | None = None
    scale_min: float | None = None
    scale_max: float | None = None
    higher_is_better: bool = True
    active: bool = True


@dataclass(frozen=True)
class ResultInput:
    """The value of one metric for an edition."""

    metric_id: int
    value: float
    respondents: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class ResultView:
    """A stored result together with the code of its metric."""

    edition_id: int
    metric_id: int
    metric_code: str
    value: float
    respondents: int | None
    note: str | None


@dataclass(frozen=True)
class EditionView:
    """A stored edition with its (sorted) country codes and its results."""

    id: int
    code: str
    kind: ExerciseKind
    title: str | None
    start_on: date
    end_on: date
    participants: int | None
    notes: str | None
    countries: tuple[str, ...]
    results: tuple[ResultView, ...]


@dataclass(frozen=True)
class MetricView:
    """A stored metric."""

    id: int
    code: str
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    unit: str | None
    scale_min: float | None
    scale_max: float | None
    higher_is_better: bool
    active: bool


@dataclass(frozen=True)
class DataQualityIssue:
    """A data-quality finding: a stable ``code`` and the codes of the records concerned."""

    code: str
    edition_code: str
    metric_code: str


def metric_label(metric: MetricView, lang: str) -> str:
    """The label of ``metric`` in ``lang`` (``pt_BR``/``en_US``/``es_ES``; ``-`` also accepted).

    Fallback (section 6): the language asked for, then pt-BR, then en-US, then the code.
    A blank label counts as missing.
    """
    labels = {
        "pt_BR": metric.label_pt_br,
        "en_US": metric.label_en_us,
        "es_ES": metric.label_es_es,
    }
    for candidate in (lang.replace("-", "_"), "pt_BR", "en_US"):
        text = labels.get(candidate)
        if text is not None and text.strip():
            return text
    return metric.code


# --------------------------------------------------------------------------- validation helpers


@dataclass(frozen=True)
class _EditionFields:
    code: str
    kind: ExerciseKind
    title: str | None
    start_on: date
    end_on: date
    participants: int | None
    notes: str | None
    countries: tuple[str, ...]


@dataclass(frozen=True)
class _MetricFields:
    code: str
    label_pt_br: str
    label_en_us: str | None
    label_es_es: str | None
    unit: str | None
    scale_min: float | None
    scale_max: float | None
    higher_is_better: bool
    active: bool


def _clean(text: str | None) -> str | None:
    """Strip a free-text field; blank becomes ``None``."""
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def _check_code(code: str) -> str:
    require(bool(code.strip()), REQUIRED, "code")
    require(LIST_CODE_PATTERN.fullmatch(code) is not None, INVALID_CODE, "code")
    return code


def _parse_kind(value: str | None) -> ExerciseKind:
    text = "" if value is None else str(value)
    require(bool(text.strip()), REQUIRED, "kind")
    try:
        return ExerciseKind(text)
    except ValueError:
        raise ServiceError(INVALID_KIND, "kind") from None


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


def _normalise_countries(codes: Iterable[str]) -> tuple[str, ...]:
    """Upper-case, de-duplicated, sorted; every code must be in ``countries.json``."""
    normalised = sorted({code.strip().upper() for code in codes})
    for code in normalised:
        require(is_known_country(code), UNKNOWN_COUNTRY, "countries")
    return tuple(normalised)


def _finite(value: float | None, field: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    require(math.isfinite(number), INVALID_NUMBER, field)
    return number


@contextmanager
def _translated() -> Iterator[None]:
    """Turn the storage errors with a service meaning into service errors; re-raise the rest."""
    try:
        yield
    except (ReadOnlyDatabaseError, RowNotFoundError) as exc:
        raise translate_storage_error(exc) from exc


def _metric_view(row: MetricRow) -> MetricView:
    return MetricView(
        id=row.id,
        code=row.code,
        label_pt_br=row.label_pt_br,
        label_en_us=row.label_en_us,
        label_es_es=row.label_es_es,
        unit=row.unit,
        scale_min=row.scale_min,
        scale_max=row.scale_max,
        higher_is_better=row.higher_is_better,
        active=row.active,
    )


def _result_view(row: ResultRow, metric_codes: dict[int, str]) -> ResultView:
    return ResultView(
        edition_id=row.edition_id,
        metric_id=row.metric_id,
        metric_code=metric_codes.get(row.metric_id, ""),
        value=row.value,
        respondents=row.respondents,
        note=row.note,
    )


# --------------------------------------------------------------------------- the service


class ExercisesService:
    """Create, change, delete and read editions, metrics and results."""

    def __init__(
        self,
        conn: DatabaseConnection,
        clock: Clock,
        operator: Callable[[], str] = lambda: "",
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._operator = operator

    # ----- plumbing

    def _ctx(self) -> WriteContext:
        return WriteContext(self._conn, self._clock, self._operator())

    def _require_writable(self) -> None:
        require(not self._conn.read_only, READ_ONLY)

    def _edition_row(self, edition_id: int) -> EditionRow:
        row = repo.get_edition(self._conn, edition_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "edition_id")
        return row

    def _metric_row(self, metric_id: int) -> MetricRow:
        row = repo.get_metric(self._conn, metric_id)
        if row is None:
            raise ServiceError(NOT_FOUND, "metric_id")
        return row

    # ----- editions: validation

    def _validate_edition(self, data: EditionInput, edition_id: int | None) -> _EditionFields:
        code = _check_code(data.code)
        kind = _parse_kind(data.kind)
        start_on = _parse_date(data.start_on, "start_on")
        end_on = _parse_date(data.end_on, "end_on")
        require(end_on >= start_on, END_BEFORE_START, "end_on")
        participants = data.participants
        require(participants is None or participants >= 0, NEGATIVE_PARTICIPANTS, "participants")
        countries = _normalise_countries(data.countries)
        existing = repo.get_edition_by_code(self._conn, code)
        require(existing is None or existing.id == edition_id, DUPLICATE_CODE, "code")
        return _EditionFields(
            code=code,
            kind=kind,
            title=_clean(data.title),
            start_on=start_on,
            end_on=end_on,
            participants=participants,
            notes=_clean(data.notes),
            countries=countries,
        )

    # ----- editions: writes

    def create_edition(self, data: EditionInput) -> int:
        """Create an edition with its countries in one transaction; returns the new id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_edition(data, None)
            ctx = self._ctx()
            edition_id = repo.insert_edition(
                ctx,
                code=fields.code,
                kind=fields.kind.value,
                title=fields.title,
                start_on=format_iso_date(fields.start_on),
                end_on=format_iso_date(fields.end_on),
                participants=fields.participants,
                notes=fields.notes,
            )
            repo.set_countries(ctx, edition_id, fields.countries)
        return edition_id

    def update_edition(self, edition_id: int, data: EditionInput) -> None:
        """Change an edition and make ``data.countries`` its countries (only differences logged)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._edition_row(edition_id)
            fields = self._validate_edition(data, edition_id)
            ctx = self._ctx()
            repo.update_edition(
                ctx,
                edition_id,
                code=fields.code,
                kind=fields.kind.value,
                title=fields.title,
                start_on=format_iso_date(fields.start_on),
                end_on=format_iso_date(fields.end_on),
                participants=fields.participants,
                notes=fields.notes,
            )
            repo.set_countries(ctx, edition_id, fields.countries)

    def delete_edition(self, edition_id: int) -> None:
        """Delete an edition together with its countries and results (each one logged)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._edition_row(edition_id)
            repo.delete_edition(self._ctx(), edition_id)

    # ----- editions: reads

    def _edition_views(self, rows: Sequence[EditionRow]) -> list[EditionView]:
        countries = repo.countries_by_edition(self._conn)
        metric_codes = {metric.id: metric.code for metric in repo.list_metrics(self._conn)}
        results: dict[int, list[ResultView]] = {}
        for result in repo.list_results(self._conn):
            results.setdefault(result.edition_id, []).append(_result_view(result, metric_codes))
        return [
            EditionView(
                id=row.id,
                code=row.code,
                kind=ExerciseKind(row.kind),
                title=row.title,
                start_on=parse_iso_date(row.start_on),
                end_on=parse_iso_date(row.end_on),
                participants=row.participants,
                notes=row.notes,
                countries=tuple(sorted(countries.get(row.id, frozenset()))),
                results=tuple(sorted(results.get(row.id, []), key=lambda r: r.metric_code)),
            )
            for row in rows
        ]

    def list_editions(self, kind: ExerciseKind | str | None = None) -> list[EditionView]:
        """All editions by start date and code, optionally only one kind."""
        wanted = None if kind is None else _parse_kind(str(kind))
        rows = [
            row
            for row in repo.list_editions(self._conn)
            if wanted is None or row.kind == wanted.value
        ]
        return self._edition_views(rows)

    def get_edition(self, edition_id: int) -> EditionView:
        """One edition; ``NOT_FOUND`` when it does not exist."""
        return self._edition_views([self._edition_row(edition_id)])[0]

    # ----- metrics

    def _validate_metric(self, data: MetricInput, metric_id: int | None) -> _MetricFields:
        code = _check_code(data.code)
        label_pt_br = _clean(data.label_pt_br)
        if label_pt_br is None:
            raise ServiceError(LABEL_PT_BR_REQUIRED, "label_pt_br")
        scale_min = _finite(data.scale_min, "scale_min")
        scale_max = _finite(data.scale_max, "scale_max")
        require(
            scale_min is None or scale_max is None or scale_max >= scale_min,
            SCALE_MAX_BELOW_MIN,
            "scale_max",
        )
        if metric_id is not None:
            current = self._metric_row(metric_id)
            if code != current.code:
                require(not repo.metric_in_use(self._conn, metric_id), CODE_IMMUTABLE, "code")
        existing = repo.get_metric_by_code(self._conn, code)
        require(existing is None or existing.id == metric_id, DUPLICATE_CODE, "code")
        return _MetricFields(
            code=code,
            label_pt_br=label_pt_br,
            label_en_us=_clean(data.label_en_us),
            label_es_es=_clean(data.label_es_es),
            unit=_clean(data.unit),
            scale_min=scale_min,
            scale_max=scale_max,
            higher_is_better=data.higher_is_better,
            active=data.active,
        )

    def create_metric(self, data: MetricInput) -> int:
        """Create a metric; returns its id."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            fields = self._validate_metric(data, None)
            return repo.insert_metric(
                self._ctx(),
                code=fields.code,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                unit=fields.unit,
                scale_min=fields.scale_min,
                scale_max=fields.scale_max,
                higher_is_better=fields.higher_is_better,
                active=fields.active,
            )

    def update_metric(self, metric_id: int, data: MetricInput) -> None:
        """Change a metric; its code is frozen once a result uses it (``CODE_IMMUTABLE``)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._metric_row(metric_id)
            fields = self._validate_metric(data, metric_id)
            repo.update_metric(
                self._ctx(),
                metric_id,
                code=fields.code,
                label_pt_br=fields.label_pt_br,
                label_en_us=fields.label_en_us,
                label_es_es=fields.label_es_es,
                unit=fields.unit,
                scale_min=fields.scale_min,
                scale_max=fields.scale_max,
                higher_is_better=fields.higher_is_better,
                active=fields.active,
            )

    def deactivate_metric(self, metric_id: int) -> None:
        """Mark a metric inactive: it keeps its results but cannot receive new ones."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            row = self._metric_row(metric_id)
            repo.update_metric(
                self._ctx(),
                metric_id,
                code=row.code,
                label_pt_br=row.label_pt_br,
                label_en_us=row.label_en_us,
                label_es_es=row.label_es_es,
                unit=row.unit,
                scale_min=row.scale_min,
                scale_max=row.scale_max,
                higher_is_better=row.higher_is_better,
                active=False,
            )

    def delete_metric(self, metric_id: int) -> None:
        """Delete a metric that has no results (``METRIC_IN_USE`` otherwise)."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._metric_row(metric_id)
            require(not repo.metric_in_use(self._conn, metric_id), METRIC_IN_USE, "metric_id")
            try:
                repo.delete_metric(self._ctx(), metric_id)
            except ForeignKeyError:
                raise ServiceError(METRIC_IN_USE, "metric_id") from None

    def list_metrics(self, include_inactive: bool = False) -> list[MetricView]:
        """The metrics ordered by code; inactive ones only when asked for."""
        rows = repo.list_metrics(self._conn, include_inactive=include_inactive)
        return [_metric_view(row) for row in rows]

    # ----- results

    def set_result(self, edition_id: int, data: ResultInput) -> None:
        """Insert or update the value of a metric for an edition, checked against the scale."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            self._edition_row(edition_id)
            metric = self._metric_row(data.metric_id)
            value = _finite(data.value, "value")
            if value is None:
                raise ServiceError(REQUIRED, "value")
            respondents = data.respondents
            require(respondents is None or respondents >= 0, NEGATIVE_RESPONDENTS, "respondents")
            existing = repo.get_result(self._conn, edition_id, data.metric_id)
            require(metric.active or existing is not None, METRIC_INACTIVE, "metric_id")
            require(
                rules.validate_result_in_scale(repo.metric_to_domain(metric), value),
                VALUE_OUT_OF_SCALE,
                "value",
            )
            repo.upsert_result(
                self._ctx(),
                edition_id,
                data.metric_id,
                value=value,
                respondents=respondents,
                note=_clean(data.note),
            )

    def delete_result(self, edition_id: int, metric_id: int) -> None:
        """Delete one result; ``NOT_FOUND`` when there is none."""
        self._require_writable()
        with _translated(), transaction(self._conn):
            repo.delete_result(self._ctx(), edition_id, metric_id)

    def list_results(self, edition_id: int) -> list[ResultView]:
        """The results of an edition ordered by metric code."""
        self._edition_row(edition_id)
        metric_codes = {metric.id: metric.code for metric in repo.list_metrics(self._conn)}
        views = [
            _result_view(row, metric_codes) for row in repo.list_results(self._conn, edition_id)
        ]
        return sorted(views, key=lambda view: view.metric_code)

    # ----- as-of views (built with the domain functions)

    def _domain_editions(self) -> list[Edition]:
        countries = repo.countries_by_edition(self._conn)
        return [
            repo.edition_to_domain(row, countries.get(row.id, frozenset()))
            for row in repo.list_editions(self._conn)
        ]

    def _domain_metrics(self) -> list[Metric]:
        return [repo.metric_to_domain(row) for row in repo.list_metrics(self._conn)]

    def _domain_results(self) -> list[EvaluationResult]:
        edition_codes = {row.id: row.code for row in repo.list_editions(self._conn)}
        metric_codes = {row.id: row.code for row in repo.list_metrics(self._conn)}
        return [
            repo.result_to_domain(row, edition_codes, metric_codes)
            for row in repo.list_results(self._conn)
        ]

    def history(self, as_of: date | None = None) -> list[Edition]:
        """The editions in history order (domain rule); with ``as_of`` only those finished by it."""
        editions = self._domain_editions()
        if as_of is not None:
            editions = [edition for edition in editions if edition.end_on <= as_of]
        return rules.history(editions)

    def latest_edition(self, kind: ExerciseKind | str, as_of: date) -> Edition | None:
        """The latest finished edition of ``kind`` as of ``as_of`` (domain rule)."""
        return rules.latest_edition(self._domain_editions(), _parse_kind(str(kind)), as_of)

    def evaluation_summary(self, as_of: date) -> list[EvaluationSummaryRow]:
        """The results of the editions finished by ``as_of`` with scale, unit and direction."""
        return rules.evaluation_summary(
            self._domain_editions(), self._domain_metrics(), self._domain_results(), as_of
        )

    def indicator_values(self, as_of: date) -> list[IndicatorValue]:
        """The exercises indicator values as of ``as_of`` (input of ``services/indicators.py``)."""
        return rules.indicator_values(self._domain_editions(), as_of)

    def data_quality(self, as_of: date) -> list[DataQualityIssue]:
        """Findings for the data-quality flag: results whose edition or metric is unknown.

        The orphan test does not depend on the date; ``as_of`` keeps the signature uniform with the
        other as-of views.
        """
        del as_of
        orphans = rules.orphan_results(
            self._domain_editions(), self._domain_metrics(), self._domain_results()
        )
        return [
            DataQualityIssue(ORPHAN_RESULT, orphan.edition_code, orphan.metric_code)
            for orphan in orphans
        ]
