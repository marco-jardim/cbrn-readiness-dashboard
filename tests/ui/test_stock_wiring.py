# SPDX-License-Identifier: GPL-3.0-or-later
"""``build_services`` hands ONE stock service to every service that reads stock (PLAN.md T11.7).

A service built without it would silently show no stock: the indicator service (values), the
dashboard service (chart), the snapshot service (configuration hash) and, through the context, the
report builder.
"""

import pytest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.ui.reports.actions import ReportsWorkflow
from cbrn_dashboard.ui.shell.context import AppContext, build_services

pytestmark = pytest.mark.ui


def test_build_services_wires_the_same_stock_service_everywhere(app_context: AppContext) -> None:
    services = app_context.services
    assert services.stock is not None
    assert services.indicators is not None
    assert services.dashboard is not None
    assert services.snapshots is not None
    assert services.indicators._stock is services.stock
    assert services.dashboard._stock is services.stock
    assert services.snapshots._stock is services.stock


def test_the_report_builder_made_by_the_reports_workflow_gets_the_stock_service(
    app_context: AppContext, qtbot: QtBot
) -> None:
    anchor = QWidget()
    qtbot.addWidget(anchor)
    builder = ReportsWorkflow(app_context, anchor).report_builder()
    assert builder is not None
    assert builder._stock is app_context.services.stock


def test_without_a_connection_no_service_is_built(app_context: AppContext) -> None:
    services = build_services(None, app_context.clock, lambda: "")
    assert services.stock is None
    assert services.indicators is None
    assert services.dashboard is None
