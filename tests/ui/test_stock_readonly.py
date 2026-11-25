# SPDX-License-Identifier: GPL-3.0-or-later
"""Read-only mode and the stock UI (PLAN.md T11.18).

Every stock edit action is disabled: the Stock tab of Infrastructure, the antidotes page, and the
Settings sections "Stock item types" (stock.types) and the alert windows with the P11 field. What
only navigates or reads stays enabled: the tabs and the type filter, the schedule horizon, "Open
record" and the report and export actions of Reports. All data is fictitious.
"""

from datetime import date

import pytest
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.stock import MovementKind
from cbrn_dashboard.services.stock import (
    InitialReceipt,
    LotInput,
    MovementInput,
    StockService,
)
from cbrn_dashboard.ui.antidotes.page import ALERTS_TAB, AntidotesPage
from cbrn_dashboard.ui.infrastructure.page import STOCK_TAB, InfrastructurePage
from cbrn_dashboard.ui.reports.page import ReportsPage
from cbrn_dashboard.ui.settings.sections import AlertsSection
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.stock.settings import StockTypesSection

pytestmark = pytest.mark.ui

AS_OF = date(2026, 3, 5)


def _service(context: AppContext) -> StockService:
    service = context.services.stock
    assert service is not None
    return service


def _add_lot(context: AppContext, type_code: str, lot_code: str, expires: date | None) -> int:
    view = _service(context).get_type_by_code(type_code)
    assert view is not None
    lot_id = _service(context).create_lot(
        LotInput(type_id=view.id, lot_code=lot_code, expires_on=expires),
        InitialReceipt(moved_on=date(2026, 1, 10), quantity=50),
    )
    _service(context).record_movement(
        lot_id,
        MovementInput(moved_on=date(2026, 2, 1), kind=MovementKind.ISSUE, quantity=5),
    )
    return lot_id


def test_the_stock_tab_of_infrastructure_disables_every_edit_and_keeps_the_navigation(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_lot(app_context, "GLOVE", "G1", None)
    app_context.read_only = True
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    page.type_combo.setCurrentIndex(page.type_combo.findData("stock:GLOVE"))
    page.stock_panel.lots_view.selectRow(0)
    page.stock_panel.movements_view.selectRow(0)

    targets = app_context.edit_targets()
    assert len(page.stock_panel._actions) == 6
    for action in page.stock_panel._actions:
        assert action in targets
        assert not action.isEnabled()
    # navigation: the tabs, the type filter, the tables and the hook of "Open record" still work
    assert page.tabs.currentIndex() == STOCK_TAB
    assert page.tabs.isEnabled()
    assert page.type_combo.isEnabled()
    assert page.stock_panel.lots_view.isEnabled()
    assert page.show_stock_item("GLOVE")
    assert page.type_combo.currentData() == "stock:GLOVE"


def test_the_antidotes_page_disables_every_edit_and_keeps_open_record_and_the_horizon(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_lot(app_context, "ANTIDOTE_CHEMICAL", "L-EXP", date(2026, 2, 1))
    app_context.set_as_of(AS_OF)
    app_context.read_only = True
    page = AntidotesPage(app_context)
    qtbot.addWidget(page)

    targets = app_context.edit_targets()
    assert len(page.panel._actions) == 6
    for action in page.panel._actions:
        assert action in targets
        assert not action.isEnabled()
    assert page.open_action not in targets  # it changes no data

    page.tabs.setCurrentIndex(ALERTS_TAB)
    refs = [alert.subject_ref for alert in page.shown_alerts()]
    page.alerts_view.selectRow(refs.index("L-EXP"))
    assert page.open_action.isEnabled()
    assert page.horizon_combo.isEnabled()
    assert page.type_combo.isEnabled()
    page.horizon_combo.setCurrentIndex(0)
    assert page.horizon_months() == 6
    page.open_action.trigger()
    selected = page.panel.selected_lot()
    assert selected is not None
    assert selected.lot_code == "L-EXP"
    assert not page.panel.add_lot_action.isEnabled()


def test_settings_stock_types_and_the_p11_field_are_disabled(
    app_context: AppContext, qtbot: QtBot
) -> None:
    app_context.read_only = True
    types = StockTypesSection(app_context)
    alerts = AlertsSection(app_context)
    qtbot.addWidget(types)
    qtbot.addWidget(alerts)

    registered = app_context.edit_targets()
    assert len(types._actions) == 5
    for action in types._actions:
        assert action in registered
        assert not action.isEnabled()
    for control in (alerts.stock_edit, alerts.save_button):
        assert control in registered
        assert not control.isEnabled()
    assert types.view.isEnabled()  # the list can still be read and selected


def test_the_report_and_export_actions_of_reports_stay_enabled(
    app_context: AppContext, qtbot: QtBot
) -> None:
    app_context.read_only = True
    page = ReportsPage(app_context)
    qtbot.addWidget(page)

    targets = app_context.edit_targets()
    for action in (
        page.report_action,
        page.csv_action,
        page.validation_action,
        page.templates_action,
    ):
        assert action not in targets
        assert action.isEnabled()
    for action in (page.import_action, page.record_action, page.withdraw_action):
        assert action in targets
        assert not action.isEnabled()
