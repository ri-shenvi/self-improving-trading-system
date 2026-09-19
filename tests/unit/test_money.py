"""Money is exact integer arithmetic, and rounding is never in our favour."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import pytest

from trading.schemas.money import (
    NANO,
    STORABLE_MAX,
    FractionalSharesError,
    MoneyOverflowError,
    RoundedMoney,
    apply_rate,
    dollars,
    format_usd,
    narrow,
    notional,
    round_cost,
    round_credit,
    shares,
)

pytestmark = pytest.mark.unit


class TestConstruction:
    def test_accepts_str_and_decimal(self) -> None:
        assert dollars("1.50") == 1_500_000_000
        assert dollars(Decimal("0.000000001")) == 1
        assert dollars(7) == 7 * NANO

    def test_refuses_float(self) -> None:
        """0.1 is not 0.1, and a binary literal is not reproducible."""
        with pytest.raises(TypeError, match="refuses float"):
            dollars(0.1)  # type: ignore[arg-type]

    def test_refuses_sub_nano_precision(self) -> None:
        with pytest.raises(ValueError, match="sub-nano-dollar"):
            dollars("0.0000000001")

    def test_regulatory_fee_rate_is_exact(self) -> None:
        """The premise that fees force rounding is wrong; division is what does."""
        assert dollars("0.0000051") == 5_100

    def test_sub_penny_increment_is_exact(self) -> None:
        assert dollars("0.0001") == 100_000


class TestRange:
    def test_narrow_accepts_a_realistic_notional(self) -> None:
        assert narrow(500 * NANO * 10**6, field="notional") == 5 * 10**17

    def test_narrow_raises_rather_than_wrapping(self) -> None:
        """int64 wraps silently; this is the boundary that turns that into a stack trace."""
        with pytest.raises(MoneyOverflowError, match="exceeds the storable range"):
            narrow(STORABLE_MAX + 1, field="cash")

    def test_narrow_error_names_the_field(self) -> None:
        with pytest.raises(MoneyOverflowError, match="gross_notional"):
            narrow(2**63, field="gross_notional")

    def test_notional_is_exact_and_unbounded(self) -> None:
        """An intermediate may exceed the storable range; only a stored value may not."""
        huge = notional(dollars("500"), shares(10**9))
        assert huge == 500 * NANO * 10**9
        with pytest.raises(MoneyOverflowError):
            narrow(huge, field="stored")


class TestShares:
    def test_whole_shares(self) -> None:
        assert shares(100) == 100

    def test_rejects_fractional(self) -> None:
        with pytest.raises(FractionalSharesError):
            shares(1.5)  # type: ignore[arg-type]

    def test_rejects_bool(self) -> None:
        # bool is an int subtype, so mypy permits this call; the guard is runtime-only.
        with pytest.raises(FractionalSharesError):
            shares(True)


class TestRounding:
    @pytest.mark.parametrize(
        ("exact", "cost", "credit"),
        [
            (Fraction(5, 2), 3, 2),
            (Fraction(-5, 2), -3, -2),
            (Fraction(1, 3), 1, 0),
            (Fraction(-1, 3), -1, 0),
            (Fraction(2), 2, 2),
            (Fraction(-2), -2, -2),
            (Fraction(0), 0, 0),
        ],
    )
    def test_directions(self, exact: Fraction, cost: int, credit: int) -> None:
        assert round_cost(exact).value == cost
        assert round_credit(exact).value == credit

    def test_exact_values_are_not_nudged(self) -> None:
        """Rounding an integer away from zero would invent money."""
        assert round_cost(Fraction(-2)).value == -2
        assert round_credit(Fraction(-2)).value == -2

    def test_remainder_preserves_the_exact_value(self) -> None:
        rounded = round_cost(Fraction(1, 3))
        assert rounded.exact == Fraction(1, 3)
        assert rounded.value + rounded.remainder == Fraction(1, 3)

    def test_remainder_below_one_nano(self) -> None:
        with pytest.raises(ValueError, match="whole nano-dollar"):
            RoundedMoney(narrow(1, field="x"), Fraction(3, 2))


class TestApplyRate:
    def test_cost_rounds_up_in_magnitude(self) -> None:
        # A rate that cannot land on a nano boundary.
        result = apply_rate(1_000_000_000, Fraction(1, 3), field="fee")
        assert result.value == 333_333_334
        assert result.exact == Fraction(1_000_000_000, 3)

    def test_credit_rounds_down_in_magnitude(self) -> None:
        result = apply_rate(1_000_000_000, Fraction(1, 3), credit=True, field="rebate")
        assert result.value == 333_333_333

    def test_a_cost_is_never_cheaper_than_exact(self) -> None:
        assert apply_rate(7, Fraction(1, 3), field="fee").value >= Fraction(7, 3)


def test_format_usd_is_lossless_at_nano_resolution() -> None:
    assert format_usd(dollars("1.234567891")) == "1.234567891"
