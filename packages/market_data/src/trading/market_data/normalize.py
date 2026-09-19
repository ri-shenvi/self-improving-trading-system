"""Raw vendor records to normalized contract tables.

Three properties this module exists to guarantee, each of which would be easy to
lose and hard to notice:

**Nanosecond ordering is preserved end to end.** Vendor timestamps are parsed
straight to int64 nanoseconds and never pass through a datetime. Ordering keys
are built per §16 and the rows are emitted sorted by them, so the writer's
strictly-increasing check passes for the right reason rather than by accident.

**Output is a pure function of input.** ``process_time`` and ``receive_time``
are *parameters*, not clock reads. A normalizer that stamped wall-clock times
would produce different bytes on every run, which would make the golden fixture
worthless and the snapshot id unstable. Production passes real observed times;
tests pass fixed ones. Injecting the clock is what makes "same bytes in, same
bytes out" checkable.

**knowledge_time is derived, never copied.** For backfilled data, ``receive_time``
is when *we* fetched the bytes — possibly years after the event — so it cannot
stand in for knowledge. The value is ``event_time`` plus a declared publication
lag, exactly as ``docs/vendor-timestamp-mapping.md`` specifies, and the writer
verifies the rows match the policy that was declared.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pyarrow as pa

from trading.market_data.alpaca_raw import (
    RawQuote,
    RawTrade,
    parse_quote,
    parse_trade,
    partition_files,
    read_ndjson,
)
from trading.market_data.reference import ReferenceData
from trading.schemas.identifiers import InstrumentId
from trading.schemas.instrument import resolve_ticker
from trading.schemas.io import KnowledgeTimePolicy, WriteReceipt, write_contract_table
from trading.schemas.money import dollars
from trading.schemas.ordering import MISSING_SEQUENCE, SourceRank, assign_ingest_index
from trading.schemas.registry import get
from trading.schemas.time import TimestampNs

TRADE_CONTRACT: Final = get("normalized.trade")
QUOTE_CONTRACT: Final = get("normalized.quote")


@dataclass(frozen=True, slots=True)
class NormalizationContext:
    """Everything a normalization run needs that is not in the raw bytes.

    Every field is explicit so the run is reproducible. Nothing here is read
    from a clock or an environment variable.

    Args:
        receive_time: When the gateway received these bytes. For a backfill this
            is the fetch time, which is why it cannot be ``knowledge_time``.
        process_time: When normalization completed (§6).
        publication_lag_ns: Delay between a venue publishing an event and the
            system being able to know it. Measured from live capture, versioned,
            and recorded in the snapshot. Until a real measurement exists this is
            a declared conservative constant, and a result that depends on its
            value has not been validated.
        raw_partition_id: Provenance stamped on every row.
        event_time_source: Which vendor timestamp ``event_time`` came from.
            ``vendor_unknown`` is honest and blocks promotion (D1).
        venue_coverage: ``sip`` or ``iex_only`` (D11). An IEX quote is not the
            NBBO, and the quote-replay fill model refuses to run on one.
        knowledge_policy: How ``knowledge_time`` is derived. The writer checks
            the rows actually match it.
    """

    receive_time: TimestampNs
    process_time: TimestampNs
    publication_lag_ns: int
    raw_partition_id: str
    event_time_source: str
    venue_coverage: str
    knowledge_policy: KnowledgeTimePolicy = KnowledgeTimePolicy.BACKFILL

    def knowledge_time(self, event_time: TimestampNs) -> TimestampNs:
        """Earliest instant the system could have known an event (§6)."""
        if self.knowledge_policy is KnowledgeTimePolicy.LIVE_CAPTURE:
            return self.receive_time
        return TimestampNs(int(event_time) + self.publication_lag_ns)


def _resolve(reference: ReferenceData, symbol: str, at: TimestampNs) -> InstrumentId:
    """Resolve a vendor symbol to an instrument, as of the event (D6)."""
    return resolve_ticker(reference.ticker_history, symbol, at)


def _ordering_columns(
    *, rank: SourceRank, vendor_sequence: int, position: int, context: NormalizationContext
) -> dict[str, Any]:
    return {
        "source_rank": int(rank),
        "vendor_sequence": vendor_sequence,
        # No venue sequence in Alpaca's payload; sorts first, deterministically.
        "venue_sequence": MISSING_SEQUENCE,
        "ingest_index": assign_ingest_index(position),
        "raw_partition_id": context.raw_partition_id,
        "event_time_source": context.event_time_source,
    }


def _time_columns(event_time: TimestampNs, context: NormalizationContext) -> dict[str, Any]:
    return {
        "event_time": int(event_time),
        "receive_time": int(context.receive_time),
        "process_time": int(context.process_time),
        "knowledge_time": int(context.knowledge_time(event_time)),
        "revision_time": None,
    }


def normalize_trades(
    raws: Sequence[RawTrade], reference: ReferenceData, context: NormalizationContext
) -> list[dict[str, Any]]:
    """Map raw trades onto normalized rows, sorted into §16 order."""
    rows = [
        {
            **_time_columns(raw.event_time, context),
            **_ordering_columns(
                rank=SourceRank.TRADE,
                vendor_sequence=raw.vendor_sequence,
                position=position,
                context=context,
            ),
            "instrument_id": int(_resolve(reference, raw.symbol, raw.event_time)),
            "price_nano": int(dollars(raw.price)),
            "size_shares": raw.size,
            "exchange": raw.exchange,
            "conditions": list(raw.conditions),
            "trade_id": raw.trade_id,
            "tape": raw.tape,
            "is_cancelled": False,
        }
        for position, raw in enumerate(raws)
    ]
    return _sorted_by_key(rows)


def normalize_quotes(
    raws: Sequence[RawQuote], reference: ReferenceData, context: NormalizationContext
) -> list[dict[str, Any]]:
    """Map raw quotes onto normalized rows, sorted into §16 order."""
    rows = [
        {
            **_time_columns(raw.event_time, context),
            **_ordering_columns(
                rank=SourceRank.QUOTE,
                vendor_sequence=raw.vendor_sequence,
                position=position,
                context=context,
            ),
            "instrument_id": int(_resolve(reference, raw.symbol, raw.event_time)),
            "bid_price_nano": int(dollars(raw.bid_price)),
            "bid_size_shares": raw.bid_size,
            "bid_exchange": raw.bid_exchange,
            "ask_price_nano": int(dollars(raw.ask_price)),
            "ask_size_shares": raw.ask_size,
            "ask_exchange": raw.ask_exchange,
            "conditions": list(raw.conditions),
            "tape": raw.tape,
            "venue_coverage": context.venue_coverage,
        }
        for position, raw in enumerate(raws)
    ]
    return _sorted_by_key(rows)


def _sorted_by_key(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort rows into the §16 total order.

    The key is lexicographic over the five ordering columns, matching
    :class:`trading.schemas.ordering.OrderingKey`. Sorting here rather than
    trusting the vendor's order is what lets the writer's strictly-increasing
    check pass for the right reason.
    """
    return sorted(
        rows,
        key=lambda row: (
            row["event_time"],
            row["source_rank"],
            row["vendor_sequence"],
            row["venue_sequence"],
            row["ingest_index"],
        ),
    )


def to_table(rows: Iterable[dict[str, Any]], contract_name: str) -> pa.Table:
    """Build an Arrow table in the contract's exact schema."""
    contract = get(contract_name)
    materialized = list(rows)
    columns = {name: [row[name] for row in materialized] for name in contract.field_names()}
    return pa.table(columns, schema=contract.arrow_schema())


def normalize_partition(
    raw_root: Path,
    reference: ReferenceData,
    context: NormalizationContext,
    output_root: Path,
) -> tuple[WriteReceipt, ...]:
    """Normalize one raw partition into contract tables and write them.

    Returns:
        A receipt per written file, which is exactly what the snapshot manifest
        builder consumes -- so the manifest never re-hashes files behind the
        writer's back.
    """
    trades = [
        parse_trade(record)
        for path in partition_files(raw_root / "trades")
        for record in read_ndjson(path)
    ]
    quotes = [
        parse_quote(record)
        for path in partition_files(raw_root / "quotes")
        for record in read_ndjson(path)
    ]

    receipts = []
    for contract_name, rows in (
        ("normalized.trade", normalize_trades(trades, reference, context)),
        ("normalized.quote", normalize_quotes(quotes, reference, context)),
    ):
        dataset = contract_name.split(".", 1)[1]
        destination = (
            output_root
            / "normalized"
            / dataset
            / f"date={reference.session.session_date}"
            / "part-000.parquet"
        )
        receipts.append(
            write_contract_table(
                to_table(rows, contract_name),
                get(contract_name),
                destination,
                knowledge_policy=context.knowledge_policy,
            )
        )
    return tuple(receipts)
