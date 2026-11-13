# SPDX-License-Identifier: GPL-3.0-or-later
"""Catalogue completeness (PLAN.md section 6, checks 1, 2, 3, 5, 7) and the translator manager."""

from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QLocale

from cbrn_dashboard import i18n
from cbrn_dashboard.ui.shell.i18n import (
    TranslatorManager,
    app_display_name,
    language_display_name,
    languages_available_text,
)
from tests.i18n._ts import (
    EXPECTED_NUMERUS_FORMS,
    catalogue_files,
    load_script,
    parse_ts,
    placeholders,
)

CATALOGUES = catalogue_files()
CATALOGUE_IDS = [f"{area}_{lang}" for area, lang, _ in CATALOGUES]

REVIEWED_LANGUAGES = frozenset({"pt_BR", "es_ES"})
"""Languages whose translations await the committee's review (plan section 10.1)."""

IDENTICAL_ALLOWED: frozenset[str] = frozenset()
"""Source texts whose pt_BR/es_ES translation may equal the English text (none so far)."""

APP_NAME = {
    "pt_BR": "Painel de Prontidão QBRN",
    "en_US": "CBRN Readiness Dashboard",
    "es_ES": "Panel de Preparación QBRN",
}
PLURAL_TEXT = {
    "pt_BR": ("1 idioma disponível", "2 idiomas disponíveis"),
    "en_US": ("1 language available", "2 languages available"),
    "es_ES": ("1 idioma disponible", "2 idiomas disponibles"),
}
LANGUAGE_NAMES = {
    # UI language -> names of (pt_BR, en_US, es_ES)
    "pt_BR": ("Português (Brasil)", "Inglês (Estados Unidos)", "Espanhol (Espanha)"),
    "en_US": ("Portuguese (Brazil)", "English (United States)", "Spanish (Spain)"),
    "es_ES": ("Portugués (Brasil)", "Inglés (Estados Unidos)", "Español (España)"),
}


# --- i18n helpers (Qt-free) -------------------------------------------------------------------


def test_language_codes() -> None:
    assert i18n.LANGUAGES == ("pt_BR", "en_US", "es_ES")
    assert i18n.DEFAULT_LANGUAGE == "pt_BR"
    assert i18n.to_catalogue_code("pt-BR") == "pt_BR"
    assert i18n.to_catalogue_code("es_ES") == "es_ES"
    assert i18n.to_bcp47("en_US") == "en-US"
    assert i18n.to_bcp47("pt_BR") == "pt-BR"


@pytest.mark.parametrize("code", ["", "pt", "fr_FR", "pt-br", "xx"])
def test_unknown_language_code_rejected(code: str) -> None:
    with pytest.raises(i18n.UnknownLanguageError):
        i18n.to_catalogue_code(code)
    assert issubclass(i18n.UnknownLanguageError, ValueError)


def test_catalogue_paths() -> None:
    path = i18n.catalogue_path("shell", "pt-BR")
    assert path.name == "shell_pt_BR.ts"
    assert path.parent == i18n.PACKAGE_DIR
    assert i18n.qm_dir() == i18n.PACKAGE_DIR
    assert i18n.qm_name("shell", "es_ES") == "shell_es_ES.qm"


# --- check 1: same messages in all three languages --------------------------------------------


@pytest.mark.parametrize("area", list(i18n.AREAS))
def test_catalogues_have_the_same_messages(area: str) -> None:
    keys = {lang: parse_ts(i18n.catalogue_path(area, lang)).keys for lang in i18n.LANGUAGES}
    reference = keys[i18n.DEFAULT_LANGUAGE]
    assert reference, f"catalogue {area} has no messages"
    for lang, found in keys.items():
        assert found == reference, f"{area}_{lang}: differs from {i18n.DEFAULT_LANGUAGE}"


@pytest.mark.parametrize(("area", "lang", "path"), CATALOGUES, ids=CATALOGUE_IDS)
def test_catalogue_header(area: str, lang: str, path: Path) -> None:
    assert path.is_file()
    catalogue = parse_ts(path)
    assert catalogue.language == lang
    assert catalogue.source_language == "en_US"
    assert all(message.context for message in catalogue.messages)


# --- check 2: translations non-empty, no obsolete, plural forms complete ----------------------


@pytest.mark.parametrize(("area", "lang", "path"), CATALOGUES, ids=CATALOGUE_IDS)
def test_translations_are_complete(area: str, lang: str, path: Path) -> None:
    for message in parse_ts(path).messages:
        where = f"{area}_{lang}: {message.context}/{message.source!r}"
        assert message.status in {"", "unfinished"}, f"{where}: status {message.status!r}"
        assert message.translations, f"{where}: no translation"
        assert all(text.strip() for text in message.translations), f"{where}: empty translation"
        if message.numerus:
            assert len(message.translations) == EXPECTED_NUMERUS_FORMS[lang], (
                f"{where}: wrong number of plural forms"
            )
        else:
            assert len(message.translations) == 1


@pytest.mark.parametrize(
    ("area", "lang", "path"),
    [entry for entry in CATALOGUES if entry[1] in REVIEWED_LANGUAGES],
    ids=[f"{area}_{lang}" for area, lang, _ in CATALOGUES if lang in REVIEWED_LANGUAGES],
)
def test_committee_languages_stay_unfinished_and_translated(
    area: str, lang: str, path: Path
) -> None:
    """Plan section 6 check 2 / section 10.1: pt_BR and es_ES stay unfinished until reviewed."""
    for message in parse_ts(path).messages:
        where = f"{area}_{lang}: {message.context}/{message.source!r}"
        assert message.status == "unfinished", f"{where}: marked {message.status or 'finished'}"
        if message.source in IDENTICAL_ALLOWED:
            continue
        for text in message.translations:
            assert text != message.source, f"{where}: translation copied from the English source"


@pytest.mark.parametrize("area", list(i18n.AREAS))
def test_identity_catalogue_matches_source(area: str) -> None:
    for message in parse_ts(i18n.catalogue_path(area, "en_US")).messages:
        assert message.status == "", f"{area}: {message.source!r} should be finished"
        if not message.numerus:
            assert message.translations == (message.source,)


# --- check 3: placeholders ---------------------------------------------------------------------


@pytest.mark.parametrize(("area", "lang", "path"), CATALOGUES, ids=CATALOGUE_IDS)
def test_placeholders_match(area: str, lang: str, path: Path) -> None:
    for message in parse_ts(path).messages:
        expected = placeholders(message.source)
        if message.numerus:
            assert "%n" in expected, f"{message.source!r}: plural message without %n"
        for text in message.translations:
            assert placeholders(text) == expected, f"{area}_{lang}: {message.source!r} -> {text!r}"


def test_placeholder_helper() -> None:
    assert placeholders("%1 of %2, %n day(s), 100%") == {"%1", "%2", "%n"}
    assert placeholders("no placeholders") == frozenset()


# --- check 5: lrelease compiles every catalogue without warnings ------------------------------


@pytest.mark.parametrize(("area", "lang", "path"), CATALOGUES, ids=CATALOGUE_IDS)
def test_lrelease_is_clean(area: str, lang: str, path: Path, tmp_path: Path) -> None:
    qm_path = tmp_path / i18n.qm_name(area, lang)
    result = load_script().run_lrelease(path, qm_path)
    output = (result.stdout + result.stderr).lower()
    assert result.returncode == 0, output
    assert "warning" not in output, output
    assert "error" not in output, output
    assert qm_path.is_file()


def test_compile_script_writes_to_the_given_folder(qm_dir: Path) -> None:
    written = sorted(path.name for path in qm_dir.glob("*.qm"))
    assert written == sorted(i18n.qm_name(area, lang) for area, lang, _ in CATALOGUES)


# --- translator manager -----------------------------------------------------------------------


@pytest.mark.ui
@pytest.mark.parametrize("lang", i18n.LANGUAGES)
def test_manager_translates_known_strings(translator_manager: TranslatorManager, lang: str) -> None:
    translator_manager.set_language(lang)
    assert translator_manager.current_language == lang
    assert translator_manager.missing_catalogues == ()
    assert app_display_name() == APP_NAME[lang]
    assert languages_available_text(1) == PLURAL_TEXT[lang][0]
    assert languages_available_text(2) == PLURAL_TEXT[lang][1]


@pytest.mark.ui
def test_manager_accepts_bcp47_codes(translator_manager: TranslatorManager) -> None:
    translator_manager.set_language("pt-BR")
    assert translator_manager.current_language == "pt_BR"
    assert app_display_name() == APP_NAME["pt_BR"]


@pytest.mark.ui
def test_manager_switches_back_and_forth(translator_manager: TranslatorManager) -> None:
    for lang in ("pt_BR", "en_US", "es_ES", "pt_BR", "es_ES", "en_US"):
        translator_manager.set_language(lang)
        assert app_display_name() == APP_NAME[lang]


@pytest.mark.ui
def test_manager_emits_language_changed(translator_manager: TranslatorManager) -> None:
    seen: list[str] = []
    translator_manager.language_changed.connect(seen.append)
    translator_manager.set_language("es-ES")
    translator_manager.set_language("en_US")
    assert seen == ["es_ES", "en_US"]


@pytest.mark.ui
@pytest.mark.parametrize("code", ["fr_FR", "xx", "", "pt"])
def test_manager_rejects_unknown_language(translator_manager: TranslatorManager, code: str) -> None:
    translator_manager.set_language("es_ES")
    with pytest.raises(i18n.UnknownLanguageError):
        translator_manager.set_language(code)
    assert translator_manager.current_language == "es_ES"
    assert app_display_name() == APP_NAME["es_ES"]
    assert QLocale().name() == "es_ES"


@pytest.mark.ui
@pytest.mark.parametrize("lang", i18n.LANGUAGES)
def test_manager_sets_default_locale(translator_manager: TranslatorManager, lang: str) -> None:
    translator_manager.set_language(lang)
    assert QLocale().name() == lang


@pytest.mark.ui
def test_manager_clear_removes_translators(translator_manager: TranslatorManager) -> None:
    translator_manager.set_language("pt_BR")
    translator_manager.clear()
    assert translator_manager.current_language is None
    assert app_display_name() == "CBRN Readiness Dashboard"


@pytest.mark.ui
def test_manager_reports_missing_catalogues(
    translator_manager_factory: Callable[[Path | None], TranslatorManager], tmp_path: Path
) -> None:
    manager = translator_manager_factory(tmp_path)
    manager.set_language("pt_BR")
    assert manager.current_language == "pt_BR"
    assert manager.missing_catalogues == tuple(i18n.AREAS)
    assert app_display_name() == "CBRN Readiness Dashboard"
    assert languages_available_text(2) == "2 language(s) available"
    assert QLocale().name() == "pt_BR"


@pytest.mark.ui
def test_manager_default_folder_is_the_package_folder(qapp: QCoreApplication) -> None:
    manager = TranslatorManager(qapp)
    try:
        assert manager.qm_dir == i18n.qm_dir()
    finally:
        manager.setParent(None)


@pytest.mark.ui
def test_pseudo_locale_wraps_known_string(
    translator_manager_factory: Callable[[Path | None], TranslatorManager], pseudo_qm_dir: Path
) -> None:
    manager = translator_manager_factory(pseudo_qm_dir)
    manager.set_language("pt_BR")
    assert app_display_name() == "\u27e6CBRN Readiness Dashboard\u27e7"
    assert languages_available_text(2) == "\u27e62 language(s) available\u27e7"


# --- check 7 placeholder: language names under each UI language -------------------------------


@pytest.mark.ui
@pytest.mark.parametrize("ui_lang", i18n.LANGUAGES)
def test_language_display_names(translator_manager: TranslatorManager, ui_lang: str) -> None:
    translator_manager.set_language(ui_lang)
    names = tuple(language_display_name(lang) for lang in i18n.LANGUAGES)
    assert all(names)
    assert len(set(names)) == len(names)
    assert names == LANGUAGE_NAMES[ui_lang]
    assert language_display_name("pt-BR") == names[0]
    with pytest.raises(i18n.UnknownLanguageError):
        language_display_name("fr_FR")
