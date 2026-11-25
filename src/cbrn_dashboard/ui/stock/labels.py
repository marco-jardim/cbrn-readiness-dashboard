# SPDX-License-Identifier: GPL-3.0-or-later
"""Translated labels of the codes the stock UI can show (PLAN.md Phase 11, T11.9; design section 5).

The 17 built-in item types have no labels in the database: their names live here (translation
context ``Stock``, one literal ``translate`` call each, so the extraction finds them). A
user-defined type shows its own labels with the fallback of
:func:`~cbrn_dashboard.services.stock.stock_type_label` (language asked for, pt-BR, en-US, code).
The categories, the movement kinds and the lot statuses have one entry each. Every error code of the
stock service, of the shared service errors, of the configuration service and every ``FormatError``
code a typed price can raise has one explicit entry (or the generic configuration message); an
unknown code is shown as itself, never as an exception.
"""

import re
from collections.abc import Callable, Mapping

from PySide6.QtCore import QCoreApplication

from cbrn_dashboard.domain.stock import LotStatus, MovementKind, StockCategory
from cbrn_dashboard.services.config import CONFIG_ERROR_CODES, CORRUPT_SETTING
from cbrn_dashboard.services.errors import (
    CODE_IMMUTABLE,
    INVALID_CODE,
    INVALID_DATE,
    LABEL_PT_BR_REQUIRED,
    NOT_FOUND,
    READ_ONLY,
    REQUIRED,
)
from cbrn_dashboard.services.stock import (
    BALANCE_NEGATIVE,
    BUILT_IN_TYPE,
    CATEGORY_IMMUTABLE,
    DATE_IN_FUTURE,
    DUPLICATE_CODE,
    DUPLICATE_LOT,
    DUPLICATE_MOVEMENT,
    EXPIRY_REQUIRED,
    INITIAL_RECEIPT_REQUIRED,
    INVALID_AMOUNT,
    INVALID_CATEGORY,
    INVALID_CURRENCY,
    INVALID_KIND,
    INVALID_MONTHS,
    INVALID_QUANTITY,
    NOTE_REQUIRED,
    ONLY_MOVEMENT,
    TEXT_TOO_LONG,
    TYPE_IMMUTABLE,
    TYPE_IN_USE,
    TYPE_INACTIVE,
    StockTypeView,
    stock_type_label,
)
from cbrn_dashboard.ui.shell.formatting import (
    AMBIGUOUS_NUMBER,
    EMPTY,
    INVALID_NUMBER,
    NEGATIVE_AMOUNT,
    TOO_LARGE,
    TOO_MANY_DECIMALS,
)
from cbrn_dashboard.ui.shell.widgets import label_for

__all__ = [
    "ALL_ERROR_CODES",
    "BUILT_IN_TYPE_CODES",
    "category_label",
    "code_label",
    "error_label",
    "fill_placeholders",
    "join_texts",
    "kind_label",
    "lot_status_label",
    "stock_type_display",
    "type_name",
]

_BUILT_IN_LABELS: dict[str, Callable[[], str]] = {
    "ANTIDOTE_CHEMICAL": lambda: QCoreApplication.translate("Stock", "Chemical antidote"),
    "ANTIDOTE_RAD_NUCLEAR": lambda: QCoreApplication.translate(
        "Stock", "Radiological and nuclear antidote"
    ),
    "ANTIDOTE_BIOLOGICAL": lambda: QCoreApplication.translate("Stock", "Biological antidote"),
    "DECONTAMINANT": lambda: QCoreApplication.translate("Stock", "Decontaminant"),
    "DETECTOR_CHEMICAL": lambda: QCoreApplication.translate("Stock", "Chemical detector"),
    "DETECTOR_RAD_NUCLEAR": lambda: QCoreApplication.translate(
        "Stock", "Radiological and nuclear detector"
    ),
    "DETECTOR_BIOLOGICAL": lambda: QCoreApplication.translate("Stock", "Biological detector"),
    "MASK_FULL_FACE": lambda: QCoreApplication.translate("Stock", "Full-face mask"),
    "FILTER_CBRN": lambda: QCoreApplication.translate("Stock", "CBRN filter"),
    "PPE_LEVEL_A": lambda: QCoreApplication.translate("Stock", "Level A PPE"),
    "PPE_LEVEL_B": lambda: QCoreApplication.translate("Stock", "Level B PPE"),
    "PPE_LEVEL_C": lambda: QCoreApplication.translate("Stock", "Level C PPE"),
    "GLOVE": lambda: QCoreApplication.translate("Stock", "Glove"),
    "BOOT": lambda: QCoreApplication.translate("Stock", "Boot"),
    "APRON": lambda: QCoreApplication.translate("Stock", "Apron"),
    "OXYGEN_CYLINDER": lambda: QCoreApplication.translate("Stock", "Oxygen cylinder (O2)"),
    "ISOLATION_STRETCHER": lambda: QCoreApplication.translate(
        "Stock", "Bubble stretcher (isolation transport capsule)"
    ),
}

# The codes of the 17 built-in item types, in the order of the seed migration.
BUILT_IN_TYPE_CODES: tuple[str, ...] = tuple(_BUILT_IN_LABELS)

_CATEGORY_LABELS: dict[str, Callable[[], str]] = {
    StockCategory.ANTIDOTE.value: lambda: QCoreApplication.translate("Stock", "Antidote"),
    StockCategory.DECONTAMINANT.value: lambda: QCoreApplication.translate("Stock", "Decontaminant"),
    StockCategory.DETECTOR.value: lambda: QCoreApplication.translate("Stock", "Detector"),
    StockCategory.PPE.value: lambda: QCoreApplication.translate("Stock", "PPE"),
    StockCategory.OTHER.value: lambda: QCoreApplication.translate("Stock", "Other"),
}

_KIND_LABELS: dict[str, Callable[[], str]] = {
    MovementKind.RECEIPT.value: lambda: QCoreApplication.translate("Stock", "Receipt"),
    MovementKind.ISSUE.value: lambda: QCoreApplication.translate("Stock", "Issue (consumption)"),
    MovementKind.DISPOSAL.value: lambda: QCoreApplication.translate("Stock", "Disposal"),
    MovementKind.LOSS.value: lambda: QCoreApplication.translate("Stock", "Loss"),
    MovementKind.ADJUSTMENT_IN.value: lambda: QCoreApplication.translate(
        "Stock", "Adjustment (increase)"
    ),
    MovementKind.ADJUSTMENT_OUT.value: lambda: QCoreApplication.translate(
        "Stock", "Adjustment (decrease)"
    ),
}

_STATUS_LABELS: dict[str, Callable[[], str]] = {
    LotStatus.VALID.value: lambda: QCoreApplication.translate("Stock", "Valid"),
    LotStatus.EXPIRING.value: lambda: QCoreApplication.translate("Stock", "Expiring soon"),
    LotStatus.EXPIRED.value: lambda: QCoreApplication.translate("Stock", "Expired"),
    LotStatus.EMPTY.value: lambda: QCoreApplication.translate("Stock", "Empty"),
    LotStatus.NOT_RECEIVED.value: lambda: QCoreApplication.translate("Stock", "Not yet received"),
}

_ERROR_LABELS: dict[str, Callable[[], str]] = {
    # stock service
    BALANCE_NEGATIVE: lambda: QCoreApplication.translate(
        "Stock", "The change would leave the stock of this lot below zero on some date."
    ),
    CATEGORY_IMMUTABLE: lambda: QCoreApplication.translate(
        "Stock",
        "The category cannot be changed because the type is already in use "
        "(lots, a minimum, stored readings or targets).",
    ),
    TYPE_IMMUTABLE: lambda: QCoreApplication.translate(
        "Stock", "The item type of a lot that has movements cannot be changed."
    ),
    DATE_IN_FUTURE: lambda: QCoreApplication.translate(
        "Stock", "A movement cannot be dated after today."
    ),
    DUPLICATE_LOT: lambda: QCoreApplication.translate(
        "Stock", "This item type already has a lot with this code."
    ),
    DUPLICATE_MOVEMENT: lambda: QCoreApplication.translate(
        "Stock", "The lot already has a movement with this date, kind, quantity and reference."
    ),
    EXPIRY_REQUIRED: lambda: QCoreApplication.translate(
        "Stock", "Antidote and decontaminant lots need an expiry date."
    ),
    INITIAL_RECEIPT_REQUIRED: lambda: QCoreApplication.translate(
        "Stock", "Enter the date and the quantity (at least 1) of the first receipt."
    ),
    INVALID_CATEGORY: lambda: QCoreApplication.translate("Stock", "The category is not valid."),
    INVALID_KIND: lambda: QCoreApplication.translate("Stock", "The kind of movement is not valid."),
    INVALID_MONTHS: lambda: QCoreApplication.translate(
        "Stock", "The number of months must be from 1 to 60."
    ),
    INVALID_QUANTITY: lambda: QCoreApplication.translate(
        "Stock", "The quantity must be a whole number inside the allowed range."
    ),
    NOTE_REQUIRED: lambda: QCoreApplication.translate("Stock", "An adjustment needs a note."),
    ONLY_MOVEMENT: lambda: QCoreApplication.translate(
        "Stock",
        "The last movement of a lot cannot be deleted. Close the lot with a disposal or loss.",
    ),
    # services shared with the other modules, as they apply to stock
    BUILT_IN_TYPE: lambda: QCoreApplication.translate(
        "Stock",
        "A built-in item type cannot be deleted; only its minimum and active flag can change.",
    ),
    CODE_IMMUTABLE: lambda: QCoreApplication.translate(
        "Stock",
        "The code cannot be changed because the type is already in use "
        "(lots, a minimum, stored readings or targets).",
    ),
    DUPLICATE_CODE: lambda: QCoreApplication.translate("Stock", "This code is already in use."),
    INVALID_AMOUNT: lambda: QCoreApplication.translate("Stock", "The price is not valid."),
    INVALID_CURRENCY: lambda: QCoreApplication.translate("Stock", "The currency is not valid."),
    LABEL_PT_BR_REQUIRED: lambda: QCoreApplication.translate(
        "Stock", "The Portuguese (Brazil) label is required."
    ),
    TEXT_TOO_LONG: lambda: QCoreApplication.translate("Stock", "The text is too long."),
    TYPE_INACTIVE: lambda: QCoreApplication.translate(
        "Stock", "The item type is inactive and cannot receive new lots."
    ),
    TYPE_IN_USE: lambda: QCoreApplication.translate(
        "Stock", "Lots use this item type, so it cannot be deleted. Deactivate it instead."
    ),
    READ_ONLY: lambda: QCoreApplication.translate(
        "Stock", "The data is read-only: nothing was saved."
    ),
    NOT_FOUND: lambda: QCoreApplication.translate("Stock", "The record no longer exists."),
    REQUIRED: lambda: QCoreApplication.translate("Stock", "A required field is empty."),
    INVALID_DATE: lambda: QCoreApplication.translate("Stock", "The date is not valid."),
    INVALID_CODE: lambda: QCoreApplication.translate(
        "Stock",
        "Use only letters, digits, dot, hyphen and underscore; start with a letter or digit.",
    ),
    # typed prices (FormatError codes)
    EMPTY: lambda: QCoreApplication.translate("Stock", "Enter a value."),
    INVALID_NUMBER: lambda: QCoreApplication.translate("Stock", "The number is not valid."),
    AMBIGUOUS_NUMBER: lambda: QCoreApplication.translate(
        "Stock", "The number uses the separators of another language."
    ),
    NEGATIVE_AMOUNT: lambda: QCoreApplication.translate("Stock", "The price cannot be negative."),
    TOO_MANY_DECIMALS: lambda: QCoreApplication.translate(
        "Stock", "The price has more decimal places than the currency allows."
    ),
    TOO_LARGE: lambda: QCoreApplication.translate("Stock", "The price is too large."),
    # configuration service (reading the default currency)
    CORRUPT_SETTING: lambda: QCoreApplication.translate(
        "Stock", "A stored setting cannot be read."
    ),
}

for _config_code in CONFIG_ERROR_CODES:
    # Any other configuration code (a later one included) still gets a translated message.
    _ERROR_LABELS.setdefault(
        _config_code,
        lambda: QCoreApplication.translate("Stock", "The setting is not valid."),
    )

# Every error code the stock UI can present (for the completeness test).
ALL_ERROR_CODES: tuple[str, ...] = tuple(_ERROR_LABELS)

_PLACEHOLDER = re.compile(r"%([1-9])")


def fill_placeholders(text: str, *values: str) -> str:
    """Replace ``%1``..``%9`` by ``values`` in ONE pass (a translation may reorder them).

    A value that itself contains ``%2`` is inserted as it is, never replaced again.
    """

    def substitute(match: re.Match[str]) -> str:
        position = int(match.group(1)) - 1
        return values[position] if position < len(values) else match.group(0)

    return _PLACEHOLDER.sub(substitute, text)


def error_label(code: str) -> str:
    """The translated message of an error code (the code itself when unknown)."""
    return label_for(_ERROR_LABELS, code)


def category_label(category: str) -> str:
    """The label of a stock category (``antidote``, ``decontaminant``, ``detector``, ...)."""
    return label_for(_CATEGORY_LABELS, str(category))


def kind_label(kind: str) -> str:
    """The label of a movement kind (``receipt``, ``issue``, ``adjustment_in``, ...)."""
    return label_for(_KIND_LABELS, str(kind))


def lot_status_label(status: str) -> str:
    """The label of a lot status (``VALID``, ``EXPIRING``, ``EXPIRED``, ``EMPTY``, ...)."""
    return label_for(_STATUS_LABELS, str(status))


def code_label(type_code: str) -> str:
    """The name of a type given only its code: built-in names are translated, others as is."""
    return label_for(_BUILT_IN_LABELS, type_code)


def stock_type_display(view: StockTypeView, lang: str) -> str:
    """The name of an item type: the translated name of a built-in one, else its own labels."""
    if view.built_in and view.code in _BUILT_IN_LABELS:
        return code_label(view.code)
    return stock_type_label(view, lang)


def type_name(code: str, lang: str, types: Mapping[str, StockTypeView]) -> str:
    """The name of the type with ``code``; the code itself when unknown and not built-in."""
    view = types.get(code)
    if view is not None:
        return stock_type_display(view, lang)
    return code_label(code)


def join_texts(texts: list[str]) -> str:
    """The texts of ``texts`` as one list, joined with the translated separator."""
    if not texts:
        return ""
    text = texts[0]
    for item in texts[1:]:
        text = fill_placeholders(QCoreApplication.translate("Stock", "%1, %2"), text, item)
    return text
