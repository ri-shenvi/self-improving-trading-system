# self-improving-trading-system

A research-first platform for discovering, validating and cautiously deploying
U.S. equity intraday trading strategies.

**Status: pre-implementation.** The repository currently contains the
implementation plan only. No code has been written.

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

## Documents

- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — scope,
  locked technical decisions, the twelve frozen contracts, twelve milestones
  with mechanically checkable exit tests, explicit anti-scope, and the
  end-to-end verification procedure.

Derived from the *Intraday Agentic Trading System Specification* v1.0
(19 September 2026).
