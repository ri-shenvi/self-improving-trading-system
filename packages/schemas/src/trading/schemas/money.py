"""Money is integer nano-dollars; quantity is integer shares (D2').

One scale, 1e-9 USD, for every monetary value in the system. Nano-dollars times
a dimensionless integer share count is nano-dollars, so ``price * quantity`` is
exact and there is no cross-scale conversion anywhere for one to be wrong in.
That is what lets §40's "PnL reconciles **exactly** from fills" be an equality
rather than a tolerance.

The approved plan said prices should carry a per-instrument tick scale. That
fails on its own terms: the scale is per-instrument *and* time-varying — sub-penny
rules put prices under $1.00 on a $0.0001 increment — so a stored scaled price is
meaningless without an ``(instrument_id, as_of)`` lookup, which is itself a
point-in-time join that must be got right, and which makes a raw parquet file
non-self-describing. Recorded as divergence D2'.

Two things this module exists to prevent, both verified rather than assumed:

**int64 overflow wraps.** ``np.int64(9e18) + np.int64(9e18)`` evaluates to a
negative number. It emits a RuntimeWarning, which is filtered or unread in any
real pipeline. The failure mode is therefore a negative turnover in an HTML
report, not an exception. So: *stored* values are int64-bounded and range-checked
on the way in, and *accumulators* are Python ints, which are arbitrary-precision
and cannot be silently wrong.

**Rounding does not come from small fees.** A regulatory rate of $0.0000051 per
share is exactly 5 100 nano-dollars — no rounding at all. Rounding comes from
*division by a non-integer ratio*: a mid price ``(bid + ask) / 2`` is half-nano
whenever the sum is odd, which is most quotes; borrow accrual divides an annual
rate by 360; impact models take a percentage of notional. Those are the sites
that need a direction, and each one must name it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Final, NewType

#: Nano-dollars per dollar.
NANO: Final = 1_000_000_000

#: A monetary amount in integer nano-dollars (1e-9 USD).
NanoDollars = NewType("NanoDollars", int)

#: A whole-share quantity. v1 does not trade fractional shares; see
#: ``BrokerCapabilities.fractional_shares``.
Shares = NewType("Shares", int)

#: Storable range. Deliberately half of int64, so that a value which passed this
#: check cannot overflow on one subsequent addition — the boundary is enforced
#: with headroom rather than exactly at the cliff.
STORABLE_MAX: Final = 2**62
STORABLE_MIN: Final = -(2**62)

#: int64 itself, for reference in error messages.
INT64_MAX: Final = 2**63 - 1


class MoneyOverflowError(ValueError):
    """A monetary value exceeded the storable range.

    Raised rather than wrapped. An int64 that wraps produces a plausible-looking
    negative number that flows into a report; this produces a stack trace naming
    the field.
    """


class FractionalSharesError(ValueError):
    """A non-integral share quantity was requested and is not supported in v1."""


def dollars(amount: str | int | Decimal) -> NanoDollars:
    """Construct nano-dollars from a decimal amount.

    Accepts ``str`` and ``Decimal``; ``float`` is deliberately not accepted,
    because ``0.1`` is not 0.1 and a binary float literal is not reproducible
    across platforms.

    Raises:
        MoneyOverflowError: If the result is outside the storable range.
        ValueError: If the amount has sub-nano-dollar precision.
    """
    if isinstance(amount, float):
        raise TypeError(
            f"dollars() refuses float {amount!r}: binary floats are not exact "
            "decimals (0.1 is not 0.1) and are not reproducible across "
            "platforms. Pass a str or Decimal."
        )
    value = Decimal(amount) * NANO
    if value != value.to_integral_value():
        raise ValueError(
            f"{amount!r} has sub-nano-dollar precision; the smallest "
            "representable amount is 0.000000001 USD"
        )
    return narrow(int(value), field="dollars()")


def narrow(value: int, *, field: str) -> NanoDollars:
    """Bound an exact Python int into a storable nano-dollar value.

    This is the only sanctioned transition from an accumulator to a stored
    value. Every write path goes through it, so an overflow surfaces as a named
    failure at the moment of writing rather than as a wrapped integer much later.

    Args:
        value: Exact amount in nano-dollars.
        field: Column or quantity name, used in the error message.

    Raises:
        MoneyOverflowError: If ``value`` is outside the storable range.
    """
    if not STORABLE_MIN <= value <= STORABLE_MAX:
        raise MoneyOverflowError(
            f"{field}={value} nano-dollars ({value / NANO:,.2f} USD) exceeds the "
            f"storable range of +/-{STORABLE_MAX} ({STORABLE_MAX / NANO:,.2f} USD). "
            "Accumulators are Python ints and may exceed this; a *stored* value "
            "may not, because int64 wraps silently rather than raising."
        )
    return NanoDollars(value)


def shares(count: int) -> Shares:
    """Construct a whole-share quantity."""
    if not isinstance(count, int) or isinstance(count, bool):
        raise FractionalSharesError(f"share count must be an int, got {count!r}")
    return Shares(count)


def notional(price: NanoDollars, quantity: Shares) -> int:
    """Return ``price * quantity`` exactly, as an unbounded Python int.

    Deliberately not narrowed: the product is frequently an intermediate that is
    summed before being stored, and narrowing here would reject a legitimate
    calculation whose *total* is in range. Narrow at the write path instead.
    """
    return int(price) * int(quantity)


@dataclass(frozen=True, slots=True)
class RoundedMoney:
    """A rounded amount together with what rounding discarded.

    The invariant is ``value + remainder == exact``, always, with ``remainder`` a
    signed :class:`~fractions.Fraction` of magnitude below one nano-dollar.

    Carrying the remainder is what makes "no money is created or destroyed"
    checkable *in the presence of rounding*. Accounting accumulates remainders
    per cost component, and the ledger asserts the exact identity rather than
    asserting merely that some rounding function was called.
    """

    value: NanoDollars
    remainder: Fraction

    def __post_init__(self) -> None:
        if abs(self.remainder) >= 1:
            raise ValueError(
                f"remainder {self.remainder} is a whole nano-dollar or more, "
                "which means the rounding lost a representable amount"
            )

    @property
    def exact(self) -> Fraction:
        """The unrounded value this was derived from."""
        return Fraction(int(self.value)) + self.remainder


def _round_against_us(exact: Fraction, *, away_from_zero: bool, field: str) -> RoundedMoney:
    """Round in whichever direction disadvantages us.

    ``divmod`` floors, so for a negative value the floor is already the
    away-from-zero side and for a positive value it is the toward-zero side.
    An exact value is never nudged: rounding an integer would invent money.
    """
    floor, rest = divmod(exact.numerator, exact.denominator)
    if rest == 0:
        value = floor
    elif (exact > 0) == away_from_zero:
        value = floor + 1
    else:
        value = floor
    return RoundedMoney(narrow(value, field=field), exact - value)


def round_cost(exact: Fraction, *, field: str = "cost") -> RoundedMoney:
    """Round a cost away from zero, so the simulator is never optimistic.

    Fees, commissions, borrow, financing, and the spread we pay. §41 lists cost
    blindness as a failure mode; a simulator that rounds costs down manufactures
    edge a nano-dollar at a time.
    """
    return _round_against_us(exact, away_from_zero=True, field=field)


def round_credit(exact: Fraction, *, field: str = "credit") -> RoundedMoney:
    """Round a credit toward zero, so the simulator is never optimistic.

    Rebates, interest received, and the spread we capture — the mirror of
    :func:`round_cost`. Both round *against us*; they differ only in which
    direction that is.
    """
    return _round_against_us(exact, away_from_zero=False, field=field)


def apply_rate(
    base: int, rate: Fraction, *, credit: bool = False, field: str = "rate"
) -> RoundedMoney:
    """Apply a non-integer rate to a base amount, rounding against us.

    This is the site that actually produces remainders — per-share fee *rates*
    are exactly representable, but a rate applied to a notional, or an annual
    rate divided by 360, generally is not.

    Args:
        base: Exact base amount in nano-dollars.
        rate: The rate, as a rational. Not a float: a rate schedule is a
            published exact quantity and must not acquire binary error.
        credit: Whether the result is money we receive rather than pay.
    """
    exact = Fraction(base) * rate
    return round_credit(exact, field=field) if credit else round_cost(exact, field=field)


def format_usd(value: NanoDollars | int) -> str:
    """Render nano-dollars as USD, for logs and reports only."""
    return f"{Decimal(int(value)) / NANO:,.9f}"
