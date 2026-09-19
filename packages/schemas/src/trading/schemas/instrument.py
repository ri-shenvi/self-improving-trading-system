"""Instrument identity, and the ticker history that resolves a symbol to it (D6).

§7 says "Never join solely on ticker", and §41 lists survivorship as its own
failure mode. The two are the same problem: tickers are reassigned and reused, so
a join on a symbol silently splices two companies' histories together and
produces a backtest that looks entirely reasonable.

Every row in the system therefore carries an :data:`InstrumentId` — a permanent
surrogate that is never reused and never derived from a symbol. A ticker is
resolved to one only through :func:`resolve_ticker`, and only as of a stated
instant.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from trading.schemas.identifiers import InstrumentId
from trading.schemas.registry import register
from trading.schemas.spec import (
    ContractSpec,
    FieldKind,
    FieldSpec,
    Maturity,
    TimeGroup,
    time_fields,
)
from trading.schemas.time import TimestampNs

INSTRUMENT = register(
    ContractSpec(
        name="reference.instrument",
        version=1,
        maturity=Maturity.FROZEN,
        doc="The instrument master: one row per tradable instrument, ever.",
        time_group=TimeGroup.EFFECTIVE,
        fields=(
            *time_fields(TimeGroup.EFFECTIVE),
            FieldSpec(
                "instrument_id",
                FieldKind.INSTRUMENT_ID,
                doc="Permanent surrogate. Never reused, never derived from a ticker.",
            ),
            FieldSpec(
                "primary_exchange",
                FieldKind.EXCHANGE_CODE,
                codeset="exchange_v1",
                doc="Listing venue (§7).",
            ),
            FieldSpec(
                "security_type",
                FieldKind.EXCHANGE_CODE,
                codeset="security_type_v1",
                doc="Common stock, ETF, and so on (§7). v1 trades only the first two.",
            ),
            FieldSpec(
                "lot_size",
                FieldKind.COUNT,
                doc="Round lot size (§7). Order sizing and odd-lot handling depend on it.",
            ),
            FieldSpec(
                "is_tradable",
                FieldKind.BOOL,
                doc="Whether the instrument may be traded as of this record's "
                "effective_time. Delisting sets it false rather than deleting "
                "the row, which would be survivorship bias by omission.",
            ),
        ),
    )
)

TICKER_HISTORY = register(
    ContractSpec(
        name="reference.ticker_history",
        version=1,
        maturity=Maturity.FROZEN,
        doc="Which ticker an instrument carried, over which interval (§7).",
        time_group=TimeGroup.EFFECTIVE,
        fields=(
            *time_fields(TimeGroup.EFFECTIVE),
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="The instrument."),
            FieldSpec("ticker", FieldKind.TEXT, doc="The symbol, as displayed."),
            FieldSpec(
                "end_time",
                FieldKind.TIMESTAMP_NS,
                nullable=True,
                unit="ns_utc",
                doc="Exclusive end of the assignment, or null while it still "
                "holds. Half-open intervals so a reassignment on the same day "
                "has no ambiguous instant.",
            ),
        ),
    )
)


@dataclass(frozen=True, slots=True)
class TickerAssignment:
    """One interval during which an instrument carried a ticker.

    Half-open, ``[effective_time, end_time)``: a ticker reassigned at an instant
    belongs to exactly one instrument at that instant.
    """

    instrument_id: InstrumentId
    ticker: str
    effective_time: TimestampNs
    end_time: TimestampNs | None = None

    def covers(self, at: TimestampNs) -> bool:
        if at < self.effective_time:
            return False
        return self.end_time is None or at < self.end_time


class TickerResolutionError(LookupError):
    """A ticker could not be resolved to exactly one instrument at an instant."""


def resolve_ticker(
    assignments: Iterable[TickerAssignment], ticker: str, at: TimestampNs
) -> InstrumentId:
    """Resolve a ticker to the instrument that held it at ``at``.

    Args:
        assignments: Known ticker assignments. Need not be sorted.
        ticker: The symbol, matched exactly.
        at: The instant to resolve as of — a decision time, never "now".

    Raises:
        TickerResolutionError: If no instrument held the ticker then, or if more
            than one did. Both are data defects, and neither may be papered over
            by picking one: a silent choice here is how two companies' histories
            get spliced.
    """
    matches = {a.instrument_id for a in assignments if a.ticker == ticker and a.covers(at)}
    if not matches:
        raise TickerResolutionError(
            f"no instrument held {ticker!r} at {at}. Resolving against the "
            "current instrument master instead would be survivorship bias."
        )
    if len(matches) > 1:
        raise TickerResolutionError(
            f"{ticker!r} resolves to {len(matches)} instruments at {at}: "
            f"{sorted(matches)}. Overlapping assignments are a data defect."
        )
    return matches.pop()
