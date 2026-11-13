# SPDX-License-Identifier: GPL-3.0-or-later
"""Package the one-folder bundle for a release (PLAN.md section 4.3 decision D10, section 8).

Sub-commands, all used by ``.github/workflows/release.yml``:

``check-tag --tag TAG``
    Fail unless ``TAG`` equals ``v`` + ``cbrn_dashboard.__version__``.
``package --bundle-dir DIR --out-dir DIR [--extra FILE ...]``
    Write ``cbrn-readiness-dashboard-<version>-win-x64.zip`` (top folder
    ``cbrn-readiness-dashboard/``), ``SHA256SUMS.txt`` and ``SHA256-FILES.txt``; print the paths.
    The three first-run notes and ``portable.ini.example`` from ``packaging/`` always go at the
    root of the top folder (and into ``SHA256-FILES.txt``); ``--extra`` adds more.
``prerelease-flag``
    Print ``--prerelease`` when the current version is a prerelease (below 1.0.0, or with a
    pre/dev suffix), otherwise an empty line.
``release-body --template FILE --out FILE --zip FILE``
    Fill the release-notes template.

The zip is reproducible: entries in a fixed order, a fixed timestamp, fixed attributes, a fixed
compression level, no extra fields. Two runs over the same file contents give identical bytes,
whatever the file times or the name of the bundle folder.

Only the standard library is used. The functions are importable (the tests load this file by
path, since ``scripts/`` is not a package).
"""

import argparse
import hashlib
import importlib
import re
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

PACKAGING_DIR = REPO_ROOT / "packaging"
#: Files of ``packaging/`` that ``package`` puts at the root of the top folder (T9.4): the
#: first-run notes (the MVP mitigation for the unsigned executable) and the portable-mode example.
DEFAULT_ROOT_FILES: tuple[str, ...] = (
    "README-first-run.pt-BR.txt",
    "README-first-run.en-US.txt",
    "README-first-run.es-ES.txt",
    "portable.ini.example",
)

TOP_FOLDER = "cbrn-readiness-dashboard"
ZIP_NAME_FORMAT = "cbrn-readiness-dashboard-{version}-win-x64.zip"
SUMS_NAME = "SHA256SUMS.txt"
FILES_MANIFEST_NAME = "SHA256-FILES.txt"

#: ZIP cannot store dates before 1980; every entry gets this one.
FIXED_DATE_TIME: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0)
#: ``create_system`` 3 = Unix, so that ``external_attr`` below is read as a Unix mode.
FIXED_CREATE_SYSTEM = 3
#: Regular file, ``rw-r--r--``, in the high 16 bits of ``external_attr``.
FIXED_EXTERNAL_ATTR = 0o644 << 16
FIXED_COMPRESS_LEVEL = 9

# The two links below are the only places that know the layout of the upstream download sites;
# correct them here if a link ever breaks.
#: Qt source archive. ``{major_minor}`` is for example ``6.12``, ``{qt_version}`` is ``6.12.0``.
QT_SOURCE_URL_FORMAT = (
    "https://download.qt.io/official_releases/qt/{major_minor}/{qt_version}/single/"
    "qt-everywhere-src-{qt_version}.tar.xz"
)
#: PySide6 (Qt for Python) source archive.
PYSIDE_SOURCE_URL_FORMAT = (
    "https://download.qt.io/official_releases/QtForPython/pyside6/"
    "PySide6-{pyside_version}-src/pyside-setup-everywhere-src-{pyside_version}.tar.xz"
)
#: The tag of this project that matches the release.
PROJECT_SOURCE_URL_FORMAT = (
    "https://github.com/marco-jardim/cbrn-readiness-dashboard/tree/v{version}"
)

_VERSION = re.compile(
    r"""
    ^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)
    (?P<pre>[-_.]?(?:a|b|c|rc|alpha|beta|pre|preview)[-_.]?\d*)?
    (?P<post>[-_.]?post[-_.]?\d*)?
    (?P<dev>[-_.]?dev[-_.]?\d*)?
    (?:\+[A-Za-z0-9.]+)?$
    """,
    re.VERBOSE,
)
_TOKEN = re.compile(r"\{\{[^{}]*\}\}")


# --------------------------------------------------------------------------------------------
# Version and tag
# --------------------------------------------------------------------------------------------


def is_prerelease(version: str) -> bool:
    """Tell whether ``version`` is a prerelease: below 1.0.0, or with a pre/dev suffix.

    Raise :class:`ValueError` when ``version`` is not ``major.minor.patch`` with an optional
    PEP 440 suffix.
    """
    match = _VERSION.match(version)
    if match is None:
        raise ValueError(f"Not a valid version: {version!r}")
    if int(match.group("major")) < 1:
        return True
    return match.group("pre") is not None or match.group("dev") is not None


def expected_tag(version: str) -> str:
    """Return the git tag that releases ``version``: ``v`` + ``version``."""
    return f"v{version}"


def check_tag(tag: str, version: str) -> None:
    """Raise :class:`ValueError` unless ``tag`` is exactly ``v`` + ``version``."""
    wanted = expected_tag(version)
    if tag != wanted:
        raise ValueError(
            f"The tag {tag!r} does not match the package version {version!r}; "
            f"expected the tag {wanted!r}. Fix __version__ or tag again."
        )


# --------------------------------------------------------------------------------------------
# Zip and checksums
# --------------------------------------------------------------------------------------------


def zip_file_name(version: str) -> str:
    """Return the name of the release zip for ``version``."""
    return ZIP_NAME_FORMAT.format(version=version)


def bundle_file_paths(bundle_dir: Path) -> list[tuple[str, Path]]:
    """Return ``(posix relative path, file)`` for every file below ``bundle_dir``, sorted.

    The order is the ordinal (code point, case-sensitive) order of the POSIX relative path.
    Directories are not listed.
    """
    if not bundle_dir.is_dir():
        raise ValueError(f"Not a folder: {bundle_dir}")
    found = [
        (path.relative_to(bundle_dir).as_posix(), path)
        for path in bundle_dir.rglob("*")
        if path.is_file()
    ]
    return sorted(found, key=lambda item: item[0])


def sha256_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 of the file ``path`` (read in chunks)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_zip(
    bundle_dir: Path,
    out_dir: Path,
    version: str,
    extra_root_files: Sequence[Path] = (),
) -> Path:
    """Write the reproducible release zip into ``out_dir`` and return its path.

    The content of ``bundle_dir`` goes under ``cbrn-readiness-dashboard/`` whatever the folder is
    called; each of ``extra_root_files`` goes at the root of that top folder.
    """
    entries: dict[str, Path] = {}
    for relative, path in bundle_file_paths(bundle_dir):
        entries[f"{TOP_FOLDER}/{relative}"] = path
    for extra in extra_root_files:
        if not extra.is_file():
            raise ValueError(f"Not a file: {extra}")
        arcname = f"{TOP_FOLDER}/{extra.name}"
        if arcname in entries:
            raise ValueError(f"{arcname} would be stored twice")
        entries[arcname] = extra

    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / zip_file_name(version)
    with zipfile.ZipFile(
        zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=FIXED_COMPRESS_LEVEL
    ) as archive:
        for arcname in sorted(entries):
            info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE_TIME)
            info.create_system = FIXED_CREATE_SYSTEM
            info.external_attr = FIXED_EXTERNAL_ATTR
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                info,
                entries[arcname].read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=FIXED_COMPRESS_LEVEL,
            )
    return zip_path


def _write_text(path: Path, text: str) -> None:
    """Write ``text`` as UTF-8 with ``\\n`` line ends on every platform."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def write_sha256sums(zip_path: Path, out_dir: Path) -> Path:
    """Write ``SHA256SUMS.txt`` (``sha256sum`` text format) for ``zip_path``; return its path."""
    path = out_dir / SUMS_NAME
    _write_text(path, f"{sha256_file(zip_path)}  {zip_path.name}\n")
    return path


def default_root_files(packaging_dir: Path = PACKAGING_DIR) -> list[Path]:
    """Return the :data:`DEFAULT_ROOT_FILES` in ``packaging_dir``; raise if one is missing."""
    paths = [packaging_dir / name for name in DEFAULT_ROOT_FILES]
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise ValueError(f"Missing in {packaging_dir}: {', '.join(missing)}")
    return paths


def write_file_manifest(
    bundle_dir: Path, out_dir: Path, extra_root_files: Sequence[Path] = ()
) -> Path:
    """Write ``SHA256-FILES.txt``: one line per file of the top folder, to verify each file.

    The lines are flat SHA-256 file hashes (what ``Get-FileHash`` prints); they are not rules of
    any allow-listing product.

    ``extra_root_files`` (the first-run notes and the portable-mode example) are listed too: they
    are files a user receives inside the folder. Lines are sorted by the POSIX relative path.
    """
    hashed: dict[str, Path] = dict(bundle_file_paths(bundle_dir))
    for extra in extra_root_files:
        if not extra.is_file():
            raise ValueError(f"Not a file: {extra}")
        if extra.name in hashed:
            raise ValueError(f"{TOP_FOLDER}/{extra.name} would be listed twice")
        hashed[extra.name] = extra
    lines = [f"{sha256_file(hashed[name])}  {TOP_FOLDER}/{name}\n" for name in sorted(hashed)]
    path = out_dir / FILES_MANIFEST_NAME
    _write_text(path, "".join(lines))
    return path


# --------------------------------------------------------------------------------------------
# Release notes
# --------------------------------------------------------------------------------------------


def qt_source_url(qt_version: str) -> str:
    """Return the link to the Qt source archive of ``qt_version``."""
    major_minor = ".".join(qt_version.split(".")[:2])
    return QT_SOURCE_URL_FORMAT.format(major_minor=major_minor, qt_version=qt_version)


def pyside_source_url(pyside_version: str) -> str:
    """Return the link to the PySide6 source archive of ``pyside_version``."""
    return PYSIDE_SOURCE_URL_FORMAT.format(pyside_version=pyside_version)


def project_source_url(version: str) -> str:
    """Return the link to the source tag of this project for ``version``."""
    return PROJECT_SOURCE_URL_FORMAT.format(version=version)


def render_release_body(
    template: str,
    *,
    version: str,
    pyside_version: str,
    qt_version: str,
    zip_name: str,
    sha256: str,
    flagged_placeholders: Sequence[str],
) -> str:
    """Fill the ``{{name}}`` tokens of ``template``; raise :class:`ValueError` on a leftover."""
    flagged = ", ".join(f"`{name}`" for name in flagged_placeholders) or "none"
    values = {
        "version": version,
        "pyside_version": pyside_version,
        "qt_version": qt_version,
        "zip_name": zip_name,
        "sha256": sha256,
        "flagged_placeholders": flagged,
        "source_tag_url": project_source_url(version),
        "qt_source_url": qt_source_url(qt_version),
        "pyside_source_url": pyside_source_url(pyside_version),
    }
    body = template
    for name, value in values.items():
        body = body.replace("{{" + name + "}}", value)
    leftovers = sorted(set(_TOKEN.findall(body)))
    if leftovers:
        raise ValueError(f"Unreplaced tokens in the release body: {', '.join(leftovers)}")
    return body


# --------------------------------------------------------------------------------------------
# Inputs read from the installed project (imported lazily)
# --------------------------------------------------------------------------------------------


def read_version() -> str:
    """Return ``cbrn_dashboard.__version__``."""
    try:
        package = importlib.import_module("cbrn_dashboard")
    except ImportError:
        sys.path.insert(0, str(SRC_DIR))
        package = importlib.import_module("cbrn_dashboard")
    return str(package.__version__)


def read_qt_versions() -> tuple[str, str]:
    """Return ``(PySide6 version, Qt version)`` of the installed PySide6."""
    pyside = importlib.import_module("PySide6")
    qt_core = importlib.import_module("PySide6.QtCore")
    return str(pyside.__version__), str(qt_core.qVersion())


def read_flagged_placeholders() -> list[str]:
    """Return the ids of the placeholders still flagged (``flagged_placeholder_ids``, T1.5).

    Fails loudly when the function cannot be imported: an empty list would claim "none".
    """
    try:
        config = importlib.import_module("cbrn_dashboard.domain.config")
        function = config.flagged_placeholder_ids
    except (ImportError, AttributeError) as error:
        raise RuntimeError(
            f"Cannot read the flagged placeholders from cbrn_dashboard.domain.config: {error}"
        ) from error
    return [str(name) for name in function()]


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------


def _command_check_tag(args: argparse.Namespace) -> int:
    check_tag(args.tag, read_version())
    print(f"tag {args.tag} matches the package version")
    return 0


def _command_package(args: argparse.Namespace) -> int:
    version = read_version()
    root_files = [*default_root_files(), *args.extra]
    zip_path = make_zip(args.bundle_dir, args.out_dir, version, root_files)
    sums_path = write_sha256sums(zip_path, args.out_dir)
    manifest_path = write_file_manifest(args.bundle_dir, args.out_dir, root_files)
    for path in (zip_path, sums_path, manifest_path):
        print(path)
    return 0


def _command_prerelease_flag(_args: argparse.Namespace) -> int:
    print("--prerelease" if is_prerelease(read_version()) else "")
    return 0


def _command_release_body(args: argparse.Namespace) -> int:
    pyside_version, qt_version = read_qt_versions()
    body = render_release_body(
        args.template.read_text(encoding="utf-8"),
        version=read_version(),
        pyside_version=pyside_version,
        qt_version=qt_version,
        zip_name=args.zip.name,
        sha256=sha256_file(args.zip),
        flagged_placeholders=read_flagged_placeholders(),
    )
    _write_text(args.out, body)
    print(args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="make_release_zip.py", description="Package the bundle for a release."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check-tag", help="fail unless the tag is v<version>")
    check.add_argument("--tag", required=True)
    check.set_defaults(handler=_command_check_tag)

    package = commands.add_parser("package", help="write the zip and the checksum files")
    package.add_argument("--bundle-dir", type=Path, required=True)
    package.add_argument("--out-dir", type=Path, required=True)
    package.add_argument("--extra", type=Path, action="append", default=[])
    package.set_defaults(handler=_command_package)

    flag = commands.add_parser("prerelease-flag", help="print --prerelease below 1.0.0")
    flag.set_defaults(handler=_command_prerelease_flag)

    body = commands.add_parser("release-body", help="fill the release-notes template")
    body.add_argument("--template", type=Path, required=True)
    body.add_argument("--out", type=Path, required=True)
    body.add_argument("--zip", type=Path, required=True)
    body.set_defaults(handler=_command_release_body)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (ValueError, RuntimeError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
