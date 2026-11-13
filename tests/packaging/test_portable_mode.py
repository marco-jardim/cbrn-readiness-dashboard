# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable mode of the frozen bundle (T9.4, PLAN.md D02).

``portable.ini`` beside ``cbrn-dashboard.exe`` puts the data in ``.\\data\\`` beside the program;
without it the data goes to ``%LOCALAPPDATA%\\cbrn-readiness-dashboard\\``. Both are proved with
the frozen ``--self-test`` and no ``--data-dir``, on a copy of the built folder, with
``LOCALAPPDATA`` pointing at an empty temporary folder.

Deselected by default (``-m "not packaging"``); run with ``pytest -m packaging``. The bundle is
built once per session by the ``bundle_dir`` fixture.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.packaging

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = REPO_ROOT / "packaging" / "portable.ini.example"
EXE_NAME = "cbrn-dashboard.exe"
MARKER_NAME = "portable.ini"
DATA_DIR_NAME = "data"
APP_DIR_NAME = "cbrn-readiness-dashboard"
DATABASE_FILE_NAME = "cbrn-dashboard.sqlite3"
RESULT_FILE_NAME = "selftest.json"


@pytest.fixture(scope="module")
def program_copy(bundle_dir: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One copy of the built folder, so that the session's ``bundle_dir`` is never written to."""
    target = tmp_path_factory.mktemp("portable") / "cbrn-readiness-dashboard"
    shutil.copytree(bundle_dir, target)
    return target


@pytest.fixture
def program(program_copy: Path) -> Path:
    """The copy in a clean state: no marker, no data folder, no result file."""
    (program_copy / MARKER_NAME).unlink(missing_ok=True)
    shutil.rmtree(program_copy / DATA_DIR_NAME, ignore_errors=True)
    (program_copy / RESULT_FILE_NAME).unlink(missing_ok=True)
    return program_copy


def _run_self_test(program: Path, local_app_data: Path) -> subprocess.CompletedProcess[bytes]:
    """Run ``--self-test`` without ``--data-dir`` and without ``CBRN_DASHBOARD_DATA_DIR``."""
    env = {**os.environ, "LOCALAPPDATA": str(local_app_data), "QT_QPA_PLATFORM": "offscreen"}
    env.pop("CBRN_DASHBOARD_DATA_DIR", None)
    return subprocess.run(
        [str(program / EXE_NAME), "--self-test"],
        env=env,
        cwd=local_app_data.parent,
        capture_output=True,
        timeout=180,
        check=False,
    )


def _assert_all_checks_passed(result_file: Path, returncode: int) -> None:
    text = "<no selftest.json>"
    if result_file.is_file():
        text = result_file.read_text(encoding="utf-8")
    sys.stdout.write(f"{result_file}:\n{text}\n")
    assert returncode == 0, f"exit code {returncode}; selftest.json:\n{text}"
    document = json.loads(text)
    assert document["passed"] is True, text
    assert document["checks"], text
    failed = [check for check in document["checks"] if check["passed"] is not True]
    assert not failed, f"failed checks: {failed}\n{text}"


def test_portable_ini_puts_the_data_beside_the_program(program: Path, tmp_path: Path) -> None:
    shutil.copyfile(EXAMPLE_PATH, program / MARKER_NAME)
    local = tmp_path / "local-app-data"
    local.mkdir()

    result = _run_self_test(program, local)

    data = program / DATA_DIR_NAME
    _assert_all_checks_passed(data / RESULT_FILE_NAME, result.returncode)
    assert not list((data / "tmp").glob("selftest-*")), "a throwaway folder was left behind"
    assert not (data / DATABASE_FILE_NAME).exists(), "the self-test created a real database"
    written = sorted(path.name for path in local.iterdir())
    assert not written, f"something was written to LOCALAPPDATA: {written}"


def test_without_portable_ini_the_data_goes_to_the_windows_profile(
    program: Path, tmp_path: Path
) -> None:
    assert not (program / MARKER_NAME).exists()
    local = tmp_path / "local-app-data"
    local.mkdir()

    result = _run_self_test(program, local)

    data = local / APP_DIR_NAME
    _assert_all_checks_passed(data / RESULT_FILE_NAME, result.returncode)
    assert not (program / DATA_DIR_NAME).exists(), "data was written beside the program"
    assert not (program / RESULT_FILE_NAME).exists()
    assert not (data / DATABASE_FILE_NAME).exists(), "the self-test created a real database"
