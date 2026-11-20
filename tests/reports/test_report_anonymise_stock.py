# SPDX-License-Identifier: GPL-3.0-or-later
"""The anonymised report drops the internal-only stock content (PLAN.md T11.7, D37, Q27).

The document is built by hand from fictitious cells: per-type stock quantities and the stock chart
are ``internal_only``; the lot counts stay.
"""

from dataclasses import replace
from datetime import date

from cbrn_dashboard.domain.indicators import Direction, IndicatorStatus, Module, UnitKind
from cbrn_dashboard.reports.anonymise import anonymise
from cbrn_dashboard.reports.model import (
    Cell,
    IndicatorRow,
    KeyFigureGroup,
    ReportChart,
    ReportDocument,
    ReportHeader,
    ReportSeries,
    ReportVariant,
)

QTY_KEY = "indicator:STOCK_VALID_QTY:category=antidote;item=ANTIDOTE_CHEMICAL"
LOTS_KEY = "indicator:STOCK_LOTS_EXPIRED:category=antidote"


def _row(code: str, dimension: str, cell: Cell) -> IndicatorRow:
    parts = tuple(sorted((k, v) for k, v in (item.split("=") for item in dimension.split(";"))))
    return IndicatorRow(
        code=code,
        dimension=dimension,
        dimension_parts=parts,
        module=Module.STOCK,
        unit=UnitKind.COUNT,
        direction=Direction.HIGHER_IS_BETTER,
        value=cell,
        status=IndicatorStatus.NO_TARGET,
        warning_value=None,
        critical_value=None,
    )


def _document() -> ReportDocument:
    quantity = Cell(key=QTY_KEY, value=17.0, internal_only=True)
    lots = Cell(key=LOTS_KEY, value=1.0)
    chart_key = "chart:stock_antidotes_by_item:stock_valid:ANTIDOTE_CHEMICAL"
    chart_cells = (Cell(key=chart_key, value=17.0, internal_only=True),)
    money = Cell(key="kf:STOCK:value_valid:BRL", value=12.5, is_count=False, internal_only=True)
    return ReportDocument(
        variant=ReportVariant.INTERNAL,
        header=ReportHeader("Institution", "Unit", date(2026, 3, 5), "t", "1.1.0", "operator"),
        handling_notice="notice",
        is_demo=True,
        small_count_threshold=5,
        key_figures=(
            KeyFigureGroup(
                Module.STOCK,
                (Cell(key="kf:STOCK:lots_expired", value=1.0), money),
            ),
        ),
        indicators=(
            _row("STOCK_VALID_QTY", "category=antidote;item=ANTIDOTE_CHEMICAL", quantity),
            _row("STOCK_LOTS_EXPIRED", "category=antidote", lots),
        ),
        alert_summary=(),
        charts=(
            ReportChart(
                key="stock_antidotes_by_item",
                categories=("ANTIDOTE_CHEMICAL",),
                series=(ReportSeries("stock_valid", chart_cells),),
                unit=UnitKind.COUNT,
                parameters=(),
                internal_only=True,
            ),
        ),
        retraining=(),
        overdue_assets=(),
    )


def _all_cells(document: ReportDocument) -> list[Cell]:
    cells = [cell for group in document.key_figures for cell in group.cells]
    cells.extend(row.value for row in document.indicators)
    cells.extend(alert.cell for alert in document.alert_summary)
    cells.extend(c for chart in document.charts for s in chart.series for c in s.cells)
    return cells


def test_the_internal_report_keeps_everything() -> None:
    document = _document()
    assert len(document.indicators) == 2
    assert [chart.key for chart in document.charts] == ["stock_antidotes_by_item"]


def test_the_anonymised_report_drops_internal_only_cells_rows_and_charts() -> None:
    result = anonymise(_document())
    assert [row.code for row in result.indicators] == ["STOCK_LOTS_EXPIRED"]
    assert result.charts == ()
    [group] = result.key_figures
    assert [cell.key for cell in group.cells] == ["kf:STOCK:lots_expired"]
    assert not [cell for cell in _all_cells(result) if cell.internal_only]


def test_no_total_of_names_an_internal_only_cell() -> None:
    document = _document()
    internal = {cell.key for cell in _all_cells(document) if cell.internal_only}
    assert internal
    for variant in (document, anonymise(document)):
        kept = {cell.key for cell in _all_cells(variant)}
        for cell in _all_cells(variant):
            assert not set(cell.total_of) & internal, cell.key
        if variant.variant is ReportVariant.ANONYMISED:
            assert not kept & internal


def test_the_input_is_not_changed() -> None:
    document = _document()
    before = replace(document)
    anonymise(document)
    assert document == before
