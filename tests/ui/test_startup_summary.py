# SPDX-License-Identifier: GPL-3.0-or-later
"""The start-up alert summary and the status-bar alert badge (PLAN.md T6.6).

The alert service is replaced by a small double that returns hand-written alerts per as-of date
(``tests/ui/_alert_samples.py``), so the counts are known without seeding a database. Expected
texts are written out by hand: the English ones are the source texts (they need no catalogue entry),
the Portuguese and Spanish ones need the new strings in the shell catalogues.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.alerts import Alert, Severity, count_by_severity
from cbrn_dashboard.ui.shell.banners import AlertCounts
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.main_window import MainWindow
from tests.ui import _alert_samples as samples
from tests.ui._fakes import expect_handle
from tests.ui.conftest import StartApp

pytestmark = pytest.mark.ui

TODAY = date(2026, 3, 5)  # the date of ``FixedClock.at(NOW)``: the start-up as-of date
LATER = date(2026, 3, 6)
EMPTY = date(2026, 3, 7)

#: ``samples.ALERTS``: three critical, three warning, one information alert.
MIXED_BADGE = "Alerts: 3 critical, 3 warning, 1 info"
MIXED_SUMMARY = "Alerts need attention: 3 critical, 3 warning."
INFO_ONLY_BADGE = "Alerts: 0 critical, 0 warning, 1 info"
NONE_BADGE = "Alerts: 0 critical, 0 warning, 0 info"


class FakeAlerts:
    """The part of the alert service the window uses, over memory.

    The alerts of each as-of date are as given (a date that is not listed has none); every read is
    recorded in ``calls``. It is put into the context with ``vars(context.services)``.
    """

    def __init__(self, by_date: Mapping[date, Sequence[Alert]]) -> None:
        self.by_date: dict[date, list[Alert]] = {key: list(value) for key, value in by_date.items()}
        self.calls: list[date] = []

    def alerts(self, as_of: date) -> list[Alert]:
        self.calls.append(as_of)
        return list(self.by_date.get(as_of, ()))

    def counts(self, as_of: date) -> Mapping[Severity, int]:
        return count_by_severity(self.alerts(as_of))


def _install(context: AppContext, alerts: FakeAlerts | None) -> None:
    vars(context.services)["alerts"] = alerts


def _window(qtbot: QtBot, context: AppContext, alerts: FakeAlerts | None) -> MainWindow:
    _install(context, alerts)
    window = MainWindow(context)
    qtbot.addWidget(window)
    return window


def _summary_shown(window: MainWindow) -> bool:
    return "ALERT_SUMMARY" in window.banners.visible_codes()


# --------------------------------------------------------------------------- the summary


def test_warning_and_critical_alerts_show_the_badge_and_the_summary(
    app_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, app_context, FakeAlerts({TODAY: samples.ALERTS}))
    assert not window.alert_badge.isHidden()
    assert window.alert_badge.text() == MIXED_BADGE
    assert _summary_shown(window)
    assert window.banners.text("ALERT_SUMMARY") == MIXED_SUMMARY
    assert window.banners.summary_button.text() == "Open alerts"


def test_the_summary_button_opens_the_alerts_page(app_context: AppContext, qtbot: QtBot) -> None:
    window = _window(qtbot, app_context, FakeAlerts({TODAY: samples.ALERTS}))
    window.show_page("personnel")
    assert window.pages.currentWidget() is window.page_widget("personnel")
    window.banners.summary_button.click()
    assert window.pages.currentWidget() is window.page_widget("alerts")
    assert window.navigation.currentRow() == window.page_keys().index("alerts")


def test_only_information_alerts_are_in_the_badge_but_never_in_a_summary(
    app_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, app_context, FakeAlerts({TODAY: [samples.MAINT_SCHEDULE_UNKNOWN]}))
    assert window.alert_badge.text() == INFO_ONLY_BADGE
    assert not _summary_shown(window)


def test_a_single_warning_is_enough_for_the_summary(app_context: AppContext, qtbot: QtBot) -> None:
    window = _window(qtbot, app_context, FakeAlerts({TODAY: [samples.CERT_EXPIRING]}))
    assert _summary_shown(window)
    assert window.banners.text("ALERT_SUMMARY") == "Alerts need attention: 0 critical, 1 warning."


def test_no_alerts_show_a_zero_badge_and_no_summary(app_context: AppContext, qtbot: QtBot) -> None:
    window = _window(qtbot, app_context, FakeAlerts({}))
    assert window.alert_badge.text() == NONE_BADGE
    assert not _summary_shown(window)


def test_with_the_preference_off_there_is_no_summary_but_the_badge_stays(
    app_context: AppContext, qtbot: QtBot
) -> None:
    app_context.preferences.update(startup_summary=False)
    window = _window(qtbot, app_context, FakeAlerts({TODAY: samples.ALERTS}))
    assert not _summary_shown(window)
    assert not window.alert_badge.isHidden()
    assert window.alert_badge.text() == MIXED_BADGE


def test_the_preference_defaults_to_on(app_context: AppContext) -> None:
    assert app_context.preferences.current.startup_summary is True


def test_the_summary_and_the_badge_also_appear_in_demo_and_read_only_mode(
    app_context: AppContext, qtbot: QtBot
) -> None:
    # Alerts are computed on demand and nothing here writes, so both modes behave alike.
    app_context.is_demo = True
    app_context.read_only = True
    window = _window(qtbot, app_context, FakeAlerts({TODAY: samples.ALERTS}))
    shown = window.banners.visible_codes()
    assert {"DEMO", "READ_ONLY", "ALERT_SUMMARY"} <= set(shown)
    assert window.alert_badge.text() == MIXED_BADGE


# --------------------------------------------------------------------------- refreshing (R05)


def test_the_counts_follow_the_as_of_date(app_context: AppContext, qtbot: QtBot) -> None:
    fake = FakeAlerts(
        {
            TODAY: [samples.MAINT_SCHEDULE_UNKNOWN],
            LATER: [samples.CERT_EXPIRED, samples.CERT_EXPIRING, samples.INDICATOR_WARNING],
        }
    )
    window = _window(qtbot, app_context, fake)
    assert window.alert_badge.text() == INFO_ONLY_BADGE
    app_context.set_as_of(LATER)
    assert fake.calls[-1] == LATER
    assert window.alert_badge.text() == "Alerts: 1 critical, 2 warning, 0 info"
    # The summary is a start-up message: a later change does not raise it.
    assert not _summary_shown(window)
    app_context.set_as_of(TODAY)
    assert window.alert_badge.text() == INFO_ONLY_BADGE


def test_the_counts_follow_a_data_change(app_context: AppContext, qtbot: QtBot) -> None:
    fake = FakeAlerts({TODAY: [samples.CERT_EXPIRING]})
    window = _window(qtbot, app_context, fake)
    assert window.alert_badge.text() == "Alerts: 0 critical, 1 warning, 0 info"
    fake.by_date[TODAY] = [samples.CERT_EXPIRING, samples.CERT_EXPIRED, samples.MAINT_OVERDUE]
    app_context.notify_data_changed()
    assert window.alert_badge.text() == "Alerts: 2 critical, 1 warning, 0 info"


def test_a_shown_summary_follows_the_counts_and_goes_when_none_is_left(
    app_context: AppContext, qtbot: QtBot
) -> None:
    fake = FakeAlerts({TODAY: samples.ALERTS, LATER: [samples.CERT_EXPIRING]})
    window = _window(qtbot, app_context, fake)
    assert window.banners.text("ALERT_SUMMARY") == MIXED_SUMMARY
    app_context.set_as_of(LATER)
    assert _summary_shown(window)
    assert window.banners.text("ALERT_SUMMARY") == "Alerts need attention: 0 critical, 1 warning."
    app_context.set_as_of(EMPTY)
    assert not _summary_shown(window)
    assert window.alert_badge.text() == NONE_BADGE
    app_context.set_as_of(TODAY)  # once gone it is not raised again
    assert not _summary_shown(window)
    assert window.alert_badge.text() == MIXED_BADGE


# --------------------------------------------------------------------------- language


def test_the_texts_follow_a_language_switch_without_reading_the_service_again(
    app_context: AppContext, qtbot: QtBot
) -> None:
    fake = FakeAlerts({TODAY: samples.ALERTS})
    window = _window(qtbot, app_context, fake)
    reads = len(fake.calls)
    window.language_actions["pt_BR"].trigger()
    assert window.alert_badge.text() == "Alertas: 3 cr\u00edticos, 3 avisos, 1 informativo"
    assert window.banners.text("ALERT_SUMMARY") == (
        "Os alertas exigem aten\u00e7\u00e3o: 3 cr\u00edticos, 3 avisos."
    )
    assert window.banners.summary_button.text() == "Abrir alertas"
    window.language_actions["es_ES"].trigger()
    assert window.alert_badge.text() == "Alertas: 3 cr\u00edticas, 3 advertencias, 1 informativa"
    assert window.banners.summary_button.text() == "Abrir alertas"
    window.language_actions["en_US"].trigger()
    assert window.alert_badge.text() == MIXED_BADGE
    assert len(fake.calls) == reads


# --------------------------------------------------------------------------- no services


def test_without_an_alert_service_there_is_no_badge_and_no_summary(
    app_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, app_context, None)
    assert app_context.services.alerts is None
    assert window.alert_badge.isHidden()
    assert window.alert_badge.text() == ""
    assert not _summary_shown(window)


def test_nothing_raises_after_the_database_was_closed(
    app_context: AppContext, qtbot: QtBot
) -> None:
    window = _window(qtbot, app_context, FakeAlerts({TODAY: samples.ALERTS}))
    assert _summary_shown(window)
    app_context.conn = None  # as AppHandle.close_database does: the services are emptied
    assert app_context.services.alerts is None
    window.language_actions["pt_BR"].trigger()
    QCoreApplication.sendEvent(window, QEvent(QEvent.Type.LanguageChange))
    app_context.notify_data_changed()
    app_context.set_as_of(LATER)
    assert window.alert_badge.isHidden()
    assert not _summary_shown(window)


class _FailingAlerts(FakeAlerts):
    def alerts(self, as_of: date) -> list[Alert]:
        raise RuntimeError("DEMO-ZEBRA-7731")


def test_a_failing_read_hides_the_badge_and_is_logged_as_a_code(started_app: StartApp) -> None:
    # The Alerts page reads the same service in its own slot and fails too: that error prompt is
    # expected here, so the fixture is told not to count it.
    handle = expect_handle(started_app(expect_errors=True))
    window, context = handle.window, handle.context
    assert not window.alert_badge.isHidden()
    _install(context, _FailingAlerts({}))
    context.set_as_of(LATER)
    assert window.alert_badge.isHidden()
    assert not _summary_shown(window)
    handle.logging.handler.flush()
    assert handle.logging.path is not None
    text = handle.logging.path.read_text(encoding="utf-8")
    assert "UI.ALERT_COUNTS_FAILED" in text
    assert "RuntimeError" in text
    assert "ZEBRA" not in text


# --------------------------------------------------------------------------- the real start path


def test_a_real_start_on_an_empty_database_has_a_badge_and_no_summary(
    started_app: StartApp, tmp_path: Path
) -> None:
    handle = expect_handle(started_app(data_dir=tmp_path / "real"))
    window = handle.window
    assert window.alert_badge.text().startswith("Alerts: ")
    assert not _summary_shown(window)


def test_the_counts_value_object_separates_the_actionable_alerts() -> None:
    counts = AlertCounts(critical=2, warning=1, info=5)
    assert counts.actionable == 3
    assert AlertCounts(critical=0, warning=0, info=5).actionable == 0
