# SPDX-License-Identifier: GPL-3.0-or-later
"""Preferences store (T1.5): defaults, round trip, corrupt files, read-only and atomic writes."""

import json
from pathlib import Path
from typing import Any

import pytest

from cbrn_dashboard import prefs as prefs_module
from cbrn_dashboard.i18n import DEFAULT_LANGUAGE, UnknownLanguageError
from cbrn_dashboard.prefs import (
    PREFS_FILE_NAME,
    Preferences,
    PreferencesStore,
    PreferencesWarning,
)


def _file(folder: Path) -> Path:
    return folder / PREFS_FILE_NAME


def _write(folder: Path, content: str) -> None:
    _file(folder).write_text(content, encoding="utf-8")


def _temp_files(folder: Path) -> list[Path]:
    return sorted(folder.glob(f"{PREFS_FILE_NAME}.tmp-*"))


# Wrong value types, passed through ``Any`` on purpose: the signature rejects them statically.
_WRONG_TYPES: list[dict[str, Any]] = [
    {"language": 3},
    {"startup_summary": "yes"},
    {"first_run_notice_shown": 1},
    {"startup_summary": 0},
]
_UNKNOWN_FIELD: dict[str, Any] = {"colour": "blue"}


# --------------------------------------------------------------------------- defaults


def test_defaults() -> None:
    defaults = Preferences()
    assert defaults.language == "pt_BR" == DEFAULT_LANGUAGE
    assert defaults.first_run_notice_shown is False
    assert defaults.startup_summary is True


def test_file_name() -> None:
    assert PREFS_FILE_NAME == "prefs.json"


def test_missing_file_gives_defaults_and_creates_nothing(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path)
    assert store.load() == Preferences()
    assert store.current == Preferences()
    assert store.warnings == ()
    assert store.persisted
    assert list(tmp_path.iterdir()) == []


def test_current_loads_lazily(tmp_path: Path) -> None:
    _write(tmp_path, '{"language": "es_ES"}')
    assert PreferencesStore(tmp_path).current.language == "es_ES"


def test_with_changes_validates() -> None:
    assert Preferences().with_changes(language="en-US").language == "en_US"
    with pytest.raises(UnknownLanguageError):
        Preferences().with_changes(language="fr_FR")
    for wrong in _WRONG_TYPES:
        with pytest.raises(TypeError):
            Preferences().with_changes(**wrong)
    with pytest.raises(TypeError):
        Preferences().with_changes(**_UNKNOWN_FIELD)


def test_none_keeps_the_current_value() -> None:
    start = Preferences("en_US", True, False)
    assert start.with_changes() == start
    assert start.with_changes(language=None, startup_summary=None) == start
    assert start.with_changes(startup_summary=True) == Preferences("en_US", True, True)


def test_update_without_changes_keeps_the_values(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path)
    store.update(language="es_ES")
    assert store.update() == Preferences(language="es_ES")
    assert PreferencesStore(tmp_path).load() == Preferences(language="es_ES")


# --------------------------------------------------------------------------- round trip


def test_round_trip_through_a_new_store(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path)
    result = store.update(language="en_US", first_run_notice_shown=True, startup_summary=False)
    assert result == Preferences("en_US", True, False)
    assert store.persisted
    assert store.warnings == ()

    again = PreferencesStore(tmp_path)
    assert again.load() == Preferences("en_US", True, False)
    assert again.warnings == ()


def test_file_content_is_json_with_the_three_keys(tmp_path: Path) -> None:
    PreferencesStore(tmp_path).update(language="es_ES")
    text = _file(tmp_path).read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text) == {
        "first_run_notice_shown": False,
        "language": "es_ES",
        "startup_summary": True,
    }
    assert list(json.loads(text)) == sorted(json.loads(text))
    assert '\n  "language"' in text  # indent=2


def test_partial_update_keeps_the_other_fields(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path)
    store.update(startup_summary=False)
    store.update(language="en_US")
    assert PreferencesStore(tmp_path).load() == Preferences(
        language="en_US", first_run_notice_shown=False, startup_summary=False
    )


def test_language_given_in_bcp47_is_stored_as_catalogue_code(tmp_path: Path) -> None:
    assert PreferencesStore(tmp_path).update(language="en-US").language == "en_US"
    assert json.loads(_file(tmp_path).read_text(encoding="utf-8"))["language"] == "en_US"


def test_unknown_keys_are_preserved_on_rewrite(tmp_path: Path) -> None:
    _write(tmp_path, json.dumps({"language": "en_US", "future": {"a": [1, 2]}, "z": None}))
    store = PreferencesStore(tmp_path)
    assert store.load().language == "en_US"
    assert store.warnings == ()
    store.update(startup_summary=False)
    data = json.loads(_file(tmp_path).read_text(encoding="utf-8"))
    assert data["future"] == {"a": [1, 2]}
    assert data["z"] is None
    assert data["language"] == "en_US"
    assert data["startup_summary"] is False


# --------------------------------------------------------------------------- corrupt files


@pytest.mark.parametrize(
    "content",
    ["{not json", "[]", '"x"', "42", "null", "", "{", '{"language": ', "\ufeff{}x"],
)
def test_unusable_file_falls_back_to_all_defaults(tmp_path: Path, content: str) -> None:
    _write(tmp_path, content)
    store = PreferencesStore(tmp_path)
    assert store.load() == Preferences()
    assert PreferencesWarning.CORRUPT_FILE in store.warnings
    assert store.persisted


def test_undecodable_file_falls_back_to_defaults(tmp_path: Path) -> None:
    _file(tmp_path).write_bytes(b"\xff\xfe\x00{")
    store = PreferencesStore(tmp_path)
    assert store.load() == Preferences()
    assert store.warnings == (PreferencesWarning.CORRUPT_FILE,)


def test_directory_in_place_of_the_file_is_not_an_error(tmp_path: Path) -> None:
    _file(tmp_path).mkdir()
    store = PreferencesStore(tmp_path)
    assert store.load() == Preferences()
    assert store.warnings == (PreferencesWarning.CORRUPT_FILE,)


@pytest.mark.parametrize(
    "bad",
    [
        {"language": "fr_FR"},
        {"language": 3},
        {"language": None},
        {"first_run_notice_shown": "yes"},
        {"first_run_notice_shown": 1},
        {"startup_summary": 0},
        {"startup_summary": None},
    ],
)
def test_one_bad_field_falls_back_and_keeps_the_valid_fields(
    tmp_path: Path, bad: dict[str, object]
) -> None:
    valid: dict[str, object] = {
        "language": "es_ES",
        "first_run_notice_shown": True,
        "startup_summary": False,
    }
    stored = {**valid, **bad}
    _write(tmp_path, json.dumps(stored))
    store = PreferencesStore(tmp_path)
    loaded = store.load()
    assert store.warnings == (PreferencesWarning.CORRUPT_FILE,)
    defaults = Preferences().to_json_object()
    for key, value in loaded.to_json_object().items():
        expected = defaults[key] if key in bad else valid[key]
        assert value == expected, key


def test_missing_fields_are_defaults_without_warning(tmp_path: Path) -> None:
    _write(tmp_path, "{}")
    store = PreferencesStore(tmp_path)
    assert store.load() == Preferences()
    assert store.warnings == ()


def test_corrupt_file_is_replaced_by_a_valid_one_on_update(tmp_path: Path) -> None:
    _write(tmp_path, "{not json")
    store = PreferencesStore(tmp_path)
    store.update(language="en_US")
    assert PreferencesStore(tmp_path).load() == Preferences(language="en_US")
    assert PreferencesStore(tmp_path).warnings == ()


# --------------------------------------------------------------------------- invalid updates


def test_invalid_updates_are_rejected_and_change_nothing(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path)
    store.update(language="en_US")
    before = _file(tmp_path).read_bytes()

    with pytest.raises(UnknownLanguageError):
        store.update(language="fr_FR")
    for wrong in _WRONG_TYPES:
        with pytest.raises(TypeError):
            store.update(**wrong)
    with pytest.raises(TypeError):
        store.update(**_UNKNOWN_FIELD)

    assert store.current == Preferences(language="en_US")
    assert _file(tmp_path).read_bytes() == before
    assert store.persisted
    assert _temp_files(tmp_path) == []


def test_invalid_update_does_not_create_the_file(tmp_path: Path) -> None:
    with pytest.raises(UnknownLanguageError):
        PreferencesStore(tmp_path).update(language="fr_FR")
    assert not _file(tmp_path).exists()


# --------------------------------------------------------------------------- read-only folder


def test_read_only_keeps_the_change_for_the_session_only(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path, writable=False)
    result = store.update(language="en_US")
    assert result.language == "en_US"
    assert store.current.language == "en_US"
    assert not store.persisted
    assert PreferencesWarning.NOT_SAVED in store.warnings
    assert list(tmp_path.iterdir()) == []


def test_read_only_never_modifies_an_existing_file(tmp_path: Path) -> None:
    PreferencesStore(tmp_path).update(language="es_ES")
    before = _file(tmp_path).read_bytes()
    store = PreferencesStore(tmp_path, writable=False)
    assert store.load().language == "es_ES"
    store.update(language="en_US", startup_summary=False)
    assert store.current == Preferences("en_US", False, False)
    assert _file(tmp_path).read_bytes() == before
    assert _temp_files(tmp_path) == []


# --------------------------------------------------------------------------- atomic writes


def test_no_temporary_file_remains_after_success(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path)
    for code in ("en_US", "es_ES", "pt_BR"):
        store.update(language=code)
    assert _temp_files(tmp_path) == []
    assert [p.name for p in tmp_path.iterdir()] == [PREFS_FILE_NAME]


def test_write_failure_keeps_the_session_value_and_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PreferencesStore(tmp_path)
    store.update(language="es_ES")
    before = _file(tmp_path).read_bytes()

    def fail(_self: Path, _target: object) -> Path:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "replace", fail)
    result = store.update(language="en_US")

    assert result.language == "en_US"
    assert store.current.language == "en_US"
    assert not store.persisted
    assert PreferencesWarning.NOT_SAVED in store.warnings
    assert _file(tmp_path).read_bytes() == before
    assert _temp_files(tmp_path) == []


def test_os_replace_failure_is_handled_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(prefs_module.os, "replace", fail)
    store = PreferencesStore(tmp_path)
    assert store.update(startup_summary=False).startup_summary is False
    assert PreferencesWarning.NOT_SAVED in store.warnings
    assert not _file(tmp_path).exists()
    assert _temp_files(tmp_path) == []


def test_fsync_failure_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_fd: int) -> None:
        raise OSError("io error")

    monkeypatch.setattr(prefs_module.os, "fsync", fail)
    store = PreferencesStore(tmp_path)
    store.update(language="en_US")
    assert store.warnings == (PreferencesWarning.NOT_SAVED,)
    assert list(tmp_path.iterdir()) == []


def test_a_transient_sharing_violation_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = Path.replace
    calls: list[int] = []

    def flaky(self: Path, target: Path) -> Path:
        calls.append(1)
        if len(calls) <= 2:
            raise PermissionError("sharing violation")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    store = PreferencesStore(tmp_path)
    assert store.update(language="en_US").language == "en_US"

    assert len(calls) == 3
    assert store.persisted
    assert store.warnings == ()
    assert PreferencesStore(tmp_path).load().language == "en_US"
    assert _temp_files(tmp_path) == []


def test_a_permanent_sharing_violation_gives_not_saved_and_keeps_the_old_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = PreferencesStore(tmp_path)
    store.update(language="es_ES")
    before = _file(tmp_path).read_bytes()
    calls: list[int] = []

    def always(_self: Path, _target: object) -> Path:
        calls.append(1)
        raise PermissionError("sharing violation")

    monkeypatch.setattr(Path, "replace", always)
    assert store.update(language="en_US").language == "en_US"

    assert len(calls) == 4  # the first attempt and three immediate retries
    assert not store.persisted
    assert store.warnings == (PreferencesWarning.NOT_SAVED,)
    assert _file(tmp_path).read_bytes() == before
    assert _temp_files(tmp_path) == []


def test_other_os_errors_are_not_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def disk_full(_self: Path, _target: object) -> Path:
        calls.append(1)
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", disk_full)
    store = PreferencesStore(tmp_path)
    store.update(language="en_US")
    assert len(calls) == 1
    assert store.warnings == (PreferencesWarning.NOT_SAVED,)


def test_stale_temporary_files_are_removed_on_load_when_writable(tmp_path: Path) -> None:
    _write(tmp_path, '{"language": "es_ES"}')
    stale = [tmp_path / f"{PREFS_FILE_NAME}.tmp-abc123", tmp_path / f"{PREFS_FILE_NAME}.tmp-"]
    for path in stale:
        path.write_text("{partial", encoding="utf-8")
    other = tmp_path / "notes.txt"
    other.write_text("keep me", encoding="utf-8")

    store = PreferencesStore(tmp_path)
    assert store.load().language == "es_ES"

    assert _temp_files(tmp_path) == []
    assert other.read_text(encoding="utf-8") == "keep me"
    assert _file(tmp_path).exists()


def test_stale_temporary_files_are_removed_even_without_a_prefs_file(tmp_path: Path) -> None:
    leftover = tmp_path / f"{PREFS_FILE_NAME}.tmp-xyz"
    leftover.write_text("x", encoding="utf-8")
    assert PreferencesStore(tmp_path).load() == Preferences()
    assert not leftover.exists()


def test_stale_temporary_files_are_left_alone_when_read_only(tmp_path: Path) -> None:
    leftover = tmp_path / f"{PREFS_FILE_NAME}.tmp-abc123"
    leftover.write_text("x", encoding="utf-8")
    store = PreferencesStore(tmp_path, writable=False)
    store.load()
    store.update(language="en_US")
    assert leftover.exists()


def test_a_file_with_a_byte_order_mark_is_loaded(tmp_path: Path) -> None:
    content = json.dumps({"language": "en_US", "startup_summary": False, "future": [1]})
    _file(tmp_path).write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))
    store = PreferencesStore(tmp_path)
    assert store.load() == Preferences(language="en_US", startup_summary=False)
    assert store.warnings == ()

    store.update(first_run_notice_shown=True)  # unknown keys survive the rewrite
    data = json.loads(_file(tmp_path).read_text(encoding="utf-8"))
    assert data["future"] == [1]
    assert data["language"] == "en_US"
    assert data["first_run_notice_shown"] is True


def test_missing_folder_is_not_saved_and_not_an_error(tmp_path: Path) -> None:
    store = PreferencesStore(tmp_path / "does-not-exist")
    assert store.update(language="en_US").language == "en_US"
    assert PreferencesWarning.NOT_SAVED in store.warnings
    assert not (tmp_path / "does-not-exist").exists()


def test_successful_save_clears_a_previous_not_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_self: Path, _target: object) -> Path:
        raise OSError("x")

    store = PreferencesStore(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail)
        store.update(language="en_US")
    assert not store.persisted
    store.update(language="es_ES")
    assert store.persisted
    assert store.warnings == ()
    assert PreferencesStore(tmp_path).load().language == "es_ES"
