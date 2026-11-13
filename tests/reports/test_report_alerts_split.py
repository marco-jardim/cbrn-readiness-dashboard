# SPDX-License-Identifier: GPL-3.0-or-later
"""The alert summary and the anonymiser (P8-01, P8-03, P8-17): nothing hidden can be recomputed.

The worked example is built THROUGH the services with fictitious data; every expected cell is
written by hand from the rules (threshold 5, no targets, as of 2026-03-05, warning window 90 days).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain import budget as budget_domain
from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.budget import BudgetTotal
from cbrn_dashboard.domain.indicators import Direction, IndicatorStatus, Module, UnitKind
from cbrn_dashboard.reports.anonymise import anonymise
from cbrn_dashboard.reports.model import (
    AlertCountRow,
    AlertSource,
    Cell,
    IndicatorRow,
    KeyFigureGroup,
    ReportBuilder,
    ReportDocument,
    ReportHeader,
    ReportVariant,
    _alert_summary,
    _budget_figures,
    _indicator_cell,
    _indicator_row,
)
from cbrn_dashboard.services.alerts import AlertService
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.services.dashboard import (
    ChartSpec,
    DashboardService,
    SeriesSpec,
    Tile,
)
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import CertificateInput, PersonnelService, StaffInput
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate

AS_OF = date(2026, 3, 5)


def _operator() -> str:
    return "TEST-OPERATOR"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[DatabaseConnection]:
    opened = open_and_migrate(
        tmp_path / "split.sqlite3",
        data_dir=tmp_path,
        identity=DatabaseIdentity.REAL,
        backup=False,
    )
    try:
        yield opened
    finally:
        opened.close()


def _builder(conn: DatabaseConnection) -> tuple[ReportBuilder, PersonnelService]:
    clock = FixedClock.at("2026-03-05T12:00:00Z")
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
        budget=budget,
    )
    return builder, personnel


def _seed_worked_example(personnel: PersonnelService) -> None:
    """Expiring A 7, B 6, C 2 (valid until 2026-04-20, inside the window); expired A 3.

    People 1..7 hold A, 1..6 hold B, 1..2 hold C (all expiring); people 8..10 hold only an expired
    A certificate (valid until 2026-01-10). So active staff 10, retraining A 10, B 6, C 2.
    """
    ids = [personnel.create_staff(StaffInput(f"WE-{n:02d}", "2020-01-01")) for n in range(1, 11)]
    for level, count in (("A", 7), ("B", 6), ("C", 2)):
        for staff_id in ids[:count]:
            personnel.add_certificate(staff_id, CertificateInput(level, "2025-02-10", "2026-04-20"))
    for staff_id in ids[7:]:
        personnel.add_certificate(staff_id, CertificateInput("A", "2025-02-10", "2026-01-10"))


def _cells(document: ReportDocument) -> dict[str, Cell]:
    found: dict[str, Cell] = {}
    for group in document.key_figures:
        found.update({c.key: c for c in group.cells})
    found.update({r.value.key: r.value for r in document.indicators})
    found.update({a.cell.key: a.cell for a in document.alert_summary})
    return found


def assert_nothing_recoverable(document: ReportDocument) -> None:
    """Generic check: no visible total has a hidden part; no hidden personnel cell is a part."""
    cells = _cells(document)
    hidden_personnel = {k for k, c in cells.items() if c.suppressed and c.personnel_derived}
    for key, cell in cells.items():
        if cell.suppressed or not cell.total_of:
            continue
        for part in cell.total_of:
            assert part not in cells or not cells[part].suppressed, (key, part)
            assert part not in hidden_personnel, (key, part)


# --------------------------------------------------------------------------- the worked example


def test_the_worked_example_hides_every_figure_that_could_be_subtracted(
    conn: DatabaseConnection,
) -> None:
    builder, personnel = _builder(conn)
    _seed_worked_example(personnel)

    internal = _cells(builder.build(AS_OF, ReportVariant.INTERNAL))
    document = builder.build(AS_OF, ReportVariant.ANONYMISED)
    cells = _cells(document)

    # the internal figures, by hand
    assert {
        key: internal[key].value
        for key in (
            "kf:PERSONNEL:expiring:A",
            "kf:PERSONNEL:expiring:B",
            "kf:PERSONNEL:expiring:C",
            "kf:PERSONNEL:expired:A",
            "kf:PERSONNEL:retraining:A",
            "kf:PERSONNEL:retraining:B",
            "kf:PERSONNEL:retraining:C",
            "alert:WARNING",
            "alert:WARNING:personnel",
            "alert:CRITICAL",
            "alert:CRITICAL:personnel",
            "alert:INFO",
        )
    } == {
        "kf:PERSONNEL:expiring:A": 7.0,
        "kf:PERSONNEL:expiring:B": 6.0,
        "kf:PERSONNEL:expiring:C": 2.0,
        "kf:PERSONNEL:expired:A": 3.0,
        "kf:PERSONNEL:retraining:A": 10.0,
        "kf:PERSONNEL:retraining:B": 6.0,
        "kf:PERSONNEL:retraining:C": 2.0,
        "alert:WARNING": 15.0,
        "alert:WARNING:personnel": 15.0,
        "alert:CRITICAL": 3.0,
        "alert:CRITICAL:personnel": 3.0,
        "alert:INFO": 0.0,
    }

    # visible in the anonymised document
    shown = {
        "kf:PERSONNEL:expiring:A": 7.0,
        "kf:PERSONNEL:expiring:B": 6.0,
        "kf:INFRASTRUCTURE:due_soon": 0.0,
        "kf:INFRASTRUCTURE:overdue": 0.0,
        "alert:WARNING:infrastructure": 0.0,
        "alert:WARNING:indicators": 0.0,
        "alert:CRITICAL:infrastructure": 0.0,
        "alert:CRITICAL:indicators": 0.0,
        "alert:INFO": 0.0,
    }
    for key, value in shown.items():
        assert not cells[key].suppressed, key
        assert cells[key].value == value, key
    # hidden: C = 2, every expired count, retraining (expiring + expired), both sums
    for key in (
        "kf:PERSONNEL:expiring:C",
        "kf:PERSONNEL:expired:A",
        "kf:PERSONNEL:expired:B",
        "kf:PERSONNEL:expired:C",
        "kf:PERSONNEL:retraining:A",
        "kf:PERSONNEL:retraining:B",
        "kf:PERSONNEL:retraining:C",
        "alert:WARNING",
        "alert:WARNING:personnel",
        "alert:CRITICAL",
        "alert:CRITICAL:personnel",
    ):
        assert cells[key].suppressed, key
        assert cells[key].value is None, key
    assert_nothing_recoverable(document)

    # no visible number is a difference or a sum that gives the hidden figures 2, 3 or 15
    visible_personnel = sorted(
        c.value for c in cells.values() if c.personnel_derived and c.value is not None
    )
    assert 2.0 not in visible_personnel
    assert 15.0 not in visible_personnel
    assert 3.0 not in visible_personnel


def test_a_total_that_has_no_hidden_part_stays_visible(conn: DatabaseConnection) -> None:
    builder, personnel = _builder(conn)
    ids = [personnel.create_staff(StaffInput(f"VS-{n:02d}", "2020-01-01")) for n in range(1, 13)]
    for level, count in (("A", 7), ("B", 6), ("C", 5)):
        for staff_id in ids[:count]:
            personnel.add_certificate(staff_id, CertificateInput(level, "2025-02-10", "2026-04-20"))

    cells = _cells(builder.build(AS_OF, ReportVariant.ANONYMISED))

    # expiring 7 + 6 + 5 = 18 (all shown); nothing expired, so the expired cells (0) are hidden
    assert cells["alert:WARNING:personnel"].value == 18.0
    assert cells["alert:WARNING"].value == 18.0
    assert cells["alert:CRITICAL"].suppressed
    assert cells["alert:CRITICAL:personnel"].suppressed
    assert cells["alert:CRITICAL:infrastructure"].value == 0.0


def test_the_info_count_is_maintenance_only_and_never_suppressed(
    conn: DatabaseConnection,
) -> None:
    builder, _personnel = _builder(conn)

    internal = builder.build(AS_OF, ReportVariant.INTERNAL)
    anonymised = builder.build(AS_OF, ReportVariant.ANONYMISED)

    info = [a for a in internal.alert_summary if a.severity is Severity.INFO]
    assert [(a.source, a.cell.personnel_derived, a.cell.total_of) for a in info] == [
        (AlertSource.ALL, False, ())
    ]
    [shown] = [a for a in anonymised.alert_summary if a.severity is Severity.INFO]
    assert (shown.cell.suppressed, shown.cell.value) == (False, 0.0)


# --------------------------------------------------------------------------- indicator rows


def _tile(code: str, level: str, value: float, status: IndicatorStatus) -> Tile:
    return Tile(
        code=code,
        dimension=f"level={level}",
        dimension_parts=MappingProxyType({"level": level}),
        module=Module.PERSONNEL,
        unit=UnitKind.COUNT,
        direction=Direction.HIGHER_IS_BETTER,
        value=value,
        status=status,
        warning_value=40.0,
        critical_value=30.0,
        context=MappingProxyType({}),
    )


def _document(tiles: tuple[Tile, ...]) -> ReportDocument:
    cells = {t.code + t.dimension: _indicator_cell(t) for t in tiles}
    keyed = {f"indicator:{t.code}:{t.dimension}": cells[t.code + t.dimension] for t in tiles}
    rows: tuple[IndicatorRow, ...] = tuple(
        _indicator_row(t, cells[t.code + t.dimension]) for t in tiles
    )
    return ReportDocument(
        variant=ReportVariant.INTERNAL,
        header=ReportHeader("", "", AS_OF, "2026-03-05T12:00:00Z", "t", ""),
        handling_notice="",
        is_demo=False,
        small_count_threshold=5,
        key_figures=(KeyFigureGroup(Module.PERSONNEL, ()),),
        indicators=rows,
        alert_summary=_alert_summary(
            expiring=0,
            expired=0,
            expired_keys=(),
            maintenance=[],
            tiles=tiles,
            indicator_cells=keyed,
        ),
        charts=(),
        retraining=(),
        overdue_assets=(),
    )


def test_the_indicator_alert_count_is_hidden_when_a_counted_row_is_hidden() -> None:
    # PERS_CERT_VALID A = 3 (hidden, WARNING), B = 50 (shown, OK): one indicator warning
    document = _document(
        (
            _tile("PERS_CERT_VALID", "A", 3.0, IndicatorStatus.WARNING),
            _tile("PERS_CERT_VALID", "B", 50.0, IndicatorStatus.OK),
        )
    )
    internal = {a.cell.key: a.cell for a in document.alert_summary}
    assert internal["alert:WARNING:indicators"].value == 1.0
    assert internal["alert:WARNING:indicators"].total_of == (
        "indicator:PERS_CERT_VALID:level=A",
        "indicator:PERS_CERT_VALID:level=B",
    )

    anonymised = anonymise(document)

    cells = _cells(anonymised)
    assert cells["indicator:PERS_CERT_VALID:level=A"].suppressed
    assert cells["alert:WARNING:indicators"].suppressed
    assert cells["alert:CRITICAL:indicators"].suppressed  # same declared rows: no status leaks
    assert cells["alert:WARNING"].suppressed
    assert_nothing_recoverable(anonymised)


def test_the_indicator_alert_count_is_shown_when_every_counted_row_is_shown() -> None:
    document = _document(
        (
            _tile("PERS_CERT_VALID", "A", 35.0, IndicatorStatus.WARNING),
            _tile("PERS_CERT_VALID", "B", 50.0, IndicatorStatus.OK),
        )
    )

    anonymised = anonymise(document)

    cells = _cells(anonymised)
    assert cells["alert:WARNING:indicators"].suppressed is False
    assert cells["alert:WARNING:indicators"].value == 1.0
    assert cells["alert:CRITICAL:indicators"].value == 0.0
    assert_nothing_recoverable(anonymised)


def test_the_two_argument_alert_row_still_builds() -> None:
    row = AlertCountRow(Severity.INFO, Cell("alert:INFO", 3.0))

    assert row.source is AlertSource.ALL


# --------------------------------------------------------------------------- budget (P8-17)


def test_budget_key_figures_use_the_decimals_of_the_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(budget_domain, "CURRENCY_DECIMALS", MappingProxyType({"BRL": 2, "KWD": 3}))
    chart = ChartSpec(
        key="budget_KWD",
        categories=("A", "B"),
        series=(
            SeriesSpec("allocated", (1.001, 2.002)),
            SeriesSpec("executed", (0.003, None)),
        ),
        unit=UnitKind.CURRENCY,
        parameters=MappingProxyType({"currency": "KWD", "fiscal_year": "2026"}),
    )

    group = _budget_figures((chart,))

    assert {c.key: c.value for c in group.cells} == {
        "kf:BUDGET:allocated:KWD": 3.003,  # a hard-coded two-decimal rounding gave 3.0
        "kf:BUDGET:executed:KWD": 0.003,
    }


def test_budget_key_figures_are_built_from_the_exact_minor_units_when_known() -> None:
    chart = ChartSpec(
        key="budget_BRL",
        categories=("A", "B"),
        series=(SeriesSpec("allocated", (0.0, 0.0)), SeriesSpec("executed", (0.0, 0.0))),
        unit=UnitKind.CURRENCY,
        parameters=MappingProxyType({"currency": "BRL", "fiscal_year": "2026"}),
    )
    totals = [
        BudgetTotal(2026, "A", "BRL", 10_000_000_000_000_001, 1, None),
        BudgetTotal(2026, "B", "BRL", None, 2, None),
        BudgetTotal(2026, "C", "USD", 5, 5, None),
    ]

    group = _budget_figures((chart,), totals)

    assert {c.key: c.value for c in group.cells} == {
        "kf:BUDGET:allocated:BRL": float(Decimal("100000000000000.01")),
        "kf:BUDGET:executed:BRL": 0.03,
    }
