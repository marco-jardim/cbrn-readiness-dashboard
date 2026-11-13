# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the dashboard service (PLAN.md T6.5, service half; 5.4, D13-D15, R05).

All data is fictitious and is written THROUGH the module services. The expected values are written
out in this file: they were worked out by hand from the rules of the module services for the dates
below (see the comments of ``_seed``), not by calling the service under test.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import MappingProxyType

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorStatus,
    Module,
    UnitKind,
)
from cbrn_dashboard.domain.infrastructure import AssetStatus, MaintenanceKind
from cbrn_dashboard.services.alerts import AlertService
from cbrn_dashboard.services.budget import BudgetService, EntryInput
from cbrn_dashboard.services.dashboard import (
    ChartSpec,
    DashboardData,
    DashboardService,
    SeriesSpec,
    Tile,
)
from cbrn_dashboard.services.exercises import EditionInput, ExercisesService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import (
    AssetInput,
    AssetTypeInput,
    InfrastructureService,
)
from cbrn_dashboard.services.personnel import (
    CertificateInput,
    CourseInput,
    PersonnelService,
    StaffInput,
    TrainingInput,
)
from cbrn_dashboard.storage.db import DatabaseConnection

AS_OF = date(2026, 3, 5)
EARLIER = date(2025, 6, 15)
OPERATOR = "op-demo"

NT = IndicatorStatus.NO_TARGET
ND = IndicatorStatus.NO_DATA
OK = IndicatorStatus.OK
WARN = IndicatorStatus.WARNING
CRIT = IndicatorStatus.CRITICAL

type Row = tuple[str, str, float | None, IndicatorStatus]


@dataclass
class Stack:
    """The six services over one connection, with the ids the tests need."""

    personnel: PersonnelService
    infrastructure: InfrastructureService
    exercises: ExercisesService
    budget: BudgetService
    indicators: IndicatorService
    alerts: AlertService
    dashboard: DashboardService
    brl_dirsa_entry: int = 0


def _stack(conn: DatabaseConnection, clock: FixedClock) -> Stack:
    def operator() -> str:
        return OPERATOR

    personnel = PersonnelService(conn, clock, operator)
    infrastructure = InfrastructureService(conn, clock, operator)
    exercises = ExercisesService(conn, clock, operator)
    budget = BudgetService(conn, clock, operator)
    indicators = IndicatorService(
        conn,
        clock,
        operator,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
    )
    alerts = AlertService(personnel=personnel, infrastructure=infrastructure, indicators=indicators)
    dashboard = DashboardService(
        indicators=indicators,
        alerts=alerts,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
    )
    return Stack(personnel, infrastructure, exercises, budget, indicators, alerts, dashboard)


def _source_id(conn: DatabaseConnection, code: str) -> int:
    row = conn.execute("SELECT id FROM funding_source WHERE code = ?", (code,)).fetchone()
    return int(row[0])


def _seed(stack: Stack, conn: DatabaseConnection) -> None:
    """The fictitious dataset; AS_OF = 2026-03-05, EARLIER = 2025-06-15.

    Personnel (warning window 90 days): P001 holds A until 2026-03-20 (expiring on AS_OF) and B
    until 2027-02-10; P002 holds A until 2027-02-10 and B until 2026-01-10 (expired on AS_OF, still
    valid on EARLIER); P003 holds A until 2027-01-10. One training record of P001 on 2026-01-10.

    Infrastructure: type A has A001 (operational, interval 0) and A002 (degraded from 2026-01-10,
    interval 30, preventive maintenance on 2026-02-20 due 2026-03-25); type B has A003
    (operational, no interval, so the schedule is unknown) and A004 (operational, interval 30, no
    maintenance, so due 2025-01-31). All four are in service since 2025-01-01. The four built-in
    types hold none.

    Exercises: EX-24 ended 2024-03-05 (40 participants, 3 countries), EX-25 ended 2025-09-05 (no
    participant count, 2 countries), EX-27 is in the future (2026-09-01).

    Budget: FY2025 DIRSA/BRL 80 000 allocated, 60 000 executed on 2025-03-01 and 10 000 on
    2025-09-01; FY2026 DIRSA/BRL 100 000 (25 000 on 2026-01-10 and 40 000 on 2026-04-10),
    COMAER/BRL 50 000 (10 000 on 2026-02-01) and DIRSA/USD 20 000 (5 000 on 2026-03-01).
    All amounts in minor units.
    """
    people = stack.personnel
    first = people.create_staff(StaffInput("DEMO-P001", "2020-01-01"))
    second = people.create_staff(StaffInput("DEMO-P002", "2020-01-01"))
    third = people.create_staff(StaffInput("DEMO-P003", "2021-01-01"))
    people.add_certificate(first, CertificateInput("A", "2024-03-20", "2026-03-20"))
    people.add_certificate(first, CertificateInput("B", "2025-02-10", "2027-02-10"))
    people.add_certificate(second, CertificateInput("A", "2025-02-10", "2027-02-10"))
    people.add_certificate(second, CertificateInput("B", "2024-01-10", "2026-01-10"))
    people.add_certificate(third, CertificateInput("A", "2025-01-10", "2027-01-10"))
    course = people.create_course(CourseInput("DEMO-C1", "Curso Demo"))
    people.add_training(first, TrainingInput(course, "2026-01-10", 8))

    infra = stack.infrastructure
    type_a = infra.create_type(AssetTypeInput("DEMO-TYPE-A", "Tipo demo A"))
    type_b = infra.create_type(AssetTypeInput("DEMO-TYPE-B", "Tipo demo B"))

    def asset(tag: str, type_id: int, interval: int | None) -> int:
        return infra.create_asset(
            AssetInput(
                tag=tag,
                type_id=type_id,
                in_service_from="2025-01-01",
                maintenance_interval_days=interval,
            ),
            AssetStatus.OPERATIONAL,
        )

    asset("DEMO-A001", type_a, 0)
    degraded = asset("DEMO-A002", type_a, 30)
    infra.change_status(degraded, "2026-01-10", AssetStatus.DEGRADED)
    infra.record_maintenance(degraded, "2026-02-20", MaintenanceKind.PREVENTIVE, "2026-03-25")
    asset("DEMO-A003", type_b, None)
    asset("DEMO-A004", type_b, 30)

    exercises = stack.exercises
    exercises.create_edition(
        EditionInput(
            code="DEMO-EX-24",
            kind="CBRAMED",
            start_on="2024-03-01",
            end_on="2024-03-05",
            participants=40,
            countries=("BR", "AR", "PT"),
        )
    )
    exercises.create_edition(
        EditionInput(
            code="DEMO-EX-25",
            kind="CBRAMED",
            start_on="2025-09-01",
            end_on="2025-09-05",
            countries=("BR", "AR"),
        )
    )
    exercises.create_edition(
        EditionInput(
            code="DEMO-EX-27",
            kind="CBRAMED",
            start_on="2026-09-01",
            end_on="2026-09-05",
            participants=60,
            countries=("BR",),
        )
    )

    budget = stack.budget
    dirsa = _source_id(conn, "DIRSA")
    comaer = _source_id(conn, "COMAER")
    last_year = budget.create_entry(
        EntryInput(fiscal_year=2025, source_id=dirsa, allocated_minor=80_000, currency="BRL")
    )
    budget.add_execution(last_year, "2025-03-01", 60_000)
    budget.add_execution(last_year, "2025-09-01", 10_000)
    stack.brl_dirsa_entry = budget.create_entry(
        EntryInput(fiscal_year=2026, source_id=dirsa, allocated_minor=100_000, currency="BRL")
    )
    budget.add_execution(stack.brl_dirsa_entry, "2026-01-10", 25_000)
    budget.add_execution(stack.brl_dirsa_entry, "2026-04-10", 40_000)
    other = budget.create_entry(
        EntryInput(fiscal_year=2026, source_id=comaer, allocated_minor=50_000, currency="BRL")
    )
    budget.add_execution(other, "2026-02-01", 10_000)
    dollars = budget.create_entry(
        EntryInput(fiscal_year=2026, source_id=dirsa, allocated_minor=20_000, currency="USD")
    )
    budget.add_execution(dollars, "2026-03-01", 5_000)

    # Targets: B certificates (higher is better), overdue maintenance of type A (lower is better)
    # and the year-end execution rate of DIRSA/BRL (pro-rated by the elapsed part of the year).
    stack.indicators.set_target("PERS_CERT_VALID", "level=B", warning_value=2, critical_value=1)
    stack.indicators.set_target(
        "INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A", warning_value=1, critical_value=2
    )
    stack.indicators.set_target(
        "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", warning_value=0.9, critical_value=0.6
    )


@pytest.fixture
def bare(db: DatabaseConnection, clock: FixedClock) -> Stack:
    """The services over a fresh database with no records at all."""
    return _stack(db, clock)


@pytest.fixture
def stack(bare: Stack, db: DatabaseConnection) -> Stack:
    """The services over the seeded fictitious database."""
    _seed(bare, db)
    return bare


# --------------------------------------------------------------------------- expected values

# (code, dimension, value, status) of every tile on AS_OF, in registry and dimension order.
EXPECTED_ROWS_AS_OF: list[Row] = [
    ("PERS_CERT_VALID", "level=A", 3.0, NT),
    ("PERS_CERT_VALID", "level=B", 1.0, CRIT),
    ("PERS_CERT_VALID", "level=C", 0.0, NT),
    ("PERS_CERT_EXPIRING", "level=A", 1.0, NT),
    ("PERS_CERT_EXPIRING", "level=B", 0.0, NT),
    ("PERS_CERT_EXPIRING", "level=C", 0.0, NT),
    ("PERS_RETRAINING_NEEDED", "level=A", 1.0, NT),
    ("PERS_RETRAINING_NEEDED", "level=B", 1.0, NT),
    ("PERS_RETRAINING_NEEDED", "level=C", 0.0, NT),
    ("PERS_DEGREE", "level=doctorate;status=completed", 0.0, NT),
    ("PERS_DEGREE", "level=doctorate;status=in_progress", 0.0, NT),
    ("PERS_DEGREE", "level=master;status=completed", 0.0, NT),
    ("PERS_DEGREE", "level=master;status=in_progress", 0.0, NT),
    ("PERS_DEGREE", "level=specialisation;status=completed", 0.0, NT),
    ("PERS_DEGREE", "level=specialisation;status=in_progress", 0.0, NT),
    ("PERS_TRAINING_12M", "", 1.0, NT),
    ("INFRA_AVAILABLE", "type=DEMO-TYPE-A", 1.0, NT),
    ("INFRA_AVAILABLE", "type=DEMO-TYPE-B", 2.0, NT),
    ("INFRA_AVAILABLE", "type=bay", 0.0, NT),
    ("INFRA_AVAILABLE", "type=bed", 0.0, NT),
    ("INFRA_AVAILABLE", "type=decon_tent", 0.0, NT),
    ("INFRA_AVAILABLE", "type=neg_pressure_filtration", 0.0, NT),
    ("INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A", 0.0, OK),
    ("INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-B", 1.0, NT),
    ("INFRA_MAINT_OVERDUE", "type=bay", 0.0, NT),
    ("INFRA_MAINT_OVERDUE", "type=bed", 0.0, NT),
    ("INFRA_MAINT_OVERDUE", "type=decon_tent", 0.0, NT),
    ("INFRA_MAINT_OVERDUE", "type=neg_pressure_filtration", 0.0, NT),
    ("EX_LAST_PARTICIPANTS", "kind=CBRAMED", None, ND),
    ("EX_LAST_PARTICIPANTS", "kind=EXBRAMED", None, ND),
    ("EX_LAST_PARTICIPANTS", "kind=OTHER", None, ND),
    ("EX_LAST_COUNTRIES", "kind=CBRAMED", 2.0, NT),
    ("EX_LAST_COUNTRIES", "kind=EXBRAMED", None, ND),
    ("EX_LAST_COUNTRIES", "kind=OTHER", None, ND),
    ("EX_DAYS_SINCE_LAST", "kind=CBRAMED", 181.0, NT),
    ("EX_DAYS_SINCE_LAST", "kind=EXBRAMED", None, ND),
    ("EX_DAYS_SINCE_LAST", "kind=OTHER", None, ND),
    ("BUD_EXEC_RATE", "currency=BRL;source=COMAER", 0.2, NT),
    ("BUD_EXEC_RATE", "currency=BRL;source=DIRSA", 0.25, OK),
    ("BUD_EXEC_RATE", "currency=USD;source=DIRSA", 0.25, NT),
]

# The tiles that differ on EARLIER, and the number of tiles there (the FY2025 budget has one row).
EXPECTED_SOME_ROWS_EARLIER: list[Row] = [
    ("PERS_CERT_VALID", "level=A", 3.0, NT),
    ("PERS_CERT_VALID", "level=B", 2.0, WARN),
    ("PERS_CERT_EXPIRING", "level=A", 0.0, NT),
    ("PERS_RETRAINING_NEEDED", "level=A", 0.0, NT),
    ("PERS_RETRAINING_NEEDED", "level=B", 0.0, NT),
    ("PERS_TRAINING_12M", "", 0.0, NT),
    ("INFRA_AVAILABLE", "type=DEMO-TYPE-A", 2.0, NT),
    ("INFRA_AVAILABLE", "type=DEMO-TYPE-B", 2.0, NT),
    ("INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A", 1.0, WARN),
    ("INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-B", 1.0, NT),
    ("EX_LAST_PARTICIPANTS", "kind=CBRAMED", 40.0, NT),
    ("EX_LAST_COUNTRIES", "kind=CBRAMED", 3.0, NT),
    ("EX_DAYS_SINCE_LAST", "kind=CBRAMED", 467.0, NT),
    ("BUD_EXEC_RATE", "currency=BRL;source=DIRSA", 0.75, OK),
]
TILE_COUNT_AS_OF = 40
TILE_COUNT_EARLIER = 38

# The asset type codes, sorted: the two demo types, then the four built-in ones (no assets).
TYPE_CODES = ("DEMO-TYPE-A", "DEMO-TYPE-B", "bay", "bed", "decon_tent", "neg_pressure_filtration")


def _counts(critical: int, warning: int, info: int) -> dict[Severity, int]:
    return {Severity.CRITICAL: critical, Severity.WARNING: warning, Severity.INFO: info}


CHARTS_AS_OF: list[ChartSpec] = [
    ChartSpec(
        key="personnel_valid_by_level",
        categories=("A", "B", "C"),
        series=(SeriesSpec("valid", (3.0, 1.0, 0.0)),),
        unit=UnitKind.COUNT,
        parameters={},
    ),
    ChartSpec(
        key="infrastructure_availability",
        categories=TYPE_CODES,
        series=(
            SeriesSpec("available", (1.0, 2.0, 0.0, 0.0, 0.0, 0.0)),
            SeriesSpec("in_service", (2.0, 2.0, 0.0, 0.0, 0.0, 0.0)),
        ),
        unit=UnitKind.COUNT,
        parameters={},
    ),
    ChartSpec(
        key="exercises_by_edition",
        categories=("DEMO-EX-24", "DEMO-EX-25"),
        series=(
            SeriesSpec("participants", (40.0, None)),
            SeriesSpec("countries", (3.0, 2.0)),
        ),
        unit=UnitKind.COUNT,
        parameters={},
    ),
    ChartSpec(
        key="budget_BRL",
        categories=("COMAER", "DIRSA"),
        series=(
            SeriesSpec("allocated", (500.0, 1000.0)),
            SeriesSpec("executed", (100.0, 250.0)),
        ),
        unit=UnitKind.CURRENCY,
        parameters={"currency": "BRL", "fiscal_year": "2026"},
    ),
    ChartSpec(
        key="budget_USD",
        categories=("DIRSA",),
        series=(
            SeriesSpec("allocated", (200.0,)),
            SeriesSpec("executed", (50.0,)),
        ),
        unit=UnitKind.CURRENCY,
        parameters={"currency": "USD", "fiscal_year": "2026"},
    ),
]

CHARTS_EARLIER: list[ChartSpec] = [
    ChartSpec(
        key="personnel_valid_by_level",
        categories=("A", "B", "C"),
        series=(SeriesSpec("valid", (3.0, 2.0, 0.0)),),
        unit=UnitKind.COUNT,
        parameters={},
    ),
    ChartSpec(
        key="infrastructure_availability",
        categories=TYPE_CODES,
        series=(
            SeriesSpec("available", (2.0, 2.0, 0.0, 0.0, 0.0, 0.0)),
            SeriesSpec("in_service", (2.0, 2.0, 0.0, 0.0, 0.0, 0.0)),
        ),
        unit=UnitKind.COUNT,
        parameters={},
    ),
    ChartSpec(
        key="exercises_by_edition",
        categories=("DEMO-EX-24",),
        series=(
            SeriesSpec("participants", (40.0,)),
            SeriesSpec("countries", (3.0,)),
        ),
        unit=UnitKind.COUNT,
        parameters={},
    ),
    ChartSpec(
        key="budget_BRL",
        categories=("DIRSA",),
        series=(
            SeriesSpec("allocated", (800.0,)),
            SeriesSpec("executed", (600.0,)),
        ),
        unit=UnitKind.CURRENCY,
        parameters={"currency": "BRL", "fiscal_year": "2025"},
    ),
]


# --------------------------------------------------------------------------- helpers


def _rows(data: DashboardData) -> list[Row]:
    return [(t.code, t.dimension, t.value, t.status) for t in data.tiles]


def _tile(data: DashboardData, code: str, dimension: str = "") -> Tile:
    for tile in data.tiles:
        if (tile.code, tile.dimension) == (code, dimension):
            return tile
    raise AssertionError((code, dimension))


def _charts(data: DashboardData) -> list[ChartSpec]:
    return list(data.charts)


# --------------------------------------------------------------------------- tiles


def test_tiles_have_the_explicit_codes_values_and_statuses(stack: Stack) -> None:
    data = stack.dashboard.data(AS_OF)
    assert data.as_of == AS_OF
    assert len(data.tiles) == TILE_COUNT_AS_OF
    assert _rows(data) == EXPECTED_ROWS_AS_OF


def test_tiles_are_exactly_the_indicator_readings_in_the_same_order(stack: Stack) -> None:
    for as_of in (AS_OF, EARLIER):
        data = stack.dashboard.data(as_of)
        readings = stack.indicators.evaluate(as_of)
        assert [
            (t.code, t.dimension, t.value, t.status, t.warning_value, t.critical_value)
            for t in data.tiles
        ] == [
            (r.code, r.dimension, r.value, r.status, r.warning_value, r.critical_value)
            for r in readings
        ]


def test_tiles_carry_unit_direction_module_and_decoded_dimension(stack: Stack) -> None:
    data = stack.dashboard.data(AS_OF)

    valid = _tile(data, "PERS_CERT_VALID", "level=B")
    assert valid.unit is UnitKind.COUNT
    assert valid.direction is Direction.HIGHER_IS_BETTER
    assert valid.module is Module.PERSONNEL
    assert dict(valid.dimension_parts) == {"level": "B"}

    days = _tile(data, "EX_DAYS_SINCE_LAST", "kind=CBRAMED")
    assert (days.unit, days.direction, days.module) == (
        UnitKind.DAYS,
        Direction.LOWER_IS_BETTER,
        Module.EXERCISES,
    )

    rate = _tile(data, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA")
    assert (rate.unit, rate.direction, rate.module) == (
        UnitKind.RATIO,
        Direction.HIGHER_IS_BETTER,
        Module.BUDGET,
    )
    assert dict(rate.dimension_parts) == {"currency": "BRL", "source": "DIRSA"}

    training = _tile(data, "PERS_TRAINING_12M")
    assert dict(training.dimension_parts) == {}
    assert dict(training.context) == {}


def test_tiles_carry_the_thresholds_in_force(stack: Stack) -> None:
    data = stack.dashboard.data(AS_OF)

    valid = _tile(data, "PERS_CERT_VALID", "level=B")
    assert (valid.warning_value, valid.critical_value) == (2.0, 1.0)
    overdue = _tile(data, "INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A")
    assert (overdue.warning_value, overdue.critical_value) == (1.0, 2.0)

    # the year-end target 0.9 / 0.6 scaled by day 64 of 365 (P08)
    rate = _tile(data, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA")
    assert rate.warning_value == pytest.approx(0.9 * 64 / 365)
    assert rate.critical_value == pytest.approx(0.6 * 64 / 365)

    untargeted = [
        t
        for t in data.tiles
        if (t.code, t.dimension)
        not in {
            ("PERS_CERT_VALID", "level=B"),
            ("INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A"),
            ("BUD_EXEC_RATE", "currency=BRL;source=DIRSA"),
        }
    ]
    assert len(untargeted) == TILE_COUNT_AS_OF - 3
    assert all(t.warning_value is None and t.critical_value is None for t in untargeted)


def test_availability_tiles_carry_the_in_service_total_as_context(stack: Stack) -> None:
    data = stack.dashboard.data(AS_OF)
    expected_in_service = {
        "type=DEMO-TYPE-A": 2.0,
        "type=DEMO-TYPE-B": 2.0,
        "type=bay": 0.0,
        "type=bed": 0.0,
        "type=decon_tent": 0.0,
        "type=neg_pressure_filtration": 0.0,
    }
    available = {t.dimension: t for t in data.tiles if t.code == "INFRA_AVAILABLE"}
    assert {dim: dict(t.context) for dim, t in available.items()} == {
        dim: {"in_service": total} for dim, total in expected_in_service.items()
    }
    assert available["type=DEMO-TYPE-A"].value == 1.0  # one operational, one degraded
    with_context = {"INFRA_AVAILABLE", "BUD_EXEC_RATE"}
    assert all(dict(t.context) == {} for t in data.tiles if t.code not in with_context)


def test_budget_tiles_keep_the_exact_minor_units_in_their_context(stack: Stack) -> None:
    data = stack.dashboard.data(AS_OF)
    contexts = {t.dimension: dict(t.context) for t in data.tiles if t.code == "BUD_EXEC_RATE"}
    assert contexts == {
        "currency=BRL;source=DIRSA": {"allocated_minor": 100_000.0, "executed_minor": 25_000.0},
        "currency=BRL;source=COMAER": {
            "allocated_minor": 50_000.0,
            "executed_minor": 10_000.0,
        },
        "currency=USD;source=DIRSA": {"allocated_minor": 20_000.0, "executed_minor": 5_000.0},
    }


# --------------------------------------------------------------------------- alert counts


def test_alert_counts_by_severity(stack: Stack) -> None:
    # critical: P002 level B expired, A004 overdue, indicator PERS_CERT_VALID level B;
    # warning: P001 level A expiring, A002 due soon; info: A003 schedule unknown.
    counts = stack.dashboard.data(AS_OF).alert_counts
    assert dict(counts) == _counts(3, 2, 1)
    assert set(counts) == set(Severity)


# --------------------------------------------------------------------------- charts


def test_charts_have_the_explicit_categories_and_series_values(stack: Stack) -> None:
    data = stack.dashboard.data(AS_OF)
    assert _charts(data) == CHARTS_AS_OF
    assert [chart.key for chart in data.charts] == [
        "personnel_valid_by_level",
        "infrastructure_availability",
        "exercises_by_edition",
        "budget_BRL",
        "budget_USD",
    ]


def test_budget_charts_are_one_per_currency_and_as_of_the_date(stack: Stack) -> None:
    charts = {c.key: c for c in stack.dashboard.data(AS_OF).charts if c.key.startswith("budget_")}
    assert set(charts) == {"budget_BRL", "budget_USD"}
    for currency, chart in (("BRL", charts["budget_BRL"]), ("USD", charts["budget_USD"])):
        assert chart.parameters["currency"] == currency
        assert chart.unit is UnitKind.CURRENCY
    # the 40 000 executed on 2026-04-10 (after AS_OF) is not in the DIRSA / BRL bar: 250.00 only
    assert charts["budget_BRL"].series[1] == SeriesSpec("executed", (100.0, 250.0))
    # no USD entry in 2025: no USD chart then
    assert "budget_USD" not in {c.key for c in stack.dashboard.data(EARLIER).charts}


def test_exercises_chart_excludes_the_future_edition_and_keeps_a_missing_count(
    stack: Stack,
) -> None:
    [chart] = [c for c in stack.dashboard.data(AS_OF).charts if c.key == "exercises_by_edition"]
    assert chart.categories == ("DEMO-EX-24", "DEMO-EX-25")
    assert "DEMO-EX-27" not in chart.categories
    assert chart.series[0] == SeriesSpec("participants", (40.0, None))


def test_the_exercises_chart_shows_at_most_the_twelve_latest_editions(
    stack: Stack,
) -> None:
    for number in range(1, 14):
        stack.exercises.create_edition(
            EditionInput(
                code=f"DEMO-OLD-{number:02d}",
                kind="OTHER",
                start_on=date(2000 + number, 5, 1),
                end_on=date(2000 + number, 5, 2),
                participants=number,
            )
        )
    [chart] = [c for c in stack.dashboard.data(AS_OF).charts if c.key == "exercises_by_edition"]
    # 13 + 2 finished editions: the 12 most recent are DEMO-OLD-04 .. 13 and the two DEMO-EX ones
    assert len(chart.categories) == 12
    assert chart.categories[-2:] == ("DEMO-EX-24", "DEMO-EX-25")
    assert chart.categories[0] == "DEMO-OLD-04"


def test_chart_spec_is_codes_and_read_only_numbers(stack: Stack) -> None:
    for chart in stack.dashboard.data(AS_OF).charts:
        assert isinstance(chart.parameters, MappingProxyType)
        for series in chart.series:
            assert len(series.values) == len(chart.categories)


# --------------------------------------------------------------------------- as-of date


def test_changing_the_as_of_date_changes_tiles_charts_and_counts(stack: Stack) -> None:
    late = stack.dashboard.data(AS_OF)
    early = stack.dashboard.data(EARLIER)

    assert early.as_of == EARLIER
    assert len(early.tiles) == TILE_COUNT_EARLIER
    early_rows = {(code, dim): (value, status) for code, dim, value, status in _rows(early)}
    for code, dim, value, status in EXPECTED_SOME_ROWS_EARLIER:
        assert early_rows[code, dim] == (value, status)
    assert _charts(early) == CHARTS_EARLIER
    # critical: A002 and A004 overdue; warning: indicators B certificates and type A overdue;
    # info: A003 schedule unknown
    assert dict(early.alert_counts) == _counts(2, 2, 1)

    assert _rows(early) != _rows(late)
    assert _charts(early) != _charts(late)
    assert early.alert_counts != late.alert_counts


def test_nothing_is_cached_a_new_record_shows_on_the_next_call(stack: Stack) -> None:
    before = stack.dashboard.data(AS_OF)
    stack.budget.add_execution(stack.brl_dirsa_entry, "2026-03-01", 5_000)
    after = stack.dashboard.data(AS_OF)
    assert after != before
    [chart] = [c for c in after.charts if c.key == "budget_BRL"]
    assert chart.series[1] == SeriesSpec("executed", (100.0, 300.0))
    assert _tile(after, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA").value == pytest.approx(0.3)


# --------------------------------------------------------------------------- empty and read-only


def test_an_empty_database_gives_only_no_target_or_no_data_and_empty_charts(bare: Stack) -> None:
    data = bare.dashboard.data(AS_OF)

    assert data.tiles
    assert {t.status for t in data.tiles} <= {NT, ND}
    assert all(t.warning_value is None and t.critical_value is None for t in data.tiles)
    assert dict(data.alert_counts) == _counts(0, 0, 0)
    # no budget entry: no budget chart; the three other charts are present but empty
    assert [chart.key for chart in data.charts] == [
        "personnel_valid_by_level",
        "infrastructure_availability",
        "exercises_by_edition",
    ]
    for chart in data.charts:
        assert chart.categories == ()
        assert all(series.values == () for series in chart.series)


def test_a_read_only_connection_gives_the_same_dashboard(
    stack: Stack, read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    reader = _stack(read_only_db, clock)
    for as_of in (AS_OF, EARLIER):
        assert reader.dashboard.data(as_of) == stack.dashboard.data(as_of)
