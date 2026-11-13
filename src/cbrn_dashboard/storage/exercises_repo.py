# SPDX-License-Identifier: GPL-3.0-or-later
"""Storage of exercise editions, their countries, evaluation metrics and results (T4.4).

Reads are plain parameterised ``SELECT`` statements. Every write goes through the repository
helpers (:func:`~cbrn_dashboard.storage.repository.insert`, ``update`` and ``delete``), so each
affected row gets its ``change_log`` row in the same transaction. This module checks no business
rule: that is the service's job (``services/exercises.py``). It also holds the one place where
rows become domain objects.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from cbrn_dashboard.domain.dates import parse_iso_date
from cbrn_dashboard.domain.exercises import Edition, EvaluationResult, ExerciseKind, Metric
from cbrn_dashboard.storage.db import DatabaseConnection, transaction
from cbrn_dashboard.storage.repository import RepositoryError, WriteContext, delete, insert, update

__all__ = [
    "EditionRow",
    "MetricRow",
    "ResultRow",
    "countries_by_edition",
    "delete_edition",
    "delete_metric",
    "delete_result",
    "edition_to_domain",
    "get_edition",
    "get_edition_by_code",
    "get_metric",
    "get_metric_by_code",
    "get_result",
    "insert_edition",
    "insert_metric",
    "list_edition_countries",
    "list_editions",
    "list_metrics",
    "list_results",
    "metric_in_use",
    "metric_to_domain",
    "result_to_domain",
    "set_countries",
    "update_edition",
    "update_metric",
    "upsert_result",
]

_EDITION = "exercise_edition"
_COUNTRY = "exercise_country"
_METRIC = "evaluation_metric"
_RESULT = "evaluation_result"

_EDITION_COLUMNS = "id, code, kind, title, start_on, end_on, participants, notes"
_METRIC_COLUMNS = (
    "id, code, label_pt_br, label_en_us, label_es_es, unit, scale_min, scale_max,"
    " higher_is_better, active"
)
_RESULT_COLUMNS = "edition_id, metric_id, value, respondents, note"


# --------------------------------------------------------------------------- rows


@dataclass(frozen=True)
class EditionRow:
    """A row of ``exercise_edition``; the dates are ISO text as stored."""

    id: int
    code: str
    kind: str
    title: str | None
    start_on: str
    end_on: str
    participants: int | None
    notes: str | None


@dataclass(frozen=True)
class MetricRow:
    """A row of ``evaluation_metric``."""

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
class ResultRow:
    """A row of ``evaluation_result``."""

    edition_id: int
    metric_id: int
    value: float
    respondents: int | None
    note: str | None


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


def _float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    msg = "Expected a numeric column."
    raise RepositoryError(msg, "UNEXPECTED_COLUMN_TYPE")


def _opt_float(value: object) -> float | None:
    return None if value is None else _float(value)


def _edition_row(row: sqlite3.Row) -> EditionRow:
    return EditionRow(
        id=_int(row["id"]),
        code=_text(row["code"]),
        kind=_text(row["kind"]),
        title=_opt_text(row["title"]),
        start_on=_text(row["start_on"]),
        end_on=_text(row["end_on"]),
        participants=_opt_int(row["participants"]),
        notes=_opt_text(row["notes"]),
    )


def _metric_row(row: sqlite3.Row) -> MetricRow:
    return MetricRow(
        id=_int(row["id"]),
        code=_text(row["code"]),
        label_pt_br=_opt_text(row["label_pt_br"]),
        label_en_us=_opt_text(row["label_en_us"]),
        label_es_es=_opt_text(row["label_es_es"]),
        unit=_opt_text(row["unit"]),
        scale_min=_opt_float(row["scale_min"]),
        scale_max=_opt_float(row["scale_max"]),
        higher_is_better=_int(row["higher_is_better"]) == 1,
        active=_int(row["active"]) == 1,
    )


def _result_row(row: sqlite3.Row) -> ResultRow:
    return ResultRow(
        edition_id=_int(row["edition_id"]),
        metric_id=_int(row["metric_id"]),
        value=_float(row["value"]),
        respondents=_opt_int(row["respondents"]),
        note=_opt_text(row["note"]),
    )


def _new_id(new_id: int | None) -> int:
    if new_id is None:
        msg = "The new row has no id."
        raise RepositoryError(msg, "INSERT_NOT_FOUND")
    return new_id


# --------------------------------------------------------------------------- editions


def list_editions(conn: DatabaseConnection) -> list[EditionRow]:
    """All editions ordered by start date and code."""
    sql = f"SELECT {_EDITION_COLUMNS} FROM exercise_edition ORDER BY start_on, code"
    return [_edition_row(row) for row in conn.execute(sql).fetchall()]


def get_edition(conn: DatabaseConnection, edition_id: int) -> EditionRow | None:
    sql = f"SELECT {_EDITION_COLUMNS} FROM exercise_edition WHERE id = ?"
    row = conn.execute(sql, (edition_id,)).fetchone()
    return None if row is None else _edition_row(row)


def get_edition_by_code(conn: DatabaseConnection, code: str) -> EditionRow | None:
    sql = f"SELECT {_EDITION_COLUMNS} FROM exercise_edition WHERE code = ?"
    row = conn.execute(sql, (code,)).fetchone()
    return None if row is None else _edition_row(row)


def insert_edition(
    ctx: WriteContext,
    *,
    code: str,
    kind: str,
    title: str | None,
    start_on: str,
    end_on: str,
    participants: int | None,
    notes: str | None,
) -> int:
    """Insert an edition and return its id."""
    values: dict[str, object] = {
        "code": code,
        "kind": kind,
        "title": title,
        "start_on": start_on,
        "end_on": end_on,
        "participants": participants,
        "notes": notes,
    }
    return _new_id(insert(ctx, _EDITION, values))


def update_edition(
    ctx: WriteContext,
    edition_id: int,
    *,
    code: str,
    kind: str,
    title: str | None,
    start_on: str,
    end_on: str,
    participants: int | None,
    notes: str | None,
) -> bool:
    """Set every editable column; returns whether anything changed (only then a log row)."""
    changes: dict[str, object] = {
        "code": code,
        "kind": kind,
        "title": title,
        "start_on": start_on,
        "end_on": end_on,
        "participants": participants,
        "notes": notes,
    }
    return update(ctx, _EDITION, edition_id, changes)


def delete_edition(ctx: WriteContext, edition_id: int) -> int:
    """Delete an edition; its countries and results go with it, each with its own log row."""
    return delete(ctx, _EDITION, edition_id)


# --------------------------------------------------------------------------- countries


def list_edition_countries(conn: DatabaseConnection, edition_id: int) -> list[str]:
    sql = "SELECT country_code FROM exercise_country WHERE edition_id = ? ORDER BY country_code"
    return [_text(row["country_code"]) for row in conn.execute(sql, (edition_id,)).fetchall()]


def countries_by_edition(conn: DatabaseConnection) -> dict[int, frozenset[str]]:
    """The country codes of every edition that has any."""
    sql = "SELECT edition_id, country_code FROM exercise_country ORDER BY edition_id, country_code"
    grouped: dict[int, set[str]] = {}
    for row in conn.execute(sql).fetchall():
        grouped.setdefault(_int(row["edition_id"]), set()).add(_text(row["country_code"]))
    return {edition_id: frozenset(codes) for edition_id, codes in grouped.items()}


def set_countries(
    ctx: WriteContext, edition_id: int, codes: Iterable[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Make ``codes`` the countries of the edition; only the differences are written.

    Returns ``(added, removed)`` as sorted tuples.
    """
    wanted = frozenset(codes)
    with transaction(ctx.conn):
        current = frozenset(list_edition_countries(ctx.conn, edition_id))
        removed = tuple(sorted(current - wanted))
        added = tuple(sorted(wanted - current))
        for code in removed:
            delete(ctx, _COUNTRY, {"edition_id": edition_id, "country_code": code})
        for code in added:
            insert(ctx, _COUNTRY, {"edition_id": edition_id, "country_code": code})
    return added, removed


# --------------------------------------------------------------------------- metrics


def list_metrics(conn: DatabaseConnection, *, include_inactive: bool = True) -> list[MetricRow]:
    """Metrics ordered by code; inactive ones are included unless excluded."""
    where = "" if include_inactive else " WHERE active = 1"
    sql = f"SELECT {_METRIC_COLUMNS} FROM evaluation_metric{where} ORDER BY code"
    return [_metric_row(row) for row in conn.execute(sql).fetchall()]


def get_metric(conn: DatabaseConnection, metric_id: int) -> MetricRow | None:
    sql = f"SELECT {_METRIC_COLUMNS} FROM evaluation_metric WHERE id = ?"
    row = conn.execute(sql, (metric_id,)).fetchone()
    return None if row is None else _metric_row(row)


def get_metric_by_code(conn: DatabaseConnection, code: str) -> MetricRow | None:
    sql = f"SELECT {_METRIC_COLUMNS} FROM evaluation_metric WHERE code = ?"
    row = conn.execute(sql, (code,)).fetchone()
    return None if row is None else _metric_row(row)


def _metric_values(
    *,
    code: str,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    unit: str | None,
    scale_min: float | None,
    scale_max: float | None,
    higher_is_better: bool,
    active: bool,
) -> dict[str, object]:
    return {
        "code": code,
        "label_pt_br": label_pt_br,
        "label_en_us": label_en_us,
        "label_es_es": label_es_es,
        "unit": unit,
        "scale_min": scale_min,
        "scale_max": scale_max,
        "higher_is_better": 1 if higher_is_better else 0,
        "active": 1 if active else 0,
    }


def insert_metric(
    ctx: WriteContext,
    *,
    code: str,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    unit: str | None,
    scale_min: float | None,
    scale_max: float | None,
    higher_is_better: bool,
    active: bool,
) -> int:
    """Insert a metric and return its id."""
    values = _metric_values(
        code=code,
        label_pt_br=label_pt_br,
        label_en_us=label_en_us,
        label_es_es=label_es_es,
        unit=unit,
        scale_min=scale_min,
        scale_max=scale_max,
        higher_is_better=higher_is_better,
        active=active,
    )
    return _new_id(insert(ctx, _METRIC, values))


def update_metric(
    ctx: WriteContext,
    metric_id: int,
    *,
    code: str,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    unit: str | None,
    scale_min: float | None,
    scale_max: float | None,
    higher_is_better: bool,
    active: bool,
) -> bool:
    """Set every editable column; returns whether anything changed."""
    changes = _metric_values(
        code=code,
        label_pt_br=label_pt_br,
        label_en_us=label_en_us,
        label_es_es=label_es_es,
        unit=unit,
        scale_min=scale_min,
        scale_max=scale_max,
        higher_is_better=higher_is_better,
        active=active,
    )
    return update(ctx, _METRIC, metric_id, changes)


def delete_metric(ctx: WriteContext, metric_id: int) -> int:
    """Delete a metric; the database refuses (``ROW_IN_USE``) while results use it."""
    return delete(ctx, _METRIC, metric_id)


def metric_in_use(conn: DatabaseConnection, metric_id: int) -> bool:
    """Whether any result uses the metric."""
    sql = "SELECT 1 FROM evaluation_result WHERE metric_id = ? LIMIT 1"
    return conn.execute(sql, (metric_id,)).fetchone() is not None


# --------------------------------------------------------------------------- results


def list_results(conn: DatabaseConnection, edition_id: int | None = None) -> list[ResultRow]:
    """The results of one edition, or of all editions, ordered by edition id and metric id."""
    if edition_id is None:
        sql = f"SELECT {_RESULT_COLUMNS} FROM evaluation_result ORDER BY edition_id, metric_id"
        rows = conn.execute(sql).fetchall()
    else:
        sql = (
            f"SELECT {_RESULT_COLUMNS} FROM evaluation_result WHERE edition_id = ?"
            " ORDER BY metric_id"
        )
        rows = conn.execute(sql, (edition_id,)).fetchall()
    return [_result_row(row) for row in rows]


def get_result(conn: DatabaseConnection, edition_id: int, metric_id: int) -> ResultRow | None:
    sql = f"SELECT {_RESULT_COLUMNS} FROM evaluation_result WHERE edition_id = ? AND metric_id = ?"
    row = conn.execute(sql, (edition_id, metric_id)).fetchone()
    return None if row is None else _result_row(row)


def upsert_result(
    ctx: WriteContext,
    edition_id: int,
    metric_id: int,
    *,
    value: float,
    respondents: int | None,
    note: str | None,
) -> bool:
    """Insert the result or update the existing one; returns whether anything was written."""
    key: dict[str, object] = {"edition_id": edition_id, "metric_id": metric_id}
    with transaction(ctx.conn):
        if get_result(ctx.conn, edition_id, metric_id) is None:
            insert(ctx, _RESULT, {**key, "value": value, "respondents": respondents, "note": note})
            return True
        changes: dict[str, object] = {"value": value, "respondents": respondents, "note": note}
        return update(ctx, _RESULT, key, changes)


def delete_result(ctx: WriteContext, edition_id: int, metric_id: int) -> int:
    """Delete one result (``RowNotFoundError`` when there is none)."""
    return delete(ctx, _RESULT, {"edition_id": edition_id, "metric_id": metric_id})


# --------------------------------------------------------------------------- domain converters


def edition_to_domain(row: EditionRow, countries: frozenset[str]) -> Edition:
    """The domain edition for a row and its country codes."""
    return Edition(
        code=row.code,
        kind=ExerciseKind(row.kind),
        start_on=parse_iso_date(row.start_on),
        end_on=parse_iso_date(row.end_on),
        participants=row.participants,
        countries=countries,
    )


def metric_to_domain(row: MetricRow) -> Metric:
    """The domain metric for a row."""
    return Metric(
        code=row.code,
        unit=row.unit,
        scale_min=row.scale_min,
        scale_max=row.scale_max,
        higher_is_better=row.higher_is_better,
    )


def result_to_domain(
    row: ResultRow, edition_codes: Mapping[int, str], metric_codes: Mapping[int, str]
) -> EvaluationResult:
    """The domain result; an unknown edition or metric id becomes ``#<id>`` (an orphan)."""
    return EvaluationResult(
        edition_code=edition_codes.get(row.edition_id, f"#{row.edition_id}"),
        metric_code=metric_codes.get(row.metric_id, f"#{row.metric_id}"),
        value=row.value,
        respondents=row.respondents,
    )
