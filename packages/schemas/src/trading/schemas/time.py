"""Time is int64 UTC nanoseconds, everywhere (D3).

There is one representation of an instant in this system and it is an integer.
Not ``datetime``, which is microsecond-precision and so cannot hold a venue
timestamp; not ``pa.timestamp("ns", tz="UTC")``, which round-trips into
``datetime`` objects the moment a table touches pandas or polars and quietly
reintroduces the surface ``tools/banned_patterns.py`` and ``tools/model_audit.py``
exist to eliminate.

The cost is honest and worth naming: an integer column renders as an integer in
DuckDB and in parquet viewers. That is an ergonomic cost, recoverable with a
formatting helper. A naive datetime that shifts an hour at a DST boundary is an
unrepairable correctness cost, and §41 lists look-ahead as failure mode one.

Parsing therefore never goes through ``datetime`` either: ``strptime`` would
truncate a nanosecond venue timestamp to microseconds, silently, on ingestion.
:func:`parse_rfc3339_ns` is integer arithmetic end to end.
"""

from __future__ import annotations

import calendar
import re
import time
from typing import Final, NewType

#: An instant, as integer nanoseconds since the Unix epoch, UTC.
TimestampNs = NewType("TimestampNs", int)

NS_PER_US: Final = 1_000
NS_PER_MS: Final = 1_000_000
NS_PER_SECOND: Final = 1_000_000_000
NS_PER_MINUTE: Final = 60 * NS_PER_SECOND
NS_PER_HOUR: Final = 60 * NS_PER_MINUTE
NS_PER_DAY: Final = 24 * NS_PER_HOUR

#: Plausibility band for any timestamp the system stores.
#:
#: Epoch zero is the classic "present but wrong" value — an uninitialised field,
#: a failed parse defaulted to 0, a vendor sending an empty string. It passes
#: every null check. Rejecting the band is what turns those into loud failures.
MIN_PLAUSIBLE_NS: Final = TimestampNs(946_684_800 * NS_PER_SECOND)  # 2000-01-01
MAX_PLAUSIBLE_NS: Final = TimestampNs(4_102_444_800 * NS_PER_SECOND)  # 2100-01-01

_RFC3339 = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"[Tt ](?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))?"
    r"(?:(?P<zulu>[Zz])|(?P<sign>[+-])(?P<oh>\d{2}):(?P<om>\d{2}))$"
)


class TimestampError(ValueError):
    """A timestamp could not be parsed, or is outside the plausibility band."""


def parse_rfc3339_ns(text: str) -> TimestampNs:
    """Parse an RFC-3339 timestamp to integer nanoseconds, losslessly.

    Args:
        text: e.g. ``2026-09-19T13:30:00.123456789Z``. An explicit offset is
            required — a timestamp without one is ambiguous, and guessing UTC is
            how a feed's local-time field becomes a silent one-hour error.

    Raises:
        TimestampError: If the text is malformed or carries no offset.
    """
    match = _RFC3339.match(text)
    if match is None:
        raise TimestampError(
            f"{text!r} is not an RFC-3339 timestamp with an explicit offset "
            "(e.g. '2026-09-19T13:30:00.123456789Z')"
        )

    parts = match.groupdict()
    days = calendar.timegm(
        (
            int(parts["year"]),
            int(parts["month"]),
            int(parts["day"]),
            int(parts["hour"]),
            int(parts["minute"]),
            int(parts["second"]),
            0,
            0,
            0,
        )
    )
    total = days * NS_PER_SECOND

    if fraction := parts["fraction"]:
        # Right-pad to nanosecond width: ".5" is 500ms, not 5ns.
        total += int(fraction.ljust(9, "0"))

    if sign := parts["sign"]:
        offset = int(parts["oh"]) * NS_PER_HOUR + int(parts["om"]) * NS_PER_MINUTE
        # "+05:00" means local is ahead of UTC, so UTC is earlier.
        total += -offset if sign == "+" else offset

    return TimestampNs(total)


def format_ns(value: TimestampNs) -> str:
    """Render nanoseconds as RFC-3339 UTC, for logs and reports only.

    Never round-trip through this for storage. It exists so an integer column is
    readable by a human, not so timestamps can live as strings.
    """
    # floor division, so a pre-epoch instant still yields a non-negative
    # nanosecond remainder rather than a malformed fractional part.
    seconds, nanos = divmod(int(value), NS_PER_SECOND)
    parts = time.gmtime(seconds)
    return (
        f"{parts.tm_year:04d}-{parts.tm_mon:02d}-{parts.tm_mday:02d}"
        f"T{parts.tm_hour:02d}:{parts.tm_min:02d}:{parts.tm_sec:02d}"
        f".{nanos:09d}Z"
    )


def is_plausible(value: TimestampNs) -> bool:
    """Whether a timestamp falls inside the band the system will store."""
    return MIN_PLAUSIBLE_NS <= value <= MAX_PLAUSIBLE_NS


def require_plausible(value: TimestampNs, *, field: str) -> TimestampNs:
    """Return the timestamp, or raise naming the field that carried it."""
    if not is_plausible(value):
        raise TimestampError(
            f"{field}={value} is outside the plausible band "
            f"[{MIN_PLAUSIBLE_NS}, {MAX_PLAUSIBLE_NS}] "
            f"({format_ns(MIN_PLAUSIBLE_NS)} .. {format_ns(MAX_PLAUSIBLE_NS)}). "
            "Zero and other sentinel values are rejected here rather than "
            "surviving as a plausible-looking 1970 decision time."
        )
    return value
