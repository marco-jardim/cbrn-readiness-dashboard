# SPDX-License-Identifier: GPL-3.0-or-later
"""The frozen one-folder bundle (T0.9): it builds, passes its own self-test and is lean.

Deselected by default (``-m "not packaging"``); run with ``pytest -m packaging``. The bundle is
built once per session by the ``bundle_dir`` fixture.
"""

import fnmatch
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from cbrn_dashboard import i18n

pytestmark = pytest.mark.packaging

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_PACKAGE = REPO_ROOT / "src" / "cbrn_dashboard"
EXE_NAME = "cbrn-dashboard.exe"
MAX_BUNDLE_MB = 400

#: Substrings that must not occur in any path of the bundle (lower case).
FORBIDDEN_PATH_PARTS: tuple[str, ...] = (
    "numpy",
    "matplotlib",
    "tkinter",
    "_tkinter",
    "tcl86",
    "tk86",
    "qtwebengine",
)


def _internal(bundle: Path) -> Path:
    return bundle / "_internal"


def _files(bundle: Path) -> list[Path]:
    return sorted(path for path in bundle.rglob("*") if path.is_file())


def test_build_produced_executable_and_internal_folder(bundle_dir: Path) -> None:
    assert (bundle_dir / EXE_NAME).is_file()
    assert _internal(bundle_dir).is_dir()


def test_frozen_self_test_passes(bundle_dir: Path, tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    env.pop("CBRN_DASHBOARD_DATA_DIR", None)  # --data-dir is what is exercised here
    result = subprocess.run(
        [str(bundle_dir / EXE_NAME), "--self-test", "--data-dir", str(data_dir)],
        env=env,
        capture_output=True,
        timeout=180,
        check=False,
    )
    result_file = data_dir / "selftest.json"
    text = "<no selftest.json>"
    if result_file.is_file():
        text = result_file.read_text(encoding="utf-8")
    sys.stdout.write(f"selftest.json:\n{text}\n")
    assert result.returncode == 0, f"exit code {result.returncode}; selftest.json:\n{text}"
    document = json.loads(text)
    assert document["passed"] is True, text
    failed = [check for check in document["checks"] if check["passed"] is not True]
    assert document["checks"], text
    assert not failed, f"failed checks: {failed}\n{text}"


def test_bundle_has_compiled_catalogues(bundle_dir: Path) -> None:
    folder = _internal(bundle_dir) / "cbrn_dashboard" / "i18n"
    expected = [i18n.qm_name(area, lang) for area in i18n.AREAS for lang in i18n.LANGUAGES]
    assert expected, "no catalogues are expected"
    missing = [name for name in expected if not (folder / name).is_file()]
    assert not missing, f"missing in {folder}: {missing}"


def test_bundle_has_qt_platform_plugins(bundle_dir: Path) -> None:
    assert list(bundle_dir.glob("**/platforms/qoffscreen.dll")), "no offscreen platform plug-in"
    assert list(bundle_dir.glob("**/platforms/qwindows.dll")), "no windows platform plug-in"


def test_bundle_contains_all_package_data(bundle_dir: Path, build_script: ModuleType) -> None:
    package_root = _internal(bundle_dir) / "cbrn_dashboard"
    relative_files: list[Path] = build_script.package_data_files(SRC_PACKAGE)
    missing = [str(path) for path in relative_files if not (package_root / path).is_file()]
    assert not missing, f"package data missing from the bundle: {missing}"


def test_bundle_has_no_ts_catalogues(bundle_dir: Path) -> None:
    ts_files = [str(path.relative_to(bundle_dir)) for path in bundle_dir.rglob("*.ts")]
    assert not ts_files, f".ts files in the bundle: {ts_files}"


def test_unwanted_qt_files_are_pruned(bundle_dir: Path, build_script: ModuleType) -> None:
    patterns: tuple[str, ...] = build_script.UNWANTED_FILE_PATTERNS
    offenders = [
        str(path.relative_to(bundle_dir))
        for path in _files(bundle_dir)
        if any(fnmatch.fnmatchcase(path.name.lower(), pattern.lower()) for pattern in patterns)
    ]
    assert not offenders, f"unwanted files in the bundle: {offenders}"


def test_unwanted_plugin_folders_are_pruned(bundle_dir: Path, build_script: ModuleType) -> None:
    folders: tuple[str, ...] = build_script.UNWANTED_PLUGIN_DIRS
    internal = _internal(bundle_dir)
    present = [name for name in folders if internal.joinpath(*name.split("/")).exists()]
    assert not present, f"unwanted folders in the bundle: {present}"


def test_bundle_has_no_unused_libraries(bundle_dir: Path) -> None:
    offenders: list[str] = []
    for path in _files(bundle_dir):
        relative = path.relative_to(bundle_dir).as_posix().lower()
        if any(part in relative for part in FORBIDDEN_PATH_PARTS) or path.name.lower() == (
            "qt6network.dll"
        ):
            offenders.append(relative)
    assert not offenders, f"unused libraries in the bundle: {offenders}"


def test_bundle_size_is_reasonable(
    bundle_dir: Path, record_property: Callable[[str, object], None]
) -> None:
    total = sum(path.stat().st_size for path in _files(bundle_dir))
    megabytes = round(total / (1024 * 1024), 1)
    record_property("bundle_size_mb", megabytes)
    sys.stdout.write(f"bundle size: {megabytes} MB\n")
    assert megabytes < MAX_BUNDLE_MB
