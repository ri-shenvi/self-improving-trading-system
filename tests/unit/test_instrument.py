"""A ticker resolves to whichever instrument held it *then*, or to nothing (D6)."""

from __future__ import annotations

import pytest

from trading.schemas.identifiers import InstrumentId
from trading.schemas.instrument import (
    TickerAssignment,
    TickerResolutionError,
    resolve_ticker,
)
from trading.schemas.time import TimestampNs, parse_rfc3339_ns

pytestmark = pytest.mark.unit

ACME = InstrumentId(1)
ZENITH = InstrumentId(2)

T2019 = parse_rfc3339_ns("2019-01-01T00:00:00Z")
T2022 = parse_rfc3339_ns("2022-01-01T00:00:00Z")
T2024 = parse_rfc3339_ns("2024-01-01T00:00:00Z")

#: The case the whole design exists for: one symbol, two companies, two eras.
REUSED = [
    TickerAssignment(ACME, "XYZ", effective_time=T2019, end_time=T2022),
    TickerAssignment(ZENITH, "XYZ", effective_time=T2022),
]


class TestReuse:
    def test_resolves_to_the_holder_at_that_time(self) -> None:
        assert resolve_ticker(REUSED, "XYZ", T2019) == ACME
        assert resolve_ticker(REUSED, "XYZ", T2024) == ZENITH

    def test_the_same_ticker_gives_different_instruments_across_eras(self) -> None:
        """Joining on the symbol would splice two companies' histories together."""
        assert resolve_ticker(REUSED, "XYZ", T2019) != resolve_ticker(REUSED, "XYZ", T2024)

    def test_intervals_are_half_open(self) -> None:
        """At the reassignment instant the ticker belongs to exactly one instrument."""
        assert resolve_ticker(REUSED, "XYZ", T2022) == ZENITH

    def test_resolution_order_does_not_matter(self) -> None:
        assert resolve_ticker(list(reversed(REUSED)), "XYZ", T2019) == ACME


class TestFailures:
    def test_before_any_assignment_raises(self) -> None:
        """Falling back to the current master would be survivorship bias."""
        with pytest.raises(TickerResolutionError, match="no instrument held"):
            resolve_ticker(REUSED, "XYZ", TimestampNs(T2019 - 1))

    def test_unknown_ticker_raises(self) -> None:
        with pytest.raises(TickerResolutionError):
            resolve_ticker(REUSED, "NOPE", T2024)

    def test_overlapping_assignments_raise_rather_than_pick(self) -> None:
        """A silent choice here is how two histories get spliced."""
        overlapping = [
            TickerAssignment(ACME, "XYZ", effective_time=T2019),
            TickerAssignment(ZENITH, "XYZ", effective_time=T2019),
        ]
        with pytest.raises(TickerResolutionError, match="resolves to 2 instruments"):
            resolve_ticker(overlapping, "XYZ", T2022)

    def test_open_interval_has_no_end(self) -> None:
        current = TickerAssignment(ACME, "XYZ", effective_time=T2019)
        assert current.covers(T2024)
