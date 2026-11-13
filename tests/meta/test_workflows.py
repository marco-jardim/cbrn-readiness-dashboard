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


def workflow_files() -> list[Path]:
    """Return every ``.github/workflows/*.yml`` file, sorted by name."""
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


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
