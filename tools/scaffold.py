"""One-shot scaffold for the M0 package skeleton. Safe to re-run."""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# name -> (summary, intra-workspace deps, external deps)
PACKAGES: dict[str, tuple[str, list[str], list[str]]] = {
    "runtime": (
        "Determinism envelope: seeding, environment pinning, build fingerprints.",
        [],
        ["numpy>=2.1"],
    ),
    "schemas": (
        "Frozen Pydantic and Arrow contracts. Every on-disk format embeds these.",
        ["runtime"],
        ["pydantic>=2.9", "pyarrow>=17"],
    ),
    "market_data": (
        "Vendor connectors, normalization, snapshots and data-quality gates.",
        ["schemas"],
        ["polars>=1.9"],
    ),
    "features": (
        "Versioned causal feature registry and the sanctioned point-in-time join.",
        ["schemas", "market_data"],
        ["polars>=1.9", "numpy>=2.1"],
    ),
    "alpha_dsl": (
        "Alpha DSL parser, validator and compiler with the static leakage report.",
        ["schemas", "features"],
        ["lark>=1.2", "pyyaml>=6.0"],
    ),
    "risk": (
        "Pre-trade checks and continuous limits with closed reason codes.",
        ["schemas"],
        [],
    ),
    "oms": (
        "Pure order state machine, idempotent client order IDs, reconciliation.",
        ["schemas"],
        [],
    ),
    "brokers": (
        "The BrokerAdapter seam. SimBroker and the Alpaca paper adapter.",
        ["schemas", "oms"],
        [],
    ),
    "backtest": (
        "Event clock, engine, fill models, accounting and cost decomposition.",
        ["schemas", "features", "risk", "oms", "brokers"],
        ["polars>=1.9", "numpy>=2.1"],
    ),
    "portfolio": (
        "Forecast scaling and the signal-to-intent seam.",
        ["schemas"],
        ["numpy>=2.1"],
    ),
    "validation": (
        "Walk-forward, purge/embargo, robustness attacks, DSR and PBO.",
        ["schemas", "backtest"],
        ["numpy>=2.1", "scipy>=1.14"],
    ),
    "memory": (
        "Experiment registry, family trial accounting and holdout auditing.",
        ["schemas"],
        ["sqlalchemy>=2.0", "psycopg[binary]>=3.2"],
    ),
}

APPS: dict[str, tuple[str, list[str], list[str]]] = {
    "cli": ("Operator and researcher command line.", list(PACKAGES), ["typer>=0.12"]),
    "api": (
        "FastAPI control and query surface (§38).",
        ["schemas", "memory", "risk"],
        ["fastapi>=0.115"],
    ),
}

PKG_TEMPLATE = """\
[project]
name = "trading-{dist}"
version = "0.0.0"
description = "{summary}"
requires-python = ">=3.12,<3.13"
dependencies = [
{deps}
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/trading"]
"""


def render(kind: str, name: str, summary: str, internal: list[str], external: list[str]) -> None:
    base = ROOT / kind / name
    src = base / "src" / "trading" / name
    src.mkdir(parents=True, exist_ok=True)
    # PEP 420 namespace: deliberately no src/trading/__init__.py.
    deps = [f'    "trading-{d.replace("_", "-")}",' for d in internal]
    deps += [f'    "{d}",' for d in external]
    (base / "pyproject.toml").write_text(
        PKG_TEMPLATE.format(
            dist=name.replace("_", "-"),
            summary=summary,
            deps="\n".join(deps),
        )
    )
    init = src / "__init__.py"
    if not init.exists():
        init.write_text(f'"""{summary}"""\n')
    (src / "py.typed").touch()


for name, (summary, internal, external) in PACKAGES.items():
    render("packages", name, summary, internal, external)
for name, (summary, internal, external) in APPS.items():
    render("apps", name, summary, internal, external)

DIRS = [
    "configs/universes",
    "configs/strategies",
    "configs/risk_policies",
    "configs/environments",
    "configs/features",
    "configs/gates",
    "configs/hypotheses",
    "tests/unit",
    "tests/property",
    "tests/golden",
    "tests/integration",
    "tests/chaos",
    "tests/statistical",
    "tests/security",
    "infra/docker",
    "infra/migrations",
    "infra/observability",
    "infra/runbooks",
]
for d in DIRS:
    p = ROOT / d
    p.mkdir(parents=True, exist_ok=True)
    keep = p / ".gitkeep"
    if not any(c for c in p.iterdir() if c.name != ".gitkeep"):
        keep.touch()

print(f"scaffolded {len(PACKAGES)} packages, {len(APPS)} apps, {len(DIRS)} dirs")
