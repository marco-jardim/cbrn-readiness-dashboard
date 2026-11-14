# SPDX-License-Identifier: GPL-3.0-or-later
"""Package the one-folder bundle for a release (PLAN.md section 4.3 decision D10, section 8).

Sub-commands, all used by ``.github/workflows/release.yml``:

``check-tag --tag TAG``
    Fail unless ``TAG`` equals ``v`` + ``cbrn_dashboard.__version__``.
``package --bundle-dir DIR --out-dir DIR [--extra FILE ...] [--installer FILE]
[--source-archives-dir DIR]``
    Write ``cbrn-readiness-dashboard-<version>-win-x64.zip`` (top folder
    ``cbrn-readiness-dashboard/``), ``SHA256SUMS.txt`` and ``SHA256-FILES.txt``; print the paths.
    The three first-run notes and ``portable.ini.example`` from ``packaging/`` always go at the
    root of the top folder (and into ``SHA256-FILES.txt``); ``--extra`` adds more.
    ``--installer`` names the ``*-setup.exe`` that ``scripts/build_installer.py`` made: it is
    copied into ``--out-dir`` when it is elsewhere and gets its own line in ``SHA256SUMS.txt``
    (after the zip's); ``SHA256-FILES.txt`` stays about the bundle.
    ``--source-archives-dir`` names the folder where ``scripts/fetch_source_archives.py`` put the
    Qt and PySide6 source archives pinned in ``packaging/source-archives.json``: each one is
    checked against its pin, copied into ``--out-dir`` when it is elsewhere and gets a line in
    ``SHA256SUMS.txt`` (after the installer's). They are not part of the zip. This command is the
    only writer of ``SHA256SUMS.txt``.
``prerelease-flag``
    Print ``--prerelease`` when the current version is a prerelease (below 1.0.0, or with a
    pre/dev suffix), otherwise an empty line.
``print-version``
    Print ``cbrn_dashboard.__version__`` (the workflow passes it to the SignPath request).
``release-body --template FILE --out FILE --zip FILE [--installer FILE] [--signed]
[--source-archives-dir DIR]``
    Fill the release-notes template. ``--signed`` (given only when the workflow signed the
    executable through SignPath) swaps the "unsigned" section for the signed one.
    ``--installer`` keeps the "Installer" section of the template and fills it with the name and
    the SHA-256 of the setup file; without it the section is left out.
    ``--source-archives-dir`` keeps the "Source code of Qt and PySide6" section and fills it with
    the file names and the pinned SHA-256 of the archives found (and verified) in that folder;
    without it the section is left out.

The zip is reproducible: entries in a fixed order, a fixed timestamp, fixed attributes, a fixed
compression level, no extra fields. Two runs over the same file contents give identical bytes,
whatever the file times or the name of the bundle folder.

Only the standard library is used. The functions are importable (the tests load this file by
path, since ``scripts/`` is not a package).
"""

import argparse
import functools
import hashlib
import importlib
import importlib.util
import re
import shutil
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Protocol

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

PACKAGING_DIR = REPO_ROOT / "packaging"
#: The script that downloads the pinned source archives. It also owns the pin file schema
#: (``packaging/source-archives.json``), so this script loads it instead of parsing the file again.
FETCH_SCRIPT = REPO_ROOT / "scripts" / "fetch_source_archives.py"
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
#: The per-user installer built by ``scripts/build_installer.py``
#: (``cbrn-readiness-dashboard-<version>-win-x64-setup.exe``).
INSTALLER_SUFFIX = "-setup.exe"

#: ZIP cannot store dates before 1980; every entry gets this one.
FIXED_DATE_TIME: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0)
#: ``create_system`` 3 = Unix, so that ``external_attr`` below is read as a Unix mode.
FIXED_CREATE_SYSTEM = 3
#: Regular file, ``rw-r--r--``, in the high 16 bits of ``external_attr``.
FIXED_EXTERNAL_ATTR = 0o644 << 16
FIXED_COMPRESS_LEVEL = 9

# The two links below are the only places that know the layout of the upstream download sites;
# correct them here if a link ever breaks. The URLs in ``packaging/source-archives.json`` (what
# ``scripts/fetch_source_archives.py`` downloads) are pinned copies of what these formats give for
# the bundled version; a test fails when they differ or when the pinned version is not the
# installed PySide6 version.
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
#: The code signing policy of this project, as it is at the tag of the release.
POLICY_URL_FORMAT = (
    "https://github.com/marco-jardim/cbrn-readiness-dashboard/blob/v{version}/"
    "CODE-SIGNING-POLICY.md"
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

#: The release-notes template wraps its "the program is unsigned" section in these two lines
#: (HTML comments, invisible when rendered). The lines are removed from the notes; with
#: ``signed=True`` everything between them is replaced by :data:`SIGNED_NOTICE`.
SIGNING_START_MARKER = "<!-- signing-notice:start -->"
SIGNING_END_MARKER = "<!-- signing-notice:end -->"

#: The template wraps its "Installer" section in these two lines. Without an installer
#: (:func:`render_release_body` called with ``installer_name=None``) the lines and everything
#: between them are removed; with one, only the marker lines are removed and the tokens
#: ``{{installer_name}}`` and ``{{installer_sha256}}`` are filled.
INSTALLER_START_MARKER = "<!-- installer:start -->"
INSTALLER_END_MARKER = "<!-- installer:end -->"

#: The template wraps its "Source code of Qt and PySide6" section in these two lines. Without
#: source archives (:func:`render_release_body` called with ``source_archives=None``) the lines
#: and everything between them are removed; with them, only the marker lines are removed and the
#: token ``{{source_archives}}`` is filled with one bullet per archive.
SOURCE_ARCHIVES_START_MARKER = "<!-- source-archives:start -->"
SOURCE_ARCHIVES_END_MARKER = "<!-- source-archives:end -->"

#: What the release notes say when the executable was signed through SignPath. ``{{version}}`` is
#: filled like every other token. Only ``cbrn-dashboard.exe`` is signed; the third-party files of
#: the bundle are not.
SIGNED_NOTICE = """\
## The executable is signed

The executable (`cbrn-dashboard.exe`) is signed with an Authenticode certificate of the SignPath
Foundation. Free code signing provided by [SignPath.io](https://about.signpath.io), certificate
by [SignPath Foundation](https://signpath.org). Every release is approved by hand before it is
signed; see the [Code signing policy]({{policy_url}}).

Only `cbrn-dashboard.exe` is signed. The other files in the zip (Qt, Python, the Microsoft
runtime, `.dll` and `.pyd` files) are third-party files: this project does not sign them.

To check the signature, extract the zip, open the Properties of `cbrn-dashboard.exe` and look at
the Digital Signatures tab, or run in PowerShell:

```powershell
Get-AuthenticodeSignature .\\cbrn-readiness-dashboard\\cbrn-dashboard.exe
```

The status must be `Valid` and the signer certificate must be issued to "SignPath Foundation". A
valid signature shows who built the executable and that it was not changed afterwards. It does not
show that the program is safe or that its indicators are validated. Depending on how a computer
is set up, Microsoft Defender SmartScreen may still warn until the file has built a reputation,
and AppLocker or Windows Defender Application Control (WDAC) policies may still need an
administrator's decision.
"""


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


def write_sha256sums(
    zip_path: Path,
    out_dir: Path,
    installer_path: Path | None = None,
    source_archive_paths: Sequence[Path] = (),
) -> Path:
    """Write ``SHA256SUMS.txt`` (``sha256sum`` text format); return its path.

    One line for ``zip_path``, then one for the setup file ``installer_path`` when given, then
    one for each of ``source_archive_paths`` (the Qt and PySide6 source archives). The per-file
    manifest (``SHA256-FILES.txt``) stays about the bundle.
    """
    path = out_dir / SUMS_NAME
    lines = [f"{sha256_file(zip_path)}  {zip_path.name}\n"]
    extras = [installer_path] if installer_path is not None else []
    for extra in [*extras, *source_archive_paths]:
        if not extra.is_file():
            raise ValueError(f"Not a file: {extra}")
        lines.append(f"{sha256_file(extra)}  {extra.name}\n")
    _write_text(path, "".join(lines))
    return path


def place_installer(installer: Path, out_dir: Path) -> Path:
    """Return the setup file inside ``out_dir`` (copied there when it is somewhere else).

    Raise :class:`ValueError` when ``installer`` is not a ``*-setup.exe`` file.
    """
    if not installer.is_file():
        raise ValueError(f"Not a file: {installer}")
    if not installer.name.endswith(INSTALLER_SUFFIX):
        raise ValueError(f"The installer must be named *{INSTALLER_SUFFIX}: {installer.name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / installer.name
    if target.resolve() != installer.resolve():
        shutil.copyfile(installer, target)
    return target


class SourceArchiveLike(Protocol):
    """What this script needs from a pinned archive (``fetch_source_archives.SourceArchive``)."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def filename(self) -> str: ...

    @property
    def sha256(self) -> str: ...


@functools.cache
def _fetch_script() -> ModuleType:
    """Load ``scripts/fetch_source_archives.py`` by path (``scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location("cbrn_fetch_source_archives", FETCH_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {FETCH_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_source_archives(pins_path: Path | None = None) -> list[SourceArchiveLike]:
    """Return the pinned Qt and PySide6 source archives (``packaging/source-archives.json``)."""
    fetch = _fetch_script()
    pins: list[SourceArchiveLike] = fetch.load_pins(pins_path or fetch.PINS_PATH)
    return pins


def place_source_archives(
    archives: Sequence[SourceArchiveLike], directory: Path, out_dir: Path
) -> list[Path]:
    """Verify the pinned ``archives`` in ``directory``; return their paths inside ``out_dir``.

    Each file is checked against its pinned size and SHA-256 (``ArchiveError`` otherwise) and
    copied into ``out_dir`` when it is somewhere else.
    """
    paths: list[Path] = _fetch_script().verify_archives(archives, directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    placed: list[Path] = []
    for path in paths:
        target = out_dir / path.name
        if target.resolve() != path.resolve():
            shutil.copyfile(path, target)
        placed.append(target)
    return placed


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


def policy_url(version: str) -> str:
    """Return the link to the code signing policy of this project at the tag of ``version``."""
    return POLICY_URL_FORMAT.format(version=version)


def apply_signing_notice(template: str, *, signed: bool) -> str:
    """Resolve the signing section of ``template``, delimited by the two marker lines.

    Unsigned: only the marker lines are dropped, the section stays as written. Signed: the
    section is replaced by :data:`SIGNED_NOTICE`. Raise :class:`ValueError` when the markers are
    not exactly one start line followed by one end line.
    """
    lines = template.split("\n")
    starts = [index for index, line in enumerate(lines) if line.strip() == SIGNING_START_MARKER]
    ends = [index for index, line in enumerate(lines) if line.strip() == SIGNING_END_MARKER]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError(
            f"The template needs one {SIGNING_START_MARKER} line followed by one "
            f"{SIGNING_END_MARKER} line"
        )
    start, end = starts[0], ends[0]
    inner = SIGNED_NOTICE.rstrip("\n").split("\n") if signed else lines[start + 1 : end]
    return "\n".join([*lines[:start], *inner, *lines[end + 1 :]])


def _apply_optional_section(
    template: str, start_marker: str, end_marker: str, *, present: bool
) -> str:
    """Resolve an optional section of ``template``, delimited by two marker lines.

    Present: only the marker lines are dropped. Absent: the lines between them go as well. A
    template without any of the two markers is returned as it is. Raise :class:`ValueError`
    when the markers are not exactly one start line followed by one end line.
    """
    if start_marker not in template and end_marker not in template:
        return template
    lines = template.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == start_marker]
    ends = [i for i, line in enumerate(lines) if line.strip() == end_marker]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise ValueError(
            f"The template needs one {start_marker} line followed by one {end_marker} line"
        )
    start, end = starts[0], ends[0]
    inner = lines[start + 1 : end] if present else []
    return "\n".join([*lines[:start], *inner, *lines[end + 1 :]])


def apply_installer_section(template: str, *, present: bool) -> str:
    """Resolve the installer section of ``template`` (see :func:`_apply_optional_section`)."""
    return _apply_optional_section(
        template, INSTALLER_START_MARKER, INSTALLER_END_MARKER, present=present
    )


def apply_source_archives_section(template: str, *, present: bool) -> str:
    """Resolve the source-archives section (see :func:`_apply_optional_section`)."""
    return _apply_optional_section(
        template, SOURCE_ARCHIVES_START_MARKER, SOURCE_ARCHIVES_END_MARKER, present=present
    )


def source_archives_list(archives: Sequence[SourceArchiveLike]) -> str:
    """Return the markdown bullets that name each archive and give its pinned SHA-256."""
    return "\n".join(
        f"- `{archive.filename}` ({archive.name} {archive.version}), SHA-256: `{archive.sha256}`"
        for archive in archives
    )


def render_release_body(
    template: str,
    *,
    version: str,
    pyside_version: str,
    qt_version: str,
    zip_name: str,
    sha256: str,
    flagged_placeholders: Sequence[str],
    signed: bool = False,
    installer_name: str | None = None,
    installer_sha256: str | None = None,
    source_archives: Sequence[SourceArchiveLike] | None = None,
) -> str:
    """Fill the ``{{name}}`` tokens of ``template``; raise :class:`ValueError` on a leftover.

    The installer section is resolved first (see :func:`apply_installer_section`;
    ``installer_name`` and ``installer_sha256`` go together), then the source-archives section
    (kept and filled when ``source_archives`` is given, see
    :func:`apply_source_archives_section`). A template that has the signing markers is resolved
    next (see :func:`apply_signing_notice`); one without them is filled as it is, unless
    ``signed`` is true, which then raises :class:`ValueError`.
    """
    if (installer_name is None) != (installer_sha256 is None):
        raise ValueError("installer_name and installer_sha256 go together")
    flagged = ", ".join(f"`{name}`" for name in flagged_placeholders) or "none"
    template = apply_installer_section(template, present=installer_name is not None)
    template = apply_source_archives_section(template, present=source_archives is not None)
    if SIGNING_START_MARKER in template or SIGNING_END_MARKER in template or signed:
        template = apply_signing_notice(template, signed=signed)
    values = {
        "policy_url": policy_url(version),
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
    if installer_name is not None and installer_sha256 is not None:
        values["installer_name"] = installer_name
        values["installer_sha256"] = installer_sha256
    if source_archives is not None:
        values["source_archives"] = source_archives_list(source_archives)
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
    installer_path = None
    if args.installer is not None:
        installer_path = place_installer(args.installer, args.out_dir)
    archive_paths: list[Path] = []
    if args.source_archives_dir is not None:
        archive_paths = place_source_archives(
            load_source_archives(), args.source_archives_dir, args.out_dir
        )
    sums_path = write_sha256sums(zip_path, args.out_dir, installer_path, archive_paths)
    manifest_path = write_file_manifest(args.bundle_dir, args.out_dir, root_files)
    printed = [zip_path, sums_path, manifest_path]
    if installer_path is not None:
        printed.append(installer_path)
    printed.extend(archive_paths)
    for path in printed:
        print(path)
    return 0


def _command_prerelease_flag(_args: argparse.Namespace) -> int:
    print("--prerelease" if is_prerelease(read_version()) else "")
    return 0


def _command_print_version(_args: argparse.Namespace) -> int:
    print(read_version())
    return 0


def _command_release_body(args: argparse.Namespace) -> int:
    pyside_version, qt_version = read_qt_versions()
    installer_name: str | None = None
    installer_sha256: str | None = None
    if args.installer is not None:
        if not args.installer.is_file():
            raise ValueError(f"Not a file: {args.installer}")
        installer_name = args.installer.name
        installer_sha256 = sha256_file(args.installer)
    archives: list[SourceArchiveLike] | None = None
    if args.source_archives_dir is not None:
        archives = load_source_archives()
        _fetch_script().verify_archives(archives, args.source_archives_dir)
    body = render_release_body(
        args.template.read_text(encoding="utf-8"),
        version=read_version(),
        pyside_version=pyside_version,
        qt_version=qt_version,
        zip_name=args.zip.name,
        sha256=sha256_file(args.zip),
        flagged_placeholders=read_flagged_placeholders(),
        signed=args.signed,
        installer_name=installer_name,
        installer_sha256=installer_sha256,
        source_archives=archives,
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
    package.add_argument(
        "--installer",
        type=Path,
        default=None,
        help="the *-setup.exe made by build_installer.py: it goes into SHA256SUMS.txt too",
    )
    package.add_argument(
        "--source-archives-dir",
        type=Path,
        default=None,
        help="folder with the pinned Qt and PySide6 source archives: verified, listed in "
        "SHA256SUMS.txt and copied into --out-dir",
    )
    package.set_defaults(handler=_command_package)

    flag = commands.add_parser("prerelease-flag", help="print --prerelease below 1.0.0")
    flag.set_defaults(handler=_command_prerelease_flag)

    version = commands.add_parser("print-version", help="print the package version")
    version.set_defaults(handler=_command_print_version)

    body = commands.add_parser("release-body", help="fill the release-notes template")
    body.add_argument("--template", type=Path, required=True)
    body.add_argument("--out", type=Path, required=True)
    body.add_argument("--zip", type=Path, required=True)
    body.add_argument(
        "--installer",
        type=Path,
        default=None,
        help="the *-setup.exe of the release: the notes then have the Installer section",
    )
    body.add_argument(
        "--source-archives-dir",
        type=Path,
        default=None,
        help="folder with the pinned source archives: the notes then list them with their SHA-256",
    )
    body.add_argument(
        "--signed",
        action="store_true",
        help="say that the executable was signed (only when the signing step ran)",
    )
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
