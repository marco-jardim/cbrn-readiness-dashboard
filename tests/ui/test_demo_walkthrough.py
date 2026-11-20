# SPDX-License-Identifier: GPL-3.0-or-later
"""The demo walkthrough on screen (PLAN.md T10.1): every page shows demo data under the banner.

The application is started in demo mode on a fixed clock (5 March 2026), so the dataset is the one
of ``docs/demo-walkthrough.md`` for that day. Every page of the registry is made current in turn;
each one must show at least one row or tile, and the DEMO banner must be visible while it is the
current page. The dashboard must show every status and the alerts page every severity and kind the
walkthrough promises. The expectations are written by hand from the fixed cases of the demo
generators; they are not read back from the services under test.
"""

import re

import pytest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.clock import FixedClock
from cbrn_dashboard.domain.alerts import AlertKind, Severity
from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.ui.alerts.page import AlertsPage
from cbrn_dashboard.ui.antidotes.page import AntidotesPage
from cbrn_dashboard.ui.budget.page import BudgetPage
from cbrn_dashboard.ui.dashboard.page import DashboardPage
from cbrn_dashboard.ui.exercises.page import ExercisesPage
from cbrn_dashboard.ui.infrastructure.page import InfrastructurePage
from cbrn_dashboard.ui.personnel.page import PersonnelPage
from cbrn_dashboard.ui.reports.page import ReportsPage
from cbrn_dashboard.ui.settings.page import SettingsPage
from cbrn_dashboard.ui.settings.sections import TargetsSection
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.banners import BannerCode
from cbrn_dashboard.ui.shell.main_window import MainWindow
from tests.ui._fakes import expect_handle
from tests.ui.conftest import StartApp

pytestmark = pytest.mark.ui

CLOCK = FixedClock.at("2026-03-05T12:00:00Z")

#: The pages of the registry, by key, in navigation order.
PAGE_KEYS = (
    "dashboard",
    "personnel",
    "infrastructure",
    "antidotes",
    "exercises",
    "budget",
    "alerts",
    "reports",
    "settings",
)

#: The least number of rows (tiles) each page must show, from the fixed cases of the generators:
#: 20 readings on the dashboard (16 with a target, one without, one "No data" and two more),
#: 5 active people with certificates (DEMO-P001 to P004 and P006), 7 assets in service
#: (DEMO-A001 to A007), 8 started editions, 6 budget entries of the current year, 8 snapshots,
#: 7 alerts (one of each kind) and 16 targets.
MINIMUM_ROWS = {
    "dashboard": 20,
    "personnel": 5,
    "infrastructure": 7,
    "antidotes": 0,  # the demo stock arrives with T11.16, which raises this to its lot count
    "exercises": 8,
    "budget": 6,
    "alerts": 7,
    "reports": 8,
    "settings": 16,
}

DEMO_BANNER = "DEMO \u2014 fictitious data"

#: (indicator code, dimension, status) on 5 March 2026, from the walkthrough.
TILES = (
    ("PERS_CERT_VALID", "level=A", IndicatorStatus.OK),
    ("PERS_CERT_VALID", "level=B", IndicatorStatus.WARNING),
    ("PERS_CERT_VALID", "level=C", IndicatorStatus.CRITICAL),
    ("INFRA_MAINT_OVERDUE", "type=bed", IndicatorStatus.CRITICAL),
    ("BUD_EXEC_RATE", "currency=BRL;source=DIRSA", IndicatorStatus.CRITICAL),
    ("BUD_EXEC_RATE", "currency=USD;source=COMAER", IndicatorStatus.OK),
    ("PERS_CERT_EXPIRING", "level=B", IndicatorStatus.NO_TARGET),
    ("EX_LAST_PARTICIPANTS", "kind=EXBRAMED", IndicatorStatus.NO_DATA),
)


def _row_count(page: QWidget) -> int:
    """The number of rows (tiles) the page shows, read from its public attributes."""
    if isinstance(page, DashboardPage):
        return len(page.tile_widgets)
    if isinstance(page, PersonnelPage):
        return page.staff_model.rowCount()
    if isinstance(page, InfrastructurePage):
        return page.assets_model.rowCount()
    if isinstance(page, AntidotesPage):
        return page.panel.lots_model.rowCount()
    if isinstance(page, ExercisesPage):
        return page.editions_model.rowCount()
    if isinstance(page, BudgetPage):
        return page.entries_model.rowCount()
    if isinstance(page, AlertsPage):
        return len(page.shown_alerts())
    if isinstance(page, ReportsPage):
        return page.snapshots_model.rowCount()
    if isinstance(page, SettingsPage):
        targets = page.section_widget("settings.targets")
        assert isinstance(targets, TargetsSection)
        return targets.model.rowCount()
    msg = f"unknown page type {type(page).__name__}"
    raise AssertionError(msg)


def _started(started_app: StartApp, qtbot: QtBot) -> MainWindow:
    handle = expect_handle(started_app(demo=True, clock=CLOCK))
    handle.window.show()
    qtbot.waitExposed(handle.window)
    return handle.window


def test_the_registry_has_the_pages_the_walkthrough_walks() -> None:
    assert tuple(spec.key for spec in registry.pages()) == PAGE_KEYS
    assert set(MINIMUM_ROWS) == set(PAGE_KEYS)


def test_every_page_shows_demo_data_under_the_demo_banner(
    started_app: StartApp, qtbot: QtBot
) -> None:
    window = _started(started_app, qtbot)
    assert window.page_keys() == PAGE_KEYS
    for spec in registry.pages():
        window.show_page(spec.key)
        page = window.page_widget(spec.key)
        assert window.pages.currentWidget() is page, spec.key
        assert page.isVisibleTo(window), spec.key
        # The banner is part of the window, above whichever page is current.
        assert BannerCode.DEMO in window.banners.visible_codes(), spec.key
        assert window.banners.isVisibleTo(window), spec.key
        assert window.banners.text(BannerCode.DEMO) == DEMO_BANNER, spec.key
        assert _row_count(page) >= MINIMUM_ROWS[spec.key], spec.key


def test_the_dashboard_shows_every_status_the_walkthrough_promises(
    started_app: StartApp, qtbot: QtBot
) -> None:
    window = _started(started_app, qtbot)
    window.show_page("dashboard")
    page = window.page_widget("dashboard")
    assert isinstance(page, DashboardPage)
    for code, dimension, status in TILES:
        tile = page.tile_for(code, dimension)
        assert tile is not None, (code, dimension)
        assert tile.tile.status is status, (code, dimension)
        assert tile.status_label.text() != "", (code, dimension)
    assert {widget.tile.status for widget in page.tile_widgets} == set(IndicatorStatus)
    # The alert counts of the dashboard: every severity has at least one alert.
    for severity in Severity:
        text = page.alert_labels[severity].text()
        numbers = [int(number) for number in re.findall(r"\d+", text)]
        assert numbers, (severity, text)
        assert max(numbers) > 0, (severity, text)


def test_the_alerts_page_shows_every_severity_and_every_kind(
    started_app: StartApp, qtbot: QtBot
) -> None:
    window = _started(started_app, qtbot)
    window.show_page("alerts")
    page = window.page_widget("alerts")
    assert isinstance(page, AlertsPage)
    shown = page.shown_alerts()
    assert {alert.severity for alert in shown} == set(Severity)
    # the stock kinds join the demo with the stock demo data (T11.16)
    stock_kinds = {"LOT_EXPIRED", "LOT_EXPIRING", "LOW_STOCK"}
    assert {alert.kind for alert in shown} >= {
        kind for kind in AlertKind if kind.value not in stock_kinds
    }
    subjects = {alert.subject_ref for alert in shown}
    assert {"DEMO-P002", "DEMO-P003", "DEMO-A001", "DEMO-A002", "DEMO-A003"} <= subjects
