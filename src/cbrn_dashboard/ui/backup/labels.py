# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels of the codes the backup and restore UI can show (PLAN.md section 6, T7.4).

Every error code of the restore service, of the encrypted-backup writer, of the passphrase rule and
of the configuration fields this section edits has one explicit entry; the backup-file codes
(``WRONG_PASSPHRASE``, ``CORRUPT_BACKUP``, ``BACKUP_TOO_NEW``) are among the restore codes. An
unknown code is shown as itself, never as an exception. No label contains a passphrase or a path.
"""

import re
from collections.abc import Callable

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.services.backup import (
    BACKUP_TARGET_EXISTS,
    BACKUP_VERIFY_FAILED,
    BACKUP_WRITE_FAILED,
    PASSPHRASE_BLOCKLISTED,
    PASSPHRASE_MISMATCH,
    PASSPHRASE_TOO_FEW_DISTINCT,
    PASSPHRASE_TOO_SHORT,
)
from cbrn_dashboard.services.errors import READ_ONLY
from cbrn_dashboard.services.restore import (
    BACKUP_TOO_NEW,
    BACKUP_UNREADABLE,
    CORRUPT_BACKUP,
    DEMO_MISMATCH,
    INTEGRITY_FAILED,
    JOURNAL_PRESENT,
    LIVE_UNREADABLE,
    MIGRATION_FAILED,
    NOT_AN_APPLICATION_DATABASE,
    OTHER_CONNECTIONS_OPEN,
    RESTORE_COPY_FAILED,
    RESTORE_ROLLBACK_FAILED,
    SAFETY_COPY_FAILED,
    TEMP_FILE_FAILED,
    TRANSACTION_OPEN,
    WRONG_PASSPHRASE,
)
from cbrn_dashboard.ui.shell.widgets import label_for

__all__ = ["ALL_ERROR_CODES", "error_label", "fill_placeholders"]

_PLACEHOLDER = re.compile(r"%([1-9])")


def fill_placeholders(text: str, *values: str) -> str:
    """Replace ``%1``..``%9`` by ``values`` in ONE pass (a translation may reorder them).

    A value that itself contains ``%2`` is inserted as it is, never replaced again; a placeholder
    without a value is left as it is.
    """

    def substitute(match: re.Match[str]) -> str:
        position = int(match.group(1)) - 1
        return values[position] if position < len(values) else match.group(0)

    return _PLACEHOLDER.sub(substitute, text)


_ERROR_LABELS: dict[str, Callable[[], str]] = {
    # restore: the backup file
    WRONG_PASSPHRASE: lambda: QCoreApplication.translate(
        "Backup", "The passphrase is wrong. Nothing was changed."
    ),
    CORRUPT_BACKUP: lambda: QCoreApplication.translate(
        "Backup", "The backup file is damaged or is not a backup file. Nothing was changed."
    ),
    BACKUP_TOO_NEW: lambda: QCoreApplication.translate(
        "Backup", "The backup was made by a newer version of the program. Nothing was changed."
    ),
    BACKUP_UNREADABLE: lambda: QCoreApplication.translate(
        "Backup", "The backup file cannot be read. Check that it exists and is not in use."
    ),
    NOT_AN_APPLICATION_DATABASE: lambda: QCoreApplication.translate(
        "Backup", "The file is not a backup of this application. Nothing was changed."
    ),
    INTEGRITY_FAILED: lambda: QCoreApplication.translate(
        "Backup", "The backup failed its integrity check. Nothing was changed."
    ),
    DEMO_MISMATCH: lambda: QCoreApplication.translate(
        "Backup", "Demonstration data and real data cannot be exchanged. Nothing was changed."
    ),
    MIGRATION_FAILED: lambda: QCoreApplication.translate(
        "Backup", "The backup could not be upgraded to the current version. Nothing was changed."
    ),
    # restore: the live data
    TEMP_FILE_FAILED: lambda: QCoreApplication.translate(
        "Backup", "A temporary file could not be written in the data folder. Nothing was changed."
    ),
    OTHER_CONNECTIONS_OPEN: lambda: QCoreApplication.translate(
        "Backup", "Another part of the program is using the data. Close it and try again."
    ),
    TRANSACTION_OPEN: lambda: QCoreApplication.translate(
        "Backup", "A change is still being saved. Try again in a moment."
    ),
    JOURNAL_PRESENT: lambda: QCoreApplication.translate(
        "Backup", "An unfinished write was found in the data folder. Restart the program."
    ),
    LIVE_UNREADABLE: lambda: QCoreApplication.translate(
        "Backup", "The current data could not be read, so nothing was restored."
    ),
    SAFETY_COPY_FAILED: lambda: QCoreApplication.translate(
        "Backup", "A safety copy of the current data could not be made, so nothing was restored."
    ),
    RESTORE_COPY_FAILED: lambda: QCoreApplication.translate(
        "Backup", "The restore failed while copying. The previous data was put back."
    ),
    RESTORE_ROLLBACK_FAILED: lambda: QCoreApplication.translate(
        "Backup",
        "The restore failed while copying and the previous data could NOT be put back. The data "
        "may be damaged. Close the program and recover the data from the safety copy %1, which "
        "is beside the database in the data folder.",
    ),
    READ_ONLY: lambda: QCoreApplication.translate(
        "Backup", "The data is read-only: nothing was changed."
    ),
    # backup: the passphrase and the file
    PASSPHRASE_MISMATCH: lambda: QCoreApplication.translate(
        "Backup", "The two passphrases are different."
    ),
    PASSPHRASE_TOO_SHORT: lambda: QCoreApplication.translate(
        "Backup", "The passphrase is too short."
    ),
    PASSPHRASE_TOO_FEW_DISTINCT: lambda: QCoreApplication.translate(
        "Backup", "The passphrase uses too few different characters."
    ),
    PASSPHRASE_BLOCKLISTED: lambda: QCoreApplication.translate(
        "Backup", "The passphrase is too easy to guess. Choose another one."
    ),
    BACKUP_WRITE_FAILED: lambda: QCoreApplication.translate(
        "Backup", "The backup file could not be written. Check the chosen location."
    ),
    BACKUP_VERIFY_FAILED: lambda: QCoreApplication.translate(
        "Backup", "The backup file was written but could not be read back, so it was deleted."
    ),
    BACKUP_TARGET_EXISTS: lambda: QCoreApplication.translate(
        "Backup", "A backup file with that name already exists. Choose another name."
    ),
    # configuration fields of the settings section
    "BACKUP_FLOOR": lambda: QCoreApplication.translate(
        "Backup", "The number of daily backups is below the allowed minimum."
    ),
    "PASSPHRASE_FLOOR": lambda: QCoreApplication.translate(
        "Backup", "The passphrase length is below the allowed minimum."
    ),
    "NEGATIVE_DAYS": lambda: QCoreApplication.translate(
        "Backup", "The number of days cannot be negative."
    ),
    "VALUE_TOO_LARGE": lambda: QCoreApplication.translate("Backup", "The value is too large."),
    "INVALID_TYPE": lambda: QCoreApplication.translate("Backup", "The value has the wrong type."),
    "CORRUPT_SETTING": lambda: QCoreApplication.translate(
        "Backup", "A stored setting cannot be read."
    ),
    "UNKNOWN_PLACEHOLDER": lambda: QCoreApplication.translate(
        "Backup", "This placeholder is not known."
    ),
}

#: Every error code the backup UI can present (for the completeness test).
ALL_ERROR_CODES: tuple[str, ...] = tuple(_ERROR_LABELS)


def error_label(code: str, *values: str) -> str:
    """The translated message of an error code (the code itself when unknown).

    ``values`` fill the ``%1`` placeholders of a message that has some (the safety copy of
    ``RESTORE_ROLLBACK_FAILED``: a file NAME, never a path), in one pass.
    """
    return fill_placeholders(label_for(_ERROR_LABELS, code), *values)
