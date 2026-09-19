-- The live order event log (§9), append-only and independently reconciled.
--
-- DIVERGENCE 1 from §9. The specified key,
--   UNIQUE(account_id, client_order_id, event_type, event_time)
-- rejects two legitimate partial fills that share a timestamp, so the order's
-- fill history goes silently incomplete and "position equals the signed sum of
-- fills" (§40) stops holding. It also assumes every event has a
-- client_order_id, which unsolicited events and post-reconnect events for
-- unrecognised orders do not.
--
-- The key is therefore the broker's own event identity. Partial unique indexes
-- rather than one composite UNIQUE with COALESCE sentinels: a sentinel collapses
-- distinct rows, which is the same class of bug being fixed here.
--
-- DIVERGENCE 7. §9 specifies TIMESTAMPTZ, which in Postgres is microsecond
-- precision and would silently truncate the nanoseconds D3 makes authoritative
-- and the ordering key depends on. The *_ns BIGINT columns are authoritative;
-- event_time is a generated column for human queries only.

CREATE TABLE order_event (
    event_id            UUID        PRIMARY KEY,
    account_id          TEXT        NOT NULL,
    -- Nullable: an unsolicited cancel has no client order id of ours.
    client_order_id     TEXT,
    broker_order_id     TEXT,
    -- Broker-supplied where available, otherwise a deterministic hash over the
    -- canonical payload. Which one it is, is a broker capability the adapter
    -- reports; a derived identity cannot distinguish two byte-identical partial
    -- fills at the same nanosecond, and that is a capability gap to be reported
    -- rather than something the schema can conjure away.
    broker_event_id     TEXT        NOT NULL,
    execution_id        TEXT,
    broker_sequence     BIGINT,
    event_type          TEXT        NOT NULL,
    state               TEXT        NOT NULL,
    risk_reason         TEXT        NOT NULL,

    event_time_ns       BIGINT      NOT NULL,
    receive_time_ns     BIGINT      NOT NULL,
    knowledge_time_ns   BIGINT      NOT NULL,
    event_time          TIMESTAMPTZ GENERATED ALWAYS AS (
        TIMESTAMPTZ 'epoch' + (event_time_ns / 1000) * INTERVAL '1 microsecond'
    ) STORED,

    strategy_version    TEXT        NOT NULL,
    risk_policy_version TEXT        NOT NULL,
    payload             JSONB       NOT NULL,

    -- A fill without an execution id cannot be deduplicated or reconciled.
    CONSTRAINT order_event_fill_requires_execution_id CHECK (
        event_type <> 'fill' OR execution_id IS NOT NULL
    ),
    -- D4 reaches Postgres too: a row that claims to be known before it happened
    -- is leakage wherever it is stored.
    CONSTRAINT order_event_knowledge_not_before_event CHECK (
        knowledge_time_ns >= event_time_ns
    ),

    UNIQUE (account_id, broker_event_id)
);

CREATE UNIQUE INDEX order_event_execution_uk
    ON order_event (account_id, execution_id) WHERE execution_id IS NOT NULL;
CREATE UNIQUE INDEX order_event_sequence_uk
    ON order_event (account_id, broker_sequence) WHERE broker_sequence IS NOT NULL;
-- The spec's tuple, retained as a query path. It was always an access pattern
-- wearing a constraint's clothes.
CREATE INDEX order_event_order_lookup
    ON order_event (account_id, client_order_id, event_time_ns);
