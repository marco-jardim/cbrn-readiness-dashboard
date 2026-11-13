# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of ``scripts/collect_licenses.py`` (T9.2): real environment, output in ``tmp_path``."""

import importlib.util
import json
import sys
from collections.abc import Sequence
from importlib.metadata import Distribution
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "collect_licenses.py"
RELEASE_SCRIPT_PATH = ROOT / "scripts" / "make_release_zip.py"
SOURCES = ROOT / "packaging" / "licenses"

PYSIDE_DECLARED = "LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only"
FAKE_VERSIONS = ("6.12.0", "6.12.0")

#: ``(output folder, index entries)`` of one real collection run (entries are ``LicenseEntry``).
Collected = tuple[Path, list[Any]]


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script() -> ModuleType:
    return _load("cbrn_collect_licenses_test_script", SCRIPT_PATH)


@pytest.fixture(scope="module")
def release() -> ModuleType:
    return _load("cbrn_make_release_zip_for_licenses", RELEASE_SCRIPT_PATH)


def _snapshot(folder: Path) -> dict[str, bytes]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def make_distribution(
    folder: Path,
    name: str,
    *,
    license_expression: str | None = None,
    classifiers: Sequence[str] = (),
    license_files: Sequence[tuple[str, str]] = (),
    version: str = "1.0",
) -> Distribution:
    """Write a minimal ``*.dist-info`` below ``folder`` and load it."""
    info = folder / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}"]
    if license_expression is not None:
        lines.append(f"License-Expression: {license_expression}")
    lines.extend(f"Classifier: {item}" for item in classifiers)
    lines.extend(f"License-File: {file_name}" for file_name, _text in license_files)
    (info / "METADATA").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for file_name, text in license_files:
        target = info / "licenses" / file_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return Distribution.at(info)


@pytest.fixture(scope="module")
def collected(script: ModuleType, tmp_path_factory: pytest.TempPathFactory) -> Collected:
    out = tmp_path_factory.mktemp("licenses") / "licenses"
    entries = script.collect(
        out, repo_root=ROOT, allow_missing_pyinstaller=script.pyinstaller_distribution() is None
    )
    return out, entries


def _entries_by_component(entries: Sequence[Any]) -> dict[str, Any]:
    return {entry.component: entry for entry in entries}


# --------------------------------------------------------------------------------------------
# The real environment
# --------------------------------------------------------------------------------------------


def test_every_runtime_distribution_has_an_entry_and_a_licence_text(
    script: ModuleType, collected: Collected
) -> None:
    out, entries = collected
    by_name = {script.normalize_name(entry.component): entry for entry in entries}
    dists = script.runtime_distributions()
    assert dists
    for dist in dists:
        entry = by_name[script.normalize_name(dist.name)]
        assert entry.files, f"{dist.name}: no licence file"
        for relative in entry.files:
            path = out / relative
            assert path.is_file(), f"{dist.name}: missing {relative}"
            assert path.stat().st_size > 0, f"{dist.name}: empty {relative}"


def test_pyside_entries_record_the_or_expression_and_ship_the_lgpl_text(
    script: ModuleType, collected: Collected
) -> None:
    out, entries = collected
    by_name = {script.normalize_name(entry.component): entry for entry in entries}
    lgpl = (SOURCES / "LGPL-3.0.txt").read_bytes()
    for name in ("pyside6", "shiboken6"):
        entry = by_name[name]
        assert entry.declared == PYSIDE_DECLARED
        assert entry.chosen == "LGPL-3.0-only"
        assert (out / name / "LGPL-3.0.txt").read_bytes() == lgpl
    commercial = [p for p in out.rglob("*") if "commercial" in p.name.lower()]
    assert not commercial, f"commercial pointer copied: {commercial}"


def test_explicit_entries(collected: Collected) -> None:
    _out, entries = collected
    by_component = _entries_by_component(entries)
    expected = {
        "Qt (core modules and Qt for Python bindings)": "LGPL-3.0-only",
        "Qt Charts": "GPL-3.0-only",
        "CPython": "PSF-2.0",
        "OpenSSL (bundled with CPython and cryptography)": "Apache-2.0",
        "Unicode CLDR data (countries.json)": "Unicode-3.0",
        "Microsoft Visual C++ runtime": "LicenseRef-Microsoft-VC-Redist",
        "cbrn-readiness-dashboard": "GPL-3.0-or-later",
    }
    for component, chosen in expected.items():
        assert component in by_component, component
        assert by_component[component].chosen == chosen, component


def test_qt_charts_is_a_separate_entry_with_the_qt_version(
    release: ModuleType, collected: Collected
) -> None:
    _out, entries = collected
    by_component = _entries_by_component(entries)
    charts = by_component["Qt Charts"]
    qt = by_component["Qt (core modules and Qt for Python bindings)"]
    assert charts is not qt
    _pyside_version, qt_version = release.read_qt_versions()
    assert charts.version == qt_version
    assert charts.files == ("GPL-3.0.txt", "SOURCE-OFFER.md")


def test_qt_entry_lists_the_vendored_notices_of_the_bundled_qt_version(
    release: ModuleType, collected: Collected
) -> None:
    out, entries = collected
    qt = _entries_by_component(entries)["Qt (core modules and Qt for Python bindings)"]
    assert "QT-THIRD-PARTY-NOTICES.txt" in qt.files
    assert "QT-THIRD-PARTY.md" in qt.files
    _pyside_version, qt_version = release.read_qt_versions()
    text = (out / "QT-THIRD-PARTY-NOTICES.txt").read_text(encoding="utf-8")
    assert f"\nQt version: {qt_version}\n" in text
    assert (out / "QT-THIRD-PARTY-NOTICES.txt").read_bytes() == (
        SOURCES / "qt-attributions" / "QT-THIRD-PARTY-NOTICES.txt"
    ).read_bytes().replace(b"\r\n", b"\n")
    pointer = (out / "QT-THIRD-PARTY.md").read_text(encoding="utf-8")
    assert "QT-THIRD-PARTY-NOTICES.txt" in pointer
    assert "https://doc.qt.io/qt-6/licenses-used-in-qt.html" in pointer
    assert "Known limitation" not in pointer


def test_the_vendored_qt_notices_must_exist(script: ModuleType, tmp_path: Path) -> None:
    with pytest.raises(script.LicenseError, match="Missing vendored Qt notices"):
        script._copy_qt_notices(tmp_path / "absent.txt", tmp_path / "out", "6.12.0")
    assert not (tmp_path / "out").exists()


def test_the_vendored_qt_notices_must_state_the_bundled_qt_version(
    script: ModuleType, tmp_path: Path
) -> None:
    source = tmp_path / "QT-THIRD-PARTY-NOTICES.txt"
    source.write_text("Qt third-party notices\n\nQt version: 6.11.2\n", encoding="utf-8")
    with pytest.raises(script.LicenseError, match=r"for Qt 6\.11\.2.*bundled Qt is 6\.12\.0"):
        script._copy_qt_notices(source, tmp_path / "out", "6.12.0")
    source.write_text("no version line here\n", encoding="utf-8")
    with pytest.raises(script.LicenseError, match="unknown version"):
        script._copy_qt_notices(source, tmp_path / "out", "6.12.0")
    source.write_bytes(b"Qt third-party notices\r\n\r\nQt version: 6.12.0\r\n")
    assert script._copy_qt_notices(source, tmp_path / "out", "6.12.0") == (
        "QT-THIRD-PARTY-NOTICES.txt"
    )
    copied = (tmp_path / "out" / "QT-THIRD-PARTY-NOTICES.txt").read_bytes()
    assert copied == b"Qt third-party notices\n\nQt version: 6.12.0\n"


def test_collect_fails_when_the_bundled_qt_is_not_the_one_of_the_notices(
    script: ModuleType, tmp_path: Path
) -> None:
    with pytest.raises(script.LicenseError, match=r"bundled Qt is 9\.9\.9"):
        script.collect(
            tmp_path / "out",
            repo_root=ROOT,
            distributions=[],
            qt_versions=("9.9.9", "9.9.9"),
            allow_missing_pyinstaller=True,
        )


def test_pyinstaller_entry_carries_the_bootloader_exception(
    script: ModuleType, collected: Collected
) -> None:
    out, entries = collected
    by_component = _entries_by_component(entries)
    if script.pyinstaller_distribution() is None:
        assert "PyInstaller bootloader" not in by_component
        pytest.skip("PyInstaller is not installed")
    entry = by_component["PyInstaller bootloader"]
    assert entry.chosen == "GPL-2.0-or-later WITH Bootloader-exception"
    assert "bootloader exception" in entry.note.lower()
    text = (out / "pyinstaller" / "COPYING.txt").read_text(encoding="utf-8")
    assert "bootloader" in text.lower()
    assert "exception" in text.lower()


@pytest.mark.parametrize(
    "relative",
    [
        "GPL-3.0.txt",
        "LGPL-3.0.txt",
        "Apache-2.0.txt",
        "Unicode-3.0.txt",
        "README.md",
        "QT-THIRD-PARTY.md",
        "QT-THIRD-PARTY-NOTICES.txt",
        "OPENSSL.md",
        "MSVC-RUNTIME.md",
        "SOURCE-OFFER.md",
        "index.json",
        "INDEX.md",
        "python-build-standalone/LICENSE.cpython.txt",
        "python-build-standalone/LICENSE.openssl-3.txt",
        "python-build-standalone/LICENSE.sqlite.txt",
    ],
)
def test_notice_files_are_present(collected: Collected, relative: str) -> None:
    out, _entries = collected
    path = out / relative
    assert path.is_file(), relative
    assert path.stat().st_size > 0, relative


def test_every_file_of_every_entry_exists(collected: Collected) -> None:
    out, entries = collected
    for entry in entries:
        for relative in entry.files:
            assert (out / relative).is_file(), f"{entry.component}: {relative}"


def test_source_offer_is_complete_and_links_the_exact_sources(
    release: ModuleType, collected: Collected
) -> None:
    out, _entries = collected
    text = (out / "SOURCE-OFFER.md").read_text(encoding="utf-8")
    assert "{{" not in text
    assert "}}" not in text
    pyside_version, qt_version = release.read_qt_versions()
    assert release.qt_source_url(qt_version) in text
    assert release.pyside_source_url(pyside_version) in text
    assert qt_version in text
    assert pyside_version in text


def test_source_offer_covers_every_locked_runtime_package(
    script: ModuleType, collected: Collected
) -> None:
    """P9-10: the offer lists every runtime package with the source URL ``uv.lock`` records."""
    out, _entries = collected
    text = (out / "SOURCE-OFFER.md").read_text(encoding="utf-8")
    locked = script.locked_sources(ROOT)
    assert locked, "uv.lock has no packages"
    for dist in script.runtime_distributions():
        url = locked[(script.normalize_name(dist.name), dist.version)]
        expected = url if url else "no source archive is recorded in uv.lock"
        assert f"- {dist.metadata['Name']} {dist.version}: {expected}" in text, dist.name
    assert "one-folder build" in text
    assert "scripts/build_exe.py" in text


def test_locked_sources_reads_sdist_urls_and_wheel_only_packages(
    script: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "uv.lock").write_text(
        "[[package]]\n"
        'name = "Has_Sdist"\n'
        'version = "1.0"\n'
        'sdist = { url = "https://example.invalid/has-sdist-1.0.tar.gz", hash = "sha256:00" }\n'
        "[[package]]\n"
        'name = "wheel-only"\n'
        'version = "2.0"\n',
        encoding="utf-8",
    )
    assert script.locked_sources(tmp_path) == {
        ("has-sdist", "1.0"): "https://example.invalid/has-sdist-1.0.tar.gz",
        ("wheel-only", "2.0"): None,
    }
    assert script.locked_sources(tmp_path / "missing") == {}


def test_msvc_notice_has_no_token_and_says_the_list_is_generated(collected: Collected) -> None:
    out, _entries = collected
    text = (out / "MSVC-RUNTIME.md").read_text(encoding="utf-8")
    assert "{{" not in text
    assert "generated when the bundle is built" in text


def test_msvc_notice_names_every_runtime_file_of_a_bundle(
    script: ModuleType, tmp_path: Path
) -> None:
    bundle = tmp_path / "bundle"
    for relative in (
        "_internal/vcruntime140.dll",
        "_internal/VCRUNTIME140_1.dll",
        "_internal/PySide6/msvcp140.dll",
        "_internal/PySide6/MSVCP140_1.dll",
        "_internal/PySide6/concrt140.dll",
        "_internal/PySide6/Qt6Core.dll",
        "_internal/shiboken6/MSVCP140.dll",
        "_internal/shiboken6/VCRUNTIME140.dll",
        "_internal/shiboken6/VCRUNTIME140_1.dll",
        "_internal/UCRTBASE.dll",
        "_internal/api-ms-win-crt-runtime-l1-1-0.dll",
        "_internal/API-MS-WIN-core-sysinfo-l1-2-0.dll",
    ):
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    files = script.msvc_runtime_files(bundle)
    assert files == sorted(
        [
            "_internal/PySide6/MSVCP140_1.dll",
            "_internal/PySide6/concrt140.dll",
            "_internal/PySide6/msvcp140.dll",
            "_internal/UCRTBASE.dll",
            "_internal/VCRUNTIME140_1.dll",
            "_internal/vcruntime140.dll",
            "_internal/API-MS-WIN-core-sysinfo-l1-2-0.dll",
            "_internal/api-ms-win-crt-runtime-l1-1-0.dll",
            "_internal/shiboken6/MSVCP140.dll",
            "_internal/shiboken6/VCRUNTIME140.dll",
            "_internal/shiboken6/VCRUNTIME140_1.dll",
        ]
    )
    template = (SOURCES / "MSVC-RUNTIME.md").read_text(encoding="utf-8")
    text = script.render_msvc_notice(template, files)
    for relative in files:
        assert f"`{relative}`" in text
    assert "Qt6Core" not in text
    assert script.msvc_runtime_files(None) is None


def test_msvc_notice_states_the_microsoft_terms(script: ModuleType) -> None:
    """Q21: the notice says whose files these are, under which terms, and what is not shipped."""
    template = (SOURCES / "MSVC-RUNTIME.md").read_text(encoding="utf-8")
    text = script.render_msvc_notice(template, ["_internal/vcruntime140.dll"])
    flat = " ".join(text.split())
    assert "not** covered by the GPL-3.0" in flat
    assert "redistributed unmodified" in flat
    assert "separate Microsoft component" in flat
    assert "notices that are inside the files are kept" in flat
    assert "No Microsoft trademark is used in the name of this program" in flat
    assert "Windows 10 (version 1809 or later) and Windows 11" in flat
    assert "always uses its own copy" in flat
    assert "https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution" in text
    assert "https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment" in text
    assert "LicenseRef-Microsoft-VC-Redist" in text


def test_msvc_notice_template_must_keep_its_token(script: ModuleType) -> None:
    with pytest.raises(script.LicenseError):
        script.render_msvc_notice("no token here\n", ["a.dll"])


def test_openssl_entry_records_what_cryptography_reports(collected: Collected) -> None:
    _out, entries = collected
    entry = _entries_by_component(entries)["OpenSSL (bundled with CPython and cryptography)"]
    assert "cryptography reports for its own backend:" in entry.note


def test_gpl_text_is_the_repository_licence_byte_for_byte(
    collected: Collected,
) -> None:
    out, _entries = collected
    assert (out / "GPL-3.0.txt").read_bytes() == (ROOT / "LICENSE").read_bytes()


def test_index_json_is_sorted_and_matches_index_md(collected: Collected) -> None:
    out, entries = collected
    data = json.loads((out / "index.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == len(entries)
    components = [item["component"] for item in data]
    assert components == sorted(components)
    assert len(set(components)) == len(components)
    for item in data:
        assert list(item) == ["component", "version", "declared", "chosen", "files", "note"]
        assert item["chosen"]
        assert isinstance(item["files"], list)
    markdown = (out / "INDEX.md").read_text(encoding="utf-8")
    for component in components:
        assert f"| {component} | " in markdown, component
    rows = [line for line in markdown.splitlines() if line.startswith("| ")]
    assert len(rows) == len(components) + 2  # header and separator


def test_generated_files_use_unix_line_ends(collected: Collected) -> None:
    out, _entries = collected
    for name in (
        "index.json",
        "INDEX.md",
        "SOURCE-OFFER.md",
        "README.md",
        "OPENSSL.md",
        "QT-THIRD-PARTY-NOTICES.txt",
    ):
        assert b"\r" not in (out / name).read_bytes(), name


def test_two_runs_produce_identical_folders(
    script: ModuleType, tmp_path: Path, collected: Collected
) -> None:
    out, _entries = collected
    second = tmp_path / "again"
    script.collect(
        second, repo_root=ROOT, allow_missing_pyinstaller=script.pyinstaller_distribution() is None
    )
    first_snapshot = _snapshot(out)
    assert first_snapshot
    assert _snapshot(second) == first_snapshot


def test_main_writes_the_folder_and_prints_the_count(
    script: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    if script.pyinstaller_distribution() is None:
        pytest.skip("PyInstaller is not installed")
    out = tmp_path / "cli"
    assert script.main(["--out", str(out)]) == 0
    printed = capsys.readouterr().out
    count = len(json.loads((out / "index.json").read_text(encoding="utf-8")))
    assert str(count) in printed


# --------------------------------------------------------------------------------------------
# Fake distributions
# --------------------------------------------------------------------------------------------


def _collect_fake(script: ModuleType, tmp_path: Path, dist: Distribution) -> list[Any]:
    return script.collect(
        tmp_path / "out",
        repo_root=ROOT,
        distributions=[dist],
        qt_versions=FAKE_VERSIONS,
        allow_missing_pyinstaller=True,
    )


def test_fake_distribution_without_licence_raises(script: ModuleType, tmp_path: Path) -> None:
    dist = make_distribution(tmp_path / "site", "mystery-pkg")
    with pytest.raises(script.LicenseError, match="mystery-pkg"):
        _collect_fake(script, tmp_path, dist)


def test_fake_distribution_with_disallowed_licence_raises(
    script: ModuleType, tmp_path: Path
) -> None:
    dist = make_distribution(tmp_path / "site", "bad-pkg", license_expression="GPL-2.0-only")
    with pytest.raises(script.LicenseError, match="bad-pkg"):
        _collect_fake(script, tmp_path, dist)


def test_fake_distribution_licence_files_are_copied(script: ModuleType, tmp_path: Path) -> None:
    dist = make_distribution(
        tmp_path / "site",
        "Fake_Pkg",
        license_expression="GPL-2.0-only OR MIT",
        license_files=[("LICENSE.txt", "MIT text of the fake package\n")],
    )
    entries = _collect_fake(script, tmp_path, dist)
    by_component = _entries_by_component(entries)
    entry = by_component["Fake_Pkg"]
    assert entry.chosen == "MIT"
    assert entry.declared == "GPL-2.0-only OR MIT"
    assert entry.files == ("fake-pkg/LICENSE.txt",)
    copied = (tmp_path / "out" / "fake-pkg" / "LICENSE.txt").read_text(encoding="utf-8")
    assert copied == "MIT text of the fake package\n"


def test_fake_distribution_without_text_gets_the_standard_text(
    script: ModuleType, tmp_path: Path
) -> None:
    dist = make_distribution(tmp_path / "site", "bare-pkg", license_expression="Apache-2.0")
    entries = _collect_fake(script, tmp_path, dist)
    entry = _entries_by_component(entries)["bare-pkg"]
    assert entry.files == ("bare-pkg/Apache-2.0.txt",)
    copied = (tmp_path / "out" / "bare-pkg" / "Apache-2.0.txt").read_bytes()
    assert copied == (SOURCES / "Apache-2.0.txt").read_bytes()


def test_fake_distribution_with_mit_and_no_text_raises(script: ModuleType, tmp_path: Path) -> None:
    dist = make_distribution(tmp_path / "site", "textless", license_expression="MIT")
    with pytest.raises(script.LicenseError, match="no licence text"):
        _collect_fake(script, tmp_path, dist)


def test_missing_pyinstaller_raises_unless_allowed(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(script, "pyinstaller_distribution", lambda: None)
    dist = make_distribution(tmp_path / "site", "bare-pkg", license_expression="Apache-2.0")
    with pytest.raises(script.LicenseError, match="PyInstaller"):
        script.collect(
            tmp_path / "strict",
            repo_root=ROOT,
            distributions=[dist],
            qt_versions=FAKE_VERSIONS,
        )
    entries = _collect_fake(script, tmp_path, dist)
    assert "PyInstaller bootloader" not in _entries_by_component(entries)
