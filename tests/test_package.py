# SPDX-License-Identifier: GPL-3.0-or-later
"""Package skeleton checks: import, metadata version and the ``--version`` flag."""

import importlib.metadata
import subprocess
import sys

import pytest

import cbrn_dashboard
from cbrn_dashboard.__main__ import main


def test_package_imports_with_version() -> None:
    assert isinstance(cbrn_dashboard.__version__, str)
    assert cbrn_dashboard.__version__


def test_installed_metadata_version_matches() -> None:
    assert importlib.metadata.version("cbrn-readiness-dashboard") == cbrn_dashboard.__version__


def test_module_version_flag_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "cbrn_dashboard", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert cbrn_dashboard.__version__ in result.stdout


def test_main_version_prints_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert f"cbrn-dashboard {cbrn_dashboard.__version__}" in capsys.readouterr().out


def test_main_without_arguments_returns_zero() -> None:
    assert main([]) == 0
