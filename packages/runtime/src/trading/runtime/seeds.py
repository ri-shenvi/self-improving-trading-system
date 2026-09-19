"""Named random streams derived from a single recorded experiment seed (D9).

Every experiment records exactly one ``random_seed`` (section 9). All randomness in
the system descends from it through this module, so a run can be reproduced
from the registry row alone.

Streams are addressed **by name**, not by spawn order. ``SeedSequence.spawn()``
hands out children positionally, which means the values a consumer receives
depend on how many other consumers asked first. That is a silent reproducibility
hazard: adding a bootstrap to the validation stage would shift the queue model's
draws and change fill outcomes in an unrelated experiment. Deriving the spawn key
from a stable hash of the stream name instead makes each consumer's sequence a
function of ``(experiment_seed, name)`` only.

The name hash is BLAKE2b rather than :func:`hash`, which is salted per process
unless ``PYTHONHASHSEED`` is pinned. Depending on an environment variable for a
correctness property would be a trap; this way the derivation is stable whether
or not the envelope is enforced.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

import numpy as np

_SPAWN_KEY_BYTES: Final = 8


def _stable_name_key(name: str) -> int:
    """Map a stream name to a process-independent spawn key."""
    if not name:
        raise ValueError("stream name must be non-empty")
    digest = hashlib.blake2b(name.encode("utf-8"), digest_size=_SPAWN_KEY_BYTES).digest()
    return int.from_bytes(digest, "big")


@dataclass(frozen=True, slots=True)
class SeedEnvelope:
    """The single seed for one experiment, and the named streams it derives.

    Args:
        experiment_seed: The ``random_seed`` recorded on the experiment row.
    """

    experiment_seed: int

    def __post_init__(self) -> None:
        if self.experiment_seed < 0:
            raise ValueError("experiment_seed must be non-negative")

    def sequence(self, name: str) -> np.random.SeedSequence:
        """Return the seed sequence for a named consumer."""
        return np.random.SeedSequence(
            entropy=self.experiment_seed,
            spawn_key=(_stable_name_key(name),),
        )

    def stream(self, name: str) -> np.random.Generator:
        """Return an independent generator for a named consumer.

        Args:
            name: Stable identifier for the consumer, e.g. ``"fills.queue"`` or
                ``"validation.block_bootstrap"``. Callers must not construct this
                from anything that varies between runs.
        """
        return np.random.Generator(np.random.PCG64(self.sequence(name)))
