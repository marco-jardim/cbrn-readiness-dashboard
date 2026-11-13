# SPDX-License-Identifier: GPL-3.0-or-later
"""Infrastructure rules and indicators (PLAN T3.2, 5.4, A01, A05, A06, P02, D26).

Pure domain code: no Qt, no I/O, no clock. Every function takes the as-of date ``d`` explicitly, so
a past as-of date gives the reading computed from the records as known now for that date (I03).
Only codes and numbers are produced; the UI maps the codes to labels.

Rules
-----
* An asset is *in service* on ``d`` when ``in_service_from <= d`` and ``in_service_until`` is
  ``None`` or ``d <= in_service_until`` (both ends inclusive). Retired and not-yet-in-service assets
  are excluded from the indicators and the due lists.
* The status on ``d`` is that of the latest status event with ``effective_on <= d`` (an event dated
  ``d`` applies on ``d``). With no such event the status is ``unknown`` (D26): not available, and
  reported by :func:`data_quality`. ``unknown`` is only ever returned, never stored.
* *Available* (A01, A05) means in service and ``operational``, plus ``degraded`` when
  ``InfrastructureRules.degraded_counts_as_available``. It is not "free": no occupancy is tracked.
* Maintenance due date (A06), see :func:`maintenance_schedule`. Only maintenance with
  ``performed_on <= d`` is considered.

  1. the ``next_due_on`` of the latest maintenance that records one (it always wins, even over an
     interval of 0); records without it never reset the schedule;
  2. otherwise an effective interval of 0 means "no scheduled maintenance" (no due date, no
     unknown-schedule flag);
  3. otherwise a positive interval: the latest preventive ``performed_on`` (else
     ``in_service_from``) plus the interval;
  4. otherwise the schedule is unknown.

* Overdue: ``due_on < d``. Due soon (P02): ``d <= due_on <= d + maintenance_warning_days``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorDefinition,
    IndicatorValue,
    Module,
    UnitKind,
    encode_dimension,
)

_DIMENSION_KEY = "type"


# --------------------------------------------------------------------------------------------
# Data objects
# --------------------------------------------------------------------------------------------


class AssetStatus(StrEnum):
    """Status of an asset; ``unknown`` is computed (D26) and never stored."""

    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    OUT_OF_SERVICE = "out_of_service"
    UNKNOWN = "unknown"


class MaintenanceKind(StrEnum):
    PREVENTIVE = "preventive"
    CORRECTIVE = "corrective"
    INSPECTION = "inspection"


class ScheduleBasis(StrEnum):
    """How the due date of :class:`MaintenanceSchedule` was obtained (A06)."""

    RECORDED_NEXT_DUE = "RECORDED_NEXT_DUE"
    PREVENTIVE_PLUS_INTERVAL = "PREVENTIVE_PLUS_INTERVAL"
    IN_SERVICE_PLUS_INTERVAL = "IN_SERVICE_PLUS_INTERVAL"
    NO_SCHEDULED_MAINTENANCE = "NO_SCHEDULED_MAINTENANCE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class InfrastructureRules:
    """Configuration taken by the rules (P02, A05); the service reads it from the settings."""

    maintenance_warning_days: int = 30
    degraded_counts_as_available: bool = False


@dataclass(frozen=True)
class AssetType:
    code: str
    default_maintenance_interval_days: int | None


@dataclass(frozen=True)
class Asset:
    id: int
    tag: str
    type_code: str
    in_service_from: date
    in_service_until: date | None
    maintenance_interval_days: int | None


@dataclass(frozen=True)
class StatusEvent:
    asset_id: int
    effective_on: date
    status: AssetStatus


@dataclass(frozen=True)
class MaintenanceEvent:
    asset_id: int
    performed_on: date
    kind: MaintenanceKind
    next_due_on: date | None


@dataclass(frozen=True)
class MaintenanceSchedule:
    """Result of the due-date rule (A06)."""

    due_on: date | None
    basis: ScheduleBasis
    last_maintenance_on: date | None


@dataclass(frozen=True)
class AssetRow:
    """One asset as shown on the page and in reports; ``days_to_due`` is signed (< 0 = late)."""

    asset_id: int
    tag: str
    type_code: str
    in_service: bool
    status: AssetStatus
    available: bool
    last_maintenance_on: date | None
    due_on: date | None
    basis: ScheduleBasis
    overdue: bool
    due_soon: bool
    schedule_unknown: bool
    days_to_due: int | None


@dataclass(frozen=True)
class MaintenanceDueLists:
    """Rows of in-service assets that are overdue or due soon, each sorted by asset tag (R36)."""

    overdue: tuple[AssetRow, ...]
    due_soon: tuple[AssetRow, ...]


# --------------------------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------------------------

_STATUS_SEVERITY = {
    AssetStatus.OPERATIONAL: 0,
    AssetStatus.DEGRADED: 1,
    AssetStatus.OUT_OF_SERVICE: 2,
    AssetStatus.UNKNOWN: 3,
}


def is_in_service(asset: Asset, d: date) -> bool:
    """Whether ``asset`` is in service on ``d``; both ends are inclusive."""
    if asset.in_service_from > d:
        return False
    return asset.in_service_until is None or d <= asset.in_service_until


def status_on(events: Iterable[StatusEvent], asset_id: int, d: date) -> AssetStatus:
    """Status of the latest event of the asset with ``effective_on <= d``, else ``unknown`` (D26).

    Several events on the same day: the worst status wins (deterministic, independent of order).
    """
    best: StatusEvent | None = None
    for event in events:
        if event.asset_id != asset_id or event.effective_on > d:
            continue
        if best is None or (event.effective_on, _STATUS_SEVERITY[event.status]) > (
            best.effective_on,
            _STATUS_SEVERITY[best.status],
        ):
            best = event
    return AssetStatus.UNKNOWN if best is None else best.status


def is_available(status: AssetStatus, rules: InfrastructureRules) -> bool:
    """Available = operational, plus degraded when the A05 switch is on."""
    if status is AssetStatus.OPERATIONAL:
        return True
    return status is AssetStatus.DEGRADED and rules.degraded_counts_as_available


def effective_interval(asset: Asset, asset_type: AssetType | None) -> int | None:
    """The asset's own interval when set (0 included), else its type's default, else ``None``."""
    if asset.maintenance_interval_days is not None:
        return asset.maintenance_interval_days
    return None if asset_type is None else asset_type.default_maintenance_interval_days


def maintenance_schedule(
    asset: Asset,
    asset_type: AssetType | None,
    maintenance: Iterable[MaintenanceEvent],
    d: date,
) -> MaintenanceSchedule:
    """The due-date rule (A06); maintenance performed after ``d`` is ignored."""
    own = [m for m in maintenance if m.asset_id == asset.id and m.performed_on <= d]
    last_any = max((m.performed_on for m in own), default=None)

    recorded = [m for m in own if m.next_due_on is not None]
    if recorded:
        latest = max(
            recorded,
            key=lambda m: (m.performed_on, m.next_due_on or date.min),
        )
        return MaintenanceSchedule(latest.next_due_on, ScheduleBasis.RECORDED_NEXT_DUE, last_any)

    interval = effective_interval(asset, asset_type)
    if interval == 0:
        return MaintenanceSchedule(None, ScheduleBasis.NO_SCHEDULED_MAINTENANCE, last_any)
    if interval is not None and interval > 0:
        step = timedelta(days=interval)
        preventive = max(
            (m.performed_on for m in own if m.kind is MaintenanceKind.PREVENTIVE),
            default=None,
        )
        if preventive is not None:
            return MaintenanceSchedule(
                preventive + step, ScheduleBasis.PREVENTIVE_PLUS_INTERVAL, last_any
            )
        return MaintenanceSchedule(
            asset.in_service_from + step, ScheduleBasis.IN_SERVICE_PLUS_INTERVAL, last_any
        )
    return MaintenanceSchedule(None, ScheduleBasis.UNKNOWN, last_any)


def is_overdue(schedule: MaintenanceSchedule, d: date) -> bool:
    return schedule.due_on is not None and schedule.due_on < d


def is_due_soon(schedule: MaintenanceSchedule, d: date, rules: InfrastructureRules) -> bool:
    """Due within the warning window, ``d`` and ``d + warning days`` both inclusive (P02)."""
    if schedule.due_on is None:
        return False
    return d <= schedule.due_on <= d + timedelta(days=rules.maintenance_warning_days)


def is_schedule_unknown(schedule: MaintenanceSchedule) -> bool:
    return schedule.basis is ScheduleBasis.UNKNOWN


# --------------------------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------------------------


def asset_rows(
    assets: Iterable[Asset],
    types: Iterable[AssetType],
    status_events: Iterable[StatusEvent],
    maintenance: Iterable[MaintenanceEvent],
    d: date,
    rules: InfrastructureRules,
) -> list[AssetRow]:
    """A row for every asset (the caller filters), sorted by type code and then tag."""
    types_by_code = {t.code: t for t in types}
    events = list(status_events)
    records = list(maintenance)
    rows: list[AssetRow] = []
    for asset in assets:
        status = status_on(events, asset.id, d)
        schedule = maintenance_schedule(asset, types_by_code.get(asset.type_code), records, d)
        rows.append(
            AssetRow(
                asset_id=asset.id,
                tag=asset.tag,
                type_code=asset.type_code,
                in_service=is_in_service(asset, d),
                status=status,
                available=is_available(status, rules),
                last_maintenance_on=schedule.last_maintenance_on,
                due_on=schedule.due_on,
                basis=schedule.basis,
                overdue=is_overdue(schedule, d),
                due_soon=is_due_soon(schedule, d, rules),
                schedule_unknown=is_schedule_unknown(schedule),
                days_to_due=None if schedule.due_on is None else (schedule.due_on - d).days,
            )
        )
    rows.sort(key=lambda row: (row.type_code, row.tag))
    return rows


def maintenance_due_lists(
    assets: Iterable[Asset],
    types: Iterable[AssetType],
    status_events: Iterable[StatusEvent],
    maintenance: Iterable[MaintenanceEvent],
    d: date,
    rules: InfrastructureRules,
) -> MaintenanceDueLists:
    """Overdue and due-soon rows of the assets in service on ``d``, each sorted by tag (R36)."""
    rows = [
        row
        for row in asset_rows(assets, types, status_events, maintenance, d, rules)
        if row.in_service
    ]
    overdue = sorted((r for r in rows if r.overdue), key=lambda r: r.tag)
    due_soon = sorted((r for r in rows if r.due_soon), key=lambda r: r.tag)
    return MaintenanceDueLists(overdue=tuple(overdue), due_soon=tuple(due_soon))


def data_quality(
    assets: Iterable[Asset],
    status_events: Iterable[StatusEvent],
    d: date,
) -> list[str]:
    """Tags of the assets in service on ``d`` whose status is ``unknown`` (D26), sorted."""
    events = list(status_events)
    return sorted(
        asset.tag
        for asset in assets
        if is_in_service(asset, d) and status_on(events, asset.id, d) is AssetStatus.UNKNOWN
    )


# --------------------------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------------------------


def indicator_definitions() -> tuple[IndicatorDefinition, ...]:
    """The infrastructure indicators (PLAN 5.4), both with dimension ``type``."""
    return (
        IndicatorDefinition(
            code="INFRA_AVAILABLE",
            module=Module.INFRASTRUCTURE,
            unit=UnitKind.COUNT,
            direction=Direction.HIGHER_IS_BETTER,
            dimension_keys=(_DIMENSION_KEY,),
            source="R17-R19, A01, A05",
        ),
        IndicatorDefinition(
            code="INFRA_MAINT_OVERDUE",
            module=Module.INFRASTRUCTURE,
            unit=UnitKind.COUNT,
            direction=Direction.LOWER_IS_BETTER,
            dimension_keys=(_DIMENSION_KEY,),
            source="R20, R26",
        ),
    )


def indicator_values(
    assets: Iterable[Asset],
    types: Iterable[AssetType],
    status_events: Iterable[StatusEvent],
    maintenance: Iterable[MaintenanceEvent],
    d: date,
    rules: InfrastructureRules,
) -> list[IndicatorValue]:
    """One value per asset type and indicator, only assets in service on ``d`` counted.

    Order: every ``INFRA_AVAILABLE`` (by type code), then every ``INFRA_MAINT_OVERDUE``. Types
    without assets give ``0.0``. ``INFRA_AVAILABLE`` carries ``context={"in_service": n}``.
    """
    type_list = sorted({t.code: t for t in types}.values(), key=lambda t: t.code)
    rows = [
        row
        for row in asset_rows(assets, type_list, status_events, maintenance, d, rules)
        if row.in_service
    ]
    available: list[IndicatorValue] = []
    overdue: list[IndicatorValue] = []
    for asset_type in type_list:
        mine = [row for row in rows if row.type_code == asset_type.code]
        dimension = encode_dimension({_DIMENSION_KEY: asset_type.code})
        available.append(
            IndicatorValue(
                code="INFRA_AVAILABLE",
                value=float(sum(1 for row in mine if row.available)),
                dimension=dimension,
                context={"in_service": float(len(mine))},
            )
        )
        overdue.append(
            IndicatorValue(
                code="INFRA_MAINT_OVERDUE",
                value=float(sum(1 for row in mine if row.overdue)),
                dimension=dimension,
            )
        )
    return available + overdue
