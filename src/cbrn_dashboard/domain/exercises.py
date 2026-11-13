# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercises rules and indicators (PLAN T4.3, §5.4, A07, A13, D20).

Pure domain code: no Qt, no I/O, no clock. Every function that depends on "today" takes the as-of
date explicitly, so a past as-of date gives the reading computed from the records as known now for
that date: the same data with an earlier ``as_of`` simply sees fewer finished editions.

Only codes and numbers are produced here; the UI maps the codes to labels. Participants are counts
only (D20). Country codes are ISO 3166-1 alpha-2 strings validated by the service layer (T4.4).

Rules
-----
* An edition counts as "finished" for an as-of date ``d`` when ``end_on <= d``. Ongoing and future
  editions (``end_on > d``) are ignored everywhere.
* The latest edition of a kind is the finished one with the greatest ``end_on`` (ties: greater
  ``start_on``, then greater ``code``).
* Indicators carry the dimension ``kind=<CBRAMED|EXBRAMED|OTHER>``; there is always one value per
  kind, in that fixed order, and ``None`` (No data) when it cannot be computed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from cbrn_dashboard.domain.dates import days_between
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorDefinition,
    IndicatorValue,
    Module,
    UnitKind,
    encode_dimension,
)

EX_DAYS_SINCE_LAST_NOTE = "a design proposal (D), not stated in the appendix; needs Q1"
"""Label of ``EX_DAYS_SINCE_LAST`` (PLAN §5.4): shown wherever the indicator is documented."""

_DIMENSION_KEY = "kind"


# --------------------------------------------------------------------------------------------
# Data objects
# --------------------------------------------------------------------------------------------


class ExerciseKind(StrEnum):
    """Kind of exercise (A13); the stored value is the stable code."""

    CBRAMED = "CBRAMED"
    EXBRAMED = "EXBRAMED"
    OTHER = "OTHER"


@dataclass(frozen=True)
class Edition:
    """One edition of an exercise; ``participants`` is ``None`` when not recorded."""

    code: str
    kind: ExerciseKind
    start_on: date
    end_on: date
    participants: int | None
    countries: frozenset[str]


@dataclass(frozen=True)
class Metric:
    """An evaluation metric (A07); a missing scale bound is open."""

    code: str
    unit: str | None
    scale_min: float | None
    scale_max: float | None
    higher_is_better: bool


@dataclass(frozen=True)
class EvaluationResult:
    """The value of one metric for one edition."""

    edition_code: str
    metric_code: str
    value: float
    respondents: int | None


@dataclass(frozen=True)
class EvaluationSummaryRow:
    """One (edition, metric) result together with the metric's scale, unit and direction."""

    edition_code: str
    kind: ExerciseKind
    end_on: date
    metric_code: str
    value: float
    respondents: int | None
    scale_min: float | None
    scale_max: float | None
    unit: str | None
    direction: Direction


# --------------------------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------------------------


def history(editions: Iterable[Edition]) -> list[Edition]:
    """All editions sorted by ``start_on`` and then ``code`` (deterministic)."""
    return sorted(editions, key=lambda edition: (edition.start_on, edition.code))


def country_count(edition: Edition) -> int:
    """Number of distinct countries represented in ``edition``."""
    return len(edition.countries)


def latest_edition(editions: Iterable[Edition], kind: ExerciseKind, as_of: date) -> Edition | None:
    """Latest edition of ``kind`` with ``end_on <= as_of``; ``None`` when there is none.

    Ties on ``end_on`` are broken by ``start_on`` and then ``code``.
    """
    finished = [e for e in editions if e.kind is kind and e.end_on <= as_of]
    if not finished:
        return None
    return max(finished, key=lambda e: (e.end_on, e.start_on, e.code))


def distinct_countries(editions: Iterable[Edition], start: date, end: date) -> frozenset[str]:
    """Union of the countries of the editions that ended within ``[start, end]`` (inclusive)."""
    result: set[str] = set()
    for edition in editions:
        if start <= edition.end_on <= end:
            result.update(edition.countries)
    return frozenset(result)


def validate_result_in_scale(metric: Metric, value: float) -> bool:
    """Whether ``value`` lies in the metric's scale (inclusive bounds, a missing bound is open).

    The service turns ``False`` into the error code ``VALUE_OUT_OF_SCALE``.
    """
    if metric.scale_min is not None and value < metric.scale_min:
        return False
    return not (metric.scale_max is not None and value > metric.scale_max)


def evaluation_summary(
    editions: Iterable[Edition],
    metrics: Iterable[Metric],
    results: Iterable[EvaluationResult],
    as_of: date,
) -> list[EvaluationSummaryRow]:
    """One row per result of an edition that ended on or before ``as_of``.

    Rows are sorted by edition ``start_on``, edition code and metric code. A result whose edition
    or metric is unknown is skipped; see :func:`orphan_results`.
    """
    editions_by_code = {e.code: e for e in editions}
    metrics_by_code = {m.code: m for m in metrics}
    keyed: list[tuple[tuple[date, str, str], EvaluationSummaryRow]] = []
    for result in results:
        edition = editions_by_code.get(result.edition_code)
        metric = metrics_by_code.get(result.metric_code)
        if edition is None or metric is None or edition.end_on > as_of:
            continue
        row = EvaluationSummaryRow(
            edition_code=edition.code,
            kind=edition.kind,
            end_on=edition.end_on,
            metric_code=metric.code,
            value=result.value,
            respondents=result.respondents,
            scale_min=metric.scale_min,
            scale_max=metric.scale_max,
            unit=metric.unit,
            direction=(
                Direction.HIGHER_IS_BETTER if metric.higher_is_better else Direction.LOWER_IS_BETTER
            ),
        )
        keyed.append(((edition.start_on, edition.code, metric.code), row))
    keyed.sort(key=lambda item: item[0])
    return [row for _, row in keyed]


def orphan_results(
    editions: Iterable[Edition],
    metrics: Iterable[Metric],
    results: Iterable[EvaluationResult],
) -> list[EvaluationResult]:
    """Results whose edition or metric is unknown, in input order (for a data-quality flag)."""
    edition_codes = {e.code for e in editions}
    metric_codes = {m.code for m in metrics}
    return [
        r
        for r in results
        if r.edition_code not in edition_codes or r.metric_code not in metric_codes
    ]


# --------------------------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------------------------


def indicator_definitions() -> tuple[IndicatorDefinition, ...]:
    """The exercises indicators (PLAN §5.4), all with dimension ``kind``.

    ``EX_DAYS_SINCE_LAST`` is a design proposal (D), not stated in the appendix; needs Q1
    (see :data:`EX_DAYS_SINCE_LAST_NOTE`).
    """
    return (
        IndicatorDefinition(
            code="EX_LAST_PARTICIPANTS",
            module=Module.EXERCISES,
            unit=UnitKind.COUNT,
            direction=Direction.HIGHER_IS_BETTER,
            dimension_keys=(_DIMENSION_KEY,),
            source="R22",
        ),
        IndicatorDefinition(
            code="EX_LAST_COUNTRIES",
            module=Module.EXERCISES,
            unit=UnitKind.COUNT,
            direction=Direction.HIGHER_IS_BETTER,
            dimension_keys=(_DIMENSION_KEY,),
            source="R22",
        ),
        IndicatorDefinition(
            code="EX_DAYS_SINCE_LAST",
            module=Module.EXERCISES,
            unit=UnitKind.DAYS,
            direction=Direction.LOWER_IS_BETTER,
            dimension_keys=(_DIMENSION_KEY,),
            source="R05",
        ),
    )


def indicator_values(editions: Iterable[Edition], as_of: date) -> list[IndicatorValue]:
    """Values of the three indicators for every kind, as of ``as_of``.

    Order: ``EX_LAST_PARTICIPANTS``, ``EX_LAST_COUNTRIES``, ``EX_DAYS_SINCE_LAST``; within each,
    CBRAMED, EXBRAMED, OTHER. A value is ``None`` (No data) when it cannot be computed.
    """
    pending = list(editions)
    latest = {kind: latest_edition(pending, kind, as_of) for kind in ExerciseKind}

    def dimension(kind: ExerciseKind) -> str:
        return encode_dimension({_DIMENSION_KEY: kind.value})

    values: list[IndicatorValue] = []
    for kind in ExerciseKind:
        edition = latest[kind]
        participants = None if edition is None else edition.participants
        values.append(
            IndicatorValue(
                code="EX_LAST_PARTICIPANTS",
                value=None if participants is None else float(participants),
                dimension=dimension(kind),
            )
        )
    for kind in ExerciseKind:
        edition = latest[kind]
        values.append(
            IndicatorValue(
                code="EX_LAST_COUNTRIES",
                value=None if edition is None else float(country_count(edition)),
                dimension=dimension(kind),
            )
        )
    for kind in ExerciseKind:
        edition = latest[kind]
        values.append(
            IndicatorValue(
                code="EX_DAYS_SINCE_LAST",
                value=None if edition is None else float(days_between(edition.end_on, as_of)),
                dimension=dimension(kind),
            )
        )
    return values
