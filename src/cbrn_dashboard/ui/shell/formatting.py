# SPDX-License-Identifier: GPL-3.0-or-later
"""Locale-aware formatting and parsing of dates, numbers, percentages and money (T1.10).

Every function takes an explicit language code (``pt_BR``, ``en_US`` or ``es_ES``; the BCP-47
form ``pt-BR`` is accepted too) validated through :mod:`cbrn_dashboard.i18n`. Nothing here reads
the global default locale except :func:`current_language_locale`.

Design notes
------------
* The module holds **no translatable text**. Failures raise :class:`FormatError` with a stable
  ``code``; the UI layer maps codes to translated labels.
* Dates use explicit four-digit-year patterns (``QLocale.ShortFormat`` yields two-digit years).
* Money is a whole number of minor units plus an ISO 4217 code (D15) and is formatted from
  integers only (``divmod``); no float is involved. Parsing user input is exact
  (:class:`decimal.Decimal` / integers).
* Parsing does **not** use ``QLocale.toDouble``: es-ES refuses ``1.234,56`` there (minimum
  grouping rule) although the budget dialog must accept it. Parsing is implemented here from the
  locale's decimal and group separators.
* The exact strings of ``QLocale`` depend on the CLDR version inside the pinned Qt; the tests
  are regenerated deliberately on a Qt upgrade.
* Integers handed to ``QLocale.toString`` must fit in 64 bits (|n| < 2**63).
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Final

from PySide6.QtCore import QDate, QLocale
from PySide6.QtWidgets import QDateEdit, QWidget

from cbrn_dashboard.i18n import to_catalogue_code

# --------------------------------------------------------------------------------------------
# Error codes

EMPTY: Final = "EMPTY"
INVALID_NUMBER: Final = "INVALID_NUMBER"
AMBIGUOUS_NUMBER: Final = "AMBIGUOUS_NUMBER"
NEGATIVE_AMOUNT: Final = "NEGATIVE_AMOUNT"
TOO_MANY_DECIMALS: Final = "TOO_MANY_DECIMALS"
INVALID_DATE: Final = "INVALID_DATE"
INVALID_CURRENCY: Final = "INVALID_CURRENCY"


class FormatError(ValueError):
    """Raised when a value cannot be formatted or parsed; ``code`` is stable and untranslated."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code: str = code


# --------------------------------------------------------------------------------------------
# Locale helpers

_NBSP: Final = "\xa0"
_CTX: Final = Context(prec=100)


def locale_for(lang: str) -> QLocale:
    """Return the :class:`QLocale` of ``lang`` (raises ``UnknownLanguageError`` otherwise)."""
    return QLocale(to_catalogue_code(lang))


def current_language_locale() -> QLocale:
    """Return the application's default locale (set by the shell on language change).

    The only function of this module that reads global state.
    """
    return QLocale()


def apply_locale(widget: QWidget, lang: str) -> None:
    """Give ``widget`` the locale of ``lang`` (``QLocale.setDefault`` does not update widgets).

    A :class:`QDateEdit` also gets the four-digit-year display format of the language.
    """
    widget.setLocale(locale_for(lang))
    if isinstance(widget, QDateEdit):
        widget.setDisplayFormat(date_pattern(lang))


# --------------------------------------------------------------------------------------------
# Dates

_DATE_PATTERNS: Final[dict[str, str]] = {
    "pt_BR": "dd/MM/yyyy",
    "es_ES": "dd/MM/yyyy",
    "en_US": "MM/dd/yyyy",
}


def date_pattern(lang: str) -> str:
    """Return the Qt date pattern of ``lang`` (for ``QDateEdit.setDisplayFormat``)."""
    return _DATE_PATTERNS[to_catalogue_code(lang)]


def to_qdate(value: date) -> QDate:
    """Convert a :class:`datetime.date` to a :class:`QDate`."""
    return QDate(value.year, value.month, value.day)


def from_qdate(value: QDate) -> date:
    """Convert a valid :class:`QDate` to a :class:`datetime.date`."""
    if not value.isValid():
        raise FormatError(INVALID_DATE, "invalid QDate")
    return date(value.year(), value.month(), value.day())


def format_date(value: date, lang: str) -> str:
    """Format ``value`` with the four-digit-year pattern of ``lang`` (``05/03/2026``)."""
    return locale_for(lang).toString(to_qdate(value), date_pattern(lang))


def format_iso_date_text(iso: str, lang: str) -> str:
    """Format an ISO ``YYYY-MM-DD`` text (as stored in the database) for ``lang``."""
    if len(iso) != 10:
        raise FormatError(INVALID_DATE, f"not an ISO date: {iso!r}")
    try:
        value = date.fromisoformat(iso)
    except ValueError as exc:
        raise FormatError(INVALID_DATE, f"not an ISO date: {iso!r}") from exc
    return format_date(value, lang)


def _date_regex(pattern: str) -> re.Pattern[str]:
    body = (
        re.escape(pattern)
        .replace("dd", "(?P<d>[0-9]{2})")
        .replace("MM", "(?P<m>[0-9]{2})")
        .replace("yyyy", "(?P<y>[0-9]{4})")
    )
    return re.compile(body, re.ASCII)


_DATE_REGEXES: Final[dict[str, re.Pattern[str]]] = {
    code: _date_regex(pattern) for code, pattern in _DATE_PATTERNS.items()
}


def parse_date(text: str, lang: str) -> date:
    """Parse ``text`` strictly against the date pattern of ``lang``.

    Two-digit day and month, four-digit year, a real calendar date; surrounding whitespace is
    ignored. Raises :class:`FormatError` with code ``INVALID_DATE`` otherwise.
    """
    regex = _DATE_REGEXES[to_catalogue_code(lang)]
    match = regex.fullmatch(text.strip())
    if match is None:
        raise FormatError(INVALID_DATE, f"does not match {date_pattern(lang)}")
    try:
        return date(int(match["y"]), int(match["m"]), int(match["d"]))
    except ValueError as exc:
        raise FormatError(INVALID_DATE, "not a calendar date") from exc


# --------------------------------------------------------------------------------------------
# Numbers and percentages


def _to_decimal(value: float | int | Decimal) -> Decimal:
    """Exact decimal of ``value``; floats go through their shortest repr (1234.5 -> 1234.5)."""
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    else:
        result = Decimal(repr(value))
    if not result.is_finite():
        raise FormatError(INVALID_NUMBER, "not a finite number")
    return result


def _format_decimal(value: Decimal, locale: QLocale, decimals: int) -> str:
    """Round half up to ``decimals`` places and group with the locale; sign is ``-``."""
    if decimals < 0:
        raise ValueError("decimals must be >= 0")
    rounded = value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP, context=_CTX)
    text = format(abs(rounded), "f")
    major, _, fraction = text.partition(".")
    result = locale.toString(int(major))
    if fraction:
        result += locale.decimalPoint() + fraction
    return f"-{result}" if rounded < 0 else result


def format_number(value: float | int | Decimal, lang: str, *, decimals: int | None = None) -> str:
    """Format a number with the grouping and decimal separator of ``lang``.

    ``decimals=None`` gives the shortest exact fixed representation: integers have no decimals,
    floats use their shortest round-trip text (``1234.5`` -> one decimal) and a ``Decimal``
    keeps its own exponent. An explicit ``decimals`` rounds half up. Grouping is the locale's
    (es-ES does not group four-digit numbers).
    """
    locale = locale_for(lang)
    number = _to_decimal(value)
    if decimals is None:
        exponent = number.as_tuple().exponent
        places = max(0, -exponent) if isinstance(exponent, int) else 0
    else:
        places = decimals
    return _format_decimal(number, locale, places)


# CLDR percent patterns: pt "#,##0%", en "#,##0%", es "#,##0 %" (non-breaking space).
# QLocale exposes no percent pattern, hence this small table.
_PERCENT_SUFFIX: Final[dict[str, str]] = {"pt_BR": "%", "en_US": "%", "es_ES": f"{_NBSP}%"}


def format_percent(ratio: float | Decimal, lang: str, *, decimals: int = 1) -> str:
    """Format ``ratio`` (0.4567 = 45.67 %) as a percentage with ``decimals`` places."""
    code = to_catalogue_code(lang)
    percent = _CTX.multiply(_to_decimal(ratio), Decimal(100))
    return _format_decimal(percent, locale_for(code), decimals) + _PERCENT_SUFFIX[code]


# --------------------------------------------------------------------------------------------
# Money

# TODO(T5.2): domain/budget.py becomes the source of truth of the currency allow-list and its
# decimal places (D15); this table is then replaced by an import.
CURRENCY_DECIMALS: Final[dict[str, int]] = {"BRL": 2, "USD": 2, "EUR": 2}

_DEFAULT_DECIMALS: Final = 2
_CURRENCY_SYMBOLS: Final[dict[str, str]] = {"BRL": "R$", "EUR": "€", "USD": "US$"}
# Placement of the symbol, as CLDR does it: pt "R$ 1,00", en "R$1.00", es "1,00 R$".
_MONEY_TEMPLATES: Final[dict[str, str]] = {
    "pt_BR": f"{{symbol}}{_NBSP}{{number}}",
    "en_US": "{symbol}{number}",
    "es_ES": f"{{number}}{_NBSP}{{symbol}}",
}
_CURRENCY_CODE: Final = re.compile(r"[A-Z]{3}", re.ASCII)


def _currency_decimals(currency: str) -> int:
    if _CURRENCY_CODE.fullmatch(currency) is None:
        raise FormatError(INVALID_CURRENCY, f"not an ISO 4217 code: {currency!r}")
    return CURRENCY_DECIMALS.get(currency, _DEFAULT_DECIMALS)


def currency_symbol(currency: str) -> str:
    """Return the display symbol of ``currency`` (the ISO code when it has no symbol)."""
    _currency_decimals(currency)
    return _CURRENCY_SYMBOLS.get(currency, currency)


def format_amount(minor_units: int, currency: str, lang: str) -> str:
    """Format whole ``minor_units`` as a plain number without symbol (for input fields).

    Exact integer arithmetic. A negative amount gets a leading ``-``.
    """
    decimals = _currency_decimals(currency)
    locale = locale_for(lang)
    major, fraction = divmod(abs(minor_units), 10**decimals)
    result = locale.toString(major)
    if decimals:
        result += locale.decimalPoint() + str(fraction).zfill(decimals)
    return f"-{result}" if minor_units < 0 else result


def format_money(minor_units: int, currency: str, lang: str) -> str:
    """Format whole ``minor_units`` of ``currency`` with its symbol placed as ``lang`` does.

    pt-BR ``R$<nbsp>1.234,56``, en-US ``R$1,234.56``, es-ES ``1234,56<nbsp>R$``. Currencies
    without a symbol in the map show their ISO code (en-US then adds a non-breaking space so
    the code does not touch the digits). A negative amount gets a ``-`` before everything
    (``-R$<nbsp>1,00``).
    """
    code = to_catalogue_code(lang)
    symbol = currency_symbol(currency)
    number = format_amount(abs(minor_units), currency, code)
    template = _MONEY_TEMPLATES[code]
    if code == "en_US" and symbol[-1].isalpha():
        template = f"{{symbol}}{_NBSP}{{number}}"
    result = template.format(symbol=symbol, number=number)
    return f"-{result}" if minor_units < 0 else result


# --------------------------------------------------------------------------------------------
# Parsing user input

_MINUS_SIGNS: Final = ("-", "\u2212")


def _scan(body: str, decimal_point: str, group: str) -> tuple[str, str] | None:
    """Return ``(integer digits, fraction digits)`` if ``body`` is valid for the separators.

    The integer part is plain digits or a 1-3 digit head (no leading zero) followed by groups
    of exactly three digits; at most one decimal point, followed by at least one digit.
    """
    grp = re.escape(group)
    dec = re.escape(decimal_point)
    integer = rf"(?:[0-9]+|[1-9][0-9]{{0,2}}(?:{grp}[0-9]{{3}})+)"
    match = re.fullmatch(rf"({integer})(?:{dec}([0-9]+))?", body, re.ASCII)
    if match is None:
        return None
    return match.group(1).replace(group, ""), match.group(2) or ""


def _parse_digits(body: str, locale: QLocale) -> tuple[str, str]:
    """Parse an unsigned number text into ``(integer digits, fraction digits)``."""
    if not body:
        raise FormatError(EMPTY, "no input")
    decimal_point = locale.decimalPoint()
    group = locale.groupSeparator()
    result = _scan(body, decimal_point, group)
    if result is not None:
        return result
    if _scan(body, group, decimal_point) is not None:
        raise FormatError(AMBIGUOUS_NUMBER, f"{body!r} is only valid with swapped separators")
    raise FormatError(INVALID_NUMBER, f"not a number: {body!r}")


def _strip_sign(text: str) -> tuple[bool, str]:
    if text and text[0] in _MINUS_SIGNS:
        return True, text[1:].strip()
    return False, text


def parse_number(text: str, lang: str) -> Decimal:
    """Parse a number typed in ``lang`` exactly (optional leading ``-``).

    Accepts plain digits or digits grouped by the locale's group separator in groups of three,
    and at most one decimal separator. Spaces, ``'`` and the other convention's separators are
    refused: text valid only under the other convention (``1,234.56`` in pt-BR/es-ES, ``1,5``
    in en-US, ``1.5`` in pt-BR) raises ``AMBIGUOUS_NUMBER``; other garbage ``INVALID_NUMBER``;
    blank input ``EMPTY``. ``1.234`` is 1234 in pt-BR/es-ES and ``1,234`` is 1234 in en-US.
    """
    locale = locale_for(lang)
    negative, body = _strip_sign(text.strip())
    integer, fraction = _parse_digits(body.strip(), locale)
    value = Decimal(f"{integer}.{fraction}" if fraction else integer)
    return -value if negative else value


def _strip_currency(text: str, currency: str) -> str:
    """Remove one prefix or suffix equal to the currency symbol or ISO code."""
    candidates = sorted({currency_symbol(currency), currency}, key=len, reverse=True)
    for candidate in candidates:
        size = len(candidate)
        if text[:size].casefold() == candidate.casefold():
            return text[size:].strip()
        if text[-size:].casefold() == candidate.casefold():
            return text[:-size].strip()
    return text


def parse_amount(text: str, currency: str, lang: str) -> int:
    """Parse an amount typed in ``lang`` into whole minor units of ``currency``.

    Same rules as :func:`parse_number`, plus: a currency symbol or ISO code of ``currency`` as
    prefix or suffix is tolerated; fewer fraction digits than the currency has are padded
    (``1.234,5`` -> 123450); more raise ``TOO_MANY_DECIMALS``; a negative amount raises
    ``NEGATIVE_AMOUNT`` (after the text has been found otherwise valid). Exact: no float.
    """
    decimals = _currency_decimals(currency)
    locale = locale_for(lang)
    negative, body = _strip_sign(text.strip())
    body = _strip_currency(body, currency)
    if not negative:
        negative, body = _strip_sign(body)
    integer, fraction = _parse_digits(body.strip(), locale)
    if len(fraction) > decimals:
        raise FormatError(TOO_MANY_DECIMALS, f"{currency} has {decimals} decimal places")
    if negative:
        raise FormatError(NEGATIVE_AMOUNT, "amounts cannot be negative")
    return int(integer + fraction.ljust(decimals, "0"))
