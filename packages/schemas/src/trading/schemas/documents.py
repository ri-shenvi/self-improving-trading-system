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

from pydantic import BaseModel, ConfigDict, Field

from trading.schemas.canonical_json import document_hash


class _Document(BaseModel):
    """Base for hashed documents: frozen, and no silently ignored fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def canonical_hash(self) -> str:
        """Hash through the frozen canonical encoder."""
        return document_hash(self.model_dump(mode="json"))


class FileEntry(_Document):
    """One file inside a snapshot (D10)."""

    path: str
    """Path relative to the snapshot root."""
    row_count: int
    """Rows written, from the writer's receipt."""
    file_sha256: str
    """Integrity. Moves when the parquet writer's version moves."""
    content_sha256: str
    """Logical identity. Independent of writer version, so a pyarrow upgrade
    does not invalidate a snapshot nobody touched."""
    contract: str
    """Which contract the file was written under."""
    contract_version: int


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

    def snapshot_id(self) -> str:
        """The snapshot's identity, which *is* the hash of this body (D10).

        Derived from each file's ``content_sha256`` rather than ``file_sha256``,
        so upgrading the parquet writer does not change the identity of data
        that has not changed.
        """
        return self.canonical_hash()


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
