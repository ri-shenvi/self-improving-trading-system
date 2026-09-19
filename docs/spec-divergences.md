# Divergences from the specification

The *Intraday Agentic Trading System Specification* v1.0 is the blueprint. Where
the implementation departs from it, the departure is recorded here with its
reason — silent divergence is what makes a blueprint stop describing the system.

Each entry states what the spec says, what we build, and why. Divergences are
added by the change that introduces them, never retroactively.

---

## 1. `order_event` is keyed on the broker's event identity

**Spec §9** declares `UNIQUE(account_id, client_order_id, event_type, event_time)`.

**We key on** `UNIQUE(account_id, broker_event_id)`, with partial unique indexes
on `execution_id` and `broker_sequence`, and the spec's tuple retained as a
non-unique index.

**Why.** The spec's key fails twice. Two partial fills of one order can share a
timestamp — venues report sub-microsecond executions and some brokers truncate —
and under that key the second is rejected as a duplicate, so the fill history is
silently incomplete and `position == Σ signed fills` (§40) stops holding. It also
assumes every event carries a `client_order_id`, which unsolicited cancels and
post-reconnect events for unrecognised orders do not.

Partial unique indexes rather than one composite `UNIQUE` over `COALESCE`
sentinels: a sentinel collapses genuinely distinct rows, which is the same class
of bug being fixed. The spec's tuple was always a query pattern wearing a
constraint's clothes, and it survives as an index.

Where a broker supplies no event identity, `broker_event_id` is a deterministic
hash over the canonical payload. That cannot distinguish two byte-identical
partial fills at the same nanosecond, and it is not pretended otherwise: it is a
broker capability gap for the adapter to report, not something a schema can
conjure away.

**Status.** Implemented at M1 — `infra/migrations/0002_order_event.sql`.

---

## 2. Byte-equivalent metrics require a pinned thread count

**Spec §2** expects "byte-equivalent orders and metrics for repeated runs on the
same snapshot", at 100 percent for deterministic paths.

**We keep the criterion** and pin what makes it achievable: `OMP_NUM_THREADS`,
`OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`,
`VECLIB_MAXIMUM_THREADS` and `POLARS_MAX_THREADS` are all fixed at 1, alongside
`PYTHONHASHSEED=0` and `TZ=UTC`.

**Why.** Orders are reproducible from ordering and seeding alone. Float *metrics*
are not: BLAS and OpenMP split reductions across threads, and the split point
decides summation order, so the same data on a machine with a different core
count yields metrics differing in the last bits. The alternative — restating the
criterion as a hash over metrics rounded to a declared precision — is recorded as
the fallback if single-threaded reductions ever become too slow. It was not
chosen now because "approximately reproducible" is not reproducible, and once
reconciliation assertions carry a tolerance you can no longer distinguish a
rounding artifact from an accounting bug.

**Cost.** Single-threaded numerics. Accepted until profiling says otherwise;
research throughput is a parallel-experiments problem, not a parallel-BLAS one.

**Status.** Implemented at M0 — `trading.runtime.determinism`, enforced in the
Makefile, Dockerfile and CI workflow, with a test asserting all three agree.

---

## 3. Pre-trade risk reads one-event-stale state, on purpose

**Spec §16** runs `pre_trade_risk.filter(intents, broker_shadow_state)` against
state that has not yet seen fills generated later in the same loop iteration.

**We keep this exactly** and pin it with a test.

**Why.** It is correct and conservative: risk decides using only what was known
at the decision instant. But it *reads* like an off-by-one, which makes it
exactly the kind of thing a future contributor "fixes" — and the fix is a
look-ahead leak that would make risk checks consult fills that had not happened
yet. Documented in the engine module docstring and pinned by an ordering test, so
changing it requires deleting a test that says why.

**Status.** To be implemented at M3 with the event loop.

---

## 4. Provenance is recorded as two fields, not one

**Spec §9** stores a single `container_digest` per experiment; **§40** asks a
reviewer to reproduce any metric from the experiment ID alone.

**We record two fields**: `container_digest` (which image ran) and
`environment_fingerprint` (a deterministic hash over base image digest, resolved
lockfile, interpreter version and the pinned environment).

**Why.** They answer different questions and only one of them is reproducible.
An image digest identifies the artifact after the fact but cannot be recomputed:
builds embed timestamps and layer ordering, so building "the same" image twice
gives different digests from identical inputs. A reviewer reconstructing an
environment needs to check that what they built matches what ran, and the digest
cannot tell them. The fingerprint can, because it is computed over inputs rather
than outputs. Recording only the digest would make §36's Phase 0 exit criterion —
"two builds from one lockfile yield the same digest" — untestable as written.

**Status.** Implemented at M0 — `trading.runtime.fingerprint`. The experiment
table carries `environment_fingerprint` alongside `container_digest` from M1.

---

## 5. Additional package: `packages/runtime`

**Spec §37** lists the repository layout without a home for cross-cutting
runtime concerns.

**We add** `packages/runtime`, holding the determinism envelope, seed derivation
and provenance capture. It depends on nothing else in the workspace and
everything else depends on it.

**Why.** These are preconditions for every other package rather than the concern
of any one of them, and section 2 makes them hard controls. Putting them in
`schemas` would make the contract package depend on process management; putting
them in each consumer would produce several subtly different seeding schemes,
which is precisely the failure the single recorded `random_seed` exists to
prevent.

**Status.** Implemented at M0.

---

## 6. The §6 timestamps are two groups, not six fields on every record

**Spec §6** requires six time fields — `event_time`, `receive_time`,
`process_time`, `knowledge_time`, `effective_time`, `revision_time` — and reads
as though all six belong on every record.

**We split them.** `TimeGroup.CORE` carries four required timestamps plus a
nullable `revision_time`. `TimeGroup.EFFECTIVE` adds a required `effective_time`.
A contract declares which group it belongs to.

**Why.** `effective_time` means "when this record becomes economically
effective" — a corporate action's ex-date, a ticker assignment's start. A trade
print has no such date, ever, for any row. Carrying the column anyway would make
it 100% null across the largest tables in the system, which is not a contract but
an invitation: every reader must handle it, and sooner or later a feature author
reads it and finds zero.

`revision_time` is genuinely nullable rather than absent, because a trade print
*can* be corrected or cancelled — the vendor publishes both — so the column is
meaningful and usually empty. Forcing a sentinel instead would make "never
revised" indistinguishable from "revised at the epoch".

Raw records carry only `event_time` and `receive_time`: `process_time` means
"normalization completed", which has not happened yet. Raw and normalized are
therefore separate contracts rather than one contract with optional fields.

**Cost.** Any helper that projects the timestamps must branch on the group, and
`ContractSpec` carries a `time_group`. Small and contained, against a
permanently meaningless column on billion-row tables.

**Status.** Implemented at M1 — `trading.schemas.spec.TimeGroup`.

---

## 7. Nanosecond timestamps are stored as `BIGINT`, not `TIMESTAMPTZ`

**Spec §9** types `event_time` and `receive_time` as `TIMESTAMPTZ`.

**We store** `event_time_ns`, `receive_time_ns` and `knowledge_time_ns` as
`BIGINT`, with `event_time` as a generated `TIMESTAMPTZ` column for human queries.

**Why.** Postgres `TIMESTAMPTZ` is microsecond precision. It would silently
truncate the nanoseconds that D3 makes authoritative and that the §16 ordering
key depends on — and the truncation is invisible, because a microsecond-truncated
timestamp still looks like a perfectly good timestamp. Two events that the
ordering key distinguishes would become indistinguishable in the durable log,
which is precisely where reconciliation needs them separate.

**Status.** Implemented at M1 — `infra/migrations/0002_order_event.sql`.

---

## 8. Prices and money use one scale, not per-instrument tick scaling

**The implementation plan's D2** specified prices at per-instrument tick scale,
quantities as int64 shares, and cash in micro-dollars.

**We use** integer nano-dollars (1e-9 USD) for every monetary value, with
integer share quantities.

**Why.** A per-instrument scale is also *time-varying* — sub-penny rules put
prices under $1.00 on a $0.0001 increment — so a stored scaled price is
meaningless without an `(instrument_id, as_of)` lookup, which is itself a
point-in-time join that must be got right, and which stops a raw parquet file
being self-describing. Mixed scales also force a conversion at every
`price × quantity`, reintroducing rounding exactly where §40 demands PnL
"reconcile **exactly** from fills".

With one scale, nano-dollars times a dimensionless share count is nano-dollars.
There is no conversion anywhere for one to be wrong in.

**The limit is stated rather than assumed.** int64 nano-dollars caps at
$9,223,372,036.85. That is ample for any single value and routine for a
cumulative gross-notional figure over a multi-year backtest, and **numpy int64
overflow wraps silently** — verified: `9e18 + 9e18` is negative. So stored values
are range-checked through `narrow()`, which raises, while accumulators stay
Python ints, which are arbitrary-precision and cannot be quietly wrong.

**Where rounding is permitted.** Not where the plan said. A regulatory rate of
$0.0000051 per share is exactly 5,100 nano-dollars — fees are not the problem.
Rounding comes from *division by a non-integer ratio*: a mid price `(bid + ask) / 2`
is half-nano whenever the sum is odd, which is most quotes; borrow accrual divides
an annual rate by 360; impact models take a percentage of notional. Costs round
away from zero and credits toward it — both against us — and each rounding returns
the discarded remainder, so `value + remainder == exact` and accounting can assert
that money is neither created nor destroyed *in the presence of rounding*.

**Status.** Implemented at M1 — `trading.schemas.money`.

---

## 9. `instrument_id` is an int64 surrogate, not a UUID

**The implementation plan's D6** named a UUID surrogate.

**We use** an int64 assigned by the instrument master.

**Why.** D6's requirement is a permanent, never-reused surrogate that is never a
ticker; it does not require a particular width. This column appears on every row
of the largest tables in the system, where a 36-byte string would cost more than
the rest of a trade print combined, and it joins and sorts faster.

**Status.** Implemented at M1 — `trading.schemas.identifiers`.

---

## 10. Contracts carry a maturity level

**The implementation plan** treated all twelve contract families as frozen at M1.

**We use** two levels: `frozen` (bytes exist on disk; changing it is a breaking
migration requiring `--break-frozen "<reason>"`) and `provisional` (no durable
representation yet; settles at the milestone that implements it).

**Why.** "Frozen" was doing two jobs: *this has bytes on disk* and *we have
thought about this enough*. `StrategySpec` has neither property at M1 — the DSL
does not exist until M5. Declaring it frozen leads to breaking the freeze at M5,
after which everyone learns that frozen is negotiable, which devalues the freeze
on `normalized.trade` where it is genuinely load-bearing. A freeze is a social
contract, and spending it on a guess is how you lose it.

Both levels are hash-pinned; the difference is what a change costs. Maturity is
part of the canonical form, so promoting provisional to frozen is itself a
versioned, reviewable event rather than an edit.

**The split that matters.** A document's *field set* can be provisional while its
*canonical encoder* cannot: `strategy_spec_hash` is stored on every experiment
row and `snapshot_id` **is** the hash of a manifest body, so a change to how a
document becomes bytes would make every stored hash unreproducible. The encoder
is frozen at M1; the fields are not.

**Status.** Implemented at M1 — `trading.schemas.spec.Maturity`,
`trading.schemas.canonical_json`.

---

## 11. Snapshot identity derives from content hashes, not file bytes

**The implementation plan's D10** hashes `(path, file_sha256, row_count)`.

**We record two hashes per file** and intend `snapshot_id` to derive from the
content hash.

**Why.** Parquet embeds `created_by` in its footer — verified: a file written
here reads back `parquet-cpp-arrow version 25.0.1`. A pyarrow upgrade would
therefore change every file's bytes and invalidate every snapshot, including
experiments nobody touched. `file_sha256` stays, because detecting corruption is
its job. `content_sha256`, over the Arrow IPC encoding of the combined table,
carries no writer version and is independent of chunking (both verified).

**How identity and integrity are separated.** `SnapshotManifest` has two hashes,
because they answer different questions:

- `snapshot_id()` hashes `identity_body()`: each file's `path`, `row_count`,
  `content_sha256`, `contract` and `contract_version`, plus every semantic
  manifest field (calendar version, corporate-action version, cost model id,
  data-quality report, licence). It answers *which data did this experiment
  read*. Files are sorted by path, so listing order — an artifact of how the
  manifest was assembled — does not affect it.
- `canonical_hash()` hashes the full body, `file_sha256` included. It answers
  *are these exact bytes intact*, and is what detects corruption or tampering.

`file_sha256` is therefore still recorded and still checked; it simply does not
define identity. Including it would mean a routine pyarrow upgrade changed the
identity of every snapshot in the corpus without a single row changing,
invalidating experiments nobody touched and breaking §40's promise that a result
can be reproduced from its experiment id alone.

A manifest also rejects duplicate paths: two entries for one path leave the
snapshot ambiguous about which bytes were read.

**Status.** Resolved. Writer implemented at M1 — `trading.schemas.io`; manifest
identity implemented in `trading.schemas.documents.SnapshotManifest`, with tests
asserting that `file_sha256` alone does not move `snapshot_id` while every
content-bearing and semantic field does.
