# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels of the codes the Settings UI can show (PLAN.md section 6, T6.1).

Indicator codes, units, directions, settings groups, dimension keys and every error code of the
configuration service, of the indicator service, of the shared service errors and of the number
parser have one explicit entry; an unknown code is shown as itself, never as an exception.
Dimension VALUES (``A``, ``DIRSA``, ...) are data and are shown unchanged.
"""

import re
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.services.config import CONFIG_ERROR_CODES, CORRUPT_SETTING, UNKNOWN_PLACEHOLDER
from cbrn_dashboard.services.errors import NOT_FOUND, READ_ONLY, REQUIRED
from cbrn_dashboard.services.indicators import (
    INVALID_DIMENSION,
    INVALID_NUMBER,
    TARGET_EMPTY,
    TARGET_NOT_FINITE,
    TARGET_ORDER,
    TARGET_OUT_OF_RANGE,
    UNKNOWN_INDICATOR,
)
from cbrn_dashboard.ui.shell.formatting import AMBIGUOUS_NUMBER, EMPTY, TOO_LARGE
from cbrn_dashboard.ui.shell.widgets import label_for

__all__ = [
    "ALL_ERROR_CODES",
    "GROUP_CODES",
    "INDICATOR_CODES",
    "dimension_text",
    "direction_label",
    "error_label",
    "fill_placeholders",
    "group_label",
    "indicator_label",
    "unit_label",
]

_ERROR_LABELS: dict[str, Callable[[], str]] = {
    # configuration service
    "BACKUP_FLOOR": lambda: QCoreApplication.translate(
        "Settings", "The backup setting is below the allowed minimum."
    ),
    "INVALID_CURRENCY": lambda: QCoreApplication.translate(
        "Settings", "The currency is not valid."
    ),
    "INVALID_PPE_LEVEL": lambda: QCoreApplication.translate(
        "Settings", "The PPE level is not valid."
    ),
    "INVALID_TEXT": lambda: QCoreApplication.translate("Settings", "The text is not valid."),
    "INVALID_TYPE": lambda: QCoreApplication.translate("Settings", "The value has the wrong type."),
    "INVALID_VALIDITY_MONTHS": lambda: QCoreApplication.translate(
        "Settings", "The validity in months is not valid."
    ),
    "NEGATIVE_DAYS": lambda: QCoreApplication.translate(
        "Settings", "The number of days cannot be negative."
    ),
    "PASSPHRASE_FLOOR": lambda: QCoreApplication.translate(
        "Settings", "The passphrase setting is below the allowed minimum."
    ),
    "THRESHOLD_TOO_LOW": lambda: QCoreApplication.translate(
        "Settings", "The threshold is below the allowed minimum."
    ),
    "VALUE_TOO_LARGE": lambda: QCoreApplication.translate("Settings", "The value is too large."),
    CORRUPT_SETTING: lambda: QCoreApplication.translate(
        "Settings", "A stored setting cannot be read."
    ),
    UNKNOWN_PLACEHOLDER: lambda: QCoreApplication.translate(
        "Settings", "This placeholder is not known."
    ),
    # indicator service
    UNKNOWN_INDICATOR: lambda: QCoreApplication.translate(
        "Settings", "The indicator is not known."
    ),
    INVALID_DIMENSION: lambda: QCoreApplication.translate(
        "Settings", "The dimension is not valid for this indicator."
    ),
    INVALID_NUMBER: lambda: QCoreApplication.translate("Settings", "The number is not valid."),
    TARGET_ORDER: lambda: QCoreApplication.translate(
        "Settings", "Warning and critical values are in the wrong order for this indicator."
    ),
    TARGET_NOT_FINITE: lambda: QCoreApplication.translate(
        "Settings", "A threshold must be a finite number."
    ),
    TARGET_EMPTY: lambda: QCoreApplication.translate(
        "Settings", "Enter at least one threshold or delete the target."
    ),
    TARGET_OUT_OF_RANGE: lambda: QCoreApplication.translate(
        "Settings", "The percentage must be between 0% and 1000%."
    ),
    # shared service errors
    READ_ONLY: lambda: QCoreApplication.translate(
        "Settings", "The data is read-only: nothing was saved."
    ),
    NOT_FOUND: lambda: QCoreApplication.translate("Settings", "The record no longer exists."),
    REQUIRED: lambda: QCoreApplication.translate("Settings", "A required field is empty."),
    # typed numbers (FormatError codes)
    EMPTY: lambda: QCoreApplication.translate("Settings", "Enter a value."),
    AMBIGUOUS_NUMBER: lambda: QCoreApplication.translate(
        "Settings", "The number uses the separators of another language."
    ),
    TOO_LARGE: lambda: QCoreApplication.translate("Settings", "The number is too large."),
}

# Every error code the Settings UI can present (for the completeness test).
ALL_ERROR_CODES: tuple[str, ...] = tuple(dict.fromkeys((*_ERROR_LABELS, *CONFIG_ERROR_CODES)))

_INDICATOR_LABELS: dict[str, Callable[[], str]] = {
    # The same wording as the dashboard (ui/dashboard/labels.py), which follows PLAN.md 5.4.
    "PERS_CERT_VALID": lambda: QCoreApplication.translate(
        "Settings", "Staff with a valid certificate"
    ),
    "PERS_CERT_EXPIRING": lambda: QCoreApplication.translate(
        "Settings", "Certificates expiring soon"
    ),
    "PERS_RETRAINING_NEEDED": lambda: QCoreApplication.translate(
        "Settings", "Staff needing retraining"
    ),
    "PERS_DEGREE": lambda: QCoreApplication.translate("Settings", "Staff with a degree"),
    "PERS_TRAINING_12M": lambda: QCoreApplication.translate(
        "Settings", "Training records in the last 12 months"
    ),
    "INFRA_AVAILABLE": lambda: QCoreApplication.translate("Settings", "Available units"),
    "INFRA_MAINT_OVERDUE": lambda: QCoreApplication.translate(
        "Settings", "Units with overdue maintenance"
    ),
    "EX_LAST_PARTICIPANTS": lambda: QCoreApplication.translate(
        "Settings", "Participants in the latest exercise"
    ),
    "EX_LAST_COUNTRIES": lambda: QCoreApplication.translate(
        "Settings", "Countries in the latest exercise"
    ),
    "EX_DAYS_SINCE_LAST": lambda: QCoreApplication.translate(
        "Settings", "Days since the latest exercise"
    ),
    "BUD_EXEC_RATE": lambda: QCoreApplication.translate("Settings", "Budget execution rate"),
}

# The indicator codes this module can name (the registry is checked against it by a test).
INDICATOR_CODES: tuple[str, ...] = tuple(_INDICATOR_LABELS)

_UNIT_LABELS: dict[str, Callable[[], str]] = {
    "COUNT": lambda: QCoreApplication.translate("Settings", "Count"),
    "RATIO": lambda: QCoreApplication.translate("Settings", "Percent"),
    "CURRENCY": lambda: QCoreApplication.translate("Settings", "Amount of money"),
    "DAYS": lambda: QCoreApplication.translate("Settings", "Days"),
}

_DIRECTION_LABELS: dict[str, Callable[[], str]] = {
    "HIGHER_IS_BETTER": lambda: QCoreApplication.translate("Settings", "Higher is better"),
    "LOWER_IS_BETTER": lambda: QCoreApplication.translate("Settings", "Lower is better"),
}

_GROUP_LABELS: dict[str, Callable[[], str]] = {
    "general": lambda: QCoreApplication.translate("Settings", "General settings"),
    "alerts": lambda: QCoreApplication.translate("Settings", "Alerts"),
    "targets": lambda: QCoreApplication.translate("Settings", "Targets"),
    "personnel": lambda: QCoreApplication.translate("Settings", "Personnel"),
    "infrastructure": lambda: QCoreApplication.translate("Settings", "Infrastructure"),
    "exercises": lambda: QCoreApplication.translate("Settings", "Exercises"),
    "budget": lambda: QCoreApplication.translate("Settings", "Budget"),
    "backup": lambda: QCoreApplication.translate("Settings", "Backup"),
    "reports": lambda: QCoreApplication.translate("Settings", "Reports"),
    "snapshots": lambda: QCoreApplication.translate("Settings", "Snapshots"),
}

# The settings group codes this module can name (checked against the registry by a test).
GROUP_CODES: tuple[str, ...] = tuple(_GROUP_LABELS)

_DIMENSION_KEY_LABELS: dict[str, Callable[[], str]] = {
    "level": lambda: QCoreApplication.translate("Settings", "Level"),
    "status": lambda: QCoreApplication.translate("Settings", "Status"),
    "kind": lambda: QCoreApplication.translate("Settings", "Kind"),
    "type": lambda: QCoreApplication.translate("Settings", "Type"),
    "currency": lambda: QCoreApplication.translate("Settings", "Currency"),
    "source": lambda: QCoreApplication.translate("Settings", "Source"),
}


def error_label(code: str) -> str:
    """The translated message of an error code (the code itself when unknown)."""
    return label_for(_ERROR_LABELS, code)


def indicator_label(code: str) -> str:
    """The translated name of an indicator (the code itself when unknown)."""
    return label_for(_INDICATOR_LABELS, code)


def unit_label(code: str) -> str:
    """The translated name of an indicator unit (the code itself when unknown)."""
    return label_for(_UNIT_LABELS, code)


def direction_label(code: str) -> str:
    """The translated name of an indicator direction (the code itself when unknown)."""
    return label_for(_DIRECTION_LABELS, code)


def group_label(code: str) -> str:
    """The translated name of a settings group (the code itself when unknown)."""
    return label_for(_GROUP_LABELS, code)


_PLACEHOLDER = re.compile(r"%([1-9])")


def fill_placeholders(text: str, *values: str) -> str:
    """Replace ``%1``..``%9`` by ``values`` in ONE pass (a translation may reorder them).

    A value that itself contains ``%2`` is inserted as it is, never replaced again.
    """

    def substitute(match: re.Match[str]) -> str:
        position = int(match.group(1)) - 1
        return values[position] if position < len(values) else match.group(0)

    return _PLACEHOLDER.sub(substitute, text)


def dimension_text(dimension: str) -> str:
    """An encoded dimension (``key=value;key=value``) with translated keys; values unchanged."""
    if not dimension:
        return QCoreApplication.translate("Settings", "No dimension")
    text = ""
    for position, part in enumerate(dimension.split(";")):
        key, separator, value = part.partition("=")
        shown = part
        if separator:
            shown = fill_placeholders(
                QCoreApplication.translate("Settings", "%1: %2"),
                label_for(_DIMENSION_KEY_LABELS, key),
                value,
            )
        if position == 0:
            text = shown
        else:
            text = fill_placeholders(QCoreApplication.translate("Settings", "%1; %2"), text, shown)
    return text
