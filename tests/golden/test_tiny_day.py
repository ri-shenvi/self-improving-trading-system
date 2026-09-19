"""The golden fixture: raw bytes in, the same snapshot out, every time.

These are M2's exit criteria. Every later milestone regresses against this
fixture, so a change to any expected value here should be read carefully rather
than regenerated reflexively.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools.golden_fixture import AS_OF, EXPECTED_PATH, FIXTURE_DIR, run_fixture

from trading.market_data.snapshot import SnapshotReader
from trading.market_data.snapshot.builder import load_manifest, verify_snapshot
from trading.schemas.time import TimestampNs, parse_rfc3339_ns

pytestmark = pytest.mark.golden

EXPECTED = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def snapshot(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    root = tmp_path_factory.mktemp("snapshot")
    return run_fixture(root), root


class TestReproducibility:
    def test_snapshot_id_matches_the_recorded_value(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        result, _ = snapshot
        assert result.snapshot_id == EXPECTED["snapshot_id"]

    def test_two_runs_produce_the_same_snapshot_id(self, tmp_path: Path) -> None:
        """The property the whole injected-clock design exists for."""
        first = run_fixture(tmp_path / "a").snapshot_id
        second = run_fixture(tmp_path / "b").snapshot_id
        assert first == second

    def test_content_hashes_match(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        """Content hashes rather than parquet bytes: see tools/build_golden.py."""
        result, _ = snapshot
        actual = {receipt.contract: receipt.content_sha256 for receipt in result.receipts}
        expected = {name: body["content_sha256"] for name, body in EXPECTED["files"].items()}
        assert actual == expected

    def test_row_counts_match(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        result, _ = snapshot
        actual = {receipt.contract: receipt.row_count for receipt in result.receipts}
        assert actual == {n: b["row_count"] for n, b in EXPECTED["files"].items()}


class TestNanosecondSemantics:
    def test_event_times_keep_their_nanoseconds(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        """Nothing in the pipeline may round to microseconds."""
        _, root = snapshot
        trades = SnapshotReader(root).read_contract("normalized.trade").to_pydict()
        assert any(value % 1_000 != 0 for value in trades["event_time"])

    def test_the_first_trade_time_is_exact(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        _, root = snapshot
        trades = SnapshotReader(root).read_contract("normalized.trade").to_pydict()
        assert trades["event_time"][0] == EXPECTED["first_trade_event_time"]

    def test_ordering_keys_are_strictly_increasing(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        """§16: a duplicate key means the stream is not a total order."""
        _, root = snapshot
        reader = SnapshotReader(root)
        for contract in ("normalized.trade", "normalized.quote", "normalized.bar"):
            columns = reader.read_contract(contract).to_pydict()
            keys = list(
                zip(
                    columns["event_time"],
                    columns["source_rank"],
                    columns["vendor_sequence"],
                    columns["venue_sequence"],
                    columns["ingest_index"],
                    strict=True,
                )
            )
            assert keys == sorted(keys), contract
            assert len(set(keys)) == len(keys), contract

    def test_the_same_nanosecond_collision_is_ordered(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        """The fixture contains two prints at one nanosecond, on purpose."""
        _, root = snapshot
        columns = SnapshotReader(root).read_contract("normalized.trade").to_pydict()
        times = columns["event_time"]
        collisions = {t for t in times if times.count(t) > 1}
        assert collisions, "the fixture should contain a same-nanosecond collision"

    def test_knowledge_time_is_derived_from_the_lag(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        """Backfill: knowledge_time is event_time plus the declared lag, not receive_time."""
        _, root = snapshot
        trades = SnapshotReader(root).read_contract("normalized.trade").to_pydict()
        assert trades["knowledge_time"][0] == EXPECTED["first_trade_knowledge_time"]
        assert trades["knowledge_time"][0] - trades["event_time"][0] == 250_000

    def test_knowledge_time_never_precedes_the_event(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        _, root = snapshot
        reader = SnapshotReader(root)
        for contract in ("normalized.trade", "normalized.quote", "normalized.bar"):
            columns = reader.read_contract(contract).to_pydict()
            assert all(
                k >= e
                for k, e in zip(columns["knowledge_time"], columns["event_time"], strict=True)
            ), contract


class TestBars:
    def test_bar_count(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        _, root = snapshot
        bars = SnapshotReader(root).read_contract("normalized.bar").to_pydict()
        assert len(bars["event_time"]) == EXPECTED["bar_count"]

    def test_first_bar_matches(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        _, root = snapshot
        bars = SnapshotReader(root).read_contract("normalized.bar").to_pydict()
        actual = {key: bars[key][0] for key in EXPECTED["first_bar"]}
        assert actual == EXPECTED["first_bar"]

    def test_ineligible_prints_are_excluded(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        """Form-T prints are in the trade table and must not reach a bar (D12)."""
        _, root = snapshot
        reader = SnapshotReader(root)
        trades = reader.read_contract("normalized.trade").to_pydict()
        bars = reader.read_contract("normalized.bar").to_pydict()

        form_t = sum(1 for conditions in trades["conditions"] if "T" in (conditions or ()))
        assert form_t > 0, "the fixture should contain condition-filtered prints"
        assert sum(bars["trade_count"]) == len(trades["event_time"]) - form_t
        assert sum(bars["trade_count"]) == EXPECTED["trades_in_bars"]

    def test_windows_are_half_open_and_aligned(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        _, root = snapshot
        bars = SnapshotReader(root).read_contract("normalized.bar").to_pydict()
        session_open = parse_rfc3339_ns("2026-09-18T13:30:00.000000000Z")
        for start, window in zip(bars["event_time"], bars["window_ns"], strict=True):
            assert (start - session_open) % window == 0

    def test_ohlc_is_bounded_by_high_and_low(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        _, root = snapshot
        bars = SnapshotReader(root).read_contract("normalized.bar").to_pydict()
        for index in range(len(bars["event_time"])):
            low, high = bars["low_nano"][index], bars["high_nano"][index]
            assert low <= bars["open_nano"][index] <= high
            assert low <= bars["close_nano"][index] <= high
            assert low <= bars["vwap_nano"][index] <= high

    def test_a_window_still_open_is_marked_incomplete(self, tmp_path: Path) -> None:
        """A partial bar must never look closed to a feature (§12)."""
        early = TimestampNs(parse_rfc3339_ns("2026-09-18T13:40:00.000000000Z"))
        result = run_fixture(tmp_path, as_of=early)
        bars = SnapshotReader(tmp_path, result.manifest).read_contract("normalized.bar").to_pydict()
        assert any(bars["is_complete"]), "early windows closed before as_of"
        assert not all(bars["is_complete"]), "later windows had not closed at as_of"


class TestSnapshotIntegrity:
    def test_manifest_round_trips(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        result, root = snapshot
        assert load_manifest(root).snapshot_id() == result.snapshot_id

    def test_a_clean_snapshot_verifies(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        result, root = snapshot
        assert verify_snapshot(result.manifest, root) == []

    def test_a_flipped_byte_fails_verification(self, tmp_path: Path) -> None:
        result = run_fixture(tmp_path)
        target = tmp_path / result.manifest.files[0].path
        data = bytearray(target.read_bytes())
        data[len(data) // 2] ^= 0xFF
        target.write_bytes(bytes(data))

        findings = verify_snapshot(result.manifest, tmp_path)
        assert findings
        assert "bytes changed" in str(findings[0])

    def test_a_missing_file_fails_verification(self, tmp_path: Path) -> None:
        result = run_fixture(tmp_path)
        (tmp_path / result.manifest.files[0].path).unlink()
        assert "missing on disk" in str(verify_snapshot(result.manifest, tmp_path)[0])

    def test_an_unrelated_file_does_not_change_the_snapshot_id(self, tmp_path: Path) -> None:
        """A correction appended beside a snapshot is not part of it (§8)."""
        result = run_fixture(tmp_path)
        before = result.snapshot_id
        (tmp_path / "normalized" / "trade" / "corrections.ndjson").write_text("{}\n")
        assert load_manifest(tmp_path).snapshot_id() == before
        assert verify_snapshot(load_manifest(tmp_path), tmp_path) == []


class TestReaderBoundary:
    def test_listed_paths_are_readable(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        _, root = snapshot
        reader = SnapshotReader(root)
        for path in reader.paths():
            assert reader.read(path).num_rows > 0

    def test_an_unlisted_path_is_refused(self, snapshot) -> None:  # type: ignore[no-untyped-def]
        """The refusal is the whole point of the reader (§16, as-was data)."""
        from trading.market_data.snapshot import UnlistedPathError

        _, root = snapshot
        with pytest.raises(UnlistedPathError, match="not in snapshot"):
            SnapshotReader(root).read("normalized/trade/date=2026-09-19/part-000.parquet")

    def test_a_file_present_on_disk_but_unlisted_is_still_refused(self, tmp_path: Path) -> None:
        """Existing on disk is not the test; being in the manifest is."""
        from trading.market_data.snapshot import UnlistedPathError

        result = run_fixture(tmp_path)
        intruder = tmp_path / "normalized" / "trade" / "extra.parquet"
        intruder.write_bytes((tmp_path / result.manifest.files[0].path).read_bytes())

        with pytest.raises(UnlistedPathError):
            SnapshotReader(tmp_path, result.manifest).read("normalized/trade/extra.parquet")


def test_the_fixture_is_committed() -> None:
    assert (FIXTURE_DIR / "raw" / "trades" / "0000.ndjson").is_file()
    assert (FIXTURE_DIR / "reference.json").is_file()
    assert EXPECTED_PATH.is_file()


def test_as_of_is_after_the_session_close() -> None:
    """Otherwise the default run would silently produce incomplete bars."""
    assert parse_rfc3339_ns("2026-09-18T20:00:00.000000000Z") <= AS_OF
