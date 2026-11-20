# SPDX-License-Identifier: GPL-3.0-or-later
"""Storage of stock item types, lots and movements (PLAN T11.5).

Reads are plain parameterised ``SELECT`` statements. Every write goes through the repository
helpers (:func:`~cbrn_dashboard.storage.repository.insert`, ``update`` and ``delete``), so each
affected row gets its ``change_log`` row in the same transaction. Deleting a lot cascades to its
movements (``ON DELETE CASCADE``): the ``delete`` helper finds them first and logs one ``delete``
row for the lot and one for every movement, so this module logs nothing by hand. This module
checks no business rule: that is the service's job (``services/stock.py``). It also holds the one
place where rows become domain objects.

The movement functions cover the reads, the natural-key lookup and insert, update and delete of one
movement (T11.6); the service checks the balance rule before it calls them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from cbrn_dashboard.domain.dates import parse_iso_date
from cbrn_dashboard.domain.stock import Lot, Movement, MovementKind, StockCategory, StockType
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import RepositoryError, WriteContext, delete, insert, update

__all__ = [
    "StockLotRow",
    "StockMovementRow",
    "StockTypeRow",
    "code_in_stored_dimensions",
    "delete_lot",
    "delete_movement",
    "delete_type",
    "get_lot",
    "get_lot_by_code",
    "get_movement",
    "get_movement_by_key",
    "get_type",
    "get_type_by_code",
    "insert_lot",
    "insert_movement",
    "insert_type",
    "list_lots",
    "list_movements",
    "list_types",
    "lot_in_use",
    "lot_to_domain",
    "movement_to_domain",
    "type_in_use",
    "type_to_domain",
    "update_lot",
    "update_movement",
    "update_type",
]

_TYPE = "stock_item_type"
_LOT = "stock_lot"
_MOVEMENT = "stock_movement"

_TYPE_COLUMNS = (
    "id, code, built_in, category, label_pt_br, label_en_us, label_es_es, minimum_quantity, active"
)
_LOT_COLUMNS = "id, type_id, lot_code, expires_on, unit_price_minor, currency, notes"
_MOVEMENT_COLUMNS = "id, lot_id, moved_on, kind, quantity, reference, note"


# --------------------------------------------------------------------------- rows


@dataclass(frozen=True)
class StockTypeRow:
    """A row of ``stock_item_type``; ``category`` is the stored text."""

    id: int
    code: str
    built_in: bool
    category: str
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    minimum_quantity: int | None
    active: bool


@dataclass(frozen=True)
class StockLotRow:
    """A row of ``stock_lot``; ``expires_on`` is ISO text as stored (``None`` = no expiry)."""

    id: int
    type_id: int
    lot_code: str
    expires_on: str | None
    unit_price_minor: int | None
    currency: str | None
    notes: str | None


@dataclass(frozen=True)
class StockMovementRow:
    """A row of ``stock_movement``; ``reference`` is ``''`` (never NULL) when there is none."""

    id: int
    lot_id: int
    moved_on: str
    kind: str
    quantity: int
    reference: str
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


def _new_id(new_id: int | None) -> int:
    if new_id is None:
        msg = "The new row has no id."
        raise RepositoryError(msg, "INSERT_NOT_FOUND")
    return new_id


def _type_row(row: sqlite3.Row) -> StockTypeRow:
    return StockTypeRow(
        id=_int(row["id"]),
        code=_text(row["code"]),
        built_in=_int(row["built_in"]) == 1,
        category=_text(row["category"]),
        label_pt_br=_opt_text(row["label_pt_br"]),
        label_en_us=_opt_text(row["label_en_us"]),
        label_es_es=_opt_text(row["label_es_es"]),
        minimum_quantity=_opt_int(row["minimum_quantity"]),
        active=_int(row["active"]) == 1,
    )


def _lot_row(row: sqlite3.Row) -> StockLotRow:
    return StockLotRow(
        id=_int(row["id"]),
        type_id=_int(row["type_id"]),
        lot_code=_text(row["lot_code"]),
        expires_on=_opt_text(row["expires_on"]),
        unit_price_minor=_opt_int(row["unit_price_minor"]),
        currency=_opt_text(row["currency"]),
        notes=_opt_text(row["notes"]),
    )


def _movement_row(row: sqlite3.Row) -> StockMovementRow:
    return StockMovementRow(
        id=_int(row["id"]),
        lot_id=_int(row["lot_id"]),
        moved_on=_text(row["moved_on"]),
        kind=_text(row["kind"]),
        quantity=_int(row["quantity"]),
        reference=_text(row["reference"]),
        note=_opt_text(row["note"]),
    )


# --------------------------------------------------------------------------- item types


def list_types(conn: DatabaseConnection, *, include_inactive: bool = True) -> list[StockTypeRow]:
    """Item types ordered by code; inactive ones are included unless excluded."""
    where = "" if include_inactive else " WHERE active = 1"
    sql = f"SELECT {_TYPE_COLUMNS} FROM stock_item_type{where} ORDER BY code"
    return [_type_row(row) for row in conn.execute(sql).fetchall()]


def get_type(conn: DatabaseConnection, type_id: int) -> StockTypeRow | None:
    sql = f"SELECT {_TYPE_COLUMNS} FROM stock_item_type WHERE id = ?"
    row = conn.execute(sql, (type_id,)).fetchone()
    return None if row is None else _type_row(row)


def get_type_by_code(conn: DatabaseConnection, code: str) -> StockTypeRow | None:
    sql = f"SELECT {_TYPE_COLUMNS} FROM stock_item_type WHERE code = ?"
    row = conn.execute(sql, (code,)).fetchone()
    return None if row is None else _type_row(row)


def type_in_use(conn: DatabaseConnection, type_id: int) -> bool:
    """Whether any lot uses the type."""
    sql = "SELECT 1 FROM stock_lot WHERE type_id = ? LIMIT 1"
    return conn.execute(sql, (type_id,)).fetchone() is not None


def code_in_stored_dimensions(conn: DatabaseConnection, code: str) -> bool:
    """Whether ``item=<code>`` is a part of a stored snapshot reading or indicator target.

    The dimension text is ``key=value;key=value`` (sorted keys); the stock indicators use the
    ``item`` key for the code of an item type. Such a row names the type by its code, so the code
    must not change afterwards. The match is exact (case included), on a whole part.
    """
    needle = f";item={code};"
    for table in ("readiness_snapshot_value", "indicator_target"):
        sql = f"SELECT 1 FROM {table} WHERE instr(';' || dimension || ';', ?) > 0 LIMIT 1"
        if conn.execute(sql, (needle,)).fetchone() is not None:
            return True
    return False


def insert_type(
    ctx: WriteContext,
    *,
    code: str,
    built_in: bool,
    category: str,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    minimum_quantity: int | None,
    active: bool,
) -> int:
    """Insert an item type and return its id."""
    values: dict[str, object] = {
        "code": code,
        "built_in": 1 if built_in else 0,
        "category": category,
        "label_pt_br": label_pt_br,
        "label_en_us": label_en_us,
        "label_es_es": label_es_es,
        "minimum_quantity": minimum_quantity,
        "active": 1 if active else 0,
    }
    return _new_id(insert(ctx, _TYPE, values))


def update_type(
    ctx: WriteContext,
    type_id: int,
    *,
    code: str,
    category: str,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    minimum_quantity: int | None,
    active: bool,
) -> bool:
    """Set every editable column (never ``built_in``); returns whether anything changed."""
    changes: dict[str, object] = {
        "code": code,
        "category": category,
        "label_pt_br": label_pt_br,
        "label_en_us": label_en_us,
        "label_es_es": label_es_es,
        "minimum_quantity": minimum_quantity,
        "active": 1 if active else 0,
    }
    return update(ctx, _TYPE, type_id, changes)


def delete_type(ctx: WriteContext, type_id: int) -> int:
    """Delete a type; the database refuses (``ROW_IN_USE``) while lots use it."""
    return delete(ctx, _TYPE, type_id)


# --------------------------------------------------------------------------- lots


def list_lots(conn: DatabaseConnection, type_id: int | None = None) -> list[StockLotRow]:
    """The lots of one type, or all of them, ordered by type id, lot code and id."""
    if type_id is None:
        sql = f"SELECT {_LOT_COLUMNS} FROM stock_lot ORDER BY type_id, lot_code, id"
        rows = conn.execute(sql).fetchall()
    else:
        sql = f"SELECT {_LOT_COLUMNS} FROM stock_lot WHERE type_id = ? ORDER BY lot_code, id"
        rows = conn.execute(sql, (type_id,)).fetchall()
    return [_lot_row(row) for row in rows]


def get_lot(conn: DatabaseConnection, lot_id: int) -> StockLotRow | None:
    sql = f"SELECT {_LOT_COLUMNS} FROM stock_lot WHERE id = ?"
    row = conn.execute(sql, (lot_id,)).fetchone()
    return None if row is None else _lot_row(row)


def get_lot_by_code(conn: DatabaseConnection, type_id: int, lot_code: str) -> StockLotRow | None:
    """The lot of a type with this code (natural key)."""
    sql = f"SELECT {_LOT_COLUMNS} FROM stock_lot WHERE type_id = ? AND lot_code = ?"
    row = conn.execute(sql, (type_id, lot_code)).fetchone()
    return None if row is None else _lot_row(row)


def lot_in_use(conn: DatabaseConnection, lot_id: int) -> bool:
    """Whether the lot has any movement."""
    sql = "SELECT 1 FROM stock_movement WHERE lot_id = ? LIMIT 1"
    return conn.execute(sql, (lot_id,)).fetchone() is not None


def _lot_values(
    *,
    type_id: int,
    lot_code: str,
    expires_on: str | None,
    unit_price_minor: int | None,
    currency: str | None,
    notes: str | None,
) -> dict[str, object]:
    return {
        "type_id": type_id,
        "lot_code": lot_code,
        "expires_on": expires_on,
        "unit_price_minor": unit_price_minor,
        "currency": currency,
        "notes": notes,
    }


def insert_lot(
    ctx: WriteContext,
    *,
    type_id: int,
    lot_code: str,
    expires_on: str | None,
    unit_price_minor: int | None,
    currency: str | None,
    notes: str | None,
) -> int:
    """Insert a lot and return its id."""
    values = _lot_values(
        type_id=type_id,
        lot_code=lot_code,
        expires_on=expires_on,
        unit_price_minor=unit_price_minor,
        currency=currency,
        notes=notes,
    )
    return _new_id(insert(ctx, _LOT, values))


def update_lot(
    ctx: WriteContext,
    lot_id: int,
    *,
    type_id: int,
    lot_code: str,
    expires_on: str | None,
    unit_price_minor: int | None,
    currency: str | None,
    notes: str | None,
) -> bool:
    """Set every editable column; returns whether anything changed."""
    changes = _lot_values(
        type_id=type_id,
        lot_code=lot_code,
        expires_on=expires_on,
        unit_price_minor=unit_price_minor,
        currency=currency,
        notes=notes,
    )
    return update(ctx, _LOT, lot_id, changes)


def delete_lot(ctx: WriteContext, lot_id: int) -> int:
    """Delete a lot; its movements go with it, each with its own ``delete`` log row.

    Returns the number of rows deleted (the lot and its movements).
    """
    return delete(ctx, _LOT, lot_id)


# --------------------------------------------------------------------------- movements


def list_movements(conn: DatabaseConnection, lot_id: int | None = None) -> list[StockMovementRow]:
    """The movements of one lot, or of all lots, by lot, date and id."""
    if lot_id is None:
        sql = f"SELECT {_MOVEMENT_COLUMNS} FROM stock_movement ORDER BY lot_id, moved_on, id"
        rows = conn.execute(sql).fetchall()
    else:
        sql = (
            f"SELECT {_MOVEMENT_COLUMNS} FROM stock_movement WHERE lot_id = ? ORDER BY moved_on, id"
        )
        rows = conn.execute(sql, (lot_id,)).fetchall()
    return [_movement_row(row) for row in rows]


def get_movement(conn: DatabaseConnection, movement_id: int) -> StockMovementRow | None:
    sql = f"SELECT {_MOVEMENT_COLUMNS} FROM stock_movement WHERE id = ?"
    row = conn.execute(sql, (movement_id,)).fetchone()
    return None if row is None else _movement_row(row)


def insert_movement(
    ctx: WriteContext,
    *,
    lot_id: int,
    moved_on: str,
    kind: str,
    quantity: int,
    reference: str,
    note: str | None,
) -> int:
    """Insert a movement and return its id (an empty reference is ``''``)."""
    values: dict[str, object] = {
        "lot_id": lot_id,
        "moved_on": moved_on,
        "kind": kind,
        "quantity": quantity,
        "reference": reference,
        "note": note,
    }
    return _new_id(insert(ctx, _MOVEMENT, values))


def get_movement_by_key(
    conn: DatabaseConnection,
    lot_id: int,
    moved_on: str,
    kind: str,
    quantity: int,
    reference: str,
) -> StockMovementRow | None:
    """The movement with this natural key (lot, date, kind, quantity, reference), if any."""
    sql = (
        f"SELECT {_MOVEMENT_COLUMNS} FROM stock_movement "
        "WHERE lot_id = ? AND moved_on = ? AND kind = ? AND quantity = ? AND reference = ?"
    )
    row = conn.execute(sql, (lot_id, moved_on, kind, quantity, reference)).fetchone()
    return None if row is None else _movement_row(row)


def update_movement(
    ctx: WriteContext,
    movement_id: int,
    *,
    moved_on: str,
    kind: str,
    quantity: int,
    reference: str,
    note: str | None,
) -> bool:
    """Set every editable column (never the lot); returns whether anything changed."""
    changes: dict[str, object] = {
        "moved_on": moved_on,
        "kind": kind,
        "quantity": quantity,
        "reference": reference,
        "note": note,
    }
    return update(ctx, _MOVEMENT, movement_id, changes)


def delete_movement(ctx: WriteContext, movement_id: int) -> int:
    """Delete one movement (logged as a ``delete`` row); returns the number of rows deleted."""
    return delete(ctx, _MOVEMENT, movement_id)


# --------------------------------------------------------------------------- domain converters


def type_to_domain(row: StockTypeRow) -> StockType:
    """The domain item type for a row."""
    return StockType(
        id=row.id,
        code=row.code,
        category=StockCategory(row.category),
        minimum_quantity=row.minimum_quantity,
        active=row.active,
    )


def lot_to_domain(row: StockLotRow, type_codes: Mapping[int, str]) -> Lot:
    """The domain lot; it carries the TYPE CODE (an unknown type id becomes ``#<id>``)."""
    return Lot(
        id=row.id,
        type_code=type_codes.get(row.type_id, f"#{row.type_id}"),
        lot_code=row.lot_code,
        expires_on=None if row.expires_on is None else parse_iso_date(row.expires_on),
        unit_price_minor=row.unit_price_minor,
        currency=row.currency,
    )


def movement_to_domain(row: StockMovementRow) -> Movement:
    """The domain movement for a row."""
    return Movement(
        id=row.id,
        lot_id=row.lot_id,
        moved_on=parse_iso_date(row.moved_on),
        kind=MovementKind(row.kind),
        quantity=row.quantity,
    )
