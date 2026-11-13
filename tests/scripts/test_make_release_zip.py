# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of ``scripts/make_release_zip.py`` (T9.3) on a fake bundle folder: no build needed."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "make_release_zip.py"
TEMPLATE_PATH = ROOT / ".github" / "release-body.template.md"

TOP = "cbrn-readiness-dashboard"
UMLAUT_NAME = "\u00dcn\u00efcode.txt"

#: Contents of the fake bundle: POSIX relative path -> bytes.
FAKE_FILES: dict[str, bytes] = {
    "cbrn-dashboard.exe": b"MZ fake executable",
    "_internal/x.dll": b"fake dll " * 1000,
    "_internal/pkg/y.pyd": b"fake pyd",
    "_internal/alpha.txt": b"alpha",
    "_internal/Zeta.txt": b"zeta",
    f"_internal/{UMLAUT_NAME}": b"non-ascii name",
    "_internal/empty.bin": b"",
}

#: Ordinal, case-sensitive order of ``FAKE_FILES`` ("Z" < "a", non-ASCII last).
EXPECTED_ORDER: list[str] = [
    "_internal/Zeta.txt",
    "_internal/alpha.txt",
    "_internal/empty.bin",
    "_internal/pkg/y.pyd",
    "_internal/x.dll",
    f"_internal/{UMLAUT_NAME}",
    "cbrn-dashboard.exe",
]

FIXED_DATE = (1980, 1, 1, 0, 0, 0)


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cbrn_make_release_zip_script", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_bundle(folder: Path) -> Path:
    for relative, content in FAKE_FILES.items():
        path = folder.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return folder


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    return _make_bundle(tmp_path / "in" / "cbrn-dashboard")


def test_fake_bundle_order_is_what_the_tests_expect() -> None:
    assert sorted(FAKE_FILES) == EXPECTED_ORDER


# --------------------------------------------------------------------------------------------
# The zip
# --------------------------------------------------------------------------------------------


def test_zip_has_the_expected_name_and_entries_in_sorted_order(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    zip_path = script.make_zip(bundle, tmp_path / "out", "0.1.0")
    assert zip_path.name == "cbrn-readiness-dashboard-0.1.0-win-x64.zip"
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.namelist() == [f"{TOP}/{name}" for name in EXPECTED_ORDER]
        assert archive.testzip() is None
        for relative, content in FAKE_FILES.items():
            assert archive.read(f"{TOP}/{relative}") == content


def test_zip_has_a_single_top_folder_and_no_directory_entries(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    zip_path = script.make_zip(bundle, tmp_path / "out", "0.1.0")
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert {name.split("/")[0] for name in names} == {TOP}
    assert not [name for name in names if name.endswith("/")]
    assert not [name for name in names if "\\" in name]


def test_zip_entries_have_fixed_metadata(script: ModuleType, bundle: Path, tmp_path: Path) -> None:
    zip_path = script.make_zip(bundle, tmp_path / "out", "0.1.0")
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
    assert infos
    for info in infos:
        assert info.date_time == FIXED_DATE, info.filename
        assert info.create_system == 3, info.filename
        assert info.external_attr == 0o644 << 16, info.filename
        assert info.compress_type == zipfile.ZIP_DEFLATED, info.filename
        assert info.extra == b"", info.filename
        assert info.comment == b"", info.filename


def test_extra_root_files_land_at_the_top_folder_root(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    notes = tmp_path / "FIRST-RUN.txt"
    notes.write_bytes(b"notes")
    sample = tmp_path / "portable.ini.example"
    sample.write_bytes(b"[portable]\n")
    zip_path = script.make_zip(bundle, tmp_path / "out", "0.1.0", [notes, sample])
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        assert archive.read(f"{TOP}/FIRST-RUN.txt") == b"notes"
        assert archive.read(f"{TOP}/portable.ini.example") == b"[portable]\n"
    assert names == sorted(names)
    assert len(names) == len(FAKE_FILES) + 2


def test_extra_file_that_collides_with_a_bundle_file_is_refused(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    clash = tmp_path / "cbrn-dashboard.exe"
    clash.write_bytes(b"other")
    with pytest.raises(ValueError, match="twice"):
        script.make_zip(bundle, tmp_path / "out", "0.1.0", [clash])
    with pytest.raises(ValueError, match="Not a file"):
        script.make_zip(bundle, tmp_path / "out", "0.1.0", [tmp_path / "missing.txt"])


def test_make_zip_refuses_a_missing_bundle_folder(script: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Not a folder"):
        script.make_zip(tmp_path / "nope", tmp_path / "out", "0.1.0")


def test_two_runs_give_byte_identical_zips(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    first = script.make_zip(bundle, tmp_path / "out1", "0.1.0")
    second = script.make_zip(bundle, tmp_path / "out2", "0.1.0")
    assert first.read_bytes() == second.read_bytes()


def test_zip_is_identical_after_touching_mtimes_and_renaming_the_bundle_folder(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    first = script.make_zip(bundle, tmp_path / "out1", "0.1.0")

    copy = tmp_path / "elsewhere" / "some-other-folder-name"
    shutil.copytree(bundle, copy)
    for index, path in enumerate(sorted(copy.rglob("*"))):
        if path.is_file():
            stamp = 1_700_000_000 + index * 12_345
            os.utime(path, (stamp, stamp))
    second = script.make_zip(copy, tmp_path / "out2", "0.1.0")

    assert first.read_bytes() == second.read_bytes()


def test_zip_changes_when_a_file_changes(script: ModuleType, bundle: Path, tmp_path: Path) -> None:
    first = script.make_zip(bundle, tmp_path / "out1", "0.1.0")
    (bundle / "_internal" / "alpha.txt").write_bytes(b"changed")
    second = script.make_zip(bundle, tmp_path / "out2", "0.1.0")
    assert first.read_bytes() != second.read_bytes()


# --------------------------------------------------------------------------------------------
# Checksum files
# --------------------------------------------------------------------------------------------


def test_sha256_file_matches_hashlib(script: ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "big.bin"
    content = b"0123456789abcdef" * 200_000  # larger than one read chunk
    path.write_bytes(content)
    assert script.sha256_file(path) == hashlib.sha256(content).hexdigest()


def test_sha256sums_has_exactly_one_sha256sum_format_line(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    zip_path = script.make_zip(bundle, out, "0.1.0")
    sums = script.write_sha256sums(zip_path, out)
    assert sums.name == "SHA256SUMS.txt"
    raw = sums.read_bytes()
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert raw == f"{digest}  {zip_path.name}\n".encode()
    assert b"\r" not in raw
    (line,) = raw.decode("ascii").splitlines()
    checksum, name = line.split("  ")
    assert checksum == checksum.lower()
    assert len(checksum) == 64
    assert name == "cbrn-readiness-dashboard-0.1.0-win-x64.zip"


def test_file_manifest_lists_every_bundle_file_with_its_hash_sorted(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    manifest = script.write_file_manifest(bundle, out)
    assert manifest.name == "SHA256-FILES.txt"
    raw = manifest.read_bytes()
    assert b"\r" not in raw
    digests = {name: hashlib.sha256(content).hexdigest() for name, content in FAKE_FILES.items()}
    expected = "".join(f"{digests[name]}  {TOP}/{name}\n" for name in EXPECTED_ORDER)
    assert raw.decode("utf-8") == expected
    text = raw.decode("utf-8")
    assert ".dll" in text
    assert ".pyd" in text


def test_file_manifest_is_identical_on_two_runs(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    first = script.write_file_manifest(bundle, tmp_path / "out1")
    for path in bundle.rglob("*"):
        if path.is_file():
            os.utime(path, (1_600_000_000, 1_600_000_000))
    second = script.write_file_manifest(bundle, tmp_path / "out2")
    assert first.read_bytes() == second.read_bytes()


# --------------------------------------------------------------------------------------------
# Version and tag
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.0.1", True),
        ("0.1.0", True),
        ("0.9.9", True),
        ("1.0.0", False),
        ("1.2.3", False),
        ("10.0.0", False),
        ("1.0.0rc1", True),
        ("1.0.0a1", True),
        ("1.0.0b2", True),
        ("1.0.0.dev3", True),
        ("1.2.3.post1", False),
        ("2.0.0rc1", True),
    ],
)
def test_is_prerelease(script: ModuleType, version: str, expected: bool) -> None:
    assert script.is_prerelease(version) is expected


@pytest.mark.parametrize("version", ["garbage", "", "1.0", "1.0.0.0", "v1.0.0", "1.0.0-", "a.b.c"])
def test_is_prerelease_rejects_invalid_versions(script: ModuleType, version: str) -> None:
    with pytest.raises(ValueError, match="valid version"):
        script.is_prerelease(version)


def test_expected_tag_and_check_tag(script: ModuleType) -> None:
    assert script.expected_tag("0.1.0") == "v0.1.0"
    script.check_tag("v0.1.0", "0.1.0")
    for wrong in ("v0.1.1", "0.1.0", "v0.1.0 ", "V0.1.0", ""):
        with pytest.raises(ValueError, match=r"v0\.1\.0"):
            script.check_tag(wrong, "0.1.0")


# --------------------------------------------------------------------------------------------
# Release notes
# --------------------------------------------------------------------------------------------

SAMPLE = {
    "version": "0.1.0",
    "pyside_version": "6.12.0",
    "qt_version": "6.12.0",
    "zip_name": "cbrn-readiness-dashboard-0.1.0-win-x64.zip",
    "sha256": "ab" * 32,
}


def test_render_fills_every_token(script: ModuleType) -> None:
    template = (
        "{{version}} {{pyside_version}} {{qt_version}} {{zip_name}} {{sha256}}\n"
        "{{flagged_placeholders}}\n{{source_tag_url}}\n{{qt_source_url}}\n{{pyside_source_url}}\n"
        "{{version}} again\n"
    )
    body = script.render_release_body(template, flagged_placeholders=["a_id", "b_id"], **SAMPLE)
    assert "{{" not in body
    assert body.startswith("0.1.0 6.12.0 6.12.0 cbrn-readiness-dashboard-0.1.0-win-x64.zip ")
    assert "`a_id`, `b_id`" in body
    assert body.endswith("0.1.0 again\n")
    assert "https://github.com/marco-jardim/cbrn-readiness-dashboard/tree/v0.1.0" in body
    assert (
        "https://download.qt.io/official_releases/qt/6.12/6.12.0/single/"
        "qt-everywhere-src-6.12.0.tar.xz"
    ) in body
    assert (
        "https://download.qt.io/official_releases/QtForPython/pyside6/"
        "PySide6-6.12.0-src/pyside-setup-everywhere-src-6.12.0.tar.xz"
    ) in body


def test_render_fails_on_a_leftover_token(script: ModuleType) -> None:
    template = "{{version}} {{unknown_token}}"
    with pytest.raises(ValueError, match="unknown_token"):
        script.render_release_body(template, flagged_placeholders=[], **SAMPLE)


def test_render_says_none_for_an_empty_placeholder_list(script: ModuleType) -> None:
    template = "flagged: {{flagged_placeholders}}"
    body = script.render_release_body(template, flagged_placeholders=[], **SAMPLE)
    assert body == "flagged: none"


def test_source_url_constants_are_format_strings(script: ModuleType) -> None:
    assert "{qt_version}" in script.QT_SOURCE_URL_FORMAT
    assert "{major_minor}" in script.QT_SOURCE_URL_FORMAT
    assert "{pyside_version}" in script.PYSIDE_SOURCE_URL_FORMAT
    assert script.qt_source_url("6.12.3").split("/")[5:7] == ["6.12", "6.12.3"]


@pytest.fixture(scope="module")
def template_text() -> str:
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def test_template_has_the_preliminary_notice_and_unsigned_statement(template_text: str) -> None:
    notice = "Preliminary version \u2014 indicators not institutionally validated."
    assert notice in template_text
    lowered = template_text.lower()
    assert "unsigned" in lowered
    assert "smartscreen" in lowered
    assert "smart app control" in lowered
    assert "applocker" in lowered
    assert "wdac" in lowered
    assert "SHA256-FILES.txt" in template_text


def test_template_explains_how_to_verify_and_what_it_proves(template_text: str) -> None:
    assert "Get-FileHash .\\{{zip_name}} -Algorithm SHA256" in template_text
    assert "{{sha256}}" in template_text
    assert "SHA256SUMS.txt" in template_text
    assert "gh attestation verify {{zip_name}} --repo marco-jardim/cbrn-readiness-dashboard" in (
        template_text
    )
    assert (
        "`SHA256SUMS.txt` on the same release page proves transfer integrity, not authenticity"
    ) in template_text
    assert (
        "The attestation proves where and how the build ran, not that the program is safe"
    ) in template_text


def test_template_has_the_source_links_flagged_placeholders_and_licences(
    template_text: str,
) -> None:
    for token in (
        "{{version}}",
        "{{source_tag_url}}",
        "{{qt_source_url}}",
        "{{pyside_source_url}}",
        "{{qt_version}}",
        "{{pyside_version}}",
        "{{flagged_placeholders}}",
    ):
        assert token in template_text, token
    assert template_text.startswith("# CBRN Readiness Dashboard {{version}}")
    assert "Placeholders still flagged" in template_text
    assert "GPL-3.0-or-later" in template_text
    assert "LGPL-3.0-only" in template_text
    assert "GPL-3.0-only" in template_text
    assert "licenses\\" in template_text


def test_template_has_the_written_offer(template_text: str) -> None:
    lowered = " ".join(template_text.lower().split())
    assert "written offer" in lowered
    assert "at least three years" in lowered
    assert "issue tracker" in lowered
    assert "cost of physically performing the distribution" in lowered


def test_real_template_renders_without_leftover_tokens(
    script: ModuleType, template_text: str
) -> None:
    body = script.render_release_body(template_text, flagged_placeholders=["x"], **SAMPLE)
    assert "{{" not in body
    assert SAMPLE["sha256"] in body
    assert "Get-FileHash .\\cbrn-readiness-dashboard-0.1.0-win-x64.zip" in body


# --------------------------------------------------------------------------------------------
# Command line (the project-reading helpers are replaced; no build and no PySide6 needed)
# --------------------------------------------------------------------------------------------


def test_cli_check_tag(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    assert script.main(["check-tag", "--tag", "v0.1.0"]) == 0
    assert script.main(["check-tag", "--tag", "v0.2.0"]) == 1


def test_cli_prerelease_flag(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    assert script.main(["prerelease-flag"]) == 0
    assert capsys.readouterr().out.strip() == "--prerelease"
    monkeypatch.setattr(script, "read_version", lambda: "1.0.0")
    assert script.main(["prerelease-flag"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_cli_package_writes_zip_and_both_checksum_files(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bundle: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    out = tmp_path / "release"
    extra = tmp_path / "NOTES.txt"
    extra.write_bytes(b"notes")
    assert script.main(["package", "--bundle-dir", str(bundle), "--out-dir", str(out)]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert [Path(item).name for item in printed] == [
        "cbrn-readiness-dashboard-0.1.0-win-x64.zip",
        "SHA256SUMS.txt",
        "SHA256-FILES.txt",
    ]
    assert sorted(path.name for path in out.iterdir()) == sorted(Path(i).name for i in printed)

    out2 = tmp_path / "release2"
    args = ["package", "--bundle-dir", str(bundle), "--out-dir", str(out2), "--extra", str(extra)]
    assert script.main(args) == 0
    with zipfile.ZipFile(out2 / "cbrn-readiness-dashboard-0.1.0-win-x64.zip") as archive:
        assert f"{TOP}/NOTES.txt" in archive.namelist()


def test_cli_release_body(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    monkeypatch.setattr(script, "read_qt_versions", lambda: ("6.12.0", "6.12.0"))
    monkeypatch.setattr(script, "read_flagged_placeholders", lambda: ["demo_flag"])
    zip_path = script.make_zip(bundle, tmp_path / "release", "0.1.0")
    out = tmp_path / "release" / "body.md"
    args = ["release-body", "--template", str(TEMPLATE_PATH)]
    args += ["--out", str(out), "--zip", str(zip_path)]
    assert script.main(args) == 0
    body = out.read_text(encoding="utf-8")
    assert "{{" not in body
    assert hashlib.sha256(zip_path.read_bytes()).hexdigest() in body
    assert "`demo_flag`" in body
    assert "# CBRN Readiness Dashboard 0.1.0" in body


def test_cli_release_body_fails_loudly_without_the_placeholder_function(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bundle: Path,
    tmp_path: Path,
) -> None:
    def broken() -> list[str]:
        raise RuntimeError("Cannot read the flagged placeholders")

    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    monkeypatch.setattr(script, "read_qt_versions", lambda: ("6.12.0", "6.12.0"))
    monkeypatch.setattr(script, "read_flagged_placeholders", broken)
    zip_path = script.make_zip(bundle, tmp_path / "release", "0.1.0")
    out = tmp_path / "body.md"
    args = ["release-body", "--template", str(TEMPLATE_PATH)]
    args += ["--out", str(out), "--zip", str(zip_path)]
    assert script.main(args) == 1
    assert not out.exists()
    assert "Cannot read the flagged placeholders" in capsys.readouterr().err
