# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the one-folder Windows bundle with PyInstaller (PLAN.md section 8, decision D01).

``python scripts/build_exe.py [--dist-dir DIR] [--work-dir DIR]``
    Compile the translation catalogues, run PyInstaller through its Python API (no committed
    ``.spec`` file: the spec is generated into the work folder), then delete the Qt libraries and
    plug-ins that only serve modules the application does not use. The result is the folder
    ``<dist-dir>/cbrn-dashboard`` holding ``cbrn-dashboard.exe`` and ``_internal/``. The last step
    writes the third-party licence folder ``licenses/`` beside the executable
    (``scripts/collect_licenses.py``).

The functions are importable (the packaging tests load this file by path, since ``scripts/`` is
not a package): :func:`build`, :func:`package_data_files`, :func:`prune_bundle` and the tables
:data:`UNWANTED_FILE_PATTERNS` / :data:`UNWANTED_PLUGIN_DIRS`.

The package data comes from ``git ls-files`` (tracked files only); without a git work tree every
file is a candidate and the build is refused if one looks like a database, backup or other user
data. The build also writes ``cbrn_dashboard/build_info.json`` (``built_at_utc``, honouring
``SOURCE_DATE_EPOCH``) into the bundle; it is generated in the work folder, never in ``src/``.

``--exclude-module`` takes Python module names and can leave the Qt DLLs behind, hence the pruning
step. If the frozen self-test ever proves that a pruned DLL is a link-time dependency of a kept
one (``Qt6Network.dll`` is the usual suspect), drop its single line from the table below.
"""

import argparse
import fnmatch
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
PACKAGE_NAME = "cbrn_dashboard"
PACKAGE_DIR = SRC_DIR / PACKAGE_NAME
ICON_PATH = PACKAGE_DIR / "resources" / "app.ico"
I18N_SCRIPT = REPO_ROOT / "scripts" / "i18n.py"
COLLECT_LICENSES_SCRIPT = REPO_ROOT / "scripts" / "collect_licenses.py"
#: The licence folder sits at the bundle root, beside the executable (PLAN.md section 8).
LICENSES_DIR_NAME = "licenses"

APP_NAME = "cbrn-dashboard"
INTERNAL_DIR_NAME = "_internal"
DEFAULT_DIST_DIR = REPO_ROOT / "dist"
DEFAULT_WORK_DIR = REPO_ROOT / "build"

#: Package files that are never shipped as data: sources (compiled into the archive), the
#: Linguist catalogues, byte code, and stale ``.qm`` files (the catalogues are compiled afresh).
EXCLUDED_DATA_SUFFIXES: frozenset[str] = frozenset({".ts", ".py", ".pyc", ".pyo", ".qm"})
EXCLUDED_DATA_DIRS: frozenset[str] = frozenset({"__pycache__"})

#: Base-name patterns (case-insensitive) of files that must never be bundled: databases,
#: backups, preferences, self-test results, logs. A candidate that matches stops the build.
DATA_FILE_NAME_PATTERNS: tuple[str, ...] = (
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*-journal",
    "*.cbrnbak",
    "*.before-restore-*",
    "prefs.json",
    "selftest.json",
    "location.json",
    "*.log",
    "*.csv",
)
#: Leading bytes of an SQLite database and of a CBRN backup archive (any file name).
DATA_FILE_MAGIC: tuple[bytes, ...] = (b"SQLite format 3\x00", b"CBRNBAK1")

#: Generated at build time (work folder) and shipped as ``cbrn_dashboard/build_info.json``; the
#: application's start-up clock check reads ``built_at_utc`` from it.
BUILD_INFO_NAME = "build_info.json"

EXCLUDED_MODULES: tuple[str, ...] = (
    "PySide6.QtNetwork",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "numpy",
    "matplotlib",
    "tkinter",
)

#: File-name patterns (case-insensitive, matched against the name only) deleted from
#: ``_internal`` after the build. One line per pattern: drop a line to keep that file.
UNWANTED_FILE_PATTERNS: tuple[str, ...] = (
    "Qt6Network*.dll",
    "Qt6WebEngine*.dll",
    "Qt6WebChannel*.dll",
    "Qt6WebSockets*.dll",
    "Qt6Qml*.dll",
    "Qt6Quick*.dll",
    "Qt63D*.dll",
    "Qt6Multimedia*.dll",
    "Qt6Bluetooth*.dll",
    "Qt6Positioning*.dll",
    "Qt6Sql*.dll",
    "Qt6Pdf*.dll",
    "Qt6HttpServer*.dll",
    "QtNetwork*.pyd",  # the Python bindings of the excluded modules
    "QtWebEngine*.pyd",
    "QtWebSockets*.pyd",
    "QtWebChannel*.pyd",
    "QtHttpServer*.pyd",
    "QtQml*.pyd",
    "QtQuick*.pyd",
    "QtSql*.pyd",
    "QtPdf*.pyd",
    "QtMultimedia*.pyd",
    "QtBluetooth*.pyd",
    "QtPositioning*.pyd",
    "QtWebEngineProcess*.exe",
    "qpdf.dll",  # the image-format plug-in that needs Qt6Pdf.dll
    "qtwebengine*.qm",
)

#: Folders (POSIX paths relative to ``_internal``) deleted after the build: the plug-in folders
#: that only serve the excluded modules, plus the QML and QtWebEngine resource trees.
UNWANTED_PLUGIN_DIRS: tuple[str, ...] = (
    "PySide6/plugins/tls",
    "PySide6/plugins/networkinformation",
    "PySide6/plugins/sqldrivers",
    "PySide6/plugins/multimedia",
    "PySide6/plugins/qmltooling",
    "PySide6/plugins/qmllint",
    "PySide6/plugins/position",
    "PySide6/plugins/webview",
    "PySide6/plugins/scenegraph",
    "PySide6/plugins/sceneparsers",
    "PySide6/plugins/renderers",
    "PySide6/plugins/geometryloaders",
    "PySide6/plugins/assetimporters",
    "PySide6/plugins/renderplugins",
    "PySide6/qml",
    "PySide6/resources",
)


class BuildError(RuntimeError):
    """The bundle could not be built."""


def _load_i18n_script() -> ModuleType:
    """Import ``scripts/i18n.py`` by path (``scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location("cbrn_build_i18n_script", I18N_SCRIPT)
    if spec is None or spec.loader is None:
        raise BuildError(f"Cannot load {I18N_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_collect_licenses_script() -> ModuleType:
    """Import ``scripts/collect_licenses.py`` by path; it is registered in ``sys.modules`` first."""
    name = "cbrn_build_collect_licenses_script"
    spec = importlib.util.spec_from_file_location(name, COLLECT_LICENSES_SCRIPT)
    if spec is None or spec.loader is None:
        raise BuildError(f"Cannot load {COLLECT_LICENSES_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git_tracked_files(src_pkg: Path) -> list[Path] | None:
    """Return the files git tracks below ``src_pkg`` (relative to it), or ``None``.

    ``None`` means git is missing, ``src_pkg`` is not inside a git work tree, or git lists nothing
    there (for example a source tarball unpacked inside an unrelated repository).
    """
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=src_pkg,
            capture_output=True,
            check=True,
        )
        if inside.stdout.strip() != b"true":
            return None
        listing = subprocess.run(
            ["git", "ls-files", "-z", "--", "."],
            cwd=src_pkg,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    names = [os.fsdecode(item) for item in listing.stdout.split(b"\x00") if item]
    # A tracked file may be deleted in the working tree: it cannot be bundled, so skip it.
    tracked = [Path(name) for name in names if (src_pkg / name).is_file()]
    return tracked or None


def _walk_files(src_pkg: Path) -> list[Path]:
    """Return every file below ``src_pkg`` (relative to it), whatever git says about it."""
    return [path.relative_to(src_pkg) for path in src_pkg.rglob("*") if path.is_file()]


def _is_data_file_name(name: str) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in DATA_FILE_NAME_PATTERNS)


def _has_data_file_magic(path: Path) -> bool:
    longest = max(len(magic) for magic in DATA_FILE_MAGIC)
    with path.open("rb") as handle:
        head = handle.read(longest)
    return any(head.startswith(magic) for magic in DATA_FILE_MAGIC)


def _refuse_data_files(src_pkg: Path, candidates: Sequence[Path]) -> None:
    """Raise :class:`BuildError` when a candidate looks like user data (name or magic bytes)."""
    offenders = [
        relative.as_posix()
        for relative in candidates
        if _is_data_file_name(relative.name) or _has_data_file_magic(src_pkg / relative)
    ]
    if offenders:
        raise BuildError(
            f"Refusing to bundle what looks like data (database, backup, preferences, log): "
            f"{sorted(offenders)}. Remove these files from {src_pkg}."
        )


def package_data_with_source(src_pkg: Path) -> tuple[list[Path], str]:
    """Return ``(files, source)``: the package data files and where the list came from.

    ``source`` is ``"git"`` when ``src_pkg`` is in a git work tree (only tracked files are
    listed, so an untracked or ignored stray file is never bundled) and ``"filesystem"`` when git
    is unavailable (a source tarball): then every file is a candidate. In both cases the build is
    refused (:class:`BuildError`) when a candidate looks like a database, backup or other user
    data file (:data:`DATA_FILE_NAME_PATTERNS`, :data:`DATA_FILE_MAGIC`).
    """
    tracked = _git_tracked_files(src_pkg)
    source = "git" if tracked is not None else "filesystem"
    listed = tracked if tracked is not None else _walk_files(src_pkg)
    found: list[Path] = []
    for relative in listed:
        if any(part in EXCLUDED_DATA_DIRS for part in relative.parts[:-1]):
            continue
        if relative.suffix.lower() in EXCLUDED_DATA_SUFFIXES:
            continue
        found.append(relative)
    found.sort()
    _refuse_data_files(src_pkg, found)
    return found, source


def package_data_files(src_pkg: Path) -> list[Path]:
    """Return the data files of the package folder ``src_pkg``, relative to it, sorted.

    Every tracked file below ``src_pkg`` is data except sources, byte code, ``.ts`` catalogues and
    stale ``.qm`` files (see :data:`EXCLUDED_DATA_SUFFIXES`) and anything inside ``__pycache__``.
    The list is generic, so migrations, resources and help files are picked up with no script
    change. See :func:`package_data_with_source` for the git/filesystem rules.
    """
    return package_data_with_source(src_pkg)[0]


def build_timestamp_utc(environ: Mapping[str, str] | None = None) -> str:
    """Return the build time as ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, second precision).

    ``SOURCE_DATE_EPOCH`` (integer seconds since 1970) is honoured when set, so that a rebuild can
    be reproduced; otherwise the current UTC time is used.
    """
    variables = os.environ if environ is None else environ
    epoch = variables.get("SOURCE_DATE_EPOCH", "").strip()
    if epoch:
        try:
            seconds = int(epoch)
        except ValueError as error:
            raise BuildError(f"SOURCE_DATE_EPOCH is not an integer: {epoch!r}") from error
        moment = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    else:
        moment = datetime.now(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def write_build_info(work_dir: Path) -> Path:
    """Write ``build_info.json`` into ``work_dir`` (not the source tree) and return its path."""
    folder = work_dir / "build_info"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / BUILD_INFO_NAME
    document = {"built_at_utc": build_timestamp_utc()}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _add_data_argument(source: Path, destination: str) -> str:
    return f"--add-data={source}{os.pathsep}{destination}"


def _destination(relative_dir: Path) -> str:
    parts = [PACKAGE_NAME, *relative_dir.parts]
    return "/".join(parts)


def _write_launcher(work_dir: Path) -> Path:
    """Write the entry script of the frozen app (absolute imports work inside a frozen app)."""
    launcher_dir = work_dir / "launcher"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    launcher = launcher_dir / "cbrn_dashboard_launcher.py"
    launcher.write_text(
        "# SPDX-License-Identifier: GPL-3.0-or-later\n"
        "from cbrn_dashboard.app import main\n"
        "\n"
        "raise SystemExit(main())\n",
        encoding="utf-8",
    )
    return launcher


def pyinstaller_arguments(
    dist_dir: Path,
    work_dir: Path,
    qm_files: Sequence[Path],
    data_files: Sequence[Path] | None = None,
    build_info: Path | None = None,
) -> list[str]:
    """Return the PyInstaller command line (without the program name).

    ``data_files`` (relative to the package folder) defaults to :func:`package_data_files`;
    ``build_info`` is the generated ``build_info.json``, added to the package folder when given.
    """
    if data_files is None:
        data_files = package_data_files(PACKAGE_DIR)
    launcher = _write_launcher(work_dir)
    arguments = [
        "--onedir",
        "--windowed",
        "--noupx",
        "--noconfirm",
        "--clean",
        f"--name={APP_NAME}",
        f"--icon={ICON_PATH}",
        f"--distpath={dist_dir}",
        f"--workpath={work_dir / 'pyinstaller'}",
        f"--specpath={work_dir}",
        f"--paths={SRC_DIR}",
        f"--contents-directory={INTERNAL_DIR_NAME}",
        f"--collect-submodules={PACKAGE_NAME}",
    ]
    arguments.extend(f"--exclude-module={module}" for module in EXCLUDED_MODULES)
    for relative in data_files:
        destination = _destination(relative.parent)
        arguments.append(_add_data_argument(PACKAGE_DIR / relative, destination))
    if build_info is not None:
        arguments.append(_add_data_argument(build_info, PACKAGE_NAME))
    for qm_file in qm_files:
        arguments.append(_add_data_argument(qm_file, _destination(Path("i18n"))))
    arguments.append(str(launcher))
    return arguments


def _matches_unwanted_file(name: str) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, pattern.lower()) for pattern in UNWANTED_FILE_PATTERNS)


def prune_bundle(bundle: Path) -> int:
    """Delete the unwanted Qt files and folders from ``<bundle>/_internal``; return the count.

    The count is the number of files removed (files inside removed folders included).
    """
    internal = bundle / INTERNAL_DIR_NAME
    if not internal.is_dir():
        raise BuildError(f"No {INTERNAL_DIR_NAME} folder in {bundle}")
    removed = 0
    for relative in UNWANTED_PLUGIN_DIRS:
        folder = internal.joinpath(*relative.split("/"))
        if folder.is_dir():
            removed += sum(1 for item in folder.rglob("*") if item.is_file())
            shutil.rmtree(folder)
    for path in sorted(internal.rglob("*")):
        if path.is_file() and _matches_unwanted_file(path.name):
            path.unlink()
            removed += 1
    return removed


def bundle_size_bytes(bundle: Path) -> int:
    """Return the total size in bytes of all files below ``bundle``."""
    return sum(path.stat().st_size for path in bundle.rglob("*") if path.is_file())


def build(dist_dir: Path, work_dir: Path) -> Path:
    """Build the bundle into ``dist_dir`` using ``work_dir`` for scratch files.

    Returns the bundle folder ``<dist_dir>/cbrn-dashboard``. Raises :class:`BuildError` when the
    icon is missing or PyInstaller does not produce the executable.
    """
    if not ICON_PATH.is_file():
        raise BuildError(f"Missing icon {ICON_PATH}; run scripts/gen_icon.py first")
    dist_dir = dist_dir.resolve()
    work_dir = work_dir.resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    qm_dir = work_dir / "qm"
    shutil.rmtree(qm_dir, ignore_errors=True)
    qm_files = _load_i18n_script().compile_catalogues(qm_dir)

    data_files, data_source = package_data_with_source(PACKAGE_DIR)
    print(f"package data: {len(data_files)} file(s) from {data_source}")
    build_info = write_build_info(work_dir)
    arguments = pyinstaller_arguments(dist_dir, work_dir, qm_files, data_files, build_info)
    import PyInstaller.__main__ as pyinstaller_main

    pyinstaller_main.run(arguments)

    bundle = dist_dir / APP_NAME
    if not (bundle / f"{APP_NAME}.exe").is_file():
        raise BuildError(f"PyInstaller did not produce {bundle / (APP_NAME + '.exe')}")
    pruned = prune_bundle(bundle)
    licenses_dir = bundle / LICENSES_DIR_NAME
    license_entries = _load_collect_licenses_script().collect(licenses_dir, repo_root=REPO_ROOT)
    print(f"licenses: {len(license_entries)} component(s) in {licenses_dir}")
    megabytes = bundle_size_bytes(bundle) / (1024 * 1024)
    print(f"pruned {pruned} file(s)")
    print(f"bundle size: {megabytes:.1f} MB ({bundle})")
    return bundle


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        prog="build_exe.py", description="Build the one-folder bundle."
    )
    parser.add_argument("--dist-dir", type=Path, default=DEFAULT_DIST_DIR, help="output folder")
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR, help="scratch folder")
    args = parser.parse_args(argv)
    try:
        build(args.dist_dir, args.work_dir)
    except Exception as error:  # report any build failure as a clean exit code
        print(f"build failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
