# SPDX-License-Identifier: GPL-3.0-or-later
"""The banner area above the pages (PLAN.md T1.9, D02, D23, D25, I06, P07).

Each banner has a code and is drawn as an ICON plus TEXT, never colour alone (D23). ``DEMO`` is
permanent once shown: ``hide_banner`` leaves it alone. Texts go through
``QCoreApplication.translate("Shell", ...)`` and are re-applied by :meth:`BannerArea.retranslate`.

The ``ALERT_SUMMARY`` banner (T6.6) is the start-up alert summary: its text carries the number of
critical and warning alerts (:meth:`BannerArea.set_alert_summary`) and it has a button that emits
:attr:`BannerArea.alerts_requested`. This module also builds the texts of the status-bar badge
(:func:`alert_badge_text`).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from PySide6.QtCore import QCoreApplication, QEvent, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from cbrn_dashboard.ui.shell.widgets import device_pixel_ratio

__all__ = ["AlertCounts", "BannerArea", "BannerCode", "alert_badge_text", "alert_summary_text"]

ICON_SIZE = 20

_PLACEHOLDER = re.compile(r"%([1-9])")


def _fill(text: str, *values: str) -> str:
    """Replace ``%1``..``%9`` by ``values`` in one pass (a translation may reorder them)."""

    def substitute(match: re.Match[str]) -> str:
        position = int(match.group(1)) - 1
        return values[position] if position < len(values) else match.group(0)

    return _PLACEHOLDER.sub(substitute, text)


@dataclass(frozen=True)
class AlertCounts:
    """The number of alerts per severity on one date (T6.6)."""

    critical: int
    warning: int
    info: int

    @property
    def actionable(self) -> int:
        """Warning and critical alerts: the ones that trigger the start-up summary."""
        return self.critical + self.warning


def _critical_text(count: int) -> str:
    return QCoreApplication.translate("Shell", "%n critical", None, count)


def _warning_text(count: int) -> str:
    return QCoreApplication.translate("Shell", "%n warning", None, count)


def _info_text(count: int) -> str:
    return QCoreApplication.translate("Shell", "%n info", None, count)


def alert_badge_text(counts: AlertCounts) -> str:
    """The text of the status-bar badge: all three severities (information counts here)."""
    template = QCoreApplication.translate("Shell", "Alerts: %1, %2, %3")
    return _fill(
        template,
        _critical_text(counts.critical),
        _warning_text(counts.warning),
        _info_text(counts.info),
    )


def alert_summary_text(critical: int, warning: int) -> str:
    """The text of the start-up summary banner: critical and warning only (never information)."""
    template = QCoreApplication.translate("Shell", "Alerts need attention: %1, %2.")
    return _fill(template, _critical_text(critical), _warning_text(warning))


class BannerCode(StrEnum):
    """The banner codes, in display order (top to bottom)."""

    DEMO = "DEMO"
    READ_ONLY = "READ_ONLY"
    NETWORK_PATH = "NETWORK_PATH"
    ONEDRIVE = "ONEDRIVE"
    POINTER_INVALID = "POINTER_INVALID"
    NO_PROFILE_DIR = "NO_PROFILE_DIR"
    CLOCK_SUSPECT = "CLOCK_SUSPECT"
    BACKUP_REMINDER = "BACKUP_REMINDER"
    ALERT_SUMMARY = "ALERT_SUMMARY"
    PREFERENCES_RESET = "PREFERENCES_RESET"
    TRANSLATIONS_MISSING = "TRANSLATIONS_MISSING"


# Banners that carry an informational icon; every other banner carries a warning icon.
_INFORMATION = frozenset({BannerCode.DEMO})

# The banners keep their own light colours whatever the system palette is (a dark system theme
# would otherwise give the labels and the action button light text on the light background), so
# every colour of text, button and focus mark is set here and none comes from the palette.
_TEXT_STYLE = (
    "QLabel {color: #000000; border: none; background: transparent;} "
    "QPushButton, QToolButton {color: #000000; background-color: #ffffff; "
    "border: 1px solid #595959; padding: 2px 10px;} "
    "QPushButton:hover, QToolButton:hover {background-color: #e6e6e6;} "
    "QPushButton:pressed, QToolButton:pressed {background-color: #cccccc;} "
    "QPushButton:focus, QToolButton:focus {border: 2px solid #000000;} "
    "QPushButton:disabled, QToolButton:disabled {color: #595959; background-color: #f0f0f0;}"
)
_STYLE_INFORMATION = "QFrame {background-color: #e8f1fb; border: 1px solid #1f4e8c;} " + _TEXT_STYLE
_STYLE_WARNING = "QFrame {background-color: #fff4d6; border: 1px solid #8a5a00;} " + _TEXT_STYLE


def banner_text(code: BannerCode) -> str:
    """The translated text of a banner in the current language."""
    match code:
        case BannerCode.DEMO:
            return QCoreApplication.translate("Shell", "DEMO — fictitious data")
        case BannerCode.READ_ONLY:
            return QCoreApplication.translate(
                "Shell",
                "Read-only mode: the database cannot be written, so nothing can be changed.",
            )
        case BannerCode.NETWORK_PATH:
            return QCoreApplication.translate(
                "Shell",
                "The data folder is on a network share, where database locking is unreliable.",
            )
        case BannerCode.ONEDRIVE:
            return QCoreApplication.translate(
                "Shell", "The data folder is inside a OneDrive-synchronised folder."
            )
        case BannerCode.POINTER_INVALID:
            return QCoreApplication.translate(
                "Shell", "The saved data-folder pointer is invalid and was ignored."
            )
        case BannerCode.NO_PROFILE_DIR:
            return QCoreApplication.translate(
                "Shell",
                "No user profile folder was found, so there is no default data folder.",
            )
        case BannerCode.CLOCK_SUSPECT:
            return QCoreApplication.translate(
                "Shell",
                "The computer clock looks wrong: snapshots and backup rotation are skipped.",
            )
        case BannerCode.BACKUP_REMINDER:
            return QCoreApplication.translate(
                "Shell",
                "The last encrypted backup is old or missing: make a new one and keep it on "
                "separate media.",
            )
        case BannerCode.ALERT_SUMMARY:
            # The counts are set on the area (set_alert_summary); this is the "none yet" text.
            return alert_summary_text(0, 0)
        case BannerCode.PREFERENCES_RESET:
            return QCoreApplication.translate(
                "Shell",
                "The saved preferences could not be read and were reset to their defaults.",
            )
        case BannerCode.TRANSLATIONS_MISSING:
            return QCoreApplication.translate(
                "Shell", "Translations are not compiled: the English source text is shown."
            )


class BannerArea(QWidget):
    """Zero or more banners stacked vertically; ``DEMO`` cannot be hidden once shown."""

    #: Emitted when the button of the ``ALERT_SUMMARY`` banner is pressed (open the Alerts page).
    alerts_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("banner_area")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._summary_counts: tuple[int, int] = (0, 0)
        self._frames: dict[BannerCode, QFrame] = {}
        self._labels: dict[BannerCode, QLabel] = {}
        self._shown: set[BannerCode] = set()
        self._permanent: set[BannerCode] = set()
        style = self.style()
        ratio = device_pixel_ratio()
        for code in BannerCode:
            frame = QFrame(self)
            frame.setObjectName(f"banner_{code.value}")
            frame.setStyleSheet(_STYLE_INFORMATION if code in _INFORMATION else _STYLE_WARNING)
            row = QHBoxLayout(frame)
            row.setContentsMargins(8, 4, 8, 4)
            icon = QLabel(frame)
            icon.setObjectName(f"banner_icon_{code.value}")
            icon_kind = (
                QStyle.StandardPixmap.SP_MessageBoxInformation
                if code in _INFORMATION
                else QStyle.StandardPixmap.SP_MessageBoxWarning
            )
            icon.setPixmap(style.standardIcon(icon_kind).pixmap(QSize(ICON_SIZE, ICON_SIZE), ratio))
            icon.setFixedSize(ICON_SIZE, ICON_SIZE)
            text = QLabel(frame)
            text.setObjectName(f"banner_text_{code.value}")
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(text, 1)
            if code is BannerCode.ALERT_SUMMARY:
                self.summary_button = QPushButton(frame)
                self.summary_button.setObjectName("banner_button_ALERT_SUMMARY")
                self.summary_button.clicked.connect(self.alerts_requested)
                row.addWidget(self.summary_button, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(frame)
            frame.setVisible(False)
            self._frames[code] = frame
            self._labels[code] = text
        self.retranslate()

    # ------------------------------------------------------------------ API

    def show_banner(self, code: str) -> None:
        """Show the banner ``code`` (raises ``ValueError`` for an unknown code).

        Showing ``DEMO`` makes it permanent (D25): the session stays marked as fictitious.
        """
        banner = BannerCode(code)
        if banner is BannerCode.DEMO:
            self._permanent.add(banner)
        self._shown.add(banner)
        self._frames[banner].setVisible(True)

    def set_permanent(self, code: str) -> None:
        """Show the banner ``code`` and make it impossible to hide."""
        banner = BannerCode(code)
        self._permanent.add(banner)
        self.show_banner(banner)

    def hide_banner(self, code: str) -> None:
        """Hide the banner ``code``; permanent banners (a shown ``DEMO``) stay."""
        banner = BannerCode(code)
        if banner in self._permanent:
            return
        self._shown.discard(banner)
        self._frames[banner].setVisible(False)

    def visible_codes(self) -> tuple[str, ...]:
        """Codes of the visible banners, in display order."""
        return tuple(code.value for code in BannerCode if code in self._shown)

    def text(self, code: str) -> str:
        """The text currently shown (or ready to be shown) for the banner ``code``."""
        return self._labels[BannerCode(code)].text()

    def set_alert_summary(self, critical: int, warning: int) -> None:
        """Set the counts named by the ``ALERT_SUMMARY`` banner (it is not shown or hidden here)."""
        self._summary_counts = (critical, warning)
        self._labels[BannerCode.ALERT_SUMMARY].setText(alert_summary_text(critical, warning))

    def retranslate(self) -> None:
        """Apply the texts of all banners in the current language."""
        for code, label in self._labels.items():
            if code is BannerCode.ALERT_SUMMARY:
                label.setText(alert_summary_text(*self._summary_counts))
            else:
                label.setText(banner_text(code))
        self.summary_button.setText(QCoreApplication.translate("Shell", "Open alerts"))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
