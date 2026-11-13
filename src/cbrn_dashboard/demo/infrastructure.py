# SPDX-License-Identifier: GPL-3.0-or-later
"""Infrastructure demo generator (PLAN.md T3.5, D25, I07, F05, A06).

Fills the demo database with FICTITIOUS assets: one user-defined asset type and about twenty assets
of every built-in type and of that type, with status history and maintenance records. Every value
comes from the seed (``ctx.rng``) or from the fixed cases below, never from a real room, serial
number, equipment model or record. Every tag, type code, label, description and location starts
with ``DEMO``.

All dates are placed RELATIVE TO ``ctx.today`` (the injected clock's date), so the sample shows
the same situations on the day the demo database is created. They age with the calendar afterwards
(a due date passes), so a later ``--demo`` start offers to create the data again. The data is
written THROUGH
:class:`~cbrn_dashboard.services.infrastructure.InfrastructureService`, so every row is validated
and logged (with the operator label ``DEMO``).

The first nine assets are built explicitly and do not use the random generator: they GUARANTEE
every status on ``today`` (operational, degraded, out of service, with a status history), one asset
whose maintenance is overdue, one due soon, one with an unknown schedule, one with "no scheduled
maintenance", one whose due date is preventive plus interval, one that takes the type default, one
retired asset that still has history and one that is not yet in service; corrective and inspection
records exist as well as preventive ones. The remaining assets are random filler drawn from
``ctx.rng``.

Qt-free.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from cbrn_dashboard.domain.infrastructure import AssetStatus, MaintenanceKind
from cbrn_dashboard.services.infrastructure import (
    AssetInput,
    AssetTypeInput,
    InfrastructureService,
)

if TYPE_CHECKING:
    from cbrn_dashboard.demo import DemoContext

__all__ = ["generate"]

#: Label written to the change log for every change made by the generator.
OPERATOR = "DEMO"

_ASSET_TOTAL = 20
_LOCATION_COUNT = 4
_DEMO_TYPE_CODE = "DEMO-TYPE"
_DEMO_TYPE_INTERVAL = 180
_BUILT_IN_TYPES = ("bed", "bay", "neg_pressure_filtration", "decon_tent")
_FILLER_INTERVALS: tuple[int | None, ...] = (None, None, None, 0, 60, 90, 365)

_OPERATIONAL = AssetStatus.OPERATIONAL
_DEGRADED = AssetStatus.DEGRADED
_OUT_OF_SERVICE = AssetStatus.OUT_OF_SERVICE
_STORABLE = (_OPERATIONAL, _DEGRADED, _OUT_OF_SERVICE)
_PREVENTIVE = MaintenanceKind.PREVENTIVE
_CORRECTIVE = MaintenanceKind.CORRECTIVE
_INSPECTION = MaintenanceKind.INSPECTION


def _on(today: date, offset: int) -> date:
    """The date ``offset`` days from ``today`` (negative: in the past)."""
    return today + timedelta(days=offset)


def _demo(value: str) -> str:
    """``value`` itself, after proving that it starts with ``DEMO``."""
    from cbrn_dashboard.demo import assert_demo_identifier

    assert_demo_identifier(value)
    return value


def _tag(number: int) -> str:
    from cbrn_dashboard.demo import demo_identifier

    return _demo(demo_identifier("A", number))


def _create_demo_type(service: InfrastructureService) -> int:
    """The one user-defined asset type, with a default maintenance interval."""
    return service.create_type(
        AssetTypeInput(
            code=_demo(_DEMO_TYPE_CODE),
            label_pt_br=_demo("DEMO Tipo"),
            label_en_us=_demo("DEMO Type"),
            label_es_es=_demo("DEMO Tipo"),
            default_maintenance_interval_days=_DEMO_TYPE_INTERVAL,
        )
    )


def _type_ids(service: InfrastructureService) -> dict[str, int]:
    return {view.code: view.id for view in service.list_types(include_inactive=True)}


def _asset(
    service: InfrastructureService,
    today: date,
    number: int,
    type_id: int,
    *,
    start: int,
    status: AssetStatus = _OPERATIONAL,
    interval: int | None = None,
    location: int | None = None,
) -> int:
    """Create asset ``DEMO-A<number>`` in service from ``start`` days from today."""
    place = location if location is not None else (number - 1) % _LOCATION_COUNT + 1
    return service.create_asset(
        AssetInput(
            tag=_tag(number),
            type_id=type_id,
            in_service_from=_on(today, start),
            description=_demo(f"DEMO asset {number:03d}"),
            location=_demo(f"DEMO location {place}"),
            maintenance_interval_days=interval,
        ),
        status,
    )


def _status(
    service: InfrastructureService, asset_id: int, today: date, offset: int, status: AssetStatus
) -> None:
    service.change_status(asset_id, _on(today, offset), status)


def _maintenance(
    service: InfrastructureService,
    asset_id: int,
    today: date,
    offset: int,
    kind: MaintenanceKind,
    next_due: int | None = None,
) -> None:
    """Record maintenance ``offset`` days from today; ``next_due`` is also an offset."""
    service.record_maintenance(
        asset_id,
        _on(today, offset),
        kind,
        None if next_due is None else _on(today, next_due),
    )


def _guaranteed(
    service: InfrastructureService, today: date, types: dict[str, int], demo_type: int
) -> None:
    """The fixed cases (assets 1 to 9); they do not draw from the random generator."""
    bed, bay = types["bed"], types["bay"]
    filtration, tent = types["neg_pressure_filtration"], types["decon_tent"]

    # 1: operational, maintenance OVERDUE (recorded next due date 20 days ago).
    asset = _asset(service, today, 1, bed, start=-400)
    _maintenance(service, asset, today, -80, _PREVENTIVE, next_due=-20)
    _maintenance(service, asset, today, -85, _CORRECTIVE)

    # 2: DEGRADED since 15 days ago (operational before); maintenance DUE SOON (in 10 days).
    asset = _asset(service, today, 2, bay, start=-400)
    _status(service, asset, today, -15, _DEGRADED)
    _maintenance(service, asset, today, -50, _PREVENTIVE, next_due=10)

    # 3: OUT OF SERVICE since 10 days ago (operational, then degraded); schedule UNKNOWN: a built-in
    # type has no interval and the corrective and inspection records record no next due date.
    asset = _asset(service, today, 3, filtration, start=-400)
    _status(service, asset, today, -60, _DEGRADED)
    _status(service, asset, today, -10, _OUT_OF_SERVICE)
    _maintenance(service, asset, today, -9, _CORRECTIVE)
    _maintenance(service, asset, today, -100, _INSPECTION)

    # 4: "no scheduled maintenance" (asset interval 0, no recorded next due date).
    asset = _asset(service, today, 4, tent, start=-300, interval=0)
    _maintenance(service, asset, today, -40, _INSPECTION)

    # 5: due date from the latest preventive record plus the asset's own interval.
    asset = _asset(service, today, 5, bed, start=-500, interval=90)
    _maintenance(service, asset, today, -30, _PREVENTIVE)

    # 6: due date from the latest preventive record plus the DEMO type's default interval.
    asset = _asset(service, today, 6, demo_type, start=-400)
    _maintenance(service, asset, today, -100, _PREVENTIVE)

    # 7: due date from the in-service date plus the DEMO type's default interval (no records).
    _asset(service, today, 7, demo_type, start=-90)

    # 8: RETIRED 30 days ago; the history stays (it is out of the indicators and the lists).
    asset = _asset(service, today, 8, bay, start=-900)
    _status(service, asset, today, -200, _DEGRADED)
    _status(service, asset, today, -35, _OUT_OF_SERVICE)
    _maintenance(service, asset, today, -300, _PREVENTIVE, next_due=-250)
    service.retire_asset(asset, _on(today, -30))

    # 9: NOT YET in service (starts in 20 days).
    _asset(service, today, 9, bed, start=20)


def _filler(ctx: DemoContext, service: InfrastructureService, types: list[int], first: int) -> None:
    """Random assets ``first`` to ``_ASSET_TOTAL``; every choice comes from ``ctx.rng``."""
    rng = ctx.rng
    today = ctx.today
    for number in range(first, _ASSET_TOTAL + 1):
        start = -rng.randint(200, 1500)
        asset = _asset(
            service,
            today,
            number,
            rng.choice(types),
            start=start,
            status=rng.choice(_STORABLE),
            interval=rng.choice(_FILLER_INTERVALS),
            location=rng.randint(1, _LOCATION_COUNT),
        )

        taken = {start}
        for _ in range(rng.randint(0, 3)):
            offset = rng.randint(start + 1, -1)
            if offset in taken:
                continue
            taken.add(offset)
            _status(service, asset, today, offset, rng.choice(_STORABLE))

        recorded: set[tuple[int, MaintenanceKind]] = set()
        for _ in range(rng.randint(0, 4)):
            kind = rng.choice(list(MaintenanceKind))
            offset = -rng.randint(0, -start)
            if (offset, kind) in recorded:
                continue
            recorded.add((offset, kind))
            next_due = offset + rng.randint(30, 400) if rng.random() < 0.5 else None
            _maintenance(service, asset, today, offset, kind, next_due)


def generate(ctx: DemoContext) -> None:
    """Create the fictitious infrastructure data of the demo database (runs once, inside the
    seeding transaction of :func:`cbrn_dashboard.demo.generate`).
    """
    service = InfrastructureService(ctx.conn, ctx.clock, operator=lambda: OPERATOR)
    demo_type = _create_demo_type(service)
    types = _type_ids(service)
    _guaranteed(service, ctx.today, types, demo_type)
    available = [types[code] for code in _BUILT_IN_TYPES] + [demo_type]
    _filler(ctx, service, available, first=10)
