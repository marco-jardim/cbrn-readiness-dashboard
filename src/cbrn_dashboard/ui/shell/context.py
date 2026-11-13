# SPDX-License-Identifier: GPL-3.0-or-later
"""``AppContext``: what every page and dialog of the shell shares (PLAN.md T1.9, D05, D13, D25).

It holds the open database connection, the clock, the data location, the prompts interface, the
preferences, the translator manager and the module services; the mode flags (read-only, demo,
suspect clock); the as-of date with its change signal (D13); a ``data_changed`` signal for pages
that must refresh; the backup-reminder flag with its change signal (T7.5); and the registry of
edit actions that read-only mode disables.

``is_demo`` is read from ``app_meta.is_demo`` of the OPEN database, never from the command line
(D25). ``ui/`` does not import ``sqlite3``: the connection is typed through
``cbrn_dashboard.storage.db.DatabaseConnection``.
"""

import weakref
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from cbrn_dashboard.clock import Clock
from cbrn_dashboard.paths import DataLocation
from cbrn_dashboard.prefs import PreferencesStore
from cbrn_dashboard.services.alerts import AlertService
from cbrn_dashboard.services.budget import BudgetService
from cbrn_dashboard.services.config import ConfigService
from cbrn_dashboard.services.dashboard import DashboardService
from cbrn_dashboard.services.exercises import ExercisesService
from cbrn_dashboard.services.indicators import IndicatorService
from cbrn_dashboard.services.infrastructure import InfrastructureService
from cbrn_dashboard.services.personnel import PersonnelService
from cbrn_dashboard.services.snapshots import SnapshotService
from cbrn_dashboard.services.validation_export import ValidationExportService
from cbrn_dashboard.storage import app_meta
from cbrn_dashboard.storage.db import DatabaseConnection
from cbrn_dashboard.ui.shell.i18n import TranslatorManager
from cbrn_dashboard.ui.shell.prompts import Prompts

__all__ = ["AppContext", "Services", "build_services"]

type EditTarget = QAction | QWidget


@dataclass
class Services:
    """One attribute per service; ``None`` while no database is open.

    Later tasks (T6.5 dashboard, T7.x backup, T8.x snapshots and reports) add ONE line each here
    and one line in :func:`build_services`.
    """

    personnel: PersonnelService | None = None
    infrastructure: InfrastructureService | None = None
    exercises: ExercisesService | None = None
    budget: BudgetService | None = None
    indicators: IndicatorService | None = None
    alerts: AlertService | None = None
    config: ConfigService | None = None
    dashboard: DashboardService | None = None
    snapshots: SnapshotService | None = None
    validation_export: ValidationExportService | None = None


def build_services(
    conn: DatabaseConnection | None, clock: Clock, operator: Callable[[], str]
) -> Services:
    """The services over ``conn`` (all ``None`` without a connection).

    All of them share the connection, the clock and the operator-label callable.
    """
    if conn is None:
        return Services()
    personnel = PersonnelService(conn, clock, operator)
    infrastructure = InfrastructureService(conn, clock, operator)
    exercises = ExercisesService(conn, clock, operator)
    budget = BudgetService(conn, clock, operator)
    indicators = IndicatorService(
        conn,
        clock,
        operator,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
    )
    alerts = AlertService(personnel=personnel, infrastructure=infrastructure, indicators=indicators)
    dashboard = DashboardService(
        indicators=indicators,
        alerts=alerts,
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
    )
    snapshots = SnapshotService(
        conn, clock, operator, indicators=indicators, infrastructure=infrastructure
    )
    validation_export = ValidationExportService(
        conn, clock, snapshots=snapshots, exercises=exercises, indicators=indicators
    )
    return Services(
        personnel=personnel,
        infrastructure=infrastructure,
        exercises=exercises,
        budget=budget,
        indicators=indicators,
        alerts=alerts,
        config=ConfigService(conn, clock, operator),
        dashboard=dashboard,
        snapshots=snapshots,
        validation_export=validation_export,
    )


class _ReadOnlyGuard(QObject):
    """Event filter that disables a registered widget again whenever it becomes enabled."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.EnabledChange
            and isinstance(watched, QWidget)
            and watched.isEnabled()
        ):
            watched.setEnabled(False)
        return False


class AppContext(QObject):
    """The shared application state; see the module docstring."""

    #: Emitted with the new ``datetime.date`` exactly once per actual change of the as-of date.
    as_of_changed = Signal(object)
    #: Emitted by :meth:`notify_data_changed` after a page stored a change.
    data_changed = Signal()
    #: Emitted with the new value of :attr:`backup_reminder_due` whenever it changes (T7.5).
    backup_reminder_changed = Signal(bool)

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
        self.backup_reminder_due: bool = False
        self._operator_label = ""
        # D13: the as-of date defaults to today at start-up and then stays PINNED until changed
        # (so the context and the toolbar selector cannot disagree after midnight).
        self._as_of: date = clock.local_date()
        self._edit_targets: list[EditTarget] = []
        self._enforcing = False
        self._read_only_guard = _ReadOnlyGuard(self)
        self.services: Services = build_services(conn, clock, self.operator_label)

    # ------------------------------------------------------------------ connection

    @property
    def conn(self) -> DatabaseConnection | None:
        """The open database connection; ``None`` once it was closed."""
        return self._conn

    @conn.setter
    def conn(self, value: DatabaseConnection | None) -> None:
        self._conn = value
        if value is None:
            # The services work over the old connection: after it is closed they would raise on
            # every read (a page re-reading on a posted language change, for one).
            self.services = Services()

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
        """The date every indicator is evaluated for: the local date at start-up unless changed."""
        return self._as_of

    @property
    def is_today(self) -> bool:
        """Whether the as-of date is the clock's CURRENT local date."""
        return self._as_of == self.clock.local_date()

    def set_as_of(self, value: date) -> None:
        """Choose the as-of date; ``as_of_changed`` is emitted once, and not for the same date."""
        if isinstance(value, datetime) or not isinstance(value, date):
            msg = "the as-of date must be a datetime.date"
            raise TypeError(msg)
        if value == self._as_of:
            return
        self._as_of = value
        self.as_of_changed.emit(value)

    def reset_as_of(self) -> None:
        """Set the as-of date to the CURRENT local date; emits only when that is a change."""
        self.set_as_of(self.clock.local_date())

    # ------------------------------------------------------------------ data changes

    def notify_data_changed(self) -> None:
        """Tell the pages that stored data changed."""
        self.data_changed.emit()

    # ------------------------------------------------------------------ backup reminder

    def set_backup_reminder(self, due: bool) -> None:
        """Say whether the last encrypted backup is older than P09; emits only on a change."""
        if due == self.backup_reminder_due:
            return
        self.backup_reminder_due = due
        self.backup_reminder_changed.emit(due)

    # ------------------------------------------------------------------ edit actions

    def register_edit_action(self, target: EditTarget) -> None:
        """Register an action or widget that edits data: disabled whenever the app is read-only.

        In read-only mode the target also stays disabled: a later ``setEnabled(True)`` on it is
        undone at once (``QAction.changed`` for actions, an event filter for widgets).
        """
        is_new = target not in self._edit_targets
        if is_new:
            self._edit_targets.append(target)
        if self.read_only:
            target.setEnabled(False)
            if is_new:
                self._keep_disabled(target)

    def _keep_disabled(self, target: EditTarget) -> None:
        if isinstance(target, QAction):
            ref = weakref.ref(target)

            def disable_again() -> None:
                action = ref()
                if action is None or not isValid(action) or not action.isEnabled():
                    return
                if self._enforcing:
                    return
                self._enforcing = True
                try:
                    action.setEnabled(False)
                finally:
                    self._enforcing = False

            target.changed.connect(disable_again)
        else:
            target.installEventFilter(self._read_only_guard)

    def set_edit_enabled(self, target: EditTarget, enabled: bool) -> None:
        """Enable or disable a registered edit target; read-only mode keeps it disabled."""
        target.setEnabled(enabled and not self.read_only)

    def edit_targets(self) -> tuple[EditTarget, ...]:
        """The registered edit actions and widgets that still exist."""
        self._edit_targets = [target for target in self._edit_targets if isValid(target)]
        return tuple(self._edit_targets)
