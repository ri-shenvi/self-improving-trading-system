"""The contract registry: every declared contract, and the lock that pins it.

A contract's shape is checked into ``registry/contracts.json`` alongside its
hash. ``make verify`` recomputes and compares, so changing a field without
bumping the version fails CI with a diff naming the field.

The lock stores each contract's full canonical form, not just its hash. Two hex
strings differing tells a reviewer nothing; the canonical form makes the change
itself reviewable in the diff of the lock file, which is the point — the lock is
a review artifact, not a checksum.

Contracts self-register at import. ``trading.schemas`` imports every contract
module, so importing the package yields a complete registry.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

from trading.schemas.spec import ContractSpec, Maturity, emitter_version

__all__ = [
    "LOCK_PATH",
    "Finding",
    "Lock",
    "LockEntry",
    "Maturity",
    "RegistryError",
    "all_contracts",
    "check",
    "get",
    "load_lock",
    "lock_body",
    "register",
    "render_lock",
]

# .../packages/schemas/src/trading/schemas/registry.py -> .../packages/schemas
LOCK_PATH: Final = Path(__file__).resolve().parents[3] / "registry" / "contracts.json"


class LockEntry(TypedDict):
    """One contract as recorded in the lock."""

    version: int
    maturity: str
    hash: str
    canonical: str


class Lock(TypedDict):
    """The checked-in lock file."""

    emitter_version: str
    contracts: dict[str, LockEntry]


_CONTRACTS: Final[dict[str, ContractSpec]] = {}


class RegistryError(RuntimeError):
    """The declared contracts and the checked-in lock disagree."""


def register(spec: ContractSpec) -> ContractSpec:
    """Add a contract to the registry, returning it for module-level binding."""
    if spec.name in _CONTRACTS:
        raise RegistryError(f"contract {spec.name!r} is registered twice")
    _CONTRACTS[spec.name] = spec
    return spec


def get(name: str) -> ContractSpec:
    try:
        return _CONTRACTS[name]
    except KeyError:
        raise RegistryError(f"no contract named {name!r}") from None


def all_contracts() -> tuple[ContractSpec, ...]:
    """Every registered contract, in name order."""
    return tuple(_CONTRACTS[name] for name in sorted(_CONTRACTS))


@dataclass(frozen=True, slots=True)
class Finding:
    """One disagreement between the declared contracts and the lock."""

    contract: str
    detail: str

    def __str__(self) -> str:
        return f"{self.contract}: {self.detail}"


def lock_body(contracts: tuple[ContractSpec, ...] | None = None) -> Lock:
    """Render contracts as the lock file's content. Defaults to the registry."""
    specs = all_contracts() if contracts is None else contracts
    return Lock(
        emitter_version=emitter_version(),
        contracts={
            spec.name: LockEntry(
                version=spec.version,
                maturity=spec.maturity.value,
                hash=spec.content_hash(),
                canonical=spec.canonical_form(),
            )
            for spec in specs
        },
    )


def render_lock(contracts: tuple[ContractSpec, ...] | None = None) -> str:
    return json.dumps(lock_body(contracts), indent=2, sort_keys=True) + "\n"


def load_lock(path: Path = LOCK_PATH) -> Lock:
    if not path.is_file():
        return Lock(emitter_version="", contracts={})
    loaded: Lock = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def check(
    path: Path = LOCK_PATH, contracts: tuple[ContractSpec, ...] | None = None
) -> list[Finding]:
    """Compare declared contracts against the lock.

    Returns findings in a deliberate order: the emitter check first, because a
    changed type mapping invalidates every contract at once and reporting a
    hundred per-contract diffs would bury the one cause.
    """
    specs = all_contracts() if contracts is None else contracts
    lock = load_lock(path)
    locked: dict[str, LockEntry] = dict(lock["contracts"])
    findings: list[Finding] = []

    if lock["emitter_version"] != emitter_version():
        findings.append(
            Finding(
                "<emitter>",
                "the FieldKind-to-Arrow mapping changed, so every contract's bytes "
                "may have changed even where no contract was edited. Review "
                "trading.schemas.spec, then re-accept the whole registry.",
            )
        )

    for spec in specs:
        entry = locked.pop(spec.name, None)
        if entry is None:
            findings.append(Finding(spec.name, "declared but not in the lock; run --accept"))
            continue

        if entry["hash"] == spec.content_hash():
            continue

        diff = "\n".join(
            difflib.unified_diff(
                entry["canonical"].splitlines(),
                spec.canonical_form().splitlines(),
                fromfile=f"{spec.name} (locked v{entry['version']})",
                tofile=f"{spec.name} (declared v{spec.version})",
                lineterm="",
            )
        )
        if entry["version"] == spec.version:
            frozen = entry["maturity"] == Maturity.FROZEN.value
            findings.append(
                Finding(
                    spec.name,
                    f"shape changed but version is still {spec.version}.\n{diff}\n"
                    + (
                        "This contract is FROZEN: files already written under "
                        f"version {spec.version} will not be readable under the new "
                        "shape. Bump the version, then re-accept with "
                        '--break-frozen "<reason>".'
                        if frozen
                        else "Bump the version, then re-accept."
                    ),
                )
            )
        else:
            findings.append(
                Finding(
                    spec.name,
                    f"version bumped {entry['version']} -> {spec.version}; "
                    f"re-accept to record it.\n{diff}",
                )
            )

    findings.extend(
        Finding(
            name,
            "in the lock but no longer declared; removing a contract "
            "orphans every file written under it",
        )
        for name in sorted(locked)
    )
    return findings
