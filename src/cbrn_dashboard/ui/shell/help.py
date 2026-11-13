# SPDX-License-Identifier: GPL-3.0-or-later
"""The in-app help: one Markdown file per language, shown in a viewer (PLAN.md T10.2, F06, D19).

The help files are package data, ``cbrn_dashboard/help/<lang>.md`` (``pt_BR``, ``en_US``,
``es_ES``), written from scratch and without clinical content. They are read through
``importlib.resources``, so the same code works from source and in the frozen bundle (the build
ships every tracked package file).

File format: one ``# `` title, then topics. A topic starts with a ``## `` or ``### `` heading and
the very next line is the marker ``<!-- topic: <id> -->``; the marker is removed before the text is
shown. The topic ids are the same in every language, and the id of a page topic is the registry key
of the page (``tests/ui/test_help_and_about.py`` checks both).

The viewer loads nothing from outside: the files hold no link and no image, the browser does not
follow links (``setOpenLinks(False)``) and does not open external ones. It follows the UI language
and keeps the selected topic when the language changes. Texts of the chrome go through
``QCoreApplication.translate("Shell", ...)``; the topic titles and bodies come from the files.
"""

import re
from dataclasses import dataclass
from importlib import resources

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard import i18n
from cbrn_dashboard.ui.shell.context import AppContext
from cbrn_dashboard.ui.shell.widgets import current_language, follow_language

__all__ = [
    "HELP_DIRECTORY",
    "HelpDialog",
    "HelpFormatError",
    "HelpTopic",
    "demo_help_dialog",
    "load_topics",
    "parse_help",
    "read_help_text",
]

#: The folder of the help files inside the package.
HELP_DIRECTORY = "help"
#: The language tried when the file of the wanted language cannot be used.
_FALLBACK_LANGUAGE = "en_US"
_HEADING = re.compile(r"^(#{1,6}) +(\S.*?)\s*$")
_MARKER = re.compile(r"^<!-- topic: ([a-z][a-z_]*) -->$")
_TOPIC_LEVELS = (2, 3)


class HelpFormatError(ValueError):
    """A help file whose topics are not written in the documented format."""


@dataclass(frozen=True)
class HelpTopic:
    """One topic: its id, its heading level (2 or 3), its title and its Markdown text."""

    key: str
    level: int
    title: str
    markdown: str


def parse_help(text: str) -> tuple[HelpTopic, ...]:
    """The topics of a help file, in order. Raises :class:`HelpFormatError` for a bad file.

    A topic runs from its heading to the next heading of level 2 or 3; its text includes the
    heading and not the marker line. Lines before the first topic are ignored.
    """
    topics: list[HelpTopic] = []
    seen: set[str] = set()
    heading: tuple[int, str] | None = None
    key: str | None = None
    body: list[str] = []

    def finish() -> None:
        if heading is None:
            return
        if key is None:
            msg = f"The heading {heading[1]!r} has no topic marker"
            raise HelpFormatError(msg)
        if key in seen:
            msg = f"The topic {key!r} appears twice"
            raise HelpFormatError(msg)
        seen.add(key)
        topics.append(HelpTopic(key, heading[0], heading[1], "\n".join(body).strip() + "\n"))

    for line in text.splitlines():
        match = _HEADING.match(line)
        if match is not None and len(match.group(1)) in (1, *_TOPIC_LEVELS):
            finish()
            level = len(match.group(1))
            if level == 1:
                heading, key, body = None, None, []
            else:
                heading, key, body = (level, match.group(2)), None, [line]
            continue
        if heading is None:
            continue
        if key is None:
            marker = _MARKER.match(line.strip())
            if marker is None:
                msg = f"The line after the heading {heading[1]!r} is not a topic marker"
                raise HelpFormatError(msg)
            key = marker.group(1)
            continue
        body.append(line)
    finish()
    return tuple(topics)


def read_help_text(language: str) -> str | None:
    """The text of the help file of ``language`` (a catalogue code), or ``None`` if unreadable."""
    if language not in i18n.LANGUAGES:
        return None
    try:
        folder = resources.files("cbrn_dashboard").joinpath(HELP_DIRECTORY)
        return folder.joinpath(f"{language}.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def load_topics(language: str) -> tuple[HelpTopic, ...]:
    """The topics in ``language``; the English file when that one cannot be used, else ``()``."""
    for code in (language, _FALLBACK_LANGUAGE):
        text = read_help_text(code)
        if text is None:
            continue
        try:
            topics = parse_help(text)
        except HelpFormatError:
            continue
        if topics:
            return topics
    return ()


class HelpDialog(QDialog):
    """The topic list and the text of the selected topic, in the current UI language."""

    def __init__(self, context: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("help_dialog")
        self.context = context
        self._topics: tuple[HelpTopic, ...] = ()
        self._language = ""
        self.topic_list = QListWidget(self)
        self.topic_list.setObjectName("help_topic_list")
        self.viewer = QTextBrowser(self)
        self.viewer.setObjectName("help_viewer")
        self.viewer.setReadOnly(True)
        self.viewer.setOpenLinks(False)
        self.viewer.setOpenExternalLinks(False)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.buttons.rejected.connect(self.reject)
        body = QHBoxLayout()
        body.addWidget(self.topic_list, 1)
        body.addWidget(self.viewer, 3)
        root = QVBoxLayout(self)
        root.addLayout(body, 1)
        root.addWidget(self.buttons)
        self.resize(820, 560)
        self.topic_list.currentRowChanged.connect(self._show_row)
        follow_language(context, self.retranslate)
        self.retranslate()

    # ------------------------------------------------------------------ topics

    def topics(self) -> tuple[HelpTopic, ...]:
        """The topics shown, in order."""
        return self._topics

    @property
    def loaded_language(self) -> str:
        """The catalogue code whose help file was asked for last."""
        return self._language

    def current_topic_key(self) -> str | None:
        """The id of the selected topic, or ``None`` when there is none."""
        row = self.topic_list.currentRow()
        return self._topics[row].key if 0 <= row < len(self._topics) else None

    def show_topic(self, key: str) -> bool:
        """Select the topic ``key``; ``False`` (and no change) when this help has no such topic."""
        for row, topic in enumerate(self._topics):
            if topic.key == key:
                self.topic_list.setCurrentRow(row)
                return True
        return False

    def _show_row(self, row: int) -> None:
        if 0 <= row < len(self._topics):
            self.viewer.setMarkdown(self._topics[row].markdown)

    def _load(self, language: str) -> None:
        selected = self.current_topic_key()
        self._language = language
        self._topics = load_topics(language)
        self.topic_list.blockSignals(True)
        try:
            self.topic_list.clear()
            for topic in self._topics:
                indent = "    " * (topic.level - 2)
                self.topic_list.addItem(QListWidgetItem(indent + topic.title))
        finally:
            self.topic_list.blockSignals(False)
        self.viewer.clear()
        if self._topics:
            keys = [topic.key for topic in self._topics]
            self.topic_list.setCurrentRow(keys.index(selected) if selected in keys else 0)

    # ------------------------------------------------------------------ language

    def retranslate(self) -> None:
        """Apply the texts of the chrome and load the help file of the current language."""
        self.setWindowTitle(QCoreApplication.translate("Shell", "Help"))
        self.topic_list.setAccessibleName(QCoreApplication.translate("Shell", "Help topics"))
        self.viewer.setAccessibleName(QCoreApplication.translate("Shell", "Help text"))
        language = current_language(self.context)
        if language != self._language:
            self._load(language)
        if not self._topics:
            self.viewer.setPlainText(
                QCoreApplication.translate("Shell", "The help text could not be loaded.")
            )

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()


def demo_help_dialog(context: AppContext, parent: QWidget | None = None) -> QDialog:
    """The registry factory: the help needs no data."""
    return HelpDialog(context, parent)
