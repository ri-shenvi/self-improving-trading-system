# self-improving-trading-system

A research-first platform for discovering, validating and cautiously deploying
U.S. equity intraday trading strategies.

**Status: M0 complete.** Foundations and the determinism envelope are in place.
There is no market data, no backtester and no strategy yet — see the milestone
list in the implementation plan.

## What this is

An apparatus for *disproving* trading strategies cheaply and honestly. A
researcher states a falsifiable hypothesis, compiles it into a constrained
Alpha DSL, runs it against a content-addressed data snapshot, and has it
attacked by a validation gauntlet — walk-forward with purging and embargo,
cost stress, parameter and universe perturbation, block bootstrap, regime
tests, and multiple-testing corrections that count every trial in the
strategy family, including the failures.

The governing architectural constraint: **a language model may propose and
organize research, but deterministic systems own data access, feature
calculation, experiment execution, statistical evaluation, risk decisions,
order generation and broker communication.** No LLM process holds broker
credentials or an order-submission capability.

## What this is not

No system design can ensure positive PnL or eliminate loss. Raw backtest
Sharpe is never a sufficient release criterion, and a low candidate pass rate
through the gauntlet is the intended outcome, not a defect. Nothing here is
investment advice or a stock recommendation.

## Working on it

```sh
make install    # uv sync --all-packages
make verify     # lint, strict typecheck, banned patterns, model audit, tests
make up         # local Postgres, Redis and MinIO
```

`make verify` is the whole gate. CI runs it and nothing else, so a green local
run and a green pipeline cannot diverge.

Results are only reproducible inside a pinned environment, so the Makefile,
Dockerfile and CI workflow all export the same determinism envelope — fixed
thread counts, `PYTHONHASHSEED=0`, `TZ=UTC` — before any interpreter starts. A
test asserts the three declarations agree, and `trading.runtime` refuses to run
outside it.

## Documents

- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — scope,
  locked technical decisions, the twelve frozen contracts, twelve milestones
  with mechanically checkable exit tests, explicit anti-scope, and the
  end-to-end verification procedure.
- [`docs/spec-divergences.md`](docs/spec-divergences.md) — every departure from
  the specification, with its reason.
- [`docs/vendor-timestamp-mapping.md`](docs/vendor-timestamp-mapping.md) — how
  Alpaca fields become the six required timestamps, and how `knowledge_time` is
  derived rather than copied.

Derived from the *Intraday Agentic Trading System Specification* v1.0
(19 September 2026).
