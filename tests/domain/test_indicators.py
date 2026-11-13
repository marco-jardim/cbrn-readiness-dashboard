# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the indicator framework (PLAN T1.6)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import pytest

from cbrn_dashboard.domain import registry as registry_module
from cbrn_dashboard.domain.indicators import (
    Direction,
    DuplicateIndicatorError,
    IndicatorDefinition,
    IndicatorRegistry,
    IndicatorStatus,
    IndicatorValue,
    InvalidDimensionError,
    InvalidIndicatorError,
    Module,
    Target,
    TargetKey,
    TargetNotFiniteError,
    TargetOrderError,
    UnitKind,
    UnknownIndicatorError,
    decode_dimension,
    encode_dimension,
    evaluate,
    evaluate_all,
    evaluate_status,
    validate_target_order,
)
from cbrn_dashboard.domain.registry import build_registry

HIGHER = Direction.HIGHER_IS_BETTER
LOWER = Direction.LOWER_IS_BETTER
OK = IndicatorStatus.OK
WARNING = IndicatorStatus.WARNING
CRITICAL = IndicatorStatus.CRITICAL
NO_TARGET = IndicatorStatus.NO_TARGET
NO_DATA = IndicatorStatus.NO_DATA


def make_definition(
    code: str = "PERS_X",
    *,
    module: Module = Module.PERSONNEL,
    direction: Direction = HIGHER,
    dimension_keys: tuple[str, ...] = (),
) -> IndicatorDefinition:
    return IndicatorDefinition(
        code=code,
        module=module,
        unit=UnitKind.COUNT,
        direction=direction,
        dimension_keys=dimension_keys,
    )


# --------------------------------------------------------------------------------------------
# Definition
# --------------------------------------------------------------------------------------------


def test_definition_carries_its_fields() -> None:
    definition = IndicatorDefinition(
        code="BUD_EXEC_RATE",
        module=Module.BUDGET,
        unit=UnitKind.RATIO,
        direction=HIGHER,
        dimension_keys=("source", "currency"),
        source="R24",
    )
    assert definition.code == "BUD_EXEC_RATE"
    assert definition.module is Module.BUDGET
    assert definition.unit is UnitKind.RATIO
    assert definition.direction is HIGHER
    assert definition.dimension_keys == ("currency", "source")  # stored sorted
    assert definition.source == "R24"


def test_definition_defaults() -> None:
    definition = make_definition()
    assert definition.dimension_keys == ()
    assert definition.source == ""


@pytest.mark.parametrize(
    "code", ["", "pers_x", "1ABC", "_ABC", "AB-C", "AB C", "ABc", "AB\n", "\u00c9"]
)
def test_definition_rejects_bad_code(code: str) -> None:
    with pytest.raises(InvalidIndicatorError) as info:
        make_definition(code)
    assert info.value.code == "INVALID_INDICATOR"


@pytest.mark.parametrize("code", ["A", "PERS_CERT_VALID", "EX_DAYS_SINCE_LAST", "A1_B2"])
def test_definition_accepts_good_code(code: str) -> None:
    assert make_definition(code).code == code


@pytest.mark.parametrize("keys", [("",), ("a=b",), ("a;b",), ("level", "level")])
def test_definition_rejects_bad_dimension_keys(keys: tuple[str, ...]) -> None:
    with pytest.raises(InvalidIndicatorError):
        make_definition(dimension_keys=keys)


def test_enum_codes_are_stable() -> None:
    assert [s.value for s in IndicatorStatus] == [
        "OK",
        "WARNING",
        "CRITICAL",
        "NO_TARGET",
        "NO_DATA",
    ]
    assert [d.value for d in Direction] == ["HIGHER_IS_BETTER", "LOWER_IS_BETTER"]
    assert [u.value for u in UnitKind] == ["COUNT", "RATIO", "CURRENCY", "DAYS"]
    assert [m.value for m in Module] == ["PERSONNEL", "INFRASTRUCTURE", "EXERCISES", "BUDGET"]


# --------------------------------------------------------------------------------------------
# Dimension encoding
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("parts", "text"),
    [
        ({}, ""),
        ({"level": "A"}, "level=A"),
        ({"source": "DIRSA", "currency": "BRL"}, "currency=BRL;source=DIRSA"),
        ({"status": "completed", "level": "A"}, "level=A;status=completed"),
    ],
)
def test_dimension_round_trip(parts: dict[str, str], text: str) -> None:
    assert encode_dimension(parts) == text
    assert decode_dimension(text) == parts
    assert encode_dimension(decode_dimension(text)) == text


@pytest.mark.parametrize(
    "parts",
    [
        {"": "A"},
        {"level": ""},
        {"le=vel": "A"},
        {"level": "A=B"},
        {"le;vel": "A"},
        {"level": "A;B"},
    ],
)
def test_encode_rejects_bad_parts(parts: dict[str, str]) -> None:
    with pytest.raises(InvalidDimensionError) as info:
        encode_dimension(parts)
    assert info.value.code == "INVALID_DIMENSION"


@pytest.mark.parametrize(
    "text",
    ["level", "=A", "level=", "a=b=c", "a=b;", ";a=b", "a=b;;c=d", "a=b;a=c", " "],
)
def test_decode_rejects_bad_text(text: str) -> None:
    with pytest.raises(InvalidDimensionError) as info:
        decode_dimension(text)
    assert info.value.code == "INVALID_DIMENSION"


@pytest.mark.parametrize(
    "text",
    ["source=DIRSA;currency=BRL", "z=1;a=2", "status=completed;level=A", "b=1;a=1;c=1"],
)
def test_decode_rejects_non_canonical_key_order(text: str) -> None:
    with pytest.raises(InvalidDimensionError) as info:
        decode_dimension(text)
    assert info.value.code == "INVALID_DIMENSION"
    with pytest.raises(InvalidDimensionError):
        make_definition(dimension_keys=("currency", "source")).validate_dimension(text)


@pytest.mark.parametrize(
    ("keys", "dimension", "valid"),
    [
        (("level",), "level=A", True),
        (("level",), "", False),
        (("level",), "type=A", False),
        (("level",), "level=A;status=x", False),
        (("currency", "source"), "currency=BRL;source=DIRSA", True),
        (("currency", "source"), "source=DIRSA;currency=BRL", False),  # not the canonical order
        (("currency", "source"), "currency=BRL", False),
        ((), "", True),
        ((), "level=A", False),
    ],
)
def test_validate_dimension(keys: tuple[str, ...], dimension: str, valid: bool) -> None:
    definition = make_definition(dimension_keys=keys)
    if valid:
        definition.validate_dimension(dimension)
    else:
        with pytest.raises(InvalidDimensionError):
            definition.validate_dimension(dimension)


def test_validate_dimension_rejects_malformed_text() -> None:
    with pytest.raises(InvalidDimensionError):
        make_definition(dimension_keys=("level",)).validate_dimension("level")


# --------------------------------------------------------------------------------------------
# Status evaluation: inclusive boundaries
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (100, OK),
        (6, OK),
        (5.5, OK),
        (5, WARNING),  # warning threshold is the last value of the warning band
        (4, WARNING),
        (3, WARNING),
        (2.5, WARNING),
        (2, CRITICAL),  # critical threshold is the last value of the critical band
        (1, CRITICAL),
        (0, CRITICAL),
        (-3, CRITICAL),
    ],
)
def test_higher_is_better_boundaries(value: float, expected: IndicatorStatus) -> None:
    assert evaluate_status(value, Target(warning_value=5, critical_value=2), HIGHER) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-1, OK),
        (0, OK),
        (0.5, OK),
        (1, WARNING),
        (2, WARNING),
        (2.5, WARNING),
        (3, CRITICAL),
        (4, CRITICAL),
        (9, CRITICAL),
    ],
)
def test_lower_is_better_boundaries(value: float, expected: IndicatorStatus) -> None:
    assert evaluate_status(value, Target(warning_value=1, critical_value=3), LOWER) is expected


@pytest.mark.parametrize(
    ("direction", "value", "expected"),
    [
        (HIGHER, 10, OK),
        (HIGHER, 5.1, OK),
        (HIGHER, 5, WARNING),
        (HIGHER, 0, WARNING),
        (LOWER, 0, OK),
        (LOWER, 4.9, OK),
        (LOWER, 5, WARNING),
        (LOWER, 50, WARNING),
    ],
)
def test_only_warning_target(direction: Direction, value: float, expected: IndicatorStatus) -> None:
    assert evaluate_status(value, Target(warning_value=5, critical_value=None), direction) is (
        expected
    )


@pytest.mark.parametrize(
    ("direction", "value", "expected"),
    [
        (HIGHER, 10, OK),
        (HIGHER, 2.1, OK),
        (HIGHER, 2, CRITICAL),
        (HIGHER, 0, CRITICAL),
        (LOWER, 0, OK),
        (LOWER, 1.9, OK),
        (LOWER, 2, CRITICAL),
        (LOWER, 50, CRITICAL),
    ],
)
def test_only_critical_target(
    direction: Direction, value: float, expected: IndicatorStatus
) -> None:
    assert evaluate_status(value, Target(warning_value=None, critical_value=2), direction) is (
        expected
    )


@pytest.mark.parametrize("direction", [HIGHER, LOWER])
def test_equal_thresholds_are_critical_at_the_threshold(direction: Direction) -> None:
    target = Target(warning_value=3, critical_value=3)
    assert evaluate_status(3, target, direction) is CRITICAL


# --------------------------------------------------------------------------------------------
# No target / no data
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("direction", [HIGHER, LOWER])
@pytest.mark.parametrize(
    "target",
    [
        None,
        Target(warning_value=None, critical_value=None),
        Target(warning_value=5, critical_value=2, enabled=False),
        Target(warning_value=None, critical_value=None, enabled=False),
    ],
)
def test_no_target(target: Target | None, direction: Direction) -> None:
    assert evaluate_status(3, target, direction) is NO_TARGET


@pytest.mark.parametrize("direction", [HIGHER, LOWER])
@pytest.mark.parametrize("value", [None, math.nan])
@pytest.mark.parametrize(
    "target",
    [
        None,
        Target(warning_value=None, critical_value=None),
        Target(warning_value=5, critical_value=2),
        Target(warning_value=5, critical_value=2, enabled=False),
    ],
)
def test_no_data_wins_over_target(
    value: float | None, target: Target | None, direction: Direction
) -> None:
    assert evaluate_status(value, target, direction) is NO_DATA


# --------------------------------------------------------------------------------------------
# Target: scaling and order validation
# --------------------------------------------------------------------------------------------


def test_scaled_multiplies_both_values_and_keeps_enabled() -> None:
    scaled = Target(warning_value=0.8, critical_value=0.5, enabled=False).scaled(0.5)
    assert scaled == Target(warning_value=0.4, critical_value=0.25, enabled=False)


def test_scaled_keeps_none() -> None:
    assert Target(warning_value=None, critical_value=4).scaled(0.5) == Target(None, 2.0)
    assert Target(warning_value=4, critical_value=None).scaled(0.5) == Target(2.0, None)


def test_scaled_returns_a_new_target_with_exactly_the_scaled_values() -> None:
    original = Target(warning_value=10, critical_value=4, enabled=False)
    scaled = original.scaled(2.5)
    assert scaled is not original
    assert (scaled.warning_value, scaled.critical_value) == (25.0, 10.0)
    assert scaled.enabled is False  # preserved
    assert scaled.scaled(0.4) == Target(warning_value=10.0, critical_value=4.0, enabled=False)
    assert original.scaled(1.0) is not original  # even the identity factor gives a new object
    assert (original.warning_value, original.critical_value) == (10, 4)  # the original is intact


@pytest.mark.parametrize(
    ("direction", "warning", "critical"),
    [
        (HIGHER, 5, 2),
        (HIGHER, 3, 3),
        (HIGHER, None, 2),
        (HIGHER, 5, None),
        (HIGHER, None, None),
        (LOWER, 1, 3),
        (LOWER, 3, 3),
        (LOWER, None, 3),
        (LOWER, 1, None),
        (LOWER, None, None),
    ],
)
def test_valid_target_order(
    direction: Direction, warning: float | None, critical: float | None
) -> None:
    validate_target_order(Target(warning, critical), direction)


@pytest.mark.parametrize(
    ("direction", "warning", "critical"),
    [
        (HIGHER, 2, 5),
        (HIGHER, 2.0, 2.1),
        (LOWER, 3, 1),
        (LOWER, 3.1, 3.0),
    ],
)
def test_wrong_target_order(direction: Direction, warning: float, critical: float) -> None:
    with pytest.raises(TargetOrderError) as info:
        validate_target_order(Target(warning, critical), direction)
    assert info.value.code == "TARGET_ORDER"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("direction", [HIGHER, LOWER])
def test_target_not_finite(bad: float, direction: Direction) -> None:
    for target in (Target(bad, None), Target(None, bad), Target(bad, bad)):
        with pytest.raises(TargetNotFiniteError) as info:
            validate_target_order(target, direction)
        assert info.value.code == "TARGET_NOT_FINITE"


# --------------------------------------------------------------------------------------------
# evaluate: targets keyed by (code, dimension)
# --------------------------------------------------------------------------------------------


def test_target_applies_only_to_its_exact_dimension() -> None:
    definition = make_definition("PERS_CERT_VALID", dimension_keys=("level",))
    targets: dict[TargetKey, Target] = {
        ("PERS_CERT_VALID", "level=A"): Target(warning_value=5, critical_value=2)
    }

    a = evaluate(definition, IndicatorValue("PERS_CERT_VALID", 1, "level=A"), targets)
    b = evaluate(definition, IndicatorValue("PERS_CERT_VALID", 1, "level=B"), targets)
    none = evaluate(definition, IndicatorValue("PERS_CERT_VALID", 1), targets)

    assert a.status is CRITICAL
    assert (a.warning_value, a.critical_value) == (5, 2)
    for other in (b, none):
        assert other.status is NO_TARGET
        assert (other.warning_value, other.critical_value) == (None, None)


def test_target_for_empty_dimension_does_not_apply_to_a_dimension() -> None:
    definition = make_definition("PERS_CERT_VALID", dimension_keys=("level",))
    targets = {("PERS_CERT_VALID", ""): Target(warning_value=5, critical_value=2)}
    reading = evaluate(definition, IndicatorValue("PERS_CERT_VALID", 1, "level=A"), targets)
    assert reading.status is NO_TARGET


def test_target_for_another_code_does_not_apply() -> None:
    definition = make_definition("PERS_A")
    targets = {("PERS_B", ""): Target(warning_value=5, critical_value=2)}
    assert evaluate(definition, IndicatorValue("PERS_A", 1), targets).status is NO_TARGET


def test_evaluate_uses_definition_direction() -> None:
    targets = {("LOW", ""): Target(warning_value=1, critical_value=3)}
    definition = make_definition("LOW", direction=LOWER)
    assert evaluate(definition, IndicatorValue("LOW", 3), targets).status is CRITICAL
    assert evaluate(definition, IndicatorValue("LOW", 0), targets).status is OK


def test_evaluate_reading_copies_value_and_context() -> None:
    definition = make_definition("INFRA_AVAILABLE")
    value = IndicatorValue("INFRA_AVAILABLE", 3.0, "type=X", context={"in_service": 5.0})
    reading = evaluate(definition, value, {})
    assert reading.code == "INFRA_AVAILABLE"
    assert reading.dimension == "type=X"
    assert reading.value == 3.0
    assert reading.status is NO_TARGET
    assert reading.context == {"in_service": 5.0}


def test_evaluate_disabled_target_records_no_thresholds() -> None:
    definition = make_definition("X")
    targets = {("X", ""): Target(warning_value=5, critical_value=2, enabled=False)}
    reading = evaluate(definition, IndicatorValue("X", 1), targets)
    assert reading.status is NO_TARGET
    assert (reading.warning_value, reading.critical_value) == (None, None)


def test_evaluate_no_data_still_records_enabled_thresholds() -> None:
    definition = make_definition("X")
    targets = {("X", ""): Target(warning_value=5, critical_value=2)}
    reading = evaluate(definition, IndicatorValue("X", None), targets)
    assert reading.status is NO_DATA
    assert reading.value is None
    assert (reading.warning_value, reading.critical_value) == (5, 2)


def test_evaluate_applies_target_scale_and_records_scaled_thresholds() -> None:
    definition = make_definition("BUD_EXEC_RATE", direction=HIGHER)
    targets = {("BUD_EXEC_RATE", ""): Target(warning_value=0.8, critical_value=0.4)}
    # Unscaled, 0.3 is critical; scaled by 0.5 the thresholds are 0.4 / 0.2 -> warning.
    unscaled = evaluate(definition, IndicatorValue("BUD_EXEC_RATE", 0.3), targets)
    scaled = evaluate(definition, IndicatorValue("BUD_EXEC_RATE", 0.3), targets, target_scale=0.5)
    assert unscaled.status is CRITICAL
    assert (unscaled.warning_value, unscaled.critical_value) == (0.8, 0.4)
    assert scaled.status is WARNING
    assert (scaled.warning_value, scaled.critical_value) == (0.4, 0.2)


def test_evaluate_scale_does_not_change_the_stored_target() -> None:
    definition = make_definition("X")
    target = Target(warning_value=10, critical_value=4)
    evaluate(definition, IndicatorValue("X", 1), {("X", ""): target}, target_scale=0.25)
    assert target == Target(warning_value=10, critical_value=4)


# --------------------------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------------------------


def test_registry_rejects_duplicate_code() -> None:
    registry = IndicatorRegistry()
    registry.register(make_definition("PERS_A"))
    with pytest.raises(DuplicateIndicatorError) as info:
        registry.register(make_definition("PERS_A", module=Module.BUDGET))
    assert info.value.code == "DUPLICATE_INDICATOR"
    assert len(registry) == 1
    assert registry.get("PERS_A").module is Module.PERSONNEL


def test_registry_iterates_in_registration_order() -> None:
    registry = IndicatorRegistry()
    order = ["ZED", "ALPHA", "MIDDLE", "BETA"]
    for code in order:
        registry.register(make_definition(code))
    assert [d.code for d in registry] == order
    assert registry.codes() == tuple(order)
    assert [d.code for d in registry] == order  # stable across iterations
    assert len(registry) == 4


def test_registry_lookup_and_membership() -> None:
    registry = IndicatorRegistry()
    definition = make_definition("PERS_A")
    registry.register(definition)
    assert "PERS_A" in registry
    assert "PERS_B" not in registry
    assert registry.get("PERS_A") is definition
    with pytest.raises(UnknownIndicatorError) as info:
        registry.get("PERS_B")
    assert info.value.code == "UNKNOWN_INDICATOR"


def test_registry_by_module_keeps_registration_order() -> None:
    registry = IndicatorRegistry()
    registry.register(make_definition("B2", module=Module.BUDGET))
    registry.register(make_definition("P1", module=Module.PERSONNEL))
    registry.register(make_definition("B1", module=Module.BUDGET))
    assert [d.code for d in registry.by_module(Module.BUDGET)] == ["B2", "B1"]
    assert [d.code for d in registry.by_module(Module.PERSONNEL)] == ["P1"]
    assert registry.by_module(Module.EXERCISES) == ()


def _provider(*codes: str) -> Callable[[], Sequence[IndicatorDefinition]]:
    def provide() -> Sequence[IndicatorDefinition]:
        return [make_definition(code) for code in codes]

    return provide


def test_build_registry_registers_providers_in_order() -> None:
    registry = build_registry([_provider("Z1", "A1"), _provider("M1")])
    assert registry.codes() == ("Z1", "A1", "M1")


def test_build_registry_rejects_duplicate_across_providers() -> None:
    with pytest.raises(DuplicateIndicatorError):
        build_registry([_provider("A1", "B1"), _provider("C1", "A1")])


def test_build_registry_with_no_providers_is_empty() -> None:
    assert len(build_registry([])) == 0


def test_real_providers_build_a_registry_with_unique_codes_in_stable_order() -> None:
    assert isinstance(registry_module.PROVIDERS, tuple)
    first = build_registry()
    second = build_registry()
    codes = first.codes()
    assert len(set(codes)) == len(codes)
    assert [d.code for d in first] == list(codes)
    assert second.codes() == codes
    assert [d.code for d in second] == [d.code for d in first]


# --------------------------------------------------------------------------------------------
# evaluate_all
# --------------------------------------------------------------------------------------------


def _registry_zed_alpha() -> IndicatorRegistry:
    registry = IndicatorRegistry()
    registry.register(make_definition("ZED", dimension_keys=("level",)))
    registry.register(make_definition("ALPHA", direction=LOWER))
    return registry


def test_evaluate_all_orders_by_registry_then_dimension() -> None:
    registry = _registry_zed_alpha()
    values = [
        IndicatorValue("ALPHA", 1.0),
        IndicatorValue("ZED", 1.0, "level=C"),
        IndicatorValue("ZED", 2.0, "level=A"),
        IndicatorValue("ZED", 3.0, "level=B"),
    ]
    readings = evaluate_all(registry, values, {})
    assert [(r.code, r.dimension) for r in readings] == [
        ("ZED", "level=A"),
        ("ZED", "level=B"),
        ("ZED", "level=C"),
        ("ALPHA", ""),
    ]


def test_evaluate_all_applies_targets_and_direction() -> None:
    registry = _registry_zed_alpha()
    targets = {
        ("ZED", "level=A"): Target(warning_value=5, critical_value=2),
        ("ALPHA", ""): Target(warning_value=1, critical_value=3),
    }
    values = [
        IndicatorValue("ALPHA", 3.0),
        IndicatorValue("ZED", 5.0, "level=A"),
        IndicatorValue("ZED", 0.0, "level=B"),
        IndicatorValue("ZED", None, "level=C"),
    ]
    readings = evaluate_all(registry, values, targets)
    assert [r.status for r in readings] == [WARNING, NO_TARGET, NO_DATA, CRITICAL]


def test_evaluate_all_accepts_a_generator_and_is_stable_for_equal_keys() -> None:
    registry = _registry_zed_alpha()
    values = (IndicatorValue("ALPHA", float(n)) for n in (3, 1, 2))
    assert [r.value for r in evaluate_all(registry, values, {})] == [3.0, 1.0, 2.0]


def test_evaluate_all_rejects_unknown_code() -> None:
    registry = _registry_zed_alpha()
    with pytest.raises(UnknownIndicatorError) as info:
        evaluate_all(registry, [IndicatorValue("ALPHA", 1.0), IndicatorValue("NOPE", 1.0)], {})
    assert info.value.code == "UNKNOWN_INDICATOR"


@pytest.mark.parametrize(
    ("code", "dimension"),
    [
        ("ZED", "type=X"),  # wrong key
        ("ZED", ""),  # missing key
        ("ZED", "level=A;type=X"),  # extra key
        ("ALPHA", "level=A"),  # a dimension for an indicator without keys
        ("ZED", "level"),  # malformed
    ],
)
def test_evaluate_all_rejects_a_dimension_that_does_not_match_the_definition(
    code: str, dimension: str
) -> None:
    registry = _registry_zed_alpha()
    values = [IndicatorValue("ALPHA", 1.0), IndicatorValue(code, 1, dimension)]
    with pytest.raises(InvalidDimensionError) as info:
        evaluate_all(registry, values, {})
    assert info.value.code == "INVALID_DIMENSION"


def test_evaluate_all_rejects_a_non_canonical_dimension() -> None:
    registry = IndicatorRegistry()
    registry.register(make_definition("BOTH", dimension_keys=("currency", "source")))
    swapped = [IndicatorValue("BOTH", 1.0, "source=DIRSA;currency=BRL")]
    with pytest.raises(InvalidDimensionError):
        evaluate_all(registry, swapped, {})
    canonical = [IndicatorValue("BOTH", 1.0, "currency=BRL;source=DIRSA")]
    assert [r.dimension for r in evaluate_all(registry, canonical, {})] == [
        "currency=BRL;source=DIRSA"
    ]


def test_evaluate_all_empty() -> None:
    assert evaluate_all(_registry_zed_alpha(), [], {}) == []
