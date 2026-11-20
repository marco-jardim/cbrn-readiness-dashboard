# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the report model and the anonymisation (PLAN.md T8.5; A11, R11-R13, D18, D25).

All data is fictitious and is written THROUGH the module services. The strings that must never
reach the anonymised variant are distinctive (``ZEBRA``, ``LEMUR``, ``Fictitious ...``). The
expected values were worked out by hand from the rules of the module services for the dates below
(see the comments of ``_seed``).
"""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.indicators import IndicatorStatus, Module
from cbrn_dashboard.domain.infrastructure import AssetStatus
from cbrn_dashboard.domain.personnel import PpeLevel
from cbrn_dashboard.reports.anonymise import anonymise
from cbrn_dashboard.reports.model import (
    PRELIMINARY_NOTICE_CODE,
    AlertSource,
    Cell,
    IndicatorRow,
    KeyFigureGroup,
    ReportBuilder,
    ReportDocument,
    ReportHeader,
    ReportVariant,
)
from cbrn_dashboard.services.alerts import AlertService
from cbrn_dashboard.services.budget import BudgetService, EntryInput
from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.services.dashboard import DashboardService
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
    DegreeInput,
    PersonnelService,
    StaffInput,
    TrainingInput,
)
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

AS_OF = date(2026, 3, 5)
OPERATOR = "DEMO-OPERATOR"
INSTITUTION = "DEMO Institution"
UNIT = "DEMO Unit"
HANDLING = "DEMO HANDLING"
IDENTIFIER = "DEMO-ZEBRA-7731"
LABEL = "Fictitious Label QX"
ASSET_TAG = "DEMO-LEMUR-A42"
NOTE = "Fictitious Note KW"
DESCRIPTION = "DEMO Fictitious Description"
VERSION = "9.9.9-test"

#: Substrings that must not appear in any string of the anonymised variant.
FORBIDDEN = (
    IDENTIFIER,
    LABEL,
    ASSET_TAG,
    NOTE,
    DESCRIPTION,
    OPERATOR,
    INSTITUTION,
    UNIT,
    HANDLING,
    "ZEBRA",
    "LEMUR",
    "Fictitious",
    "DEMO-S0",
)


# --------------------------------------------------------------------------- fixture


@dataclass
class World:
    """The services over one seeded database."""

    conn: DatabaseConnection
    personnel: PersonnelService
    config: ConfigService
    dashboard: DashboardService
    builder: ReportBuilder
    staff: dict[str, int]


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock.at("2026-03-05T12:00:00Z")


@pytest.fixture
def world(tmp_path: Path, clock: FixedClock) -> Iterator[World]:
    conn = open_and_migrate(
        tmp_path / "reports.sqlite3",
        data_dir=tmp_path,
        identity=DatabaseIdentity.REAL,
        backup=False,
    )
    try:
        yield _world(conn, clock)
    finally:
        conn.close()


def _operator() -> str:
    return OPERATOR


def _world(conn: DatabaseConnection, clock: FixedClock) -> World:
    personnel = PersonnelService(conn, clock, _operator)
    infrastructure = InfrastructureService(conn, clock, _operator)
    exercises = ExercisesService(conn, clock, _operator)
    budget = BudgetService(conn, clock, _operator)
    indicators = IndicatorService(
        conn,
        clock,
        _operator,
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
    config = ConfigService(conn, clock, _operator)
    builder = ReportBuilder(
        conn=conn,
        clock=clock,
        dashboard=dashboard,
        personnel=personnel,
        infrastructure=infrastructure,
        config_loader=config.load,
        app_version=VERSION,
    )
    staff = _seed(conn, personnel, infrastructure, exercises, budget, indicators)
    config.save(
        dataclasses.replace(
            config.load(),
            institution_name=INSTITUTION,
            unit_name=UNIT,
            operator_label=OPERATOR,
            report_handling_notice=HANDLING,
        )
    )
    return World(conn, personnel, config, dashboard, builder, staff)


def _seed(
    conn: DatabaseConnection,
    people: PersonnelService,
    infra: InfrastructureService,
    exercises: ExercisesService,
    budget: BudgetService,
    indicators: IndicatorService,
) -> dict[str, int]:
    """The fictitious dataset; AS_OF = 2026-03-05.

    Personnel: DEMO-ZEBRA-7731 and DEMO-S01 .. DEMO-S08 (nine active). All hold A: S05 .. S08 until
    2026-04-20 (expiring on AS_OF, window 90 days), the others until 2027-02-10. S01 and S02 hold B
    until 2027-02-10; ZEBRA's B expired on 2026-01-10. So valid A 9, B 2, C 0; expiring A 4;
    retraining A 4 (the expiring) and B 1 (ZEBRA). S01 .. S05 completed a course on 2026-01-10
    (training 12 months: 5). Completed degrees: specialisation S01 .. S07 (7), master S01 .. S06
    (6), doctorate S01 and S02 (2); their sum is 15.

    Infrastructure: two in-service assets of DEMO-TYPE-A; DEMO-LEMUR-A42 has a 30-day interval and
    no maintenance, so it is overdue since 2025-01-31; DEMO-A002 has no scheduled maintenance.

    Exercises: one edition ended 2024-03-05 with 3 participants and 2 countries (730 days before).
    Budget: FY2026 DIRSA/BRL 100 000 minor units allocated, 25 000 executed on 2026-01-10.
    """
    staff: dict[str, int] = {}
    for name in (IDENTIFIER, *(f"DEMO-S{n:02d}" for n in range(1, 9))):
        staff[name] = people.create_staff(StaffInput(name, "2020-01-01", label=LABEL))
    for name, staff_id in staff.items():
        soon = name in {f"DEMO-S{n:02d}" for n in range(5, 9)}
        valid_until = "2026-04-20" if soon else "2027-02-10"
        people.add_certificate(
            staff_id, CertificateInput("A", "2025-02-10", valid_until, reference=NOTE)
        )
    for name in ("DEMO-S01", "DEMO-S02"):
        people.add_certificate(staff[name], CertificateInput("B", "2025-02-10", "2027-02-10"))
    people.add_certificate(staff[IDENTIFIER], CertificateInput("B", "2024-01-10", "2026-01-10"))
    course = people.create_course(CourseInput("DEMO-C1", LABEL))
    for n in range(1, 6):
        people.add_training(staff[f"DEMO-S{n:02d}"], TrainingInput(course, "2026-01-10", 8))
    for level, count in (("specialisation", 7), ("master", 6), ("doctorate", 2)):
        for n in range(1, count + 1):
            people.add_degree(staff[f"DEMO-S{n:02d}"], DegreeInput(level, "completed", field=NOTE))

    type_a = infra.create_type(AssetTypeInput("DEMO-TYPE-A", LABEL))
    infra.create_asset(
        AssetInput(
            tag=ASSET_TAG,
            type_id=type_a,
            in_service_from="2025-01-01",
            description=DESCRIPTION,
            location=LABEL,
            maintenance_interval_days=30,
            notes=NOTE,
        ),
        AssetStatus.OPERATIONAL,
    )
    infra.create_asset(
        AssetInput(
            tag="DEMO-A002",
            type_id=type_a,
            in_service_from="2025-01-01",
            maintenance_interval_days=0,
        ),
        AssetStatus.OPERATIONAL,
    )

    exercises.create_edition(
        EditionInput(
            code="DEMO-EX-24",
            kind="CBRAMED",
            start_on="2024-03-01",
            end_on="2024-03-05",
            title=LABEL,
            participants=3,
            notes=NOTE,
            countries=("BR", "AR"),
        )
    )

    row = conn.execute("SELECT id FROM funding_source WHERE code = ?", ("DIRSA",)).fetchone()
    entry = budget.create_entry(
        EntryInput(
            fiscal_year=2026,
            source_id=int(row[0]),
            allocated_minor=100_000,
            currency="BRL",
            description=DESCRIPTION,
            notes=NOTE,
        )
    )
    budget.add_execution(entry, "2026-01-10", 25_000, note=NOTE)

    indicators.set_target("PERS_CERT_VALID", "level=B", warning_value=3, critical_value=1)
    return staff


# --------------------------------------------------------------------------- helpers


def _strings(value: object) -> Iterator[str]:
    """Every string reachable from ``value`` (dataclasses, mappings, tuples, enums)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Enum):
        yield from _strings(value.value)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield from _strings(getattr(value, field.name))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, tuple | list | set | frozenset):
        for item in value:
            yield from _strings(item)


def _group(document: ReportDocument, module: Module) -> KeyFigureGroup:
    return next(g for g in document.key_figures if g.module is module)


def _figure(document: ReportDocument, module: Module, name: str) -> Cell:
    key = f"kf:{module.value}:{name}"
    return next(c for c in _group(document, module).cells if c.key == key)


def _row(document: ReportDocument, code: str, dimension: str = "") -> IndicatorRow:
    return next(r for r in document.indicators if (r.code, r.dimension) == (code, dimension))


def _chart_cells(document: ReportDocument) -> list[Cell]:
    return [c for chart in document.charts for s in chart.series for c in s.cells]


def _shown(cell: Cell, value: float) -> None:
    assert not cell.suppressed, cell.key
    assert cell.value == value, cell.key


def _hidden(cell: Cell) -> None:
    assert cell.suppressed, cell.key
    assert cell.value is None, cell.key


# --------------------------------------------------------------------------- internal variant


def test_internal_header_notice_and_flags(world: World) -> None:
    document = world.builder.build(AS_OF, ReportVariant.INTERNAL)

    assert document.variant is ReportVariant.INTERNAL
    assert document.header == ReportHeader(
        institution_name=INSTITUTION,
        unit_name=UNIT,
        as_of=AS_OF,
        generated_at_utc="2026-03-05T12:00:00Z",
        app_version=VERSION,
        operator_label=OPERATOR,
    )
    assert document.preliminary_notice_code == PRELIMINARY_NOTICE_CODE == "PRELIMINARY"
    assert document.handling_notice == HANDLING
    assert document.small_count_threshold == 5
    assert document.is_demo is False


def test_internal_key_figures_per_module(world: World) -> None:
    document = world.builder.build(AS_OF, ReportVariant.INTERNAL)

    assert [g.module for g in document.key_figures] == [
        Module.PERSONNEL,
        Module.INFRASTRUCTURE,
        Module.EXERCISES,
        Module.BUDGET,
    ]
    people = Module.PERSONNEL
    expected = {
        "active_staff": 9.0,
        "valid:A": 9.0,
        "valid:B": 2.0,
        "valid:C": 0.0,
        "expiring:A": 4.0,
        "expiring:B": 0.0,
        "retraining:A": 4.0,
        "retraining:B": 1.0,
        "retraining:C": 0.0,
        "degree_completed:specialisation": 7.0,
        "degree_completed:master": 6.0,
        "degree_completed:doctorate": 2.0,
        "degree_completed_total": 15.0,
    }
    for name, value in expected.items():
        cell = _figure(document, people, name)
        assert (cell.value, cell.suppressed, cell.personnel_derived) == (value, False, True), name
    total = _figure(document, people, "degree_completed_total")
    levels = ("specialisation", "master", "doctorate")
    assert set(total.total_of) == {f"kf:PERSONNEL:degree_completed:{level}" for level in levels}

    infra = Module.INFRASTRUCTURE
    assert _figure(document, infra, "overdue").value == 1.0
    assert _figure(document, infra, "due_soon").value == 0.0
    assert not _figure(document, infra, "overdue").personnel_derived
    assert _figure(document, Module.EXERCISES, "days_since_last").value == 730.0
    assert _figure(document, Module.EXERCISES, "last_participants").value == 3.0
    assert _figure(document, Module.EXERCISES, "last_countries").value == 2.0
    assert _figure(document, Module.BUDGET, "allocated:BRL").value == 1000.0
    assert _figure(document, Module.BUDGET, "executed:BRL").value == 250.0


def test_internal_indicator_table_has_statuses_and_thresholds(world: World) -> None:
    document = world.builder.build(AS_OF, ReportVariant.INTERNAL)

    # worked out by hand from the seed (see ``_seed``); only PERS_CERT_VALID level B has a target
    none = IndicatorStatus.NO_TARGET
    expected = {
        ("PERS_CERT_VALID", "level=A"): (9.0, none, None, None),
        ("PERS_CERT_VALID", "level=B"): (2.0, IndicatorStatus.WARNING, 3.0, 1.0),
        ("PERS_CERT_VALID", "level=C"): (0.0, none, None, None),
        ("PERS_CERT_EXPIRING", "level=A"): (4.0, none, None, None),
        ("PERS_CERT_EXPIRING", "level=B"): (0.0, none, None, None),
        ("PERS_RETRAINING_NEEDED", "level=A"): (4.0, none, None, None),
        ("PERS_RETRAINING_NEEDED", "level=B"): (1.0, none, None, None),
        ("PERS_RETRAINING_NEEDED", "level=C"): (0.0, none, None, None),
    }
    found = {
        (r.code, r.dimension): (r.value.value, r.status, r.warning_value, r.critical_value)
        for r in document.indicators
    }
    for key, row_values in expected.items():
        assert found[key] == row_values, key
    valid_b = _row(document, "PERS_CERT_VALID", "level=B")
    assert valid_b.status is IndicatorStatus.WARNING
    assert (valid_b.warning_value, valid_b.critical_value) == (3.0, 1.0)
    assert valid_b.dimension_parts == (("level", "B"),)
    assert valid_b.value.personnel_derived
    assert not _row(document, "INFRA_AVAILABLE", "type=DEMO-TYPE-A").value.personnel_derived


def _alerts(document: ReportDocument) -> dict[str, Cell]:
    return {a.cell.key: a.cell for a in document.alert_summary}


def test_internal_alert_summary_is_split_by_source_with_hand_computed_values(
    world: World,
) -> None:
    # Seed: expiring certificates A 4 (S05..S08), expired B 1 (ZEBRA); one overdue asset; the
    # target of PERS_CERT_VALID level B is crossed (2 < 3): one indicator warning.
    document = world.builder.build(AS_OF, ReportVariant.INTERNAL)
    cells = _alerts(document)

    assert [(a.severity, a.source) for a in document.alert_summary] == [
        (Severity.CRITICAL, AlertSource.ALL),
        (Severity.CRITICAL, AlertSource.PERSONNEL),
        (Severity.CRITICAL, AlertSource.INFRASTRUCTURE),
        (Severity.CRITICAL, AlertSource.INDICATORS),
        (Severity.CRITICAL, AlertSource.STOCK),
        (Severity.WARNING, AlertSource.ALL),
        (Severity.WARNING, AlertSource.PERSONNEL),
        (Severity.WARNING, AlertSource.INFRASTRUCTURE),
        (Severity.WARNING, AlertSource.INDICATORS),
        (Severity.WARNING, AlertSource.STOCK),
        (Severity.INFO, AlertSource.ALL),
    ]
    values = {key: cell.value for key, cell in cells.items()}
    assert values == {
        "alert:CRITICAL": 2.0,
        "alert:CRITICAL:personnel": 1.0,
        "alert:CRITICAL:infrastructure": 1.0,
        "alert:CRITICAL:indicators": 0.0,
        "alert:CRITICAL:stock": 0.0,
        "alert:WARNING": 5.0,
        "alert:WARNING:personnel": 4.0,
        "alert:WARNING:infrastructure": 0.0,
        "alert:WARNING:indicators": 1.0,
        "alert:WARNING:stock": 0.0,
        "alert:INFO": 0.0,
    }
    assert cells["alert:WARNING"].total_of == (
        "alert:WARNING:personnel",
        "alert:WARNING:infrastructure",
        "alert:WARNING:indicators",
        "alert:WARNING:stock",
    )
    assert not cells["alert:WARNING:stock"].personnel_derived
    assert cells["alert:WARNING:stock"].total_of == ()
    assert cells["alert:WARNING:personnel"].total_of == (
        "kf:PERSONNEL:expiring:A",
        "kf:PERSONNEL:expiring:B",
        "kf:PERSONNEL:expiring:C",
    )
    assert cells["alert:CRITICAL:personnel"].total_of == (
        "kf:PERSONNEL:expired:A",
        "kf:PERSONNEL:expired:B",
        "kf:PERSONNEL:expired:C",
    )
    assert cells["alert:WARNING:indicators"].total_of == ("indicator:PERS_CERT_VALID:level=B",)
    assert cells["alert:WARNING:personnel"].personnel_derived
    assert not cells["alert:WARNING:infrastructure"].personnel_derived
    assert not cells["alert:INFO"].personnel_derived  # maintenance only (P8-03)
    assert cells["alert:INFO"].total_of == ()


def test_internal_lists_carry_identifiers_and_tags(world: World) -> None:
    document = world.builder.build(AS_OF, ReportVariant.INTERNAL)

    rows = {(r.identifier, r.level) for r in document.retraining}
    assert (IDENTIFIER, PpeLevel.B) in rows
    assert {name for name, level in rows if level is PpeLevel.A} == {
        f"DEMO-S{n:02d}" for n in range(5, 9)
    }
    assert len(document.retraining) == 5
    zebra = next(r for r in document.retraining if r.identifier == IDENTIFIER)
    assert zebra.valid_until == date(2026, 1, 10)

    [asset] = document.overdue_assets
    assert (asset.tag, asset.type_code) == (ASSET_TAG, "DEMO-TYPE-A")
    assert asset.due_on == date(2025, 1, 31)
    assert asset.days_to_due is not None
    assert asset.days_to_due < 0


def test_internal_charts_are_built_from_the_cells_of_the_document(world: World) -> None:
    document = world.builder.build(AS_OF, ReportVariant.INTERNAL)
    by_key = {c.key: c for c in _chart_cells(document)}
    [personnel_chart] = [c for c in document.charts if c.key == "personnel_valid_by_level"]

    assert personnel_chart.categories == ("A", "B", "C")
    assert [c.value for c in personnel_chart.series[0].cells] == [9.0, 2.0, 0.0]
    row = _row(document, "PERS_CERT_VALID", "level=B")
    assert by_key[row.value.key] == row.value
    assert [c.key for c in document.charts] == [
        "personnel_valid_by_level",
        "infrastructure_availability",
        "exercises_by_edition",
        "budget_BRL",
    ]


def test_the_document_is_deterministic(world: World) -> None:
    for variant in ReportVariant:
        assert world.builder.build(AS_OF, variant) == world.builder.build(AS_OF, variant)


# --------------------------------------------------------------------------- demo marker


def test_is_demo_follows_app_meta_in_both_variants(world: World) -> None:
    assert not world.builder.build(AS_OF, ReportVariant.INTERNAL).is_demo
    assert not world.builder.build(AS_OF, ReportVariant.ANONYMISED).is_demo

    app_meta.set_value(world.conn, app_meta.IS_DEMO, "1")

    assert world.builder.build(AS_OF, ReportVariant.INTERNAL).is_demo
    assert world.builder.build(AS_OF, ReportVariant.ANONYMISED).is_demo


# --------------------------------------------------------------------------- anonymised variant


def test_the_internal_model_does_carry_the_fixture_strings(world: World) -> None:
    found = "\n".join(_strings(world.builder.build(AS_OF, ReportVariant.INTERNAL)))
    for text in (IDENTIFIER, ASSET_TAG, INSTITUTION, UNIT, OPERATOR, HANDLING):
        assert text in found


def test_anonymised_variant_contains_none_of_the_fixture_strings(world: World) -> None:
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)

    strings = list(_strings(document))
    assert strings  # the scan sees the document
    for text in strings:
        for forbidden in FORBIDDEN:
            assert forbidden not in text, (forbidden, text)


def test_operator_entered_codes_are_the_only_seeded_text_in_the_anonymised_variant(
    world: World,
) -> None:
    # P8-16 / Q10: asset-type, edition and funding-source codes are printed as entered. Every
    # seeded text carries the prefix DEMO, so once those codes are removed nothing may be left.
    allowed = ("DEMO-TYPE-A", "DEMO-EX-24")
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)

    found = set()
    for text in _strings(document):
        rest = text
        for code in allowed:
            if code in rest:
                found.add(code)
                rest = rest.replace(code, "")
        assert "DEMO" not in rest, text
    assert found == set(allowed)  # the scan does see the codes
    assert "DIRSA" in "\n".join(_strings(document))


def test_anonymised_header_lists_and_notice(world: World) -> None:
    internal = world.builder.build(AS_OF, ReportVariant.INTERNAL)
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)

    assert document.variant is ReportVariant.ANONYMISED
    assert document.header == ReportHeader(
        institution_name="",
        unit_name="",
        as_of=AS_OF,
        generated_at_utc="2026-03-05T12:00:00Z",
        app_version=VERSION,
        operator_label="",
    )
    assert document.handling_notice == ""
    assert document.retraining == ()
    assert document.overdue_assets == ()
    assert document.preliminary_notice_code == "PRELIMINARY"
    assert document.small_count_threshold == 5
    assert [g.module for g in document.key_figures] == [
        Module.PERSONNEL,
        Module.INFRASTRUCTURE,
        Module.EXERCISES,
        Module.BUDGET,
    ]
    assert len(document.indicators) == len(internal.indicators)
    assert [a.cell.key for a in document.alert_summary] == [
        a.cell.key for a in internal.alert_summary
    ]


def test_zero_and_small_personnel_counts_are_suppressed_including_the_zero(
    world: World,
) -> None:
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)
    people = Module.PERSONNEL

    _hidden(_figure(document, people, "valid:C"))  # zero
    _hidden(_figure(document, people, "expiring:B"))  # zero
    _hidden(_figure(document, people, "valid:B"))  # 2
    _hidden(_figure(document, people, "retraining:B"))  # 1
    _hidden(_figure(document, people, "expiring:A"))  # 4
    _hidden(_figure(document, people, "degree_completed:doctorate"))  # 2
    _hidden(_row(document, "PERS_CERT_VALID", "level=C").value)
    _hidden(_row(document, "PERS_DEGREE", "level=master;status=in_progress").value)  # zero
    _shown(_figure(document, people, "valid:A"), 9.0)
    _shown(_figure(document, people, "active_staff"), 9.0)
    _shown(_figure(document, people, "degree_completed:master"), 6.0)


def test_a_count_equal_to_the_threshold_is_shown(world: World) -> None:
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)

    _shown(_row(document, "PERS_TRAINING_12M").value, 5.0)


def test_alert_counts_are_suppressed_with_hand_computed_expectations(world: World) -> None:
    # values: see test_internal_alert_summary_is_split_by_source_with_hand_computed_values
    cells = _alerts(world.builder.build(AS_OF, ReportVariant.ANONYMISED))

    for key in (
        "alert:WARNING",  # a part is hidden
        "alert:WARNING:personnel",  # 4 < 5
        "alert:WARNING:indicators",  # its row PERS_CERT_VALID level B (2) is hidden
        "alert:CRITICAL",
        "alert:CRITICAL:personnel",  # 1 < 5
        "alert:CRITICAL:indicators",
    ):
        _hidden(cells[key])
    _shown(cells["alert:WARNING:infrastructure"], 0.0)
    _shown(cells["alert:CRITICAL:infrastructure"], 1.0)
    _shown(cells["alert:INFO"], 0.0)  # maintenance only: never suppressed (P8-03)


def test_suppressed_rows_lose_status_and_thresholds(world: World) -> None:
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)

    valid_b = _row(document, "PERS_CERT_VALID", "level=B")  # 2, warning 3 / critical 1
    assert valid_b.status is IndicatorStatus.NO_DATA
    assert (valid_b.warning_value, valid_b.critical_value) == (None, None)


def test_suppression_does_not_touch_infrastructure_exercise_or_budget_figures(
    world: World,
) -> None:
    internal = world.builder.build(AS_OF, ReportVariant.INTERNAL)
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)

    _shown(_row(document, "INFRA_AVAILABLE", "type=DEMO-TYPE-A").value, 2.0)
    _shown(_row(document, "INFRA_AVAILABLE", "type=bay").value, 0.0)
    _shown(_row(document, "INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A").value, 1.0)
    _shown(_row(document, "EX_LAST_PARTICIPANTS", "kind=CBRAMED").value, 3.0)
    _shown(_row(document, "EX_LAST_COUNTRIES", "kind=CBRAMED").value, 2.0)
    _shown(_figure(document, Module.INFRASTRUCTURE, "overdue"), 1.0)
    _shown(_figure(document, Module.INFRASTRUCTURE, "due_soon"), 0.0)
    _shown(_figure(document, Module.EXERCISES, "last_participants"), 3.0)
    _shown(_figure(document, Module.BUDGET, "allocated:BRL"), 1000.0)
    _shown(_figure(document, Module.BUDGET, "executed:BRL"), 250.0)
    internal_rows = {(r.code, r.dimension): r for r in internal.indicators}
    for row in document.indicators:
        if not row.value.personnel_derived:
            assert row == internal_rows[row.code, row.dimension]


def test_secondary_suppression_hides_the_total_when_one_part_is_suppressed(
    world: World,
) -> None:
    # completed degrees: doctorate 2 (suppressed), master 6, specialisation 7; total 15
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)
    people = Module.PERSONNEL

    _hidden(_figure(document, people, "degree_completed:doctorate"))
    _shown(_figure(document, people, "degree_completed:master"), 6.0)
    _shown(_figure(document, people, "degree_completed:specialisation"), 7.0)
    _hidden(_figure(document, people, "degree_completed_total"))


def test_a_total_with_no_suppressed_part_is_shown(world: World) -> None:
    for n in range(3, 7):  # doctorate 2 -> 6
        world.personnel.add_degree(
            world.staff[f"DEMO-S{n:02d}"], DegreeInput("doctorate", "completed")
        )
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)
    people = Module.PERSONNEL

    _shown(_figure(document, people, "degree_completed:doctorate"), 6.0)
    _shown(_figure(document, people, "degree_completed:master"), 6.0)
    _shown(_figure(document, people, "degree_completed:specialisation"), 7.0)
    _shown(_figure(document, people, "degree_completed_total"), 19.0)


def test_the_threshold_comes_from_the_configuration(world: World) -> None:
    people = Module.PERSONNEL
    before = world.builder.build(AS_OF, ReportVariant.ANONYMISED)
    _hidden(_figure(before, people, "expiring:A"))  # 4 < 5
    _hidden(_figure(before, people, "retraining:A"))

    world.config.save(dataclasses.replace(world.config.load(), small_count_threshold=3))
    after = world.builder.build(AS_OF, ReportVariant.ANONYMISED)

    assert after.small_count_threshold == 3
    _shown(_figure(after, people, "expiring:A"), 4.0)  # 3 <= 4
    # retraining = expiring + expired: nobody of level A is expired (0 < 3, hidden), so showing
    # the 4 would give that zero away; the total goes with its hidden part.
    _hidden(_figure(after, people, "expired:A"))
    _hidden(_figure(after, people, "retraining:A"))
    _hidden(_figure(after, people, "valid:B"))  # 2 < 3
    _hidden(_figure(after, people, "valid:C"))  # zero is always below the threshold
    # the institution names are still blanked, whatever the threshold
    assert after.header.institution_name == ""


def test_charts_of_the_anonymised_variant_hold_no_suppressed_cell(world: World) -> None:
    internal = world.builder.build(AS_OF, ReportVariant.INTERNAL)
    document = world.builder.build(AS_OF, ReportVariant.ANONYMISED)

    [chart] = [c for c in document.charts if c.key == "personnel_valid_by_level"]
    assert chart.categories == ("A",)  # B (2) and C (0) are suppressed: no category, no value
    assert [c.value for c in chart.series[0].cells] == [9.0]
    assert all(not c.suppressed for c in _chart_cells(document))
    chart_text = "\n".join(_strings(document.charts))
    assert "level=B" not in chart_text
    assert "level=C" not in chart_text
    # the other charts are the internal ones, unchanged
    for key in ("infrastructure_availability", "exercises_by_edition", "budget_BRL"):
        assert next(c for c in document.charts if c.key == key) == next(
            c for c in internal.charts if c.key == key
        )
    # the chart cells are the suppressed document cells (same keys, same state)
    shown = {c.key: c for c in _chart_cells(document)}
    row = _row(document, "PERS_CERT_VALID", "level=A")
    assert shown[row.value.key] == row.value


def test_anonymise_does_not_mutate_its_input_and_is_idempotent(world: World) -> None:
    internal = world.builder.build(AS_OF, ReportVariant.INTERNAL)
    snapshot = copy.deepcopy(internal)

    once = anonymise(internal)

    assert internal == snapshot
    assert internal.retraining and internal.header.institution_name == INSTITUTION
    assert once is not internal
    assert anonymise(once) == once


# --------------------------------------------------------------------------- the rules alone


def _synthetic(*cells: Cell, threshold: int = 5) -> ReportDocument:
    return ReportDocument(
        variant=ReportVariant.INTERNAL,
        header=ReportHeader(INSTITUTION, UNIT, AS_OF, "2026-03-05T12:00:00Z", VERSION, OPERATOR),
        handling_notice=HANDLING,
        is_demo=False,
        small_count_threshold=threshold,
        key_figures=(KeyFigureGroup(Module.PERSONNEL, cells),),
        indicators=(),
        alert_summary=(),
        charts=(),
        retraining=(),
        overdue_assets=(),
    )


def _p(key: str, value: float | None, total_of: tuple[str, ...] = ()) -> Cell:
    return Cell(key=key, value=value, personnel_derived=True, total_of=total_of)


def _anonymised(*cells: Cell, threshold: int = 5) -> dict[str, Cell]:
    document = anonymise(_synthetic(*cells, threshold=threshold))
    return {c.key: c for c in document.key_figures[0].cells}


def test_primary_rule_boundaries() -> None:
    state = _anonymised(
        _p("zero", 0.0),
        _p("four", 4.0),
        _p("five", 5.0),
        _p("none", None),
        Cell(key="other_zero", value=0.0),
        Cell(key="other_two", value=2.0),
        Cell(key="amount", value=2.0, personnel_derived=True, is_count=False),
    )

    _hidden(state["zero"])
    _hidden(state["four"])
    _shown(state["five"], 5.0)
    assert (state["none"].value, state["none"].suppressed) == (None, False)
    _shown(state["other_zero"], 0.0)  # not personnel-derived: never suppressed
    _shown(state["other_two"], 2.0)
    _shown(state["amount"], 2.0)  # not a count


def test_secondary_rule_one_suppressed_part_hides_the_total() -> None:
    parts = ("a", "b", "c")
    state = _anonymised(_p("a", 6.0), _p("b", 7.0), _p("c", 2.0), _p("t", 15.0, parts))

    _shown(state["a"], 6.0)
    _shown(state["b"], 7.0)
    _hidden(state["c"])
    _hidden(state["t"])  # 15 - 6 - 7 would reveal c


def test_secondary_rule_a_total_without_suppressed_part_is_shown() -> None:
    state = _anonymised(_p("a", 6.0), _p("b", 7.0), _p("c", 9.0), _p("t", 22.0, ("a", "b", "c")))

    for key, value in {"a": 6.0, "b": 7.0, "c": 9.0, "t": 22.0}.items():
        _shown(state[key], value)


def test_secondary_rule_two_suppressed_parts_also_hide_a_shown_total() -> None:
    # t - a would reveal b + c = 3 (and a sum of 0 would fix both): the total goes too
    state = _anonymised(_p("a", 6.0), _p("b", 2.0), _p("c", 1.0), _p("t", 9.0, ("a", "b", "c")))

    _shown(state["a"], 6.0)
    _hidden(state["b"])
    _hidden(state["c"])
    _hidden(state["t"])


def test_secondary_rule_a_total_suppressed_with_all_its_parts_is_consistent() -> None:
    state = _anonymised(_p("a", 1.0), _p("b", 2.0), _p("t", 3.0, ("a", "b")))

    for key in ("a", "b", "t"):
        _hidden(state[key])


def test_secondary_rule_runs_to_a_fixed_point_whatever_the_order() -> None:
    # g is listed before t1, and t1 is only suppressed by the secondary rule
    state = _anonymised(
        _p("g", 18.0, ("t1", "t3")),
        _p("t1", 8.0, ("p1", "p2")),
        _p("t3", 10.0),
        _p("p1", 2.0),
        _p("p2", 6.0),
    )

    _hidden(state["p1"])
    _hidden(state["t1"])
    _hidden(state["g"])
    _shown(state["p2"], 6.0)
    _shown(state["t3"], 10.0)


def test_secondary_rule_covers_totals_that_are_not_personnel_derived() -> None:
    state = _anonymised(
        _p("a", 1.0),
        Cell(key="b", value=20.0),
        Cell(key="t", value=21.0, total_of=("a", "b")),
    )

    _hidden(state["a"])
    _shown(state["b"], 20.0)
    _hidden(state["t"])
