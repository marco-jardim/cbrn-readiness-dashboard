# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels of the codes the personnel UI can show (PLAN.md section 6, T2.4).

The PPE level letters ``A``/``B``/``C`` are data and are returned unchanged. Every error code of the
personnel service, of the shared service errors and of the configuration service has one explicit
entry; an unknown code is shown as itself, never as an exception.
"""

import re
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.domain.personnel import CertStatus, DegreeLevel, DegreeStatus
from cbrn_dashboard.services.config import CONFIG_ERROR_CODES
from cbrn_dashboard.services.errors import (
    CODE_IMMUTABLE,
    INVALID_CODE,
    INVALID_DATE,
    LABEL_PT_BR_REQUIRED,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
)
from cbrn_dashboard.services.personnel import (
    ACTIVE_UNTIL_BEFORE_FROM,
    COURSE_IN_USE,
    COURSE_INACTIVE,
    DUPLICATE_CERTIFICATE,
    DUPLICATE_CODE,
    DUPLICATE_DEGREE,
    DUPLICATE_IDENTIFIER,
    DUPLICATE_TRAINING,
    IDENTIFIER_LOOKS_LIKE_NATIONAL_ID,
    INVALID_DEGREE_LEVEL,
    INVALID_DEGREE_STATUS,
    INVALID_NO_RENEWAL_REASON,
    INVALID_NUMBER,
    INVALID_PPE_LEVEL,
    INVALID_YEAR,
    NEGATIVE_HOURS,
    NO_RENEWAL_REASON_WITHOUT_DATE,
    PSEUDONYM_COLLISION,
    TEXT_TOO_LONG,
    VALID_UNTIL_BEFORE_ISSUED,
)
from cbrn_dashboard.ui.shell.formatting import AMBIGUOUS_NUMBER
from cbrn_dashboard.ui.shell.widgets import label_for

__all__ = [
    "ALL_ERROR_CODES",
    "cert_status_label",
    "degree_level_label",
    "degree_status_label",
    "error_label",
    "fill_placeholders",
    "ppe_level_label",
    "reason_label",
]

_PLACEHOLDER = re.compile(r"%([1-9])")


def fill_placeholders(text: str, *values: str) -> str:
    """Replace ``%1``..``%9`` by ``values`` in ONE pass.

    A value that itself contains ``%2`` is never substituted again, and a translation may
    reorder the placeholders. Mirrors ``_fill`` of ``ui/alerts/labels.py``.
    """

    def substitute(match: re.Match[str]) -> str:
        position = int(match.group(1)) - 1
        return values[position] if position < len(values) else match.group(0)

    return _PLACEHOLDER.sub(substitute, text)


_DEGREE_LEVEL_LABELS: dict[str, Callable[[], str]] = {
    DegreeLevel.SPECIALISATION.value: lambda: QCoreApplication.translate(
        "Personnel", "Specialisation"
    ),
    DegreeLevel.MASTER.value: lambda: QCoreApplication.translate("Personnel", "Master's degree"),
    DegreeLevel.DOCTORATE.value: lambda: QCoreApplication.translate("Personnel", "Doctorate"),
}

_DEGREE_STATUS_LABELS: dict[str, Callable[[], str]] = {
    DegreeStatus.COMPLETED.value: lambda: QCoreApplication.translate("Personnel", "Completed"),
    DegreeStatus.IN_PROGRESS.value: lambda: QCoreApplication.translate("Personnel", "In progress"),
}

_CERT_STATUS_LABELS: dict[str, Callable[[], str]] = {
    CertStatus.VALID.value: lambda: QCoreApplication.translate("Personnel", "Valid"),
    CertStatus.EXPIRING.value: lambda: QCoreApplication.translate("Personnel", "Expiring"),
    CertStatus.EXPIRED.value: lambda: QCoreApplication.translate("Personnel", "Expired"),
    CertStatus.NO_RENEWAL.value: lambda: QCoreApplication.translate("Personnel", "No renewal"),
    CertStatus.NONE.value: lambda: QCoreApplication.translate("Personnel", "No qualification"),
}

_REASON_LABELS: dict[str, Callable[[], str]] = {
    "left_unit": lambda: QCoreApplication.translate("Personnel", "Left the unit"),
    "role_change": lambda: QCoreApplication.translate("Personnel", "Change of role"),
    "other": lambda: QCoreApplication.translate("Personnel", "Other reason"),
}

_ERROR_LABELS: dict[str, Callable[[], str]] = {
    # --- personnel service
    DUPLICATE_IDENTIFIER: lambda: QCoreApplication.translate(
        "Personnel", "This identifier is already in use."
    ),
    ACTIVE_UNTIL_BEFORE_FROM: lambda: QCoreApplication.translate(
        "Personnel", "The end of the active period cannot be before its start."
    ),
    TEXT_TOO_LONG: lambda: QCoreApplication.translate("Personnel", "The text is too long."),
    IDENTIFIER_LOOKS_LIKE_NATIONAL_ID: lambda: QCoreApplication.translate(
        "Personnel", "The identifier looks like a national ID number. Use a local code instead."
    ),
    INVALID_PPE_LEVEL: lambda: QCoreApplication.translate(
        "Personnel", "The protection level is not valid."
    ),
    VALID_UNTIL_BEFORE_ISSUED: lambda: QCoreApplication.translate(
        "Personnel", "The validity end cannot be before the issue date."
    ),
    DUPLICATE_CERTIFICATE: lambda: QCoreApplication.translate(
        "Personnel", "The person already has a qualification of this level issued on this date."
    ),
    INVALID_NO_RENEWAL_REASON: lambda: QCoreApplication.translate(
        "Personnel", "The reason for no renewal is not valid."
    ),
    NO_RENEWAL_REASON_WITHOUT_DATE: lambda: QCoreApplication.translate(
        "Personnel", "A reason for no renewal needs a date."
    ),
    DUPLICATE_CODE: lambda: QCoreApplication.translate("Personnel", "This code is already in use."),
    COURSE_IN_USE: lambda: QCoreApplication.translate(
        "Personnel",
        "The course has training records and cannot be deleted. Deactivate it instead.",
    ),
    COURSE_INACTIVE: lambda: QCoreApplication.translate(
        "Personnel", "The course is inactive and cannot receive new training records."
    ),
    DUPLICATE_TRAINING: lambda: QCoreApplication.translate(
        "Personnel", "The person already has this course recorded on this date."
    ),
    NEGATIVE_HOURS: lambda: QCoreApplication.translate(
        "Personnel", "The number of hours cannot be negative."
    ),
    INVALID_NUMBER: lambda: QCoreApplication.translate("Personnel", "The number is not valid."),
    INVALID_DEGREE_LEVEL: lambda: QCoreApplication.translate(
        "Personnel", "The degree level is not valid."
    ),
    INVALID_DEGREE_STATUS: lambda: QCoreApplication.translate(
        "Personnel", "The degree status is not valid."
    ),
    INVALID_YEAR: lambda: QCoreApplication.translate("Personnel", "The year is not valid."),
    DUPLICATE_DEGREE: lambda: QCoreApplication.translate(
        "Personnel", "The person already has this degree."
    ),
    PSEUDONYM_COLLISION: lambda: QCoreApplication.translate(
        "Personnel", "No unused random code could be found. Try again."
    ),
    # --- shared service errors
    READ_ONLY: lambda: QCoreApplication.translate(
        "Personnel", "The data is read-only: nothing was saved."
    ),
    NOT_FOUND: lambda: QCoreApplication.translate("Personnel", "The record no longer exists."),
    REQUIRED: lambda: QCoreApplication.translate("Personnel", "A required field is empty."),
    INVALID_DATE: lambda: QCoreApplication.translate("Personnel", "The date is not valid."),
    LABEL_PT_BR_REQUIRED: lambda: QCoreApplication.translate(
        "Personnel", "The Portuguese (Brazil) label is required."
    ),
    CODE_IMMUTABLE: lambda: QCoreApplication.translate(
        "Personnel", "The code cannot be changed because records already use it."
    ),
    INVALID_CODE: lambda: QCoreApplication.translate(
        "Personnel",
        "Use only letters, digits, dot, hyphen and underscore; start with a letter or digit.",
    ),
    AMBIGUOUS_NUMBER: lambda: QCoreApplication.translate(
        "Personnel", "The number uses the separators of another language."
    ),
    # --- configuration service
    "INVALID_TYPE": lambda: QCoreApplication.translate("Personnel", "A value has the wrong type."),
    "INVALID_VALIDITY_MONTHS": lambda: QCoreApplication.translate(
        "Personnel", "The validity must be at least one month."
    ),
    "VALUE_TOO_LARGE": lambda: QCoreApplication.translate("Personnel", "The value is too large."),
    "NEGATIVE_DAYS": lambda: QCoreApplication.translate(
        "Personnel", "The number of days cannot be negative."
    ),
    "PASSPHRASE_FLOOR": lambda: QCoreApplication.translate(
        "Personnel", "The passphrase length is below the allowed minimum."
    ),
    "BACKUP_FLOOR": lambda: QCoreApplication.translate(
        "Personnel", "The number of backups is below the allowed minimum."
    ),
    "THRESHOLD_TOO_LOW": lambda: QCoreApplication.translate(
        "Personnel", "The threshold is below the allowed minimum."
    ),
    "INVALID_CURRENCY": lambda: QCoreApplication.translate(
        "Personnel", "The currency is not valid."
    ),
    "INVALID_TEXT": lambda: QCoreApplication.translate("Personnel", "The text is not valid."),
    "REGISTRY_INVALID": lambda: QCoreApplication.translate(
        "Personnel", "The list of placeholders is not valid."
    ),
    "CORRUPT_SETTING": lambda: QCoreApplication.translate(
        "Personnel", "A stored setting cannot be read."
    ),
    "UNKNOWN_PLACEHOLDER": lambda: QCoreApplication.translate(
        "Personnel", "The placeholder is not known."
    ),
}

#: Every error code the personnel UI can present (for the completeness test); the codes of the
#: configuration service that are not in the table are listed too, so the test shows the gap.
ALL_ERROR_CODES: tuple[str, ...] = tuple(dict.fromkeys((*_ERROR_LABELS, *CONFIG_ERROR_CODES)))


def error_label(code: str) -> str:
    """The translated message of an error code (the code itself when unknown)."""
    return label_for(_ERROR_LABELS, code)


def ppe_level_label(level: str) -> str:
    """The label of a PPE level: the letters ``A``/``B``/``C`` are data, returned unchanged."""
    return str(level)


def degree_level_label(level: str) -> str:
    return label_for(_DEGREE_LEVEL_LABELS, str(level))


def degree_status_label(status: str) -> str:
    return label_for(_DEGREE_STATUS_LABELS, str(status))


def cert_status_label(status: str) -> str:
    return label_for(_CERT_STATUS_LABELS, str(status))


def reason_label(reason: str | None) -> str:
    """The label of a no-renewal reason code (empty for none)."""
    return "" if not reason else label_for(_REASON_LABELS, reason)
