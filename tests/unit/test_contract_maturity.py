"""Frozen and provisional contracts are distinguished, and both are pinned."""

from __future__ import annotations

import pytest

import trading.schemas  # noqa: F401  -- registers the contracts
from trading.schemas.registry import all_contracts, load_lock
from trading.schemas.spec import Maturity

pytestmark = pytest.mark.unit


def test_both_maturities_are_in_use() -> None:
    """If everything were frozen, the distinction would be decorative."""
    levels = {c.maturity for c in all_contracts()}
    assert levels == {Maturity.FROZEN, Maturity.PROVISIONAL}


def test_provisional_contracts_are_the_ones_whose_consumer_is_unbuilt() -> None:
    provisional = {c.name for c in all_contracts() if c.maturity is Maturity.PROVISIONAL}
    assert provisional == {"features.value"}, (
        "a contract is provisional only while nothing writes it; promoting one "
        "is itself a hashed, reviewable change"
    )


def test_every_contract_is_pinned_regardless_of_maturity() -> None:
    """Provisional means 'may change', never 'is untracked'."""
    locked = load_lock()["contracts"]
    for contract in all_contracts():
        assert contract.name in locked
        assert locked[contract.name]["hash"] == contract.content_hash()
        assert locked[contract.name]["maturity"] == contract.maturity.value


def test_on_disk_contracts_are_frozen() -> None:
    """Anything the writer can emit has bytes, so it cannot be provisional."""
    for contract in all_contracts():
        if contract.name.startswith(("normalized.", "reference.", "execution.")):
            assert contract.maturity is Maturity.FROZEN, contract.name
