"""Record what the fixture is expected to produce.

The expectations are content hashes and spot values rather than a checked-in
parquet file. Parquet embeds its writer's version in the footer, so a
byte-for-byte golden would fail on every pyarrow bump with an alarming and
unattributable diff — the same reasoning that keeps ``file_sha256`` out of
``snapshot_id`` (divergence 11).

``content_sha256`` is over the Arrow encoding of the data and carries no writer
version, so it is stable for the right reason: it changes when the *data*
changes and not otherwise.

Usage::

    python tools/build_golden.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

# Run as a script, sys.path[0] is tools/, so the sibling module is not importable
# as tools.golden_fixture -- which is how the tests import it. Same module, one
# import path, so the generator and the tests cannot diverge.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.golden_fixture import EXPECTED_PATH, run_fixture

from trading.market_data.snapshot import SnapshotReader


def compute() -> dict[str, Any]:
    """Run the pipeline on the fixture and capture what it produced."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        result = run_fixture(root)
        reader = SnapshotReader(root, result.manifest)

        bars = reader.read_contract("normalized.bar").to_pydict()
        trades = reader.read_contract("normalized.trade").to_pydict()

        return {
            "snapshot_id": result.snapshot_id,
            "files": {
                receipt.contract: {
                    "row_count": receipt.row_count,
                    "content_sha256": receipt.content_sha256,
                }
                for receipt in sorted(result.receipts, key=lambda r: r.contract)
            },
            "first_bar": {
                "event_time": bars["event_time"][0],
                "open_nano": bars["open_nano"][0],
                "high_nano": bars["high_nano"][0],
                "low_nano": bars["low_nano"][0],
                "close_nano": bars["close_nano"][0],
                "volume_shares": bars["volume_shares"][0],
                "vwap_nano": bars["vwap_nano"][0],
                "trade_count": bars["trade_count"][0],
                "is_complete": bars["is_complete"][0],
            },
            "bar_count": len(bars["event_time"]),
            "trades_in_bars": sum(bars["trade_count"]),
            "first_trade_event_time": trades["event_time"][0],
            "first_trade_knowledge_time": trades["knowledge_time"][0],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if expectations are stale")
    args = parser.parse_args(argv)

    rendered = json.dumps(compute(), indent=2, sort_keys=True) + "\n"

    if args.check:
        if not EXPECTED_PATH.is_file():
            print(f"{EXPECTED_PATH} is missing; run: make golden", file=sys.stderr)
            return 1
        if EXPECTED_PATH.read_text(encoding="utf-8") != rendered:
            print(
                f"{EXPECTED_PATH} does not match what the pipeline produces. If the "
                "change is intended, run `make golden` and review the diff -- every "
                "later milestone regresses against these values.",
                file=sys.stderr,
            )
            return 1
        print("golden expectations: up to date")
        return 0

    EXPECTED_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {EXPECTED_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
