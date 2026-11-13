# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure date and timestamp arithmetic (PLAN T1.1).

No I/O, no clock, no Qt. Every function takes its dates and instants as parameters. Errors carry
stable codes (``INVALID_DATE``, ``INVALID_TIMESTAMP``); the domain never produces translated text.
"""

from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime

_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_UTC_TIMESTAMP = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?Z"
)
#: The ``timespec`` values of :func:`format_utc_timestamp` that can be parsed back.
_TIMESPECS = ("seconds", "milliseconds", "microseconds")


class InvalidDateError(ValueError):
    """Text is not a strict, real-calendar ``YYYY-MM-DD`` date, or a date is out of range."""

    code = "INVALID_DATE"


class InvalidTimestampError(ValueError):
    """Text is not a strict ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z`` UTC timestamp."""

    code = "INVALID_TIMESTAMP"


def parse_iso_date(text: str) -> date:
    """Parse strict ``YYYY-MM-DD`` (ASCII digits, real calendar date); no whitespace, no time."""
    match = _ISO_DATE.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        msg = f"not a YYYY-MM-DD date: {text!r}"
        raise InvalidDateError(msg)
    year, month, day = (int(group) for group in match.groups())
    try:
        return date(year, month, day)
    except ValueError as exc:
        msg = f"not a real calendar date: {text!r}"
        raise InvalidDateError(msg) from exc


def format_iso_date(value: date) -> str:
    """Format as ``YYYY-MM-DD`` with a zero-padded 4-digit year."""
    return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"


def add_months(value: date, months: int) -> date:
    """Add (or, if negative, subtract) calendar months, clamping the day to the month's end.

    The result is always computed from the original day, so repeated calls do not drift:
    ``add_months(date(2025, 1, 31), 1)`` is 28 February, and ``add_months(date(2025, 1, 31), 2)``
    is 31 March (not 28 March). A result outside years 1 to 9999 raises :class:`InvalidDateError`.
    """
    year, month_index = divmod(value.year * 12 + (value.month - 1) + months, 12)
    if not date.min.year <= year <= date.max.year:
        msg = f"adding {months} months to {format_iso_date(value)} leaves the supported years"
        raise InvalidDateError(msg)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def days_between(start: date, end: date) -> int:
    """Signed number of days from ``start`` to ``end`` (negative if ``end`` is earlier)."""
    return (end - start).days


def month_start(value: date) -> date:
    """The first day of the month containing ``value``."""
    return value.replace(day=1)


def is_same_month(a: date, b: date) -> bool:
    """Whether both dates fall in the same calendar month of the same year."""
    return (a.year, a.month) == (b.year, b.month)


def days_in_year(year: int) -> int:
    """365, or 366 in a leap year (Gregorian rules: 1900 is not a leap year, 2000 is)."""
    return 366 if calendar.isleap(year) else 365


def day_of_year(value: date) -> int:
    """Ordinal day within the year, 1 for 1 January."""
    return value.timetuple().tm_yday


def format_utc_timestamp(instant: datetime, timespec: str = "seconds") -> str:
    """Format an aware ``instant`` as UTC ISO 8601 with a trailing ``Z``.

    ``timespec`` is passed to :meth:`datetime.isoformat` (default: second precision, giving
    ``2026-03-05T02:30:00Z``). Only the values that :func:`parse_utc_timestamp` reads back are
    accepted (``"seconds"``, ``"milliseconds"``, ``"microseconds"``); any other ``timespec`` and
    a naive ``instant`` raise ``ValueError``.
    """
    if timespec not in _TIMESPECS:
        msg = f"timespec must be one of {', '.join(_TIMESPECS)}"
        raise ValueError(msg)
    if instant.tzinfo is None or instant.utcoffset() is None:
        msg = "a timezone-aware datetime is required"
        raise ValueError(msg)
    text = instant.astimezone(UTC).replace(tzinfo=None).isoformat(timespec=timespec)
    return f"{text}Z"


def parse_utc_timestamp(text: str) -> datetime:
    """Strict inverse of :func:`format_utc_timestamp`: only the ``...Z`` form is accepted.

    Optional fractional seconds (1 to 6 digits) are allowed. Returns an aware UTC datetime.
    """
    match = _UTC_TIMESTAMP.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        msg = f"not a UTC timestamp ending in Z: {text!r}"
        raise InvalidTimestampError(msg)
    year, month, day, hour, minute, second = (int(group) for group in match.groups()[:6])
    fraction = match.group(7)
    microsecond = int(fraction.ljust(6, "0")) if fraction else 0
    try:
        return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC)
    except ValueError as exc:
        msg = f"not a real UTC timestamp: {text!r}"
        raise InvalidTimestampError(msg) from exc
