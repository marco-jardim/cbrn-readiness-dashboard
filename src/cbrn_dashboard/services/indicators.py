# SPDX-License-Identifier: GPL-3.0-or-later
"""Indicator service: evaluation of every indicator and the stored targets (PLAN.md T6.1).

Qt-free. The rules about *values* (status, direction, thresholds, pro-rating) live in
``domain/indicators.py`` and ``domain/budget.py`` and are only called from here. The rules about
*input* (is the code registered, does the dimension fit, are the values numbers in the right order)
live here and are reported as :class:`~cbrn_dashboard.services.errors.ServiceError` with a stable
code and the name of the offending field; the UI maps codes to texts.

Evaluation (D13, D14)
---------------------
:meth:`IndicatorService.evaluate` evaluates EVERY registered indicator for an as-of date: it asks
the four module services for their ``indicator_values(as_of)``, loads the stored targets and calls
the domain ``evaluate`` per value, in registry order and then by dimension. Nothing is cached, so a
past date gives that date's readings from the records as known today. A value whose code is not
registered raises :class:`~cbrn_dashboard.domain.indicators.UnknownIndicatorError` (never silently
dropped); a registered indicator for which no module returns a value has simply no reading. With
no stored target the status is ``NO_TARGET`` (P03): the application invents no readiness standard,
and a DISABLED target behaves exactly as if it were absent.

Targets (P03, Settings -> Targets)
----------------------------------
Targets are keyed by exactly ``(indicator code, dimension)``; there is no fallback to another
dimension. The dimension is the encoded ``key=value;key=value`` text of section 5.4 (``""`` for an
indicator without dimension keys). Targets entered for ``BUD_EXEC_RATE`` are YEAR-END targets: the
stored value is never pro-rated, the P08 factor (elapsed fraction of the fiscal year) is applied to
the stored target at evaluation time only, and a reading records the scaled thresholds it used.

Every mutating method

* first refuses a read-only connection (``READ_ONLY``),
* validates and writes inside ONE transaction, so a refusal leaves neither a target row nor a
  ``change_log`` row behind,
* writes only through ``storage/targets_repo.py`` (one ``change_log`` row per real change, with
  ``entity_key = {"dimension": ..., "indicator_code": ...}``). A change that changes nothing
  writes nothing.

No target is ever created by the application itself.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.domain import indicators as rules
from cbrn_dashboard.domain.indicators import (
    IndicatorDefinition,
    IndicatorReading,
    IndicatorRegistry,
    IndicatorValue,
    InvalidDimensionError,
    Target,
    TargetOrderError,
    UnknownIndicatorError,
    decode_dimension,
    validate_target_order,
)
from cbrn_dashboard.domain.registry import build_registry
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.errors import (
    NOT_FOUND,
    READ_ONLY,
    ServiceError,
    require,
    translate_storage_error,
)
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.storage import targets_repo as repo
from cbrn_dashboard.storage.db import DatabaseConnection, ReadOnlyDatabaseError, transaction
from cbrn_dashboard.storage.repository import RowNotFoundError, WriteContext
from cbrn_dashboard.storage.targets_repo import TargetRow

__all__ = [
    "BUDGET_RATE_CODE",
    "INVALID_DIMENSION",
    "INVALID_NUMBER",
    "TARGET_EMPTY",
    "TARGET_NOT_FINITE",
    "TARGET_ORDER",
    "UNKNOWN_INDICATOR",
    "IndicatorService",
    "TargetView",
]

# Error codes of this service (the shared ones are in services/errors.py).
#: The indicator code is not in the registry.
UNKNOWN_INDICATOR = "UNKNOWN_INDICATOR"
#: The dimension text does not decode, or its keys differ from the indicator's dimension keys.
INVALID_DIMENSION = "INVALID_DIMENSION"
#: Warning and critical are in the wrong order for the indicator's direction.
TARGET_ORDER = "TARGET_ORDER"
#: A threshold is NaN or infinite.
TARGET_NOT_FINITE = "TARGET_NOT_FINITE"
#: A threshold is not a real number (``bool``, text, ...).
INVALID_NUMBER = "INVALID_NUMBER"
#: Both thresholds are ``None``: delete the target instead.
TARGET_EMPTY = "TARGET_EMPTY"

#: The one indicator whose target is pro-rated over the fiscal year at evaluation (P08).
BUDGET_RATE_CODE = "BUD_EXEC_RATE"


@dataclass(frozen=True)
class TargetView:
    """A stored target: thresholds as entered (year-end for ``BUD_EXEC_RATE``) and its switch."""

    indicator_code: str
    dimension: str
    warning_value: float | None
    critical_value: float | None
    enabled: bool


def _view(row: TargetRow) -> TargetView:
    return TargetView(
        indicator_code=row.indicator_code,
        dimension=row.dimension,
        warning_value=row.warning_value,
        critical_value=row.critical_value,
        enabled=row.enabled,
    )


def _number(value: object, field: str) -> float | None:
    """A threshold as a ``float``; ``None`` (not set) is allowed, ``bool`` and text are not."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ServiceError(INVALID_NUMBER, field)
    try:
        number = float(value)
    except OverflowError:
        raise ServiceError(INVALID_NUMBER, field) from None
    require(math.isfinite(number), TARGET_NOT_FINITE, field)
    return number


@contextmanager
def _translated() -> Iterator[None]:
    """Turn the storage errors with a service meaning into service errors; re-raise the rest."""
    try:
        yield
    except (ReadOnlyDatabaseError, RowNotFoundError) as exc:
        raise translate_storage_error(exc) from exc


class IndicatorService:
    """Evaluate every indicator for an as-of date and manage the stored targets."""

    def __init__(
        self,
        conn: DatabaseConnection,
        clock: Clock,
        operator: Callable[[], str] = lambda: "",
        *,
        personnel: PersonnelService,
        infrastructure: InfrastructureService,
        exercises: ExercisesService,
        budget: BudgetService,
        registry: IndicatorRegistry | None = None,
    ) -> None:
        self._conn = conn
        self._clock = clock
        self._operator = operator
        self._personnel = personnel
        self._infrastructure = infrastructure
        self._exercises = exercises
        self._budget = budget
        self._registry = build_registry() if registry is None else registry

    # ----- plumbing

    def _ctx(self) -> WriteContext:
        return WriteContext(self._conn, self._clock, self._operator())

    def _require_writable(self) -> None:
        require(not self._conn.read_only, READ_ONLY)

    def _known(self, code: str) -> IndicatorDefinition:
        """The definition of a registered code; ``UNKNOWN_INDICATOR`` otherwise."""
        if not isinstance(code, str) or code not in self._registry:
            raise ServiceError(UNKNOWN_INDICATOR, "indicator_code")
        return self._registry.get(code)

    # ----- definitions

    def definitions(self) -> list[IndicatorDefinition]:
        """Every registered indicator, in registry order."""
        return list(self._registry)

    def definition(self, code: str) -> IndicatorDefinition:
        """The definition of ``code``; ``UNKNOWN_INDICATOR`` when it is not registered."""
        return self._known(code)

    # ----- evaluation

    def _values(self, as_of: date) -> list[IndicatorValue]:
        values: list[IndicatorValue] = []
        values.extend(self._personnel.indicator_values(as_of))
        values.extend(self._infrastructure.indicator_values(as_of))
        values.extend(self._exercises.indicator_values(as_of))
        values.extend(self._budget.indicator_values(as_of))
        return values

    def _ordered_values(self, as_of: date) -> list[IndicatorValue]:
        """All module values, in registry order then by dimension; unknown codes raise."""
        order = {code: index for index, code in enumerate(self._registry.codes())}
        values = self._values(as_of)
        for item in values:
            if item.code not in order:
                msg = f"unknown indicator: {item.code!r}"
                raise UnknownIndicatorError(msg)
        values.sort(key=lambda item: (order[item.code], item.dimension))
        return values

    def evaluate(self, as_of: date) -> list[IndicatorReading]:
        """The reading of every (code, dimension) the modules produce for ``as_of``.

        Ordered by registry order, then by dimension. A reading records the thresholds actually
        used: for ``BUD_EXEC_RATE`` the stored YEAR-END target multiplied by the elapsed fraction
        of the fiscal year (P08; 1.0 when the switch is off), for every other indicator the stored
        values unchanged.
        """
        values = self._ordered_values(as_of)
        targets = repo.load_targets(self._conn)
        budget_scale: float | None = None
        readings: list[IndicatorReading] = []
        for item in values:
            scale = 1.0
            if item.code == BUDGET_RATE_CODE:
                if budget_scale is None:
                    budget_scale = self._budget.target_scale(as_of)
                scale = budget_scale
            definition = self._registry.get(item.code)
            readings.append(rules.evaluate(definition, item, targets, target_scale=scale))
        return readings

    def readings_by_code(self, as_of: date) -> dict[str, list[IndicatorReading]]:
        """:meth:`evaluate` grouped by indicator code (registry order; codes without reading
        are absent)."""
        grouped: dict[str, list[IndicatorReading]] = {}
        for reading in self.evaluate(as_of):
            grouped.setdefault(reading.code, []).append(reading)
        return grouped

    def known_dimensions(self, as_of: date) -> dict[str, list[str]]:
        """For every registered code, the dimensions that currently have a value (sorted).

        The Settings page offers these when a target is entered. A code without any value maps to
        an empty list; ``""`` is the dimension of an indicator without dimension keys.
        """
        result: dict[str, list[str]] = {code: [] for code in self._registry.codes()}
        for item in self._ordered_values(as_of):
            dimensions = result[item.code]
            if item.dimension not in dimensions:
                dimensions.append(item.dimension)
        return result

    # ----- targets: reads

    def list_targets(self) -> list[TargetView]:
        """Every stored target (disabled ones included): registry order, then dimension.

        Targets of a code that is no longer registered come last, by code. Thresholds are shown as
        entered: the ``BUD_EXEC_RATE`` ones are year-end values.
        """
        order = {code: index for index, code in enumerate(self._registry.codes())}
        rows = repo.list_targets(self._conn)
        rows.sort(
            key=lambda r: (order.get(r.indicator_code, len(order)), r.indicator_code, r.dimension)
        )
        return [_view(row) for row in rows]

    def get_target(self, code: str, dimension: str) -> TargetView:
        """The stored target of exactly ``(code, dimension)``; ``NOT_FOUND`` when there is none."""
        row = repo.get_target(self._conn, code, dimension)
        if row is None:
            raise ServiceError(NOT_FOUND)
        return _view(row)

    # ----- targets: writes

    def _check_dimension(self, definition: IndicatorDefinition, dimension: str) -> str:
        if not isinstance(dimension, str):
            raise ServiceError(INVALID_DIMENSION, "dimension")
        try:
            definition.validate_dimension(dimension)
            # Only the canonical text (sorted keys, no stray characters) is a stored key.
            decoded = decode_dimension(dimension)
        except InvalidDimensionError:
            raise ServiceError(INVALID_DIMENSION, "dimension") from None
        canonical = ";".join(f"{key}={decoded[key]}" for key in sorted(decoded))
        require(canonical == dimension, INVALID_DIMENSION, "dimension")
        return dimension

    def set_target(
        self,
        code: str,
        dimension: str,
        *,
        warning_value: float | None,
        critical_value: float | None,
        enabled: bool = True,
    ) -> bool:
        """Create or change the target of ``(code, dimension)``; return whether anything changed.

        For ``BUD_EXEC_RATE`` the values are YEAR-END targets (a ratio, for example 0.9): they are
        stored as entered and pro-rated only when evaluated (P08).

        Refusals (nothing is written): ``UNKNOWN_INDICATOR``, ``INVALID_DIMENSION``,
        ``INVALID_NUMBER``, ``TARGET_NOT_FINITE``, ``TARGET_EMPTY`` (both values ``None``: delete
        the target instead) and ``TARGET_ORDER`` (higher is better needs critical <= warning,
        lower is better needs warning <= critical).
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            definition = self._known(code)
            checked = self._check_dimension(definition, dimension)
            warning = _number(warning_value, "warning_value")
            critical = _number(critical_value, "critical_value")
            require(warning is not None or critical is not None, TARGET_EMPTY)
            try:
                validate_target_order(Target(warning, critical, enabled), definition.direction)
            except TargetOrderError as exc:
                raise ServiceError(exc.code) from None
            return repo.upsert_target(
                self._ctx(), definition.code, checked, warning, critical, bool(enabled)
            )

    def set_target_enabled(self, code: str, dimension: str, enabled: bool) -> bool:
        """Switch a stored target on or off; return whether anything changed.

        ``NOT_FOUND`` when there is no such target. A disabled target is kept but behaves as if it
        were absent.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            current = repo.get_target(self._conn, code, dimension)
            if current is None:
                raise ServiceError(NOT_FOUND)
            return repo.upsert_target(
                self._ctx(),
                code,
                dimension,
                current.warning_value,
                current.critical_value,
                bool(enabled),
            )

    def delete_target(self, code: str, dimension: str) -> None:
        """Delete a stored target; ``NOT_FOUND`` when there is none.

        A target of a code that is no longer registered can be deleted too.
        """
        self._require_writable()
        with _translated(), transaction(self._conn):
            if not repo.delete_target(self._ctx(), code, dimension):
                raise ServiceError(NOT_FOUND)
