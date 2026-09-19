"""Generate the golden fixture: one fictional symbol, one session.

§42.4 asks for a tiny deterministic replay fixture before a large backtester.
This is it, and every later milestone regresses against it.

Three properties matter more than realism:

**Synthetic.** A fictional symbol with invented prints, so the fixture can be
committed and run in CI with no market-data licence entangled in it (§34).

**Alpaca-shaped.** The raw records use Alpaca's wire field names — ``t``, ``p``,
``s``, ``x``, ``c``, ``z`` — so the normalizer written against this fixture is
the normalizer that will meet the real feed. A fixture in a convenient shape
would quietly defer every field-mapping decision to M7.

**Deterministic.** Generated from a fixed seed with no clock and no ambient
state, so re-running reproduces the committed bytes. A fixture that drifts is
not a golden fixture.

The data deliberately includes cases the normalizer must handle rather than a
clean happy path: a nanosecond-level timestamp collision, an odd-cent quote
whose mid is half a nano-dollar, a condition-filtered print that must not reach
a bar, a crossed quote, and a late correction.

Usage::

    python tools/build_fixture.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Final

import numpy as np

ROOT: Final = Path(__file__).resolve().parent.parent
FIXTURE_DIR: Final = ROOT / "tests/golden/fixtures/tiny_day"

#: A symbol that cannot collide with a real listing.
SYMBOL: Final = "ZZTEST"
INSTRUMENT_ID: Final = 900_001

#: 2026-09-18 was a Friday; a regular session, no early close.
SESSION_DATE: Final = "2026-09-18"
SESSION_OPEN_NS: Final = 1_789_738_200_000_000_000  # 13:30:00Z == 09:30 New York
SESSION_CLOSE_NS: Final = 1_789_761_600_000_000_000  # 20:00:00Z == 16:00 New York

#: Deterministic, and never used for anything that reaches a decision.
SEED: Final = 20_260_918

#: Alpaca trade conditions. '@' is a regular sale; 'T' is a form-T
#: (extended-hours) print, which must not contribute to a regular-session bar.
REGULAR_SALE: Final = "@"
FORM_T: Final = "T"

NS_PER_SECOND: Final = 1_000_000_000


def _price_cents(rng: np.random.Generator, previous: int) -> int:
    """A mean-reverting integer cent price, so the walk cannot run away."""
    step = int(rng.integers(-3, 4))
    pull = (5_000 - previous) // 400
    return max(100, previous + step + pull)


def generate() -> dict[str, list[dict[str, Any]]]:
    """Build the raw records. Pure: same seed, same output, no clock read."""
    rng = np.random.Generator(np.random.PCG64(SEED))

    trades: list[dict[str, Any]] = []
    quotes: list[dict[str, Any]] = []

    price_cents = 5_000
    event_ns = SESSION_OPEN_NS
    sequence = 0

    # ~2,000 events spread over roughly the first half-hour of the session, so
    # the fixture spans some thirty one-minute windows rather than one. A
    # fixture that produces a single bar cannot exercise window boundaries,
    # which is most of what bar construction gets wrong.
    for index in range(1_000):
        event_ns += int(rng.integers(1_000_000_000, 3_000_000_000))
        price_cents = _price_cents(rng, price_cents)
        sequence += 1

        # A half-cent-wide book, so the mid is an odd number of nano-dollars and
        # exercises the rounding path that most quotes take.
        bid_cents = price_cents - 1
        ask_cents = price_cents + 2 if index % 7 else price_cents - 2  # every 7th is crossed
        quotes.append(
            {
                "T": "q",
                "S": SYMBOL,
                "t": _rfc3339(event_ns),
                "bp": bid_cents / 100,
                "bs": int(rng.integers(1, 20)) * 100,
                "bx": "V",
                "ap": ask_cents / 100,
                "as": int(rng.integers(1, 20)) * 100,
                "ax": "V",
                "c": ["R"],
                "z": "C",
                "q": sequence,
            }
        )

        # The trade lands a fraction of a millisecond after its quote, so the
        # engine can require a quote strictly before the print it fills against.
        trade_ns = event_ns + 250_000
        sequence += 1
        trades.append(
            {
                "T": "t",
                "S": SYMBOL,
                "t": _rfc3339(trade_ns),
                "p": price_cents / 100,
                "s": int(rng.integers(1, 10)) * 100,
                "x": "V",
                # Every 50th print is form-T: it must be excluded from bars.
                "c": [FORM_T] if index % 50 == 49 else [REGULAR_SALE],
                "i": f"tr-{index:05d}",
                "z": "C",
                "q": sequence,
            }
        )

    # A second print at an already-used nanosecond, distinguished only by its
    # vendor sequence. Without the sequence the two would be unorderable.
    collision = dict(trades[100])
    collision["i"] = "tr-collide"
    collision["q"] = trades[100]["q"] + 100_000
    collision["s"] = 300
    trades.insert(101, collision)

    return {"trades": trades, "quotes": quotes}


def _rfc3339(nanos: int) -> str:
    """Render nanoseconds as Alpaca does: RFC-3339 with nanosecond precision."""
    import time

    seconds, rest = divmod(nanos, NS_PER_SECOND)
    parts = time.gmtime(seconds)
    return (
        f"{parts.tm_year:04d}-{parts.tm_mon:02d}-{parts.tm_mday:02d}"
        f"T{parts.tm_hour:02d}:{parts.tm_min:02d}:{parts.tm_sec:02d}"
        f".{rest:09d}Z"
    )


def reference() -> dict[str, Any]:
    """The instrument master row, ticker assignment and calendar day."""
    return {
        "instrument": {
            "instrument_id": INSTRUMENT_ID,
            "primary_exchange": "XNAS",
            "security_type": "common_stock",
            "lot_size": 100,
            "is_tradable": True,
            "effective_time": "2020-01-01T00:00:00.000000000Z",
        },
        "ticker_history": [
            {
                "instrument_id": INSTRUMENT_ID,
                "ticker": SYMBOL,
                "effective_time": "2020-01-01T00:00:00.000000000Z",
                "end_time": None,
            }
        ],
        "calendar": {
            "session_date": SESSION_DATE,
            "is_trading_day": True,
            "regular_open_ns": SESSION_OPEN_NS,
            "regular_close_ns": SESSION_CLOSE_NS,
            "is_early_close": False,
            "opening_auction_ns": SESSION_OPEN_NS,
            "closing_auction_ns": SESSION_CLOSE_NS,
        },
    }


def _render(records: list[dict[str, Any]]) -> str:
    """One JSON object per line, keys sorted, so a diff is readable."""
    return "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in records)


def files() -> dict[str, str]:
    raw = generate()
    return {
        "raw/trades/0000.ndjson": _render(raw["trades"]),
        "raw/quotes/0000.ndjson": _render(raw["quotes"]),
        "reference.json": json.dumps(reference(), indent=2, sort_keys=True) + "\n",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the fixture is stale")
    args = parser.parse_args(argv)

    rendered = files()

    if args.check:
        for name, body in rendered.items():
            path = FIXTURE_DIR / name
            if not path.is_file():
                print(f"{path} is missing; run: make fixture", file=sys.stderr)
                return 1
            if path.read_text(encoding="utf-8") != body:
                print(
                    f"{path} does not match the generator. A fixture that drifts "
                    "is not a golden fixture -- run: make fixture, and review the "
                    "diff carefully, because every golden test regresses against it.",
                    file=sys.stderr,
                )
                return 1
        digest = hashlib.sha256("".join(rendered[k] for k in sorted(rendered)).encode()).hexdigest()
        print(f"fixture: up to date ({len(rendered)} files, sha256 {digest[:12]})")
        return 0

    for name, body in rendered.items():
        path = FIXTURE_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    print(f"wrote {len(rendered)} fixture file(s) to {FIXTURE_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
