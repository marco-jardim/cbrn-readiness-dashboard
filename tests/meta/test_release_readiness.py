# SPDX-License-Identifier: GPL-3.0-or-later
"""The release material of the current version is complete and says only what is true (T9.6).

The checks read plain files; nothing here tags, builds or publishes anything. They cover:

* the version: one source (``__init__.py``), read by hatch, equal to the installed metadata, and
  stated by the documents that talk about the release;
* ``CHANGELOG.md``: an entry for the version, listing exactly the placeholders still flagged in
  ``domain/config.py`` (local-only ones marked), the assumptions without a setting, and every open
  question by its status only;
* the release machinery (workflow, release-body template) and the manual smoke-test script exist;
* the documents do not claim that a release was published, tested on real machines or signed.

T10.5 extends this module for version 1.0: the 1.0.0 entry lists the placeholders still flagged,
the local-only values stay flagged with an empty default, the number of unfinished translation
messages stated equals the number found, every question Q1 to Q29 has one of the three status
phrases, and the manual test script for the committee names every registered page.
"""

from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from importlib import metadata
from pathlib import Path

import pytest

from cbrn_dashboard import __version__
from cbrn_dashboard.domain.config import (
    PLACEHOLDERS,
    PlaceholderKind,
    ReadinessConfig,
    flagged_placeholder_ids,
    placeholder,
)

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
INIT = ROOT / "src" / "cbrn_dashboard" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
PLAN = ROOT / "PLAN.md"
SMOKE_TEST = DOCS / "smoke-test.pt-BR.md"
MANUAL_SCRIPT = DOCS / "manual-test-script.pt-BR.md"
REGISTRY = ROOT / "src" / "cbrn_dashboard" / "ui" / "shell" / "registry.py"
I18N = ROOT / "src" / "cbrn_dashboard" / "i18n"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
TEMPLATE = ROOT / ".github" / "release-body.template.md"
LANGUAGES = ("pt-BR", "en-US", "es-ES")

#: The last version published on GitHub (1.0.2, on 2026-11-14). The current version in the source
#: may be newer and not published yet; the documents then name both.
LAST_PUBLISHED = "1.0.2"
LAST_PUBLISHED_DATE = "2026-11-14"

#: The questions of PLAN.md section 12 that the changelog lists: Q1 to Q29.
QUESTION_NUMBERS = range(1, 30)

#: The local-only placeholders (PLAN.md 3.5): flagged in code, never given a code default.
LOCAL_ONLY_IDS = ("P03", "P10", "D18", "P12")

#: Every registered page (registry key) and its Brazilian Portuguese navigation title. The manual
#: test script must name each title; a new page makes the registry test below fail until it is
#: added here and to the script.
PAGE_TITLES = {
    "dashboard": "Painel",
    "personnel": "Pessoal",
    "infrastructure": "Infraestrutura",
    "exercises": "Exerc\u00edcios",
    "budget": "Or\u00e7amento",
    "alerts": "Alertas",
    "reports": "Relat\u00f3rios",
    "settings": "Configura\u00e7\u00f5es",
}

#: The A-items without a setting (PLAN.md 3.5): assumptions, listed in the changelog as open
#: questions only.
ASSUMPTIONS_WITHOUT_SETTING = {"A01", "A03", "A12", "A13", "A14", "A15", "A16"}

#: The three status phrases of an open question (PLAN.md section 12).
STATUS_FORM = re.compile(
    r"^- (Q\d+): (open|answered and applied locally|answered and implemented in task T\d+\.\d+)$"
)

#: Texts that must not appear in the release documents: claims of events that did not happen.
FORBIDDEN_CLAIMS = (
    "was released on",
    "released on 20",
    "tested on a clean windows",
    "has been tested on",
    "code-signed",
    "is signed",
    "tem assinatura digital",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


#: The status line of a manual test document: either not executed, or executed on a date with a
#: result after it ("EXECUTADO em 2026-12-01, resultado: aprovado").
_STATUS_LINE = re.compile(
    r"Status da execução: (?:NÃO EXECUTADO"
    r"|EXECUTADO em (?:\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})\W+\w[^\n]*)"
)


def _has_status_line(text: str) -> bool:
    return _STATUS_LINE.search(text) is not None


def _entry(version: str) -> str:
    """The text of the ``## [version]`` entry of the changelog, up to the next entry."""
    lines = _read(CHANGELOG).splitlines()
    start = next(
        (i for i, line in enumerate(lines) if re.match(rf"^## \[{re.escape(version)}\]", line)),
        None,
    )
    assert start is not None, f"CHANGELOG.md has no entry for {version}"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            end = i
            break
    return "\n".join(lines[start:end])


def _section(entry: str, heading_start: str) -> list[str]:
    """The lines of the ``### heading_start...`` section of ``entry`` (without the heading)."""
    lines = entry.splitlines()
    prefix = f"### {heading_start}"
    start = next((i for i, line in enumerate(lines) if line.startswith(prefix)), None)
    assert start is not None, f"the entry has no section '{heading_start}'"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("### "):
            end = i
            break
    return lines[start + 1 : end]


def _one_line(text: str) -> str:
    return " ".join(text.lower().split())


# --- the version -----------------------------------------------------------------------------


def test_version_has_the_form_major_minor_patch() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__), __version__


def test_version_is_set_in_one_place_and_read_by_the_build() -> None:
    found = re.findall(r'^__version__ = "([^"]+)"', _read(INIT), re.MULTILINE)
    assert found == [__version__]
    project = tomllib.loads(_read(ROOT / "pyproject.toml"))
    assert "version" in project["project"]["dynamic"]
    assert "version" not in project["project"]
    assert project["tool"]["hatch"]["version"]["path"] == "src/cbrn_dashboard/__init__.py"


def test_version_equals_the_installed_metadata() -> None:
    # A stale editable install fails here on purpose: run ``uv sync`` after a version change.
    assert metadata.version("cbrn-readiness-dashboard") == __version__


def test_the_lock_file_does_not_pin_another_version_of_the_project() -> None:
    lock = _read(ROOT / "uv.lock")
    blocks = re.split(r"^\[\[package\]\]\r?\n", lock, flags=re.MULTILINE)
    mine = [block for block in blocks if block.startswith('name = "cbrn-readiness-dashboard"')]
    assert len(mine) == 1
    versions = re.findall(r'^version = "([^"]+)"', mine[0], re.MULTILINE)
    # An editable project is recorded without a version; if uv ever records one, it must match.
    assert versions in ([], [__version__])


def test_the_version_is_not_stated_as_the_old_one_anywhere() -> None:
    documents = [
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        *DOCS.glob("*.md"),
        *(ROOT / "packaging").glob("README-first-run.*.txt"),
    ]
    stale = [path.name for path in documents if "0.0.1" in _read(path)]
    assert stale == []


def test_the_readme_states_the_version_and_links_the_release_material() -> None:
    text = _read(ROOT / "README.md")
    assert __version__ in text
    assert "(CHANGELOG.md)" in text
    assert "(docs/smoke-test.pt-BR.md)" in text
    assert "https://github.com/marco-jardim/cbrn-readiness-dashboard/releases" in text


def test_the_readme_states_the_current_and_the_last_published_version() -> None:
    text = _read(ROOT / "README.md")
    assert f"Version {LAST_PUBLISHED} was published on GitHub on {LAST_PUBLISHED_DATE}" in text
    assert f"/releases/tag/v{LAST_PUBLISHED})" in text
    assert f"cbrn-readiness-dashboard-{__version__}-win-x64-setup.exe" in text
    assert "(docs/manual-test-script.pt-BR.md)" in text
    assert "still pending" in text
    assert "unsigned" in text


@pytest.mark.parametrize("language", LANGUAGES)
def test_install_guides_state_the_version_and_the_last_published_one(
    language: str,
) -> None:
    text = _read(DOCS / f"install.{language}.md")
    assert f"`{__version__}`" in text
    assert "smoke-test.pt-BR.md" in text
    assert "manual-test-script.pt-BR.md" in text
    assert LAST_PUBLISHED_DATE in text
    assert f"/releases/tag/v{LAST_PUBLISHED})" in text


def test_the_architecture_document_states_the_version() -> None:
    assert f"`{__version__}`" in _read(DOCS / "architecture.md")


# --- the changelog ---------------------------------------------------------------------------


def test_the_changelog_has_an_entry_for_the_current_version() -> None:
    entry = _entry(__version__)
    assert entry.startswith(f"## [{__version__}]")


def test_the_changelog_entry_states_its_publication_status() -> None:
    entry = _entry(__version__)
    heading = entry.splitlines()[0]
    text = _one_line(entry)
    dated = re.fullmatch(rf"## \[{re.escape(__version__)}\] - (\d{{4}}-\d{{2}}-\d{{2}})", heading)
    if dated is None:
        # Not published: the heading says so, and the entry says what has not happened.
        assert heading == f"## [{__version__}] - unreleased"
        assert "no tag" in text
        assert "has never run" in text
        assert "has not been executed yet" in text
    else:
        # Dated by the person who publishes, never before: the entry states the publication, links
        # the release and says whether the manual test was executed (it may come after the date).
        date = dated.group(1)
        assert f"was published on github on {date}" in text
        assert f"releases/tag/v{__version__}" in text
        assert "status of this entry: published" in text
        assert "not been executed yet" in text or "was executed on" in text


def test_the_changelog_lists_exactly_the_flagged_placeholders() -> None:
    lines = _section(_entry(__version__), "Placeholders still flagged")
    listed: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^- `([A-Z]\d\d)`( - .*)?$", line)
        if match is not None:
            assert match.group(1) not in listed, f"{match.group(1)} is listed twice"
            listed[match.group(1)] = line
    assert set(listed) == set(flagged_placeholder_ids())


def test_the_changelog_marks_the_local_only_values() -> None:
    lines = _section(_entry(__version__), "Placeholders still flagged")
    marked = {
        match.group(1)
        for line in lines
        if (match := re.match(r"^- `([A-Z]\d\d)`.*\(local-only\)$", line)) is not None
    }
    local_only = {item.id for item in PLACEHOLDERS if item.kind is PlaceholderKind.LOCAL_ONLY}
    assert local_only
    assert marked == local_only


def test_the_local_only_values_are_flagged_and_have_no_code_default() -> None:
    flagged = set(flagged_placeholder_ids())
    defaults = ReadinessConfig()
    for placeholder_id in LOCAL_ONLY_IDS:
        item = placeholder(placeholder_id)
        assert item.kind is PlaceholderKind.LOCAL_ONLY, placeholder_id
        assert placeholder_id in flagged, f"{placeholder_id} lost its flag"
        for name in item.fields:
            assert getattr(defaults, name) in ("", None), f"{name} has a code default"
    # The indicator targets (P03) live in their own table and have no config field at all.
    assert placeholder("P03").fields == ()
    # Nothing else is local-only: the list above is the whole of it.
    assert {item.id for item in PLACEHOLDERS if item.kind is PlaceholderKind.LOCAL_ONLY} == set(
        LOCAL_ONLY_IDS
    )


def test_the_changelog_lists_the_assumptions_without_a_setting_as_questions_only() -> None:
    lines = _section(_entry(__version__), "Assumptions without a setting")
    items = {
        match.group(1): match.group(2)
        for line in lines
        if (match := re.match(r"^- (A\d\d) depends on (Q\d+(?: and Q\d+)*)$", line)) is not None
    }
    assert set(items) == ASSUMPTIONS_WITHOUT_SETTING
    registered = {item.id for item in PLACEHOLDERS}
    assert not (set(items) & registered), "an assumption without a setting is flagged in the code"


def test_every_open_question_is_listed_by_its_status_only() -> None:
    lines = _section(_entry(__version__), "Open questions")
    bullets = [line for line in lines if line.startswith("- ")]
    assert bullets
    found: dict[str, str] = {}
    for line in bullets:
        match = STATUS_FORM.match(line)
        assert match is not None, f"not of the form '- Qn: <status>': {line!r}"
        assert match.group(1) not in found, f"{match.group(1)} is listed twice"
        found[match.group(1)] = match.group(2)
    assert set(found) == {f"Q{number}" for number in QUESTION_NUMBERS}


def test_the_changelog_lists_the_questions_of_the_plan() -> None:
    # Section 12 of the plan opens every question with "**Qn" and an em dash.
    in_plan = {
        f"Q{number}" for number in re.findall(r"^\*\*Q(\d+) \u2014", _read(PLAN), re.MULTILINE)
    }
    assert in_plan == {f"Q{number}" for number in QUESTION_NUMBERS}
    lines = _section(_entry(__version__), "Open questions")
    listed = {match.group(1) for line in lines if (match := STATUS_FORM.match(line)) is not None}
    assert listed == in_plan


def test_the_changelog_states_the_review_status_of_the_translations() -> None:
    text = _one_line("\n".join(_section(_entry(__version__), "Translations")))
    assert "q14" in text
    assert "pending" in text
    assert "unfinished" in text
    assert "drafts" in text


def _unfinished_counts() -> tuple[int, int]:
    """``(occurrences of type="unfinished", messages whose translation is unfinished)``."""
    files = sorted(I18N.glob("*.ts"))
    assert files
    occurrences = 0
    messages = 0
    for path in files:
        occurrences += _read(path).count('type="unfinished"')
        for message in ET.parse(path).getroot().iter("message"):
            translation = message.find("translation")
            if translation is not None and translation.get("type") == "unfinished":
                messages += 1
    return occurrences, messages


def test_the_unfinished_count_stated_equals_the_count_found() -> None:
    occurrences, messages = _unfinished_counts()
    # One marker per message: a marker anywhere else would make the count ambiguous.
    assert occurrences == messages
    lines = _section(_entry(__version__), "Translations")
    stated = [
        int(match.group(1))
        for line in lines
        if (match := re.match(r"^- Messages still marked unfinished: (\d+)\b", line)) is not None
    ]
    if messages == 0:
        text = _one_line("\n".join(lines))
        assert stated in ([], [0])
        assert "none remain" in text or stated == [0]
    else:
        assert stated == [messages]


@pytest.mark.parametrize(
    "needle",
    [
        "unsigned",
        "published on 2026-11-13",
        "published on 2026-11-14",
        "visual c++ runtime",
        "unc",
        "branch protection",
        "has not been run",
    ],
)
def test_the_changelog_states_the_known_limits(needle: str) -> None:
    text = _one_line("\n".join(_section(_entry(__version__), "Known limits")))
    assert needle in text


# --- the release machinery and the smoke test exist ------------------------------------------


def test_the_release_workflow_exists_and_uses_the_release_script() -> None:
    text = _read(WORKFLOW)
    assert "make_release_zip.py" in text
    assert "check-tag" in text
    assert "prerelease-flag" in text
    assert "--draft" in text


def test_the_release_body_template_exists_and_states_the_preliminary_status() -> None:
    text = _read(TEMPLATE)
    assert "{{version}}" in text
    assert "Preliminary version" in text
    assert "unsigned" in text


def test_the_smoke_test_exists_and_names_the_current_version() -> None:
    assert SMOKE_TEST.is_file()
    text = _read(SMOKE_TEST)
    assert __version__ in text
    assert f"cbrn-readiness-dashboard-{__version__}-win-x64.zip" in text


def test_the_smoke_test_states_whether_it_was_executed() -> None:
    text = _read(SMOKE_TEST)
    assert _has_status_line(text)
    assert "perfil" in text.lower()
    assert "administrador" in text.lower()


def test_the_smoke_test_covers_what_the_plan_asks_for() -> None:
    text = _read(SMOKE_TEST).lower()
    for needle in (
        "perfil limpo",
        "pessoal",
        "infraestrutura",
        "exercícios",
        "orçamento",
        "idioma",
        "fazer backup",
        "restaurar",
        "painel",
        "versão preliminar",
        "get-filehash",
        "--demo",
        "demo-walkthrough.md",
        "dados de demonstração de outro dia",
    ):
        assert needle in text, needle


def test_the_smoke_test_links_resolve() -> None:
    for target in re.findall(r"\]\(([^)\s]+)\)", _read(SMOKE_TEST)):
        link = str(target)
        if link.startswith(("http://", "https://", "#")):
            continue
        assert (DOCS / link.split("#", 1)[0]).resolve().exists(), link


def test_the_smoke_test_is_not_a_place_for_real_data() -> None:
    text = _read(SMOKE_TEST).lower()
    assert "não insira dados reais" in text


# --- the manual test script for the committee (T10.5) ----------------------------------------


def _registered_page_keys() -> list[str]:
    """The keys of ``PAGES`` in ``ui/shell/registry.py``, read from the source (no Qt needed)."""
    return re.findall(r'^    PageSpec\("(\w+)",', _read(REGISTRY), re.MULTILINE)


def test_every_registered_page_has_a_title_in_this_module() -> None:
    assert sorted(_registered_page_keys()) == sorted(PAGE_TITLES)


def test_the_page_titles_are_the_portuguese_titles_of_the_catalogues() -> None:
    text = "\n".join(_read(path) for path in sorted(I18N.glob("*_pt_BR.ts")))
    for title in PAGE_TITLES.values():
        assert f">{title}</translation>" in text, title


def test_the_manual_test_script_names_every_registered_page() -> None:
    assert MANUAL_SCRIPT.is_file()
    text = _read(MANUAL_SCRIPT)
    for key, title in PAGE_TITLES.items():
        assert f"**{title}**" in text, f"the manual test script does not name the page {key}"


def test_the_manual_test_script_states_whether_it_was_executed() -> None:
    text = _read(MANUAL_SCRIPT)
    assert _has_status_line(text)
    assert __version__ in text
    assert "não insira dados reais" in text.lower()


def test_the_manual_test_script_covers_what_the_plan_asks_for() -> None:
    text = _read(MANUAL_SCRIPT).lower()
    for needle in (
        "alertas",
        "idioma",
        "ctrl+shift+1",
        "ctrl+shift+2",
        "ctrl+shift+3",
        "mídia removível",
        "fazer backup...",
        "ctrl+b",
        "restaurar...",
        "ctrl+shift+r",
        "12 caracteres",
        "relatório interno",
        "relatório anonimizado",
        "uso interno",
        "exportar arquivos csv",
        "exportação de validação",
        "importar arquivo csv",
        "gravar modelos",
        "somente leitura",
        "--data-dir",
        "attrib +r",
        "dirsa",
        "comando da aeronáutica",
        "habilitação de epi",
        "demo-walkthrough.md",
    ):
        assert needle in text, needle
    assert "certificado" not in text


def test_the_manual_test_script_links_resolve() -> None:
    for target in re.findall(r"\]\(([^)\s]+)\)", _read(MANUAL_SCRIPT)):
        link = str(target)
        if link.startswith(("http://", "https://", "#")):
            continue
        assert (DOCS / link.split("#", 1)[0]).resolve().exists(), link


# --- nothing claims an event that did not happen ---------------------------------------------


def test_no_release_document_claims_a_publication_or_a_signature() -> None:
    documents = [
        ROOT / "README.md",
        CHANGELOG,
        SMOKE_TEST,
        MANUAL_SCRIPT,
        *(DOCS / f"install.{language}.md" for language in LANGUAGES),
    ]
    for path in documents:
        text = _one_line(_read(path))
        found = [claim for claim in FORBIDDEN_CLAIMS if claim in text]
        assert not found, f"{path.name} claims too much: {found}"
