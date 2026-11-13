# SPDX-License-Identifier: GPL-3.0-or-later
"""The Reports page and the Reports and Snapshots settings sections (PLAN.md T8.7, A11, P04, P10).

The page offers the PDF report (internal or anonymised), the CSV export, the validation export, the
CSV import wizard and the snapshot list where snapshots are recorded and withdrawn (a withdrawn
snapshot stays stored and is hidden by default; there is no delete action). The report, the CSV
export and the validation export stay available in read-only mode; importing and recording or
withdrawing a snapshot are edit actions. The settings sections hold the small-count threshold
(A11) and the handling notice (P10), and the two snapshot switches (P04), each with the "to be
confirmed" badge of its placeholder. Settings are read and written ONLY through
``context.services.config``.

The module-level factories are what the registries of the shell call; they build without services
and never prompt, open a dialog or touch the database.
"""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.domain.config import (
    MAX_SMALL_COUNT_THRESHOLD,
    MAX_TEXT_LENGTH,
    ReadinessConfig,
)
from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.snapshots import SnapshotOrigin, SnapshotService, SnapshotView
from cbrn_dashboard.ui.budget.labels import fill_placeholders
from cbrn_dashboard.ui.reports.actions import ReportsWorkflow
from cbrn_dashboard.ui.reports.dialogs import (
    ImportDialog,
    ReportDialog,
    ValidationExportDialog,
    open_dialog,
)
from cbrn_dashboard.ui.reports.labels import error_label
from cbrn_dashboard.ui.reports.models import SnapshotsModel
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import format_date
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_change,
    current_language,
    follow_language,
    make_edit_action,
    make_table_view,
)

__all__ = [
    "ReportsPage",
    "ReportsSettingsSection",
    "SnapshotsSettingsSection",
    "create_page",
    "create_reports_section",
    "create_snapshots_section",
    "demo_import_dialog",
    "demo_report_dialog",
    "demo_validation_export_dialog",
    "page_title",
    "reports_section_title",
    "snapshots_section_title",
]


# --------------------------------------------------------------------------- the page


class ReportsPage(QWidget):
    """Reports, exports, import and the snapshot list."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("reports_page")
        self.context = context
        self.workflow = ReportsWorkflow(context, self)
        self.snapshots_model = SnapshotsModel(self)
        self.report_caption = QLabel(self)
        self.report_hint = QLabel(self)
        self.report_hint.setWordWrap(True)
        self.export_caption = QLabel(self)
        self.export_hint = QLabel(self)
        self.export_hint.setWordWrap(True)
        self.import_caption = QLabel(self)
        self.import_hint = QLabel(self)
        self.import_hint.setWordWrap(True)
        self.snapshots_caption = QLabel(self)
        self.show_withdrawn = QCheckBox(self)
        self.show_withdrawn.setObjectName("show_withdrawn")
        self.snapshots_view = make_table_view(self.snapshots_model, self)
        self.snapshots_view.setObjectName("snapshots_view")
        self.snapshots_caption.setBuddy(self.snapshots_view)

        # Not edit actions: a report and the exports only read (they stay available read-only).
        self.report_action = EditAction(
            self, lambda: QCoreApplication.translate("ReportsUi", "Create report...")
        )
        self.report_action.triggered.connect(self.create_report)
        self.csv_action = EditAction(
            self, lambda: QCoreApplication.translate("ReportsUi", "Export CSV files...")
        )
        self.csv_action.triggered.connect(self.export_csv)
        self.validation_action = EditAction(
            self, lambda: QCoreApplication.translate("ReportsUi", "Validation export...")
        )
        self.validation_action.triggered.connect(self.export_validation)
        self.templates_action = EditAction(
            self, lambda: QCoreApplication.translate("ReportsUi", "Write templates...")
        )
        self.templates_action.triggered.connect(self.write_templates)
        # Edit actions: they write to the database.
        self.import_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("ReportsUi", "Import CSV file..."),
            self.open_import,
        )
        self.record_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("ReportsUi", "Record snapshot"),
            self.record_snapshot,
        )
        self.withdraw_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("ReportsUi", "Withdraw snapshot..."),
            self.withdraw_snapshot,
        )
        self._actions: tuple[EditAction, ...] = (
            self.report_action,
            self.csv_action,
            self.validation_action,
            self.templates_action,
            self.import_action,
            self.record_action,
            self.withdraw_action,
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self.report_caption)
        layout.addWidget(self.report_hint)
        layout.addLayout(action_row((self.report_action,), self))
        layout.addWidget(self.export_caption)
        layout.addWidget(self.export_hint)
        layout.addLayout(action_row((self.csv_action, self.validation_action), self))
        layout.addWidget(self.import_caption)
        layout.addWidget(self.import_hint)
        layout.addLayout(action_row((self.import_action, self.templates_action), self))
        header = QHBoxLayout()
        header.addWidget(self.snapshots_caption)
        header.addStretch(1)
        header.addWidget(self.show_withdrawn)
        layout.addLayout(header)
        layout.addWidget(self.snapshots_view, 1)
        layout.addLayout(action_row((self.record_action, self.withdraw_action), self))

        self.show_withdrawn.toggled.connect(lambda _on: self.refresh())
        selection = self.snapshots_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(lambda *_args: self._update_actions())
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        """Re-apply every text of the page in the current language."""
        self.report_caption.setText(QCoreApplication.translate("ReportsUi", "PDF report"))
        self.report_hint.setText(
            QCoreApplication.translate(
                "ReportsUi", "Create the PDF report of the as-of date, internal or anonymised."
            )
        )
        self.export_caption.setText(QCoreApplication.translate("ReportsUi", "Data export"))
        self.export_hint.setText(
            QCoreApplication.translate(
                "ReportsUi", "CSV files and the validation export contain internal data."
            )
        )
        self.import_caption.setText(QCoreApplication.translate("ReportsUi", "Data import"))
        self.import_hint.setText(
            QCoreApplication.translate(
                "ReportsUi", "Check a CSV file first: a file with any error imports nothing."
            )
        )
        self.snapshots_caption.setText(
            QCoreApplication.translate("ReportsUi", "Readiness snapshots")
        )
        self.show_withdrawn.setText(
            QCoreApplication.translate("ReportsUi", "Show withdrawn snapshots")
        )
        for action in self._actions:
            action.retranslate()
        self.snapshots_model.set_language(current_language(self.context))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- data

    def _snapshot_service(self) -> SnapshotService | None:
        return self.context.services.snapshots

    def selected_snapshot(self) -> SnapshotView | None:
        row = self.snapshots_model.selected_row(self.snapshots_view)
        return row if isinstance(row, SnapshotView) else None

    def refresh(self) -> None:
        """Read the snapshot list again (withdrawn ones only when asked for)."""
        service = self._snapshot_service()
        previous = self.selected_snapshot()
        if service is None:
            self.snapshots_model.set_snapshots([])
        else:
            found = service.list_snapshots(include_withdrawn=self.show_withdrawn.isChecked())
            self.snapshots_model.set_snapshots(found)
            if previous is not None:
                for row, snapshot in enumerate(found):
                    if snapshot.id == previous.id:
                        self.snapshots_view.selectRow(row)
        self._update_actions()

    def _update_actions(self) -> None:
        context = self.context
        self.report_action.setEnabled(self.workflow.report_builder() is not None)
        self.csv_action.setEnabled(self.workflow.exporter() is not None)
        self.validation_action.setEnabled(context.services.validation_export is not None)
        self.templates_action.setEnabled(self.workflow.importer() is not None)
        context.set_edit_enabled(self.import_action, self.workflow.importer() is not None)
        service = self._snapshot_service()
        context.set_edit_enabled(self.record_action, service is not None)
        selected = self.selected_snapshot()
        can_withdraw = service is not None and selected is not None and not selected.withdrawn
        context.set_edit_enabled(self.withdraw_action, can_withdraw)

    # ----- the actions

    def create_report(self) -> None:
        """Open the report dialog (non-blocking)."""
        open_dialog(ReportDialog(self.context, self, workflow=self.workflow))

    def export_csv(self) -> None:
        """Choose a folder, warn about internal data and write the CSV files."""
        self.workflow.export_csv()

    def export_validation(self) -> None:
        """Open the validation-export dialog (non-blocking)."""
        open_dialog(ValidationExportDialog(self.context, self, workflow=self.workflow))

    def write_templates(self) -> None:
        """Choose a folder and write the empty CSV templates of every kind of data."""
        self.workflow.write_templates()

    def open_import(self) -> None:
        """Open the import wizard (non-blocking)."""
        open_dialog(ImportDialog(self.context, self, workflow=self.workflow))

    def record_snapshot(self) -> None:
        """Record a snapshot of the as-of date (origin ``manual``; the service may set another)."""
        service = self._snapshot_service()
        if service is None:
            return
        as_of = self.context.as_of
        if as_of < self.context.clock.local_date():  # P8-19: ask first, as the dashboard does
            question = fill_placeholders(
                QCoreApplication.translate("ReportsUi", "Record a retroactive snapshot for %1?"),
                format_date(as_of, current_language(self.context)),
            )
            title = QCoreApplication.translate("ReportsUi", "Record snapshot")
            if not self.context.prompts.confirm(self, title, question):
                return
        apply_change(
            self.context,
            self,
            error_label,
            lambda: service.record(as_of, origin=SnapshotOrigin.MANUAL),
        )

    def withdraw_snapshot(self) -> None:
        """Ask for a reason and withdraw the selected snapshot; it stays stored."""
        service = self._snapshot_service()
        snapshot = self.selected_snapshot()
        if service is None or snapshot is None:
            return
        reason = self.context.prompts.text_input(
            self,
            QCoreApplication.translate("ReportsUi", "Withdraw snapshot"),
            QCoreApplication.translate(
                "ReportsUi", "Reason for withdrawing the snapshot (it stays stored):"
            ),
        )
        if reason is None:
            return
        snapshot_id = snapshot.id
        apply_change(self.context, self, error_label, lambda: service.withdraw(snapshot_id, reason))


# --------------------------------------------------------------------------- settings sections


class _Row:
    """One setting: its editor, placeholder badge and Confirm button."""

    def __init__(self, field: str, editor: QWidget, badge: QLabel, confirm: QPushButton) -> None:
        self.field = field
        self.editor = editor
        self.badge = badge
        self.confirm = confirm
        self.caption: QLabel | None = None
        self.placeholder: str | None = None


class _SettingsSection(QWidget):
    """Shared plumbing of the two settings sections: rows with badges, load, confirm."""

    def __init__(self, context: AppContext, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(name)
        self.context = context
        self._rows: list[_Row] = []
        #: The error code of a configuration that cannot be read (``None`` while it can be).
        self._config_error: str | None = None
        self.config_error_label = QLabel(self)
        self.config_error_label.setObjectName("config_error_label")
        self.config_error_label.setWordWrap(True)
        self.config_error_label.setVisible(False)
        self.save_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("ReportsUi", "Save settings"),
            self.save_settings,
        )

    def _add_row(self, field: str, editor: QWidget, name: str, caption: QLabel | None) -> _Row:
        badge = QLabel(self)
        badge.setObjectName(f"{name}_badge")
        confirm = QPushButton(self)
        confirm.setObjectName(f"{name}_confirm")
        badge.setVisible(False)
        confirm.setVisible(False)
        row = _Row(field, editor, badge, confirm)
        row.caption = caption
        if caption is not None:
            caption.setBuddy(editor)  # the caption names the input (a screen reader, Alt+key)
        for target in (editor, confirm):
            self.context.register_edit_action(target)
        confirm.clicked.connect(lambda: self._confirm(row))
        self._rows.append(row)
        return row

    def _row_layout(self, row: _Row) -> QHBoxLayout:
        line = QHBoxLayout()
        if row.caption is not None:
            line.addWidget(row.caption)
        line.addWidget(row.editor)
        line.addWidget(row.badge)
        line.addWidget(row.confirm)
        line.addStretch(1)
        return line

    def _retranslate_rows(self) -> None:
        badge = QCoreApplication.translate("ReportsUi", "Placeholder - to be confirmed")
        confirm = QCoreApplication.translate("ReportsUi", "Confirm")
        for row in self._rows:
            row.badge.setText(badge)
            row.confirm.setText(confirm)
        self.save_action.retranslate()
        self._show_config_error()

    def _show_config_error(self) -> None:
        """Show why the settings inputs are off (a configuration that cannot be read)."""
        code = self._config_error
        self.config_error_label.setVisible(code is not None)
        self.config_error_label.setText("" if code is None else error_label(code))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def retranslate(self) -> None:
        raise NotImplementedError

    def save_settings(self) -> None:
        raise NotImplementedError

    def _show_values(self, stored: ReadinessConfig) -> None:
        raise NotImplementedError

    def _config(self) -> ConfigService | None:
        found: object = getattr(self.context.services, "config", None)
        return found if isinstance(found, ConfigService) else None

    def refresh(self) -> None:
        """Show the stored settings with their badges."""
        config = self._config()
        stored = ReadinessConfig()
        self._config_error = None
        if config is not None:
            try:
                stored = config.load()
            except ServiceError as error:
                self._config_error = error.code
                config = None
        self._show_config_error()
        self._show_values(stored)
        for row in self._rows:
            row.placeholder = None
            if config is not None:
                try:
                    row.placeholder = config.badge_for_field(row.field)
                except ServiceError:
                    row.placeholder = None
            row.badge.setVisible(row.placeholder is not None)
            row.confirm.setVisible(row.placeholder is not None)
            self.context.set_edit_enabled(row.editor, config is not None)
            self.context.set_edit_enabled(row.confirm, config is not None)
        self.context.set_edit_enabled(self.save_action, config is not None)

    def _confirm(self, row: _Row) -> None:
        config = self._config()
        placeholder = row.placeholder
        if config is None or placeholder is None:
            return
        apply_change(self.context, self, error_label, lambda: config.confirm(placeholder))


class ReportsSettingsSection(_SettingsSection):
    """Settings -> Reports: the small-count threshold (A11) and the handling notice (P10)."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, "reports_section", parent)
        self.threshold_spin = QSpinBox(self)
        self.threshold_spin.setObjectName("threshold_spin")
        self.threshold_spin.setRange(1, MAX_SMALL_COUNT_THRESHOLD)
        self.notice_edit = QLineEdit(self)
        self.notice_edit.setObjectName("notice_edit")
        self.notice_edit.setMaxLength(MAX_TEXT_LENGTH)
        self.threshold_row = self._add_row(
            "small_count_threshold", self.threshold_spin, "threshold", QLabel(self)
        )
        self.notice_row = self._add_row(
            "report_handling_notice", self.notice_edit, "notice", QLabel(self)
        )
        self.notice_hint = QLabel(self)
        self.notice_hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self.config_error_label)
        layout.addLayout(self._row_layout(self.threshold_row))
        layout.addLayout(self._row_layout(self.notice_row))
        layout.addWidget(self.notice_hint)
        layout.addLayout(action_row((self.save_action,), self))
        layout.addStretch(1)

        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        if self.threshold_row.caption is not None:
            self.threshold_row.caption.setText(
                QCoreApplication.translate(
                    "ReportsUi", "Small-count threshold (smaller counts are hidden)"
                )
            )
        if self.notice_row.caption is not None:
            self.notice_row.caption.setText(
                QCoreApplication.translate(
                    "ReportsUi", "Handling notice printed on the internal report"
                )
            )
        self.notice_hint.setText(
            QCoreApplication.translate(
                "ReportsUi", "The notice stays on this computer and is empty by default."
            )
        )
        self._retranslate_rows()

    def _show_values(self, stored: ReadinessConfig) -> None:
        self.threshold_spin.setValue(stored.small_count_threshold)
        self.notice_edit.setText(stored.report_handling_notice)

    def save_settings(self) -> None:
        """Store the threshold and the notice; a refused value is shown and the old ones return."""
        config = self._config()
        if config is None:
            return
        threshold = self.threshold_spin.value()
        notice = self.notice_edit.text()

        def save() -> object:
            return config.save(
                config.load().with_changes(
                    small_count_threshold=threshold, report_handling_notice=notice
                )
            )

        if not apply_change(self.context, self, error_label, save):
            self.refresh()


class SnapshotsSettingsSection(_SettingsSection):
    """Settings -> Snapshots: the monthly snapshot and the snapshot-with-a-report default (P04)."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, "snapshots_section", parent)
        self.monthly_check = QCheckBox(self)
        self.monthly_check.setObjectName("monthly_check")
        self.on_report_check = QCheckBox(self)
        self.on_report_check.setObjectName("on_report_check")
        self.monthly_row = self._add_row("snapshot_monthly", self.monthly_check, "monthly", None)
        self.on_report_row = self._add_row(
            "snapshot_on_report", self.on_report_check, "on_report", None
        )

        layout = QVBoxLayout(self)
        layout.addWidget(self.config_error_label)
        layout.addLayout(self._row_layout(self.monthly_row))
        layout.addLayout(self._row_layout(self.on_report_row))
        layout.addLayout(action_row((self.save_action,), self))
        layout.addStretch(1)

        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        self.monthly_check.setText(
            QCoreApplication.translate(
                "ReportsUi", "Record a snapshot at the first start of each month"
            )
        )
        self.on_report_check.setText(
            QCoreApplication.translate(
                "ReportsUi", "Tick the snapshot option by default when creating a report"
            )
        )
        self._retranslate_rows()

    def _show_values(self, stored: ReadinessConfig) -> None:
        self.monthly_check.setChecked(stored.snapshot_monthly)
        self.on_report_check.setChecked(stored.snapshot_on_report)

    def save_settings(self) -> None:
        config = self._config()
        if config is None:
            return
        monthly = self.monthly_check.isChecked()
        on_report = self.on_report_check.isChecked()

        def save() -> object:
            return config.save(
                config.load().with_changes(snapshot_monthly=monthly, snapshot_on_report=on_report)
            )

        if not apply_change(self.context, self, error_label, save):
            self.refresh()


# --------------------------------------------------------------------------- registry factories


def page_title() -> str:
    return QCoreApplication.translate("ReportsUi", "Reports")


def create_page(context: AppContext) -> QWidget:
    return ReportsPage(context)


def reports_section_title() -> str:
    return QCoreApplication.translate("ReportsUi", "Reports and anonymisation")


def create_reports_section(context: AppContext) -> QWidget:
    return ReportsSettingsSection(context)


def snapshots_section_title() -> str:
    return QCoreApplication.translate("ReportsUi", "Readiness snapshots")


def create_snapshots_section(context: AppContext) -> QWidget:
    return SnapshotsSettingsSection(context)


def demo_report_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """The report dialog with its defaults; it writes nothing until an output file is chosen."""
    return ReportDialog(context, parent)


def demo_validation_export_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """The validation-export dialog; it writes nothing until a folder is chosen."""
    return ValidationExportDialog(context, parent)


def demo_import_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """The import wizard; it imports nothing until a file is chosen."""
    return ImportDialog(context, parent)
