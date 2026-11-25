# SPDX-License-Identifier: GPL-3.0-or-later
"""The rendered report PDF is read back with pypdf (PLAN.md T8.6, QA finding P8-04).

pypdf is a test-only dependency (``dev`` group); it is never bundled. The parse is checked for
the page count, the A4 page size and, when pypdf can extract text from a Qt-generated PDF, the
page number on every page (and that neither half of the removed preliminary notice is there).

Text extraction from Qt PDFs is not guaranteed (PLAN.md K18). The text checks therefore run only
when ``extract_text()`` returns non-empty text for page 1; the page count and the page size are
always asserted.
"""

import re
from pathlib import Path

import pytest
from pypdf import PdfReader
from PySide6.QtWidgets import QApplication

from cbrn_dashboard.reports.anonymise import anonymise
from cbrn_dashboard.reports.model import ReportDocument, ReportVariant
from cbrn_dashboard.reports.pdf import write_report_pdf
from tests.reports.test_report_pdf import NOTICE_EN, _internal, _pages

pytestmark = pytest.mark.ui

#: A4 in PDF points (595.28 x 841.89), with the tolerance of one point.
A4_WIDTH_PT = 595.0
A4_HEIGHT_PT = 842.0
TOLERANCE_PT = 1.0


@pytest.fixture(autouse=True)
def _application(qapp: QApplication) -> QApplication:
    return qapp


def _squeeze(text: str) -> str:
    """``text`` without any white space (text may wrap or space differently in the PDF)."""
    return re.sub(r"\s+", "", text)


def _document(variant: ReportVariant, *, extra_assets: int) -> ReportDocument:
    document = _internal(demo=True, extra_assets=extra_assets)
    return document if variant is ReportVariant.INTERNAL else anonymise(document)


@pytest.mark.parametrize("extra_assets", [0, 150], ids=["short", "long"])
@pytest.mark.parametrize("variant", list(ReportVariant))
def test_the_pdf_parses_with_pypdf_in_a4_with_page_numbers_and_no_preliminary_notice(
    qm_dir: Path, tmp_path: Path, variant: ReportVariant, extra_assets: int
) -> None:
    target = tmp_path / "report.pdf"

    write_report_pdf(
        _document(variant, extra_assets=extra_assets), target, language="en_US", qm_dir=qm_dir
    )

    reader = PdfReader(str(target))
    pages = list(reader.pages)
    assert len(pages) == _pages(target.read_bytes())
    assert len(pages) >= 1
    if extra_assets:
        assert len(pages) >= 2
    for page in pages:
        assert abs(float(page.mediabox.width) - A4_WIDTH_PT) <= TOLERANCE_PT
        assert abs(float(page.mediabox.height) - A4_HEIGHT_PT) <= TOLERANCE_PT

    if not pages[0].extract_text().strip():
        return  # K18: no text can be read back from this PDF; size and count were checked

    before, _, after = NOTICE_EN.partition("\u2014")  # the dash may not survive the extraction
    for number, page in enumerate(pages, start=1):
        text = _squeeze(page.extract_text())
        assert _squeeze(before) not in text, number
        assert _squeeze(after) not in text, number
        assert _squeeze(f"Page {number} of {len(pages)}") in text, number
