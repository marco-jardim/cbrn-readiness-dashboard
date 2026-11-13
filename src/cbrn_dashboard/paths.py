# SPDX-License-Identifier: GPL-3.0-or-later
"""Data-location resolution (PLAN.md D02, task T0.5).

The chosen folder later holds the database, preferences, backups, logs and so on; this module
only decides *which* folder, creates it if it is missing, and reports whether it is writable and
whether it sits on a network share or in a OneDrive-synced folder. It never falls back to another
location silently: an unusable folder is reported as ``writable=False`` with the same path.

Resolution order (first match wins):

1. the ``--data-dir`` option;
2. the ``CBRN_DASHBOARD_DATA_DIR`` environment variable;
3. portable mode: ``portable.ini`` beside a frozen executable puts the data in ``.\\data\\``;
4. the pointer file ``%LOCALAPPDATA%\\cbrn-readiness-dashboard\\location.json``;
5. the default ``%LOCALAPPDATA%\\cbrn-readiness-dashboard\\``.

Because portable mode ranks above the pointer file, the pointer is honoured in portable mode only
when the portable folder is unusable (not writable and holding no database).

Everything environmental (environment, executable, probes) is injectable so tests never touch the
real profile, registry or network. Warnings are codes only; the UI translates them.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import NamedTuple

APP_DIR_NAME = "cbrn-readiness-dashboard"
DATABASE_FILE_NAME = "cbrn-dashboard.sqlite3"
ENV_VAR = "CBRN_DASHBOARD_DATA_DIR"
PORTABLE_MARKER = "portable.ini"
POINTER_FILE_NAME = "location.json"

#: Name of the data sub-folder used in portable mode, beside the executable.
PORTABLE_DATA_DIR_NAME = "data"
#: Key of the pointer file's JSON object.
POINTER_KEY = "data_dir"
#: Environment variables that name OneDrive roots.
ONEDRIVE_ENV_VARS = ("OneDrive", "OneDriveCommercial", "OneDriveConsumer")

FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_PINNED = 0x80000
FILE_ATTRIBUTE_UNPINNED = 0x100000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
#: Any of these on a folder marks it as a cloud placeholder.
CLOUD_PLACEHOLDER_MASK = (
    FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_PINNED
    | FILE_ATTRIBUTE_UNPINNED
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)


class LocationSource(StrEnum):
    """Which rule of the D02 order chose the folder."""

    CLI = "cli"
    ENV = "env"
    PORTABLE = "portable"
    POINTER = "pointer"
    DEFAULT = "default"


class LocationWarning(StrEnum):
    """Warning codes attached to a resolved location (translated by the UI)."""

    NETWORK_PATH = "network_path"
    ONEDRIVE = "onedrive"
    POINTER_INVALID = "pointer_invalid"
    #: The injected environment names no profile folder, so no default location exists.
    NO_PROFILE_DIR = "no_profile_dir"


@dataclass(frozen=True)
class DataLocation:
    """The resolved data folder."""

    path: Path
    source: LocationSource
    writable: bool
    warnings: tuple[LocationWarning, ...] = ()

    @property
    def database_path(self) -> Path:
        return self.path / DATABASE_FILE_NAME

    @property
    def database_exists(self) -> bool:
        return self.database_path.is_file()


# --------------------------------------------------------------------------- real probes


def create_directory(path: Path) -> bool:
    """Create ``path`` (and parents) if missing; ``False`` when that is impossible.

    A path the operating system rejects outright (for example an embedded NUL, which raises
    ``ValueError``) counts as impossible too.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except (OSError, ValueError):
        return False
    return path.is_dir()


def probe_directory_writable(folder: Path) -> bool:
    """Real writability probe: create and delete a uniquely named temporary file."""
    probe = folder / f".write-probe-{uuid.uuid4().hex}.tmp"
    try:
        with probe.open("xb") as handle:
            handle.write(b"0")
        probe.unlink()
    except (OSError, ValueError):  # ValueError: e.g. an embedded NUL in the folder name
        return False
    return True


def is_file_writable(path: Path) -> bool:
    """Whether the existing file ``path`` can be appended to.

    Never creates or truncates the file: a missing file is reported as not writable. The Windows
    read-only attribute is checked explicitly, then the file is opened for append.
    """
    try:
        if not path.is_file():
            return False
        if sys.platform == "win32":
            if path.stat().st_file_attributes & FILE_ATTRIBUTE_READONLY:
                return False
        elif not path.stat().st_mode & stat.S_IWUSR:
            return False
        with path.open("ab"):
            pass
    except OSError:
        return False
    return True


def is_unc_path(path: str | os.PathLike[str]) -> bool:
    """``True`` for UNC paths (``\\\\server\\share``, ``//server/share``), not ``\\\\?\\C:\\``."""
    drive = PureWindowsPath(os.fspath(path)).drive
    if drive.startswith(("\\\\?\\", "\\\\.\\")):
        return drive[4:].upper().startswith("UNC\\")
    return drive.startswith("\\\\")


def _has_network_mapping(letter: str) -> bool:
    """Whether ``HKCU\\Network\\<letter>`` exists (a persistent mapped network drive)."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"Network\\{letter}"):
            return True
    except OSError:
        return False


def is_network_drive(path: Path) -> bool:
    """Real mapped-drive lookup (no ``ctypes``); ``False`` on non-Windows or on any error.

    On Windows ``Path.resolve()`` turns a mapped network drive into its ``\\\\server\\share``
    form; the per-user registry key ``HKCU\\Network\\<letter>`` is checked as well.
    """
    if sys.platform != "win32":
        return False
    drive = PureWindowsPath(str(path)).drive
    if len(drive) != 2 or drive[1] != ":":
        return False
    try:
        resolved_root = Path(drive + "\\").resolve()
    except (OSError, RuntimeError, ValueError):
        return _has_network_mapping(drive[0])
    return is_unc_path(resolved_root) or _has_network_mapping(drive[0])


_ONEDRIVE_ACCOUNTS_KEY = r"Software\Microsoft\OneDrive\Accounts"


def _user_folder(account: str) -> Path | None:
    """Read ``UserFolder`` of one OneDrive account sub-key (Windows only)."""
    if sys.platform != "win32":
        return None
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, f"{_ONEDRIVE_ACCOUNTS_KEY}\\{account}"
        ) as key:
            value = winreg.QueryValueEx(key, "UserFolder")[0]
    except OSError:
        return None
    if isinstance(value, str) and value.strip():
        return Path(value.strip())
    return None


def read_onedrive_mount_points() -> tuple[Path, ...]:
    """Real registry reader: ``UserFolder`` values below the OneDrive ``Accounts`` key in HKCU.

    Read-only and tolerant of missing keys (returns an empty tuple).
    """
    if sys.platform != "win32":
        return ()
    import winreg

    mounts: list[Path] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _ONEDRIVE_ACCOUNTS_KEY) as accounts:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(accounts, index)
                except OSError:
                    break
                index += 1
                mount = _user_folder(name)
                if mount is not None:
                    mounts.append(mount)
    except OSError:
        return ()
    return tuple(mounts)


def read_file_attributes(path: Path) -> int:
    """Real attribute reader: ``st_file_attributes`` on Windows, ``0`` on error or elsewhere."""
    if sys.platform != "win32":
        return 0
    try:
        return path.stat().st_file_attributes
    except (OSError, ValueError):
        return 0


@dataclass(frozen=True)
class Probes:
    """Injectable environment probes; ``Probes.system()`` gives the real ones."""

    writable: Callable[[Path], bool]
    network_drive: Callable[[Path], bool]
    onedrive_mounts: Callable[[], Sequence[Path]]
    attributes: Callable[[Path], int]
    ensure_directory: Callable[[Path], bool]

    @classmethod
    def system(cls) -> Probes:
        return cls(
            writable=probe_directory_writable,
            network_drive=is_network_drive,
            onedrive_mounts=read_onedrive_mount_points,
            attributes=read_file_attributes,
            ensure_directory=create_directory,
        )


# --------------------------------------------------------------------------- resolution


class _Pointer(NamedTuple):
    path: Path | None
    invalid: bool


def _non_blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _profile_dir(environ: Mapping[str, str]) -> Path | None:
    """``%LOCALAPPDATA%\\cbrn-readiness-dashboard`` from the injected ``environ`` only.

    ``LOCALAPPDATA``, else ``USERPROFILE\\AppData\\Local``, else
    ``HOMEDRIVE`` + ``HOMEPATH`` + ``\\AppData\\Local``. ``None`` when none of them is set: the
    real environment and ``Path.home()`` are never consulted.
    """
    local = _non_blank(environ.get("LOCALAPPDATA"))
    if local is not None:
        return Path(local).absolute() / APP_DIR_NAME
    home = _non_blank(environ.get("USERPROFILE"))
    if home is None:
        drive = _non_blank(environ.get("HOMEDRIVE"))
        home_path = _non_blank(environ.get("HOMEPATH"))
        if drive is None or home_path is None:
            return None
        home = drive + home_path
    return (Path(home) / "AppData" / "Local").absolute() / APP_DIR_NAME


def _has_control_character(text: str) -> bool:
    return any(ord(char) < 0x20 for char in text)


def _read_pointer(environ: Mapping[str, str]) -> _Pointer:
    """Read the pointer file. Missing: no pointer; unreadable or malformed: ``invalid``."""
    profile = _profile_dir(environ)
    if profile is None:
        return _Pointer(None, False)
    pointer_file = profile / POINTER_FILE_NAME
    try:
        text = pointer_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _Pointer(None, False)
    except (OSError, ValueError):
        return _Pointer(None, True)
    try:
        data: object = json.loads(text)
    except (ValueError, RecursionError):  # RecursionError: absurdly nested JSON
        return _Pointer(None, True)
    if not isinstance(data, dict):
        return _Pointer(None, True)
    value: object = data.get(POINTER_KEY)
    if not isinstance(value, str) or _non_blank(value) is None:
        return _Pointer(None, True)
    if _has_control_character(value.strip()):  # NUL and other control characters
        return _Pointer(None, True)
    candidate = Path(value.strip())
    if not candidate.is_absolute():
        return _Pointer(None, True)
    return _Pointer(candidate, False)


def _normalise(path: Path) -> Path:
    """Absolute, symlink-resolved form for prefix comparison (UNC paths are left untouched)."""
    absolute = path.absolute()
    if is_unc_path(absolute):
        return absolute
    try:
        return absolute.resolve()
    except (OSError, RuntimeError, ValueError):
        return absolute


def _folded_parts(path: Path) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.parts)


def _is_inside(path: Path, root: Path) -> bool:
    """Component-wise, case-insensitive: is ``path`` equal to or below ``root``?"""
    if not root.is_absolute():
        return False
    root_parts = _folded_parts(_normalise(root))
    return bool(root_parts) and _folded_parts(_normalise(path))[: len(root_parts)] == root_parts


def _is_onedrive(path: Path, environ: Mapping[str, str], probes: Probes) -> bool:
    for name in ONEDRIVE_ENV_VARS:
        value = _non_blank(environ.get(name))
        if value is not None and _is_inside(path, Path(value)):
            return True
    if any(_is_inside(path, mount) for mount in probes.onedrive_mounts()):
        return True
    return (probes.attributes(path) & CLOUD_PLACEHOLDER_MASK) != 0


def _build(
    path: Path,
    source: LocationSource,
    writable: bool,
    environ: Mapping[str, str],
    probes: Probes,
    extra: tuple[LocationWarning, ...] = (),
) -> DataLocation:
    warnings: list[LocationWarning] = []
    if is_unc_path(path) or probes.network_drive(path):
        warnings.append(LocationWarning.NETWORK_PATH)
    if _is_onedrive(path, environ, probes):
        warnings.append(LocationWarning.ONEDRIVE)
    warnings.extend(extra)
    return DataLocation(path=path, source=source, writable=writable, warnings=tuple(warnings))


def _prepare(path: Path, probes: Probes) -> bool:
    """Create the folder if missing and probe it; ``False`` if either step fails."""
    return probes.ensure_directory(path) and probes.writable(path)


def resolve_data_location(
    *,
    cli_data_dir: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    executable: Path | None = None,
    frozen: bool | None = None,
    probes: Probes | None = None,
) -> DataLocation:
    """Resolve the data folder following the D02 order; see the module docstring.

    ``environ`` defaults to ``os.environ``, ``executable`` to ``sys.executable``, ``frozen`` to
    ``getattr(sys, "frozen", False)`` and ``probes`` to ``Probes.system()``. The folder is created
    if missing; if that or the writability probe fails the location is returned with
    ``writable=False`` (same path, never replaced).

    Only the injected ``environ`` is read; ``Path.home()`` is never used. If it names no profile
    folder (no ``LOCALAPPDATA``, ``USERPROFILE`` or ``HOMEDRIVE``+``HOMEPATH``) and nothing
    higher in the order applies, the result is the unusable placeholder ``Path(APP_DIR_NAME)``
    (relative, deterministic, never created) with ``source=DEFAULT``, ``writable=False`` and the
    ``NO_PROFILE_DIR`` warning; no other location is substituted.

    Never raises for bad *values*: a NUL or other control character in ``--data-dir``, the
    environment variable or the pointer file, a corrupt or deeply nested pointer file, or an
    unreadable folder yield ``writable=False`` or ``POINTER_INVALID`` instead. Injected probes
    are trusted and their exceptions propagate; ``MemoryError`` and the like are not handled.
    """
    env: Mapping[str, str] = os.environ if environ is None else environ
    active = Probes.system() if probes is None else probes
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    exe = Path(sys.executable) if executable is None else executable

    # 1. --data-dir
    cli = _non_blank(os.fspath(cli_data_dir)) if cli_data_dir is not None else None
    if cli is not None:
        path = Path(cli).absolute()
        return _build(path, LocationSource.CLI, _prepare(path, active), env, active)

    # 2. environment variable
    from_env = _non_blank(env.get(ENV_VAR))
    if from_env is not None:
        path = Path(from_env).absolute()
        return _build(path, LocationSource.ENV, _prepare(path, active), env, active)

    # 3. portable mode (frozen executable only)
    pointer: _Pointer | None = None
    if is_frozen and (exe.parent / PORTABLE_MARKER).is_file():
        portable = (exe.parent / PORTABLE_DATA_DIR_NAME).absolute()
        portable_writable = _prepare(portable, active)
        if portable_writable or (portable / DATABASE_FILE_NAME).is_file():
            return _build(portable, LocationSource.PORTABLE, portable_writable, env, active)
        # Portable folder unusable: the pointer file may redirect.
        pointer = _read_pointer(env)
        if pointer.path is None:
            extra = (LocationWarning.POINTER_INVALID,) if pointer.invalid else ()
            return _build(portable, LocationSource.PORTABLE, False, env, active, extra)

    # 4. pointer file
    if pointer is None:
        pointer = _read_pointer(env)
    if pointer.path is not None:
        target = pointer.path
        return _build(target, LocationSource.POINTER, _prepare(target, active), env, active)

    # 5. default
    default = _profile_dir(env)
    if default is None:
        return DataLocation(
            path=Path(APP_DIR_NAME),
            source=LocationSource.DEFAULT,
            writable=False,
            warnings=(LocationWarning.NO_PROFILE_DIR,),
        )
    extra = (LocationWarning.POINTER_INVALID,) if pointer.invalid else ()
    return _build(default, LocationSource.DEFAULT, _prepare(default, active), env, active, extra)
