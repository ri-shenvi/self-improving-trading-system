"""Bars built from normalized trades, never taken from the vendor (D12).

§7 says to build bars internally where possible, and D12 makes that a rule. The
reason is reproducibility at the bottom of the stack: a vendor's bar carries its
own revision semantics and its own condition filter, neither of which we control,
so a historical vendor bar cannot be rebuilt and the as-was guarantee fails on
the very first derived table.

Building them ourselves makes three things explicit that a vendor bar hides:

**Which prints count.** Sale conditions decide eligibility, and the filter is a
versioned policy rather than a hidden default.

**Where the window boundaries are.** Half-open in nanoseconds,
``[start, start + window)``, so a print at exactly the boundary belongs to
exactly one bar.

**Whether the window closed.** ``is_complete`` is false for a window still
open at the moment the bars were built, so a feature whose decision clock
assumes a closed window cannot silently read a partial one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final

from trading.schemas.money import round_statistic
from trading.schemas.ordering import MISSING_SEQUENCE, SourceRank, assign_ingest_index
from trading.schemas.time import TimestampNs

#: Sale conditions that disqualify a print from a regular-session bar.
#:
#: ``T`` and ``U`` are extended-hours prints and ``Z`` is sold out of sequence;
#: none reflects a regular-session transaction at the time it is reported.
#:
#: This is a starting policy, not the authoritative table. The full CTA and UTP
#: condition sets must be verified against the vendor at M7 -- see question 4 in
#: docs/vendor-timestamp-mapping.md, which asks whether IEX populates conditions
#: identically to SIP. The set is versioned so a change is visible: every bar
#: carries the version it was built under.
INELIGIBLE_CONDITIONS: Final = frozenset({"T", "U", "Z"})
CONDITION_POLICY_VERSION: Final = "bar_eligibility_v1"

#: One minute, the default research clock in §13's example strategy.
ONE_MINUTE_NS: Final = 60_000_000_000


@dataclass(frozen=True, slots=True)
class TradeInput:
    """The fields of a normalized trade that bar construction reads."""

    event_time: TimestampNs
    price_nano: int
    size_shares: int
    conditions: tuple[str, ...]
    instrument_id: int


def is_bar_eligible(conditions: Sequence[str]) -> bool:
    """Whether a print may contribute to a regular-session bar."""
    return not (set(conditions) & INELIGIBLE_CONDITIONS)


def window_start(event_time: TimestampNs, window_ns: int, origin_ns: int) -> int:
    """Return the start of the half-open window containing ``event_time``.

    Windows are anchored to ``origin_ns`` -- the session open -- rather than to
    the epoch, so a bar boundary lands on the session clock rather than wherever
    the epoch happens to fall relative to it.
    """
    offset = int(event_time) - origin_ns
    return origin_ns + (offset // window_ns) * window_ns


def build_bars(
    trades: Sequence[TradeInput],
    *,
    window_ns: int,
    origin_ns: int,
    as_of: TimestampNs,
    raw_partition_id: str,
    event_time_source: str,
    receive_time: TimestampNs,
    process_time: TimestampNs,
    knowledge_lag_ns: int,
) -> list[dict[str, Any]]:
    """Aggregate trades into bar rows, in §16 order.

    Args:
        trades: Normalized trades. Need not be sorted.
        window_ns: Window length in nanoseconds.
        origin_ns: Window anchor, normally the session open.
        as_of: The instant up to which data is known. A window ending after this
            is marked incomplete.
        knowledge_lag_ns: Added to a window's *end* to give its knowledge time --
            a bar cannot be known before the last print it contains.

    Returns:
        One row per window that contained at least one eligible print. Empty
        windows are omitted rather than emitted as zero-volume bars, which would
        be indistinguishable from a real bar with no trades.
    """
    grouped: dict[int, list[TradeInput]] = {}
    for trade in trades:
        if not is_bar_eligible(trade.conditions):
            continue
        grouped.setdefault(window_start(trade.event_time, window_ns, origin_ns), []).append(trade)

    rows: list[dict[str, Any]] = []
    for position, start in enumerate(sorted(grouped)):
        window = sorted(grouped[start], key=lambda t: int(t.event_time))
        end = start + window_ns

        volume = sum(t.size_shares for t in window)
        notional = sum(t.price_nano * t.size_shares for t in window)
        # A division, so it rounds -- toward zero, because a VWAP describes what
        # happened rather than being money anyone paid. See round_statistic.
        vwap = round_statistic(Fraction(notional, volume), field="vwap_nano").value

        # A bar is knowable once its window has closed and the feed has caught
        # up, never at the window's start.
        knowledge_time = end + knowledge_lag_ns

        rows.append(
            {
                "event_time": start,
                "receive_time": max(int(receive_time), knowledge_time),
                "process_time": max(int(process_time), knowledge_time),
                "knowledge_time": knowledge_time,
                "revision_time": None,
                "source_rank": int(SourceRank.BAR),
                "vendor_sequence": MISSING_SEQUENCE,
                "venue_sequence": MISSING_SEQUENCE,
                "ingest_index": assign_ingest_index(position),
                "raw_partition_id": raw_partition_id,
                "event_time_source": event_time_source,
                "instrument_id": window[0].instrument_id,
                "window_ns": window_ns,
                "open_nano": window[0].price_nano,
                "high_nano": max(t.price_nano for t in window),
                "low_nano": min(t.price_nano for t in window),
                "close_nano": window[-1].price_nano,
                "volume_shares": volume,
                "vwap_nano": int(vwap),
                "trade_count": len(window),
                "is_complete": end <= int(as_of),
            }
        )
    return rows
