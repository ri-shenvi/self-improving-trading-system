"""How the golden fixture is processed, defined once.

The generator that writes the expected values and the tests that assert them
must agree exactly, or the golden test is checking the generator against itself.
Both import this module, so there is one definition of the run.

Every parameter is fixed. Nothing here reads a clock, which is what makes the
whole pipeline a pure function of the committed fixture bytes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from trading.market_data.normalize import NormalizationContext
from trading.market_data.pipeline import SnapshotResult, run
from trading.schemas.io import KnowledgeTimePolicy
from trading.schemas.time import TimestampNs, parse_rfc3339_ns

ROOT: Final = Path(__file__).resolve().parent.parent
FIXTURE_DIR: Final = ROOT / "tests/golden/fixtures/tiny_day"
EXPECTED_PATH: Final = FIXTURE_DIR / "expected.json"

#: The session the fixture covers closed at 20:00Z, so every window is complete.
AS_OF: Final = parse_rfc3339_ns("2026-09-18T20:00:00.000000000Z")

#: Backfill, because the fixture is historical: we hold the bytes long after the
#: events, so receive_time cannot stand in for knowledge_time.
CONTEXT: Final = NormalizationContext(
    receive_time=parse_rfc3339_ns("2026-09-19T00:00:00.000000000Z"),
    process_time=parse_rfc3339_ns("2026-09-19T00:05:00.000000000Z"),
    # A declared conservative constant until M7 measures the real distribution.
    # A result that depends on this value has not been validated.
    publication_lag_ns=250_000,
    raw_partition_id="fixture/tiny_day/000",
    # The fixture is synthetic and stands in for consolidated data.
    event_time_source="sip",
    venue_coverage="sip",
    knowledge_policy=KnowledgeTimePolicy.BACKFILL,
)

CALENDAR_VERSION: Final = "xnys_v1"


def run_fixture(output_root: Path, *, as_of: TimestampNs = AS_OF) -> SnapshotResult:
    """Normalize the committed fixture into ``output_root`` and seal a snapshot."""
    return run(
        FIXTURE_DIR / "raw",
        FIXTURE_DIR / "reference.json",
        output_root,
        CONTEXT,
        as_of=as_of,
        calendar_version=CALENDAR_VERSION,
    )
