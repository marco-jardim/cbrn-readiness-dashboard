# SPDX-License-Identifier: GPL-3.0-or-later
"""The first-run data-protection notice and the backup reminder (PLAN.md T7.5; D02, D03, D04, A12).

Two start-up hooks of ``app.py`` call into this module:

* :func:`first_run_startup` shows the notice ONCE, through the prompts interface, and remembers it
  in ``prefs.json`` (``first_run_notice_shown``). In read-only mode the preferences stay in memory
  (the data folder is not written), so the notice comes back at the next start; that is the price
  of writing nothing to a read-only folder. With a demo database it is not shown at all and the
  flag is left alone: nothing real can be entered there, and the notice must still be shown before
  real data is. The hook is registered with ``runs_in_demo=False``.
* :func:`backup_reminder_startup` sets the reminder flag of the context when the last encrypted
  backup is older than P09 days, or when none was ever made. The main window shows the
  ``BACKUP_REMINDER`` banner from that flag. It only reads, so it also runs in read-only mode.

Every text goes through ``QCoreApplication.translate("Shell", ...)`` with a literal source string.
Log lines carry event codes only.
"""

from pathlib import Path

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.logging_setup import log_event
from cbrn_dashboard.services.backup import BackupService
from cbrn_dashboard.storage.backup import DatabaseIdentity
from cbrn_dashboard.ui.shell.context import AppContext

__all__ = [
    "backup_reminder_startup",
    "first_run_notice_text",
    "first_run_notice_title",
    "first_run_startup",
    "refresh_backup_reminder",
]


def first_run_notice_title() -> str:
    """The title of the first-run notice."""
    return QCoreApplication.translate("Shell", "Data protection notice")


def first_run_notice_text(data_folder: Path) -> str:
    """The text of the first-run notice, paragraph by paragraph, for ``data_folder``.

    It says where the data lives; that full-disk encryption is required by the documentation
    (D03), cannot be checked by the application and does not protect exported files on removable
    media; how backups work; that "sensitive" is not a formal classification and that real data
    must not be entered before Q19, Q4, Q11 and Q13 are answered; and how several people can share
    one machine (A12).
    """
    location = QCoreApplication.translate(
        "Shell", "Your data is stored only on this computer, in this folder: %1"
    ).replace("%1", str(data_folder))
    encryption = QCoreApplication.translate(
        "Shell",
        "Disk encryption: the documentation requires full-disk encryption of this computer "
        "(for example BitLocker). This application cannot check whether it is on, and it does "
        "not protect files that you export or copy to removable media.",
    )
    backups = QCoreApplication.translate(
        "Shell",
        "Backups: a plain copy of the database is made automatically once a day in the backups "
        "folder of the data folder. Encrypted backups are made by hand to a place that you "
        "choose; keep them on separate media. A lost passphrase cannot be recovered.",
    )
    classification = QCoreApplication.translate(
        "Shell",
        'Classification: "sensitive" is only a working label for data that stays on this '
        "computer; it is not a formal classification. Do not enter real data until the "
        "classification question (Q19) and the questions Q4, Q11 and Q13 have been answered. "
        "Until then use only demo data.",
    )
    shared = QCoreApplication.translate(
        "Shell",
        "Shared computer: several people can take turns on one computer only with one shared "
        "Windows account, or with --data-dir pointing to a local folder restricted to the "
        "committee. With separate Windows accounts each person gets a separate database.",
    )
    return "\n\n".join((location, encryption, backups, classification, shared))


def first_run_startup(context: AppContext) -> None:
    """``StartupHook.run``: show the notice once and remember that it was shown."""
    if context.preferences.current.first_run_notice_shown:
        return
    context.prompts.info(
        None, first_run_notice_title(), first_run_notice_text(context.location.path)
    )
    # In read-only mode the store keeps this in memory only and writes nothing.
    context.preferences.update(first_run_notice_shown=True)
    log_event("APP.FIRST_RUN_NOTICE_SHOWN")


def refresh_backup_reminder(context: AppContext) -> None:
    """Re-read the time of the last encrypted backup and update the reminder flag of ``context``.

    The backup interface calls this after a successful backup, which hides the banner.
    """
    conn = context.conn
    if conn is None:
        return
    service = BackupService(
        conn, context.clock, data_dir=context.location.path, identity=DatabaseIdentity.REAL
    )
    context.set_backup_reminder(service.encrypted_backup_reminder_due())


def backup_reminder_startup(context: AppContext) -> None:
    """``StartupHook.run``: raise the reminder when the last encrypted backup is too old."""
    refresh_backup_reminder(context)
