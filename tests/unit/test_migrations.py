"""Migrations are ordered, immutable once applied, and describe the real schema.

These run without a database. The applier's contract -- discovery, ordering, and
the refusal to proceed when an applied file has changed -- is pure logic, and the
Cursor protocol is narrow enough to fake. Tests that genuinely need Postgres are
in tests/integration and run in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trading.memory.migrate import (
    MIGRATIONS_DIR,
    Migration,
    MigrationError,
    apply,
    discover,
    pending,
)

pytestmark = pytest.mark.unit


class UndefinedTable(RuntimeError):
    """Stands in for psycopg's UndefinedTable, so the fake fails like Postgres."""


class FakeCursor:
    """The slice of DB-API the applier uses, with no database behind it.

    Deliberately strict about the bootstrap case. An earlier version returned an
    empty result when asked for the ledger on a fresh database, so the offline
    tests passed while the first real run failed with "relation
    schema_migration does not exist". A fake that is more forgiving than the
    thing it stands in for is worse than no fake.
    """

    def __init__(
        self, applied: dict[int, str] | None = None, *, ledger: bool | None = None
    ) -> None:
        self.applied = dict(applied or {})
        # Ledger exists once migration 0 has run, unless a test says otherwise.
        self.ledger = ledger if ledger is not None else 0 in self.applied
        self.executed: list[str] = []
        self._rows: list[tuple[object, ...]] = []

    def execute(self, query: str, params: tuple[object, ...] = (), /) -> None:
        if query.startswith("SELECT to_regclass"):
            self._rows = [("schema_migration" if self.ledger else None,)]
        elif query.startswith("SELECT version, sha256"):
            if not self.ledger:
                raise UndefinedTable('relation "schema_migration" does not exist')
            self._rows = [(v, h) for v, h in sorted(self.applied.items())]
        elif query.startswith("INSERT INTO schema_migration"):
            if not self.ledger:
                raise UndefinedTable('relation "schema_migration" does not exist')
            self.applied[int(str(params[0]))] = str(params[2])
        else:
            self.executed.append(query)
            if "CREATE TABLE schema_migration" in query:
                self.ledger = True

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class TestDiscovery:
    def test_the_repository_migrations_are_found(self) -> None:
        """A silently empty result looks identical to 'already up to date'."""
        versions = [m.version for m in discover()]
        assert versions == [0, 1, 2]

    def test_migrations_directory_resolves(self) -> None:
        assert MIGRATIONS_DIR.is_dir(), MIGRATIONS_DIR

    def test_missing_directory_is_fatal(self, tmp_path: Path) -> None:
        with pytest.raises(MigrationError, match="no migrations directory"):
            discover(tmp_path / "absent")

    def test_malformed_filename_is_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "oops.sql").write_text("SELECT 1;")
        with pytest.raises(MigrationError, match="not a migration filename"):
            discover(tmp_path)

    def test_unpadded_version_is_rejected(self, tmp_path: Path) -> None:
        """Unpadded ordinals sort differently lexicographically and numerically."""
        (tmp_path / "1_thing.sql").write_text("SELECT 1;")
        with pytest.raises(MigrationError, match="zero-padded"):
            discover(tmp_path)

    def test_duplicate_versions_are_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "0001_a.sql").write_text("SELECT 1;")
        (tmp_path / "0001_b.sql").write_text("SELECT 2;")
        with pytest.raises(MigrationError, match="duplicate migration version"):
            discover(tmp_path)


class TestImmutability:
    def test_unchanged_applied_migrations_are_skipped(self) -> None:
        migrations = discover()
        cursor = FakeCursor({m.version: m.sha256 for m in migrations})
        assert pending(cursor) == ()

    def test_a_changed_applied_migration_is_fatal(self) -> None:
        """D10's content addressing, applied to DDL."""
        migrations = discover()
        cursor = FakeCursor({migrations[0].version: "0" * 64})
        with pytest.raises(MigrationError, match="changed after it was applied"):
            pending(cursor)

    def test_the_error_says_to_write_a_new_migration(self) -> None:
        cursor = FakeCursor({0: "0" * 64})
        with pytest.raises(MigrationError, match="write a new one"):
            pending(cursor)

    def test_a_migration_applied_but_absent_is_fatal(self) -> None:
        # ledger=True: the database is not fresh, it has a record we cannot explain.
        cursor = FakeCursor({99: "0" * 64}, ledger=True)
        with pytest.raises(MigrationError, match="not in the repository"):
            pending(cursor)


class TestBootstrap:
    """An empty database has no ledger, because migration 0000 creates it."""

    def test_a_fresh_database_reports_nothing_applied(self) -> None:
        assert pending(FakeCursor(ledger=False)) != ()

    def test_applying_to_a_fresh_database_works(self) -> None:
        cursor = FakeCursor(ledger=False)
        applied = apply(cursor)
        assert [m.version for m in applied] == [0, 1, 2]

    def test_the_ledger_check_does_not_swallow_other_failures(self) -> None:
        """to_regclass rather than catching the error: a permissions failure
        must not be read as 'no migrations applied' and re-run everything."""
        from trading.memory.migrate import LEDGER_EXISTS_QUERY

        assert "to_regclass" in LEDGER_EXISTS_QUERY


class TestApply:
    def test_applies_all_and_records_them(self) -> None:
        cursor = FakeCursor()
        applied = apply(cursor)
        assert [m.version for m in applied] == [0, 1, 2]
        assert set(cursor.applied) == {0, 1, 2}

    def test_is_idempotent(self) -> None:
        cursor = FakeCursor()
        apply(cursor)
        assert apply(cursor) == ()

    def test_hash_changes_with_any_edit(self, tmp_path: Path) -> None:
        path = tmp_path / "0001_x.sql"
        path.write_text("CREATE TABLE a (id INT);")
        before = Migration(1, "x", path, path.read_text()).sha256
        path.write_text("CREATE TABLE a (id BIGINT);")
        assert Migration(1, "x", path, path.read_text()).sha256 != before


class TestDivergencesAreInTheDDL:
    """The corrections recorded in docs/spec-divergences.md must be in the SQL."""

    def sql(self, version: int) -> str:
        return next(m.sql for m in discover() if m.version == version)

    @staticmethod
    def statements(sql: str) -> str:
        """Strip `--` comments: these assertions are about SQL, not prose.

        The comments explain why COALESCE and IF NOT EXISTS are absent, so a
        naive substring search finds them in the very text arguing against them.
        """
        return "\n".join(line.split("--")[0] for line in sql.splitlines())

    def test_order_event_keys_on_broker_event_identity(self) -> None:
        """Divergence 1: the §9 tuple collides on same-timestamp partial fills."""
        sql = self.sql(2)
        assert "UNIQUE (account_id, broker_event_id)" in sql
        assert "order_event_execution_uk" in sql

    def test_no_coalesce_sentinels(self) -> None:
        """A sentinel collapses distinct rows -- the bug being fixed."""
        assert "COALESCE" not in self.statements(self.sql(2)).upper()

    def test_nanoseconds_are_authoritative(self) -> None:
        """Divergence 7: TIMESTAMPTZ is microsecond and would truncate."""
        sql = self.sql(2)
        assert "event_time_ns       BIGINT      NOT NULL" in sql
        assert "GENERATED ALWAYS AS" in sql

    def test_knowledge_time_constraint_reaches_postgres(self) -> None:
        assert "knowledge_time_ns >= event_time_ns" in self.sql(2)

    def test_experiment_pins_the_gate_policy_before_the_run(self) -> None:
        """§20: a strategy cannot select a threshold after seeing results."""
        assert "gate_policy_version" in self.sql(1)

    def test_experiment_records_the_environment_fingerprint(self) -> None:
        """Divergence 4 needs a home, or it is not recorded anywhere."""
        assert "environment_fingerprint" in self.sql(1)

    def test_family_trial_count_is_captured_at_start(self) -> None:
        assert "family_trial_count_at_start" in self.sql(1)

    def test_trial_index_is_unique_per_family(self) -> None:
        assert "UNIQUE (family_id, trial_index)" in self.sql(1)

    def test_family_and_hypothesis_have_real_foreign_keys(self) -> None:
        """A UUID with no FK is how orphan family ids appear (D8)."""
        sql = self.sql(1)
        assert "REFERENCES strategy_family(family_id)" in sql
        assert "REFERENCES hypothesis(hypothesis_id)" in sql

    def test_no_if_not_exists_anywhere(self) -> None:
        """IF NOT EXISTS hides drift, which is what the ledger defends against."""
        for migration in discover():
            assert "IF NOT EXISTS" not in self.statements(migration.sql).upper(), migration.name
