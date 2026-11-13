# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the config service (PLAN.md 3.5, 4.1, T6.1); fictitious values only."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import config as domain_config
from cbrn_dashboard.domain.config import PLACEHOLDERS, ReadinessConfig
from cbrn_dashboard.services.config import (
    CONFIG_ERROR_CODES,
    CORRUPT_SETTING,
    UNKNOWN_PLACEHOLDER,
    ConfigService,
)
from cbrn_dashboard.services.errors import READ_ONLY, ServiceError
from cbrn_dashboard.storage.db import DatabaseConnection
from tests.services.conftest import ChangeLogRows

NOW_TEXT = "2026-03-05T12:00:00Z"
OPERATOR = "op-demo"


@pytest.fixture
def service(db: DatabaseConnection, clock: FixedClock) -> ConfigService:
    return ConfigService(db, clock, lambda: OPERATOR)


def _error(call: Callable[[], object]) -> ServiceError:
    with pytest.raises(ServiceError) as info:
        call()
    return info.value


def _count(conn: DatabaseConnection, table: str) -> int:
    row = conn.execute(f"SELECT count(*) FROM {table}").fetchone()
    return int(row[0])


def _stored(conn: DatabaseConnection, key: str) -> object:
    row = conn.execute("SELECT value_json FROM setting WHERE key = ?", (key,)).fetchone()
    return None if row is None else json.loads(str(row[0]))


def _logged_keys(rows: list[dict[str, object]]) -> set[str]:
    return {str(json.loads(str(row["entity_key"]))["key"]) for row in rows}


# --------------------------------------------------------------------------- load and save


def test_load_returns_the_defaults_on_a_fresh_database(service: ConfigService) -> None:
    assert service.load() == ReadinessConfig()


def test_save_round_trips_and_logs_only_the_changed_keys(
    service: ConfigService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    before = len(change_log_rows(db))
    changed_config = ReadinessConfig().with_changes(
        cert_warning_days=120,
        ppe_hierarchy_enabled=True,
        ppe_hierarchy={"A": ("B",)},
        ppe_validity_months={"A": 24, "B": None, "C": None},
        operator_label="op-new",
    )

    changed = service.save(changed_config)

    expected = {
        "config.cert_warning_days",
        "config.ppe_hierarchy_enabled",
        "config.ppe_hierarchy",
        "config.ppe_validity_months",
        "config.operator_label",
    }
    assert set(changed) == expected
    assert service.load() == changed_config
    rows = change_log_rows(db)[before:]
    assert _logged_keys(rows) == expected
    assert len(rows) == len(expected)
    assert all(row["entity"] == "setting" and row["action"] == "insert" for row in rows)
    assert all(row["operator"] == OPERATOR and row["at_utc"] == NOW_TEXT for row in rows)


def test_saving_the_stored_configuration_again_writes_nothing(
    service: ConfigService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    config = ReadinessConfig().with_changes(unit_name="Demo unit")
    service.save(config)
    before = len(change_log_rows(db))

    assert service.save(config) == ()
    assert len(change_log_rows(db)) == before


def test_saving_a_later_change_logs_an_update_of_that_key_only(
    service: ConfigService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    first = ReadinessConfig().with_changes(unit_name="Demo unit", small_count_threshold=7)
    service.save(first)
    before = len(change_log_rows(db))

    assert service.save(first.with_changes(small_count_threshold=9)) == (
        "config.small_count_threshold",
    )
    rows = change_log_rows(db)[before:]
    assert len(rows) == 1
    assert rows[0]["action"] == "update"
    assert _logged_keys(rows) == {"config.small_count_threshold"}
    assert service.load().small_count_threshold == 9


_INVALID: tuple[tuple[ReadinessConfig, str, str], ...] = (
    (ReadinessConfig().with_changes(cert_warning_days=-1), "NEGATIVE_DAYS", "cert_warning_days"),
    (
        ReadinessConfig().with_changes(maintenance_warning_days=99999),
        "VALUE_TOO_LARGE",
        "maintenance_warning_days",
    ),
    (
        ReadinessConfig().with_changes(min_passphrase_length=11),
        "PASSPHRASE_FLOOR",
        "min_passphrase_length",
    ),
    (ReadinessConfig().with_changes(daily_backups_kept=1), "BACKUP_FLOOR", "daily_backups_kept"),
    (
        ReadinessConfig().with_changes(small_count_threshold=0),
        "THRESHOLD_TOO_LOW",
        "small_count_threshold",
    ),
    (
        ReadinessConfig().with_changes(default_currency="NOPE"),
        "INVALID_CURRENCY",
        "default_currency",
    ),
    (
        ReadinessConfig().with_changes(ppe_hierarchy={"Z": ()}),
        "INVALID_PPE_LEVEL",
        "ppe_hierarchy",
    ),
    (
        ReadinessConfig().with_changes(ppe_validity_months={"A": 0}),
        "INVALID_VALIDITY_MONTHS",
        "ppe_validity_months",
    ),
    (
        ReadinessConfig().with_changes(institution_name="x" * 201),
        "INVALID_TEXT",
        "institution_name",
    ),
    (
        ReadinessConfig().with_changes(backup_reminder_days="30"),  # type: ignore[arg-type]
        "INVALID_TYPE",
        "backup_reminder_days",
    ),
)


@pytest.mark.parametrize(("config", "code", "field"), _INVALID)
def test_an_invalid_configuration_is_refused_with_the_domain_code_and_nothing_is_written(
    service: ConfigService,
    db: DatabaseConnection,
    change_log_rows: ChangeLogRows,
    config: ReadinessConfig,
    code: str,
    field: str,
) -> None:
    settings_before = _count(db, "setting")
    log_before = len(change_log_rows(db))

    error = _error(lambda: service.save(config))

    assert (error.code, error.field) == (code, field)
    assert _count(db, "setting") == settings_before
    assert len(change_log_rows(db)) == log_before


def test_the_hard_floors_are_enforced_but_the_floor_values_are_accepted(
    service: ConfigService,
) -> None:
    low = ReadinessConfig().with_changes(min_passphrase_length=11, daily_backups_kept=1)
    assert _error(lambda: service.save(low)).code == "PASSPHRASE_FLOOR"
    assert _error(lambda: service.save(low.with_changes(min_passphrase_length=12))).code == (
        "BACKUP_FLOOR"
    )

    service.save(ReadinessConfig().with_changes(min_passphrase_length=12, daily_backups_kept=2))
    assert service.load().daily_backups_kept == 2


def test_a_corrupt_stored_setting_makes_load_fail_with_corrupt_setting(
    service: ConfigService, db: DatabaseConnection
) -> None:
    db.execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)",
        ("config.cert_warning_days", "not json"),
    )

    error = _error(service.load)

    assert error.code == CORRUPT_SETTING == "CORRUPT_SETTING"


def test_a_stored_value_of_the_wrong_type_makes_load_fail_with_corrupt_setting(
    service: ConfigService, db: DatabaseConnection
) -> None:
    db.execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)",
        ("config.cert_warning_days", '"ninety"'),
    )

    assert _error(service.load).code == CORRUPT_SETTING


# --------------------------------------------------------------------------- placeholders


def test_placeholders_are_the_registry_in_registry_order(service: ConfigService) -> None:
    items = service.placeholders()

    assert items == PLACEHOLDERS
    assert [item.id for item in items][:3] == ["P01", "P02", "P03"]


def test_needs_badge_confirm_and_unconfirm(
    service: ConfigService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    assert service.needs_badge("P01") is True
    before = len(change_log_rows(db))

    service.confirm("P01")

    assert service.needs_badge("P01") is False
    assert service.needs_badge("P02") is True
    rows = change_log_rows(db)[before:]
    assert _logged_keys(rows) == {"config.cert_warning_days", "confirmed.P01"}
    assert all(row["operator"] == OPERATOR and row["at_utc"] == NOW_TEXT for row in rows)

    service.unconfirm("P01")

    assert service.needs_badge("P01") is True
    assert _stored(db, "confirmed.P01") is None


def test_confirming_pins_the_current_value_even_when_it_is_the_default(
    service: ConfigService, db: DatabaseConnection
) -> None:
    assert _stored(db, "config.cert_warning_days") is None

    service.confirm("P01")

    assert _stored(db, "config.cert_warning_days") == 90
    assert _stored(db, "confirmed.P01") is True


def test_confirming_keeps_a_changed_value(service: ConfigService, db: DatabaseConnection) -> None:
    service.save(ReadinessConfig().with_changes(cert_warning_days=120))

    service.confirm("P01")

    assert _stored(db, "config.cert_warning_days") == 120
    assert service.load().cert_warning_days == 120


def test_confirm_and_unconfirm_are_idempotent(
    service: ConfigService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    service.confirm("P03")  # a placeholder without config fields
    before = len(change_log_rows(db))

    service.confirm("P03")
    service.unconfirm("P09")

    assert len(change_log_rows(db)) == before
    assert service.needs_badge("P03") is False


def test_an_unknown_placeholder_id_is_refused(
    service: ConfigService, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    before = len(change_log_rows(db))

    for call in (
        lambda: service.confirm("P99"),
        lambda: service.unconfirm("P99"),
        lambda: service.needs_badge("P99"),
    ):
        error = _error(call)
        assert error.code == UNKNOWN_PLACEHOLDER == "UNKNOWN_PLACEHOLDER"
    assert len(change_log_rows(db)) == before


# --------------------------------------------------------------------------- badge per field


def test_badge_for_field_follows_the_confirmation(service: ConfigService) -> None:
    assert service.badge_for_field("cert_warning_days") == "P01"
    assert service.badge_for_field("ppe_hierarchy") == "A02"

    service.confirm("P01")

    assert service.badge_for_field("cert_warning_days") is None
    assert service.badge_for_field("ppe_hierarchy") == "A02"

    service.unconfirm("P01")

    assert service.badge_for_field("cert_warning_days") == "P01"


def test_badge_for_field_is_none_for_fields_without_a_placeholder(service: ConfigService) -> None:
    assert service.badge_for_field("operator_label") is None
    assert service.badge_for_field("no_such_field") is None


# --------------------------------------------------------------------------- read-only


def test_a_read_only_connection_can_load_but_not_write(
    read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    service = ConfigService(read_only_db, clock, lambda: OPERATOR)
    log_before = _count(read_only_db, "change_log")

    assert service.load() == ReadinessConfig()
    assert service.needs_badge("P01") is True
    assert service.badge_for_field("cert_warning_days") == "P01"
    assert _error(lambda: service.save(ReadinessConfig().with_changes(unit_name="x"))).code == (
        READ_ONLY
    )
    assert _error(lambda: service.confirm("P01")).code == READ_ONLY
    assert _error(lambda: service.unconfirm("P01")).code == READ_ONLY
    assert _count(read_only_db, "change_log") == log_before


# --------------------------------------------------------------------------- error-code list


def _literal_codes(source: str) -> set[str]:
    return set(re.findall(r'ConfigError\(\s*"([A-Z_]+)"', source))


def test_config_error_codes_match_the_codes_in_the_domain_source() -> None:
    # Robust choice: scan the source of domain/config.py for ConfigError("CODE", ...) literals and
    # leave out the registry self-check, which is not part of validating a configuration.
    all_codes = _literal_codes(inspect.getsource(domain_config))
    registry_codes = _literal_codes(inspect.getsource(domain_config.check_registry))

    assert all_codes - registry_codes
    assert set(CONFIG_ERROR_CODES) == all_codes - registry_codes
    assert len(set(CONFIG_ERROR_CODES)) == len(CONFIG_ERROR_CODES)


def test_every_listed_config_error_code_is_actually_raised_by_save(service: ConfigService) -> None:
    raised = {_error(lambda c=config: service.save(c)).code for config, _, _ in _INVALID}

    assert raised == set(CONFIG_ERROR_CODES)
