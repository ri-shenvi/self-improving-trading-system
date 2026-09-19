"""The naive-datetime detector must fire before there is anything to find.

packages/schemas has no models yet, so the repository-wide audit passes
vacuously. That is exactly when a detector rots, so it is proven here against
models written to violate it.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import AwareDatetime, BaseModel
from tools.model_audit import audit, naive_datetime_fields

pytestmark = pytest.mark.unit


class NaiveRow(BaseModel):
    event_time: dt.datetime


class OptionalNaiveRow(BaseModel):
    revision_time: dt.datetime | None = None


class NestedNaiveRow(BaseModel):
    corrections: dict[str, dt.datetime] = {}


class AwareRow(BaseModel):
    event_time: AwareDatetime


class NanosecondRow(BaseModel):
    event_time_ns: int
    session: dt.date


@pytest.mark.parametrize("model", [NaiveRow, OptionalNaiveRow, NestedNaiveRow])
def test_detects_fields_admitting_naive_values(model: type[BaseModel]) -> None:
    assert naive_datetime_fields(model)


def test_accepts_aware_datetimes() -> None:
    """AwareDatetime rejects naive values at validation, which is the real property."""
    assert naive_datetime_fields(AwareRow) == []


def test_accepts_nanosecond_integers_and_dates() -> None:
    assert naive_datetime_fields(NanosecondRow) == []


def test_finding_names_the_model_and_field() -> None:
    (finding,) = naive_datetime_fields(NaiveRow)
    assert finding.field == "event_time"
    assert finding.model.endswith("NaiveRow")
    assert "D3" in finding.render()


def test_repository_models_are_clean() -> None:
    findings = audit()
    assert findings == [], "\n".join(f.render() for f in findings)
