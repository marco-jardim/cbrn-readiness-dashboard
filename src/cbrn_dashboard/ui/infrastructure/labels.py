# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels of the codes the infrastructure UI can show (PLAN.md section 6, T3.4).

The four built-in asset types (``bed``, ``bay``, ``neg_pressure_filtration``, ``decon_tent``) have
no labels in the database: their names live here. A user-defined type is named by its own labels
(data) with the fallback of :func:`~cbrn_dashboard.services.infrastructure.type_label`. Every error
code of the infrastructure service, of the shared service errors and of the configuration service
has one explicit entry; an unknown code is shown as itself, never as an exception.
"""

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.domain.infrastructure import (
    AssetRow,
    AssetStatus,
    MaintenanceKind,
    ScheduleBasis,
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
from cbrn_dashboard.services.infrastructure import (
    BUILT_IN_TYPE,
    DUPLICATE_CODE,
    DUPLICATE_MAINTENANCE,
    DUPLICATE_TAG,
    IN_SERVICE_UNTIL_BEFORE_FROM,
    INITIAL_STATUS_REQUIRED,
    INVALID_INTERVAL,
    INVALID_MAINTENANCE_KIND,
    INVALID_STATUS,
    NEGATIVE_INTERVAL,
    NEXT_DUE_BEFORE_PERFORMED,
    ONLY_STATUS_EVENT,
    STATUS_DATE_TAKEN,
    TEXT_TOO_LONG,
    TYPE_IN_USE,
    TYPE_INACTIVE,
    AssetTypeView,
    type_label,
)
from cbrn_dashboard.ui.shell.widgets import label_for

__all__ = [
    "ALL_ERROR_CODES",
    "BUILT_IN_TYPE_CODES",
    "STORABLE_STATUSES",
    "basis_label",
    "code_label",
    "error_label",
    "flag_labels",
    "join_labels",
    "kind_label",
    "status_label",
    "type_display",
]

#: The statuses a user can store (``unknown`` is computed, D26).
STORABLE_STATUSES: tuple[AssetStatus, ...] = (
    AssetStatus.OPERATIONAL,
    AssetStatus.DEGRADED,
    AssetStatus.OUT_OF_SERVICE,
)

_BUILT_IN_LABELS: dict[str, Callable[[], str]] = {
    "bed": lambda: QCoreApplication.translate("Infrastructure", "Bed"),
    "bay": lambda: QCoreApplication.translate("Infrastructure", "Bay"),
    "neg_pressure_filtration": lambda: QCoreApplication.translate(
        "Infrastructure", "Negative-pressure and filtration equipment"
    ),
    "decon_tent": lambda: QCoreApplication.translate("Infrastructure", "Decontamination tent"),
}

#: The codes of the built-in asset types.
BUILT_IN_TYPE_CODES: tuple[str, ...] = tuple(_BUILT_IN_LABELS)

_STATUS_LABELS: dict[str, Callable[[], str]] = {
    AssetStatus.OPERATIONAL.value: lambda: QCoreApplication.translate(
        "Infrastructure", "Operational"
    ),
    AssetStatus.DEGRADED.value: lambda: QCoreApplication.translate("Infrastructure", "Degraded"),
    AssetStatus.OUT_OF_SERVICE.value: lambda: QCoreApplication.translate(
        "Infrastructure", "Out of service"
    ),
    AssetStatus.UNKNOWN.value: lambda: QCoreApplication.translate("Infrastructure", "Unknown"),
}

_KIND_LABELS: dict[str, Callable[[], str]] = {
    MaintenanceKind.PREVENTIVE.value: lambda: QCoreApplication.translate(
        "Infrastructure", "Preventive"
    ),
    MaintenanceKind.CORRECTIVE.value: lambda: QCoreApplication.translate(
        "Infrastructure", "Corrective"
    ),
    MaintenanceKind.INSPECTION.value: lambda: QCoreApplication.translate(
        "Infrastructure", "Inspection"
    ),
}

_BASIS_LABELS: dict[str, Callable[[], str]] = {
    ScheduleBasis.RECORDED_NEXT_DUE.value: lambda: QCoreApplication.translate(
        "Infrastructure", "Recorded next due date"
    ),
    ScheduleBasis.PREVENTIVE_PLUS_INTERVAL.value: lambda: QCoreApplication.translate(
        "Infrastructure", "Last preventive maintenance plus interval"
    ),
    ScheduleBasis.IN_SERVICE_PLUS_INTERVAL.value: lambda: QCoreApplication.translate(
        "Infrastructure", "In service date plus interval"
    ),
    ScheduleBasis.NO_SCHEDULED_MAINTENANCE.value: lambda: QCoreApplication.translate(
        "Infrastructure", "No scheduled maintenance"
    ),
    ScheduleBasis.UNKNOWN.value: lambda: QCoreApplication.translate(
        "Infrastructure", "No interval or maintenance record"
    ),
}

_ERROR_LABELS: dict[str, Callable[[], str]] = {
    # shared service errors
    READ_ONLY: lambda: QCoreApplication.translate(
        "Infrastructure", "The data is read-only: nothing was saved."
    ),
    NOT_FOUND: lambda: QCoreApplication.translate("Infrastructure", "The record no longer exists."),
    REQUIRED: lambda: QCoreApplication.translate("Infrastructure", "A required field is empty."),
    INVALID_DATE: lambda: QCoreApplication.translate("Infrastructure", "The date is not valid."),
    LABEL_PT_BR_REQUIRED: lambda: QCoreApplication.translate(
        "Infrastructure", "The Portuguese (Brazil) label is required."
    ),
    CODE_IMMUTABLE: lambda: QCoreApplication.translate(
        "Infrastructure", "The code cannot be changed because assets already use it."
    ),
    INVALID_CODE: lambda: QCoreApplication.translate(
        "Infrastructure",
        "Use only letters, digits, dot, hyphen and underscore; start with a letter or digit.",
    ),
    # infrastructure service errors
    DUPLICATE_CODE: lambda: QCoreApplication.translate(
        "Infrastructure", "This code is already in use."
    ),
    NEGATIVE_INTERVAL: lambda: QCoreApplication.translate(
        "Infrastructure", "The maintenance interval cannot be negative."
    ),
    INVALID_INTERVAL: lambda: QCoreApplication.translate(
        "Infrastructure", "The maintenance interval must be a whole number of days."
    ),
    TYPE_IN_USE: lambda: QCoreApplication.translate(
        "Infrastructure", "Assets use this type, so it cannot be deleted. Deactivate it instead."
    ),
    BUILT_IN_TYPE: lambda: QCoreApplication.translate(
        "Infrastructure", "Built-in asset types cannot be deleted or renamed."
    ),
    TYPE_INACTIVE: lambda: QCoreApplication.translate(
        "Infrastructure", "The asset type is inactive and cannot receive new assets."
    ),
    DUPLICATE_TAG: lambda: QCoreApplication.translate(
        "Infrastructure", "This asset tag is already in use."
    ),
    TEXT_TOO_LONG: lambda: QCoreApplication.translate("Infrastructure", "The text is too long."),
    INITIAL_STATUS_REQUIRED: lambda: QCoreApplication.translate(
        "Infrastructure", "Choose the initial status of the asset."
    ),
    IN_SERVICE_UNTIL_BEFORE_FROM: lambda: QCoreApplication.translate(
        "Infrastructure", "The last day in service cannot be before the first day in service."
    ),
    INVALID_STATUS: lambda: QCoreApplication.translate(
        "Infrastructure", "The status is not valid."
    ),
    STATUS_DATE_TAKEN: lambda: QCoreApplication.translate(
        "Infrastructure", "The asset already has a status change on this date."
    ),
    INVALID_MAINTENANCE_KIND: lambda: QCoreApplication.translate(
        "Infrastructure", "The maintenance kind is not valid."
    ),
    NEXT_DUE_BEFORE_PERFORMED: lambda: QCoreApplication.translate(
        "Infrastructure", "The next due date cannot be before the date performed."
    ),
    DUPLICATE_MAINTENANCE: lambda: QCoreApplication.translate(
        "Infrastructure", "A maintenance record of this kind already exists on this date."
    ),
    ONLY_STATUS_EVENT: lambda: QCoreApplication.translate(
        "Infrastructure",
        "This is the only status change of the asset and cannot be deleted. Correct it instead.",
    ),
    # configuration service errors (the A05 switch saves a configuration)
    "INVALID_TYPE": lambda: QCoreApplication.translate(
        "Infrastructure", "The value has the wrong type."
    ),
    "INVALID_PPE_LEVEL": lambda: QCoreApplication.translate(
        "Infrastructure", "The PPE level is not valid."
    ),
    "INVALID_VALIDITY_MONTHS": lambda: QCoreApplication.translate(
        "Infrastructure", "The validity in months is not valid."
    ),
    "VALUE_TOO_LARGE": lambda: QCoreApplication.translate(
        "Infrastructure", "The value is too large."
    ),
    "NEGATIVE_DAYS": lambda: QCoreApplication.translate(
        "Infrastructure", "The number of days cannot be negative."
    ),
    "PASSPHRASE_FLOOR": lambda: QCoreApplication.translate(
        "Infrastructure", "The minimum passphrase length is below the allowed floor."
    ),
    "BACKUP_FLOOR": lambda: QCoreApplication.translate(
        "Infrastructure", "The number of daily backups kept is below the allowed minimum."
    ),
    "THRESHOLD_TOO_LOW": lambda: QCoreApplication.translate(
        "Infrastructure", "The small-count threshold is below the allowed minimum."
    ),
    "INVALID_CURRENCY": lambda: QCoreApplication.translate(
        "Infrastructure", "The currency code is not valid."
    ),
    "INVALID_TEXT": lambda: QCoreApplication.translate("Infrastructure", "The text is not valid."),
    "CORRUPT_SETTING": lambda: QCoreApplication.translate(
        "Infrastructure", "A stored setting cannot be read."
    ),
}

for _config_code in CONFIG_ERROR_CODES:
    # A configuration code added later still gets a (generic) translated message.
    _ERROR_LABELS.setdefault(
        _config_code,
        lambda: QCoreApplication.translate("Infrastructure", "The setting is not valid."),
    )

#: Every error code the infrastructure UI can present (for the completeness test).
ALL_ERROR_CODES: tuple[str, ...] = tuple(_ERROR_LABELS)


def error_label(code: str) -> str:
    """The translated message of an error code (the code itself when unknown)."""
    return label_for(_ERROR_LABELS, code)


def status_label(status: str) -> str:
    """The label of an asset status (``operational``, ``degraded``, ``out_of_service``, ...)."""
    return label_for(_STATUS_LABELS, str(status))


def kind_label(kind: str) -> str:
    """The label of a maintenance kind."""
    return label_for(_KIND_LABELS, str(kind))


def basis_label(basis: str) -> str:
    """The label of the basis of a maintenance due date."""
    return label_for(_BASIS_LABELS, str(basis))


def code_label(type_code: str) -> str:
    """The name of a type given only its code: built-in names are translated, others as is."""
    return label_for(_BUILT_IN_LABELS, type_code)


def type_display(asset_type: AssetTypeView, lang: str) -> str:
    """The name of a type: the translated label of a built-in one, else its own labels."""
    if asset_type.built_in and asset_type.code in _BUILT_IN_LABELS:
        return code_label(asset_type.code)
    return type_label(asset_type, lang)


def join_labels(labels: list[str]) -> str:
    """The texts of ``labels`` as one list, joined with the translated separator."""
    if not labels:
        return ""
    text = labels[0]
    for label in labels[1:]:
        joined = QCoreApplication.translate("Infrastructure", "%1, %2")
        text = joined.replace("%1", text, 1).replace("%2", label, 1)
    return text


def flag_labels(row: AssetRow) -> list[str]:
    """The schedule flags of an asset row as texts (never colour alone, D23)."""
    if not row.in_service:
        return [QCoreApplication.translate("Infrastructure", "Not in service")]
    flags: list[str] = []
    if row.status is AssetStatus.UNKNOWN:
        flags.append(QCoreApplication.translate("Infrastructure", "Status unknown (data quality)"))
    if row.overdue:
        flags.append(QCoreApplication.translate("Infrastructure", "Overdue"))
    if row.due_soon:
        flags.append(QCoreApplication.translate("Infrastructure", "Due soon"))
    if row.schedule_unknown:
        flags.append(QCoreApplication.translate("Infrastructure", "Schedule unknown"))
    if row.basis is ScheduleBasis.NO_SCHEDULED_MAINTENANCE:
        flags.append(QCoreApplication.translate("Infrastructure", "No scheduled maintenance"))
    return flags
