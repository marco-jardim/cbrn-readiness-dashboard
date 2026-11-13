# SPDX-License-Identifier: GPL-3.0-or-later
"""The main window: banners, navigation list, page stack, menus, toolbar and status bar
(PLAN.md tasks T0.7 and T1.9).

The window is built from an :class:`~cbrn_dashboard.ui.shell.context.AppContext`. The navigation
and the page stack are filled from the page registry; the toolbar holds the as-of date selector
(D13), bound both ways to ``context.as_of``; the banner area shows the demo, read-only, location,
clock and translation banners and the permanent preliminary notice.

Every user-visible text is applied in :meth:`MainWindow.retranslate`, which runs once on
construction and again on every ``LanguageChange`` event, so switching the language retitles the
whole window live. Texts go through ``QCoreApplication.translate("Shell", ...)`` (never
``self.tr()``).
"""

from datetime import date
from functools import partial

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QDateEdit,
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
from cbrn_dashboard.logging_setup import log_exception
from cbrn_dashboard.prefs import PreferencesWarning
from cbrn_dashboard.ui.shell import registry
from cbrn_dashboard.ui.shell.banners import BannerArea, BannerCode
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.formatting import apply_locale, from_qdate, to_qdate
from cbrn_dashboard.ui.shell.i18n import app_display_name, language_display_name

_PAGE_KEY_ROLE = Qt.ItemDataRole.UserRole


class MainWindow(QMainWindow):
    """The shell of the application; the pages come from the page registry."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._manager = context.translator_manager
        self.setObjectName("main_window")

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
        self.quit_action = QAction(self)
        self.quit_action.setObjectName("action_quit")
        self.quit_action.setShortcuts(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)
        self.file_menu.addAction(self.quit_action)

        self.language_menu = self.menuBar().addMenu("")
        self.language_menu.setObjectName("menu_language")
        self._language_group = QActionGroup(self)
        self._language_group.setExclusive(True)
        self.language_actions: dict[str, QAction] = {}
        for code in i18n.LANGUAGES:
            action = QAction(self)
            action.setObjectName(f"action_language_{code}")
            action.setCheckable(True)
            action.triggered.connect(partial(self._select_language, code))
            self._language_group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action

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
        self.toolbar.addWidget(self.as_of_label)
        self.toolbar.addWidget(self.as_of_edit)
        self.toolbar.addAction(self.today_action)
        self.as_of_edit.setDate(to_qdate(context.as_of))
        self.as_of_edit.dateChanged.connect(self._on_edit_date_changed)
        self.today_action.triggered.connect(self._on_today)
        context.as_of_changed.connect(self._on_as_of_changed)

        self.data_folder_label = QLabel()
        self.data_folder_label.setObjectName("data_folder_label")
        self.data_folder_label.setTextFormat(Qt.TextFormat.PlainText)
        self.statusBar().addPermanentWidget(self.data_folder_label)

        self._page_keys: list[str] = []
        self._page_specs: tuple[registry.PageSpec, ...] = ()
        self._placeholders: list[QLabel] = []
        self._build_pages()
        self._sync_context_banners()

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
        if PreferencesWarning.CORRUPT_FILE in context.preferences.warnings:
            self.banners.show_banner(BannerCode.PREFERENCES_RESET)

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

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    def retranslate(self) -> None:
        """Apply every translated text of the window in the current language."""
        self.setWindowTitle(app_display_name())
        self.file_menu.setTitle(QCoreApplication.translate("Shell", "&File"))
        self.quit_action.setText(QCoreApplication.translate("Shell", "&Quit"))
        self.language_menu.setTitle(QCoreApplication.translate("Shell", "&Language"))
        for code, action in self.language_actions.items():
            action.setText(language_display_name(code))
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
