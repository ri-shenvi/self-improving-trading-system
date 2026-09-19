"""Pydantic models generated from the contract declarations.

DO NOT EDIT. Regenerate with ``make codegen``; ``make verify`` fails if this
file disagrees with the declarations in ``trading.schemas``.

Models are frozen and forbid extra fields: a contract row is a record of what
happened, and a typo in a field name must be an error rather than a silently
ignored attribute.
"""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict

from trading.schemas.identifiers import InstrumentId
from trading.schemas.money import NanoDollars, Shares
from trading.schemas.time import TimestampNs

__all__ = [
    "ReferenceInstrument",
    "ReferenceTickerHistory",
]


class ReferenceInstrument(BaseModel):
    """The instrument master: one row per tradable instrument, ever.

    Contract ``reference.instrument`` v1 (frozen).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_time: TimestampNs
    """Timestamp assigned by the originating venue or source (§6)."""
    receive_time: TimestampNs
    """When the gateway received the message (§6). Used for latency and stale-feed detection."""
    process_time: TimestampNs
    """When normalization completed (§6). Absent from raw records, which have not been normalized yet."""
    knowledge_time: TimestampNs
    """Earliest time the system could have known this value (§6). The field point-in-time correctness rests on: every feature join is bounded by it, and it is never copied from a vendor field (D1)."""
    effective_time: TimestampNs
    """When the record becomes economically effective (§6) -- a corporate action's ex-date, a ticker assignment's start. Distinct from knowledge_time, which is when we could first know of it."""
    revision_time: TimestampNs | None
    """When a correction or restatement arrived (§6), or null if this record has never been revised."""
    instrument_id: InstrumentId
    """Permanent surrogate. Never reused, never derived from a ticker."""
    primary_exchange: str
    """Listing venue (§7)."""
    security_type: str
    """Common stock, ETF, and so on (§7). v1 trades only the first two."""
    lot_size: int
    """Round lot size (§7). Order sizing and odd-lot handling depend on it."""
    is_tradable: bool
    """Whether the instrument may be traded as of this record's effective_time. Delisting sets it false rather than deleting the row, which would be survivorship bias by omission."""


class ReferenceTickerHistory(BaseModel):
    """Which ticker an instrument carried, over which interval (§7).

    Contract ``reference.ticker_history`` v1 (frozen).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_time: TimestampNs
    """Timestamp assigned by the originating venue or source (§6)."""
    receive_time: TimestampNs
    """When the gateway received the message (§6). Used for latency and stale-feed detection."""
    process_time: TimestampNs
    """When normalization completed (§6). Absent from raw records, which have not been normalized yet."""
    knowledge_time: TimestampNs
    """Earliest time the system could have known this value (§6). The field point-in-time correctness rests on: every feature join is bounded by it, and it is never copied from a vendor field (D1)."""
    effective_time: TimestampNs
    """When the record becomes economically effective (§6) -- a corporate action's ex-date, a ticker assignment's start. Distinct from knowledge_time, which is when we could first know of it."""
    revision_time: TimestampNs | None
    """When a correction or restatement arrived (§6), or null if this record has never been revised."""
    instrument_id: InstrumentId
    """The instrument."""
    ticker: str
    """The symbol, as displayed."""
    end_time: TimestampNs | None
    """Exclusive end of the assignment, or null while it still holds. Half-open intervals so a reassignment on the same day has no ambiguous instant."""
