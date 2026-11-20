# SPDX-License-Identifier: GPL-3.0-or-later
"""Open record of a stock alert outside the antidote categories, in the real window (P11-08).

The demo glove lot DEMO-L011 has an expiring-lot alert; "Open record" must show the Stock (lots)
tab of Infrastructure with the Type filter on that item type, not just the page.
"""

import pytest

from cbrn_dashboard.domain.alerts import AlertKind
from cbrn_dashboard.ui.alerts.page import AlertsPage
from cbrn_dashboard.ui.infrastructure.page import STOCK_TAB, UNITS_TAB, InfrastructurePage
from tests.ui._fakes import expect_handle
from tests.ui.conftest import StartApp

pytestmark = pytest.mark.ui


def test_open_record_of_a_glove_alert_shows_the_stock_tab_filtered_on_the_type(
    started_app: StartApp,
) -> None:
    handle = expect_handle(started_app(demo=True))
    window = handle.window
    window.show()
    infrastructure = window.page_widget("infrastructure")
    assert isinstance(infrastructure, InfrastructurePage)
    infrastructure.tabs.setCurrentIndex(UNITS_TAB)  # the tab and the filter start elsewhere
    assert infrastructure.type_combo.currentData() is None

    window.show_page("alerts")
    alerts_page = window.page_widget("alerts")
    assert isinstance(alerts_page, AlertsPage)
    shown = alerts_page.shown_alerts()
    wanted = [
        index
        for index, alert in enumerate(shown)
        if alert.subject_ref == "DEMO-L011" and alert.kind is AlertKind.LOT_EXPIRING
    ]
    assert wanted, "the demo has no expiring-lot alert for DEMO-L011"
    alerts_page.view.selectRow(wanted[0])

    assert alerts_page.open_selected()

    assert window.pages.currentWidget() is infrastructure
    assert infrastructure.tabs.currentIndex() == STOCK_TAB
    assert infrastructure.type_combo.currentData() == "stock:GLOVE"
    assert {row.row.type_code for row in infrastructure.stock_panel.lots_model.rows()} == {"GLOVE"}
