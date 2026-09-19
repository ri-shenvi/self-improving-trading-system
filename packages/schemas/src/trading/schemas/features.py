"""Computed feature values (§12). PROVISIONAL until M4 builds the registry."""

from __future__ import annotations

from trading.schemas.registry import register
from trading.schemas.spec import (
    ContractSpec,
    FieldKind,
    FieldSpec,
    Maturity,
    TimeGroup,
    time_fields,
)

FEATURE_VALUE = register(
    ContractSpec(
        name="features.value",
        version=1,
        maturity=Maturity.PROVISIONAL,
        doc="One feature's value for one instrument at one decision time (§12).",
        time_group=TimeGroup.CORE,
        fields=(
            *time_fields(TimeGroup.CORE),
            FieldSpec("feature_id", FieldKind.TEXT, doc="Registry identifier."),
            FieldSpec(
                "feature_version",
                FieldKind.COUNT,
                doc="Features are immutable and versioned; a changed definition "
                "is a new version, never an edit to an existing one.",
            ),
            FieldSpec("instrument_id", FieldKind.INSTRUMENT_ID, doc="Instrument."),
            FieldSpec(
                "decision_time",
                FieldKind.TIMESTAMP_NS,
                unit="ns_utc",
                doc="The clock instant this value is for. Composition is only "
                "legal where a value's knowledge_time is at or before the "
                "consumer's decision_time (§12).",
            ),
            FieldSpec(
                "value",
                FieldKind.RATIO,
                nullable=True,
                doc="Null where the feature's missing policy yields no value. "
                "A float because a feature is a statistic, never money.",
            ),
        ),
    )
)
