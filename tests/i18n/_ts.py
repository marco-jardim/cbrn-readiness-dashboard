# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers shared by the translation tests: ``.ts`` parsing and the ``scripts/i18n.py`` loader."""

import importlib.util
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import ModuleType

from cbrn_dashboard import i18n

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "i18n.py"
SRC_ROOT = REPO_ROOT / "src"

PLACEHOLDER_RE = re.compile(r"%(?:L?[1-9]|n)")

#: Number of ``<numerusform>`` entries Qt expects for each language.
EXPECTED_NUMERUS_FORMS: dict[str, int] = {"pt_BR": 2, "en_US": 2, "es_ES": 2}

MessageKey = tuple[str, str, bool]


@dataclass(frozen=True)
class Message:
    """One ``<message>`` of a catalogue."""

    context: str
    source: str
    numerus: bool
    translations: tuple[str, ...]
    """One entry for a plain message, one per ``<numerusform>`` for a plural message."""
    status: str
    """The ``type`` attribute of ``<translation>``: ``""``, ``unfinished``, ``obsolete``..."""

    @property
    def key(self) -> MessageKey:
        return (self.context, self.source, self.numerus)


@dataclass(frozen=True)
class Catalogue:
    """A parsed ``.ts`` file."""

    path: Path
    language: str
    source_language: str
    messages: tuple[Message, ...]

    @property
    def keys(self) -> set[MessageKey]:
        return {message.key for message in self.messages}


@cache
def load_script() -> ModuleType:
    """Import ``scripts/i18n.py`` by path (``scripts/`` is not a package)."""
    spec = importlib.util.spec_from_file_location("cbrn_i18n_script", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def catalogue_files() -> list[tuple[str, str, Path]]:
    """Return ``(area, language, path)`` for every catalogue that must exist."""
    return [
        (area, lang, i18n.catalogue_path(area, lang))
        for area in i18n.AREAS
        for lang in i18n.LANGUAGES
    ]


def parse_ts(path: Path) -> Catalogue:
    """Parse a ``.ts`` file."""
    root = ET.parse(path).getroot()
    messages: list[Message] = []
    for context in root.findall("context"):
        name = context.findtext("name") or ""
        for message in context.findall("message"):
            translation = message.find("translation")
            numerus = message.get("numerus") == "yes"
            if translation is None:
                forms: tuple[str, ...] = ()
                status = "missing"
            else:
                status = translation.get("type", "")
                if numerus:
                    forms = tuple(f.text or "" for f in translation.findall("numerusform"))
                else:
                    forms = (translation.text or "",)
            messages.append(
                Message(
                    context=name,
                    source=message.findtext("source") or "",
                    numerus=numerus,
                    translations=forms,
                    status=status,
                )
            )
    return Catalogue(
        path=path,
        language=root.get("language", ""),
        source_language=root.get("sourcelanguage", ""),
        messages=tuple(messages),
    )


def placeholders(text: str) -> frozenset[str]:
    """Return the set of ``%1``..``%9`` / ``%n`` placeholders of ``text``."""
    return frozenset(PLACEHOLDER_RE.findall(text))


def write_pseudo_ts(source: Path, target: Path) -> None:
    """Write a copy of catalogue ``source`` whose every translation is ``⟦<source text>⟧``."""
    tree = ET.parse(source)
    for message in tree.getroot().iter("message"):
        text = message.findtext("source") or ""
        translation = message.find("translation")
        if translation is None:
            translation = ET.SubElement(message, "translation")
        translation.attrib.pop("type", None)
        wrapped = f"\u27e6{text}\u27e7"
        forms = translation.findall("numerusform")
        if forms:
            for form in forms:
                form.text = wrapped
        else:
            translation.text = wrapped
    body = ET.tostring(tree.getroot(), encoding="unicode")
    target.write_text(
        f'<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE TS>\n{body}\n', encoding="utf-8"
    )
