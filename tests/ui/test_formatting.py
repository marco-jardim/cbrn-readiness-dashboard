# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests of the locale formatting and parsing helpers (T1.10).

The expected strings depend on the CLDR version inside the pinned Qt (PySide6 6.12.0) and are
regenerated deliberately on a Qt upgrade. ``\\xa0`` is a non-breaking space, always written
explicitly.
"""

from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pytest
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QDateEdit, QDoubleSpinBox
from pytestqt.qtbot import QtBot

from cbrn_dashboard.domain import budget as budget_domain
from cbrn_dashboard.domain.budget import CURRENCY_DECIMALS
from cbrn_dashboard.i18n import LANGUAGES, UnknownLanguageError
from cbrn_dashboard.ui.shell import formatting as fmt
from cbrn_dashboard.ui.shell.formatting import FormatError

FIXED_DATE = date(2026, 3, 5)


# ---------------------------------------------------------------------------- locale and dates


@pytest.mark.parametrize(
    ("lang", "name", "decimal_point", "group"),
    [("pt_BR", "pt_BR", ",", "."), ("en_US", "en_US", ".", ","), ("es_ES", "es_ES", ",", ".")],
)
def test_locale_for(lang: str, name: str, decimal_point: str, group: str) -> None:
    locale = fmt.locale_for(lang)
    assert locale.name() == name
    assert locale.decimalPoint() == decimal_point
    assert locale.groupSeparator() == group


def test_locale_for_accepts_bcp47() -> None:
    assert fmt.locale_for("pt-BR").name() == "pt_BR"


@pytest.mark.parametrize("lang", ["fr_FR", "pt", "", "PT_br"])
def test_unknown_language_is_rejected(lang: str) -> None:
    with pytest.raises(UnknownLanguageError):
        fmt.locale_for(lang)
    with pytest.raises(UnknownLanguageError):
        fmt.format_date(FIXED_DATE, lang)
    with pytest.raises(UnknownLanguageError):
        fmt.format_number(1.5, lang)
    with pytest.raises(UnknownLanguageError):
        fmt.format_percent(0.5, lang)
    with pytest.raises(UnknownLanguageError):
        fmt.format_money(100, "BRL", lang)
    with pytest.raises(UnknownLanguageError):
        fmt.parse_number("1", lang)
    with pytest.raises(UnknownLanguageError):
        fmt.parse_amount("1", "BRL", lang)
    with pytest.raises(UnknownLanguageError):
        fmt.parse_date("05/03/2026", lang)


def test_current_language_locale_returns_a_qlocale() -> None:
    assert isinstance(fmt.current_language_locale(), QLocale)


@pytest.mark.parametrize(
    ("lang", "expected", "pattern"),
    [
        ("pt_BR", "05/03/2026", "dd/MM/yyyy"),
        ("es_ES", "05/03/2026", "dd/MM/yyyy"),
        ("en_US", "03/05/2026", "MM/dd/yyyy"),
    ],
)
def test_format_date(lang: str, expected: str, pattern: str) -> None:
    assert fmt.format_date(FIXED_DATE, lang) == expected
    assert fmt.date_pattern(lang) == pattern
    assert fmt.format_iso_date_text("2026-03-05", lang) == expected


@pytest.mark.parametrize(
    ("lang", "value", "expected"),
    [
        ("en_US", date(2026, 3, 5), "March 2026"),
        ("pt_BR", date(2026, 3, 5), "Mar\u00e7o 2026"),
        ("es_ES", date(2026, 3, 5), "Marzo 2026"),
        ("en_US", date(2026, 12, 31), "December 2026"),
        ("pt_BR", date(2027, 1, 1), "Janeiro 2027"),
        ("es_ES", date(2027, 1, 1), "Enero 2027"),
    ],
)
def test_format_month(lang: str, value: date, expected: str) -> None:
    """The month name of Qt with the first letter raised, and the four-digit year."""
    assert fmt.format_month(value, lang) == expected


def test_format_month_ignores_the_day_and_accepts_bcp47() -> None:
    first = fmt.format_month(date(2026, 3, 1), "en_US")
    assert first == fmt.format_month(date(2026, 3, 31), "en-US") == "March 2026"


@pytest.mark.parametrize("iso", ["", "2026-3-5", "2026-02-30", "05/03/2026", "20260305", "x" * 10])
def test_format_iso_date_text_rejects_garbage(iso: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.format_iso_date_text(iso, "pt_BR")
    assert info.value.code == "INVALID_DATE"


@pytest.mark.parametrize(
    ("lang", "text"),
    [("pt_BR", "05/03/2026"), ("es_ES", "05/03/2026"), ("en_US", "03/05/2026")],
)
def test_parse_date(lang: str, text: str) -> None:
    assert fmt.parse_date(text, lang) == FIXED_DATE
    assert fmt.parse_date(f"  {text}\xa0", lang) == FIXED_DATE


@pytest.mark.parametrize("lang", LANGUAGES)
def test_date_round_trip(lang: str) -> None:
    for value in (date(2026, 1, 1), date(2024, 2, 29), date(1999, 12, 31), date(2030, 11, 9)):
        assert fmt.parse_date(fmt.format_date(value, lang), lang) == value


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("pt_BR", "5/3/2026"),
        ("pt_BR", "05/03/26"),
        ("pt_BR", "05-03-2026"),
        ("pt_BR", "31/02/2026"),
        ("pt_BR", "00/03/2026"),
        ("pt_BR", "05/13/2026"),
        ("pt_BR", "29/02/2026"),
        ("pt_BR", "2026-03-05"),
        ("pt_BR", ""),
        ("pt_BR", "05/03/2026 x"),
        ("pt_BR", "05/03/0000"),
        ("es_ES", "03/05"),
        ("en_US", "13/05/2026"),
        ("en_US", "05/32/2026"),
        ("pt_BR", "\u0660\u0665/\u0660\u0663/\u0662\u0660\u0662\u0666"),
    ],
)
def test_parse_date_rejects(lang: str, text: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_date(text, lang)
    assert info.value.code == "INVALID_DATE"


def test_qdate_conversion_round_trip() -> None:
    qdate = fmt.to_qdate(FIXED_DATE)
    assert (qdate.year(), qdate.month(), qdate.day()) == (2026, 3, 5)
    assert fmt.from_qdate(qdate) == FIXED_DATE
    with pytest.raises(FormatError):
        fmt.from_qdate(type(qdate)())


# ---------------------------------------------------------------------------- numbers


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("pt_BR", "1.234,5"), ("en_US", "1,234.5"), ("es_ES", "1234,5")],
)
def test_format_number_1234_5(lang: str, expected: str) -> None:
    assert fmt.format_number(1234.5, lang) == expected
    assert fmt.format_number(Decimal("1234.5"), lang) == expected
    assert fmt.format_number(1234.5, lang, decimals=1) == expected


@pytest.mark.parametrize(
    ("lang", "big", "integer", "five_digits", "four_digits"),
    [
        ("pt_BR", "1.234.567,89", "1.234", "12.345", "1.234"),
        ("en_US", "1,234,567.89", "1,234", "12,345", "1,234"),
        ("es_ES", "1.234.567,89", "1234", "12.345", "1234"),
    ],
)
def test_format_number_grouping(
    lang: str, big: str, integer: str, five_digits: str, four_digits: str
) -> None:
    assert fmt.format_number(1234567.89, lang, decimals=2) == big
    assert fmt.format_number(1234, lang) == integer
    assert fmt.format_number(12345, lang) == five_digits
    assert fmt.format_number(1234.0, lang, decimals=0) == four_digits


def test_format_number_decimals_and_rounding() -> None:
    assert fmt.format_number(2.5, "pt_BR", decimals=3) == "2,500"
    assert fmt.format_number(2.675, "en_US", decimals=2) == "2.68"
    assert fmt.format_number(-1234.5, "pt_BR") == "-1.234,5"
    assert fmt.format_number(-0.001, "pt_BR", decimals=2) == "0,00"
    assert fmt.format_number(0, "en_US") == "0"
    assert fmt.format_number(Decimal("1E+3"), "en_US") == "1,000"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), Decimal("NaN")])
def test_format_number_rejects_non_finite(value: float | Decimal) -> None:
    with pytest.raises(FormatError) as info:
        fmt.format_number(value, "pt_BR")
    assert info.value.code == "INVALID_NUMBER"


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("pt_BR", "45,7%"), ("en_US", "45.7%"), ("es_ES", "45,7\xa0%")],
)
def test_format_percent(lang: str, expected: str) -> None:
    assert fmt.format_percent(0.4567, lang) == expected


@pytest.mark.parametrize(
    ("ratio", "decimals", "pt", "en", "es"),
    [
        (1.0, 0, "100%", "100%", "100\xa0%"),
        (0.0, 1, "0,0%", "0.0%", "0,0\xa0%"),
        (0.4567, 0, "46%", "46%", "46\xa0%"),
        (12.345, 2, "1.234,50%", "1,234.50%", "1234,50\xa0%"),
        (0.5, 1, "50,0%", "50.0%", "50,0\xa0%"),
    ],
)
def test_format_percent_variants(ratio: float, decimals: int, pt: str, en: str, es: str) -> None:
    assert fmt.format_percent(ratio, "pt_BR", decimals=decimals) == pt
    assert fmt.format_percent(ratio, "en_US", decimals=decimals) == en
    assert fmt.format_percent(ratio, "es_ES", decimals=decimals) == es


# ---------------------------------------------------------------------------- money


@pytest.mark.parametrize(
    ("minor", "currency", "pt", "en", "es"),
    [
        (123456, "BRL", "R$\xa01.234,56", "R$1,234.56", "1234,56\xa0R$"),
        (123456, "EUR", "€\xa01.234,56", "€1,234.56", "1234,56\xa0€"),
        (123456, "USD", "US$\xa01.234,56", "US$1,234.56", "1234,56\xa0US$"),
        (123456789, "BRL", "R$\xa01.234.567,89", "R$1,234,567.89", "1.234.567,89\xa0R$"),
        (5, "BRL", "R$\xa00,05", "R$0.05", "0,05\xa0R$"),
        (0, "EUR", "€\xa00,00", "€0.00", "0,00\xa0€"),
        (100, "BRL", "R$\xa01,00", "R$1.00", "1,00\xa0R$"),
        (99999, "BRL", "R$\xa0999,99", "R$999.99", "999,99\xa0R$"),
        (-100, "BRL", "-R$\xa01,00", "-R$1.00", "-1,00\xa0R$"),
        (-123456, "EUR", "-€\xa01.234,56", "-€1,234.56", "-1234,56\xa0€"),
    ],
)
def test_format_money(minor: int, currency: str, pt: str, en: str, es: str) -> None:
    assert fmt.format_money(minor, currency, "pt_BR") == pt
    assert fmt.format_money(minor, currency, "en_US") == en
    assert fmt.format_money(minor, currency, "es_ES") == es


@pytest.mark.parametrize(
    ("minor", "pt", "en", "es"),
    [
        (123456, "1.234,56", "1,234.56", "1234,56"),
        (123456789, "1.234.567,89", "1,234,567.89", "1.234.567,89"),
        (5, "0,05", "0.05", "0,05"),
        (-250, "-2,50", "-2.50", "-2,50"),
    ],
)
def test_format_amount(minor: int, pt: str, en: str, es: str) -> None:
    assert fmt.format_amount(minor, "BRL", "pt_BR") == pt
    assert fmt.format_amount(minor, "BRL", "en_US") == en
    assert fmt.format_amount(minor, "BRL", "es_ES") == es


def test_format_money_is_exact_for_huge_values() -> None:
    # No float is involved: 2**53 + 1 minor units would be lost by a float.
    minor = 2**53 + 1
    assert fmt.format_amount(minor, "BRL", "en_US") == "90,071,992,547,409.93"


@pytest.mark.parametrize(
    "currency", ["", "br", "BRLX", "R$", "123", "CHF", "JPY", "KWD", "GBP", "brl"]
)
def test_invalid_currency_code(currency: str) -> None:
    # Outside the allow-list of domain/budget.py: no silent 2-decimal fallback (P1B-30).
    with pytest.raises(FormatError) as info:
        fmt.format_money(100, currency, "pt_BR")
    assert info.value.code == "INVALID_CURRENCY"
    with pytest.raises(FormatError) as info:
        fmt.format_amount(100, currency, "pt_BR")
    assert info.value.code == "INVALID_CURRENCY"
    with pytest.raises(FormatError) as info:
        fmt.currency_symbol(currency)
    assert info.value.code == "INVALID_CURRENCY"
    with pytest.raises(FormatError) as info:
        fmt.parse_amount("1", currency, "pt_BR")
    assert info.value.code == "INVALID_CURRENCY"


def test_every_allow_listed_currency_is_formattable() -> None:
    # The allow-list and decimals come from domain/budget.py; the symbol map must cover it.
    for currency, decimals in CURRENCY_DECIMALS.items():
        assert fmt.currency_symbol(currency)
        text = fmt.format_amount(1, currency, "en_US")
        assert text == "0." + "0" * (decimals - 1) + "1"
        assert fmt.parse_amount(text, currency, "en_US") == 1
    assert not hasattr(fmt, "CURRENCY_DECIMALS")


# ------------------------------------------------------- currencies with 0 and 3 decimals


@pytest.fixture
def widened_allow_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """JPY (0 decimals) and KWD (3 decimals) join the allow-list, with test symbols.

    The real allow-list has only 2-decimal currencies, so the other paths of the formatting code
    are reachable only through this patch. The symbols are plain ASCII stand-ins.
    """
    widened = MappingProxyType({**CURRENCY_DECIMALS, "JPY": 0, "KWD": 3})
    monkeypatch.setattr(budget_domain, "CURRENCY_DECIMALS", widened)
    monkeypatch.setitem(fmt._CURRENCY_SYMBOLS, "JPY", "YEN")
    monkeypatch.setitem(fmt._CURRENCY_SYMBOLS, "KWD", "KD")


@pytest.mark.usefixtures("widened_allow_list")
@pytest.mark.parametrize(
    ("minor", "currency", "pt", "en", "es"),
    [
        (0, "JPY", "0", "0", "0"),
        (1234, "JPY", "1.234", "1,234", "1234"),
        (1234567, "JPY", "1.234.567", "1,234,567", "1.234.567"),
        (5, "KWD", "0,005", "0.005", "0,005"),
        (1234567, "KWD", "1.234,567", "1,234.567", "1234,567"),
        (12345678, "KWD", "12.345,678", "12,345.678", "12.345,678"),
    ],
)
def test_format_amount_with_zero_and_three_decimals(
    minor: int, currency: str, pt: str, en: str, es: str
) -> None:
    assert fmt.format_amount(minor, currency, "pt_BR") == pt
    assert fmt.format_amount(minor, currency, "en_US") == en
    assert fmt.format_amount(minor, currency, "es_ES") == es
    # what is shown can be typed back
    assert fmt.parse_amount(pt, currency, "pt_BR") == minor
    assert fmt.parse_amount(en, currency, "en_US") == minor
    assert fmt.parse_amount(es, currency, "es_ES") == minor


@pytest.mark.usefixtures("widened_allow_list")
def test_format_amount_of_a_negative_amount_with_zero_and_three_decimals() -> None:
    assert fmt.format_amount(-5, "JPY", "en_US") == "-5"
    assert fmt.format_amount(-1500, "KWD", "en_US") == "-1.500"
    assert fmt.format_amount(-1500, "KWD", "pt_BR") == "-1,500"


@pytest.mark.usefixtures("widened_allow_list")
@pytest.mark.parametrize(
    ("minor", "currency", "pt", "en", "es"),
    [
        (1234567, "JPY", "YEN\xa01.234.567", "YEN1,234,567", "1.234.567\xa0YEN"),
        (12345678, "KWD", "KD\xa012.345,678", "KD12,345.678", "12.345,678\xa0KD"),
        (-5, "KWD", "-KD\xa00,005", "-KD0.005", "-0,005\xa0KD"),
    ],
)
def test_format_money_with_zero_and_three_decimals(
    minor: int, currency: str, pt: str, en: str, es: str
) -> None:
    assert fmt.format_money(minor, currency, "pt_BR") == pt
    assert fmt.format_money(minor, currency, "en_US") == en
    assert fmt.format_money(minor, currency, "es_ES") == es


@pytest.mark.usefixtures("widened_allow_list")
@pytest.mark.parametrize(
    ("text", "currency", "lang", "minor"),
    [
        ("1,234,567", "JPY", "en_US", 1234567),
        ("1.234.567", "JPY", "pt_BR", 1234567),
        ("1.234", "JPY", "pt_BR", 1234),
        ("YEN 1,234", "JPY", "en_US", 1234),
        ("1234", "JPY", "es_ES", 1234),
        ("12,345.678", "KWD", "en_US", 12345678),
        ("12,345.6", "KWD", "en_US", 12345600),
        ("5", "KWD", "en_US", 5000),
        ("12.345,678", "KWD", "pt_BR", 12345678),
        ("0,005", "KWD", "pt_BR", 5),
        ("12.345,678", "KWD", "es_ES", 12345678),
        ("KD 0,5", "KWD", "es_ES", 500),
    ],
)
def test_parse_amount_with_zero_and_three_decimals(
    text: str, currency: str, lang: str, minor: int
) -> None:
    assert fmt.parse_amount(text, currency, lang) == minor


@pytest.mark.usefixtures("widened_allow_list")
@pytest.mark.parametrize(
    ("text", "currency", "lang"),
    [
        ("1,234.5", "JPY", "en_US"),
        ("0.5", "JPY", "en_US"),
        ("1.234,5", "JPY", "pt_BR"),
        ("1,234", "JPY", "pt_BR"),
        ("1.2345", "KWD", "en_US"),
        ("1,2345", "KWD", "pt_BR"),
    ],
)
def test_parse_amount_refuses_more_decimals_than_the_currency_has(
    text: str, currency: str, lang: str
) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_amount(text, currency, lang)
    assert info.value.code == "TOO_MANY_DECIMALS"


def test_the_patch_of_the_allow_list_is_undone_after_the_tests() -> None:
    with pytest.raises(FormatError) as info:
        fmt.format_amount(1, "KWD", "en_US")
    assert info.value.code == "INVALID_CURRENCY"


# ---------------------------------------------------------------------------- 64-bit limits

INT64_MAX = 2**63 - 1


def test_format_amount_boundary_in_each_locale() -> None:
    assert fmt.format_amount(INT64_MAX, "BRL", "en_US") == "92,233,720,368,547,758.07"
    assert fmt.format_amount(INT64_MAX, "BRL", "pt_BR") == "92.233.720.368.547.758,07"
    assert fmt.format_amount(INT64_MAX, "BRL", "es_ES") == "92.233.720.368.547.758,07"
    assert fmt.format_money(INT64_MAX, "BRL", "en_US") == "R$92,233,720,368,547,758.07"
    assert fmt.format_money(-(2**63), "BRL", "en_US") == "-R$92,233,720,368,547,758.08"


@pytest.mark.parametrize("minor", [2**63, -(2**63) - 1, 10**30])
def test_format_money_and_amount_reject_out_of_range_ints(minor: int) -> None:
    for lang in LANGUAGES:
        with pytest.raises(FormatError) as info:
            fmt.format_amount(minor, "BRL", lang)
        assert info.value.code == "TOO_LARGE"
        with pytest.raises(FormatError) as info:
            fmt.format_money(minor, "BRL", lang)
        assert info.value.code == "TOO_LARGE"


def test_format_number_rejects_a_value_that_rounds_out_of_range() -> None:
    with pytest.raises(FormatError) as info:
        fmt.format_number(Decimal("9223372036854775807.6"), "en_US", decimals=0)
    assert info.value.code == "TOO_LARGE"
    assert fmt.format_number(Decimal("9223372036854775807.6"), "en_US") == (
        "9,223,372,036,854,775,807.6"
    )


@pytest.mark.parametrize("value", [2**63, -(2**63), 10**30, Decimal("1E+30"), 1e30])
def test_format_number_rejects_out_of_range(value: float | Decimal) -> None:
    for lang in LANGUAGES:
        with pytest.raises(FormatError) as info:
            fmt.format_number(value, lang, decimals=0)
        assert info.value.code == "TOO_LARGE"
    with pytest.raises(FormatError) as info:
        fmt.format_number(value, "en_US")
    assert info.value.code == "TOO_LARGE"


def test_format_number_and_percent_accept_the_largest_magnitude() -> None:
    assert fmt.format_number(INT64_MAX, "en_US") == "9,223,372,036,854,775,807"
    assert fmt.format_number(-INT64_MAX, "pt_BR") == "-9.223.372.036.854.775.807"
    assert fmt.format_number(Decimal("0E+100"), "en_US", decimals=0) == "0"
    with pytest.raises(FormatError) as info:
        fmt.format_percent(10**30, "en_US")
    assert info.value.code == "TOO_LARGE"


# ---------------------------------------------------------------------------- parsing numbers


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("pt_BR", "1.234,56", "1234.56"),
        ("pt_BR", "1234,56", "1234.56"),
        ("pt_BR", "1.234", "1234"),
        ("pt_BR", "12.345.678", "12345678"),
        ("pt_BR", "0,5", "0.5"),
        ("pt_BR", "  1.234,5\xa0", "1234.5"),
        ("pt_BR", "-1.234,5", "-1234.5"),
        ("pt_BR", "- 3", "-3"),
        ("pt_BR", "\u22123,25", "-3.25"),
        ("pt_BR", "007", "7"),
        ("en_US", "1,234.56", "1234.56"),
        ("en_US", "1234.56", "1234.56"),
        ("en_US", "1,234", "1234"),
        ("en_US", "12,345,678.9", "12345678.9"),
        ("en_US", "-0.5", "-0.5"),
        ("es_ES", "1234,56", "1234.56"),
        ("es_ES", "1.234,56", "1234.56"),
        ("es_ES", "1.234", "1234"),
        ("es_ES", "12.345,6", "12345.6"),
        ("es_ES", "12345", "12345"),
    ],
)
def test_parse_number(lang: str, text: str, expected: str) -> None:
    result = fmt.parse_number(text, lang)
    assert isinstance(result, Decimal)
    assert result == Decimal(expected)
    assert str(result) == str(Decimal(expected))


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("pt_BR", "1,234.56"),
        ("pt_BR", "1.5"),
        ("pt_BR", "1.23"),
        ("pt_BR", "1234.567"),
        ("pt_BR", "0.123"),
        ("es_ES", "1,234.56"),
        ("es_ES", "1.5"),
        ("es_ES", "1234.567"),
        ("en_US", "1.234,56"),
        ("en_US", "1,5"),
        ("en_US", "1,23"),
        ("en_US", "1.234.567"),
    ],
)
def test_parse_number_ambiguous(lang: str, text: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_number(text, lang)
    assert info.value.code == "AMBIGUOUS_NUMBER"


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("pt_BR", "abc"),
        ("pt_BR", "1..234"),
        ("pt_BR", ".123"),
        ("pt_BR", ",5"),
        ("pt_BR", "5,"),
        ("pt_BR", "1,2,3"),
        ("pt_BR", "1.23.4"),
        ("pt_BR", "1 234,56"),
        ("pt_BR", "1\xa0234,56"),
        ("pt_BR", "1'234,56"),
        ("pt_BR", "1e5"),
        ("pt_BR", "--1"),
        ("pt_BR", "+1"),
        ("pt_BR", "1-"),
        ("pt_BR", "\u0661\u0662"),
        ("pt_BR", "12.34a"),
        ("en_US", "1 234.56"),
        ("en_US", ".5"),
        ("en_US", "1..2"),
        ("es_ES", "1 234,56"),
    ],
)
def test_parse_number_invalid(lang: str, text: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_number(text, lang)
    assert info.value.code == "INVALID_NUMBER"


@pytest.mark.parametrize("text", ["", "   ", "\xa0", "\t\n"])
def test_parse_number_empty(text: str) -> None:
    for lang in LANGUAGES:
        with pytest.raises(FormatError) as info:
            fmt.parse_number(text, lang)
        assert info.value.code == "EMPTY"


def test_format_error_is_a_value_error_with_code() -> None:
    error = FormatError("EMPTY", "no input")
    assert isinstance(error, ValueError)
    assert error.code == "EMPTY"
    assert str(error) == "EMPTY: no input"
    assert str(FormatError("EMPTY")) == "EMPTY"


# ---------------------------------------------------------------------------- parsing amounts


@pytest.mark.parametrize(
    ("lang", "currency", "text", "expected"),
    [
        ("pt_BR", "BRL", "1.234,56", 123456),
        ("pt_BR", "BRL", "1234,56", 123456),
        ("pt_BR", "BRL", "1.234,5", 123450),
        ("pt_BR", "BRL", "1.234", 123400),
        ("pt_BR", "BRL", "0,05", 5),
        ("pt_BR", "BRL", "0", 0),
        ("pt_BR", "BRL", "R$ 1.234,56", 123456),
        ("pt_BR", "BRL", "R$\xa01.234,56", 123456),
        ("pt_BR", "BRL", "R$1.234,56", 123456),
        ("pt_BR", "BRL", "BRL 1.234,56", 123456),
        ("pt_BR", "BRL", "brl 1.234,56", 123456),
        ("pt_BR", "BRL", "1.234,56 R$", 123456),
        ("pt_BR", "EUR", "€\xa012,3", 1230),
        ("en_US", "BRL", "1,234.56", 123456),
        ("en_US", "BRL", "1234.56", 123456),
        ("en_US", "BRL", "R$1,234.56", 123456),
        ("en_US", "USD", "US$1,234.56", 123456),
        ("en_US", "USD", "USD 1,234.56", 123456),
        ("en_US", "EUR", "1,234", 123400),
        ("en_US", "EUR", "  1,234.5  ", 123450),
        ("es_ES", "BRL", "1234,56", 123456),
        ("es_ES", "BRL", "1.234,56", 123456),
        ("es_ES", "BRL", "1.234.567,89\xa0R$", 123456789),
        ("es_ES", "EUR", "1234,56\xa0€", 123456),
        ("es_ES", "EUR", "1.234,56 EUR", 123456),
        ("es_ES", "EUR", "1.234", 123400),
    ],
)
def test_parse_amount(lang: str, currency: str, text: str, expected: int) -> None:
    result = fmt.parse_amount(text, currency, lang)
    assert result == expected
    assert type(result) is int


@pytest.mark.parametrize("lang", LANGUAGES)
@pytest.mark.parametrize("currency", ["BRL", "EUR", "USD"])
@pytest.mark.parametrize(
    "minor",
    [
        0,
        1,
        5,
        99,
        100,
        999,
        1000,
        123456,
        99999,
        100000,
        123450,
        1234567,
        123456789,
        2**53 + 1,
        2**63 - 1,
    ],
)
def test_amount_round_trips(lang: str, currency: str, minor: int) -> None:
    assert fmt.parse_amount(fmt.format_amount(minor, currency, lang), currency, lang) == minor
    assert fmt.parse_amount(fmt.format_money(minor, currency, lang), currency, lang) == minor


@pytest.mark.parametrize("lang", LANGUAGES)
def test_number_round_trip(lang: str) -> None:
    for value in (Decimal("1234.5"), Decimal("0.25"), Decimal("12345678.125"), Decimal(7)):
        text = fmt.format_number(value, lang)
        assert fmt.parse_number(text, lang) == value


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("pt_BR", "1,234.56"),
        ("pt_BR", "1.5"),
        ("es_ES", "1,234.56"),
        ("es_ES", "1.5"),
        ("en_US", "1.234,56"),
        ("en_US", "1,5"),
    ],
)
def test_parse_amount_ambiguous(lang: str, text: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_amount(text, "BRL", lang)
    assert info.value.code == "AMBIGUOUS_NUMBER"


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("pt_BR", "abc"),
        ("pt_BR", "1 234,56"),
        ("pt_BR", "R$ R$ 1,00"),
        ("pt_BR", "EUR 1,00"),
        ("pt_BR", "+1,00"),
        ("pt_BR", "-abc"),
        ("en_US", "1,00 BRL BRL"),
    ],
)
def test_parse_amount_invalid(lang: str, text: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_amount(text, "BRL", lang)
    assert info.value.code == "INVALID_NUMBER"


@pytest.mark.parametrize("text", ["", "  ", "\xa0", "R$", "R$ ", "BRL"])
def test_parse_amount_empty(text: str) -> None:
    for lang in LANGUAGES:
        with pytest.raises(FormatError) as info:
            fmt.parse_amount(text, "BRL", lang)
        assert info.value.code == "EMPTY"


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("pt_BR", "-1,00"),
        ("pt_BR", "-1.234,56"),
        ("pt_BR", "-R$ 1,00"),
        ("pt_BR", "R$ -1,00"),
        ("pt_BR", "\u22121,00"),
        ("en_US", "-1.00"),
        ("en_US", "-R$1.00"),
        ("es_ES", "-1,00\xa0R$"),
        ("pt_BR", "-0"),
    ],
)
def test_parse_amount_negative(lang: str, text: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_amount(text, "BRL", lang)
    assert info.value.code == "NEGATIVE_AMOUNT"


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("pt_BR", "1,234"),
        ("pt_BR", "1.234,567"),
        ("pt_BR", "R$ 0,001"),
        ("en_US", "1.234"),
        ("en_US", "1,234.567"),
        ("es_ES", "1234,567"),
    ],
)
def test_parse_amount_too_many_decimals(lang: str, text: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_amount(text, "BRL", lang)
    assert info.value.code == "TOO_MANY_DECIMALS"


# ---------------------------------------------------------------------------- upper bounds

_AT_LIMIT = {
    "en_US": "92,233,720,368,547,758.07",
    "pt_BR": "92.233.720.368.547.758,07",
    "es_ES": "92.233.720.368.547.758,07",
}
_OVER_LIMIT = {
    "en_US": "92,233,720,368,547,758.08",
    "pt_BR": "92.233.720.368.547.758,08",
    "es_ES": "92.233.720.368.547.758,08",
}


@pytest.mark.parametrize("lang", LANGUAGES)
def test_parse_amount_boundary(lang: str) -> None:
    assert fmt.parse_amount(_AT_LIMIT[lang], "BRL", lang) == 2**63 - 1
    assert fmt.parse_amount(f"R$ {_AT_LIMIT[lang]}", "BRL", lang) == 2**63 - 1
    with pytest.raises(FormatError) as info:
        fmt.parse_amount(_OVER_LIMIT[lang], "BRL", lang)
    assert info.value.code == "TOO_LARGE"


@pytest.mark.parametrize("lang", LANGUAGES)
@pytest.mark.parametrize("text", ["99999999999999999999", "9" * 5000, "1" + "0" * 30 + "00"])
def test_parse_amount_too_large(lang: str, text: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_amount(text, "BRL", lang)
    assert info.value.code == "TOO_LARGE"


def test_parse_amount_leading_zeros_do_not_count() -> None:
    assert fmt.parse_amount("0" * 40 + "1,00", "BRL", "pt_BR") == 100
    assert fmt.parse_amount("0" * 40, "BRL", "pt_BR") == 0


def test_parse_amount_negative_wins_over_too_large() -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_amount("-99999999999999999999", "BRL", "pt_BR")
    assert info.value.code == "NEGATIVE_AMOUNT"


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("en_US", "999999999999999999", 10**18 - 1),
        ("en_US", "999,999,999,999,999,999.5", Decimal("999999999999999999.5")),
        ("pt_BR", "999.999.999.999.999.999,25", Decimal("999999999999999999.25")),
        ("es_ES", "-999999999999999999", -(10**18 - 1)),
        ("pt_BR", "0" * 30 + "7", 7),
    ],
)
def test_parse_number_below_the_bound(lang: str, text: str, expected: int | Decimal) -> None:
    assert fmt.parse_number(text, lang) == expected


@pytest.mark.parametrize("lang", LANGUAGES)
@pytest.mark.parametrize("text", ["1" + "0" * 18, "-" + "1" + "0" * 18, "9" * 5000])
def test_parse_number_too_large(lang: str, text: str) -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_number(text, lang)
    assert info.value.code == "TOO_LARGE"


def test_parse_number_too_large_with_grouping() -> None:
    with pytest.raises(FormatError) as info:
        fmt.parse_number("1,000,000,000,000,000,000", "en_US")
    assert info.value.code == "TOO_LARGE"
    with pytest.raises(FormatError) as info:
        fmt.parse_number("1.000.000.000.000.000.000,5", "pt_BR")
    assert info.value.code == "TOO_LARGE"


# ---------------------------------------------------------------------------- separator rule


@pytest.mark.parametrize(
    ("lang", "text", "value"),
    [("pt_BR", "1.234", 1234), ("en_US", "1,234", 1234), ("es_ES", "1.234", 1234)],
)
def test_locale_group_separator_without_decimals_is_an_integer(
    lang: str, text: str, value: int
) -> None:
    # By design (P1B-19): the locale's own separators are authoritative.
    assert fmt.parse_number(text, lang) == value
    assert fmt.parse_amount(text, "BRL", lang) == value * 100


@pytest.mark.parametrize(
    ("lang", "text"), [("pt_BR", "1.23"), ("es_ES", "1.23"), ("en_US", "1,23"), ("en_US", "1,5")]
)
def test_text_valid_only_in_the_other_convention_is_rejected(lang: str, text: str) -> None:
    for call in (
        lambda: fmt.parse_number(text, lang),
        lambda: fmt.parse_amount(text, "BRL", lang),
    ):
        with pytest.raises(FormatError) as info:
            call()
        assert info.value.code == "AMBIGUOUS_NUMBER"


@pytest.mark.parametrize(
    ("lang", "text", "expected"),
    [
        ("pt_BR", "1.234", "1.234"),
        ("pt_BR", "1,234", "1234"),
        ("pt_BR", "-1.234", "-1.234"),
        ("pt_BR", "  1.000  ", "1.000"),
        ("pt_BR", "12.345", "12.345"),
        ("pt_BR", "1.234,56", None),
        ("pt_BR", "1234", None),
        ("pt_BR", "1234,56", None),
        ("pt_BR", "12.345.678", None),
        ("pt_BR", "1.23", None),
        ("pt_BR", "0,5", None),
        ("pt_BR", "abc", None),
        ("pt_BR", "", None),
        ("pt_BR", "-", None),
        ("en_US", "1,234", "1.234"),
        ("en_US", "1.234", "1234"),
        ("en_US", "-1,234", "-1.234"),
        ("en_US", "1,234.56", None),
        ("en_US", "1234.56", None),
        ("en_US", "1,234,567", None),
        ("en_US", "1,23", None),
        ("en_US", "7", None),
        ("es_ES", "1.234", "1.234"),
        ("es_ES", "1,234", "1234"),
        ("es_ES", "1.234,56", None),
        ("es_ES", "1234,56", None),
        ("es_ES", "1234", None),
        ("es_ES", "", None),
    ],
)
def test_other_convention_value(lang: str, text: str, expected: str | None) -> None:
    result = fmt.other_convention_value(text, lang)
    if expected is None:
        assert result is None
    else:
        assert isinstance(result, Decimal)
        assert str(result) == str(Decimal(expected))


def test_other_convention_value_does_not_change_parsing() -> None:
    assert fmt.parse_number("1.234", "pt_BR") == 1234
    assert fmt.other_convention_value("1.234", "pt_BR") == Decimal("1.234")
    with pytest.raises(UnknownLanguageError):
        fmt.other_convention_value("1.234", "fr_FR")


# ---------------------------------------------------------------------------- widgets


@pytest.mark.ui
@pytest.mark.parametrize(
    ("lang", "pattern", "decimal_point"),
    [("pt_BR", "dd/MM/yyyy", ","), ("en_US", "MM/dd/yyyy", "."), ("es_ES", "dd/MM/yyyy", ",")],
)
def test_apply_locale_to_date_edit(
    qtbot: QtBot, lang: str, pattern: str, decimal_point: str
) -> None:
    widget = QDateEdit()
    qtbot.addWidget(widget)
    widget.setDate(fmt.to_qdate(FIXED_DATE))
    fmt.apply_locale(widget, lang)
    assert widget.locale().name() == lang
    assert widget.locale().decimalPoint() == decimal_point
    assert widget.displayFormat() == pattern
    assert widget.text() == fmt.format_date(FIXED_DATE, lang)


@pytest.mark.ui
def test_apply_locale_switches_language_live(qtbot: QtBot) -> None:
    widget = QDateEdit()
    qtbot.addWidget(widget)
    widget.setDate(fmt.to_qdate(FIXED_DATE))
    fmt.apply_locale(widget, "pt_BR")
    assert widget.text() == "05/03/2026"
    fmt.apply_locale(widget, "en_US")
    assert widget.text() == "03/05/2026"


@pytest.mark.ui
@pytest.mark.parametrize(
    ("lang", "expected"), [("pt_BR", "1,50"), ("en_US", "1.50"), ("es_ES", "1,50")]
)
def test_apply_locale_to_double_spin_box(qtbot: QtBot, lang: str, expected: str) -> None:
    widget = QDoubleSpinBox()
    qtbot.addWidget(widget)
    widget.setDecimals(2)
    fmt.apply_locale(widget, lang)
    assert widget.locale().name() == lang
    assert widget.textFromValue(1.5) == expected


@pytest.mark.ui
def test_apply_locale_rejects_unknown_language(qtbot: QtBot) -> None:
    widget = QDoubleSpinBox()
    qtbot.addWidget(widget)
    with pytest.raises(UnknownLanguageError):
        fmt.apply_locale(widget, "xx_XX")
