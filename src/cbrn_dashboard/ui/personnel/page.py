# SPDX-License-Identifier: GPL-3.0-or-later
"""The Personnel page and its settings section (PLAN.md T2.4, D17, D24, A02, A04, A09).

The page lists the staff (with filters and the status per level on the as-of date), shows the
counts per level and, for the selected person, the certificates, training records and degrees. It
reads and writes ONLY through ``context.services.personnel``; the settings section also uses the
configuration service when the context has one. Dialogs are opened non-modally with ``open()`` so
tests can drive them. The module-level factories are what the registries of the shell call.
"""

from collections.abc import Callable
from datetime import date
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.domain.config import ReadinessConfig
from cbrn_dashboard.domain.personnel import (
    CertStatus,
    DegreeLevel,
    DegreeStatus,
    PpeLevel,
)
from cbrn_dashboard.services.errors import ServiceError
from cbrn_dashboard.services.personnel import (
    INVALID_NUMBER,
    CertificateView,
    CourseView,
    DegreeView,
    StaffView,
    TrainingView,
)
from cbrn_dashboard.ui.personnel.dialogs import (
    CertificateDialog,
    CourseDialog,
    DegreeDialog,
    StaffDialog,
    TrainingDialog,
)
from cbrn_dashboard.ui.personnel.labels import error_label, fill_placeholders, ppe_level_label
from cbrn_dashboard.ui.personnel.models import (
    CertificatesModel,
    CoursesModel,
    DegreesModel,
    StaffModel,
    StaffRow,
    SummaryModel,
    TrainingModel,
    TrainingRow,
)
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
    mark_data,
    show_service_error,
)

__all__ = [
    "PersonnelPage",
    "PersonnelSettingsSection",
    "create_page",
    "create_settings_section",
    "demo_certificate_dialog",
    "demo_course_dialog",
    "demo_degree_dialog",
    "demo_staff_dialog",
    "demo_training_dialog",
    "page_title",
    "settings_section_title",
]

#: The configuration fields the placeholder badges of this section refer to.
_A02_FIELDS = ("ppe_hierarchy_enabled", "ppe_hierarchy")
_A04_FIELDS = ("ppe_validity_months",)


def _open(dialog: QDialog) -> None:
    """Show ``dialog`` window-modally without blocking; it deletes itself when closed."""
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.open()


# --------------------------------------------------------------------------- the page


class PersonnelPage(QWidget):
    """Staff table with filters, summary per level and the details of the selected person."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("personnel_page")
        self.context = context
        self.staff_model = StaffModel(self)
        self.summary_model = SummaryModel(self)
        self.certificates_model = CertificatesModel(self)
        self.training_model = TrainingModel(self)
        self.degrees_model = DegreesModel(self)

        self.active_check = QCheckBox(self)
        self.active_check.setObjectName("active_filter")
        self.level_caption = QLabel(self)
        self.level_combo = QComboBox(self)
        self.level_combo.setObjectName("level_filter")
        mark_data(self.level_combo)
        self.level_caption.setBuddy(self.level_combo)
        self.level_combo.addItem("", None)
        for level in PpeLevel:
            self.level_combo.addItem(ppe_level_label(level.value), level.value)
        self.retraining_check = QCheckBox(self)
        self.retraining_check.setObjectName("retraining_filter")

        self.summary_caption = QLabel(self)
        self.summary_view = make_table_view(self.summary_model, self)
        self.summary_view.setObjectName("summary_view")
        self.summary_view.setMaximumHeight(120)
        self.summary_caption.setBuddy(self.summary_view)
        self.staff_view = make_table_view(self.staff_model, self)
        self.staff_view.setObjectName("staff_view")
        self.detail_caption = QLabel(self)
        self.certificates_view = make_table_view(self.certificates_model, self)
        self.certificates_view.setObjectName("certificates_view")
        self.training_view = make_table_view(self.training_model, self)
        self.training_view.setObjectName("training_view")
        self.degrees_view = make_table_view(self.degrees_model, self)
        self.degrees_view.setObjectName("degrees_view")

        self.add_staff_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Add person"), self.add_staff
        )
        self.edit_staff_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Edit person"), self.edit_staff
        )
        self.deactivate_staff_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Deactivate person"),
            self.deactivate_staff,
        )
        self.delete_staff_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Delete person"), self.delete_staff
        )
        self.pseudonymise_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Pseudonymise person"),
            self.pseudonymise_staff,
        )
        self.add_cert_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Add qualification"),
            self.add_certificate,
        )
        self.edit_cert_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Edit qualification"),
            self.edit_certificate,
        )
        self.delete_cert_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Delete qualification"),
            self.delete_certificate,
        )
        self.set_no_renewal_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Set no renewal"),
            self.set_no_renewal,
        )
        self.clear_no_renewal_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Clear no renewal"),
            self.clear_no_renewal,
        )
        self.add_training_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Add training"), self.add_training
        )
        self.edit_training_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Edit training"), self.edit_training
        )
        self.delete_training_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Delete training"),
            self.delete_training,
        )
        self.add_degree_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Add degree"), self.add_degree
        )
        self.edit_degree_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Edit degree"), self.edit_degree
        )
        self.delete_degree_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Delete degree"), self.delete_degree
        )
        self._staff_actions: tuple[EditAction, ...] = (
            self.add_staff_action,
            self.edit_staff_action,
            self.deactivate_staff_action,
            self.delete_staff_action,
            self.pseudonymise_action,
        )
        self._cert_actions: tuple[EditAction, ...] = (
            self.add_cert_action,
            self.edit_cert_action,
            self.delete_cert_action,
            self.set_no_renewal_action,
            self.clear_no_renewal_action,
        )
        self._training_actions: tuple[EditAction, ...] = (
            self.add_training_action,
            self.edit_training_action,
            self.delete_training_action,
        )
        self._degree_actions: tuple[EditAction, ...] = (
            self.add_degree_action,
            self.edit_degree_action,
            self.delete_degree_action,
        )
        self._actions: tuple[EditAction, ...] = (
            *self._staff_actions,
            *self._cert_actions,
            *self._training_actions,
            *self._degree_actions,
        )

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.active_check)
        filter_row.addWidget(self.level_caption)
        filter_row.addWidget(self.level_combo)
        filter_row.addWidget(self.retraining_check)
        filter_row.addStretch(1)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("detail_tabs")
        for view, actions in (
            (self.certificates_view, self._cert_actions),
            (self.training_view, self._training_actions),
            (self.degrees_view, self._degree_actions),
        ):
            tab = QWidget(self.tabs)
            tab_layout = QVBoxLayout(tab)
            tab_layout.addWidget(view, 1)
            tab_layout.addLayout(action_row(actions, tab))
            self.tabs.addTab(tab, "")

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary_caption)
        layout.addWidget(self.summary_view)
        layout.addLayout(filter_row)
        layout.addWidget(self.staff_view, 1)
        layout.addLayout(action_row(self._staff_actions, self))
        layout.addWidget(self.detail_caption)
        layout.addWidget(self.tabs, 1)

        for check in (self.active_check, self.retraining_check):
            check.toggled.connect(self.refresh)
        self.level_combo.currentIndexChanged.connect(self.refresh)
        for view in (
            self.staff_view,
            self.certificates_view,
            self.training_view,
            self.degrees_view,
        ):
            selection = view.selectionModel()
            if selection is not None:
                handler = self._staff_selected if view is self.staff_view else self._update_actions
                selection.selectionChanged.connect(handler)
        context.data_changed.connect(self.refresh)
        context.as_of_changed.connect(self._as_of_changed)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    def _action(self, text_fn: Callable[[], str], slot: Callable[[], None]) -> EditAction:
        return make_edit_action(self.context, self, text_fn, slot)

    # ----- texts

    def retranslate(self) -> None:
        """Re-apply every text of the page in the current language."""
        self.active_check.setText(QCoreApplication.translate("Personnel", "Active only"))
        self.retraining_check.setText(QCoreApplication.translate("Personnel", "Needs retraining"))
        self.level_caption.setText(QCoreApplication.translate("Personnel", "Level"))
        self.level_combo.setItemText(0, QCoreApplication.translate("Personnel", "All levels"))
        self.summary_caption.setText(
            QCoreApplication.translate(
                "Personnel", "PPE qualifications per level on the as-of date"
            )
        )
        self.detail_caption.setText(
            QCoreApplication.translate("Personnel", "Details of the selected person")
        )
        self.tabs.setTabText(0, QCoreApplication.translate("Personnel", "PPE qualifications"))
        self.tabs.setTabText(1, QCoreApplication.translate("Personnel", "Training"))
        self.tabs.setTabText(2, QCoreApplication.translate("Personnel", "Degrees"))
        # The tables without a caption of their own are named like their tab.
        self.staff_view.setAccessibleName(QCoreApplication.translate("Personnel", "Staff"))
        self.certificates_view.setAccessibleName(
            QCoreApplication.translate("Personnel", "PPE qualifications")
        )
        self.training_view.setAccessibleName(QCoreApplication.translate("Personnel", "Training"))
        self.degrees_view.setAccessibleName(QCoreApplication.translate("Personnel", "Degrees"))
        for action in self._actions:
            action.retranslate()
        lang = current_language(self.context)
        for model in (
            self.staff_model,
            self.summary_model,
            self.certificates_model,
            self.training_model,
            self.degrees_model,
        ):
            model.set_language(lang)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- selection

    def selected_staff(self) -> StaffView | None:
        row = self.staff_model.selected_row(self.staff_view)
        return row.staff if isinstance(row, StaffRow) else None

    def selected_certificate(self) -> CertificateView | None:
        row = self.certificates_model.selected_row(self.certificates_view)
        return row if isinstance(row, CertificateView) else None

    def selected_training(self) -> TrainingView | None:
        row = self.training_model.selected_row(self.training_view)
        return row.training if isinstance(row, TrainingRow) else None

    def selected_degree(self) -> DegreeView | None:
        row = self.degrees_model.selected_row(self.degrees_view)
        return row if isinstance(row, DegreeView) else None

    # ----- data

    def refresh(self, *_args: object) -> None:
        """Read the staff, the summary and the details of the selected person again."""
        service = self.context.services.personnel
        if service is None:
            self.staff_model.set_rows([])
            self.summary_model.set_rows([])
        else:
            previous = self.selected_staff()
            as_of = self.context.as_of
            staff = service.list_staff(
                as_of,
                active_only=self.active_check.isChecked(),
                level=self.level_combo.currentData(),
                needs_retraining=self.retraining_check.isChecked(),
            )
            statuses: dict[int, dict[PpeLevel, CertStatus]] = {}
            for level_row in service.level_rows(as_of):
                statuses.setdefault(level_row.staff_id, {})[level_row.level] = level_row.status
            self.staff_model.set_rows([StaffRow(view, statuses.get(view.id, {})) for view in staff])
            self.summary_model.set_rows(service.summary(as_of))
            if previous is not None:
                for row, view in enumerate(staff):
                    if view.id == previous.id:
                        self.staff_view.selectRow(row)
        self._refresh_details()

    def _as_of_changed(self, *_args: object) -> None:
        self.refresh()

    def _refresh_details(self) -> None:
        service = self.context.services.personnel
        person = self.selected_staff()
        if service is None or person is None:
            self.certificates_model.set_rows([])
            self.training_model.set_rows([])
            self.degrees_model.set_rows([])
        else:
            detail = service.staff_detail(person.id)
            courses: dict[int, CourseView] = {
                course.id: course for course in service.list_courses(include_inactive=True)
            }
            self.certificates_model.set_certificates(list(detail.certificates))
            self.training_model.set_training(list(detail.training), courses)
            self.degrees_model.set_degrees(list(detail.degrees))
        self._update_actions()

    def _staff_selected(self, *_args: object) -> None:
        self._refresh_details()

    def _update_actions(self, *_args: object) -> None:
        has_service = self.context.services.personnel is not None
        person = self.selected_staff()
        certificate = self.selected_certificate()
        enable = self.context.set_edit_enabled
        enable(self.add_staff_action, has_service)
        enable(self.edit_staff_action, has_service and person is not None)
        enable(
            self.deactivate_staff_action,
            has_service and person is not None and person.active_until is None,
        )
        enable(self.delete_staff_action, has_service and person is not None)
        enable(self.pseudonymise_action, has_service and person is not None)
        enable(self.add_cert_action, has_service and person is not None)
        enable(self.edit_cert_action, has_service and certificate is not None)
        enable(self.delete_cert_action, has_service and certificate is not None)
        enable(self.set_no_renewal_action, has_service and certificate is not None)
        enable(
            self.clear_no_renewal_action,
            has_service and certificate is not None and certificate.no_renewal_from is not None,
        )
        enable(self.add_training_action, has_service and person is not None)
        enable(self.edit_training_action, has_service and self.selected_training() is not None)
        enable(self.delete_training_action, has_service and self.selected_training() is not None)
        enable(self.add_degree_action, has_service and person is not None)
        enable(self.edit_degree_action, has_service and self.selected_degree() is not None)
        enable(self.delete_degree_action, has_service and self.selected_degree() is not None)

    # ----- staff

    def add_staff(self) -> None:
        _open(StaffDialog(self.context, self))

    def edit_staff(self) -> None:
        person = self.selected_staff()
        if person is not None:
            _open(StaffDialog(self.context, self, person))

    def deactivate_staff(self) -> None:
        person = self.selected_staff()
        service = self.context.services.personnel
        if person is None or service is None:
            return
        as_of = self.context.as_of
        title = QCoreApplication.translate("Personnel", "Deactivate person")
        question = fill_placeholders(
            QCoreApplication.translate("Personnel", "Deactivate person %1 as of %2?"),
            person.identifier,
            format_date(as_of, current_language(self.context)),
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context,
                self,
                error_label,
                lambda: service.deactivate_staff(person.id, as_of),
            )

    def delete_staff(self) -> None:
        person = self.selected_staff()
        service = self.context.services.personnel
        if person is None or service is None:
            return
        title = QCoreApplication.translate("Personnel", "Delete person")
        question = fill_placeholders(
            QCoreApplication.translate(
                "Personnel",
                "Delete person %1 together with the PPE qualifications, training records and "
                "degrees?",
            ),
            person.identifier,
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(self.context, self, error_label, lambda: service.delete_staff(person.id))

    def pseudonymise_staff(self) -> None:
        """Replace the identifier and free text with random codes (D17), if confirmed."""
        person = self.selected_staff()
        service = self.context.services.personnel
        if person is None or service is None:
            return
        title = QCoreApplication.translate("Personnel", "Pseudonymise person")
        template = QCoreApplication.translate(
            "Personnel",
            "Pseudonymise %1? Identifier and free text become random codes. This cannot be undone.",
        )
        question = fill_placeholders(template, person.identifier)
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context, self, error_label, lambda: service.pseudonymise_staff(person.id)
            )

    # ----- certificates

    def add_certificate(self) -> None:
        person = self.selected_staff()
        if person is not None:
            _open(CertificateDialog(self.context, self, person.id))

    def edit_certificate(self) -> None:
        person = self.selected_staff()
        certificate = self.selected_certificate()
        if person is not None and certificate is not None:
            _open(CertificateDialog(self.context, self, person.id, certificate))

    def set_no_renewal(self) -> None:
        """Open the certificate dialog with the "no renewal" mark switched on."""
        person = self.selected_staff()
        certificate = self.selected_certificate()
        if person is not None and certificate is not None:
            _open(CertificateDialog(self.context, self, person.id, certificate, no_renewal=True))

    def clear_no_renewal(self) -> None:
        certificate = self.selected_certificate()
        service = self.context.services.personnel
        if certificate is not None and service is not None:
            apply_change(
                self.context, self, error_label, lambda: service.clear_no_renewal(certificate.id)
            )

    def delete_certificate(self) -> None:
        certificate = self.selected_certificate()
        service = self.context.services.personnel
        if certificate is None or service is None:
            return
        title = QCoreApplication.translate("Personnel", "Delete qualification")
        template = QCoreApplication.translate(
            "Personnel", "Delete the level %1 qualification issued on %2?"
        )
        question = fill_placeholders(
            template,
            certificate.level.value,
            format_date(certificate.issued_on, current_language(self.context)),
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context, self, error_label, lambda: service.delete_certificate(certificate.id)
            )

    # ----- training

    def add_training(self) -> None:
        person = self.selected_staff()
        if person is not None:
            _open(TrainingDialog(self.context, self, person.id))

    def edit_training(self) -> None:
        person = self.selected_staff()
        training = self.selected_training()
        if person is not None and training is not None:
            _open(TrainingDialog(self.context, self, person.id, training))

    def delete_training(self) -> None:
        training = self.selected_training()
        service = self.context.services.personnel
        if training is None or service is None:
            return
        title = QCoreApplication.translate("Personnel", "Delete training")
        question = fill_placeholders(
            QCoreApplication.translate("Personnel", "Delete the training record of course %1?"),
            training.course_code,
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(
                self.context, self, error_label, lambda: service.delete_training(training.id)
            )

    # ----- degrees

    def add_degree(self) -> None:
        person = self.selected_staff()
        if person is not None:
            _open(DegreeDialog(self.context, self, person.id))

    def edit_degree(self) -> None:
        person = self.selected_staff()
        degree = self.selected_degree()
        if person is not None and degree is not None:
            _open(DegreeDialog(self.context, self, person.id, degree))

    def delete_degree(self) -> None:
        degree = self.selected_degree()
        service = self.context.services.personnel
        if degree is None or service is None:
            return
        title = QCoreApplication.translate("Personnel", "Delete degree")
        question = QCoreApplication.translate("Personnel", "Delete the selected degree?")
        if self.context.prompts.confirm(self, title, question):
            apply_change(self.context, self, error_label, lambda: service.delete_degree(degree.id))


# --------------------------------------------------------------------------- the settings section


#: The state of the rule inputs: A02 switch, mapping pairs, typed A04 months per level.
type _RuleState = tuple[bool, frozenset[tuple[str, str]], tuple[tuple[str, str], ...]]


class _InputError(Exception):
    """A typed value was refused; carries the service-style error to present."""

    def __init__(self, error: ServiceError) -> None:
        super().__init__(error.code)
        self.error = error


class PersonnelSettingsSection(QWidget):
    """Settings -> Personnel: the A02 mapping, the A04 months and the course list (A09)."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("personnel_section")
        self.context = context
        self.courses_model = CoursesModel(self)
        self._badge_ids: dict[str, str | None] = {"A02": None, "A04": None}
        #: The rule inputs as last loaded from the configuration (``None`` before the first load).
        self._loaded_rules: _RuleState | None = None
        #: The error code of a configuration that cannot be read (``None`` while it can be).
        self._config_error: str | None = None
        self.config_error_label = QLabel(self)
        self.config_error_label.setObjectName("config_error_label")
        self.config_error_label.setWordWrap(True)
        self.config_error_label.setVisible(False)

        # A02: the level mapping
        self.mapping_box = QGroupBox(self)
        self.mapping_box.setObjectName("mapping_box")
        self.hierarchy_check = QCheckBox(self.mapping_box)
        self.hierarchy_check.setObjectName("hierarchy_check")
        self.mapping_checks: dict[tuple[str, str], QCheckBox] = {}
        self.mapping_labels: dict[str, QLabel] = {}
        grid = QGridLayout()
        for row, level in enumerate(PpeLevel):
            caption = QLabel(self.mapping_box)
            self.mapping_labels[level.value] = caption
            grid.addWidget(caption, row, 0)
            column = 1
            for other in PpeLevel:
                if other is level:
                    continue
                box = QCheckBox(ppe_level_label(other.value), self.mapping_box)
                mark_data(box)
                self.mapping_checks[(level.value, other.value)] = box
                grid.addWidget(box, row, column)
                column += 1
        self.a02_badge = QLabel(self.mapping_box)
        self.a02_badge.setObjectName("a02_badge")
        self.confirm_a02_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Confirm"), self.confirm_a02
        )
        a02_row = QHBoxLayout()
        a02_row.addWidget(self.a02_badge)
        a02_row.addLayout(action_row((self.confirm_a02_action,), self.mapping_box))
        mapping_layout = QVBoxLayout(self.mapping_box)
        mapping_layout.addWidget(self.hierarchy_check)
        mapping_layout.addLayout(grid)
        mapping_layout.addLayout(a02_row)

        # A04: the validity months
        self.validity_box = QGroupBox(self)
        self.validity_box.setObjectName("validity_box")
        self.months_edits: dict[str, QLineEdit] = {}
        self.months_labels: dict[str, QLabel] = {}
        validity_grid = QGridLayout()
        for row, level in enumerate(PpeLevel):
            caption = QLabel(self.validity_box)
            edit = QLineEdit(self.validity_box)
            edit.setObjectName(f"months_edit_{level.value}")
            caption.setBuddy(edit)
            self.months_labels[level.value] = caption
            self.months_edits[level.value] = edit
            validity_grid.addWidget(caption, row, 0)
            validity_grid.addWidget(edit, row, 1)
        self.a04_badge = QLabel(self.validity_box)
        self.a04_badge.setObjectName("a04_badge")
        self.confirm_a04_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Confirm"), self.confirm_a04
        )
        a04_row = QHBoxLayout()
        a04_row.addWidget(self.a04_badge)
        a04_row.addLayout(action_row((self.confirm_a04_action,), self.validity_box))
        validity_layout = QVBoxLayout(self.validity_box)
        validity_layout.addLayout(validity_grid)
        validity_layout.addLayout(a04_row)

        self.save_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Save rules"), self.save_rules
        )

        # A09: the course list
        self.courses_box = QGroupBox(self)
        self.courses_box.setObjectName("courses_box")
        self.courses_view = make_table_view(self.courses_model, self.courses_box)
        self.courses_view.setObjectName("courses_view")
        self.add_course_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Add course"), self.add_course
        )
        self.edit_course_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Edit course"), self.edit_course
        )
        self.deactivate_course_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Deactivate course"),
            self.deactivate_course,
        )
        self.delete_course_action = self._action(
            lambda: QCoreApplication.translate("Personnel", "Delete course"), self.delete_course
        )
        self._course_actions: tuple[EditAction, ...] = (
            self.add_course_action,
            self.edit_course_action,
            self.deactivate_course_action,
            self.delete_course_action,
        )
        courses_layout = QVBoxLayout(self.courses_box)
        courses_layout.addWidget(self.courses_view, 1)
        courses_layout.addLayout(action_row(self._course_actions, self.courses_box))

        self._actions: tuple[EditAction, ...] = (
            self.confirm_a02_action,
            self.confirm_a04_action,
            self.save_action,
            *self._course_actions,
        )
        self._inputs: tuple[QWidget, ...] = (
            self.hierarchy_check,
            *self.mapping_checks.values(),
            *self.months_edits.values(),
        )
        for widget in self._inputs:
            context.register_edit_action(widget)

        layout = QVBoxLayout(self)
        layout.addWidget(self.config_error_label)
        layout.addWidget(self.mapping_box)
        layout.addWidget(self.validity_box)
        layout.addLayout(action_row((self.save_action,), self))
        layout.addWidget(self.courses_box, 1)

        selection = self.courses_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._update_actions)
        context.data_changed.connect(self.refresh)
        follow_language(context, self.retranslate)
        self.retranslate()
        self.refresh()

    def _action(self, text_fn: Callable[[], str], slot: Callable[[], None]) -> EditAction:
        return make_edit_action(self.context, self, text_fn, slot)

    def _config(self) -> Any:
        """The configuration service of the context, or ``None`` when there is none."""
        return getattr(self.context.services, "config", None)

    # ----- texts

    def retranslate(self) -> None:
        self.mapping_box.setTitle(
            QCoreApplication.translate("Personnel", "Qualifications that count for other levels")
        )
        self.hierarchy_check.setText(
            QCoreApplication.translate("Personnel", "A qualification also counts for other levels")
        )
        for level, caption in self.mapping_labels.items():
            caption.setText(
                QCoreApplication.translate(
                    "Personnel", "A level %1 qualification counts for:"
                ).replace("%1", ppe_level_label(level))
            )
        self.validity_box.setTitle(
            QCoreApplication.translate("Personnel", "Validity of a qualification in months")
        )
        for level, caption in self.months_labels.items():
            caption.setText(
                QCoreApplication.translate("Personnel", "Level %1").replace(
                    "%1", ppe_level_label(level)
                )
            )
        for edit in self.months_edits.values():
            edit.setPlaceholderText(QCoreApplication.translate("Personnel", "Not set"))
        self.courses_box.setTitle(QCoreApplication.translate("Personnel", "Courses"))
        self.courses_view.setAccessibleName(QCoreApplication.translate("Personnel", "Courses"))
        badge = QCoreApplication.translate("Personnel", "Placeholder - to be confirmed")
        self.a02_badge.setText(badge)
        self.a04_badge.setText(badge)
        for action in self._actions:
            action.retranslate()
        self._show_config_error()
        self.courses_model.set_language(current_language(self.context))

    def _show_config_error(self) -> None:
        """Show why the rule inputs are off (a configuration that cannot be read)."""
        code = self._config_error
        self.config_error_label.setVisible(code is not None)
        self.config_error_label.setText("" if code is None else error_label(code))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ----- data

    def selected_course(self) -> CourseView | None:
        row = self.courses_model.selected_row(self.courses_view)
        return row if isinstance(row, CourseView) else None

    @staticmethod
    def _badge_for(config: Any, fields: tuple[str, ...]) -> str | None:
        for name in fields:
            badge = config.badge_for_field(name)
            if badge:
                return str(badge)
        return None

    def _typed_rules(self) -> _RuleState:
        """What the rule inputs show now: switch, mapping pairs and the typed months."""
        return (
            self.hierarchy_check.isChecked(),
            frozenset(key for key, box in self.mapping_checks.items() if box.isChecked()),
            tuple((level, edit.text().strip()) for level, edit in self.months_edits.items()),
        )

    def is_dirty(self) -> bool:
        """Whether the rule inputs differ from what was last loaded into them (unsaved edits)."""
        return self._loaded_rules is not None and self._typed_rules() != self._loaded_rules

    def reload_rules(self) -> None:
        """Put the stored A02 switch, the mapping and the A04 months into the inputs."""
        config = self._config()
        if config is None:
            return
        try:
            current = config.load()
        except ServiceError as error:
            self._config_error = error.code
            self._show_config_error()
            self._update_actions()
            return
        self._config_error = None
        self._show_config_error()
        self._apply_rules(current)

    def _apply_rules(self, current: ReadinessConfig) -> None:
        """Put the loaded configuration into the rule inputs."""
        self.hierarchy_check.setChecked(bool(current.ppe_hierarchy_enabled))
        for (level, other), box in self.mapping_checks.items():
            box.setChecked(other in current.ppe_hierarchy.get(level, ()))
        for level, edit in self.months_edits.items():
            months = current.ppe_validity_months.get(level)
            edit.setText("" if months is None else str(months))
        self._loaded_rules = self._typed_rules()

    def refresh(self, *_args: object) -> None:
        """Read the courses and the badges again.

        The rule inputs are reloaded only the first time and when they hold no unsaved edit: a
        change signalled by the course list or by another page must not discard what was typed.
        A configuration that cannot be read is shown as a message and switches the inputs off
        until a later refresh can read it.
        """
        config = self._config()
        self._badge_ids = {"A02": None, "A04": None}
        if config is not None:
            try:
                stored = config.load()
                self._badge_ids = {
                    "A02": self._badge_for(config, _A02_FIELDS),
                    "A04": self._badge_for(config, _A04_FIELDS),
                }
            except ServiceError as error:
                self._badge_ids = {"A02": None, "A04": None}
                self._config_error = error.code
            else:
                self._config_error = None
                if self._loaded_rules is None or not self.is_dirty():
                    self._apply_rules(stored)
        else:
            self._config_error = None
        self._show_config_error()
        self.a02_badge.setVisible(self._badge_ids["A02"] is not None)
        self.a04_badge.setVisible(self._badge_ids["A04"] is not None)
        service = self.context.services.personnel
        previous = self.selected_course()
        courses = [] if service is None else service.list_courses(include_inactive=True)
        self.courses_model.set_rows(courses)
        if previous is not None:
            for row, course in enumerate(courses):
                if course.id == previous.id:
                    self.courses_view.selectRow(row)
        self._update_actions()

    def _update_actions(self, *_args: object) -> None:
        config = self._config() is not None and self._config_error is None
        has_service = self.context.services.personnel is not None
        course = self.selected_course()
        enable = self.context.set_edit_enabled
        for widget in self._inputs:
            enable(widget, config)
        enable(self.save_action, config)
        enable(self.confirm_a02_action, config and self._badge_ids["A02"] is not None)
        enable(self.confirm_a04_action, config and self._badge_ids["A04"] is not None)
        enable(self.add_course_action, has_service)
        enable(self.edit_course_action, has_service and course is not None)
        enable(self.deactivate_course_action, has_service and course is not None and course.active)
        enable(self.delete_course_action, has_service and course is not None)

    # ----- configuration

    def confirm_a02(self) -> None:
        self._confirm("A02")

    def confirm_a04(self) -> None:
        self._confirm("A04")

    def _confirm(self, key: str) -> None:
        config = self._config()
        badge = self._badge_ids[key]
        if (
            config is not None
            and badge is not None
            and apply_change(self.context, self, error_label, lambda: config.confirm(badge))
        ):
            self.reload_rules()

    def _read_months(self) -> dict[str, int | None]:
        months: dict[str, int | None] = {}
        for level, edit in self.months_edits.items():
            text = edit.text().strip()
            if not text:
                months[level] = None
            elif text.isascii() and text.isdigit():
                months[level] = int(text)
            else:
                raise _InputError(ServiceError(INVALID_NUMBER, "ppe_validity_months"))
        return months

    def save_rules(self) -> None:
        """Save the A02 switch and mapping and the A04 months through the config service."""
        config = self._config()
        if config is None:
            return
        try:
            months = self._read_months()
        except _InputError as failure:
            show_service_error(self.context, self, failure.error, error_label)
            return
        hierarchy: dict[str, tuple[str, ...]] = {}
        for level in PpeLevel:
            also = tuple(
                other.value
                for other in PpeLevel
                if (level.value, other.value) in self.mapping_checks
                and self.mapping_checks[(level.value, other.value)].isChecked()
            )
            if also:
                hierarchy[level.value] = also
        hierarchy_enabled = self.hierarchy_check.isChecked()

        def save() -> object:
            return config.save(
                config.load().with_changes(
                    ppe_hierarchy_enabled=hierarchy_enabled,
                    ppe_hierarchy=hierarchy,
                    ppe_validity_months=months,
                )
            )

        if apply_change(self.context, self, error_label, save):
            self.reload_rules()

    # ----- courses

    def add_course(self) -> None:
        _open(CourseDialog(self.context, self))

    def edit_course(self) -> None:
        course = self.selected_course()
        if course is not None:
            _open(CourseDialog(self.context, self, course))

    def deactivate_course(self) -> None:
        course = self.selected_course()
        service = self.context.services.personnel
        if course is not None and service is not None:
            apply_change(
                self.context, self, error_label, lambda: service.deactivate_course(course.id)
            )

    def delete_course(self) -> None:
        course = self.selected_course()
        service = self.context.services.personnel
        if course is None or service is None:
            return
        title = QCoreApplication.translate("Personnel", "Delete course")
        question = fill_placeholders(
            QCoreApplication.translate("Personnel", "Delete course %1?"), course.code
        )
        if self.context.prompts.confirm(self, title, question):
            apply_change(self.context, self, error_label, lambda: service.delete_course(course.id))


# --------------------------------------------------------------------------- registry factories


def page_title() -> str:
    return QCoreApplication.translate("Personnel", "Personnel")


def create_page(context: AppContext) -> QWidget:
    return PersonnelPage(context)


def settings_section_title() -> str:
    return QCoreApplication.translate("Personnel", "Personnel rules and courses")


def create_settings_section(context: AppContext) -> QWidget:
    return PersonnelSettingsSection(context)


def demo_staff_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A staff dialog filled with fictitious data (it writes nothing unless accepted)."""
    staff = StaffView(
        id=0,
        identifier="DEMO-001",
        label="Demo person",
        category="Demo category",
        active_from=date(2026, 1, 12),
        active_until=None,
    )
    return StaffDialog(context, parent, staff)


def demo_certificate_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A certificate dialog filled with a fictitious certificate."""
    certificate = CertificateView(
        id=0,
        staff_id=0,
        level=PpeLevel.A,
        issued_on=date(2025, 3, 3),
        valid_until=date(2026, 3, 3),
        no_renewal_from=date(2026, 3, 3),
        no_renewal_reason="other",
        reference="DEMO-REF-1",
    )
    return CertificateDialog(context, parent, 0, certificate)


def demo_training_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A training dialog filled with a fictitious record."""
    training = TrainingView(
        id=0,
        staff_id=0,
        course_id=0,
        course_code="DEMO-COURSE",
        completed_on=date(2025, 9, 15),
        hours=24.0,
    )
    return TrainingDialog(context, parent, 0, training)


def demo_degree_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A degree dialog filled with a fictitious degree."""
    degree = DegreeView(
        id=0,
        staff_id=0,
        level=DegreeLevel.MASTER,
        status=DegreeStatus.IN_PROGRESS,
        year=2027,
        field="Demo field",
    )
    return DegreeDialog(context, parent, 0, degree)


def demo_course_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A course dialog filled with a fictitious course."""
    course = CourseView(
        id=0,
        code="DEMO-COURSE",
        label_pt_br="Curso de demonstracao",
        label_en_us="Demo course",
        label_es_es=None,
        active=True,
    )
    return CourseDialog(context, parent, course)
