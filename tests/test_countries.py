# SPDX-License-Identifier: GPL-3.0-or-later
"""T4.2: the committed country reference data (``countries.json``) and its notice.

The generator script is loaded by path only for its embedded code list; Babel is not needed.
"""

import importlib.util
import json
import re
import sys
import tomllib
from functools import cache
from importlib import resources
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "gen_countries.py"
LOCALES = ("pt_BR", "en_US", "es_ES")
EXCLUDED = ("XK", "AC", "CP", "DG", "EA", "IC", "TA", "EU", "EZ", "UN", "QO", "ZZ")


@cache
def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cbrn_gen_countries_script", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@cache
def _document() -> dict[str, Any]:
    text = (
        resources.files("cbrn_dashboard.resources")
        .joinpath("countries.json")
        .read_text(encoding="utf-8")
    )
    document = json.loads(text)
    assert isinstance(document, dict)
    return document


def _countries() -> list[dict[str, str]]:
    countries = _document()["countries"]
    assert isinstance(countries, list)
    return countries


def _by_code() -> dict[str, dict[str, str]]:
    return {entry["code"]: entry for entry in _countries()}


def test_embedded_list_is_249_sorted_unique_codes() -> None:
    codes = _load_script().ISO_3166_1_ALPHA2
    assert len(codes) == 249
    assert len(set(codes)) == 249
    assert list(codes) == sorted(codes)


def test_codes_are_unique_two_uppercase_ascii_letters() -> None:
    codes = [entry["code"] for entry in _countries()]
    assert len(codes) == len(set(codes))
    for code in codes:
        assert re.fullmatch(r"[A-Z]{2}", code), code


def test_codes_equal_the_embedded_list_exactly() -> None:
    codes = [entry["code"] for entry in _countries()]
    assert set(codes) == set(_load_script().ISO_3166_1_ALPHA2)
    assert len(codes) == 249


def test_non_iso_codes_are_absent() -> None:
    present = set(_by_code())
    assert present.isdisjoint(EXCLUDED)


def test_every_entry_has_three_non_empty_names() -> None:
    for entry in _countries():
        for locale in LOCALES:
            name = entry.get(locale)
            assert isinstance(name, str), (entry["code"], locale)
            assert name.strip(), (entry["code"], locale)


def test_countries_are_sorted_by_code() -> None:
    codes = [entry["code"] for entry in _countries()]
    assert codes == sorted(codes)


def test_cldr_version_is_recorded() -> None:
    version = _document()["cldr_version"]
    assert isinstance(version, str)
    assert version.strip()


@pytest.mark.parametrize(
    ("code", "pt_br", "en_us", "es_es"),
    [
        ("BR", "Brasil", "Brazil", "Brasil"),
        ("DE", "Alemanha", "Germany", "Alemania"),
    ],
)
def test_spot_checks(code: str, pt_br: str, en_us: str, es_es: str) -> None:
    entry = _by_code()[code]
    assert entry["pt_BR"] == pt_br
    assert entry["en_US"] == en_us
    assert entry["es_ES"] == es_es


def test_united_states_english_name() -> None:
    assert _by_code()["US"]["en_US"] == "United States"


def test_notice_file_names_the_unicode_licence() -> None:
    notice = resources.files("cbrn_dashboard.resources").joinpath("THIRD_PARTY_DATA.md")
    assert notice.is_file()
    text = notice.read_text(encoding="utf-8")
    assert "Unicode" in text
    assert "CLDR" in text


def _pyproject() -> dict[str, Any]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def _requirement_names(requirements: list[Any]) -> list[str]:
    names: list[str] = []
    for requirement in requirements:
        if isinstance(requirement, str):
            match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement.strip())
            if match:
                names.append(match.group(0).lower().replace("_", "-"))
    return names


def test_babel_is_not_a_runtime_dependency() -> None:
    dependencies = _pyproject()["project"]["dependencies"]
    assert "babel" not in _requirement_names(dependencies)


def test_babel_is_in_the_tools_group() -> None:
    tools = _pyproject()["dependency-groups"]["tools"]
    assert "babel" in _requirement_names(tools)
