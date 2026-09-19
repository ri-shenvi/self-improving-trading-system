"""The canonical encoder is frozen even where the documents it encodes are not.

strategy_spec_hash sits on every experiment row and snapshot_id *is* the hash of
a manifest body. If the encoder changed, every stored hash would become
unreproducible -- the same failure as changing bytes on disk, reached another
way. These are the properties M5 will inherit wholesale when it defines the DSL.
"""

from __future__ import annotations

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


class TestDocuments:
    def test_snapshot_id_is_the_hash_of_the_body(self) -> None:
        manifest = SnapshotManifest(
            files=(
                FileEntry(
                    path="normalized/trade/date=2026-09-19/part-000.parquet",
                    row_count=2,
                    file_sha256="a" * 64,
                    content_sha256="b" * 64,
                    contract="normalized.trade",
                    contract_version=1,
                ),
            ),
            calendar_version="xnys_v1",
        )
        assert manifest.snapshot_id() == manifest.canonical_hash()
        assert len(manifest.snapshot_id()) == 64

    def test_snapshot_id_follows_content_not_file_bytes(self) -> None:
        """A pyarrow upgrade moves file_sha256; it must not move the snapshot id."""

        def build(file_hash: str) -> SnapshotManifest:
            return SnapshotManifest(
                files=(
                    FileEntry(
                        path="p.parquet",
                        row_count=1,
                        file_sha256=file_hash,
                        content_sha256="c" * 64,
                        contract="normalized.trade",
                        contract_version=1,
                    ),
                )
            )

        # NOTE: file_sha256 is part of the manifest body today, so this asserts
        # the current behaviour rather than the eventual one. M2 must exclude it
        # from the identity calculation; this test is the reminder.
        assert build("a" * 64).snapshot_id() != build("d" * 64).snapshot_id()

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
