# SPDX-License-Identifier: GPL-3.0-or-later
"""Repository hygiene checks (T0.3), driven by ``git ls-files``.

The checks keep real data, databases, backups and oversized files out of the repository and
make sure that no source file is silently hidden by an ignore rule. The whole module is skipped
when git is missing or the folder is not inside a git work tree.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[2]

SPDX_LINE = "# SPDX-License-Identifier: GPL-3.0-or-later"

# File-name patterns (matched on the base name, case-insensitively) that must never be tracked.
FORBIDDEN_NAME_PATTERNS: tuple[str, ...] = (
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*-journal",
    "*.cbrnbak",
    "*.qm",
    "*.before-restore-*",
)

# Leading bytes of an SQLite database and of a CBRN backup archive.
FORBIDDEN_MAGIC: tuple[bytes, ...] = (b"SQLite format 3\x00", b"CBRNBAK1")

# Folders that must contain no ignored file (apart from generated artefacts).
SOURCE_FOLDERS: tuple[str, ...] = ("src", "tests", "docs", "packaging", "scripts")

# Generated artefacts that may legitimately be ignored inside the source folders.
ARTEFACT_DIR_NAMES: frozenset[str] = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
)
ARTEFACT_SUFFIXES: frozenset[str] = frozenset({".pyc", ".qm"})

MAX_FILE_BYTES = 1_000_000  # 1 MB

# Tracked files allowed to exceed MAX_FILE_BYTES. Keep this empty unless a file really needs it
# (uv.lock is far below the limit, so it is not listed). Add a comment for every entry.
SIZE_ALLOW_LIST: frozenset[str] = frozenset()


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


def _git(*args: str) -> bytes:
    """Run git in the repository root and return its standard output."""
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return result.stdout


def _split_z(output: bytes) -> list[str]:
    """Split NUL-separated git output into path strings."""
    return [os.fsdecode(item) for item in output.split(b"\x00") if item]


def _inside_git_work_tree() -> bool:
    try:
        return _git("rev-parse", "--is-inside-work-tree").strip() == b"true"
    except (OSError, subprocess.CalledProcessError):
        return False


def matches_forbidden_name(path: str) -> bool:
    """Return True if the base name of ``path`` matches a database/backup/catalogue pattern."""
    name = PurePosixPath(path.replace("\\", "/")).name.lower()
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in FORBIDDEN_NAME_PATTERNS)


def has_forbidden_magic(path: Path) -> bool:
    """Return True if the file starts with the SQLite or backup magic bytes."""
    longest = max(len(magic) for magic in FORBIDDEN_MAGIC)
    with path.open("rb") as handle:
        head = handle.read(longest)
    return any(head.startswith(magic) for magic in FORBIDDEN_MAGIC)


def is_generated_artefact(path: str) -> bool:
    """Return True for caches, bytecode and compiled catalogues."""
    pure = PurePosixPath(path.replace("\\", "/"))
    if any(part in ARTEFACT_DIR_NAMES for part in pure.parts):
        return True
    return pure.suffix.lower() in ARTEFACT_SUFFIXES


def first_line_is_spdx(path: Path) -> bool:
    """Return True if the first line of the file is exactly the SPDX line."""
    with path.open("rb") as handle:
        first = handle.readline()
    return first.rstrip(b"\r\n") == SPDX_LINE.encode("ascii")


def is_oversized(size: int, path: str, allow: frozenset[str] = SIZE_ALLOW_LIST) -> bool:
    """Return True if a file of ``size`` bytes at ``path`` breaks the size limit."""
    return size > MAX_FILE_BYTES and path not in allow


# --------------------------------------------------------------------------------------------
# Skip the whole module outside a git work tree
# --------------------------------------------------------------------------------------------

if not _inside_git_work_tree():
    pytest.skip("git is missing or this folder is not a git work tree", allow_module_level=True)


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    """Tracked paths that still exist as regular files in the working tree."""
    names = _split_z(_git("ls-files", "-z"))
    # A tracked file may be deleted in the working tree (or be a submodule): skip those.
    return [name for name in names if (ROOT / name).is_file()]


# --------------------------------------------------------------------------------------------
# Repository checks
# --------------------------------------------------------------------------------------------


def test_no_tracked_database_backup_or_catalogue_names(tracked: list[str]) -> None:
    offenders = [name for name in tracked if matches_forbidden_name(name)]
    assert not offenders, f"database/journal/backup/catalogue files are tracked: {offenders}"


def test_no_tracked_file_has_database_or_backup_magic(tracked: list[str]) -> None:
    offenders = [name for name in tracked if has_forbidden_magic(ROOT / name)]
    assert not offenders, f"SQLite or .cbrnbak content is tracked (any name): {offenders}"


def test_no_source_file_is_ignored() -> None:
    output = _git(
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
        *SOURCE_FOLDERS,
    )
    ignored = [name for name in _split_z(output) if not is_generated_artefact(name)]
    assert not ignored, (
        f"files under {', '.join(SOURCE_FOLDERS)} are hidden by an ignore rule "
        f"(rename the folder or file): {ignored}"
    )


def test_python_files_start_with_spdx_line(tracked: list[str]) -> None:
    offenders = [
        name for name in tracked if name.endswith(".py") and not first_line_is_spdx(ROOT / name)
    ]
    assert not offenders, f"first line must be '{SPDX_LINE}': {offenders}"


def test_no_tracked_file_is_oversized(tracked: list[str]) -> None:
    offenders = [name for name in tracked if is_oversized((ROOT / name).stat().st_size, name)]
    assert not offenders, (
        f"files larger than {MAX_FILE_BYTES} bytes and not allow-listed: {offenders}"
    )


# --------------------------------------------------------------------------------------------
# Self-tests of the helpers (fictitious names and bytes) -- they prove the checks bite
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "demo.sqlite",
        "demo.sqlite3",
        "folder/demo.db",
        "demo.db-journal",
        "demo.sqlite3-journal",
        "demo.sqlite-journal",
        "x/backup.cbrnbak",
        "catalogue_pt_BR.qm",
        "demo.db.before-restore-20000101",
        "UPPER.SQLITE",
    ],
)
def test_name_matcher_flags_forbidden_names(name: str) -> None:
    assert matches_forbidden_name(name)


@pytest.mark.parametrize(
    "name",
    [
        "README.md",
        "src/cbrn_dashboard/storage.py",
        "database.py",
        "journal.txt",
        "catalogue_pt_BR.ts",
        "sqlite_notes.md",
        "mydb",
    ],
)
def test_name_matcher_accepts_ordinary_names(name: str) -> None:
    assert not matches_forbidden_name(name)


def test_magic_detector_flags_sqlite_and_backup_whatever_the_name(tmp_path: Path) -> None:
    sqlite_like = tmp_path / "innocent.txt"
    sqlite_like.write_bytes(b"SQLite format 3\x00" + b"\x00" * 32)
    backup_like = tmp_path / "notes.md"
    backup_like.write_bytes(b"CBRNBAK1" + b"payload")
    assert has_forbidden_magic(sqlite_like)
    assert has_forbidden_magic(backup_like)


def test_magic_detector_accepts_ordinary_content(tmp_path: Path) -> None:
    plain = tmp_path / "plain.txt"
    plain.write_bytes(b"hello, nothing to see")
    near_miss = tmp_path / "near.bin"
    near_miss.write_bytes(b"SQLite format 4\x00")
    prefix_only = tmp_path / "prefix.bin"
    prefix_only.write_bytes(b"CBRN")
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    assert not has_forbidden_magic(plain)
    assert not has_forbidden_magic(near_miss)
    assert not has_forbidden_magic(prefix_only)
    assert not has_forbidden_magic(empty)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/pkg/__pycache__/mod.cpython-312.pyc", True),
        ("tests/.pytest_cache/v/cache/lastfailed", True),
        ("src/.mypy_cache/3.12/meta.json", True),
        ("scripts/.ruff_cache/CACHEDIR.TAG", True),
        ("src/pkg/other.pyc", True),
        ("src/pkg/i18n/pt_BR.qm", True),
        ("src/pkg/data/demo.db", False),
        ("src/pkg/logs/app.log", False),
        ("docs/tmp/notes.md", False),
    ],
)
def test_artefact_predicate(path: str, expected: bool) -> None:
    assert is_generated_artefact(path) is expected


def test_spdx_predicate(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_bytes(f"{SPDX_LINE}\r\nx = 1\r\n".encode("ascii"))
    missing = tmp_path / "missing.py"
    missing.write_text("x = 1\n", encoding="utf-8")
    shebang_first = tmp_path / "shebang.py"
    shebang_first.write_text(f"#!/usr/bin/env python\n{SPDX_LINE}\n", encoding="utf-8")
    wrong_licence = tmp_path / "wrong.py"
    wrong_licence.write_text("# SPDX-License-Identifier: MIT\n", encoding="utf-8")
    empty = tmp_path / "empty.py"
    empty.write_text("", encoding="utf-8")
    assert first_line_is_spdx(good)
    assert not first_line_is_spdx(missing)
    assert not first_line_is_spdx(shebang_first)
    assert not first_line_is_spdx(wrong_licence)
    assert not first_line_is_spdx(empty)


def test_size_predicate() -> None:
    allowed = frozenset({"listed.bin"})
    assert not is_oversized(MAX_FILE_BYTES, "a.txt")
    assert is_oversized(MAX_FILE_BYTES + 1, "a.txt")
    assert is_oversized(MAX_FILE_BYTES + 1, "a.txt", allowed)
    assert not is_oversized(MAX_FILE_BYTES + 1, "listed.bin", allowed)
