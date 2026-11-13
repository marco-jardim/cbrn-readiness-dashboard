# SPDX-License-Identifier: GPL-3.0-or-later
"""The Infrastructure page, its dialogs, the asset-type editor and the labels (PLAN.md T3.4)."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QDate
from PySide6.QtWidgets import QDialog, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain.infrastructure import AssetStatus, MaintenanceKind, ScheduleBasis
from cbrn_dashboard.services import errors as errors_module
from cbrn_dashboard.services import infrastructure as infrastructure_module
from cbrn_dashboard.services.config import CONFIG_ERROR_CODES
from cbrn_dashboard.services.infrastructure import (
    AssetInput,
    AssetTypeInput,
    AssetTypeView,
    InfrastructureService,
)
from cbrn_dashboard.ui.infrastructure.dialogs import (
    AssetDialog,
    MaintenanceDialog,
    StatusDialog,
    TypeDialog,
)
from cbrn_dashboard.ui.infrastructure.labels import (
    ALL_ERROR_CODES,
    BUILT_IN_TYPE_CODES,
    basis_label,
    code_label,
    error_label,
    join_labels,
    kind_label,
    status_label,
    type_display,
)
from cbrn_dashboard.ui.infrastructure.models import AssetsModel
from cbrn_dashboard.ui.infrastructure.page import (
    InfrastructurePage,
    InfrastructureSettingsSection,
    create_page,
    create_settings_section,
    demo_asset_dialog,
    demo_maintenance_dialog,
    demo_status_dialog,
    demo_type_dialog,
    page_title,
    settings_section_title,
)
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from tests.ui._fakes import FakePrompts
from tests.ui._walk import assert_fully_translated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")
AS_OF = date(2026, 3, 5)


# --------------------------------------------------------------------------- helpers


def _service(context: AppContext) -> InfrastructureService:
    service = context.services.infrastructure
    assert service is not None
    return service


def _type_view(context: AppContext, code: str) -> AssetTypeView:
    for asset_type in _service(context).list_types(include_inactive=True):
        if asset_type.code == code:
            return asset_type
    raise AssertionError(code)


def _add_asset(
    context: AppContext,
    tag: str = "DEMO-A001",
    code: str = "bed",
    status: str = "operational",
    start: date = date(2026, 1, 1),
    interval: int | None = None,
) -> int:
    data = AssetInput(
        tag=tag,
        type_id=_type_view(context, code).id,
        in_service_from=start,
        maintenance_interval_days=interval,
    )
    return _service(context).create_asset(data, status)


def _row_cells(page: InfrastructurePage, index: int) -> dict[str, str]:
    model = page.assets_model
    return {
        column.key: str(model.index(index, position).data())
        for position, column in enumerate(AssetsModel.COLUMNS)
    }


def _by_tag(page: InfrastructurePage) -> dict[str, dict[str, str]]:
    model = page.assets_model
    return {
        str(model.index(row, 0).data()): _row_cells(page, row) for row in range(model.rowCount())
    }


def _availability(page: InfrastructurePage) -> dict[str, tuple[int, int]]:
    return {
        row.type_code: (row.available, row.in_service) for row in page.availability_model.rows()
    }


def _select_asset(page: InfrastructurePage, tag: str) -> None:
    for index, row in enumerate(page.assets_model.rows()):
        if row.row.tag == tag:
            page.assets_view.selectRow(index)
            return
    raise AssertionError(tag)


def _select_type(section: InfrastructureSettingsSection, code: str) -> None:
    for index, row in enumerate(section.model.rows()):
        if row.code == code:
            section.view.selectRow(index)
            return
    raise AssertionError(code)


def _open_dialog[D: QDialog](page: QWidget, kind: type[D]) -> D:
    shown = [dialog for dialog in page.findChildren(kind) if dialog.isVisible()]
    assert len(shown) == 1
    return shown[0]


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


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


# --------------------------------------------------------------------------- add through dialogs


def test_adding_an_asset_and_changing_its_status_updates_table_and_summary(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    assert page.assets_model.rowCount() == 0

    dialog = AssetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.tag_edit.setText("DEMO-B001")
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData(_type_view(app_context, "bed").id))
    dialog.location_edit.setText("DEMO ward")
    dialog.from_edit.setDate(QDate(2026, 1, 10))
    dialog.interval.set_value(365)
    dialog.status_combo.setCurrentIndex(dialog.status_combo.findData("operational"))
    dialog.accept()

    (stored,) = service.list_assets()
    assert (stored.tag, stored.location, stored.maintenance_interval_days) == (
        "DEMO-B001",
        "DEMO ward",
        365,
    )
    assert page.assets_model.rowCount() == 1
    cells = _by_tag(page)["DEMO-B001"]
    assert cells["type"] == "Bed"
    assert cells["status"] == "Operational"
    assert cells["last_maintenance"] == "-"
    assert cells["next_due"] == "01/10/2027"
    assert cells["basis"] == "In service date plus interval"
    assert cells["flags"] == ""
    assert _availability(page)["bed"] == (1, 1)

    page.assets_view.selectRow(0)
    page.change_status()
    status_dialog = _open_dialog(page, StatusDialog)
    combo = status_dialog.status_combo
    combo.setCurrentIndex(combo.findData("out_of_service"))
    status_dialog.note_edit.setText("Compressor failure")
    status_dialog.accept()

    assert _by_tag(page)["DEMO-B001"]["status"] == "Out of service"
    assert _availability(page)["bed"] == (0, 1)
    history = service.asset_history(stored.id)
    assert [event.status for event in history.status_events] == [
        AssetStatus.OPERATIONAL,
        AssetStatus.OUT_OF_SERVICE,
    ]
    assert history.status_events[-1].note == "Compressor failure"


def test_editing_an_asset_through_the_dialog(app_context: AppContext, qtbot: QtBot) -> None:
    asset_id = _add_asset(app_context, interval=30)
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    page.assets_view.selectRow(0)
    page.edit_asset()
    dialog = _open_dialog(page, AssetDialog)
    assert dialog.tag_edit.text() == "DEMO-A001"
    assert dialog.interval.value() == 30
    assert not dialog.status_combo.isVisibleTo(dialog)
    dialog.location_edit.setText("DEMO annex")
    dialog.interval.set_value(None)
    dialog.accept()
    stored = _service(app_context).get_asset(asset_id).asset
    assert stored.location == "DEMO annex"
    assert stored.maintenance_interval_days is None
    assert _by_tag(page)["DEMO-A001"]["flags"] == "Schedule unknown"


def test_recording_maintenance_updates_the_next_due_date(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_asset(app_context, interval=30, start=date(2026, 1, 1))
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    before = _by_tag(page)["DEMO-A001"]
    assert before["next_due"] == "01/31/2026"
    assert before["flags"] == "Overdue"

    page.assets_view.selectRow(0)
    page.record_maintenance()
    dialog = _open_dialog(page, MaintenanceDialog)
    dialog.performed_edit.setDate(QDate(2026, 3, 1))
    dialog.kind_combo.setCurrentIndex(dialog.kind_combo.findData("preventive"))
    assert not dialog.next_edit.isEnabled()
    dialog.accept()
    after = _by_tag(page)["DEMO-A001"]
    assert after["last_maintenance"] == "03/01/2026"
    assert after["next_due"] == "03/31/2026"
    assert after["basis"] == "Last preventive maintenance plus interval"
    assert after["flags"] == "Due soon"

    page.assets_view.selectRow(0)
    page.record_maintenance()
    with_due = _open_dialog(page, MaintenanceDialog)
    with_due.performed_edit.setDate(QDate(2026, 3, 2))
    with_due.kind_combo.setCurrentIndex(with_due.kind_combo.findData("inspection"))
    with_due.next_check.setChecked(True)
    assert with_due.next_edit.isEnabled()
    with_due.next_edit.setDate(QDate(2026, 9, 1))
    with_due.accept()
    final = _by_tag(page)["DEMO-A001"]
    assert final["last_maintenance"] == "03/02/2026"
    assert final["next_due"] == "09/01/2026"
    assert final["basis"] == "Recorded next due date"
    assert final["flags"] == ""


# --------------------------------------------------------------------------- flags as text


def test_overdue_due_soon_and_unknown_schedule_are_shown_as_text(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_asset(app_context, "DEMO-OVER", interval=10, start=date(2026, 1, 1))
    _add_asset(app_context, "DEMO-SOON", interval=30, start=date(2026, 2, 20))
    _add_asset(app_context, "DEMO-UNK", start=date(2026, 1, 1))
    _add_asset(app_context, "DEMO-NONE", interval=0, start=date(2026, 1, 1))
    _add_asset(app_context, "DEMO-BAY", code="bay", start=date(2026, 1, 1), interval=365)
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    cells = _by_tag(page)
    assert cells["DEMO-OVER"]["flags"] == "Overdue"
    assert cells["DEMO-OVER"]["next_due"] == "01/11/2026"
    assert cells["DEMO-SOON"]["flags"] == "Due soon"
    assert cells["DEMO-SOON"]["next_due"] == "03/22/2026"
    assert cells["DEMO-UNK"]["flags"] == "Schedule unknown"
    assert cells["DEMO-UNK"]["next_due"] == "-"
    assert cells["DEMO-UNK"]["basis"] == "No interval or maintenance record"
    assert cells["DEMO-NONE"]["flags"] == "No scheduled maintenance"
    assert cells["DEMO-BAY"]["flags"] == ""
    # sorted by type (bay before bed) and then by tag
    tags = [row.row.tag for row in page.assets_model.rows()]
    assert tags == ["DEMO-BAY", "DEMO-NONE", "DEMO-OVER", "DEMO-SOON", "DEMO-UNK"]
    assert page.count_label.text() == "5 assets shown"


def test_flags_and_statuses_follow_the_language(app_context: AppContext, qtbot: QtBot) -> None:
    _add_asset(app_context, "DEMO-OVER", interval=10)
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    assert _by_tag(page)["DEMO-OVER"]["flags"] == "Overdue"
    app_context.translator_manager.set_language("pt_BR")
    cells = _by_tag(page)["DEMO-OVER"]
    assert cells["flags"] == QCoreApplication.translate("Infrastructure", "Overdue")
    assert cells["flags"] != "Overdue"
    assert cells["status"] != "Operational"
    assert cells["type"] == code_label("bed")
    assert cells["type"] != "Bed"


def test_dates_follow_the_language_and_reformat_on_a_switch(
    app_context: AppContext, qtbot: QtBot
) -> None:
    _add_asset(app_context, interval=365, start=date(2026, 1, 10))
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    model = page.assets_model
    assert model.index(0, 4).data() == "01/10/2027"
    assert page.add_action.text() == "Add asset"
    expected_dates = (("pt_BR", "10/01/2027"), ("es_ES", "10/01/2027"), ("en_US", "01/10/2027"))
    for lang, expected in expected_dates:
        app_context.translator_manager.set_language(lang)
        assert model.index(0, 4).data() == expected
        assert model.index(0, 0).data() == "DEMO-A001"
    app_context.translator_manager.set_language("pt_BR")
    assert page.add_action.text() != "Add asset"
    assert page.add_action.text() == QCoreApplication.translate("Infrastructure", "Add asset")


# --------------------------------------------------------------------------- validation errors


def test_a_duplicate_tag_is_refused_and_nothing_is_written(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    _add_asset(app_context)
    dialog = AssetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tag_edit.setText("DEMO-A001")
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData(_type_view(app_context, "bed").id))
    dialog.status_combo.setCurrentIndex(dialog.status_combo.findData("operational"))
    dialog.accept()
    assert _warnings(fake_prompts) == ["This asset tag is already in use."]
    assert fake_prompts.calls_of("warning")[0].title == "Cannot save"
    assert dialog.isVisible()
    assert len(_service(app_context).list_assets()) == 1


def test_a_validation_error_is_shown_translated(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    app_context.translator_manager.set_language("pt_BR")
    _add_asset(app_context)
    dialog = AssetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tag_edit.setText("DEMO-A001")
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData(_type_view(app_context, "bed").id))
    dialog.status_combo.setCurrentIndex(dialog.status_combo.findData("operational"))
    dialog.accept()
    (text,) = _warnings(fake_prompts)
    assert text == error_label("DUPLICATE_TAG")
    assert text != "This asset tag is already in use."


def test_a_missing_initial_status_is_refused_and_nothing_is_written(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    dialog = AssetDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tag_edit.setText("DEMO-B001")
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData(_type_view(app_context, "bed").id))
    assert dialog.status_combo.currentData() is None
    dialog.accept()
    assert _warnings(fake_prompts) == ["Choose the initial status of the asset."]
    assert dialog.isVisible()
    assert _service(app_context).list_assets() == []


def test_a_second_status_event_on_the_same_date_is_refused(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    asset_id = _add_asset(app_context, start=date(2026, 1, 1))
    dialog = StatusDialog(app_context, None, asset_id, "DEMO-A001")
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.effective_edit.setDate(QDate(2026, 1, 1))
    dialog.status_combo.setCurrentIndex(dialog.status_combo.findData("degraded"))
    dialog.accept()
    assert _warnings(fake_prompts) == ["The asset already has a status change on this date."]
    assert dialog.isVisible()
    assert len(_service(app_context).asset_history(asset_id).status_events) == 1


def test_a_next_due_date_before_the_performed_date_is_refused(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    asset_id = _add_asset(app_context)
    dialog = MaintenanceDialog(app_context, None, asset_id, "DEMO-A001")
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.performed_edit.setDate(QDate(2026, 3, 1))
    dialog.next_check.setChecked(True)
    dialog.next_edit.setDate(QDate(2026, 2, 1))
    dialog.accept()
    assert _warnings(fake_prompts) == ["The next due date cannot be before the date performed."]
    assert _service(app_context).asset_history(asset_id).maintenance_events == ()


# --------------------------------------------------------------------------- the as-of date


def test_changing_the_as_of_date_changes_status_and_flags(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    asset_id = _add_asset(app_context, interval=10, start=date(2026, 3, 1))
    service.change_status(asset_id, date(2026, 3, 10), "degraded")
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    cells = _by_tag(page)["DEMO-A001"]
    assert (cells["status"], cells["flags"]) == ("Operational", "Due soon")
    assert _availability(page)["bed"] == (1, 1)

    app_context.set_as_of(date(2026, 3, 12))
    cells = _by_tag(page)["DEMO-A001"]
    assert (cells["status"], cells["flags"]) == ("Degraded", "Overdue")
    assert _availability(page)["bed"] == (0, 1)

    app_context.set_as_of(AS_OF)
    assert _by_tag(page)["DEMO-A001"]["status"] == "Operational"


# --------------------------------------------------------------------------- filter and history


def test_the_type_filter_limits_the_assets(app_context: AppContext, qtbot: QtBot) -> None:
    _add_asset(app_context, "DEMO-BED", code="bed")
    _add_asset(app_context, "DEMO-BAY", code="bay")
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    types = _service(app_context).list_types(include_inactive=True)
    assert page.type_combo.count() == 1 + len(types)
    assert page.assets_model.rowCount() == 2
    page.type_combo.setCurrentIndex(page.type_combo.findData("bay"))
    assert [row.row.tag for row in page.assets_model.rows()] == ["DEMO-BAY"]
    page.type_combo.setCurrentIndex(0)
    assert page.assets_model.rowCount() == 2
    assert page.type_combo.itemText(page.type_combo.findData("bed")) == "Bed"


def test_the_history_lists_status_and_maintenance_by_date(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    service = _service(app_context)
    asset_id = _add_asset(app_context, start=date(2026, 1, 1))
    service.change_status(asset_id, date(2026, 2, 1), "degraded", "Pump")
    service.record_maintenance(asset_id, date(2026, 1, 15), "preventive", date(2026, 9, 1))
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    assert page.history_model.rowCount() == 0
    assert not page.edit_entry_action.isEnabled()

    page.assets_view.selectRow(0)
    model = page.history_model
    rows = [[model.index(r, c).data() for c in range(4)] for r in range(model.rowCount())]
    assert rows == [
        ["01/01/2026", "Status change", "Operational", ""],
        ["01/15/2026", "Maintenance", "Preventive, next due 09/01/2026", ""],
        ["02/01/2026", "Status change", "Degraded", "Pump"],
    ]

    page.history_view.selectRow(2)
    assert page.edit_entry_action.isEnabled()
    page.edit_entry()
    dialog = _open_dialog(page, StatusDialog)
    assert dialog.note_edit.text() == "Pump"
    dialog.note_edit.setText("Valve")
    dialog.accept()
    assert service.asset_history(asset_id).status_events[-1].note == "Valve"

    page.history_view.selectRow(1)
    page.edit_entry()
    maintenance = _open_dialog(page, MaintenanceDialog)
    assert maintenance.next_check.isChecked()
    maintenance.note_edit.setText("Checked")
    maintenance.accept()
    assert service.asset_history(asset_id).maintenance_events[0].note == "Checked"

    page.history_view.selectRow(1)
    page.delete_entry_action.trigger()
    assert len(service.asset_history(asset_id).maintenance_events) == 1
    fake_prompts.script("confirm", True)
    page.delete_entry_action.trigger()
    assert service.asset_history(asset_id).maintenance_events == ()
    assert page.history_model.rowCount() == 2


def test_retiring_and_deleting_an_asset_ask_for_confirmation(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    service = _service(app_context)
    asset_id = _add_asset(app_context)
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    page.assets_view.selectRow(0)

    page.retire_action.trigger()
    assert service.get_asset(asset_id).asset.in_service_until is None
    assert "DEMO-A001" in fake_prompts.calls_of("confirm")[0].text
    fake_prompts.script("confirm", True)
    page.retire_action.trigger()
    assert service.get_asset(asset_id).asset.in_service_until == AS_OF

    page.delete_action.trigger()
    assert len(service.list_assets()) == 1
    fake_prompts.script("confirm", True)
    page.delete_action.trigger()
    assert service.list_assets() == []
    assert page.assets_model.rowCount() == 0


# --------------------------------------------------------------------------- the settings section


def test_the_a05_switch_changes_the_availability_summary(
    app_context: AppContext, qtbot: QtBot
) -> None:
    config = app_context.services.config
    assert config is not None
    _add_asset(app_context, status="degraded")
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    section = InfrastructureSettingsSection(app_context)
    qtbot.addWidget(section)
    assert not section.degraded_check.isChecked()
    assert _availability(page)["bed"] == (0, 1)

    section.degraded_check.setChecked(True)
    assert config.load().degraded_counts_as_available is True
    assert _availability(page)["bed"] == (1, 1)
    section.degraded_check.setChecked(False)
    assert config.load().degraded_counts_as_available is False
    assert _availability(page)["bed"] == (0, 1)


def test_the_a05_placeholder_badge_and_confirm_button(
    app_context: AppContext, qtbot: QtBot
) -> None:
    config = app_context.services.config
    assert config is not None
    field = "degraded_counts_as_available"
    placeholder = config.badge_for_field(field)
    if placeholder is None:  # confirmed in this database: un-confirm it through the service API
        placeholder = next(item.id for item in config.placeholders() if field in item.fields)
        config.unconfirm(placeholder)
    assert config.badge_for_field(field) == placeholder
    section = InfrastructureSettingsSection(app_context)
    qtbot.addWidget(section)
    assert section.badge_label.text() == "Placeholder - to be confirmed"
    assert section.badge_label.isVisibleTo(section)
    assert section.confirm_button.isVisibleTo(section)
    assert section.confirm_action.isEnabled()
    section.confirm_action.trigger()
    assert config.badge_for_field(field) is None
    assert not section.badge_label.isVisibleTo(section)
    assert not section.confirm_button.isVisibleTo(section)


def test_built_in_types_cannot_be_deleted(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    app_context.translator_manager.set_language("pt_BR")
    section = InfrastructureSettingsSection(app_context)
    qtbot.addWidget(section)
    for code in BUILT_IN_TYPE_CODES:
        _select_type(section, code)
        assert section.selected_type() is not None
    _select_type(section, "bed")
    fake_prompts.script("confirm", True)
    section.delete_action.trigger()
    (text,) = _warnings(fake_prompts)
    assert text == error_label("BUILT_IN_TYPE")
    assert text != "Built-in asset types cannot be deleted or renamed."
    assert _type_view(app_context, "bed").built_in
    # the table shows the translated names of the built-in types
    codes = [row.code for row in section.model.rows()]
    assert section.model.index(codes.index("bed"), 1).data() == code_label("bed")


def test_the_type_editor_adds_edits_deactivates_and_deletes_types(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    service = _service(app_context)
    section = InfrastructureSettingsSection(app_context)
    qtbot.addWidget(section)
    before = section.model.rowCount()
    assert before == len(BUILT_IN_TYPE_CODES)
    assert section.model.index(0, 2).data() == "Not set"

    dialog = TypeDialog(app_context)
    qtbot.addWidget(dialog)
    assert dialog.interval.value() is None
    dialog.code_edit.setText("DEMO-TENT")
    dialog.label_pt_edit.setText("Tenda de demonstracao")
    dialog.label_en_edit.setText("Demo tent")
    dialog.interval.set_value(0)
    dialog.accept()
    created = _type_view(app_context, "DEMO-TENT")
    assert created.default_maintenance_interval_days == 0
    assert not created.built_in
    assert section.model.rowCount() == before + 1
    index = [row.code for row in section.model.rows()].index("DEMO-TENT")
    assert section.model.index(index, 1).data() == "Demo tent"
    assert section.model.index(index, 2).data() == "No scheduled maintenance"
    assert section.model.index(index, 3).data() == "User-defined"

    # a built-in type: code and labels are read-only, the default interval can change
    bed = TypeDialog(app_context, None, _type_view(app_context, "bed"))
    qtbot.addWidget(bed)
    assert not bed.code_edit.isEnabled()
    assert not bed.label_pt_edit.isEnabled()
    bed.interval.set_value(90)
    bed.accept()
    assert _type_view(app_context, "bed").default_maintenance_interval_days == 90
    row = [r.code for r in section.model.rows()].index("bed")
    assert section.model.index(row, 2).data() == "90 days"
    assert section.model.index(row, 3).data() == "Built-in"

    # an inactive type is no longer offered for new assets
    _select_type(section, "DEMO-TENT")
    assert section.deactivate_action.isEnabled()
    section.deactivate_type()
    assert not _type_view(app_context, "DEMO-TENT").active
    assert not section.deactivate_action.isEnabled()
    asset_dialog = AssetDialog(app_context)
    qtbot.addWidget(asset_dialog)
    assert asset_dialog.type_combo.findData(created.id) == -1

    section.delete_action.trigger()
    assert any(t.code == "DEMO-TENT" for t in service.list_types(include_inactive=True))
    fake_prompts.script("confirm", True)
    section.delete_action.trigger()
    assert all(t.code != "DEMO-TENT" for t in service.list_types(include_inactive=True))
    assert section.model.rowCount() == before


def test_the_type_editor_refuses_an_invalid_type(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    dialog = TypeDialog(app_context)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.code_edit.setText("DEMO-TENT")
    dialog.accept()
    assert _warnings(fake_prompts) == ["The Portuguese (Brazil) label is required."]
    dialog.label_pt_edit.setText("Tenda")
    dialog.code_edit.setText("bed")
    dialog.accept()
    assert _warnings(fake_prompts)[-1] == "This code is already in use."
    assert dialog.isVisible()
    stored = _service(app_context).list_types(include_inactive=True)
    assert [t.code for t in stored].count("bed") == 1


def test_the_interval_editor_distinguishes_not_set_from_zero(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = TypeDialog(app_context)
    qtbot.addWidget(dialog)
    editor = dialog.interval
    assert editor.value() is None
    assert not editor.days_spin.isEnabled()
    editor.set_value(0)
    assert editor.value() == 0
    assert editor.mode_combo.currentText() == "No scheduled maintenance"
    editor.set_value(45)
    assert editor.value() == 45
    assert editor.days_spin.isEnabled()
    editor.set_value(None)
    assert editor.value() is None
    assert editor.mode_combo.currentText() == "Not set"


def test_the_days_suffix_follows_the_plural_and_a_large_interval_is_kept(
    app_context: AppContext, qtbot: QtBot
) -> None:
    dialog = TypeDialog(app_context)
    qtbot.addWidget(dialog)
    editor = dialog.interval
    editor.set_value(1)
    assert editor.days_spin.suffix() == " day"
    editor.set_value(45)
    assert editor.days_spin.suffix() == " days"
    editor.set_value(40_000)  # above the usual maximum: shown and kept, never clamped
    assert editor.value() == 40_000
    assert editor.days_spin.maximum() >= 40_000
    editor.set_value(30)
    assert editor.value() == 30
    app_context.translator_manager.set_language("pt_BR")
    editor.set_value(1)
    assert editor.days_spin.suffix() == " dia"
    editor.set_value(2)
    assert editor.days_spin.suffix() == " dias"


def test_flags_are_joined_with_the_translated_separator(app_context: AppContext) -> None:
    assert join_labels([]) == ""
    assert join_labels(["a"]) == "a"
    assert join_labels(["a", "b", "c"]) == "a, b, c"
    app_context.translator_manager.set_language("pt_BR")
    assert join_labels(["a", "b", "c"]) == "a; b; c"


def test_the_asset_dialog_corrects_and_clears_the_last_day_in_service(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    asset_id = _add_asset(app_context, start=date(2026, 1, 1))
    service.retire_asset(asset_id, date(2026, 2, 1))
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    page.assets_view.selectRow(0)
    page.edit_asset()
    dialog = _open_dialog(page, AssetDialog)
    assert dialog.until_check.isChecked()
    assert dialog.until_edit.isEnabled()
    assert dialog.until_edit.date() == QDate(2026, 2, 1)
    dialog.until_edit.setDate(QDate(2026, 2, 15))
    dialog.accept()
    assert service.get_asset(asset_id).asset.in_service_until == date(2026, 2, 15)

    page.assets_view.selectRow(0)
    page.edit_asset()
    again = _open_dialog(page, AssetDialog)
    assert again.until_edit.date() == QDate(2026, 2, 15)
    again.until_check.setChecked(False)
    assert not again.until_edit.isEnabled()
    again.accept()
    assert service.get_asset(asset_id).asset.in_service_until is None
    assert _by_tag(page)["DEMO-A001"]["flags"] != "Not in service"


def test_moving_in_service_from_past_a_set_last_day_shows_the_field_with_the_error(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    asset_id = _add_asset(app_context, start=date(2026, 1, 1))
    _service(app_context).retire_asset(asset_id, date(2026, 2, 1))
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    page.assets_view.selectRow(0)
    page.edit_asset()
    dialog = _open_dialog(page, AssetDialog)
    dialog.from_edit.setDate(QDate(2026, 3, 1))
    assert dialog.until_check.isVisibleTo(dialog)
    assert dialog.until_check.isChecked()
    dialog.accept()
    assert _warnings(fake_prompts) == [
        "The last day in service cannot be before the first day in service."
    ]


def test_an_in_service_asset_without_a_status_is_flagged_as_a_data_quality_issue(
    app_context: AppContext, qtbot: QtBot
) -> None:
    service = _service(app_context)
    asset_id = _add_asset(app_context, start=date(2026, 4, 1))
    service.update_asset(
        asset_id,
        AssetInput(
            tag="DEMO-A001",
            type_id=_type_view(app_context, "bed").id,
            in_service_from=date(2026, 1, 1),
        ),
    )
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    cells = _by_tag(page)["DEMO-A001"]
    assert cells["status"] == "Unknown"
    assert cells["flags"] == "Status unknown (data quality), Schedule unknown"
    app_context.translator_manager.set_language("pt_BR")
    pt_cells = _by_tag(page)["DEMO-A001"]
    assert pt_cells["flags"] != cells["flags"]
    assert ";" in pt_cells["flags"]


def test_the_only_status_entry_of_an_asset_cannot_be_deleted(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    service = _service(app_context)
    asset_id = _add_asset(app_context)
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    page.assets_view.selectRow(0)
    page.history_view.selectRow(0)
    fake_prompts.script("confirm", True)
    page.delete_entry_action.trigger()
    assert _warnings(fake_prompts) == [error_label("ONLY_STATUS_EVENT")]
    assert len(service.asset_history(asset_id).status_events) == 1
    assert page.history_model.rowCount() == 1


# --------------------------------------------------------------------------- read-only, no service


def test_read_only_mode_disables_every_edit_action(app_context: AppContext, qtbot: QtBot) -> None:
    _add_asset(app_context)
    app_context.read_only = True
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    section = InfrastructureSettingsSection(app_context)
    qtbot.addWidget(section)
    page.assets_view.selectRow(0)
    page.history_view.selectRow(0)
    section.view.selectRow(0)
    actions = [*page._actions, *section._actions]
    assert len(actions) == 13
    targets = app_context.edit_targets()
    for action in actions:
        assert action in targets
        assert not action.isEnabled()
    assert section.degraded_check in targets
    assert not section.degraded_check.isEnabled()


def test_the_page_builds_without_an_infrastructure_service(
    app_context: AppContext, qtbot: QtBot
) -> None:
    app_context.services.infrastructure = None
    page = InfrastructurePage(app_context)
    qtbot.addWidget(page)
    section = InfrastructureSettingsSection(app_context)
    qtbot.addWidget(section)
    assert page.assets_model.rowCount() == 0
    assert page.availability_model.rowCount() == 0
    assert page.history_model.rowCount() == 0
    assert section.model.rowCount() == 0
    assert not page.add_action.isEnabled()
    assert not section.add_action.isEnabled()
    for dialog in (
        AssetDialog(app_context),
        demo_asset_dialog(app_context, None),
        demo_status_dialog(app_context, None),
        demo_maintenance_dialog(app_context, None),
        demo_type_dialog(app_context, None),
    ):
        qtbot.addWidget(dialog)
        assert dialog.windowTitle()


# --------------------------------------------------------------------------- pseudo-locale walk

FACTORIES: dict[str, Callable[[AppContext], QWidget]] = {
    "page": create_page,
    "settings_section": create_settings_section,
    "asset_dialog": lambda context: demo_asset_dialog(context, None),
    "status_dialog": lambda context: demo_status_dialog(context, None),
    "maintenance_dialog": lambda context: demo_maintenance_dialog(context, None),
    "type_dialog": lambda context: demo_type_dialog(context, None),
}


@pytest.mark.parametrize("name", list(FACTORIES))
def test_everything_is_translated_in_the_pseudo_locale(
    pseudo_context: AppContext, qtbot: QtBot, name: str
) -> None:
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    assert_fully_translated(widget)


@pytest.mark.parametrize("name", ["page", "settings_section"])
def test_the_pseudo_locale_walk_with_data(
    pseudo_context: AppContext, qtbot: QtBot, name: str
) -> None:
    service = _service(pseudo_context)
    asset_id = _add_asset(pseudo_context, interval=30)
    service.record_maintenance(asset_id, date(2026, 2, 1), "preventive", date(2026, 8, 1))
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    if isinstance(widget, InfrastructurePage):
        widget.assets_view.selectRow(0)
    assert_fully_translated(widget)


def test_the_titles_are_translated(pseudo_context: AppContext) -> None:
    assert page_title() == "\u27e6Infrastructure\u27e7"
    assert settings_section_title() == "\u27e6Asset types and availability\u27e7"


# --------------------------------------------------------------------------- labels


def test_every_enum_value_and_built_in_type_has_a_label_in_all_languages(
    app_context: AppContext,
) -> None:
    bed = _type_view(app_context, "bed")
    labels: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        found: dict[str, str] = {}
        found.update({f"status:{s.value}": status_label(s.value) for s in AssetStatus})
        found.update({f"kind:{k.value}": kind_label(k.value) for k in MaintenanceKind})
        found.update({f"basis:{b.value}": basis_label(b.value) for b in ScheduleBasis})
        found.update({f"type:{code}": code_label(code) for code in BUILT_IN_TYPE_CODES})
        found["display:bed"] = type_display(bed, lang)
        labels[lang] = found
    assert len(BUILT_IN_TYPE_CODES) == 4
    for lang in LANGUAGES:
        for key, text in labels[lang].items():
            assert text.strip(), (lang, key)
            assert text != key.split(":", 1)[1], (lang, key)
    for key, english in labels["en_US"].items():
        assert labels["pt_BR"][key] != english, key
        assert labels["es_ES"][key] != english, key
    assert labels["en_US"]["type:bed"] == "Bed"
    assert labels["en_US"]["type:bay"] == "Bay"
    assert labels["en_US"]["type:neg_pressure_filtration"] == (
        "Negative-pressure and filtration equipment"
    )
    assert labels["en_US"]["type:decon_tent"] == "Decontamination tent"
    assert labels["pt_BR"]["type:bed"] == "Leito"
    assert labels["es_ES"]["type:bed"] == "Cama"
    assert labels["en_US"]["display:bed"] == "Bed"


def test_a_user_defined_type_uses_its_own_labels_with_the_service_fallback(
    app_context: AppContext,
) -> None:
    service = _service(app_context)
    service.create_type(
        AssetTypeInput(code="DEMO-TENT", label_pt_br="Tenda demo", label_en_us="Demo tent")
    )
    custom = _type_view(app_context, "DEMO-TENT")
    assert type_display(custom, "en_US") == "Demo tent"
    assert type_display(custom, "pt_BR") == "Tenda demo"
    assert type_display(custom, "es_ES") == "Tenda demo"


def test_every_error_code_has_a_label_in_all_languages(app_context: AppContext) -> None:
    errors: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        errors[lang] = {code: error_label(code) for code in ALL_ERROR_CODES}
    for lang in LANGUAGES:
        for code, text in errors[lang].items():
            assert text.strip(), (lang, code)
            assert text != code, (lang, code)
    for code, english in errors["en_US"].items():
        assert errors["pt_BR"][code] != english, code
        assert errors["es_ES"][code] != english, code


def test_an_unknown_code_is_shown_as_itself() -> None:
    assert error_label("NOT_A_CODE") == "NOT_A_CODE"
    assert status_label("NOT_A_STATUS") == "NOT_A_STATUS"
    assert kind_label("NOT_A_KIND") == "NOT_A_KIND"
    assert basis_label("NOT_A_BASIS") == "NOT_A_BASIS"
    assert code_label("my_type") == "my_type"


def test_all_error_codes_lists_every_code_of_the_services() -> None:
    def constants(module: object) -> set[str]:
        return {
            name
            for name, value in vars(module).items()
            if name.isupper() and isinstance(value, str) and value == name
        }

    found = constants(infrastructure_module) | constants(errors_module)
    assert {"DUPLICATE_TAG", "STATUS_DATE_TAKEN", "INITIAL_STATUS_REQUIRED", "READ_ONLY"} <= found
    assert found <= set(ALL_ERROR_CODES), sorted(found - set(ALL_ERROR_CODES))
    assert set(CONFIG_ERROR_CODES) <= set(ALL_ERROR_CODES)
    assert len(set(ALL_ERROR_CODES)) == len(ALL_ERROR_CODES)
