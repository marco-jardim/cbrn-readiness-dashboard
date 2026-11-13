# SPDX-License-Identifier: GPL-3.0-or-later
"""Storage of the readiness snapshots (PLAN.md T8.1, D13, D21, K13, R31).

Reads are plain parameterised ``SELECT`` statements. Every write goes through the repository
helpers (:func:`~cbrn_dashboard.storage.repository.insert`), so each row gets its ``change_log``
row in the same transaction. The three tables are append-only (migration 0007): this module offers
no update and no delete, and the triggers would refuse them anyway. A snapshot that must not count
is withdrawn by appending a ``snapshot_withdrawal`` row.

This module checks no business rule (origin, hash, read-only): that is the service's job
(``services/snapshots.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import RepositoryError, WriteContext, insert

__all__ = [
    "SnapshotRow",
    "SnapshotValueRow",
    "get_snapshot",
    "insert_snapshot",
    "insert_values",
    "insert_withdrawal",
    "list_snapshots",
    "list_values",
    "monthly_taken_times",
]

_SNAPSHOT = "readiness_snapshot"
_VALUE = "readiness_snapshot_value"
_WITHDRAWAL = "snapshot_withdrawal"

_SNAPSHOT_SELECT = (
    "SELECT s.id AS id, s.taken_at_utc AS taken_at_utc, s.as_of AS as_of, s.origin AS origin,"
    " s.app_version AS app_version, s.config_hash AS config_hash, s.config_json AS config_json,"
    " s.note AS note, w.id AS withdrawal_id, w.withdrawn_at_utc AS withdrawn_at_utc,"
    " w.reason AS withdrawal_reason, w.operator AS withdrawal_operator"
    " FROM readiness_snapshot AS s"
    " LEFT JOIN snapshot_withdrawal AS w ON w.snapshot_id = s.id"
)
_SNAPSHOT_ORDER = " ORDER BY s.taken_at_utc DESC, s.id DESC"


@dataclass(frozen=True)
class SnapshotRow:
    """A row of ``readiness_snapshot`` with its withdrawal (``withdrawn_at_utc`` is ``None`` when
    the snapshot has not been withdrawn)."""

    id: int
    taken_at_utc: str
    as_of: str
    origin: str
    app_version: str
    config_hash: str
    config_json: str
    note: str | None
    withdrawn_at_utc: str | None
    withdrawal_reason: str | None
    withdrawal_operator: str | None

    @property
    def withdrawn(self) -> bool:
        return self.withdrawn_at_utc is not None


@dataclass(frozen=True)
class SnapshotValueRow:
    """A row of ``readiness_snapshot_value``; ``value`` is ``None`` when there was no data."""

    snapshot_id: int
    indicator_code: str
    dimension: str
    value: float | None
    status: str
    warning_value: float | None
    critical_value: float | None


# --------------------------------------------------------------------------- column readers


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    msg = "Expected a text column."
    raise RepositoryError(msg, "UNEXPECTED_COLUMN_TYPE")


def _opt_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    msg = "Expected an integer column."
    raise RepositoryError(msg, "UNEXPECTED_COLUMN_TYPE")


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    msg = "Expected a real column."
    raise RepositoryError(msg, "UNEXPECTED_COLUMN_TYPE")


def _snapshot_row(row: Mapping[str, object]) -> SnapshotRow:
    # ``row`` is a ``sqlite3.Row`` (the connection's row factory): columns are read by name.
    return SnapshotRow(
        id=_int(row["id"]),
        taken_at_utc=_text(row["taken_at_utc"]),
        as_of=_text(row["as_of"]),
        origin=_text(row["origin"]),
        app_version=_text(row["app_version"]),
        config_hash=_text(row["config_hash"]),
        config_json=_text(row["config_json"]),
        note=_opt_text(row["note"]),
        withdrawn_at_utc=_opt_text(row["withdrawn_at_utc"]),
        withdrawal_reason=_opt_text(row["withdrawal_reason"]),
        withdrawal_operator=_opt_text(row["withdrawal_operator"]),
    )


# --------------------------------------------------------------------------- reads


def list_snapshots(
    conn: DatabaseConnection, *, include_withdrawn: bool = False
) -> list[SnapshotRow]:
    """Every snapshot, newest first; withdrawn ones only when ``include_withdrawn`` is true."""
    where = "" if include_withdrawn else " WHERE w.id IS NULL"
    cursor = conn.execute(_SNAPSHOT_SELECT + where + _SNAPSHOT_ORDER)
    return [_snapshot_row(row) for row in cursor.fetchall()]


def get_snapshot(conn: DatabaseConnection, snapshot_id: int) -> SnapshotRow | None:
    """The snapshot with ``snapshot_id`` (withdrawn or not), or ``None``."""
    cursor = conn.execute(_SNAPSHOT_SELECT + " WHERE s.id = ?", (snapshot_id,))
    row = cursor.fetchone()
    return None if row is None else _snapshot_row(row)


def list_values(conn: DatabaseConnection, snapshot_id: int) -> list[SnapshotValueRow]:
    """The value rows of a snapshot, ordered by code and dimension."""
    cursor = conn.execute(
        "SELECT snapshot_id, indicator_code, dimension, value, status, warning_value,"
        " critical_value FROM readiness_snapshot_value WHERE snapshot_id = ?"
        " ORDER BY indicator_code, dimension",
        (snapshot_id,),
    )
    return [
        SnapshotValueRow(
            snapshot_id=_int(row["snapshot_id"]),
            indicator_code=_text(row["indicator_code"]),
            dimension=_text(row["dimension"]),
            value=_opt_float(row["value"]),
            status=_text(row["status"]),
            warning_value=_opt_float(row["warning_value"]),
            critical_value=_opt_float(row["critical_value"]),
        )
        for row in cursor.fetchall()
    ]


def monthly_taken_times(conn: DatabaseConnection) -> list[str]:
    """``taken_at_utc`` of every snapshot of origin ``monthly``, WITHDRAWN ONES INCLUDED (P04).

    The month is done once its monthly snapshot was taken, whatever happened to it afterwards
    (T8.1: several starts in one month produce exactly one monthly snapshot).
    """
    cursor = conn.execute(
        "SELECT taken_at_utc FROM readiness_snapshot WHERE origin = 'monthly' ORDER BY taken_at_utc"
    )
    return [_text(row["taken_at_utc"]) for row in cursor.fetchall()]


# --------------------------------------------------------------------------- writes


def insert_snapshot(
    ctx: WriteContext,
    *,
    taken_at_utc: str,
    as_of: str,
    origin: str,
    app_version: str,
    config_hash: str,
    config_json: str,
    note: str | None,
) -> int:
    """Insert the header of a snapshot and return its new ``id``."""
    new_id = insert(
        ctx,
        _SNAPSHOT,
        {
            "taken_at_utc": taken_at_utc,
            "as_of": as_of,
            "origin": origin,
            "app_version": app_version,
            "config_hash": config_hash,
            "config_json": config_json,
            "note": note,
        },
    )
    if new_id is None:
        msg = "The new snapshot has no id."
        raise RepositoryError(msg, "KEY_MISSING")
    return new_id


def insert_values(ctx: WriteContext, snapshot_id: int, rows: Sequence[SnapshotValueRow]) -> None:
    """Insert the value rows of a snapshot (``rows[i].snapshot_id`` is ignored)."""
    for row in rows:
        insert(
            ctx,
            _VALUE,
            {
                "snapshot_id": snapshot_id,
                "indicator_code": row.indicator_code,
                "dimension": row.dimension,
                "value": row.value,
                "status": row.status,
                "warning_value": row.warning_value,
                "critical_value": row.critical_value,
            },
        )


def insert_withdrawal(
    ctx: WriteContext, snapshot_id: int, *, withdrawn_at_utc: str, reason: str, operator: str
) -> int:
    """Append the withdrawal of a snapshot and return its ``id``."""
    new_id = insert(
        ctx,
        _WITHDRAWAL,
        {
            "snapshot_id": snapshot_id,
            "withdrawn_at_utc": withdrawn_at_utc,
            "reason": reason,
            "operator": operator,
        },
    )
    if new_id is None:
        msg = "The new withdrawal has no id."
        raise RepositoryError(msg, "KEY_MISSING")
    return new_id
