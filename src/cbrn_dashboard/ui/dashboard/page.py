# SPDX-License-Identifier: GPL-3.0-or-later
"""The Dashboard page: indicator tiles, alert counts and charts (PLAN.md T6.5, T8.1, D08, D23).

The page shows what ``DashboardService.data(as_of)`` returns for the as-of date of the context:

* one tile per indicator reading, grouped by module, with value, unit, status and the thresholds
  in force. The status is a text, an icon SHAPE and a colour of the colour-blind-safe palette
  (D23); "No target" and "No data" have their own texts (D14). No composite score is shown;
* the alert counts by severity;
* the charts, converted to the chart adapter's data (``ui/shell/charts.py``). Every chart has a
  "Show as table" toggle that shows exactly the same numbers as a table (D08, K09).

Everything is read again from the service on every ``as_of_changed``, every ``data_changed`` and
every language switch; nothing is cached. The "Record snapshot" action (T8.1) records a snapshot
of the as-of date through ``context.services.snapshots`` (when that service exists) and is an
edit action: read-only mode disables it. The module-level factories are what the registry calls;
they work without services and read nothing but the dashboard service.
"""

from functools import partial

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.domain.indicators import Module, UnitKind
from cbrn_dashboard.services.budget import SourceView
from cbrn_dashboard.services.dashboard import ChartSpec, DashboardData, Tile
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.infrastructure import AssetTypeView
from cbrn_dashboard.services.snapshots import SnapshotOrigin, SnapshotService, SnapshotView
from cbrn_dashboard.services.stock import StockTypeView
from cbrn_dashboard.ui.dashboard.labels import (
    STATUS_COLOURS,
    DisplayNames,
    alert_text,
    as_of_text,
    category_header,
    chart_data,
    context_text,
    dimension_text,
    error_label,
    indicator_name,
    module_title,
    origin_label,
    series_label,
    severity_pixmap,
    status_label,
    status_pixmap,
    thresholds_text,
    unit_label,
    value_text,
)
from cbrn_dashboard.ui.dashboard.models import (
    ChartTableModel,
    SeriesColumn,
    count_text,
    major_money_text,
)
from cbrn_dashboard.ui.shell.charts import PALETTE, ChartData, ChartView
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import format_date
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_change,
    apply_tab_order,
    current_language,
    make_edit_action,
    make_table_view,
)

__all__ = [
    "ChartPanel",
    "DashboardPage",
    "TileWidget",
    "create_page",
    "page_title",
]

# Tiles per row inside a module group.
_TILE_COLUMNS = 3


def _bold(label: QLabel, scale: float = 1.0) -> None:
    font = label.font()
    font.setBold(True)
    if scale != 1.0 and font.pointSizeF() > 0:
        font.setPointSizeF(font.pointSizeF() * scale)
    label.setFont(font)


def _plain(label: QLabel) -> QLabel:
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


def _clear(layout: QLayout) -> None:
    """Remove and delete every widget of ``layout``."""
    while layout.count():
        item = layout.takeAt(0)
        widget = None if item is None else item.widget()
        if widget is not None:
            # Hidden and deleted where it is: setParent(None) would first make it a window of
            # its own, and Qt then moves it out of the Tab chain the page has set.
            widget.hide()
            widget.deleteLater()


# --------------------------------------------------------------------------- one tile


class TileWidget(QFrame):
    """One indicator reading: name, dimension, value, unit, status and the thresholds in force.

    The status is a text, an icon shape and a palette colour (D23).
    """

    def __init__(self, tile: Tile, names: DisplayNames, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tile = tile
        lang = names.lang
        status = tile.status.value
        self.setObjectName("tile")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("indicator_code", tile.code)
        self.setProperty("indicator_dimension", tile.dimension)
        # A coloured edge: the colour backs up the text and the icon, it never replaces them.
        colour = STATUS_COLOURS.get(status, PALETTE[7])
        self.setStyleSheet(f"QFrame#tile {{ border-left: 6px solid {colour}; }}")

        self.name_label = _plain(QLabel(indicator_name(tile.code), self))
        self.name_label.setObjectName("tile_name")
        self.name_label.setWordWrap(True)
        _bold(self.name_label)
        dimension = dimension_text(tile.code, tile.dimension_parts, names)
        self.dimension_label = _plain(QLabel(dimension, self))
        self.dimension_label.setObjectName("tile_dimension")
        self.dimension_label.setWordWrap(True)
        self.dimension_label.setVisible(bool(dimension))
        self.value_label = _plain(QLabel(value_text(tile, lang), self))
        self.value_label.setObjectName("tile_value")
        _bold(self.value_label, 1.6)
        self.unit_label = _plain(QLabel(unit_label(tile.code, tile.unit.value, tile.value), self))
        self.unit_label.setObjectName("tile_unit")
        status_text = status_label(status)
        self.status_icon = QLabel(self)
        self.status_icon.setObjectName("tile_status_icon")
        self.status_icon.setPixmap(status_pixmap(status))
        self.status_icon.setAccessibleName(status_text)
        self.status_label = _plain(QLabel(status_text, self))
        self.status_label.setObjectName("tile_status")
        _bold(self.status_label)
        self.thresholds_label = _plain(QLabel(thresholds_text(tile, lang), self))
        self.thresholds_label.setObjectName("tile_thresholds")
        self.thresholds_label.setWordWrap(True)
        context = context_text(tile, lang)
        self.context_label = _plain(QLabel(context, self))
        self.context_label.setObjectName("tile_context")
        self.context_label.setWordWrap(True)
        self.context_label.setVisible(bool(context))

        value_row = QHBoxLayout()
        value_row.addWidget(self.value_label)
        value_row.addWidget(self.unit_label)
        value_row.addStretch(1)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status_icon)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.name_label)
        layout.addWidget(self.dimension_label)
        layout.addLayout(value_row)
        layout.addLayout(status_row)
        layout.addWidget(self.thresholds_label)
        layout.addWidget(self.context_label)


# --------------------------------------------------------------------------- one chart


class ChartPanel(QFrame):
    """A chart and, behind the "Show as table" toggle, the same numbers as a table (D08)."""

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("chart_panel")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.toggle = QCheckBox(self)
        self.toggle.setObjectName("table_toggle")
        self.table_caption = _plain(QLabel(self))
        self.table_caption.setObjectName("table_caption")
        _bold(self.table_caption)
        self.table_caption.setVisible(False)
        self.chart_view = ChartView(parent=self)
        self.table_model = ChartTableModel(self)
        self.table_view = make_table_view(self.table_model, self)
        self.table_view.setObjectName("chart_table")
        self.table_view.setMinimumHeight(120)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.chart_view)
        self.stack.addWidget(self.table_view)
        layout = QVBoxLayout(self)
        layout.addWidget(self.toggle)
        layout.addWidget(self.table_caption)
        layout.addWidget(self.stack, 1)
        self.toggle.toggled.connect(self._toggled)

    def data(self) -> ChartData:
        """The data the chart view shows now."""
        return self.chart_view.data()

    def table_shown(self) -> bool:
        """Whether the table, not the chart, is the visible alternative."""
        return self.stack.currentWidget() is self.table_view

    def set_content(self, spec: ChartSpec, names: DisplayNames) -> None:
        """Show ``spec``: the chart, the table with the same values and the texts of ``names``."""
        data = chart_data(spec, names)
        self.chart_view.set_data(data)
        self.table_caption.setText(data.title)
        self.table_view.setAccessibleName(data.title)
        self.toggle.setText(QCoreApplication.translate("Dashboard", "Show as table"))
        currency = spec.parameters.get("currency", "")

        def money(value: float | None, lang: str) -> str:
            return major_money_text(value, currency, lang)

        columns: list[SeriesColumn] = [
            (partial(series_label, item.key), item.values) for item in spec.series
        ]
        self.table_model.set_content(
            partial(category_header, spec.key),
            data.categories,
            columns,
            money if spec.unit is UnitKind.CURRENCY else count_text,
        )
        self.table_model.set_language(names.lang)

    def _toggled(self, checked: bool) -> None:
        self.stack.setCurrentWidget(self.table_view if checked else self.chart_view)
        self.table_caption.setVisible(checked)


# --------------------------------------------------------------------------- the page


class DashboardPage(QWidget):
    """Tiles, alert counts and charts for the as-of date, and the "Record snapshot" action."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("dashboard_page")
        self.context = context
        self.tile_widgets: list[TileWidget] = []
        self._panels: dict[str, ChartPanel] = {}
        self._panel_order: list[str] = []
        self._data: DashboardData | None = None
        self._problem: str | None = None
        self._types: dict[str, AssetTypeView] = {}
        self._sources: dict[str, SourceView] = {}
        self._stock_types: dict[str, StockTypeView] = {}

        self.as_of_label = _plain(QLabel(self))
        self.as_of_label.setObjectName("as_of_label")
        _bold(self.as_of_label, 1.2)
        self.empty_label = _plain(QLabel(self))
        self.empty_label.setObjectName("empty_label")
        self.snapshot_action: EditAction = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Dashboard", "Record snapshot"),
            self.record_snapshot,
        )
        # A navigation action: it changes no data, so it is NOT made with make_edit_action and
        # stays enabled in read-only mode.
        self.antidotes_action = EditAction(
            self,
            lambda: QCoreApplication.translate("Dashboard", "Open antidotes and decontaminants"),
        )
        self.antidotes_action.triggered.connect(self.open_antidotes)

        self.alerts_box = QGroupBox(self)
        self.alerts_box.setObjectName("alerts_box")
        alerts_row = QHBoxLayout(self.alerts_box)
        self.alert_icons: dict[Severity, QLabel] = {}
        self.alert_labels: dict[Severity, QLabel] = {}
        for severity in Severity:
            icon = QLabel(self.alerts_box)
            icon.setObjectName(f"alert_icon_{severity.value.lower()}")
            icon.setPixmap(severity_pixmap(severity.value))
            text = _plain(QLabel(self.alerts_box))
            text.setObjectName(f"alert_{severity.value.lower()}")
            _bold(text)
            alerts_row.addWidget(icon)
            alerts_row.addWidget(text)
            alerts_row.addSpacing(16)
            self.alert_icons[severity] = icon
            self.alert_labels[severity] = text
        alerts_row.addStretch(1)

        self.tiles_caption = _plain(QLabel(self))
        self.tiles_caption.setObjectName("tiles_caption")
        _bold(self.tiles_caption, 1.2)
        self.charts_caption = _plain(QLabel(self))
        self.charts_caption.setObjectName("charts_caption")
        _bold(self.charts_caption, 1.2)
        self.tiles_layout = QVBoxLayout()
        self.charts_layout = QVBoxLayout()

        content = QWidget()
        self._content = content
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(self.alerts_box)
        content_layout.addWidget(self.tiles_caption)
        content_layout.addLayout(self.tiles_layout)
        content_layout.addWidget(self.charts_caption)
        content_layout.addLayout(self.charts_layout)
        content_layout.addStretch(1)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setObjectName("dashboard_scroll")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(content)

        layout = QVBoxLayout(self)
        layout.addWidget(self.as_of_label)
        layout.addLayout(action_row((self.snapshot_action, self.antidotes_action), self))
        layout.addWidget(self.empty_label)
        layout.addWidget(self.scroll_area, 1)

        context.as_of_changed.connect(self._as_of_changed)
        context.data_changed.connect(self.refresh)
        context.translator_manager.language_changed.connect(self._language_changed)
        self._static_texts()
        self.refresh()

    # ----- texts

    def _static_texts(self) -> None:
        self.snapshot_action.retranslate()
        self.antidotes_action.retranslate()
        self.alerts_box.setTitle(QCoreApplication.translate("Dashboard", "Alerts"))
        self.tiles_caption.setText(QCoreApplication.translate("Dashboard", "Indicators"))
        self.charts_caption.setText(QCoreApplication.translate("Dashboard", "Charts"))

    def retranslate(self) -> None:
        """Re-apply every text of the page in the current language.

        The data is shown again from what was read last: a language change is not a data
        change, so nothing is read here (see :meth:`_language_changed`). Once the database was
        closed there is nothing to show again: what was read from it is dropped.
        """
        self._static_texts()
        if self.context.services.dashboard is None:
            self._data = None
            self._problem = None
            self._types, self._sources, self._stock_types = {}, {}, {}
        self._render()

    def _language_changed(self, _code: str) -> None:
        """The translator manager announced a language: texts and a fresh read, once.

        The ``LanguageChange`` event Qt posts for the same switch only re-renders
        (:meth:`retranslate`), so a language switch reads the services exactly once.
        """
        self._static_texts()
        self.refresh()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- data

    def _as_of_changed(self, _value: object) -> None:
        self.refresh()

    def _lookups(
        self,
    ) -> tuple[dict[str, AssetTypeView], dict[str, SourceView], dict[str, StockTypeView]]:
        """The user-defined asset types, funding sources and stock types, for the display names."""
        infrastructure = self.context.services.infrastructure
        budget = self.context.services.budget
        stock = self.context.services.stock
        types: dict[str, AssetTypeView] = {}
        if infrastructure is not None:
            types = {t.code: t for t in infrastructure.list_types(include_inactive=True)}
        sources: dict[str, SourceView] = {}
        if budget is not None:
            sources = {s.code: s for s in budget.list_sources(include_inactive=True)}
        stock_types: dict[str, StockTypeView] = {}
        if stock is not None:
            stock_types = {t.code: t for t in stock.list_types(include_inactive=True)}
        return types, sources, stock_types

    def refresh(self) -> None:
        """Read the dashboard for the as-of date again and rebuild what is shown.

        A stored setting that cannot be used (``CORRUPT_SETTING``) or any other service error
        leaves the page empty with a translated message; nothing is raised from a slot.
        """
        service = self.context.services.dashboard
        self._data = None
        self._problem = None
        self._types, self._sources, self._stock_types = {}, {}, {}
        if service is not None:
            try:
                self._data = service.data(self.context.as_of)
                self._types, self._sources, self._stock_types = self._lookups()
            except ServiceError as error:
                self._data = None
                self._types, self._sources, self._stock_types = {}, {}, {}
                self._problem = error.code
        self._render()

    def _render(self) -> None:
        """Show what the last :meth:`refresh` read, in the current language."""
        lang = current_language(self.context)
        data = self._data
        self.as_of_label.setText(as_of_text(self.context.as_of, lang))
        if self._problem is None:
            self.empty_label.setText(
                QCoreApplication.translate("Dashboard", "No database is open.")
            )
        else:
            self.empty_label.setText(error_label(self._problem))
        self.empty_label.setVisible(data is None)
        self.scroll_area.setVisible(data is not None)
        if data is None:
            self._show_tiles((), DisplayNames(lang))
            for severity in Severity:
                self.alert_labels[severity].setText("")
            self._show_charts((), DisplayNames(lang))
        else:
            names = DisplayNames(lang, self._types, self._sources, self._stock_types)
            self._show_tiles(data.tiles, names)
            for severity in Severity:
                text = alert_text(severity.value, data.alert_counts.get(severity, 0), lang)
                self.alert_labels[severity].setText(text)
                self.alert_icons[severity].setAccessibleName(text)
            self._show_charts(data.charts, names)
        self._update_actions()
        # Tiles and charts come and go: the Tab chain follows the layout again.
        apply_tab_order(self)

    def _show_tiles(self, tiles: tuple[Tile, ...], names: DisplayNames) -> None:
        _clear(self.tiles_layout)
        self.tile_widgets = []
        by_module: dict[Module, list[Tile]] = {}
        for tile in tiles:
            by_module.setdefault(tile.module, []).append(tile)
        for module in Module:
            group = by_module.get(module)
            if not group:
                continue
            box = QGroupBox(module_title(module.value), self._content)
            box.setObjectName(f"module_{module.value.lower()}")
            grid = QGridLayout(box)
            for index, tile in enumerate(group):
                widget = TileWidget(tile, names, box)
                self.tile_widgets.append(widget)
                grid.addWidget(widget, index // _TILE_COLUMNS, index % _TILE_COLUMNS)
            self.tiles_layout.addWidget(box)

    def _show_charts(self, specs: tuple[ChartSpec, ...], names: DisplayNames) -> None:
        keys = [spec.key for spec in specs]
        for key in [key for key in self._panels if key not in keys]:
            gone = self._panels.pop(key)
            self.charts_layout.removeWidget(gone)
            gone.hide()  # deleted in place, as in _clear
            gone.deleteLater()
        for kept in self._panels.values():
            self.charts_layout.removeWidget(kept)
        for spec in specs:
            panel = self._panels.get(spec.key)
            if panel is None:
                # Created inside the scroll content, not reparented later: a widget without a
                # parent first gets its place in the Tab chain apart from the page.
                panel = ChartPanel(spec.key, self._content)
                self._panels[spec.key] = panel
            panel.set_content(spec, names)
            self.charts_layout.addWidget(panel)
        self._panel_order = keys

    # ----- what the tests and callers look at

    def tile_for(self, code: str, dimension: str = "") -> TileWidget | None:
        """The tile of ``code`` and ``dimension`` (``None`` when there is none)."""
        for widget in self.tile_widgets:
            if (widget.tile.code, widget.tile.dimension) == (code, dimension):
                return widget
        return None

    def chart_panels(self) -> list[ChartPanel]:
        """The chart panels in the order of the service."""
        return [self._panels[key] for key in self._panel_order]

    def chart_panel(self, key: str) -> ChartPanel | None:
        """The panel of the chart with ``key``."""
        return self._panels.get(key)

    # ----- the snapshot action (T8.1)

    def _snapshots(self) -> SnapshotService | None:
        """The snapshot service, once the shell provides it (``Services.snapshots``)."""
        service: object = getattr(self.context.services, "snapshots", None)
        return service if isinstance(service, SnapshotService) else None

    def _update_actions(self) -> None:
        self.context.set_edit_enabled(self.snapshot_action, self._snapshots() is not None)

    def open_antidotes(self) -> bool:
        """Show the page "antidotes" in the main window; ``False`` when it is not registered.

        Pattern of the Alerts page: the key is looked up in the registry and the top-level
        widget of this page (the main window) switches to it. It changes no data.
        """
        # Imported here: the registry imports this module to register the page.
        from cbrn_dashboard.ui.shell import registry

        key = "antidotes"
        if key not in {spec.key for spec in registry.pages()}:
            return False
        show_page = getattr(self.window(), "show_page", None)
        if callable(show_page):
            show_page(key)
            return True
        return False

    def record_snapshot(self) -> None:
        """Record a manual snapshot of the as-of date; a past date is recorded as retroactive."""
        found = self._snapshots()
        if found is None or self.context.read_only:
            return
        service: SnapshotService = found
        as_of = self.context.as_of
        title = QCoreApplication.translate("Dashboard", "Record snapshot")
        lang = current_language(self.context)
        if as_of < self.context.clock.local_date():
            question = QCoreApplication.translate(
                "Dashboard", "Record a retroactive snapshot for %1?"
            ).replace("%1", format_date(as_of, lang))
            if not self.context.prompts.confirm(self, title, question):
                return
        recorded: list[SnapshotView] = []

        def record() -> object:
            view = service.record(as_of, origin=SnapshotOrigin.MANUAL)
            recorded.append(view)
            return view

        if apply_change(self.context, self, error_label, record) and recorded:
            message = (
                QCoreApplication.translate("Dashboard", "Snapshot recorded for %1 (origin: %2).")
                .replace("%1", format_date(recorded[0].as_of, lang))
                .replace("%2", origin_label(recorded[0].origin.value))
            )
            self.context.prompts.info(self, title, message)


# --------------------------------------------------------------------------- registry factories


def page_title() -> str:
    return QCoreApplication.translate("Dashboard", "Dashboard")


def create_page(context: AppContext) -> QWidget:
    return DashboardPage(context)
