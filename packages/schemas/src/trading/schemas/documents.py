"""Documents that are hashed rather than tabulated.

A snapshot manifest, a cost model, a strategy specification: nested, read whole,
and identified by the hash of their content. They are Pydantic models rather than
Arrow contracts because they are not tables — there is no column layout to fix
and no partition to write.

All are PROVISIONAL. Their field sets settle at the milestone that implements
them: the manifest at M2, the cost model at M3, feature specs at M4, strategies
at M5, risk policies at M8. What is *not* provisional is
:mod:`trading.schemas.canonical_json` — the encoder that turns any of them into
bytes is frozen now, because the hashes it produces are stored on experiment rows
and would otherwise become unreproducible.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading.schemas.canonical_json import document_hash


class _Document(BaseModel):
    """Base for hashed documents: frozen, and no silently ignored fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_hash(self) -> str:
        """Hash the document's full body through the frozen canonical encoder.

        For a snapshot manifest this is the *integrity* hash, covering every
        field including serialization details. Identity is a narrower question —
        see :meth:`SnapshotManifest.snapshot_id`.
        """
        return document_hash(self.model_dump(mode="json"))


class FileEntry(_Document):
    """One file inside a snapshot (D10)."""

    path: str
    """Path relative to the snapshot root."""
    row_count: int
    """Rows written, from the writer's receipt."""
    file_sha256: str
    """Integrity only. Detects corruption, and moves whenever the parquet
    writer's version moves, so it is deliberately excluded from
    :meth:`identity`."""
    content_sha256: str
    """Logical identity: the Arrow encoding of the data itself, independent of
    writer version and of chunking."""
    contract: str
    """Which contract the file was written under."""
    contract_version: int

    def identity(self) -> dict[str, Any]:
        """The fields that define *what data this is*.

        Everything here changes only when the underlying market data or its
        interpretation changes. ``file_sha256`` is absent on purpose: it is a
        property of how the bytes were serialized, not of what they mean, and a
        parquet writer upgrade moves it without a single row changing.
        """
        return {
            "path": self.path,
            "row_count": self.row_count,
            "content_sha256": self.content_sha256,
            "contract": self.contract,
            "contract_version": self.contract_version,
        }


class SnapshotManifest(_Document):
    """An immutable, content-addressed view of the data an experiment saw (§8, D10).

    PROVISIONAL until M2 builds the snapshot machinery.
    """

    files: tuple[FileEntry, ...] = ()
    calendar_version: str = ""
    """Recorded because the exchange calendar is authoritative for sessions (§7)."""
    corporate_action_version: str = ""
    cost_model_id: str = ""
    data_quality_report_sha256: str = ""
    license_id: str = ""
    """Market-data entitlements govern storage and derived data (§34)."""

    @model_validator(mode="after")
    def _paths_are_unique(self) -> SnapshotManifest:
        paths = [entry.path for entry in self.files]
        duplicates = sorted({path for path in paths if paths.count(path) > 1})
        if duplicates:
            raise ValueError(
                f"duplicate paths in manifest: {duplicates}. Two entries for one "
                "path make the snapshot ambiguous about which bytes an "
                "experiment read."
            )
        return self

    def identity_body(self) -> dict[str, Any]:
        """The fields :meth:`snapshot_id` hashes.

        Files are sorted by path, so two manifests listing the same files in a
        different order describe the same snapshot and hash identically —
        listing order is an artifact of how the manifest was assembled, not a
        property of the data.
        """
        return {
            "calendar_version": self.calendar_version,
            "corporate_action_version": self.corporate_action_version,
            "cost_model_id": self.cost_model_id,
            "data_quality_report_sha256": self.data_quality_report_sha256,
            "files": [entry.identity() for entry in sorted(self.files, key=lambda f: f.path)],
            "license_id": self.license_id,
        }

    def snapshot_id(self) -> str:
        """The snapshot's identity (D10).

        Hashes :meth:`identity_body`, which carries each file's
        ``content_sha256`` and every semantic manifest field, and deliberately
        omits ``file_sha256``.

        The reason is that snapshot identity must track the data an experiment
        read, not the encoding it happened to be stored in. Parquet embeds its
        writer's version in the file footer, so including ``file_sha256`` would
        make a routine pyarrow upgrade change the identity of every snapshot in
        the corpus — invalidating experiments nobody touched and breaking §40's
        promise that a result can be reproduced from its experiment id.

        Integrity is not lost by this: ``file_sha256`` is still recorded on every
        entry and still hashed into :meth:`canonical_hash`, which is what detects
        a corrupted or tampered file.
        """
        return document_hash(self.identity_body())


class FeeComponent(_Document):
    """One effective-dated cost term, as an exact rational (§17)."""

    name: str
    rate_numerator: int
    rate_denominator: int = 1
    """A rational, never a float: a published fee schedule is exact, and a
    float would make the cost model's hash unstable."""
    basis: Literal["per_share", "per_notional", "per_order"] = "per_share"
    effective_from_ns: int = 0


class CostModel(_Document):
    """Versioned, effective-dated cost schedule (§17, §39).

    PROVISIONAL until M3 gives it a v0 and M8 calibrates it. Referenced by id
    from the experiment manifest so net PnL can be recomputed when a schedule
    changes.
    """

    cost_model_id: str = ""
    components: tuple[FeeComponent, ...] = ()


class FeatureSpecDocument(_Document):
    """A feature's definition (§12). PROVISIONAL until M4."""

    feature_id: str = ""
    version: int = 1
    inputs: tuple[str, ...] = ()
    decision_clock: str = ""
    lookback_ns: int = 0
    availability_lag_ns: int = 0
    """§12's example is 250ms against a 1m clock. The inverse -- a lag longer
    than the clock spacing -- is the most common real leak and is statically
    detectable, which is why the compiler will check it at M5."""
    missing_policy: str = "null"
    valid_range: tuple[int, int] | None = None


class StrategySpecDocument(_Document):
    """A compiled strategy (§13). PROVISIONAL until M5 defines the DSL.

    Only ``strategy_spec_hash`` is load-bearing now: it is stored on every
    experiment row, so the *encoder* is frozen even though these fields are not.
    """

    strategy_id: str = ""
    family_id: str = ""
    """Declared immutably at hypothesis creation and never derived from
    similarity (D8): a multiple-testing penalty must not depend on an embedding
    threshold."""
    body: dict[str, Any] = Field(default_factory=dict)

    def strategy_spec_hash(self) -> str:
        return self.canonical_hash()


class RiskPolicyDocument(_Document):
    """Signed risk limits (§25). PROVISIONAL until M8.

    A strategy may tighten these and never loosen them (§13); the envelope is
    enforced by construction at compile time rather than checked afterwards.
    """

    policy_version: str = ""
    max_position_nav_bps: Annotated[int, Field(ge=0)] = 200
    max_gross_exposure_nav_bps: Annotated[int, Field(ge=0)] = 5_000
    max_net_exposure_nav_bps: Annotated[int, Field(ge=0)] = 2_000
    daily_loss_limit_nav_bps: Annotated[int, Field(ge=0)] = 50
    risk_per_trade_nav_bps: Annotated[int, Field(ge=0)] = 5
