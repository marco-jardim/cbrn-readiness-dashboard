# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the one-folder Windows bundle with PyInstaller (PLAN.md section 8, decision D01).

``python scripts/build_exe.py [--dist-dir DIR] [--work-dir DIR]``
    Compile the translation catalogues, run PyInstaller through its Python API (no committed
    ``.spec`` file: the spec is generated into the work folder), then delete the Qt libraries and
    plug-ins that only serve modules the application does not use. The result is the folder
    ``<dist-dir>/cbrn-dashboard`` holding ``cbrn-dashboard.exe`` and ``_internal/``.

The functions are importable (the packaging tests load this file by path, since ``scripts/`` is
not a package): :func:`build`, :func:`package_data_files`, :func:`prune_bundle` and the tables
:data:`UNWANTED_FILE_PATTERNS` / :data:`UNWANTED_PLUGIN_DIRS`.

``--exclude-module`` takes Python module names and can leave the Qt DLLs behind, hence the pruning
step. If the frozen self-test ever proves that a pruned DLL is a link-time dependency of a kept
one (``Qt6Network.dll`` is the usual suspect), drop its single line from the table below.
"""

import argparse
import fnmatch
import importlib.util
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
PACKAGE_NAME = "cbrn_dashboard"
PACKAGE_DIR = SRC_DIR / PACKAGE_NAME
ICON_PATH = PACKAGE_DIR / "resources" / "app.ico"
I18N_SCRIPT = REPO_ROOT / "scripts" / "i18n.py"

APP_NAME = "cbrn-dashboard"
INTERNAL_DIR_NAME = "_internal"
DEFAULT_DIST_DIR = REPO_ROOT / "dist"
DEFAULT_WORK_DIR = REPO_ROOT / "build"

#: Package files that are never shipped as data: sources (compiled into the archive), the
#: Linguist catalogues, byte code, and stale ``.qm`` files (the catalogues are compiled afresh).
EXCLUDED_DATA_SUFFIXES: frozenset[str] = frozenset({".ts", ".py", ".pyc", ".pyo", ".qm"})
EXCLUDED_DATA_DIRS: frozenset[str] = frozenset({"__pycache__"})

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


def package_data_files(src_pkg: Path) -> list[Path]:
    """Return the data files of the package folder ``src_pkg``, relative to it, sorted.

    Every file below ``src_pkg`` is data except sources, byte code, ``.ts`` catalogues and stale
    ``.qm`` files (see :data:`EXCLUDED_DATA_SUFFIXES`) and anything inside ``__pycache__``. The
    walk is generic, so migrations, resources and help files are picked up with no script change.
    """
    found: list[Path] = []
    for path in src_pkg.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(src_pkg)
        if any(part in EXCLUDED_DATA_DIRS for part in relative.parts[:-1]):
            continue
        if path.suffix.lower() in EXCLUDED_DATA_SUFFIXES:
            continue
        found.append(relative)
    return sorted(found)


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


def pyinstaller_arguments(dist_dir: Path, work_dir: Path, qm_files: Sequence[Path]) -> list[str]:
    """Return the PyInstaller command line (without the program name)."""
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
    for relative in package_data_files(PACKAGE_DIR):
        destination = _destination(relative.parent)
        arguments.append(_add_data_argument(PACKAGE_DIR / relative, destination))
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

    arguments = pyinstaller_arguments(dist_dir, work_dir, qm_files)
    import PyInstaller.__main__ as pyinstaller_main

    pyinstaller_main.run(arguments)

    bundle = dist_dir / APP_NAME
    if not (bundle / f"{APP_NAME}.exe").is_file():
        raise BuildError(f"PyInstaller did not produce {bundle / (APP_NAME + '.exe')}")
    pruned = prune_bundle(bundle)
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
