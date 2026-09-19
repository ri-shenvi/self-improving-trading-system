"""Generate the Pydantic side of every contract from its declaration.

The contract declaration is authoritative and emits both the Arrow schema (at
runtime) and the Pydantic model (here, to a checked-in file).

Generating to a *file* rather than calling ``pydantic.create_model`` is the whole
point. A model built at runtime is ``BaseModel`` as far as mypy is concerned, so
every field access on every contract would be untyped — quietly undoing
``mypy --strict`` across the one package everything else imports. Generated
source keeps the single source of truth and the static types.

``make verify`` regenerates and fails if the result differs from what is
committed, so the file cannot drift from the declarations.

Usage::

    python tools/codegen.py [--check]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

import trading.schemas  # noqa: F401  -- registers the contracts
from trading.schemas.registry import all_contracts
from trading.schemas.spec import ContractSpec

OUTPUT: Final = (
    Path(__file__).resolve().parent.parent
    / "packages/schemas/src/trading/schemas/_generated/models.py"
)

HEADER: Final = '''"""Pydantic models generated from the contract declarations.

DO NOT EDIT. Regenerate with ``make codegen``; ``make verify`` fails if this
file disagrees with the declarations in ``trading.schemas``.

Models are frozen and forbid extra fields: a contract row is a record of what
happened, and a typo in a field name must be an error rather than a silently
ignored attribute.
"""

from __future__ import annotations

import datetime

from pydantic import BaseModel, ConfigDict

from trading.schemas.identifiers import InstrumentId
from trading.schemas.money import NanoDollars, Shares
from trading.schemas.time import TimestampNs

__all__ = [
'''


def render_model(spec: ContractSpec) -> str:
    """Render one contract as a Pydantic class."""
    lines = [
        f"class {spec.class_name}(BaseModel):",
        f'    """{spec.doc}',
        "",
        f"    Contract ``{spec.name}`` v{spec.version} ({spec.maturity.value}).",
        '    """',
        "",
        '    model_config = ConfigDict(frozen=True, extra="forbid")',
        "",
    ]
    for field in spec.fields:
        lines.append(f"    {field.name}: {field.python_type()}")
        if field.doc:
            lines.append(f'    """{field.doc}"""')
    return "\n".join(lines) + "\n"


def render() -> str:
    specs = all_contracts()
    exports = "".join(f'    "{spec.class_name}",\n' for spec in specs)
    body = "\n\n".join(render_model(spec) for spec in specs)
    return HEADER + exports + "]\n" + ("\n\n" + body if body else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args(argv)

    rendered = render()

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != rendered:
            print(
                f"{OUTPUT} is out of date with the contract declarations. Run: make codegen",
                file=sys.stderr,
            )
            return 1
        print(f"generated models: up to date ({len(all_contracts())} contract(s)).")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    (OUTPUT.parent / "__init__.py").write_text(
        '"""Generated contract models. Do not edit by hand."""\n', encoding="utf-8"
    )
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(all_contracts())} contract(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
