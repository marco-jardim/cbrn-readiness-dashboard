# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the exercises rules and indicators (PLAN T4.3). All data is fictitious."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from cbrn_dashboard.domain.exercises import (
    EX_DAYS_SINCE_LAST_NOTE,
    Edition,
    EvaluationResult,
    EvaluationSummaryRow,
    ExerciseKind,
    Metric,
    country_count,
    distinct_countries,
    evaluation_summary,
    history,
    indicator_definitions,
    indicator_values,
    latest_edition,
    orphan_results,
    validate_result_in_scale,
)
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorStatus,
    IndicatorValue,
    Module,
    Target,
    UnitKind,
    evaluate,
)
from cbrn_dashboard.domain.registry import build_registry

CBR = ExerciseKind.CBRAMED
EXB = ExerciseKind.EXBRAMED
OTH = ExerciseKind.OTHER


def edition(
    code: str,
    kind: ExerciseKind,
    start_on: date,
    end_on: date,
    participants: int | None,
    countries: tuple[str, ...] = (),
) -> Edition:
    return Edition(
        code=code,
        kind=kind,
        start_on=start_on,
        end_on=end_on,
        participants=participants,
        countries=frozenset(countries),
    )


CBR_1 = edition("DEMO-EX-01", CBR, date(2024, 3, 1), date(2024, 3, 5), 100, ("AA", "BB"))
CBR_2 = edition("DEMO-EX-02", CBR, date(2025, 3, 1), date(2025, 3, 5), 150, ("AA", "BB", "CC"))
EXB_1 = edition("DEMO-EX-03", EXB, date(2024, 9, 10), date(2024, 9, 12), None, ("AA", "DD"))
OTH_FUTURE = edition("DEMO-EX-04", OTH, date(2030, 1, 1), date(2030, 1, 3), 40, ("AA",))

ALL = [CBR_2, OTH_FUTURE, EXB_1, CBR_1]  # deliberately unsorted

PARTICIPANTS = "EX_LAST_PARTICIPANTS"
COUNTRIES = "EX_LAST_COUNTRIES"
DAYS = "EX_DAYS_SINCE_LAST"
KINDS = (CBR, EXB, OTH)


def by_key(values: list[IndicatorValue]) -> dict[tuple[str, str], float | None]:
    return {(v.code, v.dimension): v.value for v in values}


def dim(kind: ExerciseKind) -> str:
    return f"kind={kind.value}"


# --------------------------------------------------------------------------------------------
# History and counts
# --------------------------------------------------------------------------------------------


def test_history_sorted_by_start_then_code() -> None:
    same_start_b = edition("DEMO-EX-20", CBR, date(2024, 3, 1), date(2024, 3, 2), 1)
    same_start_a = edition("DEMO-EX-19", EXB, date(2024, 3, 1), date(2024, 3, 9), 1)
    result = history([CBR_2, same_start_b, EXB_1, same_start_a, CBR_1])
    assert [e.code for e in result] == [
        "DEMO-EX-01",
        "DEMO-EX-19",
        "DEMO-EX-20",
        "DEMO-EX-03",
        "DEMO-EX-02",
    ]


def test_history_is_stable_for_any_input_order_and_does_not_mutate() -> None:
    source = list(ALL)
    assert history(source) == history(reversed(source))
    assert source == ALL
    assert history([]) == []


@pytest.mark.parametrize(
    ("countries", "expected"),
    [((), 0), (("AA",), 1), (("AA", "BB", "CC"), 3), (("AA", "AA", "BB"), 2)],
)
def test_country_count(countries: tuple[str, ...], expected: int) -> None:
    sample = edition("DEMO-EX-90", CBR, date(2024, 1, 1), date(2024, 1, 2), 5, countries)
    assert country_count(sample) == expected


# --------------------------------------------------------------------------------------------
# Latest edition per kind
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("as_of", "expected_code"),
    [
        (date(2024, 3, 4), None),  # the day before the first one ends
        (date(2024, 3, 5), "DEMO-EX-01"),  # on end_on
        (date(2025, 3, 3), "DEMO-EX-01"),  # newer edition ongoing: ignored
        (date(2025, 3, 4), "DEMO-EX-01"),  # the day before the newer one ends
        (date(2025, 3, 5), "DEMO-EX-02"),  # on end_on of the newer one
        (date(2025, 3, 6), "DEMO-EX-02"),  # the day after
        (date(2040, 1, 1), "DEMO-EX-02"),
    ],
)
def test_latest_edition_before_and_after_a_newer_edition_ends(
    as_of: date, expected_code: str | None
) -> None:
    result = latest_edition(ALL, CBR, as_of)
    assert (None if result is None else result.code) == expected_code


def test_latest_edition_keeps_kinds_apart() -> None:
    as_of = date(2025, 6, 1)
    assert latest_edition(ALL, CBR, as_of) == CBR_2
    assert latest_edition(ALL, EXB, as_of) == EXB_1
    assert latest_edition(ALL, OTH, as_of) is None  # the only OTHER edition is in the future


def test_latest_edition_ignores_future_and_ongoing() -> None:
    ongoing = edition("DEMO-EX-05", EXB, date(2025, 5, 30), date(2025, 6, 2), 9)
    assert latest_edition([EXB_1, ongoing], EXB, date(2025, 6, 1)) == EXB_1
    assert latest_edition([EXB_1, ongoing], EXB, date(2025, 6, 2)) == ongoing
    assert latest_edition([OTH_FUTURE], OTH, date(2029, 12, 31)) is None
    assert latest_edition([], CBR, date(2025, 1, 1)) is None


def test_latest_edition_tie_breaks_on_start_then_code() -> None:
    long_one = edition("DEMO-EX-31", CBR, date(2025, 1, 1), date(2025, 1, 10), 1)
    short_one = edition("DEMO-EX-30", CBR, date(2025, 1, 8), date(2025, 1, 10), 2)
    twin = edition("DEMO-EX-32", CBR, date(2025, 1, 8), date(2025, 1, 10), 3)
    assert latest_edition([long_one, short_one], CBR, date(2025, 2, 1)) == short_one
    assert latest_edition([short_one, twin, long_one], CBR, date(2025, 2, 1)) == twin
    assert latest_edition([twin, long_one, short_one], CBR, date(2025, 2, 1)) == twin


# --------------------------------------------------------------------------------------------
# Distinct countries over a period
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2024, 1, 1), date(2024, 12, 31), {"AA", "BB", "DD"}),
        (date(2024, 3, 5), date(2024, 3, 5), {"AA", "BB"}),  # inclusive both ends
        (date(2024, 3, 6), date(2024, 9, 11), set()),  # just outside on both sides
        (date(2024, 9, 12), date(2025, 3, 4), {"AA", "DD"}),  # starts on the end_on of EXB_1
        (date(2024, 1, 1), date(2025, 12, 31), {"AA", "BB", "CC", "DD"}),
        (date(2025, 3, 6), date(2025, 12, 31), set()),
        (date(2025, 1, 1), date(2024, 1, 1), set()),  # reversed period is empty
    ],
)
def test_distinct_countries_over_period(start: date, end: date, expected: set[str]) -> None:
    assert distinct_countries(ALL, start, end) == frozenset(expected)


def test_distinct_countries_uses_end_on_not_start_on() -> None:
    # CBR_2 starts 2025-03-01 but ends 2025-03-05: a period ending 03-04 does not include it.
    assert distinct_countries([CBR_2], date(2025, 1, 1), date(2025, 3, 4)) == frozenset()
    assert distinct_countries([CBR_2], date(2025, 1, 1), date(2025, 3, 5)) == CBR_2.countries


# --------------------------------------------------------------------------------------------
# Indicator values
# --------------------------------------------------------------------------------------------


def test_indicator_values_always_one_value_per_kind_in_fixed_order() -> None:
    samples: tuple[list[Edition], list[Edition]] = ([], ALL)
    for editions in samples:
        values = indicator_values(editions, date(2025, 6, 1))
        assert [(v.code, v.dimension) for v in values] == [
            (code, dim(kind)) for code in (PARTICIPANTS, COUNTRIES, DAYS) for kind in KINDS
        ]
    assert dim(CBR) == "kind=CBRAMED"
    assert dim(EXB) == "kind=EXBRAMED"
    assert dim(OTH) == "kind=OTHER"


def test_indicator_values_without_editions_are_all_no_data() -> None:
    assert {v.value for v in indicator_values([], date(2025, 6, 1))} == {None}


def test_indicator_values_reading_for_today() -> None:
    values = by_key(indicator_values(ALL, date(2025, 3, 10)))
    assert values == {
        (PARTICIPANTS, dim(CBR)): 150.0,
        (PARTICIPANTS, dim(EXB)): None,  # participants not recorded
        (PARTICIPANTS, dim(OTH)): None,  # no finished edition
        (COUNTRIES, dim(CBR)): 3.0,
        (COUNTRIES, dim(EXB)): 2.0,  # still a value although participants are empty
        (COUNTRIES, dim(OTH)): None,
        (DAYS, dim(CBR)): 5.0,
        (DAYS, dim(EXB)): float((date(2025, 3, 10) - date(2024, 9, 12)).days),
        (DAYS, dim(OTH)): None,
    }


def test_empty_participants_is_no_data_while_countries_still_has_a_value() -> None:
    values = by_key(indicator_values([EXB_1], date(2025, 1, 1)))
    assert values[(PARTICIPANTS, dim(EXB))] is None
    assert values[(COUNTRIES, dim(EXB))] == 2.0


def test_zero_participants_is_a_value_not_no_data() -> None:
    zero = edition("DEMO-EX-06", OTH, date(2025, 1, 1), date(2025, 1, 2), 0, ("AA",))
    values = by_key(indicator_values([zero], date(2025, 1, 2)))
    assert values[(PARTICIPANTS, dim(OTH))] == 0.0


@pytest.mark.parametrize(
    ("as_of", "expected_participants", "expected_countries", "expected_days"),
    [
        (date(2025, 3, 4), 100.0, 2.0, 364.0),  # the day before the newer edition ends
        (date(2025, 3, 5), 150.0, 3.0, 0.0),  # on end_on: 0 days
        (date(2025, 3, 6), 150.0, 3.0, 1.0),  # the day after: 1 day
        (date(2025, 3, 5) + timedelta(days=30), 150.0, 3.0, 30.0),
        (date(2024, 3, 4), None, None, None),  # before any edition ended
        (date(2024, 3, 5), 100.0, 2.0, 0.0),
    ],
)
def test_cbramed_indicators_at_boundary_days(
    as_of: date,
    expected_participants: float | None,
    expected_countries: float | None,
    expected_days: float | None,
) -> None:
    values = by_key(indicator_values(ALL, as_of))
    assert values[(PARTICIPANTS, dim(CBR))] == expected_participants
    assert values[(COUNTRIES, dim(CBR))] == expected_countries
    assert values[(DAYS, dim(CBR))] == expected_days


def test_future_and_ongoing_editions_are_ignored_by_indicators() -> None:
    values = by_key(indicator_values(ALL, date(2025, 3, 3)))  # CBR_2 is ongoing
    assert values[(PARTICIPANTS, dim(CBR))] == 100.0
    assert values[(PARTICIPANTS, dim(OTH))] is None  # OTH_FUTURE is far ahead


def test_past_as_of_gives_the_reading_for_that_date_from_the_same_records() -> None:
    past = by_key(indicator_values(ALL, date(2024, 6, 1)))
    now = by_key(indicator_values(ALL, date(2025, 6, 1)))
    assert past[(PARTICIPANTS, dim(CBR))] == 100.0
    assert now[(PARTICIPANTS, dim(CBR))] == 150.0
    assert past[(DAYS, dim(CBR))] == float((date(2024, 6, 1) - date(2024, 3, 5)).days)
    assert now[(DAYS, dim(CBR))] == float((date(2025, 6, 1) - date(2025, 3, 5)).days)
    assert past[(COUNTRIES, dim(EXB))] is None  # EXB_1 had not ended yet
    assert now[(COUNTRIES, dim(EXB))] == 2.0


def test_indicator_values_do_not_depend_on_input_order() -> None:
    as_of = date(2025, 6, 1)
    assert indicator_values(ALL, as_of) == indicator_values(history(ALL), as_of)


# --------------------------------------------------------------------------------------------
# Evaluation summary
# --------------------------------------------------------------------------------------------

M_SCORE = Metric("DEMO-M-01", "SCORE", 1.0, 5.0, True)
M_DELAY = Metric("DEMO-M-02", None, 0.0, None, False)
METRICS = [M_DELAY, M_SCORE]


def test_evaluation_summary_rows_and_ordering() -> None:
    results = [
        EvaluationResult("DEMO-EX-02", "DEMO-M-02", 7.5, None),
        EvaluationResult("DEMO-EX-02", "DEMO-M-01", 4.2, 30),
        EvaluationResult("DEMO-EX-01", "DEMO-M-02", 3.0, 12),
        EvaluationResult("DEMO-EX-01", "DEMO-M-01", 3.9, 20),
    ]
    rows = evaluation_summary(ALL, METRICS, results, date(2025, 6, 1))
    assert rows == [
        EvaluationSummaryRow(
            "DEMO-EX-01",
            CBR,
            date(2024, 3, 5),
            "DEMO-M-01",
            3.9,
            20,
            1.0,
            5.0,
            "SCORE",
            Direction.HIGHER_IS_BETTER,
        ),
        EvaluationSummaryRow(
            "DEMO-EX-01",
            CBR,
            date(2024, 3, 5),
            "DEMO-M-02",
            3.0,
            12,
            0.0,
            None,
            None,
            Direction.LOWER_IS_BETTER,
        ),
        EvaluationSummaryRow(
            "DEMO-EX-02",
            CBR,
            date(2025, 3, 5),
            "DEMO-M-01",
            4.2,
            30,
            1.0,
            5.0,
            "SCORE",
            Direction.HIGHER_IS_BETTER,
        ),
        EvaluationSummaryRow(
            "DEMO-EX-02",
            CBR,
            date(2025, 3, 5),
            "DEMO-M-02",
            7.5,
            None,
            0.0,
            None,
            None,
            Direction.LOWER_IS_BETTER,
        ),
    ]


def test_evaluation_summary_orders_editions_by_start_on_across_kinds() -> None:
    results = [
        EvaluationResult("DEMO-EX-02", "DEMO-M-01", 4.0, 1),
        EvaluationResult("DEMO-EX-03", "DEMO-M-01", 3.0, 1),
        EvaluationResult("DEMO-EX-01", "DEMO-M-01", 2.0, 1),
    ]
    rows = evaluation_summary(ALL, METRICS, results, date(2025, 6, 1))
    assert [r.edition_code for r in rows] == ["DEMO-EX-01", "DEMO-EX-03", "DEMO-EX-02"]
    assert [r.kind for r in rows] == [CBR, EXB, CBR]


@pytest.mark.parametrize(
    ("as_of", "expected_codes"),
    [
        (date(2025, 3, 4), ["DEMO-EX-01"]),  # newer edition not ended yet
        (date(2025, 3, 5), ["DEMO-EX-01", "DEMO-EX-02"]),  # on end_on
        (date(2024, 3, 4), []),
    ],
)
def test_evaluation_summary_only_includes_editions_ended_by_as_of(
    as_of: date, expected_codes: list[str]
) -> None:
    results = [
        EvaluationResult("DEMO-EX-02", "DEMO-M-01", 4.0, 1),
        EvaluationResult("DEMO-EX-01", "DEMO-M-01", 3.0, 1),
        EvaluationResult("DEMO-EX-04", "DEMO-M-01", 5.0, 1),  # future edition
    ]
    rows = evaluation_summary(ALL, METRICS, results, as_of)
    assert [r.edition_code for r in rows] == expected_codes


def test_orphan_results_are_skipped_and_reported_in_input_order() -> None:
    good = EvaluationResult("DEMO-EX-01", "DEMO-M-01", 3.0, 5)
    unknown_edition = EvaluationResult("DEMO-EX-99", "DEMO-M-01", 3.0, 5)
    unknown_metric = EvaluationResult("DEMO-EX-01", "DEMO-M-99", 3.0, 5)
    both_unknown = EvaluationResult("DEMO-EX-98", "DEMO-M-98", 3.0, 5)
    future = EvaluationResult("DEMO-EX-04", "DEMO-M-01", 3.0, 5)  # known, merely not ended
    results = [unknown_edition, good, unknown_metric, future, both_unknown]
    rows = evaluation_summary(ALL, METRICS, results, date(2025, 6, 1))
    assert [(r.edition_code, r.metric_code) for r in rows] == [("DEMO-EX-01", "DEMO-M-01")]
    assert orphan_results(ALL, METRICS, results) == [unknown_edition, unknown_metric, both_unknown]
    assert orphan_results(ALL, METRICS, []) == []


# --------------------------------------------------------------------------------------------
# Scale validation
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scale_min", "scale_max", "value", "expected"),
    [
        (1.0, 5.0, 1.0, True),  # inclusive lower bound
        (1.0, 5.0, 5.0, True),  # inclusive upper bound
        (1.0, 5.0, 3.3, True),
        (1.0, 5.0, 0.99, False),
        (1.0, 5.0, 5.01, False),
        (None, 5.0, -1000.0, True),  # open minimum
        (None, 5.0, 5.0, True),
        (None, 5.0, 5.5, False),
        (0.0, None, 1e9, True),  # open maximum
        (0.0, None, 0.0, True),
        (0.0, None, -0.1, False),
        (None, None, -1e9, True),  # fully open
        (None, None, 1e9, True),
    ],
)
def test_validate_result_in_scale(
    scale_min: float | None, scale_max: float | None, value: float, expected: bool
) -> None:
    metric = Metric("DEMO-M-10", None, scale_min, scale_max, True)
    assert validate_result_in_scale(metric, value) is expected


# --------------------------------------------------------------------------------------------
# Definitions and the real registry
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "unit", "direction", "source"),
    [
        (PARTICIPANTS, UnitKind.COUNT, Direction.HIGHER_IS_BETTER, "R22"),
        (COUNTRIES, UnitKind.COUNT, Direction.HIGHER_IS_BETTER, "R22"),
        (DAYS, UnitKind.DAYS, Direction.LOWER_IS_BETTER, "R05"),
    ],
)
def test_definitions_are_registered_in_the_real_registry(
    code: str, unit: UnitKind, direction: Direction, source: str
) -> None:
    registry = build_registry()
    assert code in registry
    definition = registry.get(code)
    assert definition.module is Module.EXERCISES
    assert definition.unit is unit
    assert definition.direction is direction
    assert definition.dimension_keys == ("kind",)
    assert definition.source == source
    definition.validate_dimension(dim(CBR))


def test_provider_lists_exactly_the_three_definitions_in_order() -> None:
    assert [d.code for d in indicator_definitions()] == [PARTICIPANTS, COUNTRIES, DAYS]
    registry = build_registry()
    exercises_codes = [d.code for d in registry.by_module(Module.EXERCISES)]
    assert exercises_codes == [PARTICIPANTS, COUNTRIES, DAYS]


def test_days_since_last_is_labelled_as_a_design_proposal_pending_q1() -> None:
    assert EX_DAYS_SINCE_LAST_NOTE == "a design proposal (D), not stated in the appendix; needs Q1"
    assert indicator_definitions.__doc__ is not None
    assert "a design proposal (D), not stated in the appendix; needs Q1" in " ".join(
        indicator_definitions.__doc__.split()
    )


def test_every_indicator_is_no_target_without_targets_and_no_data_when_none() -> None:
    registry = build_registry()
    values = indicator_values(ALL, date(2025, 3, 10))
    assert any(v.value is not None for v in values)
    assert any(v.value is None for v in values)
    for value in values:
        reading = evaluate(registry.get(value.code), value, {})
        expected = IndicatorStatus.NO_DATA if value.value is None else IndicatorStatus.NO_TARGET
        assert reading.status is expected
        assert reading.dimension == value.dimension


def test_targets_are_looked_up_by_kind_dimension() -> None:
    registry = build_registry()
    definition = registry.get(DAYS)
    targets = {(DAYS, dim(CBR)): Target(warning_value=365.0, critical_value=730.0)}
    cbr_ok = IndicatorValue(code=DAYS, value=10.0, dimension=dim(CBR))
    cbr_late = IndicatorValue(code=DAYS, value=400.0, dimension=dim(CBR))
    exb_late = IndicatorValue(code=DAYS, value=400.0, dimension=dim(EXB))
    on_target = evaluate(definition, cbr_ok, targets)
    late = evaluate(definition, cbr_late, targets)
    other_kind = evaluate(definition, exb_late, targets)
    assert on_target.status is IndicatorStatus.OK
    assert late.status is IndicatorStatus.WARNING
    assert other_kind.status is IndicatorStatus.NO_TARGET
