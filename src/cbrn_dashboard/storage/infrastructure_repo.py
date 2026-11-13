# SPDX-License-Identifier: GPL-3.0-or-later
"""Storage of asset types, assets, status events and maintenance events (T3.3).

Reads are plain parameterised ``SELECT`` statements. Every write goes through the repository
helpers (:func:`~cbrn_dashboard.storage.repository.insert`, ``update`` and ``delete``), so each
affected row gets its ``change_log`` row in the same transaction. This module checks no business
rule: that is the service's job (``services/infrastructure.py``). It also holds the one place where
rows become domain objects.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from cbrn_dashboard.domain.dates import parse_iso_date
from cbrn_dashboard.domain.infrastructure import (
    Asset,
    AssetStatus,
    AssetType,
    MaintenanceEvent,
    MaintenanceKind,
    StatusEvent,
)
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import RepositoryError, WriteContext, delete, insert, update

__all__ = [
    "AssetRow",
    "AssetTypeRow",
    "MaintenanceRow",
    "StatusEventRow",
    "asset_to_domain",
    "delete_asset",
    "delete_maintenance",
    "delete_status_event",
    "delete_type",
    "get_asset",
    "get_asset_by_tag",
    "get_maintenance",
    "get_maintenance_by_key",
    "get_status_event",
    "get_status_event_by_date",
    "get_type",
    "get_type_by_code",
    "insert_asset",
    "insert_maintenance",
    "insert_status_event",
    "insert_type",
    "list_assets",
    "list_maintenance",
    "list_status_events",
    "list_types",
    "maintenance_to_domain",
    "status_event_to_domain",
    "type_in_use",
    "type_to_domain",
    "update_asset",
    "update_maintenance",
    "update_status_event",
    "update_type",
]

_TYPE = "asset_type"
_ASSET = "asset"
_STATUS = "asset_status_event"
_MAINTENANCE = "maintenance_event"

_TYPE_COLUMNS = (
    "id, code, built_in, label_pt_br, label_en_us, label_es_es,"
    " default_maintenance_interval_days, active"
)
_ASSET_COLUMNS = (
    "id, type_id, tag, description, location, in_service_from, in_service_until,"
    " maintenance_interval_days, notes"
)
_STATUS_COLUMNS = "id, asset_id, effective_on, status, note"
_MAINTENANCE_COLUMNS = "id, asset_id, performed_on, kind, next_due_on, note"


# --------------------------------------------------------------------------- rows


@dataclass(frozen=True)
class AssetTypeRow:
    """A row of ``asset_type``."""

    id: int
    code: str
    built_in: bool
    label_pt_br: str | None
    label_en_us: str | None
    label_es_es: str | None
    default_maintenance_interval_days: int | None
    active: bool


@dataclass(frozen=True)
class AssetRow:
    """A row of ``asset``; the dates are ISO text as stored."""

    id: int
    type_id: int
    tag: str
    description: str | None
    location: str | None
    in_service_from: str
    in_service_until: str | None
    maintenance_interval_days: int | None
    notes: str | None


@dataclass(frozen=True)
class StatusEventRow:
    """A row of ``asset_status_event``."""

    id: int
    asset_id: int
    effective_on: str
    status: str
    note: str | None


@dataclass(frozen=True)
class MaintenanceRow:
    """A row of ``maintenance_event``."""

    id: int
    asset_id: int
    performed_on: str
    kind: str
    next_due_on: str | None
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


def _type_row(row: sqlite3.Row) -> AssetTypeRow:
    return AssetTypeRow(
        id=_int(row["id"]),
        code=_text(row["code"]),
        built_in=_int(row["built_in"]) == 1,
        label_pt_br=_opt_text(row["label_pt_br"]),
        label_en_us=_opt_text(row["label_en_us"]),
        label_es_es=_opt_text(row["label_es_es"]),
        default_maintenance_interval_days=_opt_int(row["default_maintenance_interval_days"]),
        active=_int(row["active"]) == 1,
    )


def _asset_row(row: sqlite3.Row) -> AssetRow:
    return AssetRow(
        id=_int(row["id"]),
        type_id=_int(row["type_id"]),
        tag=_text(row["tag"]),
        description=_opt_text(row["description"]),
        location=_opt_text(row["location"]),
        in_service_from=_text(row["in_service_from"]),
        in_service_until=_opt_text(row["in_service_until"]),
        maintenance_interval_days=_opt_int(row["maintenance_interval_days"]),
        notes=_opt_text(row["notes"]),
    )


def _status_row(row: sqlite3.Row) -> StatusEventRow:
    return StatusEventRow(
        id=_int(row["id"]),
        asset_id=_int(row["asset_id"]),
        effective_on=_text(row["effective_on"]),
        status=_text(row["status"]),
        note=_opt_text(row["note"]),
    )


def _maintenance_row(row: sqlite3.Row) -> MaintenanceRow:
    return MaintenanceRow(
        id=_int(row["id"]),
        asset_id=_int(row["asset_id"]),
        performed_on=_text(row["performed_on"]),
        kind=_text(row["kind"]),
        next_due_on=_opt_text(row["next_due_on"]),
        note=_opt_text(row["note"]),
    )


def _new_id(new_id: int | None) -> int:
    if new_id is None:
        msg = "The new row has no id."
        raise RepositoryError(msg, "INSERT_NOT_FOUND")
    return new_id


# --------------------------------------------------------------------------- asset types


def list_types(conn: DatabaseConnection, *, include_inactive: bool = True) -> list[AssetTypeRow]:
    """Asset types ordered by code; inactive ones are included unless excluded."""
    where = "" if include_inactive else " WHERE active = 1"
    sql = f"SELECT {_TYPE_COLUMNS} FROM asset_type{where} ORDER BY code"
    return [_type_row(row) for row in conn.execute(sql).fetchall()]


def get_type(conn: DatabaseConnection, type_id: int) -> AssetTypeRow | None:
    sql = f"SELECT {_TYPE_COLUMNS} FROM asset_type WHERE id = ?"
    row = conn.execute(sql, (type_id,)).fetchone()
    return None if row is None else _type_row(row)


def get_type_by_code(conn: DatabaseConnection, code: str) -> AssetTypeRow | None:
    sql = f"SELECT {_TYPE_COLUMNS} FROM asset_type WHERE code = ?"
    row = conn.execute(sql, (code,)).fetchone()
    return None if row is None else _type_row(row)


def type_in_use(conn: DatabaseConnection, type_id: int) -> bool:
    """Whether any asset uses the type."""
    sql = "SELECT 1 FROM asset WHERE type_id = ? LIMIT 1"
    return conn.execute(sql, (type_id,)).fetchone() is not None


def insert_type(
    ctx: WriteContext,
    *,
    code: str,
    built_in: bool,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    default_maintenance_interval_days: int | None,
    active: bool,
) -> int:
    """Insert an asset type and return its id."""
    values: dict[str, object] = {
        "code": code,
        "built_in": 1 if built_in else 0,
        "label_pt_br": label_pt_br,
        "label_en_us": label_en_us,
        "label_es_es": label_es_es,
        "default_maintenance_interval_days": default_maintenance_interval_days,
        "active": 1 if active else 0,
    }
    return _new_id(insert(ctx, _TYPE, values))


def update_type(
    ctx: WriteContext,
    type_id: int,
    *,
    code: str,
    label_pt_br: str | None,
    label_en_us: str | None,
    label_es_es: str | None,
    default_maintenance_interval_days: int | None,
    active: bool,
) -> bool:
    """Set every editable column (never ``built_in``); returns whether anything changed."""
    changes: dict[str, object] = {
        "code": code,
        "label_pt_br": label_pt_br,
        "label_en_us": label_en_us,
        "label_es_es": label_es_es,
        "default_maintenance_interval_days": default_maintenance_interval_days,
        "active": 1 if active else 0,
    }
    return update(ctx, _TYPE, type_id, changes)


def delete_type(ctx: WriteContext, type_id: int) -> int:
    """Delete a type; the database refuses (``ROW_IN_USE``) while assets use it."""
    return delete(ctx, _TYPE, type_id)


# --------------------------------------------------------------------------- assets


def list_assets(conn: DatabaseConnection, type_id: int | None = None) -> list[AssetRow]:
    """The assets of one type, or all of them, ordered by tag."""
    if type_id is None:
        sql = f"SELECT {_ASSET_COLUMNS} FROM asset ORDER BY tag"
        rows = conn.execute(sql).fetchall()
    else:
        sql = f"SELECT {_ASSET_COLUMNS} FROM asset WHERE type_id = ? ORDER BY tag"
        rows = conn.execute(sql, (type_id,)).fetchall()
    return [_asset_row(row) for row in rows]


def get_asset(conn: DatabaseConnection, asset_id: int) -> AssetRow | None:
    sql = f"SELECT {_ASSET_COLUMNS} FROM asset WHERE id = ?"
    row = conn.execute(sql, (asset_id,)).fetchone()
    return None if row is None else _asset_row(row)


def get_asset_by_tag(conn: DatabaseConnection, tag: str) -> AssetRow | None:
    sql = f"SELECT {_ASSET_COLUMNS} FROM asset WHERE tag = ?"
    row = conn.execute(sql, (tag,)).fetchone()
    return None if row is None else _asset_row(row)


def _asset_values(
    *,
    type_id: int,
    tag: str,
    description: str | None,
    location: str | None,
    in_service_from: str,
    in_service_until: str | None,
    maintenance_interval_days: int | None,
    notes: str | None,
) -> dict[str, object]:
    return {
        "type_id": type_id,
        "tag": tag,
        "description": description,
        "location": location,
        "in_service_from": in_service_from,
        "in_service_until": in_service_until,
        "maintenance_interval_days": maintenance_interval_days,
        "notes": notes,
    }


def insert_asset(
    ctx: WriteContext,
    *,
    type_id: int,
    tag: str,
    description: str | None,
    location: str | None,
    in_service_from: str,
    in_service_until: str | None,
    maintenance_interval_days: int | None,
    notes: str | None,
) -> int:
    """Insert an asset and return its id."""
    values = _asset_values(
        type_id=type_id,
        tag=tag,
        description=description,
        location=location,
        in_service_from=in_service_from,
        in_service_until=in_service_until,
        maintenance_interval_days=maintenance_interval_days,
        notes=notes,
    )
    return _new_id(insert(ctx, _ASSET, values))


def update_asset(
    ctx: WriteContext,
    asset_id: int,
    *,
    type_id: int,
    tag: str,
    description: str | None,
    location: str | None,
    in_service_from: str,
    in_service_until: str | None,
    maintenance_interval_days: int | None,
    notes: str | None,
) -> bool:
    """Set every editable column; returns whether anything changed."""
    changes = _asset_values(
        type_id=type_id,
        tag=tag,
        description=description,
        location=location,
        in_service_from=in_service_from,
        in_service_until=in_service_until,
        maintenance_interval_days=maintenance_interval_days,
        notes=notes,
    )
    return update(ctx, _ASSET, asset_id, changes)


def delete_asset(ctx: WriteContext, asset_id: int) -> int:
    """Delete an asset; its status and maintenance events go with it, each with its own log row."""
    return delete(ctx, _ASSET, asset_id)


# --------------------------------------------------------------------------- status events


def list_status_events(
    conn: DatabaseConnection, asset_id: int | None = None
) -> list[StatusEventRow]:
    """The status events of one asset, or of all assets, by asset, date and id."""
    if asset_id is None:
        sql = (
            f"SELECT {_STATUS_COLUMNS} FROM asset_status_event ORDER BY asset_id, effective_on, id"
        )
        rows = conn.execute(sql).fetchall()
    else:
        sql = (
            f"SELECT {_STATUS_COLUMNS} FROM asset_status_event WHERE asset_id = ?"
            " ORDER BY effective_on, id"
        )
        rows = conn.execute(sql, (asset_id,)).fetchall()
    return [_status_row(row) for row in rows]


def get_status_event(conn: DatabaseConnection, event_id: int) -> StatusEventRow | None:
    sql = f"SELECT {_STATUS_COLUMNS} FROM asset_status_event WHERE id = ?"
    row = conn.execute(sql, (event_id,)).fetchone()
    return None if row is None else _status_row(row)


def get_status_event_by_date(
    conn: DatabaseConnection, asset_id: int, effective_on: str
) -> StatusEventRow | None:
    """The status event of an asset on a day (natural key)."""
    sql = (
        f"SELECT {_STATUS_COLUMNS} FROM asset_status_event WHERE asset_id = ? AND effective_on = ?"
    )
    row = conn.execute(sql, (asset_id, effective_on)).fetchone()
    return None if row is None else _status_row(row)


def insert_status_event(
    ctx: WriteContext, *, asset_id: int, effective_on: str, status: str, note: str | None
) -> int:
    """Insert a status event and return its id."""
    values: dict[str, object] = {
        "asset_id": asset_id,
        "effective_on": effective_on,
        "status": status,
        "note": note,
    }
    return _new_id(insert(ctx, _STATUS, values))


def update_status_event(
    ctx: WriteContext,
    event_id: int,
    *,
    effective_on: str,
    status: str,
    note: str | None,
) -> bool:
    """Set the editable columns of a status event; returns whether anything changed."""
    changes: dict[str, object] = {"effective_on": effective_on, "status": status, "note": note}
    return update(ctx, _STATUS, event_id, changes)


def delete_status_event(ctx: WriteContext, event_id: int) -> int:
    return delete(ctx, _STATUS, event_id)


# --------------------------------------------------------------------------- maintenance events


def list_maintenance(conn: DatabaseConnection, asset_id: int | None = None) -> list[MaintenanceRow]:
    """The maintenance events of one asset, or of all assets, by asset, date, kind and id."""
    if asset_id is None:
        sql = (
            f"SELECT {_MAINTENANCE_COLUMNS} FROM maintenance_event"
            " ORDER BY asset_id, performed_on, kind, id"
        )
        rows = conn.execute(sql).fetchall()
    else:
        sql = (
            f"SELECT {_MAINTENANCE_COLUMNS} FROM maintenance_event WHERE asset_id = ?"
            " ORDER BY performed_on, kind, id"
        )
        rows = conn.execute(sql, (asset_id,)).fetchall()
    return [_maintenance_row(row) for row in rows]


def get_maintenance(conn: DatabaseConnection, maintenance_id: int) -> MaintenanceRow | None:
    sql = f"SELECT {_MAINTENANCE_COLUMNS} FROM maintenance_event WHERE id = ?"
    row = conn.execute(sql, (maintenance_id,)).fetchone()
    return None if row is None else _maintenance_row(row)


def get_maintenance_by_key(
    conn: DatabaseConnection, asset_id: int, performed_on: str, kind: str
) -> MaintenanceRow | None:
    """The maintenance event of an asset on a day and kind (natural key)."""
    sql = (
        f"SELECT {_MAINTENANCE_COLUMNS} FROM maintenance_event"
        " WHERE asset_id = ? AND performed_on = ? AND kind = ?"
    )
    row = conn.execute(sql, (asset_id, performed_on, kind)).fetchone()
    return None if row is None else _maintenance_row(row)


def insert_maintenance(
    ctx: WriteContext,
    *,
    asset_id: int,
    performed_on: str,
    kind: str,
    next_due_on: str | None,
    note: str | None,
) -> int:
    """Insert a maintenance event and return its id."""
    values: dict[str, object] = {
        "asset_id": asset_id,
        "performed_on": performed_on,
        "kind": kind,
        "next_due_on": next_due_on,
        "note": note,
    }
    return _new_id(insert(ctx, _MAINTENANCE, values))


def update_maintenance(
    ctx: WriteContext,
    maintenance_id: int,
    *,
    performed_on: str,
    kind: str,
    next_due_on: str | None,
    note: str | None,
) -> bool:
    """Set the editable columns of a maintenance event; returns whether anything changed."""
    changes: dict[str, object] = {
        "performed_on": performed_on,
        "kind": kind,
        "next_due_on": next_due_on,
        "note": note,
    }
    return update(ctx, _MAINTENANCE, maintenance_id, changes)


def delete_maintenance(ctx: WriteContext, maintenance_id: int) -> int:
    return delete(ctx, _MAINTENANCE, maintenance_id)


# --------------------------------------------------------------------------- domain converters


def type_to_domain(row: AssetTypeRow) -> AssetType:
    """The domain asset type for a row."""
    return AssetType(
        code=row.code, default_maintenance_interval_days=row.default_maintenance_interval_days
    )


def asset_to_domain(row: AssetRow, type_codes: Mapping[int, str]) -> Asset:
    """The domain asset; it carries the TYPE CODE (an unknown type id becomes ``#<id>``)."""
    return Asset(
        id=row.id,
        tag=row.tag,
        type_code=type_codes.get(row.type_id, f"#{row.type_id}"),
        in_service_from=parse_iso_date(row.in_service_from),
        in_service_until=(
            None if row.in_service_until is None else parse_iso_date(row.in_service_until)
        ),
        maintenance_interval_days=row.maintenance_interval_days,
    )


def status_event_to_domain(row: StatusEventRow) -> StatusEvent:
    """The domain status event for a row."""
    return StatusEvent(
        asset_id=row.asset_id,
        effective_on=parse_iso_date(row.effective_on),
        status=AssetStatus(row.status),
    )


def maintenance_to_domain(row: MaintenanceRow) -> MaintenanceEvent:
    """The domain maintenance event for a row."""
    return MaintenanceEvent(
        asset_id=row.asset_id,
        performed_on=parse_iso_date(row.performed_on),
        kind=MaintenanceKind(row.kind),
        next_due_on=None if row.next_due_on is None else parse_iso_date(row.next_due_on),
    )
