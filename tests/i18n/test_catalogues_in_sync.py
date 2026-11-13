# SPDX-License-Identifier: GPL-3.0-or-later
"""Sync check (PLAN.md section 6, check 4): every string in the code is in the catalogues."""

import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from cbrn_dashboard import i18n
from tests.i18n._ts import catalogue_files, find_translate_calls, load_script, parse_ts

CATALOGUES = catalogue_files()


@pytest.mark.parametrize(
    ("area", "lang", "path"),
    CATALOGUES,
    ids=[f"{area}_{lang}" for area, lang, _ in CATALOGUES],
)
def test_lupdate_adds_and_removes_nothing(area: str, lang: str, path: Path, tmp_path: Path) -> None:
    copy = tmp_path / path.name
    shutil.copyfile(path, copy)
    before = parse_ts(copy).keys

    written = load_script().update_catalogues(tmp_path, areas=[area], languages=[lang])

    assert written == [copy], f"no existing source folder for area {area!r}"
    after = parse_ts(copy).keys
    assert not after - before, f"{path.name}: strings in code missing from the catalogue: " + str(
        sorted(after - before)
    )
    assert not before - after, f"{path.name}: catalogue entries not found in code: " + str(
        sorted(before - after)
    )


def test_every_area_has_all_catalogues() -> None:
    for area in i18n.AREAS:
        for lang in i18n.LANGUAGES:
            assert i18n.catalogue_path(area, lang).is_file()


# --- every translate() call belongs to an area, every AREAS entry exists -----------------------


def uncovered_translate_files(source_root: Path, areas: Mapping[str, Sequence[str]]) -> list[Path]:
    """Return the ``*.py`` files under ``source_root`` that call ``translate`` outside all areas.

    A file is covered when it is a listed file or lies inside a listed folder of some area.
    """
    entries = [source_root / entry for listed in areas.values() for entry in listed]
    uncovered: list[Path] = []
    for path in sorted(source_root.rglob("*.py")):
        if not find_translate_calls(path.read_text(encoding="utf-8"), str(path)):
            continue
        if not any(path == entry or entry in path.parents for entry in entries):
            uncovered.append(path)
    return uncovered


def test_every_translating_source_file_belongs_to_an_area() -> None:
    uncovered = uncovered_translate_files(i18n.SOURCE_ROOT, i18n.AREAS)
    assert not uncovered, (
        "files call translate() but are in no area of i18n.AREAS (their strings would ship "
        "untranslated): " + ", ".join(str(p.relative_to(i18n.SOURCE_ROOT)) for p in uncovered)
    )


def test_no_area_lists_a_missing_source_path() -> None:
    for area in i18n.AREAS:
        assert i18n.missing_source_paths(area) == (), area
        assert len(i18n.source_paths(area)) == len(i18n.AREAS[area]), area


def test_coverage_check_reports_an_uncovered_file(tmp_path: Path) -> None:
    (tmp_path / "ui" / "shell").mkdir(parents=True)
    (tmp_path / "ui" / "shell" / "deep").mkdir()
    (tmp_path / "ui" / "personnel").mkdir()
    (tmp_path / "ui" / "shell" / "window.py").write_text(
        'QCoreApplication.translate("Shell", "Quit")\n', encoding="utf-8"
    )
    (tmp_path / "ui" / "shell" / "deep" / "nested.py").write_text(
        'from PySide6.QtCore import QCoreApplication as QCA\nQCA.translate("Shell", "Open")\n',
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        '_translate = QCoreApplication.translate\n_translate("Shell", "Hi")\n', encoding="utf-8"
    )
    uncovered_page = tmp_path / "ui" / "personnel" / "page.py"
    uncovered_page.write_text('QCoreApplication.translate("Personnel", "Staff")\n', "utf-8")
    uncovered_alias = tmp_path / "other.py"
    uncovered_alias.write_text("from x import translate\ntranslate('A', 'B')\n", "utf-8")
    (tmp_path / "ui" / "personnel" / "plain.py").write_text("text.translate(table)\n", "utf-8")
    areas: dict[str, Sequence[str]] = {"shell": ("ui/shell", "app.py")}

    assert uncovered_translate_files(tmp_path, areas) == sorted([uncovered_alias, uncovered_page])

    areas["personnel"] = ("ui/personnel",)
    assert uncovered_translate_files(tmp_path, areas) == [uncovered_alias]


def test_missing_source_paths_reports_the_absent_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(i18n.AREAS, "ghost", ("ui/shell", "no_such_module.py"))
    assert i18n.missing_source_paths("ghost") == ("no_such_module.py",)
    assert i18n.source_paths("ghost") == [i18n.SOURCE_ROOT / "ui/shell"]
    with pytest.raises(KeyError):
        i18n.missing_source_paths("unknown-area")


# --- update_catalogues never damages a catalogue ------------------------------------------------

_ORIGINAL = b'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n<TS><!-- original --></TS>\n'
_REWRITTEN = b"<TS><!-- rewritten by the fake lupdate --></TS>\n"
_FOUND_OK = "Updating 'x.ts'...\n    Found 3 source text(s) (0 new and 3 already existing)\n"


def _install_fake_lupdate(
    monkeypatch: pytest.MonkeyPatch, returncode: int, output: str
) -> list[list[str]]:
    """Replace the tool runner: the fake rewrites the catalogue it is given, then reports."""
    script = load_script()
    commands: list[list[str]] = []

    def fake_run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        commands.append(list(command))
        Path(command[command.index("-ts") + 1]).write_bytes(_REWRITTEN)
        return subprocess.CompletedProcess(list(command), returncode, stdout=output, stderr="")

    monkeypatch.setattr(script, "_run", fake_run)
    monkeypatch.setattr(script, "find_tool", lambda name: Path(name))
    return commands


@pytest.fixture
def original_catalogue(tmp_path: Path) -> Path:
    path = tmp_path / "shell_pt_BR.ts"
    path.write_bytes(_ORIGINAL)
    return path


@pytest.mark.parametrize(
    ("returncode", "output"),
    [
        (0, "Found 0 source text(s) (0 new and 0 already existing)\n"),
        (0, "Updating 'x.ts'...\n"),
        (1, _FOUND_OK),
    ],
    ids=["zero-found", "no-found-line", "non-zero-exit"],
)
def test_failed_extraction_leaves_the_catalogue_untouched(
    monkeypatch: pytest.MonkeyPatch, original_catalogue: Path, returncode: int, output: str
) -> None:
    commands = _install_fake_lupdate(monkeypatch, returncode, output)
    script = load_script()

    with pytest.raises(script.ToolError):
        script.update_catalogues(original_catalogue.parent, areas=["shell"], languages=["pt_BR"])

    assert len(commands) == 1
    assert Path(commands[0][commands[0].index("-ts") + 1]) != original_catalogue
    assert original_catalogue.read_bytes() == _ORIGINAL


def test_successful_extraction_replaces_the_catalogue(
    monkeypatch: pytest.MonkeyPatch, original_catalogue: Path
) -> None:
    commands = _install_fake_lupdate(monkeypatch, 0, _FOUND_OK)

    written = load_script().update_catalogues(
        original_catalogue.parent, areas=["shell"], languages=["pt_BR"]
    )

    assert written == [original_catalogue]
    assert len(commands) == 1
    assert original_catalogue.read_bytes() == _REWRITTEN


def test_update_refuses_to_run_when_an_area_has_a_missing_source_path(
    monkeypatch: pytest.MonkeyPatch, original_catalogue: Path
) -> None:
    commands = _install_fake_lupdate(monkeypatch, 0, _FOUND_OK)
    monkeypatch.setitem(i18n.AREAS, "ghost", ("ui/shell", "renamed_module.py"))
    script = load_script()

    with pytest.raises(script.ToolError, match=r"renamed_module\.py"):
        script.update_catalogues(
            original_catalogue.parent, areas=["shell", "ghost"], languages=["pt_BR"]
        )

    assert commands == []
    assert original_catalogue.read_bytes() == _ORIGINAL


def test_update_works_on_a_copy_even_when_the_catalogue_does_not_exist_yet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_lupdate(monkeypatch, 0, _FOUND_OK)

    written = load_script().update_catalogues(tmp_path, areas=["shell"], languages=["es_ES"])

    assert written == [tmp_path / "shell_es_ES.ts"]
    assert written[0].read_bytes() == _REWRITTEN
