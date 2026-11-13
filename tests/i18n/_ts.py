# SPDX-License-Identifier: GPL-3.0-or-later
"""Helpers shared by the translation tests: ``.ts`` parsing and the ``scripts/i18n.py`` loader."""

import ast
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

QT_APPLICATION_CLASSES = frozenset({"QCoreApplication", "QGuiApplication", "QApplication"})


def receiver_names(node: ast.expr) -> set[str]:
    """Names along an attribute chain: ``QtCore.QCoreApplication`` -> both names."""
    names: set[str] = set()
    while isinstance(node, ast.Attribute):
        names.add(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.add(node.id)
    return names


def translate_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return ``(class names, function names)`` that stand for ``QCoreApplication``/``translate``.

    Understands ``from ... import QCoreApplication as QCA``, ``from ... import translate as t`` and
    the plain alias ``_translate = QCoreApplication.translate``.
    """
    class_names = set(QT_APPLICATION_CLASSES)
    function_names = {"translate"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in QT_APPLICATION_CLASSES:
                    class_names.add(alias.asname or alias.name)
                elif alias.name == "translate":
                    function_names.add(alias.asname or alias.name)
        elif (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "translate"
            and receiver_names(node.value.value) & class_names
        ):
            function_names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return class_names, function_names


def is_translate_call(call: ast.Call, class_names: set[str], function_names: set[str]) -> bool:
    """Whether ``call`` is ``X.translate(...)`` (>= 2 args or a Qt class receiver) or bare."""
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr == "translate" and (
            bool(receiver_names(func.value) & class_names) or len(call.args) >= 2
        )
    return isinstance(func, ast.Name) and func.id in function_names


def find_translate_calls(source: str, filename: str = "<snippet>") -> list[ast.Call]:
    """Return every ``translate(...)`` call found in ``source``."""
    tree = ast.parse(source, filename=filename)
    class_names, function_names = translate_aliases(tree)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and is_translate_call(node, class_names, function_names)
    ]


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
