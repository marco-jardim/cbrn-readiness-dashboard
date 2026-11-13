# SPDX-License-Identifier: GPL-3.0-or-later
"""Languages, translation areas and catalogue locations (Qt-free; PLAN.md section 6).

Catalogues are Qt Linguist ``.ts`` files named ``<area>_<lang>.ts`` and live in this folder.
The compiled ``.qm`` files are never committed: ``scripts/i18n.py compile`` writes them here
(git-ignored), the test session writes them to a temporary folder.
"""

from pathlib import Path

LANGUAGES: tuple[str, ...] = ("pt_BR", "en_US", "es_ES")
"""Catalogue codes of the supported user-interface languages."""

DEFAULT_LANGUAGE = "pt_BR"
"""Language used on first start, whatever the Windows locale (F03)."""

PACKAGE_DIR = Path(__file__).resolve().parent
"""This folder: it holds the ``.ts`` catalogues and, once compiled, the ``.qm`` files."""

SOURCE_ROOT = PACKAGE_DIR.parent
"""``src/cbrn_dashboard``: the base of the paths in :data:`AREAS`."""

AREAS: dict[str, tuple[str, ...]] = {
    "shell": ("ui/shell", "app.py", "cli.py", "selftest.py", "__main__.py"),
    "personnel": ("ui/personnel",),
    "infrastructure": ("ui/infrastructure",),
    "exercises": ("ui/exercises",),
    "budget": ("ui/budget",),
    "alerts": ("ui/alerts",),
}
"""Translation areas -> source folders/files, relative to :data:`SOURCE_ROOT`.

Each later task adds one line for its area. Every entry is required to exist:
:func:`missing_source_paths` lists the ones that do not, a test asserts there are none and
``scripts/i18n.py update`` refuses to run while one is missing.
"""


class UnknownLanguageError(ValueError):
    """Raised for a language code that is not one of :data:`LANGUAGES`."""


def to_catalogue_code(lang: str) -> str:
    """Return the catalogue code (``pt_BR``) for ``pt_BR`` or the BCP-47 form ``pt-BR``."""
    code = lang.replace("-", "_")
    if code not in LANGUAGES:
        raise UnknownLanguageError(f"Unknown language code: {lang!r}")
    return code


def to_bcp47(lang: str) -> str:
    """Return the BCP-47 form (``pt-BR``) for ``pt_BR`` or ``pt-BR``."""
    return to_catalogue_code(lang).replace("_", "-")


def catalogue_path(area: str, lang: str) -> Path:
    """Return the path of the ``.ts`` catalogue of ``area`` in ``lang``."""
    if area not in AREAS:
        raise KeyError(f"Unknown translation area: {area!r}")
    return PACKAGE_DIR / f"{area}_{to_catalogue_code(lang)}.ts"


def qm_name(area: str, lang: str) -> str:
    """Return the file name of the compiled catalogue of ``area`` in ``lang``."""
    if area not in AREAS:
        raise KeyError(f"Unknown translation area: {area!r}")
    return f"{area}_{to_catalogue_code(lang)}.qm"


def qm_dir() -> Path:
    """Return the default folder holding the compiled ``.qm`` files."""
    return PACKAGE_DIR


def source_paths(area: str) -> list[Path]:
    """Return the existing source folders/files of ``area`` (absolute paths)."""
    if area not in AREAS:
        raise KeyError(f"Unknown translation area: {area!r}")
    candidates = (SOURCE_ROOT / entry for entry in AREAS[area])
    return [path for path in candidates if path.exists()]


def missing_source_paths(area: str) -> tuple[str, ...]:
    """Return the entries of ``area`` in :data:`AREAS` that do not exist (empty when all do)."""
    if area not in AREAS:
        raise KeyError(f"Unknown translation area: {area!r}")
    return tuple(entry for entry in AREAS[area] if not (SOURCE_ROOT / entry).exists())
