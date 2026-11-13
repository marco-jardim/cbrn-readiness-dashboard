# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for ``cbrn_dashboard.domain.config`` (PLAN 3.5, T1.5).

The expected tables below are written out on purpose: they are neither read from PLAN.md nor
derived from the code, so a silent change of a default or of a flag fails here.
"""

from __future__ import annotations

import dataclasses
import json
from types import MappingProxyType

import pytest

from cbrn_dashboard.domain import config as cfg
from cbrn_dashboard.domain.config import (
    DAILY_BACKUPS_FLOOR,
    PASSPHRASE_LENGTH_FLOOR,
    PLACEHOLDERS,
    ConfigError,
    PlaceholderKind,
    ReadinessConfig,
    check_registry,
    flagged_placeholder_ids,
    from_settings,
    local_only_fields,
    placeholder,
    placeholder_for_field,
    to_settings,
    validate,
)

EXPECTED_DEFAULTS: dict[str, object] = {
    "cert_warning_days": 90,
    "maintenance_warning_days": 30,
    "snapshot_monthly": True,
    "snapshot_on_report": True,
    "min_passphrase_length": 12,
    "daily_backups_kept": 7,
    "budget_prorate_target": True,
    "backup_reminder_days": 30,
    "ppe_hierarchy_enabled": False,
    "ppe_hierarchy": {},
    "ppe_validity_months": {"A": None, "B": None, "C": None},
    "degraded_counts_as_available": False,
    "default_currency": "BRL",
    "small_count_threshold": 5,
    "institution_name": "",
    "unit_name": "",
    "operator_label": "",
    "report_handling_notice": "",
}

L = PlaceholderKind.LOCAL_ONLY
G = PlaceholderKind.GENERIC_DEFAULT

# (id, kind, fields, question, flag)
EXPECTED_REGISTRY: list[tuple[str, PlaceholderKind, tuple[str, ...], str | None, bool]] = [
    ("P01", G, ("cert_warning_days",), "Q2", True),
    ("P02", G, ("maintenance_warning_days",), "Q6", True),
    ("P03", L, (), "Q1", True),
    ("P04", G, ("snapshot_monthly", "snapshot_on_report"), "Q9", True),
    ("P05", G, ("min_passphrase_length",), "Q11", True),
    ("P06", G, ("daily_backups_kept",), None, True),
    ("P07", G, (), "Q15", True),
    ("P08", G, ("budget_prorate_target",), "Q8", True),
    ("P09", G, ("backup_reminder_days",), "Q11", True),
    ("P10", L, ("report_handling_notice",), "Q10", True),
    ("A02", G, ("ppe_hierarchy_enabled", "ppe_hierarchy"), "Q2", True),
    ("A04", G, ("ppe_validity_months",), "Q2", True),
    ("A05", G, ("degraded_counts_as_available",), "Q5", True),
    ("A08", G, ("default_currency",), "Q8", True),
    ("A11", G, ("small_count_threshold",), "Q10", True),
    ("D18", L, ("institution_name", "unit_name"), "Q17", True),
]


# --------------------------------------------------------------------------- defaults


def test_defaults_equal_the_explicit_table() -> None:
    config = ReadinessConfig()
    actual = {spec.name: getattr(config, spec.name) for spec in dataclasses.fields(config)}
    assert actual == EXPECTED_DEFAULTS
    assert set(actual) == set(EXPECTED_DEFAULTS)


def test_default_configuration_is_valid() -> None:
    validate(ReadinessConfig())


def test_floor_constants() -> None:
    assert PASSPHRASE_LENGTH_FLOOR == 12
    assert DAILY_BACKUPS_FLOOR == 2


def test_configuration_is_frozen_and_comparable() -> None:
    config = ReadinessConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.cert_warning_days = 1
    assert config == ReadinessConfig()
    assert hash(config) == hash(ReadinessConfig())


def test_mapping_fields_are_read_only() -> None:
    config = ReadinessConfig()
    with pytest.raises(TypeError):
        config.ppe_validity_months["A"] = 12
    with pytest.raises(TypeError):
        config.ppe_hierarchy["A"] = ("B",)
    source = {"A": ("B",)}
    built = ReadinessConfig(ppe_hierarchy=source)
    source["B"] = ("C",)  # changing the caller's dict must not leak in
    assert dict(built.ppe_hierarchy) == {"A": ("B",)}
    assert isinstance(built.ppe_hierarchy, MappingProxyType)


def test_with_changes_replaces_fields_and_keeps_the_rest() -> None:
    changed = ReadinessConfig().with_changes(cert_warning_days=60, ppe_hierarchy={"A": ("B", "C")})
    assert changed.cert_warning_days == 60
    assert changed.ppe_hierarchy == {"A": ("B", "C")}
    assert changed.maintenance_warning_days == 30
    assert isinstance(changed, ReadinessConfig)
    with pytest.raises(TypeError):
        ReadinessConfig().with_changes(**{"no_such_field": 1})


def test_with_changes_none_keeps_the_current_value_and_false_or_zero_change_it() -> None:
    base = ReadinessConfig(cert_warning_days=60, institution_name="Test institution")
    assert base.with_changes() == base
    assert base.with_changes(cert_warning_days=None) == base
    changed = base.with_changes(cert_warning_days=0, snapshot_monthly=False, institution_name="")
    assert changed.cert_warning_days == 0
    assert changed.snapshot_monthly is False
    assert changed.institution_name == ""
    assert base.cert_warning_days == 60  # the original is untouched


# --------------------------------------------------------------------------- local-only values


def test_local_only_values_have_no_code_default_and_are_marked() -> None:
    config = ReadinessConfig()
    assert config.institution_name == ""
    assert config.unit_name == ""
    assert config.report_handling_notice == ""
    assert local_only_fields() == frozenset(
        {"institution_name", "unit_name", "report_handling_notice"}
    )
    for placeholder_id in ("P03", "P10", "D18"):
        assert placeholder(placeholder_id).kind is PlaceholderKind.LOCAL_ONLY
        assert placeholder(placeholder_id).placeholder is True
    assert placeholder("P03").fields == ()  # the targets live in their own table


def test_operator_label_is_not_a_placeholder() -> None:
    assert placeholder_for_field("operator_label") is None
    assert ReadinessConfig().operator_label == ""


# --------------------------------------------------------------------------- registry


def test_registry_equals_the_explicit_table() -> None:
    actual = [(p.id, p.kind, p.fields, p.question, p.placeholder) for p in PLACEHOLDERS]
    assert actual == EXPECTED_REGISTRY


def test_flagged_placeholder_ids_in_registry_order() -> None:
    assert flagged_placeholder_ids() == tuple(row[0] for row in EXPECTED_REGISTRY if row[4])
    assert flagged_placeholder_ids() == (
        "P01", "P02", "P03", "P04", "P05", "P06", "P07", "P08", "P09", "P10",
        "A02", "A04", "A05", "A08", "A11", "D18",
    )  # fmt: skip
    assert isinstance(flagged_placeholder_ids(), tuple)


def test_flagged_ids_follow_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    cleared = dataclasses.replace(PLACEHOLDERS[0], placeholder=False)
    with monkeypatch.context() as patch:
        patch.setattr(cfg, "PLACEHOLDERS", (cleared, *PLACEHOLDERS[1:]))
        assert flagged_placeholder_ids() == tuple(p.id for p in PLACEHOLDERS[1:])
    assert flagged_placeholder_ids()[0] == "P01"


def test_placeholder_lookup() -> None:
    assert placeholder("P05").fields == ("min_passphrase_length",)
    with pytest.raises(KeyError):
        placeholder("P99")
    found = placeholder_for_field("snapshot_on_report")
    assert found is not None
    assert found.id == "P04"
    assert placeholder_for_field("cert_warning_days") is not None
    assert placeholder_for_field("no_such_field") is None


def test_registry_invariants_hold() -> None:
    check_registry()
    names = {spec.name for spec in dataclasses.fields(ReadinessConfig)}
    seen: set[str] = set()
    for item in PLACEHOLDERS:
        for name in item.fields:
            assert name in names
            assert name not in seen
            seen.add(name)
    assert "operator_label" not in seen
    assert len({item.id for item in PLACEHOLDERS}) == len(PLACEHOLDERS)


def test_registry_check_detects_broken_invariants(monkeypatch: pytest.MonkeyPatch) -> None:
    broken_sets = [
        (*PLACEHOLDERS, cfg.Placeholder("X01", G, ("no_such_field",), None)),
        (*PLACEHOLDERS, cfg.Placeholder("X01", G, ("cert_warning_days",), None)),  # field twice
        (*PLACEHOLDERS, cfg.Placeholder("P01", G, (), None)),  # id twice
        (*PLACEHOLDERS, cfg.Placeholder("X01", G, ("operator_label",), None)),
        (*PLACEHOLDERS, cfg.Placeholder("X01", L, ("default_currency",), None)),  # not empty
        (*PLACEHOLDERS, cfg.Placeholder("X01", L, (), None, placeholder=False)),
    ]
    for broken in broken_sets:
        with monkeypatch.context() as patch:
            patch.setattr(cfg, "PLACEHOLDERS", broken)
            with pytest.raises(ConfigError) as info:
                check_registry()
            assert info.value.code == "REGISTRY_INVALID"
    check_registry()


# --------------------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("changes", "code", "field"),
    [
        ({"cert_warning_days": -1}, "NEGATIVE_DAYS", "cert_warning_days"),
        ({"maintenance_warning_days": -5}, "NEGATIVE_DAYS", "maintenance_warning_days"),
        ({"backup_reminder_days": -1}, "NEGATIVE_DAYS", "backup_reminder_days"),
        ({"cert_warning_days": 1.5}, "NEGATIVE_DAYS", "cert_warning_days"),
        ({"cert_warning_days": "90"}, "NEGATIVE_DAYS", "cert_warning_days"),
        ({"cert_warning_days": True}, "INVALID_TYPE", "cert_warning_days"),
        ({"backup_reminder_days": False}, "INVALID_TYPE", "backup_reminder_days"),
        ({"small_count_threshold": 0}, "THRESHOLD_TOO_LOW", "small_count_threshold"),
        ({"small_count_threshold": True}, "INVALID_TYPE", "small_count_threshold"),
        ({"small_count_threshold": "5"}, "INVALID_TYPE", "small_count_threshold"),
        ({"min_passphrase_length": 11}, "PASSPHRASE_FLOOR", "min_passphrase_length"),
        ({"min_passphrase_length": 0}, "PASSPHRASE_FLOOR", "min_passphrase_length"),
        ({"min_passphrase_length": True}, "INVALID_TYPE", "min_passphrase_length"),
        ({"daily_backups_kept": 1}, "BACKUP_FLOOR", "daily_backups_kept"),
        ({"daily_backups_kept": 0}, "BACKUP_FLOOR", "daily_backups_kept"),
        ({"daily_backups_kept": True}, "INVALID_TYPE", "daily_backups_kept"),
        ({"default_currency": "XXX"}, "INVALID_CURRENCY", "default_currency"),
        ({"default_currency": "brl"}, "INVALID_CURRENCY", "default_currency"),
        ({"default_currency": 986}, "INVALID_CURRENCY", "default_currency"),
        ({"ppe_hierarchy": {"D": ("A",)}}, "INVALID_PPE_LEVEL", "ppe_hierarchy"),
        ({"ppe_hierarchy": {"A": ("D",)}}, "INVALID_PPE_LEVEL", "ppe_hierarchy"),
        ({"ppe_hierarchy": {"A": ("A",)}}, "INVALID_PPE_LEVEL", "ppe_hierarchy"),
        ({"ppe_hierarchy": {"A": "B"}}, "INVALID_PPE_LEVEL", "ppe_hierarchy"),
        ({"ppe_hierarchy": ["A"]}, "INVALID_TYPE", "ppe_hierarchy"),
        ({"ppe_validity_months": {"D": 12}}, "INVALID_PPE_LEVEL", "ppe_validity_months"),
        ({"ppe_validity_months": {"A": 0}}, "INVALID_VALIDITY_MONTHS", "ppe_validity_months"),
        ({"ppe_validity_months": {"A": -3}}, "INVALID_VALIDITY_MONTHS", "ppe_validity_months"),
        ({"ppe_validity_months": {"A": True}}, "INVALID_TYPE", "ppe_validity_months"),
        ({"ppe_validity_months": {"A": "12"}}, "INVALID_TYPE", "ppe_validity_months"),
        ({"institution_name": 5}, "INVALID_TEXT", "institution_name"),
        ({"unit_name": "x" * 201}, "INVALID_TEXT", "unit_name"),
        ({"operator_label": None}, "INVALID_TEXT", "operator_label"),
        ({"report_handling_notice": "y" * 201}, "INVALID_TEXT", "report_handling_notice"),
        ({"snapshot_monthly": 1}, "INVALID_TYPE", "snapshot_monthly"),
        ({"snapshot_on_report": "yes"}, "INVALID_TYPE", "snapshot_on_report"),
        ({"budget_prorate_target": None}, "INVALID_TYPE", "budget_prorate_target"),
        ({"ppe_hierarchy_enabled": 0}, "INVALID_TYPE", "ppe_hierarchy_enabled"),
        ({"degraded_counts_as_available": 1}, "INVALID_TYPE", "degraded_counts_as_available"),
    ],
)
def test_invalid_values_are_rejected_with_code_and_field(
    changes: dict[str, object], code: str, field: str
) -> None:
    # dataclasses.replace bypasses the static typing of with_changes, so wrong types (and None)
    # can reach validate() on purpose
    config = dataclasses.replace(ReadinessConfig(), **changes)
    with pytest.raises(ConfigError) as info:
        validate(config)
    assert info.value.code == code
    assert info.value.field == field
    assert isinstance(info.value, ValueError)


def test_boundary_values_are_accepted() -> None:
    validate(
        ReadinessConfig(
            cert_warning_days=0,
            maintenance_warning_days=0,
            backup_reminder_days=0,
            min_passphrase_length=12,
            daily_backups_kept=2,
            small_count_threshold=1,
            default_currency="USD",
            ppe_hierarchy={"A": ("B", "C"), "B": ("C",)},
            ppe_validity_months={"A": 1, "B": None, "C": 60},
            institution_name="i" * 200,
            unit_name="",
            report_handling_notice="n" * 200,
            operator_label="o" * 200,
        )
    )


def test_error_message_does_not_contain_the_value() -> None:
    secret = "SECRET-VALUE-" + "x" * 300
    with pytest.raises(ConfigError) as info:
        validate(ReadinessConfig(institution_name=secret))
    assert "SECRET-VALUE" not in str(info.value)


# --------------------------------------------------------------------------- (de)serialisation

NON_DEFAULT = ReadinessConfig(
    cert_warning_days=60,
    maintenance_warning_days=14,
    snapshot_monthly=False,
    snapshot_on_report=False,
    min_passphrase_length=16,
    daily_backups_kept=3,
    budget_prorate_target=False,
    backup_reminder_days=10,
    ppe_hierarchy_enabled=True,
    ppe_hierarchy={"A": ("B", "C"), "B": ("C",)},
    ppe_validity_months={"A": 24, "B": None, "C": 12},
    degraded_counts_as_available=True,
    default_currency="EUR",
    small_count_threshold=3,
    institution_name="Test institution",
    unit_name="Test unit",
    operator_label="DEMO-OPERATOR",
    report_handling_notice="Demo notice",
)


def test_to_settings_has_one_prefixed_key_per_field() -> None:
    values = to_settings(ReadinessConfig())
    assert set(values) == {"config." + name for name in EXPECTED_DEFAULTS}
    assert values["config.cert_warning_days"] == 90
    assert values["config.ppe_validity_months"] == {"A": None, "B": None, "C": None}
    assert values["config.ppe_hierarchy"] == {}


def test_to_settings_is_json_compatible() -> None:
    text = json.dumps(to_settings(NON_DEFAULT), sort_keys=True)
    assert json.loads(text)["config.ppe_hierarchy"] == {"A": ["B", "C"], "B": ["C"]}


def test_round_trip_of_a_non_default_configuration() -> None:
    assert from_settings(to_settings(NON_DEFAULT)) == NON_DEFAULT
    through_json = json.loads(json.dumps(to_settings(NON_DEFAULT)))
    restored = from_settings(through_json)
    assert restored == NON_DEFAULT
    assert restored.ppe_hierarchy == {"A": ("B", "C"), "B": ("C",)}
    assert restored.ppe_validity_months == {"A": 24, "B": None, "C": 12}


def test_round_trip_of_the_default_configuration() -> None:
    assert from_settings(to_settings(ReadinessConfig())) == ReadinessConfig()


def test_missing_keys_take_the_defaults_and_unknown_keys_are_ignored() -> None:
    config = from_settings(
        {
            "config.cert_warning_days": 45,
            "config.some_future_field": "ignored",
            "confirmed.P01": True,
            "other": 1,
        }
    )
    assert config == ReadinessConfig(cert_warning_days=45)
    assert from_settings({}) == ReadinessConfig()


@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("config.cert_warning_days", "90", "NEGATIVE_DAYS"),
        ("config.cert_warning_days", True, "INVALID_TYPE"),
        ("config.snapshot_monthly", 1, "INVALID_TYPE"),
        ("config.small_count_threshold", None, "INVALID_TYPE"),
        ("config.default_currency", 5, "INVALID_CURRENCY"),
        ("config.institution_name", 5, "INVALID_TEXT"),
        ("config.ppe_hierarchy", ["A"], "INVALID_TYPE"),
        ("config.ppe_hierarchy", {"A": "B"}, "INVALID_TYPE"),
        ("config.ppe_validity_months", [1], "INVALID_TYPE"),
        ("config.min_passphrase_length", 8, "PASSPHRASE_FLOOR"),
        ("config.daily_backups_kept", 1, "BACKUP_FLOOR"),
        ("config.ppe_hierarchy", {"A": ["A"]}, "INVALID_PPE_LEVEL"),
    ],
)
def test_stored_values_of_the_wrong_type_or_range_are_rejected(
    key: str, value: object, code: str
) -> None:
    with pytest.raises(ConfigError) as info:
        from_settings({key: value})
    assert info.value.code == code
