# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline tests of ``scripts/build_installer.py``: the pure helpers and a run with a fake ISCC."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_installer.py"
ISS_PATH = ROOT / "packaging" / "installer" / "cbrn-dashboard.iss"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cbrn_build_installer_under_test", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _never_on_path(_name: str) -> str | None:
    return None


def _files(*present: str) -> object:
    existing = {Path(item) for item in present}

    def is_file(path: Path) -> bool:
        return path in existing

    return is_file


# --- names and versions ----------------------------------------------------------------------


def test_the_file_name_is_the_release_name(script: ModuleType) -> None:
    assert script.installer_base_name("1.0.2") == "cbrn-readiness-dashboard-1.0.2-win-x64-setup"
    expected = "cbrn-readiness-dashboard-1.0.2-win-x64-setup.exe"
    assert script.installer_file_name("1.0.2") == expected
    assert script.installer_file_name("1.1.0rc1").endswith("-1.1.0rc1-win-x64-setup.exe")
    assert script.installer_file_name("1.0.2").endswith(script.INSTALLER_SUFFIX)


def test_the_file_name_matches_the_zip_name_of_the_release_script(script: ModuleType) -> None:
    spec = importlib.util.spec_from_file_location(
        "cbrn_release_zip_for_names", ROOT / "scripts" / "make_release_zip.py"
    )
    assert spec is not None
    assert spec.loader is not None
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    zip_name = release.zip_file_name("1.0.2")
    assert zip_name.removesuffix(".zip") + "-setup.exe" == script.installer_file_name("1.0.2")
    assert release.INSTALLER_SUFFIX == script.INSTALLER_SUFFIX


@pytest.mark.parametrize(
    "version", ["1.0", "v1.0.2", "", "1.0.2 ", "1.0.2;rm", "1.0.2\n", "a.b.c", "1.0.2/..\\x"]
)
def test_a_bad_version_is_refused(script: ModuleType, version: str) -> None:
    with pytest.raises(script.InstallerError, match="valid version"):
        script.installer_file_name(version)
    with pytest.raises(script.InstallerError, match="valid version"):
        script.numeric_version(version)


def test_the_numeric_version_has_four_numbers(script: ModuleType) -> None:
    assert script.numeric_version("1.0.2") == "1.0.2.0"
    assert script.numeric_version("12.34.56rc1") == "12.34.56.0"


def test_the_package_version_is_read_as_text(script: ModuleType, tmp_path: Path) -> None:
    init = tmp_path / "__init__.py"
    init.write_text('"""Doc."""\n__version__ = "3.2.1"\n', encoding="utf-8")
    assert script.read_package_version(init) == "3.2.1"
    init.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(script.InstallerError, match="__version__"):
        script.read_package_version(init)
    assert script.read_package_version() == script.read_package_version(script.INIT_FILE)


# --- the lookup of ISCC.exe ------------------------------------------------------------------

X86 = r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
X64 = r"C:\Program Files\Inno Setup 6\ISCC.exe"
USER = r"C:\Users\me\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
ENVIRONMENT = {
    "ProgramFiles(x86)": r"C:\Program Files (x86)",
    "ProgramFiles": r"C:\Program Files",
    "LOCALAPPDATA": r"C:\Users\me\AppData\Local",
}


def test_the_standard_locations_are_in_the_documented_order(script: ModuleType) -> None:
    places = [str(place) for place in script.standard_iscc_locations(ENVIRONMENT)]
    assert [place.replace("/", "\\") for place in places] == [X86, X64, USER]


def test_the_standard_locations_work_without_variables(script: ModuleType) -> None:
    places = [str(place).replace("/", "\\") for place in script.standard_iscc_locations({})]
    assert places == [X86, X64]


def test_the_argument_wins_over_everything(script: ModuleType) -> None:
    environment = {**ENVIRONMENT, "ISCC": r"D:\env\ISCC.exe"}
    is_file = _files(r"D:\arg\ISCC.exe", r"D:\env\ISCC.exe", X86)
    explicit = Path(r"D:\arg\ISCC.exe")
    found = script.find_iscc(explicit, environment, lambda _n: r"D:\p\iscc", is_file)
    assert found == explicit


def test_the_environment_variable_is_second(script: ModuleType) -> None:
    environment = {**ENVIRONMENT, "ISCC": r"D:\env\ISCC.exe"}
    is_file = _files(r"D:\env\ISCC.exe", X86)
    found = script.find_iscc(None, environment, lambda _n: r"D:\p\iscc", is_file)
    assert found == Path(r"D:\env\ISCC.exe")


def test_path_is_third_and_the_standard_places_are_last(script: ModuleType) -> None:
    is_file = _files(X86, USER)
    assert script.find_iscc(None, ENVIRONMENT, lambda _n: r"D:\p\iscc.EXE", is_file) == Path(
        r"D:\p\iscc.EXE"
    )
    assert script.find_iscc(None, ENVIRONMENT, _never_on_path, is_file) == Path(X86)
    assert script.find_iscc(None, ENVIRONMENT, _never_on_path, _files(USER)) == Path(USER)
    assert script.find_iscc(None, ENVIRONMENT, _never_on_path, _files(X64, USER)) == Path(X64)


def test_a_wrong_explicit_path_or_variable_is_an_error_not_a_fall_through(
    script: ModuleType,
) -> None:
    is_file = _files(X86)
    with pytest.raises(script.InstallerError, match="--iscc"):
        script.find_iscc(Path(r"D:\typo\ISCC.exe"), ENVIRONMENT, _never_on_path, is_file)
    with pytest.raises(script.InstallerError, match="variable ISCC"):
        script.find_iscc(None, {**ENVIRONMENT, "ISCC": r"D:\typo"}, _never_on_path, is_file)
    # An empty variable counts as not set.
    blank = {**ENVIRONMENT, "ISCC": " "}
    assert script.find_iscc(None, blank, _never_on_path, is_file) == Path(X86)


def test_a_missing_compiler_is_reported_clearly(script: ModuleType) -> None:
    with pytest.raises(script.InstallerError) as raised:
        script.find_iscc(None, ENVIRONMENT, _never_on_path, _files())
    message = str(raised.value)
    assert "ISCC.exe" in message
    assert "--iscc" in message
    assert "Inno Setup" in message
    assert X86.replace("\\", "/") in message.replace("\\", "/")


# --- the command line of ISCC ----------------------------------------------------------------


def test_the_arguments_carry_every_define_and_end_with_the_script(script: ModuleType) -> None:
    arguments = script.iscc_arguments(
        Path(r"C:\Inno\ISCC.exe"),
        Path(r"C:\repo\packaging\installer\cbrn-dashboard.iss"),
        "1.0.2",
        Path(r"C:\work\bundle"),
        Path(r"C:\work\release"),
    )
    assert arguments[0] == r"C:\Inno\ISCC.exe"
    assert arguments[1] == "/Q"
    assert arguments[-1] == r"C:\repo\packaging\installer\cbrn-dashboard.iss"
    defines = dict(item[2:].split("=", 1) for item in arguments if item.startswith("/D"))
    assert defines == {
        "AppVersion": "1.0.2",
        "VersionInfoVersion": "1.0.2.0",
        "BundleDir": r"C:\work\bundle",
        "OutputDir": r"C:\work\release",
        "OutputBaseFilename": "cbrn-readiness-dashboard-1.0.2-win-x64-setup",
    }


def test_verbose_leaves_out_the_quiet_flag(script: ModuleType) -> None:
    arguments = script.iscc_arguments(
        Path("ISCC.exe"), Path("a.iss"), "1.0.2", Path("b"), Path("o"), quiet=False
    )
    assert "/Q" not in arguments


def test_every_define_the_arguments_pass_is_used_by_the_script(script: ModuleType) -> None:
    text = ISS_PATH.read_text(encoding="utf-8")
    arguments = script.iscc_arguments(Path("ISCC.exe"), ISS_PATH, "1.0.2", Path("b"), Path("o"))
    for item in arguments:
        if item.startswith("/D"):
            assert "{#" + item[2:].split("=", 1)[0] + "}" in text, item


# --- the build, with a fake compiler ---------------------------------------------------------


def _bundle(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "cbrn-dashboard.exe").write_bytes(b"MZ")
    return folder


def test_the_build_refuses_a_folder_that_is_not_a_bundle(
    script: ModuleType, tmp_path: Path
) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(script.InstallerError, match=r"cbrn-dashboard\.exe"):
        script.build_installer(tmp_path / "empty", tmp_path / "out", "1.0.2", Path("ISCC.exe"))


def test_the_build_checks_the_exit_code_and_the_output(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    out = tmp_path / "out"
    calls: list[list[str]] = []

    class Done:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    def fail(arguments: list[str], **_kwargs: object) -> Done:
        calls.append(arguments)
        return Done(1)

    monkeypatch.setattr(script.subprocess, "run", fail)
    with pytest.raises(script.InstallerError, match="exit code 1"):
        script.build_installer(bundle, out, "1.0.2", Path("ISCC.exe"), ISS_PATH)

    def succeed_without_output(arguments: list[str], **_kwargs: object) -> Done:
        calls.append(arguments)
        return Done(0)

    monkeypatch.setattr(script.subprocess, "run", succeed_without_output)
    with pytest.raises(script.InstallerError, match="does not exist"):
        script.build_installer(bundle, out, "1.0.2", Path("ISCC.exe"), ISS_PATH)

    def succeed(arguments: list[str], **_kwargs: object) -> Done:
        calls.append(arguments)
        (out / "cbrn-readiness-dashboard-1.0.2-win-x64-setup.exe").write_bytes(b"MZ setup")
        return Done(0)

    monkeypatch.setattr(script.subprocess, "run", succeed)
    built = script.build_installer(bundle, out, "1.0.2", Path("ISCC.exe"), ISS_PATH)
    assert built == out.resolve() / "cbrn-readiness-dashboard-1.0.2-win-x64-setup.exe"
    assert len(calls) == 3
    assert f"/DBundleDir={bundle.resolve()}" in calls[-1]


def test_a_stale_setup_file_is_not_taken_for_a_new_one(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    out = tmp_path / "out"
    out.mkdir()
    stale = out / "cbrn-readiness-dashboard-1.0.2-win-x64-setup.exe"
    stale.write_bytes(b"old")

    class Done:
        returncode = 0

    monkeypatch.setattr(script.subprocess, "run", lambda *_a, **_k: Done())
    with pytest.raises(script.InstallerError, match="does not exist"):
        script.build_installer(bundle, out, "1.0.2", Path("ISCC.exe"), ISS_PATH)


def test_main_reports_a_missing_compiler_with_exit_code_1(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    monkeypatch.delenv("ISCC", raising=False)
    monkeypatch.setattr(script.shutil, "which", _never_on_path)
    monkeypatch.setattr(script, "standard_iscc_locations", lambda _environ: [tmp_path / "none"])
    code = script.main(["--bundle-dir", str(bundle), "--out-dir", str(tmp_path / "out")])
    assert code == 1
    assert "ISCC.exe" in capsys.readouterr().err


def test_main_prints_the_path_and_the_size(
    script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path / "bundle")
    fake_iscc = tmp_path / "ISCC.exe"
    fake_iscc.write_bytes(b"x")
    out = tmp_path / "out"

    class Done:
        returncode = 0

    def run(arguments: list[str], **_kwargs: object) -> Done:
        (out / "cbrn-readiness-dashboard-9.9.9-win-x64-setup.exe").write_bytes(b"MZ" * 1024)
        return Done()

    monkeypatch.setattr(script.subprocess, "run", run)
    args = ["--bundle-dir", str(bundle), "--out-dir", str(out), "--version", "9.9.9"]
    assert script.main([*args, "--iscc", str(fake_iscc), "--script", str(ISS_PATH)]) == 0
    printed = capsys.readouterr().out
    assert "cbrn-readiness-dashboard-9.9.9-win-x64-setup.exe" in printed
    assert "size:" in printed
    assert "2048 bytes" in printed


def test_the_script_is_ascii_and_fits_the_line_length() -> None:
    text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert text.isascii()
    assert max(len(line) for line in text.splitlines()) <= 100
    assert text.startswith("# SPDX-License-Identifier: GPL-3.0-or-later\n")
