"""The pinned process environment required for byte-reproducible results (D9).

Section 2 of the specification asks for "byte-equivalent orders and metrics for
repeated runs on the same snapshot". Orders are reproducible from ordering and
seeding alone; float *metrics* are not, because BLAS and OpenMP split reductions
across threads and the split point decides the summation order. Two runs on the
same data with different thread counts produce metrics that differ in the last
bits. The counts are therefore pinned rather than the criterion weakened — see
``docs/spec-divergences.md``, divergence 2.

These variables must be set before the interpreter starts, or before the numeric
libraries are first imported. This module verifies rather than mutates: a library
that has already read its thread count will not re-read it, so a late
``os.environ`` write would leave a process that looks compliant and is not. The
entry points (``Makefile``, ``infra/docker/Dockerfile``, the CI workflow) set the
variables; the process checks them.
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from trading.runtime.errors import DeterminismError

PINNED_ENV: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        # Salted string hashing changes set and dict iteration order, which can
        # reach output through any unsorted collection.
        "PYTHONHASHSEED": "0",
        # Every timestamp is UTC nanoseconds (D3). A non-UTC process clock would
        # only surface at a DST boundary.
        "TZ": "UTC",
        # Thread counts fix float reduction order. One thread is the only value
        # that is stable across machines with different core counts.
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "POLARS_MAX_THREADS": "1",
    }
)

# Importing one of these freezes the corresponding thread count, so a violation
# is unrecoverable in-process rather than merely unset.
_THREAD_SENSITIVE_MODULES: Final = ("numpy", "polars", "scipy")


@dataclass(frozen=True, slots=True)
class EnvViolation:
    """One environment variable that is missing or set to the wrong value."""

    name: str
    expected: str
    actual: str | None

    def __str__(self) -> str:
        got = "unset" if self.actual is None else repr(self.actual)
        return f"{self.name}: expected {self.expected!r}, got {got}"


def verify_environment(env: dict[str, str] | None = None) -> list[EnvViolation]:
    """Return every pinned variable that is missing or wrong.

    Args:
        env: Environment to inspect. Defaults to the live process environment.

    Returns:
        Violations in declaration order. Empty means the envelope holds.
    """
    source = os.environ if env is None else env
    return [
        EnvViolation(name=name, expected=expected, actual=source.get(name))
        for name, expected in PINNED_ENV.items()
        if source.get(name) != expected
    ]


def numeric_libraries_already_imported() -> tuple[str, ...]:
    """Return the thread-sensitive libraries already loaded in this process."""
    return tuple(name for name in _THREAD_SENSITIVE_MODULES if name in sys.modules)


def require_deterministic_environment(env: dict[str, str] | None = None) -> None:
    """Raise unless the process can produce byte-reproducible results.

    Call this at every entry point that writes an experiment artifact, before
    any numeric work.

    Raises:
        DeterminismError: If any pinned variable is missing or wrong.
    """
    violations = verify_environment(env)
    if not violations:
        return

    detail = "\n".join(f"  - {v}" for v in violations)
    loaded = numeric_libraries_already_imported()
    hint = (
        f"\n{', '.join(loaded)} already imported, so the thread counts are frozen "
        "for this process; set the variables before starting the interpreter "
        "(see the Makefile or infra/docker/Dockerfile)."
        if loaded
        else "\nSet these before starting the interpreter."
    )
    raise DeterminismError(f"non-deterministic environment:\n{detail}{hint}")


def process_timezone_is_utc() -> bool:
    """Report whether the process clock is UTC.

    ``TZ`` being set is not sufficient: it is read by libc at first use, so a
    process that set it late has a stale zone.
    """
    return time.timezone == 0 and (not time.daylight or time.altzone == 0)
