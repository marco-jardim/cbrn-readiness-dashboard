# SPDX-License-Identifier: GPL-3.0-or-later
"""Retroactive readiness snapshots for the demo database (PLAN.md T10.1, T8.1, T8.2, K13, D25).

Gives the validation export something to read: for every demo edition that has already started on
``ctx.today``, one snapshot is recorded for the day BEFORE the edition's ``start_on``. The demo
database is created today, so every one of them is taken after its ``as_of`` date and the snapshot
service stores it with the origin ``retroactive`` (K13); this generator asks for ``manual`` and
cannot choose otherwise. The edition that starts after today gets none.

Nothing bypasses the service: each snapshot is recorded by
:meth:`~cbrn_dashboard.services.snapshots.SnapshotService.record`, which evaluates every indicator
for that day from the records as known today, with the targets of the targets generator (run
before this one) in force. Each snapshot note starts with ``DEMO`` and names the edition.

The monthly snapshot hook does not run in demo mode, so these are the only snapshots a demo
database holds until the operator records more.

Qt-free.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from cbrn_dashboard.demo.stack import build_services
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.snapshots import SnapshotOrigin, SnapshotService

if TYPE_CHECKING:
    from cbrn_dashboard.demo import DemoContext

__all__ = ["generate"]


def generate(ctx: DemoContext) -> None:
    """Record one retroactive snapshot per already started demo edition."""
    from cbrn_dashboard.demo import assert_demo_identifier
    from cbrn_dashboard.demo.stack import OPERATOR

    services = build_services(ctx)
    exercises = ExercisesService(ctx.conn, ctx.clock, lambda: OPERATOR)
    snapshots = SnapshotService(
        ctx.conn,
        ctx.clock,
        lambda: OPERATOR,
        indicators=services.indicators,
        infrastructure=services.infrastructure,
        stock=services.stock,
    )
    for edition in exercises.list_editions():
        if edition.start_on > ctx.today:
            continue  # an edition that has not started has nothing to look back from
        note = f"DEMO - reading the day before {edition.code} (fictitious)"
        assert_demo_identifier(note)
        snapshots.record(
            edition.start_on - timedelta(days=1), origin=SnapshotOrigin.MANUAL, note=note
        )
