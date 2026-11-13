# SPDX-License-Identifier: GPL-3.0-or-later
"""The Inno Setup installer built from the frozen bundle (packaging suite).

The installer is built with ``scripts/build_installer.py`` from the bundle of the session
(``bundle_dir`` fixture) and then run through ``scripts/smoke_installer.ps1``: silent install for
the current user into a temporary folder, the frozen ``--self-test`` of the installed program,
silent uninstall, and a check that the data folder survived.

Inno Setup 6 (``ISCC.exe``) is preinstalled on the GitHub ``windows-2025`` image. Where it is not
found the test is skipped with the reason, except on GitHub Actions (``GITHUB_ACTIONS`` is
``true``): there a missing compiler is a failure, so that CI always builds and tests the installer.

Deselected by default (``-m "not packaging"``); run with ``pytest -m packaging``.
"""

import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.packaging

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_installer.py"
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "smoke_installer.ps1"
#: ``smoke_installer.ps1`` exits with 2 when the program is already installed on this computer.
EXIT_ALREADY_INSTALLED = 2


def must_not_skip(environ: Mapping[str, str]) -> bool:
    """Tell whether a missing ISCC is a failure: true exactly on GitHub Actions."""
    return environ.get("GITHUB_ACTIONS") == "true"


@pytest.fixture(scope="module")
def installer_script() -> ModuleType:
    """``scripts/build_installer.py`` imported by path (``scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location("cbrn_build_installer_script", BUILD_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def iscc(installer_script: ModuleType) -> Path:
    """The path of ``ISCC.exe``; skip (not on GitHub Actions) or fail when it is missing."""
    try:
        found = installer_script.find_iscc(None, os.environ, shutil.which, Path.is_file)
    except installer_script.InstallerError as error:
        if must_not_skip(os.environ):
            pytest.fail(f"Inno Setup is required on GitHub Actions: {error}")
        pytest.skip(f"Inno Setup 6 (ISCC.exe) is not installed here: {error}")
    assert isinstance(found, Path)
    return found


@pytest.fixture(scope="module")
def setup_file(
    installer_script: ModuleType,
    iscc: Path,
    bundle_dir: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Build the installer from the session's bundle once."""
    out_dir = tmp_path_factory.mktemp("installer")
    version = installer_script.read_package_version()
    built = installer_script.build_installer(bundle_dir, out_dir, version, iscc)
    assert isinstance(built, Path)
    return built


def test_the_installer_is_built_with_the_release_name(
    installer_script: ModuleType, setup_file: Path
) -> None:
    version = installer_script.read_package_version()
    assert setup_file.name == f"cbrn-readiness-dashboard-{version}-win-x64-setup.exe"
    assert setup_file.read_bytes()[:2] == b"MZ"
    assert setup_file.stat().st_size > 1_000_000


def test_silent_install_self_test_and_silent_uninstall_keep_the_data(
    setup_file: Path, tmp_path: Path
) -> None:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if shell is None:
        pytest.skip("neither pwsh nor powershell is on PATH")
    command = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SMOKE_SCRIPT)]
    command += ["-Setup", str(setup_file), "-WorkDir", str(tmp_path / "smoke")]
    result = subprocess.run(command, capture_output=True, timeout=1200, check=False)
    output = result.stdout.decode("utf-8", errors="replace")
    sys.stdout.write(output)
    if result.returncode == EXIT_ALREADY_INSTALLED:
        pytest.skip("the program is installed on this computer; uninstall it to run this test")
    assert result.returncode == 0, f"exit code {result.returncode}\n{output}"
    assert "PASSED" in output
