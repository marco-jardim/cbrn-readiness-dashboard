# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the budget service (PLAN.md T5.3); every amount and name here is fictitious."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import cast

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import budget as rules
from cbrn_dashboard.domain.budget import BudgetEntry, BudgetExecution
from cbrn_dashboard.services.budget import (
    BUILT_IN_SOURCE,
    DUPLICATE_CODE,
    DUPLICATE_ENTRY,
    DUPLICATE_EXECUTION,
    EXECUTION_OUTSIDE_FISCAL_YEAR,
    INVALID_AMOUNT,
    INVALID_CURRENCY,
    INVALID_YEAR,
    MAX_MINOR,
    NEGATIVE_AMOUNT,
    SOURCE_IN_USE,
    SOURCE_INACTIVE,
    BudgetService,
    EntryInput,
    SourceInput,
    SourceView,
    source_label,
)
from cbrn_dashboard.services.errors import (
    CODE_IMMUTABLE,
    INVALID_CODE,
    INVALID_DATE,
    LABEL_PT_BR_REQUIRED,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
    ServiceError,
)
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import load_config, save_config
from tests.services.conftest import ChangeLogRows

AS_OF = date(2026, 3, 5)
NOW_TEXT = "2026-03-05T12:00:00Z"
OPERATOR = "op-demo"
SRC_A = "DEMO-SRC-A"


@pytest.fixture
def service(db: DatabaseConnection, clock: FixedClock) -> BudgetService:
    return BudgetService(db, clock, lambda: OPERATOR)


def _error(call: Callable[[], object]) -> ServiceError:
    with pytest.raises(ServiceError) as info:
        call()
    return info.value


def _sid(service: BudgetService, code: str) -> int:
    source = service.get_source_by_code(code)
    assert source is not None
    return source.id


def _demo_source(service: BudgetService) -> int:
    return service.create_source(SourceInput(SRC_A, "Fonte demonstrativa A", "Demo source A"))


def _new_entry(
    service: BudgetService,
    source_id: int,
    *,
    fiscal_year: int = 2026,
    allocated: int | None = 1_000_000,
    currency: str | None = None,
    description: str | None = None,
    notes: str | None = None,
) -> int:
    return service.create_entry(
        EntryInput(fiscal_year, source_id, allocated, currency, description, notes)
    )


def _count(conn: DatabaseConnection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0])


def _state(conn: DatabaseConnection, change_log_rows: ChangeLogRows) -> list[object]:
    """Every budget row plus the whole change_log: equal states mean nothing was written."""
    tables = ("funding_source", "budget_entry", "budget_execution")
    data: list[object] = [
        [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]
        for table in tables
    ]
    data.append(change_log_rows(conn))
    return data


def _entities(rows: list[dict[str, object]]) -> Counter[tuple[object, object]]:
    return Counter((row["entity"], row["action"]) for row in rows)


# --------------------------------------------------------------------------- funding sources


def test_built_in_sources_exist_without_labels(service: BudgetService) -> None:
    sources = {source.code: source for source in service.list_sources(include_inactive=True)}
    assert {"DIRSA", "OPCW_TRUST_FUND"} <= set(sources)
    for code in ("DIRSA", "OPCW_TRUST_FUND"):
        source = sources[code]
        assert source.built_in
        assert source.active
        assert (source.label_pt_br, source.label_en_us, source.label_es_es) == (None, None, None)
        assert source_label(source, "en_US") == code  # the UI replaces it with its own name


def test_create_source_writes_one_log_row(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    before = len(change_log_rows(db))
    source_id = _demo_source(service)
    rows = change_log_rows(db)[before:]
    assert len(rows) == 1
    assert (rows[0]["entity"], rows[0]["action"], rows[0]["entity_id"]) == (
        "funding_source",
        "insert",
        source_id,
    )
    assert rows[0]["operator"] == OPERATOR
    assert rows[0]["at_utc"] == NOW_TEXT
    source = service.get_source(source_id)
    assert (source.code, source.built_in, source.active) == (SRC_A, False, True)
    assert source.label_pt_br == "Fonte demonstrativa A"
    assert source.label_es_es is None


def test_user_source_needs_only_the_pt_br_label(service: BudgetService) -> None:
    service.create_source(SourceInput("DEMO-ONLY-PT", "  Somente pt-BR  "))
    assert service.get_source(_sid(service, "DEMO-ONLY-PT")).label_pt_br == "Somente pt-BR"
    for label in (None, "", "   "):
        error = _error(lambda label=label: service.create_source(SourceInput("DEMO-X", label)))
        assert (error.code, error.field) == (LABEL_PT_BR_REQUIRED, "label_pt_br")
        assert service.get_source_by_code("DEMO-X") is None
    # an English label alone does not replace the pt-BR one
    assert _error(lambda: service.create_source(SourceInput("DEMO-X", None, "Only EN"))).code == (
        LABEL_PT_BR_REQUIRED
    )


@pytest.mark.parametrize(
    ("code", "expected"),
    [("", REQUIRED), ("   ", REQUIRED), ("bad code", INVALID_CODE), ("-x", INVALID_CODE)],
)
def test_source_code_must_be_valid(
    service: BudgetService,
    db: DatabaseConnection,
    change_log_rows: ChangeLogRows,
    code: str,
    expected: str,
) -> None:
    state = _state(db, change_log_rows)
    assert _error(lambda: service.create_source(SourceInput(code, "Rotulo"))).code == expected
    assert _state(db, change_log_rows) == state


def test_duplicate_source_code_is_refused(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    _demo_source(service)
    other = service.create_source(SourceInput("DEMO-SRC-B", "Fonte B"))
    state = _state(db, change_log_rows)
    for code in (SRC_A, "DIRSA"):
        data = SourceInput(code, "Outra")
        assert _error(lambda data=data: service.create_source(data)).code == DUPLICATE_CODE
    error = _error(lambda: service.update_source(other, SourceInput(SRC_A, "Fonte B")))
    assert error.code == DUPLICATE_CODE
    assert _state(db, change_log_rows) == state


def test_built_in_source_can_be_deactivated_but_not_deleted(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    dirsa = _sid(service, "DIRSA")
    state = _state(db, change_log_rows)
    assert _error(lambda: service.delete_source(dirsa)).code == BUILT_IN_SOURCE
    assert _state(db, change_log_rows) == state

    before = len(change_log_rows(db))
    service.deactivate_source(dirsa)
    rows = change_log_rows(db)
    assert len(rows) == before + 1
    last = rows[-1]
    assert (last["entity"], last["action"]) == ("funding_source", "update")
    assert last["entity_id"] == dirsa
    assert json.loads(str(last["before_json"]))["active"] == 1
    assert json.loads(str(last["after_json"]))["active"] == 0
    assert last["operator"] == OPERATOR
    assert "DIRSA" not in [source.code for source in service.list_sources()]
    assert "DIRSA" in [source.code for source in service.list_sources(include_inactive=True)]
    # still a built-in source, still not deletable
    assert service.get_source(dirsa).built_in
    assert _error(lambda: service.delete_source(dirsa)).code == BUILT_IN_SOURCE


def test_built_in_source_code_cannot_change_and_labels_stay_empty(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    opcw = _sid(service, "OPCW_TRUST_FUND")
    state = _state(db, change_log_rows)
    error = _error(lambda: service.update_source(opcw, SourceInput("OPCW_RENAMED", "Nome")))
    assert (error.code, error.field) == (BUILT_IN_SOURCE, "code")
    assert _state(db, change_log_rows) == state

    # labels sent for a built-in source are ignored: nothing changes, nothing is logged
    service.update_source(opcw, SourceInput("OPCW_TRUST_FUND", "Nome", "Name", "Nombre"))
    assert _state(db, change_log_rows) == state
    # the active flag can change, in both directions
    service.update_source(opcw, SourceInput("OPCW_TRUST_FUND", active=False))
    assert not service.get_source(opcw).active
    service.update_source(opcw, SourceInput("OPCW_TRUST_FUND", active=True))
    source = service.get_source(opcw)
    assert source.active
    assert source.built_in
    assert source.label_pt_br is None


def test_source_in_use_cannot_be_deleted(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    source_id = _demo_source(service)
    entry_id = _new_entry(service, source_id)
    state = _state(db, change_log_rows)
    error = _error(lambda: service.delete_source(source_id))
    assert (error.code, error.field) == (SOURCE_IN_USE, "source_id")
    assert _state(db, change_log_rows) == state

    service.delete_entry(entry_id)
    before = len(change_log_rows(db))
    service.delete_source(source_id)
    rows = change_log_rows(db)[before:]
    assert [(r["entity"], r["action"], r["entity_id"]) for r in rows] == [
        ("funding_source", "delete", source_id)
    ]
    assert service.get_source_by_code(SRC_A) is None
    assert _error(lambda: service.delete_source(source_id)).code == NOT_FOUND


def test_source_code_is_immutable_once_an_entry_uses_it(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    source_id = _demo_source(service)
    # unused: the code may change
    service.update_source(source_id, SourceInput("DEMO-SRC-B", "Fonte B"))
    assert service.get_source(source_id).code == "DEMO-SRC-B"

    _new_entry(service, source_id)
    state = _state(db, change_log_rows)
    error = _error(lambda: service.update_source(source_id, SourceInput(SRC_A, "Fonte B")))
    assert (error.code, error.field) == (CODE_IMMUTABLE, "code")
    assert _state(db, change_log_rows) == state
    # labels and the active flag stay editable
    service.update_source(source_id, SourceInput("DEMO-SRC-B", "Fonte B2", "Source B2"))
    assert service.get_source(source_id).label_en_us == "Source B2"
    assert _error(lambda: service.update_source(9999, SourceInput("X", "Y"))).code == NOT_FOUND


def test_inactive_source_refuses_new_entries_only(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    source_id = _demo_source(service)
    entry_id = _new_entry(service, source_id, description="Antiga")
    other_id = _new_entry(service, _sid(service, "DIRSA"))
    service.deactivate_source(source_id)

    state = _state(db, change_log_rows)
    error = _error(lambda: _new_entry(service, source_id, description="Nova"))
    assert (error.code, error.field) == (SOURCE_INACTIVE, "source_id")
    # moving an existing entry onto the inactive source is a new use of it
    moved = EntryInput(2026, source_id, 5)
    assert _error(lambda: service.update_entry(other_id, moved)).code == SOURCE_INACTIVE
    assert _state(db, change_log_rows) == state

    # what already uses the source keeps working
    service.update_entry(entry_id, EntryInput(2026, source_id, 2_000_000, description="Antiga"))
    assert service.get_entry(entry_id).allocated_minor == 2_000_000
    service.add_execution(entry_id, "2026-02-01", 1_000)
    # reactivating makes it available again
    service.update_source(source_id, SourceInput(SRC_A, "Fonte demonstrativa A"))
    assert _new_entry(service, source_id, description="Nova") > 0


def test_source_label_fallback() -> None:
    source = SourceView(1, "DEMO-X", False, "Rotulo", "Label", None, True)
    assert source_label(source, "pt_BR") == "Rotulo"
    assert source_label(source, "en-US") == "Label"
    assert source_label(source, "es_ES") == "Rotulo"  # es-ES missing: pt-BR
    assert source_label(replace(source, label_pt_br="  "), "es_ES") == "Label"
    assert source_label(replace(source, label_pt_br=None, label_en_us=None), "es_ES") == "DEMO-X"


# --------------------------------------------------------------------------- entries


def test_create_entry_writes_one_log_row_and_normalises_text(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    source_id = _sid(service, "DIRSA")
    before = len(change_log_rows(db))
    entry_id = _new_entry(
        service, source_id, allocated=1_234_567, description="  Custeio  ", notes="   "
    )
    rows = change_log_rows(db)[before:]
    assert len(rows) == 1
    assert (rows[0]["entity"], rows[0]["action"], rows[0]["entity_id"]) == (
        "budget_entry",
        "insert",
        entry_id,
    )
    assert rows[0]["operator"] == OPERATOR
    assert rows[0]["at_utc"] == NOW_TEXT
    view = service.get_entry(entry_id)
    assert (view.fiscal_year, view.source_code, view.source_id) == (2026, "DIRSA", source_id)
    assert (view.currency, view.allocated_minor) == ("BRL", 1_234_567)
    assert view.description == "Custeio"
    assert view.notes is None
    assert view.executions == ()


def test_entry_without_description_stores_empty_text_and_allocation_may_be_unknown(
    service: BudgetService, db: DatabaseConnection
) -> None:
    entry_id = _new_entry(service, _sid(service, "DIRSA"), allocated=None, description=None)
    view = service.get_entry(entry_id)
    assert view.description == ""
    assert view.allocated_minor is None
    stored = db.execute("SELECT description FROM budget_entry WHERE id = ?", (entry_id,))
    assert stored.fetchone()["description"] == ""
    # zero is a valid amount, different from "not known yet"
    zero = _new_entry(service, _sid(service, "DIRSA"), allocated=0, description="Zero")
    assert service.get_entry(zero).allocated_minor == 0


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("fiscal_year", None, REQUIRED),
        ("fiscal_year", 1899, INVALID_YEAR),
        ("fiscal_year", 2201, INVALID_YEAR),
        ("fiscal_year", True, INVALID_YEAR),
        ("fiscal_year", "2026", INVALID_YEAR),
        ("fiscal_year", 2026.0, INVALID_YEAR),
        ("source_id", None, REQUIRED),
        ("source_id", 9999, NOT_FOUND),
        ("currency", "CHF", INVALID_CURRENCY),
        ("currency", "XXX", INVALID_CURRENCY),
        ("currency", "brl", INVALID_CURRENCY),
        ("currency", "", INVALID_CURRENCY),
        ("currency", "BRLL", INVALID_CURRENCY),
        ("allocated_minor", -1, NEGATIVE_AMOUNT),
        ("allocated_minor", -(10**12), NEGATIVE_AMOUNT),
        ("allocated_minor", 1.5, INVALID_AMOUNT),
        ("allocated_minor", 100.0, INVALID_AMOUNT),
        ("allocated_minor", True, INVALID_AMOUNT),
        ("allocated_minor", "100", INVALID_AMOUNT),
        ("allocated_minor", MAX_MINOR + 1, INVALID_AMOUNT),
    ],
)
def test_invalid_entry_is_refused_and_nothing_is_written(
    service: BudgetService,
    db: DatabaseConnection,
    change_log_rows: ChangeLogRows,
    field: str,
    value: object,
    expected: str,
) -> None:
    existing = _new_entry(service, _sid(service, "DIRSA"), description="Existente")
    base = EntryInput(2026, _sid(service, "DIRSA"), 100, "BRL", "Nova")
    data = replace(base, **{field: value})
    state = _state(db, change_log_rows)

    error = _error(lambda: service.create_entry(data))
    assert error.code == expected
    assert error.field == field
    assert _state(db, change_log_rows) == state

    error = _error(lambda: service.update_entry(existing, data))
    assert error.code == expected
    assert _state(db, change_log_rows) == state


def test_entry_not_found_codes(service: BudgetService) -> None:
    data = EntryInput(2026, _sid(service, "DIRSA"), 1)
    assert _error(lambda: service.update_entry(999, data)).code == NOT_FOUND
    assert _error(lambda: service.delete_entry(999)).code == NOT_FOUND
    assert _error(lambda: service.get_entry(999)).code == NOT_FOUND


def test_allowed_currencies_are_accepted(service: BudgetService) -> None:
    source_id = _sid(service, "DIRSA")
    for currency in ("BRL", "USD", "EUR"):
        entry_id = _new_entry(service, source_id, currency=currency)
        assert service.get_entry(entry_id).currency == currency


def test_new_entry_uses_the_configured_default_currency(
    service: BudgetService, db: DatabaseConnection, clock: FixedClock
) -> None:
    source_id = _sid(service, "DIRSA")
    first = _new_entry(service, source_id, description="Padrao")
    assert service.get_entry(first).currency == "BRL"  # A08 default

    save_config(
        WriteContext(db, clock, OPERATOR), load_config(db).with_changes(default_currency="USD")
    )
    second = _new_entry(service, source_id, description="Depois")
    assert service.get_entry(second).currency == "USD"
    # an explicit currency still wins, and existing entries are not touched
    third = _new_entry(service, source_id, currency="EUR", description="Explicita")
    assert service.get_entry(third).currency == "EUR"
    assert service.get_entry(first).currency == "BRL"
    # updating without a currency keeps the entry's own
    service.update_entry(first, EntryInput(2026, source_id, 5, None, "Padrao"))
    assert service.get_entry(first).currency == "BRL"


def test_duplicate_entry_is_refused(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    source_id = _sid(service, "DIRSA")
    first = _new_entry(service, source_id, description="Custeio")
    state = _state(db, change_log_rows)
    same = EntryInput(2026, source_id, 5, "BRL", "  Custeio ")
    assert _error(lambda: service.create_entry(same)).code == DUPLICATE_ENTRY
    assert _state(db, change_log_rows) == state

    # both descriptions omitted (None and blank) are the same key
    _new_entry(service, source_id, description=None)
    state = _state(db, change_log_rows)
    for description in (None, "", "   "):
        data = EntryInput(2026, source_id, 7, "BRL", description)
        assert _error(lambda data=data: service.create_entry(data)).code == DUPLICATE_ENTRY
    assert _state(db, change_log_rows) == state

    # any part of the key differs: allowed
    _new_entry(service, source_id, description="Custeio", currency="USD")
    _new_entry(service, source_id, description="Custeio", fiscal_year=2027)
    _new_entry(service, _sid(service, "OPCW_TRUST_FUND"), description="Custeio")
    _new_entry(service, source_id, description="Capital")

    # an update may not collide with another entry, but may keep its own key
    other = _new_entry(service, source_id, description="Outra")
    collide = EntryInput(2026, source_id, 9, "BRL", "Custeio")
    assert _error(lambda: service.update_entry(other, collide)).code == DUPLICATE_ENTRY
    service.update_entry(first, EntryInput(2026, source_id, 8, "BRL", "Custeio"))
    assert service.get_entry(first).allocated_minor == 8


def test_update_entry_logs_only_real_changes(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    source_id = _sid(service, "DIRSA")
    entry_id = _new_entry(service, source_id, allocated=1_000, description="Custeio")
    before = len(change_log_rows(db))
    service.update_entry(entry_id, EntryInput(2026, source_id, 1_000, "BRL", "Custeio"))
    assert len(change_log_rows(db)) == before  # nothing changed, nothing logged

    service.update_entry(entry_id, EntryInput(2026, source_id, 2_500, "BRL", "Custeio", "Nota"))
    rows = change_log_rows(db)[before:]
    assert len(rows) == 1
    assert (rows[0]["entity"], rows[0]["action"], rows[0]["entity_id"]) == (
        "budget_entry",
        "update",
        entry_id,
    )
    assert json.loads(str(rows[0]["before_json"]))["allocated_minor"] == 1_000
    assert json.loads(str(rows[0]["after_json"]))["allocated_minor"] == 2_500
    assert rows[0]["operator"] == OPERATOR
    assert rows[0]["at_utc"] == NOW_TEXT
    view = service.get_entry(entry_id)
    assert (view.allocated_minor, view.notes) == (2_500, "Nota")


def test_delete_entry_logs_the_entry_and_each_execution_row(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    source_id = _sid(service, "DIRSA")
    entry_id = _new_entry(service, source_id)
    keep_id = _new_entry(service, source_id, description="Fica")
    execution_ids = [
        service.add_execution(entry_id, "2026-01-10", 100),
        service.add_execution(entry_id, "2026-02-10", 200),
        service.add_execution(entry_id, "2026-02-10", 300, "mesma data"),
    ]
    kept_execution = service.add_execution(keep_id, "2026-01-10", 100)
    before = len(change_log_rows(db))

    service.delete_entry(entry_id)

    rows = change_log_rows(db)[before:]
    assert len(rows) == 4
    assert _entities(rows) == Counter(
        {("budget_execution", "delete"): 3, ("budget_entry", "delete"): 1}
    )
    deleted_executions = {r["entity_id"] for r in rows if r["entity"] == "budget_execution"}
    assert deleted_executions == set(execution_ids)
    entry_rows = [r for r in rows if r["entity"] == "budget_entry"]
    assert entry_rows[0]["entity_id"] == entry_id
    assert all(r["operator"] == OPERATOR and r["at_utc"] == NOW_TEXT for r in rows)
    assert json.loads(str(entry_rows[0]["before_json"]))["fiscal_year"] == 2026
    assert [e.id for e in service.list_entries()] == [keep_id]
    assert [x.id for x in service.get_entry(keep_id).executions] == [kept_execution]
    assert _count(db, "budget_execution") == 1


def test_list_entries_filters_by_year_and_orders_them(service: BudgetService) -> None:
    dirsa = _sid(service, "DIRSA")
    opcw = _sid(service, "OPCW_TRUST_FUND")
    late = _new_entry(service, opcw, fiscal_year=2027)
    second = _new_entry(service, opcw, fiscal_year=2026, currency="USD")
    first = _new_entry(service, dirsa, fiscal_year=2026)
    service.add_execution(first, "2026-05-01", 10)
    service.add_execution(first, "2026-01-01", 20)
    assert [e.id for e in service.list_entries()] == [first, second, late]
    assert [e.id for e in service.list_entries(2027)] == [late]
    assert service.list_entries(1999) == []
    assert [x.executed_on for x in service.get_entry(first).executions] == [
        date(2026, 1, 1),
        date(2026, 5, 1),
    ]


# --------------------------------------------------------------------------- execution rows


def test_add_update_delete_execution_log_rows(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    entry_id = _new_entry(service, _sid(service, "DIRSA"))
    before = len(change_log_rows(db))

    execution_id = service.add_execution(entry_id, "2026-02-03", 150_000, "  primeira parcela ")
    rows = change_log_rows(db)[before:]
    assert [(r["entity"], r["action"], r["entity_id"]) for r in rows] == [
        ("budget_execution", "insert", execution_id)
    ]
    view = service.get_entry(entry_id).executions[0]
    assert (view.id, view.entry_id, view.executed_on) == (execution_id, entry_id, date(2026, 2, 3))
    assert (view.amount_minor, view.note) == (150_000, "primeira parcela")

    # corrections are edits of the row, each one in the change log
    service.update_execution(execution_id, date(2026, 2, 4), 140_000, None)
    rows = change_log_rows(db)[before:]
    assert [(r["entity"], r["action"]) for r in rows][-1] == ("budget_execution", "update")
    assert json.loads(str(rows[-1]["before_json"]))["amount_minor"] == 150_000
    assert json.loads(str(rows[-1]["after_json"]))["amount_minor"] == 140_000
    changed = service.get_entry(entry_id).executions[0]
    assert (changed.executed_on, changed.amount_minor, changed.note) == (
        date(2026, 2, 4),
        140_000,
        None,
    )
    count = len(rows)
    service.update_execution(execution_id, "2026-02-04", 140_000)  # identical: no log row
    assert len(change_log_rows(db)[before:]) == count

    service.delete_execution(execution_id)
    rows = change_log_rows(db)[before:]
    assert [(r["entity"], r["action"]) for r in rows][-1] == ("budget_execution", "delete")
    assert all(r["operator"] == OPERATOR and r["at_utc"] == NOW_TEXT for r in rows)
    assert service.get_entry(entry_id).executions == ()


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("entry_id", 9999, NOT_FOUND),
        ("executed_on", "", REQUIRED),
        ("executed_on", "2026-02-30", INVALID_DATE),
        ("executed_on", "05/03/2026", INVALID_DATE),
        ("executed_on", "2026-3-5", INVALID_DATE),
        ("executed_on", datetime(2026, 3, 5, tzinfo=UTC), INVALID_DATE),
        ("amount_minor", None, REQUIRED),
        ("amount_minor", -1, NEGATIVE_AMOUNT),
        ("amount_minor", -(10**12), NEGATIVE_AMOUNT),
        ("amount_minor", 12.5, INVALID_AMOUNT),
        ("amount_minor", 10.0, INVALID_AMOUNT),
        ("amount_minor", True, INVALID_AMOUNT),
        ("amount_minor", "10", INVALID_AMOUNT),
        ("amount_minor", MAX_MINOR + 1, INVALID_AMOUNT),
    ],
)
def test_invalid_execution_is_refused_and_nothing_is_written(
    service: BudgetService,
    db: DatabaseConnection,
    change_log_rows: ChangeLogRows,
    field: str,
    value: object,
    expected: str,
) -> None:
    entry_id = _new_entry(service, _sid(service, "DIRSA"))
    existing = service.add_execution(entry_id, "2026-01-02", 500)
    arguments: dict[str, object] = {
        "entry_id": entry_id,
        "executed_on": "2026-02-03",
        "amount_minor": 100,
    }
    arguments[field] = value
    state = _state(db, change_log_rows)

    def add() -> int:
        return service.add_execution(
            cast("int", arguments["entry_id"]),
            cast("str", arguments["executed_on"]),
            cast("int", arguments["amount_minor"]),
        )

    error = _error(add)
    assert error.code == expected
    assert error.field == field
    assert _state(db, change_log_rows) == state

    if field != "entry_id":  # the entry of an existing row never changes
        error = _error(
            lambda: service.update_execution(
                existing,
                cast("str", arguments["executed_on"]),
                cast("int", arguments["amount_minor"]),
            )
        )
        assert error.code == expected
        assert _state(db, change_log_rows) == state


def test_zero_amount_execution_is_valid(service: BudgetService) -> None:
    entry_id = _new_entry(service, _sid(service, "DIRSA"))
    service.add_execution(entry_id, "2026-01-02", 0)
    assert service.get_entry(entry_id).executions[0].amount_minor == 0


def test_execution_not_found_codes(service: BudgetService) -> None:
    assert _error(lambda: service.update_execution(999, "2026-01-01", 1)).code == NOT_FOUND
    assert _error(lambda: service.delete_execution(999)).code == NOT_FOUND


def test_duplicate_execution_is_refused(
    service: BudgetService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    source_id = _sid(service, "DIRSA")
    entry_id = _new_entry(service, source_id)
    other_entry = _new_entry(service, source_id, description="Outra")
    first = service.add_execution(entry_id, "2026-02-03", 100)
    state = _state(db, change_log_rows)
    error = _error(lambda: service.add_execution(entry_id, date(2026, 2, 3), 100, "outra nota"))
    assert error.code == DUPLICATE_EXECUTION
    assert _state(db, change_log_rows) == state

    # a different date, amount or entry is not a duplicate
    second = service.add_execution(entry_id, "2026-02-04", 100)
    service.add_execution(entry_id, "2026-02-03", 101)
    service.add_execution(other_entry, "2026-02-03", 100)
    # an update may not collide with another row, but may keep its own key
    assert _error(lambda: service.update_execution(second, "2026-02-03", 100)).code == (
        DUPLICATE_EXECUTION
    )
    service.update_execution(first, "2026-02-03", 100, "so a nota")
    assert service.get_entry(entry_id).executions[0].note == "so a nota"


def test_execution_outside_the_fiscal_year_is_stored_and_flagged(service: BudgetService) -> None:
    entry_id = _new_entry(service, _sid(service, "DIRSA"), fiscal_year=2026)
    assert service.data_quality(AS_OF) == []
    service.add_execution(entry_id, "2026-01-01", 1)
    service.add_execution(entry_id, "2026-12-31", 2)
    assert service.data_quality(AS_OF) == []

    service.add_execution(entry_id, "2025-12-31", 10)
    late = service.add_execution(entry_id, "2027-01-01", 20)
    issues = service.data_quality(AS_OF)
    assert [(i.code, i.entry_id, i.executed_on, i.amount_minor) for i in issues] == [
        (EXECUTION_OUTSIDE_FISCAL_YEAR, entry_id, date(2025, 12, 31), 10),
        (EXECUTION_OUTSIDE_FISCAL_YEAR, entry_id, date(2027, 1, 1), 20),
    ]
    # the row is attributed to its entry's year regardless of its own date
    total = service.totals_for_year(2026, date(2027, 6, 1))
    assert [(t.fiscal_year, t.executed_minor) for t in total] == [(2026, 33)]
    assert service.totals_for_year(2025, date(2027, 6, 1)) == []

    # correcting the date clears the finding
    service.update_execution(late, "2026-06-01", 20)
    assert [i.amount_minor for i in service.data_quality(AS_OF)] == [10]


# --------------------------------------------------------------------------- exact amounts


def test_amounts_above_2_pow_53_stay_exact(service: BudgetService) -> None:
    entry_id = _new_entry(service, _sid(service, "DIRSA"), allocated=2**60 + 1)
    service.add_execution(entry_id, "2026-01-10", 2**59 + 3)
    service.add_execution(entry_id, "2026-02-10", 2**59 + 5)

    view = service.get_entry(entry_id)
    assert view.allocated_minor == 2**60 + 1
    assert [x.amount_minor for x in view.executions] == [2**59 + 3, 2**59 + 5]
    (total,) = service.totals(AS_OF)
    assert total.allocated_minor == 2**60 + 1
    assert total.executed_minor == 2**60 + 8

    top = _new_entry(service, _sid(service, "DIRSA"), allocated=MAX_MINOR, description="Maximo")
    assert service.get_entry(top).allocated_minor == MAX_MINOR
    service.update_execution(view.executions[0].id, "2026-01-10", MAX_MINOR)
    assert service.get_entry(entry_id).executions[0].amount_minor == MAX_MINOR


# --------------------------------------------------------------------------- as-of views


@dataclass(frozen=True)
class _Fixture:
    entries: list[BudgetEntry]
    executions: list[BudgetExecution]


def _build_fixture(service: BudgetService) -> _Fixture:
    """Several years, two sources, three currencies, a missing allocation, rows around AS_OF.

    Returns the same data as DOMAIN objects, written by hand from the specification below.
    """
    _demo_source(service)
    dirsa, opcw, demo = (_sid(service, code) for code in ("DIRSA", "OPCW_TRUST_FUND", SRC_A))
    # (year, source id, source code, currency, allocated, description)
    specs: list[tuple[int, int, str, str, int | None, str]] = [
        (2025, dirsa, "DIRSA", "BRL", 1_000_000, ""),
        (2026, dirsa, "DIRSA", "BRL", 5_000_000, "Custeio"),
        (2026, dirsa, "DIRSA", "BRL", 2_500_000, "Capital"),
        (2026, demo, SRC_A, "USD", None, ""),
        (2026, opcw, "OPCW_TRUST_FUND", "USD", 800_000, ""),
        (2027, demo, SRC_A, "EUR", 300_000, ""),
        (2026, demo, SRC_A, "BRL", 0, ""),
    ]
    entries: list[BudgetEntry] = []
    for year, source_id, code, currency, allocated, description in specs:
        entry_id = service.create_entry(
            EntryInput(year, source_id, allocated, currency, description)
        )
        entries.append(BudgetEntry(entry_id, year, code, currency, allocated))
    # (index of the entry, date, amount): before, on and after AS_OF; one outside the year
    rows: list[tuple[int, date, int]] = [
        (0, date(2025, 6, 1), 400_000),
        (1, date(2026, 3, 4), 1_000_000),
        (1, date(2026, 3, 5), 500_000),
        (1, date(2026, 3, 6), 700_000),
        (2, date(2026, 1, 15), 250_000),
        (2, date(2025, 12, 31), 100_000),
        (3, date(2026, 2, 1), 12_345),
        (4, date(2026, 3, 5), 200_000),
        (4, date(2026, 12, 1), 50_000),
        (5, date(2027, 1, 10), 10_000),
        (6, date(2026, 3, 1), 1_000),
    ]
    executions: list[BudgetExecution] = []
    for index, day, amount in rows:
        entry = entries[index]
        service.add_execution(entry.id, day, amount)
        executions.append(BudgetExecution(entry.id, day, amount))
    return _Fixture(entries, executions)


@pytest.mark.parametrize(
    "as_of", [date(2025, 12, 31), AS_OF, date(2026, 12, 31), date(2028, 2, 29)]
)
def test_service_views_equal_the_domain_results(service: BudgetService, as_of: date) -> None:
    fx = _build_fixture(service)
    assert service.totals(as_of) == rules.totals(fx.entries, fx.executions, as_of)
    assert service.multi_year_table(as_of) == rules.multi_year_table(
        fx.entries, fx.executions, as_of
    )
    for year in (2024, 2025, 2026, 2027):
        assert service.totals_for_year(year, as_of) == rules.totals_for_year(
            fx.entries, fx.executions, as_of, year
        )
    assert service.indicator_values(as_of) == rules.indicator_values(
        fx.entries, fx.executions, as_of
    )


def test_fixture_results_are_not_trivial(service: BudgetService) -> None:
    _build_fixture(service)
    groups = {(t.fiscal_year, t.source_code, t.currency): t for t in service.totals(AS_OF)}
    assert len(groups) == 6
    dirsa_2026 = groups[(2026, "DIRSA", "BRL")]
    assert dirsa_2026.allocated_minor == 7_500_000  # two entries of the same group
    assert dirsa_2026.executed_minor == 1_850_000  # 3/4 + 3/5 + 1/15 + 12/31 of 2025; not 3/6
    assert dirsa_2026.rate == 1_850_000 / 7_500_000
    missing = groups[(2026, SRC_A, "USD")]
    assert (missing.allocated_minor, missing.executed_minor, missing.rate) == (None, 12_345, None)
    zero = groups[(2026, SRC_A, "BRL")]
    assert (zero.allocated_minor, zero.rate) == (0, None)
    assert groups[(2027, SRC_A, "EUR")].executed_minor == 0  # dated after AS_OF
    assert groups[(2026, "OPCW_TRUST_FUND", "USD")].executed_minor == 200_000
    # currencies are never added together
    assert {t.currency for t in service.totals_for_year(2026, AS_OF)} == {"BRL", "USD"}
    values = service.indicator_values(AS_OF)
    assert len(values) == 4  # the 2026 groups only
    assert all(value.code == rules.BUD_EXEC_RATE for value in values)


def test_views_of_an_empty_budget(service: BudgetService) -> None:
    assert service.totals(AS_OF) == []
    assert service.multi_year_table(AS_OF) == []
    assert service.totals_for_year(2026, AS_OF) == []
    assert service.indicator_values(AS_OF) == []
    assert service.data_quality(AS_OF) == []


def test_target_scale_follows_the_stored_prorate_switch(
    service: BudgetService, db: DatabaseConnection, clock: FixedClock
) -> None:
    assert load_config(db).budget_prorate_target  # P08 default: on
    assert service.target_scale(AS_OF) == rules.elapsed_fraction(AS_OF)
    assert 0.0 < service.target_scale(AS_OF) < 1.0
    assert service.target_scale(date(2026, 12, 31)) == 1.0
    assert service.target_scale(date(2028, 12, 31)) == 1.0  # leap year

    save_config(
        WriteContext(db, clock, OPERATOR),
        load_config(db).with_changes(budget_prorate_target=False),
    )
    assert service.target_scale(AS_OF) == 1.0
    assert service.target_scale(date(2026, 1, 1)) == 1.0

    save_config(
        WriteContext(db, clock, OPERATOR),
        load_config(db).with_changes(budget_prorate_target=True),
    )
    assert service.target_scale(AS_OF) == rules.elapsed_fraction(AS_OF)


# --------------------------------------------------------------------------- read-only


def test_read_only_connection_refuses_every_write_and_still_reads(
    service: BudgetService,
    read_only_db: DatabaseConnection,
    db: DatabaseConnection,
    clock: FixedClock,
    change_log_rows: ChangeLogRows,
) -> None:
    fx = _build_fixture(service)
    read_only = BudgetService(read_only_db, clock, lambda: OPERATOR)
    entry_id = fx.entries[0].id
    data = EntryInput(2026, _sid(service, "DIRSA"), 1)
    writes: list[Callable[[], object]] = [
        lambda: read_only.create_source(SourceInput("DEMO-RO", "Somente leitura")),
        lambda: read_only.update_source(1, SourceInput("DIRSA")),
        lambda: read_only.deactivate_source(1),
        lambda: read_only.delete_source(1),
        lambda: read_only.create_entry(data),
        lambda: read_only.update_entry(entry_id, data),
        lambda: read_only.delete_entry(entry_id),
        lambda: read_only.add_execution(entry_id, "2026-01-01", 1),
        lambda: read_only.update_execution(1, "2026-01-01", 1),
        lambda: read_only.delete_execution(1),
    ]
    log_before = change_log_rows(db)
    for write in writes:
        assert _error(write).code == READ_ONLY
    assert change_log_rows(db) == log_before

    assert [s.code for s in read_only.list_sources(include_inactive=True)] == [
        s.code for s in service.list_sources(include_inactive=True)
    ]
    assert read_only.list_entries() == service.list_entries()
    assert read_only.get_entry(entry_id) == service.get_entry(entry_id)
    assert read_only.totals(AS_OF) == service.totals(AS_OF)
    assert read_only.multi_year_table(AS_OF) == service.multi_year_table(AS_OF)
    assert read_only.totals_for_year(2026, AS_OF) == service.totals_for_year(2026, AS_OF)
    assert read_only.indicator_values(AS_OF) == service.indicator_values(AS_OF)
    assert read_only.target_scale(AS_OF) == service.target_scale(AS_OF)
    assert read_only.data_quality(AS_OF) == service.data_quality(AS_OF)


def test_operator_label_is_read_for_each_write(
    db: DatabaseConnection, clock: FixedClock, change_log_rows: ChangeLogRows
) -> None:
    current = ["first"]
    service = BudgetService(db, clock, lambda: current[0])
    before = len(change_log_rows(db))
    service.create_source(SourceInput("DEMO-OP-1", "Um"))
    current[0] = "second"
    service.create_source(SourceInput("DEMO-OP-2", "Dois"))
    assert [row["operator"] for row in change_log_rows(db)[before:]] == ["first", "second"]
    default = BudgetService(db, clock)
    default.create_source(SourceInput("DEMO-OP-3", "Tres"))
    assert change_log_rows(db)[-1]["operator"] == ""
