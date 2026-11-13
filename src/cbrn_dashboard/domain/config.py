# SPDX-License-Identifier: GPL-3.0-or-later
"""Readiness configuration and the placeholder registry (PLAN.md section 3.5, D05, D18, T1.5).

Pure module: no Qt, no I/O, no storage imports, codes only (the UI translates the codes).

* :class:`ReadinessConfig` holds every configurable value of the readiness rules with the
  defaults of the plan. :func:`validate` rejects invalid values with a :class:`ConfigError` that
  carries a stable ``code`` and the offending ``field``.
* :data:`PLACEHOLDERS` is the code-level registry of section 3.5. Its ``placeholder`` flags are
  the release-level truth: constants of the release that are never changed at run time. The
  per-installation "confirmed" state lives in the database (``storage/settings_repo.py``) and only
  hides the badge there. Two kinds exist: ``LOCAL_ONLY`` values never get a code default and their
  flag is never cleared in code; ``GENERIC_DEFAULT`` values may be cleared only by a release
  commit.
* :func:`to_settings` / :func:`from_settings` convert the configuration to and from the flat
  ``config.<field>`` keys of the ``setting`` table.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Self

from cbrn_dashboard.domain.budget import DEFAULT_CURRENCY, is_valid_currency

__all__ = [
    "DAILY_BACKUPS_FLOOR",
    "MAX_DAILY_BACKUPS",
    "MAX_PASSPHRASE_LENGTH",
    "MAX_SMALL_COUNT_THRESHOLD",
    "MAX_VALIDITY_MONTHS",
    "MAX_WARNING_DAYS",
    "PASSPHRASE_LENGTH_FLOOR",
    "PLACEHOLDERS",
    "SETTING_PREFIX",
    "ConfigError",
    "Placeholder",
    "PlaceholderKind",
    "ReadinessConfig",
    "check_registry",
    "flagged_placeholder_ids",
    "from_settings",
    "local_only_fields",
    "placeholder",
    "placeholder_for_field",
    "to_settings",
    "validate",
]

#: Hard floor of the minimum backup passphrase length (P05), whatever the caller passes.
PASSPHRASE_LENGTH_FLOOR = 12
#: Hard floor of the number of daily local backups kept (P06).
DAILY_BACKUPS_FLOOR = 2
#: Largest accepted warning or reminder window in days (about ten years); keeps dates in range.
MAX_WARNING_DAYS = 3650
#: Largest accepted number of daily local backups kept.
MAX_DAILY_BACKUPS = 365
#: Largest accepted minimum backup passphrase length.
MAX_PASSPHRASE_LENGTH = 128
#: Largest accepted small-count suppression threshold.
MAX_SMALL_COUNT_THRESHOLD = 1000
#: Largest accepted certificate validity period in months (50 years).
MAX_VALIDITY_MONTHS = 600
#: Longest accepted free-text setting.
MAX_TEXT_LENGTH = 200
#: Prefix of the ``setting`` keys that hold the configuration.
SETTING_PREFIX = "config."

#: The personal-protective-equipment levels (A02, A04).
_PPE_LEVELS: tuple[str, ...] = ("A", "B", "C")

_DAY_FIELDS: tuple[str, ...] = (
    "cert_warning_days",
    "maintenance_warning_days",
    "backup_reminder_days",
)
_BOOL_FIELDS: tuple[str, ...] = (
    "snapshot_monthly",
    "snapshot_on_report",
    "budget_prorate_target",
    "ppe_hierarchy_enabled",
    "degraded_counts_as_available",
)
_TEXT_FIELDS: tuple[str, ...] = (
    "institution_name",
    "unit_name",
    "operator_label",
    "report_handling_notice",
)


# --------------------------------------------------------------------------- errors


class ConfigError(ValueError):
    """An invalid or unreadable configuration value.

    ``code`` is stable and translated by the UI; ``field`` names the offending field (or the
    setting key). The message never contains the value.
    """

    def __init__(self, code: str, field: str = "", message: str | None = None) -> None:
        super().__init__(message if message is not None else f"{code}: {field}")
        self.code = code
        self.field = field


# --------------------------------------------------------------------------- the configuration


def _default_hierarchy() -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({})


def _default_validity() -> Mapping[str, int | None]:
    return MappingProxyType({"A": None, "B": None, "C": None})


def _freeze_hierarchy(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    frozen: dict[object, object] = {
        key: tuple(item) if isinstance(item, list | tuple) else item for key, item in value.items()
    }
    return MappingProxyType(frozen)


def _freeze_validity(value: object) -> object:
    if not isinstance(value, Mapping):
        return value
    return MappingProxyType(dict(value))


def _pick[T](new: T | None, current: T) -> T:
    """``new`` unless it is ``None`` (meaning "keep"), then ``current``."""
    return current if new is None else new


@dataclass(frozen=True)
class ReadinessConfig:
    """Every configurable value of the readiness rules; the defaults are those of PLAN.md 3.5.

    The mapping fields are normalised to read-only mappings on construction. Construction does not
    validate: call :func:`validate` (the repository does it before every save). Consumers must
    only use configurations that passed :func:`validate`, as those returned by ``load_config`` and
    accepted by ``save_config`` do; an unvalidated instance may hold out-of-range values.
    """

    cert_warning_days: int = 90  # P01
    maintenance_warning_days: int = 30  # P02
    snapshot_monthly: bool = True  # P04
    snapshot_on_report: bool = True  # P04
    min_passphrase_length: int = 12  # P05, hard floor 12
    daily_backups_kept: int = 7  # P06, hard floor 2
    budget_prorate_target: bool = True  # P08
    backup_reminder_days: int = 30  # P09
    ppe_hierarchy_enabled: bool = False  # A02
    #: Levels a certificate at a level ALSO counts for; empty until Q2 is answered (A02).
    ppe_hierarchy: Mapping[str, tuple[str, ...]] = field(
        default_factory=_default_hierarchy, hash=False
    )
    #: Optional validity period in months per level; only pre-fills the form (A04).
    ppe_validity_months: Mapping[str, int | None] = field(
        default_factory=_default_validity, hash=False
    )
    degraded_counts_as_available: bool = False  # A05
    default_currency: str = DEFAULT_CURRENCY  # A08
    small_count_threshold: int = 5  # A11
    institution_name: str = ""  # D18, local-only
    unit_name: str = ""  # D18, local-only
    operator_label: str = ""  # D05, not a placeholder
    report_handling_notice: str = ""  # P10, local-only

    def __post_init__(self) -> None:
        object.__setattr__(self, "ppe_hierarchy", _freeze_hierarchy(self.ppe_hierarchy))
        object.__setattr__(self, "ppe_validity_months", _freeze_validity(self.ppe_validity_months))

    def with_changes(
        self,
        *,
        cert_warning_days: int | None = None,
        maintenance_warning_days: int | None = None,
        snapshot_monthly: bool | None = None,
        snapshot_on_report: bool | None = None,
        min_passphrase_length: int | None = None,
        daily_backups_kept: int | None = None,
        budget_prorate_target: bool | None = None,
        backup_reminder_days: int | None = None,
        ppe_hierarchy_enabled: bool | None = None,
        ppe_hierarchy: Mapping[str, tuple[str, ...]] | None = None,
        ppe_validity_months: Mapping[str, int | None] | None = None,
        degraded_counts_as_available: bool | None = None,
        default_currency: str | None = None,
        small_count_threshold: int | None = None,
        institution_name: str | None = None,
        unit_name: str | None = None,
        operator_label: str | None = None,
        report_handling_notice: str | None = None,
    ) -> Self:
        """A copy with the given fields replaced; ``None`` keeps the current value.

        No field of the configuration is itself ``None``, so ``None`` is free to mean "keep".
        Unknown field names raise ``TypeError`` (the signature has no ``**kwargs``).
        """
        return type(self)(
            cert_warning_days=_pick(cert_warning_days, self.cert_warning_days),
            maintenance_warning_days=_pick(maintenance_warning_days, self.maintenance_warning_days),
            snapshot_monthly=_pick(snapshot_monthly, self.snapshot_monthly),
            snapshot_on_report=_pick(snapshot_on_report, self.snapshot_on_report),
            min_passphrase_length=_pick(min_passphrase_length, self.min_passphrase_length),
            daily_backups_kept=_pick(daily_backups_kept, self.daily_backups_kept),
            budget_prorate_target=_pick(budget_prorate_target, self.budget_prorate_target),
            backup_reminder_days=_pick(backup_reminder_days, self.backup_reminder_days),
            ppe_hierarchy_enabled=_pick(ppe_hierarchy_enabled, self.ppe_hierarchy_enabled),
            ppe_hierarchy=_pick(ppe_hierarchy, self.ppe_hierarchy),
            ppe_validity_months=_pick(ppe_validity_months, self.ppe_validity_months),
            degraded_counts_as_available=_pick(
                degraded_counts_as_available, self.degraded_counts_as_available
            ),
            default_currency=_pick(default_currency, self.default_currency),
            small_count_threshold=_pick(small_count_threshold, self.small_count_threshold),
            institution_name=_pick(institution_name, self.institution_name),
            unit_name=_pick(unit_name, self.unit_name),
            operator_label=_pick(operator_label, self.operator_label),
            report_handling_notice=_pick(report_handling_notice, self.report_handling_notice),
        )


# --------------------------------------------------------------------------- validation


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_int(name: str, value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError("INVALID_TYPE", name)
    return value


def _validate_hierarchy(value: object) -> None:
    name = "ppe_hierarchy"
    if not isinstance(value, Mapping):
        raise ConfigError("INVALID_TYPE", name)
    for level, also in value.items():
        if not isinstance(level, str) or level not in _PPE_LEVELS:
            raise ConfigError("INVALID_PPE_LEVEL", name)
        if not isinstance(also, tuple):
            raise ConfigError("INVALID_PPE_LEVEL", name)
        for other in also:
            if not isinstance(other, str) or other not in _PPE_LEVELS or other == level:
                raise ConfigError("INVALID_PPE_LEVEL", name)


def _validate_validity(value: object) -> None:
    name = "ppe_validity_months"
    if not isinstance(value, Mapping):
        raise ConfigError("INVALID_TYPE", name)
    for level, months in value.items():
        if not isinstance(level, str) or level not in _PPE_LEVELS:
            raise ConfigError("INVALID_PPE_LEVEL", name)
        if months is None:
            continue
        if not _is_int(months):
            raise ConfigError("INVALID_TYPE", name)
        if months < 1:
            raise ConfigError("INVALID_VALIDITY_MONTHS", name)
        if months > MAX_VALIDITY_MONTHS:
            raise ConfigError("VALUE_TOO_LARGE", name)


def validate(config: ReadinessConfig) -> None:
    """Raise :class:`ConfigError` when a value is invalid; return ``None`` otherwise."""
    for name in _DAY_FIELDS:
        days = _require_int(name, getattr(config, name))
        if days < 0:
            raise ConfigError("NEGATIVE_DAYS", name)
        if days > MAX_WARNING_DAYS:
            raise ConfigError("VALUE_TOO_LARGE", name)
    for name in _BOOL_FIELDS:
        if not isinstance(getattr(config, name), bool):
            raise ConfigError("INVALID_TYPE", name)
    passphrase = _require_int("min_passphrase_length", config.min_passphrase_length)
    if passphrase < PASSPHRASE_LENGTH_FLOOR:
        raise ConfigError("PASSPHRASE_FLOOR", "min_passphrase_length")
    if passphrase > MAX_PASSPHRASE_LENGTH:
        raise ConfigError("VALUE_TOO_LARGE", "min_passphrase_length")
    backups = _require_int("daily_backups_kept", config.daily_backups_kept)
    if backups < DAILY_BACKUPS_FLOOR:
        raise ConfigError("BACKUP_FLOOR", "daily_backups_kept")
    if backups > MAX_DAILY_BACKUPS:
        raise ConfigError("VALUE_TOO_LARGE", "daily_backups_kept")
    threshold = _require_int("small_count_threshold", config.small_count_threshold)
    if threshold < 1:
        raise ConfigError("THRESHOLD_TOO_LOW", "small_count_threshold")
    if threshold > MAX_SMALL_COUNT_THRESHOLD:
        raise ConfigError("VALUE_TOO_LARGE", "small_count_threshold")
    currency: object = config.default_currency
    if not isinstance(currency, str) or not is_valid_currency(currency):
        raise ConfigError("INVALID_CURRENCY", "default_currency")
    _validate_hierarchy(config.ppe_hierarchy)
    _validate_validity(config.ppe_validity_months)
    for name in _TEXT_FIELDS:
        text: object = getattr(config, name)
        if not isinstance(text, str) or len(text) > MAX_TEXT_LENGTH:
            raise ConfigError("INVALID_TEXT", name)


# --------------------------------------------------------------------------- placeholder registry


class PlaceholderKind(StrEnum):
    """The two kinds of placeholder of PLAN.md 3.5."""

    LOCAL_ONLY = "local_only"
    GENERIC_DEFAULT = "generic_default"


@dataclass(frozen=True)
class Placeholder:
    """One line of the placeholder table.

    ``fields`` are the :class:`ReadinessConfig` fields it governs (possibly none), ``question`` the
    open question (``None`` when the item is purely technical) and ``placeholder`` the code-level
    flag, a constant of the release.
    """

    id: str
    kind: PlaceholderKind
    fields: tuple[str, ...]
    question: str | None
    placeholder: bool = True


_LOCAL = PlaceholderKind.LOCAL_ONLY
_GENERIC = PlaceholderKind.GENERIC_DEFAULT

PLACEHOLDERS: tuple[Placeholder, ...] = (
    Placeholder("P01", _GENERIC, ("cert_warning_days",), "Q2"),
    Placeholder("P02", _GENERIC, ("maintenance_warning_days",), "Q6"),
    # Indicator targets live in their own table (T6.1), so no config field.
    Placeholder("P03", _LOCAL, (), "Q1"),
    Placeholder("P04", _GENERIC, ("snapshot_monthly", "snapshot_on_report"), "Q9"),
    Placeholder("P05", _GENERIC, ("min_passphrase_length",), "Q11"),
    Placeholder("P06", _GENERIC, ("daily_backups_kept",), None),
    # The disclaimer wording lives in the translations, so no config field.
    Placeholder("P07", _GENERIC, (), "Q15"),
    Placeholder("P08", _GENERIC, ("budget_prorate_target",), "Q8"),
    Placeholder("P09", _GENERIC, ("backup_reminder_days",), "Q11"),
    Placeholder("P10", _LOCAL, ("report_handling_notice",), "Q10"),
    Placeholder("A02", _GENERIC, ("ppe_hierarchy_enabled", "ppe_hierarchy"), "Q2"),
    Placeholder("A04", _GENERIC, ("ppe_validity_months",), "Q2"),
    Placeholder("A05", _GENERIC, ("degraded_counts_as_available",), "Q5"),
    # A06, A07, A09 and A10 keep their values in their own tables (maintenance intervals,
    # evaluation metrics, the course list, the degree status), so no config field.
    Placeholder("A06", _GENERIC, (), "Q6"),
    Placeholder("A07", _GENERIC, (), "Q7"),
    Placeholder("A08", _GENERIC, ("default_currency",), "Q8"),
    Placeholder("A09", _GENERIC, (), "Q3"),
    Placeholder("A10", _GENERIC, (), "Q3"),
    Placeholder("A11", _GENERIC, ("small_count_threshold",), "Q10"),
    Placeholder("D18", _LOCAL, ("institution_name", "unit_name"), "Q17"),
)


def flagged_placeholder_ids() -> tuple[str, ...]:
    """Ids whose code-level flag is set, in registry order (release notes, changelog)."""
    return tuple(item.id for item in PLACEHOLDERS if item.placeholder)


def placeholder(placeholder_id: str) -> Placeholder:
    """The registry entry ``placeholder_id``; ``KeyError`` when unknown."""
    for item in PLACEHOLDERS:
        if item.id == placeholder_id:
            return item
    raise KeyError(placeholder_id)


def placeholder_for_field(field_name: str) -> Placeholder | None:
    """The placeholder that governs the config field ``field_name``, or ``None``."""
    for item in PLACEHOLDERS:
        if field_name in item.fields:
            return item
    return None


def local_only_fields() -> frozenset[str]:
    """The config fields that hold local-only values (never a code default)."""
    return frozenset(
        name
        for item in PLACEHOLDERS
        if item.kind is PlaceholderKind.LOCAL_ONLY
        for name in item.fields
    )


def _has_empty_default(spec: dataclasses.Field[object]) -> bool:
    value: object
    if spec.default is not dataclasses.MISSING:
        value = spec.default
    elif callable(spec.default_factory):
        value = spec.default_factory()
    else:
        return False
    return value is None or value == "" or (isinstance(value, Mapping) and not value)


def check_registry() -> None:
    """Raise :class:`ConfigError` (``REGISTRY_INVALID``) when the registry breaks an invariant.

    Called at import time and by the tests: every named field exists on :class:`ReadinessConfig`,
    no id or field is declared twice, every local-only field defaults to empty and keeps its flag,
    and ``operator_label`` belongs to no placeholder.
    """
    specs = {spec.name: spec for spec in dataclasses.fields(ReadinessConfig)}
    seen_ids: set[str] = set()
    seen_fields: set[str] = set()
    for item in PLACEHOLDERS:
        if item.id in seen_ids:
            raise ConfigError("REGISTRY_INVALID", item.id)
        seen_ids.add(item.id)
        if item.kind is PlaceholderKind.LOCAL_ONLY and not item.placeholder:
            raise ConfigError("REGISTRY_INVALID", item.id)
        for name in item.fields:
            if name not in specs or name in seen_fields:
                raise ConfigError("REGISTRY_INVALID", name)
            seen_fields.add(name)
            if item.kind is PlaceholderKind.LOCAL_ONLY and not _has_empty_default(specs[name]):
                raise ConfigError("REGISTRY_INVALID", name)
    if "operator_label" in seen_fields:
        raise ConfigError("REGISTRY_INVALID", "operator_label")


check_registry()


# --------------------------------------------------------------------------- (de)serialisation


def _encode(name: str, value: object) -> object:
    if name == "ppe_hierarchy" and isinstance(value, Mapping):
        return {
            str(level): list(also) if isinstance(also, tuple) else also
            for level, also in sorted(value.items(), key=_by_level)
        }
    if name == "ppe_validity_months" and isinstance(value, Mapping):
        return {str(level): months for level, months in sorted(value.items(), key=_by_level)}
    return value


def _by_level(pair: tuple[object, object]) -> str:
    return str(pair[0])


def to_settings(config: ReadinessConfig) -> dict[str, object]:
    """One ``config.<field>`` key per field, with JSON-compatible values."""
    return {
        SETTING_PREFIX + spec.name: _encode(spec.name, getattr(config, spec.name))
        for spec in dataclasses.fields(ReadinessConfig)
    }


def _read_int(values: Mapping[str, object], name: str, default: int) -> int:
    """The stored int ``config.<name>`` or ``default``; any other type is ``INVALID_TYPE``."""
    key = SETTING_PREFIX + name
    if key not in values:
        return default
    value = values[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("INVALID_TYPE", name)
    return value


def _read_bool(values: Mapping[str, object], name: str, default: bool) -> bool:
    key = SETTING_PREFIX + name
    if key not in values:
        return default
    value = values[key]
    if not isinstance(value, bool):
        raise ConfigError("INVALID_TYPE", name)
    return value


def _read_str(values: Mapping[str, object], name: str, default: str, *, code: str) -> str:
    key = SETTING_PREFIX + name
    if key not in values:
        return default
    value = values[key]
    if not isinstance(value, str):
        raise ConfigError(code, name)
    return value


def _read_hierarchy(
    values: Mapping[str, object], name: str, default: Mapping[str, tuple[str, ...]]
) -> Mapping[str, tuple[str, ...]]:
    key = SETTING_PREFIX + name
    if key not in values:
        return default
    stored = values[key]
    if not isinstance(stored, Mapping):
        raise ConfigError("INVALID_TYPE", name)
    result: dict[str, tuple[str, ...]] = {}
    for level, also in stored.items():
        if not isinstance(level, str) or not isinstance(also, list):
            raise ConfigError("INVALID_TYPE", name)
        members: list[str] = []
        for other in also:
            if not isinstance(other, str):
                raise ConfigError("INVALID_TYPE", name)
            members.append(other)
        result[level] = tuple(members)
    return result


def _read_validity(
    values: Mapping[str, object], name: str, default: Mapping[str, int | None]
) -> Mapping[str, int | None]:
    key = SETTING_PREFIX + name
    if key not in values:
        return default
    stored = values[key]
    if not isinstance(stored, Mapping):
        raise ConfigError("INVALID_TYPE", name)
    result: dict[str, int | None] = {}
    for level, months in stored.items():
        if not isinstance(level, str) or isinstance(months, bool):
            raise ConfigError("INVALID_TYPE", name)
        if months is not None and not isinstance(months, int):
            raise ConfigError("INVALID_TYPE", name)
        result[level] = months
    return result


def from_settings(values: Mapping[str, object]) -> ReadinessConfig:
    """Build and validate a configuration from ``config.<field>`` keys.

    Missing keys take the defaults, unknown keys are ignored; a stored value of the wrong type or
    failing validation raises :class:`ConfigError` (it is never silently replaced).
    """
    d = ReadinessConfig()
    config = ReadinessConfig(
        cert_warning_days=_read_int(values, "cert_warning_days", d.cert_warning_days),
        maintenance_warning_days=_read_int(
            values, "maintenance_warning_days", d.maintenance_warning_days
        ),
        snapshot_monthly=_read_bool(values, "snapshot_monthly", d.snapshot_monthly),
        snapshot_on_report=_read_bool(values, "snapshot_on_report", d.snapshot_on_report),
        min_passphrase_length=_read_int(values, "min_passphrase_length", d.min_passphrase_length),
        daily_backups_kept=_read_int(values, "daily_backups_kept", d.daily_backups_kept),
        budget_prorate_target=_read_bool(values, "budget_prorate_target", d.budget_prorate_target),
        backup_reminder_days=_read_int(values, "backup_reminder_days", d.backup_reminder_days),
        ppe_hierarchy_enabled=_read_bool(values, "ppe_hierarchy_enabled", d.ppe_hierarchy_enabled),
        ppe_hierarchy=_read_hierarchy(values, "ppe_hierarchy", d.ppe_hierarchy),
        ppe_validity_months=_read_validity(values, "ppe_validity_months", d.ppe_validity_months),
        degraded_counts_as_available=_read_bool(
            values, "degraded_counts_as_available", d.degraded_counts_as_available
        ),
        default_currency=_read_str(
            values, "default_currency", d.default_currency, code="INVALID_CURRENCY"
        ),
        small_count_threshold=_read_int(values, "small_count_threshold", d.small_count_threshold),
        institution_name=_read_str(
            values, "institution_name", d.institution_name, code="INVALID_TEXT"
        ),
        unit_name=_read_str(values, "unit_name", d.unit_name, code="INVALID_TEXT"),
        operator_label=_read_str(values, "operator_label", d.operator_label, code="INVALID_TEXT"),
        report_handling_notice=_read_str(
            values, "report_handling_notice", d.report_handling_notice, code="INVALID_TEXT"
        ),
    )
    validate(config)
    return config
