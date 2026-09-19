"""Order lifecycle, fills, positions and account state (§9, §30).

The OMS is a state machine, not an HTTP wrapper (§30), and these are the shapes
it moves through. They are declared here rather than in ``packages/oms`` because
both the simulator and the broker adapters write them, and a contract owned by
one consumer drifts toward that consumer's convenience.

The backtest artifacts (``execution.*``) are Arrow contracts. The live
``order_event`` table is Postgres and deliberately a different shape: parquet
holds a typed simulated event log, while Postgres holds broker events with a
JSONB payload we do not control. Unifying them would force the simulator to
carry a blob it never reads.
"""

from __future__ import annotations

from enum import StrEnum

from trading.schemas.registry import register
from trading.schemas.spec import (
    ContractSpec,
    FieldKind,
    FieldSpec,
    Maturity,
    TimeGroup,
    time_fields,
)

_CORE = time_fields(TimeGroup.CORE)


class OrderState(StrEnum):
    """The §30 order state machine.

    ``CREATED -> RISK_APPROVED -> SUBMITTING -> ACKNOWLEDGED -> PARTIALLY_FILLED
    -> FILLED``, with ``REJECTED``, ``UNKNOWN``, ``CANCELING`` and ``CANCELED``
    as the branches.
    """

    CREATED = "created"
    RISK_APPROVED = "risk_approved"
    SUBMITTING = "submitting"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELING = "canceling"
    CANCELED = "canceled"

    #: The broker's view could not be established. §30 is explicit: an UNKNOWN
    #: order is never retried as a new order. Query by client_order_id,
    #: reconcile, and enter SAFE if it cannot be resolved inside the timeout
    #: budget. Retrying is how one intent becomes two live orders.
    UNKNOWN = "unknown"


#: States from which no further transition is possible.
TERMINAL_STATES = frozenset({OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELED})


class RiskReason(StrEnum):
    """Closed reason codes for a pre-trade decision (§25).

    Closed on purpose: §25 requires a reason-coded approval or rejection
    persisted *before* any broker call, and a free-text reason cannot be
    aggregated, alerted on, or tested for.
    """

    APPROVED = "approved"
    DUPLICATE_CLIENT_ORDER_ID = "duplicate_client_order_id"
    SYMBOL_HALTED = "symbol_halted"
    OUTSIDE_LULD_BAND = "outside_luld_band"
    STALE_MARKET_DATA = "stale_market_data"
    OUTSIDE_SESSION = "outside_session"
    PRICE_COLLAR = "price_collar"
    POSITION_LIMIT = "position_limit"
    GROSS_EXPOSURE_LIMIT = "gross_exposure_limit"
    NET_EXPOSURE_LIMIT = "net_exposure_limit"
    SECTOR_EXPOSURE_LIMIT = "sector_exposure_limit"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    PARTICIPATION_LIMIT = "participation_limit"
    INSUFFICIENT_BUYING_POWER = "insufficient_buying_power"
    SHORT_NOT_SUPPORTED = "short_not_supported"
    FRACTIONAL_NOT_SUPPORTED = "fractional_not_supported"
    UNSIGNED_STRATEGY = "unsigned_strategy"
    OPERATING_STATE_FORBIDS = "operating_state_forbids"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


ORDER_INTENT = register(
    ContractSpec(
        name="execution.order_intent",
        version=1,
        maturity=Maturity.FROZEN,
        doc="What a strategy asked for, before risk saw it (§16).",
        time_group=TimeGroup.CORE,
        fields=(
            *_CORE,
            FieldSpec(
                "client_order_id",
                FieldKind.TEXT,
                doc="Derived deterministically from (strategy_version, "
                "instrument_id, decision_time, intent_hash), so a retry "
                "regenerates the same id rather than a second live order (§30).",
            ),
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="Target instrument."),
            FieldSpec("side", FieldKind.CODE, codeset="side_v1", doc="Buy or sell."),
            FieldSpec("quantity_shares", FieldKind.SHARES, unit="share", doc="Whole shares."),
            FieldSpec(
                "limit_price_nano",
                FieldKind.NANO_DOLLARS,
                nullable=True,
                unit="nanodollar",
                doc="Limit price, or null for a market order.",
            ),
            FieldSpec("order_type", FieldKind.CODE, codeset="order_type_v1", doc="Order type."),
            FieldSpec("time_in_force", FieldKind.CODE, codeset="tif_v1", doc="Time in force."),
            FieldSpec(
                "decision_time",
                FieldKind.TIMESTAMP_NS,
                unit="ns_utc",
                doc="When the strategy clock fired. The submission key is this "
                "plus decision latency, and no fill may use an event at or "
                "before it (§16).",
            ),
            FieldSpec("strategy_version", FieldKind.TEXT, doc="Signed strategy version."),
            FieldSpec("risk_policy_version", FieldKind.TEXT, doc="Signed risk policy version."),
        ),
    )
)

ORDER_EVENT = register(
    ContractSpec(
        name="execution.order_event",
        version=1,
        maturity=Maturity.FROZEN,
        doc="Append-only order lifecycle log for a simulated run (§9, §30).",
        time_group=TimeGroup.CORE,
        fields=(
            *_CORE,
            FieldSpec("client_order_id", FieldKind.TEXT, doc="Idempotency key."),
            FieldSpec(
                "broker_order_id",
                FieldKind.TEXT,
                nullable=True,
                doc="Broker's identifier, once acknowledged.",
            ),
            FieldSpec(
                "broker_exec_id",
                FieldKind.TEXT,
                nullable=True,
                doc="Execution identifier for a fill. Part of the uniqueness key: "
                "without it two partial fills sharing a timestamp collide, which "
                "is divergence 1 from §9.",
            ),
            FieldSpec("event_type", FieldKind.CODE, codeset="order_event_v1", doc="Event type."),
            FieldSpec("state", FieldKind.CODE, codeset="order_state_v1", doc="Resulting state."),
            FieldSpec(
                "risk_reason",
                FieldKind.CODE,
                codeset="risk_reason_v1",
                doc="Reason-coded risk decision, persisted before any broker call (§25).",
            ),
            FieldSpec("strategy_version", FieldKind.TEXT, doc="Signed strategy version."),
            FieldSpec("risk_policy_version", FieldKind.TEXT, doc="Signed risk policy version."),
        ),
    )
)

FILL = register(
    ContractSpec(
        name="execution.fill",
        version=1,
        maturity=Maturity.FROZEN,
        doc="One execution. PnL reconciles from these and nothing else (§18).",
        time_group=TimeGroup.CORE,
        fields=(
            *_CORE,
            FieldSpec("client_order_id", FieldKind.TEXT, doc="Parent order."),
            FieldSpec("broker_exec_id", FieldKind.TEXT, doc="Execution identifier."),
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="Instrument."),
            FieldSpec("side", FieldKind.CODE, codeset="side_v1", doc="Buy or sell."),
            FieldSpec("quantity_shares", FieldKind.SHARES, unit="share", doc="Filled quantity."),
            FieldSpec("price_nano", FieldKind.NANO_DOLLARS, unit="nanodollar", doc="Fill price."),
            FieldSpec(
                "commission_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Broker commission. Each cost is a separate column, never "
                "one blended number, so §17's decomposition is recoverable.",
            ),
            FieldSpec(
                "regulatory_fees_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Regulatory and exchange fees, rounded against us.",
            ),
            FieldSpec(
                "arrival_price_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Reference price at submission, for implementation shortfall (§22).",
            ),
        ),
    )
)

POSITION = register(
    ContractSpec(
        name="execution.position",
        version=1,
        maturity=Maturity.FROZEN,
        doc="Position as of an instant. Always equals the signed sum of fills (§40).",
        time_group=TimeGroup.CORE,
        fields=(
            *_CORE,
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="Instrument."),
            FieldSpec(
                "quantity_shares",
                FieldKind.SHARES,
                unit="share",
                doc="Signed. Negative is short, which v1 research does not produce (D14).",
            ),
            FieldSpec(
                "average_cost_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Average entry cost per share.",
            ),
            FieldSpec(
                "mark_price_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Causal mark: the last price knowable at this row's "
                "knowledge_time, never a later one.",
            ),
            FieldSpec(
                "realized_pnl_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Realized PnL. Marked separately from unrealized (§18).",
            ),
            FieldSpec(
                "unrealized_pnl_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Unrealized PnL at the causal mark.",
            ),
        ),
    )
)

ACCOUNT_STATE = register(
    ContractSpec(
        name="execution.account_state",
        version=1,
        maturity=Maturity.FROZEN,
        doc="Account as of an instant. The broker is authoritative for these (§30).",
        time_group=TimeGroup.CORE,
        fields=(
            *_CORE,
            FieldSpec("account_id", FieldKind.TEXT, doc="Account. Paper and live never share one."),
            FieldSpec("cash_nano", FieldKind.NANO_DOLLARS, unit="nanodollar", doc="Settled cash."),
            FieldSpec(
                "equity_nano", FieldKind.NANO_DOLLARS, unit="nanodollar", doc="Total equity."
            ),
            FieldSpec(
                "buying_power_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="As reported by the broker. Never computed locally: §30 makes "
                "the broker authoritative, and the intraday margin regime in "
                "force is discovered at startup rather than assumed.",
            ),
            FieldSpec(
                "gross_exposure_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Sum of absolute position notionals.",
            ),
            FieldSpec(
                "net_exposure_nano",
                FieldKind.NANO_DOLLARS,
                unit="nanodollar",
                doc="Signed sum of position notionals.",
            ),
            FieldSpec(
                "operating_state",
                FieldKind.CODE,
                codeset="operating_state_v1",
                doc="Which §5 state produced this row, so a paper row can never "
                "be mistaken for a live one.",
            ),
        ),
    )
)
