# SPDX-License-Identifier: GPL-3.0-or-later
"""The report dialog, the validation-export dialog and the import wizard (PLAN.md T8.7).

* :class:`ReportDialog` - variant, language, as-of date and output file of a PDF report, with the
  "record a snapshot" option (P04, ticked by default; a past as-of date records a ``retroactive``
  snapshot and the dialog says so). The anonymised variant is labelled as such.
* :class:`ValidationExportDialog` - the validation export (T8.2), labelled as internal data, with
  the suppression option and the retroactive-reading option for editions without an earlier
  snapshot (recording is an edit action).
* :class:`ImportDialog` - the import wizard: the kind of data and the file, the dry-run preview
  with its per-row errors, then the confirmation. A file with any error writes nothing.

Every file choice and every message goes through ``context.prompts`` (through the shared
:class:`~cbrn_dashboard.ui.reports.actions.ReportsWorkflow`); the dialogs are opened without
blocking. The dialogs build without services and never prompt or write at construction.
"""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.i18n import LANGUAGES
from cbrn_dashboard.reports.model import ReportVariant
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.importer import ImportReport
from cbrn_dashboard.services.snapshots import SnapshotOrigin
from cbrn_dashboard.services.validation_export import (
    ValidationExportError,
    ValidationExportResult,
)
from cbrn_dashboard.storage import csv_io
from cbrn_dashboard.ui.budget.labels import fill_placeholders
from cbrn_dashboard.ui.reports.actions import ReportsWorkflow
from cbrn_dashboard.ui.reports.labels import (
    NO_FILE_CHOSEN,
    NO_OUTPUT_CHOSEN,
    entity_label,
    error_label,
    variant_label,
)
from cbrn_dashboard.ui.reports.models import IssuesModel
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import apply_locale, format_number, from_qdate, to_qdate
from cbrn_dashboard.ui.shell.i18n import language_display_name
from cbrn_dashboard.ui.shell.widgets import (
    FormDialog,
    current_language,
    guarded,
    make_table_view,
    mark_data,
)

__all__ = ["ImportDialog", "ReportDialog", "ValidationExportDialog", "open_dialog"]


def open_dialog(dialog: QDialog) -> None:
    """Show ``dialog`` window-modally without blocking; it deletes itself when closed."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


def _row_of(first: QWidget, second: QWidget, parent: QWidget) -> QWidget:
    """Two widgets side by side (a text field and its "Choose..." button)."""
    box = QWidget(parent)
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(first, 1)
    layout.addWidget(second)
    return box


def _threshold(context: AppContext) -> int:
    """The small-count threshold of the configuration (A11); the default without one."""
    default = ReadinessConfig().small_count_threshold
    config = context.services.config
    if config is None:
        return default
    try:
        return config.load().small_count_threshold
    except ServiceError:
        return default


# --------------------------------------------------------------------------- the report


class ReportDialog(FormDialog):
    """Choose the variant, language, as-of date and output file, then write the PDF report."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        *,
        workflow: ReportsWorkflow | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("report_dialog")
        self.workflow = ReportsWorkflow(context, self) if workflow is None else workflow
        today = context.clock.local_date()
        self.variant_combo = QComboBox(self)
        self.variant_combo.setObjectName("variant_combo")
        for variant in ReportVariant:
            self.variant_combo.addItem("", variant.value)
        self.language_combo = QComboBox(self)
        self.language_combo.setObjectName("language_combo")
        for code in LANGUAGES:
            self.language_combo.addItem("", code)
        self.language_combo.setCurrentIndex(
            max(self.language_combo.findData(current_language(context)), 0)
        )
        self.date_edit = QDateEdit(to_qdate(min(context.as_of, today)), self)
        self.date_edit.setObjectName("report_date_edit")
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setMaximumDate(to_qdate(today))
        self.path_edit = QLineEdit(self)
        self.path_edit.setObjectName("report_path_edit")
        self.choose_button = QPushButton(self)
        self.choose_button.setObjectName("report_choose_button")
        self.snapshot_check = QCheckBox(self)
        self.snapshot_check.setObjectName("snapshot_check")
        context.register_edit_action(self.snapshot_check)
        self.variant_note = QLabel(self)
        self.variant_note.setObjectName("variant_note")
        self.variant_note.setWordWrap(True)
        self.snapshot_note = QLabel(self)
        self.snapshot_note.setObjectName("snapshot_note")
        self.snapshot_note.setWordWrap(True)

        self.add_field(
            lambda: QCoreApplication.translate("ReportsUi", "Report"), self.variant_combo
        )
        self.add_field(
            lambda: QCoreApplication.translate("ReportsUi", "Language"), self.language_combo
        )
        self.add_field(lambda: QCoreApplication.translate("ReportsUi", "As of"), self.date_edit)
        self.add_field(
            lambda: QCoreApplication.translate("ReportsUi", "Output file"),
            _row_of(self.path_edit, self.choose_button, self),
        )
        self.form.addRow(self.variant_note)
        self.form.addRow(self.snapshot_check)
        self.form.addRow(self.snapshot_note)

        self.choose_button.clicked.connect(lambda: self.choose_path())
        self._suggested: Path | None = None
        self.variant_combo.currentIndexChanged.connect(lambda _index: self._choice_changed())
        self.date_edit.dateChanged.connect(lambda _day: self._choice_changed())
        self.snapshot_check.toggled.connect(lambda _on: self._update_notes())
        self._load_defaults()
        self.retranslate()

    # ----- state

    def _load_defaults(self) -> None:
        """Tick the snapshot option from P04, and never in read-only mode."""
        ticked = ReadinessConfig().snapshot_on_report
        config = self.context.services.config
        if config is not None:
            try:
                ticked = config.load().snapshot_on_report
            except ServiceError:
                ticked = True
        self.snapshot_check.setChecked(ticked and not self.context.read_only)

    def variant(self) -> ReportVariant:
        return ReportVariant(str(self.variant_combo.currentData()))

    def report_language(self) -> str:
        return str(self.language_combo.currentData())

    def as_of(self) -> date:
        return from_qdate(self.date_edit.date())

    def _is_past(self) -> bool:
        return self.as_of() < self.context.clock.local_date()

    # ----- texts

    def retranslate(self) -> None:
        super().retranslate()
        self.setWindowTitle(QCoreApplication.translate("ReportsUi", "Create report"))
        for index in range(self.variant_combo.count()):
            variant = str(self.variant_combo.itemData(index))
            self.variant_combo.setItemText(index, variant_label(variant))
        for index in range(self.language_combo.count()):
            code = str(self.language_combo.itemData(index))
            self.language_combo.setItemText(index, language_display_name(code))
        self.choose_button.setText(QCoreApplication.translate("ReportsUi", "Choose file..."))
        self.snapshot_check.setText(
            QCoreApplication.translate(
                "ReportsUi", "Record a snapshot of the readings together with the report"
            )
        )
        apply_locale(self.date_edit, self.language)
        self._update_notes()

    def _update_notes(self) -> None:
        if self.variant() is ReportVariant.ANONYMISED:
            text = QCoreApplication.translate(
                "ReportsUi", "Anonymised report: staff identifiers, labels and notes are left out."
            )
            text += " " + fill_placeholders(
                QCoreApplication.translate(
                    "ReportsUi", "Personnel counts below %1 are shown as '< %1'."
                ),
                format_number(_threshold(self.context), self.language, decimals=0),
            )
        else:
            text = QCoreApplication.translate(
                "ReportsUi",
                "Internal report: it lists staff identifiers. Handle it as internal data.",
            )
        self.variant_note.setText(text)
        self.snapshot_note.setText(
            QCoreApplication.translate(
                "ReportsUi", "A snapshot recorded for a past date is stored as retroactive."
            )
        )
        self.snapshot_note.setVisible(self.snapshot_check.isChecked() and self._is_past())

    # ----- the output file

    def choose_path(self) -> None:
        """Ask for the output file through the prompts interface and show it."""
        title = QCoreApplication.translate("ReportsUi", "Create report")
        file_filter = QCoreApplication.translate("ReportsUi", "PDF report (*.pdf)")
        name = self.workflow.default_report_name(self.variant(), self.as_of())
        chosen = self.context.prompts.save_file(self, title, name, file_filter)
        if chosen is not None:
            self.path_edit.setText(str(chosen))
            self._suggested = chosen if chosen.name == name else None

    def _resuggest(self) -> None:
        """While the path is still the suggested one, follow a change of variant or date (P8-02)."""
        suggested = self._suggested
        if suggested is None or self.path_edit.text().strip() != str(suggested):
            return
        name = self.workflow.default_report_name(self.variant(), self.as_of())
        renamed = suggested.with_name(name)
        self._suggested = renamed
        self.path_edit.setText(str(renamed))

    def _choice_changed(self) -> None:
        self._resuggest()
        self._update_notes()

    # ----- the report

    def _name_contradicts_variant(self, target: Path) -> bool:
        """Whether the file name carries the marker of the OTHER variant (P8-02)."""
        other = (
            ReportVariant.ANONYMISED
            if self.variant() is ReportVariant.INTERNAL
            else ReportVariant.INTERNAL
        )
        return other.value.lower() in target.name.lower()

    def submit(self) -> bool:
        title = QCoreApplication.translate("ReportsUi", "Create report")
        text = self.path_edit.text().strip()
        if text and self._name_contradicts_variant(Path(text)):
            other = (
                ReportVariant.ANONYMISED
                if self.variant() is ReportVariant.INTERNAL
                else ReportVariant.INTERNAL
            )
            self.context.prompts.warning(
                self,
                title,
                fill_placeholders(
                    QCoreApplication.translate(
                        "ReportsUi",
                        "The file name belongs to another kind of report (%1), but the chosen "
                        "report is: %2. Change the file name or the report.",
                    ),
                    variant_label(other.value),
                    variant_label(self.variant().value),
                ),
            )
            return False
        if self.workflow.report_builder() is None:
            return False
        if not text:
            self.context.prompts.warning(self, title, error_label(NO_OUTPUT_CHOSEN))
            return False
        target = Path(text)
        if target.suffix.lower() != ".pdf":
            target = target.with_name(target.name + ".pdf")
        if not self.workflow.confirm_destination(target.parent, title, None):
            return False
        variant, as_of = self.variant(), self.as_of()
        if not self.workflow.write_report(as_of, variant, self.report_language(), target):
            return False
        if variant is ReportVariant.ANONYMISED:
            done = QCoreApplication.translate(
                "ReportsUi", "The anonymised report was written to %1."
            )
        else:
            done = QCoreApplication.translate("ReportsUi", "The internal report was written to %1.")
        done = fill_placeholders(done, str(target))
        done += self._record_snapshot(as_of)
        self.context.prompts.info(self, title, done)
        return True

    def _record_snapshot(self, as_of: date) -> str:
        """Record the snapshot when ticked; the sentence that says what happened (or nothing)."""
        service = self.context.services.snapshots
        if service is None or self.context.read_only or not self.snapshot_check.isChecked():
            return ""
        view = guarded(
            self.context,
            self,
            error_label,
            lambda: service.record(as_of, origin=SnapshotOrigin.REPORT),
        )
        if view is None:
            return ""
        self.context.notify_data_changed()
        if view.origin is SnapshotOrigin.RETROACTIVE:
            return " " + QCoreApplication.translate(
                "ReportsUi",
                "A snapshot was recorded, marked as retroactive because the date is in the past.",
            )
        return " " + QCoreApplication.translate(
            "ReportsUi", "A snapshot of the readings was recorded."
        )


# --------------------------------------------------------------------------- validation export


class ValidationExportDialog(FormDialog):
    """Write the validation export (T8.2) into a folder; internal data, with the A11 option."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        *,
        workflow: ReportsWorkflow | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("validation_export_dialog")
        self.workflow = ReportsWorkflow(context, self) if workflow is None else workflow
        self._missing: list[str] = []
        self.folder_edit = QLineEdit(self)
        self.folder_edit.setObjectName("validation_folder_edit")
        self.choose_button = QPushButton(self)
        self.choose_button.setObjectName("validation_choose_button")
        self.suppress_check = QCheckBox(self)
        self.suppress_check.setObjectName("suppress_check")
        self.retro_check = QCheckBox(self)
        self.retro_check.setObjectName("retro_check")
        context.register_edit_action(self.retro_check)
        self.notice_label = QLabel(self)
        self.notice_label.setObjectName("validation_notice")
        self.notice_label.setWordWrap(True)
        self.editions_label = QLabel(self)
        self.editions_label.setObjectName("editions_label")
        self.editions_label.setWordWrap(True)

        self.add_field(
            lambda: QCoreApplication.translate("ReportsUi", "Folder"),
            _row_of(self.folder_edit, self.choose_button, self),
        )
        self.form.addRow(self.notice_label)
        self.form.addRow(self.suppress_check)
        self.form.addRow(self.editions_label)
        self.form.addRow(self.retro_check)

        self.choose_button.clicked.connect(lambda: self.choose_folder())
        self.suppress_check.toggled.connect(lambda _on: self.retranslate())
        self.refresh()
        self.retranslate()

    def refresh(self) -> None:
        """Read the editions that have no earlier snapshot (the retroactive option is for them)."""
        service = self.context.services.validation_export
        self._missing = [] if service is None else service.editions_without_prior_snapshot()
        self.context.set_edit_enabled(self.retro_check, bool(self._missing))
        if not self._missing:
            self.retro_check.setChecked(False)

    def retranslate(self) -> None:
        super().retranslate()
        self.setWindowTitle(QCoreApplication.translate("ReportsUi", "Validation export"))
        self.choose_button.setText(QCoreApplication.translate("ReportsUi", "Choose folder..."))
        self.suppress_check.setText(
            QCoreApplication.translate(
                "ReportsUi", "Suppress small personnel counts as in the anonymised report"
            )
        )
        self.retro_check.setText(
            QCoreApplication.translate(
                "ReportsUi", "Record a retroactive reading for the editions without a snapshot"
            )
        )
        if self.suppress_check.isChecked():
            notice = fill_placeholders(
                QCoreApplication.translate(
                    "ReportsUi",
                    "Counts below %1 are replaced by '< %1'. The files are still internal data.",
                ),
                format_number(_threshold(self.context), self.language, decimals=0),
            )
        else:
            notice = QCoreApplication.translate(
                "ReportsUi",
                "These files are unsuppressed internal data: they hold the exact counts.",
            )
        self.notice_label.setText(notice)
        if self._missing:
            listing = fill_placeholders(
                QCoreApplication.translate("ReportsUi", "Editions without an earlier snapshot: %1"),
                ", ".join(self._missing),
            )
        else:
            listing = QCoreApplication.translate(
                "ReportsUi", "Every edition has an earlier snapshot."
            )
        self.editions_label.setText(listing)

    def choose_folder(self) -> None:
        """Ask for the output folder through the prompts interface and show it."""
        title = QCoreApplication.translate("ReportsUi", "Validation export")
        chosen = self.context.prompts.choose_folder(self, title)
        if chosen is not None:
            self.folder_edit.setText(str(chosen))

    def submit(self) -> bool:
        service = self.context.services.validation_export
        if service is None:
            return False
        title = QCoreApplication.translate("ReportsUi", "Validation export")
        text = self.folder_edit.text().strip()
        if not text:
            self.context.prompts.warning(self, title, error_label(NO_OUTPUT_CHOSEN))
            return False
        folder = Path(text)
        if not self.workflow.confirm_destination(folder, title, None):
            return False
        suppress = self.suppress_check.isChecked()
        retroactive = self.retro_check.isChecked() and self.retro_check.isEnabled()
        failures: list[ValidationExportError] = []

        def run() -> ValidationExportResult:
            try:
                return service.export(
                    folder, suppress_small_counts=suppress, record_retroactive=retroactive
                )
            except ValidationExportError as error:
                failures.append(error)
                raise

        result = guarded(self.context, self, error_label, run)
        if result is None:
            if failures and failures[0].recorded_snapshot_ids:
                # P8-08: the snapshots recorded for the failed export stay; say which, refresh
                self.context.notify_data_changed()
                numbers = ", ".join(
                    format_number(number, self.language, decimals=0)
                    for number in failures[0].recorded_snapshot_ids
                )
                self.context.prompts.warning(
                    self,
                    title,
                    fill_placeholders(
                        QCoreApplication.translate(
                            "ReportsUi",
                            "Retroactive snapshots were recorded before the export failed "
                            "(snapshot numbers: %1). They stay stored; withdraw them in the "
                            "snapshot list if they are not wanted.",
                        ),
                        numbers,
                    ),
                )
            return False
        done = fill_placeholders(
            QCoreApplication.translate("ReportsUi", "The validation export was written to %1."),
            str(folder),
        )
        if result.recorded_snapshot_ids:
            done += " " + fill_placeholders(
                QCoreApplication.translate("ReportsUi", "Retroactive snapshots recorded: %1."),
                format_number(len(result.recorded_snapshot_ids), self.language, decimals=0),
            )
            self.context.notify_data_changed()
        if result.editions_without_reading:
            done += " " + fill_placeholders(
                QCoreApplication.translate("ReportsUi", "Editions without a reading: %1."),
                ", ".join(result.editions_without_reading),
            )
        self.context.prompts.info(self, title, done)
        return True


# --------------------------------------------------------------------------- import wizard


class ImportDialog(FormDialog):
    """Choose the kind of data and the file, see the dry-run preview, confirm the import."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        *,
        workflow: ReportsWorkflow | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("import_dialog")
        self.workflow = ReportsWorkflow(context, self) if workflow is None else workflow
        self._file: Path | None = None
        self._report: ImportReport | None = None
        self.entity_combo = QComboBox(self)
        self.entity_combo.setObjectName("entity_combo")
        for spec in csv_io.ENTITIES:
            self.entity_combo.addItem("", spec.name)
        self.file_label = QLabel(self)
        self.file_label.setObjectName("import_file_label")
        mark_data(self.file_label)  # a file name is data
        self.choose_button = QPushButton(self)
        self.choose_button.setObjectName("import_choose_button")
        context.register_edit_action(self.choose_button)
        self.summary_label = QLabel(self)
        self.summary_label.setObjectName("import_summary")
        self.summary_label.setWordWrap(True)
        self.issues_model = IssuesModel(self)
        self.issues_view = make_table_view(self.issues_model, self)
        self.issues_view.setObjectName("issues_view")
        ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            context.register_edit_action(ok_button)

        self.add_field(
            lambda: QCoreApplication.translate("ReportsUi", "Kind of data"), self.entity_combo
        )
        self.add_field(
            lambda: QCoreApplication.translate("ReportsUi", "File"),
            _row_of(self.file_label, self.choose_button, self),
        )
        self.form.addRow(self.summary_label)
        self.form.addRow(self.issues_view)

        self.choose_button.clicked.connect(lambda: self.choose_file())
        self.entity_combo.currentIndexChanged.connect(lambda _index: self.check())
        self.retranslate()

    # ----- state

    def entity(self) -> str:
        return str(self.entity_combo.currentData())

    def chosen_file(self) -> Path | None:
        return self._file

    def report(self) -> ImportReport | None:
        """The result of the last check of the chosen file (``None`` before any)."""
        return self._report

    # ----- texts

    def retranslate(self) -> None:
        super().retranslate()
        self.setWindowTitle(QCoreApplication.translate("ReportsUi", "Import CSV file"))
        for index in range(self.entity_combo.count()):
            name = str(self.entity_combo.itemData(index))
            self.entity_combo.setItemText(index, entity_label(name))
        self.choose_button.setText(QCoreApplication.translate("ReportsUi", "Choose file..."))
        self.issues_view.setAccessibleName(
            QCoreApplication.translate("ReportsUi", "Problems found in the file")
        )
        self.issues_model.set_language(self.language)
        self._show_summary()

    def _show_summary(self) -> None:
        report = self._report
        if report is None:
            text = QCoreApplication.translate(
                "ReportsUi", "Choose a file to check it before anything is imported."
            )
        elif report.ok:
            text = fill_placeholders(
                QCoreApplication.translate(
                    "ReportsUi", "No problems found: %1 rows can be imported."
                ),
                format_number(report.total_rows, self.language, decimals=0),
            )
        else:
            text = fill_placeholders(
                QCoreApplication.translate(
                    "ReportsUi",
                    "%1 problems found in %2 rows. Nothing is imported until they are fixed.",
                ),
                format_number(len(report.errors), self.language, decimals=0),
                format_number(report.total_rows, self.language, decimals=0),
            )
        if report is not None and report.assets_without_status_event:
            text += " " + QCoreApplication.translate(
                "ReportsUi",
                "%n in-service asset(s) have no status event yet and count as in service with "
                "an unknown status until their status events are imported.",
                None,
                report.assets_without_status_event,
            )
        if report is not None and report.lots_without_movements:
            text += " " + QCoreApplication.translate(
                "ReportsUi",
                "%n lot(s) have no movement yet and show no stock until their movements are "
                "imported.",
                None,
                report.lots_without_movements,
            )
        self.summary_label.setText(text)

    # ----- the file

    def choose_file(self) -> None:
        """Ask for the CSV file through the prompts interface, then check it (a dry run)."""
        title = QCoreApplication.translate("ReportsUi", "Import CSV file")
        file_filter = QCoreApplication.translate("ReportsUi", "CSV files (*.csv)")
        chosen = self.context.prompts.open_file(self, title, file_filter)
        if chosen is None:
            return
        self._file = chosen
        self.file_label.setText(chosen.name)
        self.check()

    def check(self) -> ImportReport | None:
        """Dry-run the chosen file: show every error with line, column and code; write nothing."""
        service = self.workflow.importer()
        path = self._file
        if service is None or path is None:
            return None
        entity = self.entity()
        report = guarded(self.context, self, error_label, lambda: service.dry_run(entity, path))
        self._report = report
        self.issues_model.set_issues(() if report is None else report.errors)
        self._show_summary()
        return report

    # ----- the import

    def submit(self) -> bool:
        service = self.workflow.importer()
        if service is None:
            return False
        title = QCoreApplication.translate("ReportsUi", "Import CSV file")
        path = self._file
        if path is None:
            self.context.prompts.warning(self, title, error_label(NO_FILE_CHOSEN))
            return False
        entity = self.entity()
        problems = QCoreApplication.translate(
            "ReportsUi", "The file has problems. Nothing was imported."
        )
        checked = self.check()  # the file may have changed since it was chosen
        if checked is None:
            return False
        if not checked.ok:
            self.context.prompts.warning(self, title, problems)
            return False
        question = fill_placeholders(
            QCoreApplication.translate("ReportsUi", "Import %1 rows of %2?"),
            format_number(checked.total_rows, self.language, decimals=0),
            entity_label(entity),
        )
        if not self.context.prompts.confirm(self, title, question):
            return False
        report = guarded(self.context, self, error_label, lambda: service.import_file(entity, path))
        if report is None:
            return False
        self._report = report
        self.issues_model.set_issues(report.errors)
        self._show_summary()
        if not report.ok:
            self.context.prompts.warning(self, title, problems)
            return False
        if report.imported:
            self.context.notify_data_changed()
        done = fill_placeholders(
            QCoreApplication.translate("ReportsUi", "%1 rows of %2 were imported."),
            format_number(report.imported, self.language, decimals=0),
            entity_label(entity),
        )
        self.context.prompts.info(self, title, done)
        return True
