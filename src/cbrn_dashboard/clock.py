# SPDX-License-Identifier: GPL-3.0-or-later
"""The only module allowed to read the wall clock (PLAN T1.1, repository guard rule CLOCK).

Two notions of time are kept apart:

* Stored timestamps are always UTC: :meth:`Clock.utc_now` returns an aware ``datetime`` whose
  ``tzinfo`` is :data:`datetime.UTC`.
* "Today" is the *local calendar date of the workstation*: :meth:`Clock.local_date`. Day and month
  boundaries (daily backup, monthly snapshot, as-of date) use it. It is defined once, here.

The method names deliberately avoid the names the guard flags (``today``, ``now``, ``time`` ...),
so that callers of a clock never trip the guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


def _require_aware(instant: datetime) -> None:
    if instant.tzinfo is None or instant.utcoffset() is None:
        msg = "a timezone-aware datetime is required"
        raise ValueError(msg)


@runtime_checkable
class Clock(Protocol):
    """Source of the current instant and of the local calendar date."""

    def utc_now(self) -> datetime:
        """Current instant as an aware ``datetime`` with ``tzinfo=UTC``."""
        ...

    def local_date(self) -> date:
        """The local calendar date of the workstation ("today")."""
        ...

    def local_date_of(self, instant: datetime) -> date:
        """The local calendar date of an aware ``instant`` (same zone as :meth:`local_date`)."""
        ...


class SystemClock:
    """The real clock: UTC instants, local date in the system time zone."""

    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def local_date(self) -> date:
        return self.utc_now().astimezone().date()

    def local_date_of(self, instant: datetime) -> date:
        _require_aware(instant)
        return instant.astimezone().date()


@dataclass(frozen=True)
class FixedClock:
    """A deterministic clock for tests: a fixed UTC instant and a fixed UTC offset.

    ``instant`` must be timezone-aware; it is normalised to UTC. The local date is the date of
    ``instant`` shifted by ``utc_offset`` (for example ``timedelta(hours=-3)``).
    """

    instant: datetime
    utc_offset: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        _require_aware(self.instant)
        timezone(self.utc_offset)  # raises ValueError if the offset is not within one day
        object.__setattr__(self, "instant", self.instant.astimezone(UTC))

    @classmethod
    def at(cls, iso_utc: str, utc_offset_hours: float = 0) -> FixedClock:
        """Build from an ISO 8601 string such as ``2026-03-05T02:30:00Z`` (must carry a zone)."""
        return cls(datetime.fromisoformat(iso_utc), timedelta(hours=utc_offset_hours))

    def advanced(self, delta: timedelta) -> FixedClock:
        """A new clock ``delta`` later (earlier if negative), with the same offset."""
        return FixedClock(self.instant + delta, self.utc_offset)

    def utc_now(self) -> datetime:
        return self.instant

    def local_date(self) -> date:
        return self.local_date_of(self.instant)

    def local_date_of(self, instant: datetime) -> date:
        _require_aware(instant)
        return instant.astimezone(timezone(self.utc_offset)).date()
