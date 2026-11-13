# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendering fixes of the Phase 8 review: dimension labels, day counts, chart locale, alert rows."""

from dataclasses import replace
from pathlib import Path

import pytest
from PySide6.QtCore import QLocale
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.indicators import Direction, IndicatorStatus, Module, UnitKind
from cbrn_dashboard.reports import pdf
from cbrn_dashboard.reports.labels import ReportTexts
from cbrn_dashboard.reports.message_keys import DEGREE_STATUS_KEYS, EXERCISE_KIND_KEYS
from cbrn_dashboard.reports.model import (
    AlertCountRow,
    AlertSource,
    Cell,
    IndicatorRow,
    ReportDocument,
)
from cbrn_dashboard.ui.shell.charts import ChartData
from tests.reports.test_report_pdf import _internal, _layout

pytestmark = pytest.mark.ui


@pytest.fixture(autouse=True)
def _application(qapp: QApplication) -> QApplication:
    return qapp


def _row(
    code: str,
    parts: tuple[tuple[str, str], ...],
    unit: UnitKind = UnitKind.COUNT,
    value: float = 12.0,
    warning: float | None = None,
    critical: float | None = None,
) -> IndicatorRow:
    dimension = ";".join(f"{name}={shown}" for name, shown in parts)
    return IndicatorRow(
        code=code,
        dimension=dimension,
        dimension_parts=parts,
        module=Module.BUDGET,  # not personnel: never suppressed
        unit=unit,
        direction=Direction.HIGHER_IS_BETTER,
        value=Cell(f"indicator:{code}:{dimension}", value, is_count=unit is UnitKind.COUNT),
        status=IndicatorStatus.NO_TARGET,
        warning_value=warning,
        critical_value=critical,
    )


def _document(*rows: IndicatorRow) -> ReportDocument:
    return replace(_internal(), indicators=rows, charts=())


# --------------------------------------------------------------------------- P8-05


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en_US", ("Master's degree", "In progress", "Other")),
        ("pt_BR", ("Mestrado", "Em andamento", "Outro")),
        ("es_ES", ("Máster", "En curso", "Otro")),
    ],
)
def test_dimension_values_are_translated_not_printed_as_codes(
    qm_dir: Path, language: str, expected: tuple[str, str, str]
) -> None:
    document = _document(
        _row("PERS_DEGREE", (("level", "master"), ("status", "in_progress"))),
        _row("EX_LAST_PARTICIPANTS", (("kind", "OTHER"),)),
    )

    text = _layout(document, language, qm_dir).text

    level, status, kind = expected
    assert level in text
    assert status in text
    assert kind in text
    for raw in ("master", "in_progress", "OTHER"):
        assert raw not in text


def test_exercise_names_and_protection_levels_stay_as_they_are(qm_dir: Path) -> None:
    document = _document(
        _row("EX_LAST_PARTICIPANTS", (("kind", "CBRAMED"),)),
        _row("PERS_CERT_VALID", (("level", "A"),)),
    )

    text = _layout(document, "pt_BR", qm_dir).text

    assert "CBRAMED" in text
    assert ": A | " in text  # the detail of the level row: the code of the protection level
    texts = ReportTexts("pt_BR", qm_dir)
    assert texts.exercise_kind("EXBRAMED") == "EXBRAMED"
    assert texts.degree_level("A") == "A"


@pytest.mark.parametrize("language", ["en_US", "pt_BR", "es_ES"])
def test_every_shared_degree_status_and_exercise_kind_has_a_label(
    qm_dir: Path, language: str
) -> None:
    texts = ReportTexts(language, qm_dir)

    for code in DEGREE_STATUS_KEYS:
        assert texts.degree_status(code) not in {"", code}
    for code in EXERCISE_KIND_KEYS:
        assert texts.exercise_kind(code) not in {"", code}


# --------------------------------------------------------------------------- P8-18 (days)


@pytest.mark.parametrize(
    ("language", "one", "many"),
    [
        ("en_US", "1 day", "730 days"),
        ("pt_BR", "1 dia", "730 dias"),
        ("es_ES", "1 día", "730 días"),
    ],
)
def test_day_counts_use_the_plural_form_of_the_language(
    qm_dir: Path, language: str, one: str, many: str
) -> None:
    document = _document(
        _row(
            "EX_DAYS_SINCE_LAST",
            (("kind", "CBRAMED"),),
            UnitKind.DAYS,
            value=730.0,
            warning=1.0,
            critical=30.0,
        )
    )

    line = next(
        line for line in _layout(document, language, qm_dir).text.splitlines() if "CBRAMED" in line
    )

    assert many in line
    assert one in line
    assert f"30 {many.split(' ', 1)[1]}" in line


# --------------------------------------------------------------------------- P8-01 (rows)


@pytest.mark.parametrize(
    ("language", "all_sources"),
    [("en_US", "All sources"), ("pt_BR", "Todas as origens"), ("es_ES", "Todos los orígenes")],
)
def test_alert_rows_name_their_source(qm_dir: Path, language: str, all_sources: str) -> None:
    document = replace(
        _internal(),
        alert_summary=(
            AlertCountRow(Severity.WARNING, Cell("alert:WARNING", 7.0)),
            AlertCountRow(
                Severity.WARNING, Cell("alert:WARNING:indicators", 1.0), AlertSource.INDICATORS
            ),
        ),
    )

    layout = _layout(document, language, qm_dir)

    texts = ReportTexts(language, qm_dir)
    lines = layout.text.splitlines()
    assert any(
        line.startswith(texts.severity("WARNING")) and all_sources in line and line.endswith("| 7")
        for line in lines
    )
    assert any(texts.alert_source("INDICATORS") in line and line.endswith("| 1") for line in lines)


@pytest.mark.parametrize("language", ["en_US", "pt_BR", "es_ES"])
def test_the_expired_certificates_cell_has_a_label(qm_dir: Path, language: str) -> None:
    texts = ReportTexts(language, qm_dir)

    label = texts.cell_label("kf:PERSONNEL:expired:B")

    assert label.endswith("B")
    assert label != "kf:PERSONNEL:expired:B"
    assert label != texts.cell_label("kf:PERSONNEL:expiring:B")


# --------------------------------------------------------------------------- P8-06


def test_charts_are_built_with_the_locale_of_the_report_not_the_ui(
    qm_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    real = pdf.render_to_image

    def spy(data: ChartData, width: int, height: int, *, locale: QLocale | None = None) -> QImage:
        seen.append("" if locale is None else locale.name())
        return real(data, width, height, locale=locale)

    monkeypatch.setattr(pdf, "render_to_image", spy)
    previous = QLocale()
    QLocale.setDefault(QLocale("en_US"))
    try:
        pdf.write_report_pdf(_internal(), tmp_path / "es.pdf", language="es_ES", qm_dir=qm_dir)
    finally:
        QLocale.setDefault(previous)

    assert seen
    assert set(seen) == {"es_ES"}
