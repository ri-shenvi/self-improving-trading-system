-- The experiment registry (§9), plus the tables family_id and hypothesis_id
-- must point at.
--
-- This is the system of record for multiple-testing accounting. §19's entire
-- anti-overfitting architecture rests on the trial count being right, and a
-- count that can race or be reconstructed after the fact is not right. Hence
-- Postgres rather than a file (D7), and hence the UNIQUE constraint below.

CREATE TABLE strategy_family (
    family_id       UUID        PRIMARY KEY,
    name            TEXT        NOT NULL UNIQUE,
    mechanism       TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Immutable once created (D8). Family membership is declared by a human
    -- against a written rule, never derived from embedding similarity: a
    -- statistical penalty must not depend on a similarity threshold, and a
    -- trial count reset by renaming is undetectable after the fact.
    membership_rule_version TEXT NOT NULL
);

CREATE TABLE hypothesis (
    hypothesis_id   UUID        PRIMARY KEY,
    family_id       UUID        NOT NULL REFERENCES strategy_family(family_id),
    claim           TEXT        NOT NULL,
    mechanism       TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      TEXT        NOT NULL
);

CREATE TABLE experiment (
    experiment_id           UUID        PRIMARY KEY,
    family_id               UUID        NOT NULL REFERENCES strategy_family(family_id),
    hypothesis_id           UUID        NOT NULL REFERENCES hypothesis(hypothesis_id),
    parent_experiment_id    UUID        REFERENCES experiment(experiment_id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    dataset_snapshot_id     TEXT        NOT NULL,
    code_commit             TEXT        NOT NULL,
    container_digest        TEXT        NOT NULL,
    -- Divergence 4: the image digest identifies what ran but cannot be
    -- recomputed, because builds embed timestamps and layer ordering. The
    -- fingerprint is deterministic, so a reviewer can confirm the environment
    -- they rebuilt matches the one that produced the result.
    environment_fingerprint TEXT        NOT NULL,
    strategy_spec_hash      TEXT        NOT NULL,
    random_seed             BIGINT      NOT NULL,
    trial_index             INTEGER     NOT NULL,
    -- Captured at creation, not at completion: DSR and PBO need the count as
    -- it stood when the trial was taken (§39).
    family_trial_count_at_start INTEGER NOT NULL,
    -- Pinned before the run, so a strategy cannot select a threshold after
    -- seeing its results (§20).
    gate_policy_version     TEXT        NOT NULL,
    cost_model_id           TEXT        NOT NULL,
    risk_policy_version     TEXT        NOT NULL,
    status                  TEXT        NOT NULL,
    requested_by            TEXT        NOT NULL,
    approved_by             TEXT,

    CONSTRAINT experiment_status_is_known CHECK (
        status IN ('created', 'queued', 'running', 'succeeded', 'failed', 'cancelled')
    ),

    -- §9. The trial index is allocated in a serializable transaction at
    -- experiment *creation*, so a cancelled or crashed run still consumes one.
    -- The control table is explicit: every variant, sweep and rejected run
    -- increments the family's count.
    UNIQUE (family_id, trial_index)
);

-- Opening the final holdout is an audited event with a counter (§39). Reading
-- the holdout range without writing a row here is not possible: there is one
-- code path and it requires a token.
CREATE TABLE holdout_access (
    access_id       UUID        PRIMARY KEY,
    family_id       UUID        NOT NULL REFERENCES strategy_family(family_id),
    experiment_id   UUID        REFERENCES experiment(experiment_id),
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    accessed_by     TEXT        NOT NULL,
    reason          TEXT        NOT NULL
);

CREATE INDEX experiment_family_idx ON experiment (family_id, trial_index);
CREATE INDEX holdout_access_family_idx ON holdout_access (family_id, accessed_at);
