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
    "NormalizedBar",
    "NormalizedQuote",
    "NormalizedTrade",
    "NormalizedTradingStatus",
    "ReferenceBorrow",
    "ReferenceCalendarSession",
    "ReferenceCorporateAction",
    "ReferenceInstrument",
    "ReferenceTickerHistory",
]


class NormalizedBar(BaseModel):
    """An aggregated window, built from trades rather than vendored (§7 Bars, D12).

    Contract ``normalized.bar`` v1 (frozen).
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
    revision_time: TimestampNs | None
    """When a correction or restatement arrived (§6), or null if this record has never been revised."""
    source_rank: int
    """Dispatch priority among events sharing a timestamp. See trading.schemas.ordering.SourceRank -- constraints before opportunities."""
    vendor_sequence: int
    """Vendor's sequence number, or -1 where the feed supplies none."""
    venue_sequence: int
    """Venue's sequence number, or -1 where absent."""
    ingest_index: int
    """Position within the raw partition, in the byte order of the raw file. Never arrival order -- see ordering.assign_ingest_index."""
    raw_partition_id: str
    """Provenance: which raw partition this row was normalized from. Non-key, but ingest_index is only unique within one."""
    event_time_source: str
    """Whether event_time is the participant timestamp, the SIP timestamp, or unknown. Recorded from the first row written because D1's cost is unrepairable: if the vendor field turns out to be an ingest time, knowledge_time is wrong everywhere and unrecoverable. M7's quality gate refuses to promote a snapshot containing 'vendor_unknown'."""
    instrument_id: InstrumentId
    """Resolved instrument."""
    window_ns: int
    """Window length in nanoseconds. event_time is the window's start; the window is half-open, [start, start + window_ns)."""
    open_nano: NanoDollars
    """First eligible print."""
    high_nano: NanoDollars
    """Highest eligible print."""
    low_nano: NanoDollars
    """Lowest eligible print."""
    close_nano: NanoDollars
    """Last eligible print."""
    volume_shares: Shares
    """Summed eligible size."""
    vwap_nano: NanoDollars
    """Volume-weighted average price over the window only. Never the session-to-close VWAP, which is a look-ahead value (§21)."""
    trade_count: int
    """Eligible prints in the window."""
    is_complete: bool
    """Whether the window had closed when this row was built. A partial bar must never feed a feature whose decision clock assumes a closed window."""


class NormalizedQuote(BaseModel):
    """A bid/ask pair as published (§7 Quotes).

    Contract ``normalized.quote`` v1 (frozen).
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
    revision_time: TimestampNs | None
    """When a correction or restatement arrived (§6), or null if this record has never been revised."""
    source_rank: int
    """Dispatch priority among events sharing a timestamp. See trading.schemas.ordering.SourceRank -- constraints before opportunities."""
    vendor_sequence: int
    """Vendor's sequence number, or -1 where the feed supplies none."""
    venue_sequence: int
    """Venue's sequence number, or -1 where absent."""
    ingest_index: int
    """Position within the raw partition, in the byte order of the raw file. Never arrival order -- see ordering.assign_ingest_index."""
    raw_partition_id: str
    """Provenance: which raw partition this row was normalized from. Non-key, but ingest_index is only unique within one."""
    event_time_source: str
    """Whether event_time is the participant timestamp, the SIP timestamp, or unknown. Recorded from the first row written because D1's cost is unrepairable: if the vendor field turns out to be an ingest time, knowledge_time is wrong everywhere and unrecoverable. M7's quality gate refuses to promote a snapshot containing 'vendor_unknown'."""
    instrument_id: InstrumentId
    """Resolved instrument."""
    bid_price_nano: NanoDollars
    """Best bid."""
    bid_size_shares: Shares
    """Displayed bid size."""
    bid_exchange: str
    """Bid venue."""
    ask_price_nano: NanoDollars
    """Best ask."""
    ask_size_shares: Shares
    """Displayed ask size."""
    ask_exchange: str
    """Ask venue."""
    conditions: tuple[str, ...]
    """Quote conditions, including the ones that mark a quote non-firm. A locked or crossed book is flagged, never discarded (§10)."""
    tape: str
    """Tape A, B or C."""
    venue_coverage: str
    """Whether this quote is consolidated ('sip') or a single venue's own book ('iex_only') (D11). An IEX quote is NOT the NBBO -- it is a few percent of volume -- so the quote-replay fill model refuses to run on it. Nothing downstream may infer coverage from context."""


class NormalizedTrade(BaseModel):
    """A single executed print (§7 Trades).

    Contract ``normalized.trade`` v1 (frozen).
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
    revision_time: TimestampNs | None
    """When a correction or restatement arrived (§6), or null if this record has never been revised."""
    source_rank: int
    """Dispatch priority among events sharing a timestamp. See trading.schemas.ordering.SourceRank -- constraints before opportunities."""
    vendor_sequence: int
    """Vendor's sequence number, or -1 where the feed supplies none."""
    venue_sequence: int
    """Venue's sequence number, or -1 where absent."""
    ingest_index: int
    """Position within the raw partition, in the byte order of the raw file. Never arrival order -- see ordering.assign_ingest_index."""
    raw_partition_id: str
    """Provenance: which raw partition this row was normalized from. Non-key, but ingest_index is only unique within one."""
    event_time_source: str
    """Whether event_time is the participant timestamp, the SIP timestamp, or unknown. Recorded from the first row written because D1's cost is unrepairable: if the vendor field turns out to be an ingest time, knowledge_time is wrong everywhere and unrecoverable. M7's quality gate refuses to promote a snapshot containing 'vendor_unknown'."""
    instrument_id: InstrumentId
    """Resolved from the vendor's symbol through ticker_history. The symbol itself is never stored as a join key (D6)."""
    price_nano: NanoDollars
    """Print price."""
    size_shares: Shares
    """Print size."""
    exchange: str
    """Executing venue."""
    conditions: tuple[str, ...]
    """Sale conditions. Decides bar and VWAP eligibility, so the codeset version is part of the contract."""
    trade_id: str
    """Vendor's print identifier. Required to apply a later correction or cancel to the right print."""
    tape: str
    """Tape A, B or C."""
    is_cancelled: bool
    """Whether a later cancel/error message voided this print. Set by appending a revision, never by deleting the row (§8)."""


class NormalizedTradingStatus(BaseModel):
    """Halt, resumption and price-band state (§7 Halts and bands).

    Contract ``normalized.trading_status`` v1 (frozen).
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
    revision_time: TimestampNs | None
    """When a correction or restatement arrived (§6), or null if this record has never been revised."""
    source_rank: int
    """Dispatch priority among events sharing a timestamp. See trading.schemas.ordering.SourceRank -- constraints before opportunities."""
    vendor_sequence: int
    """Vendor's sequence number, or -1 where the feed supplies none."""
    venue_sequence: int
    """Venue's sequence number, or -1 where absent."""
    ingest_index: int
    """Position within the raw partition, in the byte order of the raw file. Never arrival order -- see ordering.assign_ingest_index."""
    raw_partition_id: str
    """Provenance: which raw partition this row was normalized from. Non-key, but ingest_index is only unique within one."""
    event_time_source: str
    """Whether event_time is the participant timestamp, the SIP timestamp, or unknown. Recorded from the first row written because D1's cost is unrepairable: if the vendor field turns out to be an ingest time, knowledge_time is wrong everywhere and unrecoverable. M7's quality gate refuses to promote a snapshot containing 'vendor_unknown'."""
    instrument_id: InstrumentId
    """Resolved instrument."""
    status: str
    """Halted, resumed, paused, and so on. Dispatched ahead of quotes and trades so risk sees a halt before a print can generate an order."""
    reason: str
    """Venue reason code."""
    resume_time: TimestampNs | None
    """Announced resumption, where the venue gives one."""
    luld_upper_nano: NanoDollars | None
    """Limit-up band. An order priced outside the band is not executable, so a simulated fill outside it is invalid."""
    luld_lower_nano: NanoDollars | None
    """Limit-down band."""


class ReferenceBorrow(BaseModel):
    """Short availability and Regulation SHO state (§7 Borrow and SSR).

    Contract ``reference.borrow`` v1 (frozen).
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
    """Instrument."""
    is_shortable: bool
    """Whether the broker reported the instrument shortable. §17: reject a historical short where borrow plausibility is absent rather than assuming free inventory."""
    available_shares: Shares | None
    """Quantity the broker reported available, where given."""
    borrow_fee_annual_bps: float
    """Annualised borrow fee in basis points. A rate, never a monetary amount: accrual divides it by 360 and rounds the resulting cost against us."""
    locate_state: str
    """Locate status."""
    rule_201_restricted: bool
    """Whether the Rule 201 short-sale price test is in force after a 10 percent decline."""


class ReferenceCalendarSession(BaseModel):
    """Sessions, holidays, early closes and auction windows (§7 Calendar).

    Contract ``reference.calendar_session`` v1 (frozen).
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
    session_date: datetime.date
    """Exchange-local session date."""
    is_trading_day: bool
    """False for a holiday. The exchange calendar is authoritative (§7)."""
    regular_open_ns: TimestampNs | None
    """Regular-session open, null on a non-trading day."""
    regular_close_ns: TimestampNs | None
    """Regular-session close. Early closes carry an earlier value rather than a separate flag being the only signal."""
    is_early_close: bool
    """Whether the session closes early."""
    opening_auction_ns: TimestampNs | None
    """Opening auction time."""
    closing_auction_ns: TimestampNs | None
    """Closing auction time."""


class ReferenceCorporateAction(BaseModel):
    """Splits, dividends, mergers and symbol changes (§7 Corporate actions).

    Contract ``reference.corporate_action`` v1 (frozen).
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
    """Affected instrument."""
    action_type: str
    """split, dividend, merger, symbol_change."""
    announcement_time: TimestampNs
    """When the action was announced (§7 requires both times). Distinct from effective_time, the ex-date: conflating them is survivorship bias with extra steps."""
    split_numerator: int | None
    """Split ratio numerator. Stored as an exact rational pair rather than a float, because 3-for-2 is not representable in binary and an adjustment factor must be exact."""
    split_denominator: int | None
    """Split ratio denominator."""
    cash_amount_nano: NanoDollars | None
    """Dividend or cash-in-lieu amount per share."""
    new_ticker: str | None
    """Post-change symbol, for a symbol change. The instrument_id does not change; only the ticker assignment does."""


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
