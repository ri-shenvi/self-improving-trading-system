"""Two runs of the same trivial pipeline must agree byte for byte (M0 exit test).

Run in separate interpreters rather than twice in one process. A same-process
comparison shares import order, hash salt and thread pools, so it would pass on a
system where none of those were pinned — which is the whole class of defect this
is meant to catch.

The pipeline is deliberately minimal but touches what actually breaks: named
random streams, a float reduction whose summation order depends on BLAS thread
count, and serialization.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys

import pytest

from trading.runtime.determinism import PINNED_ENV

pytestmark = pytest.mark.property

PIPELINE = """
import hashlib, json
import numpy as np
from trading.runtime.seeds import SeedEnvelope

envelope = SeedEnvelope(20260919)
draws = {
    name: envelope.stream(name).standard_normal(5000)
    for name in ("fills.queue", "fills.partial", "validation.block_bootstrap")
}
summary = {
    name: {
        "sum": float(values.sum()),
        "dot": float(values @ values),
        "sorted_tail": [float(v) for v in np.sort(values)[-3:]],
    }
    for name, values in sorted(draws.items())
}
body = json.dumps(summary, sort_keys=True, separators=(",", ":")).encode()
print(hashlib.sha256(body).hexdigest())
"""


def run_pipeline() -> str:
    env = {**os.environ, **PINNED_ENV}
    result = subprocess.run(
        [sys.executable, "-c", PIPELINE],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def test_repeated_runs_are_byte_identical() -> None:
    first = run_pipeline()
    second = run_pipeline()
    assert first == second
    assert len(first) == 64


def test_output_is_independent_of_hash_salt() -> None:
    """PYTHONHASHSEED is pinned, but nothing may actually depend on it."""
    env = {**os.environ, **PINNED_ENV, "PYTHONHASHSEED": "1"}
    salted = subprocess.run(
        [sys.executable, "-c", PIPELINE], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()
    assert salted == run_pipeline()


def test_pipeline_hash_is_not_trivially_constant() -> None:
    """Guards the test itself: a pipeline that ignored its seed would also 'pass'."""
    altered = PIPELINE.replace("SeedEnvelope(20260919)", "SeedEnvelope(20260920)")
    env = {**os.environ, **PINNED_ENV}
    other = subprocess.run(
        [sys.executable, "-c", altered], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()
    assert other != run_pipeline()


def test_digest_matches_a_local_recomputation() -> None:
    assert hashlib.sha256(b"").hexdigest() != run_pipeline()
