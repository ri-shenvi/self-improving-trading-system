"""Runtime audit of contract models for timestamp fields that permit naive values.

``tools/banned_patterns.py`` rejects a bare ``datetime`` annotation where it can
see one in the source. This catches what survives that: a field whose annotation
is built at runtime, aliased, or reached through a generic, and which therefore
accepts a datetime with no timezone.

Both halves are needed because the consequence is the same either way. A naive
timestamp compares equal across timezones and shifts by an hour at a DST
boundary, so a decision clock built on one drifts silently and produces backtest
results nobody can reproduce or explain.

The audit is vacuous until ``packages/schemas`` defines its first model, and
becomes load-bearing the moment it does. That is the intent: wire it into
``make verify`` before there is anything to find, so it is never introduced
retroactively against a body of already-violating code.

Usage::

    python tools/model_audit.py
"""

from __future__ import annotations

import datetime as dt
import importlib
import pkgutil
import sys
import typing
from dataclasses import dataclass
from typing import Any, Final

from pydantic import BaseModel

NAMESPACE: Final = "trading"


@dataclass(frozen=True, slots=True)
class NaiveField:
    model: str
    field: str
    annotation: str

    def render(self) -> str:
        return (
            f"{self.model}.{self.field}: {self.annotation} permits a naive datetime; "
            "use the nanosecond int64 timestamp type from trading.schemas.time (D3)"
        )


def _mentions_datetime(annotation: Any) -> bool:
    """Whether a type annotation admits ``datetime.datetime`` anywhere inside it."""
    if annotation is dt.datetime:
        return True
    return any(_mentions_datetime(arg) for arg in typing.get_args(annotation))


def naive_datetime_fields(model: type[BaseModel]) -> list[NaiveField]:
    """Return the fields of ``model`` whose annotation admits a naive datetime.

    Pydantic's ``AwareDatetime`` is accepted: it rejects naive values at
    validation time, which is the property this audit is actually protecting.
    """
    found: list[NaiveField] = []
    for name, field in model.model_fields.items():
        annotation = field.annotation
        if annotation is None or not _mentions_datetime(annotation):
            continue
        if any(getattr(m, "tz", "missing") is not None for m in field.metadata):
            continue  # constrained to aware values
        found.append(
            NaiveField(
                model=f"{model.__module__}.{model.__qualname__}",
                field=name,
                annotation=repr(annotation),
            )
        )
    return found


def discover_models(namespace: str = NAMESPACE) -> list[type[BaseModel]]:
    """Import every module under ``namespace`` and collect its Pydantic models."""
    try:
        root = importlib.import_module(namespace)
    except ModuleNotFoundError:
        return []

    models: dict[str, type[BaseModel]] = {}
    for info in pkgutil.walk_packages(root.__path__, prefix=f"{namespace}."):
        try:
            module = importlib.import_module(info.name)
        except Exception as exc:  # an unimportable module is itself a finding
            print(f"warning: could not import {info.name}: {exc}", file=sys.stderr)
            continue
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, BaseModel)
                and value is not BaseModel
                and value.__module__.startswith(f"{namespace}.")
            ):
                models[f"{value.__module__}.{value.__qualname__}"] = value
    return [models[key] for key in sorted(models)]


def audit(namespace: str = NAMESPACE) -> list[NaiveField]:
    return [f for model in discover_models(namespace) for f in naive_datetime_fields(model)]


def main() -> int:
    findings = audit()
    for finding in findings:
        print(finding.render())
    if findings:
        print(f"\n{len(findings)} field(s) permit naive datetimes.")
        return 1
    print(f"model audit: no naive datetime fields across {len(discover_models())} model(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
