"""Determinism envelope: seeding, environment pinning, build fingerprints.

The specification makes reproducibility a hard control rather than a goal:
identical dataset snapshot, code commit, seed and config must produce identical
results, and a failure to do so stops releases. This package holds the machinery
that claim rests on, and is depended on by every other package.
"""

from trading.runtime.determinism import (
    PINNED_ENV,
    EnvViolation,
    require_deterministic_environment,
    verify_environment,
)
from trading.runtime.errors import DeterminismError, ProvenanceError
from trading.runtime.fingerprint import (
    CONTAINER_DIGEST_ENV,
    ContainerIdentity,
    EnvironmentFingerprint,
    compute_environment_fingerprint,
    container_identity,
    file_sha256,
)
from trading.runtime.seeds import SeedEnvelope

__all__ = [
    "CONTAINER_DIGEST_ENV",
    "PINNED_ENV",
    "ContainerIdentity",
    "DeterminismError",
    "EnvViolation",
    "EnvironmentFingerprint",
    "ProvenanceError",
    "SeedEnvelope",
    "compute_environment_fingerprint",
    "container_identity",
    "file_sha256",
    "require_deterministic_environment",
    "verify_environment",
]
