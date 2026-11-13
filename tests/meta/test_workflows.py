# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks on the GitHub Actions workflows (T0.8), done on the workflow text.

No YAML library is available, so the workflows are read as text with a handful of small helpers.
The helpers are written to be reused: T0.9 adds a ``build`` job to ``ci.yml``, T9.3 adds
``release.yml`` and T9.5 adds Dependabot checks. Every check that applies to *all* workflows
runs over :func:`workflow_files`; checks on one file use ``ci.yml``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# ``owner/repo`` or ``owner/repo/path`` pinned to a full, lowercase, 40-character commit SHA.
PINNED_USES = re.compile(r"[\w.-]+/[\w.-]+(?:/[\w./-]+)?@[0-9a-f]{40}")

# A pinned Windows image label, for example ``windows-2025``.
PINNED_WINDOWS_LABEL = re.compile(r"windows-\d{4}(?:-[a-z0-9]+)*")

_COMMENT = re.compile(r"(?:^|\s)#.*$")
_USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(?P<value>\S.*?)\s*$")
_RUNS_ON = re.compile(r"^\s*runs-on:\s*(?P<value>.*?)\s*$")
_UV_SYNC = re.compile(r"\buv\s+sync\b")
_WRITE_GRANT = re.compile(r":\s*write")
_FAIL_UNDER_90 = re.compile(r"--(?:cov-)?fail-under=90\b")
_TOP_LEVEL_KEY = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):\s*(?P<inline>.*)$")

REQUIRED_COVERAGE_PACKAGES: tuple[str, ...] = (
    "cbrn_dashboard.domain",
    "cbrn_dashboard.storage",
    "cbrn_dashboard.services",
)


# --------------------------------------------------------------------------------------------
# Helpers (reusable by later tasks)
# --------------------------------------------------------------------------------------------


def workflow_files(directory: Path = WORKFLOWS_DIR) -> list[Path]:
    """Return every ``*.yml`` and ``*.yaml`` file in ``directory``, sorted.

    GitHub runs both extensions, so both must go through the checks.
    """
    return sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])


def read_workflow(name: str) -> str:
    """Return the text of the workflow ``name`` (for example ``"ci.yml"``)."""
    return (WORKFLOWS_DIR / name).read_text(encoding="utf-8")


def strip_comment(line: str) -> str:
    """Remove a YAML comment (a ``#`` at the start or after whitespace) and trailing blanks."""
    return _COMMENT.sub("", line).rstrip()


def code_lines(text: str) -> list[str]:
    """Return the non-empty lines of ``text`` without comments, indentation kept."""
    lines = (strip_comment(line) for line in text.splitlines())
    return [line for line in lines if line.strip()]


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def uses_refs(text: str) -> list[str]:
    """Return every ``uses:`` value, ignoring comments and local ``./`` actions."""
    refs: list[str] = []
    for line in code_lines(text):
        match = _USES.match(line)
        if match is None:
            continue
        value = _unquote(match.group("value"))
        if value.startswith("./"):
            continue
        refs.append(value)
    return refs


def is_sha_pinned(ref: str) -> bool:
    """Tell whether ``ref`` is ``owner/repo[/path]@<40 lowercase hex>``."""
    return PINNED_USES.fullmatch(ref) is not None


def runs_on_values(text: str) -> list[str]:
    """Return every ``runs-on:`` value as written (without quotes)."""
    values: list[str] = []
    for line in code_lines(text):
        match = _RUNS_ON.match(line)
        if match is not None:
            values.append(_unquote(match.group("value")))
    return values


def runs_on_problem(value: str) -> str | None:
    """Return why ``value`` is not an acceptable ``runs-on`` value, or ``None`` if it is fine.

    Only the simple scalar form is accepted. A matrix, an expression, a list or a mapping is
    refused on purpose, so that nobody sneaks an unpinned runner in behind one.
    """
    if not value:
        return "empty or block-form runs-on is not supported; use a plain scalar label"
    if "${{" in value or value[0] in "[{":
        return f"matrix/expression/list form {value!r} is not supported; use a plain scalar label"
    if value.endswith("-latest"):
        return f"{value!r} is a floating '-latest' label; pin the image (for example windows-2025)"
    if PINNED_WINDOWS_LABEL.fullmatch(value) is None:
        return f"{value!r} is not a pinned Windows image label (windows-NNNN...)"
    return None


def uv_sync_lines(text: str) -> list[str]:
    """Return the (comment-free, stripped) lines that run ``uv sync``."""
    return [line.strip() for line in code_lines(text) if _UV_SYNC.search(line)]


def uv_sync_without_locked(text: str) -> list[str]:
    """Return the ``uv sync`` lines that lack ``--locked``."""
    return [line for line in uv_sync_lines(text) if "--locked" not in line]


def top_level_entry(text: str, key: str) -> tuple[str, list[str]] | None:
    """Find the top-level (column 0) ``key:`` entry.

    Return ``(inline_value, body_lines)``: the text after the colon on the key line, and the
    comment-free, non-empty indented lines that follow it (indentation kept). Return ``None``
    when the key is absent.
    """
    lines = code_lines(text)
    for index, line in enumerate(lines):
        match = _TOP_LEVEL_KEY.match(line)
        if match is None or match.group("key") != key:
            continue
        body: list[str] = []
        for following in lines[index + 1 :]:
            if not following[0].isspace():
                break
            body.append(following)
        return match.group("inline").strip(), body
    return None


def trigger_names(text: str) -> set[str]:
    """Return the event names under the top-level ``on:`` key (block, list or scalar form)."""
    entry = top_level_entry(text, "on")
    if entry is None:
        return set()
    inline, body = entry
    if inline:
        items = inline.strip("[]").split(",")
        return {_unquote(item) for item in items if item.strip()}
    if not body:
        return set()
    indent = min(len(line) - len(line.lstrip()) for line in body)
    names: set[str] = set()
    for line in body:
        if len(line) - len(line.lstrip()) != indent:
            continue
        match = re.match(r"\s*(?:-\s+)?(?P<name>[A-Za-z_][\w-]*)\s*:?", line)
        if match is not None:
            names.add(match.group("name"))
    return names


def grants_write(text: str) -> list[str]:
    """Return the lines that grant a ``write`` permission (``contents: write``, ``write-all``)."""
    return [line.strip() for line in code_lines(text) if _WRITE_GRANT.search(line)]


def has_read_only_top_level_permissions(text: str) -> bool:
    """Tell whether a top-level ``permissions:`` block grants ``contents: read`` and no write."""
    entry = top_level_entry(text, "permissions")
    if entry is None:
        return False
    inline, body = entry
    if inline:
        return False
    stripped = [line.strip() for line in body]
    return "contents: read" in stripped and not any(_WRITE_GRANT.search(s) for s in stripped)


def has_cancelling_concurrency(text: str) -> bool:
    """Tell whether a top-level ``concurrency:`` block sets ``cancel-in-progress: true``."""
    entry = top_level_entry(text, "concurrency")
    if entry is None:
        return False
    _, body = entry
    return any(line.strip() == "cancel-in-progress: true" for line in body)


def sets_env(text: str, name: str, value: str) -> bool:
    """Tell whether some line sets the environment variable ``name`` to ``value``."""
    pattern = re.compile(rf"^\s*{re.escape(name)}:\s*[\"']?{re.escape(value)}[\"']?\s*$")
    return any(pattern.match(line) for line in code_lines(text))


def job_lines(text: str, job: str) -> list[str]:
    """Return the comment-free body lines of the job ``job`` (empty when there is no such job)."""
    entry = top_level_entry(text, "jobs")
    if entry is None:
        return []
    _, body = entry
    if not body:
        return []
    base = min(len(line) - len(line.lstrip()) for line in body)
    lines: list[str] = []
    inside = False
    for line in body:
        if len(line) - len(line.lstrip()) == base:
            inside = line.strip() == f"{job}:"
            continue
        if inside:
            lines.append(line)
    return lines


def job_needs(text: str, job: str) -> set[str]:
    """Return the jobs named by ``needs:`` of ``job`` (scalar or inline-list form)."""
    for line in job_lines(text, job):
        match = re.match(r"\s*needs:\s*(?P<value>.+)$", line)
        if match is not None:
            items = match.group("value").strip().strip("[]").split(",")
            return {_unquote(item) for item in items if item.strip()}
    return set()


def has_coverage_gate(text: str) -> bool:
    """Tell whether a 90% coverage gate exists and the three gated packages are measured."""
    lines = code_lines(text)
    gate = any(_FAIL_UNDER_90.search(line) for line in lines)
    text_without_comments = "\n".join(lines)
    measured = all(package in text_without_comments for package in REQUIRED_COVERAGE_PACKAGES)
    return gate and measured


# --------------------------------------------------------------------------------------------
# Checks on the real workflows
# --------------------------------------------------------------------------------------------


def test_ci_workflow_exists() -> None:
    assert (WORKFLOWS_DIR / "ci.yml").is_file()
    assert WORKFLOWS_DIR / "ci.yml" in workflow_files()


@pytest.mark.parametrize("path", workflow_files(), ids=lambda path: path.name)
def test_every_action_is_pinned_to_a_full_sha(path: Path) -> None:
    refs = uses_refs(path.read_text(encoding="utf-8"))
    unpinned = [ref for ref in refs if not is_sha_pinned(ref)]
    assert not unpinned, f"{path.name}: actions not pinned to a 40-hex commit SHA: {unpinned}"


@pytest.mark.parametrize("path", workflow_files(), ids=lambda path: path.name)
def test_every_runner_is_a_pinned_windows_image(path: Path) -> None:
    values = runs_on_values(path.read_text(encoding="utf-8"))
    assert values, f"{path.name}: no runs-on found"
    problems = {value: runs_on_problem(value) for value in values}
    bad = {value: problem for value, problem in problems.items() if problem is not None}
    assert not bad, f"{path.name}: {bad}"


@pytest.mark.parametrize("path", workflow_files(), ids=lambda path: path.name)
def test_no_workflow_runs_uv_sync_without_locked(path: Path) -> None:
    offenders = uv_sync_without_locked(path.read_text(encoding="utf-8"))
    assert not offenders, f"{path.name}: 'uv sync' without --locked: {offenders}"


def test_ci_sets_qt_offscreen() -> None:
    assert sets_env(read_workflow("ci.yml"), "QT_QPA_PLATFORM", "offscreen")


def test_ci_syncs_locked_with_all_groups() -> None:
    lines = uv_sync_lines(read_workflow("ci.yml"))
    assert lines, "ci.yml does not run 'uv sync'"
    assert any("--locked" in line and "--all-groups" in line for line in lines), lines


def test_ci_permissions_are_read_only() -> None:
    text = read_workflow("ci.yml")
    assert has_read_only_top_level_permissions(text), "no top-level 'permissions: contents: read'"
    assert grants_write(text) == []


def test_ci_triggers_on_push_and_pull_request() -> None:
    assert {"push", "pull_request"} <= trigger_names(read_workflow("ci.yml"))


def test_ci_push_trigger_is_limited_to_the_main_branch() -> None:
    """P9-15: an unfiltered push ran CI for tags and again for every pull-request branch."""
    lines = on_block_lines(read_workflow("ci.yml"))
    assert "push:" in lines
    assert "branches: [main]" in lines
    assert not [line for line in lines if line.startswith(("tags", "tags-ignore"))]


def test_ci_cancels_superseded_runs() -> None:
    assert has_cancelling_concurrency(read_workflow("ci.yml"))


def test_ci_gates_coverage_at_90_percent() -> None:
    assert has_coverage_gate(read_workflow("ci.yml"))


def test_ci_has_a_build_job_after_the_tests() -> None:
    text = read_workflow("ci.yml")
    assert job_lines(text, "build"), "ci.yml has no 'build' job"
    assert "test" in job_needs(text, "build")


def test_ci_build_job_runs_the_packaging_tests() -> None:
    lines = [line.strip() for line in job_lines(read_workflow("ci.yml"), "build")]
    assert any(line.endswith("uv run pytest -m packaging") for line in lines), lines


def _env_value(lines: list[str], name: str) -> str | None:
    """Return the value of the ``NAME: value`` line among ``lines`` (quotes removed), if any."""
    for line in lines:
        match = re.match(rf"\s*{re.escape(name)}:\s*(?P<value>\S.*?)\s*$", line)
        if match is not None:
            return _unquote(match.group("value"))
    return None


def test_ci_build_job_builds_once_inside_the_packaging_tests() -> None:
    lines = job_lines(read_workflow("ci.yml"), "build")
    dist = _env_value(lines, "CBRN_BUNDLE_DIST_DIR")
    work = _env_value(lines, "CBRN_BUNDLE_WORK_DIR")
    assert dist, "the build job does not set CBRN_BUNDLE_DIST_DIR"
    assert work, "the build job does not set CBRN_BUNDLE_WORK_DIR"
    run_index = index_of_run(lines, "uv run pytest -m packaging")
    env_index = index_containing(lines, "CBRN_BUNDLE_DIST_DIR")
    assert 0 <= run_index < env_index, "the variables must belong to the packaging test step"
    assert index_containing(lines, "CBRN_BUNDLE_WORK_DIR") > run_index


def test_ci_never_runs_the_build_script_directly() -> None:
    lines = code_lines(read_workflow("ci.yml"))
    offenders = [line.strip() for line in lines if "build_exe" in line]
    assert offenders == [], f"ci.yml must not build a second time: {offenders}"


def test_ci_zip_step_archives_the_tested_bundle_folder() -> None:
    lines = [line.strip() for line in job_lines(read_workflow("ci.yml"), "build")]
    dist = _env_value(lines, "CBRN_BUNDLE_DIST_DIR")
    assert dist
    zips = [line for line in lines if "Compress-Archive" in line]
    assert len(zips) == 1, zips
    assert f"-Path {dist}/cbrn-dashboard " in zips[0], zips[0]
    run_index = index_of_run(lines, "uv run pytest -m packaging")
    assert 0 <= run_index < index_containing(lines, "Compress-Archive")


def test_ci_build_job_uploads_the_artefact_for_14_days() -> None:
    lines = [line.strip() for line in job_lines(read_workflow("ci.yml"), "build")]
    assert any("uses: actions/upload-artifact@" in line for line in lines), lines
    assert "retention-days: 14" in lines
    assert "name: cbrn-dashboard-win-x64" in lines


def test_ci_build_job_has_its_own_pinned_runner_and_setup() -> None:
    raw = job_lines(read_workflow("ci.yml"), "build")
    lines = [line.strip() for line in raw]
    assert "runs-on: windows-2025" in lines
    assert "timeout-minutes: 45" in lines
    assert any("uv sync" in line and "--locked" in line for line in lines), lines
    assert sets_env("\n".join(raw), "QT_QPA_PLATFORM", "offscreen")


# --------------------------------------------------------------------------------------------
# Self-tests: each check must bite on a small fictitious workflow
# --------------------------------------------------------------------------------------------

GOOD_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def test_workflow_files_finds_yml_and_yaml(tmp_path: Path) -> None:
    for name in ("b.yaml", "a.yml", "notes.txt", "c.yml.bak"):
        (tmp_path / name).write_text("name: x\n", encoding="utf-8")
    assert workflow_files(tmp_path) == [tmp_path / "a.yml", tmp_path / "b.yaml"]
    assert workflow_files(tmp_path / "missing") == []


def test_uses_refs_ignores_comments_and_local_actions() -> None:
    text = (
        "steps:\n"
        f"  - uses: actions/checkout@{GOOD_SHA} # v7.0.1\n"
        "  # - uses: actions/cache@v4\n"
        "  - uses: ./.github/actions/local\n"
        f"  - uses: 'astral-sh/setup-uv@{GOOD_SHA}'\n"
        "    with:\n"
        "      name: uses is only a word here\n"
    )
    assert uses_refs(text) == [
        f"actions/checkout@{GOOD_SHA}",
        f"astral-sh/setup-uv@{GOOD_SHA}",
    ]


@pytest.mark.parametrize(
    "ref",
    [
        "actions/checkout@v4",
        "actions/checkout@3d3c42e",
        f"actions/checkout@{GOOD_SHA.upper()}",
        f"actions/checkout@{GOOD_SHA}0",
        f"actions/checkout@{GOOD_SHA[:-1]}",
        "actions/checkout",
        f"checkout@{GOOD_SHA}",
    ],
)
def test_sha_pinning_check_rejects_unpinned_refs(ref: str) -> None:
    assert not is_sha_pinned(ref)
    assert not is_sha_pinned(uses_refs(f"- uses: {ref}")[0])


@pytest.mark.parametrize("ref", [f"actions/checkout@{GOOD_SHA}", f"o/r/sub/path@{GOOD_SHA}"])
def test_sha_pinning_check_accepts_pinned_refs(ref: str) -> None:
    assert is_sha_pinned(ref)


@pytest.mark.parametrize(
    "line",
    [
        "runs-on: windows-latest",
        "runs-on: ubuntu-24.04",
        "runs-on: windows-2025-latest",
        "runs-on: ${{ matrix.os }}",
        "runs-on: [windows-2025]",
        "runs-on:",
    ],
)
def test_runner_check_rejects_bad_labels(line: str) -> None:
    (value,) = runs_on_values(f"jobs:\n  t:\n    {line}\n")
    assert runs_on_problem(value) is not None


@pytest.mark.parametrize("label", ["windows-2025", "windows-2022", "windows-2025-vs2026"])
def test_runner_check_accepts_pinned_windows_labels(label: str) -> None:
    (value,) = runs_on_values(f'jobs:\n  t:\n    runs-on: "{label}"  # pinned\n')
    assert runs_on_problem(value) is None


def test_uv_sync_check_requires_locked() -> None:
    bad = "steps:\n  - run: uv sync --all-groups\n  - run: uv sync --locked\n"
    assert uv_sync_without_locked(bad) == ["- run: uv sync --all-groups"]
    assert uv_sync_without_locked("steps:\n  - run: uv sync --locked --all-groups\n") == []
    assert uv_sync_without_locked("# uv sync\nsteps:\n  - run: uv run pytest\n") == []


def test_permissions_check_requires_read_only_top_level_block() -> None:
    read_only = "on: push\npermissions:\n  contents: read\njobs:\n  t:\n    runs-on: x\n"
    assert has_read_only_top_level_permissions(read_only)
    assert grants_write(read_only) == []
    assert not has_read_only_top_level_permissions("on: push\njobs:\n  t:\n    runs-on: x\n")
    assert not has_read_only_top_level_permissions("permissions: read-all\n")
    assert not has_read_only_top_level_permissions("permissions:\n  contents: write\n")
    job_level_only = "jobs:\n  t:\n    permissions:\n      contents: read\n"
    assert not has_read_only_top_level_permissions(job_level_only)
    sneaky = read_only + "    permissions:\n      id-token: write\n"
    assert grants_write(sneaky) == ["id-token: write"]


def test_trigger_check_reads_block_list_and_scalar_forms() -> None:
    assert trigger_names("on:\n  push:\n    branches: [main]\n  pull_request:\n") == {
        "push",
        "pull_request",
    }
    assert trigger_names("on: [push, pull_request]\n") == {"push", "pull_request"}
    assert trigger_names("on: push\n") == {"push"}
    assert trigger_names("on:\n  - push\n  - pull_request\n") == {"push", "pull_request"}
    assert trigger_names("name: CI\n") == set()
    assert "pull_request" not in trigger_names("on:\n  push:\n")


def test_concurrency_check_requires_cancel_in_progress() -> None:
    good = "concurrency:\n  group: g\n  cancel-in-progress: true\njobs:\n"
    assert has_cancelling_concurrency(good)
    assert not has_cancelling_concurrency("concurrency:\n  group: g\n")
    assert not has_cancelling_concurrency("concurrency:\n  cancel-in-progress: false\n")
    assert not has_cancelling_concurrency("jobs:\n  t:\n    cancel-in-progress: true\n")


def test_env_check_requires_offscreen() -> None:
    assert sets_env("env:\n  QT_QPA_PLATFORM: offscreen\n", "QT_QPA_PLATFORM", "offscreen")
    assert sets_env("env:\n  QT_QPA_PLATFORM: 'offscreen'\n", "QT_QPA_PLATFORM", "offscreen")
    assert not sets_env("env:\n  QT_QPA_PLATFORM: windows\n", "QT_QPA_PLATFORM", "offscreen")
    assert not sets_env("# QT_QPA_PLATFORM: offscreen\n", "QT_QPA_PLATFORM", "offscreen")


def test_job_helpers_split_jobs_and_read_needs() -> None:
    text = (
        "jobs:\n"
        "  a:\n"
        "    runs-on: windows-2025\n"
        "  b:\n"
        "    needs: [a, c]\n"
        "    steps:\n"
        "      - run: x\n"
        "  c:\n"
        "    needs: a\n"
    )
    assert job_lines(text, "a") == ["    runs-on: windows-2025"]
    assert job_needs(text, "b") == {"a", "c"}
    assert job_needs(text, "c") == {"a"}
    assert job_needs(text, "a") == set()
    assert job_lines(text, "missing") == []
    assert job_lines("name: x\n", "a") == []


def test_coverage_gate_check_needs_threshold_and_all_packages() -> None:
    cov = " ".join(f"--cov={package}" for package in REQUIRED_COVERAGE_PACKAGES)
    good = f"- run: uv run pytest {cov}\n- run: uv run coverage report --fail-under=90\n"
    assert has_coverage_gate(good)
    assert has_coverage_gate(f"- run: uv run pytest {cov} --cov-fail-under=90\n")
    assert not has_coverage_gate(good.replace("=90", "=80"))
    assert not has_coverage_gate(good.replace("cbrn_dashboard.storage", "cbrn_dashboard.other"))
    assert not has_coverage_gate(f"- run: uv run pytest {cov}\n# --fail-under=90\n")


# --------------------------------------------------------------------------------------------
# Release workflow (T9.3): helpers
# --------------------------------------------------------------------------------------------

RELEASE_ELEVATED_PERMISSIONS: tuple[str, ...] = (
    "contents: write",
    "id-token: write",
    "attestations: write",
)
_ATTEST_ACTION = re.compile(r"actions/attest-build-provenance@[0-9a-f]{40}")
_REF_NAME = re.compile(r"\$\{\{\s*github\.ref_name\s*\}\}")
_ENV_ENTRY_WITH_REF_NAME = re.compile(
    r"^\s*[A-Za-z_][A-Za-z0-9_]*:\s*\$\{\{\s*github\.ref_name\s*\}\}\s*$"
)


def on_block_lines(text: str) -> list[str]:
    """Return the stripped, comment-free lines under the top-level ``on:`` key."""
    entry = top_level_entry(text, "on")
    if entry is None:
        return []
    return [line.strip() for line in entry[1]]


def tag_patterns(text: str) -> list[str]:
    """Return the patterns of an inline ``tags: [...]`` filter under ``on:`` (empty if none)."""
    for line in on_block_lines(text):
        match = re.match(r"tags:\s*\[(?P<items>.*)\]$", line)
        if match is not None:
            items = match.group("items").split(",")
            return [_unquote(item) for item in items if item.strip()]
    return []


def job_names(text: str) -> list[str]:
    """Return the names of the jobs under the top-level ``jobs:`` key, in file order."""
    entry = top_level_entry(text, "jobs")
    if entry is None or not entry[1]:
        return []
    body = entry[1]
    base = min(len(line) - len(line.lstrip()) for line in body)
    return [
        line.strip().removesuffix(":")
        for line in body
        if len(line) - len(line.lstrip()) == base and line.strip().endswith(":")
    ]


def index_of_run(lines: list[str], command: str) -> int:
    """Return the index of the line that is exactly ``run: <command>``, or -1."""
    pattern = re.compile(rf"(?:-\s+)?run:\s*{re.escape(command)}")
    for index, line in enumerate(lines):
        if pattern.fullmatch(line.strip()):
            return index
    return -1


def index_containing(lines: list[str], fragment: str) -> int:
    """Return the index of the first line containing ``fragment``, or -1."""
    for index, line in enumerate(lines):
        if fragment in line:
            return index
    return -1


def ref_name_outside_env(text: str) -> list[str]:
    """Return the lines that use ``github.ref_name`` other than as ``NAME: ${{ ... }}``.

    Putting the ref name straight into a script is an expression-injection hole: a tag can
    contain shell metacharacters. It must go through an ``env:`` entry and be read from there.
    """
    return [
        line.strip()
        for line in code_lines(text)
        if _REF_NAME.search(line) and _ENV_ENTRY_WITH_REF_NAME.match(line) is None
    ]


# --------------------------------------------------------------------------------------------
# Release workflow (T9.3): checks on release.yml
# --------------------------------------------------------------------------------------------


def _release_text() -> str:
    return read_workflow("release.yml")


def _release_job() -> list[str]:
    return job_lines(_release_text(), "release")


def _build_job() -> list[str]:
    return job_lines(_release_text(), "build")


def _stripped(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines]


def test_release_workflow_exists_and_is_named_release() -> None:
    assert WORKFLOWS_DIR / "release.yml" in workflow_files()
    assert "name: Release" in code_lines(_release_text())


def test_release_triggers_only_on_version_tags() -> None:
    text = _release_text()
    assert trigger_names(text) == {"push"}
    assert tag_patterns(text) == ["v*.*.*"]
    forbidden = ("branches", "paths", "pull_request")
    assert not [line for line in on_block_lines(text) if line.startswith(forbidden)]


def test_release_has_read_only_top_level_permissions() -> None:
    assert has_read_only_top_level_permissions(_release_text())


def test_release_has_a_build_job_and_a_release_job_that_needs_it() -> None:
    text = _release_text()
    assert job_names(text) == ["build", "release"]
    assert job_needs(text, "release") == {"build"}
    assert job_needs(text, "build") == set()


def test_release_elevated_permissions_are_only_inside_the_release_job() -> None:
    """P9-01: dependency install, tests and PyInstaller run without any write permission."""
    text = _release_text()
    assert grants_write("\n".join(_build_job())) == []
    assert not [line for line in _build_job() if line.strip() == "permissions:"]
    in_job = grants_write("\n".join(_release_job()))
    assert sorted(in_job) == sorted(RELEASE_ELEVATED_PERMISSIONS)
    assert sorted(grants_write(text)) == sorted(RELEASE_ELEVATED_PERMISSIONS)


def test_release_job_asks_for_no_more_than_it_uses() -> None:
    permissions = _sub_block(_release_job(), "permissions", 4)
    granted = sorted(line.strip() for line in permissions)
    assert granted == sorted(RELEASE_ELEVATED_PERMISSIONS)


def test_release_job_installs_nothing_and_runs_no_project_code() -> None:
    joined = "\n".join(_release_job())
    assert uv_sync_lines("\n".join(_release_job())) == []
    for forbidden in ("uv run", "uv sync", "actions/checkout", "setup-uv", "pytest", "build_exe"):
        assert forbidden not in joined, forbidden


def test_release_jobs_run_on_the_pinned_runner_with_a_timeout() -> None:
    build = _stripped(_build_job())
    assert "runs-on: windows-2025" in build
    assert "timeout-minutes: 60" in build
    assert sets_env("\n".join(_build_job()), "QT_QPA_PLATFORM", "offscreen")
    release = _stripped(_release_job())
    assert "runs-on: windows-2025" in release
    assert any(line.startswith("timeout-minutes: ") for line in release)


def test_release_does_not_cancel_a_running_release() -> None:
    entry = top_level_entry(_release_text(), "concurrency")
    assert entry is not None
    assert "cancel-in-progress: false" in [line.strip() for line in entry[1]]
    assert not has_cancelling_concurrency(_release_text())


def test_release_checkout_keeps_no_credentials_and_uv_cache_is_off() -> None:
    lines = _stripped(_build_job())
    assert "persist-credentials: false" in lines
    assert "enable-cache: false" in lines
    assert 'version: "0.11.7"' in lines


def test_release_syncs_locked_with_all_groups() -> None:
    lines = uv_sync_lines(_release_text())
    assert lines, "release.yml does not run 'uv sync'"
    assert all("--locked" in line and "--all-groups" in line for line in lines), lines


def test_release_never_runs_the_build_script_directly() -> None:
    """P9-01: like ci.yml, the release ships the bundle the packaging tests built, not a second."""
    offenders = [line.strip() for line in code_lines(_release_text()) if "build_exe" in line]
    assert offenders == [], f"release.yml must not build a second time: {offenders}"


def test_release_checks_the_tag_before_testing() -> None:
    lines = _build_job()
    check = index_containing(lines, "make_release_zip.py check-tag")
    packaging_suite = index_of_run(lines, "uv run pytest -m packaging")
    assert check != -1, "no check-tag step"
    assert packaging_suite != -1
    assert check < packaging_suite
    assert index_containing(lines, "--tag") != -1


def test_release_runs_both_test_suites_before_packaging() -> None:
    lines = _build_job()
    default_suite = index_of_run(lines, "uv run pytest")
    packaging_suite = index_of_run(lines, "uv run pytest -m packaging")
    package = index_containing(lines, "make_release_zip.py package")
    assert -1 not in (default_suite, packaging_suite, package)
    assert default_suite < packaging_suite < package


def test_release_packaging_tests_build_into_the_folders_that_are_zipped() -> None:
    """P9-01: the two CBRN_BUNDLE_* variables belong to the packaging step, and the zip is made
    from the folder they name."""
    lines = _build_job()
    dist = _env_value(lines, "CBRN_BUNDLE_DIST_DIR")
    work = _env_value(lines, "CBRN_BUNDLE_WORK_DIR")
    assert dist, "the build job does not set CBRN_BUNDLE_DIST_DIR"
    assert work, "the build job does not set CBRN_BUNDLE_WORK_DIR"
    run_index = index_of_run(lines, "uv run pytest -m packaging")
    assert 0 <= run_index < index_containing(lines, "CBRN_BUNDLE_DIST_DIR")
    assert run_index < index_containing(lines, "CBRN_BUNDLE_WORK_DIR")
    package = next(line for line in lines if "make_release_zip.py package" in line)
    assert f"--bundle-dir {dist}/cbrn-dashboard " in package + " ", package


def test_release_uploads_the_zip_and_the_release_job_attests_that_zip() -> None:
    build = _stripped(_build_job())
    package = next(line for line in build if "make_release_zip.py package" in line)
    assert "--out-dir release" in package
    upload = next(i for i, line in enumerate(build) if "uses: actions/upload-artifact@" in line)
    upload_step = build[upload:]
    assert "name: cbrn-dashboard-release" in upload_step
    assert "path: release" in upload_step
    assert "if-no-files-found: error" in upload_step
    assert index_containing(build, "make_release_zip.py package") < upload

    release = _release_job()
    attest = next((i for i, line in enumerate(release) if _ATTEST_ACTION.search(line)), -1)
    assert attest != -1, "no actions/attest-build-provenance@<sha> step"
    assert "subject-path: release/*.zip" in _stripped(release)
    # The artefact moves between the jobs with the pinned download action (the documented way to
    # share data between jobs of one run), not with a CLI call that needs another permission.
    download = index_containing(release, "uses: actions/download-artifact@")
    assert 0 <= download < attest
    download_step = _stripped(release[download:attest])
    assert "name: cbrn-dashboard-release" in download_step
    assert "path: release" in download_step
    assert index_containing(release, "gh run download") == -1
    assert index_containing(release, "gh release create") > attest


def test_release_notes_are_written_in_the_build_job_before_the_upload() -> None:
    build = _build_job()
    body = index_containing(build, "make_release_zip.py release-body")
    flag = index_containing(build, "make_release_zip.py prerelease-flag")
    upload = index_containing(build, "uses: actions/upload-artifact@")
    package = index_containing(build, "make_release_zip.py package")
    assert -1 not in (body, flag, upload, package)
    assert package < body < upload
    assert package < flag < upload
    assert "release-body.template.md" in "\n".join(build)


def test_release_creates_a_draft_with_prerelease_handling_and_the_three_files() -> None:
    joined = "\n".join(_release_job())
    assert "gh release create" in joined
    assert "--draft" in joined
    assert "--notes-file" in joined
    assert "release/prerelease.txt" in joined
    assert "$pre" in joined
    assert "release/SHA256SUMS.txt" in joined
    assert "release/SHA256-FILES.txt" in joined
    assert "release/body.md" in joined
    assert "release/prerelease.txt" in "\n".join(_build_job())


def test_release_never_publishes() -> None:
    joined = "\n".join(code_lines(_release_text()))
    assert "--draft=false" not in joined
    assert "gh release edit" not in joined
    assert "gh release upload" not in joined


def test_release_sets_the_github_token_for_gh() -> None:
    lines = _stripped(_release_job())
    assert lines.count("GH_TOKEN: ${{ github.token }}") == 1  # only "gh release create" uses gh
    assert "GH_REPO: ${{ github.repository }}" in lines


def test_release_uses_pwsh_for_powershell_steps() -> None:
    lines = _stripped(code_lines(_release_text()))
    assert lines.count("shell: pwsh") >= 3
    assert "$env:TAG" in "\n".join(lines)


def test_release_never_puts_the_ref_name_into_a_script() -> None:
    text = _release_text()
    assert _REF_NAME.search(text), "release.yml should pass the tag through env"
    assert ref_name_outside_env(text) == []
    env_lines = [line.strip() for line in code_lines(text) if _REF_NAME.search(line)]
    assert env_lines
    assert all(line == "TAG: ${{ github.ref_name }}" for line in env_lines)


# --------------------------------------------------------------------------------------------
# Release workflow (T9.3): helper self-tests
# --------------------------------------------------------------------------------------------


def test_tag_patterns_and_on_block_lines_read_the_filter() -> None:
    text = "on:\n  push:\n    tags: [\"v*.*.*\", 'rel-*']\n\npermissions:\n  contents: read\n"
    assert on_block_lines(text) == ["push:", "tags: [\"v*.*.*\", 'rel-*']"]
    assert tag_patterns(text) == ["v*.*.*", "rel-*"]
    assert tag_patterns("on:\n  push:\n    branches: [main]\n") == []
    assert tag_patterns("on: push\n") == []
    assert on_block_lines("name: x\n") == []


def test_job_names_lists_top_level_jobs_only() -> None:
    text = "jobs:\n  a:\n    steps:\n      - run: x\n  b:\n    needs: a\n"
    assert job_names(text) == ["a", "b"]
    assert job_names("name: x\n") == []
    assert job_names("jobs:\n") == []


def test_index_helpers_find_exact_and_partial_lines() -> None:
    lines = [
        "- run: uv run pytest -m packaging",
        "      - run: uv run pytest",
        "run: uv run pytest",
        "- run: uv run python scripts/build_exe.py --dist-dir dist",
    ]
    assert index_of_run(lines, "uv run pytest") == 1
    assert index_of_run(lines, "uv run pytest -m packaging") == 0
    assert index_of_run(lines, "uv run coverage") == -1
    assert index_of_run(["- run: uv run pytest --cov"], "uv run pytest") == -1
    assert index_containing(lines, "scripts/build_exe.py") == 3
    assert index_containing(lines, "nothing") == -1


def test_ref_name_check_allows_env_entries_and_flags_scripts() -> None:
    env_only = 'env:\n  TAG: ${{ github.ref_name }}\nrun: echo "$env:TAG"\n'
    assert ref_name_outside_env(env_only) == []
    inline = 'steps:\n  - run: echo "${{ github.ref_name }}"\n'
    assert ref_name_outside_env(inline) == ['- run: echo "${{ github.ref_name }}"']
    block = "run: |\n  gh release create ${{github.ref_name}} --draft\n"
    assert ref_name_outside_env(block) == ["gh release create ${{github.ref_name}} --draft"]
    mixed = "env:\n  TAG: ${{ github.ref_name }} extra\n"
    assert ref_name_outside_env(mixed) == ["TAG: ${{ github.ref_name }} extra"]
    assert ref_name_outside_env("concurrency:\n  group: g-${{ github.ref }}\n") == []
    assert ref_name_outside_env("# ${{ github.ref_name }} in a comment\n") == []


# --------------------------------------------------------------------------------------------
# Dependabot (T9.5): helpers
# --------------------------------------------------------------------------------------------

DEPENDABOT_FILE = ROOT / ".github" / "dependabot.yml"
REQUIRED_ECOSYSTEMS: tuple[str, ...] = ("github-actions", "uv")
PYSIDE_FAMILY: tuple[str, ...] = (
    "pyside6",
    "pyside6-essentials",
    "pyside6-addons",
    "pyside6-pdf",
    "pyside6-webengine",
    "shiboken6",
)

_ECOSYSTEM_LINE = re.compile(r"^\s*-\s+package-ecosystem:\s*(?P<value>\S.*?)\s*$")
_INTERVAL_LINE = re.compile(r"^\s*interval:\s*(?P<value>\S.*?)\s*$")
_UPDATE_TYPES_LINE = re.compile(r"^\s*update-types:\s*\[(?P<items>.*)\]\s*$")
_IGNORE_NAME_LINE = re.compile(r"^-\s+dependency-name:\s*(?P<value>\S.*?)\s*$")
_IGNORE_VERSIONS_LINE = re.compile(r"^versions:\s*\[(?P<items>.*)\]\s*$")


def read_dependabot() -> str:
    """Return the text of ``.github/dependabot.yml``."""
    return DEPENDABOT_FILE.read_text(encoding="utf-8")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _sub_block(lines: list[str], key: str, key_indent: int) -> list[str]:
    """Return the lines nested under the ``key:`` line that sits at ``key_indent``."""
    for index, line in enumerate(lines):
        if _indent(line) != key_indent or line.strip() != f"{key}:":
            continue
        block: list[str] = []
        for following in lines[index + 1 :]:
            if _indent(following) <= key_indent:
                break
            block.append(following)
        return block
    return []


def _split_items(items: str) -> list[str]:
    return [_unquote(item) for item in items.split(",") if item.strip()]


def dependabot_updates(text: str) -> list[dict[str, str]]:
    """Split the ``updates:`` list of a Dependabot file into one dict per ecosystem entry.

    Keys (a key is absent when the entry does not have the setting):

    - ``package-ecosystem``: the ecosystem name, without quotes;
    - ``interval``: the ``schedule: interval`` value;
    - ``update-types``: one group per ``;``, each group a sorted, comma-separated list of the
      inline ``update-types: [...]`` of a ``groups`` entry;
    - ``ignore``: the comment-free lines of the ``ignore`` block, stripped, joined by newlines.
    """
    entry = top_level_entry(text, "updates")
    if entry is None:
        return []
    chunks: list[list[str]] = []
    for line in entry[1]:
        if _ECOSYSTEM_LINE.match(line):
            chunks.append([line])
        elif chunks:
            chunks[-1].append(line)
    updates: list[dict[str, str]] = []
    for chunk in chunks:
        match = _ECOSYSTEM_LINE.match(chunk[0])
        assert match is not None
        key_indent = _indent(chunk[0]) + 2
        update = {"package-ecosystem": _unquote(match.group("value"))}
        for line in _sub_block(chunk, "schedule", key_indent):
            interval = _INTERVAL_LINE.match(line)
            if interval is not None:
                update["interval"] = _unquote(interval.group("value"))
        groups: list[str] = []
        for line in _sub_block(chunk, "groups", key_indent):
            types = _UPDATE_TYPES_LINE.match(line)
            if types is not None:
                groups.append(",".join(sorted(_split_items(types.group("items")))))
        if groups:
            update["update-types"] = ";".join(groups)
        ignore = _sub_block(chunk, "ignore", key_indent)
        if ignore:
            update["ignore"] = "\n".join(line.strip() for line in ignore)
        updates.append(update)
    return updates


def has_grouped_update_types(update: dict[str, str], required: tuple[str, ...]) -> bool:
    """Tell whether one ``groups`` entry of ``update`` covers all of the ``required`` types."""
    groups = update.get("update-types", "").split(";")
    return any(set(required) <= set(group.split(",")) for group in groups if group)


def ignored_versions(update: dict[str, str]) -> dict[str, list[str]]:
    """Return ``{dependency-name: [version specs]}`` from the ``ignore`` block of ``update``."""
    result: dict[str, list[str]] = {}
    current: str | None = None
    for line in update.get("ignore", "").splitlines():
        name = _IGNORE_NAME_LINE.match(line)
        if name is not None:
            current = _unquote(name.group("value"))
            result.setdefault(current, [])
            continue
        versions = _IGNORE_VERSIONS_LINE.match(line)
        if versions is not None and current is not None:
            result[current].extend(_split_items(versions.group("items")))
    return result


def dependabot_problems(text: str, required: tuple[str, ...] = REQUIRED_ECOSYSTEMS) -> list[str]:
    """Return what is wrong with the update entries: a missing ecosystem, schedule or grouping."""
    updates = dependabot_updates(text)
    found = [update["package-ecosystem"] for update in updates]
    problems = [f"ecosystem {name!r} is not configured" for name in required if name not in found]
    for update in updates:
        name = update["package-ecosystem"]
        if update.get("interval") != "weekly":
            problems.append(f"{name}: no weekly schedule interval")
        if not has_grouped_update_types(update, ("minor", "patch")):
            problems.append(f"{name}: no group covering minor and patch updates")
    return problems


# --------------------------------------------------------------------------------------------
# Dependabot (T9.5): checks on the real file
# --------------------------------------------------------------------------------------------


def test_dependabot_file_exists() -> None:
    assert DEPENDABOT_FILE.is_file()


def test_dependabot_is_version_2() -> None:
    entry = top_level_entry(read_dependabot(), "version")
    assert entry is not None, "no top-level 'version:'"
    assert entry[0] == "2"


def test_dependabot_has_no_tabs() -> None:
    assert "\t" not in read_dependabot()


def test_dependabot_configures_exactly_both_ecosystems() -> None:
    updates = dependabot_updates(read_dependabot())
    found = sorted(update["package-ecosystem"] for update in updates)
    assert found == sorted(REQUIRED_ECOSYSTEMS)


def test_dependabot_schedules_and_groups_every_ecosystem() -> None:
    assert dependabot_problems(read_dependabot()) == []


def test_dependabot_holds_the_pyside6_family_below_6_13() -> None:
    (uv,) = [u for u in dependabot_updates(read_dependabot()) if u["package-ecosystem"] == "uv"]
    ignored = ignored_versions(uv)
    for name in PYSIDE_FAMILY:
        assert ">=6.13" in ignored.get(name, []), f"{name} is not ignored from 6.13 on"


def test_dependabot_update_pull_requests_run_ci_including_the_packaging_job() -> None:
    ci = read_workflow("ci.yml")
    assert "pull_request" in trigger_names(ci)
    build = [line.strip() for line in job_lines(ci, "build")]
    assert index_of_run(build, "uv run pytest -m packaging") != -1
    assert "test" in job_needs(ci, "build")


# --------------------------------------------------------------------------------------------
# Dependabot (T9.5): helper self-tests
# --------------------------------------------------------------------------------------------

GOOD_DEPENDABOT = (
    "version: 2\n"
    "updates:\n"
    "  # a comment\n"
    '  - package-ecosystem: "github-actions"\n'
    '    directory: "/"\n'
    "    schedule:\n"
    '      interval: "weekly"\n'
    "    groups:\n"
    "      all:\n"
    '        update-types: ["patch", "minor"]\n'
    '        patterns: ["*"]\n'
    "  - package-ecosystem: uv\n"
    "    schedule:\n"
    "      interval: weekly\n"
    "    groups:\n"
    "      py:\n"
    "        update-types: [minor, patch]\n"
    "    ignore:\n"
    '      - dependency-name: "demo-lib"\n'
    '        versions: [">=2.0", "1.5.0"]\n'
    '      - dependency-name: "other-lib"\n'
    '        versions: [">=3"]\n'
    "    open-pull-requests-limit: 5\n"
)


def test_dependabot_updates_splits_the_entries_and_reads_their_settings() -> None:
    first, second = dependabot_updates(GOOD_DEPENDABOT)
    assert first == {
        "package-ecosystem": "github-actions",
        "interval": "weekly",
        "update-types": "minor,patch",
    }
    assert second["package-ecosystem"] == "uv"
    assert second["interval"] == "weekly"
    assert second["update-types"] == "minor,patch"
    assert ignored_versions(second) == {"demo-lib": [">=2.0", "1.5.0"], "other-lib": [">=3"]}
    assert ignored_versions(first) == {}
    assert dependabot_updates("version: 2\n") == []
    assert dependabot_problems(GOOD_DEPENDABOT) == []


def test_dependabot_check_reports_a_missing_ecosystem() -> None:
    only_actions = GOOD_DEPENDABOT.split("  - package-ecosystem: uv\n")[0]
    assert len(dependabot_updates(only_actions)) == 1
    assert dependabot_problems(only_actions) == ["ecosystem 'uv' is not configured"]
    assert dependabot_problems("version: 2\n") == [
        "ecosystem 'github-actions' is not configured",
        "ecosystem 'uv' is not configured",
    ]


def test_dependabot_check_reports_an_entry_without_schedule() -> None:
    no_schedule = GOOD_DEPENDABOT.replace("    schedule:\n      interval: weekly\n", "")
    assert dependabot_problems(no_schedule) == ["uv: no weekly schedule interval"]
    daily = GOOD_DEPENDABOT.replace('interval: "weekly"', 'interval: "daily"')
    assert dependabot_problems(daily) == ["github-actions: no weekly schedule interval"]
    outside = "updates:\n  - package-ecosystem: uv\ninterval: weekly\n"
    assert "uv: no weekly schedule interval" in dependabot_problems(outside)


def test_dependabot_check_reports_missing_or_split_groups() -> None:
    py_groups = "    groups:\n      py:\n        update-types: [minor, patch]\n"
    no_groups = GOOD_DEPENDABOT.replace(py_groups, "")
    assert dependabot_problems(no_groups) == ["uv: no group covering minor and patch updates"]
    split = GOOD_DEPENDABOT.replace("[minor, patch]", "[minor]")
    assert dependabot_problems(split) == ["uv: no group covering minor and patch updates"]
    update = {"update-types": "minor;major,minor,patch"}
    assert has_grouped_update_types(update, ("minor", "patch"))
    assert not has_grouped_update_types({"update-types": "minor;patch"}, ("minor", "patch"))
    assert not has_grouped_update_types({}, ("minor", "patch"))
