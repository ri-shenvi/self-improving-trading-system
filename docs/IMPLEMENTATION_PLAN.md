# Implementation Plan — Intraday Agentic Trading System

## Context

`ri-shenvi/self-improving-trading-system` is an empty repository — git init, zero commits, no remote branches. The uploaded specification (v1.0, 43 sections, Parts A–F) is a complete blueprint for a research-first intraday U.S. equity platform. Its central claim, from the opening section, is the thing the whole architecture exists to enforce: **the LLM may propose and organize research, but deterministic systems must own data access, feature calculation, experiment execution, statistical evaluation, risk decisions, order generation, and broker communication.**

This plan builds that system from nothing.

**What the deliverable is.** A researcher can state a hypothesis, compile it to a constrained DSL, run it against a pinned data snapshot, have it attacked by a full validation gauntlet, and receive a defensible **reject** — reproducibly, with the trial counted against its family's multiple-testing budget. Getting an *accept* is not a software acceptance criterion. Per the spec's own opening limitation, nothing here makes a strategy profitable; the apparatus exists to disprove strategies cheaply and honestly, and §2 says so outright ("Candidate pass rate through full gauntlet — low by design; rejection is healthy").

**Scope, confirmed with the user:**

| Decision | Choice |
|---|---|
| Build scope | Spec **Phases 0–4** (§36): foundations, market data, event backtester, feature registry + Alpha DSL, validation gauntlet — plus a bounded slice of Phase 6 (OMS + Alpaca paper adapter), which the architecture below makes nearly free. |
| Market data | **Alpaca**, whose event schemas [6] already model the §6 timestamp semantics. |
| Feed tier | **Start IEX, upgrade to SIP later.** Quote-replay fills are built but refuse IEX data. |
| Broker | **Alpaca paper adapter now; live path scaffolded and inert.** |
| Strategies | **Three families + synthetic overfit/stable controls** (§42.10). |
| Short selling | **Long-only v1**; compiler rejects `side: short`. A daily job begins accruing borrow history for a later v2. |
| Spec defects | **Fix in code, document each divergence.** |

---

## The one structural change to the spec's roadmap

§36 orders the phases as a narrative. As a *dependency* order it has one significant defect worth correcting before any code is written:

**§36 places the OMS and pre-trade risk in Phase 6, but the Phase 2 backtester already needs them.** The §16 event loop literally calls `pre_trade_risk.filter(intents, broker_shadow_state)` and `simulator.submit(...)`. Building order-state handling inside the simulator in Phase 2 and then writing the live OMS (§30) fresh in Phase 6 yields **two order state machines and two risk engines** — after which the paper-fidelity gate (§20, §23) is comparing two *implementations* rather than a model against reality, and every divergence is ambiguous.

**The correction: the backtest simulator is a broker adapter.** Take the §30 adapter method table — `get_capabilities`, `get_account`, `get_positions`, `submit_order`, `cancel_order`, `replace_order`, `stream_events`, `get_orders_since`, `get_shortability` — and make it the seam. `SimBroker` implements it; the Alpaca paper adapter implements it; live would implement it later. The OMS state machine, pre-trade risk, accounting and reconciliation are written **once**, above the seam.

Three things follow, all of them wins:

- Paper fidelity becomes a comparison of *fill models*, not of codebases — which is the only comparison that means anything.
- §21's explicit demand to "test kill-switch, halt, LULD, stale-feed, partial-fill, reject, disconnect, reconnect, and duplicate-event behavior **inside replay**" becomes possible. It is impossible if the OMS doesn't exist until Phase 6.
- The user's "Alpaca paper adapter now" choice collapses to writing one more implementation of an interface that already exists.

Two smaller corrections, adopted below:

- **Drop the vectorized research engine.** §35's "differential" test layer implies one, but no phase delivers it, §16 permits it only for early feature research, and a second PnL implementation is a classic origin of same-bar look-ahead (§41). Replace the differential layer with: *two fill models on one engine must agree where their stated assumptions overlap, and bar-pessimistic must never be more optimistic than quote-replay.* Stronger test, one class instead of one engine.
- **Split §18 attribution.** The cost half (spread, impact, fees, borrow, timing) derives mechanically from fills → engine milestone. The risk-factor half (alpha, beta, sector) needs sector data and a factor model → validation milestone. Shipping them together either blocks the engine on a factor model or ships a half-attribution everyone then trusts.

There is also a genuine **circular dependency between Phase 4 and Phase 9**: Phase 4's exit criterion runs through the DSR/PBO gate, which consumes `family_trial_count_at_start` (§39), whose family membership §28 determines via an embedding-similarity engine that is Phase 9. Broken by inverting the authority — see decision D8.

---

## Decisions to lock before writing code

Settled here so no milestone re-litigates them. Each names the cost of getting it wrong.

| # | Decision | Ruling | Cost of error |
|---|---|---|---|
| **D1** | **Vendor timestamp semantics** | Before the first schema is authored, write the Alpaca-field → `(event_time, receive_time, knowledge_time)` mapping into a versioned document beside the connector. Require venue event timestamps, not ingest times. | Unrepairable. If vendor timestamps are ingest rather than venue times, every `knowledge_time` is wrong and the true value is unrecoverable from stored data. Every backtest built before the discovery is worthless. |
| **D2** | **Price and money representation** | Scaled `int64` — prices at per-instrument tick scale, quantities as int64 shares, cash and PnL as int64 micro-dollars. `Decimal` at boundaries only. `float64` confined to the statistics layer. | §40 requires PnL to "reconcile **exactly** from fills." Float accumulation turns "exactly" into a tolerance argument, and once reconciliation assertions carry `approx`, you permanently lose the ability to tell a rounding artifact from an accounting bug. |
| **D3** | **Time representation** | `int64` nanoseconds since epoch, UTC, everywhere. Naive `datetime` fails schema validation. `America/New_York` appears only at DSL parse and report render. | DST and early-close bugs silently shift decision clocks — a high-yield source of fake alpha. |
| **D4** | **The §6 time sextuple is mandatory** | Every normalized row carries all six fields. A row missing `knowledge_time` cannot be written — enforced in the Arrow schema, not by convention. | Retrofitting means re-ingesting everything and invalidating every prior experiment. |
| **D5** | **PIT joins are one function** | `as_of_join(...)` is the only sanctioned join, and it **raises** — never silently filters — if any candidate right-row has `knowledge_time > decision_time`. Direct `join`/`join_asof` inside `packages/features` is lint-banned. | Ad-hoc joins are how leakage enters. §41 lists look-ahead as failure mode #1. |
| **D6** | **Instrument identity** | Permanent surrogate `instrument_id`; `ticker_history(instrument_id, ticker, effective_time, end_time)`; all partitioning and joins keyed on `instrument_id`; ticker appears only at the UI edge. §7: "Never join solely on ticker." | Cheapest to decide early, most expensive to retrofit — every parquet partition, feature file and order record would be rewritten. Worse, the resulting survivorship bugs are *silent*: they produce plausible, publishable backtests. |
| **D7** | **Postgres / Parquet boundary** | Postgres owns mutable transactional state: experiment/family/trial registry, holdout access log, release registry, risk-policy versions, live `order_event`. Parquet + DuckDB owns immutable bulk data: raw/normalized market data, features, experiment artifacts. Redis holds only ephemeral state rebuildable from Postgres. Never time series in Postgres; **never the trial counter in a file.** | A trial counter in files means races, means wrong trial counts, means DSR and PBO are wrong, means the entire §19 anti-overfitting architecture is ceremonial. This is the control table's "invalidate multiple-testing statistics until reconstructed" — and reconstruction is generally impossible. |
| **D8** | **Family definition** | `family_id` is declared explicitly and **immutably at hypothesis creation**, governed by a written rule in `configs/` (same mechanism + same core feature set + same decision-clock class), human-reviewed. §28's similarity engine is **advisory forever** — it flags suspected unregistered merges; it never mutates a trial count. | Breaks the Ph4↔Ph9 cycle. Never let a statistical penalty depend on an embedding threshold. And trial counts reset by renaming — the exact attack §28 describes — are undetectable after the fact. |
| **D9** | **Determinism envelope** | Randomness from `SeedSequence(seed).spawn()`, one named stream per consumer. Module-level `random`/`np.random` lint-banned. Pin `PYTHONHASHSEED`, `TZ=UTC`, **BLAS/OMP thread counts** (thread count changes float reduction order and therefore metric bytes), base image by digest, lockfile hash. Capture the container digest **from the running container**, not a build-time variable. | Nominally reproducible experiments that silently differ because a transitive dep or thread count changed — discovered when someone tries to reproduce a six-month-old result, which is precisely when §40's first criterion is supposed to earn its keep. |
| **D10** | **Content addressing** | `snapshot_id` **is** the sha256 of the manifest body, over the sorted list of `(relative_path, file_sha256, row_count)` plus calendar version, corporate-action version, cost-model version and DQ report hash. A `SnapshotReader` **refuses to open any path not listed in the manifest**. | The reader restriction is what actually enforces §16's "as-was data" invariant, rather than trusting every future author to remember. |
| **D11** | **IEX partial-venue provenance** | Every quote row carries `venue_coverage: iex_only \| sip`. The quote-replay fill model **refuses to run on `iex_only` data**. DQ reports state coverage prominently. | Silently simulating NBBO fills against a 2–3% venue is the most dangerous single error available in this build. |
| **D12** | **Bars are built, not vendored** | Built from normalized trades with a documented condition filter (§7). Vendor bars retained only as a reconciliation sample. | Vendor bar revision semantics leak into features, and a historical bar becomes irreproducible — breaking the as-was guarantee at the bottom of the stack. |
| **D13** | **Calendar authority + closed clock enum** | One versioned exchange calendar, recorded in the snapshot manifest. Decision clocks are a **closed enum**, so the compiler can statically compare `availability_lag` against clock spacing. | If clocks are free-form strings, §13's "static leakage report" cannot be static, and the single highest-yield compile-time leak check becomes a runtime hope. |
| **D14** | **Short selling** | Long-only v1. The DSL compiler **rejects `side: short`** with an explicit reason code, per §17: "Reject a historical short if borrow plausibility is absent rather than assuming free inventory." From M7, a daily job snapshots Alpaca shortability/ETB flags so a real borrow history accrues for v2. | Otherwise half the §15 catalog generates unachievable short legs and the pipeline manufactures edge that cannot be traded — worse than having no strategies, because it produces confident, well-validated wrong answers. |
| **D15** | **Broker paper is an integration surface, not evidence** | §17 and [5] establish that Alpaca paper models neither impact, leakage, latency, queue position, price improvement nor regulatory fees. Paper exercises the OMS and adapter. Performance evidence comes from the platform's own simulator fed by live data in SHADOW. | Otherwise you spend §23's 60 required sessions accumulating "paper evidence" containing no fill model at all, and canary detonates the fidelity gate — after a calendar quarter you cannot get back. |

---

## The twelve frozen contracts

`packages/schemas` is written **first and frozen** before anything consumes it, in this dependency order. Everything else in the §37 package list can move; these cannot, because every later package embeds them in on-disk formats.

1. **Time** — the §6 sextuple as a reusable struct, canonical UTC-nanosecond representation, plus an `AsOf` query type.
2. **Instrument identity** — surrogate `instrument_id` + `ticker_history`.
3. **Ordering key** — `(event_time, source_rank, vendor_sequence, venue_sequence, ingest_index)`: the concrete realization of §16's "Stable priority" invariant.
4. **Market event union** — Trade, Quote, Bar, Status/Halt/LULD, CorporateAction, ReferenceUpdate, each carrying (1) and (3).
5. **SnapshotManifest** — §8 content hashes, partitions, license id, calendar version, CA version, DQ report hash.
6. **FeatureSpec + FeatureValue** — the §12 YAML fields as typed models.
7. **StrategySpec** + canonical serialization + `strategy_spec_hash` (§13).
8. **Experiment / Family / TrialIndex** — the §9 DDL plus `holdout_access`.
9. **OrderIntent / OrderEvent / Fill / Position / AccountState** (§9, §30).
10. **RiskPolicy** (signed, versioned) + **RiskDecision** with a closed reason-code enum (§25).
11. **CostModel** — effective-dated, versioned, referenced by id from the experiment manifest (§17, §39).
12. **Money / Price / Quantity** (per D2) and **Calendar / Session** types.

---

## Milestones

Twelve. Each exit test is a command that exits nonzero on failure, not a judgment call. Sizes: **S** ≈ days, **M** ≈ 1–2 weeks, **L** ≈ 3+ weeks.

### M0 — Foundations and determinism harness · *Ph 0* · M

Monorepo per §37. Python 3.12, `uv` locking, `mypy --strict`, `ruff`, `pytest` + `Hypothesis`. Docker Compose (Postgres, Redis, MinIO). CI: lint → typecheck → banned-pattern greps → unit → property → golden. The D9 determinism envelope. D1's vendor timestamp-mapping document.

**Creates:** `pyproject.toml`, `packages/*/` skeletons, `infra/docker/Dockerfile`, `.github/workflows/ci.yml`, `Makefile` (`make verify`), `docs/spec-divergences.md`, `docs/vendor-timestamp-mapping.md`.

**Exit test:** `make verify` green from a clean clone. `test_no_naive_datetime` fails any model with a bare `datetime`. `test_container_digest` asserts the running process reads its own image digest and that two builds from one lockfile yield the same digest.

### M1 — Freeze the twelve contracts · *Ph 0, §§6, 7, 9* · M

All twelve contract families as paired Pydantic + Arrow schemas. Postgres DDL for `experiment` and `order_event` per §9 — with the documented divergence below. Operating-state enum (§5) with CANARY/LIVE present but guarded at a single call site.

> **Spec divergence 1.** §9's `UNIQUE(account_id, client_order_id, event_type, event_time)` rejects legitimate distinct partial fills sharing a timestamp. Add a broker-supplied sequence or execution id to the key.
> **Spec divergence 2.** §2's "byte-equivalent metrics" is unachievable for float aggregates without pinned thread counts and reduction order. We pin them (D9) and keep the criterion; the alternative — a hash over metrics rounded to a declared precision — is recorded as the fallback. "Approximately reproducible" is not reproducible, so this is decided, not left ambiguous.

**Creates:** `packages/schemas/{time,instrument,market_events,snapshot,feature_spec,strategy_spec,experiment,orders,risk_policy,cost_model,money,calendar}.py`, `infra/migrations/0001_*.sql`.

**Exit test:** parametrized round-trip (Pydantic → Arrow → Parquet → Pydantic) equality for every model. A schema-hash stability test failing loudly on any contract change without a version bump. A test asserting a row missing `knowledge_time` is rejected at write time.

### M2 — Golden fixture, normalization, snapshot manifest · *Ph 0–1, §42.3–4* · M

The hand-authored fixture: one fictional symbol, one trading day, ~2,000 trade and quote events plus one instrument-master row and one calendar day — **synthetic and committed to git**, so CI runs it with no licensing entanglement, but schema-faithful to Alpaca (this is why D1 lands first). Normalization; bars built from trades per D12; `snapshot build|verify|materialize`; the D10 `SnapshotReader`.

§42.4 asks for exactly this: "Build a tiny deterministic replay fixture before a large backtester."

**Creates:** `packages/market_data/{normalize,bars,calendar,instruments}.py`, `packages/market_data/snapshot/{manifest,builder,reader}.py`, `tests/golden/fixtures/tiny_day/`, `apps/cli/`.

**Exit test:** (a) build twice → identical `snapshot_id`; (b) append an unrelated correction partition → `snapshot_id` unchanged *and* re-running an experiment yields identical metrics; (c) flip one byte in a listed file → `verify` fails; (d) `SnapshotReader.open(unlisted_path)` raises. Bars rebuilt from the fixture match a checked-in golden parquet byte-for-byte.

### M3 — Thin vertical slice: event engine, broker seam, OMS, quote-replay fills, costs, PnL · *Ph 2 + OMS pulled forward from Ph 6; §§16–18, 30, 42.5* · L

**This is the pivotal milestone.** The §16 loop implemented literally; the `BrokerAdapter` protocol (§30) with `SimBroker` as its first implementation; the pure OMS state machine; pre-trade risk with reason codes; cash and positions reconciled exactly from fills; the §17 cost decomposition.

It runs end to end on the M2 fixture: fixture → normalize → snapshot → one feature → one strategy → event backtest → `orders/fills/positions/pnl.parquet` + `metrics.json` → integrity gate → HTML report.

**Why a slice rather than the next layer.** §40's first criterion — reproduce any metric from the experiment ID alone using pinned data, code, container, config and seed — is *cross-cutting*: it touches the manifest, the registry, the container capture, the seed discipline and the report writer. Under layer-by-layer phasing you first test that property in Phase 3, after three layers have been built on unvalidated assumptions about it. A frozen schema that has never been read by a feature, a compiler, a fill model and a report is a guess; the slice consumes all twelve contracts once, cheaply.

**Deliberately quote-replay, not bar-pessimistic.** Quote replay is the harder model and the one that actually constrains event ordering, latency and partial fills. Bar-pessimistic arrives later as a *second* implementation of the same interface — which is what then yields the differential test for free. Building the easy fill model first would defer exactly the decisions that matter. The fixture is synthetic, so D11's IEX restriction does not bite here.

**Deliberately stubbed** — every *interface* on the load-bearing list is real; only the *implementations* are thin:
- Universe → hard-coded single symbol; `universe_ref` resolves to a literal list.
- Corporate actions → fixture asserts none; CA version is a null sentinel.
- Shorts → rejected with a reason code (D14).
- Market impact → zero, but the cost report emits `impact: 0.0 (model=none)` so it is *visibly* missing, not silently absent.
- Portfolio → identity map behind the real `Portfolio.convert()` signature from §16.
- Risk → three checks (price collar, max position, session window) behind the real interface and full reason-code enum.
- Strategy → a `CompiledStrategy` object constructed directly in Python. M5's DSL adds a front end producing the same object, so there is no rework.
- Validation → integrity gate only. Agents, live path, web UI absent; OpenTelemetry present as a no-op tracer so instrumentation sites exist.

**Creates:** `packages/backtest/{clock,event_stream,engine,sim_broker,accounting,costs}.py`, `packages/backtest/fills/quote_replay.py`, `packages/oms/{state_machine,order_store,client_order_id}.py`, `packages/risk/{pretrade,reason_codes}.py`, `packages/brokers/base.py`.

Two details worth pinning:
- `client_order_id` is derived deterministically from `(strategy_version, instrument_id, decision_time, intent_hash)`, so a retry regenerates the same id rather than a new order.
- The OMS transition function is **pure** — `(state, event) -> (new_state, actions)`, zero I/O — so a `hypothesis.stateful` machine can explore tens of thousands of interleavings in milliseconds.

**Exit test:** golden replay reproduces a checked-in orders/fills/pnl triple byte-exactly. An **always-on runtime assertion** (not test-only) that `fill_source_event.key > order.submit_key`, plus a mutation test that deletes it and asserts the golden diff fails. Hypothesis properties: `position == Σ signed fills`; `cash delta == −Σ(price×qty) − fees`. A stateful OMS test against a scripted adversarial broker asserting: never two live orders per `client_order_id`; no transition out of a terminal state; a submit that times out and later acks produces exactly one order; unresolvable `UNKNOWN` reaches SAFE within budget. Determinism double-run byte-equality.

> **Spec divergence 3.** §16's loop runs `pre_trade_risk.filter` against state one event stale relative to fills generated later in the same iteration. This is correct and conservative — but it is exactly what a future contributor "fixes" into a look-ahead leak. Documented as intentional in the engine docstring and pinned by a test.

### M4 — Feature registry and causal operators · *Ph 3a, §12, §42.6* · L

Versioned `FeatureSpec` registry; the D5 PIT join primitive; warm-up isolation; 15–25 baseline features across the §12 groups (price/return, liquidity, order flow, volatility, relative value, regime, execution); a harness running §12's three mandated tests against every registered feature automatically.

**Creates:** `packages/features/{registry,pit,clock}.py`, `packages/features/operators/{price,liquidity,orderflow,volatility,relative_value,regime}.py`, `packages/features/testing/harness.py`, `configs/features/`.

**Exit test:** §40 criterion 2, in both halves. **Static:** the operator graph cannot reference post-decision nodes. **Dynamic:** a leakage fuzzer generates a random history with revisions and out-of-order arrivals, computes each feature at `T`, appends an arbitrary set of records all with `knowledge_time > T`, and asserts the value at `T` is **bit-identical**. CI fails if any registered feature lacks any spec field or any of `causal_window` / `finite_when_volume_positive` / `invariant_to_events_after_decision_time`. A warm-up test asserts PnL attributable to warm-up bars is exactly zero. A mutation test swaps `knowledge_time` for `event_time` inside the join and asserts the suite goes red — if it stays green, the test is decorative.

### M5 — Alpha DSL v1 · *Ph 3b, §13, §42.7* · L

Grammar, parser, resolver, compiler for the §13 form. Operators for momentum, reversal, VWAP, relative value, filters, exits and risk. The compiler emits all five §13 artifacts: operator graph, dependency manifest, **static leakage report**, complexity score (node count + free-parameter count), canonical hash. Each node carries `(decision_clock, lookback, availability_lag, warm_up)`; compilation fails if any node's knowledge-time offset relative to decision time exceeds zero. Risk values clamp into the signed envelope — strategies **tighten but never loosen** (§13), by construction.

The highest-value single check, enabled by D13: reject any feature whose `availability_lag` exceeds its decision-clock spacing. §12's own example (`availability_lag: 250ms`, `decision_clock: 1m_close`) is fine; the inverse is the most common real leak and is statically detectable.

**Creates:** `packages/alpha_dsl/{grammar,ast,parser,resolver,leakage,compiler,canonical}.py`, `configs/strategies/`.

**Exit test:** a corpus of ~20 checked-in strategies, ≥10 deliberately leaky in *distinct* ways — session VWAP computed to the close; final daily volume; a forward-window extremum; revised data; `availability_lag` exceeding clock spacing; a feature version that didn't exist at the backtest start date. Assert zero false negatives **and** that each rejection carries the expected reason code (a compiler that rejects everything also achieves zero false negatives). Canonical hash invariant under key reordering, comments and whitespace; sensitive to every semantic edit. Declared-vs-observed dependency-manifest equality on an instrumented run. A strategy raising a risk limit fails compilation; `side: short` is rejected with the D14 reason code.

### M6 — Experiment registry, family trials, reproducibility, reports · *Ph 3c, §§9, 39, §42.8* · M

The §9 Postgres schema; `experiment create|run|show`; container/seed/commit capture; the §39 manifest; HTML report with full cost decomposition.

**`trial_index` is allocated in a serializable transaction at experiment *creation*, not completion** — so cancelled, crashed and abandoned runs still consume an index. That is precisely what the control table demands: "Every variant, prompt, parameter sweep, and rejected run increments the strategy family trial count." The final-holdout date range is readable only through one code path requiring an explicit token, which increments `holdout_access_count`.

**Creates:** `packages/memory/registry/{models,repository,trials,holdout}.py`, `infra/migrations/`, `apps/api/routers/experiments.py`, `packages/backtest/report/`.

**Exit test:** N parallel `experiment create` calls yield exactly N distinct indices, no gaps or duplicates. A run killed with SIGKILL mid-flight leaves its index permanently consumed. Any read touching holdout dates without a token raises and emits an audit row. Renaming a strategy does not reset its family trial count. Reproduction from `experiment_id` alone, in a fresh checkout under the pinned container, yields an identical `metrics.json`.

*This milestone completes §40's criteria 1, 3 and 5.*

### M7 — Alpaca ingestion, instrument master, corporate actions, PIT universe, DQ gates · *Ph 1 proper, §§7, 10, 11, §42.1–2* · L

The Alpaca connector; instrument master with ticker history; corporate actions with announcement *and* effective times; halts and LULD; the §11 universe builder; the nine §10 quality gates as blocking checks; a 30-session quality report. Raw partitions append-only and never overwritten; corrections appended and resolved through versioned views (§8). D11 coverage stamping. The D14 daily borrow-snapshot job starts here.

**Sequencing note.** This deliberately lands *after* the engine, inverting §36's Ph1 → Ph2. The connector is the component most likely to be rewritten, and building it once you know exactly which fields the engine and features consume avoids normalizing dozens you never read. The licensing and timestamp-semantics *decision* still happens at M0 (D1) — only the code moves.

**Creates:** `packages/market_data/vendors/alpaca/`, `packages/market_data/{corporate_actions,halts,universe,borrow_snapshot}.py`, `packages/market_data/quality/`, `configs/universes/liquid_us_equities_v1.yaml`.

**Exit test:** all nine §10 gates emit metrics against configured thresholds and the 30-session report generates. A **survivorship test** builds the universe as of a past date, asserts it contains at least one symbol since delisted or renamed, and asserts no membership decision consumed data with `knowledge_time` after the membership date. A **known-split test** asserts raw prices unchanged for execution, adjusted series correct for features, and that the unresolved-CA gate blocks snapshot release. A deliberately corrupted partition is quarantined, not ingested.

### M8 — Validation gauntlet and attack battery · *Ph 4, §§19–22, 26, §42.9* · L

The twelve §20 gates at their default thresholds: integrity, economic, cost stress (2×/3×), walk-forward, parameter stability, universe stability, concentration, bootstrap, regime, attribution, multiple testing (DSR ≥ 0.95, PBO < 0.20), paper fidelity. Chronological splits with purging and embargo (§19). All twelve §21 attacks. The nine §26 scenarios exercised inside replay — possible because M3 built the OMS. Factor attribution, deferred from M3, lands here.

Thresholds live in a versioned policy file, and the policy version must be pinned in the manifest **before** the run — a strategy cannot select a threshold after seeing results (§20).

**Creates:** `packages/validation/{splits,walkforward,purge_embargo,bootstrap,dsr,pbo,perturbation,cost_stress,regimes,attribution,attacks,scenarios,gauntlet}.py`, `configs/gates/research_v1.yaml`.

**Exit test** — the §35 statistical layer as the gate:
- (a) 1,000 random strategies on null labels → pass rate ≤ nominal α.
- (b) A synthetic signal of known SNR → pass rate within tolerance of an analytically computed power curve.
- (c) A strategy overfit by construction (best of 500 sweeps on dev data) fails at least one gate, **with the specific gate name asserted**. Naming the gate is what makes §36's Ph 4 exit criterion mechanically checkable rather than aspirational.
- (d) A purge/embargo unit test on constructed overlapping-label data where leakage magnitude is known in closed form.
- (e) DSR evaluated at trial 1 versus trial 500 on *identical* return series produces materially different verdicts — proving trial accounting is wired into the statistics, not merely recorded.
- (f) Signal-shift-by-one-and-two-bars degrades PnL monotonically within tolerance and never improves it.

### M9 — Three strategy families and overfit controls · *Ph 3–4, §§14, 15, §42.10* · M

Opening-range continuation, VWAP deviation reversion, intraday residual momentum — each pre-registered per the §14 hypothesis fields and the §15 protocol (mechanism, target, decision clock, universe, search budget, expected failures, acceptance criteria), each competing against its §15-required baselines, each with a naive baseline built before any complexity. Plus deliberately-overfit twins and known-stable controls.

> **Consequence of D14 worth stating plainly:** all three run long-only. VWAP reversion loses its short leg, and residual momentum — naturally a market-neutral long-short construct — is reduced to a long-only cross-sectional top-decile. This weakens both families' economic case and should be read as a *data limitation*, not a finding about the strategies. The borrow-snapshot job started at M7 is what unblocks the honest long-short version later.

**Creates:** `configs/strategies/families/`, `configs/hypotheses/`, `tests/statistical/test_family_calibration.py`.

**Exit test:** each family produces a complete written decision record — mechanism, evidence, weaknesses, capacity, rollback triggers (§15 step 7) — whether the verdict is promote or reject. §15 protocol step 2 is enforced **in code**: a complex variant failing to beat its naive baseline on net OOS utility is auto-rejected. Each overfit twin fails at its expected gate.

### M10 — Alpaca paper adapter, SHADOW mode, reconciliation, SAFE, kill switch · *bounded Ph 6, §§30–31* · M

The Alpaca paper adapter behind M3's existing `BrokerAdapter` — a second implementation, not a second system. Streaming feature computation reusing M4 operators verbatim. `apps/live_runner` in SHADOW only (live data, hypothetical orders, no submission). The §31 startup and shutdown checklists. Reconciliation against broker-authoritative state. SAFE mode and `POST /risk/kill`.

CANARY and LIVE transitions raise at the single guarded call site from M1. The live path is scaffolded, not enabled.

**Creates:** `packages/brokers/alpaca_paper.py`, `apps/live_runner/`, `packages/oms/reconcile.py`, `packages/risk/continuous.py`, `infra/runbooks/`.

**Exit test:** §40 criterion 8 — duplicate submission, network timeout, unknown order, disconnect, partial fill, halt, stale data and kill switch each resolve to a **named** documented safe state, one test per §26 scenario. A shadow-versus-backtest equivalence test replays one recorded live session through the engine and asserts identical order generation — the paper-fidelity harness, which only works because M3 built one OMS. Paper and live cannot share account IDs or credentials (§40 criterion 9). A network-policy test asserts the research service cannot reach the broker host. A test proves no path reaches broker submission without a signed strategy, risk policy and fresh market data.

### M11 — API surface, control plane, observability · *§§32, 38* · M

The nine §38 endpoints with their authorization tiers. The §32 monitoring plane across data, strategy, execution, risk, PnL and systems domains, each metric mapped to a runbook. Critical risk and reconciliation alerts move the system to SAFE automatically. OpenTelemetry, Prometheus, Grafana, structured logs.

**Creates:** `apps/api/routers/`, `apps/web/` (minimal read-only research + risk views), `infra/observability/`.

**Exit test:** every §38 endpoint has an authz test proving the wrong role is rejected. A kill-switch drill completes within a configured SLA. Paper and live are visibly distinguished in UI and logs (§40 criterion 9) — the one UI requirement that cannot be deferred, satisfied with a banner on whatever surface exists, including the CLI.

---

### Execution order

M0 → M1 → M2 → **M3 (the slice)** → M4 → M5 → M6 → M7 → M8 → M9. M10 and M11 can run alongside M6–M9, since they depend only on the M1 contracts and the M3 seam.

**Mapping to §36:** Ph 0 → M0, M1, M2. Ph 1 → M2, M7. Ph 2 → M3. Ph 3 → M4, M5, M6, M9. Ph 4 → M8, M9. Ph 6 (bounded) → M3 (OMS/risk) + M10. Ph 5, 7, 8, 9 → out of scope.

---

## Anti-scope

Deferred deliberately. Each names the seam that keeps it cheap later.

| Deferred | Spec | Seam that keeps it cheap | Why safe |
|---|---|---|---|
| Agent layer | §27, Ph 5 | The §38 API is the agents' only entry point and is built for humans first — typed and correct means agents are purely additive. | Building agents early injects nondeterminism into a system whose principal deliverable is determinism. All §40 criteria are met with zero agents. |
| Knowledge graph + similarity | §28, Ph 9 | `family_id`, `hypothesis_id`, `parent_experiment_id` are columns from M1; the graph is later *derived* from relational tables. | A graph can be built from labeled relational data at any time; it cannot be built from family labels never recorded. **Defer the graph, never the registry.** |
| Contextual bandit research policy | §29, Ph 9 | Post-validation OOS utility reward is recorded from M8 onward, so training data accrues meanwhile. | §29 defers it itself. With a few dozen trials there is nothing to learn. |
| Portfolio optimizer | §24 | `Portfolio.convert(signal) -> intents` exists from M3; the optimizer is a second implementation. | §24 says so itself. A covariance optimizer over a one-strategy book is complexity with no degrees of freedom. |
| Live / canary | §§23, 31, Ph 7–8 | `BrokerAdapter`, the signed-release registry and the §5 state machine all exist — going live is configuration plus approval, not a rewrite. | §23 requires 60 paper + 20 canary sessions: calendar time that cannot be compressed and is not on the critical path for any §40 criterion. |
| Trade-and-quote replay with queue estimation | §17 tier 3 | Each fill model declares its `required_data` and tier; the promotion record stores which tier produced each result. | Quote replay (tier 2) is the v1 bar. Evidence quality stays explicit and upgradeable per candidate. |
| Close-imbalance strategies | §15 | — | Require auction imbalance entitlement and queue modeling. §15 already lists "inability to model queue" as a primary failure mode — the one family the spec half-disqualifies itself. |
| News and filings | §7, §12 Event group | The `knowledge_time` / `receive_time` / `revision_time` distinction in contract (1) is exactly what news needs; nothing structural changes when it arrives. | Worst timestamp semantics (vendor backfill times masquerading as publication times), highest leakage surface, large incremental licensing cost. |
| Vectorized research engine | implied by §35 | Differential layer redefined as two fill models on one engine. | A second PnL implementation is a classic origin of same-bar look-ahead. |
| Rust hot paths | §4 | Feature computation stays on Arrow batches, not Python objects per tick. | §4's own upgrade trigger. First bottleneck will be I/O and feature recomputation, not the loop. |
| Dagster/Prefect, Kafka/NATS, read replicas | §4 | — | Deferred per §4's own upgrade triggers. |

---

## Verification

**Per-commit (CI, all blocking per §35):**

```
make verify   # ruff → mypy --strict → banned-pattern greps (naive datetime,
              #   raw joins in packages/features, module-level random, ticker joins)
              # → pytest: unit, property, golden, differential, mutation
```

**End-to-end acceptance**, run against the §40 criteria once M0–M9 land:

1. **Reproducibility** — `trading reproduce <experiment_id>` re-materializes the snapshot from its manifest, rebuilds the container from its digest, re-runs with the stored seed, and asserts byte-equality of `orders.parquet`, `fills.parquet`, `pnl.parquet` and `metrics.json`. *(§40.1)*
2. **Causality proof** — `trading audit-causality --all-features` runs the static operator-graph check and the dynamic post-decision-mutation fuzzer over every registered feature. *(§40.2)*
3. **Trial accounting** — `trading audit-families` asserts every experiment, including failed, cancelled and abandoned, is counted, and that no family's trial count ever decreased. *(§40.3)*
4. **Gauntlet calibration** — `pytest tests/statistical/` runs the six M8 exit assertions, including the null-label and time-scrambled runs finding no edge. *(§40.6)*
5. **Cost honesty** — every report shows gross, each cost component separately, base net, and 2×/3× stressed net. *(§40.5)*
6. **Safety drills** — `pytest tests/chaos/` covers the eight §40.8 failure modes, each resolving to its named safe state; then a manual kill-switch drill against the paper account. *(§40.8)*
7. **Data quality** — `trading quality-report --sessions 30` generates, is reviewed, and states IEX partial-venue coverage explicitly. *(§2 Data quality)*
8. **Separation** — `pytest tests/security/` asserts paper and live cannot share credentials or account IDs, and that no research-side process holds a broker credential or a network route to the broker. *(§40.7, §40.9)*

**The honest limitation to carry forward.** On the IEX feed, §20's cost-stress and paper-fidelity gates cannot be evaluated credibly, because IEX quotes are not the NBBO. Until SIP lands, research runs on conservative fills and candidate promotion past "research approved" (§23) is unsupported — recorded in `docs/spec-divergences.md` rather than papered over.
