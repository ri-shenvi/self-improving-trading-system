"""Time is int64 UTC nanoseconds, and parsing never loses a nanosecond."""

from __future__ import annotations

import pytest

from trading.schemas.time import (
    MAX_PLAUSIBLE_NS,
    MIN_PLAUSIBLE_NS,
    NS_PER_SECOND,
    TimestampError,
    TimestampNs,
    format_ns,
    is_plausible,
    parse_rfc3339_ns,
    require_plausible,
)

pytestmark = pytest.mark.unit


class TestParsing:
    def test_nanosecond_precision_survives(self) -> None:
        """datetime is microsecond; a venue timestamp is not."""
        assert parse_rfc3339_ns("2026-09-19T13:30:00.123456789Z") % NS_PER_SECOND == 123_456_789

    def test_fraction_is_left_aligned(self) -> None:
        """'.5' is 500 milliseconds, not 5 nanoseconds."""
        assert parse_rfc3339_ns("2026-09-19T09:30:00.5Z") % NS_PER_SECOND == 500_000_000

    @pytest.mark.parametrize(
        "text",
        [
            "2026-09-19T13:30:00Z",
            "2026-09-19T09:30:00-04:00",
            "2026-09-19T18:30:00+05:00",
            "2026-09-19t13:30:00z",
        ],
    )
    def test_offsets_resolve_to_the_same_instant(self, text: str) -> None:
        assert parse_rfc3339_ns(text) == parse_rfc3339_ns("2026-09-19T13:30:00Z")

    def test_offset_is_required(self) -> None:
        """Guessing UTC is how a feed's local-time field becomes a one-hour error."""
        with pytest.raises(TimestampError, match="explicit offset"):
            parse_rfc3339_ns("2026-09-19T13:30:00")

    @pytest.mark.parametrize("text", ["", "not a time", "2026-09-19", "20260919T133000Z"])
    def test_malformed_input_raises(self, text: str) -> None:
        with pytest.raises(TimestampError):
            parse_rfc3339_ns(text)

    def test_round_trip(self) -> None:
        original = "2026-09-19T13:30:00.123456789Z"
        assert format_ns(parse_rfc3339_ns(original)) == original


class TestPlausibility:
    def test_epoch_zero_is_rejected(self) -> None:
        """The classic present-but-wrong value: it passes every null check."""
        assert not is_plausible(TimestampNs(0))
        with pytest.raises(TimestampError, match="knowledge_time"):
            require_plausible(TimestampNs(0), field="knowledge_time")

    def test_band_edges(self) -> None:
        assert is_plausible(MIN_PLAUSIBLE_NS)
        assert is_plausible(MAX_PLAUSIBLE_NS)
        assert not is_plausible(TimestampNs(MIN_PLAUSIBLE_NS - 1))
        assert not is_plausible(TimestampNs(MAX_PLAUSIBLE_NS + 1))

    def test_a_real_session_timestamp_is_plausible(self) -> None:
        assert is_plausible(parse_rfc3339_ns("2026-09-19T13:30:00Z"))

    def test_error_explains_the_band(self) -> None:
        with pytest.raises(TimestampError, match="plausible band"):
            require_plausible(TimestampNs(1), field="event_time")
