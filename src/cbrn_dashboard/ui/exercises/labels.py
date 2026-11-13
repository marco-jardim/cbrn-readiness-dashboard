# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels of the codes the exercises UI can show (PLAN.md section 6, T4.5).

``CBRAMED`` and ``EXBRAMED`` are proper names, shown unchanged (data). Every error code of the
exercises service (and of the shared service errors) has one explicit entry; an unknown code is
shown as itself, never as an exception.
"""

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.domain.exercises import ExerciseKind
from cbrn_dashboard.services.errors import (
    CODE_IMMUTABLE,
    INVALID_CODE,
    INVALID_DATE,
    LABEL_PT_BR_REQUIRED,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
)
from cbrn_dashboard.services.exercises import (
    DUPLICATE_CODE,
    END_BEFORE_START,
    INVALID_KIND,
    INVALID_NUMBER,
    METRIC_IN_USE,
    METRIC_INACTIVE,
    NEGATIVE_PARTICIPANTS,
    NEGATIVE_RESPONDENTS,
    ORPHAN_RESULT,
    SCALE_MAX_BELOW_MIN,
    UNKNOWN_COUNTRY,
    VALUE_OUT_OF_SCALE,
)
from cbrn_dashboard.ui.shell.formatting import AMBIGUOUS_NUMBER
from cbrn_dashboard.ui.shell.widgets import label_for

__all__ = ["ALL_ERROR_CODES", "error_label", "kind_label"]

_KIND_LABELS: dict[str, Callable[[], str]] = {
    ExerciseKind.CBRAMED.value: lambda: "CBRAMED",
    ExerciseKind.EXBRAMED.value: lambda: "EXBRAMED",
    ExerciseKind.OTHER.value: lambda: QCoreApplication.translate("Exercises", "Other"),
}

_ERROR_LABELS: dict[str, Callable[[], str]] = {
    DUPLICATE_CODE: lambda: QCoreApplication.translate("Exercises", "This code is already in use."),
    INVALID_KIND: lambda: QCoreApplication.translate(
        "Exercises", "The exercise kind is not valid."
    ),
    END_BEFORE_START: lambda: QCoreApplication.translate(
        "Exercises", "The end date cannot be before the start date."
    ),
    NEGATIVE_PARTICIPANTS: lambda: QCoreApplication.translate(
        "Exercises", "The number of participants cannot be negative."
    ),
    UNKNOWN_COUNTRY: lambda: QCoreApplication.translate(
        "Exercises", "A selected country is not in the country list."
    ),
    VALUE_OUT_OF_SCALE: lambda: QCoreApplication.translate(
        "Exercises", "The value is outside the scale of the metric."
    ),
    SCALE_MAX_BELOW_MIN: lambda: QCoreApplication.translate(
        "Exercises", "The maximum of the scale cannot be below the minimum."
    ),
    NEGATIVE_RESPONDENTS: lambda: QCoreApplication.translate(
        "Exercises", "The number of respondents cannot be negative."
    ),
    METRIC_IN_USE: lambda: QCoreApplication.translate(
        "Exercises", "The metric has results and cannot be deleted. Deactivate it instead."
    ),
    METRIC_INACTIVE: lambda: QCoreApplication.translate(
        "Exercises", "The metric is inactive and cannot receive new results."
    ),
    INVALID_NUMBER: lambda: QCoreApplication.translate("Exercises", "The number is not valid."),
    ORPHAN_RESULT: lambda: QCoreApplication.translate(
        "Exercises", "A result refers to an edition or metric that does not exist."
    ),
    READ_ONLY: lambda: QCoreApplication.translate(
        "Exercises", "The data is read-only: nothing was saved."
    ),
    NOT_FOUND: lambda: QCoreApplication.translate("Exercises", "The record no longer exists."),
    REQUIRED: lambda: QCoreApplication.translate("Exercises", "A required field is empty."),
    INVALID_DATE: lambda: QCoreApplication.translate("Exercises", "The date is not valid."),
    LABEL_PT_BR_REQUIRED: lambda: QCoreApplication.translate(
        "Exercises", "The Portuguese (Brazil) label is required."
    ),
    CODE_IMMUTABLE: lambda: QCoreApplication.translate(
        "Exercises", "The code cannot be changed because results already use it."
    ),
    INVALID_CODE: lambda: QCoreApplication.translate(
        "Exercises",
        "Use only letters, digits, dot, hyphen and underscore; start with a letter or digit.",
    ),
    AMBIGUOUS_NUMBER: lambda: QCoreApplication.translate(
        "Exercises", "The number uses the separators of another language."
    ),
}

#: Every error code the exercises UI can present (for the completeness test).
ALL_ERROR_CODES: tuple[str, ...] = tuple(_ERROR_LABELS)


def error_label(code: str) -> str:
    """The translated message of an error code (the code itself when unknown)."""
    return label_for(_ERROR_LABELS, code)


def kind_label(kind: str) -> str:
    """The label of an exercise kind (``CBRAMED``/``EXBRAMED`` are names, ``OTHER`` is text)."""
    return label_for(_KIND_LABELS, str(kind))
