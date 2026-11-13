# SPDX-License-Identifier: GPL-3.0-or-later
"""The About dialog (PLAN.md T10.2, section 8 "Licences", P07).

It shows the application name, the version (``cbrn_dashboard.__version__``), the GPL-3.0-or-later
notice with the absence of any warranty, the source URL as plain, selectable text, the preliminary
notice, and one line per component of the third-party licence index that the bundle ships.

The index is ``licenses\\index.json``, written beside the executable by ``scripts/build_exe.py``
(``scripts/collect_licenses.py`` produces it). It is looked up only when the program is frozen;
running from source there is no built index, and the dialog says so in a translated line. A
missing, unreadable or empty index never makes the dialog invent component names. The dialog makes
no network connection and does not check for updates; it opens no link (the URL is text).

It builds with every service ``None`` and touches no database. Texts are applied in
:meth:`AboutDialog.retranslate`, which runs on construction and on every language change.
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard import __version__
from cbrn_dashboard.ui.shell.banners import BannerCode, banner_text
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.i18n import app_display_name
from cbrn_dashboard.ui.shell.widgets import follow_language, mark_data

__all__ = [
    "INDEX_FILE_NAME",
    "LICENCE_ID",
    "LICENSES_DIR_NAME",
    "SOURCE_URL",
    "AboutDialog",
    "Component",
    "LicenceIndexError",
    "component_line",
    "demo_about_dialog",
    "licence_index_path",
    "read_licence_index",
]

#: The source repository, shown as plain text (never as a link).
SOURCE_URL = "https://github.com/marco-jardim/cbrn-readiness-dashboard"
#: The licence of the application source.
LICENCE_ID = "GPL-3.0-or-later"
#: The folder of the licence texts beside the executable, and the index in it.
LICENSES_DIR_NAME = "licenses"
INDEX_FILE_NAME = "index.json"


class LicenceIndexError(Exception):
    """The licence index cannot be read or does not have the documented shape."""


@dataclass(frozen=True)
class Component:
    """One entry of the licence index: component, version and the licence the bundle uses."""

    name: str
    version: str
    licence: str


def licence_index_path() -> Path | None:
    """The index of the bundle (beside the frozen executable), or ``None`` when there is none.

    Running from source there is no built index, so this gives ``None``.
    """
    if not getattr(sys, "frozen", False):
        return None
    path = Path(sys.executable).parent / LICENSES_DIR_NAME / INDEX_FILE_NAME
    return path if path.is_file() else None


def read_licence_index(path: Path) -> tuple[Component, ...]:
    """The components of the index file ``path``, in file order.

    Raises :class:`LicenceIndexError` when the file cannot be read, is not a non-empty JSON list,
    or an entry lacks the text fields ``component``, ``version`` and ``chosen``.
    """
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LicenceIndexError(path.name) from error
    if not isinstance(data, list) or not data:
        raise LicenceIndexError(path.name)
    found: list[Component] = []
    for item in data:
        if not isinstance(item, dict):
            raise LicenceIndexError(path.name)
        name = item.get("component")
        version = item.get("version")
        chosen = item.get("chosen")
        if not isinstance(name, str) or not isinstance(version, str) or not isinstance(chosen, str):
            raise LicenceIndexError(path.name)
        if not name:
            raise LicenceIndexError(path.name)
        found.append(Component(name, version, chosen))
    return tuple(found)


def component_line(component: Component) -> str:
    """The one line shown for ``component``: name, version and chosen licence."""
    version = f" ({component.version})" if component.version else ""
    licence = f" - {component.licence}" if component.licence else ""
    return f"{component.name}{version}{licence}"


class AboutDialog(QDialog):
    """Version, licence, source, preliminary notice and the third-party components.

    ``locate_index`` returns the path of the licence index or ``None``; the default looks beside
    the frozen executable. It is read once, when the dialog is built.
    """

    def __init__(
        self,
        context: AppContext,
        parent: QWidget | None = None,
        *,
        locate_index: Callable[[], Path | None] = licence_index_path,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("about_dialog")
        self.context = context
        self._components: tuple[Component, ...] = ()
        self._index_unreadable = False
        located = locate_index()
        if located is not None:
            try:
                self._components = read_licence_index(located)
            except LicenceIndexError:
                self._index_unreadable = True

        self.name_label = self._label("about_name")
        font = self.name_label.font()
        font.setBold(True)
        self.name_label.setFont(font)
        self.version_label = self._label("about_version")
        self.licence_label = self._label("about_licence")
        self.gpl_label = self._label("about_gpl_notice")
        self.warranty_label = self._label("about_warranty")
        self.licenses_label = self._label("about_licenses_folder")
        self.source_caption = self._label("about_source_caption")
        self.source_label = self._label("about_source_url")
        self.source_label.setText(SOURCE_URL)
        self.source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        mark_data(self.source_label)  # the URL is not translated
        self.notice_label = self._label("about_preliminary_notice")
        self.components_caption = self._label("about_components_caption")
        self.components_status = self._label("about_components_status")
        self.components_list = QListWidget(self)
        self.components_list.setObjectName("about_components")
        mark_data(self.components_list)  # component names and licence ids are data
        for component in self._components:
            self.components_list.addItem(QListWidgetItem(component_line(component)))
        self.components_caption.setBuddy(self.components_list)
        self.components_list.setVisible(bool(self._components))
        self.components_status.setVisible(not self._components)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        for widget in (
            self.name_label,
            self.version_label,
            self.licence_label,
            self.gpl_label,
            self.warranty_label,
            self.licenses_label,
            self.source_caption,
            self.source_label,
            self.notice_label,
            self.components_caption,
            self.components_status,
        ):
            root.addWidget(widget)
        root.addWidget(self.components_list, 1)
        root.addWidget(self.buttons)
        self.resize(560, 560)
        follow_language(context, self.retranslate)
        self.retranslate()

    def _label(self, name: str) -> QLabel:
        label = QLabel(self)
        label.setObjectName(name)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    # ------------------------------------------------------------------ what is shown

    def components(self) -> tuple[Component, ...]:
        """The components read from the index (empty when there is no usable index)."""
        return self._components

    def retranslate(self) -> None:
        """Apply every translated text of the dialog in the current language."""
        self.setWindowTitle(QCoreApplication.translate("Shell", "About"))
        self.name_label.setText(app_display_name())
        version = QCoreApplication.translate("Shell", "Version %1").replace("%1", __version__)
        self.version_label.setText(version)
        licence = QCoreApplication.translate("Shell", "Licence: %1").replace("%1", LICENCE_ID)
        self.licence_label.setText(licence)
        self.gpl_label.setText(
            QCoreApplication.translate(
                "Shell",
                "This program is free software: you can redistribute it and/or modify it under "
                "the terms of the GNU General Public License as published by the Free Software "
                "Foundation, either version 3 of the License, or (at your option) any later "
                "version.",
            )
        )
        self.warranty_label.setText(
            QCoreApplication.translate(
                "Shell",
                "This program comes with ABSOLUTELY NO WARRANTY; without even the implied "
                "warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.",
            )
        )
        self.licenses_label.setText(
            QCoreApplication.translate(
                "Shell",
                "In the released bundle, the complete licence texts and the offer of source for "
                "the bundled components are in the licenses folder next to the program.",
            )
        )
        self.source_caption.setText(QCoreApplication.translate("Shell", "Source code:"))
        self.notice_label.setText(banner_text(BannerCode.PRELIMINARY))
        self.components_caption.setText(
            QCoreApplication.translate("Shell", "Third-party components")
        )
        if self._index_unreadable:
            status = QCoreApplication.translate(
                "Shell", "The list of third-party components could not be read."
            )
        else:
            status = QCoreApplication.translate(
                "Shell", "The list of third-party components is not available in this build."
            )
        self.components_status.setText(status)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()


def demo_about_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """The registry factory: the About dialog needs no data."""
    return AboutDialog(context, parent)
