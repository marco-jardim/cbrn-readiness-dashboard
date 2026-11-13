# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels of the codes the budget UI can show (PLAN.md section 6, T5.4).

``DIRSA`` is a proper name, shown unchanged (data). ``OPCW_TRUST_FUND`` is named in each language.
User-defined sources show their own labels (``source_label`` of the service: the language asked
for, then pt-BR, then en-US, then the code). Every error code of the budget service, of the shared
service errors, of the configuration service and every ``FormatError`` code has one explicit
entry; an unknown code is shown as itself, never as an exception.
"""

from collections.abc import Callable, Mapping

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.services.budget import (
    BUILT_IN_SOURCE,
    DUPLICATE_CODE,
    DUPLICATE_ENTRY,
    DUPLICATE_EXECUTION,
    EXECUTION_OUTSIDE_FISCAL_YEAR,
    INVALID_AMOUNT,
    INVALID_CURRENCY,
    INVALID_YEAR,
    NEGATIVE_AMOUNT,
    ORPHAN_EXECUTION,
    SOURCE_IN_USE,
    SOURCE_INACTIVE,
    SourceView,
    source_label,
)
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
from cbrn_dashboard.ui.shell.formatting import (
    AMBIGUOUS_NUMBER,
    EMPTY,
    INVALID_NUMBER,
    TOO_LARGE,
    TOO_MANY_DECIMALS,
)
from cbrn_dashboard.ui.shell.widgets import label_for

__all__ = [
    "ALL_ERROR_CODES",
    "BUILT_IN_SOURCE_CODES",
    "error_label",
    "source_display",
    "source_name",
]

_SOURCE_LABELS: dict[str, Callable[[], str]] = {
    "DIRSA": lambda: "DIRSA",
    "OPCW_TRUST_FUND": lambda: QCoreApplication.translate("Budget", "OPCW Trust Fund"),
}

#: The codes of the built-in funding sources (their names come from this module).
BUILT_IN_SOURCE_CODES: tuple[str, ...] = tuple(_SOURCE_LABELS)

_ERROR_LABELS: dict[str, Callable[[], str]] = {
    # budget service
    DUPLICATE_CODE: lambda: QCoreApplication.translate("Budget", "This code is already in use."),
    INVALID_YEAR: lambda: QCoreApplication.translate("Budget", "The fiscal year is not valid."),
    INVALID_CURRENCY: lambda: QCoreApplication.translate("Budget", "The currency is not valid."),
    NEGATIVE_AMOUNT: lambda: QCoreApplication.translate("Budget", "The amount cannot be negative."),
    INVALID_AMOUNT: lambda: QCoreApplication.translate("Budget", "The amount is not valid."),
    DUPLICATE_ENTRY: lambda: QCoreApplication.translate(
        "Budget", "An entry for this year, source, currency and description already exists."
    ),
    DUPLICATE_EXECUTION: lambda: QCoreApplication.translate(
        "Budget", "An execution row with this date and amount already exists."
    ),
    SOURCE_IN_USE: lambda: QCoreApplication.translate(
        "Budget", "The source is used by an entry and cannot be deleted. Deactivate it instead."
    ),
    BUILT_IN_SOURCE: lambda: QCoreApplication.translate(
        "Budget", "A built-in source cannot be deleted and its code cannot change."
    ),
    SOURCE_INACTIVE: lambda: QCoreApplication.translate(
        "Budget", "An inactive source cannot receive new entries."
    ),
    EXECUTION_OUTSIDE_FISCAL_YEAR: lambda: QCoreApplication.translate(
        "Budget", "An execution row is dated outside the fiscal year of its entry."
    ),
    ORPHAN_EXECUTION: lambda: QCoreApplication.translate(
        "Budget", "An execution row refers to an entry that does not exist."
    ),
    # shared service errors
    READ_ONLY: lambda: QCoreApplication.translate(
        "Budget", "The data is read-only: nothing was saved."
    ),
    NOT_FOUND: lambda: QCoreApplication.translate("Budget", "The record no longer exists."),
    REQUIRED: lambda: QCoreApplication.translate("Budget", "A required field is empty."),
    INVALID_DATE: lambda: QCoreApplication.translate("Budget", "The date is not valid."),
    LABEL_PT_BR_REQUIRED: lambda: QCoreApplication.translate(
        "Budget", "The Portuguese (Brazil) label is required."
    ),
    CODE_IMMUTABLE: lambda: QCoreApplication.translate(
        "Budget", "The code cannot be changed because entries already use it."
    ),
    INVALID_CODE: lambda: QCoreApplication.translate(
        "Budget",
        "Use only letters, digits, dot, hyphen and underscore; start with a letter or digit.",
    ),
    # typed numbers and amounts (FormatError codes)
    EMPTY: lambda: QCoreApplication.translate("Budget", "Enter a value."),
    INVALID_NUMBER: lambda: QCoreApplication.translate("Budget", "The number is not valid."),
    AMBIGUOUS_NUMBER: lambda: QCoreApplication.translate(
        "Budget", "The number uses the separators of another language."
    ),
    TOO_MANY_DECIMALS: lambda: QCoreApplication.translate(
        "Budget", "The amount has more decimal places than the currency allows."
    ),
    TOO_LARGE: lambda: QCoreApplication.translate("Budget", "The amount is too large."),
    # configuration service
    "BACKUP_FLOOR": lambda: QCoreApplication.translate(
        "Budget", "The backup setting is below the allowed minimum."
    ),
    "INVALID_PPE_LEVEL": lambda: QCoreApplication.translate(
        "Budget", "The PPE level is not valid."
    ),
    "INVALID_TEXT": lambda: QCoreApplication.translate("Budget", "The text is not valid."),
    "INVALID_TYPE": lambda: QCoreApplication.translate("Budget", "The value has the wrong type."),
    "INVALID_VALIDITY_MONTHS": lambda: QCoreApplication.translate(
        "Budget", "The validity in months is not valid."
    ),
    "NEGATIVE_DAYS": lambda: QCoreApplication.translate(
        "Budget", "The number of days cannot be negative."
    ),
    "PASSPHRASE_FLOOR": lambda: QCoreApplication.translate(
        "Budget", "The passphrase setting is below the allowed minimum."
    ),
    "THRESHOLD_TOO_LOW": lambda: QCoreApplication.translate(
        "Budget", "The threshold is below the allowed minimum."
    ),
    "VALUE_TOO_LARGE": lambda: QCoreApplication.translate("Budget", "The value is too large."),
    "CORRUPT_SETTING": lambda: QCoreApplication.translate(
        "Budget", "A stored setting cannot be read."
    ),
    "UNKNOWN_PLACEHOLDER": lambda: QCoreApplication.translate(
        "Budget", "This placeholder is not known."
    ),
}

#: Every error code the budget UI can present (for the completeness test).
ALL_ERROR_CODES: tuple[str, ...] = tuple(dict.fromkeys((*_ERROR_LABELS, *CONFIG_ERROR_CODES)))


def error_label(code: str) -> str:
    """The translated message of an error code (the code itself when unknown)."""
    return label_for(_ERROR_LABELS, code)


def source_display(source: SourceView, lang: str) -> str:
    """The name of a funding source: the UI's own name for built-in ones, else its label."""
    if source.built_in or source.code in _SOURCE_LABELS:
        return label_for(_SOURCE_LABELS, source.code)
    return source_label(source, lang)


def source_name(code: str, lang: str, sources: Mapping[str, SourceView]) -> str:
    """The name of the source with ``code`` (the code itself when it is not in ``sources``)."""
    source = sources.get(code)
    if source is not None:
        return source_display(source, lang)
    return label_for(_SOURCE_LABELS, code)
