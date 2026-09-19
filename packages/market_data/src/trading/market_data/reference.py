"""Loading the reference data a normalizer needs: instruments and the calendar."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trading.schemas.identifiers import InstrumentId
from trading.schemas.instrument import TickerAssignment
from trading.schemas.time import TimestampNs, parse_rfc3339_ns


@dataclass(frozen=True, slots=True)
class Session:
    """One trading session (§7 Calendar). The exchange calendar is authoritative."""

    session_date: str
    is_trading_day: bool
    regular_open_ns: TimestampNs
    regular_close_ns: TimestampNs
    is_early_close: bool

    def contains(self, at: TimestampNs) -> bool:
        """Whether an instant falls inside the regular session, half-open."""
        return self.regular_open_ns <= at < self.regular_close_ns


@dataclass(frozen=True, slots=True)
class ReferenceData:
    """Everything a normalizer must resolve against, as of one snapshot."""

    instrument_id: InstrumentId
    primary_exchange: str
    security_type: str
    lot_size: int
    ticker_history: tuple[TickerAssignment, ...]
    session: Session


def load(path: Path) -> ReferenceData:
    """Read the reference bundle that accompanies a raw partition."""
    body: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    instrument = body["instrument"]
    calendar = body["calendar"]

    return ReferenceData(
        instrument_id=InstrumentId(int(instrument["instrument_id"])),
        primary_exchange=str(instrument["primary_exchange"]),
        security_type=str(instrument["security_type"]),
        lot_size=int(instrument["lot_size"]),
        ticker_history=tuple(
            TickerAssignment(
                instrument_id=InstrumentId(int(row["instrument_id"])),
                ticker=str(row["ticker"]),
                effective_time=parse_rfc3339_ns(str(row["effective_time"])),
                end_time=(parse_rfc3339_ns(str(row["end_time"])) if row.get("end_time") else None),
            )
            for row in body["ticker_history"]
        ),
        session=Session(
            session_date=str(calendar["session_date"]),
            is_trading_day=bool(calendar["is_trading_day"]),
            regular_open_ns=TimestampNs(int(calendar["regular_open_ns"])),
            regular_close_ns=TimestampNs(int(calendar["regular_close_ns"])),
            is_early_close=bool(calendar["is_early_close"]),
        ),
    )
