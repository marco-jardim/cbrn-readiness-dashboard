# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for ``cbrn_dashboard.storage.settings_repo`` (PLAN 3.5, T1.5)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import config as cfg
from cbrn_dashboard.domain.config import (
    PLACEHOLDERS,
    ConfigError,
    ReadinessConfig,
    flagged_placeholder_ids,
)
from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import (
    confirm_placeholder,
    confirmed_placeholders,
    get_value,
    load_config,
    needs_badge,
    save_config,
    set_value,
    unconfirm_placeholder,
)

OPERATOR = "DEMO-OPERATOR"
CLOCK = FixedClock.at("2026-03-05T12:00:00Z")

CHANGED = ReadinessConfig(
    cert_warning_days=60,
    snapshot_monthly=False,
    ppe_hierarchy_enabled=True,
    ppe_hierarchy={"A": ("B", "C")},
    ppe_validity_months={"A": 24, "B": None, "C": None},
    default_currency="USD",
    institution_name="Test institution",
    report_handling_notice="Demo notice",
)


def _ctx(conn: DatabaseConnection) -> WriteContext:
    return WriteContext(conn, CLOCK, OPERATOR)


def _log(conn: DatabaseConnection) -> list[dict[str, object]]:
    cursor = conn.execute(
        "SELECT operator, entity, entity_id, entity_key, action, before_json, after_json"
        " FROM change_log ORDER BY id"
    )
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _count(conn: DatabaseConnection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0])


def _db_path(conn: DatabaseConnection) -> Path:
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(str(row[2]))


# --------------------------------------------------------------------------- configuration


def test_default_config_loads_from_an_empty_table(migrated_db: DatabaseConnection) -> None:
    assert _count(migrated_db, "setting") == 0
    assert load_config(migrated_db) == ReadinessConfig()


def test_saving_the_defaults_writes_nothing(migrated_db: DatabaseConnection) -> None:
    assert save_config(_ctx(migrated_db), ReadinessConfig()) == ()
    assert _count(migrated_db, "setting") == 0
    assert _count(migrated_db, "change_log") == 0


def test_changed_config_round_trips_through_the_file(migrated_db: DatabaseConnection) -> None:
    changed = save_config(_ctx(migrated_db), CHANGED)
    assert set(changed) == {
        "config.cert_warning_days",
        "config.snapshot_monthly",
        "config.ppe_hierarchy_enabled",
        "config.ppe_hierarchy",
        "config.ppe_validity_months",
        "config.default_currency",
        "config.institution_name",
        "config.report_handling_notice",
    }
    path = _db_path(migrated_db)
    migrated_db.close()
    reopened = open_database(path)
    try:
        assert load_config(reopened) == CHANGED
        assert load_config(reopened).ppe_hierarchy == {"A": ("B", "C")}
    finally:
        reopened.close()


def test_each_changed_key_is_logged_once(migrated_db: DatabaseConnection) -> None:
    changed = save_config(_ctx(migrated_db), ReadinessConfig(cert_warning_days=60))
    assert changed == ("config.cert_warning_days",)
    rows = _log(migrated_db)
    assert len(rows) == 1
    row = rows[0]
    assert row["entity"] == "setting"
    assert row["entity_id"] is None
    assert row["operator"] == OPERATOR
    assert row["action"] == "insert"
    assert json.loads(str(row["entity_key"])) == {"key": "config.cert_warning_days"}
    assert row["before_json"] is None
    assert json.loads(str(row["after_json"])) == {
        "key": "config.cert_warning_days",
        "value_json": "60",
    }

    assert save_config(_ctx(migrated_db), ReadinessConfig(cert_warning_days=45)) == (
        "config.cert_warning_days",
    )
    update = _log(migrated_db)[1]
    assert update["action"] == "update"
    assert json.loads(str(update["before_json"]))["value_json"] == "60"
    assert json.loads(str(update["after_json"]))["value_json"] == "45"
    assert json.loads(str(update["entity_key"])) == {"key": "config.cert_warning_days"}


def test_only_changed_keys_are_written(migrated_db: DatabaseConnection) -> None:
    ctx = _ctx(migrated_db)
    save_config(ctx, CHANGED)
    stored_before = _count(migrated_db, "setting")
    log_before = _count(migrated_db, "change_log")
    assert stored_before == 8  # only the 8 keys that differ from the defaults

    changed = save_config(ctx, CHANGED.with_changes(maintenance_warning_days=14))
    assert changed == ("config.maintenance_warning_days",)
    assert _count(migrated_db, "setting") == stored_before + 1
    assert _count(migrated_db, "change_log") == log_before + 1

    # back to the default: the stored key is updated (not deleted), still one row
    assert save_config(ctx, CHANGED) == ("config.maintenance_warning_days",)
    assert load_config(migrated_db) == CHANGED


def test_a_no_op_save_adds_no_row(migrated_db: DatabaseConnection) -> None:
    ctx = _ctx(migrated_db)
    save_config(ctx, CHANGED)
    log_before = _count(migrated_db, "change_log")
    assert save_config(ctx, CHANGED) == ()
    assert _count(migrated_db, "change_log") == log_before


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"cert_warning_days": -1}, "NEGATIVE_DAYS"),
        ({"min_passphrase_length": 11}, "PASSPHRASE_FLOOR"),
        ({"daily_backups_kept": 1}, "BACKUP_FLOOR"),
        ({"small_count_threshold": 0}, "THRESHOLD_TOO_LOW"),
        ({"default_currency": "XXX"}, "INVALID_CURRENCY"),
        ({"cert_warning_days": True}, "INVALID_TYPE"),
        ({"cert_warning_days": "90"}, "INVALID_TYPE"),
        ({"cert_warning_days": 10**9}, "VALUE_TOO_LARGE"),
    ],
)
def test_an_invalid_config_is_rejected_and_nothing_is_written(
    migrated_db: DatabaseConnection, changes: dict[str, object], code: str
) -> None:
    # CHANGED also has valid changed keys that must not land; replace() allows wrong types
    config = dataclasses.replace(CHANGED, **changes)
    with pytest.raises(ConfigError) as info:
        save_config(_ctx(migrated_db), config)
    assert info.value.code == code
    assert _count(migrated_db, "setting") == 0
    assert _count(migrated_db, "change_log") == 0


def test_floors_are_accepted_exactly_at_the_floor(migrated_db: DatabaseConnection) -> None:
    config = ReadinessConfig(min_passphrase_length=12, daily_backups_kept=2)
    assert save_config(_ctx(migrated_db), config) == ("config.daily_backups_kept",)
    assert load_config(migrated_db) == config


def test_a_stored_value_below_the_floor_is_not_silently_replaced(
    migrated_db: DatabaseConnection,
) -> None:
    migrated_db.execute(
        "INSERT INTO setting (key, value_json) VALUES ('config.min_passphrase_length', '8')"
    )
    with pytest.raises(ConfigError) as info:
        load_config(migrated_db)
    assert info.value.code == "PASSPHRASE_FLOOR"


def test_corrupt_json_is_reported(migrated_db: DatabaseConnection) -> None:
    migrated_db.execute(
        "INSERT INTO setting (key, value_json) VALUES ('config.cert_warning_days', '{oops')"
    )
    with pytest.raises(ConfigError) as info:
        load_config(migrated_db)
    assert info.value.code == "CORRUPT_SETTING"
    assert info.value.field == "config.cert_warning_days"
    assert "oops" not in str(info.value)


def test_a_wrong_typed_stored_value_is_reported(migrated_db: DatabaseConnection) -> None:
    migrated_db.execute(
        "INSERT INTO setting (key, value_json) VALUES ('config.snapshot_monthly', '\"yes\"')"
    )
    with pytest.raises(ConfigError) as info:
        load_config(migrated_db)
    assert info.value.code == "INVALID_TYPE"


def test_unrelated_and_unknown_keys_do_not_disturb_the_config(
    migrated_db: DatabaseConnection,
) -> None:
    migrated_db.execute("INSERT INTO setting (key, value_json) VALUES ('config.future', '1')")
    migrated_db.execute("INSERT INTO setting (key, value_json) VALUES ('other.key', '{oops')")
    assert load_config(migrated_db) == ReadinessConfig()


# --------------------------------------------------------------------------- confirmed state


def test_confirming_hides_the_badge_and_is_logged(migrated_db: DatabaseConnection) -> None:
    ctx = _ctx(migrated_db)
    assert needs_badge(migrated_db, "P01") is True
    assert confirmed_placeholders(migrated_db) == frozenset()

    confirm_placeholder(ctx, "P01")

    assert needs_badge(migrated_db, "P01") is False
    assert needs_badge(migrated_db, "P02") is True
    assert confirmed_placeholders(migrated_db) == frozenset({"P01"})
    rows = _log(migrated_db)
    # the pinned value of P01 and the confirmation itself
    assert len(rows) == 2
    assert all(row["entity"] == "setting" for row in rows)
    assert all(row["operator"] == OPERATOR for row in rows)
    assert json.loads(str(rows[0]["entity_key"])) == {"key": "config.cert_warning_days"}
    assert json.loads(str(rows[1]["entity_key"])) == {"key": "confirmed.P01"}
    assert json.loads(str(rows[1]["after_json"])) == {
        "key": "confirmed.P01",
        "value_json": "true",
    }
    assert load_config(migrated_db) == ReadinessConfig()  # not mixed into the configuration


def test_confirming_is_idempotent(migrated_db: DatabaseConnection) -> None:
    ctx = _ctx(migrated_db)
    confirm_placeholder(ctx, "A05")
    log_after_first = _count(migrated_db, "change_log")
    confirm_placeholder(ctx, "A05")
    assert log_after_first == 2  # the pinned field and the confirmation
    assert _count(migrated_db, "change_log") == log_after_first
    assert confirmed_placeholders(migrated_db) == frozenset({"A05"})


def _stored_keys(conn: DatabaseConnection) -> list[str]:
    return [str(row[0]) for row in conn.execute("SELECT key FROM setting ORDER BY key")]


def test_confirming_pins_the_current_values_even_at_the_default(
    migrated_db: DatabaseConnection,
) -> None:
    assert _count(migrated_db, "setting") == 0
    confirm_placeholder(_ctx(migrated_db), "P01")
    assert _stored_keys(migrated_db) == ["config.cert_warning_days", "confirmed.P01"]
    assert get_value(migrated_db, "config.cert_warning_days") == 90

    confirm_placeholder(_ctx(migrated_db), "P04")
    assert "config.snapshot_monthly" in _stored_keys(migrated_db)
    assert "config.snapshot_on_report" in _stored_keys(migrated_db)

    # a non-default value that was already saved is the one that gets pinned (and stays)
    save_config(_ctx(migrated_db), ReadinessConfig(maintenance_warning_days=14))
    confirm_placeholder(_ctx(migrated_db), "P02")
    assert get_value(migrated_db, "config.maintenance_warning_days") == 14
    assert load_config(migrated_db).maintenance_warning_days == 14


def test_a_confirmed_value_survives_a_changed_code_default(
    migrated_db: DatabaseConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    confirm_placeholder(_ctx(migrated_db), "P01")

    @dataclasses.dataclass(frozen=True)
    class NextRelease(ReadinessConfig):
        cert_warning_days: int = 120
        maintenance_warning_days: int = 45

    monkeypatch.setattr(cfg, "ReadinessConfig", NextRelease)
    loaded = load_config(migrated_db)
    assert loaded.cert_warning_days == 90  # confirmed here: pinned in this database
    assert loaded.maintenance_warning_days == 45  # not confirmed: follows the new default


def test_confirming_a_placeholder_without_fields_writes_no_config_row(
    migrated_db: DatabaseConnection,
) -> None:
    for placeholder_id in ("P03", "P07", "A06", "A07", "A09", "A10"):
        assert cfg.placeholder(placeholder_id).fields == ()
        confirm_placeholder(_ctx(migrated_db), placeholder_id)
    assert _stored_keys(migrated_db) == [
        "confirmed.A06",
        "confirmed.A07",
        "confirmed.A09",
        "confirmed.A10",
        "confirmed.P03",
        "confirmed.P07",
    ]


def test_confirming_never_changes_the_code_flag(migrated_db: DatabaseConnection) -> None:
    before = (PLACEHOLDERS, flagged_placeholder_ids())
    for item in PLACEHOLDERS:
        confirm_placeholder(_ctx(migrated_db), item.id)
        assert needs_badge(migrated_db, item.id) is False
    assert (cfg.PLACEHOLDERS, flagged_placeholder_ids()) == before
    assert all(item.placeholder for item in cfg.PLACEHOLDERS)
    assert confirmed_placeholders(migrated_db) == frozenset(item.id for item in PLACEHOLDERS)


def test_unconfirm_restores_the_badge(migrated_db: DatabaseConnection) -> None:
    ctx = _ctx(migrated_db)
    confirm_placeholder(ctx, "P05")
    unconfirm_placeholder(ctx, "P05")
    assert needs_badge(migrated_db, "P05") is True
    rows = _log(migrated_db)
    # confirming pins the value of P05's only field, then records the confirmation; unconfirming
    # deletes just the confirmation
    assert [(row["action"], json.loads(str(row["entity_key"]))["key"]) for row in rows] == [
        ("insert", "config.min_passphrase_length"),
        ("insert", "confirmed.P05"),
        ("delete", "confirmed.P05"),
    ]
    # the pinned value stays: unconfirming only brings the badge back, it never changes the value
    assert _stored_keys(migrated_db) == ["config.min_passphrase_length"]
    assert get_value(migrated_db, "config.min_passphrase_length") == 12
    assert confirmed_placeholders(migrated_db) == frozenset()
    log_before = len(rows)
    unconfirm_placeholder(ctx, "P05")  # idempotent
    assert _count(migrated_db, "change_log") == log_before


def test_a_cleared_code_flag_hides_the_badge_without_confirmation(
    migrated_db: DatabaseConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    cleared = dataclasses.replace(PLACEHOLDERS[0], placeholder=False)
    monkeypatch.setattr(cfg, "PLACEHOLDERS", (cleared, *PLACEHOLDERS[1:]))
    assert needs_badge(migrated_db, "P01") is False
    assert needs_badge(migrated_db, "P02") is True


def test_confirmation_is_per_database(migrated_db: DatabaseConnection, tmp_path: Path) -> None:
    other = open_and_migrate(
        tmp_path / "other.sqlite3",
        data_dir=tmp_path,
        identity=DatabaseIdentity.REAL,
        backup=False,
    )
    try:
        confirm_placeholder(_ctx(migrated_db), "P01")
        assert needs_badge(migrated_db, "P01") is False
        assert needs_badge(other, "P01") is True
        assert confirmed_placeholders(other) == frozenset()
    finally:
        other.close()


def test_unknown_placeholder_is_rejected(migrated_db: DatabaseConnection) -> None:
    for call in (
        lambda: confirm_placeholder(_ctx(migrated_db), "P99"),
        lambda: unconfirm_placeholder(_ctx(migrated_db), "P99"),
        lambda: needs_badge(migrated_db, "P99"),
    ):
        with pytest.raises(ConfigError) as info:
            call()
        assert info.value.code == "UNKNOWN_PLACEHOLDER"
    assert _count(migrated_db, "setting") == 0


def test_a_stored_confirmation_of_an_unknown_id_is_ignored(
    migrated_db: DatabaseConnection,
) -> None:
    migrated_db.execute("INSERT INTO setting (key, value_json) VALUES ('confirmed.P99', 'true')")
    migrated_db.execute("INSERT INTO setting (key, value_json) VALUES ('confirmed.P02', 'false')")
    assert confirmed_placeholders(migrated_db) == frozenset()


# --------------------------------------------------------------------------- generic values


def test_get_and_set_value_round_trip(migrated_db: DatabaseConnection) -> None:
    ctx = _ctx(migrated_db)
    key = "backup.last_encrypted_utc"
    assert get_value(migrated_db, key) is None
    assert set_value(ctx, key, "2026-03-05T12:00:00Z") is True
    assert get_value(migrated_db, key) == "2026-03-05T12:00:00Z"
    assert set_value(ctx, key, "2026-03-05T12:00:00Z") is False
    assert set_value(ctx, key, "2026-04-01T08:00:00Z") is True
    assert get_value(migrated_db, key) == "2026-04-01T08:00:00Z"

    assert set_value(ctx, "some.structure", {"a": [1, 2, None], "b": True}) is True
    assert get_value(migrated_db, "some.structure") == {"a": [1, 2, None], "b": True}

    rows = _log(migrated_db)
    assert [row["action"] for row in rows] == ["insert", "update", "insert"]
    assert json.loads(str(rows[0]["entity_key"])) == {"key": key}
    assert all(row["operator"] == OPERATOR for row in rows)


def test_set_value_rejects_bad_input(migrated_db: DatabaseConnection) -> None:
    ctx = _ctx(migrated_db)
    with pytest.raises(ConfigError) as info:
        set_value(ctx, "x.y", object())
    assert info.value.code == "INVALID_VALUE"
    with pytest.raises(ConfigError) as info:
        set_value(ctx, "x.y", float("nan"))
    assert info.value.code == "INVALID_VALUE"
    for bad_key in ("", "Bad Key", "1abc", "x" * 101):
        with pytest.raises(ConfigError) as info:
            set_value(ctx, bad_key, 1)
        assert info.value.code == "INVALID_KEY"
    with pytest.raises(ConfigError) as info:
        set_value(ctx, "config.cert_warning_days", 1)
    assert info.value.code == "RESERVED_KEY"
    assert _count(migrated_db, "setting") == 0


def test_get_value_reports_corrupt_json(migrated_db: DatabaseConnection) -> None:
    migrated_db.execute("INSERT INTO setting (key, value_json) VALUES ('x.y', '{oops')")
    with pytest.raises(ConfigError) as info:
        get_value(migrated_db, "x.y")
    assert info.value.code == "CORRUPT_SETTING"
