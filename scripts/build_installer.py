# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the per-user Windows installer with Inno Setup 6 from the one-folder bundle.

``python scripts/build_installer.py --bundle-dir DIR [--out-dir DIR] [--version X.Y.Z]
[--iscc FILE] [--script FILE] [--verbose]``
    Run ``ISCC.exe`` on ``packaging/installer/cbrn-dashboard.iss`` with the version, the bundle
    folder, the output folder and the file name as ``/D`` defines, check that
    ``cbrn-readiness-dashboard-<version>-win-x64-setup.exe`` exists afterwards and print its path
    and size. The release workflow runs this on every version tag (the Inno Setup 6 compiler is
    preinstalled on the ``windows-2025`` image; nothing is downloaded); the packaging tests run it
    on every push to ``main``.

``ISCC.exe`` is looked up in this order (:func:`find_iscc`): ``--iscc``, the environment variable
``ISCC``, ``iscc`` on ``PATH``, then the standard places (Program Files (x86), Program Files, and
the per-user ``%LOCALAPPDATA%\\Programs\\Inno Setup 6``). The first source that is given must
point at a file; there is no fall-through after a wrong explicit path.

Only the standard library is used. The functions are importable (the tests load this file by
path, since ``scripts/`` is not a package); the pure helpers need no Inno Setup.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = REPO_ROOT / "src" / "cbrn_dashboard" / "__init__.py"
DEFAULT_SCRIPT = REPO_ROOT / "packaging" / "installer" / "cbrn-dashboard.iss"
DEFAULT_OUT_DIR = REPO_ROOT / "dist"

APP_EXE_NAME = "cbrn-dashboard.exe"
#: The setup file name without ``.exe``; ``{version}`` is the package version.
BASE_NAME_FORMAT = "cbrn-readiness-dashboard-{version}-win-x64-setup"
INSTALLER_SUFFIX = "-setup.exe"

ISCC_ENV_VARIABLE = "ISCC"
ISCC_FILE_NAME = "ISCC.exe"
INNO_FOLDER_NAME = "Inno Setup 6"

#: Characters allowed in a version: it goes into a ``/D`` define and into a file name.
_VERSION = re.compile(r"(?P<numbers>\d+\.\d+\.\d+)(?P<suffix>[A-Za-z0-9.+_-]*)")


class InstallerError(RuntimeError):
    """The installer could not be built."""


# --------------------------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------------------------


def check_version(version: str) -> str:
    """Return ``version`` when it is ``major.minor.patch`` plus a safe suffix; else raise."""
    if _VERSION.fullmatch(version) is None:
        raise InstallerError(f"Not a valid version: {version!r}")
    return version


def installer_base_name(version: str) -> str:
    """Return the setup file name without ``.exe`` for ``version``."""
    return BASE_NAME_FORMAT.format(version=check_version(version))


def installer_file_name(version: str) -> str:
    """Return the setup file name (with ``.exe``) for ``version``."""
    return installer_base_name(version) + ".exe"


def numeric_version(version: str) -> str:
    """Return ``major.minor.patch.0``: the version of the setup file resource."""
    match = _VERSION.fullmatch(version)
    if match is None:
        raise InstallerError(f"Not a valid version: {version!r}")
    return match.group("numbers") + ".0"


def standard_iscc_locations(environ: Mapping[str, str]) -> list[Path]:
    """Return the usual places of ``ISCC.exe``, in the order they are tried.

    Program Files (x86) first (the system-wide install of the GitHub runner image), then Program
    Files, then the per-user install. A variable that is not set is replaced by its usual value
    (the per-user place is left out when ``LOCALAPPDATA`` is not set).
    """
    program_files_x86 = environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    program_files = environ.get("ProgramFiles") or r"C:\Program Files"
    places = [
        Path(program_files_x86) / INNO_FOLDER_NAME / ISCC_FILE_NAME,
        Path(program_files) / INNO_FOLDER_NAME / ISCC_FILE_NAME,
    ]
    local = environ.get("LOCALAPPDATA")
    if local:
        places.append(Path(local) / "Programs" / INNO_FOLDER_NAME / ISCC_FILE_NAME)
    return places


def find_iscc(
    explicit: Path | None,
    environ: Mapping[str, str],
    which: Callable[[str], str | None],
    is_file: Callable[[Path], bool],
) -> Path:
    """Return the path of ``ISCC.exe``; raise :class:`InstallerError` when there is none.

    Order: ``explicit`` (``--iscc``), ``environ["ISCC"]``, ``which("iscc")``, then
    :func:`standard_iscc_locations`. An explicit path or an ``ISCC`` variable that is not a file
    is an error at once, so that a typo is not hidden by a different compiler found later.
    """
    if explicit is not None:
        if not is_file(explicit):
            raise InstallerError(f"--iscc is not a file: {explicit}")
        return explicit
    from_environment = environ.get(ISCC_ENV_VARIABLE, "").strip()
    if from_environment:
        if not is_file(Path(from_environment)):
            raise InstallerError(f"The variable ISCC is not a file: {from_environment}")
        return Path(from_environment)
    on_path = which("iscc")
    if on_path:
        return Path(on_path)
    places = standard_iscc_locations(environ)
    for place in places:
        if is_file(place):
            return place
    tried = "; ".join(str(place) for place in places)
    raise InstallerError(
        "Inno Setup 6 (ISCC.exe) was not found. Install it (it is preinstalled on the GitHub "
        f"windows-2025 image), or pass --iscc, or set ISCC. Tried: PATH; {tried}"
    )


def iscc_arguments(
    iscc: Path,
    script: Path,
    version: str,
    bundle_dir: Path,
    out_dir: Path,
    *,
    quiet: bool = True,
) -> list[str]:
    """Return the ISCC command line: the options first, the script last."""
    arguments = [str(iscc)]
    if quiet:
        arguments.append("/Q")
    arguments += [
        f"/DAppVersion={check_version(version)}",
        f"/DVersionInfoVersion={numeric_version(version)}",
        f"/DBundleDir={bundle_dir}",
        f"/DOutputDir={out_dir}",
        f"/DOutputBaseFilename={installer_base_name(version)}",
        str(script),
    ]
    return arguments


def read_package_version(init_file: Path = INIT_FILE) -> str:
    """Return ``__version__`` of the package, read as text (the package is not imported)."""
    text = init_file.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if match is None:
        raise InstallerError(f"No __version__ in {init_file}")
    return match.group(1)


def human_size(size: int) -> str:
    """Return ``size`` in bytes as megabytes with one decimal."""
    return f"{size / (1024 * 1024):.1f} MB"


# --------------------------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------------------------


def build_installer(
    bundle_dir: Path,
    out_dir: Path,
    version: str,
    iscc: Path,
    script: Path = DEFAULT_SCRIPT,
    *,
    quiet: bool = True,
) -> Path:
    """Run ISCC and return the path of the setup file; raise :class:`InstallerError` on failure.

    Paths are made absolute first: ISCC resolves the ones inside the script against the script's
    own folder.
    """
    bundle_dir = bundle_dir.resolve()
    out_dir = out_dir.resolve()
    if not (bundle_dir / APP_EXE_NAME).is_file():
        raise InstallerError(f"{APP_EXE_NAME} is not in the bundle folder {bundle_dir}")
    if not script.is_file():
        raise InstallerError(f"No installer script: {script}")
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = out_dir / installer_file_name(version)
    expected.unlink(missing_ok=True)
    arguments = iscc_arguments(iscc, script.resolve(), version, bundle_dir, out_dir, quiet=quiet)
    print("running:", " ".join(arguments), flush=True)
    try:
        result = subprocess.run(arguments, check=False)
    except OSError as error:
        raise InstallerError(f"Cannot run {iscc}: {error}") from error
    if result.returncode != 0:
        raise InstallerError(f"ISCC failed with exit code {result.returncode}")
    if not expected.is_file():
        raise InstallerError(f"ISCC finished but {expected} does not exist")
    return expected


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="build_installer.py", description="Build the Inno Setup installer."
    )
    parser.add_argument("--bundle-dir", type=Path, required=True, help="the one-folder bundle")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="output folder")
    parser.add_argument("--version", default=None, help="default: the package version")
    parser.add_argument("--iscc", type=Path, default=None, help="path of ISCC.exe")
    parser.add_argument("--script", type=Path, default=DEFAULT_SCRIPT, help="the .iss file")
    parser.add_argument("--verbose", action="store_true", help="do not pass /Q to ISCC")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    args = build_parser().parse_args(argv)
    try:
        version = args.version if args.version is not None else read_package_version()
        iscc = find_iscc(args.iscc, os.environ, shutil.which, Path.is_file)
        setup = build_installer(
            args.bundle_dir, args.out_dir, version, iscc, args.script, quiet=not args.verbose
        )
    except (InstallerError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(setup)
    print(f"size: {human_size(setup.stat().st_size)} ({setup.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
