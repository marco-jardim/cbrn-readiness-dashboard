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
* Integers handed to ``QLocale.toString`` must fit in 64 bits (|n| < 2**63). Formatting a
  larger magnitude raises ``TOO_LARGE``; so does parsing an amount of 2**63 minor units or more
  (the SQLite INTEGER limit) and parsing a plain number of 10**18 or more.
* The currency allow-list and its decimal places come from :mod:`cbrn_dashboard.domain.budget`
  (D15, single source of truth). A currency outside it raises ``INVALID_CURRENCY``.

Separator rule (what "ambiguous" means)
---------------------------------------
The **locale's own separators are authoritative**. Text that follows them is read that way, even
when it would also be valid under the other convention with a different value:

* pt-BR ``1.234`` is 1234 and en-US ``1,234`` is 1234 (the group separator typed with no
  decimals is read as an integer **by design**; this is how Brazilian and Spanish users type
  thousands, and ``1.234,56`` must be accepted as well).

Text that does **not** follow the locale's separators but would parse under the other convention
is rejected with ``AMBIGUOUS_NUMBER``, so that a number typed in the wrong convention is never
silently misread:

* pt-BR ``1.23`` (read as 1.23 elsewhere) and ``1,234.56`` are rejected; en-US ``1,5`` too.

:func:`other_convention_value` is a pure safety net for dialogs: it reports the value an
accepted text would have under the swapped separators, so a confirmation hint can be shown. It
does not change what is accepted.
"""

import re
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import Final

from PySide6.QtCore import QDate, QLocale
from PySide6.QtWidgets import QDateEdit, QWidget

from cbrn_dashboard.domain.budget import currency_decimals, is_valid_currency
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
TOO_LARGE: Final = "TOO_LARGE"


class FormatError(ValueError):
    """Raised when a value cannot be formatted or parsed; ``code`` is stable and untranslated."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code: str = code


# --------------------------------------------------------------------------------------------
# Locale helpers

_NBSP: Final = "\xa0"
_CTX: Final = Context(prec=100)
_INT64_MAX: Final = 2**63 - 1  # largest integer QLocale.toString and SQLite INTEGER take
_INT64_MIN: Final = -(2**63)
_MAX_NUMBER_DIGITS: Final = 18  # parse_number accepts |value| < 10**18


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


def format_month(value: date, lang: str) -> str:
    """Format the month of ``value`` as the month name and the year, capitalised (``March 2026``).

    The month name comes from the locale data of Qt, which writes it in lower case in pt-BR and
    es-ES; the first letter is raised here. The day of ``value`` is ignored.
    """
    text = locale_for(lang).toString(to_qdate(value), "MMMM yyyy")
    return text[:1].upper() + text[1:]


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
    # 10**19 > 2**63; checking first also keeps ``quantize`` within the context precision.
    if value and value.adjusted() >= 19:
        raise FormatError(TOO_LARGE, "magnitude does not fit in 64 bits")
    rounded = value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP, context=_CTX)
    text = format(abs(rounded), "f")
    major, _, fraction = text.partition(".")
    if int(major) > _INT64_MAX:
        raise FormatError(TOO_LARGE, "magnitude does not fit in 64 bits")
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

# The allow-list and the decimal places live in domain/budget.py (D15). Every currency of the
# allow-list needs a symbol here (a test checks it).
_CURRENCY_SYMBOLS: Final[dict[str, str]] = {"BRL": "R$", "EUR": "€", "USD": "US$"}
# Placement of the symbol, as CLDR does it: pt "R$ 1,00", en "R$1.00", es "1,00 R$".
_MONEY_TEMPLATES: Final[dict[str, str]] = {
    "pt_BR": f"{{symbol}}{_NBSP}{{number}}",
    "en_US": "{symbol}{number}",
    "es_ES": f"{{number}}{_NBSP}{{symbol}}",
}


def _currency_decimals(currency: str) -> int:
    """Decimal places of ``currency``; ``INVALID_CURRENCY`` outside the allow-list."""
    if not is_valid_currency(currency):
        raise FormatError(INVALID_CURRENCY, f"currency not in the allow-list: {currency!r}")
    return currency_decimals(currency)


def currency_symbol(currency: str) -> str:
    """Return the display symbol of ``currency`` (``INVALID_CURRENCY`` if not allowed)."""
    _currency_decimals(currency)
    return _CURRENCY_SYMBOLS[currency]


def format_amount(minor_units: int, currency: str, lang: str) -> str:
    """Format whole ``minor_units`` as a plain number without symbol (for input fields).

    Exact integer arithmetic. A negative amount gets a leading ``-``. ``INVALID_CURRENCY``
    outside the allow-list; ``TOO_LARGE`` when ``minor_units`` is outside the signed 64-bit
    range.
    """
    decimals = _currency_decimals(currency)
    if not _INT64_MIN <= minor_units <= _INT64_MAX:
        raise FormatError(TOO_LARGE, "amount does not fit in 64 bits")
    locale = locale_for(lang)
    major, fraction = divmod(abs(minor_units), 10**decimals)
    result = locale.toString(major)
    if decimals:
        result += locale.decimalPoint() + str(fraction).zfill(decimals)
    return f"-{result}" if minor_units < 0 else result


def format_money(minor_units: int, currency: str, lang: str) -> str:
    """Format whole ``minor_units`` of ``currency`` with its symbol placed as ``lang`` does.

    pt-BR ``R$<nbsp>1.234,56``, en-US ``R$1,234.56``, es-ES ``1234,56<nbsp>R$``. A negative
    amount gets a ``-`` before everything (``-R$<nbsp>1,00``). ``INVALID_CURRENCY`` outside the
    allow-list; ``TOO_LARGE`` when ``minor_units`` is outside the signed 64-bit range.
    """
    code = to_catalogue_code(lang)
    symbol = currency_symbol(currency)
    number = format_amount(minor_units, currency, code).removeprefix("-")
    template = _MONEY_TEMPLATES[code]
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

    The locale's own separators are authoritative. Accepts plain digits or digits grouped by the
    locale's group separator in groups of three, and at most one decimal separator. A value
    typed with the group separator and no decimals is read as an integer **by design**:
    ``1.234`` is 1234 in pt-BR/es-ES and ``1,234`` is 1234 in en-US, although the other
    convention would read 1.234. Text that does not follow the locale's separators but would
    parse under the other convention (``1.23`` and ``1,234.56`` in pt-BR, ``1,5`` in en-US) is
    rejected with ``AMBIGUOUS_NUMBER`` so that it is never silently misread; use
    :func:`other_convention_value` to detect the case where an accepted text has a different
    valid reading. Spaces and ``'`` are refused; other garbage raises ``INVALID_NUMBER``; blank
    input ``EMPTY``. A magnitude of 10**18 or more raises ``TOO_LARGE``.
    """
    locale = locale_for(lang)
    negative, body = _strip_sign(text.strip())
    integer, fraction = _parse_digits(body.strip(), locale)
    if len(integer.lstrip("0")) > _MAX_NUMBER_DIGITS:
        raise FormatError(TOO_LARGE, "magnitude must be below 10**18")
    value = _to_value(integer, fraction)
    return -value if negative else value


def _to_value(integer: str, fraction: str) -> Decimal:
    return Decimal(f"{integer}.{fraction}" if fraction else integer)


def other_convention_value(text: str, lang: str) -> Decimal | None:
    """Return the value ``text`` would have with the separators swapped, if it differs.

    Pure safety net, e.g. for a confirmation hint in a dialog; it never changes what
    :func:`parse_number` accepts. The result is not ``None`` only when ``text`` is valid under
    BOTH the locale's own separators and the swapped ones, with different values: pt-BR
    ``"1.234"`` (read as 1234) gives ``Decimal("1.234")``; en-US ``"1,234"`` gives
    ``Decimal("1.234")``. ``"1.234,56"`` (valid only one way), ``"1234"`` (same value both ways),
    blank or invalid text give ``None``. A leading minus is honoured; currency symbols are not
    stripped.
    """
    locale = locale_for(lang)
    negative, body = _strip_sign(text.strip())
    body = body.strip()
    decimal_point = locale.decimalPoint()
    group = locale.groupSeparator()
    own = _scan(body, decimal_point, group)
    swapped = _scan(body, group, decimal_point)
    if own is None or swapped is None:
        return None
    own_value = _to_value(*own)
    swapped_value = _to_value(*swapped)
    if own_value == swapped_value:
        return None
    return -swapped_value if negative else swapped_value


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

    Same separator rule as :func:`parse_number` (the locale's own separators are authoritative;
    pt-BR ``1.234`` is 1234 major units, i.e. 123400 minor units, by design; pt-BR ``1.23`` is
    rejected as ``AMBIGUOUS_NUMBER``). Plus: a currency symbol or ISO code of ``currency`` as
    prefix or suffix is tolerated; fewer fraction digits than the currency has are padded
    (``1.234,5`` -> 123450); more raise ``TOO_MANY_DECIMALS``; a negative amount raises
    ``NEGATIVE_AMOUNT`` (after the text has been found otherwise valid). A currency outside the
    allow-list raises ``INVALID_CURRENCY``; a result of 2**63 minor units or more (the SQLite
    INTEGER limit) raises ``TOO_LARGE``. Exact: no float.
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
    digits = (integer + fraction.ljust(decimals, "0")).lstrip("0")
    if len(digits) > len(str(_INT64_MAX)) or int(digits or "0") > _INT64_MAX:
        raise FormatError(TOO_LARGE, "amount does not fit in 64 bits")
    return int(digits or "0")
