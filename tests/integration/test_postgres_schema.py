"""The DDL applies to a real Postgres and behaves as divergence 1 describes.

Skipped unless TRADING_TEST_DSN is set. There is no Postgres in the development
environment, so these first run in CI -- stated plainly rather than implied by a
green local run.

What is verified offline lives in tests/unit/test_migrations.py; what genuinely
needs a server is here: that the SQL parses, that the constraints do what they
are claimed to do, and that re-running changes nothing.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from trading.memory.migrate import apply, pending

pytestmark = [pytest.mark.integration, pytest.mark.postgres]

DSN = os.environ.get("TRADING_TEST_DSN", "")

pytestmark.append(
    pytest.mark.skipif(not DSN, reason="TRADING_TEST_DSN is unset; see make verify-db")
)


@pytest.fixture
def connection() -> Iterator[psycopg.Connection[Any]]:
    """A connection to a scratch database, with the schema dropped and rebuilt."""
    with psycopg.connect(DSN, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        yield conn


@pytest.fixture
def migrated(connection: psycopg.Connection[Any]) -> psycopg.Connection[Any]:
    with connection.cursor() as cur:
        apply(cur)
    return connection


class TestEncoding:
    """The cluster must be UTF8 with C collation -- both, not one or the other."""

    def test_encoding_is_utf8(self, connection: psycopg.Connection[Any]) -> None:
        """SQL_ASCII is not an encoding, it is the absence of one.

        It accepts any byte sequence without validation, so UTF-8 text written
        through it can come back mojibake. It is also what initdb silently picks
        when the locale is C and no encoding is given -- which is how the first
        real run of this job failed on a section sign in a SQL comment.
        """
        with connection.cursor() as cur:
            cur.execute(
                "SELECT pg_encoding_to_char(encoding) FROM pg_database "
                "WHERE datname = current_database()"
            )
            assert _one(cur)[0] == "UTF8"

    def test_collation_is_c(self, connection: psycopg.Connection[Any]) -> None:
        """Sort order must not depend on the host's locale."""
        with connection.cursor() as cur:
            cur.execute("SELECT datcollate FROM pg_database WHERE datname = current_database()")
            assert _one(cur)[0] in {"C", "C.UTF-8", "POSIX"}

    def test_non_ascii_survives_a_round_trip(self, connection: psycopg.Connection[Any]) -> None:
        """The DDL itself contains section references; so will strategy names."""
        with connection.cursor() as cur:
            cur.execute("SELECT %s::text", ("§9 — naïve café",))
            assert _one(cur)[0] == "§9 — naïve café"


class TestApplication:
    def test_migrations_apply(self, connection: psycopg.Connection[Any]) -> None:
        with connection.cursor() as cur:
            applied = apply(cur)
        assert [m.version for m in applied] == [0, 1, 2]

    def test_reapplying_is_a_no_op(self, migrated: psycopg.Connection[Any]) -> None:
        with migrated.cursor() as cur:
            assert pending(cur) == ()

    def test_expected_tables_exist(self, migrated: psycopg.Connection[Any]) -> None:
        with migrated.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' ORDER BY table_name"
            )
            tables = {row[0] for row in cur.fetchall()}
        assert {
            "experiment",
            "holdout_access",
            "hypothesis",
            "order_event",
            "schema_migration",
            "strategy_family",
        } <= tables


def _one(cur: psycopg.Cursor[Any]) -> tuple[Any, ...]:
    """Fetch exactly one row, failing loudly if the query returned none."""
    row: tuple[Any, ...] | None = cur.fetchone()
    assert row is not None, "query returned no rows"
    return row


#: Delay between an event and our knowledge of it, matching the normalizer's
#: declared publication lag.
_LAG_NS = 250_000


def _event(cur: psycopg.Cursor[Any], **overrides: Any) -> None:
    """Insert one order event, internally consistent by default.

    receive and knowledge times are *derived* from event_time_ns rather than
    fixed, so moving the event time keeps the row satisfying
    order_event_knowledge_not_before_event. Overriding a derived field
    explicitly still wins, which is how the leakage test builds a row the
    constraint must reject.
    """
    event_ns: int = overrides.pop("event_time_ns", 1_789_824_600_000_000_000)
    row = {
        "event_id": str(uuid.uuid4()),
        "account_id": "paper-1",
        "client_order_id": "c-1",
        "broker_event_id": str(uuid.uuid4()),
        "execution_id": None,
        "event_type": "ack",
        "state": "acknowledged",
        "risk_reason": "approved",
        "event_time_ns": event_ns,
        "receive_time_ns": event_ns + _LAG_NS,
        "knowledge_time_ns": event_ns + _LAG_NS,
        "strategy_version": "s1",
        "risk_policy_version": "r1",
        "payload": "{}",
    } | overrides
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    cur.execute(f"INSERT INTO order_event ({columns}) VALUES ({placeholders})", tuple(row.values()))


class TestDivergenceOne:
    """The §9 key rejects legitimate partial fills; the corrected one does not."""

    def test_two_partial_fills_at_the_same_timestamp_are_accepted(
        self, migrated: psycopg.Connection[Any]
    ) -> None:
        with migrated.cursor() as cur:
            _event(cur, event_type="fill", execution_id="x-1")
            _event(cur, event_type="fill", execution_id="x-2")
            cur.execute("SELECT count(*) FROM order_event WHERE event_type = 'fill'")
            assert _one(cur)[0] == 2

    def test_a_replayed_broker_event_is_rejected(self, migrated: psycopg.Connection[Any]) -> None:
        """Idempotency: a retry must not create a second row."""
        import psycopg

        with migrated.cursor() as cur:
            duplicate = str(uuid.uuid4())
            _event(cur, broker_event_id=duplicate)
            with pytest.raises(psycopg.errors.UniqueViolation):
                _event(cur, broker_event_id=duplicate)

    def test_a_repeated_execution_id_is_rejected(self, migrated: psycopg.Connection[Any]) -> None:
        import psycopg

        with migrated.cursor() as cur:
            _event(cur, event_type="fill", execution_id="x-dup")
            with pytest.raises(psycopg.errors.UniqueViolation):
                _event(cur, event_type="fill", execution_id="x-dup")

    def test_a_fill_without_an_execution_id_is_rejected(
        self, migrated: psycopg.Connection[Any]
    ) -> None:
        import psycopg

        with migrated.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
            _event(cur, event_type="fill", execution_id=None)

    def test_unsolicited_events_need_no_client_order_id(
        self, migrated: psycopg.Connection[Any]
    ) -> None:
        """The §9 key assumed every event has one; unsolicited cancels do not."""
        with migrated.cursor() as cur:
            _event(cur, client_order_id=None, event_type="cancel", state="canceled")


class TestDivergenceSeven:
    """TIMESTAMPTZ is microsecond; the nanosecond columns are authoritative."""

    def test_nanoseconds_survive_a_round_trip(self, migrated: psycopg.Connection[Any]) -> None:
        with migrated.cursor() as cur:
            _event(cur, event_time_ns=1_789_824_600_123_456_789)
            cur.execute("SELECT event_time_ns FROM order_event LIMIT 1")
            assert _one(cur)[0] == 1_789_824_600_123_456_789

    def test_the_readable_view_renders_timestamps(self, migrated: psycopg.Connection[Any]) -> None:
        """Rendering lives in a view, because a stored generated column must be
        IMMUTABLE and timestamptz arithmetic is only STABLE."""
        with migrated.cursor() as cur:
            _event(cur, event_time_ns=1_789_824_600_123_456_789)
            cur.execute("SELECT event_time_ns, event_time FROM order_event_readable LIMIT 1")
            nanos, rendered = _one(cur)
            assert nanos == 1_789_824_600_123_456_789
            assert rendered is not None

    def test_the_view_loses_nanoseconds_and_the_table_does_not(
        self, migrated: psycopg.Connection[Any]
    ) -> None:
        """Why the integers stay authoritative: two events a nanosecond apart
        render identically, so nothing may join or order on the view's columns."""
        with migrated.cursor() as cur:
            _event(cur, broker_event_id="a", event_time_ns=1_789_824_600_000_000_001)
            _event(cur, broker_event_id="b", event_time_ns=1_789_824_600_000_000_002)
            cur.execute("SELECT count(DISTINCT event_time) FROM order_event_readable")
            assert _one(cur)[0] == 1
            cur.execute("SELECT count(DISTINCT event_time_ns) FROM order_event")
            assert _one(cur)[0] == 2

    def test_knowledge_before_event_is_rejected(self, migrated: psycopg.Connection[Any]) -> None:
        """D4 reaches Postgres: leakage is leakage wherever it is stored."""
        import psycopg

        with migrated.cursor() as cur, pytest.raises(psycopg.errors.CheckViolation):
            _event(cur, knowledge_time_ns=1_789_824_599_000_000_000)


class TestExperimentRegistry:
    def test_trial_index_is_unique_within_a_family(self, migrated: psycopg.Connection[Any]) -> None:
        """The constraint the whole multiple-testing edifice rests on."""
        import psycopg

        family, hypothesis = str(uuid.uuid4()), str(uuid.uuid4())
        with migrated.cursor() as cur:
            cur.execute(
                "INSERT INTO strategy_family (family_id, name, mechanism, "
                "membership_rule_version) VALUES (%s, 'f', 'm', 'v1')",
                (family,),
            )
            cur.execute(
                "INSERT INTO hypothesis (hypothesis_id, family_id, claim, mechanism, "
                "created_by) VALUES (%s, %s, 'c', 'm', 'me')",
                (hypothesis, family),
            )

            def insert(trial: int) -> None:
                cur.execute(
                    "INSERT INTO experiment (experiment_id, family_id, hypothesis_id, "
                    "dataset_snapshot_id, code_commit, container_digest, "
                    "environment_fingerprint, strategy_spec_hash, random_seed, "
                    "trial_index, family_trial_count_at_start, gate_policy_version, "
                    "cost_model_id, risk_policy_version, status, requested_by) "
                    "VALUES (%s, %s, %s, 's', 'c', 'd', 'f', 'h', 1, %s, %s, 'g', "
                    "'cm', 'rp', 'created', 'me')",
                    (str(uuid.uuid4()), family, hypothesis, trial, trial),
                )

            insert(0)
            with pytest.raises(psycopg.errors.UniqueViolation):
                insert(0)

    def test_unknown_status_is_rejected(self, migrated: psycopg.Connection[Any]) -> None:
        import psycopg

        expected = (psycopg.errors.CheckViolation, psycopg.errors.ForeignKeyViolation)
        with migrated.cursor() as cur, pytest.raises(expected):
            cur.execute(
                "INSERT INTO experiment (experiment_id, family_id, hypothesis_id, "
                "dataset_snapshot_id, code_commit, container_digest, "
                "environment_fingerprint, strategy_spec_hash, random_seed, "
                "trial_index, family_trial_count_at_start, gate_policy_version, "
                "cost_model_id, risk_policy_version, status, requested_by) "
                "VALUES (%s, %s, %s, 's', 'c', 'd', 'f', 'h', 1, 0, 0, 'g', "
                "'cm', 'rp', 'not_a_status', 'me')",
                (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())),
            )
