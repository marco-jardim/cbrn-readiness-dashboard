# SPDX-License-Identifier: GPL-3.0-or-later
"""The main window: navigation list, page stack, menus and status bar (PLAN.md task T0.7).

Every user-visible text is applied in :meth:`MainWindow.retranslate`, which runs once on
construction and again on every ``LanguageChange`` event, so switching the language retitles the
whole window live. Texts go through ``QCoreApplication.translate("Shell", ...)`` (never
``self.tr()``).
"""

from functools import partial

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QWidget,
)

from cbrn_dashboard import i18n
from cbrn_dashboard.paths import DataLocation
from cbrn_dashboard.ui.shell.i18n import TranslatorManager, app_display_name, language_display_name


class MainWindow(QMainWindow):
    """Empty shell of the application; the pages are added by later tasks."""

    def __init__(
        self,
        translator_manager: TranslatorManager,
        location: DataLocation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = translator_manager
        self._location = location
        self.setObjectName("main_window")

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
        self.setCentralWidget(splitter)

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

        self.data_folder_label = QLabel()
        self.data_folder_label.setObjectName("data_folder_label")
        self.data_folder_label.setTextFormat(Qt.TextFormat.PlainText)
        self.translations_warning_label = QLabel()
        self.translations_warning_label.setObjectName("translations_warning_label")
        self.translations_warning_label.setTextFormat(Qt.TextFormat.PlainText)
        status_bar = self.statusBar()
        status_bar.addPermanentWidget(self.translations_warning_label)
        status_bar.addPermanentWidget(self.data_folder_label)

        self._manager.language_changed.connect(self._on_language_changed)
        self._sync_language_actions()
        self.retranslate()

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
        self.data_folder_label.setText(
            QCoreApplication.translate("Shell", "Data folder: %1").replace(
                "%1", str(self._location.path)
            )
        )
        if self._manager.missing_catalogues:
            warning = QCoreApplication.translate(
                "Shell", "Translations are not compiled: the English source text is shown."
            )
        else:
            warning = ""
        self.translations_warning_label.setText(warning)
