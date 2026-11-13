# SPDX-License-Identifier: GPL-3.0-or-later
"""PDF rendering of a report document (PLAN.md T8.6; D08, D09, A11, R11-R13, P07, P10).

Two steps, so that tests can look at the content without reading a PDF:

1. :func:`build_layout` is a pure function of the :class:`ReportDocument` and a
   :class:`~cbrn_dashboard.reports.labels.ReportTexts`: it returns a :class:`ReportLayout` with the
   HTML of the report (Qt's rich-text subset), its plain text, the chart data, the footer notice and
   the watermark. Every time value comes from the document (never from the clock). Numbers, dates,
   money and percentages are formatted with :mod:`cbrn_dashboard.ui.shell.formatting` in the
   language of the report.
2. :func:`write_report_pdf` lays the HTML out in a ``QTextDocument`` and paginates it by hand with
   a ``QPainter`` on a ``QPdfWriter`` (A4), because ``QTextDocument.print()`` has no per-page
   footer: every page gets the preliminary notice and "Page i of n", and, for a demo document, the
   "DEMO - FICTITIOUS DATA" watermark. Charts go through the T6.4 adapter.

What is printed (and what is not):

* a suppressed cell is the marker ``< threshold``; never a number, never a blank. The anonymised
  variant states the threshold in a note;
* the institution, unit, operator and handling notice and the two lists exist only in the INTERNAL
  variant. The renderer also checks the variant, so a hand-made anonymised document that still
  held them would not print them; it prints no heading for an absent block;
* the PDF Info and XMP metadata hold the title (with ``DEMO`` for a demo document), the creator and
  the application version, and nothing else: no operator, institution or identifier.

Writing: the PDF is built in memory, written beside the target under a temporary name and renamed
when complete. A failure leaves no file and raises ``ServiceError(REPORT_FAILED, <field>)``.

Known limit: Qt stamps the creation date of the Info dictionary from the system clock itself; it
cannot be set through ``QPdfWriter``, so two renderings of one document differ in that one field
(the XMP packet written here carries no date).
"""

import contextlib
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape as xml_escape

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QMarginsF,
    QPointF,
    QRectF,
    QSizeF,
    Qt,
    QUrl,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
    QTextDocument,
    QTextOption,
)

from cbrn_dashboard.domain.budget import currency_decimals
from cbrn_dashboard.domain.indicators import UnitKind
from cbrn_dashboard.reports.labels import ReportTexts, fill
from cbrn_dashboard.reports.model import (
    Cell,
    IndicatorRow,
    ReportChart,
    ReportDocument,
    ReportVariant,
)
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.ui.shell.charts import ChartData, ChartKind, ChartSeries, render_to_image
from cbrn_dashboard.ui.shell.formatting import (
    FormatError,
    format_date,
    format_money,
    format_number,
    format_percent,
)

__all__ = [
    "CREATOR",
    "REPORT_FAILED",
    "ReportLayout",
    "build_layout",
    "document_xmp",
    "render_pdf_bytes",
    "write_report_pdf",
]

#: The error code of a report that could not be produced or written (the UI translates it).
REPORT_FAILED: Final = "REPORT_FAILED"

#: The application name written to the PDF as its creator (a product name, not translated).
CREATOR: Final = "CBRN Readiness Dashboard"

RESOLUTION: Final = 300  # dots per inch of the PDF device
_MARGINS_MM: Final = (18.0, 16.0, 18.0, 12.0)  # left, top, right, bottom
_FOOTER_MM: Final = 13.0
_CHART_IMAGE: Final = (800, 400)  # pixels the chart is drawn at (its text is sized for 96 dpi)
_CHART_DISPLAY_MM: Final = (150.0, 75.0)
_PADDING_MM: Final = 1.0
_BODY_POINTS: Final = 10.0
_FOOTER_POINTS: Final = 8.0
_WATERMARK_POINTS: Final = 40.0
_BUDGET_FIGURE_PREFIX: Final = "kf:BUDGET:"
_EMPTY: Final = "-"  # a value that does not apply (a date or threshold that is not set)
_DEMO_TOKEN: Final = "DEMO"  # in the PDF title of a demo document, whatever the language


def _mm_to_px(millimetres: float, resolution: int) -> int:
    return round(millimetres / 25.4 * resolution)


# --------------------------------------------------------------------------- the layout


@dataclass(frozen=True)
class ReportLayout:
    """What the renderer draws, as plain data (``html`` refers to charts as ``chart:<index>``)."""

    language: str
    title: str
    html: str
    text: str
    footer_notice: str
    page_template: str
    watermark: str
    charts: tuple[ChartData, ...]
    suppression_marker: str
    creator: str


class _Format:
    """Numbers, dates, money and percentages in the language of the report."""

    def __init__(self, texts: ReportTexts) -> None:
        self._texts = texts
        self.language = texts.language

    def _guard(self, value: float, render: Callable[[], str]) -> str:
        if not math.isfinite(value):
            return self._texts.translate("Reports", "No data")
        try:
            return render()
        except FormatError:
            return str(value)

    def whole(self, value: float) -> str:
        return self._guard(value, lambda: format_number(value, self.language, decimals=0))

    def number(self, value: float) -> str:
        decimals = 0 if float(value).is_integer() else 2
        return self._guard(value, lambda: format_number(value, self.language, decimals=decimals))

    def percent(self, value: float) -> str:
        return self._guard(value, lambda: format_percent(value, self.language, decimals=1))

    def money(self, value: float, currency: str) -> str:
        def render() -> str:
            minor = (Decimal(repr(value)) * 10 ** currency_decimals(currency)).quantize(
                Decimal(1), rounding=ROUND_HALF_UP
            )
            return format_money(int(minor), currency, self.language)

        try:
            return self._guard(value, render)
        except (ValueError, ArithmeticError):
            return f"{self.number(value)} {currency}"

    def day(self, value: date | None) -> str:
        return _EMPTY if value is None else format_date(value, self.language)

    def marker(self, threshold: int) -> str:
        return f"< {format_number(threshold, self.language, decimals=0)}"

    def cell(self, cell: Cell, threshold: int) -> str:
        """A key figure: the marker when suppressed, never a number then."""
        if cell.suppressed:
            return self.marker(threshold)
        if cell.value is None:
            return self._texts.translate("Reports", "No data")
        if cell.key.startswith(_BUDGET_FIGURE_PREFIX):
            return self.money(cell.value, cell.key.rsplit(":", 1)[-1])
        return self.whole(cell.value) if cell.is_count else self.number(cell.value)

    def amount(self, value: float | None, unit: UnitKind) -> str:
        """An indicator value or target in its unit; ``-`` when there is none."""
        if value is None:
            return _EMPTY
        if unit is UnitKind.COUNT:
            return self.whole(value)
        if unit is UnitKind.RATIO:
            return self.percent(value)
        if unit is UnitKind.DAYS:
            return fill(self._texts.translate("Reports", "%1 days"), self.number(value))
        return self.number(value)


class _Doc:
    """Collects the HTML and the plain text of the report side by side."""

    def __init__(self, resolution: int) -> None:
        self.html: list[str] = []
        self.text: list[str] = []
        self.charts: list[ChartData] = []
        self.padding = max(1, _mm_to_px(_PADDING_MM, resolution))
        self._resolution = resolution

    def heading(self, level: int, text: str) -> None:
        size = {1: 18, 2: 13, 3: 11}[level]
        self.html.append(f'<h{level} style="font-size:{size}pt">{escape(text)}</h{level}>')
        self.text.append(text)

    def paragraph(self, text: str) -> None:
        self.html.append(f"<p>{escape(text).replace(chr(10), '<br>')}</p>")
        self.text.append(text)

    def box(self, text: str, *, bold: bool = False) -> None:
        body = escape(text).replace("\n", "<br>")
        inner = f"<b>{body}</b>" if bold else body
        self.html.append(
            f'<table width="100%" border="1" cellspacing="0" cellpadding="{self.padding}">'
            f'<tr><td bgcolor="#F2F2F2">{inner}</td></tr></table><p></p>'
        )
        self.text.append(text)

    def table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        *,
        right: Sequence[int] = (),
    ) -> None:
        parts = [f'<table width="100%" border="1" cellspacing="0" cellpadding="{self.padding}">']
        if headers:
            cells = "".join(
                f'<th align="left" bgcolor="#E6E6E6">{escape(header)}</th>' for header in headers
            )
            parts.append(f"<thead><tr>{cells}</tr></thead>")
            self.text.append(" | ".join(headers))
        for row in rows:
            cells = "".join(
                f'<td align="{"right" if index in right else "left"}">{escape(cell)}</td>'
                for index, cell in enumerate(row)
            )
            parts.append(f"<tr>{cells}</tr>")
            self.text.append(" | ".join(row))
        parts.append("</table><p></p>")
        self.html.append("".join(parts))

    def chart(self, data: ChartData) -> None:
        width = _mm_to_px(_CHART_DISPLAY_MM[0], self._resolution)
        height = _mm_to_px(_CHART_DISPLAY_MM[1], self._resolution)
        self.html.append(
            f'<p><img src="chart:{len(self.charts)}" width="{width}" height="{height}"></p>'
        )
        self.charts.append(data)


def _drawable(value: float | None) -> float | None:
    """A value the chart adapter accepts (finite, not negative), else ``None``."""
    if value is None or not math.isfinite(value) or value < 0:
        return None
    return value


def _chart_data(chart: ReportChart, texts: ReportTexts) -> tuple[ChartData, bool]:
    """The chart data of a report chart and whether a category holds a suppressed cell.

    A suppressed cell has no value and is not drawn; its category is marked with ``(*)``.
    """
    flagged = [
        any(series.cells[index].suppressed for series in chart.series)
        for index in range(len(chart.categories))
    ]
    categories = tuple(
        f"{texts.chart_category(chart.key, category)} (*)"
        if flagged[index]
        else texts.chart_category(chart.key, category)
        for index, category in enumerate(chart.categories)
    )
    series = tuple(
        ChartSeries(
            texts.series_name(row.key),
            tuple(None if cell.suppressed else _drawable(cell.value) for cell in row.cells),
        )
        for row in chart.series
    )
    parameters = dict(chart.parameters)
    unit = parameters.get("currency", "") if chart.unit is UnitKind.CURRENCY else ""
    kind = ChartKind.GROUPED_BAR if len(series) > 1 else ChartKind.BAR
    return ChartData("", categories, series, unit, kind), any(flagged)


def _header_rows(
    document: ReportDocument, texts: ReportTexts, fmt: _Format, internal: bool
) -> list[tuple[str, str]]:
    header = document.header
    rows: list[tuple[str, str]] = []
    if internal and header.institution_name:
        rows.append((texts.translate("Reports", "Institution"), header.institution_name))
    if internal and header.unit_name:
        rows.append((texts.translate("Reports", "Unit"), header.unit_name))
    if internal and header.operator_label:
        rows.append((texts.translate("Reports", "Operator"), header.operator_label))
    rows.append((texts.translate("Reports", "As of"), fmt.day(header.as_of)))
    rows.append((texts.translate("Reports", "Generated (UTC)"), header.generated_at_utc))
    rows.append((texts.translate("Reports", "Application version"), header.app_version))
    return rows


def _add_key_figures(doc: _Doc, document: ReportDocument, texts: ReportTexts, fmt: _Format) -> None:
    groups = [group for group in document.key_figures if group.cells]
    if not groups:
        return
    doc.heading(2, texts.translate("Reports", "Key figures"))
    for group in groups:
        doc.heading(3, texts.module(group.module.value))
        doc.table(
            (texts.translate("Reports", "Figure"), texts.translate("Reports", "Value")),
            [
                (
                    texts.cell_label(cell.key),
                    fmt.cell(cell, document.small_count_threshold),
                )
                for cell in group.cells
            ],
            right=(1,),
        )


def _dimension_text(row: IndicatorRow, texts: ReportTexts) -> str:
    parts: list[str] = []
    for name, value in row.dimension_parts:
        if name == "type":
            shown = texts.asset_type(value)
        elif name == "source":
            shown = texts.funding_source(value)
        else:
            shown = value
        parts.append(f"{texts.dimension_name(name)}: {shown}")
    return "; ".join(parts) if parts else _EMPTY


def _indicator_value(row: IndicatorRow, threshold: int, texts: ReportTexts, fmt: _Format) -> str:
    if row.value.suppressed:
        return fmt.marker(threshold)
    if row.value.value is None:
        return texts.translate("Reports", "No data")
    return fmt.amount(row.value.value, row.unit)


def _add_indicators(doc: _Doc, document: ReportDocument, texts: ReportTexts, fmt: _Format) -> None:
    if not document.indicators:
        return
    doc.heading(2, texts.translate("Reports", "Indicators"))
    rows: list[Sequence[str]] = []
    for row in document.indicators:
        rows.append(
            (
                texts.indicator(row.code),
                _dimension_text(row, texts),
                _indicator_value(row, document.small_count_threshold, texts, fmt),
                fmt.amount(row.warning_value, row.unit),
                fmt.amount(row.critical_value, row.unit),
                texts.indicator_status(row.status.value),
            )
        )
    doc.table(
        (
            texts.translate("Reports", "Indicator"),
            texts.translate("Reports", "Detail"),
            texts.translate("Reports", "Value"),
            texts.translate("Reports", "Warning at"),
            texts.translate("Reports", "Critical at"),
            texts.translate("Reports", "Status"),
        ),
        rows,
        right=(2, 3, 4),
    )


def _add_alerts(doc: _Doc, document: ReportDocument, texts: ReportTexts, fmt: _Format) -> None:
    if not document.alert_summary:
        return
    doc.heading(2, texts.translate("Reports", "Open alerts"))
    threshold = document.small_count_threshold
    doc.table(
        (texts.translate("Reports", "Severity"), texts.translate("Reports", "Open alerts")),
        [
            (texts.severity(alert.severity.value), fmt.cell(alert.cell, threshold))
            for alert in document.alert_summary
        ],
        right=(1,),
    )


def _add_charts(doc: _Doc, document: ReportDocument, texts: ReportTexts) -> None:
    if not document.charts:
        return
    doc.heading(2, texts.translate("Reports", "Charts"))
    any_flag = False
    for chart in document.charts:
        doc.heading(3, texts.chart_title(chart.key, dict(chart.parameters)))
        data, flagged = _chart_data(chart, texts)
        if data.is_empty:
            doc.paragraph(texts.translate("Reports", "No data"))
            continue
        doc.chart(data)
        any_flag = any_flag or flagged
    if any_flag:
        doc.paragraph(
            texts.translate(
                "Reports",
                "(*) At least one value of this group is a small count and is not drawn.",
            )
        )


def _add_lists(doc: _Doc, document: ReportDocument, texts: ReportTexts, fmt: _Format) -> None:
    doc.heading(2, texts.translate("Reports", "Staff needing retraining"))
    if document.retraining:
        doc.table(
            (
                texts.translate("Reports", "Identifier"),
                texts.translate("Reports", "Protection level"),
                texts.translate("Reports", "Valid until"),
                texts.translate("Reports", "Certificate status"),
            ),
            [
                (
                    row.identifier,
                    row.level.value,
                    fmt.day(row.valid_until),
                    texts.cert_status(row.status.value),
                )
                for row in document.retraining
            ],
        )
    else:
        doc.paragraph(texts.translate("Reports", "None."))
    doc.heading(2, texts.translate("Reports", "Assets with overdue maintenance"))
    if document.overdue_assets:
        doc.table(
            (
                texts.translate("Reports", "Asset tag"),
                texts.translate("Reports", "Asset type"),
                texts.translate("Reports", "Due on"),
                texts.translate("Reports", "Days overdue"),
            ),
            [
                (
                    row.tag,
                    texts.asset_type(row.type_code),
                    fmt.day(row.due_on),
                    _EMPTY if row.days_to_due is None else fmt.whole(max(0, -row.days_to_due)),
                )
                for row in document.overdue_assets
            ],
            right=(3,),
        )
    else:
        doc.paragraph(texts.translate("Reports", "None."))


def build_layout(
    document: ReportDocument, texts: ReportTexts, *, resolution: int = RESOLUTION
) -> ReportLayout:
    """The content of the report in the language of ``texts`` (pure; no Qt painting, no clock)."""
    internal = document.variant is ReportVariant.INTERNAL
    fmt = _Format(texts)
    doc = _Doc(resolution)

    base_title = texts.translate("Reports", "CBRN Readiness Report")
    variant_name = (
        texts.translate("Reports", "Internal report")
        if internal
        else texts.translate("Reports", "Aggregated report (anonymised)")
    )
    watermark = texts.translate("Reports", "DEMO - FICTITIOUS DATA") if document.is_demo else ""
    pdf_title = f"{base_title} - {variant_name} - {fmt.day(document.header.as_of)}"
    if document.is_demo:
        pdf_title = f"{_DEMO_TOKEN} - {pdf_title}"

    doc.heading(1, base_title)
    doc.paragraph(variant_name)
    if watermark:
        doc.box(watermark, bold=True)
    doc.table((), _header_rows(document, texts, fmt, internal))
    notice = texts.preliminary_notice(document.preliminary_notice_code)
    doc.box(notice, bold=True)
    if internal and document.handling_notice:
        handling_label = texts.translate("Reports", "Handling notice")
        doc.box(f"{handling_label}: {document.handling_notice}")
    if not internal:
        doc.paragraph(
            fill(
                texts.translate(
                    "Reports",
                    "Staff-derived counts below %1 (zero included) are suppressed and shown as "
                    "< %1. Totals that would reveal a suppressed count are suppressed too.",
                ),
                format_number(document.small_count_threshold, texts.language, decimals=0),
            )
        )
    _add_key_figures(doc, document, texts, fmt)
    _add_indicators(doc, document, texts, fmt)
    _add_alerts(doc, document, texts, fmt)
    _add_charts(doc, document, texts)
    if internal:
        _add_lists(doc, document, texts, fmt)

    return ReportLayout(
        language=texts.language,
        title=pdf_title,
        html="<html><body>" + "".join(doc.html) + "</body></html>",
        text="\n".join(doc.text),
        footer_notice=notice,
        page_template=texts.translate("Reports", "Page %1 of %2"),
        watermark=watermark,
        charts=tuple(doc.charts),
        suppression_marker=fmt.marker(document.small_count_threshold),
        creator=f"{CREATOR} {document.header.app_version}".strip(),
    )


# --------------------------------------------------------------------------- the PDF


def document_xmp(layout: ReportLayout) -> str:
    """The XMP packet written to the PDF: title, creator tool and format, nothing else."""
    title = xml_escape(layout.title)
    creator = xml_escape(layout.creator)
    return (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:xmp="http://ns.adobe.com/xap/1.0/">'
        f'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">{title}</rdf:li></rdf:Alt></dc:title>'
        "<dc:format>application/pdf</dc:format>"
        f"<xmp:CreatorTool>{creator}</xmp:CreatorTool>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )


def _draw_watermark(painter: QPainter, width: int, height: int, text: str, font: QFont) -> None:
    painter.save()
    try:
        mark = QFont(font)
        mark.setPointSizeF(_WATERMARK_POINTS)
        mark.setBold(True)
        painter.setFont(mark)
        painter.setOpacity(0.15)
        painter.setPen(QColor("#B00000"))
        painter.translate(QPointF(width / 2.0, height / 2.0))
        painter.rotate(-35.0)
        area = QRectF(-float(width), -height / 4.0, 2.0 * width, height / 2.0)
        painter.drawText(area, text, QTextOption(Qt.AlignmentFlag.AlignCenter))
    finally:
        painter.restore()


def _draw_footer(
    painter: QPainter,
    width: int,
    top: int,
    height: int,
    layout: ReportLayout,
    page: tuple[int, int],
) -> None:
    painter.save()
    try:
        small = QFont(painter.font())
        small.setPointSizeF(_FOOTER_POINTS)
        painter.setFont(small)
        painter.setPen(QColor("#000000"))
        painter.drawLine(0, top, width, top)
        gap = max(4, height // 8)
        number_width = width // 5
        notice_area = QRectF(0.0, top + gap, float(width - number_width), float(height - gap))
        number_area = QRectF(
            float(width - number_width), top + gap, float(number_width), float(height - gap)
        )
        notice_option = QTextOption(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        notice_option.setWrapMode(QTextOption.WrapMode.WordWrap)
        painter.drawText(notice_area, layout.footer_notice, notice_option)
        number = fill(layout.page_template, str(page[0]), str(page[1]))
        painter.drawText(
            number_area,
            number,
            QTextOption(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop),
        )
    finally:
        painter.restore()


def render_pdf_bytes(layout: ReportLayout, *, resolution: int = RESOLUTION) -> bytes:
    """The A4 PDF of ``layout`` as bytes (built in memory; raises ``ServiceError`` on failure)."""
    buffer = QBuffer()
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise ServiceError(REPORT_FAILED, "render")
    try:
        writer = QPdfWriter(buffer)
        writer.setResolution(resolution)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        left, top, right, bottom = _MARGINS_MM
        writer.setPageMargins(QMarginsF(left, top, right, bottom), QPageLayout.Unit.Millimeter)
        writer.setTitle(layout.title)
        writer.setCreator(layout.creator)
        writer.setDocumentXmpMetadata(QByteArray(document_xmp(layout).encode("utf-8")))

        paint = writer.pageLayout().paintRectPixels(resolution)
        width, height = paint.width(), paint.height()
        footer = _mm_to_px(_FOOTER_MM, resolution)
        body = height - footer

        font = QFont()
        font.setPointSizeF(_BODY_POINTS)
        document = QTextDocument()
        document.documentLayout().setPaintDevice(writer)
        document.setDefaultFont(font)
        document.setDocumentMargin(0.0)
        document.setPageSize(QSizeF(float(width), float(body)))
        for index, data in enumerate(layout.charts):
            image = render_to_image(data, *_CHART_IMAGE)
            document.addResource(
                int(QTextDocument.ResourceType.ImageResource.value), QUrl(f"chart:{index}"), image
            )
        document.setHtml(layout.html)

        painter = QPainter(writer)
        if not painter.isActive():
            raise ServiceError(REPORT_FAILED, "render")
        try:
            pages = max(1, document.pageCount())
            for page in range(pages):
                if page:
                    writer.newPage()
                if layout.watermark:
                    _draw_watermark(painter, width, body, layout.watermark, font)
                painter.save()
                try:
                    painter.translate(QPointF(0.0, -float(page * body)))
                    document.drawContents(painter, QRectF(0.0, page * body, width, body))
                finally:
                    painter.restore()
                _draw_footer(painter, width, body, footer, layout, (page + 1, pages))
        finally:
            painter.end()
    finally:
        data_bytes = bytes(buffer.data().data())
        buffer.close()
    return data_bytes


def _write_atomic(target: Path, data: bytes) -> None:
    """Write ``data`` beside ``target`` under a temporary name, then rename; no partial file."""
    temp = target.with_name(target.name + ".part")
    try:
        with temp.open("wb") as handle:
            handle.write(data)
        temp.replace(target)
    except OSError:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
        raise ServiceError(REPORT_FAILED, "target") from None
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink(missing_ok=True)
        raise


def write_report_pdf(
    document: ReportDocument, target: Path, *, language: str, qm_dir: Path | None = None
) -> ReportLayout:
    """Render ``document`` in ``language`` to the PDF file ``target``; return what was drawn.

    ``language`` is a catalogue code (``pt_BR``) or its BCP-47 form. ``qm_dir`` is the folder of
    the compiled catalogues (``None``: the package's own). The application's translators and
    default locale are not touched. Raises ``ServiceError(REPORT_FAILED, "target")`` when the
    file cannot be written (nothing is left behind) and ``UnknownLanguageError`` for an unknown
    language.
    """
    texts = ReportTexts(language, qm_dir)
    layout = build_layout(document, texts)
    _write_atomic(Path(target), render_pdf_bytes(layout))
    return layout
