"""Normalization is a pure function of the raw bytes and the declared context."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from tools.golden_fixture import CONTEXT, FIXTURE_DIR

from trading.market_data.alpaca_raw import (
    RawRecordError,
    parse_quote,
    parse_trade,
    partition_files,
    read_ndjson,
)
from trading.market_data.normalize import normalize_trades
from trading.market_data.reference import load
from trading.schemas.ordering import MISSING_SEQUENCE, SourceRank

pytestmark = pytest.mark.unit

REFERENCE = load(FIXTURE_DIR / "reference.json")

TRADE = {
    "T": "t",
    "S": "ZZTEST",
    "t": "2026-09-18T13:30:00.123456789Z",
    "p": Decimal("50.03"),
    "s": 100,
    "x": "V",
    "c": ["@"],
    "i": "tr-1",
    "z": "C",
    "q": 7,
}


class TestPriceParsing:
    def test_decimals_are_preserved_exactly(self) -> None:
        assert parse_trade(TRADE).price == Decimal("50.03")

    def test_a_float_price_is_refused(self) -> None:
        """json.loads without parse_float=Decimal turns 50.03 into not-50.03."""
        with pytest.raises(RawRecordError, match="parse_float=Decimal"):
            parse_trade({**TRADE, "p": 50.03})

    def test_reading_ndjson_yields_decimals(self, tmp_path: Path) -> None:
        path = tmp_path / "0000.ndjson"
        path.write_text('{"p": 50.03}\n')
        assert next(read_ndjson(path))["p"] == Decimal("50.03")

    def test_a_float_parse_would_not_be_representable(self) -> None:
        """Why it matters: the float is not a whole number of nano-dollars."""
        from trading.schemas.money import dollars

        # Built through a variable: ruff rejects a Decimal(float) literal in
        # source, which is the right default. Demonstrating why it is the right
        # default needs the value the rule forbids writing.
        as_float = float("50.03")
        assert Decimal(as_float) != Decimal("50.03")
        with pytest.raises(ValueError, match="sub-nano-dollar"):
            dollars(Decimal(as_float))


class TestTimestampParsing:
    def test_nanoseconds_survive(self) -> None:
        assert parse_trade(TRADE).event_time % 1_000_000 == 123_456_789 % 1_000_000

    def test_the_full_nanosecond_value_is_kept(self) -> None:
        assert parse_trade(TRADE).event_time % 1_000_000_000 == 123_456_789


class TestMissingFields:
    @pytest.mark.parametrize("field", ["S", "t", "p", "s", "x", "i"])
    def test_a_missing_required_field_raises(self, field: str) -> None:
        """A record that cannot be mapped is rejected, never defaulted."""
        record = {k: v for k, v in TRADE.items() if k != field}
        with pytest.raises(RawRecordError, match=field):
            parse_trade(record)

    def test_a_missing_sequence_becomes_the_sentinel(self) -> None:
        """A feed that publishes no sequence sorts first, deterministically."""
        record = {k: v for k, v in TRADE.items() if k != "q"}
        assert parse_trade(record).vendor_sequence == MISSING_SEQUENCE

    def test_quotes_require_both_sides(self) -> None:
        with pytest.raises(RawRecordError, match="bp"):
            parse_quote({"S": "Z", "t": TRADE["t"], "ap": Decimal("1"), "as": 1, "bs": 1})


class TestDeterminism:
    def test_normalizing_twice_gives_identical_rows(self) -> None:
        raws = [parse_trade(TRADE), parse_trade({**TRADE, "i": "tr-2", "q": 8})]
        assert normalize_trades(raws, REFERENCE, CONTEXT) == normalize_trades(
            raws, REFERENCE, CONTEXT
        )

    def test_rows_come_out_in_ordering_key_order(self) -> None:
        """Input order does not decide output order; the §16 key does."""
        later = parse_trade({**TRADE, "t": "2026-09-18T13:30:01.000000000Z", "q": 9})
        earlier = parse_trade(TRADE)
        forward = normalize_trades([earlier, later], REFERENCE, CONTEXT)
        reverse = normalize_trades([later, earlier], REFERENCE, CONTEXT)
        assert [r["event_time"] for r in forward] == sorted(r["event_time"] for r in forward)
        assert [r["event_time"] for r in reverse] == [r["event_time"] for r in forward]

    def test_same_nanosecond_prints_are_separated_by_sequence(self) -> None:
        a = parse_trade({**TRADE, "i": "a", "q": 1})
        b = parse_trade({**TRADE, "i": "b", "q": 2})
        rows = normalize_trades([b, a], REFERENCE, CONTEXT)
        assert [row["trade_id"] for row in rows] == ["a", "b"]

    def test_trades_carry_the_trade_source_rank(self) -> None:
        (row,) = normalize_trades([parse_trade(TRADE)], REFERENCE, CONTEXT)
        assert row["source_rank"] == int(SourceRank.TRADE)

    def test_provenance_is_stamped_on_every_row(self) -> None:
        (row,) = normalize_trades([parse_trade(TRADE)], REFERENCE, CONTEXT)
        assert row["raw_partition_id"] == CONTEXT.raw_partition_id
        assert row["event_time_source"] == CONTEXT.event_time_source


class TestPartitionOrder:
    def test_files_are_returned_lexicographically(self, tmp_path: Path) -> None:
        for name in ("0002.ndjson", "0000.ndjson", "0001.ndjson"):
            (tmp_path / name).write_text("{}\n")
        assert [p.name for p in partition_files(tmp_path)] == [
            "0000.ndjson",
            "0001.ndjson",
            "0002.ndjson",
        ]

    def test_an_empty_partition_raises(self, tmp_path: Path) -> None:
        with pytest.raises(RawRecordError, match=r"no \.ndjson"):
            partition_files(tmp_path)

    def test_file_order_is_independent_of_mtime(self, tmp_path: Path) -> None:
        """Ordering must follow the names, not when the files happened to land."""
        import os

        (tmp_path / "0000.ndjson").write_text("{}\n")
        (tmp_path / "0001.ndjson").write_text("{}\n")
        os.utime(tmp_path / "0000.ndjson", (10**9, 10**9))
        assert [p.name for p in partition_files(tmp_path)] == ["0000.ndjson", "0001.ndjson"]


def test_the_fixture_parses_end_to_end() -> None:
    records = list(read_ndjson(FIXTURE_DIR / "raw" / "trades" / "0000.ndjson"))
    assert len(records) == 1001
    parsed = [parse_trade(r) for r in records]
    assert all(isinstance(p.price, Decimal) for p in parsed)


def test_the_fixture_is_valid_ndjson() -> None:
    for dataset in ("trades", "quotes"):
        path = FIXTURE_DIR / "raw" / dataset / "0000.ndjson"
        for line in path.read_text().splitlines():
            json.loads(line)
