-- Records which migrations have been applied, and refuses a changed one.
--
-- The sha256 column is the point. D10 content-addresses data; the same
-- discipline applies to DDL. If an already-applied migration's text changes,
-- the applier refuses to run rather than silently leaving the database in a
-- shape no file describes. There is no IF NOT EXISTS anywhere in these
-- migrations: that hides drift, which is the thing being defended against.
--
-- Forward-only. There is no downgrade path, and that is deliberate: a
-- "downgrade" of the trial-counter table is precisely the operation D7 says
-- must never happen.

CREATE TABLE schema_migration (
    version     INTEGER     PRIMARY KEY,
    name        TEXT        NOT NULL,
    sha256      TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
