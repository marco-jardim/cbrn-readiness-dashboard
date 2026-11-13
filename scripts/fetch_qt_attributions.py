# SPDX-License-Identifier: GPL-3.0-or-later
"""Fetch the third-party attribution texts of Qt for the licence bundle (PLAN.md T9.2, Q22).

Maintainer tool; it needs network access and is never run by the build or the tests.

``python scripts/fetch_qt_attributions.py [--qt-version X.Y.Z] [--out DIR]``
    Read the ``qt_attribution.json`` files of the Qt source repositories the bundle uses
    (:data:`QT_REPOS`) at the tag ``vX.Y.Z``, fetch the licence file (and copyright file) of every
    component they describe, and write two files into ``DIR`` (default
    ``packaging/licenses/qt-attributions``):

    * ``QT-THIRD-PARTY-NOTICES.txt``: one section per component (sorted by repository, then name)
      with its name, version, Qt repository and path, licence, copyright lines and licence text.
      A licence text identical to one printed earlier is given once and referred to afterwards.
      The header states the Qt version (``Qt version: X.Y.Z``) and the source tag; it carries no
      date, so the same input always gives the same file.
    * ``QT-THIRD-PARTY-NOTICES.sources.json``: every URL fetched and the SHA-256 of what came
      back, so the texts can be audited.

``scripts/collect_licenses.py`` copies the notices file into the bundle and refuses a file whose
Qt version is not the bundled one. Refresh after every PySide6 (Qt) upgrade and commit both files.

Only the standard library is used. The selection, parsing and rendering functions are pure (the
tests exercise them offline); only :func:`http_get` touches the network. The forbidden-API guard
covers ``src/cbrn_dashboard`` only, so this script may use ``urllib``.
"""

import argparse
import hashlib
import json
import posixpath
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = REPO_ROOT / "packaging" / "licenses" / "qt-attributions"
NOTICES_NAME = "QT-THIRD-PARTY-NOTICES.txt"
MANIFEST_NAME = "QT-THIRD-PARTY-NOTICES.sources.json"

#: The Qt repositories that hold the modules and plug-ins of the bundle (Qt6Core, Gui, Widgets,
#: OpenGL, OpenGLWidgets, Charts, Svg, VirtualKeyboard and the platform, style, image-format,
#: icon-engine, generic and input-context plug-ins).
QT_REPOS: tuple[str, ...] = ("qtbase", "qtsvg", "qtcharts", "qtimageformats", "qtvirtualkeyboard")

ATTRIBUTION_FILE_NAME = "qt_attribution.json"
#: Paths containing one of these folders (matched case-insensitively) are never attributions of
#: shipped code.
EXCLUDED_PATH_PARTS: tuple[str, ...] = (
    "/tests/",
    "/examples/",
    "/doc/",
    "/util/",
    "/coin/",
    "/cmake/",
)

API_TREE_URL = "https://api.github.com/repos/qt/{repo}/git/trees/{tag}?recursive=1"
RAW_URL = "https://raw.githubusercontent.com/qt/{repo}/{tag}/{path}"
USER_AGENT = "cbrn-dashboard-fetch-qt-attributions (licence bundle maintainer script)"
TIMEOUT_SECONDS = 60.0

NOTICES_TITLE = "Qt third-party notices"
QT_VERSION_LINE = re.compile(r"^Qt version: (\S+)[ \t]*$", re.MULTILINE)
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
RULE = "-" * 78
HEADER_SCAN_CHARS = 4000


class AttributionError(Exception):
    """The attributions cannot be fetched or understood."""


class FetchError(AttributionError):
    """A URL could not be fetched."""


class ParseError(AttributionError):
    """A fetched file is not what it should be."""


# --------------------------------------------------------------------------------------------
# Selection and parsing (pure)
# --------------------------------------------------------------------------------------------


def tag_for(version: str) -> str:
    """Return the Git tag of Qt ``version`` (``6.12.0`` gives ``v6.12.0``)."""
    if _VERSION.match(version) is None:
        raise AttributionError(f"Not a Qt version of the form X.Y.Z: {version!r}")
    return f"v{version}"


def tree_url(repo: str, tag: str) -> str:
    """Return the GitHub API URL that lists every file of ``repo`` at ``tag``."""
    return API_TREE_URL.format(repo=repo, tag=urllib.parse.quote(tag))


def raw_url(repo: str, tag: str, path: str) -> str:
    """Return the URL of the raw file ``path`` of ``repo`` at ``tag``."""
    return RAW_URL.format(repo=repo, tag=urllib.parse.quote(tag), path=urllib.parse.quote(path))


def is_attribution_path(path: str) -> bool:
    """Tell whether ``path`` is a ``qt_attribution.json`` outside the excluded folders."""
    lowered = "/" + path.lower()
    if posixpath.basename(lowered) != ATTRIBUTION_FILE_NAME:
        return False
    return not any(part in lowered for part in EXCLUDED_PATH_PARTS)


def select_attribution_paths(paths: Iterable[str]) -> list[str]:
    """Return the sorted, unique paths of ``paths`` that are wanted attribution files."""
    return sorted({path for path in paths if is_attribution_path(path)})


def parse_tree(text: str) -> list[str]:
    """Return the file paths of a GitHub ``git/trees`` response; a truncated tree is an error."""
    try:
        data = json.loads(text, strict=False)  # Qt files hold raw tabs and newlines
    except ValueError as error:
        raise ParseError(f"The tree listing is not JSON: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("tree"), list):
        raise ParseError("The tree listing has no 'tree' list")
    if data.get("truncated"):
        raise ParseError("The tree listing is truncated by GitHub; files would be missing")
    return [
        str(item["path"])
        for item in data["tree"]
        if isinstance(item, dict) and item.get("type") == "blob" and "path" in item
    ]


@dataclass(frozen=True)
class Attribution:
    """One component of a ``qt_attribution.json`` file (paths are relative to the repository)."""

    repo: str
    json_path: str
    id: str
    name: str
    version: str
    qt_module: str
    qt_usage: str
    paths: tuple[str, ...]
    license: str
    license_id: str
    license_files: tuple[str, ...]
    copyright: tuple[str, ...]
    copyright_file: str | None


def _string_list(value: object) -> tuple[str, ...]:
    """Return a JSON string-or-list value as a tuple of non-empty stripped strings."""
    if value is None:
        return ()
    items = value if isinstance(value, list) else [value]
    return tuple(text for text in (str(item).strip() for item in items) if text)


def resolve_repo_path(json_path: str, relative: str) -> str:
    """Return ``relative`` (relative to the folder of ``json_path``) as a repository path."""
    joined = posixpath.normpath(
        posixpath.join(posixpath.dirname(json_path), relative.replace("\\", "/"))
    )
    if joined == ".." or joined.startswith("../") or posixpath.isabs(joined):
        raise ParseError(f"{json_path}: {relative!r} leaves the repository")
    return joined


def parse_attribution(repo: str, json_path: str, text: str) -> list[Attribution]:
    """Parse the text of one ``qt_attribution.json`` (an object or a list of objects).

    ``LicenseFile`` and ``LicenseFiles`` (a string or a list each) are merged, in that order,
    without repeats; ``Copyright`` is a string or a list. File paths are resolved against the
    folder of the JSON file, so the result holds repository paths.
    """
    try:
        data = json.loads(text, strict=False)  # Qt files hold raw tabs and newlines
    except ValueError as error:
        raise ParseError(f"{repo}/{json_path} is not JSON: {error}") from error
    entries = data if isinstance(data, list) else [data]
    result: list[Attribution] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ParseError(f"{repo}/{json_path}: an entry is not a JSON object")
        files: list[str] = []
        for key in ("LicenseFile", "LicenseFiles"):
            for relative in _string_list(entry.get(key)):
                resolved = resolve_repo_path(json_path, relative)
                if resolved not in files:
                    files.append(resolved)
        copyright_files = _string_list(entry.get("CopyrightFile"))
        folder = posixpath.dirname(json_path) or "."
        component_paths = _string_list(entry.get("Path"))
        paths = tuple(resolve_repo_path(json_path, item) for item in component_paths)
        identifier = str(entry.get("Id", "")).strip()
        name = str(entry.get("Name", "")).strip() or identifier or folder
        result.append(
            Attribution(
                repo=repo,
                json_path=json_path,
                id=identifier,
                name=name,
                version=str(entry.get("Version", "")).strip(),
                qt_module=str(entry.get("QDocModule", "")).strip(),
                qt_usage=" ".join(str(entry.get("QtUsage", "")).split()),
                paths=paths or (folder,),
                license=str(entry.get("License", "")).strip(),
                license_id=str(entry.get("LicenseId", "")).strip(),
                license_files=tuple(files),
                copyright=_string_list(entry.get("Copyright")),
                copyright_file=(
                    resolve_repo_path(json_path, copyright_files[0]) if copyright_files else None
                ),
            )
        )
    return result


def sort_key(item: Attribution) -> tuple[str, str, str, str]:
    """Order of the sections: repository, then name, then (for ties) file and id."""
    return item.repo, item.name.lower(), item.json_path, item.id


# --------------------------------------------------------------------------------------------
# Rendering (pure)
# --------------------------------------------------------------------------------------------


def decode_bytes(raw: bytes) -> str:
    """Decode a fetched file: UTF-8 (a BOM is dropped), else Latin-1 (never fails)."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def normalize_text(text: str) -> str:
    """Return ``text`` with ``\\n`` line ends, no trailing blanks and no outer blank lines."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip("\n")


@dataclass(frozen=True)
class LicenceBlock:
    """A licence file of a component: its text, or the section that already printed the text."""

    path: str
    text: str
    same_as: int | None = None


def render_section(
    number: int,
    item: Attribution,
    blocks: Sequence[LicenceBlock],
    copyright_text: str = "",
) -> str:
    """Return the section of ``item``: its facts, copyright lines and licence text(s)."""
    location = ", ".join(f"{item.repo}/{path}" for path in item.paths)
    lines = [RULE, f"[{number}] {item.name}", RULE]
    lines.append(f"Version: {item.version or '-'}")
    lines.append(f"Qt repository and path: {location}")
    lines.append(f"Attribution file: {item.repo}/{item.json_path}")
    if item.qt_module:
        lines.append(f"Qt module: {item.qt_module}")
    if item.qt_usage:
        lines.append(f"Use in Qt: {item.qt_usage}")
    lines.append(f"License: {item.license or '-'}")
    lines.append(f"License id: {item.license_id or '-'}")
    copyright_lines = [
        line.strip() for entry in item.copyright for line in entry.splitlines() if line.strip()
    ]
    if copyright_lines or copyright_text:
        lines.append("Copyright:")
        lines.extend(f"  {line}" for line in copyright_lines)
        if copyright_text:
            lines.append(f"  (copyright notice file {item.repo}/{item.copyright_file}:)")
            lines.extend(f"  {line}" if line else "" for line in copyright_text.split("\n"))
    else:
        lines.append("Copyright: -")
    if not blocks:
        lines.append("")
        lines.append(
            "Licence text: Qt records no licence file for this component; the licence is the "
            "one named above."
        )
    for block in blocks:
        lines.append("")
        source = f"{item.repo}/{block.path}"
        if block.same_as is not None:
            lines.append(
                f"Licence text ({source}): identical to the text printed in section "
                f"[{block.same_as}]."
            )
        else:
            lines.append(f"Licence text ({source}):")
            lines.append("")
            lines.append(block.text if block.text else "(the file is empty)")
    return "\n".join(lines) + "\n"


def render_header(version: str, repos: Sequence[str], ordered: Sequence[Attribution]) -> str:
    """Return the header of the notices file, with the contents list."""
    tag = tag_for(version)
    lines = [
        NOTICES_TITLE,
        "=" * len(NOTICES_TITLE),
        "",
        f"Qt version: {version}",
        f"Source tag: {tag}",
        f"Qt source repositories: {', '.join(repos)}",
        f"Components: {len(ordered)}",
        "",
        "The Qt libraries that come with this application contain code of other projects, each",
        "under its own licence. This file holds the notice and licence text of every component",
        f"that Qt {version} documents in the qt_attribution.json files of the repositories above",
        f"(tag {tag}). It was generated by scripts/fetch_qt_attributions.py; the sources.json",
        "file beside it in the repository lists every URL read, with a SHA-256.",
        "Qt documents some components for platforms or tools that are not part of this",
        "application; they are listed too, so that none is missing. A licence text identical to",
        "one printed earlier is given once; the later section refers to it by number.",
        "",
        "Contents",
        "--------",
    ]
    lines.extend(
        f"[{number}] {item.repo}: {item.name}" + (f" {item.version}" if item.version else "")
        for number, item in enumerate(ordered, start=1)
    )
    return "\n".join(lines) + "\n"


def render_notices(
    version: str,
    attributions: Sequence[Attribution],
    files: Mapping[tuple[str, str], str],
    repos: Sequence[str] = QT_REPOS,
) -> str:
    """Return the whole notices file.

    ``files`` maps ``(repository, repository path)`` to the text of every licence and copyright
    file the attributions name. A missing file raises :class:`ParseError`.
    """
    ordered = sorted(attributions, key=sort_key)
    parts = [render_header(version, repos, ordered)]
    printed: dict[str, int] = {}
    for number, item in enumerate(ordered, start=1):
        blocks: list[LicenceBlock] = []
        for path in item.license_files:
            raw = files.get((item.repo, path))
            if raw is None:
                raise ParseError(f"No text fetched for {item.repo}/{path}")
            text = normalize_text(raw)
            first = printed.get(text)
            if first is None:
                printed[text] = number
                blocks.append(LicenceBlock(path, text))
            else:
                blocks.append(LicenceBlock(path, text, first))
        copyright_text = ""
        if item.copyright_file is not None:
            raw = files.get((item.repo, item.copyright_file))
            if raw is None:
                raise ParseError(f"No text fetched for {item.repo}/{item.copyright_file}")
            copyright_text = normalize_text(raw)
        parts.append(render_section(number, item, blocks, copyright_text))
    return "\n".join(parts)


def notices_qt_version(text: str) -> str | None:
    """Return the ``Qt version:`` stated in the header of a notices file, or ``None``."""
    match = QT_VERSION_LINE.search(text[:HEADER_SCAN_CHARS])
    return match.group(1) if match is not None else None


# --------------------------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------------------------

Getter = Callable[[str], bytes]


def http_get(url: str, *, timeout: float = TIMEOUT_SECONDS) -> bytes:
    """Return the body of ``url``; raise :class:`FetchError` on any HTTP or network error."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return bytes(response.read())
    except urllib.error.HTTPError as error:
        raise FetchError(f"HTTP {error.code} ({error.reason}) for {url}") from error
    except (urllib.error.URLError, OSError) as error:
        raise FetchError(f"Cannot fetch {url}: {error}") from error


class Recorder:
    """Wrap a getter: fetch each URL once and remember its SHA-256."""

    def __init__(self, get: Getter) -> None:
        self._get = get
        self._cache: dict[str, bytes] = {}
        self._hashes: dict[str, str] = {}

    def __call__(self, url: str) -> bytes:
        if url not in self._cache:
            body = self._get(url)
            self._cache[url] = body
            self._hashes[url] = hashlib.sha256(body).hexdigest()
        return self._cache[url]

    def entries(self) -> list[dict[str, str]]:
        """Return ``{"url", "sha256"}`` for every URL fetched, sorted by URL."""
        return [{"url": url, "sha256": self._hashes[url]} for url in sorted(self._hashes)]


@dataclass(frozen=True)
class Result:
    """What :func:`build` produced."""

    notices: str
    manifest: str
    components: int
    warnings: tuple[str, ...]


def build(version: str, get: Getter = http_get, repos: Sequence[str] = QT_REPOS) -> Result:
    """Fetch everything for Qt ``version`` through ``get`` and render both output files."""
    tag = tag_for(version)
    recorder = Recorder(get)
    attributions: list[Attribution] = []
    files: dict[tuple[str, str], str] = {}
    for repo in repos:
        tree = parse_tree(decode_bytes(recorder(tree_url(repo, tag))))
        for json_path in select_attribution_paths(tree):
            text = decode_bytes(recorder(raw_url(repo, tag, json_path)))
            for item in parse_attribution(repo, json_path, text):
                needed = list(item.license_files)
                if item.copyright_file is not None:
                    needed.append(item.copyright_file)
                for path in needed:
                    if (repo, path) not in files:
                        files[(repo, path)] = decode_bytes(recorder(raw_url(repo, tag, path)))
                attributions.append(item)
    if not attributions:
        raise ParseError(f"No qt_attribution.json found for Qt {version}")
    warnings = tuple(
        f"{item.repo}/{item.json_path}: {item.name} has no licence file"
        for item in sorted(attributions, key=sort_key)
        if not item.license_files
    )
    manifest = {
        "qt_version": version,
        "tag": tag,
        "repositories": list(repos),
        "files": recorder.entries(),
    }
    return Result(
        notices=render_notices(version, attributions, files, repos),
        manifest=json.dumps(manifest, indent=2) + "\n",
        components=len(attributions),
        warnings=warnings,
    )


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------


def installed_qt_version() -> str:
    """Return ``QtCore.qVersion()`` of the installed PySide6."""
    try:
        from PySide6 import QtCore
    except ImportError as error:
        raise AttributionError("PySide6 is not installed; pass --qt-version") from error
    return str(QtCore.qVersion())


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        prog="fetch_qt_attributions.py",
        description="Fetch the third-party attribution texts of Qt from its source repositories.",
    )
    parser.add_argument(
        "--qt-version",
        help="Qt version X.Y.Z (default: QtCore.qVersion() of the installed PySide6)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"output folder (default {DEFAULT_OUT_DIR})",
    )
    args = parser.parse_args(argv)
    try:
        version = args.qt_version or installed_qt_version()
        result = build(version, http_get)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / NOTICES_NAME).write_bytes(result.notices.encode("utf-8"))
        (args.out / MANIFEST_NAME).write_bytes(result.manifest.encode("utf-8"))
    except (AttributionError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"{result.components} component(s) of Qt {version} written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
