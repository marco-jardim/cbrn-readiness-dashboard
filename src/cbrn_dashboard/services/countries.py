# SPDX-License-Identifier: GPL-3.0-or-later
"""The country list (ISO 3166-1 alpha-2, localized names) loaded from ``countries.json``.

The file is read through :mod:`importlib.resources`, so it also works in the frozen executable.
The result is cached: the file never changes while the program runs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from types import MappingProxyType

__all__ = [
    "LANGUAGES",
    "Country",
    "cldr_version",
    "country_codes",
    "is_known_country",
    "load_countries",
]

#: Language keys used by ``countries.json`` (and by the localized labels of the services).
LANGUAGES: tuple[str, ...] = ("pt_BR", "en_US", "es_ES")

_RESOURCE_PACKAGE = "cbrn_dashboard.resources"
_RESOURCE_NAME = "countries.json"


@dataclass(frozen=True)
class Country:
    """A country: its upper-case ISO code and its names keyed ``pt_BR``/``en_US``/``es_ES``."""

    code: str
    names: Mapping[str, str] = field(hash=False)

    def name(self, lang: str) -> str:
        """The name in ``lang``; falls back to pt_BR, then en_US, then the code."""
        key = lang.replace("-", "_")
        for candidate in (key, "pt_BR", "en_US"):
            text = self.names.get(candidate)
            if text:
                return text
        return self.code


@lru_cache(maxsize=1)
def _load() -> tuple[str, tuple[Country, ...]]:
    text = resources.files(_RESOURCE_PACKAGE).joinpath(_RESOURCE_NAME).read_text(encoding="utf-8")
    document = json.loads(text)
    version = str(document["cldr_version"])
    countries: list[Country] = []
    for entry in document["countries"]:
        names = {lang: str(entry[lang]) for lang in LANGUAGES if lang in entry}
        countries.append(Country(code=str(entry["code"]), names=MappingProxyType(names)))
    return version, tuple(countries)


def load_countries() -> tuple[Country, ...]:
    """Every country, in file order."""
    return _load()[1]


@lru_cache(maxsize=1)
def country_codes() -> frozenset[str]:
    """The set of known country codes."""
    return frozenset(country.code for country in load_countries())


def is_known_country(code: str) -> bool:
    """Whether ``code`` is exactly (case-sensitive) a known upper-case country code."""
    return code in country_codes()


def cldr_version() -> str:
    """The CLDR version the names come from."""
    return _load()[0]
