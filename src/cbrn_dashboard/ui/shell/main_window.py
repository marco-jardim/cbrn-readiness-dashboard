# SPDX-License-Identifier: GPL-3.0-or-later
"""The main window: banners, navigation list, page stack, menus, toolbar and status bar
(PLAN.md tasks T0.7 and T1.9).

The window is built from an :class:`~cbrn_dashboard.ui.shell.context.AppContext`. The navigation
and the page stack are filled from the page registry; the toolbar holds the as-of date selector
(D13), bound both ways to ``context.as_of``; the banner area shows the demo, read-only, location,
clock, backup-reminder and translation banners; the demo banner cannot be hidden.

The File menu holds "Back up...", "Restore..." and "Open data folder" (T7.4, the actions of
:class:`~cbrn_dashboard.ui.backup.actions.BackupActions`; the folder is opened by the single helper
of ``ui/shell/folders.py``) and "Quit". The Help menu (T10.2) opens the in-app help (F1, at the
topic of the page shown) and the About dialog, both non-modal and built on the first request.

The status bar holds the alert badge (T6.6): the alert counts by severity for the as-of date. At
start-up, when warning or critical alerts exist and the start-up summary preference is on, the
``ALERT_SUMMARY`` banner appears with a button that opens the Alerts page (information-level alerts
never trigger it). The badge and the banner follow ``as_of_changed`` and ``data_changed``; the
banner, once shown, stays while warning or critical alerts remain. The counts are read through
``context.services.alerts`` each time (it is ``None`` without a database, which hides the badge);
a language change only re-applies the texts of the counts already read.

Every user-visible text is applied in :meth:`MainWindow.retranslate`, which runs once on
construction and again on every ``LanguageChange`` event, so switching the language retitles the
whole window live. Texts go through ``QCoreApplication.translate("Shell", ...)`` (never
``self.tr()``).
"""

from datetime import date
from functools import partial

from PySide6.QtCore import QCoreApplication, QEvent, QRect, Qt
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence, QShowEvent
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard import i18n
from cbrn_dashboard.domain.alerts import Severity
from cbrn_dashboard.logging_setup import log_exception
from cbrn_dashboard.prefs import PreferencesWarning
from cbrn_dashboard.ui.backup.actions import BackupActions
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.about import AboutDialog
from cbrn_dashboard.ui.shell.banners import AlertCounts, BannerArea, BannerCode, alert_badge_text
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.folders import open_local_folder
from cbrn_dashboard.ui.shell.formatting import apply_locale, from_qdate, to_qdate
from cbrn_dashboard.ui.shell.help import HelpDialog
from cbrn_dashboard.ui.shell.i18n import app_display_name, language_display_name
from cbrn_dashboard.ui.shell.widgets import apply_tab_order

_PAGE_KEY_ROLE = Qt.ItemDataRole.UserRole
#: The registry key of the Alerts page (the button of the start-up summary opens it).
ALERTS_PAGE_KEY = "alerts"
#: The smallest window: it still fits a 960 x 540 logical screen (a 1920 x 1080 display at 200%).
MINIMUM_WIDTH = 800
MINIMUM_HEIGHT = 500
#: Free space kept on each side between the window frame and the edge of the available area.
_SCREEN_MARGIN = 8
#: Keyboard shortcuts of the actions that have no mnemonic (the menu entries and the toolbar button
#: whose texts are translated names). The standard keys (Quit, Help) stay as they are. None of
#: these is used by a text field or by the date editor; the accessibility test checks that every
#: shortcut of the window is unique.
SHORTCUT_QUIT = "Ctrl+Q"
SHORTCUT_BACKUP = "Ctrl+B"
SHORTCUT_RESTORE = "Ctrl+Shift+R"
SHORTCUT_OPEN_FOLDER = "Ctrl+Shift+O"
SHORTCUT_TODAY = "Ctrl+T"
#: Language ``n`` (1, 2, 3 in the order of ``i18n.LANGUAGES``) has the shortcut Ctrl+Shift+n.
SHORTCUT_LANGUAGE = "Ctrl+Shift+{n}"


class MainWindow(QMainWindow):
    """The shell of the application; the pages come from the page registry."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._manager = context.translator_manager
        self.setObjectName("main_window")
        self.setMinimumSize(MINIMUM_WIDTH, MINIMUM_HEIGHT)
        self._fitted = False

        self.banners = BannerArea()
        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation_list")
        self.pages = QStackedWidget()
        self.pages.setObjectName("page_stack")
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("main_splitter")
        splitter.addWidget(self.navigation)
        splitter.addWidget(self.pages)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 780])
        central = QWidget()
        central.setObjectName("central_area")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.banners)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self.file_menu = self.menuBar().addMenu("")
        self.file_menu.setObjectName("menu_file")
        # T7.4: the three data-protection actions; the folder is opened by the one allowed helper.
        self.backup_actions = BackupActions(context, self, open_folder=open_local_folder)
        self.backup_actions.backup_action.setObjectName("action_file_backup")
        self.backup_actions.restore_action.setObjectName("action_file_restore")
        self.backup_actions.open_folder_action.setObjectName("action_file_open_data_folder")
        # Shortcuts are set here only: the Backup settings section has its own copies of these
        # actions, and two actions with one shortcut would both stop working.
        self.backup_actions.backup_action.setShortcut(QKeySequence(SHORTCUT_BACKUP))
        self.backup_actions.restore_action.setShortcut(QKeySequence(SHORTCUT_RESTORE))
        self.backup_actions.open_folder_action.setShortcut(QKeySequence(SHORTCUT_OPEN_FOLDER))
        self.file_menu.addAction(self.backup_actions.backup_action)
        self.file_menu.addAction(self.backup_actions.restore_action)
        self.file_menu.addAction(self.backup_actions.open_folder_action)
        self.file_menu.addSeparator()
        self.quit_action = QAction(self)
        self.quit_action.setObjectName("action_quit")
        self.quit_action.setShortcuts(QKeySequence.StandardKey.Quit)
        if not self.quit_action.shortcuts():  # Windows has no standard Quit key
            self.quit_action.setShortcut(QKeySequence(SHORTCUT_QUIT))
        self.quit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.quit_action)

        self.language_menu = self.menuBar().addMenu("")
        self.language_menu.setObjectName("menu_language")
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)
        self.language_actions: dict[str, QAction] = {}
        for number, code in enumerate(i18n.LANGUAGES, start=1):
            action = QAction(self)
            action.setObjectName(f"action_language_{code}")
            action.setCheckable(True)
            action.setShortcut(QKeySequence(SHORTCUT_LANGUAGE.format(n=number)))
            action.triggered.connect(partial(self._select_language, code))
            self._language_group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action

        # T10.2: the in-app help and the About dialog; both open non-modally and are built on the
        # first request (they need no service and no database).
        self.help_menu = self.menuBar().addMenu("")
        self.help_menu.setObjectName("menu_help")
        self.help_action = QAction(self)
        self.help_action.setObjectName("action_help")
        self.help_action.setShortcuts(QKeySequence.StandardKey.HelpContents)
        self.help_action.triggered.connect(self._on_help_triggered)
        self.about_action = QAction(self)
        self.about_action.setObjectName("action_about")
        self.about_action.triggered.connect(self._on_about_triggered)
        self.help_menu.addAction(self.help_action)
        self.help_menu.addAction(self.about_action)
        self.help_dialog: HelpDialog | None = None
        self.about_dialog: AboutDialog | None = None

        self.toolbar = QToolBar()
        self.toolbar.setObjectName("toolbar_main")
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        self.as_of_label = QLabel()
        self.as_of_label.setObjectName("as_of_label")
        self.as_of_edit = QDateEdit()
        self.as_of_edit.setObjectName("as_of_edit")
        self.as_of_edit.setCalendarPopup(True)
        self.as_of_edit.setKeyboardTracking(False)  # one typed edit = one change, not one per key
        self.as_of_label.setBuddy(self.as_of_edit)
        self.today_action = QAction(self)
        self.today_action.setObjectName("action_today")
        self.today_action.setShortcut(QKeySequence(SHORTCUT_TODAY))
        self.toolbar.addWidget(self.as_of_label)
        self.toolbar.addWidget(self.as_of_edit)
        self.toolbar.addAction(self.today_action)
        self.as_of_edit.setDate(to_qdate(context.as_of))
        self.as_of_edit.dateChanged.connect(self._on_edit_date_changed)
        self.today_action.triggered.connect(self._on_today)
        context.as_of_changed.connect(self._on_as_of_changed)

        self._alert_counts: AlertCounts | None = None
        self.alert_badge = QLabel()
        self.alert_badge.setObjectName("alert_badge")
        self.alert_badge.setTextFormat(Qt.TextFormat.PlainText)
        self.statusBar().addPermanentWidget(self.alert_badge)
        self.data_folder_label = QLabel()
        self.data_folder_label.setObjectName("data_folder_label")
        self.data_folder_label.setTextFormat(Qt.TextFormat.PlainText)
        self.statusBar().addPermanentWidget(self.data_folder_label)

        self._page_keys: list[str] = []
        self._page_specs: tuple[registry.PageSpec, ...] = ()
        self._placeholders: list[QLabel] = []
        self._build_pages()
        self._sync_context_banners()
        context.backup_reminder_changed.connect(self._on_backup_reminder_changed)
        self.banners.alerts_requested.connect(self._open_alerts_page)
        context.as_of_changed.connect(self._refresh_alerts)
        context.data_changed.connect(self._refresh_alerts)
        self._refresh_alerts(startup=True)

        self._manager.language_changed.connect(self._on_language_changed)
        self._sync_language_actions()
        self.retranslate()

    # ------------------------------------------------------------------ pages

    @property
    def context(self) -> AppContext:
        """The shared application context."""
        return self._context

    def _build_pages(self) -> None:
        """Create one page per registry entry and one navigation item per page."""
        try:
            self._page_specs = registry.pages()
        except registry.DuplicateKeyError as exc:  # a repeated key in the fixed tuples
            log_exception("UI.PAGE_FAILED", exc)
            self._page_specs = ()
        for spec in self._page_specs:
            try:
                widget = spec.factory(self._context)
            except Exception as exc:  # one broken page must not take the window down
                log_exception("UI.PAGE_FAILED", exc)
                widget = self._placeholder_page(spec.key)
            self.pages.addWidget(widget)
            item = QListWidgetItem(spec.title())
            item.setData(_PAGE_KEY_ROLE, spec.key)
            self.navigation.addItem(item)
            self._page_keys.append(spec.key)
        # Tab follows what is on screen, top to bottom, not the order the widgets were created in.
        for index in range(self.pages.count()):
            page = self.pages.widget(index)
            if page is not None:
                apply_tab_order(page)
        self.navigation.currentRowChanged.connect(self._on_row_changed)
        if self._page_keys:
            self.navigation.setCurrentRow(0)

    def _placeholder_page(self, key: str) -> QLabel:
        """The page shown in place of one whose factory failed (its text is set by retranslate)."""
        label = QLabel()
        label.setObjectName(f"page_placeholder_{key}")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setTextFormat(Qt.TextFormat.PlainText)
        self._placeholders.append(label)
        return label

    def _on_row_changed(self, row: int) -> None:
        if 0 <= row < self.pages.count():
            self.pages.setCurrentIndex(row)

    def page_keys(self) -> tuple[str, ...]:
        """The keys of the pages in navigation order."""
        return tuple(self._page_keys)

    def page_widget(self, key: str) -> QWidget:
        """The page widget registered under ``key`` (``KeyError`` when there is none)."""
        try:
            index = self._page_keys.index(key)
        except ValueError:
            raise KeyError(key) from None
        widget = self.pages.widget(index)
        if widget is None:
            raise KeyError(key)
        return widget

    def show_page(self, key: str) -> None:
        """Navigate to the page registered under ``key``."""
        self.navigation.setCurrentRow(self._page_keys.index(key))

    def current_page_key(self) -> str | None:
        """The key of the page shown now, or ``None`` when there is no page."""
        row = self.pages.currentIndex()
        return self._page_keys[row] if 0 <= row < len(self._page_keys) else None

    # ------------------------------------------------------------------ help and About (T10.2)

    def show_help(self, topic: str | None = None) -> HelpDialog:
        """Show the help (built on the first call), at ``topic`` when the help has that topic."""
        if self.help_dialog is None:
            self.help_dialog = HelpDialog(self._context, self)
        if topic is not None:
            self.help_dialog.show_topic(topic)
        self._bring_forward(self.help_dialog)
        return self.help_dialog

    def show_about(self) -> AboutDialog:
        """Show the About dialog (built on the first call)."""
        if self.about_dialog is None:
            self.about_dialog = AboutDialog(self._context, self)
        self._bring_forward(self.about_dialog)
        return self.about_dialog

    @staticmethod
    def _bring_forward(dialog: QDialog) -> None:
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_help_triggered(self, _checked: bool = False) -> None:
        # F1 and the menu entry open the topic of the page that is shown.
        self.show_help(self.current_page_key())

    def _on_about_triggered(self, _checked: bool = False) -> None:
        self.show_about()

    # ------------------------------------------------------------------ banners

    def _sync_context_banners(self) -> None:
        """Show the banners that follow from the context (mode, location, clock)."""
        context = self._context
        if context.is_demo:
            self.banners.show_banner(BannerCode.DEMO)
        if context.read_only:
            self.banners.show_banner(BannerCode.READ_ONLY)
        for warning in context.location.warnings:
            self.banners.show_banner(BannerCode[warning.name])
        if context.clock_suspect:
            self.banners.show_banner(BannerCode.CLOCK_SUSPECT)
        if context.backup_reminder_due:
            self.banners.show_banner(BannerCode.BACKUP_REMINDER)
        if PreferencesWarning.CORRUPT_FILE in context.preferences.warnings:
            self.banners.show_banner(BannerCode.PREFERENCES_RESET)

    def _on_backup_reminder_changed(self, due: bool) -> None:
        """Show or hide the reminder banner when the start-up hook (or a backup) changes it."""
        if due:
            self.banners.show_banner(BannerCode.BACKUP_REMINDER)
        else:
            self.banners.hide_banner(BannerCode.BACKUP_REMINDER)

    # ------------------------------------------------------------------ alerts (T6.6)

    def _read_alert_counts(self) -> AlertCounts | None:
        """The counts on the as-of date, or ``None`` (no database, or the read failed).

        The service is looked up in the context each time: ``context.conn = None`` empties it.
        """
        service = self._context.services.alerts
        if service is None:
            return None
        try:
            counts = service.counts(self._context.as_of)
        except Exception as exc:  # a failing read must not take the window down
            log_exception("UI.ALERT_COUNTS_FAILED", exc)
            return None
        return AlertCounts(
            critical=counts[Severity.CRITICAL],
            warning=counts[Severity.WARNING],
            info=counts[Severity.INFO],
        )

    def _refresh_alerts(self, *_args: object, startup: bool = False) -> None:
        """Read the counts again; update the badge and the summary banner.

        ``startup`` (the first call) is the only one that may SHOW the summary, and only when the
        preference is on and a warning or critical alert exists. Later calls update a summary that
        is already shown, or hide it once no warning or critical alert is left.
        """
        counts = self._read_alert_counts()
        self._alert_counts = counts
        self._apply_alert_badge()
        already_shown = BannerCode.ALERT_SUMMARY in self.banners.visible_codes()
        allowed = already_shown or (startup and self._context.preferences.current.startup_summary)
        if counts is not None and counts.actionable > 0 and allowed:
            self.banners.set_alert_summary(counts.critical, counts.warning)
            self.banners.show_banner(BannerCode.ALERT_SUMMARY)
        else:
            self.banners.hide_banner(BannerCode.ALERT_SUMMARY)

    def _apply_alert_badge(self) -> None:
        """Show the counts already read in the current language (hidden without counts)."""
        counts = self._alert_counts
        self.alert_badge.setVisible(counts is not None)
        if counts is None:
            self.alert_badge.clear()
            self.alert_badge.setToolTip("")
            return
        tip = QCoreApplication.translate("Shell", "Alerts on the as-of date")
        self.alert_badge.setText(alert_badge_text(counts))
        self.alert_badge.setToolTip(tip)

    def _open_alerts_page(self) -> None:
        """The button of the summary banner: show the Alerts page (when it is registered)."""
        if ALERTS_PAGE_KEY in self._page_keys:
            self.show_page(ALERTS_PAGE_KEY)

    # ------------------------------------------------------------------ as-of date

    def _on_edit_date_changed(self, value: object) -> None:
        # The toolbar selector changed: tell the context (it emits only for a real change).
        self._context.set_as_of(from_qdate(self.as_of_edit.date()))

    def _on_as_of_changed(self, value: date) -> None:
        # The context changed: show it in the selector without sending it back.
        wanted = to_qdate(value)
        if self.as_of_edit.date() != wanted:
            self.as_of_edit.blockSignals(True)
            try:
                self.as_of_edit.setDate(wanted)
            finally:
                self.as_of_edit.blockSignals(False)

    def _on_today(self, _checked: bool = False) -> None:
        self._context.reset_as_of()
        # Even when the context emitted nothing, the selector must show what the context holds.
        self._on_as_of_changed(self._context.as_of)

    # ------------------------------------------------------------------ language handling

    def _select_language(self, code: str, _checked: bool = False) -> None:
        self._manager.set_language(code)

    def _on_language_changed(self, _code: str) -> None:
        self._sync_language_actions()
        self.retranslate()

    def _sync_language_actions(self) -> None:
        current = self._manager.current_language
        for code, action in self.language_actions.items():
            action.setChecked(code == current)

    # ------------------------------------------------------------------ initial size and position

    def available_area(self) -> QRect:
        """The usable area of the screen the window opens on (the taskbar is not part of it)."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen is not None else QRect()

    def fit_to_available_area(self) -> None:
        """Shrink the window to the available screen area and move its frame inside it.

        The window never goes below ``MINIMUM_WIDTH`` x ``MINIMUM_HEIGHT``, even on a smaller area.
        """
        area = self.available_area()
        if area.isEmpty():
            return
        frame = self.frameGeometry()
        extra_width = max(0, frame.width() - self.width())
        extra_height = max(0, frame.height() - self.height())
        width = min(self.width(), area.width() - extra_width - 2 * _SCREEN_MARGIN)
        height = min(self.height(), area.height() - extra_height - 2 * _SCREEN_MARGIN)
        self.resize(max(MINIMUM_WIDTH, width), max(MINIMUM_HEIGHT, height))
        frame_width = self.width() + extra_width
        frame_height = self.height() + extra_height
        left = min(max(frame.x(), area.left()), area.right() + 1 - frame_width)
        top = min(max(frame.y(), area.top()), area.bottom() + 1 - frame_height)
        self.move(max(left, area.left()), max(top, area.top()))

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._fitted:  # only the first show: later the user's size and place are kept
            self._fitted = True
            self.fit_to_available_area()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def retranslate(self) -> None:
        """Apply every translated text of the window in the current language."""
        self.setWindowTitle(app_display_name())
        self.file_menu.setTitle(QCoreApplication.translate("Shell", "&File"))
        self.quit_action.setText(QCoreApplication.translate("Shell", "&Quit"))
        self.backup_actions.retranslate()
        self._apply_alert_badge()
        self.language_menu.setTitle(QCoreApplication.translate("Shell", "&Language"))
        for code, action in self.language_actions.items():
            action.setText(language_display_name(code))
        self.help_menu.setTitle(QCoreApplication.translate("Shell", "&Help"))
        self.help_action.setText(QCoreApplication.translate("Shell", "Help &contents"))
        self.about_action.setText(QCoreApplication.translate("Shell", "&About"))
        self.navigation.setAccessibleName(QCoreApplication.translate("Shell", "Navigation"))
        for placeholder in self._placeholders:
            placeholder.setText(
                QCoreApplication.translate("Shell", "This page could not be opened.")
            )
        for row, spec in enumerate(self._page_specs):
            item = self.navigation.item(row)
            if item is not None:
                item.setText(spec.title())

        self.toolbar.setWindowTitle(QCoreApplication.translate("Shell", "Main toolbar"))
        self.as_of_label.setText(QCoreApplication.translate("Shell", "&As-of date:"))
        self.as_of_edit.setToolTip(
            QCoreApplication.translate("Shell", "Date for which the indicators are evaluated")
        )
        self.as_of_edit.setAccessibleName(QCoreApplication.translate("Shell", "As-of date"))
        self.today_action.setText(QCoreApplication.translate("Shell", "Today"))
        self.today_action.setToolTip(QCoreApplication.translate("Shell", "Go back to today's date"))
        language = self._manager.current_language
        if language is not None:
            apply_locale(self.as_of_edit, language)

        self.data_folder_label.setText(
            QCoreApplication.translate("Shell", "Data folder: %1").replace(
                "%1", str(self._context.location.path)
            )
        )
        if self._manager.missing_catalogues:
            self.banners.show_banner(BannerCode.TRANSLATIONS_MISSING)
        else:
            self.banners.hide_banner(BannerCode.TRANSLATIONS_MISSING)
        self.banners.retranslate()
