"""Recording what code and environment produced an artifact (D9).

Section 9 stores a ``container_digest`` on every experiment and section 40 asks a
reviewer to reproduce any metric "from the experiment ID alone using pinned data,
code, container, config, and seed". Two distinct facts are needed for that, and
conflating them is how the guarantee quietly rots:

``container_digest``
    Which image actually ran. Identifies the artifact after the fact, but cannot
    be recomputed — image builds embed timestamps and layer ordering, so building
    "the same" image twice yields different digests even from identical inputs.

``environment_fingerprint``
    What the image was built *from*: base image digest, resolved dependency lock,
    interpreter version, pinned environment. This is deterministic, so two builds
    from one lockfile produce the same fingerprint, and a reviewer can check that
    the environment they reconstructed matches the one that produced the result.

Both are recorded. The fingerprint is what the M0 exit test asserts is stable;
the digest is what identifies the image that ran. Recorded as divergence 4 in
``docs/spec-divergences.md``.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from trading.runtime.determinism import PINNED_ENV
from trading.runtime.errors import ProvenanceError

#: Environment variable the container runtime injects with the running image's digest.
CONTAINER_DIGEST_ENV: Final = "TRADING_CONTAINER_DIGEST"

_DIGEST_RE: Final = re.compile(r"^sha256:[0-9a-f]{64}$")
_DOCKERENV: Final = Path("/.dockerenv")
_CGROUP: Final = Path("/proc/self/cgroup")

Provenance = Literal["container", "host"]


@dataclass(frozen=True, slots=True)
class ContainerIdentity:
    """Where this process is running, and which image it came from."""

    provenance: Provenance
    image_digest: str | None

    @property
    def is_reproducible_context(self) -> bool:
        """Whether artifacts from this process carry a usable image identity."""
        return self.provenance == "container" and self.image_digest is not None


def _is_containerized() -> bool:
    if _DOCKERENV.exists():
        return True
    try:
        cgroup = _CGROUP.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods"))


def container_identity(env: dict[str, str] | None = None) -> ContainerIdentity:
    """Report the running image's digest, as injected by the container runtime.

    The digest is supplied by whatever started the container, not baked into the
    image: a value written at build time describes the build, and an image cannot
    contain its own digest anyway.

    Args:
        env: Environment to inspect. Defaults to the live process environment.

    Raises:
        ProvenanceError: If the process is containerized but no valid digest was
            injected. Silently recording ``None`` here would produce experiment
            rows that look reproducible and are not.
    """
    source = os.environ if env is None else env
    raw = source.get(CONTAINER_DIGEST_ENV)

    if not _is_containerized():
        return ContainerIdentity(provenance="host", image_digest=raw if raw else None)

    if raw is None:
        raise ProvenanceError(
            f"running in a container but {CONTAINER_DIGEST_ENV} is unset; "
            "the runtime must inject the image digest "
            "(docker run -e TRADING_CONTAINER_DIGEST=\"$(docker image inspect -f '{{.Id}}' IMAGE)\")"
        )
    if not _DIGEST_RE.match(raw):
        raise ProvenanceError(
            f"{CONTAINER_DIGEST_ENV}={raw!r} is not a sha256 digest (expected 'sha256:<64 hex>')"
        )
    return ContainerIdentity(provenance="container", image_digest=raw)


@dataclass(frozen=True, slots=True)
class EnvironmentFingerprint:
    """A deterministic identifier for the environment an experiment ran in.

    Attributes:
        value: Hex sha256 over the canonical form of the fields below.
    """

    python_version: str
    base_image_digest: str | None
    lock_sha256: str
    pinned_env_sha256: str
    value: str

    def canonical_form(self) -> str:
        """Return the exact bytes hashed into :attr:`value`.

        Stable and inspectable on purpose: a reviewer comparing two fingerprints
        needs to see which field diverged, not just that the hashes differ.
        """
        return _canonical_form(
            python_version=self.python_version,
            base_image_digest=self.base_image_digest,
            lock_sha256=self.lock_sha256,
            pinned_env_sha256=self.pinned_env_sha256,
        )


def _canonical_form(
    *,
    python_version: str,
    base_image_digest: str | None,
    lock_sha256: str,
    pinned_env_sha256: str,
) -> str:
    fields = {
        "base_image_digest": base_image_digest or "",
        "lock_sha256": lock_sha256,
        "pinned_env_sha256": pinned_env_sha256,
        "python_version": python_version,
    }
    return "".join(f"{k}={fields[k]}\n" for k in sorted(fields))


def pinned_env_sha256() -> str:
    """Hash the declared determinism envelope.

    Changing a pinned thread count changes float reduction order, so it changes
    the environment in a way that must invalidate the fingerprint.
    """
    body = "".join(f"{k}={PINNED_ENV[k]}\n" for k in sorted(PINNED_ENV))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    """Return the hex sha256 of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def compute_environment_fingerprint(
    lock_path: Path,
    *,
    base_image_digest: str | None = None,
    python_version: str | None = None,
) -> EnvironmentFingerprint:
    """Compute the deterministic fingerprint of this environment.

    Args:
        lock_path: Path to ``uv.lock``. The resolved dependency set, not the
            declared ranges, is what makes a run reproducible.
        base_image_digest: Digest of the image the runtime was built from, pinned
            in the Dockerfile. ``None`` outside a container build.
        python_version: Defaults to the running interpreter's version.

    Raises:
        FileNotFoundError: If the lockfile is missing. An unlocked environment
            has no fingerprint worth recording.
    """
    if not lock_path.is_file():
        raise FileNotFoundError(
            f"lockfile not found at {lock_path}; run 'uv lock' — an unpinned "
            "dependency set cannot be fingerprinted"
        )

    resolved_python = python_version or platform.python_version()
    lock_hash = file_sha256(lock_path)
    env_hash = pinned_env_sha256()
    canonical = _canonical_form(
        python_version=resolved_python,
        base_image_digest=base_image_digest,
        lock_sha256=lock_hash,
        pinned_env_sha256=env_hash,
    )
    return EnvironmentFingerprint(
        python_version=resolved_python,
        base_image_digest=base_image_digest,
        lock_sha256=lock_hash,
        pinned_env_sha256=env_hash,
        value=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
