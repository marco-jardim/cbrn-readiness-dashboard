# SPDX-License-Identifier: GPL-3.0-or-later
"""The release material of the current version is complete and says only what is true (T9.6).

The checks read plain files; nothing here tags, builds or publishes anything. They cover:

* the version: one source (``__init__.py``), read by hatch, equal to the installed metadata, and
  stated by the documents that talk about the release;
* ``CHANGELOG.md``: an entry for the version, listing exactly the placeholders still flagged in
  ``domain/config.py`` (none since D39), the local-only values (marked), the assumptions without a
  setting, and every open question by its status only;
* the release machinery (workflow, release-body template) and the manual smoke-test script exist;
* the documents do not claim that a release was published, tested on real machines or signed.

T10.5 extends this module for version 1.0: the entry lists the placeholders still flagged, the
local-only values keep an empty default (T12.13: they are listed, not flagged), the number of
unfinished translation messages stated equals the number found, every question Q1 to Q29 has one of
the three status phrases, and the manual test script for the committee names every registered
page.
"""

from __future__ import annotations

import hashlib
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

#: The last version published on GitHub (1.1.0, on 2026-11-21). The current version in the source
#: may be newer and not published yet; the documents then name both.
LAST_PUBLISHED = "1.1.0"
LAST_PUBLISHED_DATE = "2026-11-21"

#: SHA-256 of the text of every published (dated) changelog entry, by version. The text of a
#: published entry never changes (P11-01): the values are filled by the person who publishes, from
#: the failure message of ``test_every_dated_changelog_entry_is_published_text_that_never_changes``.
PUBLISHED_ENTRY_SHA256: dict[str, str] = {
    "1.1.0": "cd2d298c14369965806c362bf2ed6108d47966f882faee761a8482b93f65efa5",
    "1.0.2": "2c9dc0a05101c08c0666339f983781c1df2d5c953ca56f514e325e402d0eec89",
    "1.0.1": "a2e13f62bdb05372f4d1f01becea3167d07ec1e4b40444ba569d7c891a45f9aa",
}

#: The questions of PLAN.md section 12 that the changelog lists: Q1 to Q29.
QUESTION_NUMBERS = range(1, 30)

#: The local-only values (PLAN.md 3.5): never given a code default, not flagged since D39.
LOCAL_ONLY_IDS = ("P03", "P10", "D18", "P12")

#: Every registered page (registry key) and its Brazilian Portuguese navigation title. The manual
#: test script must name each title; a new page makes the registry test below fail until it is
#: added here and to the script.
PAGE_TITLES = {
    "dashboard": "Painel",
    "personnel": "Pessoal",
    "infrastructure": "Infraestrutura",
    "antidotes": "Ant\u00eddotos e descontaminantes",
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


def _dated_versions() -> list[str]:
    """The versions whose changelog heading carries a date (``## [x.y.z] - YYYY-MM-DD``)."""
    return re.findall(
        r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}\s*$", _read(CHANGELOG), re.MULTILINE
    )


def _entry_sha256(version: str) -> str:
    """SHA-256 (hex) of the entry text: heading to the line before the next ``## `` heading.

    Line endings are normalised to LF and trailing blank lines are dropped; the text is encoded as
    UTF-8. This is the exact recipe to compute a value for ``PUBLISHED_ENTRY_SHA256``.
    """
    text = _entry(version).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_every_dated_changelog_entry_is_published_text_that_never_changes() -> None:
    dated = _dated_versions()
    assert LAST_PUBLISHED in dated, "the last published version has no dated entry"
    for version in dated:
        pinned = PUBLISHED_ENTRY_SHA256.get(version, "")
        actual = _entry_sha256(version)
        assert pinned, (
            f"the dated entry [{version}] is not pinned: put '{version}': '{actual}' in "
            "PUBLISHED_ENTRY_SHA256 (only after checking that the entry is the published text)"
        )
        assert actual == pinned, (
            f"the published entry [{version}] was edited (sha256 {actual}, pinned {pinned}); "
            "a published entry is history: put the correction in the current entry instead"
        )


def test_every_pinned_entry_is_still_a_dated_entry() -> None:
    assert set(PUBLISHED_ENTRY_SHA256) <= set(_dated_versions())


def test_the_changelog_lists_exactly_the_flagged_placeholders() -> None:
    lines = _section(_entry(__version__), "Placeholders still flagged")
    listed: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^- `([A-Z]\d\d)`( - .*)?$", line)
        if match is not None:
            assert match.group(1) not in listed, f"{match.group(1)} is listed twice"
            listed[match.group(1)] = line
    assert set(listed) == set(flagged_placeholder_ids())
    if not flagged_placeholder_ids():
        # D39: no flag is set; the section says so in a sentence and has no bullet.
        assert not [line for line in lines if line.startswith("- ")]
        assert "no placeholder is flagged" in _one_line(" ".join(lines))


def test_the_changelog_lists_the_local_only_values_marked_local_only() -> None:
    lines = _section(_entry(__version__), "Local-only values")
    bullets = [line for line in lines if line.startswith("- ")]
    listed: dict[str, str] = {}
    for line in bullets:
        match = re.match(r"^- `([A-Z]\d\d)` - .+ \(local-only\)$", line)
        assert match is not None, f"not of the form '- `Xnn` - text (local-only)': {line!r}"
        assert match.group(1) not in listed, f"{match.group(1)} is listed twice"
        listed[match.group(1)] = line
    local_only = {item.id for item in PLACEHOLDERS if item.kind is PlaceholderKind.LOCAL_ONLY}
    assert local_only
    assert set(listed) == local_only


def test_the_local_only_values_have_empty_code_defaults() -> None:
    defaults = ReadinessConfig()
    for placeholder_id in LOCAL_ONLY_IDS:
        item = placeholder(placeholder_id)
        assert item.kind is PlaceholderKind.LOCAL_ONLY, placeholder_id
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


def test_the_release_body_template_exists_without_the_preliminary_notice() -> None:
    text = _read(TEMPLATE)
    assert "{{version}}" in text
    assert "Preliminary version" not in text
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


def test_the_manual_test_guide_names_the_current_version() -> None:
    assert __version__ in _read(DOCS / "guia-teste-manual.pt-BR.md")


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


# --- the placeholder confirmation is gone (PLAN.md D39, T12.12) ------------------------------

_REMOVED_CONFIRMATION_IDENTIFIERS = re.compile(
    r"\b(?:needs_badge|badge_for_field|confirm_placeholder|unconfirm|unconfirm_placeholder"
    r"|confirmed_placeholders|CONFIRMED_PREFIX|PlaceholderBadge|UNKNOWN_PLACEHOLDER)\b"
)


def test_no_placeholder_confirmation_remains_in_the_source() -> None:
    sources = sorted((ROOT / "src").rglob("*.py"))
    assert sources, "the source tree was not found"
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{number}: {match.group(0)}"
        for path in sources
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        for match in _REMOVED_CONFIRMATION_IDENTIFIERS.finditer(line)
    ]
    assert not found, f"placeholder confirmation code is back: {found}"


# --- no preliminary notice and no real-data gate anywhere (PLAN.md D39, T12.14) --------------

#: The wordings of the removed notices, matched on lower-case text with the whitespace collapsed.
#: "Do not enter real data" alone is not listed: the test scripts keep "Não insira dados reais."
#: (it refers to the test runs); only the gate form (until / yet) is removed.
_REMOVED_NOTICE_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"preliminary version",
        r"vers[ãa]o preliminar",
        r"versi[óo]n preliminar",
        r"institutionally validated",
        r"validad[oa]s? institucionalmente",
        r"placeholder [-\u2013\u2014] to be confirmed",
        r"valor provis[óo]rio [-\u2013\u2014] a confirmar",
        r"valor provisional [-\u2013\u2014] por confirmar",
        r"do not enter real data",
        r"real data must not be entered",
        r"n[ãa]o (?:insira|digite) dados reais (?:at[ée]|ainda)",
        r"no introduzca (?:todav[íi]a )?datos reales",
    )
)

#: A claim that the tool (or its indicators) is validated, approved or homologated (R30, K25): a
#: subject about the tool, then an affirmative verb, then the claim. Matched on lower-case text
#: with the whitespace collapsed; negated sentences are dropped by ``_validation_claims``.
_VALIDATION_CLAIM = re.compile(
    r"\b(?:tool|app|application|software|dashboard|indicators?|aplicativo|ferramenta|painel"
    r"|indicadores?|aplicaci[óo]n|herramienta)\b[^.\n]{0,40}"
    r"\b(?:is|are|has been|have been|was|were|foi|foram|está|estão|é|são"
    r"|fue|fueron|es|son)\s+(?:institutionally\s+|institucionalmente\s+)?"
    r"(?:validated|approved|homologated|validad[oa]s?|aprovad[oa]s?|aprobad[oa]s?"
    r"|homologad[oa]s?)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:not|no|never|n[ãa]o|nem|nunca|sin|sem|ni)\b", re.IGNORECASE)
_SENTENCE_BREAK = (". ", "! ", "? ", ": ", ";")


def _validation_claims(text: str) -> list[str]:
    """The affirmative validation claims of ``text`` (a negation in the sentence cancels one)."""
    line = _one_line(text)
    claims: list[str] = []
    for match in _VALIDATION_CLAIM.finditer(line):
        start = max(line.rfind(mark, 0, match.start()) for mark in _SENTENCE_BREAK)
        # From the start of the sentence to the end of the claim: "does not show that ... are
        # validated" is a disclaimer, not a claim.
        if not _NEGATION.search(line[start + 1 : match.end()]):
            claims.append(match.group(0))
    return claims


#: Files that may still quote the removed notices: the history (CHANGELOG, PLAN). The committee
#: questionnaire is scanned too, except for the original question texts (``_QUESTION_START``).
#: No script, workflow or installer file needed an exemption (checked against the patterns).
_NOTICE_EXEMPT = frozenset({"CHANGELOG.md", "PLAN.md"})
_QUESTIONNAIRE = "docs/questionario-comite.pt-BR.md"
_QUESTION_START = "**Pergunta.**"


def _without_questions(text: str) -> str:
    """The questionnaire without its original question texts.

    A question starts with ``**Pergunta.**`` and runs to the next blank line (it may wrap).
    """
    kept: list[str] = []
    in_question = False
    for line in text.splitlines():
        if line.startswith(_QUESTION_START):
            in_question = True
            continue
        if in_question and line.strip():
            continue
        in_question = False
        kept.append(line)
    return "\n".join(kept)


def _scanned_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.relative_to(ROOT).as_posix() == _QUESTIONNAIRE:
        return _without_questions(text)
    return text


def _files_scanned_for_the_removed_notices() -> list[Path]:
    src = ROOT / "src"
    packaging = ROOT / "packaging"
    github = ROOT / ".github"
    files = [
        *src.rglob("*.py"),
        *src.rglob("*.md"),
        *src.rglob("*.ts"),
        *packaging.rglob("*.txt"),
        *(packaging / "installer").glob("*.iss"),
        *github.rglob("*.md"),
        *github.rglob("*.yml"),
        *github.rglob("*.yaml"),
        *(ROOT / "scripts").rglob("*.py"),
        TEMPLATE,
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        *DOCS.glob("*.md"),
    ]
    return sorted(
        path
        for path in set(files)
        if path.is_file() and path.relative_to(ROOT).as_posix() not in _NOTICE_EXEMPT
    )


def test_no_file_shows_the_preliminary_notice_or_the_real_data_gate() -> None:
    files = _files_scanned_for_the_removed_notices()
    names = {path.relative_to(ROOT).as_posix() for path in files}
    # The scan must really cover the places the notices lived in.
    assert "README.md" in names
    assert "CONTRIBUTING.md" in names
    assert ".github/release-body.template.md" in names
    assert ".github/workflows/release.yml" in names
    assert "docs/install.pt-BR.md" in names
    assert _QUESTIONNAIRE in names
    assert "packaging/installer/cbrn-dashboard.iss" in names
    assert "scripts/make_release_zip.py" in names
    assert any(name.endswith(".py") for name in names)
    assert any(name.endswith(".ts") for name in names)
    assert not names & _NOTICE_EXEMPT
    found = [
        f"{path.relative_to(ROOT).as_posix()}: {match.group(0)!r}"
        for path in files
        for match in (
            pattern.search(_one_line(_scanned_text(path))) for pattern in _REMOVED_NOTICE_PATTERNS
        )
        if match
    ]
    assert not found, f"a removed notice or gate is back: {found}"


def test_no_file_claims_that_the_tool_is_validated() -> None:
    found = [
        f"{path.relative_to(ROOT).as_posix()}: {claim!r}"
        for path in _files_scanned_for_the_removed_notices()
        for claim in _validation_claims(_scanned_text(path))
    ]
    assert not found, f"a validation claim is back (R30, K25): {found}"


def test_the_questionnaire_guard_skips_only_the_question_texts() -> None:
    text = (
        "### Q15 - Aviso de versão preliminar\n\n"
        '**Pergunta.** O que deve dizer o aviso "versão preliminar"\n'
        "e onde ele deve aparecer?\n\n"
        "**Como o aplicativo funciona hoje.** Sem aviso.\n"
    )
    kept = _without_questions(text)
    assert "e onde ele deve aparecer" not in kept
    assert "**Pergunta.**" not in kept
    assert "Aviso de versão preliminar" in kept  # a heading is not an original question
    assert "Sem aviso." in kept
    # The notice wording inside the question alone is skipped; the one in the heading is found.
    assert any(pattern.search(_one_line(kept)) for pattern in _REMOVED_NOTICE_PATTERNS)
    clean = _without_questions(text.replace("Aviso de versão preliminar", "Aviso"))
    assert not any(pattern.search(_one_line(clean)) for pattern in _REMOVED_NOTICE_PATTERNS)


def test_the_validation_claim_guard_matches_affirmative_claims_only() -> None:
    assert _validation_claims("The tool has been validated by the committee.")
    assert _validation_claims("The indicators are validated.")
    assert _validation_claims("O aplicativo foi homologado.")
    assert _validation_claims("O aplicativo foi institucionalmente validado.")
    assert _validation_claims("La herramienta fue aprobada\npor el comité.")
    assert not _validation_claims(
        "the software makes no claim of institutional homologation (an institutional step)."
    )
    assert not _validation_claims("The indicators are not validated.")
    assert not _validation_claims("O aplicativo não foi validado.")
    assert not _validation_claims("La herramienta no es validada.")
    assert not _validation_claims(
        "It does not show that the program is safe or that its indicators are validated."
    )
    assert not _validation_claims("O orçamento foi aprovado.")
    assert not _validation_claims("Every release is approved by hand before it is signed.")
    # A negation in ANOTHER sentence does not cancel the claim.
    assert _validation_claims("It is not official. The tool is validated.")


def test_the_notice_guard_matches_the_removed_wordings_only() -> None:
    def hits(text: str) -> bool:
        line = _one_line(text)
        return any(pattern.search(line) for pattern in _REMOVED_NOTICE_PATTERNS)

    assert hits("**Preliminary version - indicators not institutionally validated.**")
    assert hits("Versão  preliminar\n- indicadores")
    assert hits("Versión preliminar — indicadores no validados institucionalmente.")
    assert hits("Valor provisório - a confirmar")
    assert hits("Do not enter real data yet")
    assert hits("Não insira dados reais até que as perguntas sejam respondidas")
    assert hits("No introduzca todavía datos reales")
    assert not hits("Versions below 1.0.0 are preliminary and are published as pre-releases.")
    assert not hits("**Não insira dados reais.** Todos os dados deste roteiro são fictícios.")
    assert not hits("No real data in the repository; sensitive is a working label.")
