"""The canonical encoder is frozen even where the documents it encodes are not.

strategy_spec_hash sits on every experiment row and snapshot_id *is* the hash of
a manifest body. If the encoder changed, every stored hash would become
unreproducible -- the same failure as changing bytes on disk, reached another
way. These are the properties M5 will inherit wholesale when it defines the DSL.
"""

from __future__ import annotations

import json

import pytest

from trading.schemas.canonical_json import (
    ENCODER_VERSION,
    CanonicalEncodingError,
    document_hash,
    encode,
)
from trading.schemas.documents import (
    CostModel,
    FeeComponent,
    FileEntry,
    RiskPolicyDocument,
    SnapshotManifest,
    StrategySpecDocument,
)

pytestmark = pytest.mark.unit


class TestInvariance:
    def test_key_order_does_not_matter(self) -> None:
        assert encode({"b": 1, "a": 2}) == encode({"a": 2, "b": 1})

    def test_nested_key_order_does_not_matter(self) -> None:
        assert encode({"x": {"b": 1, "a": 2}}) == encode({"x": {"a": 2, "b": 1}})

    def test_unicode_is_normalised(self) -> None:
        """Two visually identical strings must not hash differently."""
        composed = "é"
        decomposed = "é"
        assert composed != decomposed
        assert encode({"t": composed}) == encode({"t": decomposed})

    def test_output_has_no_insignificant_whitespace(self) -> None:
        assert " " not in encode({"a": 1, "b": [1, 2]})


class TestSensitivity:
    def test_a_changed_value_changes_the_hash(self) -> None:
        assert document_hash({"a": 1}) != document_hash({"a": 2})

    def test_list_order_is_significant(self) -> None:
        """Order matters in a list even though it does not in a mapping."""
        assert document_hash({"a": [1, 2]}) != document_hash({"a": [2, 1]})

    def test_a_null_differs_from_a_missing_key(self) -> None:
        assert document_hash({"a": None}) != document_hash({})

    def test_types_are_distinguished(self) -> None:
        assert document_hash({"a": 1}) != document_hash({"a": "1"})
        assert document_hash({"a": True}) != document_hash({"a": 1})


class TestFloatsAreRejected:
    def test_top_level(self) -> None:
        with pytest.raises(CanonicalEncodingError, match="not reproducible"):
            encode({"rate": 0.1})

    def test_nested(self) -> None:
        with pytest.raises(CanonicalEncodingError, match=r"\$\.a\.b"):
            encode({"a": {"b": 1.5}})

    def test_inside_a_list(self) -> None:
        with pytest.raises(CanonicalEncodingError):
            encode({"a": [1, 2.5]})

    def test_the_message_says_what_to_use_instead(self) -> None:
        with pytest.raises(CanonicalEncodingError, match="exact rational"):
            encode({"rate": 0.5})


_ENTRY_FIELDS = frozenset(
    {"path", "row_count", "file_sha256", "content_sha256", "contract", "contract_version"}
)


def _entry(**overrides: object) -> FileEntry:
    base: dict[str, object] = {
        "path": "normalized/trade/date=2026-09-19/part-000.parquet",
        "row_count": 2,
        "file_sha256": "a" * 64,
        "content_sha256": "b" * 64,
        "contract": "normalized.trade",
        "contract_version": 1,
    }
    return FileEntry(**(base | overrides))  # type: ignore[arg-type]


def _manifest(**overrides: object) -> SnapshotManifest:
    """One-file manifest; overrides route to the entry or the manifest by name."""
    entry = {k: v for k, v in overrides.items() if k in _ENTRY_FIELDS}
    manifest = {k: v for k, v in overrides.items() if k not in _ENTRY_FIELDS}
    base: dict[str, object] = {"calendar_version": "xnys_v1"}
    return SnapshotManifest(files=(_entry(**entry),), **(base | manifest))  # type: ignore[arg-type]


class TestDocuments:
    def test_snapshot_id_is_not_the_full_body_hash(self) -> None:
        """Identity and integrity answer different questions (divergence 11)."""
        manifest = _manifest()
        assert manifest.snapshot_id() != manifest.canonical_hash()

    def test_file_sha256_alone_does_not_change_the_snapshot_id(self) -> None:
        """A pyarrow upgrade moves file_sha256 without a single row changing.

        If that moved snapshot_id, every experiment in the corpus would be
        invalidated by a routine dependency bump, and §40's promise that a
        result is reproducible from its experiment id would not hold.
        """
        assert (
            _manifest(file_sha256="a" * 64).snapshot_id()
            == _manifest(file_sha256="d" * 64).snapshot_id()
        )

    def test_file_sha256_is_still_covered_by_the_integrity_hash(self) -> None:
        """Excluding it from identity must not stop it detecting corruption."""
        assert (
            _manifest(file_sha256="a" * 64).canonical_hash()
            != _manifest(file_sha256="d" * 64).canonical_hash()
        )

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("content_sha256", "0" * 64),
            ("row_count", 99),
            ("path", "other.parquet"),
            ("contract", "normalized.quote"),
            ("contract_version", 2),
        ],
    )
    def test_changing_file_content_changes_the_snapshot_id(self, field: str, value: object) -> None:
        """Everything that describes *what data this is* must move the identity."""
        assert _manifest().snapshot_id() != _manifest(**{field: value}).snapshot_id()

    @pytest.mark.parametrize(
        "field",
        [
            "calendar_version",
            "corporate_action_version",
            "cost_model_id",
            "data_quality_report_sha256",
            "license_id",
        ],
    )
    def test_changing_a_semantic_manifest_field_changes_the_snapshot_id(self, field: str) -> None:
        """A different calendar or cost model is a different snapshot (§8)."""
        assert _manifest().snapshot_id() != _manifest(**{field: "changed"}).snapshot_id()

    def test_adding_a_file_changes_the_snapshot_id(self) -> None:
        base = _manifest()
        extended = SnapshotManifest(
            files=(*base.files, _entry(path="second.parquet")),
            calendar_version=base.calendar_version,
        )
        assert base.snapshot_id() != extended.snapshot_id()

    def test_file_listing_order_does_not_change_the_snapshot_id(self) -> None:
        """Listing order is how the manifest was assembled, not what the data is."""
        first, second = _entry(path="a.parquet"), _entry(path="b.parquet")
        forward = SnapshotManifest(files=(first, second))
        reverse = SnapshotManifest(files=(second, first))
        assert forward.snapshot_id() == reverse.snapshot_id()

    def test_duplicate_paths_are_rejected(self) -> None:
        """Two entries for one path leave the snapshot ambiguous."""
        with pytest.raises(ValueError, match="duplicate paths"):
            SnapshotManifest(files=(_entry(), _entry()))

    def test_identity_body_excludes_file_sha256(self) -> None:
        """Stated structurally, so the exclusion cannot be undone by accident."""
        body = _manifest().identity_body()
        assert "file_sha256" not in json.dumps(body)
        assert "content_sha256" in json.dumps(body)

    def test_snapshot_id_is_a_sha256(self) -> None:
        assert len(_manifest().snapshot_id()) == 64

    def test_cost_model_rates_are_rationals(self) -> None:
        """A published fee schedule is exact; a float would destabilise the hash."""
        model = CostModel(
            cost_model_id="execution_cost_v0",
            components=(
                FeeComponent(name="sec_fee", rate_numerator=51, rate_denominator=10_000_000),
            ),
        )
        assert model.canonical_hash()

    def test_strategy_hash_is_stable(self) -> None:
        spec = StrategySpecDocument(strategy_id="s", family_id="f", body={"a": 1, "b": 2})
        other = StrategySpecDocument(strategy_id="s", family_id="f", body={"b": 2, "a": 1})
        assert spec.strategy_spec_hash() == other.strategy_spec_hash()

    def test_documents_reject_unknown_fields(self) -> None:
        # Validated from a mapping rather than keyword arguments: mypy would
        # (correctly) reject the bad keyword statically, and the runtime guard
        # is what this asserts.
        with pytest.raises(ValueError, match=r"[Ee]xtra"):
            RiskPolicyDocument.model_validate({"policy_version": "v1", "not_a_limit": 1})

    def test_documents_are_frozen(self) -> None:
        policy = RiskPolicyDocument(policy_version="v1")
        with pytest.raises(ValueError, match=r"[Ff]rozen"):
            policy.policy_version = "v2"

    def test_risk_limits_cannot_be_negative(self) -> None:
        with pytest.raises(ValueError, match="greater than or equal to 0"):
            RiskPolicyDocument(daily_loss_limit_nav_bps=-1)


def test_encoder_version_is_recorded() -> None:
    """Bumping it invalidates every stored hash, so it must be visible."""
    assert ENCODER_VERSION == 1
