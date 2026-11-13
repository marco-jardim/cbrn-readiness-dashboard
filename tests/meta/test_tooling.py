# SPDX-License-Identifier: GPL-3.0-or-later
"""Lint, format and type gates run from pytest, and proof that each gate bites."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


def test_ruff_check_passes() -> None:
    result = _run(["ruff", "check", "."], REPO_ROOT)
    assert result.returncode == 0, _output(result)


def test_ruff_format_check_passes() -> None:
    result = _run(["ruff", "format", "--check", "."], REPO_ROOT)
    assert result.returncode == 0, _output(result)


def test_mypy_passes() -> None:
    result = _run(["mypy"], REPO_ROOT)
    assert result.returncode == 0, _output(result)


def test_ruff_check_reports_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad_lint.py"
    bad.write_text("import os\n\nprint('x')\n", encoding="utf-8")
    result = _run(["ruff", "check", "--no-cache", "--config", str(PYPROJECT), str(bad)], tmp_path)
    assert result.returncode != 0, _output(result)
    assert "F401" in _output(result)


def test_ruff_format_check_reports_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad_format.py"
    bad.write_text("x   =   [1,2,\n   3]\n", encoding="utf-8")
    result = _run(
        ["ruff", "format", "--check", "--no-cache", "--config", str(PYPROJECT), str(bad)],
        tmp_path,
    )
    assert result.returncode != 0, _output(result)


def test_mypy_reports_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad_types.py"
    bad.write_text('x: int = "a"\n', encoding="utf-8")
    result = _run(
        [
            "mypy",
            "--config-file",
            str(PYPROJECT),
            "--cache-dir",
            str(tmp_path / ".mypy_cache"),
            str(bad),
        ],
        tmp_path,
    )
    assert result.returncode != 0, _output(result)
