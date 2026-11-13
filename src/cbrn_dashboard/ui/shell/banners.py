# SPDX-License-Identifier: GPL-3.0-or-later
"""The banner area above the pages (PLAN.md T1.9, D02, D23, D25, I06, P07).

Each banner has a code and is drawn as an ICON plus TEXT, never colour alone (D23). The
``PRELIMINARY`` notice is permanent, and so is ``DEMO`` once shown: ``hide_banner`` leaves them
alone. Texts go through
``QCoreApplication.translate("Shell", ...)`` and are re-applied by :meth:`BannerArea.retranslate`.
"""

from enum import StrEnum

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QStyle, QVBoxLayout, QWidget

__all__ = ["BannerArea", "BannerCode"]

ICON_SIZE = 20


class BannerCode(StrEnum):
    """The banner codes, in display order (top to bottom)."""

    DEMO = "DEMO"
    READ_ONLY = "READ_ONLY"
    NETWORK_PATH = "NETWORK_PATH"
    ONEDRIVE = "ONEDRIVE"
    POINTER_INVALID = "POINTER_INVALID"
    NO_PROFILE_DIR = "NO_PROFILE_DIR"
    CLOCK_SUSPECT = "CLOCK_SUSPECT"
    PREFERENCES_RESET = "PREFERENCES_RESET"
    TRANSLATIONS_MISSING = "TRANSLATIONS_MISSING"
    PRELIMINARY = "PRELIMINARY"


# Banners that carry an informational icon; every other banner carries a warning icon.
_INFORMATION = frozenset({BannerCode.DEMO, BannerCode.PRELIMINARY})

_STYLE_INFORMATION = (
    "QFrame {background-color: #e8f1fb; border: 1px solid #1f4e8c;} "
    "QLabel {color: #000000; border: none; background: transparent;}"
)
_STYLE_WARNING = (
    "QFrame {background-color: #fff4d6; border: 1px solid #8a5a00;} "
    "QLabel {color: #000000; border: none; background: transparent;}"
)


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
        case BannerCode.PREFERENCES_RESET:
            return QCoreApplication.translate(
                "Shell",
                "The saved preferences could not be read and were reset to their defaults.",
            )
        case BannerCode.TRANSLATIONS_MISSING:
            return QCoreApplication.translate(
                "Shell", "Translations are not compiled: the English source text is shown."
            )
        case BannerCode.PRELIMINARY:
            return QCoreApplication.translate(
                "Shell", "Preliminary version — indicators not institutionally validated."
            )


class BannerArea(QWidget):
    """Zero or more banners stacked vertically; ``PRELIMINARY`` is always visible."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("banner_area")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._frames: dict[BannerCode, QFrame] = {}
        self._labels: dict[BannerCode, QLabel] = {}
        self._shown: set[BannerCode] = set()
        self._permanent: set[BannerCode] = {BannerCode.PRELIMINARY}
        style = self.style()
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
            icon.setPixmap(style.standardIcon(icon_kind).pixmap(ICON_SIZE, ICON_SIZE))
            icon.setFixedSize(ICON_SIZE, ICON_SIZE)
            text = QLabel(frame)
            text.setObjectName(f"banner_text_{code.value}")
            text.setTextFormat(Qt.TextFormat.PlainText)
            text.setWordWrap(True)
            row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(text, 1)
            layout.addWidget(frame)
            frame.setVisible(False)
            self._frames[code] = frame
            self._labels[code] = text
        self.show_banner(BannerCode.PRELIMINARY)
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
        """Hide the banner ``code``; permanent banners (``PRELIMINARY``, a shown ``DEMO``) stay."""
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

    def retranslate(self) -> None:
        """Apply the texts of all banners in the current language."""
        for code, label in self._labels.items():
            label.setText(banner_text(code))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
