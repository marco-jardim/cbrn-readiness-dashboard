# SPDX-License-Identifier: GPL-3.0-or-later
"""Lint, format and type gates run from pytest, and proof that each gate bites."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

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
    result = _run(["ruff", "check", "--no-cache", "."], REPO_ROOT)
    assert result.returncode == 0, _output(result)


def test_ruff_format_check_passes() -> None:
    result = _run(["ruff", "format", "--check", "--no-cache", "."], REPO_ROOT)
    assert result.returncode == 0, _output(result)


def test_mypy_passes(tmp_path: Path) -> None:
    result = _run(["mypy", "--cache-dir", str(tmp_path / "mypy-cache")], REPO_ROOT)
    assert result.returncode == 0, _output(result)


# Each case fires only because of the rules configured in pyproject.toml (ruff's defaults are
# just E4/E7/E9/F), except F401, which the defaults also report. The T201 per-file-ignore
# covers scripts/**, __main__.py and cli.py, so the temporary file has none of those names.
@pytest.mark.parametrize(
    ("source", "code"),
    [
        ("import os\n", "F401"),
        ("print('x')\n", "T201"),
        ("import datetime\n\nNOW = datetime.datetime.now()\n", "DTZ005"),
        ("import os\n\nJOINED = os.path.join('a', 'b')\n", "PTH"),
    ],
    ids=["F401", "T201", "DTZ005", "PTH"],
)
def test_ruff_check_reports_bad_file(tmp_path: Path, source: str, code: str) -> None:
    bad = tmp_path / "bad_lint.py"
    bad.write_text(source, encoding="utf-8")
    result = _run(["ruff", "check", "--no-cache", "--config", str(PYPROJECT), str(bad)], tmp_path)
    assert result.returncode != 0, _output(result)
    assert code in _output(result)


def test_ruff_format_check_reports_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad_format.py"
    bad.write_text("x   =   [1,2,\n   3]\n", encoding="utf-8")
    result = _run(
        ["ruff", "format", "--check", "--no-cache", "--config", str(PYPROJECT), str(bad)],
        tmp_path,
    )
    assert result.returncode != 0, _output(result)


# ``def f(x): return x`` is an error only under ``strict = true`` (``disallow_untyped_defs``);
# the global strict flag applies to a file passed explicitly, since the override in
# pyproject.toml only relaxes the Qt-facing modules.
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('x: int = "a"\n', "assignment"),
        ("def f(x):\n    return x\n", "no-untyped-def"),
    ],
    ids=["type-mismatch", "strict-untyped-def"],
)
def test_mypy_reports_bad_file(tmp_path: Path, source: str, expected: str) -> None:
    bad = tmp_path / "bad_types.py"
    bad.write_text(source, encoding="utf-8")
    result = _run(
        [
            "mypy",
            "--config-file",
            str(PYPROJECT),
            "--cache-dir",
            str(tmp_path / "mypy-cache"),
            str(bad),
        ],
        tmp_path,
    )
    assert result.returncode != 0, _output(result)
    assert expected in _output(result)
