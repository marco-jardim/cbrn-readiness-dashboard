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

T10.5 extends this module for version 1.0.
"""

from __future__ import annotations

import re
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

from cbrn_dashboard import __version__
from cbrn_dashboard.domain.config import (
    PLACEHOLDERS,
    PlaceholderKind,
    flagged_placeholder_ids,
)

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
INIT = ROOT / "src" / "cbrn_dashboard" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
SMOKE_TEST = DOCS / "smoke-test.pt-BR.md"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
TEMPLATE = ROOT / ".github" / "release-body.template.md"
LANGUAGES = ("pt-BR", "en-US", "es-ES")

#: The A-items without a setting (PLAN.md 3.5): assumptions, listed in the changelog as open
#: questions only.
ASSUMPTIONS_WITHOUT_SETTING = {"A01", "A03", "A12", "A13", "A14"}

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


@pytest.mark.parametrize("language", LANGUAGES)
def test_install_guides_state_the_version_as_prepared_and_not_published(language: str) -> None:
    text = _read(DOCS / f"install.{language}.md")
    assert f"`{__version__}`" in text
    assert "smoke-test.pt-BR.md" in text


def test_the_architecture_document_states_the_version() -> None:
    assert f"`{__version__}`" in _read(DOCS / "architecture.md")


# --- the changelog ---------------------------------------------------------------------------


def test_the_changelog_has_an_entry_for_the_current_version() -> None:
    entry = _entry(__version__)
    assert entry.startswith(f"## [{__version__}]")


def test_the_changelog_entry_says_that_nothing_was_published() -> None:
    entry = _entry(__version__)
    heading = entry.splitlines()[0]
    # The entry is dated by the person who publishes the draft, never before.
    assert "unreleased" in heading.lower() or re.search(r"\d{4}-\d{2}-\d{2}", heading)
    text = _one_line(entry)
    if "unreleased" in heading.lower():
        assert "no tag" in text
        assert "has never run" in text
        assert "has not been executed yet" in text


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
    assert set(found) == {f"Q{number}" for number in range(1, 20)}


def test_the_changelog_states_the_review_status_of_the_translations() -> None:
    text = _one_line("\n".join(_section(_entry(__version__), "Translations")))
    assert "q14" in text
    assert "pending" in text
    assert "unfinished" in text
    assert "drafts" in text


@pytest.mark.parametrize(
    "needle",
    [
        "unsigned",
        "has never run",
        "to be confirmed",
        "pointer only",
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


def test_the_smoke_test_says_that_it_was_not_executed() -> None:
    text = _read(SMOKE_TEST)
    assert "NÃO EXECUTADO" in text
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


# --- nothing claims an event that did not happen ---------------------------------------------


def test_no_release_document_claims_a_publication_or_a_signature() -> None:
    documents = [
        ROOT / "README.md",
        CHANGELOG,
        SMOKE_TEST,
        *(DOCS / f"install.{language}.md" for language in LANGUAGES),
    ]
    for path in documents:
        text = _one_line(_read(path))
        found = [claim for claim in FORBIDDEN_CLAIMS if claim in text]
        assert not found, f"{path.name} claims too much: {found}"
