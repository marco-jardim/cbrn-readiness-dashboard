# SPDX-License-Identifier: GPL-3.0-or-later
"""Table models of the personnel page and of its settings section (PLAN.md T2.4).

Headers are translated on every ``headerData`` call; cells are formatted for the current language
with the shared formatting functions. Cell contents (identifiers, labels, course names, level
letters) are data.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.domain.personnel import CertStatus, PpeLevel
from cbrn_dashboard.services.personnel import (
    CertificateView,
    CourseView,
    StaffView,
    TrainingView,
    course_label,
)
from cbrn_dashboard.ui.personnel.labels import (
    cert_status_label,
    degree_level_label,
    degree_status_label,
    ppe_level_label,
    reason_label,
)
from cbrn_dashboard.ui.shell.formatting import format_date, format_number
from cbrn_dashboard.ui.shell.widgets import Column, ModuleTableModel

__all__ = [
    "CertificatesModel",
    "CoursesModel",
    "DegreesModel",
    "StaffModel",
    "StaffRow",
    "SummaryModel",
    "TrainingModel",
    "TrainingRow",
    "format_hours",
]

#: A missing value in a cell (data, not a translatable text).
NOT_RECORDED = "-"


def format_hours(value: float, lang: str) -> str:
    """Hours of a course: whole numbers without decimals, locale separators."""
    number: float | int = int(value) if float(value).is_integer() else value
    return format_number(number, lang)


def _optional_date(value: Any, lang: str) -> str:
    return NOT_RECORDED if value is None else format_date(value, lang)


def _level_header(level: PpeLevel) -> str:
    return QCoreApplication.translate("Personnel", "Level %1").replace("%1", level.value)


# --------------------------------------------------------------------------- staff


@dataclass(frozen=True)
class StaffRow:
    """A person with the status of the counting certificate per level on the as-of date.

    ``statuses`` is empty for a person who is not active on that date.
    """

    staff: StaffView
    statuses: Mapping[PpeLevel, CertStatus]


def _status_text(row: StaffRow, level: PpeLevel) -> str:
    status = row.statuses.get(level)
    return NOT_RECORDED if status is None else cert_status_label(status.value)


class StaffModel(ModuleTableModel):
    """The staff: identifier, label, category, active period and the status per level."""

    COLUMNS = (
        Column[Any](
            "identifier",
            lambda: QCoreApplication.translate("Personnel", "Identifier"),
            lambda row, lang: row.staff.identifier,
        ),
        Column[Any](
            "label",
            lambda: QCoreApplication.translate("Personnel", "Label"),
            lambda row, lang: row.staff.label or "",
        ),
        Column[Any](
            "category",
            lambda: QCoreApplication.translate("Personnel", "Category"),
            lambda row, lang: row.staff.category or "",
        ),
        Column[Any](
            "active_from",
            lambda: QCoreApplication.translate("Personnel", "Active from"),
            lambda row, lang: format_date(row.staff.active_from, lang),
        ),
        Column[Any](
            "active_until",
            lambda: QCoreApplication.translate("Personnel", "Active until"),
            lambda row, lang: _optional_date(row.staff.active_until, lang),
        ),
        Column[Any](
            "level_a",
            lambda: _level_header(PpeLevel.A),
            lambda row, lang: _status_text(row, PpeLevel.A),
        ),
        Column[Any](
            "level_b",
            lambda: _level_header(PpeLevel.B),
            lambda row, lang: _status_text(row, PpeLevel.B),
        ),
        Column[Any](
            "level_c",
            lambda: _level_header(PpeLevel.C),
            lambda row, lang: _status_text(row, PpeLevel.C),
        ),
    )


# --------------------------------------------------------------------------- summary


class SummaryModel(ModuleTableModel):
    """The counts per level on the as-of date: valid, expiring, retraining needed."""

    COLUMNS = (
        Column[Any](
            "level",
            lambda: QCoreApplication.translate("Personnel", "Level"),
            lambda row, lang: ppe_level_label(row.level.value),
        ),
        Column[Any](
            "valid",
            lambda: QCoreApplication.translate("Personnel", "Valid"),
            lambda row, lang: format_number(row.valid, lang),
            align_right=True,
        ),
        Column[Any](
            "expiring",
            lambda: QCoreApplication.translate("Personnel", "Expiring"),
            lambda row, lang: format_number(row.expiring, lang),
            align_right=True,
        ),
        Column[Any](
            "retraining",
            lambda: QCoreApplication.translate("Personnel", "Retraining needed"),
            lambda row, lang: format_number(row.retraining_needed, lang),
            align_right=True,
        ),
    )


# --------------------------------------------------------------------------- detail tables


class CertificatesModel(ModuleTableModel):
    """The certificates of the selected person."""

    COLUMNS = (
        Column[Any](
            "level",
            lambda: QCoreApplication.translate("Personnel", "Level"),
            lambda row, lang: ppe_level_label(row.level.value),
        ),
        Column[Any](
            "issued_on",
            lambda: QCoreApplication.translate("Personnel", "Issued on"),
            lambda row, lang: format_date(row.issued_on, lang),
        ),
        Column[Any](
            "valid_until",
            lambda: QCoreApplication.translate("Personnel", "Valid until"),
            lambda row, lang: format_date(row.valid_until, lang),
        ),
        Column[Any](
            "no_renewal_from",
            lambda: QCoreApplication.translate("Personnel", "No renewal from"),
            lambda row, lang: _optional_date(row.no_renewal_from, lang),
        ),
        Column[Any](
            "reason",
            lambda: QCoreApplication.translate("Personnel", "Reason"),
            lambda row, lang: reason_label(row.no_renewal_reason),
        ),
        Column[Any](
            "reference",
            lambda: QCoreApplication.translate("Personnel", "Reference"),
            lambda row, lang: row.reference or "",
        ),
    )

    def set_certificates(self, certificates: list[CertificateView]) -> None:
        self.set_rows(certificates)


@dataclass(frozen=True)
class TrainingRow:
    """A training record with its course (``None`` when the course is unknown)."""

    training: TrainingView
    course: CourseView | None


class TrainingModel(ModuleTableModel):
    """The training records of the selected person."""

    COLUMNS = (
        Column[Any](
            "course",
            lambda: QCoreApplication.translate("Personnel", "Course"),
            lambda row, lang: (
                row.training.course_code if row.course is None else course_label(row.course, lang)
            ),
        ),
        Column[Any](
            "completed_on",
            lambda: QCoreApplication.translate("Personnel", "Completed on"),
            lambda row, lang: format_date(row.training.completed_on, lang),
        ),
        Column[Any](
            "hours",
            lambda: QCoreApplication.translate("Personnel", "Hours"),
            lambda row, lang: (
                NOT_RECORDED
                if row.training.hours is None
                else format_hours(row.training.hours, lang)
            ),
            align_right=True,
        ),
    )

    def set_training(self, records: list[TrainingView], courses: Mapping[int, CourseView]) -> None:
        self.set_rows([TrainingRow(record, courses.get(record.course_id)) for record in records])


class DegreesModel(ModuleTableModel):
    """The degrees of the selected person."""

    COLUMNS = (
        Column[Any](
            "level",
            lambda: QCoreApplication.translate("Personnel", "Degree"),
            lambda row, lang: degree_level_label(row.level.value),
        ),
        Column[Any](
            "status",
            lambda: QCoreApplication.translate("Personnel", "Status"),
            lambda row, lang: degree_status_label(row.status.value),
        ),
        Column[Any](
            "year",
            lambda: QCoreApplication.translate("Personnel", "Year"),
            lambda row, lang: NOT_RECORDED if row.year is None else str(row.year),
            align_right=True,
        ),
        Column[Any](
            "field",
            lambda: QCoreApplication.translate("Personnel", "Field"),
            lambda row, lang: row.field or "",
        ),
    )

    def set_degrees(self, degrees: list[Any]) -> None:
        self.set_rows(degrees)


# --------------------------------------------------------------------------- courses


class CoursesModel(ModuleTableModel):
    """The courses, including the inactive ones, for the settings section (A09)."""

    COLUMNS = (
        Column[Any](
            "code",
            lambda: QCoreApplication.translate("Personnel", "Code"),
            lambda row, lang: row.code,
        ),
        Column[Any](
            "label",
            lambda: QCoreApplication.translate("Personnel", "Label"),
            lambda row, lang: course_label(row, lang),
        ),
        Column[Any](
            "status",
            lambda: QCoreApplication.translate("Personnel", "Status"),
            lambda row, lang: (
                QCoreApplication.translate("Personnel", "Active")
                if row.active
                else QCoreApplication.translate("Personnel", "Inactive")
            ),
        ),
    )
