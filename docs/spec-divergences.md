# Divergences from the specification

The *Intraday Agentic Trading System Specification* v1.0 is the blueprint. Where
the implementation departs from it, the departure is recorded here with its
reason — silent divergence is what makes a blueprint stop describing the system.

Each entry states what the spec says, what we build, and why. Divergences are
added by the change that introduces them, never retroactively.

---

## 1. `order_event` uniqueness includes an execution identifier

**Spec §9** declares `UNIQUE(account_id, client_order_id, event_type, event_time)`.

**We add** a broker-supplied sequence or execution id to the key.

**Why.** Two partial fills of the same order can share a timestamp — venues
report sub-microsecond executions and some brokers truncate. Under the spec's key
the second fill is rejected as a duplicate, so the order's fill history is
silently incomplete and `position == Σ signed fills` (§40) stops holding. The
constraint is meant to make retries idempotent, which it still does; it was not
meant to cap executions per microsecond.

**Status.** To be implemented at M1 with the `order_event` DDL.

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

**Status.** Implemented at M0 — `trading.runtime.fingerprint`.

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
