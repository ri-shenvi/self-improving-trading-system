"""Building and verifying snapshot manifests (§8, D10).

A manifest is assembled from the writer's receipts rather than by re-walking the
output directory and hashing whatever is found. That matters: re-hashing would
let a file the writer never validated slip into a snapshot, which is exactly the
gap the sanctioned writer exists to close.

Identity and integrity stay separate throughout. ``snapshot_id`` depends only on
the data and the semantic manifest fields; ``verify_snapshot`` checks the bytes.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from trading.schemas.documents import FileEntry, SnapshotManifest
from trading.schemas.io import WriteReceipt

MANIFEST_NAME = "manifest.json"


class SnapshotError(RuntimeError):
    """A snapshot is missing, incomplete, or does not match its manifest."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One way a snapshot's bytes disagree with its manifest."""

    path: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}: {self.detail}"


def build_manifest(
    receipts: Iterable[WriteReceipt],
    root: Path,
    *,
    calendar_version: str = "",
    corporate_action_version: str = "",
    cost_model_id: str = "",
    data_quality_report_sha256: str = "",
    license_id: str = "",
) -> SnapshotManifest:
    """Assemble a manifest from write receipts.

    Args:
        receipts: One per file written, carrying the hashes the writer computed.
        root: Snapshot root; paths are recorded relative to it, so a snapshot
            can be moved or re-materialized elsewhere without changing identity.
    """
    entries = []
    for receipt in receipts:
        try:
            relative = receipt.path.relative_to(root)
        except ValueError as exc:
            raise SnapshotError(
                f"{receipt.path} is outside the snapshot root {root}. Paths are "
                "recorded relative to the root so a snapshot keeps its identity "
                "when re-materialized elsewhere."
            ) from exc
        entries.append(
            FileEntry(
                path=relative.as_posix(),
                row_count=receipt.row_count,
                file_sha256=receipt.file_sha256,
                content_sha256=receipt.content_sha256,
                contract=receipt.contract,
                contract_version=receipt.contract_version,
            )
        )

    return SnapshotManifest(
        files=tuple(sorted(entries, key=lambda entry: entry.path)),
        calendar_version=calendar_version,
        corporate_action_version=corporate_action_version,
        cost_model_id=cost_model_id,
        data_quality_report_sha256=data_quality_report_sha256,
        license_id=license_id,
    )


def write_manifest(manifest: SnapshotManifest, root: Path) -> Path:
    """Write a manifest under its own snapshot id, and return the path."""
    destination = root / MANIFEST_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return destination


def load_manifest(root: Path) -> SnapshotManifest:
    """Read the manifest at a snapshot root."""
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise SnapshotError(f"no {MANIFEST_NAME} at {root}")
    return SnapshotManifest.model_validate_json(path.read_text(encoding="utf-8"))


def verify_snapshot(manifest: SnapshotManifest, root: Path) -> Sequence[Finding]:
    """Check that every listed file is present and byte-identical.

    Uses ``file_sha256``, which is what detects corruption. A file whose bytes
    changed fails here even though ``snapshot_id`` would be unmoved by a
    writer-version change -- the two hashes answer different questions and both
    are checked.
    """
    findings: list[Finding] = []
    for entry in manifest.files:
        path = root / entry.path
        if not path.is_file():
            findings.append(Finding(entry.path, "listed in the manifest but missing on disk"))
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry.file_sha256:
            findings.append(
                Finding(
                    entry.path,
                    f"bytes changed since the snapshot was built "
                    f"(manifest {entry.file_sha256[:12]}, on disk {digest[:12]})",
                )
            )
    return findings
