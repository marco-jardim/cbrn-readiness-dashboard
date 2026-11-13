# SPDX-License-Identifier: GPL-3.0-or-later
"""The Exercises page and its metric editor (PLAN.md T4.5, D20, A07, A13).

The page lists the editions (filterable by kind) and, below, the evaluation results of the selected
edition. It reads and writes ONLY through ``context.services.exercises``; dialogs are opened
non-modally with ``open()`` so tests can drive them. The module-level factories are what the
registries of the shell call.
"""

from datetime import date

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from cbrn_dashboard.domain.exercises import ExerciseKind
from cbrn_dashboard.services.exercises import EditionView, MetricView, ResultView
from cbrn_dashboard.ui.exercises.dialogs import EditionDialog, MetricDialog, ResultDialog
from cbrn_dashboard.ui.exercises.labels import error_label, kind_label
from cbrn_dashboard.ui.exercises.models import EditionsModel, MetricsModel, ResultsModel
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.widgets import (
    EditAction,
    action_row,
    apply_change,
    current_language,
    follow_language,
    make_edit_action,
    make_table_view,
    mark_data,
)

__all__ = [
    "ExercisesPage",
    "MetricsSettingsSection",
    "create_page",
    "create_settings_section",
    "demo_edition_dialog",
    "demo_metric_dialog",
    "demo_result_dialog",
    "page_title",
    "settings_section_title",
]


def _open(dialog: QDialog) -> None:
    """Show ``dialog`` window-modally without blocking; it deletes itself when closed."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


# --------------------------------------------------------------------------- the page


class ExercisesPage(QWidget):
    """Editions table with kind filter, and the results table of the selected edition."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("exercises_page")
        self.context = context
        self.editions_model = EditionsModel(self)
        self.results_model = ResultsModel(self)
        self.kind_caption = QLabel(self)
        self.kind_combo = QComboBox(self)
        mark_data(self.kind_combo)
        self.kind_combo.addItem("", None)
        for kind in ExerciseKind:
            self.kind_combo.addItem("", kind.value)
        self.editions_view = make_table_view(self.editions_model, self)
        self.editions_view.setObjectName("editions_view")
        self.results_caption = QLabel(self)
        self.results_view = make_table_view(self.results_model, self)
        self.results_view.setObjectName("results_view")

        self.add_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Add edition"),
            self.add_edition,
        )
        self.edit_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Edit edition"),
            self.edit_edition,
        )
        self.delete_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Delete edition"),
            self.delete_edition,
        )
        self.add_result_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Add result"),
            self.add_result,
        )
        self.edit_result_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Edit result"),
            self.edit_result,
        )
        self.delete_result_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Delete result"),
            self.delete_result,
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_action,
            self.edit_action,
            self.delete_action,
            self.add_result_action,
            self.edit_result_action,
            self.delete_result_action,
        )

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.kind_caption)
        filter_row.addWidget(self.kind_combo)
        filter_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(filter_row)
        layout.addWidget(self.editions_view, 1)
        layout.addLayout(action_row((self.add_action, self.edit_action, self.delete_action), self))
        layout.addWidget(self.results_caption)
        layout.addWidget(self.results_view, 1)
        layout.addLayout(
            action_row(
                (self.add_result_action, self.edit_result_action, self.delete_result_action), self
            )
        )

        self.kind_combo.currentIndexChanged.connect(self.refresh)
        selection = self.editions_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._edition_selected)
        selection = self.results_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    # ----- texts

    def retranslate(self) -> None:
        """Re-apply every text of the page in the current language."""
        self.kind_caption.setText(QCoreApplication.translate("Exercises", "Kind"))
        self.results_caption.setText(
            QCoreApplication.translate("Exercises", "Evaluation results of the selected edition")
        )
        self.kind_combo.setItemText(0, QCoreApplication.translate("Exercises", "All kinds"))
        for index in range(1, self.kind_combo.count()):
            self.kind_combo.setItemText(index, kind_label(str(self.kind_combo.itemData(index))))
        for action in self._actions:
            action.retranslate()
        lang = current_language(self.context)
        self.editions_model.set_language(lang)
        self.results_model.set_language(lang)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- data

    def selected_edition(self) -> EditionView | None:
        row = self.editions_model.selected_row(self.editions_view)
        return row if isinstance(row, EditionView) else None

    def selected_result(self) -> ResultView | None:
        row = self.results_model.selected_row(self.results_view)
        return None if row is None else row.result

    def refresh(self) -> None:
        """Read the editions (and the results of the selected one) again."""
        service = self.context.services.exercises
        kept = self.selected_result()
        if service is None:
            self.editions_model.set_rows([])
        else:
            previous = self.selected_edition()
            editions = service.list_editions(self.kind_combo.currentData())
            self.editions_model.set_rows(editions)
            if previous is not None:
                for row, edition in enumerate(editions):
                    if edition.id == previous.id:
                        self.editions_view.selectRow(row)
        self._refresh_results(kept)

    def _refresh_results(self, kept: ResultView | None = None) -> None:
        """Read the results of the selected edition; ``kept`` stays selected if it is there."""
        service = self.context.services.exercises
        edition = self.selected_edition()
        previous = kept if kept is not None else self.selected_result()
        if service is None or edition is None:
            self.results_model.set_results([], {})
        else:
            metrics = {m.id: m for m in service.list_metrics(include_inactive=True)}
            results = service.list_results(edition.id)
            self.results_model.set_results(results, metrics)
            if previous is not None:
                key = (previous.edition_id, previous.metric_id)
                for row, result in enumerate(results):
                    if (result.edition_id, result.metric_id) == key:
                        self.results_view.selectRow(row)
        self._update_actions()

    def _edition_selected(self, *_args: object) -> None:
        self._refresh_results()

    def _update_actions(self, *_args: object) -> None:
        has_service = self.context.services.exercises is not None
        edition = self.selected_edition() is not None
        result = self.selected_result() is not None
        enable = self.context.set_edit_enabled
        enable(self.add_action, has_service)
        enable(self.edit_action, has_service and edition)
        enable(self.delete_action, has_service and edition)
        enable(self.add_result_action, has_service and edition)
        enable(self.edit_result_action, has_service and result)
        enable(self.delete_result_action, has_service and result)

    # ----- editions

    def add_edition(self) -> None:
        _open(EditionDialog(self.context, self))

    def edit_edition(self) -> None:
        edition = self.selected_edition()
        if edition is not None:
            _open(EditionDialog(self.context, self, edition))

    def delete_edition(self) -> None:
        edition = self.selected_edition()
        service = self.context.services.exercises
        if edition is None or service is None:
            return
        title = QCoreApplication.translate("Exercises", "Delete edition")
        question = QCoreApplication.translate(
            "Exercises", "Delete edition %1 together with its countries and results?"
        ).replace("%1", edition.code)
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context, self, error_label, lambda: service.delete_edition(edition.id)
            )

    # ----- results

    def add_result(self) -> None:
        edition = self.selected_edition()
        if edition is not None:
            _open(ResultDialog(self.context, self, edition.id))

    def edit_result(self) -> None:
        edition = self.selected_edition()
        result = self.selected_result()
        if edition is not None and result is not None:
            _open(ResultDialog(self.context, self, edition.id, result))

    def delete_result(self) -> None:
        result = self.selected_result()
        service = self.context.services.exercises
        if result is None or service is None:
            return
        title = QCoreApplication.translate("Exercises", "Delete result")
        question = QCoreApplication.translate(
            "Exercises", "Delete the result of metric %1?"
        ).replace("%1", result.metric_code)
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context,
                self,
                error_label,
                lambda: service.delete_result(result.edition_id, result.metric_id),
            )


# --------------------------------------------------------------------------- the metric editor


class MetricsSettingsSection(QWidget):
    """Settings -> Exercises: the evaluation metrics, including the inactive ones (A07)."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metrics_section")
        self.context = context
        self.model = MetricsModel(self)
        self.view = make_table_view(self.model, self)
        self.view.setObjectName("metrics_view")
        self.add_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Add metric"),
            self.add_metric,
        )
        self.edit_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Edit metric"),
            self.edit_metric,
        )
        self.deactivate_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Deactivate metric"),
            self.deactivate_metric,
        )
        self.delete_action = make_edit_action(
            context,
            self,
            lambda: QCoreApplication.translate("Exercises", "Delete metric"),
            self.delete_metric,
        )
        self._actions: tuple[EditAction, ...] = (
            self.add_action,
            self.edit_action,
            self.deactivate_action,
            self.delete_action,
        )
        layout = QVBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addLayout(action_row(self._actions, self))
        selection = self.view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    def retranslate(self) -> None:
        for action in self._actions:
            action.retranslate()
        self.model.set_language(current_language(self.context))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def selected_metric(self) -> MetricView | None:
        row = self.model.selected_row(self.view)
        return row if isinstance(row, MetricView) else None

    def refresh(self) -> None:
        service = self.context.services.exercises
        previous = self.selected_metric()
        metrics = [] if service is None else service.list_metrics(include_inactive=True)
        self.model.set_rows(metrics)
        if previous is not None:
            for row, metric in enumerate(metrics):
                if metric.id == previous.id:
                    self.view.selectRow(row)
        self._update_actions()

    def _update_actions(self, *_args: object) -> None:
        has_service = self.context.services.exercises is not None
        metric = self.selected_metric()
        enable = self.context.set_edit_enabled
        enable(self.add_action, has_service)
        enable(self.edit_action, has_service and metric is not None)
        enable(self.deactivate_action, has_service and metric is not None and metric.active)
        enable(self.delete_action, has_service and metric is not None)

    def add_metric(self) -> None:
        _open(MetricDialog(self.context, self))

    def edit_metric(self) -> None:
        metric = self.selected_metric()
        if metric is not None:
            _open(MetricDialog(self.context, self, metric))

    def deactivate_metric(self) -> None:
        metric = self.selected_metric()
        service = self.context.services.exercises
        if metric is not None and service is not None:
            apply_change(
                self.context, self, error_label, lambda: service.deactivate_metric(metric.id)
            )

    def delete_metric(self) -> None:
        metric = self.selected_metric()
        service = self.context.services.exercises
        if metric is None or service is None:
            return
        title = QCoreApplication.translate("Exercises", "Delete metric")
        question = QCoreApplication.translate("Exercises", "Delete metric %1?").replace(
            "%1", metric.code
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(self.context, self, error_label, lambda: service.delete_metric(metric.id))


# --------------------------------------------------------------------------- registry factories


def page_title() -> str:
    return QCoreApplication.translate("Exercises", "Exercises")


def create_page(context: AppContext) -> QWidget:
    return ExercisesPage(context)


def settings_section_title() -> str:
    return QCoreApplication.translate("Exercises", "Evaluation metrics")


def create_settings_section(context: AppContext) -> QWidget:
    return MetricsSettingsSection(context)


def demo_edition_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """An edition dialog filled with fictitious data (it writes nothing unless accepted)."""
    edition = EditionView(
        id=0,
        code="DEMO-2026",
        kind=ExerciseKind.OTHER,
        title="Demo exercise",
        start_on=date(2026, 3, 2),
        end_on=date(2026, 3, 6),
        participants=40,
        notes=None,
        countries=("AR", "BR", "CL"),
        results=(),
    )
    return EditionDialog(context, parent, edition)


def demo_result_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A result dialog filled with a fictitious result."""
    result = ResultView(
        edition_id=0,
        metric_id=0,
        metric_code="DEMO",
        value=4.5,
        respondents=12,
        note=None,
    )
    return ResultDialog(context, parent, 0, result)


def demo_metric_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A metric dialog filled with a fictitious metric."""
    metric = MetricView(
        id=0,
        code="DEMO",
        label_pt_br="Metrica de demonstracao",
        label_en_us="Demo metric",
        label_es_es=None,
        unit="points",
        scale_min=0.0,
        scale_max=5.0,
        higher_is_better=True,
        active=True,
    )
    return MetricDialog(context, parent, metric)
