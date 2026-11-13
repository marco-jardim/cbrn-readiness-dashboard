# SPDX-License-Identifier: GPL-3.0-or-later
"""A changing save confirms the placeholder of the changed field in every settings section.

PLAN.md 3.5: the badge stays "until the operator confirms or changes the value" and T6.1 Accept 4.
``ConfigService.save`` does it in the same transaction, so a section needs no second step: the badge
of the field that was changed is gone after the section's own save, the badges of the fields that
were not touched stay. One test per settings section (all fictitious values).
"""

import pytest
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot

from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.ui.backup.page import BackupSettingsSection
from cbrn_dashboard.ui.budget.page import BudgetSettingsSection
from cbrn_dashboard.ui.infrastructure.page import InfrastructureSettingsSection
from cbrn_dashboard.ui.personnel.page import PersonnelSettingsSection
from cbrn_dashboard.ui.reports.page import ReportsSettingsSection, SnapshotsSettingsSection
from cbrn_dashboard.ui.settings.dialogs import TargetDialog
from cbrn_dashboard.ui.settings.sections import AlertsSection, GeneralSection, TargetsSection
from cbrn_dashboard.ui.shell.context import AppContext
from tests.ui._fakes import FakePrompts

pytestmark = pytest.mark.ui


def _config(context: AppContext) -> ConfigService:
    service = context.services.config
    assert service is not None
    return service


def _indicators(context: AppContext) -> IndicatorService:
    service = context.services.indicators
    assert service is not None
    return service


def _shown(label: QLabel) -> bool:
    return not label.isHidden()


def test_the_general_section_confirms_the_names_when_they_change(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = GeneralSection(app_context)
    qtbot.addWidget(section)
    assert _shown(section.names_badge.badge)

    section.institution_edit.setText("Institute")
    section.save()

    assert section.names_badge.badge.isHidden()
    assert _config(app_context).needs_badge("D18") is False
    assert fake_prompts.calls_of("warning") == []


def test_the_alerts_section_confirms_only_the_window_that_changed(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = AlertsSection(app_context)
    qtbot.addWidget(section)

    section.cert_edit.setText("120")
    section.save()

    assert section.cert_badge.badge.isHidden()
    assert _shown(section.maintenance_badge.badge)
    assert _config(app_context).needs_badge("P01") is False
    assert _config(app_context).needs_badge("P02") is True


def test_the_targets_section_confirms_p03_when_a_target_is_switched(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _indicators(app_context).set_target(
        "PERS_CERT_VALID", "level=A", warning_value=10, critical_value=5
    )
    section = TargetsSection(app_context)
    qtbot.addWidget(section)
    assert _shown(section.badge.badge)  # storing a target through the service confirms nothing
    section.view.selectRow(0)

    section.toggle_action.trigger()

    assert section.badge.badge.isHidden()
    assert _config(app_context).needs_badge("P03") is False


def test_the_target_dialog_confirms_p03_in_the_same_call(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = TargetsSection(app_context)
    qtbot.addWidget(section)
    dialog = TargetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.indicator_combo.setCurrentIndex(dialog.indicator_combo.findData("PERS_CERT_VALID"))
    dialog.dimension_combo.setEditText("level=A")
    dialog.warning_edit.setText("10")
    dialog.critical_edit.setText("5")

    dialog.accept()

    assert section.badge.badge.isHidden()
    assert _config(app_context).needs_badge("P03") is False


def test_the_backup_section_confirms_the_changed_value_only(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = BackupSettingsSection(app_context)
    qtbot.addWidget(section)
    for row in (section.passphrase_row, section.daily_row, section.reminder_row):
        assert _shown(row.badge)

    section.daily_row.spin.setValue(section.daily_row.spin.value() + 1)
    section.save_settings()

    assert section.daily_row.badge.isHidden()
    assert section.daily_row.confirm.isHidden()
    assert _shown(section.passphrase_row.badge)
    assert _shown(section.reminder_row.badge)
    assert _config(app_context).needs_badge("P06") is False
    assert fake_prompts.calls_of("warning") == []


def test_the_budget_section_confirms_the_currency_and_the_prorating_switch(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = BudgetSettingsSection(app_context)
    qtbot.addWidget(section)
    assert _shown(section.currency_badge)
    assert _shown(section.prorate_badge)

    section.currency_combo.setCurrentIndex(section.currency_combo.findData("USD"))

    assert section.currency_badge.isHidden()  # A08
    assert _shown(section.prorate_badge)
    assert _config(app_context).needs_badge("A08") is False

    section.prorate_check.setChecked(not section.prorate_check.isChecked())

    assert section.prorate_badge.isHidden()  # P08
    assert _config(app_context).needs_badge("P08") is False


def test_the_personnel_section_confirms_the_validity_months(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = PersonnelSettingsSection(app_context)
    qtbot.addWidget(section)
    assert _shown(section.a02_badge)
    assert _shown(section.a04_badge)

    section.months_edits["A"].setText("18")
    section.save_rules()

    assert section.a04_badge.isHidden()
    assert _shown(section.a02_badge)
    assert _config(app_context).needs_badge("A04") is False
    assert _config(app_context).needs_badge("A02") is True


def test_the_infrastructure_section_confirms_the_degraded_switch(
    app_context: AppContext, qtbot: QtBot
) -> None:
    config = _config(app_context)
    if not config.needs_badge("A05"):  # confirmed in this database: start from the badge
        config.unconfirm("A05")
    section = InfrastructureSettingsSection(app_context)
    qtbot.addWidget(section)
    assert _shown(section.badge_label)

    section.degraded_check.setChecked(not section.degraded_check.isChecked())

    assert section.badge_label.isHidden()
    assert section.confirm_button.isHidden()
    assert config.needs_badge("A05") is False


def test_the_reports_section_confirms_the_threshold_when_it_changes(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = ReportsSettingsSection(app_context)
    qtbot.addWidget(section)
    assert _shown(section.threshold_row.badge)
    assert _shown(section.notice_row.badge)

    section.threshold_spin.setValue(section.threshold_spin.value() + 1)
    section.save_action.trigger()

    assert section.threshold_row.badge.isHidden()  # A11
    assert _shown(section.notice_row.badge)  # P10 was not touched
    assert _config(app_context).needs_badge("A11") is False
    assert _config(app_context).needs_badge("P10") is True


def test_the_snapshots_section_confirms_p04_when_a_switch_changes(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = SnapshotsSettingsSection(app_context)
    qtbot.addWidget(section)
    assert _shown(section.monthly_row.badge)

    section.monthly_check.setChecked(not section.monthly_check.isChecked())
    section.save_action.trigger()

    assert section.monthly_row.badge.isHidden()
    assert section.on_report_row.badge.isHidden()  # one placeholder, both fields
    assert _config(app_context).needs_badge("P04") is False


def test_a_save_that_changes_nothing_keeps_every_badge(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = BackupSettingsSection(app_context)
    qtbot.addWidget(section)

    section.save_settings()  # the stored values, unchanged

    for row in (section.passphrase_row, section.daily_row, section.reminder_row):
        assert _shown(row.badge)
    assert _config(app_context).needs_badge("P05") is True
