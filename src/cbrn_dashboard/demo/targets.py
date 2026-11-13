# SPDX-License-Identifier: GPL-3.0-or-later
"""Illustrative indicator targets for the demo database (PLAN.md T10.1, P03, D14, D25).

These targets exist ONLY in the demo database, whose banner and watermark mark everything as
fictitious. They are not readiness standards, they are never written to a real database and they
are no placeholder for one: a real database keeps no target until the committee enters one (P03).

Why they are computed. The module generators put random filler next to their fixed cases, so the
exact indicator values depend on the seed. A fixed number could therefore not promise a status.
Instead each target below is worked out from the reading the finished dataset gives on
``ctx.today``, so that the wanted status is true by construction: ``OK``, ``WARNING`` or
``CRITICAL`` for the listed (indicator, dimension) pairs. Every other pair stays without a target
and reads "No target" (D14); "No data" comes from the module data itself (an edition without a
participant count, a budget entry without an allocation). After writing, the readings are
evaluated again and a wrong status raises :class:`~cbrn_dashboard.demo.DemoDataError`, so a change
of a module generator that breaks this cannot go unnoticed.

Targets are written THROUGH :meth:`~cbrn_dashboard.services.indicators.IndicatorService.set_target`
(validated and logged with the operator label ``DEMO``).

The rule for ``BUD_EXEC_RATE`` (P08). The stored target is a YEAR-END ratio, and the service
multiplies it by the elapsed fraction of the fiscal year (``scale``) when it evaluates. So the
stored value is the wanted threshold of the day divided by ``scale``, but it is never stored above
:data:`YEAR_END_TARGET_MAX` (1.0, that is 100 % of the allocation): a year-end target is a share of
the allocation, and early in January the plain quotient would be far above 1 (on 1 January
``scale`` is 1/365) and above what the service accepts (it refuses a ratio target over 10.0,
``MAX_RATIO_TARGET``). The target is therefore valid on every day of the
year. The price is that a ratio can only read WARNING or CRITICAL while the group's executed share
is at or below ``scale``: with the stored value at its 1.0 ceiling the threshold of the day is
``scale`` itself. Where the executed share is above it (for the DIRSA group, executed 4 to 12 %,
from 1 January until about the middle of February) the wish for WARNING or CRITICAL cannot be met
and the group reads OK; :func:`reachable_status` says so and the check after writing expects it.

Qt-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cbrn_dashboard.demo.stack import build_services
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorReading,
    IndicatorStatus,
    UnitKind,
)

if TYPE_CHECKING:
    from cbrn_dashboard.demo import DemoContext, DemoDataError

__all__ = [
    "DEMO_TARGET_STATUS",
    "TARGET_PLAN",
    "YEAR_END_TARGET_MAX",
    "TargetWish",
    "generate",
    "reachable_status",
]

#: Error code raised when a reading cannot get the status the plan below wants for it.
DEMO_TARGET_STATUS = "DEMO_TARGET_STATUS"

#: The highest year-end ratio target the demo stores (100 % of the allocation).
YEAR_END_TARGET_MAX = 1.0

_OK = IndicatorStatus.OK
_WARNING = IndicatorStatus.WARNING
_CRITICAL = IndicatorStatus.CRITICAL

#: Rounding of the stored year-end ratio targets (the margins used are 10 percent or more).
_RATIO_DIGITS = 6


@dataclass(frozen=True)
class TargetWish:
    """The status the demo wants for one (indicator code, dimension)."""

    code: str
    dimension: str
    status: IndicatorStatus


#: The illustrative targets, in the order they are written. Dimensions are the encoded text of
#: PLAN.md 5.4. Everything not listed has no target.
TARGET_PLAN: tuple[TargetWish, ...] = (
    TargetWish("PERS_CERT_VALID", "level=A", _OK),
    TargetWish("PERS_CERT_VALID", "level=B", _WARNING),
    TargetWish("PERS_CERT_VALID", "level=C", _CRITICAL),
    TargetWish("PERS_CERT_EXPIRING", "level=A", _WARNING),
    TargetWish("PERS_RETRAINING_NEEDED", "level=B", _OK),
    TargetWish("PERS_TRAINING_12M", "", _OK),
    TargetWish("INFRA_AVAILABLE", "type=bed", _OK),
    TargetWish("INFRA_AVAILABLE", "type=decon_tent", _WARNING),
    TargetWish("INFRA_MAINT_OVERDUE", "type=bed", _CRITICAL),
    TargetWish("INFRA_MAINT_OVERDUE", "type=decon_tent", _OK),
    TargetWish("EX_LAST_PARTICIPANTS", "kind=CBRAMED", _OK),
    TargetWish("EX_LAST_PARTICIPANTS", "kind=OTHER", _WARNING),
    TargetWish("EX_DAYS_SINCE_LAST", "kind=CBRAMED", _OK),
    TargetWish("EX_DAYS_SINCE_LAST", "kind=OTHER", _CRITICAL),
    # The two groups with a low executed share (the budget generator's first band, 4 to 12 %).
    # DIRSA is CRITICAL only while that share is at or below the elapsed fraction of the year.
    TargetWish("BUD_EXEC_RATE", "currency=BRL;source=DIRSA", _CRITICAL),
    TargetWish("BUD_EXEC_RATE", "currency=USD;source=COMAER", _OK),
)


def _fail(message: str) -> DemoDataError:
    # Imported here: the package imports this module while it is still being initialised.
    from cbrn_dashboard.demo import DemoDataError

    return DemoDataError(DEMO_TARGET_STATUS, message)


def _count_thresholds(
    direction: Direction, status: IndicatorStatus, value: float
) -> tuple[float, float]:
    """``(warning, critical)`` that give ``value`` the wanted ``status``; counts step by one."""
    if direction is Direction.HIGHER_IS_BETTER:
        if status is _OK:
            return value - 1.0, max(value - 2.0, 0.0)
        if status is _WARNING:
            return value, max(value - 1.0, 0.0)
        return value + 1.0, value
    if status is _OK:
        return value + 1.0, value + 2.0
    if status is _WARNING:
        return value, value + 1.0
    return max(value - 1.0, 0.0), value


def _ratio_thresholds(status: IndicatorStatus, value: float) -> tuple[float, float]:
    """``(warning, critical)`` for a higher-is-better ratio, with margins of at least 10 percent."""
    if status is _OK:
        return value * 0.9, value * 0.8
    if status is _WARNING:
        return value * 1.1, value * 0.9
    return value * 1.2, value * 1.1


def _year_end(threshold: float, scale: float) -> float:
    """The stored year-end value for the wanted ``threshold`` of the day, at most the ceiling."""
    return min(round(threshold / scale, _RATIO_DIGITS), YEAR_END_TARGET_MAX)


def reachable_status(
    wish: TargetWish, value: float | None, unit: UnitKind, scale: float
) -> IndicatorStatus:
    """The status the plan can give ``wish``: the wished one, or OK for a ratio above ``scale``.

    With the stored year-end value capped at :data:`YEAR_END_TARGET_MAX`, the threshold of the day
    cannot exceed ``scale``; a ratio reading above it is OK whatever the wish (see the module
    docstring).
    """
    if unit is UnitKind.RATIO and wish.status is not _OK and value is not None and value > scale:
        return _OK
    return wish.status


def _thresholds(
    wish: TargetWish, reading: IndicatorReading, direction: Direction, unit: UnitKind, scale: float
) -> tuple[float, float]:
    value = reading.value
    if value is None:
        raise _fail(f"{wish.code} {wish.dimension}: the demo data gives no value")
    if unit is UnitKind.RATIO:
        if direction is not Direction.HIGHER_IS_BETTER or value <= 0.0 or scale <= 0.0:
            raise _fail(f"{wish.code} {wish.dimension}: no ratio target can be derived")
        warning, critical = _ratio_thresholds(wish.status, value)
        return _year_end(warning, scale), _year_end(critical, scale)
    if wish.status is not _OK and value < 1.0:
        raise _fail(f"{wish.code} {wish.dimension}: a value of 0 cannot be made {wish.status}")
    if wish.status is _OK and direction is Direction.HIGHER_IS_BETTER and value < 1.0:
        raise _fail(f"{wish.code} {wish.dimension}: a value of 0 cannot be made OK")
    return _count_thresholds(direction, wish.status, value)


def generate(ctx: DemoContext) -> None:
    """Write the targets of :data:`TARGET_PLAN` and check the resulting statuses."""
    services = build_services(ctx)
    indicators = services.indicators
    readings = {
        (reading.code, reading.dimension): reading for reading in indicators.evaluate(ctx.today)
    }
    scale = services.budget.target_scale(ctx.today)
    expected: dict[tuple[str, str], IndicatorStatus] = {}
    for wish in TARGET_PLAN:
        reading = readings.get((wish.code, wish.dimension))
        if reading is None:
            raise _fail(f"{wish.code} {wish.dimension}: the demo data has no such reading")
        definition = indicators.definition(wish.code)
        warning, critical = _thresholds(wish, reading, definition.direction, definition.unit, scale)
        expected[(wish.code, wish.dimension)] = reachable_status(
            wish, reading.value, definition.unit, scale
        )
        indicators.set_target(
            wish.code, wish.dimension, warning_value=warning, critical_value=critical
        )

    after = {(item.code, item.dimension): item.status for item in indicators.evaluate(ctx.today)}
    for wish in TARGET_PLAN:
        key = (wish.code, wish.dimension)
        if after[key] is not expected[key]:
            raise _fail(f"{wish.code} {wish.dimension}: the status is not {expected[key]}")
