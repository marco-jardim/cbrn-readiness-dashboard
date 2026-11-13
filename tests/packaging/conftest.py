# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures of the packaging tests: one PyInstaller build per test session.

The bundle is built into pytest temporary folders, unless ``CBRN_BUNDLE_DIST_DIR`` and
``CBRN_BUNDLE_WORK_DIR`` name the folders to use (absolute, or relative to the repository root;
created when missing). CI sets them so that the very bundle the tests inspected and ran is the
one that is archived and uploaded.
"""

import importlib.util
import os
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_exe.py"

DIST_DIR_VARIABLE = "CBRN_BUNDLE_DIST_DIR"
WORK_DIR_VARIABLE = "CBRN_BUNDLE_WORK_DIR"

#: ``(megabytes, bundle folder)`` once a test has measured the bundle of this session.
_BUNDLE_SIZE: dict[str, tuple[float, Path]] = {}


def record_bundle_size(megabytes: float, bundle: Path) -> None:
    """Remember the bundle size so that the terminal summary can print it."""
    _BUNDLE_SIZE["size"] = (megabytes, bundle)


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Print ``bundle size: <n> MB (<path>)`` when the bundle was measured in this session."""
    recorded = _BUNDLE_SIZE.get("size")
    if recorded is None:
        return
    megabytes, bundle = recorded
    terminalreporter.write_line(f"bundle size: {megabytes} MB ({bundle})")


def _configured_folder(variable: str) -> Path | None:
    """Return the folder named by the environment variable, made absolute, or ``None``."""
    value = os.environ.get(variable, "").strip()
    if not value:
        return None
    folder = Path(value)
    if not folder.is_absolute():
        folder = REPO_ROOT / folder
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@pytest.fixture(scope="session")
def report_bundle_size() -> Callable[[float, Path], None]:
    """The function that records the bundle size for the terminal summary."""
    return record_bundle_size


@pytest.fixture(scope="session")
def build_script() -> ModuleType:
    """``scripts/build_exe.py`` imported by path (``scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location("cbrn_build_exe_script", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def bundle_dir(build_script: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the bundle once and return ``<dist>/cbrn-dashboard``.

    The folders come from ``CBRN_BUNDLE_DIST_DIR`` / ``CBRN_BUNDLE_WORK_DIR`` when set, else
    from pytest temporary folders.
    """
    dist_dir = _configured_folder(DIST_DIR_VARIABLE) or tmp_path_factory.mktemp("dist")
    work_dir = _configured_folder(WORK_DIR_VARIABLE) or tmp_path_factory.mktemp("work")
    bundle = build_script.build(dist_dir, work_dir)
    assert isinstance(bundle, Path)
    return bundle
