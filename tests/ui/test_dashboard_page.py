# SPDX-License-Identifier: GPL-3.0-or-later
"""The Dashboard page: tiles, alert counts, charts with their table views and the snapshot action
(PLAN.md T6.5 UI half, T8.1 "Record snapshot", D08, D13-D15, D23).

All data is fictitious and is written THROUGH the module services of the context. The expected
values are written out here (worked out by hand from the dataset described in ``_seed``, the same
one as ``tests/services/test_dashboard_service.py``), never computed by the code under test. No
pixel comparison is made.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QLabel, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.indicators import (
    Direction,
    IndicatorReading,
    IndicatorStatus,
    Module,
    UnitKind,
)
from cbrn_dashboard.domain.infrastructure import AssetStatus, MaintenanceKind
from cbrn_dashboard.services.budget import EntryInput
from cbrn_dashboard.services.dashboard import ChartSpec, DashboardData, Tile
from cbrn_dashboard.services.exercises import EditionInput
from cbrn_dashboard.services.infrastructure import AssetInput, AssetTypeInput
from cbrn_dashboard.services.personnel import (
    CertificateInput,
    CourseInput,
    StaffInput,
    TrainingInput,
)
from cbrn_dashboard.services.snapshots import SnapshotOrigin, SnapshotService
from cbrn_dashboard.ui.dashboard import labels
from cbrn_dashboard.ui.dashboard.models import count_text, major_money_text
from cbrn_dashboard.ui.dashboard.page import (
    ChartPanel,
    DashboardPage,
    TileWidget,
    create_page,
    page_title,
)
from cbrn_dashboard.ui.shell.charts import PALETTE, ChartKind, read_back
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from tests.ui._fakes import FakePrompts
from tests.ui._walk import assert_fully_translated, find_untranslated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")
NBSP = "\xa0"
AS_OF = date(2026, 3, 5)
EARLIER = date(2025, 6, 15)

STATUS_TEXT = {
    IndicatorStatus.OK: "OK",
    IndicatorStatus.WARNING: "Warning",
    IndicatorStatus.CRITICAL: "Critical",
    IndicatorStatus.NO_TARGET: "No target",
    IndicatorStatus.NO_DATA: "No data",
}


# --------------------------------------------------------------------------- the dataset


def _need[T](value: T | None) -> T:
    assert value is not None
    return value


def _seed(context: AppContext) -> int:
    """The fictitious dataset (as of 2026-03-05); returns the id of the DIRSA / BRL entry.

    Personnel: P001 holds A until 2026-03-20 and B until 2027-02-10; P002 holds A until
    2027-02-10 and B until 2026-01-10 (expired); P003 holds A until 2027-01-10. One training
    record. Infrastructure: type A has A001 (operational, no schedule) and A002 (degraded,
    maintenance due 2026-03-25); type B has A003 (operational, schedule unknown) and A004
    (operational, interval 30, never maintained, so overdue). Exercises: EX-24 (40 participants,
    3 countries), EX-25 (no participant count, 2 countries), EX-27 in the future. Budget FY2026
    in minor units: DIRSA/BRL 100 000 (25 000 on 2026-01-10, 40 000 on 2026-04-10),
    OPCW_TRUST_FUND/BRL 50 000 (10 000 on 2026-02-01), DIRSA/USD 20 000 (5 000 on 2026-03-01);
    FY2025 DIRSA/BRL 80 000 (60 000 and 10 000 executed). Targets: B certificates 2 / 1,
    type A overdue 1 / 2, DIRSA/BRL execution rate 0.9 / 0.6 (year-end values).
    """
    people = _need(context.services.personnel)
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

    infra = _need(context.services.infrastructure)
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

    exercises = _need(context.services.exercises)
    for code, start, end, participants, countries in (
        ("DEMO-EX-24", "2024-03-01", "2024-03-05", 40, ("BR", "AR", "PT")),
        ("DEMO-EX-25", "2025-09-01", "2025-09-05", None, ("BR", "AR")),
        ("DEMO-EX-27", "2026-09-01", "2026-09-05", 60, ("BR",)),
    ):
        exercises.create_edition(
            EditionInput(
                code=code,
                kind="CBRAMED",
                start_on=start,
                end_on=end,
                participants=participants,
                countries=countries,
            )
        )

    budget = _need(context.services.budget)
    dirsa = _need(budget.get_source_by_code("DIRSA")).id
    opcw = _need(budget.get_source_by_code("OPCW_TRUST_FUND")).id
    last_year = budget.create_entry(
        EntryInput(fiscal_year=2025, source_id=dirsa, allocated_minor=80_000, currency="BRL")
    )
    budget.add_execution(last_year, "2025-03-01", 60_000)
    budget.add_execution(last_year, "2025-09-01", 10_000)
    brl_dirsa = budget.create_entry(
        EntryInput(fiscal_year=2026, source_id=dirsa, allocated_minor=100_000, currency="BRL")
    )
    budget.add_execution(brl_dirsa, "2026-01-10", 25_000)
    budget.add_execution(brl_dirsa, "2026-04-10", 40_000)
    other = budget.create_entry(
        EntryInput(fiscal_year=2026, source_id=opcw, allocated_minor=50_000, currency="BRL")
    )
    budget.add_execution(other, "2026-02-01", 10_000)
    dollars = budget.create_entry(
        EntryInput(fiscal_year=2026, source_id=dirsa, allocated_minor=20_000, currency="USD")
    )
    budget.add_execution(dollars, "2026-03-01", 5_000)

    indicators = _need(context.services.indicators)
    indicators.set_target("PERS_CERT_VALID", "level=B", warning_value=2, critical_value=1)
    indicators.set_target(
        "INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A", warning_value=1, critical_value=2
    )
    indicators.set_target(
        "BUD_EXEC_RATE", "currency=BRL;source=DIRSA", warning_value=0.9, critical_value=0.6
    )
    return brl_dirsa


def _attach_snapshots(context: AppContext) -> SnapshotService:
    """A real snapshot service on the context (the shell may not provide one yet)."""
    assert context.conn is not None
    service = SnapshotService(
        context.conn,
        context.clock,
        context.operator_label,
        indicators=_need(context.services.indicators),
        infrastructure=_need(context.services.infrastructure),
    )
    vars(context.services)["snapshots"] = service
    return service


def _page(context: AppContext, qtbot: QtBot) -> DashboardPage:
    page = DashboardPage(context)
    qtbot.addWidget(page)
    return page


def _tile(page: DashboardPage, code: str, dimension: str = "") -> TileWidget:
    return _need(page.tile_for(code, dimension))


def _panel(page: DashboardPage, key: str) -> ChartPanel:
    return _need(page.chart_panel(key))


def _cells(panel: ChartPanel) -> list[list[str]]:
    model = panel.table_model
    return [
        [str(model.index(row, column).data()) for column in range(model.columnCount())]
        for row in range(model.rowCount())
    ]


def _headers(panel: ChartPanel) -> list[str]:
    model = panel.table_model
    return [
        str(model.headerData(column, Qt.Orientation.Horizontal))
        for column in range(model.columnCount())
    ]


def _raw(panel: ChartPanel) -> tuple[tuple[float | None, ...], ...]:
    """The raw numbers of the table (``UserRole``), column by column."""
    model = panel.table_model
    role = Qt.ItemDataRole.UserRole
    return tuple(
        tuple(model.index(row, column).data(role) for row in range(model.rowCount()))
        for column in range(1, model.columnCount())
    )


@pytest.fixture
def pseudo_context(
    app_context: AppContext,
    translator_manager_factory: Callable[[Path | None], TranslatorManager],
    pseudo_qm_dir: Path,
) -> AppContext:
    """The context with every translated text wrapped in the pseudo-locale markers."""
    app_context.translator_manager.clear()
    manager = translator_manager_factory(pseudo_qm_dir)
    manager.set_language("pt_BR")
    app_context.translator_manager = manager
    return app_context


# --------------------------------------------------------------------------- expected values

# (code, dimension, value text, status) of every tile on AS_OF in en_US, in service order.
NT, ND, OK = IndicatorStatus.NO_TARGET, IndicatorStatus.NO_DATA, IndicatorStatus.OK
CRIT = IndicatorStatus.CRITICAL
type TileRow = tuple[str, str, str, IndicatorStatus]
EXPECTED_TILES: list[TileRow] = [
    ("PERS_CERT_VALID", "level=A", "3", NT),
    ("PERS_CERT_VALID", "level=B", "1", CRIT),
    ("PERS_CERT_VALID", "level=C", "0", NT),
    ("PERS_CERT_EXPIRING", "level=A", "1", NT),
    ("PERS_CERT_EXPIRING", "level=B", "0", NT),
    ("PERS_CERT_EXPIRING", "level=C", "0", NT),
    ("PERS_RETRAINING_NEEDED", "level=A", "1", NT),
    ("PERS_RETRAINING_NEEDED", "level=B", "1", NT),
    ("PERS_RETRAINING_NEEDED", "level=C", "0", NT),
    ("PERS_DEGREE", "level=doctorate;status=completed", "0", NT),
    ("PERS_DEGREE", "level=doctorate;status=in_progress", "0", NT),
    ("PERS_DEGREE", "level=master;status=completed", "0", NT),
    ("PERS_DEGREE", "level=master;status=in_progress", "0", NT),
    ("PERS_DEGREE", "level=specialisation;status=completed", "0", NT),
    ("PERS_DEGREE", "level=specialisation;status=in_progress", "0", NT),
    ("PERS_TRAINING_12M", "", "1", NT),
    ("INFRA_AVAILABLE", "type=DEMO-TYPE-A", "1", NT),
    ("INFRA_AVAILABLE", "type=DEMO-TYPE-B", "2", NT),
    ("INFRA_AVAILABLE", "type=bay", "0", NT),
    ("INFRA_AVAILABLE", "type=bed", "0", NT),
    ("INFRA_AVAILABLE", "type=decon_tent", "0", NT),
    ("INFRA_AVAILABLE", "type=neg_pressure_filtration", "0", NT),
    ("INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A", "0", OK),
    ("INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-B", "1", NT),
    ("INFRA_MAINT_OVERDUE", "type=bay", "0", NT),
    ("INFRA_MAINT_OVERDUE", "type=bed", "0", NT),
    ("INFRA_MAINT_OVERDUE", "type=decon_tent", "0", NT),
    ("INFRA_MAINT_OVERDUE", "type=neg_pressure_filtration", "0", NT),
    ("EX_LAST_PARTICIPANTS", "kind=CBRAMED", "-", ND),
    ("EX_LAST_PARTICIPANTS", "kind=EXBRAMED", "-", ND),
    ("EX_LAST_PARTICIPANTS", "kind=OTHER", "-", ND),
    ("EX_LAST_COUNTRIES", "kind=CBRAMED", "2", NT),
    ("EX_LAST_COUNTRIES", "kind=EXBRAMED", "-", ND),
    ("EX_LAST_COUNTRIES", "kind=OTHER", "-", ND),
    ("EX_DAYS_SINCE_LAST", "kind=CBRAMED", "181", NT),
    ("EX_DAYS_SINCE_LAST", "kind=EXBRAMED", "-", ND),
    ("EX_DAYS_SINCE_LAST", "kind=OTHER", "-", ND),
    ("BUD_EXEC_RATE", "currency=BRL;source=DIRSA", "25.0%", OK),
    ("BUD_EXEC_RATE", "currency=BRL;source=OPCW_TRUST_FUND", "20.0%", NT),
    ("BUD_EXEC_RATE", "currency=USD;source=DIRSA", "25.0%", NT),
]


@dataclass(frozen=True)
class ExpectedChart:
    """What the chart and its table show in en_US."""

    title: str
    unit: str
    kind: ChartKind
    headers: list[str]
    rows: list[list[str]]
    raw: tuple[tuple[float | None, ...], ...]


CHARTS_AS_OF: dict[str, ExpectedChart] = {
    "personnel_valid_by_level": ExpectedChart(
        "Staff with a valid certificate, by PPE level",
        "Count",
        ChartKind.BAR,
        ["PPE level", "Valid certificates"],
        [["A", "3"], ["B", "1"], ["C", "0"]],
        ((3.0, 1.0, 0.0),),
    ),
    "infrastructure_availability": ExpectedChart(
        "Availability by asset type",
        "Count",
        ChartKind.GROUPED_BAR,
        ["Asset type", "Available", "In service"],
        [
            ["Tipo demo A", "1", "2"],
            ["Tipo demo B", "2", "2"],
            ["Bay", "0", "0"],
            ["Bed", "0", "0"],
            ["Decontamination tent", "0", "0"],
            ["Negative-pressure and filtration equipment", "0", "0"],
        ],
        ((1.0, 2.0, 0.0, 0.0, 0.0, 0.0), (2.0, 2.0, 0.0, 0.0, 0.0, 0.0)),
    ),
    "exercises_by_edition": ExpectedChart(
        "Participants and countries by edition",
        "Count",
        ChartKind.GROUPED_BAR,
        ["Edition", "Participants", "Countries"],
        [["DEMO-EX-24", "40", "3"], ["DEMO-EX-25", "-", "2"]],
        ((40.0, None), (3.0, 2.0)),
    ),
    "budget_BRL": ExpectedChart(
        "Allocated and executed by funding source, BRL, fiscal year 2026",
        "BRL",
        ChartKind.GROUPED_BAR,
        ["Funding source", "Allocated", "Executed"],
        [["DIRSA", "R$1,000.00", "R$250.00"], ["OPCW Trust Fund", "R$500.00", "R$100.00"]],
        ((1000.0, 500.0), (250.0, 100.0)),
    ),
    "budget_USD": ExpectedChart(
        "Allocated and executed by funding source, USD, fiscal year 2026",
        "USD",
        ChartKind.GROUPED_BAR,
        ["Funding source", "Allocated", "Executed"],
        [["DIRSA", "US$200.00", "US$50.00"]],
        ((200.0,), (50.0,)),
    ),
}


# --------------------------------------------------------------------------- tiles


def test_every_tile_shows_its_value_and_its_status_as_text(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    assert len(page.tile_widgets) == 40
    assert [
        (t.tile.code, t.tile.dimension, t.value_label.text(), t.tile.status)
        for t in page.tile_widgets
    ] == EXPECTED_TILES
    for widget in page.tile_widgets:
        assert widget.status_label.text() == STATUS_TEXT[widget.tile.status]
        assert not widget.status_label.isHidden()
        assert widget.status_icon.accessibleName() == widget.status_label.text()
        assert not widget.status_icon.pixmap().isNull()


def test_tiles_name_unit_dimension_thresholds_and_context(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)

    valid_b = _tile(page, "PERS_CERT_VALID", "level=B")
    assert valid_b.name_label.text() == "Staff with a valid certificate"
    assert valid_b.dimension_label.text() == "Level B"
    assert valid_b.unit_label.text() == "people"
    assert valid_b.thresholds_label.text() == "Thresholds in force: warning 2, critical 1"
    assert valid_b.context_label.isHidden()

    valid_a = _tile(page, "PERS_CERT_VALID", "level=A")
    assert valid_a.thresholds_label.text() == "Thresholds in force: none"
    assert valid_a.status_label.text() == "No target"

    degree = _tile(page, "PERS_DEGREE", "level=doctorate;status=completed")
    assert degree.dimension_label.text() == "Doctorate, Completed"

    training = _tile(page, "PERS_TRAINING_12M")
    assert training.dimension_label.isHidden()
    assert training.unit_label.text() == "records"

    available = _tile(page, "INFRA_AVAILABLE", "type=DEMO-TYPE-A")
    assert available.dimension_label.text() == "Type Tipo demo A"
    assert available.context_label.text() == "of 2 in service"
    assert _tile(page, "INFRA_AVAILABLE", "type=bed").dimension_label.text() == "Type Bed"

    overdue = _tile(page, "INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A")
    assert overdue.status_label.text() == "OK"
    assert overdue.thresholds_label.text() == "Thresholds in force: warning 1, critical 2"

    nobody = _tile(page, "EX_LAST_PARTICIPANTS", "kind=CBRAMED")
    assert nobody.value_label.text() == "-"
    assert nobody.status_label.text() == "No data"
    assert nobody.dimension_label.text() == "Kind CBRAMED"
    assert _tile(page, "EX_DAYS_SINCE_LAST", "kind=CBRAMED").unit_label.text() == "days"

    rate = _tile(page, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA")
    assert rate.dimension_label.text() == "Currency BRL, Source DIRSA"
    assert rate.status_label.text() == "OK"
    # the year-end 0.9 / 0.6 scaled by day 64 of 365 (P08), as a percentage
    assert rate.thresholds_label.text() == "Thresholds in force: warning 15.8%, critical 10.5%"
    assert rate.context_label.text() == "Executed R$250.00 of R$1,000.00 allocated"
    other = _tile(page, "BUD_EXEC_RATE", "currency=BRL;source=OPCW_TRUST_FUND")
    assert other.dimension_label.text() == "Currency BRL, Source OPCW Trust Fund"


def test_tiles_are_grouped_by_module_and_no_score_is_shown(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    titles = {
        "module_personnel": "Personnel",
        "module_infrastructure": "Infrastructure",
        "module_exercises": "Exercises",
        "module_budget": "Budget",
    }
    for name, title in titles.items():
        box = page.findChild(QGroupBox, name)
        assert box is not None
        assert box.title() == title
    assert {w.tile.module for w in page.tile_widgets} == set(Module)
    texts = [label.text().lower() for label in page.findChildren(QLabel)]
    assert not any("score" in text for text in texts)


def test_the_status_icons_differ_by_shape_and_use_palette_colours() -> None:
    assert set(labels.STATUS_COLOURS) == {status.value for status in IndicatorStatus}
    assert set(labels.STATUS_COLOURS.values()) <= set(PALETTE)
    assert len(set(labels.STATUS_COLOURS.values())) == len(IndicatorStatus)


def test_every_status_has_its_own_icon_shape(qapp: QApplication) -> None:
    images = {s.value: labels.status_pixmap(s.value).toImage() for s in IndicatorStatus}
    names = sorted(images)
    for index, first in enumerate(names):
        assert not images[first].isNull()
        for second in names[index + 1 :]:
            assert images[first] != images[second], (first, second)
    for severity in Severity:
        assert not labels.severity_pixmap(severity.value).isNull()


# --------------------------------------------------------------------------- alerts


def test_the_alert_counts_are_shown_by_severity(app_context: AppContext, qtbot: QtBot) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    # critical: P002 level B expired, A004 overdue, indicator B certificates; warning: P001
    # level A expiring, A002 due soon; information: A003 schedule unknown
    assert page.alert_labels[Severity.CRITICAL].text() == "Critical alerts: 3"
    assert page.alert_labels[Severity.WARNING].text() == "Warning alerts: 2"
    assert page.alert_labels[Severity.INFO].text() == "Information alerts: 1"
    assert page.alert_icons[Severity.CRITICAL].accessibleName() == "Critical alerts: 3"
    assert page.as_of_label.text() == "Readiness as of 03/05/2026"


# --------------------------------------------------------------------------- charts


def test_each_chart_and_its_table_hold_exactly_the_expected_values(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    assert [panel.key for panel in page.chart_panels()] == list(CHARTS_AS_OF)
    for key, expected in CHARTS_AS_OF.items():
        panel = _panel(page, key)
        data = panel.data()
        assert data.title == expected.title
        assert data.unit == expected.unit
        assert data.kind is expected.kind
        assert [series.values for series in data.series] == list(expected.raw)
        assert list(data.categories) == [row[0] for row in expected.rows]
        # the table alternative: the same categories, the same numbers, formatted
        assert _headers(panel) == expected.headers
        assert _cells(panel) == expected.rows
        assert _raw(panel) == expected.raw
        assert panel.table_model.values() == expected.raw
        assert panel.table_caption.text() == expected.title


def test_the_chart_adapter_really_stores_the_values(app_context: AppContext, qtbot: QtBot) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    chart = _need(_panel(page, "personnel_valid_by_level").chart_view.chart())
    assert read_back(chart) == (("A", "B", "C"), (("Valid certificates", (3.0, 1.0, 0.0)),))
    # a participant count that is not recorded has no bar, stays None, and the legend says so
    exercises = _panel(page, "exercises_by_edition")
    assert read_back(_need(exercises.chart_view.chart()))[1] == (
        ("Participants (not recorded: DEMO-EX-25)", (40.0, None)),
        ("Countries", (3.0, 2.0)),
    )


def test_budget_charts_are_one_per_currency_and_never_mixed(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    keys = [panel.key for panel in page.chart_panels() if panel.key.startswith("budget_")]
    assert keys == ["budget_BRL", "budget_USD"]
    for key, symbol in (("budget_BRL", "R$"), ("budget_USD", "US$")):
        cells = [cell for row in _cells(_panel(page, key)) for cell in row[1:]]
        assert all(cell.startswith(symbol) for cell in cells)


def test_the_table_toggle_switches_views_and_keeps_its_state(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    panel = _panel(page, "budget_BRL")
    assert panel.toggle.text() == "Show as table"
    assert not panel.table_shown()
    assert panel.table_caption.isHidden()
    panel.toggle.setChecked(True)
    assert panel.table_shown()
    assert not panel.table_caption.isHidden()
    assert not _panel(page, "personnel_valid_by_level").table_shown()

    app_context.set_as_of(EARLIER)  # the panel is kept and still shows its table
    assert _panel(page, "budget_BRL") is panel
    assert panel.table_shown()
    panel.toggle.setChecked(False)
    assert not panel.table_shown()


def test_an_empty_database_shows_no_data_charts_and_only_no_target_or_no_data(
    app_context: AppContext, qtbot: QtBot
) -> None:
    page = _page(app_context, qtbot)
    assert page.tile_widgets
    assert {t.status_label.text() for t in page.tile_widgets} <= {"No target", "No data"}
    assert page.alert_labels[Severity.CRITICAL].text() == "Critical alerts: 0"
    assert [p.key for p in page.chart_panels()] == [
        "personnel_valid_by_level",
        "infrastructure_availability",
        "exercises_by_edition",
    ]
    for panel in page.chart_panels():
        assert panel.chart_view.chart() is None
        label = panel.chart_view.findChild(QLabel, "chart_no_data")
        assert label is not None
        assert not label.isHidden()
        assert label.text() == "No data"
        assert panel.table_model.rowCount() == 0


# --------------------------------------------------------------------------- recompute


def test_changing_the_as_of_date_updates_tiles_charts_and_counts(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    assert _tile(page, "PERS_CERT_VALID", "level=B").status_label.text() == "Critical"

    app_context.set_as_of(EARLIER)
    assert page.as_of_label.text() == "Readiness as of 06/15/2025"
    assert len(page.tile_widgets) == 38
    valid_b = _tile(page, "PERS_CERT_VALID", "level=B")
    assert (valid_b.value_label.text(), valid_b.status_label.text()) == ("2", "Warning")
    overdue = _tile(page, "INFRA_MAINT_OVERDUE", "type=DEMO-TYPE-A")
    assert (overdue.value_label.text(), overdue.status_label.text()) == ("1", "Warning")
    assert _tile(page, "EX_LAST_PARTICIPANTS", "kind=CBRAMED").value_label.text() == "40"
    rate = _tile(page, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA")
    assert (rate.value_label.text(), rate.status_label.text()) == ("75.0%", "OK")
    assert page.alert_labels[Severity.CRITICAL].text() == "Critical alerts: 2"
    assert page.alert_labels[Severity.WARNING].text() == "Warning alerts: 2"
    assert page.alert_labels[Severity.INFO].text() == "Information alerts: 1"

    # no USD entry in 2025: that panel is gone; the others show the earlier figures
    assert [p.key for p in page.chart_panels()] == [
        "personnel_valid_by_level",
        "infrastructure_availability",
        "exercises_by_edition",
        "budget_BRL",
    ]
    assert page.chart_panel("budget_USD") is None
    assert _raw(_panel(page, "personnel_valid_by_level")) == ((3.0, 2.0, 0.0),)
    assert _cells(_panel(page, "exercises_by_edition")) == [["DEMO-EX-24", "40", "3"]]
    assert _cells(_panel(page, "budget_BRL")) == [["DIRSA", "R$800.00", "R$600.00"]]
    assert _panel(page, "budget_BRL").data().title == (
        "Allocated and executed by funding source, BRL, fiscal year 2025"
    )

    app_context.set_as_of(AS_OF)  # and back again, the USD panel returns
    assert [p.key for p in page.chart_panels()] == list(CHARTS_AS_OF)
    assert _cells(_panel(page, "budget_USD")) == CHARTS_AS_OF["budget_USD"].rows


def test_a_data_change_is_shown_and_nothing_is_cached(
    app_context: AppContext, qtbot: QtBot
) -> None:
    entry = _seed(app_context)
    page = _page(app_context, qtbot)
    assert _cells(_panel(page, "budget_BRL"))[0] == ["DIRSA", "R$1,000.00", "R$250.00"]

    _need(app_context.services.budget).add_execution(entry, "2026-03-01", 5_000)
    app_context.notify_data_changed()
    assert _cells(_panel(page, "budget_BRL"))[0] == ["DIRSA", "R$1,000.00", "R$300.00"]
    rate = _tile(page, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA")
    assert rate.value_label.text() == "30.0%"
    assert rate.context_label.text() == "Executed R$300.00 of R$1,000.00 allocated"

    _need(app_context.services.budget).add_execution(entry, "2026-03-02", 5_000)
    page.refresh()  # a direct refresh reads again as well
    assert _cells(_panel(page, "budget_BRL"))[0][2] == "R$350.00"


# --------------------------------------------------------------------------- languages


def test_texts_and_numbers_follow_a_language_switch(app_context: AppContext, qtbot: QtBot) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    manager = app_context.translator_manager
    horizontal = Qt.Orientation.Horizontal

    manager.set_language("pt_BR")
    qtbot.waitUntil(
        lambda: _tile(page, "PERS_CERT_VALID", "level=B").status_label.text() == "Cr\u00edtico"
    )
    assert page.as_of_label.text() == "Prontid\u00e3o em 05/03/2026"
    assert page.snapshot_action.text() == "Registrar instant\u00e2neo"
    assert _tile(page, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA").value_label.text() == "25,0%"
    assert _tile(page, "PERS_CERT_VALID", "level=A").status_label.text() == "Sem meta"
    assert _tile(page, "EX_LAST_PARTICIPANTS", "kind=CBRAMED").status_label.text() == "Sem dados"
    budget = _panel(page, "budget_BRL")
    assert _cells(budget)[0] == ["DIRSA", f"R${NBSP}1.000,00", f"R${NBSP}250,00"]
    assert budget.table_model.headerData(0, horizontal) == "Fonte de recursos"
    assert budget.toggle.text() == "Mostrar como tabela"
    assert page.alert_labels[Severity.CRITICAL].text() == "Alertas cr\u00edticos: 3"
    assert budget.table_model.values() == CHARTS_AS_OF["budget_BRL"].raw  # numbers do not change

    manager.set_language("es_ES")
    qtbot.waitUntil(lambda: page.as_of_label.text() == "Preparaci\u00f3n al 05/03/2026")
    assert _tile(page, "BUD_EXEC_RATE", "currency=BRL;source=DIRSA").value_label.text() == (
        f"25,0{NBSP}%"
    )
    expected_row = ["DIRSA", f"1000,00{NBSP}R$", f"250,00{NBSP}R$"]
    assert _cells(_panel(page, "budget_BRL"))[0] == expected_row
    assert _panel(page, "budget_BRL").data().title == (
        "Asignado y ejecutado por fuente de financiaci\u00f3n, BRL, ejercicio 2026"
    )

    manager.set_language("en_US")
    qtbot.waitUntil(lambda: page.as_of_label.text() == "Readiness as of 03/05/2026")
    assert _cells(_panel(page, "budget_BRL"))[0] == ["DIRSA", "R$1,000.00", "R$250.00"]
    assert page.snapshot_action.text() == "Record snapshot"


def test_the_page_title_follows_the_language(app_context: AppContext) -> None:
    assert page_title() == "Dashboard"
    app_context.translator_manager.set_language("pt_BR")
    assert page_title() == "Painel"
    app_context.translator_manager.set_language("es_ES")
    assert page_title() == "Panel"


# --------------------------------------------------------------------------- snapshot action


def test_the_snapshot_action_is_disabled_without_a_snapshot_service(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    app_context.services.snapshots = None
    page = _page(app_context, qtbot)
    assert page.snapshot_action.text() == "Record snapshot"
    assert not page.snapshot_action.isEnabled()
    page.record_snapshot()  # nothing to call, nothing shown
    assert fake_prompts.calls == []


def test_recording_a_snapshot_for_today_uses_the_manual_origin(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _seed(app_context)
    snapshots = _attach_snapshots(app_context)
    page = _page(app_context, qtbot)
    assert page.snapshot_action.isEnabled()
    assert page.snapshot_action in app_context.edit_targets()

    with qtbot.waitSignal(app_context.data_changed, timeout=1000):
        page.snapshot_action.trigger()

    (view,) = snapshots.list_snapshots()
    assert (view.as_of, view.origin) == (AS_OF, SnapshotOrigin.MANUAL)
    assert len(snapshots.values(view.id)) == 40  # one value row per indicator and dimension
    assert fake_prompts.calls_of("confirm") == []
    (info,) = fake_prompts.calls_of("info")
    assert info.title == "Record snapshot"
    assert info.text == "Snapshot recorded for 03/05/2026 (origin: manual)."
    assert fake_prompts.calls_of("warning") == []


def test_a_snapshot_of_a_past_date_asks_first_and_is_marked_retroactive(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _seed(app_context)
    snapshots = _attach_snapshots(app_context)
    page = _page(app_context, qtbot)
    app_context.set_as_of(date(2026, 3, 1))

    page.snapshot_action.trigger()  # the fake answers "no" to the question
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == "Record a retroactive snapshot for 03/01/2026?"
    assert snapshots.list_snapshots() == []
    assert fake_prompts.calls_of("info") == []

    fake_prompts.script("confirm", True)
    page.snapshot_action.trigger()
    (view,) = snapshots.list_snapshots()
    assert (view.as_of, view.origin) == (date(2026, 3, 1), SnapshotOrigin.RETROACTIVE)
    (info,) = fake_prompts.calls_of("info")
    assert info.text == "Snapshot recorded for 03/01/2026 (origin: retroactive)."


def test_a_snapshot_for_a_future_date_is_refused_with_a_translated_message(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    snapshots = _attach_snapshots(app_context)
    page = _page(app_context, qtbot)
    app_context.set_as_of(date(2026, 4, 1))
    page.snapshot_action.trigger()
    (warning,) = fake_prompts.calls_of("warning")
    assert warning.title == "Cannot save"
    assert warning.text == "A snapshot cannot be recorded for a date in the future."
    assert snapshots.list_snapshots() == []
    assert fake_prompts.calls_of("info") == []

    app_context.translator_manager.set_language("pt_BR")
    page.snapshot_action.trigger()
    assert fake_prompts.calls_of("warning")[-1].text != warning.text


def test_read_only_mode_disables_the_snapshot_action(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    snapshots = _attach_snapshots(app_context)
    app_context.read_only = True
    page = _page(app_context, qtbot)
    assert page.snapshot_action in app_context.edit_targets()
    assert not page.snapshot_action.isEnabled()
    page.snapshot_action.setEnabled(True)  # read-only mode undoes it
    assert not page.snapshot_action.isEnabled()
    page.refresh()
    assert not page.snapshot_action.isEnabled()

    page.record_snapshot()  # even a direct call writes nothing
    assert snapshots.list_snapshots() == []
    assert fake_prompts.calls == []


# --------------------------------------------------------------------------- without services


def test_the_page_builds_without_a_dashboard_service(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    app_context.services.dashboard = None
    app_context.services.snapshots = None
    page = _page(app_context, qtbot)
    assert page.tile_widgets == []
    assert page.chart_panels() == []
    assert not page.empty_label.isHidden()
    assert page.empty_label.text() == "No database is open."
    assert page.scroll_area.isHidden()
    assert not page.snapshot_action.isEnabled()
    assert fake_prompts.calls == []
    app_context.set_as_of(EARLIER)  # nothing to recompute, nothing breaks
    app_context.notify_data_changed()
    assert page.as_of_label.text() == "Readiness as of 06/15/2025"


def test_a_closed_database_leaves_the_page_empty_and_a_language_switch_raises_nothing(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _seed(app_context)
    page = _page(app_context, qtbot)
    assert page.tile_widgets

    conn = _need(app_context.conn)  # what AppHandle.close_database does
    conn.close()
    app_context.conn = None
    assert app_context.services.dashboard is None
    assert app_context.services.snapshots is None

    # Qt posts the LanguageChange event; it is delivered while the loop runs. pytest-qt fails
    # the test when a slot or an event handler raised.
    app_context.translator_manager.set_language("pt_BR")
    app_context.translator_manager.set_language("en_US")
    qtbot.wait(50)
    qtbot.waitUntil(lambda: page.empty_label.text() == "No database is open.")
    assert not page.empty_label.isHidden()
    assert page.tile_widgets == []
    assert page.chart_panels() == []
    assert not page.snapshot_action.isEnabled()
    page.record_snapshot()  # nothing to call


def _corrupt_setting(context: AppContext) -> None:
    """A stored setting that no longer validates (what a restored older backup can leave)."""
    assert context.conn is not None
    context.conn.execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)",
        ("config.cert_warning_days", "not json"),
    )


def test_an_unreadable_setting_is_explained_in_the_page_and_never_raises(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    """P6-01: every as-of change, data change and language switch used to raise from a slot."""
    _seed(app_context)
    page = _page(app_context, qtbot)
    assert page.tile_widgets
    assert page.empty_label.isHidden()

    _corrupt_setting(app_context)
    app_context.notify_data_changed()  # raised ServiceError(CORRUPT_SETTING) inside the slot
    app_context.set_as_of(EARLIER)
    assert not page.empty_label.isHidden()
    assert page.empty_label.text() == "A stored setting cannot be read."
    assert page.tile_widgets == []
    assert page.chart_panels() == []
    assert page.scroll_area.isHidden()
    assert page.as_of_label.text() == "Readiness as of 06/15/2025"
    assert fake_prompts.calls == []  # a message in the page, not a dialog

    app_context.translator_manager.set_language("pt_BR")
    portuguese = "N\u00e3o foi poss\u00edvel ler uma configura\u00e7\u00e3o armazenada."
    qtbot.waitUntil(lambda: page.empty_label.text() == portuguese)
    app_context.translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: page.empty_label.text() == "No se puede leer un ajuste almacenado.")

    assert app_context.conn is not None  # repaired: the page shows the data again
    app_context.conn.execute("DELETE FROM setting WHERE key = 'config.cert_warning_days'")
    app_context.notify_data_changed()
    assert page.empty_label.isHidden()
    assert page.tile_widgets


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_unreadable_setting_message_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    pseudo_context.translator_manager.set_language(lang)
    page = _page(pseudo_context, qtbot)
    _corrupt_setting(pseudo_context)

    pseudo_context.notify_data_changed()

    assert not page.empty_label.isHidden()
    assert page.empty_label.text().startswith("\u27e6")  # a translated text, not a bare code
    assert_fully_translated(page, lang)


def test_a_language_switch_reads_the_services_once(
    app_context: AppContext, monkeypatch: pytest.MonkeyPatch, qtbot: QtBot
) -> None:
    """P6-13: the signal and the posted LanguageChange event both used to read everything."""
    _seed(app_context)
    page = _page(app_context, qtbot)
    service = _need(app_context.services.dashboard)
    real = service.data
    calls: list[date] = []

    def counting(as_of: date) -> DashboardData:
        calls.append(as_of)
        return real(as_of)

    monkeypatch.setattr(service, "data", counting)

    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: page.as_of_label.text() == "Prontid\u00e3o em 05/03/2026")
    qtbot.wait(100)  # the posted LanguageChange event is delivered as well

    assert calls == [AS_OF]
    assert _tile(page, "PERS_CERT_VALID", "level=B").status_label.text() == "Cr\u00edtico"


def test_the_dashboard_evaluates_the_indicators_once(
    app_context: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P6-13: the tiles and the alert counts share one evaluation."""
    _seed(app_context)
    indicators = _need(app_context.services.indicators)
    real = indicators.evaluate
    calls: list[date] = []

    def counting(as_of: date) -> list[IndicatorReading]:
        calls.append(as_of)
        return real(as_of)

    monkeypatch.setattr(indicators, "evaluate", counting)

    data = _need(app_context.services.dashboard).data(AS_OF)

    assert calls == [AS_OF]
    assert data.alert_counts[Severity.CRITICAL] == 3  # the counts are still right


def test_the_factories_work_without_any_service(app_context: AppContext, qtbot: QtBot) -> None:
    for name in (
        "personnel",
        "infrastructure",
        "exercises",
        "budget",
        "indicators",
        "alerts",
        "config",
        "dashboard",
    ):
        setattr(app_context.services, name, None)
    widget = create_page(app_context)
    qtbot.addWidget(widget)
    assert isinstance(widget, DashboardPage)
    assert page_title() == "Dashboard"
    assert widget.tile_widgets == []


# --------------------------------------------------------------------------- pseudo-locale walk


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_page_is_fully_translated_in_each_pseudo_language(
    pseudo_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    _seed(pseudo_context)
    _attach_snapshots(pseudo_context)
    page = _page(pseudo_context, qtbot)
    for panel in page.chart_panels():
        panel.toggle.setChecked(True)  # the table views, their headers and captions
    assert_fully_translated(page, "pt_BR")
    assert page.tile_widgets  # not vacuous
    assert page.chart_panels()

    pseudo_context.translator_manager.set_language(lang)
    qtbot.waitUntil(lambda: not find_untranslated(page, lang), timeout=3000)
    assert_fully_translated(page, lang)
    for panel in page.chart_panels():
        panel.toggle.setChecked(False)
    assert_fully_translated(page, lang)


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_empty_page_and_the_page_without_services_are_translated(
    pseudo_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    pseudo_context.translator_manager.set_language(lang)
    empty = _page(pseudo_context, qtbot)
    assert_fully_translated(empty, lang)  # the charts show the translated "No data"

    pseudo_context.services.dashboard = None
    bare = _page(pseudo_context, qtbot)
    assert_fully_translated(bare, lang)
    assert not bare.empty_label.isHidden()


def test_the_walk_rejects_mixed_and_plain_texts_on_this_page(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    _seed(pseudo_context)
    page = _page(pseudo_context, qtbot)
    assert find_untranslated(page, "pt_BR") == []

    page.as_of_label.setText(page.as_of_label.text() + " extra")  # translated + hard-coded
    assert [item.kind for item in find_untranslated(page)] == ["label"]
    page.refresh()
    assert find_untranslated(page) == []

    # a data widget is exempt from its own texts but not from its accessible name
    view = _panel(page, "budget_BRL").chart_view.findChild(QWidget, "chart_view")
    assert view is not None
    view.setAccessibleName("Plain title")
    assert [item.kind for item in find_untranslated(page)] == ["accessible name"]


def test_the_titles_are_translated(pseudo_context: AppContext) -> None:
    assert page_title() == "\u27e6Dashboard\u27e7"


# --------------------------------------------------------------------------- labels

INDICATORS = {
    "PERS_CERT_VALID",
    "PERS_CERT_EXPIRING",
    "PERS_RETRAINING_NEEDED",
    "PERS_DEGREE",
    "PERS_TRAINING_12M",
    "INFRA_AVAILABLE",
    "INFRA_MAINT_OVERDUE",
    "EX_LAST_PARTICIPANTS",
    "EX_LAST_COUNTRIES",
    "EX_DAYS_SINCE_LAST",
    "BUD_EXEC_RATE",
}
SERIES_KEYS = (
    "valid",
    "available",
    "in_service",
    "participants",
    "countries",
    "allocated",
    "executed",
)
CHART_KEYS = (
    "personnel_valid_by_level",
    "infrastructure_availability",
    "exercises_by_edition",
    "budget_BRL",
)


def _all_labels() -> dict[str, str]:
    """Every label of the module in the current language, by a descriptive name."""
    found: dict[str, str] = {}
    for code in sorted(labels.INDICATOR_CODES):
        found[f"name {code}"] = labels.indicator_name(code)
        found[f"unit {code}"] = labels.unit_label(code, "COUNT")
    for kind in UnitKind:
        found[f"unit kind {kind.value}"] = labels.unit_label("UNKNOWN", kind.value)
    for module in Module:
        found[f"module {module.value}"] = labels.module_title(module.value)
    for status in IndicatorStatus:
        found[f"status {status.value}"] = labels.status_label(status.value)
    for severity in Severity:
        found[f"alert {severity.value}"] = labels.alert_text(severity.value, 2, "en_US")
    for key in SERIES_KEYS:
        found[f"series {key}"] = labels.series_label(key)
    for key in CHART_KEYS:
        spec = ChartSpec(key, (), (), UnitKind.COUNT, {"currency": "BRL", "fiscal_year": "2026"})
        found[f"title {key}"] = labels.chart_title(spec)
        found[f"header {key}"] = labels.category_header(key)
    found["unit count"] = labels.chart_unit(ChartSpec("x", (), (), UnitKind.COUNT, {}))
    for origin in labels.ORIGINS:
        found[f"origin {origin}"] = labels.origin_label(origin)
    for code in labels.ALL_ERROR_CODES:
        found[f"error {code}"] = labels.error_label(code)
    found["thresholds none"] = labels.thresholds_text(_plain_tile(), "en_US")
    return found


def _plain_tile() -> Tile:
    return Tile(
        code="PERS_CERT_VALID",
        dimension="level=A",
        dimension_parts={"level": "A"},
        module=Module.PERSONNEL,
        unit=UnitKind.COUNT,
        direction=Direction.HIGHER_IS_BETTER,
        value=1.0,
        status=IndicatorStatus.NO_TARGET,
        warning_value=None,
        critical_value=None,
        context={},
    )


def test_every_code_has_a_label_in_all_languages(app_context: AppContext) -> None:
    found: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        found[lang] = _all_labels()
    assert set(labels.INDICATOR_CODES) == INDICATORS
    assert set(labels.ORIGINS) == {"manual", "monthly", "report", "retroactive"}
    assert {"READ_ONLY", "AS_OF_IN_FUTURE", "ORIGIN_NOT_ALLOWED"} <= set(labels.ALL_ERROR_CODES)
    english = found["en_US"]
    assert len(english) > 60
    for lang in LANGUAGES:
        assert set(found[lang]) == set(english)
        for name, text in found[lang].items():
            assert text.strip(), (lang, name)
            assert "%1" not in text and "%2" not in text, (lang, name)
    for name, text in english.items():
        if not name.startswith(("origin ", "status OK")):  # these read the same as their code
            assert text != name.split(" ", 1)[1], name
    for lang in ("pt_BR", "es_ES"):
        for name, text in found[lang].items():
            assert text != english[name], (lang, name)


def test_the_status_texts_of_the_five_statuses_are_distinct(app_context: AppContext) -> None:
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        texts = [labels.status_label(status.value) for status in IndicatorStatus]
        assert len(set(texts)) == 5
    assert texts == ["Adecuado", "Advertencia", "Cr\u00edtico", "Sin meta", "Sin datos"]


def test_an_unknown_code_is_shown_as_itself(app_context: AppContext) -> None:
    names = labels.DisplayNames("en_US")
    assert labels.indicator_name("NOT_A_CODE") == "NOT_A_CODE"
    assert labels.status_label("NOT_A_STATUS") == "NOT_A_STATUS"
    assert labels.unit_label("NOT_A_CODE", "NOT_A_UNIT") == "NOT_A_UNIT"
    assert labels.module_title("NOT_A_MODULE") == "NOT_A_MODULE"
    assert labels.series_label("not_a_series") == "not_a_series"
    assert labels.origin_label("not_an_origin") == "not_an_origin"
    assert labels.error_label("NOT_A_CODE") == "NOT_A_CODE"
    assert labels.alert_text("NOT_A_SEVERITY", 2, "en_US") == "NOT_A_SEVERITY"
    assert labels.chart_title(ChartSpec("other_chart", (), (), UnitKind.COUNT, {})) == "other_chart"
    assert labels.category_label("other_chart", "CODE-1", names) == "CODE-1"
    assert labels.category_label("infrastructure_availability", "no_such_type", names) == (
        "no_such_type"
    )
    assert labels.category_label("budget_BRL", "NO_SUCH_SOURCE", names) == "NO_SUCH_SOURCE"
    assert labels.dimension_text("X", {"foo": "bar"}, names) == "foo: bar"
    assert labels.dimension_text("X", {"type": "no_such_type"}, names) == "Type no_such_type"
    assert labels.dimension_text("X", {"source": "NO_SUCH"}, names) == "Source NO_SUCH"
    assert labels.dimension_text("X", {}, names) == ""
    assert QCoreApplication.translate("Dashboard", "Dashboard") == "Dashboard"


def test_the_number_helpers_format_counts_and_money() -> None:
    assert count_text(None, "en_US") == "-"
    assert count_text(3.0, "en_US") == "3"
    assert count_text(1234.0, "pt_BR") == "1.234"
    assert count_text(2.5, "pt_BR") == "2,5"
    assert major_money_text(None, "BRL", "en_US") == "-"
    assert major_money_text(1000.0, "BRL", "en_US") == "R$1,000.00"
    assert major_money_text(250.5, "USD", "en_US") == "US$250.50"
    assert major_money_text(250.5, "EUR", "pt_BR") == f"\u20ac{NBSP}250,50"
    assert major_money_text(5.0, "XXX", "en_US") == "5 XXX"
