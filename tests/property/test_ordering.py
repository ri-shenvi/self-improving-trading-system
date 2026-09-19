"""The event order must be *total*, or byte-exact replay is impossible.

A partial order would let two runs dispatch the same pair of events in different
sequences, producing different fills from identical data — the reproducibility
break that no run-against-itself comparison can detect. These properties are the
mechanical statement of §16's "Stable priority" invariant.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading.schemas.ordering import (
    AFTER_ALL,
    BEFORE_ALL,
    MISSING_SEQUENCE,
    OrderingKey,
    SourceRank,
    assign_ingest_index,
    is_strictly_after,
)
from trading.schemas.time import TimestampNs

pytestmark = pytest.mark.property

keys = st.builds(
    OrderingKey,
    event_time=st.integers(min_value=0, max_value=10**6).map(TimestampNs),
    source_rank=st.sampled_from(SourceRank),
    # Deliberately includes MISSING_SEQUENCE so mixed-presence sets are covered.
    vendor_sequence=st.integers(min_value=MISSING_SEQUENCE, max_value=50),
    venue_sequence=st.integers(min_value=MISSING_SEQUENCE, max_value=50),
    ingest_index=st.integers(min_value=0, max_value=50),
)


@given(a=keys)
def test_irreflexive(a: OrderingKey) -> None:
    assert not a < a


@given(a=keys, b=keys)
def test_antisymmetric(a: OrderingKey, b: OrderingKey) -> None:
    if a != b:
        assert (a < b) != (b < a)


@given(a=keys, b=keys, c=keys)
def test_transitive(a: OrderingKey, b: OrderingKey, c: OrderingKey) -> None:
    if a < b and b < c:
        assert a < c


@given(a=keys, b=keys)
def test_total(a: OrderingKey, b: OrderingKey) -> None:
    """Every pair compares. This is what a mixed-presence sentinel buys."""
    assert (a < b) or (b < a) or (a == b)


@given(collection=st.lists(keys, min_size=2, max_size=30))
def test_sorting_is_stable_under_input_permutation(collection: list[OrderingKey]) -> None:
    """The same events in any input order produce the same dispatch order."""
    # Shuffles test inputs only. Library code may not import this (TRD004); tests
    # are not scanned, so the plain import is correct here rather than suppressed.
    import random

    shuffled = list(collection)
    random.Random(0).shuffle(shuffled)
    assert sorted(collection) == sorted(shuffled)


@given(a=keys)
def test_sentinels_bound_every_real_key(a: OrderingKey) -> None:
    assert BEFORE_ALL < a < AFTER_ALL


class TestComponentPrecedence:
    def test_event_time_dominates(self) -> None:
        early = OrderingKey(TimestampNs(1), SourceRank.SYNTHETIC, 99, 99, 99)
        late = OrderingKey(TimestampNs(2), SourceRank.SESSION, 0, 0, 0)
        assert early < late

    def test_constraints_precede_opportunities(self) -> None:
        """A halt in the same nanosecond as a print must reach risk first."""
        halt = OrderingKey(TimestampNs(1), SourceRank.STATUS)
        trade = OrderingKey(TimestampNs(1), SourceRank.TRADE)
        assert halt < trade

    def test_quote_precedes_trade(self) -> None:
        quote = OrderingKey(TimestampNs(1), SourceRank.QUOTE)
        trade = OrderingKey(TimestampNs(1), SourceRank.TRADE)
        assert quote < trade

    def test_missing_sequence_sorts_first(self) -> None:
        """An event we cannot place is dispatched before ones we can."""
        unknown = OrderingKey(TimestampNs(1), SourceRank.TRADE, MISSING_SEQUENCE)
        known = OrderingKey(TimestampNs(1), SourceRank.TRADE, 0)
        assert unknown < known

    def test_ingest_index_is_the_final_tiebreak(self) -> None:
        first = OrderingKey(TimestampNs(1), SourceRank.TRADE, 7, 7, 0)
        second = OrderingKey(TimestampNs(1), SourceRank.TRADE, 7, 7, 1)
        assert first < second


class TestStrictlyAfter:
    def test_equal_keys_are_not_after(self) -> None:
        """The no-same-event-fill invariant: equality is not 'after'."""
        key = OrderingKey(TimestampNs(1), SourceRank.TRADE)
        assert not is_strictly_after(key, key)

    def test_later_key_is_after(self) -> None:
        earlier = OrderingKey(TimestampNs(1), SourceRank.TRADE)
        later = OrderingKey(TimestampNs(2), SourceRank.TRADE)
        assert is_strictly_after(later, earlier)


class TestIngestIndex:
    @given(position=st.integers(min_value=0, max_value=10**9))
    def test_is_a_pure_function_of_position(self, position: int) -> None:
        """Re-ingesting the same bytes must reproduce the same index."""
        assert assign_ingest_index(position) == assign_ingest_index(position)

    def test_rejects_negative_position(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            assign_ingest_index(-1)

    def test_reingesting_a_partition_reproduces_the_key_sequence(self) -> None:
        """The property that distinguishes position from arrival order.

        Two ingests of the same raw messages -- with the second processed by a
        run that saw them at completely different wall-clock times -- must yield
        an identical key sequence.
        """
        messages = [(TimestampNs(5), SourceRank.TRADE), (TimestampNs(5), SourceRank.TRADE)]

        def ingest() -> list[OrderingKey]:
            return [
                OrderingKey(t, rank, ingest_index=assign_ingest_index(i))
                for i, (t, rank) in enumerate(messages)
            ]

        assert ingest() == ingest()
        assert sorted(ingest()) == ingest()
