# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for data-location resolution (T0.5). Never touches the real profile or network."""

from __future__ import annotations

import json
import stat
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from cbrn_dashboard.paths import (
    APP_DIR_NAME,
    CLOUD_PLACEHOLDER_MASK,
    DATABASE_FILE_NAME,
    ENV_VAR,
    FILE_ATTRIBUTE_OFFLINE,
    FILE_ATTRIBUTE_PINNED,
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
    FILE_ATTRIBUTE_RECALL_ON_OPEN,
    FILE_ATTRIBUTE_UNPINNED,
    POINTER_FILE_NAME,
    PORTABLE_MARKER,
    DataLocation,
    LocationSource,
    LocationWarning,
    Probes,
    create_directory,
    is_file_writable,
    is_unc_path,
    probe_directory_writable,
    resolve_data_location,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")

# Probes that never leave tmp_path: real folder creation and writability, nothing else.
QUIET = Probes(
    writable=probe_directory_writable,
    network_drive=lambda _path: False,
    onedrive_mounts=lambda: (),
    attributes=lambda _path: 0,
    ensure_directory=create_directory,
)


@pytest.fixture
def local_appdata(tmp_path: Path) -> Path:
    return tmp_path / "LocalAppData"


@pytest.fixture
def env(local_appdata: Path) -> dict[str, str]:
    """Injected environment: LOCALAPPDATA inside tmp_path, nothing else."""
    return {"LOCALAPPDATA": str(local_appdata)}


@pytest.fixture
def default_dir(local_appdata: Path) -> Path:
    return local_appdata / APP_DIR_NAME


@pytest.fixture
def exe(tmp_path: Path) -> Path:
    """A simulated executable path; its folder exists but the file itself is never used."""
    folder = tmp_path / "app"
    folder.mkdir()
    return folder / "cbrn-dashboard.exe"


def write_pointer(local_appdata: Path, content: str) -> Path:
    folder = local_appdata / APP_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    pointer = folder / POINTER_FILE_NAME
    pointer.write_text(content, encoding="utf-8")
    return pointer


def pointer_to(local_appdata: Path, target: Path) -> None:
    write_pointer(local_appdata, json.dumps({"data_dir": str(target)}))


def resolve(
    env: dict[str, str],
    exe: Path,
    *,
    cli: str | Path | None = None,
    frozen: bool = False,
    probes: Probes = QUIET,
) -> DataLocation:
    return resolve_data_location(
        cli_data_dir=cli, environ=env, executable=exe, frozen=frozen, probes=probes
    )


# ---------------------------------------------------------------- precedence


def test_default_location(env: dict[str, str], exe: Path, default_dir: Path) -> None:
    result = resolve(env, exe)
    assert result.path == default_dir
    assert result.source is LocationSource.DEFAULT
    assert result.writable is True
    assert result.warnings == ()
    assert default_dir.is_dir()


def test_cli_beats_everything(
    env: dict[str, str], exe: Path, local_appdata: Path, tmp_path: Path
) -> None:
    cli_dir = tmp_path / "from-cli"
    env[ENV_VAR] = str(tmp_path / "from-env")
    (exe.parent / PORTABLE_MARKER).write_text("", encoding="utf-8")
    pointer_to(local_appdata, tmp_path / "from-pointer")
    result = resolve(env, exe, cli=cli_dir, frozen=True)
    assert result.path == cli_dir
    assert result.source is LocationSource.CLI
    assert result.writable is True


def test_env_beats_portable_pointer_default(
    env: dict[str, str], exe: Path, local_appdata: Path, tmp_path: Path
) -> None:
    env_dir = tmp_path / "from-env"
    env[ENV_VAR] = str(env_dir)
    (exe.parent / PORTABLE_MARKER).write_text("", encoding="utf-8")
    pointer_to(local_appdata, tmp_path / "from-pointer")
    result = resolve(env, exe, frozen=True)
    assert result.path == env_dir
    assert result.source is LocationSource.ENV


def test_portable_beats_pointer_and_default(
    env: dict[str, str], exe: Path, local_appdata: Path, tmp_path: Path
) -> None:
    (exe.parent / PORTABLE_MARKER).write_text("", encoding="utf-8")
    pointer_to(local_appdata, tmp_path / "from-pointer")
    result = resolve(env, exe, frozen=True)
    assert result.path == exe.parent / "data"
    assert result.source is LocationSource.PORTABLE
    assert result.writable is True
    assert (exe.parent / "data").is_dir()
    assert not (tmp_path / "from-pointer").exists()


def test_pointer_beats_default(
    env: dict[str, str], exe: Path, local_appdata: Path, tmp_path: Path
) -> None:
    target = tmp_path / "chosen"
    pointer_to(local_appdata, target)
    result = resolve(env, exe)
    assert result.path == target
    assert result.source is LocationSource.POINTER
    assert result.writable is True
    assert result.warnings == ()
    assert target.is_dir()


def test_missing_pointer_falls_through_silently(
    env: dict[str, str], exe: Path, default_dir: Path
) -> None:
    result = resolve(env, exe)
    assert result.source is LocationSource.DEFAULT
    assert result.path == default_dir
    assert LocationWarning.POINTER_INVALID not in result.warnings


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "",
        "[]",
        '"just a string"',
        "{}",
        '{"data_dir": 5}',
        '{"data_dir": ""}',
        '{"data_dir": "   "}',
        '{"data_dir": "relative\\\\folder"}',
        '{"data_dir": "relative/folder"}',
        '{"other": "C:\\\\x"}',
    ],
)
def test_corrupt_pointer_falls_through_with_warning(
    env: dict[str, str], exe: Path, local_appdata: Path, default_dir: Path, content: str
) -> None:
    write_pointer(local_appdata, content)
    result = resolve(env, exe)
    assert result.path == default_dir
    assert result.source is LocationSource.DEFAULT
    assert result.warnings == (LocationWarning.POINTER_INVALID,)


def test_undecodable_pointer_falls_through_with_warning(
    env: dict[str, str], exe: Path, local_appdata: Path, default_dir: Path
) -> None:
    pointer = write_pointer(local_appdata, "{}")
    pointer.write_bytes(b"\xff\xfe\x00\x80")
    result = resolve(env, exe)
    assert result.source is LocationSource.DEFAULT
    assert result.warnings == (LocationWarning.POINTER_INVALID,)


def test_pointer_that_is_a_directory_falls_through_with_warning(
    env: dict[str, str], exe: Path, default_dir: Path
) -> None:
    (default_dir / POINTER_FILE_NAME).mkdir(parents=True)
    result = resolve(env, exe)
    assert result.source is LocationSource.DEFAULT
    assert result.warnings == (LocationWarning.POINTER_INVALID,)


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_cli_and_env_are_absent(
    env: dict[str, str], exe: Path, default_dir: Path, blank: str
) -> None:
    env[ENV_VAR] = blank
    result = resolve(env, exe, cli=blank)
    assert result.source is LocationSource.DEFAULT
    assert result.path == default_dir


def test_blank_cli_falls_to_env(env: dict[str, str], exe: Path, tmp_path: Path) -> None:
    env[ENV_VAR] = str(tmp_path / "from-env")
    result = resolve(env, exe, cli="  ")
    assert result.source is LocationSource.ENV


def test_relative_cli_path_becomes_absolute(
    env: dict[str, str], exe: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = resolve(env, exe, cli="relative-data")
    assert result.path.is_absolute()
    assert result.path == tmp_path / "relative-data"
    assert result.path.is_dir()


def test_os_environ_is_the_default_environment(
    exe: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "via-os-environ"
    monkeypatch.setenv(ENV_VAR, str(target))
    result = resolve_data_location(executable=exe, frozen=False, probes=QUIET)
    assert result.path == target
    assert result.source is LocationSource.ENV


def test_system_probes_are_the_default(env: dict[str, str], exe: Path, tmp_path: Path) -> None:
    result = resolve_data_location(
        cli_data_dir=tmp_path / "real-probes", environ=env, executable=exe, frozen=False
    )
    assert result.path == tmp_path / "real-probes"
    assert result.source is LocationSource.CLI
    assert result.writable is True
    assert Probes.system().writable is probe_directory_writable


# ---------------------------------------------------------------- portable mode


def test_portable_marker_ignored_when_not_frozen(
    env: dict[str, str], exe: Path, default_dir: Path
) -> None:
    (exe.parent / PORTABLE_MARKER).write_text("", encoding="utf-8")
    result = resolve(env, exe, frozen=False)
    assert result.source is LocationSource.DEFAULT
    assert result.path == default_dir
    assert not (exe.parent / "data").exists()


def test_frozen_without_marker_is_not_portable(
    env: dict[str, str], exe: Path, default_dir: Path
) -> None:
    result = resolve(env, exe, frozen=True)
    assert result.source is LocationSource.DEFAULT
    assert result.path == default_dir


def test_portable_unusable_without_database_lets_pointer_win(
    env: dict[str, str], exe: Path, local_appdata: Path, tmp_path: Path
) -> None:
    (exe.parent / PORTABLE_MARKER).write_text("", encoding="utf-8")
    target = tmp_path / "chosen"
    pointer_to(local_appdata, target)
    portable = exe.parent / "data"
    probes = replace(QUIET, writable=lambda folder: folder != portable)
    result = resolve(env, exe, frozen=True, probes=probes)
    assert result.path == target
    assert result.source is LocationSource.POINTER
    assert result.writable is True


def test_portable_unusable_and_creation_failing_lets_pointer_win(
    env: dict[str, str], exe: Path, local_appdata: Path, tmp_path: Path
) -> None:
    (exe.parent / PORTABLE_MARKER).write_text("", encoding="utf-8")
    target = tmp_path / "chosen"
    pointer_to(local_appdata, target)
    portable = exe.parent / "data"
    probes = replace(QUIET, ensure_directory=lambda p: p != portable and create_directory(p))
    result = resolve(env, exe, frozen=True, probes=probes)
    assert result.path == target
    assert result.source is LocationSource.POINTER


def test_portable_not_writable_but_with_database_stays_portable(
    env: dict[str, str], exe: Path, local_appdata: Path, tmp_path: Path
) -> None:
    (exe.parent / PORTABLE_MARKER).write_text("", encoding="utf-8")
    portable = exe.parent / "data"
    portable.mkdir()
    (portable / DATABASE_FILE_NAME).write_bytes(b"")
    pointer_to(local_appdata, tmp_path / "chosen")
    probes = replace(QUIET, writable=lambda _folder: False)
    result = resolve(env, exe, frozen=True, probes=probes)
    assert result.path == portable
    assert result.source is LocationSource.PORTABLE
    assert result.writable is False
    assert result.database_exists is True
    assert not (tmp_path / "chosen").exists()


def test_portable_unusable_and_no_pointer_stays_portable_not_writable(
    env: dict[str, str], exe: Path, default_dir: Path
) -> None:
    (exe.parent / PORTABLE_MARKER).write_text("", encoding="utf-8")
    probes = replace(QUIET, writable=lambda _folder: False)
    result = resolve(env, exe, frozen=True, probes=probes)
    assert result.path == exe.parent / "data"
    assert result.source is LocationSource.PORTABLE
    assert result.writable is False
    assert result.warnings == ()
    assert not default_dir.exists()


def test_portable_unusable_and_invalid_pointer_warns(
    env: dict[str, str], exe: Path, local_appdata: Path
) -> None:
    (exe.parent / PORTABLE_MARKER).write_text("", encoding="utf-8")
    write_pointer(local_appdata, "{broken")
    probes = replace(QUIET, writable=lambda _folder: False)
    result = resolve(env, exe, frozen=True, probes=probes)
    assert result.source is LocationSource.PORTABLE
    assert result.writable is False
    assert result.warnings == (LocationWarning.POINTER_INVALID,)


# ---------------------------------------------------------------- network paths


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("\\\\server\\share\\data", True),
        ("//server/share/data", True),
        ("\\\\?\\UNC\\server\\share\\data", True),
        ("\\\\?\\C:\\data", False),
        ("\\\\.\\C:\\data", False),
        ("C:\\data", False),
        ("relative\\data", False),
        ("D:/data", False),
    ],
)
def test_is_unc_path(text: str, expected: bool) -> None:
    assert is_unc_path(text) is expected


@windows_only
@pytest.mark.parametrize("text", ["\\\\server\\share\\cbrn", "//server/share/cbrn"])
def test_unc_path_warns_without_touching_the_filesystem(
    env: dict[str, str], exe: Path, text: str
) -> None:
    created: list[Path] = []
    probed: list[Path] = []

    def fake_ensure(path: Path) -> bool:
        created.append(path)
        return True

    def fake_writable(path: Path) -> bool:
        probed.append(path)
        return True

    probes = replace(QUIET, ensure_directory=fake_ensure, writable=fake_writable)
    result = resolve(env, exe, cli=text, probes=probes)
    assert result.warnings == (LocationWarning.NETWORK_PATH,)
    assert result.source is LocationSource.CLI
    assert result.writable is True
    assert created == [result.path] == probed
    assert is_unc_path(result.path)


@windows_only
def test_extended_local_path_is_not_a_network_path(
    env: dict[str, str], exe: Path, tmp_path: Path
) -> None:
    probes = replace(QUIET, ensure_directory=lambda _p: True, writable=lambda _p: True)
    result = resolve(env, exe, cli="\\\\?\\" + str(tmp_path / "ext"), probes=probes)
    assert LocationWarning.NETWORK_PATH not in result.warnings


def test_mapped_network_drive_via_fake_lookup(
    env: dict[str, str], exe: Path, tmp_path: Path
) -> None:
    asked: list[Path] = []

    def lookup(path: Path) -> bool:
        asked.append(path)
        return True

    result = resolve(env, exe, cli=tmp_path / "mapped", probes=replace(QUIET, network_drive=lookup))
    assert result.warnings == (LocationWarning.NETWORK_PATH,)
    assert asked == [tmp_path / "mapped"]


def test_local_path_has_no_network_warning(env: dict[str, str], exe: Path, tmp_path: Path) -> None:
    result = resolve(env, exe, cli=tmp_path / "local")
    assert LocationWarning.NETWORK_PATH not in result.warnings


# ---------------------------------------------------------------- OneDrive


@pytest.mark.parametrize("variable", ["OneDrive", "OneDriveCommercial", "OneDriveConsumer"])
def test_onedrive_via_environment_prefix(
    env: dict[str, str], exe: Path, tmp_path: Path, variable: str
) -> None:
    root = tmp_path / "OneDrive - Org"
    env[variable] = str(root)
    result = resolve(env, exe, cli=root / "Documents" / "cbrn")
    assert result.warnings == (LocationWarning.ONEDRIVE,)


def test_onedrive_root_itself_and_case_insensitive(
    env: dict[str, str], exe: Path, tmp_path: Path
) -> None:
    root = tmp_path / "OneDrive"
    env["OneDrive"] = str(root).upper()
    result = resolve(env, exe, cli=root)
    assert result.warnings == (LocationWarning.ONEDRIVE,)


def test_onedrive_prefix_is_component_wise(env: dict[str, str], exe: Path, tmp_path: Path) -> None:
    env["OneDrive"] = str(tmp_path / "OneDrive")
    result = resolve(env, exe, cli=tmp_path / "OneDriveX" / "data")
    assert result.warnings == ()


def test_blank_and_relative_onedrive_variables_are_ignored(
    env: dict[str, str], exe: Path, tmp_path: Path
) -> None:
    env["OneDrive"] = "  "
    env["OneDriveCommercial"] = "relative"
    result = resolve(env, exe, cli=tmp_path / "data")
    assert result.warnings == ()


def test_onedrive_via_fake_registry_mount_point_only(
    env: dict[str, str], exe: Path, tmp_path: Path
) -> None:
    mount = tmp_path / "Synced"

    def mounts() -> Sequence[Path]:
        return [tmp_path / "Other", mount]

    result = resolve(env, exe, cli=mount / "cbrn", probes=replace(QUIET, onedrive_mounts=mounts))
    assert result.warnings == (LocationWarning.ONEDRIVE,)
    assert "OneDrive" not in env


def test_registry_mount_point_that_does_not_contain_the_folder(
    env: dict[str, str], exe: Path, tmp_path: Path
) -> None:
    probes = replace(QUIET, onedrive_mounts=lambda: [tmp_path / "Synced"])
    result = resolve(env, exe, cli=tmp_path / "SyncedNot" / "cbrn", probes=probes)
    assert result.warnings == ()


@pytest.mark.parametrize(
    "attribute",
    [
        FILE_ATTRIBUTE_OFFLINE,
        FILE_ATTRIBUTE_RECALL_ON_OPEN,
        FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS,
        FILE_ATTRIBUTE_PINNED,
        FILE_ATTRIBUTE_UNPINNED,
    ],
)
def test_onedrive_via_fake_cloud_placeholder_attributes_only(
    env: dict[str, str], exe: Path, tmp_path: Path, attribute: int
) -> None:
    probes = replace(QUIET, attributes=lambda _path: attribute | 0x10)
    result = resolve(env, exe, cli=tmp_path / "cbrn", probes=probes)
    assert result.warnings == (LocationWarning.ONEDRIVE,)


def test_ordinary_attributes_do_not_warn(env: dict[str, str], exe: Path, tmp_path: Path) -> None:
    assert (0x10 | 0x20) & CLOUD_PLACEHOLDER_MASK == 0
    probes = replace(QUIET, attributes=lambda _path: 0x10 | 0x20)
    result = resolve(env, exe, cli=tmp_path / "cbrn", probes=probes)
    assert result.warnings == ()


def test_warnings_combine_in_a_stable_order(env: dict[str, str], exe: Path, tmp_path: Path) -> None:
    probes = replace(
        QUIET, network_drive=lambda _p: True, attributes=lambda _p: FILE_ATTRIBUTE_OFFLINE
    )
    result = resolve(env, exe, cli=tmp_path / "cbrn", probes=probes)
    assert result.warnings == (LocationWarning.NETWORK_PATH, LocationWarning.ONEDRIVE)


# ---------------------------------------------------------------- writability and creation


def test_non_writable_probe_is_reported_not_replaced(
    env: dict[str, str], exe: Path, tmp_path: Path, default_dir: Path
) -> None:
    target = tmp_path / "readonly-place"
    result = resolve(env, exe, cli=target, probes=replace(QUIET, writable=lambda _p: False))
    assert result.path == target
    assert result.source is LocationSource.CLI
    assert result.writable is False
    assert not default_dir.exists()


def test_non_writable_default_stays_default(
    env: dict[str, str], exe: Path, default_dir: Path
) -> None:
    result = resolve(env, exe, probes=replace(QUIET, writable=lambda _p: False))
    assert result.path == default_dir
    assert result.source is LocationSource.DEFAULT
    assert result.writable is False


def test_failed_folder_creation_is_non_writable_and_does_not_raise(
    env: dict[str, str], exe: Path, tmp_path: Path
) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    target = blocker / "sub"
    result = resolve(env, exe, cli=target)
    assert result.path == target
    assert result.writable is False


def test_failed_creation_does_not_run_the_writability_probe(
    env: dict[str, str], exe: Path, tmp_path: Path
) -> None:
    def must_not_run(_path: Path) -> bool:
        raise AssertionError("probe must not run when the folder cannot be created")

    probes = replace(QUIET, ensure_directory=lambda _p: False, writable=must_not_run)
    result = resolve(env, exe, cli=tmp_path / "nope", probes=probes)
    assert result.writable is False


def test_real_probe_is_true_for_tmp_path(tmp_path: Path) -> None:
    assert probe_directory_writable(tmp_path) is True
    assert list(tmp_path.iterdir()) == []


def test_real_probe_is_false_for_missing_folder(tmp_path: Path) -> None:
    assert probe_directory_writable(tmp_path / "missing") is False


def test_folder_is_created_when_missing(env: dict[str, str], exe: Path, tmp_path: Path) -> None:
    target = tmp_path / "deep" / "er" / "data"
    result = resolve(env, exe, cli=target)
    assert target.is_dir()
    assert result.writable is True


def test_existing_folder_is_kept(env: dict[str, str], exe: Path, tmp_path: Path) -> None:
    target = tmp_path / "data"
    target.mkdir()
    (target / "keep.txt").write_text("k", encoding="utf-8")
    result = resolve(env, exe, cli=target)
    assert result.writable is True
    assert (target / "keep.txt").read_text(encoding="utf-8") == "k"


# ---------------------------------------------------------------- DataLocation


def test_database_path_and_existence(env: dict[str, str], exe: Path, tmp_path: Path) -> None:
    result = resolve(env, exe, cli=tmp_path / "data")
    assert result.database_path == tmp_path / "data" / "cbrn-dashboard.sqlite3"
    assert result.database_path.name == DATABASE_FILE_NAME
    assert result.database_exists is False
    result.database_path.write_bytes(b"")
    assert result.database_exists is True


def test_data_location_is_frozen(tmp_path: Path) -> None:
    location = DataLocation(tmp_path, LocationSource.CLI, True)
    with pytest.raises(AttributeError):
        location.writable = False  # type: ignore[misc]


# ---------------------------------------------------------------- is_file_writable


def test_is_file_writable_true_for_normal_file(tmp_path: Path) -> None:
    db = tmp_path / DATABASE_FILE_NAME
    db.write_bytes(b"abc")
    assert is_file_writable(db) is True
    assert db.read_bytes() == b"abc"


def test_is_file_writable_false_for_read_only_file(tmp_path: Path) -> None:
    db = tmp_path / DATABASE_FILE_NAME
    db.write_bytes(b"abc")
    db.chmod(stat.S_IREAD)
    try:
        assert is_file_writable(db) is False
    finally:
        db.chmod(stat.S_IREAD | stat.S_IWRITE)
    assert is_file_writable(db) is True


def test_is_file_writable_false_for_missing_file_and_does_not_create_it(tmp_path: Path) -> None:
    db = tmp_path / DATABASE_FILE_NAME
    assert is_file_writable(db) is False
    assert not db.exists()


def test_is_file_writable_false_for_directory(tmp_path: Path) -> None:
    assert is_file_writable(tmp_path) is False
