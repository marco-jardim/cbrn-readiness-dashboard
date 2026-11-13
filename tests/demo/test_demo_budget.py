# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo data of the budget module (T5.5): D25 rules, D15 currencies, the dashboard edge cases."""

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from cbrn_dashboard import demo
from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.demo import (
    DEFAULT_SEED,
    DEMO_SEED_KEY,
    GENERATORS,
    DemoGenerator,
    is_demo_identifier,
    open_demo_database,
)
from cbrn_dashboard.demo import budget as demo_budget
from cbrn_dashboard.domain import budget as rules
from cbrn_dashboard.domain.indicators import encode_dimension
from cbrn_dashboard.paths import DATABASE_FILE_NAME
from cbrn_dashboard.services.budget import BudgetService, EntryView
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")
TODAY = date(2026, 3, 5)
YEAR_END = date(2026, 12, 31)
LATER_CLOCK = FixedClock.at("2027-03-05T12:00:00Z")

GENERATOR = DemoGenerator("budget", demo_budget.generate)

type Rows = list[tuple[object, ...]]
type Opener = Callable[..., DatabaseConnection]

TABLE_QUERIES = {
    "funding_source": (
        "SELECT id, code, built_in, label_pt_br, label_en_us, label_es_es, active"
        " FROM funding_source ORDER BY id"
    ),
    "budget_entry": (
        "SELECT id, fiscal_year, source_id, currency, allocated_minor, description, notes"
        " FROM budget_entry ORDER BY id"
    ),
    "budget_execution": (
        "SELECT id, entry_id, executed_on, amount_minor, note FROM budget_execution ORDER BY id"
    ),
}


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def opener(tmp_path: Path) -> Iterator[Opener]:
    """Builds migrated databases seeded with ONLY the budget generator; closes them at teardown."""
    opened: list[DatabaseConnection] = []
    counter = 0

    def open_one(*, seed: int = DEFAULT_SEED, clock: FixedClock = CLOCK) -> DatabaseConnection:
        nonlocal counter
        counter += 1
        folder = tmp_path / f"data{counter}"
        folder.mkdir()
        conn = open_and_migrate(
            folder / "budget.sqlite3", data_dir=folder, identity=DatabaseIdentity.DEMO
        )
        opened.append(conn)
        app_meta.initialise(conn, is_demo=True, created_with="0.0.1")  # generate() needs the flag
        assert demo.generate(conn, clock, seed=seed, generators=[GENERATOR]) is True
        return conn

    yield open_one
    for conn in opened:
        conn.close()


def _rows(conn: DatabaseConnection, sql: str, params: tuple[object, ...] = ()) -> Rows:
    return [tuple(row) for row in conn.execute(sql, params).fetchall()]


def _table(conn: DatabaseConnection, name: str) -> Rows:
    return _rows(conn, TABLE_QUERIES[name])


def _entries(conn: DatabaseConnection, clock: FixedClock = CLOCK) -> list[EntryView]:
    return BudgetService(conn, clock).list_entries()


def _dimension(source: str, currency: str) -> str:
    return encode_dimension({"currency": currency, "source": source})


# --------------------------------------------------------------------------- entries and years


def test_entries_exist_for_four_fiscal_years_for_both_built_in_sources(opener: Opener) -> None:
    entries = _entries(opener())
    for source in ("DIRSA", "OPCW_TRUST_FUND"):
        years = {entry.fiscal_year for entry in entries if entry.source_code == source}
        assert years == {2023, 2024, 2025, 2026}
    demo_years = {
        entry.fiscal_year for entry in entries if entry.source_code == demo_budget.DEMO_SOURCE_CODE
    }
    assert demo_years == {2023, 2024, 2025, 2026}


def test_each_entry_has_several_dated_rows_spread_over_its_year(opener: Opener) -> None:
    conn = opener()
    entries = _entries(conn)
    assert entries
    for entry in entries:
        dates = {execution.executed_on for execution in entry.executions}
        assert len(dates) >= 3
        assert len(dates) == len(entry.executions)
    for entry in entries:
        if entry.fiscal_year == 2026:
            continue
        dates = sorted(execution.executed_on for execution in entry.executions)
        assert 4 <= len(dates) <= 8
        assert all(day.year == entry.fiscal_year for day in dates)
        assert (dates[-1] - dates[0]).days >= 7  # spread, not bunched on one day
    # No row of the demo data is dated outside the fiscal year of its entry.
    assert BudgetService(conn, CLOCK).data_quality(TODAY) == []


def test_exactly_one_user_defined_source_with_a_demo_code_and_labels(opener: Opener) -> None:
    service = BudgetService(opener(), CLOCK)
    user_sources = [s for s in service.list_sources(include_inactive=True) if not s.built_in]
    assert len(user_sources) == 1
    source = user_sources[0]
    assert source.code.startswith("DEMO")
    assert is_demo_identifier(source.code)
    for label in (source.label_pt_br, source.label_en_us, source.label_es_es):
        assert label is not None
        assert label.startswith("DEMO")
    assert {s.code for s in service.list_sources(include_inactive=True) if s.built_in} == {
        "DIRSA",
        "OPCW_TRUST_FUND",
    }


def test_every_description_starts_with_demo(opener: Opener) -> None:
    entries = _entries(opener())
    assert all(entry.description.startswith("DEMO") for entry in entries)
    assert all(
        execution.note is not None and execution.note.startswith("DEMO")
        for entry in entries
        for execution in entry.executions
    )


# --------------------------------------------------------------------------- currencies (D15)


def test_a_second_currency_is_kept_apart_by_the_totals(opener: Opener) -> None:
    service = BudgetService(opener(), CLOCK)
    assert {entry.currency for entry in service.list_entries()} == {"BRL", "USD"}
    rows = [
        total
        for total in service.totals(YEAR_END)
        if total.source_code == "OPCW_TRUST_FUND" and total.fiscal_year == 2025
    ]
    assert sorted(total.currency for total in rows) == ["BRL", "USD"]
    by_currency = {total.currency: total for total in rows}
    brl_entries = [
        e
        for e in service.list_entries(2025)
        if e.source_code == "OPCW_TRUST_FUND" and e.currency == "BRL"
    ]
    assert by_currency["BRL"].allocated_minor == sum(e.allocated_minor or 0 for e in brl_entries)


# --------------------------------------------------------------------------- the "No data" entry


def test_exactly_one_entry_without_an_allocation_and_its_group_is_no_data(opener: Opener) -> None:
    service = BudgetService(opener(), CLOCK)
    unallocated = [entry for entry in service.list_entries() if entry.allocated_minor is None]
    assert len(unallocated) == 1
    entry = unallocated[0]
    assert entry.fiscal_year == 2026
    assert len(entry.executions) >= 3
    group = [
        other
        for other in service.list_entries(entry.fiscal_year)
        if other.source_code == entry.source_code and other.currency == entry.currency
    ]
    assert group == [entry]  # alone in its (year, source, currency) group

    values = {value.dimension: value.value for value in service.indicator_values(TODAY)}
    assert values[_dimension(entry.source_code, entry.currency)] is None
    others = [value for key, value in values.items() if key != _dimension("DEMO-SRC-A", "USD")]
    assert others
    assert all(value is not None for value in others)


# --------------------------------------------------------------------------- plausibility


def test_executed_totals_never_exceed_the_allocation(opener: Opener) -> None:
    for entry in _entries(opener()):
        if entry.allocated_minor is None:
            continue
        executed = sum(execution.amount_minor for execution in entry.executions)
        assert executed <= entry.allocated_minor


def test_executed_rates_vary_between_groups(opener: Opener) -> None:
    service = BudgetService(opener(), CLOCK)
    rates = [value.value for value in service.indicator_values(TODAY) if value.value is not None]
    assert all(0.0 <= rate <= 1.0 for rate in rates)
    # Mid-year pro-rating at the clock date is about 17.5 %: some groups are below, some above.
    assert min(rates) < rules.elapsed_fraction(TODAY) < max(rates)


def test_a_current_year_row_dated_after_the_clock_is_ignored_as_of_today(opener: Opener) -> None:
    service = BudgetService(opener(), CLOCK)
    current = service.list_entries(2026)
    assert current
    for entry in current:
        assert any(execution.executed_on > TODAY for execution in entry.executions)
        assert any(execution.executed_on <= TODAY for execution in entry.executions)
    as_of_today = {
        (t.source_code, t.currency): t.executed_minor for t in service.totals_for_year(2026, TODAY)
    }
    at_year_end = {
        (t.source_code, t.currency): t.executed_minor
        for t in service.totals_for_year(2026, YEAR_END)
    }
    assert as_of_today.keys() == at_year_end.keys()
    for key, executed_today in as_of_today.items():
        assert executed_today < at_year_end[key]
    # Past years are complete well before the clock date.
    for total in service.totals_for_year(2025, TODAY):
        assert total.executed_minor == next(
            t.executed_minor
            for t in service.totals_for_year(2025, YEAR_END)
            if (t.source_code, t.currency) == (total.source_code, total.currency)
        )


def test_amounts_are_integers_in_the_python_objects_and_in_the_database(opener: Opener) -> None:
    conn = opener()
    for entry in _entries(conn):
        assert entry.allocated_minor is None or type(entry.allocated_minor) is int
        assert all(type(execution.amount_minor) is int for execution in entry.executions)
    executed_types = _rows(conn, "SELECT DISTINCT typeof(amount_minor) FROM budget_execution")
    assert executed_types == [("integer",)]
    allocated_types = _rows(conn, "SELECT DISTINCT typeof(allocated_minor) FROM budget_entry")
    assert {row[0] for row in allocated_types} == {"integer", "null"}


# --------------------------------------------------------------------------- determinism and time


def test_the_same_seed_gives_identical_rows(opener: Opener) -> None:
    first = opener(seed=7)
    second = opener(seed=7)
    for name in TABLE_QUERIES:
        rows = _table(first, name)
        assert rows
        assert rows == _table(second, name)


def test_a_different_seed_changes_the_amounts(opener: Opener) -> None:
    first = opener(seed=7)
    second = opener(seed=8)
    assert _table(first, "budget_entry") != _table(second, "budget_entry")
    assert _table(first, "budget_execution") != _table(second, "budget_execution")


def test_the_data_is_relative_to_the_clock(opener: Opener) -> None:
    conn = opener(clock=LATER_CLOCK)
    entries = _entries(conn, LATER_CLOCK)
    assert {entry.fiscal_year for entry in entries} == {2024, 2025, 2026, 2027}
    current = [entry for entry in entries if entry.fiscal_year == 2027]
    assert current
    assert all(
        any(execution.executed_on > date(2027, 3, 5) for execution in entry.executions)
        for entry in current
    )
    assert next(entry for entry in entries if entry.allocated_minor is None).fiscal_year == 2027


# --------------------------------------------------------------------------- framework


def test_the_change_log_carries_the_demo_operator(opener: Opener) -> None:
    conn = opener()
    rows = _rows(
        conn,
        "SELECT DISTINCT entity, operator FROM change_log"
        " WHERE entity IN ('funding_source', 'budget_entry', 'budget_execution')"
        " ORDER BY entity",
    )
    assert rows == [
        ("budget_entry", "DEMO"),
        ("budget_execution", "DEMO"),
        ("funding_source", "DEMO"),
    ]


def test_the_generator_is_registered_with_one_line() -> None:
    # T10.1 registers the cross-module generators (targets, snapshots) after the module ones.
    names = [generator.name for generator in GENERATORS]
    assert names.index("budget") == 3
    assert GENERATORS[names.index("budget")].run is demo_budget.generate


def test_the_framework_seeds_the_demo_database_once(tmp_path: Path) -> None:
    conn = open_demo_database(tmp_path, CLOCK, generators=[GENERATOR])
    try:
        before = {name: _table(conn, name) for name in TABLE_QUERIES}
        assert before["budget_execution"]
        assert app_meta.get(conn, DEMO_SEED_KEY) == str(DEFAULT_SEED)
    finally:
        conn.close()
    reopened = open_demo_database(tmp_path, CLOCK, generators=[GENERATOR])
    try:
        assert {name: _table(reopened, name) for name in TABLE_QUERIES} == before
    finally:
        reopened.close()
    # The real database is never created.
    assert not (tmp_path / DATABASE_FILE_NAME).exists()
