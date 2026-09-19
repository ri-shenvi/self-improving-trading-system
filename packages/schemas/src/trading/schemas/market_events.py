"""The market event contracts (§7).

One contract per dataset, never a union column: a trade and a quote share almost
no fields, and a union would force every reader to branch and every null to be
interpreted. Each carries the §6 timestamps for its time group and, where it is
a dispatched event, the §16 ordering columns.

Prices are integer nano-dollars and sizes integer shares throughout (D2'), so
``price * size`` is exact. Coded fields name a versioned ``codeset``, because
swapping a condition vocabulary changes how the bytes must be read even when the
Arrow type is identical — and that must move the contract hash.
"""

from __future__ import annotations

from trading.schemas.registry import register
from trading.schemas.spec import (
    ContractSpec,
    FieldKind,
    FieldSpec,
    Maturity,
    TimeGroup,
    ordering_fields,
    time_fields,
)

_CORE = time_fields(TimeGroup.CORE)
_EFFECTIVE = time_fields(TimeGroup.EFFECTIVE)
_ORDER = ordering_fields()

TRADE = register(
    ContractSpec(
        name="normalized.trade",
        version=1,
        maturity=Maturity.FROZEN,
        doc="A single executed print (§7 Trades).",
        time_group=TimeGroup.CORE,
        fields=(
            *_CORE,
            *_ORDER,
            FieldSpec(
                "instrument_id",
                FieldKind.INSTRUMENT_ID,
                doc="Resolved from the vendor's symbol through ticker_history. "
                "The symbol itself is never stored as a join key (D6).",
            ),
            FieldSpec("price_nano", FieldKind.NANO_DOLLARS, unit="nanodollar", doc="Print price."),
            FieldSpec("size_shares", FieldKind.SHARES, unit="share", doc="Print size."),
            FieldSpec("exchange", FieldKind.CODE, codeset="exchange_v1", doc="Executing venue."),
            FieldSpec(
                "conditions",
                FieldKind.CONDITIONS,
                codeset="trade_condition_v1",
                doc="Sale conditions. Decides bar and VWAP eligibility, so the "
                "codeset version is part of the contract.",
            ),
            FieldSpec(
                "trade_id",
                FieldKind.TEXT,
                doc="Vendor's print identifier. Required to apply a later "
                "correction or cancel to the right print.",
            ),
            FieldSpec("tape", FieldKind.TAPE, codeset="tape_v1", doc="Tape A, B or C."),
            FieldSpec(
                "is_cancelled",
                FieldKind.BOOL,
                doc="Whether a later cancel/error message voided this print. "
                "Set by appending a revision, never by deleting the row (§8).",
            ),
        ),
    )
)

QUOTE = register(
    ContractSpec(
        name="normalized.quote",
        version=1,
        maturity=Maturity.FROZEN,
        doc="A bid/ask pair as published (§7 Quotes).",
        time_group=TimeGroup.CORE,
        fields=(
            *_CORE,
            *_ORDER,
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="Resolved instrument."),
            FieldSpec("bid_price_nano", FieldKind.NANO_DOLLARS, unit="nanodollar", doc="Best bid."),
            FieldSpec("bid_size_shares", FieldKind.SHARES, unit="share", doc="Displayed bid size."),
            FieldSpec("bid_exchange", FieldKind.CODE, codeset="exchange_v1", doc="Bid venue."),
            FieldSpec("ask_price_nano", FieldKind.NANO_DOLLARS, unit="nanodollar", doc="Best ask."),
            FieldSpec("ask_size_shares", FieldKind.SHARES, unit="share", doc="Displayed ask size."),
            FieldSpec("ask_exchange", FieldKind.CODE, codeset="exchange_v1", doc="Ask venue."),
            FieldSpec(
                "conditions",
                FieldKind.CONDITIONS,
                codeset="quote_condition_v1",
                doc="Quote conditions, including the ones that mark a quote "
                "non-firm. A locked or crossed book is flagged, never discarded (§10).",
            ),
            FieldSpec("tape", FieldKind.TAPE, codeset="tape_v1", doc="Tape A, B or C."),
            FieldSpec(
                "venue_coverage",
                FieldKind.CODE,
                codeset="venue_coverage_v1",
                doc="Whether this quote is consolidated ('sip') or a single "
                "venue's own book ('iex_only') (D11). An IEX quote is NOT the "
                "NBBO -- it is a few percent of volume -- so the quote-replay "
                "fill model refuses to run on it. Nothing downstream may infer "
                "coverage from context.",
            ),
        ),
    )
)

BAR = register(
    ContractSpec(
        name="normalized.bar",
        version=1,
        maturity=Maturity.FROZEN,
        doc="An aggregated window, built from trades rather than vendored (§7 Bars, D12).",
        time_group=TimeGroup.CORE,
        fields=(
            *_CORE,
            *_ORDER,
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="Resolved instrument."),
            FieldSpec(
                "window_ns",
                FieldKind.SEQUENCE,
                unit=None,
                doc="Window length in nanoseconds. event_time is the window's "
                "start; the window is half-open, [start, start + window_ns).",
            ),
            FieldSpec(
                "open_nano", FieldKind.NANO_DOLLARS, unit="nanodollar", doc="First eligible print."
            ),
            FieldSpec(
                "high_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Highest eligible print.",
            ),
            FieldSpec(
                "low_nano", FieldKind.NANO_DOLLARS, unit="nanodollar", doc="Lowest eligible print."
            ),
            FieldSpec(
                "close_nano", FieldKind.NANO_DOLLARS, unit="nanodollar", doc="Last eligible print."
            ),
            FieldSpec("volume_shares", FieldKind.SHARES, unit="share", doc="Summed eligible size."),
            FieldSpec(
                "vwap_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Volume-weighted average price over the window only. Never "
                "the session-to-close VWAP, which is a look-ahead value (§21).",
            ),
            FieldSpec("trade_count", FieldKind.COUNT, doc="Eligible prints in the window."),
            FieldSpec(
                "is_complete",
                FieldKind.BOOL,
                doc="Whether the window had closed when this row was built. A "
                "partial bar must never feed a feature whose decision clock "
                "assumes a closed window.",
            ),
        ),
    )
)

TRADING_STATUS = register(
    ContractSpec(
        name="normalized.trading_status",
        version=1,
        maturity=Maturity.FROZEN,
        doc="Halt, resumption and price-band state (§7 Halts and bands).",
        time_group=TimeGroup.CORE,
        fields=(
            *_CORE,
            *_ORDER,
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="Resolved instrument."),
            FieldSpec(
                "status",
                FieldKind.CODE,
                codeset="trading_status_v1",
                doc="Halted, resumed, paused, and so on. Dispatched ahead of "
                "quotes and trades so risk sees a halt before a print can "
                "generate an order.",
            ),
            FieldSpec("reason", FieldKind.CODE, codeset="halt_reason_v1", doc="Venue reason code."),
            FieldSpec(
                "resume_time",
                FieldKind.TIMESTAMP_NS,
                nullable=True,
                unit="ns_utc",
                doc="Announced resumption, where the venue gives one.",
            ),
            FieldSpec(
                "luld_upper_nano",
                FieldKind.NANO_DOLLARS,
                nullable=True,
                unit="nanodollar",
                doc="Limit-up band. An order priced outside the band is not "
                "executable, so a simulated fill outside it is invalid.",
            ),
            FieldSpec(
                "luld_lower_nano",
                FieldKind.NANO_DOLLARS,
                nullable=True,
                unit="nanodollar",
                doc="Limit-down band.",
            ),
        ),
    )
)

CORPORATE_ACTION = register(
    ContractSpec(
        name="reference.corporate_action",
        version=1,
        maturity=Maturity.FROZEN,
        doc="Splits, dividends, mergers and symbol changes (§7 Corporate actions).",
        time_group=TimeGroup.EFFECTIVE,
        fields=(
            *_EFFECTIVE,
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="Affected instrument."),
            FieldSpec(
                "action_type",
                FieldKind.CODE,
                codeset="corporate_action_v1",
                doc="split, dividend, merger, symbol_change.",
            ),
            FieldSpec(
                "announcement_time",
                FieldKind.TIMESTAMP_NS,
                unit="ns_utc",
                doc="When the action was announced (§7 requires both times). "
                "Distinct from effective_time, the ex-date: conflating them is "
                "survivorship bias with extra steps.",
            ),
            FieldSpec(
                "split_numerator",
                FieldKind.COUNT,
                nullable=True,
                doc="Split ratio numerator. Stored as an exact rational pair "
                "rather than a float, because 3-for-2 is not representable in "
                "binary and an adjustment factor must be exact.",
            ),
            FieldSpec(
                "split_denominator", FieldKind.COUNT, nullable=True, doc="Split ratio denominator."
            ),
            FieldSpec(
                "cash_amount_nano",
                FieldKind.NANO_DOLLARS,
                nullable=True,
                unit="nanodollar",
                doc="Dividend or cash-in-lieu amount per share.",
            ),
            FieldSpec(
                "new_ticker",
                FieldKind.TEXT,
                nullable=True,
                doc="Post-change symbol, for a symbol change. The instrument_id "
                "does not change; only the ticker assignment does.",
            ),
        ),
    )
)

CALENDAR_SESSION = register(
    ContractSpec(
        name="reference.calendar_session",
        version=1,
        maturity=Maturity.FROZEN,
        doc="Sessions, holidays, early closes and auction windows (§7 Calendar).",
        time_group=TimeGroup.EFFECTIVE,
        fields=(
            *_EFFECTIVE,
            FieldSpec("session_date", FieldKind.DATE, doc="Exchange-local session date."),
            FieldSpec(
                "is_trading_day",
                FieldKind.BOOL,
                doc="False for a holiday. The exchange calendar is authoritative (§7).",
            ),
            FieldSpec(
                "regular_open_ns",
                FieldKind.TIMESTAMP_NS,
                nullable=True,
                unit="ns_utc",
                doc="Regular-session open, null on a non-trading day.",
            ),
            FieldSpec(
                "regular_close_ns",
                FieldKind.TIMESTAMP_NS,
                nullable=True,
                unit="ns_utc",
                doc="Regular-session close. Early closes carry an earlier value "
                "rather than a separate flag being the only signal.",
            ),
            FieldSpec("is_early_close", FieldKind.BOOL, doc="Whether the session closes early."),
            FieldSpec(
                "opening_auction_ns",
                FieldKind.TIMESTAMP_NS,
                nullable=True,
                unit="ns_utc",
                doc="Opening auction time.",
            ),
            FieldSpec(
                "closing_auction_ns",
                FieldKind.TIMESTAMP_NS,
                nullable=True,
                unit="ns_utc",
                doc="Closing auction time.",
            ),
        ),
    )
)

BORROW = register(
    ContractSpec(
        name="reference.borrow",
        version=1,
        maturity=Maturity.FROZEN,
        doc="Short availability and Regulation SHO state (§7 Borrow and SSR).",
        time_group=TimeGroup.EFFECTIVE,
        fields=(
            *_EFFECTIVE,
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="Instrument."),
            FieldSpec(
                "is_shortable",
                FieldKind.BOOL,
                doc="Whether the broker reported the instrument shortable. §17: "
                "reject a historical short where borrow plausibility is absent "
                "rather than assuming free inventory.",
            ),
            FieldSpec(
                "available_shares",
                FieldKind.SHARES,
                nullable=True,
                unit="share",
                doc="Quantity the broker reported available, where given.",
            ),
            FieldSpec(
                "borrow_fee_annual_bps",
                FieldKind.RATIO,
                doc="Annualised borrow fee in basis points. A rate, never a "
                "monetary amount: accrual divides it by 360 and rounds the "
                "resulting cost against us.",
            ),
            FieldSpec(
                "locate_state", FieldKind.CODE, codeset="locate_state_v1", doc="Locate status."
            ),
            FieldSpec(
                "rule_201_restricted",
                FieldKind.BOOL,
                doc="Whether the Rule 201 short-sale price test is in force "
                "after a 10 percent decline.",
            ),
        ),
    )
)
