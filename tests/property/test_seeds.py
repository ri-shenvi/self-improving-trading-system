"""Named random streams must be a function of (experiment_seed, name) alone.

The property that matters is *order independence*. If a stream's values depended
on how many other consumers drew first, adding a bootstrap to the validation
stage would shift the queue model's draws and silently change fill outcomes in an
unrelated experiment — a reproducibility break that no test comparing a run to
itself would ever catch.
"""

from __future__ import annotations

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading.runtime.seeds import SeedEnvelope

pytestmark = pytest.mark.property

seeds = st.integers(min_value=0, max_value=2**63 - 1)
names = st.text(min_size=1, max_size=40)


def draw(envelope: SeedEnvelope, name: str, n: int = 8) -> list[float]:
    return [float(v) for v in envelope.stream(name).random(n)]


@given(seed=seeds, name=names)
def test_same_seed_and_name_reproduce(seed: int, name: str) -> None:
    assert draw(SeedEnvelope(seed), name) == draw(SeedEnvelope(seed), name)


@given(seed=seeds, first=names, second=names)
def test_streams_are_independent_of_request_order(seed: int, first: str, second: str) -> None:
    """Drawing an unrelated stream first must not perturb this one."""
    envelope = SeedEnvelope(seed)
    alone = draw(envelope, second)

    other = SeedEnvelope(seed)
    other.stream(first).random(1000)
    after = draw(other, second)

    assert alone == after


@given(seed=seeds, a=names, b=names)
def test_distinct_names_give_distinct_streams(seed: int, a: str, b: str) -> None:
    envelope = SeedEnvelope(seed)
    if a == b:
        assert draw(envelope, a) == draw(envelope, b)
    else:
        assert draw(envelope, a) != draw(envelope, b)


@given(a=seeds, b=seeds, name=names)
def test_distinct_seeds_give_distinct_streams(a: int, b: int, name: str) -> None:
    if a != b:
        assert draw(SeedEnvelope(a), name) != draw(SeedEnvelope(b), name)


@given(seed=seeds, name=names)
def test_stream_is_a_pcg64_generator(seed: int, name: str) -> None:
    generator = SeedEnvelope(seed).stream(name)
    assert isinstance(generator, np.random.Generator)
    assert isinstance(generator.bit_generator, np.random.PCG64)


def test_name_hash_is_stable_across_processes() -> None:
    """Pinned against a literal: a change here silently invalidates past runs.

    The derivation must not depend on PYTHONHASHSEED. Making a correctness
    property contingent on an environment variable is exactly the trap this
    module exists to avoid, so the expected values are checked in.
    """
    assert SeedEnvelope(12345).stream("fills.queue").integers(0, 2**32, 4).tolist() == [
        477117998,
        399260162,
        83323074,
        1710561012,
    ]


def test_empty_stream_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        SeedEnvelope(1).stream("")


def test_negative_seed_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        SeedEnvelope(-1)
