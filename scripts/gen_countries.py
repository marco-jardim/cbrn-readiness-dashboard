# SPDX-License-Identifier: GPL-3.0-or-later
"""Generate ``countries.json``: country names in pt_BR, en_US and es_ES from Unicode CLDR.

Development-time tool (PLAN T4.2, D20). It uses Babel, which lives in the ``tools`` dependency
group and is never a runtime dependency; only the generated JSON and the notice in
``THIRD_PARTY_DATA.md`` are shipped. Babel is imported inside the functions that need it, so
this module (and its ``ISO_3166_1_ALPHA2`` constant) can be imported without Babel installed.

Usage::

    uv run python scripts/gen_countries.py [--out PATH]

CLDR has more region codes than ISO 3166-1 (``XK``, ``AC``, ``CP``, ``DG``, ``EA``, ``IC``,
``TA``, deprecated codes, and non-countries such as ``EU``, ``EZ``, ``UN``, ``QO``, ``ZZ``).
Only the officially assigned ISO 3166-1 alpha-2 codes embedded below are kept.
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "src" / "cbrn_dashboard" / "resources" / "countries.json"

LOCALES: tuple[str, ...] = ("pt_BR", "en_US", "es_ES")

#: The officially assigned ISO 3166-1 alpha-2 codes (249).
ISO_3166_1_ALPHA2: tuple[str, ...] = tuple(
    [
        "AD",
        "AE",
        "AF",
        "AG",
        "AI",
        "AL",
        "AM",
        "AO",
        "AQ",
        "AR",
        "AS",
        "AT",
        "AU",
        "AW",
        "AX",
        "AZ",
        "BA",
        "BB",
        "BD",
        "BE",
        "BF",
        "BG",
        "BH",
        "BI",
        "BJ",
        "BL",
        "BM",
        "BN",
        "BO",
        "BQ",
        "BR",
        "BS",
        "BT",
        "BV",
        "BW",
        "BY",
        "BZ",
        "CA",
        "CC",
        "CD",
        "CF",
        "CG",
        "CH",
        "CI",
        "CK",
        "CL",
        "CM",
        "CN",
        "CO",
        "CR",
        "CU",
        "CV",
        "CW",
        "CX",
        "CY",
        "CZ",
        "DE",
        "DJ",
        "DK",
        "DM",
        "DO",
        "DZ",
        "EC",
        "EE",
        "EG",
        "EH",
        "ER",
        "ES",
        "ET",
        "FI",
        "FJ",
        "FK",
        "FM",
        "FO",
        "FR",
        "GA",
        "GB",
        "GD",
        "GE",
        "GF",
        "GG",
        "GH",
        "GI",
        "GL",
        "GM",
        "GN",
        "GP",
        "GQ",
        "GR",
        "GS",
        "GT",
        "GU",
        "GW",
        "GY",
        "HK",
        "HM",
        "HN",
        "HR",
        "HT",
        "HU",
        "ID",
        "IE",
        "IL",
        "IM",
        "IN",
        "IO",
        "IQ",
        "IR",
        "IS",
        "IT",
        "JE",
        "JM",
        "JO",
        "JP",
        "KE",
        "KG",
        "KH",
        "KI",
        "KM",
        "KN",
        "KP",
        "KR",
        "KW",
        "KY",
        "KZ",
        "LA",
        "LB",
        "LC",
        "LI",
        "LK",
        "LR",
        "LS",
        "LT",
        "LU",
        "LV",
        "LY",
        "MA",
        "MC",
        "MD",
        "ME",
        "MF",
        "MG",
        "MH",
        "MK",
        "ML",
        "MM",
        "MN",
        "MO",
        "MP",
        "MQ",
        "MR",
        "MS",
        "MT",
        "MU",
        "MV",
        "MW",
        "MX",
        "MY",
        "MZ",
        "NA",
        "NC",
        "NE",
        "NF",
        "NG",
        "NI",
        "NL",
        "NO",
        "NP",
        "NR",
        "NU",
        "NZ",
        "OM",
        "PA",
        "PE",
        "PF",
        "PG",
        "PH",
        "PK",
        "PL",
        "PM",
        "PN",
        "PR",
        "PS",
        "PT",
        "PW",
        "PY",
        "QA",
        "RE",
        "RO",
        "RS",
        "RU",
        "RW",
        "SA",
        "SB",
        "SC",
        "SD",
        "SE",
        "SG",
        "SH",
        "SI",
        "SJ",
        "SK",
        "SL",
        "SM",
        "SN",
        "SO",
        "SR",
        "SS",
        "ST",
        "SV",
        "SX",
        "SY",
        "SZ",
        "TC",
        "TD",
        "TF",
        "TG",
        "TH",
        "TJ",
        "TK",
        "TL",
        "TM",
        "TN",
        "TO",
        "TR",
        "TT",
        "TV",
        "TW",
        "TZ",
        "UA",
        "UG",
        "UM",
        "US",
        "UY",
        "UZ",
        "VA",
        "VC",
        "VE",
        "VG",
        "VI",
        "VN",
        "VU",
        "WF",
        "WS",
        "YE",
        "YT",
        "ZA",
        "ZM",
        "ZW",
    ]
)

_CODE_RE = re.compile(r"^[A-Z]{2}$")


def _check_code_list(codes: Sequence[str]) -> None:
    """Fail loudly unless ``codes`` is 249 unique, sorted, two-uppercase-letter codes."""
    if len(codes) != 249:
        raise AssertionError(f"expected 249 ISO 3166-1 alpha-2 codes, found {len(codes)}")
    if len(set(codes)) != len(codes):
        raise AssertionError("the embedded ISO 3166-1 alpha-2 list contains duplicates")
    if list(codes) != sorted(codes):
        raise AssertionError("the embedded ISO 3166-1 alpha-2 list is not sorted")
    bad = [code for code in codes if not _CODE_RE.fullmatch(code)]
    if bad:
        raise AssertionError(f"not two uppercase ASCII letters: {bad}")


_check_code_list(ISO_3166_1_ALPHA2)


def _scalar_version(value: Any) -> str | None:
    """Turn a version-like value found in Babel's data into a string, or ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    if isinstance(value, dict):
        for key in ("version", "number", "cldr_version", "cldr"):
            if key in value:
                found = _scalar_version(value[key])
                if found:
                    return found
    return None


def cldr_version() -> str:
    """Return the CLDR release Babel's bundled data was built from (never hard-coded)."""
    from babel.core import Locale, get_global

    keys = ("cldr_version", "cldr", "version")
    for key in keys:
        try:
            found = _scalar_version(get_global(key))
        except KeyError:
            continue
        if found:
            return found
    data = getattr(Locale.parse("en_US"), "_data", None)
    if data is not None:
        for key in keys:
            try:
                found = _scalar_version(data[key])
            except KeyError:
                continue
            if found:
                return found
    raise RuntimeError(
        "cannot determine the CLDR version from this Babel installation "
        "(tried get_global and locale data keys 'cldr_version', 'cldr', 'version')"
    )


def build_document() -> dict[str, Any]:
    """Build the JSON document (CLDR names for the embedded ISO codes) in memory."""
    import babel
    from babel.core import Locale

    territories = {name: Locale.parse(name).territories for name in LOCALES}
    countries: list[dict[str, str]] = []
    missing: list[str] = []
    for code in ISO_3166_1_ALPHA2:
        entry: dict[str, str] = {"code": code}
        for name in LOCALES:
            value = territories[name].get(code)
            if not value or not value.strip():
                missing.append(f"{code}/{name}")
                continue
            entry[name] = value
        countries.append(entry)
    if missing:
        raise RuntimeError(f"CLDR has no territory name for: {', '.join(missing)}")
    return {
        "cldr_version": cldr_version(),
        "source": f"Unicode CLDR via Babel {babel.__version__}",
        "countries": countries,
    }


def render_document(document: dict[str, Any]) -> bytes:
    """Serialise ``document`` deterministically: UTF-8, two-space indent, LF, final newline."""
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    return text.encode("utf-8")


def write_document(path: Path) -> None:
    """Write the generated document to ``path`` (parent directories are created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render_document(build_document()))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate countries.json from Unicode CLDR.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output file")
    args = parser.parse_args(argv)
    write_document(args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
