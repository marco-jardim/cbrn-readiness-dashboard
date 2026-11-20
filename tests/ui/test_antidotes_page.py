# SPDX-License-Identifier: GPL-3.0-or-later
"""The page "Antidotes and decontaminants": filter, three tabs, alerts, read-only (PLAN.md T11.11).

The tests run in en-US and compare with the label functions where a catalogue could change the
wording. The expectations about the schedule are read from ``StockService.expiry_schedule`` (the
page must show exactly what the service computes); the other expectations are written by hand from
the lots the tests create.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.alerts import AlertKind
from cbrn_dashboard.domain.indicators import Module
from cbrn_dashboard.domain.stock import (
    ANTIDOTE_PAGE_CATEGORIES,
    MovementKind,
    ScheduleBucketKind,
)
from cbrn_dashboard.services.stock import (
    InitialReceipt,
    LotInput,
    MovementInput,
    StockService,
    StockTypeInput,
)
from cbrn_dashboard.ui.antidotes.page import (
    ALERTS_TAB,
    DEFAULT_HORIZON,
    HORIZONS,
    LOTS_TAB,
    SCHEDULE_TAB,
    AntidotesPage,
    create_page,
    page_title,
)
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import format_month
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.widgets import ModuleTableModel, current_language
from cbrn_dashboard.ui.stock.labels import lot_status_label
from tests.ui._walk import assert_fully_translated

pytestmark = pytest.mark.ui

AS_OF = date(2026, 3, 5)
USER_TYPE = "USER-ANT"
EXPECTED_CODES = {
    "ANTIDOTE_CHEMICAL",
    "ANTIDOTE_RAD_NUCLEAR",
    "ANTIDOTE_BIOLOGICAL",
    "DECONTAMINANT",
    USER_TYPE,
}


# --------------------------------------------------------------------------- helpers


def _service(context: AppContext) -> StockService:
    service = context.services.stock
    assert service is not None
    return service


def _type_id(context: AppContext, code: str) -> int:
    view = _service(context).get_type_by_code(code)
    assert view is not None
    return view.id


def _add_user_type(context: AppContext) -> int:
    return _service(context).create_type(
        StockTypeInput(code=USER_TYPE, category="antidote", label_pt_br="Antidoto de teste")
    )


def _add_lot(
    context: AppContext,
    *,
    code: str = "ANTIDOTE_CHEMICAL",
    lot_code: str = "L1",
    expires: date | None = date(2026, 6, 1),
    received: date = date(2026, 2, 1),
    quantity: int = 50,
) -> int:
    return _service(context).create_lot(
        LotInput(type_id=_type_id(context, code), lot_code=lot_code, expires_on=expires),
        InitialReceipt(moved_on=received, quantity=quantity),
    )


def _page(context: AppContext, qtbot: QtBot) -> AntidotesPage:
    context.set_as_of(AS_OF)
    page = AntidotesPage(context)
    qtbot.addWidget(page)
    return page


def _cell(model: ModuleTableModel, row: int, key: str) -> str:
    column = [item.key for item in model.COLUMNS].index(key)
    return str(model.index(row, column).data())


def _filter_codes(page: AntidotesPage) -> list[str]:
    combo = page.type_combo
    return [str(combo.itemData(index)) for index in range(1, combo.count())]


def _lot_codes(page: AntidotesPage) -> list[str]:
    return sorted(row.row.lot_code for row in page.panel.lots_model.rows())


def _schedule_lots(page: AntidotesPage) -> list[str]:
    return sorted(row.lot.lot_code for row in page.schedule_model.rows())


def _schedule_rows(page: AntidotesPage) -> list[tuple[ScheduleBucketKind, date | None, int]]:
    return [(row.kind, row.month, row.lot.lot_id) for row in page.schedule_model.rows()]


def _expected_rows(
    context: AppContext, months: int
) -> list[tuple[ScheduleBucketKind, date | None, int]]:
    buckets = _service(context).expiry_schedule(AS_OF, months, ANTIDOTE_PAGE_CATEGORIES)
    return [(bucket.kind, bucket.month, lot.lot_id) for bucket in buckets for lot in bucket.lots]


def _select_alert(page: AntidotesPage, ref: str) -> None:
    refs = [alert.subject_ref for alert in page.shown_alerts()]
    page.alerts_view.selectRow(refs.index(ref))


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


# --------------------------------------------------------------------------- registry, structure


def test_the_page_is_registered_between_infrastructure_and_exercises() -> None:
    specs = registry.pages()
    keys = [spec.key for spec in specs]
    assert keys.index("infrastructure") < keys.index("antidotes") < keys.index("exercises")
    (spec,) = [spec for spec in specs if spec.key == "antidotes"]
    assert spec.order == 25
    assert spec.title is page_title
    assert spec.factory is create_page


def test_the_page_has_three_tabs_and_a_note(app_context: AppContext, qtbot: QtBot) -> None:
    page = _page(app_context, qtbot)
    assert page.tabs.count() == 3
    assert page.tabs.widget(LOTS_TAB) is page.panel
    assert page.tabs.widget(SCHEDULE_TAB) is page.schedule_tab
    assert page.tabs.widget(ALERTS_TAB) is page.alerts_tab
    assert page.tabs.tabText(LOTS_TAB) == QCoreApplication.translate(
        "Antidotes", "Lots and movements"
    )
    assert page.tabs.tabText(SCHEDULE_TAB) == QCoreApplication.translate(
        "Antidotes", "Expiry schedule"
    )
    assert page.tabs.tabText(ALERTS_TAB) == QCoreApplication.translate("Antidotes", "Alerts")
    assert page.note_label.text() == QCoreApplication.translate(
        "Antidotes", "Management data: quantities, lots, expiry dates and prices."
    )
    assert "05/03/2026" in page.as_of_label.text() or "03/05/2026" in page.as_of_label.text()
    assert page_title() == QCoreApplication.translate("Antidotes", "Antidotes and decontaminants")


def test_the_page_builds_without_services(app_context: AppContext, qtbot: QtBot) -> None:
    app_context.services.stock = None
    page = _page(app_context, qtbot)
    assert _filter_codes(page) == []
    assert page.schedule_model.rowCount() == 0
    assert page.alerts_model.rowCount() == 0
    page.refresh()


# --------------------------------------------------------------------------- the type filter


def test_the_filter_lists_only_antidote_and_decontaminant_types(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_user_type(app_context)
    page = _page(app_context, qtbot)
    codes = _filter_codes(page)
    assert set(codes) == EXPECTED_CODES
    assert len(codes) == len(EXPECTED_CODES)
    assert codes[-1] == "DECONTAMINANT"  # categories keep their order: antidotes first
    assert page.type_combo.itemText(0) == QCoreApplication.translate(
        "Antidotes", "All antidotes and decontaminants"
    )
    assert page.type_code() is None


def test_an_inactive_type_is_listed_only_while_it_has_lots(
    app_context: AppContext, qtbot: QtBot
) -> None:
    user_id = _add_user_type(app_context)
    _add_lot(app_context, code=USER_TYPE, lot_code="U1")
    page = _page(app_context, qtbot)
    service = _service(app_context)

    service.deactivate_type(user_id)
    app_context.notify_data_changed()
    assert USER_TYPE in _filter_codes(page)  # inactive, but it has a lot

    other_id = service.create_type(
        StockTypeInput(code="USER-EMPTY", category="decontaminant", label_pt_br="Sem lotes")
    )
    app_context.notify_data_changed()
    assert "USER-EMPTY" in _filter_codes(page)
    service.deactivate_type(other_id)
    app_context.notify_data_changed()
    assert "USER-EMPTY" not in _filter_codes(page)


def test_only_antidote_and_decontaminant_lots_are_shown(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_user_type(app_context)
    _add_lot(app_context, code="ANTIDOTE_CHEMICAL", lot_code="L1")
    _add_lot(app_context, code=USER_TYPE, lot_code="U1")
    _add_lot(app_context, code="DECONTAMINANT", lot_code="D1")
    _add_lot(app_context, code="GLOVE", lot_code="G1", expires=date(2026, 5, 1))
    _add_lot(app_context, code="DETECTOR_CHEMICAL", lot_code="X1", expires=None)
    page = _page(app_context, qtbot)
    assert _lot_codes(page) == ["D1", "L1", "U1"]
    assert {row.summary.type_code for row in page.panel.summary_model.rows()} == {
        "ANTIDOTE_CHEMICAL",
        USER_TYPE,
        "DECONTAMINANT",
    }
    assert _schedule_lots(page) == ["D1", "L1", "U1"]


def test_the_filter_limits_the_lots_and_the_schedule(app_context: AppContext, qtbot: QtBot) -> None:
    _add_user_type(app_context)
    _add_lot(app_context, code="ANTIDOTE_CHEMICAL", lot_code="L1")
    _add_lot(app_context, code=USER_TYPE, lot_code="U1")
    page = _page(app_context, qtbot)

    page.set_type_filter(USER_TYPE)
    assert page.type_code() == USER_TYPE
    assert page.panel.type_filter == USER_TYPE
    assert _lot_codes(page) == ["U1"]
    assert _schedule_lots(page) == ["U1"]

    page.set_type_filter("ANTIDOTE_CHEMICAL")
    assert _lot_codes(page) == ["L1"]
    assert _schedule_lots(page) == ["L1"]

    page.set_type_filter(None)
    assert page.panel.type_filter is None
    assert _lot_codes(page) == ["L1", "U1"]
    assert _schedule_lots(page) == ["L1", "U1"]


def test_a_filter_that_disappears_falls_back_to_every_type(
    app_context: AppContext, qtbot: QtBot
) -> None:
    user_id = _add_user_type(app_context)
    _add_lot(app_context, code="ANTIDOTE_CHEMICAL", lot_code="L1")
    page = _page(app_context, qtbot)
    page.set_type_filter(USER_TYPE)
    assert page.type_code() == USER_TYPE
    _service(app_context).delete_type(user_id)
    app_context.notify_data_changed()
    assert page.type_code() is None
    assert _lot_codes(page) == ["L1"]


# --------------------------------------------------------------------------- the expiry schedule


def test_the_horizon_offers_6_12_and_24_months_and_starts_at_12(
    app_context: AppContext, qtbot: QtBot
) -> None:
    page = _page(app_context, qtbot)
    assert HORIZONS == (6, 12, 24)
    combo = page.horizon_combo
    assert [combo.itemData(index) for index in range(combo.count())] == [6, 12, 24]
    assert page.horizon_months() == DEFAULT_HORIZON == 12
    for position, months in enumerate(HORIZONS):
        assert page.horizon_combo.itemText(position) == QCoreApplication.translate(
            "Antidotes", "%n month(s)", None, months
        )


def test_the_schedule_is_what_the_service_computes(app_context: AppContext, qtbot: QtBot) -> None:
    _add_user_type(app_context)
    _add_lot(app_context, lot_code="GONE", expires=date(2026, 2, 1), received=date(2026, 1, 10))
    _add_lot(app_context, lot_code="SOON", expires=date(2026, 6, 1))
    _add_lot(app_context, code="DECONTAMINANT", lot_code="MID", expires=date(2026, 12, 15))
    _add_lot(app_context, code=USER_TYPE, lot_code="FAR", expires=date(2027, 6, 1))
    emptied = _add_lot(app_context, lot_code="EMPTY", expires=date(2026, 7, 1), quantity=5)
    _service(app_context).record_movement(
        emptied,
        MovementInput(moved_on=date(2026, 2, 20), kind=MovementKind.DISPOSAL, quantity=5),
    )
    page = _page(app_context, qtbot)
    lang = current_language(app_context)

    rows = _schedule_rows(page)
    assert rows == _expected_rows(app_context, 12)
    assert _schedule_lots(page) == ["FAR", "GONE", "MID", "SOON"]  # the empty lot is not listed
    by_lot = {row.lot.lot_code: row for row in page.schedule_model.rows()}
    assert by_lot["GONE"].kind is ScheduleBucketKind.EXPIRED
    assert by_lot["SOON"].kind is ScheduleBucketKind.MONTH
    assert by_lot["SOON"].month == date(2026, 6, 1)
    assert by_lot["FAR"].kind is ScheduleBucketKind.LATER
    index = {row.lot.lot_code: i for i, row in enumerate(page.schedule_model.rows())}
    assert _cell(page.schedule_model, index["SOON"], "period") == format_month(
        date(2026, 6, 1), lang
    )
    assert _cell(page.schedule_model, index["GONE"], "period") == QCoreApplication.translate(
        "Stock", "Expired (still in stock)"
    )
    assert _cell(page.schedule_model, index["FAR"], "period") == QCoreApplication.translate(
        "Stock", "Later"
    )
    assert _cell(page.schedule_model, index["SOON"], "status") == lot_status_label("EXPIRING")
    assert page.schedule_empty_label.isHidden()


def test_changing_the_horizon_reads_the_schedule_again(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_user_type(app_context)
    _add_lot(app_context, lot_code="SOON", expires=date(2026, 6, 1))
    far = _add_lot(app_context, code=USER_TYPE, lot_code="FAR", expires=date(2027, 6, 1))
    page = _page(app_context, qtbot)
    kinds = {row.lot.lot_code: row.kind for row in page.schedule_model.rows()}
    assert kinds == {"SOON": ScheduleBucketKind.MONTH, "FAR": ScheduleBucketKind.LATER}

    page.horizon_combo.setCurrentIndex(HORIZONS.index(24))
    assert page.horizon_months() == 24
    assert _schedule_rows(page) == _expected_rows(app_context, 24)
    far_row = next(row for row in page.schedule_model.rows() if row.lot.lot_id == far)
    assert far_row.kind is ScheduleBucketKind.MONTH
    assert far_row.month == date(2027, 6, 1)

    page.horizon_combo.setCurrentIndex(HORIZONS.index(6))
    assert _schedule_rows(page) == _expected_rows(app_context, 6)
    kinds = {row.lot.lot_code: row.kind for row in page.schedule_model.rows()}
    assert kinds == {"SOON": ScheduleBucketKind.MONTH, "FAR": ScheduleBucketKind.LATER}


def test_an_empty_schedule_shows_its_empty_state(app_context: AppContext, qtbot: QtBot) -> None:
    page = _page(app_context, qtbot)
    assert page.schedule_model.rowCount() == 0
    assert not page.schedule_empty_label.isHidden()
    _add_lot(app_context, lot_code="SOON")
    app_context.notify_data_changed()
    assert page.schedule_model.rowCount() == 1
    assert page.schedule_empty_label.isHidden()


def test_the_schedule_follows_the_as_of_date(app_context: AppContext, qtbot: QtBot) -> None:
    _add_lot(app_context, lot_code="SOON", expires=date(2026, 6, 1))
    page = _page(app_context, qtbot)
    assert [row.kind for row in page.schedule_model.rows()] == [ScheduleBucketKind.MONTH]
    app_context.set_as_of(date(2026, 7, 1))
    assert [row.kind for row in page.schedule_model.rows()] == [ScheduleBucketKind.EXPIRED]
    app_context.set_as_of(AS_OF)
    assert [row.kind for row in page.schedule_model.rows()] == [ScheduleBucketKind.MONTH]


# --------------------------------------------------------------------------- the alerts tab


def _stock_alert_data(context: AppContext) -> None:
    """An expired antidote lot, an expiring decontaminant lot and an expired glove lot."""
    _add_lot(context, lot_code="L-EXP", expires=date(2026, 2, 1), received=date(2026, 1, 10))
    _add_lot(context, code="DECONTAMINANT", lot_code="D-SOON", expires=date(2026, 4, 1))
    _add_lot(
        context,
        code="GLOVE",
        lot_code="G-EXP",
        expires=date(2026, 2, 1),
        received=date(2026, 1, 10),
    )


def test_the_alerts_tab_shows_only_stock_alerts_of_these_categories(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _stock_alert_data(app_context)
    page = _page(app_context, qtbot)
    everything = app_context.services.alerts
    assert everything is not None
    assert "G-EXP" in {alert.subject_ref for alert in everything.alerts(AS_OF)}  # it is an alert

    shown = page.shown_alerts()
    assert {alert.subject_ref for alert in shown} == {"L-EXP", "D-SOON"}
    assert {alert.kind for alert in shown} == {AlertKind.LOT_EXPIRED, AlertKind.LOT_EXPIRING}
    assert all(alert.module is Module.STOCK for alert in shown)
    assert page.alerts_count_label.text() == QCoreApplication.translate(
        "Antidotes", "%n alert(s) shown", None, 2
    )
    assert page.alerts_empty_label.isHidden()


def test_an_item_type_alert_belongs_to_the_page_too(app_context: AppContext, qtbot: QtBot) -> None:
    _service(app_context).set_minimum(_type_id(app_context, "ANTIDOTE_BIOLOGICAL"), 5)
    page = _page(app_context, qtbot)
    kinds = {alert.kind for alert in page.shown_alerts()}
    assert AlertKind.LOW_STOCK in kinds


def test_the_alerts_tab_is_empty_without_stock_alerts(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_lot(app_context, lot_code="FINE", expires=date(2028, 1, 1))
    page = _page(app_context, qtbot)
    assert page.shown_alerts() == []
    assert not page.alerts_empty_label.isHidden()
    assert not page.open_action.isEnabled()
    assert page.open_selected() is False


def test_open_record_selects_the_lot_in_the_first_tab(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _stock_alert_data(app_context)
    page = _page(app_context, qtbot)
    page.tabs.setCurrentIndex(ALERTS_TAB)
    assert not page.open_action.isEnabled()

    _select_alert(page, "L-EXP")
    assert page.open_action.isEnabled()
    page.open_action.trigger()
    assert page.tabs.currentIndex() == LOTS_TAB
    selected = page.panel.selected_lot()
    assert selected is not None
    assert selected.lot_code == "L-EXP"
    assert page.panel.movements_model.rowCount() == 1


def test_activating_an_alert_row_does_the_same(app_context: AppContext, qtbot: QtBot) -> None:
    _stock_alert_data(app_context)
    page = _page(app_context, qtbot)
    page.tabs.setCurrentIndex(ALERTS_TAB)
    _select_alert(page, "D-SOON")
    refs = [alert.subject_ref for alert in page.shown_alerts()]
    page.alerts_view.activated.emit(page.alerts_model.index(refs.index("D-SOON"), 0))
    assert page.tabs.currentIndex() == LOTS_TAB
    selected = page.panel.selected_lot()
    assert selected is not None
    assert selected.lot_code == "D-SOON"


def test_open_record_resets_a_filter_that_would_hide_the_lot(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _stock_alert_data(app_context)
    page = _page(app_context, qtbot)
    page.set_type_filter("DECONTAMINANT")
    assert _lot_codes(page) == ["D-SOON"]
    _select_alert(page, "L-EXP")
    assert page.open_selected() is True
    assert page.type_code() is None
    selected = page.panel.selected_lot()
    assert selected is not None
    assert selected.lot_code == "L-EXP"


def test_open_record_keeps_a_filter_that_shows_the_lot(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _stock_alert_data(app_context)
    page = _page(app_context, qtbot)
    page.set_type_filter("ANTIDOTE_CHEMICAL")
    _select_alert(page, "L-EXP")
    assert page.open_selected() is True
    assert page.type_code() == "ANTIDOTE_CHEMICAL"
    selected = page.panel.selected_lot()
    assert selected is not None
    assert selected.lot_code == "L-EXP"


def test_open_record_of_an_item_type_alert_sets_the_type_filter(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _service(app_context).set_minimum(_type_id(app_context, "ANTIDOTE_BIOLOGICAL"), 5)
    page = _page(app_context, qtbot)
    page.tabs.setCurrentIndex(ALERTS_TAB)
    _select_alert(page, "ANTIDOTE_BIOLOGICAL")
    page.open_action.trigger()
    assert page.tabs.currentIndex() == LOTS_TAB
    assert page.type_code() == "ANTIDOTE_BIOLOGICAL"
    assert page.panel.type_filter == "ANTIDOTE_BIOLOGICAL"


def test_the_alerts_follow_the_as_of_date(app_context: AppContext, qtbot: QtBot) -> None:
    _add_lot(app_context, lot_code="L1", expires=date(2026, 6, 1))
    page = _page(app_context, qtbot)
    assert {alert.kind for alert in page.shown_alerts()} == {AlertKind.LOT_EXPIRING}
    app_context.set_as_of(date(2026, 7, 1))
    assert {alert.kind for alert in page.shown_alerts()} == {AlertKind.LOT_EXPIRED}
    app_context.set_as_of(date(2026, 1, 15))  # before the first receipt: no stock, no alert
    assert page.shown_alerts() == []


# --------------------------------------------------------------------------- language, read-only


def test_the_page_follows_the_language(app_context: AppContext, qtbot: QtBot) -> None:
    _add_lot(app_context, lot_code="SOON", expires=date(2026, 6, 1))
    page = _page(app_context, qtbot)
    app_context.translator_manager.set_language("pt_BR")
    assert page_title() == "Ant\u00eddotos e descontaminantes"
    assert page.tabs.tabText(LOTS_TAB) == "Lotes e movimenta\u00e7\u00f5es"
    assert page.tabs.tabText(SCHEDULE_TAB) == "Aprazamento de vencimentos"
    assert page.tabs.tabText(ALERTS_TAB) == "Alertas"
    assert page.type_combo.itemText(0) == "Todos os ant\u00eddotos e descontaminantes"
    assert page.note_label.text() == (
        "Dados de gest\u00e3o: quantidades, lotes, validades e pre\u00e7os."
    )
    assert page.open_action.text() == "Abrir registro"
    assert page.horizon_caption.text() == "Horizonte"
    assert _cell(page.schedule_model, 0, "period") == format_month(date(2026, 6, 1), "pt_BR")
    app_context.translator_manager.set_language("en_US")
    assert page.tabs.tabText(SCHEDULE_TAB) == "Expiry schedule"
    assert _cell(page.schedule_model, 0, "period") == "June 2026"


def test_read_only_mode_disables_every_edit_but_not_the_navigation(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _stock_alert_data(app_context)
    app_context.read_only = True
    page = _page(app_context, qtbot)
    targets = app_context.edit_targets()
    assert len(page.panel._actions) == 6
    for action in page.panel._actions:
        assert action in targets
        assert not action.isEnabled()
    assert page.open_action not in targets  # navigation: it changes no data

    page.tabs.setCurrentIndex(ALERTS_TAB)
    _select_alert(page, "L-EXP")
    assert page.open_action.isEnabled()
    page.open_action.trigger()
    selected = page.panel.selected_lot()
    assert selected is not None
    assert selected.lot_code == "L-EXP"
    assert not page.panel.add_lot_action.isEnabled()
    assert not page.panel.record_action.isEnabled()
    page.horizon_combo.setCurrentIndex(0)  # the schedule still works
    assert page.horizon_months() == 6


# --------------------------------------------------------------------------- pseudo-locale walk


def test_everything_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    pseudo_context.set_as_of(AS_OF)
    page = AntidotesPage(pseudo_context)
    qtbot.addWidget(page)
    assert_fully_translated(page)


def test_the_pseudo_locale_walk_with_data_and_every_tab_state(
    pseudo_context: AppContext, qtbot: QtBot
) -> None:
    pseudo_context.set_as_of(AS_OF)
    _add_user_type(pseudo_context)
    _stock_alert_data(pseudo_context)
    _add_lot(pseudo_context, code=USER_TYPE, lot_code="U1", expires=date(2027, 6, 1))
    page = AntidotesPage(pseudo_context)
    qtbot.addWidget(page)
    assert_fully_translated(page)
    for index in range(page.horizon_combo.count()):
        page.horizon_combo.setCurrentIndex(index)
        assert_fully_translated(page)
    _select_alert(page, "L-EXP")
    page.open_action.trigger()
    assert_fully_translated(page)
    page.set_type_filter(USER_TYPE)
    assert_fully_translated(page)
