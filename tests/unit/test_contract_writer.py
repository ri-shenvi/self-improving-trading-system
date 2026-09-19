"""The writer rejects what Arrow cannot see (M1 exit test 3).

A verified probe underlies this whole module: a non-nullable Arrow field accepts
a null in memory and `Table.validate(full=True)` passes. Arrow objects only at
the parquet boundary, and only about nulls -- never about a `knowledge_time` that
is present and wrong. Each rejection below covers a case the schema alone misses.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from trading.schemas.io import (
    ContractWriteError,
    KnowledgeTimePolicy,
    WriteReceipt,
    content_sha256,
    read_contract_table,
    write_contract_table,
)
from trading.schemas.registry import get
from trading.schemas.spec import ContractSpec
from trading.schemas.time import parse_rfc3339_ns

pytestmark = pytest.mark.unit

SPEC = get("normalized.trade")

EVENT = parse_rfc3339_ns("2026-09-19T13:30:00.000000000Z")
RECEIVE = parse_rfc3339_ns("2026-09-19T13:30:00.000250000Z")
PROCESS = parse_rfc3339_ns("2026-09-19T13:30:00.001000000Z")


def row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "event_time": EVENT,
        "receive_time": RECEIVE,
        "process_time": PROCESS,
        "knowledge_time": RECEIVE,
        "revision_time": None,
        "source_rank": 5,
        "vendor_sequence": 1,
        "venue_sequence": 1,
        "ingest_index": 0,
        "raw_partition_id": "alpaca/trades/2026-09-19/000",
        "event_time_source": "sip",
        "instrument_id": 1,
        "price_nano": 100_000_000_000,
        "size_shares": 100,
        "exchange": "XNAS",
        "conditions": ["@"],
        "trade_id": "t-1",
        "tape": "C",
        "is_cancelled": False,
    }
    return base | overrides


def table(*rows: dict[str, object], spec: ContractSpec = SPEC) -> pa.Table:
    columns = {name: [r[name] for r in rows] for name in spec.field_names()}
    return pa.table(columns, schema=spec.arrow_schema())


def write(
    tmp_path: Path, *rows: dict[str, object], policy: KnowledgeTimePolicy | None = None
) -> WriteReceipt:
    return write_contract_table(
        table(*rows),
        SPEC,
        tmp_path / "trades.parquet",
        knowledge_policy=policy or KnowledgeTimePolicy.LIVE_CAPTURE,
    )


class TestHappyPath:
    def test_writes_and_reports(self, tmp_path: Path) -> None:
        receipt = write(tmp_path, row())
        assert receipt.row_count == 1
        assert receipt.contract == "normalized.trade"
        assert receipt.schema_hash == SPEC.content_hash()
        assert receipt.path.is_file()

    def test_round_trips(self, tmp_path: Path) -> None:
        write(tmp_path, row())
        restored = read_contract_table(tmp_path / "trades.parquet", SPEC)
        assert restored.column("price_nano").to_pylist() == [100_000_000_000]


class TestKnowledgeTime:
    """D4, four ways -- only the first is catchable by Arrow alone."""

    def test_null_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ContractWriteError, match="null knowledge_time"):
            write(tmp_path, row(knowledge_time=None))

    def test_epoch_zero_is_rejected(self, tmp_path: Path) -> None:
        """Present but wrong: it passes every null check."""
        with pytest.raises(ContractWriteError, match="outside the plausible band"):
            write(tmp_path, row(knowledge_time=0, receive_time=0, process_time=0, event_time=0))

    def test_knowing_before_the_event_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ContractWriteError, match="precedes event_time"):
            write(tmp_path, row(knowledge_time=EVENT - 1))

    def test_policy_must_match_the_data(self, tmp_path: Path) -> None:
        """The check that turns presence into correctness."""
        with pytest.raises(ContractWriteError, match="policy is live_capture"):
            write(tmp_path, row(knowledge_time=PROCESS))

    def test_backfill_policy_permits_a_lagged_value(self, tmp_path: Path) -> None:
        receipt = write(
            tmp_path,
            row(knowledge_time=EVENT + 5_000_000),
            policy=KnowledgeTimePolicy.BACKFILL,
        )
        assert receipt.knowledge_policy is KnowledgeTimePolicy.BACKFILL


class TestOtherTimestamps:
    def test_receive_before_event_is_rejected(self, tmp_path: Path) -> None:
        # Backfill policy, so knowledge_time is not pinned to receive_time and
        # the receive/event check is what fires rather than the knowledge check.
        with pytest.raises(ContractWriteError, match=r"receive_time=.* precedes event_time"):
            write(
                tmp_path,
                row(receive_time=EVENT - 1, process_time=EVENT, knowledge_time=EVENT + 1),
                policy=KnowledgeTimePolicy.BACKFILL,
            )

    def test_process_before_receive_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ContractWriteError, match="process_time"):
            write(tmp_path, row(process_time=EVENT))


class TestSchemaIdentity:
    def test_wrong_column_order_is_rejected(self, tmp_path: Path) -> None:
        """Column order decides the file bytes, so it is part of the contract."""
        names = list(reversed(SPEC.field_names()))
        data = row()
        reordered = pa.table({name: [data[name]] for name in names})
        with pytest.raises(ContractWriteError, match="column names or order"):
            write_contract_table(
                reordered,
                SPEC,
                tmp_path / "x.parquet",
                knowledge_policy=KnowledgeTimePolicy.LIVE_CAPTURE,
            )

    def test_no_implicit_casting(self, tmp_path: Path) -> None:
        data = row()
        wrong = pa.table(
            {name: [data[name]] for name in SPEC.field_names()},
            schema=SPEC.arrow_schema().set(
                SPEC.arrow_schema().get_field_index("size_shares"),
                pa.field("size_shares", pa.int32()),
            ),
        )
        with pytest.raises(ContractWriteError, match="does not match the contract"):
            write_contract_table(
                wrong,
                SPEC,
                tmp_path / "x.parquet",
                knowledge_policy=KnowledgeTimePolicy.LIVE_CAPTURE,
            )


class TestOrdering:
    def test_duplicate_keys_are_rejected(self, tmp_path: Path) -> None:
        """A duplicate key means the stream is not a total order."""
        with pytest.raises(ContractWriteError, match="not strictly increasing"):
            write(tmp_path, row(), row())

    def test_unsorted_rows_are_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ContractWriteError, match="not strictly increasing"):
            write(tmp_path, row(ingest_index=1), row(ingest_index=0))

    def test_sorted_rows_are_accepted(self, tmp_path: Path) -> None:
        assert write(tmp_path, row(ingest_index=0), row(ingest_index=1)).row_count == 2


class TestMoney:
    def test_beyond_the_storable_range_is_rejected(self, tmp_path: Path) -> None:
        """int64 wraps silently, so this is caught before it can become a report."""
        with pytest.raises(ContractWriteError, match="storable nano-dollar range"):
            write(tmp_path, row(price_nano=2**62 + 1))


class TestHashes:
    def test_content_hash_is_independent_of_chunking(self) -> None:
        one = table(row(ingest_index=0), row(ingest_index=1))
        chunked = pa.concat_tables([table(row(ingest_index=0)), table(row(ingest_index=1))])
        assert content_sha256(one) == content_sha256(chunked)

    def test_content_hash_changes_with_the_data(self) -> None:
        assert content_sha256(table(row())) != content_sha256(table(row(price_nano=1)))

    def test_both_hashes_are_recorded(self, tmp_path: Path) -> None:
        """file_sha256 detects corruption; content_sha256 survives a pyarrow bump."""
        receipt = write(tmp_path, row())
        assert len(receipt.file_sha256) == 64
        assert len(receipt.content_sha256) == 64
        assert receipt.file_sha256 != receipt.content_sha256

    def test_repeated_writes_are_byte_identical(self, tmp_path: Path) -> None:
        first = write(tmp_path / "a", row())
        second = write(tmp_path / "b", row())
        assert first.file_sha256 == second.file_sha256
