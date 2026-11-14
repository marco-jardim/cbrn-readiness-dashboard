# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of ``scripts/fetch_source_archives.py`` and of the pin file, offline.

The downloads run against a fake opener: no network. The pin file is also tied here to the
installed PySide6 (so that upgrading PySide6 without new pins fails) and to the URL formats of
``scripts/make_release_zip.py``.
"""

from __future__ import annotations

import hashlib
import http.client
import importlib.util
import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "fetch_source_archives.py"
RELEASE_SCRIPT_PATH = ROOT / "scripts" / "make_release_zip.py"
PINS_PATH = ROOT / "packaging" / "source-archives.json"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load("cbrn_fetch_source_archives_script", SCRIPT_PATH)


@pytest.fixture(scope="module")
def release() -> ModuleType:
    return _load("cbrn_fetch_test_release_script", RELEASE_SCRIPT_PATH)


# --------------------------------------------------------------------------------------------
# A fake opener
# --------------------------------------------------------------------------------------------

CONTENT = b"fake source archive " * 100


class _Dropping(io.BytesIO):
    """A response that fails after its first chunk, like a connection that is reset."""

    def read(self, size: int | None = -1, /) -> bytes:
        if self.tell() >= 4:
            raise ConnectionResetError("reset by peer")
        return super().read(size)


class FakeOpener:
    """Serves one planned reply per call: bytes, a response object or an exception to raise."""

    def __init__(self, *plan: bytes | io.BytesIO | BaseException) -> None:
        self.plan = list(plan)
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> io.BytesIO:
        self.requests.append(request)
        self.timeouts.append(timeout)
        step = self.plan.pop(0)
        if isinstance(step, BaseException):
            raise step
        return io.BytesIO(step) if isinstance(step, bytes) else step


class Sleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _archive(script: ModuleType, content: bytes = CONTENT, name: str = "Qt") -> Any:
    return script.SourceArchive(
        name,
        "6.12.0",
        "https://download.example.invalid/dir/qt-everywhere-src-6.12.0.tar.xz",
        len(content),
        hashlib.sha256(content).hexdigest(),
    )


def _leftovers(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir() if path.suffix == ".part")


# --------------------------------------------------------------------------------------------
# download_archive
# --------------------------------------------------------------------------------------------


def test_download_writes_the_verified_file_under_its_final_name(
    script: ModuleType, tmp_path: Path
) -> None:
    archive = _archive(script)
    opener = FakeOpener(CONTENT)
    path = script.download_archive(archive, tmp_path / "out", opener, Sleeper())
    assert path == tmp_path / "out" / "qt-everywhere-src-6.12.0.tar.xz"
    assert path.read_bytes() == CONTENT
    assert [p.name for p in (tmp_path / "out").iterdir()] == [path.name]


def test_download_sends_a_user_agent_and_a_timeout(script: ModuleType, tmp_path: Path) -> None:
    opener = FakeOpener(CONTENT)
    script.download_archive(_archive(script), tmp_path, opener, Sleeper())
    (request,) = opener.requests
    assert request.full_url == _archive(script).url
    assert request.get_header("User-agent") == script.USER_AGENT
    assert script.USER_AGENT.isascii()
    assert opener.timeouts == [script.TIMEOUT_SECONDS]
    assert 0 < script.TIMEOUT_SECONDS <= 120


def test_download_streams_in_chunks(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "CHUNK_SIZE", 7)
    path = script.download_archive(_archive(script), tmp_path, FakeOpener(CONTENT), Sleeper())
    assert path.read_bytes() == CONTENT


def test_download_replaces_an_existing_file_of_the_same_name(
    script: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "qt-everywhere-src-6.12.0.tar.xz").write_bytes(b"stale")
    path = script.download_archive(_archive(script), tmp_path, FakeOpener(CONTENT), Sleeper())
    assert path.read_bytes() == CONTENT


def test_a_hash_mismatch_fails_with_both_values_and_is_not_retried(
    script: ModuleType, tmp_path: Path
) -> None:
    archive = _archive(script)
    wrong = b"X" * len(CONTENT)
    opener = FakeOpener(wrong, wrong, wrong)
    sleeper = Sleeper()
    with pytest.raises(script.ArchiveError) as caught:
        script.download_archive(archive, tmp_path, opener, sleeper)
    message = str(caught.value)
    assert "SHA-256 mismatch" in message
    assert archive.sha256 in message
    assert hashlib.sha256(wrong).hexdigest() in message
    assert len(opener.requests) == 1
    assert sleeper.delays == []
    assert list(tmp_path.iterdir()) == []  # no final file, no temporary file


@pytest.mark.parametrize("served", [CONTENT[:-1], CONTENT + b"x"], ids=["short", "long"])
def test_a_size_mismatch_fails_and_is_not_retried(
    script: ModuleType, tmp_path: Path, served: bytes
) -> None:
    opener = FakeOpener(served, served, served)
    with pytest.raises(script.ArchiveError, match="size mismatch") as caught:
        script.download_archive(_archive(script), tmp_path, opener, Sleeper())
    assert str(len(CONTENT)) in str(caught.value)
    assert len(opener.requests) == 1
    assert list(tmp_path.iterdir()) == []


def test_a_stream_larger_than_the_pin_is_cut_short(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "CHUNK_SIZE", 10)

    class Counting(io.BytesIO):
        """Remembers how much was read: the script closes the response when it stops."""

        consumed = 0

        def read(self, size: int | None = -1) -> bytes:
            data = super().read(size)
            Counting.consumed += len(data)
            return data

    response = Counting(CONTENT * 50)
    with pytest.raises(script.ArchiveError, match="more than"):
        script.download_archive(_archive(script), tmp_path, FakeOpener(response), Sleeper())
    assert Counting.consumed <= len(CONTENT) + 10  # not read to the end


def test_network_errors_are_retried_and_the_third_attempt_can_succeed(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    opener = FakeOpener(
        urllib.error.URLError("temporary failure"),
        TimeoutError("timed out"),
        CONTENT,
    )
    sleeper = Sleeper()
    path = script.download_archive(_archive(script), tmp_path, opener, sleeper)
    assert path.read_bytes() == CONTENT
    assert len(opener.requests) == 3
    assert sleeper.delays == [script.RETRY_DELAY_SECONDS] * 2
    err = capsys.readouterr().err
    assert "attempt 1 of 3 failed" in err
    assert "attempt 2 of 3 failed" in err
    assert _leftovers(tmp_path) == []


def test_http_errors_and_short_reads_are_retried_too(script: ModuleType, tmp_path: Path) -> None:
    http_error = urllib.error.HTTPError(
        "https://download.example.invalid/x", 503, "unavailable", http.client.HTTPMessage(), None
    )
    opener = FakeOpener(http_error, http.client.IncompleteRead(b"abc", 10), CONTENT)
    path = script.download_archive(_archive(script), tmp_path, opener, Sleeper())
    assert path.read_bytes() == CONTENT
    assert len(opener.requests) == 3


def test_a_connection_that_drops_mid_stream_is_retried_from_the_start(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "CHUNK_SIZE", 4)
    opener = FakeOpener(_Dropping(CONTENT), CONTENT)
    path = script.download_archive(_archive(script), tmp_path, opener, Sleeper())
    assert path.read_bytes() == CONTENT
    assert len(opener.requests) == 2
    assert _leftovers(tmp_path) == []


def test_three_failed_attempts_give_up_without_leaving_files(
    script: ModuleType, tmp_path: Path
) -> None:
    opener = FakeOpener(*[urllib.error.URLError("down")] * 3)
    sleeper = Sleeper()
    with pytest.raises(script.ArchiveError, match="after 3 attempts"):
        script.download_archive(_archive(script), tmp_path, opener, sleeper)
    assert len(opener.requests) == script.MAX_ATTEMPTS == 3
    assert len(sleeper.delays) == 2  # no pause after the last attempt
    assert list(tmp_path.iterdir()) == []


def test_fetch_all_downloads_every_archive_in_order(script: ModuleType, tmp_path: Path) -> None:
    other = b"second archive"
    first = _archive(script)
    second = script.SourceArchive(
        "PySide6",
        "6.12.0",
        "https://download.example.invalid/dir/pyside-setup-everywhere-src-6.12.0.tar.xz",
        len(other),
        hashlib.sha256(other).hexdigest(),
    )
    opener = FakeOpener(CONTENT, other)
    paths = script.fetch_all([first, second], tmp_path / "out", opener, Sleeper())
    assert [path.name for path in paths] == [first.filename, second.filename]
    assert [request.full_url for request in opener.requests] == [first.url, second.url]


# --------------------------------------------------------------------------------------------
# verify_archives
# --------------------------------------------------------------------------------------------


def test_verify_archives_accepts_the_pinned_files(script: ModuleType, tmp_path: Path) -> None:
    archive = _archive(script)
    (tmp_path / archive.filename).write_bytes(CONTENT)
    assert script.verify_archives([archive], tmp_path) == [tmp_path / archive.filename]


def test_verify_archives_refuses_a_missing_file(script: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(script.ArchiveError, match="missing"):
        script.verify_archives([_archive(script)], tmp_path)


def test_verify_archives_refuses_a_wrong_size_and_a_wrong_hash(
    script: ModuleType, tmp_path: Path
) -> None:
    archive = _archive(script)
    target = tmp_path / archive.filename
    target.write_bytes(CONTENT + b"x")
    with pytest.raises(script.ArchiveError, match="size mismatch"):
        script.verify_archives([archive], tmp_path)
    target.write_bytes(b"Y" * len(CONTENT))
    with pytest.raises(script.ArchiveError) as caught:
        script.verify_archives([archive], tmp_path)
    assert archive.sha256 in str(caught.value)
    assert hashlib.sha256(b"Y" * len(CONTENT)).hexdigest() in str(caught.value)


# --------------------------------------------------------------------------------------------
# The pin file format
# --------------------------------------------------------------------------------------------

GOOD_ENTRY: dict[str, Any] = {
    "name": "Qt",
    "version": "6.12.0",
    "url": "https://download.example.invalid/dir/qt.tar.xz",
    "size": 10,
    "sha256": "ab" * 32,
}


def _pins(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"archives": list(entries)}


def test_parse_pins_reads_entries_in_order(script: ModuleType) -> None:
    other = {**GOOD_ENTRY, "name": "PySide6", "url": "https://x.example.invalid/p.tar.xz"}
    archives = script.parse_pins(_pins(GOOD_ENTRY, other))
    assert [archive.name for archive in archives] == ["Qt", "PySide6"]
    assert archives[0].filename == "qt.tar.xz"
    assert archives[0].size == 10


@pytest.mark.parametrize(
    "bad",
    [
        [],
        {},
        {"archives": {}},
        {"archives": []},
        {"archives": ["text"]},
        {"archives": [{**GOOD_ENTRY, "extra": 1}]},
        {"archives": [{k: v for k, v in GOOD_ENTRY.items() if k != "size"}]},
        {"archives": [{**GOOD_ENTRY, "size": "10"}]},
        {"archives": [{**GOOD_ENTRY, "size": 0}]},
        {"archives": [{**GOOD_ENTRY, "size": True}]},
        {"archives": [{**GOOD_ENTRY, "name": ""}]},
        {"archives": [{**GOOD_ENTRY, "url": "http://download.example.invalid/qt.tar.xz"}]},
        {"archives": [{**GOOD_ENTRY, "url": "https://download.example.invalid/"}]},
        {"archives": [{**GOOD_ENTRY, "sha256": "AB" * 32}]},
        {"archives": [{**GOOD_ENTRY, "sha256": "ab" * 31}]},
        {"archives": [GOOD_ENTRY, GOOD_ENTRY]},
    ],
)
def test_parse_pins_refuses_a_malformed_file(script: ModuleType, bad: object) -> None:
    with pytest.raises(ValueError, match=r"source-archives\.json"):
        script.parse_pins(bad)


def test_load_pins_refuses_invalid_json(script: ModuleType, tmp_path: Path) -> None:
    broken = tmp_path / "pins.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        script.load_pins(broken)


# --------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------


def test_main_downloads_with_the_given_pins_and_prints_the_paths(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps(_pins(GOOD_ENTRY)), encoding="utf-8")
    seen: list[Any] = []

    def fake_fetch(archives: Any, out_dir: Path) -> list[Path]:
        seen.append((list(archives), out_dir))
        return [out_dir / "qt.tar.xz"]

    monkeypatch.setattr(script, "fetch_all", fake_fetch)
    assert script.main(["--out", str(tmp_path / "out"), "--pins", str(pins)]) == 0
    assert seen[0][0][0].name == "Qt"
    assert seen[0][1] == tmp_path / "out"
    assert capsys.readouterr().out.strip() == str(tmp_path / "out" / "qt.tar.xz")


def test_main_fails_with_exit_code_1_on_a_mismatch_or_bad_pins(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def failing(archives: Any, out_dir: Path) -> list[Path]:
        raise script.ArchiveError("qt.tar.xz: SHA-256 mismatch, expected a, got b")

    pins = tmp_path / "pins.json"
    pins.write_text(json.dumps(_pins(GOOD_ENTRY)), encoding="utf-8")
    monkeypatch.setattr(script, "fetch_all", failing)
    assert script.main(["--out", str(tmp_path), "--pins", str(pins)]) == 1
    assert "SHA-256 mismatch" in capsys.readouterr().err
    pins.write_text("[]", encoding="utf-8")
    assert script.main(["--out", str(tmp_path), "--pins", str(pins)]) == 1
    assert "source-archives.json" in capsys.readouterr().err


def test_the_scripts_are_ascii_and_fit_the_line_length() -> None:
    for path in (SCRIPT_PATH, RELEASE_SCRIPT_PATH):
        text = path.read_text(encoding="utf-8")
        assert text.isascii(), path.name
        assert max(len(line) for line in text.splitlines()) <= 100, path.name
    assert SCRIPT_PATH.read_text(encoding="utf-8").startswith(
        "# SPDX-License-Identifier: GPL-3.0-or-later\n"
    )


# --------------------------------------------------------------------------------------------
# The pin file in the repository
# --------------------------------------------------------------------------------------------


def test_the_pin_file_lists_qt_and_pyside6(script: ModuleType) -> None:
    archives = script.load_pins(PINS_PATH)
    assert [archive.name for archive in archives] == ["Qt", "PySide6"]
    for archive in archives:
        assert archive.size > 1_000_000
        assert archive.url.startswith("https://download.qt.io/official_releases/")
        assert archive.filename.endswith(".tar.xz")


def test_the_pinned_versions_are_the_installed_pyside6_and_qt(script: ModuleType) -> None:
    """Upgrading PySide6 without updating packaging/source-archives.json fails here."""
    pyside_module = importlib.import_module("PySide6")
    qt_core = importlib.import_module("PySide6.QtCore")
    qt, pyside = script.load_pins(PINS_PATH)
    assert pyside.version == pyside_module.__version__
    assert qt.version == qt_core.qVersion()
    assert qt.version == pyside.version  # the PySide6 wheels carry the Qt of the same version


def test_the_pinned_urls_are_built_from_the_url_formats_of_the_release_script(
    script: ModuleType, release: ModuleType
) -> None:
    qt, pyside = script.load_pins(PINS_PATH)
    assert qt.url == release.qt_source_url(qt.version)
    assert pyside.url == release.pyside_source_url(pyside.version)
    assert qt.filename == f"qt-everywhere-src-{qt.version}.tar.xz"
    assert pyside.filename == f"pyside-setup-everywhere-src-{pyside.version}.tar.xz"


def test_the_pin_file_is_the_one_the_release_script_reads(
    script: ModuleType, release: ModuleType
) -> None:
    from_release = release.load_source_archives()
    assert [tuple(archive) for archive in from_release] == [
        tuple(archive) for archive in script.load_pins(PINS_PATH)
    ]


def test_the_pin_file_is_valid_json_with_ascii_text() -> None:
    raw = PINS_PATH.read_bytes()
    assert raw.isascii()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\r" not in raw
    json.loads(raw)
