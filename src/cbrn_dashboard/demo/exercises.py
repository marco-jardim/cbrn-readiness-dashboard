# SPDX-License-Identifier: GPL-3.0-or-later
"""Demo data for the exercises module (PLAN.md T4.6, D25, I07).

Everything here is fictitious. The numbers come from ``ctx.rng`` (a ``random.Random`` seeded per
generator), the dates are computed from ``ctx.today`` (the injected clock's date), the countries are
drawn from the seed list of known country codes and nothing is read from a real source. In
particular, no figure, date or country list of any real CBRAMED / EXBRAMED edition is used here.

What is created (everything goes THROUGH ``services.exercises.ExercisesService``, so every row is
validated and written to the change log with the operator label ``DEMO``):

* two metrics, ``DEMO-M1`` (higher is better) and ``DEMO-M2`` (lower is better);
* past editions ``DEMO-EX-01`` .. of every kind, spread over roughly the previous four years;
* ONE past edition without a participant count, the latest ended edition of its kind, so the
  "No data" case of ``EX_LAST_PARTICIPANTS`` is visible on the dashboard;
* ONE future edition (it starts after today) and therefore without results;
* results of both metrics for the past editions only, inside each metric's scale.

Participants are only counted, never identified (D20). Every identifier starts with ``DEMO``.

Qt-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from cbrn_dashboard.domain.dates import add_months
from cbrn_dashboard.domain.exercises import ExerciseKind
from cbrn_dashboard.services.countries import country_codes
from cbrn_dashboard.services.exercises import (
    EditionInput,
    ExercisesService,
    MetricInput,
    ResultInput,
)

if TYPE_CHECKING:
    # The package imports this module to register it, so DemoContext is only needed for typing.
    from cbrn_dashboard.demo import DemoContext

__all__ = ["OPERATOR", "generate"]

#: Operator label written to the change log for every row this generator creates.
OPERATOR = "DEMO"

_M1_SCALE = (0.0, 10.0)  # points, higher is better
_M2_SCALE = (0.0, 120.0)  # minutes, lower is better

_NO_PARTICIPANTS_NOTE = "DEMO - fictitious data; the participant count was not recorded"
_PAST_NOTE = "DEMO - fictitious data"
_FUTURE_NOTE = "DEMO - planned edition; the figures are expected values, not results"


@dataclass(frozen=True)
class _Plan:
    """One edition to create: its kind and how many months before today it ended."""

    kind: ExerciseKind
    months_ago: int  # negative: a future edition, this many months after today
    has_participants: bool = True


# The order is the numbering order (DEMO-EX-01, 02, ...). Within a kind the editions are at least a
# year apart, so the order by date never depends on the random day offsets. EXBRAMED's most recent
# edition is the one without a participant count.
_PLAN: tuple[_Plan, ...] = (
    _Plan(ExerciseKind.CBRAMED, 44),
    _Plan(ExerciseKind.CBRAMED, 28),
    _Plan(ExerciseKind.CBRAMED, 9),
    _Plan(ExerciseKind.EXBRAMED, 38),
    _Plan(ExerciseKind.EXBRAMED, 20),
    _Plan(ExerciseKind.EXBRAMED, 4, has_participants=False),
    _Plan(ExerciseKind.OTHER, 32),
    _Plan(ExerciseKind.OTHER, 14),
    _Plan(ExerciseKind.CBRAMED, -5),
)


def generate(ctx: DemoContext) -> None:
    """Create the demo metrics, editions, countries and results (see the module docstring)."""
    # Imported here, not at the top: the package imports this module while it is still being
    # initialised, and these two helpers are defined in the package itself.
    from cbrn_dashboard.demo import assert_demo_identifier, demo_identifier

    service = ExercisesService(ctx.conn, ctx.clock, lambda: OPERATOR)
    rng = ctx.rng

    # Metric 1: higher is better, scale 0..10. Metric 2: lower is better, scale 0..120 minutes.
    metrics: list[tuple[int, float, float]] = []  # (metric id, scale min, scale max)
    metric_inputs = (
        MetricInput(
            code=demo_identifier("M", 1, width=1),
            label_pt_br="DEMO - nota média",
            label_en_us="DEMO - average score",
            label_es_es="DEMO - nota media",
            unit="points",
            scale_min=_M1_SCALE[0],
            scale_max=_M1_SCALE[1],
            higher_is_better=True,
        ),
        MetricInput(
            code=demo_identifier("M", 2, width=1),
            label_pt_br="DEMO - tempo de resposta",
            label_en_us="DEMO - response time",
            label_es_es="DEMO - tiempo de respuesta",
            unit="min",
            scale_min=_M2_SCALE[0],
            scale_max=_M2_SCALE[1],
            higher_is_better=False,
        ),
    )
    for metric_input, scale in zip(metric_inputs, (_M1_SCALE, _M2_SCALE), strict=True):
        assert_demo_identifier(metric_input.code)
        for label in (metric_input.label_pt_br, metric_input.label_en_us, metric_input.label_es_es):
            assert_demo_identifier(label or "")
        metrics.append((service.create_metric(metric_input), scale[0], scale[1]))

    # All numbers below are random and fictitious. They are NOT copied from the thesis tables or
    # from any real edition.
    codes = sorted(country_codes())
    for number, plan in enumerate(_PLAN, start=1):
        code = demo_identifier("EX-", number, width=2)
        title = f"DEMO - {plan.kind.value} (fictitious edition {number})"
        assert_demo_identifier(code)
        assert_demo_identifier(title)
        duration = timedelta(days=rng.randint(2, 8))
        if plan.months_ago > 0:
            end_on = add_months(ctx.today, -plan.months_ago) - timedelta(days=rng.randint(0, 20))
            start_on = end_on - duration
        else:
            start_on = add_months(ctx.today, -plan.months_ago) + timedelta(days=rng.randint(0, 20))
            end_on = start_on + duration
        participants = rng.randint(40, 220)
        countries = rng.sample(codes, rng.randint(4, 14))
        is_past = plan.months_ago > 0
        if is_past:
            note = _PAST_NOTE if plan.has_participants else _NO_PARTICIPANTS_NOTE
        else:
            note = _FUTURE_NOTE
        edition_id = service.create_edition(
            EditionInput(
                code=code,
                kind=plan.kind.value,
                start_on=start_on,
                end_on=end_on,
                title=title,
                participants=participants if plan.has_participants else None,
                notes=note,
                countries=countries,
            )
        )
        if not is_past:
            continue  # a future edition has no results yet
        for metric_id, scale_min, scale_max in metrics:
            span = scale_max - scale_min
            value = round(rng.uniform(scale_min + 0.4 * span, scale_min + 0.9 * span), 1)
            service.set_result(
                edition_id,
                ResultInput(metric_id=metric_id, value=value, respondents=rng.randint(10, 80)),
            )
