# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixtures of the packaging tests: one PyInstaller build per test session."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "build_exe.py"


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
    """Build the bundle once into temporary folders and return ``<dist>/cbrn-dashboard``."""
    dist_dir = tmp_path_factory.mktemp("dist")
    work_dir = tmp_path_factory.mktemp("work")
    bundle = build_script.build(dist_dir, work_dir)
    assert isinstance(bundle, Path)
    return bundle
