# SPDX-License-Identifier: GPL-3.0-or-later
"""Indicator framework (PLAN T1.6, §5.4, D13, D14, P03).

Pure domain code: no Qt, no I/O, no clock. Everything here is codes and numbers; the domain never
produces translated text (the UI maps the stable codes below to labels).

Status evaluation
-----------------
A target holds a ``warning_value`` and a ``critical_value``. Both thresholds are INCLUSIVE: a
threshold is the *last value of the worse band*. A ``None`` threshold is skipped, so a target with
only a warning or only a critical value is valid.

Order of the checks in :func:`evaluate_status`:

1. value is ``None`` or NaN                          -> ``NO_DATA`` (even without a target)
2. no target, disabled target, or both values ``None`` -> ``NO_TARGET`` (D14, P03)
3. the direction table below

======================  ===============================  ===============================
Direction               CRITICAL                         WARNING (when not critical)
======================  ===============================  ===============================
``HIGHER_IS_BETTER``    ``value <= critical_value``      ``value <= warning_value``
``LOWER_IS_BETTER``     ``value >= critical_value``      ``value >= warning_value``
======================  ===============================  ===============================

Anything else is ``OK``.

Examples (warning, critical):

* higher is better, warning 5, critical 2: 6 -> OK, 5 -> WARNING, 3 -> WARNING, 2 -> CRITICAL,
  0 -> CRITICAL.
* lower is better, warning 1, critical 3: 0 -> OK, 1 -> WARNING, 2 -> WARNING, 3 -> CRITICAL,
  9 -> CRITICAL.

Targets are keyed by exactly ``(code, dimension)``; there is no fallback to another dimension.
A dimension is encoded as sorted ``key=value;key=value`` text built from codes (§5.4), for example
``currency=BRL;source=DIRSA``; an indicator without dimension uses ``""``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")
_DIMENSION_FORBIDDEN = ("=", ";")


# --------------------------------------------------------------------------------------------
# Errors (stable codes, no translated text)
# --------------------------------------------------------------------------------------------


class InvalidIndicatorError(ValueError):
    """An indicator definition is malformed (bad code or dimension keys)."""

    code = "INVALID_INDICATOR"


class InvalidDimensionError(ValueError):
    """A dimension part or encoded dimension text is malformed."""

    code = "INVALID_DIMENSION"


class TargetOrderError(ValueError):
    """Warning and critical values are in the wrong order for the indicator direction."""

    code = "TARGET_ORDER"


class TargetNotFiniteError(TargetOrderError):
    """A target value is NaN or infinite."""

    code = "TARGET_NOT_FINITE"


class DuplicateIndicatorError(ValueError):
    """An indicator code is registered twice."""

    code = "DUPLICATE_INDICATOR"


class UnknownIndicatorError(ValueError):
    """An indicator code is not in the registry."""

    code = "UNKNOWN_INDICATOR"


# --------------------------------------------------------------------------------------------
# Enums (stable codes stored in snapshots)
# --------------------------------------------------------------------------------------------


class IndicatorStatus(StrEnum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    NO_TARGET = "NO_TARGET"
    NO_DATA = "NO_DATA"


class Direction(StrEnum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"


class UnitKind(StrEnum):
    COUNT = "COUNT"
    RATIO = "RATIO"
    CURRENCY = "CURRENCY"
    DAYS = "DAYS"


class Module(StrEnum):
    PERSONNEL = "PERSONNEL"
    INFRASTRUCTURE = "INFRASTRUCTURE"
    EXERCISES = "EXERCISES"
    BUDGET = "BUDGET"


# --------------------------------------------------------------------------------------------
# Dimension encoding
# --------------------------------------------------------------------------------------------


def _check_dimension_token(token: object, what: str) -> str:
    if not isinstance(token, str) or not token or any(c in token for c in _DIMENSION_FORBIDDEN):
        msg = f"invalid dimension {what}: {token!r}"
        raise InvalidDimensionError(msg)
    return token


def encode_dimension(parts: Mapping[str, str]) -> str:
    """Encode dimension parts as sorted ``key=value;key=value`` text (``""`` when empty)."""
    items: list[tuple[str, str]] = []
    for key, value in parts.items():
        items.append((_check_dimension_token(key, "key"), _check_dimension_token(value, "value")))
    items.sort()
    return ";".join(f"{key}={value}" for key, value in items)


def decode_dimension(text: str) -> dict[str, str]:
    """Exact inverse of :func:`encode_dimension`; rejects malformed text."""
    if not isinstance(text, str):
        msg = f"dimension text must be a string: {text!r}"
        raise InvalidDimensionError(msg)
    if text == "":
        return {}
    result: dict[str, str] = {}
    for part in text.split(";"):
        pieces = part.split("=")
        if len(pieces) != 2:
            msg = f"invalid dimension part: {part!r}"
            raise InvalidDimensionError(msg)
        key = _check_dimension_token(pieces[0], "key")
        value = _check_dimension_token(pieces[1], "value")
        if key in result:
            msg = f"duplicate dimension key: {key!r}"
            raise InvalidDimensionError(msg)
        result[key] = value
    return result


# --------------------------------------------------------------------------------------------
# Definition
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class IndicatorDefinition:
    """What an indicator is: stable code, owning module, unit, direction and dimension names."""

    code: str
    module: Module
    unit: UnitKind
    direction: Direction
    dimension_keys: tuple[str, ...] = ()
    source: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or _CODE_PATTERN.fullmatch(self.code) is None:
            msg = f"invalid indicator code: {self.code!r}"
            raise InvalidIndicatorError(msg)
        try:
            keys = tuple(_check_dimension_token(key, "key") for key in self.dimension_keys)
        except InvalidDimensionError as exc:
            msg = f"invalid dimension keys for {self.code}: {self.dimension_keys!r}"
            raise InvalidIndicatorError(msg) from exc
        if len(set(keys)) != len(keys):
            msg = f"duplicate dimension keys for {self.code}: {self.dimension_keys!r}"
            raise InvalidIndicatorError(msg)
        object.__setattr__(self, "dimension_keys", tuple(sorted(keys)))

    def validate_dimension(self, dimension: str) -> None:
        """Raise :class:`InvalidDimensionError` unless the decoded keys equal ``dimension_keys``."""
        keys = tuple(sorted(decode_dimension(dimension)))
        if keys != self.dimension_keys:
            msg = f"dimension {dimension!r} does not match keys {self.dimension_keys!r}"
            raise InvalidDimensionError(msg)


# --------------------------------------------------------------------------------------------
# Targets and status
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """Configured thresholds; ``None`` means that threshold is not set."""

    warning_value: float | None
    critical_value: float | None
    enabled: bool = True

    def scaled(self, factor: float) -> Target:
        """Return a copy with both values multiplied by ``factor`` (budget pro-rating, P08)."""
        return Target(
            warning_value=None if self.warning_value is None else self.warning_value * factor,
            critical_value=None if self.critical_value is None else self.critical_value * factor,
            enabled=self.enabled,
        )


TargetKey = tuple[str, str]
"""``(indicator code, encoded dimension)``."""


def validate_target_order(target: Target, direction: Direction) -> None:
    """Raise when a target is not finite or its two values are in the wrong order.

    Higher-is-better requires ``critical_value <= warning_value``; lower-is-better requires
    ``warning_value <= critical_value``. Equal values are allowed.
    """
    for value in (target.warning_value, target.critical_value):
        if value is not None and not math.isfinite(value):
            msg = f"target value is not finite: {value!r}"
            raise TargetNotFiniteError(msg)
    warning = target.warning_value
    critical = target.critical_value
    if warning is None or critical is None:
        return
    if direction is Direction.HIGHER_IS_BETTER:
        ordered = critical <= warning
    else:
        ordered = warning <= critical
    if not ordered:
        msg = f"warning {warning!r} / critical {critical!r} out of order for {direction.value}"
        raise TargetOrderError(msg)


def _has_value(value: float | None) -> bool:
    return value is not None and not math.isnan(value)


def _active_thresholds(target: Target | None) -> tuple[float | None, float | None] | None:
    """Thresholds of an enabled target with at least one value, else ``None``."""
    if target is None or not target.enabled:
        return None
    if target.warning_value is None and target.critical_value is None:
        return None
    return target.warning_value, target.critical_value


def evaluate_status(
    value: float | None, target: Target | None, direction: Direction
) -> IndicatorStatus:
    """Status of ``value`` against ``target``; boundaries are inclusive (see module docstring)."""
    if value is None or math.isnan(value):
        return IndicatorStatus.NO_DATA
    thresholds = _active_thresholds(target)
    if thresholds is None:
        return IndicatorStatus.NO_TARGET
    warning, critical = thresholds
    if direction is Direction.HIGHER_IS_BETTER:
        if critical is not None and value <= critical:
            return IndicatorStatus.CRITICAL
        if warning is not None and value <= warning:
            return IndicatorStatus.WARNING
        return IndicatorStatus.OK
    if critical is not None and value >= critical:
        return IndicatorStatus.CRITICAL
    if warning is not None and value >= warning:
        return IndicatorStatus.WARNING
    return IndicatorStatus.OK


# --------------------------------------------------------------------------------------------
# Values and readings
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class IndicatorValue:
    """A computed value for one (code, dimension); ``None`` when it cannot be computed."""

    code: str
    value: float | None
    dimension: str = ""
    context: Mapping[str, float] | None = None


@dataclass(frozen=True)
class IndicatorReading:
    """A value together with its status and the thresholds actually used."""

    code: str
    dimension: str
    value: float | None
    status: IndicatorStatus
    warning_value: float | None
    critical_value: float | None
    context: Mapping[str, float] | None = None


# --------------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------------


class IndicatorRegistry:
    """Indicator definitions by code; iterates in registration order."""

    def __init__(self) -> None:
        self._definitions: dict[str, IndicatorDefinition] = {}

    def register(self, definition: IndicatorDefinition) -> None:
        if definition.code in self._definitions:
            msg = f"indicator already registered: {definition.code}"
            raise DuplicateIndicatorError(msg)
        self._definitions[definition.code] = definition

    def get(self, code: str) -> IndicatorDefinition:
        try:
            return self._definitions[code]
        except KeyError:
            msg = f"unknown indicator: {code!r}"
            raise UnknownIndicatorError(msg) from None

    def codes(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def by_module(self, module: Module) -> tuple[IndicatorDefinition, ...]:
        return tuple(d for d in self._definitions.values() if d.module is module)

    def __contains__(self, code: object) -> bool:
        return code in self._definitions

    def __len__(self) -> int:
        return len(self._definitions)

    def __iter__(self) -> Iterator[IndicatorDefinition]:
        return iter(tuple(self._definitions.values()))


# --------------------------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------------------------


def evaluate(
    definition: IndicatorDefinition,
    value: IndicatorValue,
    targets: Mapping[TargetKey, Target],
    *,
    target_scale: float = 1.0,
) -> IndicatorReading:
    """Evaluate one value; the target is looked up by exactly ``(code, dimension)``."""
    target = targets.get((definition.code, value.dimension))
    if target is not None and target_scale != 1.0:
        target = target.scaled(target_scale)
    thresholds = _active_thresholds(target)
    warning, critical = thresholds if thresholds is not None else (None, None)
    return IndicatorReading(
        code=definition.code,
        dimension=value.dimension,
        value=value.value,
        status=evaluate_status(value.value, target, definition.direction),
        warning_value=warning,
        critical_value=critical,
        context=value.context,
    )


def evaluate_all(
    registry: IndicatorRegistry,
    values: Iterable[IndicatorValue],
    targets: Mapping[TargetKey, Target],
) -> list[IndicatorReading]:
    """Evaluate every value, ordered by registry order and then by dimension (stable)."""
    order = {code: index for index, code in enumerate(registry.codes())}
    pending = list(values)
    for item in pending:
        if item.code not in order:
            msg = f"unknown indicator: {item.code!r}"
            raise UnknownIndicatorError(msg)
    pending.sort(key=lambda item: (order[item.code], item.dimension))
    return [evaluate(registry.get(item.code), item, targets) for item in pending]
