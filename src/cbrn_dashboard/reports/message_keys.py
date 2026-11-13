# SPDX-License-Identifier: GPL-3.0-or-later
"""Code to message-key map of the labels the report shares with the user interface (T8.6).

Qt-free. A message key is ``(context, source text)`` of a text that the UI catalogues already hold
(``shell``, ``personnel``, ``infrastructure``, ``budget``). The PDF renderer looks the key up in its
OWN translators for the language of the report (it never uses the installed application
translators), so the report and the UI say the same thing in the same words. A test checks that
every key here exists in the three catalogues of its area.

Codes without an entry here (and without one in ``labels.py``) are shown as themselves.
"""

from typing import Final

__all__ = [
    "ASSET_TYPE_KEYS",
    "CERT_STATUS_KEYS",
    "DEGREE_LEVEL_KEYS",
    "FUNDING_SOURCE_KEYS",
    "PRELIMINARY_KEY",
    "SHARED_AREAS",
    "MessageKey",
    "all_shared_keys",
]

type MessageKey = tuple[str, str]

#: The areas whose catalogues the renderer loads besides its own ``reports`` area.
SHARED_AREAS: Final[tuple[str, ...]] = ("shell", "personnel", "infrastructure", "budget")

#: The preliminary-version notice (I06, P07), as the shell banner words it (an em dash).
PRELIMINARY_KEY: Final[MessageKey] = (
    "Shell",
    "Preliminary version \u2014 indicators not institutionally validated.",
)

#: ``CertStatus`` values (the retraining list).
CERT_STATUS_KEYS: Final[dict[str, MessageKey]] = {
    "VALID": ("Personnel", "Valid"),
    "EXPIRING": ("Personnel", "Expiring"),
    "EXPIRED": ("Personnel", "Expired"),
    "NO_RENEWAL": ("Personnel", "No renewal"),
    "NONE": ("Personnel", "No certificate"),
}

#: ``DegreeLevel`` values.
DEGREE_LEVEL_KEYS: Final[dict[str, MessageKey]] = {
    "specialisation": ("Personnel", "Specialisation"),
    "master": ("Personnel", "Master's degree"),
    "doctorate": ("Personnel", "Doctorate"),
}

#: The built-in asset types; a user-defined type is shown by its code.
ASSET_TYPE_KEYS: Final[dict[str, MessageKey]] = {
    "bed": ("Infrastructure", "Bed"),
    "bay": ("Infrastructure", "Bay"),
    "neg_pressure_filtration": ("Infrastructure", "Negative-pressure and filtration equipment"),
    "decon_tent": ("Infrastructure", "Decontamination tent"),
}

#: The built-in funding sources that have a translated name (``DIRSA`` is a proper name).
FUNDING_SOURCE_KEYS: Final[dict[str, MessageKey]] = {
    "OPCW_TRUST_FUND": ("Budget", "OPCW Trust Fund"),
}


def all_shared_keys() -> tuple[MessageKey, ...]:
    """Every shared message key (for the catalogue check)."""
    tables = (CERT_STATUS_KEYS, DEGREE_LEVEL_KEYS, ASSET_TYPE_KEYS, FUNDING_SOURCE_KEYS)
    keys = [PRELIMINARY_KEY]
    for table in tables:
        keys.extend(table.values())
    return tuple(keys)
