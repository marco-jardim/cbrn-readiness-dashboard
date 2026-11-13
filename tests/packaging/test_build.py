# SPDX-License-Identifier: GPL-3.0-or-later
"""The frozen one-folder bundle (T0.9): it builds, passes its own self-test and is lean.

Deselected by default (``-m "not packaging"``); run with ``pytest -m packaging``. The bundle is
built once per session by the ``bundle_dir`` fixture.
"""

import ast
import ctypes
import fnmatch
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from types import ModuleType

import pytest

from cbrn_dashboard import __version__, i18n

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
    "qt6websockets",
    "qtwebchannel",
    "qt6webchannel",
    "qt6webengine",
    "qthttpserver",
    "qt6httpserver",
)

#: The checks of the frozen self-test that PLAN.md section 8 / T9.1 names: paths, database, i18n
#: in three languages, main window, chart, encrypted backup and PDF (plus the two basics).
REQUIRED_SELF_TESTS: frozenset[str] = frozenset(
    {
        "python",
        "qt",
        "paths",
        "database",
        "i18n.pt-BR",
        "i18n.en-US",
        "i18n.es-ES",
        "main_window",
        "chart",
        "encrypted_backup",
        "pdf",
    }
)

#: Folder names that must not occur anywhere in the bundle: tool caches and version control. (A
#: ``__pycache__`` folder is checked only inside the application's own package folder.)
FORBIDDEN_FOLDER_NAMES: frozenset[str] = frozenset(
    {".git", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv"}
)

#: File-name patterns (lower case) of user data; none may be in the bundle (T9.1, PLAN section 8).
DATA_NAME_PATTERNS: tuple[str, ...] = (
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.db-*",
    "*-journal",
    "*-wal",
    "*-shm",
    "*.cbrnbak",
    "*.before-restore-*",
    "*.csv",
    "prefs.json",
    "selftest.json",
    "location.json",
)
#: Leading bytes of an SQLite database and of an encrypted backup (T7.2), whatever the file name.
DATA_MAGIC: tuple[bytes, ...] = (b"SQLite format 3\x00", b"CBRNBAK1")


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
    # T9.1: every check of PLAN section 8 ran (not just "no check failed"), and so did every
    # check registered in the source, so a check added later cannot be silently skipped.
    from cbrn_dashboard import selftest

    ran = {check["name"] for check in document["checks"]}
    expected = REQUIRED_SELF_TESTS | {name for name, _check in selftest.CHECKS}
    assert expected <= ran, f"checks that did not run: {sorted(expected - ran)}\n{text}"


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


def test_windowed_build_disables_the_bootloader_traceback(
    build_script: ModuleType, tmp_path: Path
) -> None:
    # D22: the frozen window must never show a traceback with the exception message (no build).
    arguments = build_script.pyinstaller_arguments(
        tmp_path / "dist", tmp_path / "work", [], data_files=[]
    )
    assert "--windowed" in arguments
    assert "--disable-windowed-traceback" in arguments


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


# --------------------------------------------------------------------------- T9.1: contents


def _git_files(*paths: str) -> list[Path] | None:
    """Files git tracks below ``paths`` (relative to the repository), or ``None`` without git."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z", "--", *paths],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    names = [os.fsdecode(item) for item in result.stdout.split(b"\x00") if item]
    return sorted(Path(name) for name in names) or None


def _imported_qt_modules() -> set[str]:
    """The ``PySide6.Qt*`` modules the application's source imports (read from its syntax trees)."""
    found: set[str] = set()
    for path in SRC_PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if node.module == "PySide6":
                    found.update(alias.name for alias in node.names)
                elif node.module.startswith("PySide6."):
                    found.add(node.module.split(".")[1])
            elif isinstance(node, ast.Import):
                found.update(
                    alias.name.split(".")[1]
                    for alias in node.names
                    if alias.name.startswith("PySide6.")
                )
    return {name for name in found if name.startswith("Qt")}


def test_bundle_has_every_migration(bundle_dir: Path) -> None:
    # The expected set is the tracked ``storage/migrations/*.sql`` list (git), not the script's.
    migrations = Path("storage") / "migrations"
    expected = sorted(
        path
        for path in _expected_package_data()
        if path.parent == migrations and path.suffix == ".sql"
    )
    numbers = [int(path.name[:4]) for path in expected]
    assert len(expected) >= 7, f"fewer migrations than 0001-0007 are tracked: {expected}"
    assert numbers == list(range(1, len(numbers) + 1)), f"gap in the migration numbers: {numbers}"
    folder = _internal(bundle_dir) / "cbrn_dashboard" / migrations
    missing = [path.name for path in expected if not (folder / path.name).is_file()]
    assert not missing, f"migrations missing from the bundle: {missing}"
    empty = [path.name for path in expected if (folder / path.name).stat().st_size == 0]
    assert not empty, f"empty migrations in the bundle: {empty}"
    bundled = sorted(path.name for path in folder.glob("*.sql"))
    assert bundled == [path.name for path in expected], "the bundle holds other migrations"


def test_bundle_has_a_compiled_catalogue_for_every_ts_file(bundle_dir: Path) -> None:
    # Two independent sources: i18n.AREAS x LANGUAGES (so a new area is expected at once) and the
    # tracked .ts files (so a catalogue the build forgot to compile is found).
    tracked = _tracked_package_files()
    if tracked is None:
        pytest.skip("git is missing or the folder is not a git work tree: no independent list")
    ts_names = {
        path.name for path in tracked if path.parent == Path("i18n") and path.suffix == ".ts"
    }
    from_areas = {
        i18n.catalogue_path(area, lang).name for area in i18n.AREAS for lang in i18n.LANGUAGES
    }
    untracked = sorted(from_areas - ts_names)
    assert not untracked, f"areas without a tracked catalogue: {untracked}"
    expected = sorted({Path(name).with_suffix(".qm").name for name in ts_names | from_areas})
    folder = _internal(bundle_dir) / "cbrn_dashboard" / "i18n"
    missing = [name for name in expected if not (folder / name).is_file()]
    assert not missing, f"compiled catalogues missing from {folder}: {missing}"
    empty = [name for name in expected if (folder / name).stat().st_size == 0]
    assert not empty, f"empty compiled catalogues: {empty}"
    extra = sorted(path.name for path in folder.glob("*.qm") if path.name not in expected)
    assert not extra, f"catalogues without a source in the bundle: {extra}"


def test_bundle_has_countries_and_data_documents(bundle_dir: Path) -> None:
    package_root = _internal(bundle_dir) / "cbrn_dashboard"
    source = SRC_PACKAGE / "resources" / "countries.json"
    bundled = package_root / "resources" / "countries.json"
    assert bundled.is_file(), f"missing {bundled}"
    assert bundled.read_bytes() == source.read_bytes(), "the bundled countries.json differs"
    document = json.loads(bundled.read_text(encoding="utf-8"))
    assert document, "countries.json is empty"
    for relative in ("resources/THIRD_PARTY_DATA.md", "resources/app.ico"):
        path = package_root / relative
        assert path.is_file(), f"missing {path}"
        assert path.stat().st_size > 0, f"empty {path}"
    help_files = [path for path in _expected_package_data() if path.parts[0] == "help"]
    missing = [path.as_posix() for path in help_files if not (package_root / path).is_file()]
    assert not missing, f"help files missing from the bundle: {missing}"


def test_bundle_has_the_qt_modules_the_code_imports(
    bundle_dir: Path, build_script: ModuleType
) -> None:
    imported = _imported_qt_modules()
    # QtCharts: the charts; QtGui: QPdfWriter / QTextDocument of the PDF report (no extra plug-in:
    # the writer needs none and the chart images are QImage resources).
    assert {"QtCore", "QtGui", "QtWidgets", "QtCharts"} <= imported, sorted(imported)
    excluded = {
        name.removeprefix("PySide6.")
        for name in build_script.EXCLUDED_MODULES
        if name.startswith("PySide6.")
    }
    assert not imported & excluded, f"the code imports excluded modules: {imported & excluded}"
    missing: list[str] = []
    for module in sorted(imported):
        for pattern in (f"{module}*.pyd", f"Qt6{module.removeprefix('Qt')}.dll"):
            if not list(_internal(bundle_dir).rglob(pattern)):
                missing.append(pattern)
    assert not missing, f"Qt files missing from the bundle: {missing}"


def test_bundle_has_no_qt_network_or_web_library(bundle_dir: Path) -> None:
    # PLAN.md section 7.3 / K03: named explicitly, besides the broader substring check above.
    names = {path.name.lower() for path in _files(_internal(bundle_dir))}
    offenders = sorted(
        name
        for name in names
        if name == "qt6network.dll" or name.startswith(("qt6webengine", "qtwebengine"))
    )
    assert not offenders, f"network or web libraries in the bundle: {offenders}"


def test_bundle_holds_no_data_files(bundle_dir: Path) -> None:
    offenders: list[str] = []
    longest = max(len(magic) for magic in DATA_MAGIC)
    for path in _files(bundle_dir):
        relative = path.relative_to(bundle_dir).as_posix()
        name = path.name.lower()
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in DATA_NAME_PATTERNS):
            offenders.append(relative)
            continue
        with path.open("rb") as handle:
            head = handle.read(longest)
        if any(head.startswith(magic) for magic in DATA_MAGIC):
            offenders.append(relative)
    assert not offenders, f"database, backup, CSV or preference files in the bundle: {offenders}"


def test_bundle_holds_nothing_from_tests_or_caches(bundle_dir: Path) -> None:
    internal = _internal(bundle_dir)
    package_root = internal / "cbrn_dashboard"
    assert not (internal / "tests").exists(), "a tests folder in the bundle"
    offenders = [
        path.relative_to(bundle_dir).as_posix()
        for path in bundle_dir.rglob("*")
        if path.name.lower() in FORBIDDEN_FOLDER_NAMES
    ]
    offenders += [
        path.relative_to(bundle_dir).as_posix()
        for path in package_root.rglob("*")
        if path.name in {"__pycache__", "tests", "test", "conftest.py"}
        or path.suffix in {".pyc", ".pyo"}
        or (path.is_file() and path.name.startswith("test_"))
    ]
    tracked = _git_files("tests")
    if tracked is not None:
        test_names = {
            path.name
            for path in tracked
            if path.suffix == ".py"
            and (path.name.startswith("test_") or path.name == "conftest.py")
        }
        offenders += [
            path.relative_to(bundle_dir).as_posix()
            for path in _files(bundle_dir)
            if path.name in test_names
        ]
    assert not offenders, f"test files or caches in the bundle: {sorted(set(offenders))}"


class _FixedFileInfo(ctypes.Structure):
    """``VS_FIXEDFILEINFO`` of the Windows version API."""

    _fields_ = (
        ("dwSignature", wintypes.DWORD),
        ("dwStrucVersion", wintypes.DWORD),
        ("dwFileVersionMS", wintypes.DWORD),
        ("dwFileVersionLS", wintypes.DWORD),
        ("dwProductVersionMS", wintypes.DWORD),
        ("dwProductVersionLS", wintypes.DWORD),
        ("dwFileFlagsMask", wintypes.DWORD),
        ("dwFileFlags", wintypes.DWORD),
        ("dwFileOS", wintypes.DWORD),
        ("dwFileType", wintypes.DWORD),
        ("dwFileSubtype", wintypes.DWORD),
        ("dwFileDateMS", wintypes.DWORD),
        ("dwFileDateLS", wintypes.DWORD),
    )


def _read_version_resource(exe: Path) -> tuple[_FixedFileInfo, dict[str, str]]:
    """Read the version resource of ``exe`` with the Windows version API (``ctypes``)."""
    if sys.platform != "win32":
        pytest.skip("the Windows version API is available on Windows only")
    dll = ctypes.WinDLL("version")
    get_size = dll.GetFileVersionInfoSizeW
    get_size.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    get_size.restype = wintypes.DWORD
    get_info = dll.GetFileVersionInfoW
    get_info.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    get_info.restype = wintypes.BOOL
    query = dll.VerQueryValueW
    query.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    query.restype = wintypes.BOOL

    ignored = wintypes.DWORD(0)
    size = int(get_size(str(exe), ctypes.byref(ignored)))
    assert size > 0, f"{exe.name} has no version resource"
    buffer = ctypes.create_string_buffer(size)
    assert get_info(str(exe), 0, size, ctypes.addressof(buffer)), "GetFileVersionInfoW failed"

    def lookup(sub_block: str) -> tuple[int, int]:
        pointer = ctypes.c_void_p()
        length = wintypes.UINT(0)
        found = query(
            ctypes.addressof(buffer), sub_block, ctypes.byref(pointer), ctypes.byref(length)
        )
        assert found, f"no {sub_block} in the version resource"
        assert pointer.value is not None
        return pointer.value, int(length.value)

    address, _length = lookup("\\")
    fixed = _FixedFileInfo.from_address(address)
    fixed_copy = _FixedFileInfo.from_buffer_copy(fixed)
    address, _length = lookup("\\VarFileInfo\\Translation")
    raw = ctypes.string_at(address, 4)
    language = int.from_bytes(raw[:2], "little")
    code_page = int.from_bytes(raw[2:4], "little")
    strings: dict[str, str] = {}
    for key in ("FileVersion", "ProductVersion", "ProductName", "OriginalFilename"):
        address, length = lookup(f"\\StringFileInfo\\{language:04x}{code_page:04x}\\{key}")
        strings[key] = ctypes.wstring_at(address, length).rstrip("\x00")
    return fixed_copy, strings


def test_version_resource_equals_the_package_version(bundle_dir: Path) -> None:
    fixed, strings = _read_version_resource(bundle_dir / EXE_NAME)
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", __version__)
    assert match is not None, f"__version__ {__version__!r} is not major.minor.patch"
    major, minor, patch = (int(part) for part in match.groups())
    assert fixed.dwSignature == 0xFEEF04BD
    for high, low in (
        (fixed.dwFileVersionMS, fixed.dwFileVersionLS),
        (fixed.dwProductVersionMS, fixed.dwProductVersionLS),
    ):
        assert (high >> 16, high & 0xFFFF, low >> 16) == (major, minor, patch)
    assert strings["FileVersion"] == __version__
    assert strings["ProductVersion"] == __version__
    assert strings["ProductName"] == "CBRN Readiness Dashboard"
    assert strings["OriginalFilename"] == EXE_NAME


def test_version_file_is_generated_into_the_work_folder(
    build_script: ModuleType, tmp_path: Path
) -> None:
    path = build_script.write_version_file(tmp_path)
    assert isinstance(path, Path)
    assert tmp_path in path.parents
    text = path.read_text(encoding="utf-8")
    assert text.isascii()
    assert f"StringStruct('ProductVersion', {__version__!r})" in text
    arguments = build_script.pyinstaller_arguments(
        tmp_path / "dist", tmp_path / "work", [], data_files=[], version_file=path
    )
    assert f"--version-file={path}" in arguments
    tracked = _git_files(".")
    if tracked is not None:
        assert not [item for item in tracked if item.name == path.name], "version file committed"


@pytest.mark.parametrize(
    ("version", "quad"),
    [("1.2.3", (1, 2, 3, 0)), ("0.0.1", (0, 0, 1, 0)), ("1.0.0rc1", (1, 0, 0, 0))],
)
def test_version_quad_takes_the_numeric_prefix(
    build_script: ModuleType, version: str, quad: tuple[int, int, int, int]
) -> None:
    assert build_script.version_quad(version) == quad
    assert f"filevers={quad!r}" in build_script.render_version_file(version)


def test_version_quad_refuses_a_version_without_numbers(build_script: ModuleType) -> None:
    with pytest.raises(build_script.BuildError):
        build_script.version_quad("next")


def test_size_report_lists_the_top_level_folders(build_script: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "_internal" / "big").mkdir(parents=True)
    (tmp_path / "_internal" / "big" / "a.bin").write_bytes(b"x" * 3000)
    (tmp_path / "licenses").mkdir()
    (tmp_path / "licenses" / "l.txt").write_bytes(b"y" * 10)
    (tmp_path / "app.exe").write_bytes(b"z" * 20)
    lines = build_script.bundle_size_report(tmp_path)
    text = "\n".join(lines)
    assert "_internal/" in text
    assert "licenses/" in text
    assert "(files)" in text
    assert text.index("_internal/") < text.index("licenses/"), "not sorted by size"
    assert "big/" in text
