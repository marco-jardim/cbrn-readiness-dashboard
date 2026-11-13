# SPDX-License-Identifier: GPL-3.0-or-later
"""The frozen one-folder bundle (T0.9): it builds, passes its own self-test and is lean.

Deselected by default (``-m "not packaging"``); run with ``pytest -m packaging``. The bundle is
built once per session by the ``bundle_dir`` fixture.
"""

import fnmatch
import json
import os
import re
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
BUILD_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

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

#: Further substrings (lower case), checked only for paths under ``_internal/``: the Qt network
#: stack, in its DLL and Python-binding spellings. They are limited to ``_internal`` so that the
#: names in ``licenses/`` (component folders, ``QT-THIRD-PARTY.md``) can never trip them.
FORBIDDEN_INTERNAL_PATH_PARTS: tuple[str, ...] = (
    "qtnetwork",
    "qt6network",
    "qtwebsockets",
    "qthttpserver",
)


def _internal(bundle: Path) -> Path:
    return bundle / "_internal"


def _tracked_package_files() -> list[Path] | None:
    """Files git tracks below ``src/cbrn_dashboard`` (relative to it), or ``None`` without git."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", "src/cbrn_dashboard"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    names = [os.fsdecode(item) for item in result.stdout.split(b"\x00") if item]
    if not names:
        return None
    return sorted(Path(name).relative_to("src/cbrn_dashboard") for name in names)


def _expected_package_data() -> list[Path]:
    """Tracked package files that are neither ``.py`` nor ``.ts`` (independent of the build)."""
    tracked = _tracked_package_files()
    if tracked is None:
        pytest.skip("git is missing or the folder is not a git work tree: no independent list")
    return [
        relative
        for relative in tracked
        if relative.suffix.lower() not in {".py", ".ts"} and (SRC_PACKAGE / relative).is_file()
    ]


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


def test_bundle_contains_all_package_data(bundle_dir: Path) -> None:
    # The expected set comes from git, not from the build script, so a wrong exclusion in the
    # script (for example ".sql") cannot hide itself. build_info.json is generated, not tracked.
    package_root = _internal(bundle_dir) / "cbrn_dashboard"
    expected = _expected_package_data()
    assert expected, "git lists no package data"
    missing = [path.as_posix() for path in expected if not (package_root / path).is_file()]
    assert not missing, f"package data missing from the bundle: {missing}"


def test_bundle_package_folder_holds_only_tracked_data(bundle_dir: Path) -> None:
    package_root = _internal(bundle_dir) / "cbrn_dashboard"
    allowed = {path.as_posix() for path in _expected_package_data()}
    allowed.add("build_info.json")
    bundled = [path.relative_to(package_root).as_posix() for path in _files(package_root)]
    extra = [name for name in bundled if name not in allowed and not name.endswith(".qm")]
    assert not extra, f"untracked files in the bundled package folder: {extra}"


def test_bundle_has_build_info(bundle_dir: Path) -> None:
    path = _internal(bundle_dir) / "cbrn_dashboard" / "build_info.json"
    assert path.is_file(), f"missing {path}"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    stamp = document["built_at_utc"]
    assert isinstance(stamp, str)
    assert BUILD_TIMESTAMP.fullmatch(stamp), stamp


def test_build_timestamp_honours_source_date_epoch(
    build_script: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert build_script.build_timestamp_utc() == "1970-01-01T00:00:00Z"
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    assert build_script.build_timestamp_utc() == "2023-11-14T22:13:20Z"
    monkeypatch.delenv("SOURCE_DATE_EPOCH")
    assert BUILD_TIMESTAMP.fullmatch(build_script.build_timestamp_utc())
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "yesterday")
    with pytest.raises(build_script.BuildError):
        build_script.build_timestamp_utc()


def test_package_data_comes_from_git_in_this_work_tree(build_script: ModuleType) -> None:
    if _tracked_package_files() is None:
        pytest.skip("not a git work tree")
    files, source = build_script.package_data_with_source(SRC_PACKAGE)
    assert source == "git"
    assert Path("storage") / "migrations" / "0001_core.sql" in files


def test_filesystem_fallback_lists_data_and_skips_sources(
    build_script: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "pkg" / "__pycache__").mkdir(parents=True)
    (tmp_path / "pkg" / "__pycache__" / "mod.pyc").write_bytes(b"x")
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "pkg" / "cat.ts").write_text("<TS/>\n", encoding="utf-8")
    (tmp_path / "pkg" / "schema.sql").write_text("select 1;\n", encoding="utf-8")
    files, source = build_script.package_data_with_source(tmp_path)
    assert source == "filesystem"
    assert files == [Path("pkg") / "schema.sql"]


@pytest.mark.parametrize(
    "name",
    [
        "copy.sqlite3",
        "x.db",
        "x.db-journal",
        "backup.cbrnbak",
        "x.db.before-restore-20000101",
        "prefs.json",
        "selftest.json",
        "location.json",
        "app.log",
        "table.csv",
    ],
)
def test_build_refuses_data_files_by_name(
    build_script: ModuleType, tmp_path: Path, name: str
) -> None:
    (tmp_path / name).write_bytes(b"harmless")
    with pytest.raises(build_script.BuildError):
        build_script.package_data_files(tmp_path)


@pytest.mark.parametrize("head", [b"SQLite format 3\x00" + b"\x00" * 16, b"CBRNBAK1payload"])
def test_build_refuses_data_files_by_magic_bytes(
    build_script: ModuleType, tmp_path: Path, head: bytes
) -> None:
    (tmp_path / "innocent.txt").write_bytes(head)
    with pytest.raises(build_script.BuildError):
        build_script.package_data_files(tmp_path)


def test_bundle_has_the_core_migration_by_name(bundle_dir: Path) -> None:
    package_root = _internal(bundle_dir) / "cbrn_dashboard"
    migration = package_root / "storage" / "migrations" / "0001_core.sql"
    assert migration.is_file(), f"missing {migration}"


def test_bundle_has_licenses_folder_with_index(bundle_dir: Path) -> None:
    folder = bundle_dir / "licenses"
    assert folder.is_dir(), "no licenses folder at the bundle root"
    assert not (_internal(bundle_dir) / "licenses").exists()
    for name in ("index.json", "INDEX.md", "GPL-3.0.txt", "LGPL-3.0.txt", "SOURCE-OFFER.md"):
        path = folder / name
        assert path.is_file(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"
    index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    components = {item["component"].lower(): item for item in index}
    assert components["qt charts"]["chosen"] == "GPL-3.0-only"
    assert components["pyside6"]["chosen"] == "LGPL-3.0-only"
    missing = [
        relative
        for item in index
        for relative in item["files"]
        if not (folder / relative).is_file()
    ]
    assert not missing, f"index entries without a file: {missing}"


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
        forbidden = list(FORBIDDEN_PATH_PARTS)
        if relative.startswith("_internal/"):
            forbidden.extend(FORBIDDEN_INTERNAL_PATH_PARTS)
        if any(part in relative for part in forbidden):
            offenders.append(relative)
    assert not offenders, f"unused libraries in the bundle: {offenders}"


def test_bundle_size_is_reasonable(
    bundle_dir: Path,
    record_property: Callable[[str, object], None],
    report_bundle_size: Callable[[float, Path], None],
) -> None:
    total = sum(path.stat().st_size for path in _files(bundle_dir))
    megabytes = round(total / (1024 * 1024), 1)
    record_property("bundle_size_mb", megabytes)
    report_bundle_size(megabytes, bundle_dir)  # printed by the terminal summary (conftest.py)
    assert megabytes < MAX_BUNDLE_MB
