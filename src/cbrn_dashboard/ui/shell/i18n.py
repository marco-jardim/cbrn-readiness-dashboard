# SPDX-License-Identifier: GPL-3.0-or-later
"""Translator manager and the first shell messages (PLAN.md section 6, D07).

Source strings are English and go through ``QCoreApplication.translate("<Context>", ...)`` with a
string-literal context (never ``self.tr()``), so that ``pyside6-lupdate`` extracts them.
"""

from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QObject, QTranslator, Signal

from cbrn_dashboard import i18n


class TranslatorManager(QObject):
    """Installs the application catalogues and Qt's own translations for one language.

    Installing and removing translators makes Qt post ``LanguageChange`` events to the widgets,
    which re-apply their texts in ``retranslate()``. ``language_changed`` is an extra convenience
    signal carrying the new catalogue code.
    """

    language_changed = Signal(str)

    def __init__(self, app: QCoreApplication, qm_dir: Path | None = None) -> None:
        super().__init__(app)
        self._app = app
        self._qm_dir = i18n.qm_dir() if qm_dir is None else qm_dir
        self._translators: list[QTranslator] = []
        self._language: str | None = None
        self._missing: tuple[str, ...] = ()
        self._initial_locale = QLocale()

    @property
    def qm_dir(self) -> Path:
        """Folder the compiled catalogues are loaded from."""
        return self._qm_dir

    @property
    def current_language(self) -> str | None:
        """Catalogue code of the installed language, or ``None`` while none is installed."""
        return self._language

    @property
    def missing_catalogues(self) -> tuple[str, ...]:
        """Areas whose ``.qm`` file was not found (or not loadable) for the current language."""
        return self._missing

    def set_language(self, lang: str) -> None:
        """Switch to ``lang`` (``pt_BR`` or ``pt-BR``).

        Raises :class:`cbrn_dashboard.i18n.UnknownLanguageError` for an unknown code; the
        current language and translators are then left untouched.
        """
        code = i18n.to_catalogue_code(lang)
        self._remove_translators()

        missing: list[str] = []
        for area in i18n.AREAS:
            translator = self._load(self._qm_dir / i18n.qm_name(area, code))
            if translator is None:
                missing.append(area)
            else:
                self._install(translator)
        base = self._load_qt_base(code)
        if base is not None:
            self._install(base)

        self._missing = tuple(missing)
        self._language = code
        QLocale.setDefault(QLocale(code))
        self.language_changed.emit(code)

    def clear(self) -> None:
        """Remove every installed translator and restore the default locale of start-up."""
        self._remove_translators()
        self._missing = ()
        self._language = None
        QLocale.setDefault(self._initial_locale)

    def _install(self, translator: QTranslator) -> None:
        self._app.installTranslator(translator)
        self._translators.append(translator)

    def _remove_translators(self) -> None:
        for translator in self._translators:
            self._app.removeTranslator(translator)
        self._translators.clear()

    @staticmethod
    def _load(path: Path) -> QTranslator | None:
        # Never load a missing file: Qt would log a warning.
        if not path.is_file():
            return None
        translator = QTranslator()
        if not translator.load(str(path)):
            return None
        return translator

    def _load_qt_base(self, code: str) -> QTranslator | None:
        folder = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
        language = code.split("_", 1)[0]
        for name in (f"qtbase_{code}", f"qtbase_{language}"):
            translator = self._load(folder / f"{name}.qm")
            if translator is not None:
                return translator
        return None


def language_display_name(lang: str) -> str:
    """Return the name of language ``lang`` in the current UI language."""
    code = i18n.to_catalogue_code(lang)
    if code == "pt_BR":
        return QCoreApplication.translate("Shell", "Portuguese (Brazil)")
    if code == "en_US":
        return QCoreApplication.translate("Shell", "English (United States)")
    return QCoreApplication.translate("Shell", "Spanish (Spain)")


def app_display_name() -> str:
    """Return the application name in the current UI language."""
    return QCoreApplication.translate("Shell", "CBRN Readiness Dashboard")


# Production code used only by tests: it keeps a plural message in the catalogues from day one.
# The first real plural UI message (alerts, T6.3) makes this function removable.
def languages_available_text(n: int) -> str:
    """Return the plural-aware "n languages available" text."""
    return QCoreApplication.translate("Shell", "%n language(s) available", None, n)
