"""Rounding is never in our favour, and money is never created or destroyed.

These are the invariants that make §40's "PnL reconciles exactly from fills" an
equality rather than a tolerance, stated over generated values rather than
chosen ones.
"""

from __future__ import annotations

from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading.schemas.money import (
    STORABLE_MAX,
    MoneyOverflowError,
    NanoDollars,
    apply_rate,
    narrow,
    notional,
    round_cost,
    round_credit,
    shares,
)

pytestmark = pytest.mark.property

# Bounded well inside the storable range so rounding, not overflow, is under test.
exacts = st.fractions(min_value=Fraction(-(10**15)), max_value=Fraction(10**15))
rates = st.fractions(min_value=Fraction(0), max_value=Fraction(2))
bases = st.integers(min_value=-(10**15), max_value=10**15)


@given(exact=exacts)
def test_value_plus_remainder_is_exact(exact: Fraction) -> None:
    """No money is created or destroyed, even though rounding happened."""
    for rounded in (round_cost(exact), round_credit(exact)):
        assert rounded.value + rounded.remainder == exact


@given(exact=exacts)
def test_remainder_is_sub_nano(exact: Fraction) -> None:
    assert abs(round_cost(exact).remainder) < 1
    assert abs(round_credit(exact).remainder) < 1


@given(exact=exacts)
def test_a_cost_is_never_understated(exact: Fraction) -> None:
    assert abs(round_cost(exact).value) >= abs(exact)


@given(exact=exacts)
def test_a_credit_is_never_overstated(exact: Fraction) -> None:
    assert abs(round_credit(exact).value) <= abs(exact)


@given(exact=exacts)
def test_rounding_preserves_sign(exact: Fraction) -> None:
    """A cost must not flip into a credit by being rounded."""
    for rounded in (round_cost(exact), round_credit(exact)):
        if rounded.value != 0:
            assert (rounded.value > 0) == (exact > 0)


@given(base=bases, rate=rates)
def test_a_cost_is_never_cheaper_than_the_same_credit(base: int, rate: Fraction) -> None:
    """Pessimism, mechanised: charging always costs at least as much as crediting."""
    cost = apply_rate(base, rate, field="fee")
    credit = apply_rate(base, rate, credit=True, field="rebate")
    assert abs(cost.value) >= abs(credit.value)


@given(components=st.lists(exacts, min_size=1, max_size=40))
def test_accumulated_remainders_recover_the_exact_total(components: list[Fraction]) -> None:
    """The ledger identity: rounded components plus their remainders are exact.

    This is what lets accounting assert exactness in the presence of rounding,
    rather than merely asserting that a rounding function was called.
    """
    rounded = [round_cost(c) for c in components]
    total_value = sum(int(r.value) for r in rounded)
    total_remainder = sum((r.remainder for r in rounded), Fraction(0))
    assert total_value + total_remainder == sum(components, Fraction(0))


@given(
    price=st.integers(min_value=1, max_value=10**12),
    quantity=st.integers(min_value=-(10**6), max_value=10**6),
)
def test_notional_is_exact_multiplication(price: int, quantity: int) -> None:
    """The property the whole single-scale design exists for: no conversion, no loss."""
    assert notional(NanoDollars(price), shares(quantity)) == price * quantity


@given(value=st.integers(min_value=STORABLE_MAX + 1, max_value=2**70))
def test_beyond_the_boundary_raises_rather_than_wraps(value: int) -> None:
    with pytest.raises(MoneyOverflowError):
        narrow(value, field="stored")


@given(value=st.integers(min_value=-STORABLE_MAX, max_value=STORABLE_MAX))
def test_within_the_boundary_is_preserved(value: int) -> None:
    assert narrow(value, field="stored") == value
