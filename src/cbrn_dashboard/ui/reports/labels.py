# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels of the codes the reports, snapshots and import/export UI can show (T8.7).

Every error code of the snapshot, report, export and import services, of the CSV reader (the codes
of the per-row error report) and of the configuration fields these sections edit has one explicit
entry. The module services report their own codes on an imported row; the common ones have an entry
here and any other code is shown as itself, never as an exception. No label contains a value, a
path or a file name.
"""

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.reports.pdf import REPORT_FAILED
from cbrn_dashboard.services.budget import EXECUTION_OUTSIDE_FISCAL_YEAR
from cbrn_dashboard.services.config import CORRUPT_SETTING, UNKNOWN_PLACEHOLDER
from cbrn_dashboard.services.errors import INVALID_DATE, NOT_FOUND, READ_ONLY, REQUIRED
from cbrn_dashboard.services.exercises import END_BEFORE_START, VALUE_OUT_OF_SCALE
from cbrn_dashboard.services.export import EXPORT_FAILED, UNKNOWN_ENTITY
from cbrn_dashboard.services.importer import (
    BUILT_IN_NOT_ALLOWED,
    DUPLICATE_IN_FILE,
    DUPLICATE_KEY,
    FILE_UNREADABLE,
    STORAGE_REFUSED,
    UNKNOWN_REFERENCE,
)
from cbrn_dashboard.services.personnel import (
    IDENTIFIER_LOOKS_LIKE_NATIONAL_ID,
    INVALID_PPE_LEVEL,
    VALID_UNTIL_BEFORE_ISSUED,
)
from cbrn_dashboard.services.snapshots import (
    ALREADY_WITHDRAWN,
    AS_OF_IN_FUTURE,
    ORIGIN_NOT_ALLOWED,
    REASON_REQUIRED,
)
from cbrn_dashboard.ui.budget.labels import error_label as _budget_error_label
from cbrn_dashboard.ui.exercises.labels import error_label as _exercises_error_label
from cbrn_dashboard.ui.infrastructure.labels import error_label as _infrastructure_error_label
from cbrn_dashboard.ui.personnel.labels import error_label as _personnel_error_label
from cbrn_dashboard.ui.shell.widgets import label_for

#: The label functions of the module pages, asked in turn for a code this UI has no label for.
_MODULE_LABELS: tuple[Callable[[str], str], ...] = (
    _personnel_error_label,
    _infrastructure_error_label,
    _exercises_error_label,
    _budget_error_label,
)

__all__ = [
    "ALL_ERROR_CODES",
    "NO_FILE_CHOSEN",
    "NO_OUTPUT_CHOSEN",
    "entity_label",
    "error_label",
    "origin_label",
    "state_label",
    "variant_label",
]

#: The user chose no output file or folder yet (a code of this UI, not of a service).
NO_OUTPUT_CHOSEN = "NO_OUTPUT_CHOSEN"
#: The user chose no file to import yet (a code of this UI, not of a service).
NO_FILE_CHOSEN = "NO_FILE_CHOSEN"

_ERROR_LABELS: dict[str, Callable[[], str]] = {
    # general
    READ_ONLY: lambda: QCoreApplication.translate(
        "ReportsUi", "The data is read-only: nothing was changed."
    ),
    NOT_FOUND: lambda: QCoreApplication.translate("ReportsUi", "The item no longer exists."),
    INVALID_DATE: lambda: QCoreApplication.translate("ReportsUi", "The date is not valid."),
    NO_OUTPUT_CHOSEN: lambda: QCoreApplication.translate(
        "ReportsUi", "Choose where to write the file first."
    ),
    NO_FILE_CHOSEN: lambda: QCoreApplication.translate(
        "ReportsUi", "Choose the file to import first."
    ),
    # snapshots
    AS_OF_IN_FUTURE: lambda: QCoreApplication.translate(
        "ReportsUi", "The as-of date is in the future."
    ),
    ORIGIN_NOT_ALLOWED: lambda: QCoreApplication.translate(
        "ReportsUi", "This kind of snapshot cannot be recorded."
    ),
    REASON_REQUIRED: lambda: QCoreApplication.translate("ReportsUi", "A reason is required."),
    ALREADY_WITHDRAWN: lambda: QCoreApplication.translate(
        "ReportsUi", "The snapshot was already withdrawn."
    ),
    # reports and exports
    REPORT_FAILED: lambda: QCoreApplication.translate(
        "ReportsUi", "The report file could not be written. Check the chosen location."
    ),
    EXPORT_FAILED: lambda: QCoreApplication.translate(
        "ReportsUi", "The export files could not be written. Check the chosen folder."
    ),
    UNKNOWN_ENTITY: lambda: QCoreApplication.translate(
        "ReportsUi", "This kind of data is not known."
    ),
    # import: the file
    FILE_UNREADABLE: lambda: QCoreApplication.translate(
        "ReportsUi", "The file cannot be read. Check that it exists and is not in use."
    ),
    "NOT_UTF8": lambda: QCoreApplication.translate(
        "ReportsUi", "The file is not valid UTF-8. Save it as UTF-8 and try again."
    ),
    "MALFORMED_CSV": lambda: QCoreApplication.translate(
        "ReportsUi", "The file is not a well-formed CSV file."
    ),
    "HEADER_MISMATCH": lambda: QCoreApplication.translate(
        "ReportsUi", "The header row does not match the template."
    ),
    "DUPLICATE_COLUMN": lambda: QCoreApplication.translate(
        "ReportsUi", "A column appears twice in the header."
    ),
    "UNKNOWN_COLUMN": lambda: QCoreApplication.translate(
        "ReportsUi", "The header has a column that is not in the template."
    ),
    "MISSING_COLUMN": lambda: QCoreApplication.translate(
        "ReportsUi", "A column of the template is missing from the header."
    ),
    # import: a row
    "WRONG_COLUMN_COUNT": lambda: QCoreApplication.translate(
        "ReportsUi", "The row has a different number of columns than the header."
    ),
    "WRONG_FIELD_COUNT": lambda: QCoreApplication.translate(
        "ReportsUi", "The row has the wrong number of fields."
    ),
    REQUIRED: lambda: QCoreApplication.translate("ReportsUi", "A value is required."),
    "INVALID_NUMBER": lambda: QCoreApplication.translate("ReportsUi", "The number is not valid."),
    "INVALID_BOOL": lambda: QCoreApplication.translate(
        "ReportsUi", "The yes/no value is not valid."
    ),
    "INVALID_CURRENCY": lambda: QCoreApplication.translate(
        "ReportsUi", "The currency is not valid."
    ),
    "INVALID_AMOUNT": lambda: QCoreApplication.translate("ReportsUi", "The amount is not valid."),
    "INVALID_VALUE": lambda: QCoreApplication.translate("ReportsUi", "The value is not valid."),
    UNKNOWN_REFERENCE: lambda: QCoreApplication.translate(
        "ReportsUi", "The row refers to an item that does not exist."
    ),
    DUPLICATE_IN_FILE: lambda: QCoreApplication.translate(
        "ReportsUi", "The row repeats an earlier row of the file."
    ),
    DUPLICATE_KEY: lambda: QCoreApplication.translate(
        "ReportsUi", "The item already exists, so the row was refused."
    ),
    BUILT_IN_NOT_ALLOWED: lambda: QCoreApplication.translate(
        "ReportsUi", "Built-in items cannot be imported."
    ),
    STORAGE_REFUSED: lambda: QCoreApplication.translate(
        "ReportsUi", "The stored data refused the row because it breaks one of its rules."
    ),
    # import: codes of the module services that are common in practice
    END_BEFORE_START: lambda: QCoreApplication.translate(
        "ReportsUi", "The end date is before the start date."
    ),
    VALUE_OUT_OF_SCALE: lambda: QCoreApplication.translate(
        "ReportsUi", "The value is outside the scale of the metric."
    ),
    INVALID_PPE_LEVEL: lambda: QCoreApplication.translate(
        "ReportsUi", "The protection level is not valid."
    ),
    VALID_UNTIL_BEFORE_ISSUED: lambda: QCoreApplication.translate(
        "ReportsUi", "The validity ends before the issue date."
    ),
    IDENTIFIER_LOOKS_LIKE_NATIONAL_ID: lambda: QCoreApplication.translate(
        "ReportsUi", "The identifier looks like a national identity number."
    ),
    EXECUTION_OUTSIDE_FISCAL_YEAR: lambda: QCoreApplication.translate(
        "ReportsUi", "The execution date is outside the fiscal year."
    ),
    # configuration fields of the settings sections
    "THRESHOLD_TOO_LOW": lambda: QCoreApplication.translate(
        "ReportsUi", "The threshold must be at least 1."
    ),
    "VALUE_TOO_LARGE": lambda: QCoreApplication.translate("ReportsUi", "The value is too large."),
    "INVALID_TEXT": lambda: QCoreApplication.translate(
        "ReportsUi", "The text is not valid or is too long."
    ),
    "INVALID_TYPE": lambda: QCoreApplication.translate(
        "ReportsUi", "The value has the wrong type."
    ),
    CORRUPT_SETTING: lambda: QCoreApplication.translate(
        "ReportsUi", "A stored setting cannot be read."
    ),
    UNKNOWN_PLACEHOLDER: lambda: QCoreApplication.translate(
        "ReportsUi", "This placeholder is not known."
    ),
}

#: Every error code the reports UI can present (for the completeness test).
ALL_ERROR_CODES: tuple[str, ...] = tuple(_ERROR_LABELS)


def error_label(code: str) -> str:
    """The translated message of an error code.

    A code of this UI first; then the four module label maps (an imported row reports the codes of
    the module services, P8-09); the code itself when nobody knows it.
    """
    if code in _ERROR_LABELS:
        return label_for(_ERROR_LABELS, code)
    for module_label in _MODULE_LABELS:
        text = module_label(code)
        if text != code:
            return text
    return code


_VARIANT_LABELS: dict[str, Callable[[], str]] = {
    "INTERNAL": lambda: QCoreApplication.translate("ReportsUi", "Internal report"),
    "ANONYMISED": lambda: QCoreApplication.translate("ReportsUi", "Anonymised report"),
}


def variant_label(variant: str) -> str:
    """The name of a report variant (``INTERNAL`` or ``ANONYMISED``); unknown: the code itself."""
    return label_for(_VARIANT_LABELS, variant)


_ORIGIN_LABELS: dict[str, Callable[[], str]] = {
    "manual": lambda: QCoreApplication.translate("ReportsUi", "Recorded by hand"),
    "monthly": lambda: QCoreApplication.translate("ReportsUi", "Monthly"),
    "report": lambda: QCoreApplication.translate("ReportsUi", "With a report"),
    "retroactive": lambda: QCoreApplication.translate("ReportsUi", "Retroactive"),
}


def origin_label(origin: str) -> str:
    """The name of a snapshot origin; unknown: the code itself."""
    return label_for(_ORIGIN_LABELS, origin)


def state_label(*, withdrawn: bool) -> str:
    """``Withdrawn`` or ``Active``."""
    if withdrawn:
        return QCoreApplication.translate("ReportsUi", "Withdrawn")
    return QCoreApplication.translate("ReportsUi", "Active")


_ENTITY_LABELS: dict[str, Callable[[], str]] = {
    "training_course": lambda: QCoreApplication.translate("ReportsUi", "Training courses"),
    "asset_type": lambda: QCoreApplication.translate("ReportsUi", "Asset types"),
    "evaluation_metric": lambda: QCoreApplication.translate("ReportsUi", "Evaluation metrics"),
    "funding_source": lambda: QCoreApplication.translate("ReportsUi", "Funding sources"),
    "staff_member": lambda: QCoreApplication.translate("ReportsUi", "Staff"),
    "ppe_certification": lambda: QCoreApplication.translate("ReportsUi", "PPE certificates"),
    "training_record": lambda: QCoreApplication.translate("ReportsUi", "Training records"),
    "academic_degree": lambda: QCoreApplication.translate("ReportsUi", "Academic degrees"),
    "asset": lambda: QCoreApplication.translate("ReportsUi", "Assets"),
    "asset_status_event": lambda: QCoreApplication.translate("ReportsUi", "Asset status events"),
    "maintenance_event": lambda: QCoreApplication.translate("ReportsUi", "Maintenance events"),
    "exercise_edition": lambda: QCoreApplication.translate("ReportsUi", "Exercise editions"),
    "exercise_country": lambda: QCoreApplication.translate("ReportsUi", "Exercise countries"),
    "evaluation_result": lambda: QCoreApplication.translate("ReportsUi", "Evaluation results"),
    "budget_entry": lambda: QCoreApplication.translate("ReportsUi", "Budget entries"),
    "budget_execution": lambda: QCoreApplication.translate("ReportsUi", "Budget executions"),
}


def entity_label(entity: str) -> str:
    """The translated name of an importable entity; unknown: the entity name itself."""
    return label_for(_ENTITY_LABELS, entity)
