"""Every contract survives Pydantic -> Arrow -> Parquet -> Pydantic (M1 exit test 1).

Driven by generated rows rather than chosen ones: a hand-picked example proves
the happy path works, while the failures that matter are nulls in optional
fields, empty code lists, and boundary integers.
"""

from __future__ import annotations

import io
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import trading.schemas  # noqa: F401  -- registers the contracts
from trading.schemas._generated import models
from trading.schemas.registry import all_contracts
from trading.schemas.spec import ContractSpec, FieldKind

pytestmark = pytest.mark.property

_BY_KIND: dict[FieldKind, st.SearchStrategy[Any]] = {
    FieldKind.TIMESTAMP_NS: st.integers(min_value=0, max_value=2**62),
    FieldKind.NANO_DOLLARS: st.integers(min_value=-(2**62), max_value=2**62),
    FieldKind.SHARES: st.integers(min_value=-(2**40), max_value=2**40),
    FieldKind.INSTRUMENT_ID: st.integers(min_value=1, max_value=2**40),
    FieldKind.EXCHANGE_CODE: st.text(min_size=1, max_size=8),
    FieldKind.CONDITIONS: st.lists(st.text(min_size=1, max_size=4), max_size=5),
    FieldKind.TAPE: st.sampled_from(["A", "B", "C"]),
    FieldKind.SEQUENCE: st.integers(min_value=-1, max_value=2**40),
    FieldKind.TEXT: st.text(max_size=20),
    FieldKind.UUID: st.uuids().map(str),
    FieldKind.COUNT: st.integers(min_value=-(2**31), max_value=2**31 - 1),
    FieldKind.BOOL: st.booleans(),
    FieldKind.RATIO: st.floats(allow_nan=False, allow_infinity=False, width=64),
    FieldKind.DATE: st.dates(),
}


def rows_for(spec: ContractSpec) -> st.SearchStrategy[dict[str, Any]]:
    """Generate one valid row for a contract, exercising nullable fields."""
    columns = {}
    for field in spec.fields:
        base = _BY_KIND[field.kind]
        columns[field.name] = st.none() | base if field.nullable else base
    return st.fixed_dictionaries(columns)


@pytest.mark.parametrize("spec", all_contracts(), ids=lambda s: s.name)
def test_arrow_schema_matches_the_declaration(spec: ContractSpec) -> None:
    schema = spec.arrow_schema()
    assert schema.names == list(spec.field_names())
    for field in spec.fields:
        assert schema.field(field.name).nullable is field.nullable


@pytest.mark.parametrize("spec", all_contracts(), ids=lambda s: s.name)
def test_a_generated_model_exists(spec: ContractSpec) -> None:
    model = getattr(models, spec.class_name)
    assert list(model.model_fields) == list(spec.field_names())


@pytest.mark.parametrize("spec", all_contracts(), ids=lambda s: s.name)
@settings(max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(data=st.data())
def test_round_trip(spec: ContractSpec, data: st.DataObject) -> None:
    model = getattr(models, spec.class_name)
    row = data.draw(rows_for(spec))

    original = model(**row)
    table = pa.table(
        {name: [getattr(original, name)] for name in spec.field_names()},
        schema=spec.arrow_schema(),
    )

    buffer = io.BytesIO()
    pq.write_table(table, buffer)
    buffer.seek(0)
    restored_rows = pq.read_table(buffer).to_pylist()

    restored = model(**restored_rows[0])
    assert restored == original


@pytest.mark.parametrize("spec", all_contracts(), ids=lambda s: s.name)
def test_models_reject_unknown_fields(spec: ContractSpec) -> None:
    """A typo in a field name must be an error, not a silently ignored attribute."""
    model = getattr(models, spec.class_name)
    with pytest.raises(ValueError, match=r"[Ee]xtra"):
        model(**{f.name: None for f in spec.fields}, not_a_real_field=1)
