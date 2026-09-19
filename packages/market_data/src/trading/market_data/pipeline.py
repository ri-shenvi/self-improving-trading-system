"""Raw partition to sealed snapshot, in one reproducible call.

The seam M2 exists to prove: raw bytes in, a content-addressed snapshot out,
with the same bytes producing the same snapshot id every time. Everything that
would otherwise be ambient -- the clock, the publication lag, the feed's venue
coverage -- is a parameter, because a pipeline that reads a clock cannot be
checked against a golden fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trading.market_data.bars import ONE_MINUTE_NS, TradeInput, build_bars
from trading.market_data.normalize import (
    NormalizationContext,
    normalize_partition,
    to_table,
)
from trading.market_data.reference import load
from trading.market_data.snapshot.builder import build_manifest, write_manifest
from trading.schemas.documents import SnapshotManifest
from trading.schemas.io import WriteReceipt, read_contract_table, write_contract_table
from trading.schemas.registry import get
from trading.schemas.time import TimestampNs

BAR_CONTRACT = "normalized.bar"


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    """What a pipeline run produced."""

    manifest: SnapshotManifest
    receipts: tuple[WriteReceipt, ...]
    root: Path

    @property
    def snapshot_id(self) -> str:
        return self.manifest.snapshot_id()


def _bars_from(receipts: tuple[WriteReceipt, ...]) -> list[TradeInput]:
    """Read back the trades we just wrote, so bars derive from normalized data.

    Deliberately not built from the raw records in memory: bars must be a
    function of the normalized table that the snapshot actually contains, or a
    bar could describe prints that never made it to disk.
    """
    trade_receipt = next(r for r in receipts if r.contract == "normalized.trade")
    table = read_contract_table(trade_receipt.path, get("normalized.trade"))
    columns = table.to_pydict()
    return [
        TradeInput(
            event_time=TimestampNs(event_time),
            price_nano=price,
            size_shares=size,
            conditions=tuple(conditions or ()),
            instrument_id=instrument_id,
        )
        for event_time, price, size, conditions, instrument_id in zip(
            columns["event_time"],
            columns["price_nano"],
            columns["size_shares"],
            columns["conditions"],
            columns["instrument_id"],
            strict=True,
        )
    ]


def run(
    raw_root: Path,
    reference_path: Path,
    output_root: Path,
    context: NormalizationContext,
    *,
    as_of: TimestampNs,
    window_ns: int = ONE_MINUTE_NS,
    calendar_version: str = "",
) -> SnapshotResult:
    """Normalize a raw partition, build bars, and seal a snapshot.

    Args:
        as_of: The instant up to which data is known. Windows ending after it
            are marked incomplete rather than silently presented as closed.
    """
    reference = load(reference_path)
    receipts = list(normalize_partition(raw_root, reference, context, output_root))

    bar_rows = build_bars(
        _bars_from(tuple(receipts)),
        window_ns=window_ns,
        origin_ns=int(reference.session.regular_open_ns),
        as_of=as_of,
        raw_partition_id=context.raw_partition_id,
        event_time_source=context.event_time_source,
        receive_time=context.receive_time,
        process_time=context.process_time,
        knowledge_lag_ns=context.publication_lag_ns,
    )
    bar_path = (
        output_root
        / "normalized"
        / "bar"
        / f"date={reference.session.session_date}"
        / "part-000.parquet"
    )
    receipts.append(
        write_contract_table(
            to_table(bar_rows, BAR_CONTRACT),
            get(BAR_CONTRACT),
            bar_path,
            knowledge_policy=context.knowledge_policy,
        )
    )

    manifest = build_manifest(
        receipts,
        output_root,
        calendar_version=calendar_version,
    )
    write_manifest(manifest, output_root)
    return SnapshotResult(manifest=manifest, receipts=tuple(receipts), root=output_root)
