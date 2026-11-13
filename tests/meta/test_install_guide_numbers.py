# SPDX-License-Identifier: GPL-3.0-or-later
"""The install guides state numbers and menu names that live in code: tie them together (P10-06).

The guides are read as they are (section "Backups" of each). What is compared with the code:

* the retention of the three backup pools (``storage/backup.py``, ``domain/config.py``): the
  daily pool keeps the newest ``daily_backups_kept`` copies and never fewer than the hard floor,
  the pre-migration pool ``PRE_MIGRATION_KEEP`` and the before-restore pool ``BEFORE_RESTORE_KEEP``;
* the minimum length of the passphrase of an encrypted backup (``domain/config.py``);
* the File-menu entries, which are the strings of the ``Backup`` context in
  ``i18n/backup_<lang>.ts`` (the text the program shows, or the English source while empty).
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from cbrn_dashboard.domain.config import (
    DAILY_BACKUPS_FLOOR,
    PASSPHRASE_LENGTH_FLOOR,
    ReadinessConfig,
)
from cbrn_dashboard.storage.backup import BEFORE_RESTORE_KEEP, MIN_KEEP, PRE_MIGRATION_KEEP

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
I18N = ROOT / "src" / "cbrn_dashboard" / "i18n"

#: Guide file and catalogue language, by hand.
GUIDES = (
    ("install.en-US.md", "en_US"),
    ("install.pt-BR.md", "pt_BR"),
    ("install.es-ES.md", "es_ES"),
)

#: How each guide words the retention of the daily pool, of the two other pools (in the order
#: pre-migration, before restore) and the length of the passphrase. Written from the guides.
DAILY_PATTERN = {
    "en_US": r"the newest (\d+) are kept, never fewer than (\d+)",
    "pt_BR": r"as (\d+) mais recentes são mantidas, nunca menos de (\d+)",
    "es_ES": r"se conservan las (\d+) más recientes, nunca menos de (\d+)",
}
LAST_PATTERN = {
    "en_US": r"the last (\d+) are kept",
    "pt_BR": r"as últimas (\d+) são mantidas",
    "es_ES": r"se conservan las (\d+) últimas",
}
PASSPHRASE_PATTERN = {
    "en_US": r"passphrase has at least (\d+) characters",
    "pt_BR": r"senha tem pelo menos (\d+) caracteres",
    "es_ES": r"contraseña tiene al menos (\d+) caracteres",
}

#: The three File-menu entries of the backup actions (sources of the ``Backup`` context).
MENU_SOURCES = ("Back up...", "Restore...", "Open data folder")


def _text(guide: str) -> str:
    """The guide with every run of white space (line breaks included) as one space."""
    return " ".join((DOCS / guide).read_text(encoding="utf-8").split())


def _menu_names(language: str) -> list[str]:
    tree = ET.parse(I18N / f"backup_{language}.ts")
    names: dict[str, str] = {}
    for context in tree.getroot().iter("context"):
        if context.findtext("name") != "Backup":
            continue
        for message in context.iter("message"):
            source = message.findtext("source")
            if source in MENU_SOURCES:
                translation = message.findtext("translation") or ""
                names[str(source)] = translation or str(source)
    assert set(names) == set(MENU_SOURCES), (language, sorted(names))
    return [names[source] for source in MENU_SOURCES]


def test_the_constants_the_guides_are_tied_to() -> None:
    # Hand-written: the guides say 7 (never fewer than 2), 3 and 2. A change of a constant must
    # be a deliberate edit of the guides, so these numbers are fixed here as well.
    assert ReadinessConfig().daily_backups_kept == 7
    assert DAILY_BACKUPS_FLOOR == MIN_KEEP == 2
    assert PRE_MIGRATION_KEEP == 3
    assert BEFORE_RESTORE_KEEP == 2
    assert PASSPHRASE_LENGTH_FLOOR == 12
    assert ReadinessConfig().min_passphrase_length == PASSPHRASE_LENGTH_FLOOR


@pytest.mark.parametrize(("guide", "language"), GUIDES)
def test_the_guide_states_the_daily_retention_of_the_code(guide: str, language: str) -> None:
    match = re.search(DAILY_PATTERN[language], _text(guide))
    assert match is not None, f"{guide} does not state the daily retention"
    assert int(match.group(1)) == ReadinessConfig().daily_backups_kept
    assert int(match.group(2)) == DAILY_BACKUPS_FLOOR


@pytest.mark.parametrize(("guide", "language"), GUIDES)
def test_the_guide_states_the_other_two_pools_in_order(guide: str, language: str) -> None:
    kept = [int(number) for number in re.findall(LAST_PATTERN[language], _text(guide))]
    # First the pre-migration pool ("before each upgrade"), then the before-restore pool.
    assert kept == [PRE_MIGRATION_KEEP, BEFORE_RESTORE_KEEP], guide


@pytest.mark.parametrize(("guide", "language"), GUIDES)
def test_the_guide_states_the_passphrase_minimum_of_the_code(guide: str, language: str) -> None:
    match = re.search(PASSPHRASE_PATTERN[language], _text(guide))
    assert match is not None, f"{guide} does not state the passphrase minimum"
    assert int(match.group(1)) == PASSPHRASE_LENGTH_FLOOR


@pytest.mark.parametrize(("guide", "language"), GUIDES)
def test_the_guide_names_the_file_menu_entries_as_the_program_shows_them(
    guide: str, language: str
) -> None:
    text = _text(guide)
    missing = [name for name in _menu_names(language) if name not in text]
    assert missing == [], (guide, missing)
