"""Reading a snapshot, and refusing to read anything else (D10).

§16's "as-was data" invariant says a historical replay uses the snapshot
available to that experiment, not silently revised current files. A manifest
alone does not enforce that: it records what *should* be read, and every future
author has to remember to consult it.

:class:`SnapshotReader` makes it structural. It refuses to open any path the
manifest does not list, so reaching outside a snapshot is an error rather than an
oversight. That refusal is the whole point of the class.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from trading.market_data.snapshot.builder import SnapshotError, load_manifest
from trading.schemas.documents import FileEntry, SnapshotManifest
from trading.schemas.io import read_contract_table
from trading.schemas.registry import get


class UnlistedPathError(SnapshotError):
    """An attempt to read a path the manifest does not list.

    Almost always one of two things: reading live data from inside a historical
    replay, or reading a file written after the snapshot was sealed. Both are
    leakage, and both look like ordinary file access at the call site -- which is
    why this is enforced rather than documented.
    """


class SnapshotReader:
    """Bounded read access to one snapshot."""

    def __init__(self, root: Path, manifest: SnapshotManifest | None = None) -> None:
        self.root = root
        self.manifest = manifest if manifest is not None else load_manifest(root)
        self._listed = {entry.path: entry for entry in self.manifest.files}

    @property
    def snapshot_id(self) -> str:
        return self.manifest.snapshot_id()

    def paths(self) -> tuple[str, ...]:
        """Every path this snapshot permits, in manifest order."""
        return tuple(sorted(self._listed))

    def paths_for(self, contract: str) -> tuple[str, ...]:
        """Paths written under one contract."""
        return tuple(
            sorted(path for path, entry in self._listed.items() if entry.contract == contract)
        )

    def _entry(self, path: str) -> FileEntry:
        """Return a listed file's manifest entry, or refuse.

        Every read goes through here, so the refusal cannot be bypassed by
        reaching for a different accessor.
        """
        entry = self._listed.get(path)
        if entry is None:
            raise UnlistedPathError(
                f"{path!r} is not in snapshot {self.snapshot_id[:12]}. A replay may "
                "only read what the snapshot lists -- reaching outside it is how a "
                "backtest reads data that did not exist at the decision time (§16)."
            )
        return entry

    def resolve(self, path: str) -> Path:
        """Return the absolute path for a listed file.

        Raises:
            UnlistedPathError: If the manifest does not list ``path``.
        """
        return self.root / self._entry(path).path

    def read(self, path: str) -> pa.Table:
        """Read one listed file, validated against the contract it was written under."""
        entry = self._entry(path)
        table = read_contract_table(self.root / entry.path, get(entry.contract))
        if table.num_rows != entry.row_count:
            raise SnapshotError(
                f"{path}: manifest says {entry.row_count} rows, file has "
                f"{table.num_rows}. The snapshot and its data disagree."
            )
        return table

    def read_contract(self, contract: str) -> pa.Table:
        """Read and concatenate every file written under one contract."""
        paths = self.paths_for(contract)
        if not paths:
            raise SnapshotError(f"snapshot {self.snapshot_id[:12]} has no {contract} files")
        return pa.concat_tables([self.read(path) for path in paths])
