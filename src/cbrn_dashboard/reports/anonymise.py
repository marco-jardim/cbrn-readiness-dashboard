# SPDX-License-Identifier: GPL-3.0-or-later
"""Anonymisation of a report document (PLAN.md T8.5; A11, R13, K03, Q10).

:func:`anonymise` is a pure function: it never mutates its input and returns a new document of the
``ANONYMISED`` variant. What it keeps and what it drops:

* COUNTS ONLY. The retraining list and the overdue-asset list are dropped; so are the operator
  label, the handling notice and, in the header, the institution and unit names (the PDF metadata
  must carry no operator label, institution name or identifier). The model holds no notes,
  descriptions or references, only codes and numbers.
* PRIMARY SUPPRESSION (A11). A cell that is personnel-derived AND a count and whose value is in
  ``0 .. threshold - 1`` (zero included) becomes suppressed: ``suppressed=True`` and ``value=None``.
  The renderer prints "< threshold" from ``ReportDocument.small_count_threshold``. Infrastructure,
  exercise and budget figures are never suppressed by this rule.
* SECONDARY SUPPRESSION. A total cell ``T`` declares its parts in ``total_of``. If at least one
  part of ``T`` is suppressed and ``T`` is not, ``T`` is suppressed: with exactly one suppressed
  part it would be recoverable as ``T - sum(other parts)``; with two or more, the SUM of the hidden
  parts would be revealed (and a sum of 0 or of ``n * (threshold - 1)`` fixes every part). The rule
  is applied to a fixed point, because a suppressed total can be a part of a larger total. A total
  with no suppressed part stays visible. A total that is itself suppressed together with all or
  some of its parts is consistent and needs nothing more.
* A suppressed indicator row also loses its status and thresholds (a status such as CRITICAL
  bounds the value), shown as ``NO_DATA`` with no thresholds.
* CHARTS are rebuilt from the suppressed cells only: a suppressed cell has no value, and a category
  whose cells are ALL suppressed is removed from the chart together with those cells, so no value,
  label or category of a suppressed cell remains.

Limits (recorded as residual risk Q10): the rule works on the declared ``total_of`` structure only,
so relations that are not declared (for example active staff against valid certificates) are not
considered, and DIFFERENCING between successive reports (the same population read at two dates)
is NOT prevented.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.reports.model import (
    AlertCountRow,
    Cell,
    IndicatorRow,
    KeyFigureGroup,
    ReportChart,
    ReportDocument,
    ReportHeader,
    ReportSeries,
    ReportVariant,
)

__all__ = ["anonymise"]


def _suppressed(cell: Cell) -> Cell:
    return replace(cell, value=None, suppressed=True)


def _primary(cell: Cell, threshold: int) -> Cell:
    """Primary suppression of one cell (zero included)."""
    if cell.suppressed:
        return _suppressed(cell)
    if (
        cell.personnel_derived
        and cell.is_count
        and cell.value is not None
        and 0 <= cell.value < threshold
    ):
        return _suppressed(cell)
    return cell


def _all_cells(document: ReportDocument) -> Iterator[Cell]:
    for group in document.key_figures:
        yield from group.cells
    for row in document.indicators:
        yield row.value
    for alert in document.alert_summary:
        yield alert.cell
    for chart in document.charts:
        for series in chart.series:
            yield from series.cells


def _suppression_state(document: ReportDocument) -> dict[str, Cell]:
    """The cells of the document by key after primary and secondary suppression."""
    threshold = document.small_count_threshold
    state: dict[str, Cell] = {}
    for cell in _all_cells(document):
        if cell.key not in state:
            state[cell.key] = _primary(cell, threshold)
    changed = True
    while changed:
        changed = False
        for key, cell in list(state.items()):
            if cell.suppressed or not cell.total_of:
                continue
            if any(state[part].suppressed for part in cell.total_of if part in state):
                state[key] = _suppressed(cell)
                changed = True
    return state


def _indicator(row: IndicatorRow, cell: Cell) -> IndicatorRow:
    if not cell.suppressed:
        return replace(row, value=cell)
    return replace(
        row, value=cell, status=IndicatorStatus.NO_DATA, warning_value=None, critical_value=None
    )


def _chart(chart: ReportChart, state: dict[str, Cell]) -> ReportChart:
    """The chart from the suppressed cells; categories with only suppressed cells are removed."""
    kept = [
        index
        for index in range(len(chart.categories))
        if not chart.series or not all(state[s.cells[index].key].suppressed for s in chart.series)
    ]
    return replace(
        chart,
        categories=tuple(chart.categories[i] for i in kept),
        series=tuple(
            ReportSeries(s.key, tuple(state[s.cells[i].key] for i in kept)) for s in chart.series
        ),
    )


def anonymise(document: ReportDocument) -> ReportDocument:
    """The anonymised, small-count-suppressed copy of ``document`` (the input is not changed)."""
    state = _suppression_state(document)
    header = ReportHeader(
        institution_name="",
        unit_name="",
        as_of=document.header.as_of,
        generated_at_utc=document.header.generated_at_utc,
        app_version=document.header.app_version,
        operator_label="",
    )
    return ReportDocument(
        variant=ReportVariant.ANONYMISED,
        header=header,
        handling_notice="",
        is_demo=document.is_demo,
        small_count_threshold=document.small_count_threshold,
        key_figures=tuple(
            KeyFigureGroup(group.module, tuple(state[cell.key] for cell in group.cells))
            for group in document.key_figures
        ),
        indicators=tuple(_indicator(row, state[row.value.key]) for row in document.indicators),
        alert_summary=tuple(
            AlertCountRow(alert.severity, state[alert.cell.key]) for alert in document.alert_summary
        ),
        charts=tuple(_chart(chart, state) for chart in document.charts),
        retraining=(),
        overdue_assets=(),
        preliminary_notice_code=document.preliminary_notice_code,
    )
