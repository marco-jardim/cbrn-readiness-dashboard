# SPDX-License-Identifier: GPL-3.0-or-later
"""Sync check (PLAN.md section 6, check 4): every string in the code is in the catalogues."""

import shutil
from pathlib import Path

import pytest

from cbrn_dashboard import i18n
from tests.i18n._ts import catalogue_files, load_script, parse_ts

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
