"""Forward-only migration applier with content-addressed DDL.

Raw SQL rather than Alembic. Alembic's value is autogenerate, which derives
migrations from SQLAlchemy models — making the ORM authoritative for the schema
D7 designates as the system of record for trial counts. The §9 DDL is a
specification artifact: it should be transcribed, reviewed and hashed, not
generated from code that was itself written from it.

The property that earns the module is the refusal: if an already-applied
migration's text has changed, the applier stops. D10 content-addresses data, and
the same discipline applies to DDL — otherwise the database drifts into a shape
no file describes and nobody finds out.

There is no downgrade path. A "downgrade" of the trial-counter table is exactly
the operation D7 says must never happen.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

# .../packages/memory/src/trading/memory/migrate.py -> repository root.
MIGRATIONS_DIR: Final = Path(__file__).resolve().parents[5] / "infra" / "migrations"
_FILENAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """A migration cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class Migration:
    """One numbered migration file."""

    version: int
    name: str
    path: Path
    sql: str

    @property
    def sha256(self) -> str:
        """Hash of the file's exact bytes. Any edit changes it."""
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


class Cursor(Protocol):
    """The slice of DB-API a migration needs. Kept narrow so it is trivial to fake."""

    def execute(self, query: str, params: tuple[object, ...] = ..., /) -> object: ...
    def fetchall(self) -> list[tuple[object, ...]]: ...


def discover(directory: Path = MIGRATIONS_DIR) -> tuple[Migration, ...]:
    """Return every migration, in version order.

    Raises:
        MigrationError: If the directory is missing, or on a malformed filename
            or duplicate version. Ordering is the entire contract here, so an
            unparseable name is fatal rather than skipped -- and an empty result
            is indistinguishable from "already up to date", which is why a
            missing directory raises rather than returning nothing.
    """
    if not directory.is_dir():
        raise MigrationError(
            f"no migrations directory at {directory}. Returning zero migrations "
            "here would look exactly like an up-to-date database, so this is "
            "fatal instead."
        )

    found: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _FILENAME.match(path.name)
        if match is None:
            raise MigrationError(
                f"{path.name} is not a migration filename. Expected "
                "NNNN_lower_snake_name.sql, zero-padded so lexicographic order "
                "and numeric order agree."
            )
        version = int(match.group("version"))
        if version in found:
            raise MigrationError(f"duplicate migration version {version:04d}")
        found[version] = Migration(
            version=version,
            name=match.group("name"),
            path=path,
            sql=path.read_text(encoding="utf-8"),
        )
    return tuple(found[key] for key in sorted(found))


#: Returns NULL when the ledger table does not exist yet.
LEDGER_EXISTS_QUERY: Final = "SELECT to_regclass('schema_migration')"


def ledger_exists(cursor: Cursor) -> bool:
    """Whether the migration ledger has been created yet.

    The bootstrap case: on an empty database the ledger does not exist, because
    migration 0000 is what creates it. Querying it first would fail with
    "relation does not exist" -- which is what happened the first time this ran
    against a real Postgres, since a hand-written fake cursor had returned an
    empty result instead of raising.

    Checked with ``to_regclass`` rather than by catching the error, so a genuine
    permissions or connection failure still surfaces instead of being read as
    "no migrations applied" and silently re-running everything.
    """
    cursor.execute(LEDGER_EXISTS_QUERY)
    rows = cursor.fetchall()
    return bool(rows) and rows[0][0] is not None


def applied_migrations(cursor: Cursor) -> dict[int, str]:
    """Return ``{version: sha256}`` for migrations already applied."""
    if not ledger_exists(cursor):
        return {}
    cursor.execute("SELECT version, sha256 FROM schema_migration ORDER BY version")
    # str() first: the DB-API row type is deliberately opaque here so the
    # protocol stays narrow enough to fake without a database.
    return {int(str(version)): str(digest) for version, digest in cursor.fetchall()}


def pending(cursor: Cursor, directory: Path = MIGRATIONS_DIR) -> tuple[Migration, ...]:
    """Return migrations not yet applied, verifying the ones that have been.

    Raises:
        MigrationError: If an applied migration's text has changed, or if a
            migration is missing from disk. Both mean the database's shape is no
            longer described by the repository.
    """
    migrations = discover(directory)
    already = applied_migrations(cursor)
    by_version = {m.version: m for m in migrations}

    for version, recorded in sorted(already.items()):
        migration = by_version.get(version)
        if migration is None:
            raise MigrationError(
                f"migration {version:04d} was applied to this database but is not "
                "in the repository. The schema is in a state no file describes."
            )
        if migration.sha256 != recorded:
            raise MigrationError(
                f"{migration.path.name} changed after it was applied "
                f"(recorded {recorded[:12]}, now {migration.sha256[:12]}). "
                "Migrations are immutable once applied: write a new one. "
                "Editing this file has already left the database in a shape it "
                "no longer describes."
            )

    return tuple(m for m in migrations if m.version not in already)


def apply(cursor: Cursor, directory: Path = MIGRATIONS_DIR) -> tuple[Migration, ...]:
    """Apply every pending migration, one transaction per file.

    The caller owns the connection and the commit boundary, so this stays
    testable without a database and honest about who controls the transaction.
    """
    to_apply = pending(cursor, directory)
    for migration in to_apply:
        cursor.execute(migration.sql)
        cursor.execute(
            "INSERT INTO schema_migration (version, name, sha256) VALUES (%s, %s, %s)",
            (migration.version, migration.name, migration.sha256),
        )
    return to_apply
