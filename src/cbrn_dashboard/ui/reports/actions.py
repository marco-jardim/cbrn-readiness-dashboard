# SPDX-License-Identifier: GPL-3.0-or-later
"""What the reports page and its dialogs share: the services, the output-place check, CSV export.

:class:`ReportsWorkflow` finds (or lazily builds over ``context.conn``) the report builder, the CSV
exporter and the CSV importer, warns about output places (K03, T0.5) and runs the CSV export. Every
file choice and every message goes through ``context.prompts``. Nothing is written anywhere but
the file or folder the user chose.

The services come from ``context.services.report_builder`` / ``.exporter`` / ``.importer`` when the
context has them, otherwise they are built here from the services the context does have. Without an
open database every getter returns ``None`` and every flow does nothing.
"""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject
from PySide6.QtWidgets import QWidget

from cbrn_dashboard.reports.model import ReportBuilder, ReportVariant
from cbrn_dashboard.reports.pdf import write_report_pdf
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.export import EXPORT_FAILED, ExportService
from cbrn_dashboard.services.importer import ImportService
from cbrn_dashboard.storage import csv_io
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.ui.backup.actions import DestinationChecks
from cbrn_dashboard.ui.budget.labels import fill_placeholders
from cbrn_dashboard.ui.reports.labels import error_label
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.widgets import guarded

__all__ = ["DestinationChecks", "ReportsWorkflow"]


class ReportsWorkflow(QObject):
    """The services and the flows that the page, the dialogs and the tests share."""

    def __init__(self, context: AppContext, anchor: QWidget | None = None) -> None:
        super().__init__(anchor)
        self.context = context
        self.anchor = anchor
        #: Probes for the place of an output file or folder; tests inject their own.
        self.checks: DestinationChecks = DestinationChecks.system()
        #: Folder of the compiled catalogues the PDF renderer loads (``None``: the package's own).
        self.qm_dir: Path | None = None
        self._conn: DatabaseConnection | None = None
        self._builder: ReportBuilder | None = None
        self._exporter: ExportService | None = None
        self._importer: ImportService | None = None

    # ----- the services

    def _fresh(self) -> DatabaseConnection | None:
        """The open connection; the services built here are dropped when it changed."""
        conn = self.context.conn
        if conn is not self._conn:
            self._conn = conn
            self._builder = None
            self._exporter = None
            self._importer = None
        return conn

    def report_builder(self) -> ReportBuilder | None:
        """The report builder of the context, or one built over its services; ``None`` without."""
        found: object = getattr(self.context.services, "report_builder", None)
        if isinstance(found, ReportBuilder):
            return found
        conn = self._fresh()
        services = self.context.services
        dashboard = services.dashboard
        personnel = services.personnel
        infrastructure = services.infrastructure
        config = services.config
        if (
            conn is None
            or dashboard is None
            or personnel is None
            or infrastructure is None
            or config is None
        ):
            return None
        if self._builder is None:
            self._builder = ReportBuilder(
                conn=conn,
                clock=self.context.clock,
                dashboard=dashboard,
                personnel=personnel,
                infrastructure=infrastructure,
                config_loader=config.load,
                budget=services.budget,
            )
        return self._builder

    def exporter(self) -> ExportService | None:
        """The CSV exporter of the context, or one built over its connection."""
        found: object = getattr(self.context.services, "exporter", None)
        if isinstance(found, ExportService):
            return found
        conn = self._fresh()
        if conn is None:
            return None
        if self._exporter is None:
            self._exporter = ExportService(conn, self.context.clock)
        return self._exporter

    def importer(self) -> ImportService | None:
        """The CSV importer of the context, or one built over its module services."""
        found: object = getattr(self.context.services, "importer", None)
        if isinstance(found, ImportService):
            return found
        conn = self._fresh()
        services = self.context.services
        personnel = services.personnel
        infrastructure = services.infrastructure
        exercises: ExercisesService | None = services.exercises
        budget = services.budget
        if (
            conn is None
            or personnel is None
            or infrastructure is None
            or exercises is None
            or budget is None
        ):
            return None
        if self._importer is None:
            self._importer = ImportService(
                conn,
                self.context.clock,
                self.context.operator_label,
                personnel=personnel,
                infrastructure=infrastructure,
                exercises=exercises,
                budget=budget,
            )
        return self._importer

    # ----- names

    def default_report_name(self, variant: ReportVariant, as_of: date) -> str:
        """``cbrn-report-<variant>-<as-of>.pdf`` (``DEMO-`` first for demonstration data)."""
        prefix = "DEMO-" if self.context.is_demo else ""
        return f"{prefix}cbrn-report-{variant.value.lower()}-{as_of.isoformat()}.pdf"

    # ----- the output place

    def place_notes(self, folder: Path) -> list[str]:
        """The translated warnings about the place of ``folder`` (empty when it is a plain one)."""
        notes: list[str] = []
        if self.checks.network_drive(folder):
            notes.append(
                QCoreApplication.translate(
                    "ReportsUi", "The chosen location is on a network drive."
                )
            )
        if self.checks.cloud_sync(folder):
            notes.append(
                QCoreApplication.translate(
                    "ReportsUi", "The chosen location is synchronised with a cloud service."
                )
            )
        if self.checks.removable(folder):
            notes.append(
                QCoreApplication.translate(
                    "ReportsUi", "The chosen location is on removable media."
                )
            )
        return notes

    def confirm_destination(self, folder: Path, title: str, notice: str | None) -> bool:
        """Warn about the place (and about ``notice``, when given); ``True`` to go on.

        Nothing is asked when the place is a plain one and there is no notice.
        """
        notes = self.place_notes(folder)
        if notice is not None:
            notes.insert(0, notice)
        if not notes:
            return True
        notes.append(
            QCoreApplication.translate(
                "ReportsUi",
                "Files written there are no longer protected by this program. Continue anyway?",
            )
        )
        return self.context.prompts.confirm(self.anchor, title, " ".join(notes))

    # ----- the PDF report

    def write_report(
        self, as_of: date, variant: ReportVariant, language: str, target: Path
    ) -> bool:
        """Build the report and write the PDF; ``False`` (the error shown) when it failed."""
        builder = self.report_builder()
        if builder is None:
            return False

        def run() -> bool:
            document = builder.build(as_of, variant)
            write_report_pdf(document, target, language=language, qm_dir=self.qm_dir)
            return True

        return guarded(self.context, self.anchor, error_label, run) is True

    # ----- the import templates

    def write_templates(self) -> None:
        """Choose a folder and write the header-only template of every entity (P8-10)."""
        service = self.importer()
        if service is None:
            return
        title = QCoreApplication.translate("ReportsUi", "Write import templates")
        folder = self.context.prompts.choose_folder(self.anchor, title)
        if folder is None or not self.confirm_destination(folder, title, None):
            return
        existing = [
            name
            for name in (csv_io.template_file_name(spec) for spec in csv_io.ENTITIES)
            if (folder / name).exists()
        ]
        if existing:
            question = QCoreApplication.translate(
                "ReportsUi",
                "%n existing template file(s) in this folder will be replaced. Continue?",
                None,
                len(existing),
            )
            if not self.context.prompts.confirm(self.anchor, title, question):
                return

        def run() -> list[Path]:
            try:
                return service.write_all_templates(folder)
            except ServiceError:
                raise ServiceError(EXPORT_FAILED, "out_dir") from None

        written = guarded(self.context, self.anchor, error_label, run)
        if written is None:
            return
        text = QCoreApplication.translate(
            "ReportsUi", "%n template file(s) were written to %1.", None, len(written)
        )
        self.context.prompts.info(self.anchor, title, fill_placeholders(text, str(folder)))

    # ----- CSV export

    def export_csv(self) -> None:
        """Choose a folder, warn that the files hold internal data, write one file per entity."""
        service = self.exporter()
        if service is None:
            return
        title = QCoreApplication.translate("ReportsUi", "Export CSV files")
        folder = self.context.prompts.choose_folder(self.anchor, title)
        if folder is None:
            return
        notice = QCoreApplication.translate(
            "ReportsUi", "The files contain internal data: staff, assets, exercises and budget."
        )
        if not self.confirm_destination(folder, title, notice):
            return
        existing = service.existing_files(folder)
        if existing:
            question = QCoreApplication.translate(
                "ReportsUi",
                "%n existing file(s) in this folder will be replaced. Continue?",
                None,
                len(existing),
            )
            if not self.context.prompts.confirm(self.anchor, title, question):
                return
        written = guarded(
            self.context, self.anchor, error_label, lambda: service.export_all(folder)
        )
        if written is None:
            return
        text = QCoreApplication.translate(
            "ReportsUi", "%n file(s) were written to %1.", None, len(written)
        )
        self.context.prompts.info(self.anchor, title, fill_placeholders(text, str(folder)))
