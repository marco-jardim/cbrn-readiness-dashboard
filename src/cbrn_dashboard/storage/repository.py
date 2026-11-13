# SPDX-License-Identifier: GPL-3.0-or-later
"""Repository helpers with the append-only change log (PLAN.md D05, section 5.1, task T1.4).

Every write goes through :func:`insert`, :func:`update` or :func:`delete`. Each helper runs inside
:func:`~cbrn_dashboard.storage.db.transaction`, which nests as a savepoint, so the data change and
its ``change_log`` rows are committed or rolled back together: when a helper fails, everything it
wrote is undone even if the caller catches the error and the outer transaction goes on to commit.
The log rows are written only after the change itself succeeded.

* One ``change_log`` row per affected row. A delete also logs every row the delete cascades to:
  they are found *before* the delete through ``foreign_key_list`` (the ``pragma_foreign_key_list``
  table-valued form, which takes the table name as a bound parameter), recursively and guarded
  against cycles, and checked to be really gone afterwards.
* A table whose primary key is a single ``INTEGER`` column named ``id`` is logged with
  ``entity_id``; every other table is logged with ``entity_id = NULL`` and ``entity_key`` holding
  its primary-key columns as JSON.
* Personal free-text columns (:data:`REDACTED_COLUMNS`, D17) are never copied into ``change_log``;
  :func:`redact_row` is the single place that removes them and every JSON document of the log goes
  through it (:func:`row_to_json`).
* Time comes only from the injected :class:`~cbrn_dashboard.clock.Clock`.

SQL text is built only from identifiers that match ``^[a-z_][a-z0-9_]*$`` *and* exist in the live
schema; values always travel as ``?`` parameters. Errors derive from
:class:`~cbrn_dashboard.storage.db.DatabaseError`, carry a stable ``code`` and never contain record
contents.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain.dates import format_utc_timestamp
from cbrn_dashboard.storage.db import DatabaseConnection, DatabaseError, transaction

__all__ = [
    "ACTIONS",
    "PSEUDO_ENTITIES",
    "REDACTED_COLUMNS",
    "ConstraintViolationError",
    "ForeignKeyError",
    "RepositoryError",
    "RowNotFoundError",
    "TableInfo",
    "UnknownColumnError",
    "UnknownTableError",
    "WriteContext",
    "delete",
    "fetch_row",
    "insert",
    "log_event",
    "redact_row",
    "row_to_json",
    "table_info",
    "update",
]

#: Values of ``change_log.action`` (the CHECK constraint of migration 0001).
ACTIONS: tuple[str, ...] = ("insert", "update", "delete", "import", "restore")

#: Actions the :func:`insert` helper may record.
_INSERT_ACTIONS: frozenset[str] = frozenset({"insert", "import"})

#: Personal free-text columns whose values never reach ``change_log`` (section 5.1, D17). Keyed by
#: table name; tables that do not exist (yet) are simply never matched.
REDACTED_COLUMNS: Mapping[str, frozenset[str]] = {
    "staff_member": frozenset({"identifier", "label"}),
    "ppe_certification": frozenset({"reference"}),
    "academic_degree": frozenset({"field"}),
}

#: Log entities that are not tables: ``database`` is the restore event of the restore service
#: (T7.3). They have no redaction rule of their own, see :func:`log_event`.
PSEUDO_ENTITIES: frozenset[str] = frozenset({"database"})

#: Tables the helpers refuse to write: the log itself is written only by this module.
_PROTECTED_TABLES: frozenset[str] = frozenset({"change_log"})

_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
_ID_COLUMN = "id"

type Key = int | Mapping[str, object]


# --------------------------------------------------------------------------- errors


class RepositoryError(DatabaseError):
    """Base class of the repository errors; ``code`` is stable and translated by the UI."""

    code: str = "REPOSITORY_ERROR"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class UnknownTableError(RepositoryError):
    """The table name is not a valid identifier or does not exist in the schema."""

    code = "UNKNOWN_TABLE"


class UnknownColumnError(RepositoryError):
    """The column name is not a valid identifier or does not exist in the table."""

    code = "UNKNOWN_COLUMN"


class RowNotFoundError(RepositoryError):
    """The row to update or delete does not exist."""

    code = "ROW_NOT_FOUND"


class ForeignKeyError(RepositoryError):
    """A delete was refused because other rows still use the row (``ON DELETE RESTRICT``)."""

    code = "ROW_IN_USE"


class ConstraintViolationError(RepositoryError):
    """An insert or update violated a database constraint (unique, not null, check, foreign key)."""

    code = "CONSTRAINT_VIOLATION"


# --------------------------------------------------------------------------- context


@dataclass(frozen=True)
class WriteContext:
    """What a write needs: the connection, the clock and the optional operator label (D05)."""

    conn: DatabaseConnection
    clock: Clock
    operator: str = ""


# --------------------------------------------------------------------------- schema introspection


@dataclass(frozen=True)
class TableInfo:
    """A table as it is in the live schema."""

    name: str
    columns: tuple[str, ...]
    primary_key: tuple[str, ...]
    has_integer_id: bool
    integer_pk: bool

    @property
    def uses_entity_id(self) -> bool:
        """Whether rows of this table are logged with ``entity_id`` (else with ``entity_key``)."""
        return self.has_integer_id


def _quote(identifier: str) -> str:
    """Quote an identifier for SQL text; refuses anything but ``^[a-z_][a-z0-9_]*$``."""
    if not isinstance(identifier, str) or _IDENTIFIER.fullmatch(identifier) is None:
        msg = "Not a valid identifier."
        raise RepositoryError(msg, "INVALID_IDENTIFIER")
    return f'"{identifier}"'


def _rows(
    conn: sqlite3.Connection, sql: str, params: Sequence[object] = ()
) -> list[tuple[object, ...]]:
    return [tuple(row) for row in conn.execute(sql, params).fetchall()]


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = _rows(conn, "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
    return [str(row[0]) for row in rows if not str(row[0]).startswith("sqlite_")]


def table_info(conn: sqlite3.Connection, table: str) -> TableInfo:
    """Describe ``table`` from the live schema.

    Raises :class:`UnknownTableError` when ``table`` is not a valid identifier or no such table
    exists, and :class:`RepositoryError` (``PROTECTED_TABLE``, ``NO_PRIMARY_KEY``) when the table
    cannot be written through the helpers.
    """
    if not isinstance(table, str) or _IDENTIFIER.fullmatch(table) is None:
        msg = "Unknown table."
        raise UnknownTableError(msg)
    if table not in _table_names(conn):
        msg = "Unknown table."
        raise UnknownTableError(msg)
    columns = _rows(conn, "SELECT name, type, pk FROM pragma_table_info(?) ORDER BY cid", (table,))
    names = tuple(str(row[0]) for row in columns)
    pk_rows = sorted((row for row in columns if _pk(row) > 0), key=_pk)
    primary_key = tuple(str(row[0]) for row in pk_rows)
    integer_pk = len(pk_rows) == 1 and str(pk_rows[0][1]).upper() == "INTEGER"
    return TableInfo(
        name=table,
        columns=names,
        primary_key=primary_key,
        has_integer_id=integer_pk and primary_key == (_ID_COLUMN,),
        integer_pk=integer_pk,
    )


def _pk(row: tuple[object, ...]) -> int:
    position = row[2]
    return position if isinstance(position, int) else 0


def _writable_table(conn: sqlite3.Connection, table: str) -> TableInfo:
    info = table_info(conn, table)
    if table in _PROTECTED_TABLES:
        msg = "This table cannot be written through the repository helpers."
        raise RepositoryError(msg, "PROTECTED_TABLE")
    if not info.primary_key:
        msg = "The table has no primary key."
        raise RepositoryError(msg, "NO_PRIMARY_KEY")
    return info


def _check_columns(info: TableInfo, columns: Collection[str]) -> None:
    for column in columns:
        if (
            not isinstance(column, str)
            or _IDENTIFIER.fullmatch(column) is None
            or column not in info.columns
        ):
            msg = "Unknown column."
            raise UnknownColumnError(msg)


def _check_value(value: object) -> None:
    if value is not None and not isinstance(value, str | int | float):
        msg = "Only NULL, integer, real and text values are supported."
        raise RepositoryError(msg, "UNSUPPORTED_VALUE")
    if isinstance(value, float) and not math.isfinite(value):
        # The change log cannot hold NaN or an infinity (JSON); refuse before anything is written.
        msg = "A non-finite number is not supported."
        raise RepositoryError(msg, "UNSUPPORTED_VALUE")


def _check_action(action: str, allowed: Collection[str]) -> None:
    if action not in allowed:
        msg = "Invalid change_log action."
        raise RepositoryError(msg, "INVALID_ACTION")


# --------------------------------------------------------------------------- redaction and JSON


def redact_row(
    table: str, row: Mapping[str, object], changed: Collection[str] = ()
) -> dict[str, object]:
    """Copy of ``row`` with the personal free-text columns of ``table`` replaced by a marker.

    The marker is ``{"redacted": true}``, plus ``"changed": true`` for the columns named in
    ``changed``. This is the only function that decides what of a row may enter ``change_log``.
    """
    redacted = REDACTED_COLUMNS.get(table, frozenset())
    result: dict[str, object] = {}
    for column, value in row.items():
        if column in redacted:
            marker: dict[str, object] = {"redacted": True}
            if column in changed:
                marker["changed"] = True
            result[column] = marker
        else:
            result[column] = value
    return result


def _reject_value(value: object) -> object:
    msg = "Only NULL, integer, real and text values can be logged."
    raise RepositoryError(msg, "UNSUPPORTED_VALUE")


def _dumps(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
            default=_reject_value,
        )
    except ValueError as exc:
        msg = "A non-finite number cannot be logged."
        raise RepositoryError(msg, "UNSUPPORTED_VALUE") from exc


def row_to_json(table: str, row: Mapping[str, object], *, changed: Collection[str] = ()) -> str:
    """The JSON text of ``row`` as stored in ``change_log``; redaction is always applied."""
    return _dumps(redact_row(table, row, changed))


def _key_to_json(table: str, key: Mapping[str, object]) -> str:
    return _dumps(redact_row(table, key))


# --------------------------------------------------------------------------- reading


def _select_by_key(
    conn: sqlite3.Connection, info: TableInfo, key: Mapping[str, object]
) -> dict[str, object] | None:
    columns = ", ".join(_quote(column) for column in info.columns)
    where = " AND ".join(f"{_quote(column)} = ?" for column in key)
    sql = f"SELECT {columns} FROM {_quote(info.name)} WHERE {where}"
    rows = _rows(conn, sql, list(key.values()))
    if not rows:
        return None
    return dict(zip(info.columns, rows[0], strict=True))


def _resolve_key(info: TableInfo, key: Key) -> dict[str, object]:
    """Turn ``key`` (an ``id`` or a natural-key mapping) into ``{primary-key column: value}``."""
    if isinstance(key, Mapping):
        _check_columns(info, key)
        if set(key) != set(info.primary_key):
            msg = "The key must name exactly the primary-key columns."
            raise RepositoryError(msg, "INVALID_KEY")
        resolved = {column: key[column] for column in info.primary_key}
    elif info.has_integer_id and isinstance(key, int) and not isinstance(key, bool):
        resolved = {_ID_COLUMN: key}
    else:
        msg = "The key does not fit the table."
        raise RepositoryError(msg, "INVALID_KEY")
    for value in resolved.values():
        _check_value(value)
        if value is None:
            msg = "A key value must not be NULL."
            raise RepositoryError(msg, "INVALID_KEY")
    return resolved


def fetch_row(conn: sqlite3.Connection, table: str, key: Key) -> dict[str, object] | None:
    """The full row with the given ``id`` (or natural key), or ``None`` when it does not exist."""
    info = table_info(conn, table)
    if not info.primary_key:
        msg = "The table has no primary key."
        raise RepositoryError(msg, "NO_PRIMARY_KEY")
    return _select_by_key(conn, info, _resolve_key(info, key))


def _row_key(info: TableInfo, row: Mapping[str, object]) -> dict[str, object]:
    return {column: row[column] for column in info.primary_key}


# --------------------------------------------------------------------------- writing the log

_INSERT_LOG = (
    "INSERT INTO change_log"
    " (at_utc, operator, entity, entity_id, entity_key, action, before_json, after_json)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


def _append_log(
    ctx: WriteContext,
    *,
    entity: str,
    entity_id: int | None,
    entity_key_json: str | None,
    action: str,
    before_json: str | None,
    after_json: str | None,
) -> None:
    ctx.conn.execute(
        _INSERT_LOG,
        (
            format_utc_timestamp(ctx.clock.utc_now()),
            ctx.operator,
            entity,
            entity_id,
            entity_key_json,
            action,
            before_json,
            after_json,
        ),
    )


def _log_row(
    ctx: WriteContext,
    info: TableInfo,
    action: str,
    key: Mapping[str, object],
    *,
    before: Mapping[str, object] | None,
    after: Mapping[str, object] | None,
    changed: Collection[str] = (),
) -> None:
    entity_id: int | None = None
    entity_key_json: str | None = None
    if info.uses_entity_id:
        value = key[_ID_COLUMN]
        if not isinstance(value, int):
            msg = "The id is not an integer."
            raise RepositoryError(msg, "INVALID_KEY")
        entity_id = value
    else:
        entity_key_json = _key_to_json(info.name, key)
    _append_log(
        ctx,
        entity=info.name,
        entity_id=entity_id,
        entity_key_json=entity_key_json,
        action=action,
        before_json=None if before is None else row_to_json(info.name, before),
        after_json=None if after is None else row_to_json(info.name, after, changed=changed),
    )


def log_event(
    ctx: WriteContext,
    entity: str,
    action: str,
    *,
    entity_id: int | None = None,
    entity_key: Mapping[str, object] | None = None,
    before: Mapping[str, object] | None = None,
    after: Mapping[str, object] | None = None,
) -> None:
    """Write one ``change_log`` row for an event that is not a single-row write (for example
    the ``restore`` row of the restore service).

    ``entity`` is a live table name (validated like every other table) or one of
    :data:`PSEUDO_ENTITIES`. For a table, ``before``, ``after`` and ``entity_key`` are redacted
    according to it like every other log row. A pseudo-entity has no redaction rule, so it refuses
    (``REDACTED_KEY_IN_EVENT``) any of those mappings that names a redacted column of any table.
    """
    _check_action(action, ACTIONS)
    if not isinstance(entity, str) or not entity:
        msg = "The entity must be a non-empty text."
        raise RepositoryError(msg, "INVALID_ENTITY")
    if entity in PSEUDO_ENTITIES:
        redacted_names = frozenset(
            column for columns in REDACTED_COLUMNS.values() for column in columns
        )
        for mapping in (entity_key, before, after):
            if mapping is not None and not redacted_names.isdisjoint(mapping):
                msg = "A personal column cannot be recorded in an event of this entity."
                raise RepositoryError(msg, "REDACTED_KEY_IN_EVENT")
    else:
        table_info(ctx.conn, entity)
    if entity_id is not None and (not isinstance(entity_id, int) or isinstance(entity_id, bool)):
        msg = "The entity id must be an integer."
        raise RepositoryError(msg, "INVALID_KEY")
    with transaction(ctx.conn):
        _append_log(
            ctx,
            entity=entity,
            entity_id=entity_id,
            entity_key_json=None if entity_key is None else _key_to_json(entity, entity_key),
            action=action,
            before_json=None if before is None else row_to_json(entity, before),
            after_json=None if after is None else row_to_json(entity, after),
        )


# --------------------------------------------------------------------------- insert


def insert(
    ctx: WriteContext, table: str, values: Mapping[str, object], *, action: str = "insert"
) -> int | None:
    """Insert one row and log it; return the new ``id`` (``None`` for tables without an ``id``).

    ``after_json`` holds the full row as stored (defaults included); both it and the key of the log
    row come from the row SQLite returns (``RETURNING``), not from the caller's values. ``action``
    may be ``"insert"`` or ``"import"`` (the CSV importer).
    """
    _check_action(action, _INSERT_ACTIONS)
    with transaction(ctx.conn):
        info = _writable_table(ctx.conn, table)
        _check_columns(info, values)
        for value in values.values():
            _check_value(value)
        if values:
            names = ", ".join(_quote(column) for column in values)
            marks = ", ".join("?" for _ in values)
            sql = f"INSERT INTO {_quote(table)} ({names}) VALUES ({marks})"
        else:
            sql = f"INSERT INTO {_quote(table)} DEFAULT VALUES"
        sql += " RETURNING " + ", ".join(_quote(column) for column in info.columns)
        try:
            returned = ctx.conn.execute(sql, list(values.values())).fetchall()
        except sqlite3.IntegrityError as exc:
            msg = f"The row violates a database constraint ({exc.sqlite_errorname})."
            raise ConstraintViolationError(msg) from exc
        if len(returned) != 1:
            msg = "The inserted row could not be read back."
            raise RepositoryError(msg, "INSERT_NOT_FOUND")
        after = dict(zip(info.columns, tuple(returned[0]), strict=True))
        key = _row_key(info, after)
        if any(value is None for value in key.values()):
            msg = "The primary key of the new row is unknown."
            raise RepositoryError(msg, "KEY_MISSING")
        _log_row(ctx, info, action, key, before=None, after=after)
        if info.has_integer_id:
            new_id = after[_ID_COLUMN]
            return new_id if isinstance(new_id, int) else None
        return None


# --------------------------------------------------------------------------- update


def update(ctx: WriteContext, table: str, key: Key, changes: Mapping[str, object]) -> bool:
    """Change columns of one row and log it; return whether anything changed.

    ``key`` is the ``id`` or the natural-key mapping. Raises :class:`RowNotFoundError` when the row
    does not exist. When no value actually changes nothing is written or logged and ``False`` is
    returned. Primary-key columns cannot be changed. The log row holds the full row before and
    after.
    """
    with transaction(ctx.conn):
        info = _writable_table(ctx.conn, table)
        resolved = _resolve_key(info, key)
        _check_columns(info, changes)
        for value in changes.values():
            _check_value(value)
        before = _select_by_key(ctx.conn, info, resolved)
        if before is None:
            msg = "The row does not exist."
            raise RowNotFoundError(msg)
        pending: dict[str, object] = {}
        for column, value in changes.items():
            if value == before[column]:
                continue
            if column in info.primary_key:
                msg = "A primary-key column cannot be changed."
                raise RepositoryError(msg, "PRIMARY_KEY_CHANGE")
            pending[column] = value
        if not pending:
            return False
        assignments = ", ".join(f"{_quote(column)} = ?" for column in pending)
        where = " AND ".join(f"{_quote(column)} = ?" for column in resolved)
        sql = f"UPDATE {_quote(table)} SET {assignments} WHERE {where}"
        try:
            ctx.conn.execute(sql, [*pending.values(), *resolved.values()])
        except sqlite3.IntegrityError as exc:
            msg = f"The change violates a database constraint ({exc.sqlite_errorname})."
            raise ConstraintViolationError(msg) from exc
        after = _select_by_key(ctx.conn, info, resolved)
        if after is None:
            msg = "The updated row could not be read back."
            raise RepositoryError(msg, "ROW_VANISHED")
        changed = frozenset(column for column in info.columns if before[column] != after[column])
        if not changed:
            return False
        _log_row(ctx, info, "update", resolved, before=before, after=after, changed=changed)
        return True


# --------------------------------------------------------------------------- delete


@dataclass(frozen=True)
class _CascadeRef:
    """A foreign key of ``child`` that cascades deletes of ``parent``."""

    child: str
    pairs: tuple[tuple[str, str], ...]  # (child column, parent column)


@dataclass(frozen=True)
class _ForeignKey:
    """A foreign key between two tables of the cascade graph."""

    child: str
    parent: str
    pairs: tuple[tuple[str, str], ...]  # (child column, parent column)
    on_update: str
    on_delete: str


#: ``ON UPDATE`` actions that never change a child row.
_INERT_UPDATE_ACTIONS: frozenset[str] = frozenset({"NO ACTION", "RESTRICT"})
#: ``ON DELETE`` actions that change a child row without the helper logging it.
_UNLOGGED_DELETE_ACTIONS: frozenset[str] = frozenset({"SET NULL", "SET DEFAULT"})


def _canonical_column(info: TableInfo, name: str) -> str:
    """The column of ``info`` called ``name``, compared case-insensitively (as SQLite does)."""
    for column in info.columns:
        if column.lower() == name.lower():
            _check_columns(info, [column])
            return column
    msg = "Unknown column."
    raise UnknownColumnError(msg)


def _foreign_key_groups(conn: sqlite3.Connection, table: str) -> list[list[tuple[object, ...]]]:
    """The foreign keys of ``table`` as lists of ``pragma_foreign_key_list`` rows, one per key.

    Row layout: ``table`` (parent), ``from``, ``to``, ``on_update``, ``on_delete``. The table name
    travels as a bound parameter, so any name is safe to pass.
    """
    rows = _rows(
        conn,
        'SELECT id, "table", "from", "to", on_update, on_delete FROM pragma_foreign_key_list(?)'
        " ORDER BY id, seq",
        (table,),
    )
    grouped: dict[int, list[tuple[object, ...]]] = {}
    for row in rows:
        fk_id = row[0]
        if isinstance(fk_id, int):
            grouped.setdefault(fk_id, []).append(row[1:])
    return list(grouped.values())


def _schema_foreign_keys(conn: sqlite3.Connection) -> list[_ForeignKey]:
    """Every foreign key between tables with a plain identifier name.

    A table whose name fails the identifier rule cannot be handled by the helpers. It is skipped
    when it holds no foreign key to such a table; otherwise a delete could cascade into it without
    a log row, so ``UNSUPPORTED_SCHEMA`` is raised.
    """
    names = _table_names(conn)
    plain = {name.lower(): name for name in names if _IDENTIFIER.fullmatch(name)}
    infos: dict[str, TableInfo] = {}

    def info_of(name: str) -> TableInfo:
        if name not in infos:
            infos[name] = table_info(conn, name)
        return infos[name]

    result: list[_ForeignKey] = []
    for child in names:
        child_is_plain = _IDENTIFIER.fullmatch(child) is not None
        for rows in _foreign_key_groups(conn, child):
            parent = plain.get(str(rows[0][0]).lower())
            if parent is None:
                continue
            if not child_is_plain:
                msg = "A table with an unsupported name references a table; it cannot be logged."
                raise RepositoryError(msg, "UNSUPPORTED_SCHEMA")
            child_info = info_of(child)
            parent_info = info_of(parent)
            pairs: list[tuple[str, str]] = []
            for position, row in enumerate(rows):
                child_column = _canonical_column(child_info, str(row[1]))
                parent_name = row[2] if row[2] is not None else parent_info.primary_key[position]
                pairs.append((child_column, _canonical_column(parent_info, str(parent_name))))
            result.append(
                _ForeignKey(
                    child, parent, tuple(pairs), str(rows[0][3]).upper(), str(rows[0][4]).upper()
                )
            )
    return result


def _cascade_graph(conn: sqlite3.Connection, root: str) -> dict[str, list[_CascadeRef]]:
    """Foreign keys with ``ON DELETE CASCADE``, grouped by the lower-cased parent table name.

    Raises ``UNSUPPORTED_FK_ACTION`` when a delete of ``root`` could change a row without a log
    row: a table referencing ``root``, or a table cascaded from it, declares ``ON DELETE SET NULL``
    or ``SET DEFAULT``, or any ``ON UPDATE`` action other than ``NO ACTION``/``RESTRICT``.
    """
    foreign_keys = _schema_foreign_keys(conn)
    reachable = {root.lower()}
    pending = [root.lower()]
    while pending:
        parent = pending.pop()
        for fk in foreign_keys:
            is_new = fk.child.lower() not in reachable
            if fk.parent.lower() == parent and fk.on_delete == "CASCADE" and is_new:
                reachable.add(fk.child.lower())
                pending.append(fk.child.lower())
    graph: dict[str, list[_CascadeRef]] = {}
    for fk in foreign_keys:
        if fk.parent.lower() not in reachable:
            continue
        if fk.on_delete in _UNLOGGED_DELETE_ACTIONS or fk.on_update not in _INERT_UPDATE_ACTIONS:
            msg = "A foreign key action would change rows that the change log does not record."
            raise RepositoryError(msg, "UNSUPPORTED_FK_ACTION")
        if fk.on_delete == "CASCADE":
            graph.setdefault(fk.parent.lower(), []).append(_CascadeRef(fk.child, fk.pairs))
    return graph


def _collect_cascade(
    conn: sqlite3.Connection, root: TableInfo, root_row: dict[str, object]
) -> list[tuple[TableInfo, dict[str, object]]]:
    """The row and every row a delete of it cascades to (children first found, parent first)."""
    graph = _cascade_graph(conn, root.name)
    infos: dict[str, TableInfo] = {root.name: root}
    found: list[tuple[TableInfo, dict[str, object]]] = []
    seen: set[tuple[str, tuple[object, ...]]] = set()
    stack: list[tuple[TableInfo, dict[str, object]]] = [(root, root_row)]
    while stack:
        info, row = stack.pop()
        identity = (info.name, tuple(row[column] for column in info.primary_key))
        if identity in seen:
            continue
        seen.add(identity)
        found.append((info, row))
        children: list[tuple[TableInfo, dict[str, object]]] = []
        for ref in graph.get(info.name.lower(), []):
            child_info = infos.get(ref.child)
            if child_info is None:
                child_info = infos[ref.child] = table_info(conn, ref.child)
                if not child_info.primary_key:
                    msg = "A cascaded table has no primary key."
                    raise RepositoryError(msg, "NO_PRIMARY_KEY")
            values = [row[parent_column] for _, parent_column in ref.pairs]
            if any(value is None for value in values):
                continue
            columns = ", ".join(_quote(column) for column in child_info.columns)
            where = " AND ".join(f"{_quote(child_column)} = ?" for child_column, _ in ref.pairs)
            order = ", ".join(_quote(column) for column in child_info.primary_key)
            sql = f"SELECT {columns} FROM {_quote(child_info.name)} WHERE {where} ORDER BY {order}"
            for values_row in _rows(conn, sql, values):
                children.append(
                    (child_info, dict(zip(child_info.columns, values_row, strict=True)))
                )
        stack.extend(reversed(children))
    return found


def delete(ctx: WriteContext, table: str, key: Key) -> int:
    """Delete one row and log it together with every row the delete cascades to.

    Returns the total number of rows deleted (the row itself and its cascaded descendants); one
    ``delete`` log row with the full pre-image is written for each. Raises
    :class:`RowNotFoundError` when the row does not exist and :class:`ForeignKeyError`
    (``ROW_IN_USE``) when a ``RESTRICT`` reference refuses the delete; nothing is logged then.
    """
    with transaction(ctx.conn):
        info = _writable_table(ctx.conn, table)
        resolved = _resolve_key(info, key)
        root_row = _select_by_key(ctx.conn, info, resolved)
        if root_row is None:
            msg = "The row does not exist."
            raise RowNotFoundError(msg)
        affected = _collect_cascade(ctx.conn, info, root_row)
        where = " AND ".join(f"{_quote(column)} = ?" for column in resolved)
        sql = f"DELETE FROM {_quote(table)} WHERE {where}"
        try:
            ctx.conn.execute(sql, list(resolved.values()))
        except sqlite3.IntegrityError as exc:
            msg = f"The row is still in use ({exc.sqlite_errorname})."
            raise ForeignKeyError(msg) from exc
        for affected_info, row in affected:
            if _select_by_key(ctx.conn, affected_info, _row_key(affected_info, row)) is not None:
                msg = "A row that should have been deleted is still there."
                raise RepositoryError(msg, "CASCADE_MISMATCH")
        for affected_info, row in affected:
            _log_row(
                ctx, affected_info, "delete", _row_key(affected_info, row), before=row, after=None
            )
        return len(affected)
