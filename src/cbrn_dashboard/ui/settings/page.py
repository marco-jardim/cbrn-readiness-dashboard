# SPDX-License-Identifier: GPL-3.0-or-later
"""The Settings page (PLAN.md T6.1) and the registry factories of its own sections.

The page owns no setting itself: it RENDERS the settings sections that the registry of the shell
holds (``registry.SETTINGS_GROUPS`` in order, and per group ``registry.settings_sections(group)``),
one tab per group that has a section and one titled box per section. The sections T6.1 owns itself
(general, alerts and targets) are registered through the same registry like those of the modules,
with the factories at the end of this module. A group without a section is not shown.

``registry`` imports this module (for its factories), so the page imports the registry only inside
:meth:`SettingsPage._build`, when the page is constructed: the registry is read then, so temporary
registrations made by tests are rendered too.
"""

from collections.abc import Callable

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGroupBox,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.services.indicators import TargetView
from cbrn_dashboard.ui.settings.dialogs import TargetDialog
from cbrn_dashboard.ui.settings.labels import group_label
from cbrn_dashboard.ui.settings.sections import AlertsSection, GeneralSection, TargetsSection
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.widgets import follow_language

__all__ = [
    "SettingsPage",
    "alerts_section_title",
    "create_alerts_section",
    "create_general_section",
    "create_page",
    "create_targets_section",
    "demo_target_dialog",
    "general_section_title",
    "page_title",
    "targets_section_title",
]


class SettingsPage(QWidget):
    """One tab per settings group that has a registered section; one box per section."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settings_page")
        self.context = context
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("settings_tabs")
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self._groups: list[str] = []
        self._titles: list[tuple[QGroupBox, Callable[[], str]]] = []
        self._section_keys: dict[str, list[str]] = {}
        self._sections: dict[str, QWidget] = {}
        self._build()
        follow_language(context, self.retranslate)
        self.retranslate()

    def _build(self) -> None:
        # Imported here, not at module level: the registry imports this module.
        from cbrn_dashboard.ui.shell import registry

        for group in registry.SETTINGS_GROUPS:
            specs = registry.settings_sections(group)
            if not specs:
                continue
            body = QWidget()
            body.setObjectName(f"settings_group_{group}")
            column = QVBoxLayout(body)
            keys: list[str] = []
            for spec in specs:
                box = QGroupBox(body)
                box.setObjectName(f"settings_box_{spec.key}")
                inner = QVBoxLayout(box)
                section = spec.factory(self.context)
                inner.addWidget(section)
                column.addWidget(box)
                self._titles.append((box, spec.title))
                self._sections[spec.key] = section
                keys.append(spec.key)
            column.addStretch(1)
            scroll = QScrollArea()
            scroll.setObjectName(f"settings_scroll_{group}")
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(body)
            self.tabs.addTab(scroll, "")
            self._groups.append(group)
            self._section_keys[group] = keys

    # ----- what is shown

    def groups(self) -> tuple[str, ...]:
        """The codes of the groups that are shown, in tab order."""
        return tuple(self._groups)

    def section_keys(self, group: str) -> tuple[str, ...]:
        """The keys of the sections shown under ``group`` (none for a group that is not shown)."""
        return tuple(self._section_keys.get(group, ()))

    def section_widget(self, key: str) -> QWidget:
        """The widget the factory of section ``key`` built (``KeyError`` when it is not shown)."""
        return self._sections[key]

    def section_box(self, key: str) -> QGroupBox:
        """The titled box around section ``key`` (``KeyError`` when it is not shown)."""
        widget = self._sections[key]
        box = widget.parentWidget()
        if not isinstance(box, QGroupBox):
            raise KeyError(key)
        return box

    def show_group(self, group: str) -> None:
        """Make the tab of ``group`` the current one."""
        self.tabs.setCurrentIndex(self._groups.index(group))

    # ----- texts

    def retranslate(self) -> None:
        """Re-apply the tab titles and the section titles in the current language."""
        for index, group in enumerate(self._groups):
            self.tabs.setTabText(index, group_label(group))
        for box, title in self._titles:
            box.setTitle(title())

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()


# --------------------------------------------------------------------------- registry factories


def page_title() -> str:
    return QCoreApplication.translate("Settings", "Settings")


def create_page(context: AppContext) -> QWidget:
    return SettingsPage(context)


def general_section_title() -> str:
    return QCoreApplication.translate("Settings", "Language, operator and institution")


def create_general_section(context: AppContext) -> QWidget:
    return GeneralSection(context)


def alerts_section_title() -> str:
    return QCoreApplication.translate("Settings", "Warning windows")


def create_alerts_section(context: AppContext) -> QWidget:
    return AlertsSection(context)


def targets_section_title() -> str:
    return QCoreApplication.translate("Settings", "Indicator targets")


def create_targets_section(context: AppContext) -> QWidget:
    return TargetsSection(context)


def demo_target_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """A target dialog filled with a fictitious target (it writes nothing unless accepted)."""
    target = TargetView(
        indicator_code="PERS_CERT_VALID",
        dimension="level=A",
        warning_value=10.0,
        critical_value=5.0,
        enabled=True,
    )
    return TargetDialog(context, parent, target)
