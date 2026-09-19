"""Every §7 minimum field exists in the contract that implements it.

This is the test that catches a contract which is internally consistent, passes
every round-trip, and does not match the specification. The §7 table is parsed
from the committed `spec.txt`, not transcribed here, so adding a dataset or a
required field to the document fails this test until someone handles it.

The spec names fields in prose ("bid/ask price and size"); contracts name them
in code (`bid_price_nano`, `ask_size_shares`). COVERAGE is that mapping, and it
is deliberately the only hand-written part: the *left* side is checked against
the document, so a mapping cannot silently stop covering the spec.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import trading.schemas  # noqa: F401  -- registers the contracts
from trading.schemas.registry import all_contracts, get

pytestmark = pytest.mark.unit

SPEC = Path(__file__).resolve().parents[2] / "docs/specification/spec.txt"

#: §7 dataset -> (contract implementing it, spec phrase -> contract field).
#:
#: A field may live in a different contract than its dataset's primary one --
#: §7's "Reference" row lists ticker history, which is normalised into its own
#: table rather than crammed into the instrument master. Write those as
#: ``"other.contract#field"``.
COVERAGE: dict[str, tuple[str, dict[str, str]]] = {
    "Trades": (
        "normalized.trade",
        {
            "symbol": "instrument_id",
            "event time": "event_time",
            "price": "price_nano",
            "size": "size_shares",
            "exchange": "exchange",
            "conditions": "conditions",
            "trade id": "trade_id",
            "tape": "tape",
        },
    ),
    "Quotes": (
        "normalized.quote",
        {
            "bid/ask price and size": "bid_price_nano",
            "venues": "bid_exchange",
            "event time": "event_time",
            "conditions": "conditions",
        },
    ),
    "Bars": (
        "normalized.bar",
        {
            "open": "open_nano",
            "high": "high_nano",
            "low": "low_nano",
            "close": "close_nano",
            "volume": "volume_shares",
            "VWAP": "vwap_nano",
            "trade count": "trade_count",
            "window": "window_ns",
        },
    ),
    "Reference": (
        "reference.instrument",
        {
            "stable instrument id": "instrument_id",
            "ticker history": "reference.ticker_history#ticker",
            "exchange": "primary_exchange",
            "security type": "security_type",
            "lot size": "lot_size",
        },
    ),
    "Corporate actions": (
        "reference.corporate_action",
        {
            "splits": "split_numerator",
            "dividends": "cash_amount_nano",
            "mergers": "action_type",
            "symbol changes": "new_ticker",
            "effective and announcement times": "announcement_time",
        },
    ),
    "Calendar": (
        "reference.calendar_session",
        {
            "session": "session_date",
            "holidays": "is_trading_day",
            "early closes": "is_early_close",
            "auction windows": "opening_auction_ns",
        },
    ),
    "Halts and bands": (
        "normalized.trading_status",
        {
            "status": "status",
            "reason": "reason",
            "resume time": "resume_time",
            "LULD upper/lower bands": "luld_upper_nano",
        },
    ),
    "Borrow and SSR": (
        "reference.borrow",
        {
            "shortable": "is_shortable",
            "available quantity": "available_shares",
            "borrow fee": "borrow_fee_annual_bps",
            "locate state": "locate_state",
            "Rule 201 status": "rule_201_restricted",
        },
    ),
}

#: Deferred by the implementation plan's anti-scope, with the reason.
DEFERRED = {
    "News and filings": "worst timestamp semantics and highest leakage surface; M1 anti-scope",
    "Broker events": "order lifecycle contracts land in step 7",
}


def parse_section_7() -> dict[str, list[str]]:
    """Parse the §7 minimum-fields table out of the committed specification."""
    text = SPEC.read_text(encoding="utf-8")
    start = text.index("[Heading2] 7  Data sources and minimum fields")
    block = text[start : text.index("[Heading2] 8  Storage layout")]

    datasets: dict[str, list[str]] = {}
    for line in block.splitlines():
        if "|" not in line or line.startswith("Dataset"):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 2 or cells[0] in {"Dataset", ""}:
            continue
        datasets[cells[0]] = [f.strip() for f in re.split(r",(?![^(]*\))", cells[1])]
    return datasets


SECTION_7 = parse_section_7()


def test_the_table_was_parsed() -> None:
    assert len(SECTION_7) == 10, SECTION_7.keys()


def test_every_dataset_is_covered_or_deferred() -> None:
    """A dataset added to the spec must be handled, not silently ignored."""
    unhandled = set(SECTION_7) - set(COVERAGE) - set(DEFERRED)
    assert not unhandled, f"§7 datasets with no contract and no deferral: {sorted(unhandled)}"


def test_no_stale_coverage_entries() -> None:
    """A mapping for a dataset the spec no longer lists is a lie."""
    stale = (set(COVERAGE) | set(DEFERRED)) - set(SECTION_7)
    assert not stale, f"mapped datasets absent from §7: {sorted(stale)}"


@pytest.mark.parametrize("dataset", sorted(COVERAGE))
def test_every_spec_field_is_mapped(dataset: str) -> None:
    """Adding a required field to §7 must fail until a contract carries it."""
    mapped = set(COVERAGE[dataset][1])
    listed = set(SECTION_7[dataset])
    assert listed == mapped, (
        f"{dataset}: §7 lists {sorted(listed - mapped)} with no mapping, "
        f"and maps {sorted(mapped - listed)} which §7 does not list"
    )


@pytest.mark.parametrize("dataset", sorted(COVERAGE))
def test_mapped_fields_exist_in_the_contract(dataset: str) -> None:
    default_contract, mapping = COVERAGE[dataset]
    missing = {}
    for phrase, target in mapping.items():
        contract_name, _, field = target.rpartition("#")
        contract = get(contract_name or default_contract)
        if field not in set(contract.field_names()):
            missing[phrase] = f"{contract.name}.{field}"
    assert not missing, f"{dataset}: fields named by §7 but absent from the contracts: {missing}"


def test_every_market_contract_carries_the_time_sextuple() -> None:
    """§6: no record without a knowledge_time (D4)."""
    for contract in all_contracts():
        if contract.time_group is None:
            continue
        names = set(contract.field_names())
        assert {"event_time", "receive_time", "process_time", "knowledge_time"} <= names
        assert contract.field("knowledge_time").nullable is False
