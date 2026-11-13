# SPDX-License-Identifier: GPL-3.0-or-later
"""The readiness configuration and the per-database settings (PLAN.md 3.5, D05, task T1.5).

Everything lives in the ``setting`` table (``key`` -> ``value_json``):

* ``config.<field>``: the fields of :class:`~cbrn_dashboard.domain.config.ReadinessConfig`; a value
  equal to the default and not stored yet is not written;
* ``confirmed.<ID>``: ``true`` when the operator confirmed placeholder ``<ID>`` on this
  installation. This only hides the badge here; the code-level flag of
  :data:`~cbrn_dashboard.domain.config.PLACEHOLDERS` is never touched. Confirming also pins the
  current values of the placeholder's config fields in this database, default or not;
* any other key through :func:`get_value` / :func:`set_value` (for example the time of the last
  encrypted backup, T7.2).

Every write goes through the repository helpers, so it lands in ``change_log`` with
``entity = "setting"`` and ``entity_key = {"key": ...}``. Errors are
:class:`~cbrn_dashboard.domain.config.ConfigError` with a stable code and never contain values.
"""

from __future__ import annotations

import json
import re
import sqlite3

from cbrn_dashboard.domain.config import (
    PLACEHOLDERS,
    SETTING_PREFIX,
    ConfigError,
    ReadinessConfig,
    from_settings,
    placeholder,
    to_settings,
    validate,
)
from cbrn_dashboard.storage import repository
from cbrn_dashboard.storage.db import transaction
from cbrn_dashboard.storage.repository import WriteContext

__all__ = [
    "CONFIRMED_PREFIX",
    "confirm_placeholder",
    "confirmed_placeholders",
    "get_value",
    "load_config",
    "needs_badge",
    "save_config",
    "set_value",
    "unconfirm_placeholder",
]

#: Prefix of the keys that record a confirmed placeholder.
CONFIRMED_PREFIX = "confirmed."

_TABLE = "setting"
_KEY_PATTERN = re.compile(r"[a-z][A-Za-z0-9_.\-]{0,99}")


# --------------------------------------------------------------------------- JSON helpers


def _dumps(value: object) -> str:
    """Canonical JSON text of ``value``; raises ``ConfigError`` (``INVALID_VALUE``) otherwise."""
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        msg = "The value cannot be stored as JSON."
        raise ConfigError("INVALID_VALUE", "", msg) from exc


def _loads(key: str, text: object) -> object:
    if not isinstance(text, str):
        raise ConfigError("CORRUPT_SETTING", key)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ConfigError("CORRUPT_SETTING", key) from exc


def _rows_with_prefix(conn: sqlite3.Connection, prefix: str) -> list[tuple[str, object]]:
    rows = conn.execute("SELECT key, value_json FROM setting ORDER BY key").fetchall()
    return [(str(row[0]), row[1]) for row in rows if str(row[0]).startswith(prefix)]


def _check_key(key: str) -> None:
    if not isinstance(key, str) or _KEY_PATTERN.fullmatch(key) is None:
        raise ConfigError("INVALID_KEY", "")


def _put(ctx: WriteContext, key: str, value: object) -> bool:
    """Insert or update one setting; ``True`` when the stored value changed."""
    text = _dumps(value)
    with transaction(ctx.conn):
        row = repository.fetch_row(ctx.conn, _TABLE, {"key": key})
        if row is None:
            repository.insert(ctx, _TABLE, {"key": key, "value_json": text})
            return True
        try:
            same = _dumps(_loads(key, row["value_json"])) == text
        except ConfigError:
            same = False  # a corrupt stored value is repaired by the write
        if same:
            return False
        return repository.update(ctx, _TABLE, {"key": key}, {"value_json": text})


# --------------------------------------------------------------------------- configuration


def load_config(conn: sqlite3.Connection) -> ReadinessConfig:
    """The stored configuration; missing keys take the defaults.

    Raises ``ConfigError`` (``CORRUPT_SETTING``) for unreadable JSON and the validation errors of
    :func:`~cbrn_dashboard.domain.config.from_settings` for values that are not acceptable.
    """
    stored = {key: _loads(key, text) for key, text in _rows_with_prefix(conn, SETTING_PREFIX)}
    return from_settings(stored)


def save_config(ctx: WriteContext, config: ReadinessConfig) -> tuple[str, ...]:
    """Validate ``config`` and store the keys whose value differs from what is stored.

    A key at its default value that is not stored yet is not written. All writes share one
    transaction; the changed keys are returned and a no-op save writes and logs nothing.
    """
    validate(config)
    defaults = to_settings(ReadinessConfig())
    changed: list[str] = []
    with transaction(ctx.conn):
        for key, value in to_settings(config).items():
            row = repository.fetch_row(ctx.conn, _TABLE, {"key": key})
            if row is None and _dumps(value) == _dumps(defaults[key]):
                continue
            if _put(ctx, key, value):
                changed.append(key)
    return tuple(changed)


# --------------------------------------------------------------------------- confirmed state


def _known_placeholder(placeholder_id: str) -> str:
    try:
        return placeholder(placeholder_id).id
    except KeyError as exc:
        raise ConfigError("UNKNOWN_PLACEHOLDER", "placeholder_id") from exc


def confirm_placeholder(ctx: WriteContext, placeholder_id: str) -> None:
    """Record that the operator confirmed ``placeholder_id`` on this installation (idempotent).

    In the same transaction the current values of the placeholder's config fields are stored too,
    even when they equal the default, so a later release that changes a generic default cannot
    silently change a confirmed value on this database. A placeholder without config fields
    (``fields == ()``) writes only the ``confirmed.<ID>`` key.
    """
    known = _known_placeholder(placeholder_id)
    fields = placeholder(known).fields
    with transaction(ctx.conn):
        if fields:
            current = to_settings(load_config(ctx.conn))
            for name in fields:
                key = SETTING_PREFIX + name
                _put(ctx, key, current[key])
        _put(ctx, CONFIRMED_PREFIX + known, True)


def unconfirm_placeholder(ctx: WriteContext, placeholder_id: str) -> None:
    """Forget the confirmation of ``placeholder_id`` (idempotent)."""
    known = _known_placeholder(placeholder_id)
    key = CONFIRMED_PREFIX + known
    with transaction(ctx.conn):
        if repository.fetch_row(ctx.conn, _TABLE, {"key": key}) is not None:
            repository.delete(ctx, _TABLE, {"key": key})


def confirmed_placeholders(conn: sqlite3.Connection) -> frozenset[str]:
    """The ids of the placeholders confirmed in this database."""
    known = {item.id for item in PLACEHOLDERS}
    confirmed: set[str] = set()
    for key, text in _rows_with_prefix(conn, CONFIRMED_PREFIX):
        placeholder_id = key[len(CONFIRMED_PREFIX) :]
        if placeholder_id in known and _loads(key, text) is True:
            confirmed.add(placeholder_id)
    return frozenset(confirmed)


def needs_badge(conn: sqlite3.Connection, placeholder_id: str) -> bool:
    """Whether Settings shows the "to be confirmed" badge: flagged in code, not confirmed here."""
    item = placeholder(_known_placeholder(placeholder_id))
    return item.placeholder and item.id not in confirmed_placeholders(conn)


# --------------------------------------------------------------------------- generic values


def get_value(conn: sqlite3.Connection, key: str) -> object | None:
    """The JSON value stored under ``key``, or ``None`` when there is none."""
    _check_key(key)
    row = repository.fetch_row(conn, _TABLE, {"key": key})
    if row is None:
        return None
    return _loads(key, row["value_json"])


def set_value(ctx: WriteContext, key: str, value: object) -> bool:
    """Store a JSON-serialisable ``value`` under ``key``; ``True`` when anything changed.

    The ``config.`` keys belong to :func:`save_config` and are refused here.
    """
    _check_key(key)
    if key.startswith(SETTING_PREFIX):
        raise ConfigError("RESERVED_KEY", "")
    return _put(ctx, key, value)
