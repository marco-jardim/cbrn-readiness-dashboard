# SPDX-License-Identifier: GPL-3.0-or-later
"""Storage of the indicator targets (PLAN.md T6.1, D14, P03).

Reads are plain parameterised ``SELECT`` statements. Every write goes through the repository
helpers (:func:`~cbrn_dashboard.storage.repository.insert`, ``update`` and ``delete``), so each
change gets its ``change_log`` row in the same transaction: ``entity = "indicator_target"`` and
``entity_key = {"dimension": ..., "indicator_code": ...}`` (the table has a natural key, no ``id``).
This module checks no business rule (known codes, dimensions, order): that is the service's job
(``services/indicators.py``). No target is ever seeded or defaulted (P03).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from cbrn_dashboard.domain.indicators import Target, TargetKey
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import (
    RepositoryError,
    WriteContext,
    delete,
    fetch_row,
    insert,
    update,
)

__all__ = [
    "TargetRow",
    "delete_target",
    "get_target",
    "list_targets",
    "load_targets",
    "upsert_target",
]

_TABLE = "indicator_target"
_NAMES = ("indicator_code", "dimension", "warning_value", "critical_value", "enabled")
_COLUMNS = ", ".join(_NAMES)


@dataclass(frozen=True)
class TargetRow:
    """A row of ``indicator_target``; a ``None`` threshold means "not set"."""

    indicator_code: str
    dimension: str
    warning_value: float | None
    critical_value: float | None
    enabled: bool


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    msg = "Expected a real column."
    raise RepositoryError(msg, "UNEXPECTED_COLUMN_TYPE")


def _int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    msg = "Expected an integer column."
    raise RepositoryError(msg, "UNEXPECTED_COLUMN_TYPE")


def _row(values: Mapping[str, object]) -> TargetRow:
    return TargetRow(
        indicator_code=str(values["indicator_code"]),
        dimension=str(values["dimension"]),
        warning_value=_opt_float(values["warning_value"]),
        critical_value=_opt_float(values["critical_value"]),
        enabled=_int(values["enabled"]) == 1,
    )


def _key(code: str, dimension: str) -> dict[str, object]:
    return {"indicator_code": code, "dimension": dimension}


def list_targets(conn: DatabaseConnection) -> list[TargetRow]:
    """Every stored target (disabled ones included), ordered by code and dimension."""
    sql = f"SELECT {_COLUMNS} FROM {_TABLE} ORDER BY indicator_code, dimension"
    return [_row({name: row[name] for name in _NAMES}) for row in conn.execute(sql).fetchall()]


def get_target(conn: DatabaseConnection, code: str, dimension: str) -> TargetRow | None:
    """The target of exactly ``(code, dimension)``, or ``None``."""
    values = fetch_row(conn, _TABLE, _key(code, dimension))
    return None if values is None else _row(values)


def upsert_target(
    ctx: WriteContext,
    code: str,
    dimension: str,
    warning_value: float | None,
    critical_value: float | None,
    enabled: bool,
) -> bool:
    """Insert the target, or update it when something differs; return whether anything changed.

    A call that changes nothing writes and logs nothing.
    """
    flag = 1 if enabled else 0
    current = get_target(ctx.conn, code, dimension)
    if current is None:
        insert(
            ctx,
            _TABLE,
            {
                "indicator_code": code,
                "dimension": dimension,
                "warning_value": warning_value,
                "critical_value": critical_value,
                "enabled": flag,
            },
        )
        return True
    return update(
        ctx,
        _TABLE,
        _key(code, dimension),
        {"warning_value": warning_value, "critical_value": critical_value, "enabled": flag},
    )


def delete_target(ctx: WriteContext, code: str, dimension: str) -> bool:
    """Delete the target; return whether there was one (nothing is logged when there was not)."""
    if get_target(ctx.conn, code, dimension) is None:
        return False
    delete(ctx, _TABLE, _key(code, dimension))
    return True


def load_targets(conn: DatabaseConnection) -> dict[TargetKey, Target]:
    """Every stored target as a domain :class:`Target`, keyed by ``(code, dimension)``.

    Disabled targets are included with ``enabled=False``: the domain treats them as absent.
    """
    return {
        (row.indicator_code, row.dimension): Target(
            warning_value=row.warning_value,
            critical_value=row.critical_value,
            enabled=row.enabled,
        )
        for row in list_targets(conn)
    }
