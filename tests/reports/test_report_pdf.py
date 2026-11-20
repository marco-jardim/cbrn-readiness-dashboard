# SPDX-License-Identifier: GPL-3.0-or-later
"""PDF rendering of a report document (PLAN.md T8.6).

The documents are written by hand with fictitious data. Content is asserted on the layout (the
plain text and the chart data that the renderer builds before painting), never on pixels or on
the bytes of the PDF; the PDF itself is checked for its signature, page count, page size, the
absence of identifying strings in its bytes, and the failure behaviour.
"""

import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import date
from html import escape
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QLocale
from PySide6.QtWidgets import QApplication

from cbrn_dashboard import i18n
from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.indicators import Direction, IndicatorStatus, Module, UnitKind
from cbrn_dashboard.domain.personnel import CertStatus, PpeLevel
from cbrn_dashboard.domain.stock import LotStatus
from cbrn_dashboard.reports.anonymise import anonymise
from cbrn_dashboard.reports.labels import (
    CHART_SERIES_KEYS,
    DIMENSION_KEYS,
    INDICATOR_CODES,
    ReportTexts,
)
from cbrn_dashboard.reports.message_keys import (
    ASSET_TYPE_KEYS,
    CERT_STATUS_KEYS,
    DEGREE_LEVEL_KEYS,
    FUNDING_SOURCE_KEYS,
    LOT_STATUS_KEYS,
    PRELIMINARY_KEY,
    STOCK_CATEGORY_KEYS,
    all_shared_keys,
)
from cbrn_dashboard.reports.model import (
    AlertCountRow,
    AssetListRow,
    Cell,
    IndicatorRow,
    KeyFigureGroup,
    ReportChart,
    ReportDocument,
    ReportHeader,
    ReportSeries,
    ReportVariant,
    StaffListRow,
    StockLotListRow,
)
from cbrn_dashboard.reports.pdf import (
    REPORT_FAILED,
    ReportLayout,
    build_layout,
    document_xmp,
    write_report_pdf,
)
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.ui.shell.charts import ChartKind
from tests.i18n._ts import parse_ts

pytestmark = pytest.mark.ui

INSTITUTION = "Fictitious Institution Zeta"
UNIT = "Fictitious Unit Omega"
OPERATOR = "FIC-OPERATOR-9"
HANDLING = "Fictitious handling text KQ"
IDENTIFIER = "FIC-ID-5521"
TAG = "FIC-TAG-77"
AS_OF = date(2026, 3, 5)
GENERATED = "2026-03-05T12:00:00Z"
VERSION = "9.9.9-test"
THRESHOLD = 5
NOTICE_EN = "Preliminary version \u2014 indicators not institutionally validated."

#: Strings that identify the fixture's institution, operator or records.
FORBIDDEN = (INSTITUTION, UNIT, OPERATOR, HANDLING, IDENTIFIER, TAG, "Fictitious", "FIC-")


@pytest.fixture(autouse=True)
def _application(qapp: QApplication) -> QApplication:
    return qapp


# --------------------------------------------------------------------------- fixtures


def _personnel_cells() -> tuple[Cell, ...]:
    degrees = (
        Cell("kf:PERSONNEL:degree_completed:master", 40.0, personnel_derived=True),
        Cell("kf:PERSONNEL:degree_completed:doctorate", 3.0, personnel_derived=True),
    )
    return (
        Cell("kf:PERSONNEL:active_staff", 1234.0, personnel_derived=True),
        Cell("kf:PERSONNEL:valid:A", 2000.0, personnel_derived=True),
        Cell("kf:PERSONNEL:valid:B", 3.0, personnel_derived=True),
        Cell("kf:PERSONNEL:valid:C", 0.0, personnel_derived=True),
        *degrees,
        Cell(
            "kf:PERSONNEL:degree_completed_total",
            43.0,
            personnel_derived=True,
            total_of=tuple(cell.key for cell in degrees),
        ),
    )


def _indicators() -> tuple[IndicatorRow, ...]:
    return (
        IndicatorRow(
            code="PERS_CERT_VALID",
            dimension="level=B",
            dimension_parts=(("level", "B"),),
            module=Module.PERSONNEL,
            unit=UnitKind.COUNT,
            direction=Direction.HIGHER_IS_BETTER,
            value=Cell("indicator:PERS_CERT_VALID:level=B", 3.0, personnel_derived=True),
            status=IndicatorStatus.WARNING,
            warning_value=10.0,
            critical_value=5.0,
        ),
        IndicatorRow(
            code="BUD_EXEC_RATE",
            dimension="",
            dimension_parts=(),
            module=Module.BUDGET,
            unit=UnitKind.RATIO,
            direction=Direction.HIGHER_IS_BETTER,
            value=Cell("indicator:BUD_EXEC_RATE:", 0.4567, is_count=False),
            status=IndicatorStatus.OK,
            warning_value=None,
            critical_value=None,
        ),
    )


def _charts() -> tuple[ReportChart, ...]:
    personnel = ReportChart(
        key="personnel_valid_by_level",
        categories=("A", "B", "C"),
        series=(
            ReportSeries(
                "valid",
                (
                    Cell("chart:p:valid:A", 2000.0, personnel_derived=True),
                    Cell("chart:p:valid:B", 3.0, personnel_derived=True),
                    Cell("chart:p:valid:C", 0.0, personnel_derived=True),
                ),
            ),
        ),
        unit=UnitKind.COUNT,
        parameters=(),
    )
    infrastructure = ReportChart(
        key="infrastructure_availability",
        categories=("bed", "custom_type"),
        series=(
            ReportSeries("available", (Cell("chart:i:a:bed", 4.0), Cell("chart:i:a:c", 2.0))),
            ReportSeries("in_service", (Cell("chart:i:s:bed", 5.0), Cell("chart:i:s:c", 3.0))),
        ),
        unit=UnitKind.COUNT,
        parameters=(),
    )
    return (personnel, infrastructure)


def _internal(
    *, demo: bool = False, retraining: bool = True, extra_assets: int = 0
) -> ReportDocument:
    retraining_rows = (
        (StaffListRow(IDENTIFIER, PpeLevel.B, date(2026, 4, 1), CertStatus.EXPIRED),)
        if retraining
        else ()
    )
    assets = tuple(
        AssetListRow(f"{TAG}-{index}", "bed", date(2026, 2, 1), -33)
        for index in range(extra_assets)
    )
    return ReportDocument(
        variant=ReportVariant.INTERNAL,
        header=ReportHeader(
            institution_name=INSTITUTION,
            unit_name=UNIT,
            as_of=AS_OF,
            generated_at_utc=GENERATED,
            app_version=VERSION,
            operator_label=OPERATOR,
        ),
        handling_notice=HANDLING,
        is_demo=demo,
        small_count_threshold=THRESHOLD,
        key_figures=(
            KeyFigureGroup(Module.PERSONNEL, _personnel_cells()),
            KeyFigureGroup(Module.INFRASTRUCTURE, (Cell("kf:INFRASTRUCTURE:overdue", 2.0),)),
            KeyFigureGroup(
                Module.EXERCISES,
                (Cell("kf:EXERCISES:days_since_last", 1500.0, is_count=False),),
            ),
            KeyFigureGroup(
                Module.BUDGET,
                (Cell("kf:BUDGET:allocated:BRL", 1234567.5, is_count=False),),
            ),
        ),
        indicators=_indicators(),
        alert_summary=(
            AlertCountRow(Severity.CRITICAL, Cell("alert:CRITICAL", 2.0, personnel_derived=True)),
            AlertCountRow(Severity.INFO, Cell("alert:INFO", 50.0, personnel_derived=True)),
        ),
        charts=_charts(),
        retraining=retraining_rows,
        overdue_assets=(AssetListRow(TAG, "bed", date(2026, 2, 1), -33), *assets),
    )


@pytest.fixture
def internal() -> ReportDocument:
    return _internal()


@pytest.fixture
def anonymised(internal: ReportDocument) -> ReportDocument:
    return anonymise(internal)


def _layout(document: ReportDocument, language: str, qm_dir: Path) -> ReportLayout:
    return build_layout(document, ReportTexts(language, qm_dir))


def _row(layout: ReportLayout, prefix: str) -> str:
    """The first plain-text line that starts with ``prefix``."""
    for line in layout.text.splitlines():
        if line.startswith(prefix):
            return line
    raise AssertionError(f"no line starts with {prefix!r}")


# --------------------------------------------------------------------------- content: variants


def test_internal_variant_has_the_header_the_handling_notice_and_the_lists(
    internal: ReportDocument, qm_dir: Path
) -> None:
    layout = _layout(internal, "en_US", qm_dir)

    for text in (INSTITUTION, UNIT, OPERATOR, HANDLING, IDENTIFIER, TAG):
        assert text in layout.text
        assert escape(text) in layout.html
    assert f"Handling notice: {HANDLING}" in layout.text
    assert "Staff needing retraining" in layout.text.splitlines()
    assert "Assets with overdue maintenance" in layout.text.splitlines()
    assert GENERATED in layout.text
    assert VERSION in layout.text
    assert layout.footer_notice == NOTICE_EN


def test_anonymised_variant_has_no_identifying_header_notice_or_lists(
    anonymised: ReportDocument, qm_dir: Path
) -> None:
    layout = _layout(anonymised, "en_US", qm_dir)

    for text in FORBIDDEN:
        assert text not in layout.text
        assert text not in layout.html
    assert "Handling notice" not in layout.text
    lines = layout.text.splitlines()
    assert "Staff needing retraining" not in lines
    assert "Assets with overdue maintenance" not in lines
    assert "Identifier" not in layout.text
    assert "Asset tag" not in layout.text
    assert GENERATED in layout.text  # the generation time comes from the document


def test_the_renderer_does_not_print_identifying_blocks_of_an_anonymised_document(
    internal: ReportDocument, qm_dir: Path
) -> None:
    leaky = replace(anonymise(internal), handling_notice=HANDLING, retraining=internal.retraining)
    leaky = replace(
        leaky, header=replace(leaky.header, institution_name=INSTITUTION, operator_label=OPERATOR)
    )

    layout = _layout(leaky, "en_US", qm_dir)

    for text in (INSTITUTION, OPERATOR, HANDLING, IDENTIFIER):
        assert text not in layout.text


def test_an_internal_document_without_rows_prints_its_headings_and_none(qm_dir: Path) -> None:
    document = replace(_internal(retraining=False), overdue_assets=())

    layout = _layout(document, "en_US", qm_dir)

    lines = layout.text.splitlines()
    assert lines.count("None.") == 2
    assert "Staff needing retraining" in lines


def test_internal_variant_without_handling_notice_prints_no_empty_notice(qm_dir: Path) -> None:
    layout = _layout(replace(_internal(), handling_notice=""), "en_US", qm_dir)

    assert "Handling notice" not in layout.text


# --------------------------------------------------------------------------- stock


def _with_stock(document: ReportDocument) -> ReportDocument:
    """The document with a stock group and two lots (fictitious codes)."""
    group = KeyFigureGroup(
        Module.STOCK,
        (
            Cell("kf:STOCK:lots_expired", 2.0),
            Cell("kf:STOCK:lots_expiring", 1.0),
            Cell("kf:STOCK:types_below_min", 3.0),
            Cell("kf:STOCK:value_valid:BRL", 1234.5, is_count=False, internal_only=True),
            Cell("kf:STOCK:value_expired:USD", 99.0, is_count=False, internal_only=True),
        ),
    )
    lots = (
        StockLotListRow("ANTIDOTE_CHEMICAL", "FIC-LOT-1", date(2026, 2, 1), 4, LotStatus.EXPIRED),
        StockLotListRow("FIC-OWN-TYPE", "FIC-LOT-2", date(2026, 3, 20), 1250, LotStatus.EXPIRING),
    )
    return replace(document, key_figures=(*document.key_figures, group), stock_lots=lots)


def test_the_internal_report_has_the_stock_figures_and_the_lot_section(qm_dir: Path) -> None:
    layout = _layout(_with_stock(_internal()), "en_US", qm_dir)

    lines = layout.text.splitlines()
    assert "Expired or expiring lots with stock" in lines
    assert _row(layout, "Expired lots still in stock").endswith("| 2")
    assert _row(layout, "Item types below the minimum stock").endswith("| 3")
    assert "1,234.50" in _row(layout, "Value of valid stock (BRL)")
    assert "99.00" in _row(layout, "Value of expired stock (USD)")
    first = _row(layout, "Chemical antidote | FIC-LOT-1 |")
    assert first.endswith("| 4 | Expired")
    second = _row(layout, "FIC-OWN-TYPE | FIC-LOT-2 |")  # a user type shows its code
    assert second.endswith("| 1,250 | Expiring soon")
    assert "Item type | Lot | Expires on | On hand | Status" in lines


def test_the_lot_section_is_translated_and_uses_the_stock_catalogue(qm_dir: Path) -> None:
    english = _layout(_with_stock(_internal()), "en_US", qm_dir)
    portuguese = _layout(_with_stock(_internal()), "pt_BR", qm_dir)

    row_en = _row(english, "Chemical antidote | FIC-LOT-1 |")
    row_pt = next(line for line in portuguese.text.splitlines() if "FIC-LOT-1" in line)
    assert not row_pt.startswith("Chemical antidote")
    assert not row_pt.endswith("Expired")
    assert row_pt != row_en


def test_a_stock_report_without_lots_prints_none_and_one_without_stock_no_section(
    qm_dir: Path,
) -> None:
    empty = replace(_with_stock(_internal()), stock_lots=())
    layout = _layout(empty, "en_US", qm_dir)
    lines = layout.text.splitlines()
    heading = lines.index("Expired or expiring lots with stock")
    assert lines[heading + 1] == "None."

    plain = _layout(_internal(), "en_US", qm_dir)
    assert "Expired or expiring lots with stock" not in plain.text


def test_the_anonymised_report_prints_the_stock_counts_only(qm_dir: Path) -> None:
    document = _with_stock(_internal())
    layout = _layout(anonymise(document), "en_US", qm_dir)

    assert "Expired or expiring lots with stock" not in layout.text
    assert "Value of" not in layout.text
    assert "1,234.50" not in layout.text
    assert "FIC-LOT" not in layout.text
    assert "FIC-OWN-TYPE" not in layout.text
    assert _row(layout, "Expired lots still in stock").endswith("| 2")
    assert _row(layout, "Item types below the minimum stock").endswith("| 3")

    leaky = replace(anonymise(document), stock_lots=document.stock_lots)
    assert "FIC-LOT" not in _layout(leaky, "en_US", qm_dir).text  # the renderer checks the variant


def test_the_stock_codes_have_labels_in_every_language(qm_dir: Path) -> None:
    for language in i18n.LANGUAGES:
        texts = ReportTexts(language, qm_dir)
        for code in STOCK_CATEGORY_KEYS:
            assert texts.stock_category(code) != code, (language, code)
        for code in LOT_STATUS_KEYS:
            assert texts.lot_status(code) != code, (language, code)
    assert ReportTexts("en_US", qm_dir).lot_status("EXPIRING") == "Expiring soon"
    assert ReportTexts("en_US", qm_dir).stock_category("ppe") == "PPE"
    assert ReportTexts("en_US", qm_dir).stock_category("NOPE") == "NOPE"


# --------------------------------------------------------------------------- suppression


def test_suppressed_cells_show_the_marker_and_never_a_number(
    anonymised: ReportDocument, qm_dir: Path
) -> None:
    layout = _layout(anonymised, "en_US", qm_dir)

    assert layout.suppression_marker == "< 5"
    assert _row(layout, "Valid qualifications, level B").endswith("| < 5")
    assert _row(layout, "Valid qualifications, level C").endswith("| < 5")  # a zero too
    assert _row(layout, "Completed degrees, Doctorate").endswith("| < 5")
    assert _row(layout, "Completed degrees, total").endswith("| < 5")  # secondary suppression
    assert _row(layout, "Critical").endswith("| < 5")  # the alert count
    suppressed_indicator = _row(layout, "Valid qualifications | Level: B")
    assert "< 5" in suppressed_indicator
    assert suppressed_indicator.endswith("No data")  # status and targets are gone with the value
    assert _row(layout, "Valid qualifications, level A").endswith("| 2,000")
    assert _row(layout, "Information").endswith("| 50")
    assert _row(layout, "Assets with overdue maintenance |").endswith("| 2")  # not personnel


def test_the_anonymised_variant_states_the_threshold(
    anonymised: ReportDocument, internal: ReportDocument, qm_dir: Path
) -> None:
    layout = _layout(anonymised, "en_US", qm_dir)

    assert any("below 5" in line and "< 5" in line for line in layout.text.splitlines())
    assert "below 5" not in _layout(internal, "en_US", qm_dir).text


def test_the_threshold_is_read_from_the_document(anonymised: ReportDocument, qm_dir: Path) -> None:
    layout = _layout(replace(anonymised, small_count_threshold=10), "en_US", qm_dir)

    assert layout.suppression_marker == "< 10"


def test_internal_variant_shows_the_small_numbers(internal: ReportDocument, qm_dir: Path) -> None:
    layout = _layout(internal, "en_US", qm_dir)

    assert _row(layout, "Valid qualifications, level B").endswith("| 3")
    assert _row(layout, "Valid qualifications, level C").endswith("| 0")
    assert "< 5" not in layout.text


def test_chart_data_of_the_anonymised_variant_holds_no_suppressed_cell(
    anonymised: ReportDocument, qm_dir: Path
) -> None:
    layout = _layout(anonymised, "en_US", qm_dir)

    personnel = layout.charts[0]
    assert personnel.categories == ("Level A",)
    assert [series.values for series in personnel.series] == [(2000.0,)]


def test_a_partly_suppressed_chart_category_is_flagged_and_not_drawn(qm_dir: Path) -> None:
    chart = ReportChart(
        key="infrastructure_availability",
        categories=("bed", "bay"),
        series=(
            ReportSeries(
                "available",
                (Cell("a1", 4.0), Cell("a2", None, personnel_derived=True, suppressed=True)),
            ),
            ReportSeries("in_service", (Cell("b1", 5.0), Cell("b2", 6.0))),
        ),
        unit=UnitKind.COUNT,
        parameters=(),
    )

    layout = _layout(replace(_internal(), charts=(chart,)), "en_US", qm_dir)

    data = layout.charts[0]
    assert data.categories == ("Bed", "Bay (*)")
    assert data.series[0].values == (4.0, None)
    assert data.kind is ChartKind.GROUPED_BAR
    assert "(*) At least one value" in layout.text


# --------------------------------------------------------------------------- charts


def test_internal_charts_use_translated_labels_and_codes_as_they_are(
    internal: ReportDocument, qm_dir: Path
) -> None:
    layout = _layout(internal, "en_US", qm_dir)

    assert len(layout.charts) == 2
    assert layout.charts[0].categories == ("Level A", "Level B", "Level C")
    infrastructure = layout.charts[1]
    assert infrastructure.categories == ("Bed", "custom_type")  # unknown code: as itself
    assert [series.name for series in infrastructure.series] == ["Available", "In service"]
    assert layout.html.count("chart:") == 2


def test_an_empty_chart_prints_no_data_instead_of_an_image(qm_dir: Path) -> None:
    empty = ReportChart("personnel_valid_by_level", (), (), UnitKind.COUNT, ())

    layout = _layout(replace(_internal(), charts=(empty,)), "en_US", qm_dir)

    assert layout.charts == ()
    assert "<img" not in layout.html
    assert "No data" in layout.text.splitlines()


# --------------------------------------------------------------------------- languages


def test_numbers_dates_and_money_follow_the_language_of_the_report(
    internal: ReportDocument, qm_dir: Path
) -> None:
    pt = _layout(internal, "pt_BR", qm_dir)
    en = _layout(internal, "en_US", qm_dir)

    assert _row(pt, "Pessoal ativo").endswith("| 1.234")
    assert _row(en, "Active staff").endswith("| 1,234")
    assert _row(pt, "Dias desde o último exercício |").endswith("| 1.500")
    assert _row(en, "Days since the last exercise |").endswith("| 1,500")
    assert _row(pt, "Alocado (BRL)").endswith("| R$\xa01.234.567,50")
    assert _row(en, "Allocated (BRL)").endswith("| R$1,234,567.50")
    assert "45,7%" in _row(pt, "Taxa de execução orçamentária")
    assert "45.7%" in _row(en, "Budget execution rate")
    assert _row(pt, "Data de referência").endswith("| 05/03/2026")
    assert _row(en, "As of").endswith("| 03/05/2026")


@pytest.mark.parametrize(
    ("language", "title"),
    [
        ("pt_BR", "Relatório de Prontidão QBRN"),
        ("en_US", "CBRN Readiness Report"),
        ("es_ES", "Informe de Preparación QBRN"),
    ],
)
def test_the_title_and_the_notice_are_in_the_report_language(
    internal: ReportDocument, qm_dir: Path, language: str, title: str
) -> None:
    layout = _layout(internal, language, qm_dir)

    assert title in layout.title
    assert layout.text.splitlines()[0] == title
    assert layout.language == language
    assert layout.footer_notice
    if language != "en_US":
        assert layout.footer_notice != NOTICE_EN
    assert "%1" in layout.page_template
    assert "%2" in layout.page_template


@pytest.mark.parametrize("language", i18n.LANGUAGES)
def test_every_catalogue_of_the_renderer_is_found(qm_dir: Path, language: str) -> None:
    assert ReportTexts(language, qm_dir).missing_catalogues == ()


def test_a_missing_catalogue_folder_falls_back_to_the_english_source(tmp_path: Path) -> None:
    texts = ReportTexts("pt_BR", tmp_path)

    assert texts.missing_catalogues
    assert texts.module("PERSONNEL") == "Personnel"
    assert texts.asset_type("bed") == "Bed"


@pytest.mark.parametrize("language", ["pt_BR", "es_ES", "en_US"])
def test_every_label_code_has_a_translation(qm_dir: Path, language: str) -> None:
    texts = ReportTexts(language, qm_dir)
    english = ReportTexts("en_US", qm_dir)

    owned = {
        "module": [member.value for member in Module],
        "indicator_status": [member.value for member in IndicatorStatus],
        "severity": [member.value for member in Severity],
        "indicator": list(INDICATOR_CODES),
        "series_name": list(CHART_SERIES_KEYS),
        "dimension_name": list(DIMENSION_KEYS),
    }
    for method, codes in owned.items():
        for code in codes:
            label = getattr(texts, method)(code)
            assert label.strip(), (method, code)
            assert label != code, (method, code)
            if language != "en_US":
                assert label != getattr(english, method)(code), (language, method, code)

    shared = {
        "cert_status": CERT_STATUS_KEYS,
        "degree_level": DEGREE_LEVEL_KEYS,
        "asset_type": ASSET_TYPE_KEYS,
        "funding_source": FUNDING_SOURCE_KEYS,
    }
    for method, keys in shared.items():
        for code in keys:
            label = getattr(texts, method)(code)
            assert label.strip(), (method, code)
            assert label != code, (method, code)
    assert texts.preliminary_notice("PRELIMINARY").strip()


def test_unknown_codes_are_shown_as_themselves(qm_dir: Path) -> None:
    texts = ReportTexts("pt_BR", qm_dir)

    assert texts.module("NOPE") == "NOPE"
    assert texts.indicator("X_Y") == "X_Y"
    assert texts.indicator_status("?") == "?"
    assert texts.severity("?") == "?"
    assert texts.asset_type("user_type") == "user_type"
    assert texts.funding_source("DIRSA") == "DIRSA"
    assert texts.cert_status("?") == "?"
    assert texts.cell_label("not-a-key") == "not-a-key"
    assert texts.cell_label("kf:PERSONNEL:unknown") == "kf:PERSONNEL:unknown"
    assert texts.preliminary_notice("OTHER") == "OTHER"


@pytest.mark.parametrize("language", i18n.LANGUAGES)
def test_the_shared_message_keys_exist_in_the_ui_catalogues(language: str) -> None:
    for context, source in all_shared_keys():
        area = context.lower()
        catalogue = parse_ts(i18n.catalogue_path(area, language))
        found = [m for m in catalogue.messages if m.context == context and m.source == source]
        assert len(found) == 1, (area, source)
        assert found[0].translations[0].strip()
    assert PRELIMINARY_KEY in all_shared_keys()


# --------------------------------------------------------------------------- demo marker


@pytest.mark.parametrize("variant", list(ReportVariant))
def test_the_demo_marker_is_in_both_variants_and_the_title_says_demo(
    qm_dir: Path, variant: ReportVariant
) -> None:
    demo = _internal(demo=True)
    real = _internal(demo=False)
    if variant is ReportVariant.ANONYMISED:
        demo, real = anonymise(demo), anonymise(real)

    marked = _layout(demo, "en_US", qm_dir)
    plain = _layout(real, "en_US", qm_dir)

    assert marked.watermark == "DEMO - FICTITIOUS DATA"
    assert "DEMO" in marked.title
    assert "DEMO - FICTITIOUS DATA" in marked.text
    assert plain.watermark == ""
    assert "DEMO" not in plain.title
    assert "FICTITIOUS" not in plain.text


def test_the_demo_title_says_demo_in_every_language(qm_dir: Path) -> None:
    for language in i18n.LANGUAGES:
        layout = _layout(_internal(demo=True), language, qm_dir)

        assert "DEMO" in layout.title
        assert "DEMO" in layout.watermark


# --------------------------------------------------------------------------- determinism


def test_the_layout_is_a_pure_function_of_the_document(
    internal: ReportDocument, qm_dir: Path
) -> None:
    assert _layout(internal, "es_ES", qm_dir) == _layout(internal, "es_ES", qm_dir)


# --------------------------------------------------------------------------- metadata


@pytest.mark.parametrize("variant", list(ReportVariant))
def test_the_metadata_carries_no_name_or_identifier(
    internal: ReportDocument, anonymised: ReportDocument, qm_dir: Path, variant: ReportVariant
) -> None:
    document = internal if variant is ReportVariant.INTERNAL else anonymised

    layout = _layout(document, "en_US", qm_dir)
    metadata = " ".join((layout.title, layout.creator, document_xmp(layout)))

    for text in FORBIDDEN:
        assert text not in metadata
    assert "CBRN Readiness Report" in layout.title
    assert layout.creator.endswith(VERSION)


# --------------------------------------------------------------------------- the PDF file


def _pages(data: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", data))


def _media_box(data: bytes) -> tuple[float, float]:
    match = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)\s*\]", data)
    assert match is not None
    return float(match.group(1)), float(match.group(2))


@pytest.mark.parametrize("language", i18n.LANGUAGES)
@pytest.mark.parametrize("variant", list(ReportVariant))
def test_a_pdf_is_written_for_each_variant_and_language(
    internal: ReportDocument,
    anonymised: ReportDocument,
    qm_dir: Path,
    tmp_path: Path,
    variant: ReportVariant,
    language: str,
) -> None:
    document = internal if variant is ReportVariant.INTERNAL else anonymised
    target = tmp_path / "report.pdf"

    layout = write_report_pdf(document, target, language=language, qm_dir=qm_dir)

    data = target.read_bytes()
    assert data.startswith(b"%PDF-")
    assert _pages(data) >= 1
    width, height = _media_box(data)
    assert abs(width - 595.3) < 2.0
    assert abs(height - 841.9) < 2.0
    assert layout.language == language
    assert [entry.name for entry in tmp_path.iterdir()] == ["report.pdf"]


def test_a_long_report_has_several_pages(qm_dir: Path, tmp_path: Path) -> None:
    target = tmp_path / "long.pdf"

    write_report_pdf(_internal(extra_assets=150), target, language="en_US", qm_dir=qm_dir)

    assert _pages(target.read_bytes()) >= 2


def test_the_anonymised_pdf_holds_none_of_the_fixture_names(
    anonymised: ReportDocument, qm_dir: Path, tmp_path: Path
) -> None:
    target = tmp_path / "anon.pdf"

    write_report_pdf(anonymised, target, language="en_US", qm_dir=qm_dir)

    data = target.read_bytes()
    for text in FORBIDDEN:
        assert text.encode("utf-8") not in data
        assert text.encode("utf-16-be") not in data


def test_a_demo_pdf_is_written_in_both_variants(qm_dir: Path, tmp_path: Path) -> None:
    for variant, document in (
        ("internal", _internal(demo=True)),
        ("anonymised", anonymise(_internal(demo=True))),
    ):
        target = tmp_path / f"{variant}.pdf"

        write_report_pdf(document, target, language="pt_BR", qm_dir=qm_dir)

        assert target.read_bytes().startswith(b"%PDF-")


def test_rendering_in_another_language_leaves_translators_and_locale_unchanged(
    internal: ReportDocument, qm_dir: Path, tmp_path: Path
) -> None:
    locale_before = QLocale().name()
    text_before = QCoreApplication.translate("Reports", "Personnel")

    # One of the two languages differs from whatever the application is set to.
    pt = write_report_pdf(internal, tmp_path / "pt.pdf", language="pt_BR", qm_dir=qm_dir)
    es = write_report_pdf(internal, tmp_path / "es.pdf", language="es_ES", qm_dir=qm_dir)

    assert "Pessoal" in pt.text
    assert "Personal" in es.text
    assert QLocale().name() == locale_before
    assert QCoreApplication.translate("Reports", "Personnel") == text_before


def test_an_unknown_language_is_refused_before_anything_is_written(
    internal: ReportDocument, qm_dir: Path, tmp_path: Path
) -> None:
    with pytest.raises(i18n.UnknownLanguageError):
        write_report_pdf(internal, tmp_path / "x.pdf", language="fr_FR", qm_dir=qm_dir)

    assert list(tmp_path.iterdir()) == []


def test_a_missing_folder_gives_the_coded_error_and_no_file(
    internal: ReportDocument, qm_dir: Path, tmp_path: Path
) -> None:
    target = tmp_path / "missing" / "report.pdf"

    with pytest.raises(ServiceError) as caught:
        write_report_pdf(internal, target, language="en_US", qm_dir=qm_dir)

    assert caught.value.code == REPORT_FAILED == "REPORT_FAILED"
    assert caught.value.field == "target"
    assert list(tmp_path.iterdir()) == []


def test_a_target_that_is_a_folder_gives_the_coded_error_and_no_partial_file(
    internal: ReportDocument, qm_dir: Path, tmp_path: Path
) -> None:
    target = tmp_path / "taken.pdf"
    target.mkdir()

    with pytest.raises(ServiceError) as caught:
        write_report_pdf(internal, target, language="en_US", qm_dir=qm_dir)

    assert caught.value.code == REPORT_FAILED
    assert [entry.name for entry in tmp_path.iterdir()] == ["taken.pdf"]
    assert target.is_dir()
    assert list(target.iterdir()) == []


def test_a_failed_write_keeps_an_existing_report_untouched(
    internal: ReportDocument, qm_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-old")

    def broken_replace(self: Path, destination: Path) -> Path:
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "replace", broken_replace)

    with pytest.raises(ServiceError) as caught:
        write_report_pdf(internal, target, language="en_US", qm_dir=qm_dir)

    monkeypatch.undo()
    assert caught.value.code == REPORT_FAILED
    assert target.read_bytes() == b"%PDF-old"
    assert [entry.name for entry in tmp_path.iterdir()] == ["report.pdf"]


@pytest.fixture(autouse=True)
def _no_leftover_parts(tmp_path: Path) -> Iterator[None]:
    yield
    assert not list(tmp_path.rglob("*.part"))
