# SPDX-License-Identifier: GPL-3.0-or-later
"""``AppContext``: what every page and dialog of the shell shares (PLAN.md T1.9, D05, D13, D25).

It holds the open database connection, the clock, the data location, the prompts interface, the
preferences, the translator manager and the module services; the mode flags (read-only, demo,
suspect clock); the as-of date with its change signal (D13); a ``data_changed`` signal for pages
that must refresh; and the registry of edit actions that read-only mode disables.

``is_demo`` is read from ``app_meta.is_demo`` of the OPEN database, never from the command line
(D25). ``ui/`` does not import ``sqlite3``: the connection is typed through
``cbrn_dashboard.storage.db.DatabaseConnection``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.paths import DataLocation
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.prompts import Prompts

__all__ = ["AppContext", "Services", "build_services"]

type EditTarget = QAction | QWidget


@dataclass
class Services:
    """One attribute per module service; ``None`` while no database is open.

    T2.4 (personnel), T3.4 (infrastructure), T5.4 (budget) and the later services add ONE line
    each here and one line in :func:`build_services`.
    """

    exercises: ExercisesService | None = None


def build_services(
    conn: DatabaseConnection | None, clock: Clock, operator: Callable[[], str]
) -> Services:
    """The services over ``conn`` (all ``None`` without a connection)."""
    if conn is None:
        return Services()
    return Services(exercises=ExercisesService(conn, clock, operator))


class AppContext(QObject):
    """The shared application state; see the module docstring."""

    #: Emitted with the new ``datetime.date`` exactly once per actual change of the as-of date.
    as_of_changed = Signal(object)
    #: Emitted by :meth:`notify_data_changed` after a page stored a change.
    data_changed = Signal()

    def __init__(
        self,
        *,
        conn: DatabaseConnection | None,
        clock: Clock,
        location: DataLocation,
        prompts: Prompts,
        preferences: PreferencesStore,
        translator_manager: TranslatorManager,
        read_only: bool = False,
        clock_suspect: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.clock = clock
        self.location = location
        self.prompts = prompts
        self.preferences = preferences
        self.translator_manager = translator_manager
        self.read_only: bool = read_only or (conn is not None and conn.read_only)
        self.is_demo: bool = conn is not None and app_meta.read_is_demo(conn)
        self.clock_suspect: bool = clock_suspect
        self._operator_label = ""
        self._as_of: date | None = None  # None: follow the clock's local date
        self._edit_targets: list[EditTarget] = []
        self.services: Services = build_services(conn, clock, self.operator_label)

    # ------------------------------------------------------------------ operator label

    def operator_label(self) -> str:
        """The optional operator label (D05) stamped on ``change_log`` rows; may be empty."""
        return self._operator_label

    def set_operator_label(self, label: str) -> None:
        """Change the operator label (the Settings page of T6.1 calls this)."""
        self._operator_label = label

    # ------------------------------------------------------------------ as-of date (D13)

    @property
    def as_of(self) -> date:
        """The date every indicator is evaluated for; today's local date unless changed."""
        return self.clock.local_date() if self._as_of is None else self._as_of

    def set_as_of(self, value: date) -> None:
        """Choose the as-of date; ``as_of_changed`` is emitted once, and not for the same date."""
        if isinstance(value, datetime) or not isinstance(value, date):
            msg = "the as-of date must be a datetime.date"
            raise TypeError(msg)
        if value == self.as_of:
            return
        self._as_of = value
        self.as_of_changed.emit(value)

    def reset_as_of(self) -> None:
        """Go back to following today's date (emits only when the effective date changes)."""
        before = self.as_of
        self._as_of = None
        after = self.as_of
        if after != before:
            self.as_of_changed.emit(after)

    # ------------------------------------------------------------------ data changes

    def notify_data_changed(self) -> None:
        """Tell the pages that stored data changed."""
        self.data_changed.emit()

    # ------------------------------------------------------------------ edit actions

    def register_edit_action(self, target: EditTarget) -> None:
        """Register an action or widget that edits data: disabled whenever the app is read-only."""
        if target not in self._edit_targets:
            self._edit_targets.append(target)
        if self.read_only:
            target.setEnabled(False)

    def set_edit_enabled(self, target: EditTarget, enabled: bool) -> None:
        """Enable or disable a registered edit target; read-only mode keeps it disabled."""
        target.setEnabled(enabled and not self.read_only)

    def edit_targets(self) -> tuple[EditTarget, ...]:
        """The registered edit actions and widgets that still exist."""
        self._edit_targets = [target for target in self._edit_targets if isValid(target)]
        return tuple(self._edit_targets)
