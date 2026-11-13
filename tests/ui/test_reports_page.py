# SPDX-License-Identifier: GPL-3.0-or-later
"""The reports, snapshots and import/export UI: page, dialogs, settings sections, labels (T8.7).

Everything runs on a temporary data folder with the real services; the prompts are the fake of
``tests/ui/_fakes.py``. The expected texts and file names are written out by hand. All data is
fictitious. The injected ``DestinationChecks`` stand in for the network, cloud-sync and
removable-media probes.
"""

import ast
import inspect
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest
from PySide6.QtCore import QAbstractItemModel, QDate, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialogButtonBox, QLabel, QWidget
from pytestqt.qtbot import QtBot

from cbrn_dashboard.paths import DATABASE_FILE_NAME, DataLocation, LocationSource
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.reports.model import ReportVariant
from cbrn_dashboard.services import budget as budget_module
from cbrn_dashboard.services import exercises as exercises_module
from cbrn_dashboard.services import export as export_module
from cbrn_dashboard.services import importer as importer_module
from cbrn_dashboard.services import infrastructure as infrastructure_module
from cbrn_dashboard.services import personnel as personnel_module
from cbrn_dashboard.services import snapshots as snapshots_module
from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.services.exercises import EditionInput
from cbrn_dashboard.services.personnel import CertificateInput, StaffInput
from cbrn_dashboard.services.snapshots import SnapshotService, SnapshotView
from cbrn_dashboard.storage import app_meta, csv_io
from cbrn_dashboard.storage.db import DatabaseConnection, open_database
from cbrn_dashboard.storage.migrate import DatabaseIdentity, open_and_migrate
from cbrn_dashboard.ui.reports.actions import DestinationChecks, ReportsWorkflow
from cbrn_dashboard.ui.reports.dialogs import ImportDialog, ReportDialog, ValidationExportDialog
from cbrn_dashboard.ui.reports.labels import (
    ALL_ERROR_CODES,
    entity_label,
    error_label,
    origin_label,
    state_label,
    variant_label,
)
from cbrn_dashboard.ui.reports.page import (
    ReportsPage,
    ReportsSettingsSection,
    SnapshotsSettingsSection,
    create_page,
    create_reports_section,
    create_snapshots_section,
    demo_import_dialog,
    demo_report_dialog,
    demo_validation_export_dialog,
    page_title,
    reports_section_title,
    snapshots_section_title,
)
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.registry import DialogSpec, PageSpec, SettingsSectionSpec
from tests.ui._fakes import FakePrompts, snapshot
from tests.ui._walk import assert_fully_translated, find_untranslated

pytestmark = pytest.mark.ui

LANGUAGES = ("pt_BR", "en_US", "es_ES")
TODAY = date(2026, 3, 5)  # the day of ``tests/ui/conftest.NOW``
QUIET = DestinationChecks(
    network_drive=lambda _folder: False,
    cloud_sync=lambda _folder: False,
    removable=lambda _folder: False,
)
CLOSING = "Files written there are no longer protected by this program. Continue anyway?"
#: probe name -> (the checks that report only that place, the warning it must show)
PLACES: dict[str, tuple[DestinationChecks, str]] = {
    "network": (
        DestinationChecks(
            network_drive=lambda _folder: True,
            cloud_sync=lambda _folder: False,
            removable=lambda _folder: False,
        ),
        "The chosen location is on a network drive.",
    ),
    "cloud": (
        DestinationChecks(
            network_drive=lambda _folder: False,
            cloud_sync=lambda _folder: True,
            removable=lambda _folder: False,
        ),
        "The chosen location is synchronised with a cloud service.",
    ),
    "removable": (
        DestinationChecks(
            network_drive=lambda _folder: False,
            cloud_sync=lambda _folder: False,
            removable=lambda _folder: True,
        ),
        "The chosen location is on removable media.",
    ),
}
#: One CSV file per entity, in import order (written by hand from docs/import-templates.md).
CSV_FILES = (
    "training_course.csv",
    "asset_type.csv",
    "evaluation_metric.csv",
    "funding_source.csv",
    "staff_member.csv",
    "ppe_certification.csv",
    "training_record.csv",
    "academic_degree.csv",
    "asset.csv",
    "asset_status_event.csv",
    "maintenance_event.csv",
    "exercise_edition.csv",
    "exercise_country.csv",
    "evaluation_result.csv",
    "budget_entry.csv",
    "budget_execution.csv",
)

#: The English text of every code, written by hand.
EXPECTED_ENGLISH: dict[str, str] = {
    "READ_ONLY": "The data is read-only: nothing was changed.",
    "NOT_FOUND": "The item no longer exists.",
    "INVALID_DATE": "The date is not valid.",
    "NO_OUTPUT_CHOSEN": "Choose where to write the file first.",
    "NO_FILE_CHOSEN": "Choose the file to import first.",
    "AS_OF_IN_FUTURE": "The as-of date is in the future.",
    "ORIGIN_NOT_ALLOWED": "This kind of snapshot cannot be recorded.",
    "REASON_REQUIRED": "A reason is required.",
    "ALREADY_WITHDRAWN": "The snapshot was already withdrawn.",
    "REPORT_FAILED": "The report file could not be written. Check the chosen location.",
    "EXPORT_FAILED": "The export files could not be written. Check the chosen folder.",
    "UNKNOWN_ENTITY": "This kind of data is not known.",
    "FILE_UNREADABLE": "The file cannot be read. Check that it exists and is not in use.",
    "NOT_UTF8": "The file is not valid UTF-8. Save it as UTF-8 and try again.",
    "MALFORMED_CSV": "The file is not a well-formed CSV file.",
    "HEADER_MISMATCH": "The header row does not match the template.",
    "DUPLICATE_COLUMN": "A column appears twice in the header.",
    "UNKNOWN_COLUMN": "The header has a column that is not in the template.",
    "MISSING_COLUMN": "A column of the template is missing from the header.",
    "WRONG_COLUMN_COUNT": "The row has a different number of columns than the header.",
    "WRONG_FIELD_COUNT": "The row has the wrong number of fields.",
    "REQUIRED": "A value is required.",
    "INVALID_NUMBER": "The number is not valid.",
    "INVALID_BOOL": "The yes/no value is not valid.",
    "INVALID_CURRENCY": "The currency is not valid.",
    "INVALID_AMOUNT": "The amount is not valid.",
    "INVALID_VALUE": "The value is not valid.",
    "UNKNOWN_REFERENCE": "The row refers to an item that does not exist.",
    "DUPLICATE_IN_FILE": "The row repeats an earlier row of the file.",
    "DUPLICATE_KEY": "The item already exists, so the row was refused.",
    "BUILT_IN_NOT_ALLOWED": "Built-in items cannot be imported.",
    "STORAGE_REFUSED": "The stored data refused the row because it breaks one of its rules.",
    "END_BEFORE_START": "The end date is before the start date.",
    "VALUE_OUT_OF_SCALE": "The value is outside the scale of the metric.",
    "INVALID_PPE_LEVEL": "The protection level is not valid.",
    "VALID_UNTIL_BEFORE_ISSUED": "The validity ends before the issue date.",
    "IDENTIFIER_LOOKS_LIKE_NATIONAL_ID": "The identifier looks like a national identity number.",
    "EXECUTION_OUTSIDE_FISCAL_YEAR": "The execution date is outside the fiscal year.",
    "THRESHOLD_TOO_LOW": "The threshold must be at least 1.",
    "VALUE_TOO_LARGE": "The value is too large.",
    "INVALID_TEXT": "The text is not valid or is too long.",
    "INVALID_TYPE": "The value has the wrong type.",
    "CORRUPT_SETTING": "A stored setting cannot be read.",
    "UNKNOWN_PLACEHOLDER": "This placeholder is not known.",
}


# --------------------------------------------------------------------------- helpers


def _need[T](value: T | None) -> T:
    assert value is not None
    return value


def _conn(context: AppContext) -> DatabaseConnection:
    return _need(context.conn)


def _config(context: AppContext) -> ConfigService:
    return _need(context.services.config)


def _snapshots(context: AppContext) -> SnapshotService:
    return _need(context.services.snapshots)


def _warnings(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("warning")]


def _infos(prompts: FakePrompts) -> list[str]:
    return [call.text for call in prompts.calls_of("info")]


def _out(tmp_path: Path, name: str = "out") -> Path:
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    return folder


def _cells(model: QAbstractItemModel, row: int) -> list[str]:
    return [str(model.index(row, column).data()) for column in range(model.columnCount())]


def _seed(context: AppContext) -> None:
    """Two people with three certificates (fictitious)."""
    people = _need(context.services.personnel)
    first = people.create_staff(StaffInput("DEMO-P001", "2020-01-01"))
    second = people.create_staff(StaffInput("DEMO-P002", "2020-01-01"))
    people.add_certificate(first, CertificateInput("A", "2024-03-20", "2026-03-20"))
    people.add_certificate(first, CertificateInput("B", "2025-02-10", "2027-02-10"))
    people.add_certificate(second, CertificateInput("A", "2025-02-10", "2027-02-10"))


def _add_edition(context: AppContext, code: str, start: str, end: str) -> None:
    _need(context.services.exercises).create_edition(
        EditionInput(code=code, kind="CBRAMED", start_on=start, end_on=end)
    )


def _choose(dialog: ReportDialog, variant: str) -> None:
    dialog.variant_combo.setCurrentIndex(dialog.variant_combo.findData(variant))


@pytest.fixture
def anchor(qtbot: QtBot) -> QWidget:
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


@pytest.fixture
def workflow(app_context: AppContext, anchor: QWidget, qm_dir: Path) -> ReportsWorkflow:
    flow = ReportsWorkflow(app_context, anchor)
    flow.checks = QUIET
    flow.qm_dir = qm_dir
    return flow


@pytest.fixture
def read_only_context(app_context: AppContext, fake_prompts: FakePrompts) -> Iterator[AppContext]:
    """A context over a REAL read-only connection to the same database file."""
    conn = open_database(app_context.location.database_path, read_only=True)
    context = AppContext(
        conn=conn,
        clock=app_context.clock,
        location=app_context.location,
        prompts=fake_prompts,
        preferences=PreferencesStore(app_context.location.path, writable=False),
        translator_manager=app_context.translator_manager,
    )
    yield context
    conn.close()
    context.deleteLater()


@pytest.fixture
def second_context(
    app_context: AppContext, fake_prompts: FakePrompts, tmp_path: Path
) -> Iterator[AppContext]:
    """A second, empty, writable database (the target of a round trip)."""
    data_dir = tmp_path / "second"
    data_dir.mkdir()
    conn = open_and_migrate(
        data_dir / DATABASE_FILE_NAME, data_dir=data_dir, identity=DatabaseIdentity.REAL
    )
    app_meta.initialise(conn, is_demo=False, created_with="0.0.1")
    context = AppContext(
        conn=conn,
        clock=app_context.clock,
        location=DataLocation(path=data_dir, source=LocationSource.CLI, writable=True),
        prompts=fake_prompts,
        preferences=PreferencesStore(data_dir),
        translator_manager=app_context.translator_manager,
    )
    yield context
    conn.close()
    context.conn = None
    context.deleteLater()


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


def _report_dialog(
    context: AppContext, anchor: QWidget, flow: ReportsWorkflow, qtbot: QtBot
) -> ReportDialog:
    dialog = ReportDialog(context, anchor, workflow=flow)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def _write_report(
    dialog: ReportDialog, prompts: FakePrompts, target: Path, *, confirm: bool = True
) -> None:
    prompts.script("save_file", target)
    if confirm:
        prompts.script("confirm", True)
    dialog.choose_button.click()
    dialog.accept()


def _validation_dialog(
    context: AppContext, anchor: QWidget, flow: ReportsWorkflow, qtbot: QtBot
) -> ValidationExportDialog:
    dialog = ValidationExportDialog(context, anchor, workflow=flow)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def _export_validation(dialog: ValidationExportDialog, prompts: FakePrompts, folder: Path) -> None:
    prompts.script("choose_folder", folder)
    dialog.choose_button.click()
    dialog.accept()


# --------------------------------------------------------------------------- the PDF report


@pytest.mark.parametrize(
    ("variant", "stem"), [("INTERNAL", "internal"), ("ANONYMISED", "anonymised")]
)
def test_a_pdf_of_each_variant_is_written_to_the_chosen_path(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
    variant: str,
    stem: str,
) -> None:
    _seed(app_context)
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    _choose(dialog, variant)
    target = _out(tmp_path) / "report.pdf"
    _write_report(dialog, fake_prompts, target, confirm=False)

    (picker,) = fake_prompts.calls_of("save_file")
    assert picker.args == (
        "Create report",
        f"cbrn-report-{stem}-2026-03-05.pdf",
        "PDF report (*.pdf)",
    )
    assert target.read_bytes().startswith(b"%PDF-")
    assert list(_out(tmp_path).iterdir()) == [target]
    kind = "anonymised" if variant == "ANONYMISED" else "internal"
    assert _infos(fake_prompts) == [
        f"The {kind} report was written to {target}. A snapshot of the readings was recorded."
    ]
    assert _warnings(fake_prompts) == []
    assert not dialog.isVisible()  # accepted


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_report_is_written_in_the_chosen_language(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
    language: str,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    assert dialog.report_language() == "en_US"  # the UI language is the default
    dialog.language_combo.setCurrentIndex(dialog.language_combo.findData(language))
    assert dialog.report_language() == language
    target = _out(tmp_path) / f"report-{language}.pdf"
    _write_report(dialog, fake_prompts, target, confirm=False)
    assert target.read_bytes().startswith(b"%PDF-")
    assert app_context.translator_manager.current_language == "en_US"  # not swapped


def test_a_file_name_without_the_pdf_extension_gets_it(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    _write_report(dialog, fake_prompts, _out(tmp_path) / "plain", confirm=False)
    assert (_out(tmp_path) / "plain.pdf").read_bytes().startswith(b"%PDF-")
    assert not (_out(tmp_path) / "plain").exists()


def test_the_default_file_name_of_demonstration_data_starts_with_demo(
    app_context: AppContext, workflow: ReportsWorkflow
) -> None:
    assert workflow.default_report_name(ReportVariant.INTERNAL, TODAY) == (
        "cbrn-report-internal-2026-03-05.pdf"
    )
    app_context.is_demo = True
    assert workflow.default_report_name(ReportVariant.ANONYMISED, TODAY) == (
        "DEMO-cbrn-report-anonymised-2026-03-05.pdf"
    )


def test_a_report_for_today_records_a_snapshot_with_origin_report(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    assert dialog.snapshot_check.isChecked()  # ticked by default (P04)
    assert dialog.snapshot_note.isHidden()
    changed: list[int] = []
    app_context.data_changed.connect(lambda: changed.append(1))
    _write_report(dialog, fake_prompts, _out(tmp_path) / "today.pdf", confirm=False)

    (stored,) = _snapshots(app_context).list_snapshots()
    assert (stored.origin.value, stored.as_of) == ("report", TODAY)
    assert changed == [1]


def test_a_report_for_a_past_date_records_a_retroactive_snapshot_and_says_so(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    dialog.date_edit.setDate(QDate(2026, 3, 1))
    assert not dialog.snapshot_note.isHidden()
    assert dialog.snapshot_note.text() == (
        "A snapshot recorded for a past date is stored as retroactive."
    )
    target = _out(tmp_path) / "past.pdf"
    _write_report(dialog, fake_prompts, target, confirm=False)

    (stored,) = _snapshots(app_context).list_snapshots()
    assert (stored.origin.value, stored.as_of) == ("retroactive", date(2026, 3, 1))
    assert _infos(fake_prompts) == [
        f"The internal report was written to {target}. "
        "A snapshot was recorded, marked as retroactive because the date is in the past."
    ]


def test_without_the_option_no_snapshot_is_recorded(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    dialog.snapshot_check.setChecked(False)
    dialog.date_edit.setDate(QDate(2026, 3, 1))
    assert dialog.snapshot_note.isHidden()  # nothing will be recorded
    target = _out(tmp_path) / "plain.pdf"
    _write_report(dialog, fake_prompts, target, confirm=False)
    assert target.is_file()
    assert _snapshots(app_context).list_snapshots() == []
    assert _infos(fake_prompts) == [f"The internal report was written to {target}."]


def test_the_option_follows_the_p04_setting(
    app_context: AppContext, workflow: ReportsWorkflow, anchor: QWidget, qtbot: QtBot
) -> None:
    config = _config(app_context)
    config.save(config.load().with_changes(snapshot_on_report=False))
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    assert not dialog.snapshot_check.isChecked()


def test_the_date_cannot_be_after_today(
    app_context: AppContext, workflow: ReportsWorkflow, anchor: QWidget, qtbot: QtBot
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    dialog.date_edit.setDate(QDate(2026, 3, 9))
    assert dialog.as_of() == TODAY


def test_the_anonymised_variant_is_labelled_and_names_the_threshold(
    app_context: AppContext, workflow: ReportsWorkflow, anchor: QWidget, qtbot: QtBot
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    assert dialog.variant_note.text() == (
        "Internal report: it lists staff identifiers. Handle it as internal data."
    )
    _choose(dialog, "ANONYMISED")
    assert dialog.variant_note.text() == (
        "Anonymised report: staff identifiers, labels and notes are left out. "
        "Personnel counts below 5 are shown as '< 5'."
    )
    config = _config(app_context)
    config.save(config.load().with_changes(small_count_threshold=3))
    _choose(dialog, "INTERNAL")
    _choose(dialog, "ANONYMISED")
    assert dialog.variant_note.text().endswith("Personnel counts below 3 are shown as '< 3'.")
    assert [dialog.variant_combo.itemText(i) for i in range(2)] == [
        "Internal report",
        "Anonymised report",
    ]


def test_no_output_file_chosen_asks_for_one_and_writes_nothing(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    dialog.accept()
    assert _warnings(fake_prompts) == ["Choose where to write the file first."]
    assert dialog.isVisible()
    assert fake_prompts.calls_of("confirm") == []
    assert _snapshots(app_context).list_snapshots() == []


def test_cancelling_the_file_choice_keeps_the_path_empty(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    dialog.choose_button.click()  # the fake picker answers "cancelled"
    assert dialog.path_edit.text() == ""


def test_an_unwritable_target_is_reported_translated_and_records_nothing(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    _write_report(dialog, fake_prompts, tmp_path / "missing-folder" / "r.pdf", confirm=False)
    assert _warnings(fake_prompts) == [EXPECTED_ENGLISH["REPORT_FAILED"]]
    assert dialog.isVisible()
    assert _snapshots(app_context).list_snapshots() == []
    assert not (tmp_path / "missing-folder").exists()


@pytest.mark.parametrize("place", list(PLACES))
def test_a_report_in_a_risky_place_asks_first(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
    place: str,
) -> None:
    checks, warning = PLACES[place]
    workflow.checks = checks
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    target = _out(tmp_path) / "risky.pdf"
    _write_report(dialog, fake_prompts, target, confirm=False)  # declined (the fake says no)
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == f"{warning} {CLOSING}"
    assert not target.exists()
    assert dialog.isVisible()
    assert _snapshots(app_context).list_snapshots() == []

    fake_prompts.script("confirm", True)
    dialog.accept()
    assert target.read_bytes().startswith(b"%PDF-")


def test_the_report_is_available_in_read_only_mode_without_a_snapshot(
    app_context: AppContext,
    read_only_context: AppContext,
    fake_prompts: FakePrompts,
    anchor: QWidget,
    qtbot: QtBot,
    qm_dir: Path,
    tmp_path: Path,
) -> None:
    _seed(app_context)
    flow = ReportsWorkflow(read_only_context, anchor)
    flow.checks = QUIET
    flow.qm_dir = qm_dir
    dialog = _report_dialog(read_only_context, anchor, flow, qtbot)
    assert read_only_context.read_only
    assert not dialog.snapshot_check.isChecked()
    assert not dialog.snapshot_check.isEnabled()
    assert dialog.snapshot_check in read_only_context.edit_targets()
    target = _out(tmp_path) / "readonly.pdf"
    _write_report(dialog, fake_prompts, target, confirm=False)
    assert target.read_bytes().startswith(b"%PDF-")
    assert _snapshots(app_context).list_snapshots() == []
    assert _warnings(fake_prompts) == []


# --------------------------------------------------------------------------- the internal notice


def test_the_handling_notice_set_in_settings_is_on_the_internal_report(
    app_context: AppContext, workflow: ReportsWorkflow, qtbot: QtBot
) -> None:
    section = ReportsSettingsSection(app_context)
    qtbot.addWidget(section)
    builder = _need(workflow.report_builder())
    assert builder.build(TODAY, ReportVariant.INTERNAL).handling_notice == ""
    section.notice_edit.setText("Internal use only")
    section.save_action.trigger()
    assert builder.build(TODAY, ReportVariant.INTERNAL).handling_notice == "Internal use only"


# --------------------------------------------------------------------------- CSV export


def test_the_csv_export_writes_one_file_per_entity_after_the_internal_data_warning(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    tmp_path: Path,
) -> None:
    _seed(app_context)
    folder = _out(tmp_path, "csv")
    fake_prompts.script("choose_folder", folder)
    fake_prompts.script("confirm", True)
    workflow.export_csv()
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == (
        "The files contain internal data: staff, assets, exercises and budget. " + CLOSING
    )
    assert sorted(path.name for path in folder.iterdir()) == sorted(CSV_FILES)
    assert _infos(fake_prompts) == [f"16 files were written to {folder}."]
    text = (folder / "staff_member.csv").read_text(encoding="utf-8-sig")
    assert "DEMO-P001" in text
    assert "DEMO-P002" in text


def test_declining_the_internal_data_warning_writes_nothing(
    fake_prompts: FakePrompts, workflow: ReportsWorkflow, tmp_path: Path
) -> None:
    folder = _out(tmp_path, "csv")
    fake_prompts.script("choose_folder", folder)  # confirm: the fake says no
    workflow.export_csv()
    assert len(fake_prompts.calls_of("confirm")) == 1
    assert list(folder.iterdir()) == []
    assert _infos(fake_prompts) == []


def test_cancelling_the_folder_choice_asks_and_writes_nothing(
    fake_prompts: FakePrompts, workflow: ReportsWorkflow
) -> None:
    workflow.export_csv()
    assert len(fake_prompts.calls_of("choose_folder")) == 1
    assert fake_prompts.calls_of("confirm") == []


@pytest.mark.parametrize("place", list(PLACES))
def test_a_csv_export_in_a_risky_place_adds_the_matching_warning(
    fake_prompts: FakePrompts, workflow: ReportsWorkflow, tmp_path: Path, place: str
) -> None:
    checks, warning = PLACES[place]
    workflow.checks = checks
    fake_prompts.script("choose_folder", _out(tmp_path, "csv"))
    workflow.export_csv()
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == (
        f"The files contain internal data: staff, assets, exercises and budget. {warning} {CLOSING}"
    )


def test_the_csv_export_is_available_in_read_only_mode(
    app_context: AppContext,
    read_only_context: AppContext,
    fake_prompts: FakePrompts,
    anchor: QWidget,
    tmp_path: Path,
) -> None:
    _seed(app_context)
    flow = ReportsWorkflow(read_only_context, anchor)
    flow.checks = QUIET
    folder = _out(tmp_path, "csv")
    fake_prompts.script("choose_folder", folder)
    fake_prompts.script("confirm", True)
    flow.export_csv()
    assert sorted(path.name for path in folder.iterdir()) == sorted(CSV_FILES)


# --------------------------------------------------------------------------- validation export


def test_the_validation_export_writes_the_two_labelled_files(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    _add_edition(app_context, "DEMO-EX-24", "2024-03-01", "2024-03-05")
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    assert dialog.notice_label.text() == (
        "These files are unsuppressed internal data: they hold the exact counts."
    )
    assert dialog.editions_label.text() == "Editions without an earlier snapshot: DEMO-EX-24"
    folder = _out(tmp_path, "validation")
    _export_validation(dialog, fake_prompts, folder)

    assert sorted(path.name for path in folder.iterdir()) == [
        "validation_readings_unsuppressed_internal.csv",
        "validation_results_unsuppressed_internal.csv",
    ]
    readings = (folder / "validation_readings_unsuppressed_internal.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "UNSUPPRESSED_INTERNAL_DATA" in readings
    assert "NO_PRIOR_SNAPSHOT" in readings
    assert _infos(fake_prompts) == [
        f"The validation export was written to {folder}. Editions without a reading: DEMO-EX-24."
    ]
    assert _snapshots(app_context).list_snapshots() == []  # nothing recorded without the option


def test_the_suppression_option_is_labelled_and_changes_the_file_names(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    dialog.suppress_check.setChecked(True)
    assert dialog.notice_label.text() == (
        "Counts below 5 are replaced by '< 5'. The files are still internal data."
    )
    folder = _out(tmp_path, "validation")
    _export_validation(dialog, fake_prompts, folder)
    assert sorted(path.name for path in folder.iterdir()) == [
        "validation_readings_suppressed_internal.csv",
        "validation_results_suppressed_internal.csv",
    ]
    text = (folder / "validation_readings_suppressed_internal.csv").read_text(encoding="utf-8-sig")
    assert "SUPPRESSED_INTERNAL_DATA" in text
    assert "UNSUPPRESSED" not in text


def test_a_retroactive_reading_is_recorded_only_when_asked_for(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    _add_edition(app_context, "DEMO-EX-24", "2024-03-01", "2024-03-05")
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    assert dialog.retro_check.isEnabled()
    dialog.retro_check.setChecked(True)
    changed: list[int] = []
    app_context.data_changed.connect(lambda: changed.append(1))
    folder = _out(tmp_path, "validation")
    _export_validation(dialog, fake_prompts, folder)

    (stored,) = _snapshots(app_context).list_snapshots()
    assert (stored.origin.value, stored.as_of) == ("retroactive", date(2024, 2, 29))
    readings = (folder / "validation_readings_unsuppressed_internal.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "retroactive" in readings
    assert "NO_PRIOR_SNAPSHOT" not in readings
    assert _infos(fake_prompts) == [
        f"The validation export was written to {folder}. Retroactive snapshots recorded: 1."
    ]
    assert changed == [1]


def test_the_retroactive_option_is_disabled_when_every_edition_has_a_snapshot(
    app_context: AppContext, workflow: ReportsWorkflow, anchor: QWidget, qtbot: QtBot
) -> None:
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    assert dialog.editions_label.text() == "Every edition has an earlier snapshot."
    assert not dialog.retro_check.isEnabled()


def test_a_withdrawn_snapshot_is_hidden_from_the_validation_export(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    _add_edition(app_context, "DEMO-EX-27", "2026-09-01", "2026-09-05")
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    page.record_snapshot()
    first = _out(tmp_path, "before")
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    _export_validation(dialog, fake_prompts, first)
    before = (first / "validation_readings_unsuppressed_internal.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "NO_PRIOR_SNAPSHOT" not in before
    assert ";manual;" in before

    page.snapshots_view.selectRow(0)
    fake_prompts.script("text_input", "recorded by mistake")
    page.withdraw_snapshot()
    second = _out(tmp_path, "after")
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    _export_validation(dialog, fake_prompts, second)
    after = (second / "validation_readings_unsuppressed_internal.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "NO_PRIOR_SNAPSHOT" in after
    assert ";manual;" not in after


@pytest.mark.parametrize("place", list(PLACES))
def test_a_validation_export_in_a_risky_place_asks_first(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
    place: str,
) -> None:
    checks, warning = PLACES[place]
    workflow.checks = checks
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    folder = _out(tmp_path, "validation")
    _export_validation(dialog, fake_prompts, folder)  # declined
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == f"{warning} {CLOSING}"
    assert list(folder.iterdir()) == []
    fake_prompts.script("confirm", True)
    dialog.accept()
    assert len(list(folder.iterdir())) == 2


def test_the_validation_export_without_a_folder_asks_for_one(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
) -> None:
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    dialog.accept()
    assert _warnings(fake_prompts) == ["Choose where to write the file first."]
    assert dialog.isVisible()


def test_the_validation_export_in_read_only_mode_works_without_the_retroactive_option(
    app_context: AppContext,
    read_only_context: AppContext,
    fake_prompts: FakePrompts,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    _add_edition(app_context, "DEMO-EX-24", "2024-03-01", "2024-03-05")
    flow = ReportsWorkflow(read_only_context, anchor)
    flow.checks = QUIET
    dialog = _validation_dialog(read_only_context, anchor, flow, qtbot)
    assert not dialog.retro_check.isEnabled()
    assert dialog.retro_check in read_only_context.edit_targets()
    assert dialog.suppress_check not in read_only_context.edit_targets()
    folder = _out(tmp_path, "validation")
    _export_validation(dialog, fake_prompts, folder)
    assert len(list(folder.iterdir())) == 2
    assert _snapshots(app_context).list_snapshots() == []


# --------------------------------------------------------------------------- the snapshot list


def test_a_snapshot_is_recorded_and_listed(app_context: AppContext, qtbot: QtBot) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    assert page.snapshots_model.rowCount() == 0
    changed: list[int] = []
    app_context.data_changed.connect(lambda: changed.append(1))
    page.record_action.trigger()
    assert page.snapshots_model.rowCount() == 1
    cells = _cells(page.snapshots_model, 0)
    assert cells[0] == "03/05/2026"
    assert cells[1].startswith("2026-03-05T12:00:00")
    assert cells[2] == "Recorded by hand"
    assert cells[4] == "Active"
    assert cells[5] == "-"
    assert changed == [1]
    headers = [
        str(page.snapshots_model.headerData(column, Qt.Orientation.Horizontal))
        for column in range(page.snapshots_model.columnCount())
    ]
    assert headers == [
        "As of",
        "Recorded at (UTC)",
        "Origin",
        "Version",
        "State",
        "Reason for withdrawal",
        "Snapshot number",
    ]
    assert cells[6] == "1"  # the id the validation export cites as snapshot_id (P8-19)


def test_withdrawing_asks_for_a_reason_keeps_the_snapshot_and_hides_it(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    page.record_snapshot()
    assert not page.withdraw_action.isEnabled()  # nothing selected
    page.snapshots_view.selectRow(0)
    assert page.withdraw_action.isEnabled()
    fake_prompts.script("text_input", "recorded by mistake")
    page.withdraw_action.trigger()

    (asked,) = fake_prompts.calls_of("text_input")
    assert asked.args[0] == "Withdraw snapshot"
    assert asked.args[1] == "Reason for withdrawing the snapshot (it stays stored):"
    service = _snapshots(app_context)
    assert service.list_snapshots() == []
    (stored,) = service.list_snapshots(include_withdrawn=True)
    assert stored.withdrawn
    assert stored.withdrawal_reason == "recorded by mistake"
    assert service.get(stored.id).values  # the readings are still stored
    assert page.snapshots_model.rowCount() == 0  # hidden by default
    assert not page.show_withdrawn.isChecked()

    page.show_withdrawn.setChecked(True)
    assert page.snapshots_model.rowCount() == 1
    cells = _cells(page.snapshots_model, 0)
    assert (cells[4], cells[5]) == ("Withdrawn", "recorded by mistake")
    page.snapshots_view.selectRow(0)
    assert not page.withdraw_action.isEnabled()  # already withdrawn
    page.show_withdrawn.setChecked(False)
    assert page.snapshots_model.rowCount() == 0


def test_there_is_no_delete_action(app_context: AppContext, qtbot: QtBot) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    texts = [action.text().lower() for action in page.findChildren(QAction)]
    assert texts
    assert not any("delete" in text or "remove" in text for text in texts)


def test_a_blank_reason_is_refused_and_a_cancelled_question_changes_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    page.record_snapshot()
    page.snapshots_view.selectRow(0)
    page.withdraw_snapshot()  # the fake answers "cancelled"
    assert _warnings(fake_prompts) == []
    fake_prompts.script("text_input", "   ")
    page.withdraw_snapshot()
    assert _warnings(fake_prompts) == ["A reason is required."]
    (stored,) = _snapshots(app_context).list_snapshots()
    assert not stored.withdrawn


def test_a_snapshot_for_a_past_as_of_date_is_recorded_as_retroactive_after_asking(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    app_context.set_as_of(date(2026, 2, 1))
    fake_prompts.script("confirm", True)  # P8-19: the page asks first, as the dashboard does
    page.record_snapshot()
    (question,) = fake_prompts.calls_of("confirm")
    assert question.title == "Record snapshot"
    assert question.text == "Record a retroactive snapshot for 02/01/2026?"
    cells = _cells(page.snapshots_model, 0)
    assert (cells[0], cells[2]) == ("02/01/2026", "Retroactive")


def test_declining_the_retroactive_question_records_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    app_context.set_as_of(date(2026, 2, 1))
    page.record_snapshot()  # the fake answers "no"
    assert len(fake_prompts.calls_of("confirm")) == 1
    assert page.snapshots_model.rowCount() == 0
    assert _snapshots(app_context).list_snapshots() == []


def test_a_snapshot_for_today_is_recorded_without_a_question(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    page.record_snapshot()
    assert fake_prompts.calls_of("confirm") == []
    assert page.snapshots_model.rowCount() == 1


def test_the_snapshot_list_survives_a_data_change(app_context: AppContext, qtbot: QtBot) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    _snapshots(app_context).record(TODAY, origin=snapshots_module.SnapshotOrigin.MANUAL)
    assert page.snapshots_model.rowCount() == 0
    app_context.notify_data_changed()
    assert page.snapshots_model.rowCount() == 1


# --------------------------------------------------------------------------- import


def _staff_file(folder: Path, name: str, lines: list[str]) -> Path:
    path = folder / name
    header = "identifier;label;category;active_from;active_until"
    path.write_text("\n".join([header, *lines]) + "\n", encoding="utf-8")
    return path


def _import_dialog(
    context: AppContext, anchor: QWidget, flow: ReportsWorkflow, qtbot: QtBot, entity: str
) -> ImportDialog:
    dialog = ImportDialog(context, anchor, workflow=flow)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.entity_combo.setCurrentIndex(dialog.entity_combo.findData(entity))
    return dialog


def _issue_rows(dialog: ImportDialog) -> list[list[str]]:
    return [_cells(dialog.issues_model, row) for row in range(dialog.issues_model.rowCount())]


def test_a_csv_export_then_import_round_trips_through_the_ui(
    app_context: AppContext,
    second_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    _seed(app_context)
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    page.workflow.checks = QUIET
    folder = _out(tmp_path, "csv")
    fake_prompts.script("choose_folder", folder)
    fake_prompts.script("confirm", True)
    page.csv_action.trigger()
    assert (folder / "staff_member.csv").is_file()

    flow = ReportsWorkflow(second_context, anchor)
    flow.checks = QUIET
    changed: list[int] = []
    second_context.data_changed.connect(lambda: changed.append(1))
    for entity, label, count in (
        ("staff_member", "Staff", 2),
        ("ppe_certification", "PPE certificates", 3),
    ):
        dialog = _import_dialog(second_context, anchor, flow, qtbot, entity)
        fake_prompts.script("open_file", folder / f"{entity}.csv")
        dialog.choose_button.click()
        assert _need(dialog.report()).ok
        assert dialog.summary_label.text() == (f"No problems found: {count} rows can be imported.")
        assert dialog.file_label.text() == f"{entity}.csv"
        assert _issue_rows(dialog) == []
        fake_prompts.script("confirm", True)
        dialog.accept()
        assert _infos(fake_prompts)[-1] == f"{count} rows of {label} were imported."

    people = _need(second_context.services.personnel)
    assert [person.identifier for person in people.list_staff()] == ["DEMO-P001", "DEMO-P002"]
    assert changed == [1, 1]
    assert _warnings(fake_prompts) == []


def test_a_dry_run_shows_the_translated_errors_and_writes_nothing(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    source = _staff_file(
        _out(tmp_path),
        "staff_member.csv",
        [
            "DEMO-P010;;;2020-01-01;",
            "DEMO-P011;;;not-a-date;",
            "DEMO-P010;;;2021-01-01;",
        ],
    )
    changed: list[int] = []
    app_context.data_changed.connect(lambda: changed.append(1))
    dialog = _import_dialog(app_context, anchor, workflow, qtbot, "staff_member")
    fake_prompts.script("open_file", source)
    dialog.choose_button.click()

    assert _issue_rows(dialog) == [
        ["3", "active_from", "The date is not valid.", "INVALID_DATE"],
        ["4", "-", "The row repeats an earlier row of the file.", "DUPLICATE_IN_FILE"],
    ]
    assert dialog.summary_label.text() == (
        "2 problems found in 3 rows. Nothing is imported until they are fixed."
    )
    assert _need(app_context.services.personnel).list_staff() == []  # the valid row is not stored

    dialog.accept()  # the file still has problems: nothing is asked, nothing is written
    assert _warnings(fake_prompts) == ["The file has problems. Nothing was imported."]
    assert fake_prompts.calls_of("confirm") == []
    assert dialog.isVisible()
    assert _need(app_context.services.personnel).list_staff() == []
    assert changed == []


def test_a_file_that_is_not_utf8_is_rejected_as_a_whole(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    source = _out(tmp_path) / "staff_member.csv"
    text = "identifier;label;category;active_from;active_until\nDEMO-P1;caf\u00e9;;2020-01-01;\n"
    source.write_bytes(text.encode("latin-1"))
    dialog = _import_dialog(app_context, anchor, workflow, qtbot, "staff_member")
    fake_prompts.script("open_file", source)
    dialog.choose_button.click()
    assert _issue_rows(dialog) == [
        ["-", "-", "The file is not valid UTF-8. Save it as UTF-8 and try again.", "NOT_UTF8"]
    ]
    assert _need(app_context.services.personnel).list_staff() == []


def test_a_missing_file_is_reported_as_unreadable(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _import_dialog(app_context, anchor, workflow, qtbot, "staff_member")
    fake_prompts.script("open_file", _out(tmp_path) / "missing.csv")
    dialog.choose_button.click()
    assert _warnings(fake_prompts) == [EXPECTED_ENGLISH["FILE_UNREADABLE"]]
    assert dialog.report() is None


def test_changing_the_kind_of_data_checks_the_file_again(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    source = _staff_file(_out(tmp_path), "staff_member.csv", ["DEMO-P010;;;2020-01-01;"])
    dialog = _import_dialog(app_context, anchor, workflow, qtbot, "staff_member")
    fake_prompts.script("open_file", source)
    dialog.choose_button.click()
    assert _need(dialog.report()).ok
    dialog.entity_combo.setCurrentIndex(dialog.entity_combo.findData("asset"))
    report = _need(dialog.report())
    assert report.entity == "asset"
    assert not report.ok
    codes = {row[3] for row in _issue_rows(dialog)}
    assert {"UNKNOWN_COLUMN", "MISSING_COLUMN"} <= codes  # a staff file is not an asset file


def test_declining_the_import_confirmation_writes_nothing(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    source = _staff_file(_out(tmp_path), "staff_member.csv", ["DEMO-P010;;;2020-01-01;"])
    dialog = _import_dialog(app_context, anchor, workflow, qtbot, "staff_member")
    fake_prompts.script("open_file", source)
    dialog.choose_button.click()
    dialog.accept()  # the fake answers "no"
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == "Import 1 rows of Staff?"
    assert dialog.isVisible()
    assert _need(app_context.services.personnel).list_staff() == []


def test_importing_without_a_file_asks_for_one(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
) -> None:
    dialog = _import_dialog(app_context, anchor, workflow, qtbot, "staff_member")
    assert dialog.summary_label.text() == "Choose a file to check it before anything is imported."
    dialog.accept()
    assert _warnings(fake_prompts) == ["Choose the file to import first."]


def test_the_entity_names_are_translated_and_follow_the_import_order(
    app_context: AppContext, workflow: ReportsWorkflow, anchor: QWidget, qtbot: QtBot
) -> None:
    dialog = _import_dialog(app_context, anchor, workflow, qtbot, "staff_member")
    names = [str(dialog.entity_combo.itemData(i)) for i in range(dialog.entity_combo.count())]
    assert names == [spec.name for spec in csv_io.ENTITIES]
    assert dialog.entity_combo.itemText(0) == "Training courses"
    assert dialog.entity_combo.itemText(len(names) - 1) == "Budget executions"


# --------------------------------------------------------------------------- read-only mode


def test_read_only_mode_disables_import_and_snapshot_recording_but_not_reports_and_exports(
    read_only_context: AppContext, qtbot: QtBot
) -> None:
    page = ReportsPage(read_only_context)
    qtbot.addWidget(page)
    assert read_only_context.read_only
    for action in (page.import_action, page.record_action, page.withdraw_action):
        assert not action.isEnabled()
        assert action in read_only_context.edit_targets()
    for action in (page.report_action, page.csv_action, page.validation_action):
        assert action.isEnabled()
        assert action not in read_only_context.edit_targets()
    page.record_action.setEnabled(True)  # read-only mode undoes it at once
    assert not page.record_action.isEnabled()


def test_the_service_still_refuses_a_snapshot_in_read_only_mode_with_the_message(
    read_only_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    page = ReportsPage(read_only_context)
    qtbot.addWidget(page)
    page.record_snapshot()  # called directly all the same
    assert _warnings(fake_prompts) == [EXPECTED_ENGLISH["READ_ONLY"]]
    assert _snapshots(read_only_context).list_snapshots() == []


def test_the_import_wizard_is_disabled_in_read_only_mode(
    read_only_context: AppContext, anchor: QWidget, qtbot: QtBot
) -> None:
    dialog = ImportDialog(read_only_context, anchor)
    qtbot.addWidget(dialog)
    assert not dialog.choose_button.isEnabled()
    ok = _need(dialog.buttons.button(QDialogButtonBox.StandardButton.Ok))
    assert not ok.isEnabled()


def test_the_settings_sections_follow_read_only_mode(
    read_only_context: AppContext, qtbot: QtBot
) -> None:
    reports = ReportsSettingsSection(read_only_context)
    snapshots = SnapshotsSettingsSection(read_only_context)
    for section in (reports, snapshots):
        qtbot.addWidget(section)
        assert not section.save_action.isEnabled()
    assert not reports.threshold_spin.isEnabled()
    assert not reports.notice_edit.isEnabled()
    assert not reports.threshold_row.confirm.isEnabled()
    assert not snapshots.monthly_check.isEnabled()
    assert not snapshots.on_report_check.isEnabled()


# --------------------------------------------------------------------------- settings sections


def test_the_reports_section_stores_the_threshold_and_the_notice(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = ReportsSettingsSection(app_context)
    qtbot.addWidget(section)
    assert (section.threshold_spin.minimum(), section.threshold_spin.value()) == (1, 5)
    assert section.notice_edit.text() == ""
    section.threshold_spin.setValue(8)
    section.notice_edit.setText("Handle with care")
    section.save_action.trigger()
    stored = _config(app_context).load()
    assert (stored.small_count_threshold, stored.report_handling_notice) == (8, "Handle with care")

    _config(app_context).save(stored.with_changes(small_count_threshold=6))
    app_context.notify_data_changed()
    assert section.threshold_spin.value() == 6
    assert fake_prompts.calls == []


def test_a_threshold_below_one_is_refused_with_the_message(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    section = ReportsSettingsSection(app_context)
    qtbot.addWidget(section)
    section.threshold_spin.setMinimum(0)
    section.threshold_spin.setValue(0)
    section.save_action.trigger()
    assert _warnings(fake_prompts) == [EXPECTED_ENGLISH["THRESHOLD_TOO_LOW"]]
    assert _config(app_context).load().small_count_threshold == 5
    assert section.threshold_spin.value() == 5


def test_the_reports_section_badges_follow_the_placeholders(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = ReportsSettingsSection(app_context)
    qtbot.addWidget(section)
    config = _config(app_context)
    assert section.threshold_row.placeholder == "A11"
    assert section.notice_row.placeholder == "P10"
    for row in (section.threshold_row, section.notice_row):
        assert not row.badge.isHidden()
        assert row.badge.text() == "Placeholder - to be confirmed"
        assert row.confirm.text() == "Confirm"
    section.threshold_row.confirm.click()
    assert config.badge_for_field("small_count_threshold") is None
    assert section.threshold_row.badge.isHidden()
    assert section.threshold_row.confirm.isHidden()
    assert not section.notice_row.badge.isHidden()
    section.notice_row.confirm.click()
    assert config.badge_for_field("report_handling_notice") is None


def test_the_snapshots_section_stores_the_p04_switches(
    app_context: AppContext, qtbot: QtBot
) -> None:
    section = SnapshotsSettingsSection(app_context)
    qtbot.addWidget(section)
    assert section.monthly_check.isChecked()
    assert section.on_report_check.isChecked()
    section.monthly_check.setChecked(False)
    section.save_action.trigger()
    stored = _config(app_context).load()
    assert (stored.snapshot_monthly, stored.snapshot_on_report) == (False, True)
    section.on_report_check.setChecked(False)
    section.save_action.trigger()
    assert _config(app_context).load().snapshot_on_report is False


def test_the_snapshots_section_badges_follow_p04(app_context: AppContext, qtbot: QtBot) -> None:
    section = SnapshotsSettingsSection(app_context)
    qtbot.addWidget(section)
    config = _config(app_context)
    assert section.monthly_row.placeholder == "P04"
    assert section.on_report_row.placeholder == "P04"
    section.monthly_row.confirm.click()
    assert config.badge_for_field("snapshot_monthly") is None
    assert section.monthly_row.badge.isHidden()
    assert section.on_report_row.badge.isHidden()  # one placeholder, both fields


def _corrupt_setting(context: AppContext) -> None:
    """A stored setting that no longer validates (what a restored older backup can leave)."""
    _conn(context).execute(
        "INSERT INTO setting (key, value_json) VALUES (?, ?)",
        ("config.cert_warning_days", "not json"),
    )


def _repair_setting(context: AppContext) -> None:
    _conn(context).execute("DELETE FROM setting WHERE key = ?", ("config.cert_warning_days",))


def test_an_unreadable_setting_is_explained_and_the_inputs_wait_for_the_repair(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    reports = ReportsSettingsSection(app_context)
    snapshots = SnapshotsSettingsSection(app_context)
    sections = (reports, snapshots)
    inputs: tuple[QWidget, ...] = (
        reports.threshold_spin,
        reports.notice_edit,
        snapshots.monthly_check,
        snapshots.on_report_check,
    )
    for section in sections:
        qtbot.addWidget(section)
        assert section.config_error_label.isHidden()
    assert all(widget.isEnabled() for widget in inputs)

    _corrupt_setting(app_context)
    app_context.notify_data_changed()  # a raising slot would fail the test

    for section in sections:
        assert not section.config_error_label.isHidden()
        assert section.config_error_label.text() == "A stored setting cannot be read."
        assert not section.save_action.isEnabled()
    for row in (
        reports.threshold_row,
        reports.notice_row,
        snapshots.monthly_row,
        snapshots.on_report_row,
    ):
        assert row.badge.isHidden()
        assert row.confirm.isHidden()
    assert not any(widget.isEnabled() for widget in inputs)
    assert fake_prompts.calls == []

    app_context.translator_manager.set_language("pt_BR")
    portuguese = "Uma configura\u00e7\u00e3o armazenada n\u00e3o pode ser lida."
    english = "A stored setting cannot be read."

    def all_show(text: str) -> bool:
        return all(section.config_error_label.text() == text for section in sections)

    qtbot.waitUntil(lambda: all_show(portuguese))
    app_context.translator_manager.set_language("en_US")
    qtbot.waitUntil(lambda: all_show(english))

    _repair_setting(app_context)
    app_context.notify_data_changed()

    for section in sections:
        assert section.config_error_label.isHidden()
        assert section.save_action.isEnabled()
    assert all(widget.isEnabled() for widget in inputs)
    assert not reports.threshold_row.badge.isHidden()


def test_the_sections_and_the_page_are_reachable_through_the_registry(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot
) -> None:
    specs = (
        PageSpec("reports.test_page", 60, page_title, create_page),
        SettingsSectionSpec(
            "reports.test_section", "reports", reports_section_title, create_reports_section
        ),
        SettingsSectionSpec(
            "snapshots.test_section", "snapshots", snapshots_section_title, create_snapshots_section
        ),
        DialogSpec("reports.test_report", demo_report_dialog),
        DialogSpec("reports.test_validation", demo_validation_export_dialog),
        DialogSpec("reports.test_import", demo_import_dialog),
    )
    with registry.registered(*specs):
        (page_spec,) = [s for s in registry.pages() if s.key == "reports.test_page"]
        assert page_spec.title() == "Reports"
        (reports_spec,) = [
            s for s in registry.settings_sections("reports") if s.key == "reports.test_section"
        ]
        (snapshots_spec,) = [
            s for s in registry.settings_sections("snapshots") if s.key == "snapshots.test_section"
        ]
        assert reports_spec.title() == "Reports and anonymisation"
        assert snapshots_spec.title() == "Readiness snapshots"
        widgets = [
            page_spec.factory(app_context),
            reports_spec.factory(app_context),
            snapshots_spec.factory(app_context),
        ]
        dialogs = [
            s.factory(app_context, None)
            for s in registry.dialogs()
            if s.key.startswith("reports.test_")
        ]
    for widget in [*widgets, *dialogs]:
        qtbot.addWidget(widget)
    assert isinstance(widgets[0], ReportsPage)
    assert isinstance(widgets[1], ReportsSettingsSection)
    assert isinstance(widgets[2], SnapshotsSettingsSection)
    assert [type(d) for d in dialogs] == [ReportDialog, ValidationExportDialog, ImportDialog]
    assert fake_prompts.calls == []


# --------------------------------------------------------------------------- no services


def test_the_factories_build_without_services_and_prompt_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot, tmp_path: Path
) -> None:
    empty = AppContext(
        conn=None,
        clock=app_context.clock,
        location=app_context.location,
        prompts=fake_prompts,
        preferences=PreferencesStore(tmp_path / "nodb", writable=False),
        translator_manager=app_context.translator_manager,
    )
    before = snapshot(app_context.location.path)
    page = create_page(empty)
    reports = create_reports_section(empty)
    snapshots = create_snapshots_section(empty)
    dialogs = [
        demo_report_dialog(empty, None),
        demo_validation_export_dialog(empty, None),
        demo_import_dialog(empty, None),
    ]
    for widget in [page, reports, snapshots, *dialogs]:
        qtbot.addWidget(widget)
    assert isinstance(page, ReportsPage)
    for action in (
        page.report_action,
        page.csv_action,
        page.validation_action,
        page.import_action,
        page.record_action,
        page.withdraw_action,
    ):
        assert not action.isEnabled()
    assert page.snapshots_model.rowCount() == 0
    assert isinstance(reports, ReportsSettingsSection)
    assert not reports.save_action.isEnabled()
    for dialog in dialogs:
        assert dialog.windowTitle()
        dialog.show()
        dialog.accept()  # nothing to run: the dialog stays open
        assert dialog.isVisible()
    page.record_snapshot()
    page.withdraw_snapshot()
    page.export_csv()
    assert fake_prompts.calls == []
    assert snapshot(app_context.location.path) == before
    empty.deleteLater()


def test_a_language_switch_after_the_database_was_closed_raises_nothing(
    app_context: AppContext,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    sections = [ReportsSettingsSection(app_context), SnapshotsSettingsSection(app_context)]
    dialogs = [
        _report_dialog(app_context, anchor, workflow, qtbot),
        _validation_dialog(app_context, anchor, workflow, qtbot),
        _import_dialog(app_context, anchor, workflow, qtbot, "staff_member"),
    ]
    for section in sections:
        qtbot.addWidget(section)
    _conn(app_context).close()  # what AppHandle.close_database does
    app_context.conn = None
    assert app_context.services.snapshots is None

    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: page.record_action.text() == "Gravar registro")
    assert dialogs[0].windowTitle() == "Criar relat\u00f3rio"
    assert dialogs[1].windowTitle() == "Exporta\u00e7\u00e3o de valida\u00e7\u00e3o"
    app_context.translator_manager.set_language("es_ES")
    qtbot.waitUntil(lambda: page.record_action.text() == "Guardar registro")
    assert dialogs[2].windowTitle() == "Importar archivo CSV"
    assert sections[1].save_action.text() == "Guardar ajustes"


def test_the_texts_follow_a_language_switch(
    app_context: AppContext, workflow: ReportsWorkflow, anchor: QWidget, qtbot: QtBot
) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    page.record_snapshot()
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    assert page.export_caption.text() == "Data export"
    app_context.translator_manager.set_language("pt_BR")
    qtbot.waitUntil(lambda: page.export_caption.text() == "Exporta\u00e7\u00e3o de dados")
    assert page.show_withdrawn.text() == "Mostrar registros retirados"
    assert _cells(page.snapshots_model, 0)[0] == "05/03/2026"
    assert _cells(page.snapshots_model, 0)[2] == "Registrado manualmente"
    qtbot.waitUntil(lambda: dialog.windowTitle() == "Criar relat\u00f3rio")
    assert dialog.variant_combo.itemText(1) == "Relat\u00f3rio anonimizado"


# --------------------------------------------------------------------------- pseudo-locale walk

FACTORIES: dict[str, Callable[[AppContext], QWidget]] = {
    "page": create_page,
    "reports_section": create_reports_section,
    "snapshots_section": create_snapshots_section,
    "report_dialog": lambda context: demo_report_dialog(context, None),
    "validation_dialog": lambda context: demo_validation_export_dialog(context, None),
    "import_dialog": lambda context: demo_import_dialog(context, None),
}


@pytest.mark.parametrize("lang", LANGUAGES)
@pytest.mark.parametrize("name", list(FACTORIES))
def test_everything_is_translated_in_each_pseudo_language(
    pseudo_context: AppContext, qtbot: QtBot, name: str, lang: str
) -> None:
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    assert_fully_translated(widget, "pt_BR")
    pseudo_context.translator_manager.set_language(lang)
    qtbot.waitUntil(lambda: not find_untranslated(widget, lang), timeout=3000)
    assert_fully_translated(widget, lang)


@pytest.mark.parametrize("lang", LANGUAGES)
@pytest.mark.parametrize("name", ["reports_section", "snapshots_section"])
def test_the_unreadable_setting_message_is_translated_in_each_pseudo_language(
    pseudo_context: AppContext, qtbot: QtBot, name: str, lang: str
) -> None:
    pseudo_context.translator_manager.set_language(lang)
    widget = FACTORIES[name](pseudo_context)
    qtbot.addWidget(widget)
    _corrupt_setting(pseudo_context)
    pseudo_context.notify_data_changed()
    label = widget.findChild(QLabel, "config_error_label")
    assert label is not None
    assert not label.isHidden()
    assert label.text() != "A stored setting cannot be read."
    qtbot.waitUntil(lambda: not find_untranslated(widget, lang), timeout=3000)
    assert_fully_translated(widget, lang)


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_page_with_data_is_translated_in_each_pseudo_language(
    pseudo_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot, lang: str
) -> None:
    page = ReportsPage(pseudo_context)
    qtbot.addWidget(page)
    page.record_snapshot()
    page.snapshots_view.selectRow(0)
    fake_prompts.script("text_input", "reason")
    page.withdraw_snapshot()
    page.show_withdrawn.setChecked(True)
    assert page.snapshots_model.rowCount() == 1
    pseudo_context.translator_manager.set_language(lang)
    qtbot.waitUntil(lambda: not find_untranslated(page, lang), timeout=3000)
    assert_fully_translated(page, lang)


@pytest.mark.parametrize("lang", LANGUAGES)
def test_the_dialogs_in_their_other_states_are_translated(
    pseudo_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
    lang: str,
) -> None:
    _add_edition(pseudo_context, "DEMO-EX-24", "2024-03-01", "2024-03-05")
    report = _report_dialog(pseudo_context, anchor, workflow, qtbot)
    _choose(report, "ANONYMISED")
    report.date_edit.setDate(QDate(2026, 3, 1))
    validation = _validation_dialog(pseudo_context, anchor, workflow, qtbot)
    validation.suppress_check.setChecked(True)
    source = _staff_file(
        _out(tmp_path), "staff_member.csv", ["DEMO-P010;;;not-a-date;", "DEMO-P010;;;2020-01-01;"]
    )
    wizard = _import_dialog(pseudo_context, anchor, workflow, qtbot, "staff_member")
    fake_prompts.script("open_file", source)
    wizard.choose_button.click()
    assert _need(wizard.report()).errors
    assert not report.snapshot_note.isHidden()
    pseudo_context.translator_manager.set_language(lang)
    dialogs: tuple[QWidget, ...] = (report, validation, wizard)
    for dialog in dialogs:

        def translated(widget: QWidget = dialog) -> bool:
            return not find_untranslated(widget, lang)

        qtbot.waitUntil(translated, timeout=3000)
        assert_fully_translated(dialog, lang)


def test_the_titles_are_translated(pseudo_context: AppContext) -> None:
    assert page_title() == "\u27e6Reports\u27e7"
    assert reports_section_title() == "\u27e6Reports and anonymisation\u27e7"
    assert snapshots_section_title() == "\u27e6Readiness snapshots\u27e7"


# --------------------------------------------------------------------------- labels


def test_every_code_has_a_label_in_all_languages(app_context: AppContext) -> None:
    texts: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        texts[lang] = {code: error_label(code) for code in ALL_ERROR_CODES}
    for lang in LANGUAGES:
        for code, text in texts[lang].items():
            assert text.strip(), (lang, code)
            assert text != code, (lang, code)
    for code, english in texts["en_US"].items():
        assert english == EXPECTED_ENGLISH[code], code
        assert texts["pt_BR"][code] != english, code
        assert texts["es_ES"][code] != english, code
        assert texts["pt_BR"][code] != texts["es_ES"][code], code
    assert set(ALL_ERROR_CODES) == set(EXPECTED_ENGLISH)
    assert len(set(ALL_ERROR_CODES)) == len(ALL_ERROR_CODES)


def test_an_unknown_code_is_shown_as_itself() -> None:
    assert error_label("NOT_A_CODE") == "NOT_A_CODE"
    assert entity_label("not_an_entity") == "not_an_entity"
    assert origin_label("elsewhere") == "elsewhere"
    assert variant_label("OTHER") == "OTHER"


def _own_constants(module: ModuleType) -> set[str]:
    """Upper-case names the module DEFINES as a string equal to the name (imports excluded)."""
    found: set[str] = set()
    for node in ast.parse(inspect.getsource(module)).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target, value = node.targets[0], node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and value.value == target.id
        ):
            found.add(target.id)
    return found


def test_all_error_codes_lists_every_code_of_the_snapshot_export_and_import_services() -> None:
    assert _own_constants(snapshots_module) == {
        "AS_OF_IN_FUTURE",
        "ORIGIN_NOT_ALLOWED",
        "REASON_REQUIRED",
        "ALREADY_WITHDRAWN",
    }
    assert _own_constants(export_module) == {"UNKNOWN_ENTITY", "EXPORT_FAILED"}
    assert _own_constants(importer_module) == {
        "UNKNOWN_REFERENCE",
        "DUPLICATE_IN_FILE",
        "DUPLICATE_KEY",
        "BUILT_IN_NOT_ALLOWED",
        "FILE_UNREADABLE",
        "STORAGE_REFUSED",
    }
    covered = (
        _own_constants(snapshots_module)
        | _own_constants(export_module)
        | _own_constants(importer_module)
    )
    assert covered <= set(ALL_ERROR_CODES)
    assert "REPORT_FAILED" in ALL_ERROR_CODES
    assert "READ_ONLY" in ALL_ERROR_CODES


def test_all_error_codes_lists_the_csv_reader_codes() -> None:
    csv_codes = {
        "NOT_UTF8",
        "MALFORMED_CSV",
        "HEADER_MISMATCH",
        "WRONG_COLUMN_COUNT",
        "WRONG_FIELD_COUNT",
        "DUPLICATE_COLUMN",
        "UNKNOWN_COLUMN",
        "MISSING_COLUMN",
        "REQUIRED",
        "INVALID_NUMBER",
        "INVALID_DATE",
        "INVALID_BOOL",
        "INVALID_CURRENCY",
        "INVALID_AMOUNT",
        "INVALID_VALUE",
    }
    assert csv_codes <= set(ALL_ERROR_CODES)


def test_the_names_of_the_entities_origins_variants_and_states_are_translated(
    app_context: AppContext,
) -> None:
    names: dict[str, list[str]] = {}
    for lang in LANGUAGES:
        app_context.translator_manager.set_language(lang)
        names[lang] = [
            *(entity_label(spec.name) for spec in csv_io.ENTITIES),
            *(origin_label(o) for o in ("manual", "monthly", "report", "retroactive")),
            *(variant_label(v) for v in ("INTERNAL", "ANONYMISED")),
            state_label(withdrawn=True),
            state_label(withdrawn=False),
        ]
    assert len(names["en_US"]) == 16 + 4 + 2 + 2
    for position, english in enumerate(names["en_US"]):
        assert english.strip()
        assert names["pt_BR"][position] != english
        assert names["es_ES"][position] != english
    assert names["en_US"][4] == "Staff"
    assert names["pt_BR"][4] == "Pessoal"
    assert names["es_ES"][4] == "Personal"


def test_a_snapshot_view_type_is_what_the_list_holds(app_context: AppContext, qtbot: QtBot) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    page.record_snapshot()
    page.snapshots_view.selectRow(0)
    assert isinstance(page.selected_snapshot(), SnapshotView)


# --------------------------------------------------------------------------- Phase 8 review


def test_the_suggested_file_name_follows_the_variant_and_the_date(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    folder = _out(tmp_path)
    fake_prompts.script("save_file", folder / "cbrn-report-internal-2026-03-05.pdf")
    dialog.choose_button.click()

    _choose(dialog, "ANONYMISED")
    assert dialog.path_edit.text() == str(folder / "cbrn-report-anonymised-2026-03-05.pdf")
    dialog.date_edit.setDate(QDate(2026, 3, 1))
    assert dialog.path_edit.text() == str(folder / "cbrn-report-anonymised-2026-03-01.pdf")
    _choose(dialog, "INTERNAL")
    assert dialog.path_edit.text() == str(folder / "cbrn-report-internal-2026-03-01.pdf")


def test_a_name_the_user_chose_or_typed_is_never_renamed(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    folder = _out(tmp_path)
    fake_prompts.script("save_file", folder / "mine.pdf")
    dialog.choose_button.click()
    _choose(dialog, "ANONYMISED")
    assert dialog.path_edit.text() == str(folder / "mine.pdf")

    _choose(dialog, "INTERNAL")
    fake_prompts.script("save_file", folder / "cbrn-report-internal-2026-03-05.pdf")
    dialog.choose_button.click()
    dialog.path_edit.setText(str(folder / "typed.pdf"))  # the user edits the suggestion
    _choose(dialog, "ANONYMISED")
    assert dialog.path_edit.text() == str(folder / "typed.pdf")


@pytest.mark.parametrize(
    ("variant", "name", "other", "chosen"),
    [
        (
            "INTERNAL",
            "cbrn-report-anonymised-2026-03-05.pdf",
            "Anonymised report",
            "Internal report",
        ),
        (
            "ANONYMISED",
            "cbrn-report-internal-2026-03-05.pdf",
            "Internal report",
            "Anonymised report",
        ),
    ],
    ids=["internal-under-anonymised-name", "anonymised-under-internal-name"],
)
def test_a_file_name_of_the_other_variant_is_refused_and_nothing_is_written(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
    variant: str,
    name: str,
    other: str,
    chosen: str,
) -> None:
    dialog = _report_dialog(app_context, anchor, workflow, qtbot)
    _choose(dialog, variant)
    folder = _out(tmp_path)
    dialog.path_edit.setText(str(folder / name))

    assert dialog.submit() is False

    assert _warnings(fake_prompts) == [
        f"The file name belongs to another kind of report ({other}), but the chosen report is: "
        f"{chosen}. Change the file name or the report."
    ]
    assert list(folder.iterdir()) == []
    assert _snapshots(app_context).list_snapshots() == []
    assert dialog.isVisible()  # the dialog stays open


def test_the_csv_export_asks_before_replacing_existing_files(
    app_context: AppContext, fake_prompts: FakePrompts, workflow: ReportsWorkflow, tmp_path: Path
) -> None:
    folder = _out(tmp_path, "csv")
    (folder / "staff_member.csv").write_text("old", encoding="utf-8")
    (folder / "asset.csv").write_text("old", encoding="utf-8")
    fake_prompts.script("choose_folder", folder)
    fake_prompts.script("confirm", True, False)  # the internal-data notice, then the replacement

    workflow.export_csv()

    first, second = fake_prompts.calls_of("confirm")
    assert second.text == "2 existing files in this folder will be replaced. Continue?"
    assert first.text != second.text
    assert sorted(path.name for path in folder.iterdir()) == ["asset.csv", "staff_member.csv"]
    assert (folder / "staff_member.csv").read_text(encoding="utf-8") == "old"
    assert _infos(fake_prompts) == []


def test_the_csv_export_replaces_existing_files_once_confirmed(
    fake_prompts: FakePrompts, workflow: ReportsWorkflow, tmp_path: Path
) -> None:
    folder = _out(tmp_path, "csv")
    (folder / "staff_member.csv").write_text("old", encoding="utf-8")
    fake_prompts.script("choose_folder", folder)
    fake_prompts.script("confirm", True, True)

    workflow.export_csv()

    assert fake_prompts.calls_of("confirm")[1].text == (
        "1 existing file in this folder will be replaced. Continue?"
    )
    assert sorted(path.name for path in folder.iterdir()) == sorted(CSV_FILES)
    assert (folder / "staff_member.csv").read_text(encoding="utf-8-sig") != "old"


def test_the_csv_export_asks_nothing_about_replacing_in_an_empty_folder(
    fake_prompts: FakePrompts, workflow: ReportsWorkflow, tmp_path: Path
) -> None:
    fake_prompts.script("choose_folder", _out(tmp_path, "csv"))
    fake_prompts.script("confirm", True)

    workflow.export_csv()

    assert len(fake_prompts.calls_of("confirm")) == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_error_codes_of_the_module_services_have_a_label_on_an_import_row(
    app_context: AppContext, language: str
) -> None:
    app_context.translator_manager.set_language(language)
    codes = {
        "ACTIVE_UNTIL_BEFORE_FROM",
        "UNKNOWN_COUNTRY",
        "NEGATIVE_AMOUNT",
        "COURSE_INACTIVE",
        "TYPE_INACTIVE",
        "METRIC_INACTIVE",
        "SOURCE_INACTIVE",
        "IN_SERVICE_UNTIL_BEFORE_FROM",
        "INVALID_KIND",
        "INVALID_YEAR",
        "NEGATIVE_PARTICIPANTS",
        "NEGATIVE_RESPONDENTS",
        "EXECUTION_OUTSIDE_FISCAL_YEAR",
        "CURRENCY_IN_USE",
        "ONLY_STATUS_EVENT",
        "SCALE_EXCLUDES_RESULTS",
    }
    for module in (personnel_module, infrastructure_module, exercises_module, budget_module):
        codes |= _own_constants(module)

    for code in sorted(codes):
        label = error_label(code)
        assert label.strip(), code
        assert label != code, (language, code)


def test_a_failed_validation_export_after_recording_reports_the_snapshots_and_refreshes(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    _add_edition(app_context, "DEMO-EX-24", "2024-03-01", "2024-03-05")
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    dialog.retro_check.setChecked(True)
    changed: list[int] = []
    app_context.data_changed.connect(lambda: changed.append(1))
    folder = _out(tmp_path, "validation")
    (folder / "validation_results_unsuppressed_internal.csv").mkdir()  # the second file fails
    _export_validation(dialog, fake_prompts, folder)

    (stored,) = _snapshots(app_context).list_snapshots()
    assert stored.origin.value == "retroactive"  # the snapshot stays
    assert _warnings(fake_prompts) == [
        "The export files could not be written. Check the chosen folder.",
        "Retroactive snapshots were recorded before the export failed (snapshot numbers: 1). "
        "They stay stored; withdraw them in the snapshot list if they are not wanted.",
    ]
    assert changed == [1]
    assert _infos(fake_prompts) == []


def test_a_failed_validation_export_that_recorded_nothing_adds_no_second_warning(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    dialog = _validation_dialog(app_context, anchor, workflow, qtbot)
    changed: list[int] = []
    app_context.data_changed.connect(lambda: changed.append(1))
    folder = _out(tmp_path, "validation")
    (folder / "validation_results_unsuppressed_internal.csv").mkdir()
    _export_validation(dialog, fake_prompts, folder)

    assert _warnings(fake_prompts) == [
        "The export files could not be written. Check the chosen folder."
    ]
    assert changed == []


def test_the_templates_of_every_entity_are_written_after_asking_about_existing_ones(
    app_context: AppContext, fake_prompts: FakePrompts, workflow: ReportsWorkflow, tmp_path: Path
) -> None:
    folder = _out(tmp_path, "templates")
    fake_prompts.script("choose_folder", folder)
    workflow.write_templates()

    assert _infos(fake_prompts) == [f"16 template files were written to {folder}."]
    assert fake_prompts.calls_of("confirm") == []  # a plain, empty place: nothing to ask
    names = sorted(path.name for path in folder.iterdir())
    assert len(names) == 16
    assert "staff_member-template.csv" in names

    (folder / "staff_member-template.csv").write_text("old", encoding="utf-8")
    fake_prompts.script("choose_folder", folder)
    workflow.write_templates()  # the fake answers "no" to the replacement question
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == "16 existing template files in this folder will be replaced. Continue?"
    assert (folder / "staff_member-template.csv").read_text(encoding="utf-8") == "old"

    fake_prompts.script("choose_folder", folder)
    fake_prompts.script("confirm", True)
    workflow.write_templates()
    assert (folder / "staff_member-template.csv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_the_templates_action_is_on_the_page_and_cancelling_writes_nothing(
    app_context: AppContext, fake_prompts: FakePrompts, qtbot: QtBot, tmp_path: Path
) -> None:
    page = ReportsPage(app_context)
    qtbot.addWidget(page)
    assert page.templates_action.isEnabled()
    assert page.templates_action.text() == "Write templates..."
    page.templates_action.trigger()  # the fake cancels the folder choice
    assert len(fake_prompts.calls_of("choose_folder")) == 1
    assert _infos(fake_prompts) == []


def test_a_template_folder_in_a_risky_place_asks_first(
    fake_prompts: FakePrompts, workflow: ReportsWorkflow, tmp_path: Path
) -> None:
    checks, warning = PLACES["network"]
    workflow.checks = checks
    fake_prompts.script("choose_folder", _out(tmp_path, "templates"))
    workflow.write_templates()
    (question,) = fake_prompts.calls_of("confirm")
    assert question.text == f"{warning} {CLOSING}"
    assert list(_out(tmp_path, "templates").iterdir()) == []


def test_the_import_wizard_warns_about_assets_without_a_status_event(
    app_context: AppContext,
    fake_prompts: FakePrompts,
    workflow: ReportsWorkflow,
    anchor: QWidget,
    qtbot: QtBot,
    tmp_path: Path,
) -> None:
    source = _out(tmp_path) / "asset.csv"
    source.write_text(
        "tag;type_code;description;location;in_service_from;in_service_until;"
        "maintenance_interval_days;notes\r\nDEMO-T1;bay;;;2020-01-01;;;\r\n",
        encoding="utf-8",
    )
    dialog = _import_dialog(app_context, anchor, workflow, qtbot, "asset")
    fake_prompts.script("open_file", source)
    dialog.choose_button.click()

    assert dialog.summary_label.text() == (
        "No problems found: 1 rows can be imported. 1 in-service asset has no status event yet "
        "and counts as in service with an unknown status until its status events are imported."
    )
