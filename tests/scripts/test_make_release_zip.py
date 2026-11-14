# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of ``scripts/make_release_zip.py`` (T9.3) on a fake bundle folder: no build needed."""

from __future__ import annotations

import configparser
import hashlib
import importlib.util
import os
import re
import shutil
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "make_release_zip.py"
TEMPLATE_PATH = ROOT / ".github" / "release-body.template.md"
PACKAGING_DIR = ROOT / "packaging"

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


def test_template_presents_the_manifest_as_verification_not_as_hash_rules(
    template_text: str,
) -> None:
    flat = " ".join(template_text.split())
    assert "allow-list by file hash" not in flat
    assert "verify each extracted file" in flat
    assert "policy tooling of their own organisation" in flat


def test_template_offer_covers_every_locked_package_and_the_relinking_route(
    template_text: str,
) -> None:
    flat = " ".join(template_text.split())
    assert "every other Python package locked in `uv.lock`" in flat
    assert "scripts/build_exe.py" in flat
    assert "one-folder build" in flat


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
# Signed and unsigned release notes (SignPath signing is optional)
# --------------------------------------------------------------------------------------------

START = "<!-- signing-notice:start -->"
END = "<!-- signing-notice:end -->"


def _render(script: ModuleType, template: str, *, signed: bool | None = None) -> str:
    extra = {} if signed is None else {"signed": signed}
    return script.render_release_body(template, flagged_placeholders=["x"], **SAMPLE, **extra)


def test_template_wraps_the_unsigned_section_in_the_two_markers(template_text: str) -> None:
    assert template_text.count(START) == 1
    assert template_text.count(END) == 1
    inner = template_text.split(START)[1].split(END)[0]
    assert "## The program is unsigned" in inner
    assert "SmartScreen" in inner
    assert "SHA256-FILES.txt" not in inner  # the manifest paragraph is for both kinds of release


def test_unsigned_notes_are_the_template_without_the_marker_lines(
    script: ModuleType, template_text: str
) -> None:
    default = _render(script, template_text)
    assert default == _render(script, template_text, signed=False)
    assert START not in default
    assert END not in default
    assert "<!--" not in default
    assert "## The program is unsigned" in default
    assert "**unsigned**" in default
    assert "signed by" not in default.lower()
    expected = template_text.replace(START + "\n", "").replace(END + "\n", "")
    assert default == script.render_release_body(expected, flagged_placeholders=["x"], **SAMPLE)


def test_signed_notes_name_signpath_and_replace_the_unsigned_section(
    script: ModuleType, template_text: str
) -> None:
    body = _render(script, template_text, signed=True)
    assert "{{" not in body
    assert "<!--" not in body
    assert "## The program is unsigned" not in body
    assert "## The executable is signed" in body
    flat = " ".join(body.split())
    assert (
        "Free code signing provided by [SignPath.io](https://about.signpath.io), "
        "certificate by [SignPath Foundation](https://signpath.org)"
    ) in flat
    assert "Only `cbrn-dashboard.exe` is signed" in body
    assert "Get-AuthenticodeSignature" in body
    assert "https://github.com/marco-jardim/cbrn-readiness-dashboard/blob/v0.1.0/" in body
    assert "CODE-SIGNING-POLICY.md" in body
    # Everything outside the section is the same as in the unsigned notes.
    unsigned = _render(script, template_text)
    assert body.split("## The executable is signed")[0] == unsigned.split("## The program")[0]
    assert body.endswith(unsigned.split("The per-file manifest")[1])
    assert "The per-file manifest `SHA256-FILES.txt`" in body


def test_the_script_is_ascii_and_fits_the_line_length() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert text.isascii()
    assert max(len(line) for line in text.splitlines()) <= 100


def test_a_signed_render_needs_the_markers(script: ModuleType) -> None:
    with pytest.raises(ValueError, match="signing-notice"):
        script.render_release_body("{{version}}", flagged_placeholders=[], signed=True, **SAMPLE)


@pytest.mark.parametrize(
    "template",
    [
        f"a\n{START}\nb\n",  # no end
        f"a\n{END}\nb\n",  # no start
        f"{END}\nb\n{START}\n",  # wrong order
        f"{START}\n{START}\nb\n{END}\n",  # two starts
    ],
)
def test_broken_markers_are_refused(script: ModuleType, template: str) -> None:
    for signed in (False, True):
        with pytest.raises(ValueError, match="signing-notice"):
            script.render_release_body(template, flagged_placeholders=[], signed=signed, **SAMPLE)


def test_cli_release_body_signed_flag(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    monkeypatch.setattr(script, "read_qt_versions", lambda: ("6.12.0", "6.12.0"))
    monkeypatch.setattr(script, "read_flagged_placeholders", lambda: ["demo_flag"])
    zip_path = script.make_zip(bundle, tmp_path / "release", "0.1.0")
    base = ["release-body", "--template", str(TEMPLATE_PATH), "--zip", str(zip_path)]
    unsigned_out = tmp_path / "unsigned.md"
    signed_out = tmp_path / "signed.md"
    assert script.main([*base, "--out", str(unsigned_out)]) == 0
    assert script.main([*base, "--out", str(signed_out), "--signed"]) == 0
    unsigned = unsigned_out.read_text(encoding="utf-8")
    signed = signed_out.read_text(encoding="utf-8")
    assert "## The program is unsigned" in unsigned
    assert "SignPath" not in unsigned
    assert "## The executable is signed" in signed
    assert "SignPath" in signed


def test_cli_print_version(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    assert script.main(["print-version"]) == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_package_makes_the_zip_from_a_signed_folder(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The zip is made from whatever folder it is given: the signed one carries the signed exe."""
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    signed = _make_bundle(tmp_path / "signed" / "cbrn-dashboard")
    (signed / "cbrn-dashboard.exe").write_bytes(b"MZ fake executable + signature")
    out = tmp_path / "release"
    assert script.main(["package", "--bundle-dir", str(signed), "--out-dir", str(out)]) == 0
    with zipfile.ZipFile(out / "cbrn-readiness-dashboard-0.1.0-win-x64.zip") as archive:
        assert archive.read(f"{TOP}/cbrn-dashboard.exe") == b"MZ fake executable + signature"
        assert archive.read(f"{TOP}/_internal/alpha.txt") == b"alpha"
    manifest = (out / "SHA256-FILES.txt").read_text(encoding="utf-8")
    digest = hashlib.sha256(b"MZ fake executable + signature").hexdigest()
    assert f"{digest}  {TOP}/cbrn-dashboard.exe\n" in manifest
    sums = (out / "SHA256SUMS.txt").read_text(encoding="utf-8")
    zip_digest = hashlib.sha256(
        (out / "cbrn-readiness-dashboard-0.1.0-win-x64.zip").read_bytes()
    ).hexdigest()
    assert sums.startswith(zip_digest)


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


#: The four files the ``package`` command puts at the root of the top folder (T9.4).
NOTE_NAMES: dict[str, str] = {
    "pt-BR": "README-first-run.pt-BR.txt",
    "en-US": "README-first-run.en-US.txt",
    "es-ES": "README-first-run.es-ES.txt",
}
EXAMPLE_NAME = "portable.ini.example"
ROOT_FILE_NAMES: list[str] = [*NOTE_NAMES.values(), EXAMPLE_NAME]

#: The preliminary notice, verbatim, per language.
NOTICES: dict[str, str] = {
    "en-US": "Preliminary version \u2014 indicators not institutionally validated.",
    "pt-BR": "Vers\u00e3o preliminar \u2014 indicadores n\u00e3o validados institucionalmente.",
    "es-ES": "Versi\u00f3n preliminar \u2014 indicadores no validados institucionalmente.",
}
#: The sentence saying that "sensitive" is a working label and not a classification.
NOT_A_CLASSIFICATION: dict[str, str] = {
    "en-US": "It is not a formal classification",
    "pt-BR": "N\u00e3o \u00e9 uma classifica\u00e7\u00e3o formal",
    "es-ES": "No es una clasificaci\u00f3n formal",
}
SOURCE_URL = "https://github.com/marco-jardim/cbrn-readiness-dashboard"
#: Product names, paths and commands that must be identical in the three notes.
COMMON_PHRASES: tuple[str, ...] = (
    "CBRN Readiness Dashboard",
    "cbrn-dashboard.exe --demo",
    "_internal\\",
    "Get-FileHash .\\cbrn-readiness-dashboard-<version>-win-x64.zip -Algorithm SHA256",
    "gh attestation verify",
    "SHA256SUMS.txt",
    "SHA256-FILES.txt",
    "%LOCALAPPDATA%\\cbrn-readiness-dashboard",
    "portable.ini.example",
    "portable.ini",
    ".\\data\\",
    "--data-dir",
    "BitLocker",
    "licenses\\",
    "GPL-3.0-or-later",
    SOURCE_URL,
    "Q4",
    "Q11",
    "Q13",
    "Q19",
)
HEADING = re.compile(r"^(\d{1,2})\. \S", re.MULTILINE)


def _flat(text: str) -> str:
    """``text`` with every run of white space (line breaks too) replaced by one space."""
    return " ".join(text.split())


def _note_text(language: str) -> str:
    return (PACKAGING_DIR / NOTE_NAMES[language]).read_bytes().decode("utf-8")


def test_the_root_files_exist_in_the_repository(script: ModuleType) -> None:
    assert list(script.DEFAULT_ROOT_FILES) == ROOT_FILE_NAMES
    assert [path.name for path in script.default_root_files()] == ROOT_FILE_NAMES


def test_default_root_files_fail_loudly_when_one_is_missing(
    script: ModuleType, tmp_path: Path
) -> None:
    for name in ROOT_FILE_NAMES[:-1]:
        (tmp_path / name).write_bytes(b"x")
    with pytest.raises(ValueError, match=r"portable\.ini\.example"):
        script.default_root_files(tmp_path)


def test_package_puts_the_notes_and_the_example_at_the_top_folder_root(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    out = tmp_path / "release"
    assert script.main(["package", "--bundle-dir", str(bundle), "--out-dir", str(out)]) == 0
    with zipfile.ZipFile(out / "cbrn-readiness-dashboard-0.1.0-win-x64.zip") as archive:
        names = archive.namelist()
        for name in ROOT_FILE_NAMES:
            assert archive.read(f"{TOP}/{name}") == (PACKAGING_DIR / name).read_bytes(), name
    assert names == sorted(names)
    assert len(names) == len(FAKE_FILES) + len(ROOT_FILE_NAMES)
    assert not [name for name in names if name.endswith("/")]
    # A fixed file name that is not at the root would be a packaging mistake.
    assert [name for name in names if name.count("/") == 1 and name.endswith(".txt")] == sorted(
        f"{TOP}/{name}" for name in NOTE_NAMES.values()
    )


def test_package_lists_the_notes_and_the_example_in_the_file_manifest(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    out = tmp_path / "release"
    assert script.main(["package", "--bundle-dir", str(bundle), "--out-dir", str(out)]) == 0
    lines = (out / "SHA256-FILES.txt").read_bytes().decode("utf-8").splitlines()
    entries: dict[str, str] = {}
    for line in lines:
        digest, path = line.split("  ", 1)
        entries[path] = digest
    assert len(entries) == len(lines) == len(FAKE_FILES) + len(ROOT_FILE_NAMES)
    for name in ROOT_FILE_NAMES:
        digest = hashlib.sha256((PACKAGING_DIR / name).read_bytes()).hexdigest()
        assert entries[f"{TOP}/{name}"] == digest, name
    paths = [line.split("  ", 1)[1] for line in lines]
    assert paths == sorted(paths)


def test_package_with_extra_files_adds_them_to_the_defaults(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    extra = tmp_path / "NOTES.txt"
    extra.write_bytes(b"notes")
    out = tmp_path / "release"
    args = ["package", "--bundle-dir", str(bundle), "--out-dir", str(out), "--extra", str(extra)]
    assert script.main(args) == 0
    with zipfile.ZipFile(out / "cbrn-readiness-dashboard-0.1.0-win-x64.zip") as archive:
        names = set(archive.namelist())
    assert {f"{TOP}/{name}" for name in ROOT_FILE_NAMES} <= names
    assert f"{TOP}/NOTES.txt" in names
    manifest = (out / "SHA256-FILES.txt").read_text(encoding="utf-8")
    assert f"  {TOP}/NOTES.txt\n" in manifest


def test_package_zip_with_the_default_root_files_is_reproducible(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    zips: list[bytes] = []
    manifests: list[bytes] = []
    for index in (1, 2):
        out = tmp_path / f"release{index}"
        assert script.main(["package", "--bundle-dir", str(bundle), "--out-dir", str(out)]) == 0
        zips.append((out / "cbrn-readiness-dashboard-0.1.0-win-x64.zip").read_bytes())
        manifests.append((out / "SHA256-FILES.txt").read_bytes())
    assert zips[0] == zips[1]
    assert manifests[0] == manifests[1]


def test_file_manifest_with_extra_root_files_is_sorted_and_refuses_clashes(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    extra = tmp_path / "A-first.txt"
    extra.write_bytes(b"first")
    manifest = script.write_file_manifest(bundle, tmp_path / "out", [extra])
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert lines[0] == f"{hashlib.sha256(b'first').hexdigest()}  {TOP}/A-first.txt"
    clash = tmp_path / "cbrn-dashboard.exe"
    clash.write_bytes(b"other")
    with pytest.raises(ValueError, match="twice"):
        script.write_file_manifest(bundle, tmp_path / "out2", [clash])


@pytest.mark.parametrize("language", sorted(NOTE_NAMES))
def test_note_is_utf8_without_bom_tabs_or_carriage_returns(language: str) -> None:
    raw = (PACKAGING_DIR / NOTE_NAMES[language]).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert b"\t" not in raw
    assert b"\r" not in raw
    raw.decode("utf-8")  # raises when it is not valid UTF-8


def test_the_three_notes_have_the_same_numbered_sections() -> None:
    expected = [str(number) for number in range(1, 13)]
    for language in NOTE_NAMES:
        numbers = HEADING.findall(_note_text(language))
        assert numbers == expected, language


@pytest.mark.parametrize("language", sorted(NOTE_NAMES))
def test_note_has_its_languages_preliminary_notice_verbatim(language: str) -> None:
    assert NOTICES[language] in _flat(_note_text(language))


@pytest.mark.parametrize("language", sorted(NOTE_NAMES))
def test_note_says_that_sensitive_is_not_a_classification(language: str) -> None:
    flat = _flat(_note_text(language))
    assert NOT_A_CLASSIFICATION[language] in flat
    assert "Q19" in flat


@pytest.mark.parametrize("language", sorted(NOTE_NAMES))
def test_note_names_the_commands_files_and_paths(language: str) -> None:
    flat = _flat(_note_text(language))
    missing = [phrase for phrase in COMMON_PHRASES if phrase not in flat]
    assert not missing, f"{language}: missing {missing}"


def test_the_notes_do_not_mix_up_the_languages() -> None:
    for language, notice in NOTICES.items():
        for other in NOTE_NAMES:
            if other != language:
                assert notice not in _flat(_note_text(other)), (language, other)


def test_portable_example_parses_and_explains_portable_mode() -> None:
    raw = (PACKAGING_DIR / EXAMPLE_NAME).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8")
    parser = configparser.ConfigParser()
    parser.read_string(text)
    assert parser.sections() == ["portable"]
    assert dict(parser["portable"]) == {}
    flat = _flat(text)
    assert "portable.ini" in flat
    assert ".\\data\\" in flat
    assert "copying the program folder copies the data" in flat  # English
    assert "copiar a pasta do programa copia tambem os dados" in flat  # pt-BR
    assert "copiar la carpeta del programa copia tambien los datos" in flat  # es-ES
    comment_lines = [line for line in text.splitlines() if line.strip()]
    assert all(line.startswith((";", "[")) for line in comment_lines)


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


# --------------------------------------------------------------------------------------------
# The installer (Inno Setup): checksum line, release notes section
# --------------------------------------------------------------------------------------------

SETUP_NAME = "cbrn-readiness-dashboard-0.1.0-win-x64-setup.exe"
INSTALLER_START = "<!-- installer:start -->"
INSTALLER_END = "<!-- installer:end -->"
SETUP_SAMPLE = {"installer_name": SETUP_NAME, "installer_sha256": "cd" * 32}


def _setup_file(folder: Path, content: bytes = b"MZ fake setup") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / SETUP_NAME
    path.write_bytes(content)
    return path


def test_sha256sums_lists_the_zip_and_then_the_installer(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    zip_path = script.make_zip(bundle, out, "0.1.0")
    setup = _setup_file(out)
    sums = script.write_sha256sums(zip_path, out, setup)
    raw = sums.read_bytes()
    assert (
        raw
        == (
            f"{hashlib.sha256(zip_path.read_bytes()).hexdigest()}  {zip_path.name}\n"
            f"{hashlib.sha256(setup.read_bytes()).hexdigest()}  {SETUP_NAME}\n"
        ).encode()
    )
    assert b"\r" not in raw


def test_sha256sums_refuses_a_missing_installer(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    zip_path = script.make_zip(bundle, tmp_path / "out", "0.1.0")
    with pytest.raises(ValueError, match="Not a file"):
        script.write_sha256sums(zip_path, tmp_path / "out", tmp_path / "missing-setup.exe")


def test_place_installer_copies_a_file_from_elsewhere_and_keeps_one_in_place(
    script: ModuleType, tmp_path: Path
) -> None:
    elsewhere = _setup_file(tmp_path / "elsewhere")
    placed = script.place_installer(elsewhere, tmp_path / "out")
    assert placed == tmp_path / "out" / SETUP_NAME
    assert placed.read_bytes() == elsewhere.read_bytes()
    assert script.place_installer(placed, tmp_path / "out") == placed
    assert placed.read_bytes() == b"MZ fake setup"


def test_place_installer_refuses_other_names_and_missing_files(
    script: ModuleType, tmp_path: Path
) -> None:
    other = tmp_path / "program.exe"
    other.write_bytes(b"MZ")
    with pytest.raises(ValueError, match=r"setup\.exe"):
        script.place_installer(other, tmp_path / "out")
    with pytest.raises(ValueError, match="Not a file"):
        script.place_installer(tmp_path / SETUP_NAME, tmp_path / "out")


def test_cli_package_with_an_installer_checksums_it_but_does_not_zip_it(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bundle: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    out = tmp_path / "release"
    setup = _setup_file(tmp_path / "built")
    args = ["package", "--bundle-dir", str(bundle), "--out-dir", str(out)]
    assert script.main([*args, "--installer", str(setup)]) == 0
    printed = [Path(item).name for item in capsys.readouterr().out.splitlines()]
    assert printed == [
        "cbrn-readiness-dashboard-0.1.0-win-x64.zip",
        "SHA256SUMS.txt",
        "SHA256-FILES.txt",
        SETUP_NAME,
    ]
    assert (out / SETUP_NAME).read_bytes() == setup.read_bytes()
    lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert [line.split("  ")[1] for line in lines] == [
        "cbrn-readiness-dashboard-0.1.0-win-x64.zip",
        SETUP_NAME,
    ]
    assert lines[1].split("  ")[0] == hashlib.sha256(setup.read_bytes()).hexdigest()
    # The per-file manifest and the zip are about the bundle only.
    assert SETUP_NAME not in (out / "SHA256-FILES.txt").read_text(encoding="utf-8")
    with zipfile.ZipFile(out / "cbrn-readiness-dashboard-0.1.0-win-x64.zip") as archive:
        names = archive.namelist()
    assert not [name for name in names if "setup" in name]


def test_cli_package_without_an_installer_is_unchanged(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    out = tmp_path / "release"
    assert script.main(["package", "--bundle-dir", str(bundle), "--out-dir", str(out)]) == 0
    assert len((out / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()) == 1


def test_template_has_one_installer_section_with_its_tokens(template_text: str) -> None:
    assert template_text.count(INSTALLER_START) == 1
    assert template_text.count(INSTALLER_END) == 1
    inner = template_text.split(INSTALLER_START)[1].split(INSTALLER_END)[0]
    assert "## Installer (recommended)" in inner
    assert "{{installer_name}}" in inner
    assert "{{installer_sha256}}" in inner
    flat = " ".join(inner.split())
    assert "no administrator rights are needed" in flat
    assert "%LOCALAPPDATA%\\Programs\\CBRN Readiness Dashboard" in flat
    assert "Start-menu shortcut" in flat
    assert "Settings > Apps" in flat
    assert "keeps your data" in flat
    assert "is **not signed**" in flat
    assert "SmartScreen" in flat
    assert "Inno Setup" in flat
    assert "Get-FileHash .\\{{installer_name}} -Algorithm SHA256" in inner
    assert "gh attestation verify {{installer_name}} --repo" in inner
    assert "portable mode" in flat
    # The installer section is outside the signing section, so a signed release keeps it.
    assert template_text.index(INSTALLER_END) < template_text.index(START)


def test_notes_with_an_installer_keep_and_fill_the_section(
    script: ModuleType, template_text: str
) -> None:
    body = script.render_release_body(
        template_text, flagged_placeholders=["x"], **SAMPLE, **SETUP_SAMPLE
    )
    assert "{{" not in body
    assert "<!--" not in body
    assert "## Installer (recommended)" in body
    assert f"Download **`{SETUP_NAME}`**" in body
    assert SETUP_SAMPLE["installer_sha256"] in body
    assert f"Get-FileHash .\\{SETUP_NAME} -Algorithm SHA256" in body
    assert f"gh attestation verify {SETUP_NAME} --repo marco-jardim/" in body
    assert "## The program is unsigned" in body


def test_notes_without_an_installer_leave_the_section_out(
    script: ModuleType, template_text: str
) -> None:
    body = _render(script, template_text)
    assert "Installer" not in body
    assert "-setup.exe" not in body
    assert "{{" not in body
    assert "<!--" not in body


def test_a_signed_release_keeps_the_installer_section_and_says_it_is_not_signed(
    script: ModuleType, template_text: str
) -> None:
    body = script.render_release_body(
        template_text, flagged_placeholders=["x"], signed=True, **SAMPLE, **SETUP_SAMPLE
    )
    assert "## The executable is signed" in body
    assert "## Installer (recommended)" in body
    flat = " ".join(body.split())
    assert "The setup program is **not signed**" in flat
    assert body.index("## Installer (recommended)") < body.index("## The executable is signed")


def test_installer_name_and_hash_go_together(script: ModuleType, template_text: str) -> None:
    with pytest.raises(ValueError, match="go together"):
        script.render_release_body(
            template_text, flagged_placeholders=[], installer_name=SETUP_NAME, **SAMPLE
        )
    with pytest.raises(ValueError, match="go together"):
        script.render_release_body(
            template_text, flagged_placeholders=[], installer_sha256="ab" * 32, **SAMPLE
        )


@pytest.mark.parametrize(
    "template",
    [
        f"a\n{INSTALLER_START}\nb\n",
        f"a\n{INSTALLER_END}\nb\n",
        f"{INSTALLER_END}\nb\n{INSTALLER_START}\n",
        f"{INSTALLER_START}\n{INSTALLER_START}\nb\n{INSTALLER_END}\n",
    ],
)
def test_broken_installer_markers_are_refused(script: ModuleType, template: str) -> None:
    with pytest.raises(ValueError, match="installer"):
        script.render_release_body(template, flagged_placeholders=[], **SAMPLE)


def test_a_template_without_installer_markers_is_filled_as_it_is(script: ModuleType) -> None:
    template = "{{version}} {{installer_name}}"
    body = script.render_release_body(template, flagged_placeholders=[], **SAMPLE, **SETUP_SAMPLE)
    assert body == f"0.1.0 {SETUP_NAME}"


def test_cli_release_body_with_an_installer(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    monkeypatch.setattr(script, "read_qt_versions", lambda: ("6.12.0", "6.12.0"))
    monkeypatch.setattr(script, "read_flagged_placeholders", lambda: ["demo_flag"])
    zip_path = script.make_zip(bundle, tmp_path / "release", "0.1.0")
    setup = _setup_file(tmp_path / "release")
    out = tmp_path / "with.md"
    args = ["release-body", "--template", str(TEMPLATE_PATH), "--zip", str(zip_path)]
    assert script.main([*args, "--out", str(out), "--installer", str(setup)]) == 0
    body = out.read_text(encoding="utf-8")
    assert hashlib.sha256(setup.read_bytes()).hexdigest() in body
    assert SETUP_NAME in body
    plain = tmp_path / "without.md"
    assert script.main([*args, "--out", str(plain)]) == 0
    assert SETUP_NAME not in plain.read_text(encoding="utf-8")
    missing = tmp_path / "missing.md"
    absent = str(tmp_path / "no.exe")
    assert script.main([*args, "--out", str(missing), "--installer", absent]) == 1
    assert not missing.exists()


# --------------------------------------------------------------------------------------------
# The Qt and PySide6 source archives (LGPL-3.0): checksum lines, release notes section
# --------------------------------------------------------------------------------------------

SOURCES_START = "<!-- source-archives:start -->"
SOURCES_END = "<!-- source-archives:end -->"
FAKE_ARCHIVE_CONTENT: dict[str, bytes] = {
    "qt-everywhere-src-6.12.0.tar.xz": b"fake qt sources " * 50,
    "pyside-setup-everywhere-src-6.12.0.tar.xz": b"fake pyside sources " * 20,
}


def _fake_archives(script: ModuleType) -> list[object]:
    """Pins for the two fake archives (the real ones are 460 MB and are never downloaded here)."""
    archive_type = script._fetch_script().SourceArchive
    return [
        archive_type(
            name,
            "6.12.0",
            f"https://download.example.invalid/{filename}",
            len(content),
            hashlib.sha256(content).hexdigest(),
        )
        for name, (filename, content) in zip(
            ("Qt", "PySide6"), FAKE_ARCHIVE_CONTENT.items(), strict=True
        )
    ]


def _write_fake_archives(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for filename, content in FAKE_ARCHIVE_CONTENT.items():
        path = folder / filename
        path.write_bytes(content)
        paths.append(path)
    return paths


def _use_fake_pins(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(script, "load_source_archives", lambda *_args: _fake_archives(script))


def test_sha256sums_lists_zip_installer_and_then_the_source_archives(
    script: ModuleType, bundle: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    zip_path = script.make_zip(bundle, out, "0.1.0")
    setup = _setup_file(out)
    archives = _write_fake_archives(out)
    sums = script.write_sha256sums(zip_path, out, setup, archives)
    expected = [zip_path, setup, *archives]
    lines = sums.read_bytes().decode("ascii").splitlines()
    assert [line.split("  ")[1] for line in lines] == [path.name for path in expected]
    assert [line.split("  ")[0] for line in lines] == [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in expected
    ]
    assert b"\r" not in sums.read_bytes()
    with pytest.raises(ValueError, match="Not a file"):
        script.write_sha256sums(zip_path, out, None, [out / "missing.tar.xz"])


def test_cli_package_verifies_lists_and_places_the_source_archives(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bundle: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    _use_fake_pins(script, monkeypatch)
    fetched = _write_fake_archives(tmp_path / "fetched")
    out = tmp_path / "release"
    setup = _setup_file(tmp_path / "built")
    args = ["package", "--bundle-dir", str(bundle), "--out-dir", str(out)]
    args += ["--installer", str(setup), "--source-archives-dir", str(tmp_path / "fetched")]
    assert script.main(args) == 0
    printed = [Path(item).name for item in capsys.readouterr().out.splitlines()]
    assert printed == [
        "cbrn-readiness-dashboard-0.1.0-win-x64.zip",
        "SHA256SUMS.txt",
        "SHA256-FILES.txt",
        SETUP_NAME,
        *[path.name for path in fetched],
    ]
    for path in fetched:
        assert (out / path.name).read_bytes() == path.read_bytes()
    lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert [line.split("  ")[1] for line in lines] == [
        "cbrn-readiness-dashboard-0.1.0-win-x64.zip",
        SETUP_NAME,
        *[path.name for path in fetched],
    ]
    # The archives are neither in the zip nor in the per-file manifest of the bundle.
    assert "tar.xz" not in (out / "SHA256-FILES.txt").read_text(encoding="utf-8")
    with zipfile.ZipFile(out / "cbrn-readiness-dashboard-0.1.0-win-x64.zip") as archive:
        assert not [name for name in archive.namelist() if name.endswith(".tar.xz")]


def test_cli_package_keeps_archives_that_are_already_in_the_out_dir(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    """The workflow fetches into release/ and packages into release/: nothing is copied."""
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    _use_fake_pins(script, monkeypatch)
    out = tmp_path / "release"
    fetched = _write_fake_archives(out)
    args = ["package", "--bundle-dir", str(bundle), "--out-dir", str(out)]
    assert script.main([*args, "--source-archives-dir", str(out)]) == 0
    assert [path.read_bytes() for path in fetched] == list(FAKE_ARCHIVE_CONTENT.values())
    lines = (out / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_cli_package_refuses_missing_or_altered_source_archives(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bundle: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    _use_fake_pins(script, monkeypatch)
    folder = tmp_path / "fetched"
    args = ["package", "--bundle-dir", str(bundle), "--out-dir", str(tmp_path / "release")]
    args += ["--source-archives-dir", str(folder)]
    folder.mkdir()
    assert script.main(args) == 1
    assert "missing" in capsys.readouterr().err
    paths = _write_fake_archives(folder)
    paths[0].write_bytes(b"Z" * len(paths[0].read_bytes()))
    assert script.main(args) == 1
    assert "SHA-256 mismatch" in capsys.readouterr().err
    assert not (tmp_path / "release" / "SHA256SUMS.txt").exists()


def test_cli_package_without_source_archives_is_unchanged(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, bundle: Path, tmp_path: Path
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")

    def not_called(*_args: object) -> object:
        raise AssertionError("the pins must not be read without --source-archives-dir")

    monkeypatch.setattr(script, "load_source_archives", not_called)
    out = tmp_path / "release"
    assert script.main(["package", "--bundle-dir", str(bundle), "--out-dir", str(out)]) == 0
    assert not list(out.glob("*.tar.xz"))


def test_template_has_one_source_archives_section_with_its_token(template_text: str) -> None:
    assert template_text.count(SOURCES_START) == 1
    assert template_text.count(SOURCES_END) == 1
    inner = template_text.split(SOURCES_START)[1].split(SOURCES_END)[0]
    assert "## Source code of Qt and PySide6 (LGPL-3.0)" in inner
    assert "{{source_archives}}" in inner
    flat = " ".join(inner.split())
    assert "attached to this release, next to the binary" in flat
    assert "unmodified copies of the archives published at download.qt.io" in flat
    assert "SHA-256 pinned in the repository" in flat
    assert "licenses\\SOURCE-OFFER.md" in flat
    assert "remains valid" in flat
    assert "{{qt_version}}" in inner
    assert "{{pyside_version}}" in inner
    # Outside the installer and the signing sections, so that every kind of release has it.
    assert template_text.index(INSTALLER_END) < template_text.index(SOURCES_START)
    assert template_text.index(SOURCES_END) > template_text.index(END)


def test_notes_with_source_archives_name_them_with_their_hashes(
    script: ModuleType, template_text: str
) -> None:
    archives = _fake_archives(script)
    body = script.render_release_body(
        template_text, flagged_placeholders=["x"], source_archives=archives, **SAMPLE
    )
    assert "{{" not in body
    assert "<!--" not in body
    assert "## Source code of Qt and PySide6 (LGPL-3.0)" in body
    for name, content in FAKE_ARCHIVE_CONTENT.items():
        assert f"- `{name}`" in body
        assert f"SHA-256: `{hashlib.sha256(content).hexdigest()}`" in body
    assert "- `qt-everywhere-src-6.12.0.tar.xz` (Qt 6.12.0), SHA-256: `" in body
    assert "(PySide6 6.12.0), SHA-256: `" in body
    # A signed release keeps the section too.
    signed = script.render_release_body(
        template_text, flagged_placeholders=["x"], source_archives=archives, signed=True, **SAMPLE
    )
    assert "## Source code of Qt and PySide6 (LGPL-3.0)" in signed
    assert "## The executable is signed" in signed


def test_notes_without_source_archives_leave_the_section_out(
    script: ModuleType, template_text: str
) -> None:
    body = _render(script, template_text)
    assert "Source code of Qt and PySide6" not in body
    assert "source-archives" not in body
    assert "SHA-256: `" not in body
    assert "## Source code and licences" in body


@pytest.mark.parametrize(
    "template",
    [
        f"a\n{SOURCES_START}\nb\n",
        f"a\n{SOURCES_END}\nb\n",
        f"{SOURCES_END}\nb\n{SOURCES_START}\n",
        f"{SOURCES_START}\n{SOURCES_START}\nb\n{SOURCES_END}\n",
    ],
)
def test_broken_source_archives_markers_are_refused(script: ModuleType, template: str) -> None:
    with pytest.raises(ValueError, match="source-archives"):
        script.render_release_body(template, flagged_placeholders=[], **SAMPLE)


def test_cli_release_body_lists_the_verified_source_archives(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bundle: Path,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(script, "read_version", lambda: "0.1.0")
    monkeypatch.setattr(script, "read_qt_versions", lambda: ("6.12.0", "6.12.0"))
    monkeypatch.setattr(script, "read_flagged_placeholders", lambda: ["demo_flag"])
    _use_fake_pins(script, monkeypatch)
    zip_path = script.make_zip(bundle, tmp_path / "release", "0.1.0")
    folder = tmp_path / "fetched"
    _write_fake_archives(folder)
    out = tmp_path / "with.md"
    args = ["release-body", "--template", str(TEMPLATE_PATH), "--zip", str(zip_path)]
    assert script.main([*args, "--out", str(out), "--source-archives-dir", str(folder)]) == 0
    body = out.read_text(encoding="utf-8")
    for name, content in FAKE_ARCHIVE_CONTENT.items():
        assert f"- `{name}`" in body
        assert hashlib.sha256(content).hexdigest() in body
    plain = tmp_path / "without.md"
    assert script.main([*args, "--out", str(plain)]) == 0
    assert "Source code of Qt and PySide6" not in plain.read_text(encoding="utf-8")
    # The notes never name an archive that is not there or is not the pinned one.
    (folder / "qt-everywhere-src-6.12.0.tar.xz").write_bytes(b"changed")
    refused = tmp_path / "refused.md"
    capsys.readouterr()
    assert script.main([*args, "--out", str(refused), "--source-archives-dir", str(folder)]) == 1
    assert "mismatch" in capsys.readouterr().err
    assert not refused.exists()


def test_the_real_pins_fill_the_real_template(script: ModuleType, template_text: str) -> None:
    """The notes of a release carry the two real archive names and their pinned SHA-256."""
    archives = script.load_source_archives()
    body = script.render_release_body(
        template_text, flagged_placeholders=[], source_archives=archives, **SAMPLE
    )
    assert "{{" not in body
    for archive in archives:
        assert f"`{archive.filename}`" in body
        assert archive.sha256 in body
    assert "98ff4f44bac6ec3e1e62ee2a4316ae0e3d15badb015d753cc0268a20db52f165" in body
