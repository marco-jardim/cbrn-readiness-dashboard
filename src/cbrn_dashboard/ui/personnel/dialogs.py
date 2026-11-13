# SPDX-License-Identifier: GPL-3.0-or-later
"""Dialogs of the personnel module: staff, certificate, training, degree and course (T2.4, D17).

Each dialog builds the service input in ``submit()``, calls the service through ``apply_change``
(a ``ServiceError`` is shown translated and the dialog stays open) and never touches storage.
There are NO free-text note fields (D17); the remaining free-text inputs show a visible hint.
Identifiers, labels, references, course names and level letters are data, flagged with
``i18nData``.
"""

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.domain.personnel import DegreeLevel, DegreeStatus, PpeLevel
from cbrn_dashboard.services.errors import REQUIRED, ServiceError
from cbrn_dashboard.services.personnel import (
    INVALID_NUMBER,
    NO_RENEWAL_REASONS,
    CertificateInput,
    CertificateView,
    CourseInput,
    CourseView,
    DegreeInput,
    DegreeView,
    StaffInput,
    StaffView,
    TrainingInput,
    TrainingView,
    course_label,
)
from cbrn_dashboard.ui.personnel.labels import (
    degree_level_label,
    degree_status_label,
    error_label,
    ppe_level_label,
    reason_label,
)
from cbrn_dashboard.ui.personnel.models import format_hours
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import (
    AMBIGUOUS_NUMBER,
    FormatError,
    apply_locale,
    from_qdate,
    parse_number,
    to_qdate,
)
from cbrn_dashboard.ui.shell.widgets import (
    FormDialog,
    apply_change,
    mark_data,
    show_service_error,
)

__all__ = [
    "CertificateDialog",
    "CourseDialog",
    "DegreeDialog",
    "StaffDialog",
    "TrainingDialog",
]

_MAX_YEAR = 2200
_NOT_SET = 0


def _date_edit(parent: QWidget, value: QDate) -> QDateEdit:
    edit = QDateEdit(value, parent)
    edit.setCalendarPopup(True)
    return edit


def _identifier_hint() -> str:
    return QCoreApplication.translate("Personnel", "A local code, not a service number.")


def _free_text_hint() -> str:
    return QCoreApplication.translate("Personnel", "No names, health or contact data.")


class _PersonnelDialog(FormDialog):
    """A form dialog whose free-text inputs can carry a visible helper text under them."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(context, parent)
        self._hints: list[tuple[QLabel, Callable[[], str]]] = []

    def add_hinted_field(
        self,
        label_fn: Callable[[], str],
        widget: QWidget,
        hint_fn: Callable[[], str],
        hint_name: str,
    ) -> QLabel:
        """Add a form row with ``hint_fn()`` shown as helper text under ``widget``."""
        container = QWidget(self)
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        box.addWidget(widget)
        hint = QLabel(hint_fn(), container)
        hint.setObjectName(hint_name)
        hint.setWordWrap(True)
        box.addWidget(hint)
        self._hints.append((hint, hint_fn))
        label = self.add_field(label_fn, container)
        label.setBuddy(widget)
        return label

    def retranslate(self) -> None:
        super().retranslate()
        for hint, hint_fn in self._hints:
            hint.setText(hint_fn())


def _number_error(error: FormatError, field: str) -> ServiceError:
    """The service-style error for a number the user typed wrongly."""
    if error.code == AMBIGUOUS_NUMBER:
        return ServiceError(AMBIGUOUS_NUMBER, field)
    return ServiceError(INVALID_NUMBER, field)


# --------------------------------------------------------------------------- staff


class StaffDialog(_PersonnelDialog):
    """Add or edit a person: identifier, label, category and the start of the active period."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        staff: StaffView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("staff_dialog")
        self._staff = staff
        self.identifier_edit = QLineEdit(self)
        self.identifier_edit.setObjectName("identifier_edit")
        self.label_edit = QLineEdit(self)
        self.label_edit.setObjectName("label_edit")
        self.category_edit = QLineEdit(self)
        self.category_edit.setObjectName("category_edit")
        self.active_from_edit = _date_edit(self, to_qdate(context.as_of))
        self.add_hinted_field(
            lambda: QCoreApplication.translate("Personnel", "Identifier"),
            self.identifier_edit,
            _identifier_hint,
            "identifier_hint",
        )
        self.add_hinted_field(
            lambda: QCoreApplication.translate("Personnel", "Label"),
            self.label_edit,
            _free_text_hint,
            "label_hint",
        )
        self.add_field(
            lambda: QCoreApplication.translate("Personnel", "Category"), self.category_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Personnel", "Active from"), self.active_from_edit
        )
        if staff is not None:
            self.identifier_edit.setText(staff.identifier)
            self.label_edit.setText(staff.label or "")
            self.category_edit.setText(staff.category or "")
            self.active_from_edit.setDate(to_qdate(staff.active_from))
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._staff is None:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Add person"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Edit person"))
        apply_locale(self.active_from_edit, self.language)

    def submit(self) -> bool:
        service = self.context.services.personnel
        if service is None:
            return False
        staff = self._staff
        data = StaffInput(
            identifier=self.identifier_edit.text(),
            active_from=from_qdate(self.active_from_edit.date()),
            active_until=None if staff is None else staff.active_until,
            label=self.label_edit.text(),
            category=self.category_edit.text(),
        )

        def save() -> None:
            if staff is None:
                service.create_staff(data)
            else:
                service.update_staff(staff.id, data)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- certificate


class CertificateDialog(_PersonnelDialog):
    """Add or edit a certificate: level, dates, reference and the "no renewal" mark (D24).

    ``valid_until`` is pre-filled from the validity months configured for the level (A04) until
    the user changes it. ``no_renewal=True`` opens the dialog with the "no renewal" mark switched
    on (the page's "Set no renewal" action).
    """

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        staff_id: int = 0,
        certificate: CertificateView | None = None,
        *,
        no_renewal: bool = False,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("certificate_dialog")
        self._staff_id = staff_id
        self._certificate = certificate
        self._valid_touched = certificate is not None
        self._prefilling = False
        today = to_qdate(context.as_of)
        self.level_combo = QComboBox(self)
        self.level_combo.setObjectName("level_combo")
        mark_data(self.level_combo)
        for level in PpeLevel:
            self.level_combo.addItem(ppe_level_label(level.value), level.value)
        self.issued_edit = _date_edit(self, today)
        self.valid_until_edit = _date_edit(self, today)
        self.reference_edit = QLineEdit(self)
        self.reference_edit.setObjectName("reference_edit")
        self.no_renewal_check = QCheckBox(self)
        self.no_renewal_edit = _date_edit(self, today)
        self.reason_combo = QComboBox(self)
        self.reason_combo.addItem("", None)
        for reason in NO_RENEWAL_REASONS:
            self.reason_combo.addItem("", reason)
        self.add_field(lambda: QCoreApplication.translate("Personnel", "Level"), self.level_combo)
        self.add_field(
            lambda: QCoreApplication.translate("Personnel", "Issued on"), self.issued_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Personnel", "Valid until"), self.valid_until_edit
        )
        self.add_hinted_field(
            lambda: QCoreApplication.translate("Personnel", "Reference"),
            self.reference_edit,
            _free_text_hint,
            "reference_hint",
        )
        self.form.addRow(self.no_renewal_check)
        self.add_field(
            lambda: QCoreApplication.translate("Personnel", "No renewal from"),
            self.no_renewal_edit,
        )
        self.add_field(lambda: QCoreApplication.translate("Personnel", "Reason"), self.reason_combo)
        if certificate is not None:
            self._load(certificate)
        self.no_renewal_check.toggled.connect(self._sync_no_renewal)
        if no_renewal:
            self.no_renewal_check.setChecked(True)
        self._sync_no_renewal()
        self.level_combo.currentIndexChanged.connect(self._prefill)
        self.issued_edit.dateChanged.connect(self._prefill)
        self.valid_until_edit.dateChanged.connect(self._valid_until_changed)
        self._prefill()
        self.retranslate()

    def _load(self, certificate: CertificateView) -> None:
        self.level_combo.setCurrentIndex(max(0, self.level_combo.findData(certificate.level.value)))
        self.issued_edit.setDate(to_qdate(certificate.issued_on))
        self.valid_until_edit.setDate(to_qdate(certificate.valid_until))
        self.reference_edit.setText(certificate.reference or "")
        if certificate.no_renewal_from is not None:
            self.no_renewal_check.setChecked(True)
            self.no_renewal_edit.setDate(to_qdate(certificate.no_renewal_from))
            self.reason_combo.setCurrentIndex(
                max(0, self.reason_combo.findData(certificate.no_renewal_reason))
            )

    def _sync_no_renewal(self, *_args: object) -> None:
        checked = self.no_renewal_check.isChecked()
        self.no_renewal_edit.setEnabled(checked)
        self.reason_combo.setEnabled(checked)

    def _valid_until_changed(self, *_args: object) -> None:
        if not self._prefilling:
            self._valid_touched = True

    def _prefill(self, *_args: object) -> None:
        """Propose ``valid_until`` (A04) while the user has not edited it."""
        service = self.context.services.personnel
        if self._valid_touched or service is None:
            return
        issued = from_qdate(self.issued_edit.date())
        proposed = service.propose_valid_until(str(self.level_combo.currentData()), issued)
        self._prefilling = True
        try:
            self.valid_until_edit.setDate(to_qdate(issued if proposed is None else proposed))
        finally:
            self._prefilling = False

    def retranslate(self) -> None:
        super().retranslate()
        if self._certificate is None:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Add certificate"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Edit certificate"))
        self.no_renewal_check.setText(QCoreApplication.translate("Personnel", "Mark as no renewal"))
        self.reason_combo.setItemText(0, QCoreApplication.translate("Personnel", "Not specified"))
        for index in range(1, self.reason_combo.count()):
            self.reason_combo.setItemText(
                index, reason_label(str(self.reason_combo.itemData(index)))
            )
        for edit in (self.issued_edit, self.valid_until_edit, self.no_renewal_edit):
            apply_locale(edit, self.language)

    def submit(self) -> bool:
        service = self.context.services.personnel
        if service is None:
            return False
        data = CertificateInput(
            level=str(self.level_combo.currentData()),
            issued_on=from_qdate(self.issued_edit.date()),
            valid_until=from_qdate(self.valid_until_edit.date()),
            reference=self.reference_edit.text(),
        )
        marked = self.no_renewal_check.isChecked()
        mark_from = from_qdate(self.no_renewal_edit.date())
        reason = self.reason_combo.currentData()
        certificate = self._certificate
        staff_id = self._staff_id

        def save() -> None:
            if certificate is None:
                cert_id = service.add_certificate(staff_id, data)
            else:
                service.update_certificate(certificate.id, data)
                cert_id = certificate.id
            if marked:
                service.set_no_renewal(cert_id, mark_from, None if reason is None else str(reason))
            elif certificate is not None and certificate.no_renewal_from is not None:
                service.clear_no_renewal(cert_id)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- training


class TrainingDialog(_PersonnelDialog):
    """Add or edit a completed course: course (active ones), completion date and hours."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        staff_id: int = 0,
        training: TrainingView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("training_dialog")
        self._staff_id = staff_id
        self._training = training
        service = context.services.personnel
        wanted = None if training is None else training.course_id
        courses = [] if service is None else service.list_courses(include_inactive=True)
        self._courses: dict[int, CourseView] = {
            course.id: course for course in courses if course.active or course.id == wanted
        }
        self.course_combo = QComboBox(self)
        self.course_combo.setObjectName("course_combo")
        mark_data(self.course_combo)
        for course_id in self._courses:
            self.course_combo.addItem("", course_id)
        if training is not None and training.course_id not in self._courses:
            self.course_combo.addItem(training.course_code, training.course_id)
        self.completed_edit = _date_edit(self, to_qdate(context.as_of))
        self.hours_edit = QLineEdit(self)
        self.hours_edit.setObjectName("hours_edit")
        self.add_field(lambda: QCoreApplication.translate("Personnel", "Course"), self.course_combo)
        self.add_field(
            lambda: QCoreApplication.translate("Personnel", "Completed on"), self.completed_edit
        )
        self.add_field(lambda: QCoreApplication.translate("Personnel", "Hours"), self.hours_edit)
        if training is not None:
            self.course_combo.setCurrentIndex(
                max(0, self.course_combo.findData(training.course_id))
            )
            self.completed_edit.setDate(to_qdate(training.completed_on))
            if training.hours is not None:
                self.hours_edit.setText(format_hours(training.hours, self.language))
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._training is None:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Add training"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Edit training"))
        for index in range(self.course_combo.count()):
            course = self._courses.get(int(self.course_combo.itemData(index)))
            if course is not None:
                self.course_combo.setItemText(index, course_label(course, self.language))
        self.hours_edit.setPlaceholderText(QCoreApplication.translate("Personnel", "Optional"))
        apply_locale(self.completed_edit, self.language)

    def submit(self) -> bool:
        service = self.context.services.personnel
        if service is None:
            return False
        course_id = self.course_combo.currentData()
        if course_id is None:
            show_service_error(self.context, self, ServiceError(REQUIRED, "course_id"), error_label)
            return False
        text = self.hours_edit.text().strip()
        hours: float | None = None
        if text:
            try:
                hours = float(parse_number(text, self.language))
            except FormatError as error:
                show_service_error(self.context, self, _number_error(error, "hours"), error_label)
                return False
        data = TrainingInput(
            course_id=int(course_id),
            completed_on=from_qdate(self.completed_edit.date()),
            hours=hours,
        )
        training = self._training
        staff_id = self._staff_id

        def save() -> None:
            if training is None:
                service.add_training(staff_id, data)
            else:
                service.update_training(training.id, data)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- degree


class DegreeDialog(_PersonnelDialog):
    """Add or edit a degree: level, status, year and field of study."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        staff_id: int = 0,
        degree: DegreeView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("degree_dialog")
        self._staff_id = staff_id
        self._degree = degree
        self.level_combo = QComboBox(self)
        self.level_combo.setObjectName("degree_level_combo")
        for level in DegreeLevel:
            self.level_combo.addItem("", level.value)
        self.status_combo = QComboBox(self)
        self.status_combo.setObjectName("degree_status_combo")
        for status in DegreeStatus:
            self.status_combo.addItem("", status.value)
        self.year_spin = QSpinBox(self)
        self.year_spin.setRange(_NOT_SET, _MAX_YEAR)
        self.year_spin.setValue(_NOT_SET)
        self.field_edit = QLineEdit(self)
        self.field_edit.setObjectName("field_edit")
        self.add_field(lambda: QCoreApplication.translate("Personnel", "Degree"), self.level_combo)
        self.add_field(lambda: QCoreApplication.translate("Personnel", "Status"), self.status_combo)
        self.add_field(lambda: QCoreApplication.translate("Personnel", "Year"), self.year_spin)
        self.add_hinted_field(
            lambda: QCoreApplication.translate("Personnel", "Field"),
            self.field_edit,
            _free_text_hint,
            "field_hint",
        )
        if degree is not None:
            self.level_combo.setCurrentIndex(max(0, self.level_combo.findData(degree.level.value)))
            self.status_combo.setCurrentIndex(
                max(0, self.status_combo.findData(degree.status.value))
            )
            self.year_spin.setValue(_NOT_SET if degree.year is None else degree.year)
            self.field_edit.setText(degree.field or "")
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._degree is None:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Add degree"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Edit degree"))
        for index in range(self.level_combo.count()):
            self.level_combo.setItemText(
                index, degree_level_label(str(self.level_combo.itemData(index)))
            )
        for index in range(self.status_combo.count()):
            self.status_combo.setItemText(
                index, degree_status_label(str(self.status_combo.itemData(index)))
            )
        apply_locale(self.year_spin, self.language)
        self.year_spin.setSpecialValueText(QCoreApplication.translate("Personnel", "Not recorded"))

    def submit(self) -> bool:
        service = self.context.services.personnel
        if service is None:
            return False
        data = DegreeInput(
            level=str(self.level_combo.currentData()),
            status=str(self.status_combo.currentData()),
            year=None if self.year_spin.value() == _NOT_SET else self.year_spin.value(),
            field=self.field_edit.text(),
        )
        degree = self._degree
        staff_id = self._staff_id

        def save() -> None:
            if degree is None:
                service.add_degree(staff_id, data)
            else:
                service.update_degree(degree.id, data)

        return apply_change(self.context, self, error_label, save)


# --------------------------------------------------------------------------- course


class CourseDialog(_PersonnelDialog):
    """Add or edit a course of the course list (A09): code, three labels and the active flag."""

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        course: CourseView | None = None,
    ) -> None:
        super().__init__(context, parent)
        self.setObjectName("course_dialog")
        self._course = course
        self.code_edit = QLineEdit(self)
        self.code_edit.setObjectName("course_code_edit")
        self.label_pt_edit = QLineEdit(self)
        self.label_en_edit = QLineEdit(self)
        self.label_es_edit = QLineEdit(self)
        self.active_check = QCheckBox(self)
        self.active_check.setChecked(True)
        self.add_field(lambda: QCoreApplication.translate("Personnel", "Code"), self.code_edit)
        self.add_field(
            lambda: QCoreApplication.translate("Personnel", "Label (Portuguese)"),
            self.label_pt_edit,
        )
        self.add_field(
            lambda: QCoreApplication.translate("Personnel", "Label (English)"), self.label_en_edit
        )
        self.add_field(
            lambda: QCoreApplication.translate("Personnel", "Label (Spanish)"), self.label_es_edit
        )
        self.form.addRow(self.active_check)
        if course is not None:
            self.code_edit.setText(course.code)
            self.label_pt_edit.setText(course.label_pt_br or "")
            self.label_en_edit.setText(course.label_en_us or "")
            self.label_es_edit.setText(course.label_es_es or "")
            self.active_check.setChecked(course.active)
        self.retranslate()

    def retranslate(self) -> None:
        super().retranslate()
        if self._course is None:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Add course"))
        else:
            self.setWindowTitle(QCoreApplication.translate("Personnel", "Edit course"))
        self.active_check.setText(QCoreApplication.translate("Personnel", "Active"))

    def submit(self) -> bool:
        service = self.context.services.personnel
        if service is None:
            return False
        data = CourseInput(
            code=self.code_edit.text().strip(),
            label_pt_br=self.label_pt_edit.text(),
            label_en_us=self.label_en_edit.text(),
            label_es_es=self.label_es_edit.text(),
            active=self.active_check.isChecked(),
        )
        course = self._course

        def save() -> None:
            if course is None:
                service.create_course(data)
            else:
                service.update_course(course.id, data)

        return apply_change(self.context, self, error_label, save)
