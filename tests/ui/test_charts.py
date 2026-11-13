# SPDX-License-Identifier: GPL-3.0-or-later
"""Chart adapter (T6.4): data in = data out, palette, "No data", offscreen rendering, D08 rule.

No test compares pixels: images are only checked for size and for not being blank.
"""

import ast
import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCharts import QAbstractBarSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from pytestqt.qtbot import QtBot

import cbrn_dashboard
from cbrn_dashboard.ui.shell.charts import (
    PALETTE,
    ChartData,
    ChartKind,
    ChartSeries,
    ChartView,
    build_chart,
    read_back,
    render_to_image,
)
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from tests.conftest import PSEUDO_PREFIX
from tests.ui._walk import assert_fully_translated, collect_texts

pytestmark = pytest.mark.ui

SOURCE_ROOT = Path(cbrn_dashboard.__file__).parent
CHARTS_MODULE = "ui/shell/charts.py"

BAR = ChartData(
    title="Readiness",
    categories=("North", "South", "East"),
    series=(ChartSeries("Level", (1.0, 2.5, 3.0)),),
    unit="%",
)
GROUPED = ChartData(
    title="By quarter",
    categories=("Q1", "Q2"),
    series=(
        ChartSeries("Alpha", (10.0, 20.0)),
        ChartSeries("Bravo", (15.0, 5.0)),
        ChartSeries("Charlie", (7.0, 30.0)),
    ),
    unit="items",
    kind=ChartKind.GROUPED_BAR,
)
NO_CATEGORIES = ChartData(title="Nothing", categories=(), series=())
ALL_NONE = ChartData(
    title="Missing",
    categories=("A", "B"),
    series=(ChartSeries("S", (None, None)),),
)


def _distinct_colours(image: QImage) -> int:
    step_x = max(1, image.width() // 20)
    step_y = max(1, image.height() // 20)
    return len(
        {
            image.pixel(x, y)
            for x in range(0, image.width(), step_x)
            for y in range(0, image.height(), step_y)
        }
    )


def _no_data_label(view: ChartView) -> QLabel:
    label = view.findChild(QLabel, "chart_no_data")
    assert label is not None
    return label


# --------------------------------------------------------------------------- data


def test_the_palette_is_exactly_okabe_ito() -> None:
    assert PALETTE == (
        "#E69F00",
        "#56B4E9",
        "#009E73",
        "#F0E442",
        "#0072B2",
        "#D55E00",
        "#CC79A7",
        "#000000",
    )


def test_a_series_with_the_wrong_number_of_values_is_rejected() -> None:
    with pytest.raises(ValueError, match="value"):
        ChartData("T", ("A", "B"), (ChartSeries("S", (1.0,)),))
    with pytest.raises(ValueError, match="value"):
        ChartData(
            "T",
            ("A",),
            (ChartSeries("S", (1.0,)), ChartSeries("X", (1.0, 2.0))),
            kind=ChartKind.GROUPED_BAR,
        )


def test_a_bar_chart_takes_at_most_one_series() -> None:
    with pytest.raises(ValueError, match="one series"):
        ChartData("T", ("A",), (ChartSeries("S", (1.0,)), ChartSeries("X", (2.0,))))


def test_negative_and_non_finite_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="negative"):
        ChartData("T", ("A",), (ChartSeries("S", (-1.0,)),))
    with pytest.raises(ValueError, match="finite"):
        ChartData("T", ("A",), (ChartSeries("S", (float("nan"),)),))


def test_is_empty() -> None:
    assert NO_CATEGORIES.is_empty
    assert ALL_NONE.is_empty
    assert ChartData("T", ("A",), ()).is_empty
    assert not BAR.is_empty
    assert not ChartData("T", ("A", "B"), (ChartSeries("S", (None, 0.0)),)).is_empty


# --------------------------------------------------------------------------- the chart


def test_a_bar_chart_stores_what_it_was_given(qapp: QApplication) -> None:
    chart = build_chart(BAR)

    categories, bar_sets = read_back(chart)

    assert categories == BAR.categories
    assert bar_sets == (("Level", (1.0, 2.5, 3.0)),)
    assert chart.title() == "Readiness"
    assert not chart.legend().isVisible()


def test_a_grouped_bar_chart_has_one_bar_set_per_series(qapp: QApplication) -> None:
    chart = build_chart(GROUPED)

    categories, bar_sets = read_back(chart)

    assert categories == ("Q1", "Q2")
    assert bar_sets == (
        ("Alpha", (10.0, 20.0)),
        ("Bravo", (15.0, 5.0)),
        ("Charlie", (7.0, 30.0)),
    )
    assert chart.legend().isVisible()


def test_the_series_colours_come_from_the_palette_in_order(qapp: QApplication) -> None:
    chart = build_chart(GROUPED)
    series = chart.series()[0]
    assert isinstance(series, QAbstractBarSeries)

    colours = [bar_set.color().name().upper() for bar_set in series.barSets()]

    assert colours == [PALETTE[0], PALETTE[1], PALETTE[2]]


def test_the_colours_cycle_through_the_palette(qapp: QApplication) -> None:
    many = ChartData(
        "T",
        ("A",),
        tuple(ChartSeries(f"S{i}", (float(i),)) for i in range(len(PALETTE) + 2)),
        kind=ChartKind.GROUPED_BAR,
    )
    chart = build_chart(many)  # the chart owns its series: keep it alive while they are used
    series = chart.series()[0]
    assert isinstance(series, QAbstractBarSeries)

    colours = [bar_set.color().name().upper() for bar_set in series.barSets()]

    assert colours[: len(PALETTE)] == list(PALETTE)
    assert colours[len(PALETTE) :] == [PALETTE[0], PALETTE[1]]


def test_the_value_axis_starts_at_zero_and_covers_the_values(qapp: QApplication) -> None:
    chart = build_chart(GROUPED)
    axis = chart.axes(Qt.Orientation.Vertical)[0]

    assert isinstance(axis, QValueAxis)
    assert axis.min() == 0.0
    assert axis.max() >= 30.0
    assert axis.titleText() == "items"
    assert "e" not in axis.labelFormat().lower()


def test_a_missing_value_has_no_bar_and_the_chart_says_so(
    qapp: QApplication, qtbot: QtBot, translator_manager: TranslatorManager
) -> None:
    """P6-05: a value that is not recorded stays None, is not a bar, and the legend names it."""
    translator_manager.set_language("en_US")
    data = ChartData("T", ("A", "B", "C"), (ChartSeries("S", (4.0, None, 2.0)),))

    chart = build_chart(data)
    view = ChartView(data)
    qtbot.addWidget(view)

    expected = (("S (not recorded: B)", (4.0, None, 2.0)),)
    assert read_back(chart)[1] == expected
    assert view.data().series[0].values == (4.0, None, 2.0)
    shown = view.chart()
    assert shown is not None
    assert read_back(shown)[1] == expected
    series = chart.series()[0]
    assert isinstance(series, QAbstractBarSeries)
    assert series.barSets()[0].at(1) == 0.0  # no height: nothing is drawn for it
    assert chart.legend().isVisible()  # the note is in the legend, also for a single series


@pytest.mark.parametrize(
    ("language", "label"),
    [
        ("en_US", "S (not recorded: B)"),
        ("pt_BR", "S (não registrado: B)"),
        ("es_ES", "S (sin registrar: B)"),
    ],
)
def test_the_not_recorded_note_follows_the_language(
    qapp: QApplication, translator_manager: TranslatorManager, language: str, label: str
) -> None:
    translator_manager.set_language(language)
    data = ChartData("T", ("A", "B"), (ChartSeries("S", (1.0, None)),))

    assert read_back(build_chart(data))[1][0][0] == label


def test_a_real_zero_is_not_marked_as_missing(qapp: QApplication) -> None:
    data = ChartData("T", ("A", "B"), (ChartSeries("S", (0.0, 3.0)),))

    assert read_back(build_chart(data)) == (("A", "B"), (("S", (0.0, 3.0)),))
    assert not build_chart(data).legend().isVisible()


@pytest.mark.parametrize(
    ("language", "name"), [("pt_BR", "pt_BR"), ("en_US", "en_US"), ("es_ES", "es_ES")]
)
def test_the_axis_numbers_follow_the_active_language(
    qapp: QApplication, translator_manager: TranslatorManager, language: str, name: str
) -> None:
    """P6-06: the chart is localized (decimal separator of the axis labels) like the pages."""
    translator_manager.set_language(language)

    chart = build_chart(BAR)

    assert chart.localizeNumbers()
    assert chart.locale().name() == name


def test_a_shown_chart_follows_a_language_switch(
    qapp: QApplication, qtbot: QtBot, translator_manager: TranslatorManager
) -> None:
    translator_manager.set_language("en_US")
    view = ChartView(BAR)
    qtbot.addWidget(view)
    shown = view.chart()
    assert shown is not None
    assert shown.locale().name() == "en_US"

    translator_manager.set_language("pt_BR")

    qtbot.waitUntil(lambda: shown.locale().name() == "pt_BR")
    assert shown.localizeNumbers()


# --------------------------------------------------------------------------- rendering


@pytest.mark.parametrize("data", [BAR, GROUPED], ids=["bar", "grouped"])
def test_rendering_gives_an_image_of_the_requested_size(
    qapp: QApplication, data: ChartData
) -> None:
    image = render_to_image(data, 400, 260)

    assert not image.isNull()
    assert (image.width(), image.height()) == (400, 260)
    assert image.format() == QImage.Format.Format_ARGB32_Premultiplied
    assert _distinct_colours(image) >= 2


@pytest.mark.parametrize("data", [NO_CATEGORIES, ALL_NONE], ids=["no-categories", "all-none"])
def test_empty_data_renders_the_no_data_text(qapp: QApplication, data: ChartData) -> None:
    image = render_to_image(data, 300, 120)

    assert (image.width(), image.height()) == (300, 120)
    assert _distinct_colours(image) >= 1


@pytest.mark.parametrize("size", [(0, 100), (100, 0), (-1, 100), (100, -5)])
def test_rendering_rejects_non_positive_sizes(qapp: QApplication, size: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="positive"):
        render_to_image(BAR, *size)


# --------------------------------------------------------------------------- the widget


@pytest.mark.parametrize("data", [NO_CATEGORIES, ALL_NONE], ids=["no-categories", "all-none"])
def test_empty_data_shows_the_no_data_text_instead_of_a_chart(
    qapp: QApplication, qtbot: QtBot, translator_manager: TranslatorManager, data: ChartData
) -> None:
    translator_manager.set_language("en_US")
    view = ChartView(data)
    qtbot.addWidget(view)

    label = _no_data_label(view)
    chart_view = view.findChild(QWidget, "chart_view")
    assert chart_view is not None
    assert label.text() == "No data"
    assert not label.isHidden()
    assert chart_view.isHidden()
    assert view.chart() is None


def test_data_shows_the_chart_and_hides_the_text(
    qapp: QApplication, qtbot: QtBot, translator_manager: TranslatorManager
) -> None:
    translator_manager.set_language("en_US")
    view = ChartView()
    qtbot.addWidget(view)
    assert not _no_data_label(view).isHidden()

    view.set_data(GROUPED)

    assert _no_data_label(view).isHidden()
    chart_view = view.findChild(QWidget, "chart_view")
    assert chart_view is not None
    assert not chart_view.isHidden()
    assert chart_view.accessibleName() == "By quarter"
    chart = view.chart()
    assert chart is not None
    assert read_back(chart)[0] == ("Q1", "Q2")

    view.set_data(NO_CATEGORIES)

    assert not _no_data_label(view).isHidden()
    assert chart_view.isHidden()


def test_replacing_the_data_replaces_the_chart(
    qapp: QApplication, qtbot: QtBot, translator_manager: TranslatorManager
) -> None:
    view = ChartView(BAR)
    qtbot.addWidget(view)

    view.set_data(GROUPED)
    view.set_data(BAR)

    chart = view.chart()
    assert chart is not None
    assert read_back(chart) == (BAR.categories, (("Level", (1.0, 2.5, 3.0)),))
    assert view.data() == BAR


@pytest.mark.parametrize(
    ("language", "expected"),
    [("pt_BR", "Sem dados"), ("en_US", "No data"), ("es_ES", "Sin datos")],
)
def test_the_no_data_text_follows_the_language(
    qapp: QApplication,
    qtbot: QtBot,
    translator_manager: TranslatorManager,
    language: str,
    expected: str,
) -> None:
    translator_manager.set_language(language)
    view = ChartView(NO_CATEGORIES)
    qtbot.addWidget(view)

    assert _no_data_label(view).text() == expected


def test_the_no_data_text_is_retranslated_on_a_language_switch(
    qapp: QApplication, qtbot: QtBot, translator_manager: TranslatorManager
) -> None:
    translator_manager.set_language("en_US")
    view = ChartView(NO_CATEGORIES)
    qtbot.addWidget(view)
    assert _no_data_label(view).text() == "No data"

    # Qt posts (not sends) the LanguageChange event, so the text changes once the loop has run.
    translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: _no_data_label(view).text() == "Sem dados")

    translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: _no_data_label(view).text() == "Sin datos")


def test_an_embedded_chart_view_is_retranslated_with_its_parent(
    qapp: QApplication, qtbot: QtBot, translator_manager: TranslatorManager
) -> None:
    translator_manager.set_language("en_US")
    parent = QWidget()
    qtbot.addWidget(parent)
    layout = QVBoxLayout(parent)
    view = ChartView(NO_CATEGORIES, parent)
    layout.addWidget(view)
    assert _no_data_label(view).text() == "No data"

    translator_manager.set_language("pt_BR")

    qtbot.waitUntil(lambda: _no_data_label(view).text() == "Sem dados")


@pytest.mark.parametrize("data", [BAR, GROUPED, NO_CATEGORIES], ids=["bar", "grouped", "empty"])
def test_the_pseudo_locale_walk_passes(
    qapp: QApplication,
    qtbot: QtBot,
    translator_manager_factory: Callable[[Path | None], TranslatorManager],
    pseudo_qm_dir: Path,
    data: ChartData,
) -> None:
    manager = translator_manager_factory(pseudo_qm_dir)
    manager.set_language("en_US")
    # The title is supplied by the caller already translated; it becomes the accessible name of
    # the chart view, which the walker checks even on a data widget.
    title = f"\u27e6{PSEUDO_PREFIX['en_US']}{data.title}\u27e7"
    view = ChartView(dataclasses.replace(data, title=title))
    qtbot.addWidget(view)

    assert_fully_translated(view)

    texts = {item.text for item in collect_texts(view)}
    if data.is_empty:
        # not vacuous: the one visible text is checked (en_US has its own pseudo marker)
        assert texts == {f"\u27e6{PSEUDO_PREFIX['en_US']}No data\u27e7"}
    else:
        assert texts == {title}  # the chart's other texts are data


# --------------------------------------------------------------------------- D08: one importer


def _imports_qtcharts(source: str) -> bool:
    """Whether the source imports ``PySide6.QtCharts`` in any static form."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[:2] == ["PySide6", "QtCharts"] for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[:2] == ["PySide6", "QtCharts"]:
                return True
            if node.module == "PySide6" and any(alias.name == "QtCharts" for alias in node.names):
                return True
    return False


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import PySide6.QtCharts", True),
        ("import PySide6.QtCharts as qc", True),
        ("from PySide6 import QtCharts", True),
        ("from PySide6 import QtCore, QtCharts as qc", True),
        ("from PySide6.QtCharts import QChart", True),
        ("from PySide6.QtCore import QObject", False),
        ("from PySide6 import QtWidgets", False),
        ("import PySide6", False),
        ("x = 'PySide6.QtCharts'", False),
    ],
)
def test_the_qtcharts_import_check_bites(source: str, expected: bool) -> None:
    assert _imports_qtcharts(source) is expected


def test_only_the_chart_adapter_imports_qt_charts() -> None:
    importers = sorted(
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in SOURCE_ROOT.rglob("*.py")
        if _imports_qtcharts(path.read_text(encoding="utf-8"))
    )

    assert importers == [CHARTS_MODULE]
