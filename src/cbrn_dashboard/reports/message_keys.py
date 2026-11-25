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
    "DEGREE_STATUS_KEYS",
    "EXERCISE_KIND_KEYS",
    "FUNDING_SOURCE_KEYS",
    "LOT_STATUS_KEYS",
    "SHARED_AREAS",
    "STOCK_CATEGORY_KEYS",
    "STOCK_TYPE_KEYS",
    "MessageKey",
    "all_shared_keys",
    "stock_type_key",
]

type MessageKey = tuple[str, str]

#: The areas whose catalogues the renderer loads besides its own ``reports`` area.
SHARED_AREAS: Final[tuple[str, ...]] = (
    "shell",
    "personnel",
    "infrastructure",
    "exercises",
    "budget",
    "stock",
)

#: ``CertStatus`` values (the retraining list).
CERT_STATUS_KEYS: Final[dict[str, MessageKey]] = {
    "VALID": ("Personnel", "Valid"),
    "EXPIRING": ("Personnel", "Expiring"),
    "EXPIRED": ("Personnel", "Expired"),
    "NO_RENEWAL": ("Personnel", "No renewal"),
    "NONE": ("Personnel", "No qualification"),
}

#: ``DegreeLevel`` values.
DEGREE_LEVEL_KEYS: Final[dict[str, MessageKey]] = {
    "specialisation": ("Personnel", "Specialisation"),
    "master": ("Personnel", "Master's degree"),
    "doctorate": ("Personnel", "Doctorate"),
}

#: ``DegreeStatus`` values.
DEGREE_STATUS_KEYS: Final[dict[str, MessageKey]] = {
    "completed": ("Personnel", "Completed"),
    "in_progress": ("Personnel", "In progress"),
}

#: ``ExerciseKind`` values with a translated name (``CBRAMED`` and ``EXBRAMED`` are proper names).
EXERCISE_KIND_KEYS: Final[dict[str, MessageKey]] = {
    "OTHER": ("Exercises", "Other"),
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
    "COMAER": ("Budget", "Air Force Command"),
}

#: The 17 built-in stock item types (migration 0009); a user-defined type is named by its own
#: stored labels. The source texts are the ones of ``ui/stock/labels.py`` (context ``Stock``).
STOCK_TYPE_KEYS: Final[dict[str, MessageKey]] = {
    "ANTIDOTE_CHEMICAL": ("Stock", "Chemical antidote"),
    "ANTIDOTE_RAD_NUCLEAR": ("Stock", "Radiological and nuclear antidote"),
    "ANTIDOTE_BIOLOGICAL": ("Stock", "Biological antidote"),
    "DECONTAMINANT": ("Stock", "Decontaminant"),
    "DETECTOR_CHEMICAL": ("Stock", "Chemical detector"),
    "DETECTOR_RAD_NUCLEAR": ("Stock", "Radiological and nuclear detector"),
    "DETECTOR_BIOLOGICAL": ("Stock", "Biological detector"),
    "MASK_FULL_FACE": ("Stock", "Full-face mask"),
    "FILTER_CBRN": ("Stock", "CBRN filter"),
    "PPE_LEVEL_A": ("Stock", "Level A PPE"),
    "PPE_LEVEL_B": ("Stock", "Level B PPE"),
    "PPE_LEVEL_C": ("Stock", "Level C PPE"),
    "GLOVE": ("Stock", "Glove"),
    "BOOT": ("Stock", "Boot"),
    "APRON": ("Stock", "Apron"),
    "OXYGEN_CYLINDER": ("Stock", "Oxygen cylinder (O2)"),
    "ISOLATION_STRETCHER": ("Stock", "Bubble stretcher (isolation transport capsule)"),
}

#: ``StockCategory`` values; the source texts are the ones of ``ui/stock/labels.py``.
STOCK_CATEGORY_KEYS: Final[dict[str, MessageKey]] = {
    "antidote": ("Stock", "Antidote"),
    "decontaminant": ("Stock", "Decontaminant"),
    "detector": ("Stock", "Detector"),
    "ppe": ("Stock", "PPE"),
    "other": ("Stock", "Other"),
}

#: ``LotStatus`` values; the source texts are the ones of ``ui/stock/labels.py``.
LOT_STATUS_KEYS: Final[dict[str, MessageKey]] = {
    "VALID": ("Stock", "Valid"),
    "EXPIRING": ("Stock", "Expiring soon"),
    "EXPIRED": ("Stock", "Expired"),
    "EMPTY": ("Stock", "Empty"),
    "NOT_RECEIVED": ("Stock", "Not yet received"),
}


def stock_type_key(code: str) -> MessageKey | None:
    """The message key of a built-in stock item type, or ``None`` for any other code."""
    return STOCK_TYPE_KEYS.get(code)


def all_shared_keys() -> tuple[MessageKey, ...]:
    """Every shared message key (for the catalogue check)."""
    tables = (
        CERT_STATUS_KEYS,
        DEGREE_LEVEL_KEYS,
        DEGREE_STATUS_KEYS,
        EXERCISE_KIND_KEYS,
        ASSET_TYPE_KEYS,
        FUNDING_SOURCE_KEYS,
        STOCK_TYPE_KEYS,
        STOCK_CATEGORY_KEYS,
        LOT_STATUS_KEYS,
    )
    keys: list[MessageKey] = []
    for table in tables:
        keys.extend(table.values())
    return tuple(keys)
