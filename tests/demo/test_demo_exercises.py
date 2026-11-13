# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo data of the exercises module (T4.6): D25 rules, determinism, the dashboard edge cases."""

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import (
    DEFAULT_SEED,
    DEMO_SEED_KEY,
    GENERATORS,
    DemoGenerator,
    is_demo_identifier,
    open_demo_database,
)
from cbrn_dashboard.demo import exercises as demo_exercises
from cbrn_dashboard.domain.exercises import ExerciseKind
from cbrn_dashboard.domain.indicators import encode_dimension
from cbrn_dashboard.paths import DATABASE_FILE_NAME
from cbrn_dashboard.services.countries import country_codes
from cbrn_dashboard.services.exercises import EditionView, ExercisesService
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")
TODAY = date(2026, 3, 5)
LATER_CLOCK = FixedClock.at("2027-03-05T12:00:00Z")
LATER_TODAY = date(2027, 3, 5)

GENERATOR = DemoGenerator("exercises", demo_exercises.generate)

type Rows = list[tuple[object, ...]]
type Opener = Callable[..., DatabaseConnection]

TABLE_QUERIES = {
    "exercise_edition": (
        "SELECT id, code, kind, title, start_on, end_on, participants, notes"
        " FROM exercise_edition ORDER BY id"
    ),
    "exercise_country": (
        "SELECT edition_id, country_code FROM exercise_country ORDER BY edition_id, country_code"
    ),
    "evaluation_metric": (
        "SELECT id, code, label_pt_br, label_en_us, label_es_es, unit, scale_min, scale_max,"
        " higher_is_better, active FROM evaluation_metric ORDER BY id"
    ),
    "evaluation_result": (
        "SELECT edition_id, metric_id, value, respondents, note FROM evaluation_result"
        " ORDER BY edition_id, metric_id"
    ),
}


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def opener(tmp_path: Path) -> Iterator[Opener]:
    """Opens demo databases (each under its own folder) and closes them all at teardown."""
    opened: list[DatabaseConnection] = []
    counter = 0

    def open_one(
        *,
        seed: int = DEFAULT_SEED,
        clock: FixedClock = CLOCK,
        data_dir: Path | None = None,
        only_exercises: bool = True,
    ) -> DatabaseConnection:
        nonlocal counter
        counter += 1
        folder = data_dir if data_dir is not None else tmp_path / f"data{counter}"
        conn = open_demo_database(
            folder, clock, seed=seed, generators=[GENERATOR] if only_exercises else None
        )
        opened.append(conn)
        return conn

    yield open_one
    for conn in opened:
        conn.close()


def _rows(conn: DatabaseConnection, sql: str, params: tuple[object, ...] = ()) -> Rows:
    return [tuple(row) for row in conn.execute(sql, params).fetchall()]


def _table(conn: DatabaseConnection, name: str) -> Rows:
    return _rows(conn, TABLE_QUERIES[name])


def _editions(conn: DatabaseConnection, clock: FixedClock = CLOCK) -> list[EditionView]:
    return ExercisesService(conn, clock).list_editions()


def _no_participants(editions: list[EditionView]) -> list[EditionView]:
    return [edition for edition in editions if edition.participants is None]


# --------------------------------------------------------------------------- editions


def test_every_kind_has_several_past_editions_with_demo_codes_and_titles(
    opener: Opener,
) -> None:
    editions = _editions(opener())
    assert {edition.kind for edition in editions} == set(ExerciseKind)
    for kind in ExerciseKind:
        past = [e for e in editions if e.kind is kind and e.end_on <= TODAY]
        assert len(past) >= 2, kind
    codes = [edition.code for edition in editions]
    assert sorted(codes) == [f"DEMO-EX-{number:02d}" for number in range(1, len(codes) + 1)]
    titles = [edition.title for edition in editions]
    assert all(title is not None and title.startswith("DEMO") for title in titles)


def test_past_editions_are_spread_over_about_four_years(opener: Opener) -> None:
    past = [e for e in _editions(opener()) if e.end_on <= TODAY]
    oldest = min(edition.start_on for edition in past)
    assert 3 * 365 <= (TODAY - oldest).days <= 5 * 365
    assert max(edition.end_on for edition in past) <= TODAY


def test_one_past_edition_has_no_participant_count_and_is_the_latest_of_its_kind(
    opener: Opener,
) -> None:
    conn = opener()
    editions = _editions(conn)
    missing = _no_participants(editions)
    assert len(missing) == 1
    edition = missing[0]
    assert edition.end_on <= TODAY
    assert edition.countries  # the country count is still known

    service = ExercisesService(conn, CLOCK)
    latest = service.latest_edition(edition.kind, TODAY)
    assert latest is not None
    assert latest.code == edition.code
    assert latest.participants is None

    values = {(v.code, v.dimension): v.value for v in service.indicator_values(TODAY)}
    dimension = encode_dimension({"kind": edition.kind.value})
    assert values[("EX_LAST_PARTICIPANTS", dimension)] is None
    assert values[("EX_LAST_COUNTRIES", dimension)] == float(len(edition.countries))
    for kind in ExerciseKind:
        if kind is not edition.kind:
            other = encode_dimension({"kind": kind.value})
            assert values[("EX_LAST_PARTICIPANTS", other)] is not None
            assert values[("EX_LAST_COUNTRIES", other)] is not None


def test_exactly_one_future_edition_without_results(opener: Opener) -> None:
    editions = _editions(opener())
    future = [edition for edition in editions if edition.start_on > TODAY]
    assert len(future) == 1
    assert future[0].end_on >= future[0].start_on
    assert future[0].results == ()
    # every other edition has ended
    assert all(edition.end_on <= TODAY for edition in editions if edition not in future)


def test_participants_and_countries_come_from_the_seed_list(opener: Opener) -> None:
    editions = _editions(opener())
    known = country_codes()
    for edition in editions:
        assert 4 <= len(edition.countries) <= 14
        assert set(edition.countries) <= known
        assert edition.participants is None or edition.participants > 0
    assert len({edition.countries for edition in editions}) > 1
    countries = _table(opener(), "exercise_country")
    assert all(row[1] in known for row in countries)


# --------------------------------------------------------------------------- metrics and results


def test_two_demo_metrics_with_labels_units_scales_and_opposite_directions(
    opener: Opener,
) -> None:
    metrics = ExercisesService(opener(), CLOCK).list_metrics(include_inactive=True)
    assert [metric.code for metric in metrics] == ["DEMO-M1", "DEMO-M2"]
    for metric in metrics:
        for label in (metric.label_pt_br, metric.label_en_us, metric.label_es_es):
            assert label is not None
            assert label.startswith("DEMO")
        assert metric.unit
        assert metric.scale_min is not None
        assert metric.scale_max is not None
        assert metric.active
    assert metrics[0].unit != metrics[1].unit
    first, second = metrics
    assert (first.scale_min, first.scale_max) != (second.scale_min, second.scale_max)
    assert {metric.higher_is_better for metric in metrics} == {True, False}


def test_every_past_edition_has_both_results_inside_the_scale(opener: Opener) -> None:
    conn = opener()
    service = ExercisesService(conn, CLOCK)
    scales = {m.code: (m.scale_min, m.scale_max) for m in service.list_metrics()}
    past = [e for e in service.list_editions() if e.end_on <= TODAY]
    assert past
    for edition in past:
        assert [result.metric_code for result in edition.results] == ["DEMO-M1", "DEMO-M2"]
        for result in edition.results:
            low, high = scales[result.metric_code]
            assert low is not None
            assert high is not None
            assert low <= result.value <= high
    assert len(_table(conn, "evaluation_result")) == 2 * len(past)
    summary = service.evaluation_summary(TODAY)
    assert len(summary) == 2 * len(past)
    assert service.data_quality(TODAY) == []


# --------------------------------------------------------------------------- identifiers


def test_every_identifier_written_by_the_generator_starts_with_demo(opener: Opener) -> None:
    conn = opener()
    editions = _rows(conn, "SELECT code, title FROM exercise_edition")
    metrics = _rows(
        conn, "SELECT code, label_pt_br, label_en_us, label_es_es FROM evaluation_metric"
    )
    assert editions
    assert metrics
    for row in (*editions, *metrics):
        for text in row:
            assert isinstance(text, str)
            assert is_demo_identifier(text), text


# --------------------------------------------------------------------------- determinism


def test_same_seed_and_clock_give_identical_rows_in_all_four_tables(opener: Opener) -> None:
    first = opener(seed=5)
    second = opener(seed=5)
    for name in TABLE_QUERIES:
        assert _table(first, name) == _table(second, name), name
        assert _table(first, name), name


def test_default_seed_is_deterministic_too(opener: Opener) -> None:
    first = opener()
    second = opener()
    assert _table(first, "exercise_edition") == _table(second, "exercise_edition")
    assert app_meta.get(first, DEMO_SEED_KEY) == str(DEFAULT_SEED)


def test_a_different_seed_gives_different_participant_numbers(opener: Opener) -> None:
    first = [e.participants for e in _editions(opener(seed=1))]
    second = [e.participants for e in _editions(opener(seed=2))]
    assert first != second
    assert len(first) == len(second)
    countries_first = _table(opener(seed=1), "exercise_country")
    countries_second = _table(opener(seed=2), "exercise_country")
    assert countries_first != countries_second


def test_a_different_clock_date_shifts_the_dates_relative_to_the_clock(opener: Opener) -> None:
    now = _editions(opener())
    later = _editions(opener(clock=LATER_CLOCK), LATER_CLOCK)
    assert [e.code for e in now] == [e.code for e in later]
    for before, after in zip(now, later, strict=True):
        # one year later (365 or 366 days, depending on a leap day in between)
        assert (after.start_on - before.start_on).days in {365, 366}
        assert (after.end_on - before.end_on).days in {365, 366}
        # the numbers do not depend on the clock
        assert after.participants == before.participants
        assert after.countries == before.countries
        assert [r.value for r in after.results] == [r.value for r in before.results]
        # past stays past and future stays future, relative to each clock's date
        assert (before.end_on <= TODAY) == (after.end_on <= LATER_TODAY)
        assert (before.start_on > TODAY) == (after.start_on > LATER_TODAY)


# --------------------------------------------------------------------------- framework


def test_default_registry_includes_the_exercises_generator_and_seeds_once(
    tmp_path: Path, opener: Opener
) -> None:
    assert "exercises" in [generator.name for generator in GENERATORS]
    folder = tmp_path / "registry"
    conn = opener(data_dir=folder, only_exercises=False)
    editions = _table(conn, "exercise_edition")
    assert len(editions) == len(_editions(conn))
    assert len(editions) >= 6
    assert len(_table(conn, "evaluation_metric")) == 2
    results = _table(conn, "evaluation_result")
    conn.close()

    again = opener(data_dir=folder, only_exercises=False)
    assert _table(again, "exercise_edition") == editions
    assert len(_table(again, "evaluation_metric")) == 2
    assert _table(again, "evaluation_result") == results


def test_the_default_registry_gives_the_same_exercises_as_the_generator_alone(
    opener: Opener,
) -> None:
    alone = opener()
    registered = opener(only_exercises=False)
    for name in TABLE_QUERIES:
        assert _table(alone, name) == _table(registered, name), name


def test_the_change_log_carries_the_demo_operator(opener: Opener) -> None:
    conn = opener()
    operators = _rows(conn, "SELECT DISTINCT operator FROM change_log")
    assert operators == [("DEMO",)]
    entities = {row[0] for row in _rows(conn, "SELECT DISTINCT entity FROM change_log")}
    assert len(entities) >= 3
    editions = len(_table(conn, "exercise_edition"))
    logged = _rows(
        conn,
        "SELECT count(*) FROM change_log WHERE entity = ? AND action = 'insert'",
        ("exercise_edition",),
    )
    assert logged == [(editions,)]


def test_only_the_demo_database_is_created(tmp_path: Path, opener: Opener) -> None:
    opener(data_dir=tmp_path)
    assert not (tmp_path / DATABASE_FILE_NAME).exists()
    assert {entry.name for entry in tmp_path.iterdir()} == {"demo"}
    assert list(tmp_path.rglob("*.sqlite3")) == [tmp_path / "demo" / "demo.sqlite3"]
