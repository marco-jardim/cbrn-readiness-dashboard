# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the clock and the pure date arithmetic (PLAN T1.1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from cbrn_dashboard.clock import Clock, FixedClock, SystemClock
from cbrn_dashboard.domain.dates import (
    InvalidDateError,
    InvalidTimestampError,
    add_months,
    day_of_year,
    days_between,
    days_in_year,
    format_iso_date,
    format_utc_timestamp,
    is_same_month,
    month_start,
    parse_iso_date,
    parse_utc_timestamp,
)

NAIVE = datetime.fromisoformat("2026-03-05T02:30:00")


# --- Clock ------------------------------------------------------------------------------------


@pytest.mark.parametrize("clock", [SystemClock(), FixedClock.at("2026-03-05T02:30:00Z")])
def test_both_implementations_satisfy_the_clock_interface(clock: Clock) -> None:
    assert isinstance(clock, Clock)
    now = clock.utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert now.tzinfo is UTC
    local = clock.local_date()
    assert type(local) is date
    assert type(clock.local_date_of(now)) is date


def test_system_clock_local_date_of_agrees_with_local_date() -> None:
    clock = SystemClock()
    before = clock.local_date()
    instant = clock.utc_now()
    after = clock.local_date()
    # The instant lies between the two readings, so its local date is one of them (they differ
    # only when local midnight passes during the test).
    assert before <= clock.local_date_of(instant) <= after
    assert clock.local_date_of(instant) in {before, after}


@pytest.mark.parametrize(
    ("iso_utc", "offset_hours", "expected_local"),
    [
        ("2026-03-05T02:30:00Z", -3, date(2026, 3, 4)),  # after UTC midnight, previous local date
        ("2026-03-04T22:30:00Z", 3, date(2026, 3, 5)),  # before UTC midnight, next local date
        ("2026-03-05T02:30:00Z", 0, date(2026, 3, 5)),
        ("2026-03-05T12:00:00Z", -3, date(2026, 3, 5)),
        ("2026-03-01T00:30:00Z", -1, date(2026, 2, 28)),  # month boundary backwards
        ("2026-01-31T23:30:00Z", 1, date(2026, 2, 1)),  # month boundary forwards
        ("2025-12-31T23:30:00Z", 5.5, date(2026, 1, 1)),  # year boundary, fractional offset
        ("2026-03-05T02:30:00+00:00", -3, date(2026, 3, 4)),
        ("2026-03-04T23:30:00-03:00", 0, date(2026, 3, 5)),  # input in another zone, normalised
    ],
)
def test_fixed_clock_local_date(iso_utc: str, offset_hours: float, expected_local: date) -> None:
    clock = FixedClock.at(iso_utc, offset_hours)
    assert clock.local_date() == expected_local


def test_fixed_clock_utc_now_stays_utc() -> None:
    clock = FixedClock.at("2026-03-05T02:30:00Z", -3)
    assert clock.utc_now() == datetime(2026, 3, 5, 2, 30, tzinfo=UTC)
    assert clock.utc_now().tzinfo is UTC
    assert clock.utc_now().utcoffset() == timedelta(0)


def test_fixed_clock_normalises_instant_to_utc() -> None:
    other_zone = datetime(2026, 3, 4, 23, 30, tzinfo=timezone(timedelta(hours=-3)))
    clock = FixedClock(other_zone)
    assert clock.utc_now() == datetime(2026, 3, 5, 2, 30, tzinfo=UTC)
    assert clock.utc_now().tzinfo is UTC


def test_fixed_clock_rejects_naive_instant() -> None:
    with pytest.raises(ValueError, match="aware"):
        FixedClock(NAIVE)
    with pytest.raises(ValueError):
        FixedClock.at("2026-03-05T02:30:00")


def test_fixed_clock_rejects_out_of_range_offset() -> None:
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 3, 5, tzinfo=UTC), timedelta(hours=24))


@pytest.mark.parametrize(
    ("offset_hours", "instant", "expected"),
    [
        (-3, "2026-03-05T02:30:00Z", date(2026, 3, 4)),
        (-3, "2026-03-05T03:00:00Z", date(2026, 3, 5)),
        (3, "2026-03-04T20:59:59Z", date(2026, 3, 4)),
        (3, "2026-03-04T21:00:00Z", date(2026, 3, 5)),
    ],
)
def test_fixed_clock_local_date_of(offset_hours: float, instant: str, expected: date) -> None:
    clock = FixedClock.at("2000-01-01T00:00:00Z", offset_hours)
    assert clock.local_date_of(datetime.fromisoformat(instant)) == expected


def test_local_date_of_rejects_naive() -> None:
    with pytest.raises(ValueError):
        FixedClock.at("2026-03-05T02:30:00Z").local_date_of(NAIVE)
    with pytest.raises(ValueError):
        SystemClock().local_date_of(NAIVE)


def test_fixed_clock_advanced_returns_new_clock() -> None:
    clock = FixedClock.at("2026-03-05T02:30:00Z", -3)
    later = clock.advanced(timedelta(hours=1))
    assert later is not clock
    assert clock.local_date() == date(2026, 3, 4)  # original unchanged
    assert later.utc_now() == datetime(2026, 3, 5, 3, 30, tzinfo=UTC)
    assert later.local_date() == date(2026, 3, 5)
    assert later.utc_offset == clock.utc_offset
    assert clock.advanced(timedelta(days=-1)).utc_now() == datetime(2026, 3, 4, 2, 30, tzinfo=UTC)


def test_fixed_clock_is_immutable() -> None:
    clock = FixedClock.at("2026-03-05T02:30:00Z")
    with pytest.raises(AttributeError):
        clock.instant = datetime(2027, 1, 1, tzinfo=UTC)  # type: ignore[misc]


# --- add_months -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2025, 1, 31), 1, date(2025, 2, 28)),  # 2025 is not a leap year
        (date(2024, 1, 31), 1, date(2024, 2, 29)),  # 2024 is a leap year
        (date(1900, 1, 31), 1, date(1900, 2, 28)),  # century, not leap
        (date(2000, 1, 31), 1, date(2000, 2, 29)),  # divisible by 400, leap
        (date(2025, 3, 31), -1, date(2025, 2, 28)),
        (date(2024, 3, 31), -1, date(2024, 2, 29)),
        (date(2024, 2, 29), 12, date(2025, 2, 28)),
        (date(2024, 2, 29), 48, date(2028, 2, 29)),
        (date(2024, 2, 29), -12, date(2023, 2, 28)),
        (date(2025, 1, 31), 2, date(2025, 3, 31)),  # no drift: computed from the original day
        (date(2025, 1, 31), 3, date(2025, 4, 30)),
        (date(2025, 5, 15), 0, date(2025, 5, 15)),
        (date(2025, 11, 30), 3, date(2026, 2, 28)),  # year roll-over forwards
        (date(2025, 12, 15), 1, date(2026, 1, 15)),
        (date(2026, 1, 15), -1, date(2025, 12, 15)),  # year roll-over backwards
        (date(2026, 1, 31), -2, date(2025, 11, 30)),
        (date(2025, 6, 10), 25, date(2027, 7, 10)),
        (date(2025, 6, 10), -30, date(2022, 12, 10)),
    ],
)
def test_add_months(start: date, months: int, expected: date) -> None:
    assert add_months(start, months) == expected


@pytest.mark.parametrize(
    ("start", "months"),
    [
        (date(9999, 12, 31), 1),
        (date(9999, 1, 15), 12),
        (date(1, 1, 1), -1),
        (date(1, 6, 15), -6),
        (date(2026, 1, 1), 10**9),
        (date(2026, 1, 1), -(10**9)),
    ],
)
def test_add_months_out_of_range_raises_invalid_date(start: date, months: int) -> None:
    with pytest.raises(InvalidDateError) as info:
        add_months(start, months)
    assert info.value.code == "INVALID_DATE"


def test_add_months_accepts_the_range_limits() -> None:
    assert add_months(date(9999, 11, 30), 1) == date(9999, 12, 30)
    assert add_months(date(1, 2, 28), -1) == date(1, 1, 28)
    assert add_months(date(9999, 12, 31), 0) == date(9999, 12, 31)


def test_add_months_does_not_drift_when_called_repeatedly_from_original() -> None:
    start = date(2025, 1, 31)
    assert [add_months(start, n) for n in (1, 2, 3, 4)] == [
        date(2025, 2, 28),
        date(2025, 3, 31),
        date(2025, 4, 30),
        date(2025, 5, 31),
    ]


# --- days_between -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 3, 1), date(2026, 3, 1), 0),
        (date(2026, 3, 1), date(2026, 3, 11), 10),
        (date(2026, 3, 11), date(2026, 3, 1), -10),
        (date(2025, 12, 31), date(2026, 1, 1), 1),
        (date(2026, 1, 1), date(2025, 12, 31), -1),
        (date(2024, 2, 28), date(2024, 3, 1), 2),
        (date(2025, 2, 28), date(2025, 3, 1), 1),
        (date(2025, 1, 1), date(2026, 1, 1), 365),
        (date(2024, 1, 1), date(2025, 1, 1), 366),
    ],
)
def test_days_between_is_signed(start: date, end: date, expected: int) -> None:
    assert days_between(start, end) == expected


# --- ISO date parsing and formatting ----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2025-02-03", date(2025, 2, 3)),
        ("2024-02-29", date(2024, 2, 29)),
        ("0001-01-01", date(1, 1, 1)),
        ("9999-12-31", date(9999, 12, 31)),
        ("2026-12-31", date(2026, 12, 31)),
    ],
)
def test_parse_iso_date_accepts_strict_form(text: str, expected: date) -> None:
    assert parse_iso_date(text) == expected
    assert format_iso_date(expected) == text  # round trip


@pytest.mark.parametrize(
    "text",
    [
        "2025-2-3",
        "2025-02-3",
        "2025-2-03",
        "20250203",
        "2025-02-30",
        "2023-02-29",
        "1900-02-29",
        "2025-13-01",
        "2025-00-10",
        "2025-01-00",
        "0000-01-01",
        " 2025-02-03",
        "2025-02-03 ",
        "2025-02-03\n",
        "2025-02-03T00:00:00",
        "2025/02/03",
        "2025-02-03Z",
        "\u0662\u0660\u0662\u0665-\u0660\u0662-\u0660\u0663",  # Arabic-Indic digits, not ASCII
        "",
        "yesterday",
    ],
)
def test_parse_iso_date_rejects_bad_forms(text: str) -> None:
    with pytest.raises(InvalidDateError) as info:
        parse_iso_date(text)
    assert info.value.code == "INVALID_DATE"
    assert isinstance(info.value, ValueError)


@pytest.mark.parametrize("value", [None, 20250203, date(2025, 2, 3), b"2025-02-03"])
def test_parse_iso_date_rejects_non_str(value: Any) -> None:
    with pytest.raises(InvalidDateError):
        parse_iso_date(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2025, 2, 3), "2025-02-03"),
        (date(1, 2, 3), "0001-02-03"),
        (date(999, 12, 31), "0999-12-31"),
        (date(2026, 11, 13), "2026-11-13"),
    ],
)
def test_format_iso_date(value: date, expected: str) -> None:
    assert format_iso_date(value) == expected


# --- UTC timestamps ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (datetime(2026, 3, 5, 2, 30, tzinfo=UTC), "2026-03-05T02:30:00Z"),
        (datetime(2026, 3, 5, 2, 30, 7, 654321, tzinfo=UTC), "2026-03-05T02:30:07Z"),  # truncated
        (
            datetime(2026, 3, 4, 23, 30, tzinfo=timezone(timedelta(hours=-3))),
            "2026-03-05T02:30:00Z",
        ),
        (
            datetime(2026, 3, 5, 5, 30, tzinfo=timezone(timedelta(hours=3))),
            "2026-03-05T02:30:00Z",
        ),
        (
            datetime(2026, 3, 5, 8, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
            "2026-03-05T02:30:00Z",
        ),
    ],
)
def test_format_utc_timestamp(instant: datetime, expected: str) -> None:
    assert format_utc_timestamp(instant) == expected


@pytest.mark.parametrize(
    ("timespec", "expected"),
    [
        ("seconds", "2026-03-05T02:30:07Z"),
        ("milliseconds", "2026-03-05T02:30:07.654Z"),
        ("microseconds", "2026-03-05T02:30:07.654321Z"),
    ],
)
def test_format_utc_timestamp_timespec_round_trips(timespec: str, expected: str) -> None:
    instant = datetime(2026, 3, 5, 2, 30, 7, 654321, tzinfo=UTC)
    text = format_utc_timestamp(instant, timespec=timespec)
    assert text == expected
    parsed = parse_utc_timestamp(text)  # every allowed format is read back
    assert format_utc_timestamp(parsed, timespec=timespec) == text


@pytest.mark.parametrize("timespec", ["minutes", "hours", "auto", "", "Seconds"])
def test_format_utc_timestamp_rejects_timespecs_that_cannot_be_parsed(timespec: str) -> None:
    with pytest.raises(ValueError, match="timespec"):
        format_utc_timestamp(datetime(2026, 3, 5, 2, 30, 7, tzinfo=UTC), timespec=timespec)


def test_format_utc_timestamp_rejects_naive() -> None:
    with pytest.raises(ValueError, match="aware"):
        format_utc_timestamp(NAIVE)


def test_format_utc_timestamp_of_a_clock() -> None:
    clock = FixedClock.at("2026-03-05T02:30:00Z", -3)
    assert format_utc_timestamp(clock.utc_now()) == "2026-03-05T02:30:00Z"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-03-05T02:30:00Z", datetime(2026, 3, 5, 2, 30, tzinfo=UTC)),
        ("2026-03-05T02:30:07.5Z", datetime(2026, 3, 5, 2, 30, 7, 500000, tzinfo=UTC)),
        ("2026-03-05T02:30:07.654321Z", datetime(2026, 3, 5, 2, 30, 7, 654321, tzinfo=UTC)),
        ("2024-02-29T23:59:59Z", datetime(2024, 2, 29, 23, 59, 59, tzinfo=UTC)),
    ],
)
def test_parse_utc_timestamp(text: str, expected: datetime) -> None:
    parsed = parse_utc_timestamp(text)
    assert parsed == expected
    assert parsed.tzinfo is UTC


@pytest.mark.parametrize(
    "text",
    [
        "2026-03-05T02:30:00",  # naive
        "2026-03-05T02:30:00+00:00",  # offset form
        "2026-03-05T02:30:00-03:00",
        "2026-03-05 02:30:00Z",  # space separator
        "2026-03-05T02:30:00z",  # lower-case z
        "2026-03-05T02:30Z",  # no seconds
        "2026-03-05T02:30:00.Z",
        "2026-03-05T02:30:00.1234567Z",  # more than microseconds
        "2026-03-05Z",
        "2026-3-5T02:30:00Z",
        "2026-02-30T02:30:00Z",
        "2026-03-05T24:00:00Z",
        "2026-03-05T02:60:00Z",
        "2026-03-05T02:30:60Z",
        " 2026-03-05T02:30:00Z",
        "2026-03-05T02:30:00Z ",
        "2026-03-05T02:30:00Z\n",
        "",
    ],
)
def test_parse_utc_timestamp_rejects_bad_forms(text: str) -> None:
    with pytest.raises(InvalidTimestampError) as info:
        parse_utc_timestamp(text)
    assert info.value.code == "INVALID_TIMESTAMP"
    assert isinstance(info.value, ValueError)


def test_parse_utc_timestamp_rejects_non_str() -> None:
    bad: Any = None
    with pytest.raises(InvalidTimestampError):
        parse_utc_timestamp(bad)


@pytest.mark.parametrize(
    "instant",
    [
        datetime(2026, 3, 5, 2, 30, tzinfo=UTC),
        datetime(2024, 2, 29, 23, 59, 59, tzinfo=UTC),
        datetime(2026, 12, 31, 0, 0, 1, tzinfo=timezone(timedelta(hours=-3))),
    ],
)
def test_timestamp_round_trip(instant: datetime) -> None:
    text = format_utc_timestamp(instant)
    assert text.endswith("Z")
    assert parse_utc_timestamp(text) == instant
    assert format_utc_timestamp(parse_utc_timestamp(text)) == text


def test_timestamp_round_trip_with_microseconds() -> None:
    instant = datetime(2026, 3, 5, 2, 30, 7, 120000, tzinfo=UTC)
    text = format_utc_timestamp(instant, timespec="microseconds")
    assert text == "2026-03-05T02:30:07.120000Z"
    assert parse_utc_timestamp(text) == instant


# --- small helpers ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2026, 3, 5), date(2026, 3, 1)),
        (date(2026, 3, 1), date(2026, 3, 1)),
        (date(2024, 2, 29), date(2024, 2, 1)),
        (date(2026, 12, 31), date(2026, 12, 1)),
    ],
)
def test_month_start(value: date, expected: date) -> None:
    assert month_start(value) == expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (date(2026, 3, 1), date(2026, 3, 31), True),
        (date(2026, 3, 31), date(2026, 4, 1), False),
        (date(2025, 3, 15), date(2026, 3, 15), False),  # same month, different year
        (date(2026, 3, 15), date(2026, 3, 15), True),
    ],
)
def test_is_same_month(a: date, b: date, expected: bool) -> None:
    assert is_same_month(a, b) is expected


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2024, 366), (2025, 365), (1900, 365), (2000, 366), (2100, 365), (2028, 366)],
)
def test_days_in_year(year: int, expected: int) -> None:
    assert days_in_year(year) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2025, 1, 1), 1),
        (date(2025, 3, 1), 60),
        (date(2024, 3, 1), 61),
        (date(2025, 12, 31), 365),
        (date(2024, 12, 31), 366),
    ],
)
def test_day_of_year(value: date, expected: int) -> None:
    assert day_of_year(value) == expected
