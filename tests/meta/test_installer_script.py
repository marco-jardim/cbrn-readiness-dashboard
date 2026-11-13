# SPDX-License-Identifier: GPL-3.0-or-later
"""The Inno Setup script of the per-user installer keeps its promises (checks on the text).

Inno Setup is not needed here: the script is read as text. What is checked: a fixed AppId that
the smoke test knows too, installation without administrator rights, the three languages, the
files that come from the bundle folder (and no ``portable.ini``), no deletion of user data on
uninstall, the Windows version floor, and the notices the wizard shows.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER_DIR = ROOT / "packaging" / "installer"
ISS = INSTALLER_DIR / "cbrn-dashboard.iss"
SMOKE = ROOT / "scripts" / "smoke_installer.ps1"
PACKAGING_TEST = ROOT / "tests" / "packaging" / "test_installer.py"
ICON = ROOT / "src" / "cbrn_dashboard" / "resources" / "app.ico"
APP_ID = "7C3F2A58-5E1B-4D6A-9B84-2F0D1C9E6A31"
LANGUAGES = ("pt-BR", "en-US", "es-ES")
SECTION = re.compile(r"^\[(?P<name>[A-Za-z]+)\]\s*$")


def _text() -> str:
    return ISS.read_text(encoding="utf-8")


def _code_lines(text: str) -> list[str]:
    """The lines without blanks and ``;`` comment lines."""
    return [line.strip() for line in text.splitlines() if line.strip() and line[0] != ";"]


def _sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = ""
    for line in _code_lines(text):
        match = SECTION.match(line)
        if match is not None:
            current = match.group("name")
            sections.setdefault(current, [])
        elif current:
            sections[current].append(line)
    return sections


def _setup() -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in _sections(_text())["Setup"]:
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            entries[key.strip()] = value.strip()
    return entries


def test_the_script_and_its_notices_exist_and_are_ascii() -> None:
    names = [ISS.name, *(f"before-install.{language}.txt" for language in LANGUAGES)]
    for name in names:
        raw = (INSTALLER_DIR / name).read_bytes()
        assert raw.isascii(), f"{name} is not ASCII"
        assert not raw.startswith(b"\xef\xbb\xbf"), name
    assert ICON.is_file()


def test_the_app_id_is_fixed_and_escaped_for_inno() -> None:
    assert re.fullmatch(r"\{\{[0-9A-F]{8}(-[0-9A-F]{4}){3}-[0-9A-F]{12}\}", _setup()["AppId"])
    assert _text().count("AppId=") == 1


def test_the_smoke_test_uses_the_same_app_id() -> None:
    assert "{" + APP_ID + "}" in SMOKE.read_text(encoding="utf-8")
    assert _setup()["AppId"] == "{{" + APP_ID + "}"


def test_the_names_and_urls_of_the_program() -> None:
    text = _text()
    setup = _setup()
    assert '#define AppName "CBRN Readiness Dashboard"' in text
    assert '#define AppExeName "cbrn-dashboard.exe"' in text
    assert setup["AppName"] == "{#AppName}"
    assert setup["AppVersion"] == "{#AppVersion}"
    assert setup["AppVerName"] == "{#AppName} {#AppVersion}"
    assert setup["AppPublisher"] == "Marco Jardim"
    repository = "https://github.com/marco-jardim/cbrn-readiness-dashboard"
    assert f'#define AppUrl "{repository}"' in text
    assert setup["AppPublisherURL"] == "{#AppUrl}"
    assert setup["AppSupportURL"] == "{#AppUrl}"
    assert setup["UninstallDisplayIcon"] == r"{app}\{#AppExeName}"


def test_the_version_and_the_paths_come_from_defines_that_must_be_given() -> None:
    text = _text()
    for name in ("AppVersion", "BundleDir", "OutputDir", "OutputBaseFilename"):
        assert f"#ifndef {name}" in text, name
        assert "#error" in text
    setup = _setup()
    assert setup["OutputDir"] == "{#OutputDir}"
    assert setup["OutputBaseFilename"] == "{#OutputBaseFilename}"


def test_the_installation_needs_no_administrator_rights() -> None:
    setup = _setup()
    assert setup["PrivilegesRequired"] == "lowest"
    assert setup["PrivilegesRequiredOverridesAllowed"] == "dialog"
    assert setup["DefaultDirName"] == r"{autopf}\{#AppName}"


def test_the_target_systems() -> None:
    setup = _setup()
    assert setup["ArchitecturesAllowed"] == "x64compatible"
    assert setup["ArchitecturesInstallIn64BitMode"] == "x64compatible"
    assert setup["MinVersion"] == "10.0.17763"
    assert setup["WizardStyle"] == "modern"
    assert setup["Compression"] == "lzma2/ultra64"
    assert setup["SolidCompression"] == "yes"
    assert setup["DisableProgramGroupPage"] == "yes"
    assert setup["SetupLogging"] == "yes"
    assert setup["CloseApplications"] == "yes"
    assert setup["RestartApplications"] == "no"
    assert setup["ShowLanguageDialog"] == "auto"


def test_the_icon_and_the_licence_point_at_files_of_the_repository() -> None:
    setup = _setup()
    for key in ("SetupIconFile", "LicenseFile"):
        target = (INSTALLER_DIR / setup[key].replace("\\", "/")).resolve()
        assert target.is_file(), f"{key} -> {target}"
    assert (INSTALLER_DIR / setup["SetupIconFile"].replace("\\", "/")).resolve() == ICON
    assert (INSTALLER_DIR / setup["LicenseFile"].replace("\\", "/")).resolve() == ROOT / "LICENSE"
    assert "GNU GENERAL PUBLIC LICENSE" in (ROOT / "LICENSE").read_text(encoding="utf-8")


def test_there_are_three_languages_each_with_its_own_notice() -> None:
    lines = _sections(_text())["Languages"]
    assert len(lines) == 3
    joined = "\n".join(lines)
    assert 'MessagesFile: "compiler:Default.isl"' in joined
    assert r'MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"' in joined
    assert r'MessagesFile: "compiler:Languages\Spanish.isl"' in joined
    names = (("english", "en-US"), ("brazilianportuguese", "pt-BR"), ("spanish", "es-ES"))
    for name, language in names:
        line = next(item for item in lines if item.startswith(f'Name: "{name}"'))
        assert f'InfoBeforeFile: "before-install.{language}.txt"' in line


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_notice_says_what_the_first_run_notes_say(language: str) -> None:
    path = INSTALLER_DIR / f"before-install.{language}.txt"
    text = " ".join(path.read_text(encoding="ascii").split())
    data_folder = "%LOCALAPPDATA%\\cbrn-readiness-dashboard"
    for needle in ("Q19", "Q4", "Q11", "Q13", data_folder, "--demo"):
        assert needle in text, (language, needle)
    assert len(text) < 1500  # short on purpose


def test_the_files_come_from_the_bundle_folder_and_never_install_portable_mode() -> None:
    files = _sections(_text())["Files"]
    bundle = next(line for line in files if "{#BundleDir}" in line)
    assert bundle.startswith(r'Source: "{#BundleDir}\*"')
    assert 'DestDir: "{app}"' in bundle
    for flag in ("ignoreversion", "recursesubdirs", "createallsubdirs"):
        assert flag in bundle
    excludes = re.search(r'Excludes: "([^"]*)"', bundle)
    assert excludes is not None
    assert set(excludes.group(1).split(",")) == {"portable.ini", "portable.ini.example"}
    for line in files:
        assert 'DestDir: "{app}"' in line, line
        assert "{localappdata}" not in line.lower()
        assert "{userappdata}" not in line.lower()
    # portable.ini appears only to be excluded.
    code = "\n".join(_code_lines(_text()))
    assert re.findall(r"portable\.ini(?:\.example)?", code) == [
        "portable.ini",
        "portable.ini.example",
    ]
    for line in files[1:]:
        source = re.match(r'Source: "([^"]+)"', line)
        assert source is not None
        assert (INSTALLER_DIR / source.group(1).replace("\\", "/")).resolve().is_file(), line


def test_the_uninstaller_never_deletes_user_data() -> None:
    sections = _sections(_text())
    assert "UninstallDelete" not in sections
    assert "UninstallRun" not in sections
    assert "Registry" not in sections  # only the uninstall entry that Inno writes itself
    code = "\n".join(_code_lines(_text())).lower()
    # The only deletion at install time is the old program folder of an upgrade.
    assert sections["InstallDelete"] == [r'Type: filesandordirs; Name: "{app}\_internal"']
    assert "appmutex" not in code


def test_shortcuts_and_the_launch_option() -> None:
    sections = _sections(_text())
    icons = "\n".join(sections["Icons"])
    assert r'Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"' in icons
    assert "desktopicon" in icons
    (task,) = sections["Tasks"]
    assert task.startswith('Name: "desktopicon"')
    assert "Flags: unchecked" in task
    (run,) = sections["Run"]
    assert "postinstall" in run
    assert "skipifsilent" in run
    assert "nowait" in run


def test_the_smoke_script_makes_the_checks_the_release_relies_on() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    for needle in (
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CURRENTUSER",
        "/DIR=",
        "/LOG=",
        "--self-test",
        "--data-dir",
        "selftest.json",
        "passed",
        "unins000.exe",
        "portable.ini",
        "the uninstall deleted the data folder",
        "exit 2",
        "exit 1",
    ):
        assert needle in text, needle
    # Nothing in it needs administrator rights or the network.
    assert "RunAs" not in text
    assert "Invoke-WebRequest" not in text


def test_the_packaging_test_is_skipped_only_outside_github_actions() -> None:
    text = PACKAGING_TEST.read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.packaging" in text
    assert '"GITHUB_ACTIONS"' in text
    assert '== "true"' in text
    fail = text.index("pytest.fail(")
    skip = text.index("pytest.skip(")
    guard = text.index("if must_not_skip(os.environ):")
    assert guard < fail < skip, "on GitHub Actions a missing ISCC must fail before it can skip"
    assert "smoke_installer.ps1" in text
