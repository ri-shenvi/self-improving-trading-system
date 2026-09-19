# self-improving-trading-system

A research-first platform for discovering, validating and cautiously deploying
U.S. equity intraday trading strategies.

**Status: M1 complete.** Foundations, the determinism envelope, and the frozen
contract layer. There is no market data, no backtester and no strategy yet — see
the milestone list in the implementation plan.

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
make verify     # lint, strict typecheck, banned patterns, contract lock, tests
make verify-db  # the above, plus the layers needing a Postgres server
make codegen    # regenerate contract models after changing a declaration
make up         # local Postgres, Redis and MinIO
```

`make verify` is the gate for everything that runs without external services.
CI runs exactly it, so a green local run and a green pipeline cannot diverge.
The one exception is named rather than hidden: `make verify-db` needs a Postgres
server that the development environment does not have, so those tests skip
locally with a stated reason and run in a separate CI job.

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
- [`docs/specification/`](docs/specification/) — the source specification, with
  a reproducible text extraction that tests read as the authority on what is
  required.

## Contracts

`packages/schemas` holds the shapes every on-disk format embeds. Each is declared
once and emits its Arrow schema, its Pydantic model (generated to a committed
file, so `mypy --strict` still sees typed fields), and a hash pinned in
`packages/schemas/registry/contracts.json`. Changing a field without bumping the
version fails `make verify` with a diff naming the field; changing one that has
bytes on disk additionally requires a stated reason, which is recorded.

Timestamps are int64 UTC nanoseconds, money is integer nano-dollars on a single
scale, and instruments are keyed on a permanent surrogate rather than a ticker.
`trading.schemas.io.write_contract_table` is the only sanctioned way to write a
contract file, because Arrow will not notice a `knowledge_time` that is present
and wrong.

Derived from the *Intraday Agentic Trading System Specification* v1.0
(19 September 2026).
