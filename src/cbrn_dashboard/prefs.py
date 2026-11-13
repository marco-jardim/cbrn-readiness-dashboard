# SPDX-License-Identifier: GPL-3.0-or-later
"""UI preferences stored in ``prefs.json`` beside the database (PLAN.md task T1.5, D02).

The file holds the user-interface language (catalogue code, ``pt_BR`` by default), the flag that
the first-run notice was shown (T7.5) and the toggle of the start-up summary (T6.6). It is Qt-free
and never raises for a missing or damaged file: a field that is absent or invalid falls back to its
default and a ``CORRUPT_FILE`` warning code is recorded for the UI to translate later.

Writes are atomic: the JSON goes to a temporary file in the same folder, is flushed and synced,
and is then moved over ``prefs.json`` (retried up to three times, immediately, when the system
reports a transient ``PermissionError``). Leftover ``prefs.json.tmp-*`` files of a crash are
removed on load when the folder is writable. The file is read with ``utf-8-sig``, so a byte-order
mark is tolerated. When the data folder is read-only (or the write fails) the
change is kept for the session only and ``NOT_SAVED`` is recorded; nothing is raised.
"""

import contextlib
import dataclasses
import json
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Self

from cbrn_dashboard.i18n import DEFAULT_LANGUAGE, to_catalogue_code

PREFS_FILE_NAME = "prefs.json"
TEMP_PREFIX = f"{PREFS_FILE_NAME}.tmp-"

#: How often the atomic replace is retried after a transient ``PermissionError`` (on Windows, a
#: sharing violation caused by a virus scanner). The retries are immediate: no sleeping and no
#: clock, so the behaviour is deterministic.
_REPLACE_RETRIES = 3

KEY_LANGUAGE = "language"
KEY_FIRST_RUN_NOTICE_SHOWN = "first_run_notice_shown"
KEY_STARTUP_SUMMARY = "startup_summary"


class PreferencesWarning(StrEnum):
    """Warning codes of the preferences store (translated by the UI)."""

    CORRUPT_FILE = "corrupt_file"
    NOT_SAVED = "not_saved"


@dataclass(frozen=True)
class Preferences:
    """The user preferences; invalid values are rejected on construction."""

    language: str = DEFAULT_LANGUAGE
    first_run_notice_shown: bool = False
    startup_summary: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.language, str):
            raise TypeError("language must be a string")
        # Raises UnknownLanguageError; also normalises "pt-BR" to "pt_BR".
        object.__setattr__(self, "language", to_catalogue_code(self.language))
        if not isinstance(self.first_run_notice_shown, bool):
            raise TypeError("first_run_notice_shown must be a bool")
        if not isinstance(self.startup_summary, bool):
            raise TypeError("startup_summary must be a bool")

    def with_changes(
        self,
        *,
        language: str | None = None,
        first_run_notice_shown: bool | None = None,
        startup_summary: bool | None = None,
    ) -> Self:
        """Return a copy with the given fields replaced (validated like the constructor).

        ``None`` means "keep the current value"; no field can legitimately be ``None``.
        """
        new_language: str = self.language if language is None else language
        new_first_run: bool = (
            self.first_run_notice_shown
            if first_run_notice_shown is None
            else first_run_notice_shown
        )
        new_summary: bool = self.startup_summary if startup_summary is None else startup_summary
        return dataclasses.replace(
            self,
            language=new_language,
            first_run_notice_shown=new_first_run,
            startup_summary=new_summary,
        )

    def to_json_object(self) -> dict[str, object]:
        """The three keys as stored in the file."""
        return {
            KEY_LANGUAGE: self.language,
            KEY_FIRST_RUN_NOTICE_SHOWN: self.first_run_notice_shown,
            KEY_STARTUP_SUMMARY: self.startup_summary,
        }


_KNOWN_KEYS = frozenset({KEY_LANGUAGE, KEY_FIRST_RUN_NOTICE_SHOWN, KEY_STARTUP_SUMMARY})


def _parse(text: str) -> tuple[Preferences, dict[str, object], bool]:
    """Parse the file content: ``(preferences, unknown keys, whether anything was wrong)``."""
    defaults = Preferences()
    try:
        data: object = json.loads(text)
    except (ValueError, RecursionError):
        return defaults, {}, True
    if not isinstance(data, dict):
        return defaults, {}, True

    problem = False
    language = defaults.language
    first_run = defaults.first_run_notice_shown
    summary = defaults.startup_summary

    if KEY_LANGUAGE in data:
        raw_language: object = data[KEY_LANGUAGE]
        try:
            if not isinstance(raw_language, str):
                raise TypeError(KEY_LANGUAGE)
            language = Preferences(language=raw_language).language
        except (TypeError, ValueError):
            problem = True
    if KEY_FIRST_RUN_NOTICE_SHOWN in data:
        raw_first: object = data[KEY_FIRST_RUN_NOTICE_SHOWN]
        if isinstance(raw_first, bool):
            first_run = raw_first
        else:
            problem = True
    if KEY_STARTUP_SUMMARY in data:
        raw_summary: object = data[KEY_STARTUP_SUMMARY]
        if isinstance(raw_summary, bool):
            summary = raw_summary
        else:
            problem = True

    extra: dict[str, object] = {k: v for k, v in data.items() if k not in _KNOWN_KEYS}
    prefs = Preferences(
        language=language, first_run_notice_shown=first_run, startup_summary=summary
    )
    return prefs, extra, problem


class PreferencesStore:
    """Loads and saves :class:`Preferences` in ``<data_dir>/prefs.json``."""

    def __init__(self, data_dir: Path, *, writable: bool = True) -> None:
        self._path = data_dir / PREFS_FILE_NAME
        self._data_dir = data_dir
        self._writable = writable
        self._current: Preferences | None = None
        self._extra: dict[str, object] = {}
        self._warnings: list[PreferencesWarning] = []
        self._persisted = True

    @property
    def path(self) -> Path:
        """Location of ``prefs.json``."""
        return self._path

    @property
    def warnings(self) -> tuple[PreferencesWarning, ...]:
        """Warning codes recorded so far (each at most once, in order of occurrence)."""
        return tuple(self._warnings)

    @property
    def persisted(self) -> bool:
        """``False`` when the latest change could not be saved (kept for the session only)."""
        return self._persisted

    @property
    def current(self) -> Preferences:
        """The in-memory preferences; the file is read on first access."""
        if self._current is None:
            return self.load()
        return self._current

    def load(self) -> Preferences:
        """Read the file (again); a missing or damaged file gives defaults, never an error."""
        self._warnings = []
        self._extra = {}
        self._persisted = True
        if self._writable:
            self._remove_stale_temp_files()
        try:
            # utf-8-sig: a file saved with a byte-order mark (for example by Notepad) is valid
            text = self._path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            self._current = Preferences()
            return self._current
        except (OSError, ValueError):
            self._current = Preferences()
            self._warn(PreferencesWarning.CORRUPT_FILE)
            return self._current
        prefs, extra, problem = _parse(text)
        self._extra = extra
        if problem:
            self._warn(PreferencesWarning.CORRUPT_FILE)
        self._current = prefs
        return prefs

    def update(
        self,
        *,
        language: str | None = None,
        first_run_notice_shown: bool | None = None,
        startup_summary: bool | None = None,
    ) -> Preferences:
        """Change preferences, keep them for the session and save them when possible.

        ``None`` (the default) leaves a field unchanged. Raises
        :class:`~cbrn_dashboard.i18n.UnknownLanguageError` for an unknown language and
        ``TypeError`` for a wrong value type or an unknown keyword; state and file are then
        unchanged. A read-only folder or a failed write records ``NOT_SAVED`` and raises nothing.
        """
        new = self.current.with_changes(
            language=language,
            first_run_notice_shown=first_run_notice_shown,
            startup_summary=startup_summary,
        )
        self._current = new
        if not self._writable:
            self._mark_not_saved()
            return new
        try:
            self._write(new)
        except OSError:
            self._mark_not_saved()
        else:
            self._persisted = True
            if PreferencesWarning.NOT_SAVED in self._warnings:
                self._warnings.remove(PreferencesWarning.NOT_SAVED)
        return new

    # ------------------------------------------------------------------ internals

    def _warn(self, code: PreferencesWarning) -> None:
        if code not in self._warnings:
            self._warnings.append(code)

    def _remove_stale_temp_files(self) -> None:
        """Delete ``prefs.json.tmp-*`` files left behind by a crash; failures are ignored."""
        with contextlib.suppress(OSError):
            for stale in self._data_dir.glob(f"{TEMP_PREFIX}*"):
                with contextlib.suppress(OSError):
                    stale.unlink(missing_ok=True)

    def _mark_not_saved(self) -> None:
        self._persisted = False
        self._warn(PreferencesWarning.NOT_SAVED)

    def _write(self, prefs: Preferences) -> None:
        """Atomically replace ``prefs.json``; no partial file, no stray temporary file."""
        content: dict[str, object] = {**self._extra, **prefs.to_json_object()}
        payload = (json.dumps(content, indent=2, sort_keys=True) + "\n").encode("utf-8")
        descriptor, temp_name = tempfile.mkstemp(dir=self._data_dir, prefix=TEMP_PREFIX)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(_REPLACE_RETRIES + 1):
                try:
                    temp_path.replace(self._path)
                except PermissionError:
                    if attempt >= _REPLACE_RETRIES:
                        raise
                else:
                    break
        except BaseException:
            with contextlib.suppress(OSError):
                temp_path.unlink(missing_ok=True)
            raise
