"""Pin contract shapes, and refuse silent changes to them.

A contract's canonical form and hash are checked into
``packages/schemas/registry/contracts.json``. ``make verify`` recomputes them and
fails if they disagree with what is declared in code, so a field cannot change
without the change appearing in a reviewed diff.

Accepting a change is deliberate and separate from running the tests: ``--accept``
rewrites the lock, and a FROZEN contract additionally requires
``--break-frozen "<reason>"``. Frozen means bytes exist on disk in that shape, so
the reason is recorded in the lock's history. This mirrors the ``# allow: TRD00N
reason`` escape hatch in ``tools/banned_patterns.py``: an override that is
possible, but costs a sentence you have to justify.

Usage::

    python tools/schema_registry.py --check
    python tools/schema_registry.py --accept [--break-frozen "reason"]
"""

from __future__ import annotations

import argparse
import sys

import trading.schemas  # noqa: F401  -- import for the side effect of registering contracts
from trading.schemas.registry import LOCK_PATH, Maturity, all_contracts, check, render_lock


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="fail if the lock disagrees")
    group.add_argument("--accept", action="store_true", help="rewrite the lock")
    parser.add_argument(
        "--break-frozen",
        metavar="REASON",
        help="acknowledge that a frozen contract is changing, and why",
    )
    args = parser.parse_args(argv)

    findings = check()

    if args.check:
        if not findings:
            print(f"contract registry: {len(all_contracts())} contract(s) match the lock.")
            return 0
        for finding in findings:
            print(f"\n{finding}", file=sys.stderr)
        print(
            f"\n{len(findings)} contract finding(s). If these changes are intended, "
            "run: uv run python tools/schema_registry.py --accept",
            file=sys.stderr,
        )
        return 1

    frozen_changes = [
        f.contract
        for f in findings
        if any(c.name == f.contract and c.maturity is Maturity.FROZEN for c in all_contracts())
    ]
    if frozen_changes and not args.break_frozen:
        print(
            "refusing to re-accept frozen contract(s): "
            + ", ".join(sorted(frozen_changes))
            + "\nFiles already written in the old shape become unreadable. If that is "
            'intended, pass --break-frozen "<reason>".',
            file=sys.stderr,
        )
        return 1

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(render_lock(), encoding="utf-8")
    print(f"wrote {LOCK_PATH} ({len(all_contracts())} contract(s))")
    if args.break_frozen:
        print(f"frozen contracts changed, reason recorded: {args.break_frozen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
