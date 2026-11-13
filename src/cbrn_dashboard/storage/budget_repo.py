# SPDX-License-Identifier: GPL-3.0-or-later
"""Storage of funding sources, budget entries and dated budget execution rows (T5.3).

Reads are plain parameterised ``SELECT`` statements. Every write goes through the repository
helpers (:func:`~cbrn_dashboard.storage.repository.insert`, ``update`` and ``delete``), so each
affected row gets its ``change_log`` row in the same transaction. This module checks no business
rule: that is the service's job (``services/budget.py``). It also holds the one place where rows
become domain objects (a domain ``BudgetEntry`` carries the SOURCE CODE, not the source id).

Money is whole minor units (``int``) exactly as stored; nothing here converts or adds currencies.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from cbrn_dashboard.domain.budget import BudgetEntry, BudgetExecution
from cbrn_dashboard.domain.dates import parse_iso_date
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import RepositoryError, WriteContext, delete, insert, update

__all__ = [
    "EntryRow",
    "ExecutionRow",
    "SourceRow",
    "delete_entry",
    "delete_execution",
    "delete_source",
    "entry_to_domain",
    "execution_to_domain",
    "get_entry",
    "get_entry_by_key",
    "get_execution",
    "get_execution_by_key",
    "get_source",
    "get_source_by_code",
    "insert_entry",
    "insert_execution",
    "insert_source",
    "list_entries",
    "list_executions",
    "list_sources",
    "source_codes",
    "source_in_use",
    "update_entry",
    "update_execution",
    "update_source",
]

_SOURCE = "funding_source"
_ENTRY = "budget_entry"
_EXECUTION = "budget_execution"

_SOURCE_COLUMNS = "id, code, built_in, label_pt_br, label_en_us, label_es_es, active"
_ENTRY_COLUMNS = "id, fiscal_year, source_id, currency, allocated_minor, description, notes"
_ENTRY_COLUMNS_E = (
    "e.id, e.fiscal_year, e.source_id, e.currency, e.allocated_minor, e.description, e.notes"
)
_EXECUTION_COLUMNS = "id, entry_id, executed_on, amount_minor, note"


# --------------------------------------------------------------------------- rows


@dataclass(frozen=True)
class SourceRow:
    """A row of ``funding_source``."""

    id: int
    code: str
    built_in: bool
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    active: bool


@dataclass(frozen=True)
class EntryRow:
    """A row of ``budget_entry``; ``allocated_minor`` is ``None`` when not known yet."""

    id: int
    fiscal_year: int
    source_id: int
    currency: str
    allocated_minor: int | None
    description: str
    notes: str | None


@dataclass(frozen=True)
class ExecutionRow:
    """A row of ``budget_execution``; the date is ISO text as stored."""

    id: int
    entry_id: int
    executed_on: str
    amount_minor: int
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


def _source_row(row: sqlite3.Row) -> SourceRow:
    return SourceRow(
        id=_int(row["id"]),
        code=_text(row["code"]),
        built_in=_int(row["built_in"]) == 1,
        label_pt_br=_opt_text(row["label_pt_br"]),
        label_en_us=_opt_text(row["label_en_us"]),
        label_es_es=_opt_text(row["label_es_es"]),
        active=_int(row["active"]) == 1,
    )


def _entry_row(row: sqlite3.Row) -> EntryRow:
    return EntryRow(
        id=_int(row["id"]),
        fiscal_year=_int(row["fiscal_year"]),
        source_id=_int(row["source_id"]),
        currency=_text(row["currency"]),
        allocated_minor=_opt_int(row["allocated_minor"]),
        description=_text(row["description"]),
        notes=_opt_text(row["notes"]),
    )


def _execution_row(row: sqlite3.Row) -> ExecutionRow:
    return ExecutionRow(
        id=_int(row["id"]),
        entry_id=_int(row["entry_id"]),
        executed_on=_text(row["executed_on"]),
        amount_minor=_int(row["amount_minor"]),
        note=_opt_text(row["note"]),
    )


def _new_id(new_id: int | None) -> int:
    if new_id is None:
        msg = "The new row has no id."
        raise RepositoryError(msg, "INSERT_NOT_FOUND")
    return new_id


# --------------------------------------------------------------------------- funding sources


def list_sources(conn: DatabaseConnection, *, include_inactive: bool = True) -> list[SourceRow]:
    """Funding sources ordered by code; inactive ones are included unless excluded."""
    where = "" if include_inactive else " WHERE active = 1"
    sql = f"SELECT {_SOURCE_COLUMNS} FROM funding_source{where} ORDER BY code"
    return [_source_row(row) for row in conn.execute(sql).fetchall()]


def get_source(conn: DatabaseConnection, source_id: int) -> SourceRow | None:
    sql = f"SELECT {_SOURCE_COLUMNS} FROM funding_source WHERE id = ?"
    row = conn.execute(sql, (source_id,)).fetchone()
    return None if row is None else _source_row(row)


def get_source_by_code(conn: DatabaseConnection, code: str) -> SourceRow | None:
    """The source with this code (natural key), or ``None``."""
    sql = f"SELECT {_SOURCE_COLUMNS} FROM funding_source WHERE code = ?"
    row = conn.execute(sql, (code,)).fetchone()
    return None if row is None else _source_row(row)


def source_codes(conn: DatabaseConnection) -> dict[int, str]:
    """``{source id: source code}`` for every source."""
    rows = conn.execute("SELECT id, code FROM funding_source").fetchall()
    return {_int(row["id"]): _text(row["code"]) for row in rows}


def source_in_use(conn: DatabaseConnection, source_id: int) -> bool:
    """Whether any budget entry uses the source."""
    sql = "SELECT 1 FROM budget_entry WHERE source_id = ? LIMIT 1"
    return conn.execute(sql, (source_id,)).fetchone() is not None


def _source_values(
    *,
    code: str,
    built_in: bool,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    active: bool,
) -> dict[str, object]:
    return {
        "code": code,
        "built_in": 1 if built_in else 0,
        "label_pt_br": label_pt_br,
        "label_en_us": label_en_us,
        "label_es_es": label_es_es,
        "active": 1 if active else 0,
    }


def insert_source(
    ctx: WriteContext,
    *,
    code: str,
    built_in: bool,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    active: bool,
) -> int:
    """Insert a funding source and return its id."""
    values = _source_values(
        code=code,
        built_in=built_in,
        label_pt_br=label_pt_br,
        label_en_us=label_en_us,
        label_es_es=label_es_es,
        active=active,
    )
    return _new_id(insert(ctx, _SOURCE, values))


def update_source(
    ctx: WriteContext,
    source_id: int,
    *,
    code: str,
    built_in: bool,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    active: bool,
) -> bool:
    """Set every column; returns whether anything changed (only then a log row)."""
    changes = _source_values(
        code=code,
        built_in=built_in,
        label_pt_br=label_pt_br,
        label_en_us=label_en_us,
        label_es_es=label_es_es,
        active=active,
    )
    return update(ctx, _SOURCE, source_id, changes)


def delete_source(ctx: WriteContext, source_id: int) -> int:
    """Delete a source; the database refuses (``ROW_IN_USE``) while an entry uses it."""
    return delete(ctx, _SOURCE, source_id)


# --------------------------------------------------------------------------- budget entries


def list_entries(conn: DatabaseConnection, fiscal_year: int | None = None) -> list[EntryRow]:
    """Entries ordered by fiscal year and id; optionally only one fiscal year."""
    if fiscal_year is None:
        sql = f"SELECT {_ENTRY_COLUMNS} FROM budget_entry ORDER BY fiscal_year, id"
        rows = conn.execute(sql).fetchall()
    else:
        sql = f"SELECT {_ENTRY_COLUMNS} FROM budget_entry WHERE fiscal_year = ? ORDER BY id"
        rows = conn.execute(sql, (fiscal_year,)).fetchall()
    return [_entry_row(row) for row in rows]


def get_entry(conn: DatabaseConnection, entry_id: int) -> EntryRow | None:
    sql = f"SELECT {_ENTRY_COLUMNS} FROM budget_entry WHERE id = ?"
    row = conn.execute(sql, (entry_id,)).fetchone()
    return None if row is None else _entry_row(row)


def get_entry_by_key(
    conn: DatabaseConnection,
    fiscal_year: int,
    source_code: str,
    currency: str,
    description: str,
) -> EntryRow | None:
    """The entry with this natural key (fiscal year, source CODE, currency, description)."""
    sql = (
        f"SELECT {_ENTRY_COLUMNS_E} FROM budget_entry AS e"
        " JOIN funding_source AS s ON s.id = e.source_id"
        " WHERE e.fiscal_year = ? AND s.code = ? AND e.currency = ? AND e.description = ?"
    )
    row = conn.execute(sql, (fiscal_year, source_code, currency, description)).fetchone()
    return None if row is None else _entry_row(row)


def _entry_values(
    *,
    fiscal_year: int,
    source_id: int,
    currency: str,
    allocated_minor: int | None,
    description: str,
    notes: str | None,
) -> dict[str, object]:
    return {
        "fiscal_year": fiscal_year,
        "source_id": source_id,
        "currency": currency,
        "allocated_minor": allocated_minor,
        "description": description,
        "notes": notes,
    }


def insert_entry(
    ctx: WriteContext,
    *,
    fiscal_year: int,
    source_id: int,
    currency: str,
    allocated_minor: int | None,
    description: str,
    notes: str | None,
) -> int:
    """Insert an entry and return its id."""
    values = _entry_values(
        fiscal_year=fiscal_year,
        source_id=source_id,
        currency=currency,
        allocated_minor=allocated_minor,
        description=description,
        notes=notes,
    )
    return _new_id(insert(ctx, _ENTRY, values))


def update_entry(
    ctx: WriteContext,
    entry_id: int,
    *,
    fiscal_year: int,
    source_id: int,
    currency: str,
    allocated_minor: int | None,
    description: str,
    notes: str | None,
) -> bool:
    """Set every editable column; returns whether anything changed."""
    changes = _entry_values(
        fiscal_year=fiscal_year,
        source_id=source_id,
        currency=currency,
        allocated_minor=allocated_minor,
        description=description,
        notes=notes,
    )
    return update(ctx, _ENTRY, entry_id, changes)


def delete_entry(ctx: WriteContext, entry_id: int) -> int:
    """Delete an entry; its execution rows go with it, each with its own ``delete`` log row."""
    return delete(ctx, _ENTRY, entry_id)


# --------------------------------------------------------------------------- execution rows


def list_executions(conn: DatabaseConnection, entry_id: int | None = None) -> list[ExecutionRow]:
    """The execution rows of one entry, or of all entries, by date, amount and id."""
    if entry_id is None:
        sql = (
            f"SELECT {_EXECUTION_COLUMNS} FROM budget_execution"
            " ORDER BY entry_id, executed_on, amount_minor, id"
        )
        rows = conn.execute(sql).fetchall()
    else:
        sql = (
            f"SELECT {_EXECUTION_COLUMNS} FROM budget_execution WHERE entry_id = ?"
            " ORDER BY executed_on, amount_minor, id"
        )
        rows = conn.execute(sql, (entry_id,)).fetchall()
    return [_execution_row(row) for row in rows]


def get_execution(conn: DatabaseConnection, execution_id: int) -> ExecutionRow | None:
    sql = f"SELECT {_EXECUTION_COLUMNS} FROM budget_execution WHERE id = ?"
    row = conn.execute(sql, (execution_id,)).fetchone()
    return None if row is None else _execution_row(row)


def get_execution_by_key(
    conn: DatabaseConnection, entry_id: int, executed_on: str, amount_minor: int
) -> ExecutionRow | None:
    """The execution row with this natural key (entry, date, amount)."""
    sql = (
        f"SELECT {_EXECUTION_COLUMNS} FROM budget_execution"
        " WHERE entry_id = ? AND executed_on = ? AND amount_minor = ?"
    )
    row = conn.execute(sql, (entry_id, executed_on, amount_minor)).fetchone()
    return None if row is None else _execution_row(row)


def insert_execution(
    ctx: WriteContext, *, entry_id: int, executed_on: str, amount_minor: int, note: str | None
) -> int:
    """Insert an execution row and return its id."""
    values: dict[str, object] = {
        "entry_id": entry_id,
        "executed_on": executed_on,
        "amount_minor": amount_minor,
        "note": note,
    }
    return _new_id(insert(ctx, _EXECUTION, values))


def update_execution(
    ctx: WriteContext,
    execution_id: int,
    *,
    executed_on: str,
    amount_minor: int,
    note: str | None,
) -> bool:
    """Set every editable column (the entry of a row never changes); returns whether it changed."""
    changes: dict[str, object] = {
        "executed_on": executed_on,
        "amount_minor": amount_minor,
        "note": note,
    }
    return update(ctx, _EXECUTION, execution_id, changes)


def delete_execution(ctx: WriteContext, execution_id: int) -> int:
    """Delete one execution row (``RowNotFoundError`` when there is none)."""
    return delete(ctx, _EXECUTION, execution_id)


# --------------------------------------------------------------------------- domain converters


def entry_to_domain(row: EntryRow, codes: Mapping[int, str]) -> BudgetEntry:
    """The domain entry; it carries the source CODE. An unknown source id becomes ``#<id>``."""
    return BudgetEntry(
        id=row.id,
        fiscal_year=row.fiscal_year,
        source_code=codes.get(row.source_id, f"#{row.source_id}"),
        currency=row.currency,
        allocated_minor=row.allocated_minor,
    )


def execution_to_domain(row: ExecutionRow) -> BudgetExecution:
    """The domain execution row."""
    return BudgetExecution(
        entry_id=row.entry_id,
        executed_on=parse_iso_date(row.executed_on),
        amount_minor=row.amount_minor,
    )
