# SPDX-License-Identifier: GPL-3.0-or-later
"""The reference documents cannot drift from the code (PLAN.md T10.3).

The Markdown files are read as plain text, with regular expressions and ``ast``; no Markdown
library is needed. What is compared with the code:

* ``docs/install.{pt-BR,en-US,es-ES}.md``: the same heading structure, the same required
  statements, every command-line option of ``cli.py``, the file names of the release scripts and
  the current version (so that a version bump forces a second look at the "not released" text);
* ``docs/indicators.md``: one entry per registered indicator code, with its module, unit,
  direction, dimension keys, source and proposal flag, and one row per placeholder of
  ``domain/config.py`` with its kind, fields, code flag and question;
* ``docs/architecture.md``: every top-level package and module of ``src/cbrn_dashboard``, every
  migration file, page, settings group, start-up hook and translation area.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from cbrn_dashboard import __version__
from cbrn_dashboard.cli import LANG_CHOICES
from cbrn_dashboard.domain.alerts import SEVERITY_OF, AlertKind
from cbrn_dashboard.domain.config import (
    DAILY_BACKUPS_FLOOR,
    PASSPHRASE_LENGTH_FLOOR,
    PLACEHOLDERS,
    Placeholder,
    ReadinessConfig,
)
from cbrn_dashboard.domain.indicators import IndicatorStatus
from cbrn_dashboard.domain.registry import build_registry

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
PACKAGE = ROOT / "src" / "cbrn_dashboard"
REGISTRY_SOURCE = PACKAGE / "ui" / "shell" / "registry.py"

INDICATORS = DOCS / "indicators.md"
ARCHITECTURE = DOCS / "architecture.md"
LANGUAGES = ("pt-BR", "en-US", "es-ES")
REFERENCE_DOCS = (
    *(DOCS / f"install.{language}.md" for language in LANGUAGES),
    INDICATORS,
    ARCHITECTURE,
)

REGISTRY = build_registry()
REGISTERED = REGISTRY.codes()

GUIDE_NEEDLES = (
    "Get-FileHash",
    "gh attestation verify",
    r"%LOCALAPPDATA%\cbrn-readiness-dashboard",
    "AppLocker",
    "WDAC",
    "Smart App Control",
    "SmartScreen",
    "Mark-of-the-Web",
    "portable.ini",
    "CBRN_DASHBOARD_DATA_DIR",
    "unfinished",
    "UNC",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _guide(language: str) -> Path:
    return DOCS / f"install.{language}.md"


def _ticks(text: str) -> list[str]:
    """The contents of the backtick spans of ``text``."""
    return [str(item) for item in re.findall(r"`([^`]+)`", text)]


def _heading_levels(text: str) -> list[int]:
    """The level of every Markdown heading outside code fences, in order."""
    levels: list[int] = []
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6}) \S", line)
        if match is not None:
            levels.append(len(match.group(1)))
    return levels


# --- the documents exist, and their links resolve ------------------------------------------------


@pytest.mark.parametrize("path", REFERENCE_DOCS, ids=lambda path: path.name)
def test_reference_document_exists(path: Path) -> None:
    assert path.is_file(), f"{path} is missing"
    assert len(_read(path).splitlines()) > 20


@pytest.mark.parametrize("path", REFERENCE_DOCS, ids=lambda path: path.name)
def test_relative_links_resolve(path: Path) -> None:
    for target in re.findall(r"\]\(([^)\s]+)\)", _read(path)):
        link = str(target)
        if link.startswith(("http://", "https://", "#")):
            continue
        resolved = (path.parent / link.split("#", 1)[0]).resolve()
        assert resolved.exists(), f"{path.name} links to {link}, which does not exist"


# --- install guides ------------------------------------------------------------------------------


def test_install_guides_have_the_same_heading_structure() -> None:
    reference = _heading_levels(_read(_guide("en-US")))
    assert len(reference) > 15
    for language in LANGUAGES:
        levels = _heading_levels(_read(_guide(language)))
        assert levels == reference, f"{_guide(language).name} has a different heading structure"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("needle", GUIDE_NEEDLES)
def test_install_guide_mentions(language: str, needle: str) -> None:
    path = _guide(language)
    assert needle in _read(path), f"{path.name} does not mention {needle!r}"


def _cli_options() -> list[str]:
    source = _read(PACKAGE / "cli.py")
    return [str(item) for item in re.findall(r'add_argument\(\s*"(--[a-z-]+)"', source)]


def test_cli_options_are_found() -> None:
    assert {"--data-dir", "--lang", "--self-test", "--demo", "--version"} <= set(_cli_options())


@pytest.mark.parametrize("language", LANGUAGES)
def test_install_guide_names_every_command_line_option(language: str) -> None:
    text = _read(_guide(language))
    for option in _cli_options():
        assert f"`{option}" in text, f"{_guide(language).name} does not mention {option}"
    for choice in LANG_CHOICES:
        assert choice in text, f"{_guide(language).name} does not mention {choice}"


def _script_constant(name: str) -> str:
    source = _read(ROOT / "scripts" / "make_release_zip.py")
    match = re.search(rf'^{name} = "([^"]+)"', source, re.MULTILINE)
    assert match is not None, f"{name} not found in scripts/make_release_zip.py"
    return str(match.group(1))


@pytest.mark.parametrize("language", LANGUAGES)
def test_install_guide_uses_the_release_file_names(language: str) -> None:
    text = _read(_guide(language))
    zip_name = _script_constant("ZIP_NAME_FORMAT").replace("{version}", "<version>")
    for name in (zip_name, _script_constant("SUMS_NAME"), _script_constant("FILES_MANIFEST_NAME")):
        assert name in text, f"{_guide(language).name} does not mention {name}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_install_guide_states_the_current_version(language: str) -> None:
    # A version bump makes this fail on purpose: re-read the "no release yet" statements.
    assert f"`{__version__}`" in _read(_guide(language))


#: P9-02: the manifest holds flat SHA-256 file hashes. No text may say that allow-listing rules are
#: built from it, or tell IT to "take the hashes" for a product; it only verifies files.
HASH_RULE_CLAIMS: tuple[str, ...] = (
    "allow-list by file hash",
    "write hash rules",
    "take the hashes",
    "use os hashes",
    "tome los hashes",
    "regras de hash com o manifesto",
    "reglas de hash con el manifiesto",
)
POLICY_TOOLING = {
    "en-US": "policy tooling of your own organisation",
    "pt-BR": "ferramentas de política da própria organização",
    "es-ES": "herramientas de política de su propia organización",
}


def _hash_claim_sources() -> list[Path]:
    notes = sorted((ROOT / "packaging").glob("README-first-run.*.txt"))
    assert len(notes) == 3
    return [*notes, ROOT / ".github" / "release-body.template.md", *map(_guide, LANGUAGES)]


@pytest.mark.parametrize("path", _hash_claim_sources(), ids=lambda path: path.name)
def test_no_text_claims_that_hash_rules_come_from_the_manifest(path: Path) -> None:
    text = " ".join(_read(path).lower().split())
    found = [claim for claim in HASH_RULE_CLAIMS if claim in text]
    assert not found, f"{path.name} claims too much about SHA256-FILES.txt: {found}"
    assert "SHA256-FILES.txt" in _read(path)


@pytest.mark.parametrize("note", _hash_claim_sources()[:3], ids=lambda path: path.name)
def test_first_run_notes_state_the_licence_as_licenses_readme_does(note: Path) -> None:
    """P9-13: project source GPL-3.0-or-later, the bundle as a whole GPL-3.0 - everywhere."""
    readme = " ".join(_read(ROOT / "packaging" / "licenses" / "README.md").split())
    assert "source code of the application is GPL-3.0-or-later" in readme
    assert "distributed under GPL-3.0" in readme
    text = " ".join(_read(note).split())
    assert "GPL-3.0-or-later" in text
    assert "GPL-3.0 (" in text  # "... the bundle as a whole is GPL-3.0 (see licenses\README.md)"


def test_version_resource_copyright_says_both_licences() -> None:
    source = _read(ROOT / "scripts" / "build_exe.py")
    match = re.search(r'^VERSION_FILE_COPYRIGHT = "([^"]+)"', source, re.MULTILINE)
    assert match is not None
    assert "GPL-3.0-or-later" in match.group(1)
    assert "bundle: GPL-3.0" in match.group(1)


@pytest.mark.parametrize("language", LANGUAGES)
def test_install_guide_leaves_the_rules_to_the_organisations_own_tooling(language: str) -> None:
    text = " ".join(_read(_guide(language)).split())
    assert POLICY_TOOLING[language] in text


# --- indicators.md -------------------------------------------------------------------------------

ENTRY_HEADING = re.compile(r"^### `([A-Z][A-Z0-9_]*)`\s*$")
PLACEHOLDER_ID = re.compile(r"[APD]\d\d")
ALERT_ROW = re.compile(r"^\| `([A-Z_]+)` \| `([A-Z]+)` \|")
QUESTION_ROW = re.compile(r"^\| (Q\d+) \|")


def _entries(text: str) -> dict[str, list[str]]:
    """The lines of every ``### `CODE` `` entry, by code."""
    entries: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("#"):
            match = ENTRY_HEADING.match(line)
            if match is None:
                current = None
            else:
                code = match.group(1)
                assert code not in entries, f"{code} is documented twice"
                current = entries.setdefault(code, [])
            continue
        if current is not None:
            current.append(line)
    return entries


def _field(lines: list[str], label: str) -> str:
    prefix = f"- {label}: "
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return pytest.fail(f"the entry has no '{label}' line")


def test_every_registered_indicator_is_documented_and_nothing_else() -> None:
    documented = set(_entries(_read(INDICATORS)))
    registered = set(REGISTERED)
    assert registered, "the registry is empty"
    assert registered - documented == set(), "indicators missing from docs/indicators.md"
    assert documented - registered == set(), "docs/indicators.md documents unknown indicators"


def test_no_unknown_indicator_code_is_mentioned() -> None:
    prefixes = sorted({code.split("_")[0] for code in REGISTERED})
    pattern = re.compile(rf"\b(?:{'|'.join(prefixes)})_[A-Z0-9_]+\b")
    mentioned = {str(token) for token in pattern.findall(_read(INDICATORS))}
    assert mentioned - set(REGISTERED) == set()


@pytest.mark.parametrize("code", REGISTERED)
def test_indicator_entry_matches_the_registry(code: str) -> None:
    definition = REGISTRY.get(code)
    lines = _entries(_read(INDICATORS)).get(code)
    assert lines is not None, f"{code} is not documented"
    assert _ticks(_field(lines, "Module")) == [definition.module.value]
    assert _ticks(_field(lines, "Unit")) == [definition.unit.value]
    assert _ticks(_field(lines, "Direction")) == [definition.direction.value]
    keys = _field(lines, "Dimension keys")
    if definition.dimension_keys:
        assert _ticks(keys) == list(definition.dimension_keys)
    else:
        assert keys == "none"
    assert _ticks(_field(lines, "Source")) == [definition.source]
    appendix = _field(lines, "Appendix line")
    if re.search(r"\bO\d\d\b", definition.source):
        # an owner-request indicator (O01-O04) is not in Appendix A: it has no Lnn reference
        assert appendix == "none (owner request 2026-11-20)"
    else:
        assert re.fullmatch(r"L\d+(, L\d+)*", appendix) is not None
    proposal = _field(lines, "Proposal")
    if definition.proposal:
        assert _ticks(proposal)[:1] == [definition.proposal]
    else:
        assert proposal == "none"
    assert _field(lines, "Default target").startswith("none")
    assert _field(lines, "Definition")


def test_every_indicator_status_is_explained() -> None:
    text = _read(INDICATORS)
    for status in IndicatorStatus:
        assert f"`{status.value}`" in text, status


def _placeholder_rows(text: str) -> dict[str, list[str]]:
    """The cells of every row of the placeholder table, by placeholder id."""
    rows: dict[str, list[str]] = {}
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if PLACEHOLDER_ID.fullmatch(cells[0]) is None:
            continue
        assert len(cells) == 6, line  # id, kind, fields, default, code flag, question
        assert cells[0] not in rows, f"{cells[0]} appears twice"
        rows[cells[0]] = cells
    return rows


def _default_words(field_name: str) -> list[str]:
    """How the default of a configuration field is written in the table (empty: not checked)."""
    value: object = getattr(ReadinessConfig(), field_name)
    if isinstance(value, bool):
        return ["on" if value else "off"]
    if isinstance(value, int):
        return [str(value)]
    if isinstance(value, str) and value:
        return [value]
    return []


def test_every_placeholder_of_the_code_has_a_row_and_nothing_else() -> None:
    documented = set(_placeholder_rows(_read(INDICATORS)))
    declared = {item.id for item in PLACEHOLDERS}
    assert declared - documented == set(), "placeholders missing from docs/indicators.md"
    assert documented - declared == set(), "docs/indicators.md lists unknown placeholders"


@pytest.mark.parametrize("placeholder", PLACEHOLDERS, ids=[item.id for item in PLACEHOLDERS])
def test_placeholder_row_matches_the_code(placeholder: Placeholder) -> None:
    cells = _placeholder_rows(_read(INDICATORS))[placeholder.id]
    _, kind, fields, default, flag, question = cells
    assert _ticks(kind) == [placeholder.kind.value]
    if placeholder.fields:
        assert _ticks(fields) == list(placeholder.fields)
    else:
        assert fields.startswith("none")
    assert flag == ("set" if placeholder.placeholder else "cleared")
    assert question == (placeholder.question or "none")
    for name in placeholder.fields:
        for word in _default_words(name):
            assert re.search(rf"\b{re.escape(word)}\b", default), (placeholder.id, name, word)


def test_hard_floors_are_stated() -> None:
    rows = _placeholder_rows(_read(INDICATORS))
    assert f"hard floor {PASSPHRASE_LENGTH_FLOOR}" in rows["P05"][3]
    assert f"hard floor {DAILY_BACKUPS_FLOOR}" in rows["P06"][3]


def test_the_open_questions_of_the_placeholders_are_listed() -> None:
    listed = {
        match.group(1)
        for line in _read(INDICATORS).splitlines()
        if (match := QUESTION_ROW.match(line)) is not None
    }
    used = {item.question for item in PLACEHOLDERS if item.question is not None}
    assert listed == used


def test_alert_table_matches_the_code() -> None:
    documented = {
        match.group(1): match.group(2)
        for line in _read(INDICATORS).splitlines()
        if (match := ALERT_ROW.match(line)) is not None
    }
    expected = {kind.value: SEVERITY_OF[kind].value for kind in AlertKind}
    assert documented == expected


# --- architecture.md -----------------------------------------------------------------------------


def _top_level_packages() -> list[str]:
    return sorted(
        path.name
        for path in PACKAGE.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    )


def _top_level_modules() -> list[str]:
    return sorted(path.name for path in PACKAGE.glob("*.py"))


def _literal_assignment(path: Path, name: str) -> object:
    """The value of the module-level literal assignment ``name`` in the source file ``path``."""
    for node in ast.parse(_read(path)).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            value: object = ast.literal_eval(node.value)
            return value
    return pytest.fail(f"{name} not found in {path.name}")


def test_package_lists_are_found() -> None:
    assert {"domain", "storage", "services", "reports", "ui", "i18n"} <= set(_top_level_packages())
    assert {"app.py", "cli.py", "clock.py", "paths.py"} <= set(_top_level_modules())


def test_architecture_names_every_top_level_package() -> None:
    text = _read(ARCHITECTURE)
    for name in _top_level_packages():
        assert f"`{name}/`" in text, f"docs/architecture.md does not name the package {name}/"


def test_architecture_names_every_top_level_module() -> None:
    text = _read(ARCHITECTURE)
    for name in _top_level_modules():
        assert f"`{name}`" in text, f"docs/architecture.md does not name the module {name}"


def test_architecture_names_every_migration() -> None:
    text = _read(ARCHITECTURE)
    migrations = sorted(path.name for path in (PACKAGE / "storage" / "migrations").glob("*.sql"))
    assert migrations, "no migration found"
    for name in migrations:
        assert f"`{name}`" in text, f"docs/architecture.md does not name the migration {name}"


def test_architecture_names_every_page_with_its_order() -> None:
    text = _read(ARCHITECTURE)
    pages = re.findall(r'PageSpec\("([a-z_]+)",\s*(\d+)', _read(REGISTRY_SOURCE))
    assert len(pages) >= 7
    for key, order in pages:
        assert f"`{key}` ({order})" in text, f"docs/architecture.md does not name page {key}"


def test_architecture_names_every_settings_section_and_group() -> None:
    text = _read(ARCHITECTURE)
    sections = re.findall(r'SettingsSectionSpec\(\s*"([a-z_.]+)"', _read(REGISTRY_SOURCE))
    assert len(sections) >= 8
    for key in sections:
        assert f"`{key}`" in text, f"docs/architecture.md does not name section {key}"
    groups = _literal_assignment(REGISTRY_SOURCE, "SETTINGS_GROUPS")
    assert isinstance(groups, tuple)
    for group in groups:
        assert f"`{group}`" in text, f"docs/architecture.md does not name group {group}"


def test_architecture_names_every_startup_hook() -> None:
    text = _read(ARCHITECTURE)
    hooks = re.findall(r'StartupHook\(\s*"([a-z-]+)"', _read(PACKAGE / "app.py"))
    assert len(hooks) >= 5
    for name in hooks:
        assert f"`{name}`" in text, f"docs/architecture.md does not name the hook {name}"


def test_architecture_names_every_translation_area() -> None:
    text = _read(ARCHITECTURE)
    areas = _literal_assignment(PACKAGE / "i18n" / "__init__.py", "AREAS")
    assert isinstance(areas, dict)
    assert len(areas) >= 10
    for area in areas:
        assert f"`{area}`" in text, f"docs/architecture.md does not name the area {area}"


def test_architecture_names_the_layer_rules() -> None:
    text = _read(ARCHITECTURE)
    for rule in ("LAYER-DOMAIN", "LAYER-QT", "LAYER-SQL", "NET", "HANDOFF", "CLOCK"):
        assert f"`{rule}`" in text, f"docs/architecture.md does not describe the rule {rule}"


# --- the known limits are stated -----------------------------------------------------------------


@pytest.mark.parametrize("needle", ["UNC", "system clock", "unfinished"])
def test_architecture_states_the_known_limits(needle: str) -> None:
    assert needle in _read(ARCHITECTURE)
