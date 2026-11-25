# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the indicator service: evaluation and targets (PLAN.md T6.1, D13, D14, P03, P08).

All data is fictitious and is created through the module services.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import indicators as rules
from cbrn_dashboard.domain import personnel as personnel_rules
from cbrn_dashboard.domain.indicators import (
    IndicatorReading,
    IndicatorStatus,
    IndicatorValue,
    UnknownIndicatorError,
)
from cbrn_dashboard.domain.infrastructure import AssetStatus
from cbrn_dashboard.domain.registry import build_registry
from cbrn_dashboard.services.budget import BudgetService, EntryInput
from cbrn_dashboard.services.errors import NOT_FOUND, READ_ONLY, ServiceError
from cbrn_dashboard.services.exercises import EditionInput, ExercisesService
from cbrn_dashboard.services.indicators import (
    INVALID_DIMENSION,
    INVALID_NUMBER,
    MAX_RATIO_TARGET,
    TARGET_EMPTY,
    TARGET_NOT_FINITE,
    TARGET_ORDER,
    TARGET_OUT_OF_RANGE,
    UNKNOWN_INDICATOR,
    IndicatorService,
)
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
from cbrn_dashboard.storage import targets_repo
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.repository import WriteContext
from cbrn_dashboard.storage.settings_repo import load_config, save_config
from tests.services.conftest import ChangeLogRows

AS_OF = date(2026, 3, 5)
OPERATOR = "op-demo"
CERT_A = "PERS_CERT_VALID"
LEVEL_A = "level=A"
LEVEL_B = "level=B"
MAINT = "INFRA_MAINT_OVERDUE"
TYPE_DIM = "type=DEMO-TYPE"
TRAINING = "PERS_TRAINING_12M"
DAYS_SINCE = "EX_DAYS_SINCE_LAST"
DAYS_DIM = "kind=CBRAMED"
BUDGET = "BUD_EXEC_RATE"
BUDGET_DIM = "currency=BRL;source=DIRSA"


@dataclass
class Stack:
    """The four module services and the indicator service over one connection."""

    personnel: PersonnelService
    infrastructure: InfrastructureService
    exercises: ExercisesService
    budget: BudgetService
    indicators: IndicatorService


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
    return Stack(personnel, infrastructure, exercises, budget, indicators)


def _seed(stack: Stack, conn: DatabaseConnection) -> None:
    people = stack.personnel
    first = people.create_staff(StaffInput("DEMO-P001", "2020-01-01"))
    second = people.create_staff(StaffInput("DEMO-P002", "2020-01-01"))
    third = people.create_staff(StaffInput("DEMO-P003", "2021-01-01"))
    people.add_certificate(first, CertificateInput("A", "2025-01-10", "2027-01-10"))
    people.add_certificate(second, CertificateInput("A", "2025-02-10", "2027-02-10"))
    people.add_certificate(second, CertificateInput("B", "2025-02-10", "2027-02-10"))
    people.add_certificate(third, CertificateInput("A", "2024-03-20", "2026-03-20"))
    course = people.create_course(CourseInput("DEMO-C1", "Curso Demo"))
    people.add_training(first, TrainingInput(course, "2026-01-10", 8))

    infra = stack.infrastructure
    type_id = infra.create_type(AssetTypeInput("DEMO-TYPE", "Tipo demo"))
    for tag in ("DEMO-A001", "DEMO-A002", "DEMO-A003"):
        asset = infra.create_asset(
            AssetInput(tag=tag, type_id=type_id, in_service_from="2025-01-01"),
            AssetStatus.OPERATIONAL,
        )
        if tag == "DEMO-A002":
            infra.change_status(asset, "2026-01-10", AssetStatus.DEGRADED)
        if tag == "DEMO-A003":
            infra.change_status(asset, "2026-01-10", AssetStatus.OUT_OF_SERVICE)

    stack.exercises.create_edition(
        EditionInput(
            code="DEMO-EX-01",
            kind="CBRAMED",
            start_on="2024-03-01",
            end_on="2024-03-05",
            participants=40,
            countries=("BR", "AR", "PT"),
        )
    )

    source = conn.execute("SELECT id FROM funding_source WHERE code = 'DIRSA'").fetchone()
    entry = stack.budget.create_entry(
        EntryInput(
            fiscal_year=2026, source_id=int(source[0]), allocated_minor=100_000, currency="BRL"
        )
    )
    stack.budget.add_execution(entry, "2026-01-10", 50_000)


@pytest.fixture
def bare(db: DatabaseConnection, clock: FixedClock) -> Stack:
    """The services over a fresh database with no records at all."""
    return _stack(db, clock)


@pytest.fixture
def stack(bare: Stack, db: DatabaseConnection) -> Stack:
    """The services over a database with the small fictitious dataset."""
    _seed(bare, db)
    return bare


# --------------------------------------------------------------------------- helpers


def _reading(readings: list[IndicatorReading], code: str, dimension: str = "") -> IndicatorReading:
    for reading in readings:
        if (reading.code, reading.dimension) == (code, dimension):
            return reading
    raise AssertionError((code, dimension))


def _all_values(stack: Stack, as_of: date) -> list[IndicatorValue]:
    return [
        *stack.personnel.indicator_values(as_of),
        *stack.infrastructure.indicator_values(as_of),
        *stack.exercises.indicator_values(as_of),
        *stack.budget.indicator_values(as_of),
    ]


def _status(stack: Stack, code: str, dimension: str, as_of: date = AS_OF) -> IndicatorStatus:
    return _reading(stack.indicators.evaluate(as_of), code, dimension).status


def _value(stack: Stack, code: str, dimension: str, as_of: date = AS_OF) -> int:
    value = _reading(stack.indicators.evaluate(as_of), code, dimension).value
    assert value is not None
    return int(value)


def _state(db: DatabaseConnection) -> tuple[list[tuple[object, ...]], int]:
    rows = [tuple(r) for r in db.execute("SELECT * FROM indicator_target ORDER BY 1, 2")]
    log = int(db.execute("SELECT count(*) FROM change_log").fetchone()[0])
    return rows, log


def _refused(
    db: DatabaseConnection, call: Callable[[], object], code: str, field: str | None = None
) -> None:
    before = _state(db)
    with pytest.raises(ServiceError) as info:
        call()
    assert info.value.code == code
    if field is not None:
        assert info.value.field == field
    assert _state(db) == before


def _target_log(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [row for row in rows if row["entity"] == "indicator_target"]


# --------------------------------------------------------------------------- evaluation


def test_evaluate_returns_every_reading_in_registry_order(stack: Stack) -> None:
    readings = stack.indicators.evaluate(AS_OF)
    produced = {(v.code, v.dimension) for v in _all_values(stack, AS_OF)}
    assert {(r.code, r.dimension) for r in readings} == produced
    assert len(readings) == len(produced)

    registry = build_registry()
    order = {code: index for index, code in enumerate(registry.codes())}
    keys = [(order[r.code], r.dimension) for r in readings]
    assert keys == sorted(keys)
    # the four modules appear in the order personnel, infrastructure, exercises, budget
    modules = [registry.get(r.code).module for r in readings]
    assert modules == sorted(modules, key=list(rules.Module).index)
    codes = {r.code for r in readings}
    assert codes >= {CERT_A, "INFRA_AVAILABLE", "EX_LAST_PARTICIPANTS", BUDGET}


def test_evaluate_equals_the_domain_evaluation_of_the_module_values(stack: Stack) -> None:
    registry = build_registry()
    plain = rules.evaluate_all(registry, _all_values(stack, AS_OF), {})
    assert stack.indicators.evaluate(AS_OF) == plain

    # with targets, the readings are the hand-worked ones of test_evaluate_gives_the_hand_worked_...


# (as of, valid level A, status, budget thresholds in force, budget status), worked by hand: the
# certificate of DEMO-P003 ends on 2026-03-20; the 50 000 of 100 000 BRL were executed on
# 2026-01-10, so the rate is 0.5 on all three dates; the year-end targets 0.9 / 0.6 are scaled by
# the day of the year / 365: 15/365, 64/365 and 349/365.
HAND_WORKED: list[tuple[date, int, IndicatorStatus, tuple[float, float], IndicatorStatus]] = [
    (
        date(2026, 1, 15),
        3,
        IndicatorStatus.OK,
        (0.0369863013698630, 0.0246575342465753),
        IndicatorStatus.OK,
    ),
    (
        date(2026, 3, 5),
        3,
        IndicatorStatus.OK,
        (0.157808219178082, 0.105205479452055),
        IndicatorStatus.OK,
    ),
    (
        date(2026, 12, 15),
        2,
        IndicatorStatus.WARNING,
        (0.860547945205479, 0.573698630136986),
        IndicatorStatus.CRITICAL,
    ),
]


@pytest.mark.parametrize(
    ("as_of", "valid", "valid_status", "thresholds", "rate_status"), HAND_WORKED
)
def test_evaluate_gives_the_hand_worked_readings(
    stack: Stack,
    as_of: date,
    valid: int,
    valid_status: IndicatorStatus,
    thresholds: tuple[float, float],
    rate_status: IndicatorStatus,
) -> None:
    """P6-12: literal expectations, not a second run of the code under test."""
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=2, critical_value=1)
    stack.indicators.set_target(BUDGET, BUDGET_DIM, warning_value=0.9, critical_value=0.6)

    readings = stack.indicators.evaluate(as_of)

    level_a = _reading(readings, CERT_A, LEVEL_A)
    assert (level_a.value, level_a.status) == (valid, valid_status)
    assert (level_a.warning_value, level_a.critical_value) == (2, 1)
    rate = _reading(readings, BUDGET, BUDGET_DIM)
    assert rate.value == pytest.approx(0.5)
    assert rate.status is rate_status
    assert rate.warning_value == pytest.approx(thresholds[0], rel=1e-9)
    assert rate.critical_value == pytest.approx(thresholds[1], rel=1e-9)


def test_fresh_database_has_no_target_and_nothing_else_but_no_data(stack: Stack) -> None:
    assert stack.indicators.list_targets() == []
    readings = stack.indicators.evaluate(AS_OF)
    assert readings
    for reading in readings:
        assert reading.status in {IndicatorStatus.NO_TARGET, IndicatorStatus.NO_DATA}
        assert reading.warning_value is None
        assert reading.critical_value is None
    assert any(r.status is IndicatorStatus.NO_TARGET for r in readings)


def test_empty_database_has_no_budget_reading(bare: Stack) -> None:
    grouped = bare.indicators.readings_by_code(AS_OF)
    assert BUDGET not in grouped  # no budget group this year, so no reading (not an error)
    allowed = {IndicatorStatus.NO_TARGET, IndicatorStatus.NO_DATA}
    for readings in grouped.values():
        assert all(r.status in allowed for r in readings)


def test_readings_by_code_groups_in_registry_order(stack: Stack) -> None:
    grouped = stack.indicators.readings_by_code(AS_OF)
    flat = [r for readings in grouped.values() for r in readings]
    assert flat == stack.indicators.evaluate(AS_OF)
    assert all(r.code == code for code, readings in grouped.items() for r in readings)


def test_a_value_of_an_unregistered_code_is_never_dropped(
    stack: Stack, db: DatabaseConnection, clock: FixedClock
) -> None:
    only_personnel = build_registry(providers=[personnel_rules.indicator_definitions])
    service = IndicatorService(
        db,
        clock,
        personnel=stack.personnel,
        infrastructure=stack.infrastructure,
        exercises=stack.exercises,
        budget=stack.budget,
        registry=only_personnel,
    )
    with pytest.raises(UnknownIndicatorError):
        service.evaluate(AS_OF)


def test_definitions_and_definition(stack: Stack) -> None:
    registry = build_registry()
    assert [d.code for d in stack.indicators.definitions()] == list(registry.codes())
    assert stack.indicators.definition(CERT_A) == registry.get(CERT_A)
    with pytest.raises(ServiceError) as info:
        stack.indicators.definition("NOPE")
    assert info.value.code == UNKNOWN_INDICATOR


def test_known_dimensions_lists_the_dimensions_with_a_value(stack: Stack) -> None:
    known = stack.indicators.known_dimensions(AS_OF)
    registry = build_registry()
    assert list(known) == list(registry.codes())
    expected: dict[str, set[str]] = {code: set() for code in registry.codes()}
    for value in _all_values(stack, AS_OF):
        expected[value.code].add(value.dimension)
    assert {code: set(dims) for code, dims in known.items()} == expected
    for dims in known.values():
        assert dims == sorted(dims)
    assert known[TRAINING] == [""]
    assert known[BUDGET] == [BUDGET_DIM]
    assert LEVEL_A in known[CERT_A]
    assert TYPE_DIM in known[MAINT]


def test_known_dimensions_of_an_empty_database(bare: Stack) -> None:
    known = bare.indicators.known_dimensions(AS_OF)
    assert known[BUDGET] == []
    assert set(known) == set(build_registry().codes())


def test_a_past_date_gives_the_readings_of_that_date(stack: Stack) -> None:
    before_execution = date(2026, 1, 5)  # the execution row is dated 2026-01-10
    early = _reading(stack.indicators.evaluate(before_execution), BUDGET, BUDGET_DIM).value
    late = _reading(stack.indicators.evaluate(AS_OF), BUDGET, BUDGET_DIM).value
    assert early == pytest.approx(0.0)
    assert late == pytest.approx(0.5)

    days_early = _reading(stack.indicators.evaluate(date(2025, 3, 5)), DAYS_SINCE, DAYS_DIM).value
    days_late = _reading(stack.indicators.evaluate(AS_OF), DAYS_SINCE, DAYS_DIM).value
    assert days_early is not None
    assert days_late is not None
    assert days_late - days_early == 365


# --------------------------------------------------------------------------- unreadable settings


@pytest.mark.parametrize(
    "key",
    ["config.cert_warning_days", "config.maintenance_warning_days"],
)
def test_an_unreadable_setting_is_a_service_error_not_a_raw_config_error(
    stack: Stack, db: DatabaseConnection, key: str
) -> None:
    """P6-01: the personnel and infrastructure services let a raw ConfigError escape."""
    db.execute("INSERT INTO setting (key, value_json) VALUES (?, ?)", (key, "not json"))

    with pytest.raises(ServiceError) as info:
        stack.indicators.evaluate(AS_OF)

    assert info.value.code == "CORRUPT_SETTING"


# --------------------------------------------------------------------------- ratio targets


def test_a_ratio_target_outside_the_bounds_is_refused_with_a_coded_error(
    stack: Stack, db: DatabaseConnection
) -> None:
    """P6-02: "90" typed for 90 % used to be stored as 9000 %, making every reading Critical."""
    service = stack.indicators

    def put(warning: float, critical: float) -> Callable[[], object]:
        return lambda: service.set_target(
            BUDGET, BUDGET_DIM, warning_value=warning, critical_value=critical
        )

    _refused(db, put(90.0, 60.0), TARGET_OUT_OF_RANGE, "warning_value")
    _refused(db, put(10.5, 0.6), TARGET_OUT_OF_RANGE, "warning_value")
    _refused(db, put(0.9, -0.1), TARGET_OUT_OF_RANGE, "critical_value")
    assert service.list_targets() == []

    service.set_target(BUDGET, BUDGET_DIM, warning_value=10.0, critical_value=0.0)  # the bounds

    [view] = service.list_targets()
    assert (view.warning_value, view.critical_value) == (10.0, 0.0)
    assert MAX_RATIO_TARGET == 10.0


def test_the_bound_is_for_ratio_indicators_only(stack: Stack) -> None:
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=90.0, critical_value=60.0)

    [view] = stack.indicators.list_targets()
    assert (view.warning_value, view.critical_value) == (90.0, 60.0)


# --------------------------------------------------------------------------- change flags


def test_set_target_reports_whether_it_changed_and_writes_only_the_target(
    stack: Stack, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    before = len(change_log_rows(db))

    changed = stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=2, critical_value=1)
    again = stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=2, critical_value=1)

    assert (changed, again) == (True, False)
    entities = [row["entity"] for row in change_log_rows(db)[before:]]
    assert entities == ["indicator_target"]


def test_switching_a_target_reports_whether_it_changed(stack: Stack) -> None:
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=2, critical_value=1)

    assert stack.indicators.set_target_enabled(CERT_A, LEVEL_A, False) is True
    assert stack.indicators.set_target_enabled(CERT_A, LEVEL_A, False) is False


# --------------------------------------------------------------------------- targets: round trip


def test_targets_round_trip_and_drive_the_status(stack: Stack) -> None:
    service = stack.indicators
    v = _value(stack, CERT_A, LEVEL_A)
    assert v >= 2

    service.set_target(CERT_A, LEVEL_A, warning_value=v, critical_value=v - 1)
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.WARNING

    service.set_target(CERT_A, LEVEL_A, warning_value=v + 1, critical_value=v)
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.CRITICAL

    service.set_target(CERT_A, LEVEL_A, warning_value=v - 1, critical_value=v - 2)
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.OK

    [view] = service.list_targets()
    assert (view.indicator_code, view.dimension) == (CERT_A, LEVEL_A)
    assert (view.warning_value, view.critical_value, view.enabled) == (v - 1, v - 2, True)
    assert service.get_target(CERT_A, LEVEL_A) == view

    reading = _reading(service.evaluate(AS_OF), CERT_A, LEVEL_A)
    assert (reading.warning_value, reading.critical_value) == (v - 1, v - 2)


def test_lower_is_better_targets_drive_the_status(stack: Stack) -> None:
    assert build_registry().get(DAYS_SINCE).direction is rules.Direction.LOWER_IS_BETTER
    v = _value(stack, DAYS_SINCE, DAYS_DIM)
    service = stack.indicators
    service.set_target(DAYS_SINCE, DAYS_DIM, warning_value=v, critical_value=v + 1)
    assert _status(stack, DAYS_SINCE, DAYS_DIM) is IndicatorStatus.WARNING
    service.set_target(DAYS_SINCE, DAYS_DIM, warning_value=v - 1, critical_value=v)
    assert _status(stack, DAYS_SINCE, DAYS_DIM) is IndicatorStatus.CRITICAL
    service.set_target(DAYS_SINCE, DAYS_DIM, warning_value=v + 1, critical_value=v + 2)
    assert _status(stack, DAYS_SINCE, DAYS_DIM) is IndicatorStatus.OK


def test_a_target_with_only_one_threshold_is_accepted(stack: Stack) -> None:
    v = _value(stack, CERT_A, LEVEL_A)
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=None, critical_value=v)
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.CRITICAL
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=v, critical_value=None)
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.WARNING
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=v, critical_value=v)  # equal is ok
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.CRITICAL


def test_an_indicator_without_dimension_takes_the_empty_dimension(stack: Stack) -> None:
    v = _value(stack, TRAINING, "")
    stack.indicators.set_target(TRAINING, "", warning_value=v, critical_value=None)
    assert _status(stack, TRAINING, "") is IndicatorStatus.WARNING


def test_integers_are_stored_as_floats(stack: Stack, db: DatabaseConnection) -> None:
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=5, critical_value=2)
    row = db.execute(
        "SELECT typeof(warning_value), typeof(critical_value) FROM indicator_target"
    ).fetchone()
    assert tuple(row) == ("real", "real")


def test_list_targets_is_in_registry_order_then_dimension(stack: Stack) -> None:
    service = stack.indicators
    service.set_target(MAINT, TYPE_DIM, warning_value=1, critical_value=2)
    service.set_target(CERT_A, LEVEL_B, warning_value=3, critical_value=1)
    service.set_target(CERT_A, LEVEL_A, warning_value=3, critical_value=1)
    keys = [(t.indicator_code, t.dimension) for t in service.list_targets()]
    assert keys == [(CERT_A, LEVEL_A), (CERT_A, LEVEL_B), (MAINT, TYPE_DIM)]


def test_a_stale_target_of_an_unregistered_code_can_be_listed_and_deleted(
    stack: Stack, db: DatabaseConnection, clock: FixedClock
) -> None:
    targets_repo.upsert_target(WriteContext(db, clock, OPERATOR), "OLD_CODE", "", 1.0, None, True)
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=3, critical_value=1)
    assert [t.indicator_code for t in stack.indicators.list_targets()] == [CERT_A, "OLD_CODE"]
    stack.indicators.set_target_enabled("OLD_CODE", "", False)
    stack.indicators.delete_target("OLD_CODE", "")
    assert [t.indicator_code for t in stack.indicators.list_targets()] == [CERT_A]
    # a stale target does not break the evaluation
    assert stack.indicators.evaluate(AS_OF)


def test_targets_are_keyed_by_code_and_dimension(stack: Stack) -> None:
    v = _value(stack, CERT_A, LEVEL_A)
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=v, critical_value=v - 1)
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.WARNING
    other = _reading(stack.indicators.evaluate(AS_OF), CERT_A, LEVEL_B)
    assert other.status in {IndicatorStatus.NO_TARGET, IndicatorStatus.NO_DATA}
    assert other.warning_value is None
    assert other.status is not IndicatorStatus.WARNING


# --------------------------------------------------------------------------- change log


def test_every_change_writes_a_log_row_with_the_natural_key(
    stack: Stack, db: DatabaseConnection, change_log_rows: ChangeLogRows
) -> None:
    service = stack.indicators
    base = len(_target_log(change_log_rows(db)))
    assert base == 0

    assert service.set_target(CERT_A, LEVEL_A, warning_value=3, critical_value=1) is True
    assert service.set_target(CERT_A, LEVEL_A, warning_value=4, critical_value=1) is True
    assert service.set_target_enabled(CERT_A, LEVEL_A, False) is True
    assert service.set_target_enabled(CERT_A, LEVEL_A, True) is True
    service.delete_target(CERT_A, LEVEL_A)

    rows = _target_log(change_log_rows(db))
    assert [row["action"] for row in rows] == ["insert", "update", "update", "update", "delete"]
    for row in rows:
        assert row["entity_id"] is None
        assert json.loads(str(row["entity_key"])) == {
            "dimension": LEVEL_A,
            "indicator_code": CERT_A,
        }
        assert row["operator"] == OPERATOR
        assert row["at_utc"] == "2026-03-05T12:00:00Z"
    assert json.loads(str(rows[0]["after_json"]))["warning_value"] == 3.0
    assert json.loads(str(rows[1]["before_json"]))["warning_value"] == 3.0
    assert json.loads(str(rows[1]["after_json"]))["warning_value"] == 4.0
    assert json.loads(str(rows[2]["after_json"]))["enabled"] == 0
    assert json.loads(str(rows[3]["after_json"]))["enabled"] == 1
    assert json.loads(str(rows[4]["before_json"]))["critical_value"] == 1.0
    assert rows[4]["after_json"] is None


def test_a_change_that_changes_nothing_writes_nothing(stack: Stack, db: DatabaseConnection) -> None:
    service = stack.indicators
    service.set_target(CERT_A, LEVEL_A, warning_value=3, critical_value=1)
    before = _state(db)
    assert service.set_target(CERT_A, LEVEL_A, warning_value=3, critical_value=1) is False
    assert service.set_target(CERT_A, LEVEL_A, warning_value=3.0, critical_value=1.0) is False
    assert service.set_target_enabled(CERT_A, LEVEL_A, True) is False
    assert _state(db) == before


def test_evaluating_writes_nothing(stack: Stack, db: DatabaseConnection) -> None:
    before = _state(db)
    stack.indicators.evaluate(AS_OF)
    stack.indicators.known_dimensions(AS_OF)
    assert _state(db) == before


# --------------------------------------------------------------------------- order


def test_higher_is_better_needs_critical_not_above_warning(
    stack: Stack, db: DatabaseConnection
) -> None:
    _refused(
        db,
        lambda: stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=2, critical_value=5),
        TARGET_ORDER,
    )
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=5, critical_value=2)
    _refused(
        db,
        lambda: stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=1, critical_value=2),
        TARGET_ORDER,
    )
    assert [(t.warning_value, t.critical_value) for t in stack.indicators.list_targets()] == [
        (5.0, 2.0)
    ]


def test_lower_is_better_needs_warning_not_above_critical(
    stack: Stack, db: DatabaseConnection
) -> None:
    _refused(
        db,
        lambda: stack.indicators.set_target(MAINT, TYPE_DIM, warning_value=5, critical_value=2),
        TARGET_ORDER,
    )
    stack.indicators.set_target(MAINT, TYPE_DIM, warning_value=2, critical_value=5)
    assert stack.indicators.get_target(MAINT, TYPE_DIM).critical_value == 5.0


# --------------------------------------------------------------------------- enabled switch


def test_a_disabled_target_behaves_as_if_absent(stack: Stack) -> None:
    service = stack.indicators
    v = _value(stack, CERT_A, LEVEL_A)
    service.set_target(CERT_A, LEVEL_A, warning_value=v, critical_value=v - 1)
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.WARNING

    service.set_target_enabled(CERT_A, LEVEL_A, False)
    reading = _reading(service.evaluate(AS_OF), CERT_A, LEVEL_A)
    assert reading.status is IndicatorStatus.NO_TARGET
    assert (reading.warning_value, reading.critical_value) == (None, None)
    assert service.get_target(CERT_A, LEVEL_A).enabled is False  # kept, only switched off

    service.set_target_enabled(CERT_A, LEVEL_A, True)
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.WARNING


def test_a_target_can_be_created_disabled(stack: Stack) -> None:
    v = _value(stack, CERT_A, LEVEL_A)
    service = stack.indicators
    service.set_target(CERT_A, LEVEL_A, warning_value=v, critical_value=None, enabled=False)
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.NO_TARGET


def test_a_deleted_target_is_gone(stack: Stack) -> None:
    v = _value(stack, CERT_A, LEVEL_A)
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=v, critical_value=None)
    stack.indicators.delete_target(CERT_A, LEVEL_A)
    assert stack.indicators.list_targets() == []
    assert _status(stack, CERT_A, LEVEL_A) is IndicatorStatus.NO_TARGET


# --------------------------------------------------------------------------- refusals


def test_unknown_indicator(stack: Stack, db: DatabaseConnection) -> None:
    _refused(
        db,
        lambda: stack.indicators.set_target("NOPE", "", warning_value=1, critical_value=None),
        UNKNOWN_INDICATOR,
        "indicator_code",
    )


@pytest.mark.parametrize(
    ("code", "dimension"),
    [
        (CERT_A, "kind=CBRAMED"),  # wrong key
        (CERT_A, "level=A;status=completed"),  # one key too many
        (CERT_A, "level"),  # undecodable
        (CERT_A, "level=A;"),  # undecodable
        (CERT_A, "level=A;level=B"),  # duplicate key
        (CERT_A, ""),  # '' only for an indicator without dimension keys
        (TRAINING, LEVEL_A),  # this indicator has no dimension
        ("PERS_DEGREE", "status=completed;level=A"),  # keys not in the canonical (sorted) order
        (BUDGET, "source=DIRSA"),  # one key missing
    ],
)
def test_invalid_dimension(stack: Stack, db: DatabaseConnection, code: str, dimension: str) -> None:
    _refused(
        db,
        lambda: stack.indicators.set_target(code, dimension, warning_value=1, critical_value=None),
        INVALID_DIMENSION,
        "dimension",
    )


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_target_not_finite(stack: Stack, db: DatabaseConnection, bad: float) -> None:
    for warning, critical in ((bad, None), (None, bad), (5.0, bad), (bad, 1.0)):
        _refused(
            db,
            lambda w=warning, c=critical: stack.indicators.set_target(
                CERT_A, LEVEL_A, warning_value=w, critical_value=c
            ),
            TARGET_NOT_FINITE,
        )


@pytest.mark.parametrize("bad", [True, False, "5", b"5", [1], 10**400, object()])
def test_invalid_number(stack: Stack, db: DatabaseConnection, bad: Any) -> None:
    service = stack.indicators
    _refused(
        db,
        lambda: service.set_target(CERT_A, LEVEL_A, warning_value=bad, critical_value=None),
        INVALID_NUMBER,
        "warning_value",
    )
    _refused(
        db,
        lambda: service.set_target(CERT_A, LEVEL_A, warning_value=None, critical_value=bad),
        INVALID_NUMBER,
        "critical_value",
    )


def test_target_empty(stack: Stack, db: DatabaseConnection) -> None:
    service = stack.indicators
    _refused(
        db,
        lambda: service.set_target(CERT_A, LEVEL_A, warning_value=None, critical_value=None),
        TARGET_EMPTY,
    )
    # an existing target is not emptied either: it is deleted instead
    service.set_target(CERT_A, LEVEL_A, warning_value=3, critical_value=1)
    _refused(
        db,
        lambda: service.set_target(CERT_A, LEVEL_A, warning_value=None, critical_value=None),
        TARGET_EMPTY,
    )


def test_not_found(stack: Stack, db: DatabaseConnection) -> None:
    _refused(db, lambda: stack.indicators.set_target_enabled(CERT_A, LEVEL_A, False), NOT_FOUND)
    _refused(db, lambda: stack.indicators.delete_target(CERT_A, LEVEL_A), NOT_FOUND)
    with pytest.raises(ServiceError) as info:
        stack.indicators.get_target(CERT_A, LEVEL_A)
    assert info.value.code == NOT_FOUND
    # a target of another dimension does not count
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=3, critical_value=1)
    _refused(db, lambda: stack.indicators.delete_target(CERT_A, LEVEL_B), NOT_FOUND)
    _refused(db, lambda: stack.indicators.set_target_enabled(CERT_A, LEVEL_B, False), NOT_FOUND)


# --------------------------------------------------------------------------- budget pro-rating


def _set_budget_target(stack: Stack) -> None:
    stack.indicators.set_target(BUDGET, BUDGET_DIM, warning_value=0.9, critical_value=0.6)


def test_the_budget_target_is_prorated_over_the_fiscal_year(stack: Stack) -> None:
    _set_budget_target(stack)
    january = date(2026, 1, 15)
    december = date(2026, 12, 15)

    early = _reading(stack.indicators.evaluate(january), BUDGET, BUDGET_DIM)
    late = _reading(stack.indicators.evaluate(december), BUDGET, BUDGET_DIM)
    # the same executed and allocated data (rate 0.5), but a different status
    assert early.value == pytest.approx(0.5)
    assert late.value == pytest.approx(0.5)
    assert early.status is IndicatorStatus.OK
    assert late.status is IndicatorStatus.CRITICAL

    # the reading records the thresholds actually used: the scaled ones
    for reading, as_of in ((early, january), (late, december)):
        factor = as_of.timetuple().tm_yday / 365
        assert reading.warning_value == pytest.approx(0.9 * factor)
        assert reading.critical_value == pytest.approx(0.6 * factor)
        assert factor == pytest.approx(stack.budget.target_scale(as_of))
    # at the end of the year the year-end target applies unchanged
    year_end = _reading(stack.indicators.evaluate(date(2026, 12, 31)), BUDGET, BUDGET_DIM)
    assert (year_end.warning_value, year_end.critical_value) == (
        pytest.approx(0.9),
        pytest.approx(0.6),
    )
    # the stored target stays the year-end one
    stored = stack.indicators.get_target(BUDGET, BUDGET_DIM)
    assert (stored.warning_value, stored.critical_value) == (0.9, 0.6)


def test_other_indicators_are_never_prorated(stack: Stack) -> None:
    v = _value(stack, CERT_A, LEVEL_A)
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=v, critical_value=v - 1)
    for as_of in (date(2026, 1, 15), date(2026, 12, 15)):
        reading = _reading(stack.indicators.evaluate(as_of), CERT_A, LEVEL_A)
        assert (reading.warning_value, reading.critical_value) == (v, v - 1)


def test_with_the_switch_off_the_budget_target_is_used_unchanged(
    stack: Stack, db: DatabaseConnection, clock: FixedClock
) -> None:
    _set_budget_target(stack)
    config = load_config(db).with_changes(budget_prorate_target=False)
    save_config(WriteContext(db, clock, OPERATOR), config)
    for as_of in (date(2026, 1, 15), date(2026, 12, 15)):
        reading = _reading(stack.indicators.evaluate(as_of), BUDGET, BUDGET_DIM)
        assert (reading.warning_value, reading.critical_value) == (0.9, 0.6)
        assert reading.status is IndicatorStatus.CRITICAL  # 0.5 against 0.6, in January too


# --------------------------------------------------------------------------- read-only


def test_a_read_only_connection_refuses_every_change_but_reads(
    stack: Stack, db: DatabaseConnection, read_only_db: DatabaseConnection, clock: FixedClock
) -> None:
    stack.indicators.set_target(CERT_A, LEVEL_A, warning_value=3, critical_value=1)
    frozen = _stack(read_only_db, clock)
    before = _state(db)

    calls: list[Callable[[], object]] = [
        lambda: frozen.indicators.set_target(CERT_A, LEVEL_B, warning_value=3, critical_value=1),
        lambda: frozen.indicators.set_target(CERT_A, LEVEL_A, warning_value=4, critical_value=1),
        lambda: frozen.indicators.set_target_enabled(CERT_A, LEVEL_A, False),
        lambda: frozen.indicators.delete_target(CERT_A, LEVEL_A),
        # READ_ONLY comes first, before any validation
        lambda: frozen.indicators.set_target("NOPE", "", warning_value=None, critical_value=None),
        lambda: frozen.indicators.delete_target("NOPE", ""),
    ]
    for call in calls:
        with pytest.raises(ServiceError) as info:
            call()
        assert info.value.code == READ_ONLY
    assert _state(db) == before

    assert frozen.indicators.evaluate(AS_OF) == stack.indicators.evaluate(AS_OF)
    assert [t.indicator_code for t in frozen.indicators.list_targets()] == [CERT_A]
    assert frozen.indicators.get_target(CERT_A, LEVEL_A).warning_value == 3.0
    assert frozen.indicators.known_dimensions(AS_OF) == stack.indicators.known_dimensions(AS_OF)
    assert frozen.indicators.readings_by_code(AS_OF) == stack.indicators.readings_by_code(AS_OF)
