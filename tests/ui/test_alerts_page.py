# SPDX-License-Identifier: GPL-3.0-or-later
"""The Alerts page: list, filters, navigation, language switch and pseudo-locale walk (T6.3)."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QComboBox, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.alerts import Alert
from cbrn_dashboard.domain.indicators import Module
from cbrn_dashboard.domain.infrastructure import AssetStatus, MaintenanceKind
from cbrn_dashboard.services.infrastructure import AssetInput, AssetTypeInput
from cbrn_dashboard.ui.alerts.models import page_key_for
from cbrn_dashboard.ui.alerts.page import AlertsPage, create_page, page_title
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.main_window import MainWindow
from tests.ui._alert_samples import (
    ALERTS,
    CERT_EXPIRED,
    CERT_EXPIRING,
    INDICATOR_WARNING,
    MAINT_OVERDUE,
    MAINT_SCHEDULE_UNKNOWN,
    MESSAGES,
)
from tests.ui._walk import assert_fully_translated, find_untranslated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")
COLUMNS = 5

EXERCISES_INDICATOR = replace(
    INDICATOR_WARNING, module=Module.EXERCISES, subject_ref="EX_PARTICIPANTS", dimension=""
)
BUDGET_INDICATOR = replace(
    INDICATOR_WARNING, module=Module.BUDGET, subject_ref="BUD_EXECUTION", dimension=""
)


# --------------------------------------------------------------------------- helpers


class _FakeAlerts:
    """The part of the alert service the page uses, over memory (it records the as-of dates)."""

    def __init__(self, alerts: list[Alert]) -> None:
        self.current = list(alerts)
        self.by_date: dict[date, list[Alert]] = {}
        self.calls: list[date] = []

    def alerts(self, as_of: date) -> list[Alert]:
        self.calls.append(as_of)
        return list(self.by_date.get(as_of, self.current))


class _Host(QWidget):
    """A top-level widget with the ``show_page`` of the main window; it records the keys."""

    def __init__(self) -> None:
        super().__init__()
        self.shown: list[str] = []

    def show_page(self, key: str) -> None:
        self.shown.append(key)


def _install(context: AppContext, alerts: list[Alert]) -> _FakeAlerts:
    fake = _FakeAlerts(alerts)
    vars(context.services)["alerts"] = fake
    return fake


def _page(context: AppContext, qtbot: QtBot) -> AlertsPage:
    page = AlertsPage(context)
    qtbot.addWidget(page)
    return page


def _hosted(context: AppContext, qtbot: QtBot) -> tuple[_Host, AlertsPage]:
    host = _Host()
    qtbot.addWidget(host)
    return host, AlertsPage(context, host)


def _cells(page: AlertsPage, row: int) -> list[str]:
    return [str(page.model.index(row, column).data()) for column in range(COLUMNS)]


def _headers(page: AlertsPage) -> list[str]:
    horizontal = Qt.Orientation.Horizontal
    return [str(page.model.headerData(column, horizontal)) for column in range(COLUMNS)]


def _refs(page: AlertsPage) -> list[str]:
    return [alert.subject_ref for alert in page.shown_alerts()]


def _pick(combo: QComboBox, code: str) -> None:
    index = combo.findData(code)
    assert index >= 0, code
    combo.setCurrentIndex(index)


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


# --------------------------------------------------------------------------- the list


def test_an_unreadable_setting_is_explained_in_the_page_and_never_raises(
    app_context: AppContext, qtbot: QtBot
) -> None:
    """P6-01: the real alert service raises CORRUPT_SETTING; the slots used to let it escape."""
    assert app_context.services.alerts is not None
    page = _page(app_context, qtbot)
    assert page.empty_label.text() == "No alerts for this date."
    assert app_context.conn is not None

    app_context.conn.execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)",
        ("config.maintenance_warning_days", "not json"),
    )
    app_context.notify_data_changed()  # a ServiceError inside the slot reached the crash dialog
    app_context.set_as_of(date(2026, 3, 6))
    assert not page.empty_label.isHidden()
    assert page.empty_label.text() == "A stored setting cannot be read."
    assert page.model.rowCount() == 0

    app_context.translator_manager.set_language("pt_BR")
    portuguese = "N\u00e3o foi poss\u00edvel ler uma configura\u00e7\u00e3o armazenada."
    qtbot.waitUntil(lambda: page.empty_label.text() == portuguese)
    app_context.translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: page.empty_label.text() == "No se puede leer un ajuste almacenado.")

    app_context.conn.execute("DELETE FROM setting WHERE key = 'config.maintenance_warning_days'")
    app_context.notify_data_changed()
    assert page.empty_label.text() == "No hay alertas para esta fecha."


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_unreadable_setting_message_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    pseudo_context.translator_manager.set_language(lang)
    page = _page(pseudo_context, qtbot)
    assert pseudo_context.conn is not None
    pseudo_context.conn.execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)",
        ("config.maintenance_warning_days", "not json"),
    )

    pseudo_context.notify_data_changed()

    assert not page.empty_label.isHidden()
    assert page.empty_label.text().startswith("\u27e6")
    assert_fully_translated(page, lang)


def test_the_page_lists_the_alerts_of_the_as_of_date(app_context: AppContext, qtbot: QtBot) -> None:
    fake = _install(app_context, ALERTS)
    page = _page(app_context, qtbot)
    assert fake.calls == [date(2026, 3, 5)]
    assert page.model.rowCount() == 7
    assert _headers(page) == ["Severity", "Module", "Subject", "Due date", "Message"]
    expected = [
        ("Critical", "Infrastructure", "DEMO-A001", "03/10/2025"),
        ("Critical", "Personnel", "DEMO-P001", "01/10/2026"),
        ("Critical", "Infrastructure", "INFRA_MAINT_OVERDUE (type=bed)", "-"),
        ("Warning", "Infrastructure", "DEMO-A002", "03/25/2026"),
        ("Warning", "Personnel", "DEMO-P002", "04/01/2026"),
        ("Warning", "Personnel", "PERS_CERT_VALID (level=A)", "-"),
        ("Information", "Infrastructure", "DEMO-A003", "-"),
    ]
    for row, (severity, module, subject, due) in enumerate(expected):
        assert _cells(page, row) == [severity, module, subject, due, MESSAGES["en_US"][row]]
    assert page.count_label.text() == "7 alerts shown"
    assert page.empty_label.isHidden()


def test_the_severity_is_shown_as_text_and_as_an_icon(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _install(app_context, ALERTS)
    page = _page(app_context, qtbot)
    for row in range(page.model.rowCount()):
        icon = page.model.index(row, 0).data(Qt.ItemDataRole.DecorationRole)
        assert isinstance(icon, QIcon)
        assert not icon.isNull()
        assert page.model.index(row, 1).data(Qt.ItemDataRole.DecorationRole) is None
    assert page.model.index(0, 0).data() == "Critical"


def test_the_message_follows_the_language_in_the_table(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _install(app_context, ALERTS)
    page = _page(app_context, qtbot)
    for lang in ("pt_BR", "es_ES", "en_US"):
        app_context.translator_manager.set_language(lang)
        assert [page.model.index(row, 4).data() for row in range(7)] == MESSAGES[lang]


def test_the_page_reads_the_real_alert_service(app_context: AppContext, qtbot: QtBot) -> None:
    infra = app_context.services.infrastructure
    assert infra is not None
    type_id = infra.create_type(AssetTypeInput("DEMO-TYPE", "Tipo demo"))

    def asset(tag: str, interval: int | None = None) -> int:
        data = AssetInput(
            tag=tag,
            type_id=type_id,
            in_service_from="2025-01-01",
            maintenance_interval_days=interval,
        )
        return infra.create_asset(data, AssetStatus.OPERATIONAL)

    overdue = asset("DEMO-A001", 30)
    infra.record_maintenance(overdue, "2025-02-10", MaintenanceKind.PREVENTIVE, "2025-03-10")
    asset("DEMO-A003")
    page = _page(app_context, qtbot)
    assert page.model.rowCount() == 2
    assert _cells(page, 0) == [
        "Critical",
        "Infrastructure",
        "DEMO-A001",
        "03/10/2025",
        "Maintenance of asset DEMO-A001 is overdue by 360 days.",
    ]
    assert _cells(page, 1) == [
        "Information",
        "Infrastructure",
        "DEMO-A003",
        "-",
        "The maintenance schedule of asset DEMO-A003 is unknown.",
    ]

    app_context.set_as_of(date(2025, 3, 1))  # a past date gives the alerts of that date
    assert _cells(page, 0) == [
        "Warning",
        "Infrastructure",
        "DEMO-A001",
        "03/10/2025",
        "Maintenance of asset DEMO-A001 is due in 9 days.",
    ]
    assert page.model.rowCount() == 2


def test_the_page_refreshes_when_the_as_of_date_or_the_data_change(
    app_context: AppContext, qtbot: QtBot
) -> None:
    fake = _install(app_context, ALERTS)
    fake.by_date[date(2026, 6, 1)] = [MAINT_SCHEDULE_UNKNOWN]
    page = _page(app_context, qtbot)
    assert page.model.rowCount() == 7

    app_context.set_as_of(date(2026, 6, 1))
    assert fake.calls[-1] == date(2026, 6, 1)
    assert _refs(page) == ["DEMO-A003"]
    assert page.count_label.text() == "1 alert shown"

    fake.by_date[date(2026, 6, 1)] = [CERT_EXPIRED, CERT_EXPIRING]
    app_context.notify_data_changed()
    assert _refs(page) == ["DEMO-P001", "DEMO-P002"]

    app_context.set_as_of(date(2026, 3, 5))
    assert page.model.rowCount() == 7


def test_the_selection_survives_a_refresh(app_context: AppContext, qtbot: QtBot) -> None:
    _install(app_context, ALERTS)
    page = _page(app_context, qtbot)
    page.view.selectRow(3)
    assert page.selected_alert() is not None
    assert page.selected_alert() == ALERTS[3]
    app_context.notify_data_changed()
    assert page.selected_alert() == ALERTS[3]


# --------------------------------------------------------------------------- filters


def test_the_module_filter_keeps_the_order_of_the_service(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _install(app_context, ALERTS)
    page = _page(app_context, qtbot)
    _pick(page.module_combo, "INFRASTRUCTURE")
    assert _refs(page) == ["DEMO-A001", "INFRA_MAINT_OVERDUE", "DEMO-A002", "DEMO-A003"]
    assert page.count_label.text() == "4 alerts shown"
    _pick(page.module_combo, "PERSONNEL")
    assert _refs(page) == ["DEMO-P001", "DEMO-P002", "PERS_CERT_VALID"]
    _pick(page.module_combo, "ALL")
    assert page.model.rowCount() == 7


def test_the_severity_filter(app_context: AppContext, qtbot: QtBot) -> None:
    _install(app_context, ALERTS)
    page = _page(app_context, qtbot)
    _pick(page.severity_combo, "CRITICAL")
    assert _refs(page) == ["DEMO-A001", "DEMO-P001", "INFRA_MAINT_OVERDUE"]
    _pick(page.severity_combo, "WARNING")
    assert _refs(page) == ["DEMO-A002", "DEMO-P002", "PERS_CERT_VALID"]
    _pick(page.severity_combo, "INFO")
    assert _refs(page) == ["DEMO-A003"]
    assert page.count_label.text() == "1 alert shown"
    _pick(page.severity_combo, "ALL")
    assert page.model.rowCount() == 7


def test_both_filters_combine_and_an_empty_result_says_so(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _install(app_context, ALERTS)
    page = _page(app_context, qtbot)
    _pick(page.module_combo, "PERSONNEL")
    _pick(page.severity_combo, "WARNING")
    assert _refs(page) == ["DEMO-P002", "PERS_CERT_VALID"]
    assert page.empty_label.isHidden()

    _pick(page.severity_combo, "INFO")  # no information alert in Personnel
    assert page.model.rowCount() == 0
    assert page.count_label.text() == "0 alerts shown"
    assert not page.empty_label.isHidden()
    assert page.empty_label.text() == "No alerts for this date."

    _pick(page.module_combo, "EXERCISES")
    _pick(page.severity_combo, "ALL")
    assert page.model.rowCount() == 0
    _pick(page.module_combo, "ALL")
    assert page.model.rowCount() == 7
    assert page.empty_label.isHidden()


def test_the_filters_stay_when_the_data_is_read_again(
    app_context: AppContext, qtbot: QtBot
) -> None:
    fake = _install(app_context, ALERTS)
    fake.by_date[date(2026, 6, 1)] = [MAINT_OVERDUE, CERT_EXPIRED, MAINT_SCHEDULE_UNKNOWN]
    page = _page(app_context, qtbot)
    _pick(page.module_combo, "INFRASTRUCTURE")
    app_context.set_as_of(date(2026, 6, 1))
    assert _refs(page) == ["DEMO-A001", "DEMO-A003"]


def test_the_filter_entries_are_named_in_the_language(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _install(app_context, ALERTS)
    page = _page(app_context, qtbot)
    modules = [page.module_combo.itemText(i) for i in range(page.module_combo.count())]
    severities = [page.severity_combo.itemText(i) for i in range(page.severity_combo.count())]
    assert modules == ["All modules", "Personnel", "Infrastructure", "Exercises", "Budget"]
    assert severities == ["All severities", "Critical", "Warning", "Information"]


# --------------------------------------------------------------------------- activation


@pytest.mark.parametrize(
    ("alert", "key"),
    [
        (MAINT_OVERDUE, "infrastructure"),
        (CERT_EXPIRED, "personnel"),
        (ALERTS[2], "infrastructure"),  # an indicator of the Infrastructure module
        (INDICATOR_WARNING, "personnel"),  # an indicator of the Personnel module
        (EXERCISES_INDICATOR, "exercises"),
        (BUDGET_INDICATOR, "budget"),
    ],
)
def test_activating_an_alert_asks_for_the_page_of_its_record(
    app_context: AppContext, qtbot: QtBot, alert: Alert, key: str
) -> None:
    _install(app_context, [MAINT_SCHEDULE_UNKNOWN, alert])
    host, page = _hosted(app_context, qtbot)
    requested: list[str] = []
    page.page_requested.connect(requested.append)
    assert page_key_for(alert) == key

    page.view.selectRow(1)
    page.view.activated.emit(page.model.index(1, 0))
    assert host.shown == [key]
    assert requested == [key]


def test_the_open_button_does_the_same_as_activating_the_row(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _install(app_context, ALERTS)
    host, page = _hosted(app_context, qtbot)
    assert not page.open_action.isEnabled()
    assert page.open_selected() is False
    assert host.shown == []

    page.view.selectRow(0)
    assert page.open_action.isEnabled()
    page.open_action.trigger()
    assert host.shown == ["infrastructure"]
    page.view.selectRow(1)
    page.open_action.trigger()
    assert host.shown == ["infrastructure", "personnel"]
    page.view.clearSelection()
    assert not page.open_action.isEnabled()


@pytest.mark.parametrize(
    ("row", "key"), [(0, "infrastructure"), (1, "personnel"), (6, "exercises"), (7, "budget")]
)
def test_activating_an_alert_switches_the_main_window_to_the_right_page(
    app_context: AppContext, qtbot: QtBot, row: int, key: str
) -> None:
    _install(app_context, [*ALERTS[:6], EXERCISES_INDICATOR, BUDGET_INDICATOR])
    spec = registry.PageSpec("alerts_under_test", 999, page_title, create_page)
    with registry.registered(spec):
        window = MainWindow(app_context)
        qtbot.addWidget(window)
        page = window.page_widget("alerts_under_test")
        assert isinstance(page, AlertsPage)
        window.show_page("alerts_under_test")
        assert window.pages.currentWidget() is page

        page.view.selectRow(row)
        page.view.activated.emit(page.model.index(row, 0))
        assert window.pages.currentWidget() is window.page_widget(key)
        assert window.pages.currentWidget() is not page


# --------------------------------------------------------------------------- language, services


def test_the_texts_follow_a_language_switch(app_context: AppContext, qtbot: QtBot) -> None:
    _install(app_context, ALERTS)
    page = _page(app_context, qtbot)
    _pick(page.module_combo, "INFRASTRUCTURE")

    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: page.module_caption.text() == "Módulo")
    assert page.severity_caption.text() == "Gravidade"
    assert page.module_combo.itemText(0) == "Todos os módulos"
    assert page.module_combo.itemText(3) == "Exercícios"
    assert page.severity_combo.itemText(0) == "Todas as gravidades"
    assert page.severity_combo.itemText(3) == "Informação"
    assert page.open_action.text() == "Abrir registro"
    assert page.count_label.text() == "4 alertas exibidos"
    assert _headers(page) == ["Gravidade", "Módulo", "Assunto", "Vencimento", "Mensagem"]
    assert _cells(page, 0) == [
        "Crítico",
        "Infraestrutura",
        "DEMO-A001",
        "10/03/2025",
        MESSAGES["pt_BR"][0],
    ]
    assert page.module_combo.currentData() == "INFRASTRUCTURE"  # the filter stays
    assert page_title() == "Alertas"

    app_context.translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: page.severity_caption.text() == "Gravedad")
    assert page_title() == "Alertas"
    assert page.empty_label.text() == "No hay alertas para esta fecha."
    assert page.count_label.text() == "4 alertas mostradas"
    assert _cells(page, 3)[:3] == ["Información", "Infraestructura", "DEMO-A003"]

    app_context.translator_manager.set_language("en_US")
    qtbot.waitUntil(lambda: page.severity_caption.text() == "Severity")
    assert page.count_label.text() == "4 alerts shown"
    assert page.open_action.text() == "Open record"
    assert _cells(page, 0)[4] == MESSAGES["en_US"][0]


def test_the_page_builds_without_an_alert_service(app_context: AppContext, qtbot: QtBot) -> None:
    app_context.services.alerts = None
    page = create_page(app_context)
    qtbot.addWidget(page)
    assert isinstance(page, AlertsPage)
    assert page.model.rowCount() == 0
    assert page.count_label.text() == "0 alerts shown"
    assert not page.empty_label.isHidden()
    assert not page.open_action.isEnabled()
    assert page.open_selected() is False


def test_the_page_only_reads_so_read_only_mode_does_not_disable_it(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _install(app_context, ALERTS)
    app_context.read_only = True
    host, page = _hosted(app_context, qtbot)
    page.view.selectRow(0)
    assert page.open_action.isEnabled()
    assert page.module_combo.isEnabled()
    assert page.severity_combo.isEnabled()
    assert page.open_action not in app_context.edit_targets()
    page.open_action.trigger()
    assert host.shown == ["infrastructure"]


# --------------------------------------------------------------------------- pseudo-locale walk


@pytest.mark.parametrize("state", ["no_alerts", "alerts", "filtered_to_nothing"])
def test_everything_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot, state: str
) -> None:
    if state != "no_alerts":
        _install(pseudo_context, ALERTS)
    page = _page(pseudo_context, qtbot)
    if state == "alerts":
        page.view.selectRow(0)
    if state == "filtered_to_nothing":
        _pick(page.module_combo, "EXERCISES")
        assert not page.empty_label.isHidden()
    assert_fully_translated(page)


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_pseudo_locale_walk_in_each_language(
    pseudo_context: AppContext, qtbot: QtBot, lang: str
) -> None:
    _install(pseudo_context, ALERTS)
    page = _page(pseudo_context, qtbot)
    page.view.selectRow(1)
    pseudo_context.translator_manager.set_language(lang)
    qtbot.waitUntil(lambda: not find_untranslated(page, lang))
    assert_fully_translated(page, lang)


def test_the_title_is_translated(pseudo_context: AppContext) -> None:
    assert page_title() == "\u27e6Alerts\u27e7"
