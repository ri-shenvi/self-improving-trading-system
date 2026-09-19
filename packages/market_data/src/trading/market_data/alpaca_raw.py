"""Parsing Alpaca's raw wire records, losslessly.

The fixture and the eventual connector both produce records in this shape, so
the mapping from vendor fields to our contracts lives in exactly one place. The
authoritative description of what each field means is
``docs/vendor-timestamp-mapping.md``; this module implements it.

Two decisions that are easy to get wrong and expensive to discover later:

**Prices are parsed as decimals, never floats.** Alpaca sends JSON numbers, and
``json.loads`` turns ``50.03`` into a binary float that is not $50.03 —
``Decimal(float)`` of it is 50.030000000000001136... Parsing with
``parse_float=Decimal`` keeps the exact decimal the vendor wrote. The money layer
catches the mistake if it is ever made (``dollars()`` rejects sub-nano
precision), but catching it at the boundary is better than catching it at the
first write.

**Timestamps keep their nanoseconds.** Alpaca publishes nanosecond precision and
``datetime`` is microsecond, so parsing goes straight to int64 nanoseconds
(:func:`trading.schemas.time.parse_rfc3339_ns`) and never through a datetime.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from trading.schemas.ordering import MISSING_SEQUENCE
from trading.schemas.time import TimestampNs, parse_rfc3339_ns

#: Alpaca message-type discriminators.
TRADE: Final = "t"
QUOTE: Final = "q"


class RawRecordError(ValueError):
    """A raw record is malformed or missing a field the contract requires."""


@dataclass(frozen=True, slots=True)
class RawTrade:
    """One print, as the vendor sent it."""

    symbol: str
    event_time: TimestampNs
    price: Decimal
    size: int
    exchange: str
    conditions: tuple[str, ...]
    trade_id: str
    tape: str
    vendor_sequence: int


@dataclass(frozen=True, slots=True)
class RawQuote:
    """One bid/ask pair, as the vendor sent it."""

    symbol: str
    event_time: TimestampNs
    bid_price: Decimal
    bid_size: int
    bid_exchange: str
    ask_price: Decimal
    ask_size: int
    ask_exchange: str
    conditions: tuple[str, ...]
    tape: str
    vendor_sequence: int


def _require(record: dict[str, Any], key: str, kind: str) -> Any:
    if key not in record:
        raise RawRecordError(
            # default=str because prices are Decimals: without it the error
            # path raises TypeError on exactly the records it exists to describe.
            f"{kind} record is missing {key!r}: "
            f"{json.dumps(record, sort_keys=True, default=str)[:120]}. "
            "A record that cannot be mapped is rejected rather than defaulted -- "
            "an invented value is indistinguishable from a real one downstream."
        )
    return record[key]


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    raise RawRecordError(
        f"{field}={value!r} was parsed as {type(value).__name__}, not Decimal. "
        "Parse the payload with json.loads(..., parse_float=Decimal): a binary "
        "float cannot represent a decimal price exactly."
    )


def parse_trade(record: dict[str, Any]) -> RawTrade:
    """Map one Alpaca trade record onto :class:`RawTrade`."""
    return RawTrade(
        symbol=str(_require(record, "S", "trade")),
        event_time=parse_rfc3339_ns(str(_require(record, "t", "trade"))),
        price=_decimal(_require(record, "p", "trade"), "p"),
        size=int(_require(record, "s", "trade")),
        exchange=str(_require(record, "x", "trade")),
        conditions=tuple(str(c) for c in record.get("c", ())),
        trade_id=str(_require(record, "i", "trade")),
        tape=str(record.get("z", "")),
        # Absent on feeds that publish no sequence; the ordering key sorts a
        # missing sequence first rather than guessing a position.
        vendor_sequence=int(record.get("q", MISSING_SEQUENCE)),
    )


def parse_quote(record: dict[str, Any]) -> RawQuote:
    """Map one Alpaca quote record onto :class:`RawQuote`."""
    return RawQuote(
        symbol=str(_require(record, "S", "quote")),
        event_time=parse_rfc3339_ns(str(_require(record, "t", "quote"))),
        bid_price=_decimal(_require(record, "bp", "quote"), "bp"),
        bid_size=int(_require(record, "bs", "quote")),
        bid_exchange=str(record.get("bx", "")),
        ask_price=_decimal(_require(record, "ap", "quote"), "ap"),
        ask_size=int(_require(record, "as", "quote")),
        ask_exchange=str(record.get("ax", "")),
        conditions=tuple(str(c) for c in record.get("c", ())),
        tape=str(record.get("z", "")),
        vendor_sequence=int(record.get("q", MISSING_SEQUENCE)),
    )


def read_ndjson(path: Path) -> Iterator[dict[str, Any]]:
    """Yield raw records from a newline-delimited JSON partition, in file order.

    File order *is* the order: :func:`trading.schemas.ordering.assign_ingest_index`
    derives the ingest index from position, which is what makes re-ingesting the
    same bytes reproduce the same total order.
    """
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                # parse_float=Decimal: see the module docstring.
                record: dict[str, Any] = json.loads(line, parse_float=Decimal)
            except json.JSONDecodeError as exc:
                raise RawRecordError(f"{path}:{number}: {exc.msg}") from exc
            yield record


def partition_files(directory: Path) -> tuple[Path, ...]:
    """Return a partition's files in lexicographic order.

    Lexicographic order is the documented concatenation order when a session
    spans several files, which is why ordinals must be zero-padded: ``10`` sorts
    before ``9`` otherwise, silently reordering the stream.
    """
    files = sorted(directory.glob("*.ndjson"))
    if not files:
        raise RawRecordError(f"no .ndjson partition files in {directory}")
    return tuple(files)
