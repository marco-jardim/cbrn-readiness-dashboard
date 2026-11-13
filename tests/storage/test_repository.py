# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for ``cbrn_dashboard.storage.repository`` (PLAN T1.4).

Real database files under ``tmp_path``, migrated with the real migrations. The hierarchy tables
(``t_parent`` ...) and the ``staff_member`` table used for the redaction checks are fictitious and
created here, so the tests do not depend on which later migrations exist.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import closing
from pathlib import Path

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.storage.db import (
    DatabaseError,
    ReadOnlyDatabaseError,
    open_database,
    transaction,
)
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate
from cbrn_dashboard.storage.repository import (
    REDACTED_COLUMNS,
    ConstraintViolationError,
    ForeignKeyError,
    RepositoryError,
    RowNotFoundError,
    UnknownColumnError,
    UnknownTableError,
    WriteContext,
    delete,
    fetch_row,
    insert,
    log_event,
    redact_row,
    row_to_json,
    update,
)

NOW = "2026-03-05T12:00:00Z"
OPERATOR = "operator-1"

TEST_SCHEMA = (
    "CREATE TABLE t_parent ("
    " id INTEGER PRIMARY KEY, name TEXT NOT NULL, qty INTEGER NOT NULL DEFAULT 0) STRICT",
    "CREATE TABLE t_child ("
    " id INTEGER PRIMARY KEY,"
    " parent_id INTEGER NOT NULL REFERENCES t_parent(id) ON DELETE CASCADE,"
    " note TEXT) STRICT",
    "CREATE TABLE t_grandchild ("
    " id INTEGER PRIMARY KEY,"
    " child_id INTEGER NOT NULL REFERENCES t_child(id) ON DELETE CASCADE,"
    " note TEXT) STRICT",
    "CREATE TABLE t_pair ( a INTEGER NOT NULL, b TEXT NOT NULL, v REAL, PRIMARY KEY (a, b)) STRICT",
    "CREATE TABLE t_user_of ("
    " id INTEGER PRIMARY KEY,"
    " parent_id INTEGER NOT NULL REFERENCES t_parent(id) ON DELETE RESTRICT) STRICT",
    "CREATE TABLE t_node ("
    " id INTEGER PRIMARY KEY,"
    " parent_id INTEGER REFERENCES t_node(id) ON DELETE CASCADE) STRICT",
    "CREATE TABLE IF NOT EXISTS staff_member ("
    " id INTEGER PRIMARY KEY,"
    " identifier TEXT NOT NULL UNIQUE,"
    " label TEXT,"
    " category TEXT,"
    " active_from TEXT NOT NULL,"
    " active_until TEXT) STRICT",
)


# --------------------------------------------------------------------------- helpers


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "repo.sqlite3"


@pytest.fixture
def ctx(tmp_path: Path, db_path: Path) -> Iterator[WriteContext]:
    conn = open_and_migrate(
        db_path, data_dir=tmp_path, identity=DatabaseIdentity.REAL, backup=False
    )
    try:
        for statement in TEST_SCHEMA:
            conn.execute(statement)
        yield WriteContext(conn, FixedClock.at(NOW), OPERATOR)
    finally:
        conn.close()


def _query(
    conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()
) -> list[dict[str, object]]:
    cursor = conn.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, tuple(row), strict=True)) for row in cursor.fetchall()]


def _logs(conn: sqlite3.Connection, entity: str | None = None) -> list[dict[str, object]]:
    rows = _query(conn, "SELECT * FROM change_log ORDER BY id")
    return [row for row in rows if entity is None or row["entity"] == entity]


def _count(conn: sqlite3.Connection, table: str) -> int:
    rows = _query(conn, f"SELECT count(*) AS n FROM {table}")
    count = rows[0]["n"]
    assert isinstance(count, int)
    return count


def _json(value: object) -> dict[str, object]:
    assert isinstance(value, str)
    loaded = json.loads(value)
    assert isinstance(loaded, dict)
    return loaded


def _new_parent(ctx: WriteContext, name: str = "alpha", qty: int = 0) -> int:
    new_id = insert(ctx, "t_parent", {"name": name, "qty": qty})
    assert new_id is not None
    return new_id


# --------------------------------------------------------------------------- insert


def test_insert_writes_one_log_row_with_full_after_image(ctx: WriteContext) -> None:
    new_id = insert(ctx, "t_parent", {"name": "alpha"})
    assert isinstance(new_id, int)
    assert fetch_row(ctx.conn, "t_parent", new_id) == {"id": new_id, "name": "alpha", "qty": 0}

    logs = _logs(ctx.conn)
    assert len(logs) == 1
    row = logs[0]
    assert row["entity"] == "t_parent"
    assert row["entity_id"] == new_id
    assert row["entity_key"] is None
    assert row["action"] == "insert"
    assert row["before_json"] is None
    assert _json(row["after_json"]) == {"id": new_id, "name": "alpha", "qty": 0}  # incl. default
    assert row["operator"] == OPERATOR
    assert row["at_utc"] == NOW
    assert str(row["at_utc"]).endswith("Z")


def test_log_time_comes_from_the_injected_clock(ctx: WriteContext) -> None:
    later = WriteContext(ctx.conn, FixedClock.at("2030-01-02T03:04:05+02:00"))
    insert(later, "t_parent", {"name": "x"})
    row = _logs(ctx.conn)[0]
    assert row["at_utc"] == "2030-01-02T01:04:05Z"
    assert row["operator"] == ""


def test_insert_with_default_values_only(ctx: WriteContext) -> None:
    ctx.conn.execute("CREATE TABLE t_defaults (id INTEGER PRIMARY KEY, n INTEGER DEFAULT 7) STRICT")
    new_id = insert(ctx, "t_defaults", {})
    assert new_id is not None
    assert _json(_logs(ctx.conn)[0]["after_json"]) == {"id": new_id, "n": 7}


def test_insert_constraint_violation_is_wrapped_and_logs_nothing(ctx: WriteContext) -> None:
    with pytest.raises(ConstraintViolationError) as caught:
        insert(ctx, "t_parent", {"qty": 1})  # name is NOT NULL
    assert caught.value.code == "CONSTRAINT_VIOLATION"
    assert isinstance(caught.value, DatabaseError)
    assert _logs(ctx.conn) == []
    assert not ctx.conn.in_transaction


def test_insert_with_missing_parent_row_is_a_constraint_violation(ctx: WriteContext) -> None:
    with pytest.raises(ConstraintViolationError):
        insert(ctx, "t_child", {"parent_id": 999})
    assert _logs(ctx.conn) == []


def test_bytes_values_are_unsupported(ctx: WriteContext) -> None:
    with pytest.raises(RepositoryError) as caught:
        insert(ctx, "t_parent", {"name": b"raw"})
    assert caught.value.code == "UNSUPPORTED_VALUE"
    assert _logs(ctx.conn) == []
    assert _count(ctx.conn, "t_parent") == 0


# --------------------------------------------------------------------------- update


def test_update_logs_full_before_and_after(ctx: WriteContext) -> None:
    parent = _new_parent(ctx, "alpha", 1)
    assert update(ctx, "t_parent", parent, {"qty": 5}) is True

    assert fetch_row(ctx.conn, "t_parent", parent) == {"id": parent, "name": "alpha", "qty": 5}
    logs = _logs(ctx.conn)
    assert [log["action"] for log in logs] == ["insert", "update"]
    row = logs[1]
    assert row["entity"] == "t_parent"
    assert row["entity_id"] == parent
    assert row["entity_key"] is None
    assert _json(row["before_json"]) == {"id": parent, "name": "alpha", "qty": 1}
    assert _json(row["after_json"]) == {"id": parent, "name": "alpha", "qty": 5}
    assert row["operator"] == OPERATOR
    assert row["at_utc"] == NOW


def test_update_without_actual_change_writes_and_logs_nothing(ctx: WriteContext) -> None:
    parent = _new_parent(ctx, "alpha", 1)
    before_logs = _logs(ctx.conn)
    assert update(ctx, "t_parent", parent, {"qty": 1, "name": "alpha"}) is False
    assert update(ctx, "t_parent", parent, {}) is False
    assert update(ctx, "t_parent", parent, {"id": parent}) is False
    assert _logs(ctx.conn) == before_logs


def test_update_of_a_missing_row_raises(ctx: WriteContext) -> None:
    with pytest.raises(RowNotFoundError) as caught:
        update(ctx, "t_parent", 12345, {"qty": 1})
    assert caught.value.code == "ROW_NOT_FOUND"
    assert isinstance(caught.value, RepositoryError)
    assert _logs(ctx.conn) == []


def test_update_cannot_change_the_primary_key(ctx: WriteContext) -> None:
    parent = _new_parent(ctx)
    with pytest.raises(RepositoryError) as caught:
        update(ctx, "t_parent", parent, {"id": parent + 100})
    assert caught.value.code == "PRIMARY_KEY_CHANGE"
    assert fetch_row(ctx.conn, "t_parent", parent) is not None


def test_update_constraint_violation_is_wrapped_and_logs_nothing(ctx: WriteContext) -> None:
    parent = _new_parent(ctx)
    logs = _logs(ctx.conn)
    with pytest.raises(ConstraintViolationError):
        update(ctx, "t_parent", parent, {"name": None})
    assert _logs(ctx.conn) == logs
    assert fetch_row(ctx.conn, "t_parent", parent) == {"id": parent, "name": "alpha", "qty": 0}


def test_keys_must_fit_the_table(ctx: WriteContext) -> None:
    parent = _new_parent(ctx)
    bad_keys: list[int | Mapping[str, object]] = [
        True,
        {"id": parent, "name": "alpha"},
        {"name": "alpha"},
    ]
    for bad_key in bad_keys:
        with pytest.raises(RepositoryError) as caught:
            update(ctx, "t_parent", bad_key, {"qty": 3})
        assert caught.value.code == "INVALID_KEY"
    with pytest.raises(RepositoryError) as caught:
        update(ctx, "t_pair", 1, {"v": 1.0})  # natural-key table needs a mapping
    assert caught.value.code == "INVALID_KEY"


# --------------------------------------------------------------------------- natural keys


def test_natural_key_table_is_logged_with_entity_key(ctx: WriteContext) -> None:
    assert insert(ctx, "t_pair", {"a": 1, "b": "x", "v": 1.5}) is None
    assert update(ctx, "t_pair", {"a": 1, "b": "x"}, {"v": 2.5}) is True
    assert delete(ctx, "t_pair", {"b": "x", "a": 1}) == 1
    assert fetch_row(ctx.conn, "t_pair", {"a": 1, "b": "x"}) is None

    logs = _logs(ctx.conn, "t_pair")
    assert [log["action"] for log in logs] == ["insert", "update", "delete"]
    for log in logs:
        assert log["entity_id"] is None
        assert log["entity_key"] == '{"a":1,"b":"x"}'
    assert _json(logs[0]["after_json"]) == {"a": 1, "b": "x", "v": 1.5}
    assert _json(logs[1]["before_json"]) == {"a": 1, "b": "x", "v": 1.5}
    assert _json(logs[1]["after_json"]) == {"a": 1, "b": "x", "v": 2.5}
    assert _json(logs[2]["before_json"]) == {"a": 1, "b": "x", "v": 2.5}
    assert logs[2]["after_json"] is None


def test_real_setting_table_uses_entity_key(ctx: WriteContext) -> None:
    insert(ctx, "setting", {"key": "readiness", "value_json": '{"p01":1}'})
    update(ctx, "setting", {"key": "readiness"}, {"value_json": '{"p01":2}'})
    logs = _logs(ctx.conn, "setting")
    assert [log["entity_key"] for log in logs] == ['{"key":"readiness"}'] * 2
    assert [log["entity_id"] for log in logs] == [None, None]
    assert _json(logs[1]["after_json"]) == {"key": "readiness", "value_json": '{"p01":2}'}


def test_non_ascii_key_is_stored_unescaped(ctx: WriteContext) -> None:
    insert(ctx, "t_pair", {"a": 2, "b": "ação"})
    assert _logs(ctx.conn)[0]["entity_key"] == '{"a":2,"b":"ação"}'


# --------------------------------------------------------------------------- delete and cascade


def test_delete_single_row(ctx: WriteContext) -> None:
    parent = _new_parent(ctx, "alpha", 4)
    assert delete(ctx, "t_parent", parent) == 1
    assert fetch_row(ctx.conn, "t_parent", parent) is None
    row = _logs(ctx.conn)[-1]
    assert row["action"] == "delete"
    assert row["entity"] == "t_parent"
    assert row["entity_id"] == parent
    assert _json(row["before_json"]) == {"id": parent, "name": "alpha", "qty": 4}
    assert row["after_json"] is None
    assert row["operator"] == OPERATOR
    assert row["at_utc"] == NOW


def test_delete_of_a_missing_row_raises(ctx: WriteContext) -> None:
    with pytest.raises(RowNotFoundError):
        delete(ctx, "t_parent", 999)
    assert _logs(ctx.conn) == []


def test_cascaded_delete_logs_every_descendant(ctx: WriteContext) -> None:
    parent = _new_parent(ctx, "doomed")
    other = _new_parent(ctx, "survivor")
    child_ids = [insert(ctx, "t_child", {"parent_id": parent, "note": f"c{n}"}) for n in (1, 2)]
    assert all(child_ids)
    first, second = child_ids
    grandchild_ids = [
        insert(ctx, "t_grandchild", {"child_id": first, "note": "g1"}),
        insert(ctx, "t_grandchild", {"child_id": second, "note": "g2"}),
        insert(ctx, "t_grandchild", {"child_id": second, "note": "g3"}),
    ]
    other_child = insert(ctx, "t_child", {"parent_id": other, "note": "keep"})

    pre_images = {
        ("t_parent", parent): fetch_row(ctx.conn, "t_parent", parent),
        **{("t_child", cid): fetch_row(ctx.conn, "t_child", cid) for cid in child_ids if cid},
        **{
            ("t_grandchild", gid): fetch_row(ctx.conn, "t_grandchild", gid)
            for gid in grandchild_ids
            if gid
        },
    }
    assert len(pre_images) == 6
    assert all(image is not None for image in pre_images.values())
    logs_before = len(_logs(ctx.conn))

    assert delete(ctx, "t_parent", parent) == 1 + 2 + 3

    new_logs = _logs(ctx.conn)[logs_before:]
    assert len(new_logs) == 6
    assert {log["action"] for log in new_logs} == {"delete"}
    assert [log["entity"] for log in new_logs].count("t_parent") == 1
    assert [log["entity"] for log in new_logs].count("t_child") == 2
    assert [log["entity"] for log in new_logs].count("t_grandchild") == 3
    logged = {(log["entity"], log["entity_id"]): _json(log["before_json"]) for log in new_logs}
    assert logged == pre_images
    assert all(log["after_json"] is None for log in new_logs)
    assert all(log["operator"] == OPERATOR and log["at_utc"] == NOW for log in new_logs)

    assert _count(ctx.conn, "t_grandchild") == 0
    assert _count(ctx.conn, "t_child") == 1
    assert fetch_row(ctx.conn, "t_parent", parent) is None
    assert fetch_row(ctx.conn, "t_parent", other) is not None
    assert other_child is not None
    assert fetch_row(ctx.conn, "t_child", other_child) is not None


def test_cascade_through_a_self_reference_terminates(ctx: WriteContext) -> None:
    root = insert(ctx, "t_node", {})
    assert root is not None
    middle = insert(ctx, "t_node", {"parent_id": root})
    assert middle is not None
    leaf = insert(ctx, "t_node", {"parent_id": middle})
    assert leaf is not None
    ctx.conn.execute("UPDATE t_node SET parent_id = ? WHERE id = ?", (leaf, root))  # a cycle
    logs_before = len(_logs(ctx.conn))

    assert delete(ctx, "t_node", root) == 3

    new_logs = _logs(ctx.conn)[logs_before:]
    assert len(new_logs) == 3
    assert {log["entity_id"] for log in new_logs} == {root, middle, leaf}
    assert _count(ctx.conn, "t_node") == 0


def test_restrict_delete_fails_and_leaves_no_log_row(ctx: WriteContext) -> None:
    parent = _new_parent(ctx)
    child = insert(ctx, "t_child", {"parent_id": parent})
    assert child is not None
    insert(ctx, "t_user_of", {"parent_id": parent})
    logs_before = _logs(ctx.conn)

    with pytest.raises(ForeignKeyError) as caught:
        delete(ctx, "t_parent", parent)

    assert caught.value.code == "ROW_IN_USE"
    assert isinstance(caught.value, RepositoryError)
    assert _logs(ctx.conn) == logs_before
    assert fetch_row(ctx.conn, "t_parent", parent) is not None
    assert fetch_row(ctx.conn, "t_child", child) is not None
    assert not ctx.conn.in_transaction


def test_restrict_failure_inside_an_outer_transaction_leaves_no_log_row(ctx: WriteContext) -> None:
    parent = _new_parent(ctx)
    insert(ctx, "t_user_of", {"parent_id": parent})
    logs_before = _logs(ctx.conn)
    with transaction(ctx.conn):
        with pytest.raises(ForeignKeyError):
            delete(ctx, "t_parent", parent)
        assert _logs(ctx.conn) == logs_before  # nothing was logged before the failure
    assert _logs(ctx.conn) == logs_before


# --------------------------------------------------------------------------- transactions


def test_rollback_removes_the_change_and_its_log_row(ctx: WriteContext) -> None:
    kept = _new_parent(ctx, "kept")
    logs_before = _logs(ctx.conn)

    def failing_block() -> None:
        with transaction(ctx.conn):
            insert(ctx, "t_parent", {"name": "gone"})
            update(ctx, "t_parent", kept, {"qty": 9})
            delete(ctx, "t_parent", kept)
            assert len(_logs(ctx.conn)) == len(logs_before) + 3  # visible inside the transaction
            msg = "boom"
            raise RuntimeError(msg)

    with pytest.raises(RuntimeError):
        failing_block()

    assert _logs(ctx.conn) == logs_before
    assert _count(ctx.conn, "t_parent") == 1
    assert fetch_row(ctx.conn, "t_parent", kept) == {"id": kept, "name": "kept", "qty": 0}


def test_helpers_join_an_outer_transaction_and_commit_together(ctx: WriteContext) -> None:
    with transaction(ctx.conn):
        first = _new_parent(ctx, "one")
        update(ctx, "t_parent", first, {"qty": 2})
    assert [log["action"] for log in _logs(ctx.conn)] == ["insert", "update"]
    assert not ctx.conn.in_transaction


def test_helper_alone_commits_its_own_transaction(ctx: WriteContext, db_path: Path) -> None:
    _new_parent(ctx)
    assert not ctx.conn.in_transaction
    with closing(open_database(db_path, read_only=True)) as reader:
        assert _count(reader, "t_parent") == 1
        assert len(_logs(reader)) == 1


# --------------------------------------------------------------------------- append-only log


def test_change_log_cannot_be_updated_or_deleted_directly(ctx: WriteContext) -> None:
    _new_parent(ctx)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        ctx.conn.execute("UPDATE change_log SET operator = 'someone else'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        ctx.conn.execute("DELETE FROM change_log")
    assert len(_logs(ctx.conn)) == 1
    assert _logs(ctx.conn)[0]["operator"] == OPERATOR


def test_change_log_is_not_writable_through_the_helpers(ctx: WriteContext) -> None:
    for call in (
        lambda: insert(ctx, "change_log", {"at_utc": NOW, "entity": "x", "action": "insert"}),
        lambda: update(ctx, "change_log", 1, {"operator": "x"}),
        lambda: delete(ctx, "change_log", 1),
    ):
        with pytest.raises(RepositoryError) as caught:
            call()
        assert caught.value.code == "PROTECTED_TABLE"


# --------------------------------------------------------------------------- redaction

LABEL_1 = "Fictitious Label QX"
IDENT_1 = "DEMO-ZEBRA-7731"
LABEL_2 = "Fictitious Label RZ"
IDENT_2 = "DEMO-GIRAFFE-4412"
NEEDLES = (LABEL_1, IDENT_1, LABEL_2, IDENT_2, "ZEBRA", "GIRAFFE", "Fictitious")


def _assert_absent_from_change_log(conn: sqlite3.Connection) -> None:
    logs = _logs(conn)
    assert logs
    for row in logs:
        for value in row.values():
            for needle in NEEDLES:
                assert needle not in str(value)


def test_personal_free_text_columns_are_configured() -> None:
    assert REDACTED_COLUMNS["staff_member"] == {"identifier", "label"}
    assert REDACTED_COLUMNS["ppe_certification"] == {"reference"}
    assert REDACTED_COLUMNS["academic_degree"] == {"field"}


def test_personal_values_never_reach_change_log(ctx: WriteContext) -> None:
    staff = insert(
        ctx,
        "staff_member",
        {
            "identifier": IDENT_1,
            "label": LABEL_1,
            "category": "alpha",
            "active_from": "2026-01-01",
        },
    )
    assert staff is not None
    assert update(
        ctx, "staff_member", staff, {"identifier": IDENT_2, "label": LABEL_2, "category": "beta"}
    )
    assert update(ctx, "staff_member", staff, {"label": None})  # only a redacted column changes
    assert fetch_row(ctx.conn, "staff_member", staff) is not None  # the table keeps the value
    assert delete(ctx, "staff_member", staff) == 1

    _assert_absent_from_change_log(ctx.conn)

    insert_log, rename_log, only_label_log, delete_log = _logs(ctx.conn, "staff_member")
    assert insert_log["action"] == "insert"
    assert insert_log["entity_id"] == staff
    assert insert_log["entity_key"] is None
    assert insert_log["before_json"] is None
    inserted = _json(insert_log["after_json"])
    assert inserted["id"] == staff
    assert inserted["identifier"] == {"redacted": True}
    assert inserted["label"] == {"redacted": True}
    assert inserted["category"] == "alpha"
    assert inserted["active_from"] == "2026-01-01"

    before = _json(rename_log["before_json"])
    after = _json(rename_log["after_json"])
    assert before["identifier"] == {"redacted": True}
    assert before["label"] == {"redacted": True}
    assert after["identifier"] == {"redacted": True, "changed": True}
    assert after["label"] == {"redacted": True, "changed": True}
    assert before["category"] == "alpha"  # the non-personal column keeps old and new values
    assert after["category"] == "beta"
    assert "changed" not in str(after["active_from"])

    after_only_label = _json(only_label_log["after_json"])  # still written
    assert only_label_log["action"] == "update"
    assert after_only_label["label"] == {"redacted": True, "changed": True}
    assert after_only_label["identifier"] == {"redacted": True}
    assert after_only_label["category"] == "beta"

    assert delete_log["action"] == "delete"
    assert delete_log["after_json"] is None
    assert _json(delete_log["before_json"])["identifier"] == {"redacted": True}
    assert _json(delete_log["before_json"])["label"] == {"redacted": True}


def test_redaction_has_no_side_door_through_row_to_json_and_log_event(
    ctx: WriteContext,
) -> None:
    row: Mapping[str, object] = {"id": 1, "identifier": IDENT_1, "label": LABEL_1, "category": "c"}
    text = row_to_json("staff_member", row)
    assert IDENT_1 not in text
    assert LABEL_1 not in text
    assert json.loads(text)["category"] == "c"
    assert redact_row("staff_member", row, {"label"})["label"] == {
        "redacted": True,
        "changed": True,
    }
    assert row["label"] == LABEL_1  # the input is not modified
    assert row_to_json("t_parent", {"label": "visible"}) == '{"label":"visible"}'

    log_event(
        ctx,
        "staff_member",
        "update",
        entity_key={"identifier": IDENT_1},
        before=row,
        after={**row, "label": LABEL_2},
    )
    _assert_absent_from_change_log(ctx.conn)


# --------------------------------------------------------------------------- identifiers


INJECTION_TABLES = (
    "t_parent; DROP TABLE t_parent",
    "nope",
    "T_PARENT",
    "t_parent--",
    "",
    "t-parent",
)
INJECTION_COLUMNS = ("name = 1 --", "nope", "NAME", 'name"', "name; DROP TABLE t_parent")


@pytest.mark.parametrize("table", INJECTION_TABLES)
def test_unknown_or_malformed_table_names_are_rejected(ctx: WriteContext, table: str) -> None:
    parent = _new_parent(ctx)
    logs = _logs(ctx.conn)
    calls = (
        lambda: insert(ctx, table, {"name": "x"}),
        lambda: update(ctx, table, parent, {"qty": 1}),
        lambda: delete(ctx, table, parent),
        lambda: fetch_row(ctx.conn, table, parent),
    )
    for call in calls:
        with pytest.raises(UnknownTableError) as caught:
            call()
        assert caught.value.code == "UNKNOWN_TABLE"
        assert isinstance(caught.value, RepositoryError)
    assert _logs(ctx.conn) == logs
    assert fetch_row(ctx.conn, "t_parent", parent) == {"id": parent, "name": "alpha", "qty": 0}


@pytest.mark.parametrize("column", INJECTION_COLUMNS)
def test_unknown_or_malformed_column_names_are_rejected(ctx: WriteContext, column: str) -> None:
    parent = _new_parent(ctx)
    logs = _logs(ctx.conn)
    calls = (
        lambda: insert(ctx, "t_parent", {column: "x"}),
        lambda: update(ctx, "t_parent", parent, {column: "x"}),
        lambda: update(ctx, "t_parent", parent, {"qty": 3, column: "x"}),
        lambda: fetch_row(ctx.conn, "t_pair", {column: 1}),
    )
    for call in calls:
        with pytest.raises(UnknownColumnError) as caught:
            call()
        assert caught.value.code == "UNKNOWN_COLUMN"
        assert isinstance(caught.value, RepositoryError)
    assert _logs(ctx.conn) == logs
    assert fetch_row(ctx.conn, "t_parent", parent) == {"id": parent, "name": "alpha", "qty": 0}


def test_values_that_look_like_sql_are_stored_verbatim(ctx: WriteContext) -> None:
    nasty = "x'); DROP TABLE t_parent; --"
    parent = _new_parent(ctx, nasty)
    assert fetch_row(ctx.conn, "t_parent", parent) == {"id": parent, "name": nasty, "qty": 0}
    assert _json(_logs(ctx.conn)[0]["after_json"])["name"] == nasty


# --------------------------------------------------------------------------- actions and events


def test_invalid_actions_are_rejected(ctx: WriteContext) -> None:
    for action in ("bogus", "delete", "restore", "", "INSERT"):
        with pytest.raises(RepositoryError) as caught:
            insert(ctx, "t_parent", {"name": "x"}, action=action)
        assert caught.value.code == "INVALID_ACTION"
    for action in ("bogus", "", "Restore"):
        with pytest.raises(RepositoryError) as caught:
            log_event(ctx, "database", action)
        assert caught.value.code == "INVALID_ACTION"
    assert _logs(ctx.conn) == []
    assert _count(ctx.conn, "t_parent") == 0


def test_import_action_is_stored(ctx: WriteContext) -> None:
    new_id = insert(ctx, "t_parent", {"name": "csv"}, action="import")
    row = _logs(ctx.conn)[0]
    assert row["action"] == "import"
    assert row["entity_id"] == new_id
    assert _json(row["after_json"])["name"] == "csv"


def test_log_event_restore_is_stored(ctx: WriteContext) -> None:
    log_event(
        ctx,
        "database",
        "restore",
        entity_key={"source": "backup-001"},
        after={"schema_version": 5},
    )
    log_event(ctx, "t_parent", "restore", entity_id=3, before={"id": 3}, after=None)
    first, second = _logs(ctx.conn)
    assert first["action"] == "restore"
    assert first["entity"] == "database"
    assert first["entity_id"] is None
    assert first["entity_key"] == '{"source":"backup-001"}'
    assert first["before_json"] is None
    assert _json(first["after_json"]) == {"schema_version": 5}
    assert first["operator"] == OPERATOR
    assert first["at_utc"] == NOW
    assert second["entity_id"] == 3
    assert _json(second["before_json"]) == {"id": 3}
    assert second["after_json"] is None


def test_log_event_rejects_an_empty_entity(ctx: WriteContext) -> None:
    with pytest.raises(RepositoryError):
        log_event(ctx, "", "restore")
    assert _logs(ctx.conn) == []


# --------------------------------------------------------------------------- read-only


def test_writes_through_a_read_only_connection_raise(ctx: WriteContext, db_path: Path) -> None:
    parent = _new_parent(ctx)
    logs = _logs(ctx.conn)
    with closing(open_database(db_path, read_only=True)) as reader:
        read_only_ctx = WriteContext(reader, FixedClock.at(NOW), OPERATOR)
        with pytest.raises(ReadOnlyDatabaseError):
            insert(read_only_ctx, "t_parent", {"name": "x"})
        with pytest.raises(ReadOnlyDatabaseError):
            update(read_only_ctx, "t_parent", parent, {"qty": 2})
        with pytest.raises(ReadOnlyDatabaseError):
            delete(read_only_ctx, "t_parent", parent)
        with pytest.raises(ReadOnlyDatabaseError):
            log_event(read_only_ctx, "database", "restore")
        assert fetch_row(reader, "t_parent", parent) == {"id": parent, "name": "alpha", "qty": 0}
    assert _logs(ctx.conn) == logs
