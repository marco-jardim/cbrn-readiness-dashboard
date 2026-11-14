# SPDX-License-Identifier: GPL-3.0-or-later
"""Download the pinned source archives of Qt and PySide6 for a release.

The zip and the installer bundle Qt and PySide6, which are licensed under LGPL-3.0. Every release
therefore carries the matching source archives, unmodified, next to the binaries. The list is
pinned in ``packaging/source-archives.json`` (name, version, URL, size, SHA-256 of each archive).

Usage (``.github/workflows/release.yml``, job ``package``)::

    uv run python scripts/fetch_source_archives.py --out release

Every archive is streamed to a temporary file in the output folder while its SHA-256 is computed,
checked against the pinned size and hash, and only then renamed to its final name (an atomic
rename, so a file with the final name is always a verified one). A network error is retried up to
three times; a size or hash mismatch is never retried: it fails with both values printed.

Only the standard library is used (``urllib``). The functions are importable (the tests load this
file by path, since ``scripts/`` is not a package, and drive them with a fake opener: no network).
"""

import argparse
import hashlib
import http.client
import json
import os
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from pathlib import Path
from typing import IO, NamedTuple, cast

REPO_ROOT = Path(__file__).resolve().parent.parent
PINS_PATH = REPO_ROOT / "packaging" / "source-archives.json"

USER_AGENT = "cbrn-readiness-dashboard-release/1 (source archives for the LGPL-3.0 obligations)"
TIMEOUT_SECONDS = 60.0
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5.0
CHUNK_SIZE = 1024 * 1024

_FIELDS = ("name", "version", "url", "size", "sha256")
_HEX = frozenset("0123456789abcdef")

#: Opens a request and returns the response as a context manager over a binary stream. The real
#: one is :func:`urlopen_with_timeout`; the tests pass a fake.
Opener = Callable[[urllib.request.Request, float], AbstractContextManager[IO[bytes]]]


class SourceArchive(NamedTuple):
    """One pinned source archive."""

    name: str
    version: str
    url: str
    size: int
    sha256: str

    @property
    def filename(self) -> str:
        """The file name of the archive: the last segment of its URL."""
        return self.url.rsplit("/", 1)[-1]


class ArchiveError(RuntimeError):
    """A downloaded or attached archive is not the pinned one (never retried)."""


def _fail_pin(index: int, message: str) -> ValueError:
    return ValueError(f"source-archives.json, entry {index}: {message}")


def parse_pins(data: object) -> list[SourceArchive]:
    """Validate the decoded JSON of the pin file and return its archives, in file order.

    Raise :class:`ValueError` on any deviation: a missing or unknown field, a wrong type, a URL
    that is not https, a SHA-256 that is not 64 lowercase hex digits, a size below 1, a file
    name that is empty or repeated.
    """
    if not isinstance(data, dict) or not isinstance(data.get("archives"), list):
        raise ValueError("source-archives.json must be an object with an 'archives' list")
    entries: list[object] = data["archives"]
    if not entries:
        raise ValueError("source-archives.json lists no archive")
    archives: list[SourceArchive] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise _fail_pin(index, "not an object")
        unexpected = sorted(set(entry) ^ set(_FIELDS))
        if unexpected:
            raise _fail_pin(index, f"fields must be exactly {_FIELDS}; differs: {unexpected}")
        for field in ("name", "version", "url", "sha256"):
            if not isinstance(entry[field], str) or not entry[field]:
                raise _fail_pin(index, f"{field} must be a non-empty string")
        size = entry["size"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise _fail_pin(index, "size must be an integer of at least 1")
        if not entry["url"].startswith("https://"):
            raise _fail_pin(index, "url must start with https://")
        digest = entry["sha256"]
        if len(digest) != 64 or not set(digest) <= _HEX:
            raise _fail_pin(index, "sha256 must be 64 lowercase hex digits")
        archive = SourceArchive(entry["name"], entry["version"], entry["url"], size, digest)
        filename = archive.filename
        if not filename or filename in {".", ".."} or "\\" in filename or ":" in filename:
            raise _fail_pin(index, f"the url does not end in a plain file name: {filename!r}")
        if filename in {other.filename for other in archives}:
            raise _fail_pin(index, f"file name {filename} is listed twice")
        archives.append(archive)
    return archives


def load_pins(path: Path = PINS_PATH) -> list[SourceArchive]:
    """Read and validate the pin file ``path``."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    return parse_pins(data)


def urlopen_with_timeout(
    request: urllib.request.Request, timeout: float
) -> AbstractContextManager[IO[bytes]]:
    """The real opener: ``urllib.request.urlopen`` with a timeout."""
    return cast(AbstractContextManager[IO[bytes]], urllib.request.urlopen(request, timeout=timeout))


def _size_error(archive: SourceArchive, actual: str) -> ArchiveError:
    return ArchiveError(
        f"{archive.filename}: size mismatch, expected {archive.size} bytes, got {actual}"
    )


def _hash_error(archive: SourceArchive, actual: str) -> ArchiveError:
    return ArchiveError(
        f"{archive.filename}: SHA-256 mismatch, expected {archive.sha256}, got {actual}"
    )


def _download_once(archive: SourceArchive, out_dir: Path, opener: Opener) -> Path:
    """Download ``archive`` once into ``out_dir`` and return the verified final path."""
    request = urllib.request.Request(archive.url, headers={"User-Agent": USER_AGENT})
    final = out_dir / archive.filename
    handle, temp_name = tempfile.mkstemp(dir=out_dir, prefix=archive.filename, suffix=".part")
    temp = Path(temp_name)
    try:
        digest = hashlib.sha256()
        total = 0
        with os.fdopen(handle, "wb") as target, opener(request, TIMEOUT_SECONDS) as response:
            for chunk in iter(lambda: response.read(CHUNK_SIZE), b""):
                total += len(chunk)
                if total > archive.size:
                    # Stop at once: a larger stream cannot be the pinned file.
                    raise _size_error(archive, f"more than {archive.size}")
                digest.update(chunk)
                target.write(chunk)
        if total != archive.size:
            raise _size_error(archive, f"{total} bytes")
        if digest.hexdigest() != archive.sha256:
            raise _hash_error(archive, digest.hexdigest())
        temp.replace(final)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return final


def download_archive(
    archive: SourceArchive,
    out_dir: Path,
    opener: Opener = urlopen_with_timeout,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Download one pinned archive into ``out_dir``, verified; return its path.

    A network error (``OSError``, which includes ``URLError``, ``HTTPError`` and timeouts, or an
    ``http.client.HTTPException`` such as a short read) is retried up to :data:`MAX_ATTEMPTS`
    times in all, with ``sleep`` between the attempts. A size or hash mismatch raises
    :class:`ArchiveError` at once.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return _download_once(archive, out_dir, opener)
        except (OSError, http.client.HTTPException) as error:
            print(
                f"{archive.filename}: attempt {attempt} of {MAX_ATTEMPTS} failed: {error}",
                file=sys.stderr,
            )
            if attempt == MAX_ATTEMPTS:
                raise ArchiveError(
                    f"{archive.filename}: download failed after {MAX_ATTEMPTS} attempts: {error}"
                ) from error
            sleep(RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")  # pragma: no cover


def fetch_all(
    archives: Sequence[SourceArchive],
    out_dir: Path,
    opener: Opener = urlopen_with_timeout,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Path]:
    """Download every archive of ``archives`` into ``out_dir``; return the paths in order."""
    paths: list[Path] = []
    for archive in archives:
        print(f"downloading {archive.name} {archive.version}: {archive.url}", flush=True)
        paths.append(download_archive(archive, out_dir, opener, sleep))
    return paths


def sha256_of(path: Path) -> str:
    """Return the lowercase hex SHA-256 of ``path``, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archives(archives: Sequence[SourceArchive], directory: Path) -> list[Path]:
    """Check that every pinned archive is in ``directory`` with the pinned size and SHA-256.

    Return the paths in the order of ``archives``. Raise :class:`ArchiveError` on a missing file
    or a mismatch. ``make_release_zip.py`` calls this before it lists the archives in
    ``SHA256SUMS.txt`` and in the release notes.
    """
    paths: list[Path] = []
    for archive in archives:
        path = directory / archive.filename
        if not path.is_file():
            raise ArchiveError(f"{archive.filename} is missing in {directory}")
        actual_size = path.stat().st_size
        if actual_size != archive.size:
            raise _size_error(archive, f"{actual_size} bytes")
        actual = sha256_of(path)
        if actual != archive.sha256:
            raise _hash_error(archive, actual)
        paths.append(path)
    return paths


def build_parser() -> argparse.ArgumentParser:
    """Return the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="fetch_source_archives.py",
        description="Download the pinned Qt and PySide6 source archives and verify them.",
    )
    parser.add_argument("--out", type=Path, required=True, help="folder to download into")
    parser.add_argument(
        "--pins", type=Path, default=PINS_PATH, help="the pin file (default: packaging/)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    args = build_parser().parse_args(argv)
    try:
        for path in fetch_all(load_pins(args.pins), args.out):
            print(path)
    except (ValueError, ArchiveError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
