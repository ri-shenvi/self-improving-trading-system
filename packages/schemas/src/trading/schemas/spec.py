"""The declarative contract layer: one field spec, three emitted representations.

A contract is declared once, as data. From that declaration we derive the Arrow
schema (the on-disk contract), the canonical form (what the hash registry pins),
and — through ``tools/codegen.py`` — a checked-in Pydantic model (the validation
boundary). Hand-writing the Arrow schema and the Pydantic model separately would
work until the day they disagreed, and the disagreement would surface as data
that validates and cannot be read back.

Why the Pydantic side is generated to a file rather than built at runtime:
``pydantic.create_model`` produces a class mypy sees as ``BaseModel``, so every
field access on a contract would be untyped. That would quietly undo
``mypy --strict`` across the one package everything else imports. Generated
source is committed, and CI asserts regenerating produces no diff.

Field *kinds* are a closed set rather than arbitrary Arrow types. The closure is
the point: it is what lets ``FieldKind.TIMESTAMP_NS`` mean "int64 UTC
nanoseconds, never a naive datetime" (D3) and ``NANO_DOLLARS`` mean "int64 at
1e-9 USD" (D2') everywhere, instead of each contract choosing its own
representation and the differences only showing up in a reconciliation failure.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import pyarrow as pa


class Maturity(StrEnum):
    """How settled a contract is, and therefore what changing it costs.

    Both levels are version-pinned in the registry. The difference is the
    obligation a change carries, not whether a change is tracked.
    """

    #: On disk. Changing it is a breaking migration: existing partitions must be
    #: rewritten and experiments that read them are invalidated.
    FROZEN = "frozen"

    #: Config or registry shape whose consumer has not been built yet. May change
    #: without a migration until the milestone that implements it, because no
    #: data has been written in this shape.
    PROVISIONAL = "provisional"


class TimeGroup(StrEnum):
    """Which of the §6 time fields a contract carries.

    §6 asks for six timestamps on "every record", but ``effective_time`` — when a
    record becomes *economically* effective — has no meaning for a trade print.
    Carrying it as a permanently-null column on the largest tables in the system
    would be worse than omitting it: every reader would have to handle it, and
    sooner or later a feature author would read it and find zero. So the sextuple
    is split into two groups and a contract declares which it belongs to.

    Recorded as a divergence: §6 says six fields on every record; we say four or
    five, depending on whether the record has an effective date at all.
    """

    #: event, receive, process, knowledge (required); revision (nullable).
    #: Trades, quotes, bars, status, orders, fills, positions, feature values.
    CORE = "core"

    #: CORE plus a required ``effective_time``. Corporate actions, reference
    #: updates, ticker history, calendar, borrow and SSR.
    EFFECTIVE = "effective"


class FieldKind(StrEnum):
    """The closed set of field types a contract may use.

    Each kind maps to exactly one Arrow type and one Python type. Adding a kind
    is a deliberate act; using a raw Arrow type is not possible.
    """

    #: int64 UTC nanoseconds since epoch. The only representation of time in the
    #: system (D3) — naive datetimes are rejected by the checker and the audit.
    TIMESTAMP_NS = "timestamp_ns"

    #: int64 at 1e-9 USD. Every monetary value, so price x quantity is exact and
    #: no cross-scale conversion ever rounds (D2').
    NANO_DOLLARS = "nano_dollars"

    #: int64 whole shares. v1 does not trade fractional quantities.
    SHARES = "shares"

    #: int64 surrogate assigned by the instrument master, never reused (D6).
    INSTRUMENT_ID = "instrument_id"

    #: Venue code. Dictionary-encoded: low cardinality repeated on every row.
    EXCHANGE_CODE = "exchange_code"

    #: Trade or quote condition codes. A list, because prints routinely carry
    #: several and condition filtering decides bar eligibility.
    CONDITIONS = "conditions"

    #: Tape A/B/C.
    TAPE = "tape"

    #: Monotonic sequence supplied by a vendor or venue. Nullable in practice —
    #: not every feed provides one.
    SEQUENCE = "sequence"

    #: Free text. Used for identifiers and codes with open vocabularies.
    TEXT = "text"

    #: UUID, stored as text for legibility. Registry keys only, never row data.
    UUID = "uuid"

    #: Signed 32-bit integer for counts.
    COUNT = "count"

    BOOL = "bool"

    #: Ratio or rate that is genuinely real-valued and never accumulated into
    #: money (for example a borrow rate). Never used for a monetary amount.
    RATIO = "ratio"

    #: Calendar date with no time component, as days since epoch.
    DATE = "date"


_ARROW_TYPES: Final[dict[FieldKind, pa.DataType]] = {
    FieldKind.TIMESTAMP_NS: pa.int64(),
    FieldKind.NANO_DOLLARS: pa.int64(),
    FieldKind.SHARES: pa.int64(),
    FieldKind.INSTRUMENT_ID: pa.int64(),
    FieldKind.EXCHANGE_CODE: pa.dictionary(pa.int8(), pa.string()),
    FieldKind.CONDITIONS: pa.list_(pa.dictionary(pa.int8(), pa.string())),
    FieldKind.TAPE: pa.dictionary(pa.int8(), pa.string()),
    FieldKind.SEQUENCE: pa.int64(),
    FieldKind.TEXT: pa.string(),
    FieldKind.UUID: pa.string(),
    FieldKind.COUNT: pa.int32(),
    FieldKind.BOOL: pa.bool_(),
    FieldKind.RATIO: pa.float64(),
    FieldKind.DATE: pa.date32(),
}

#: Python annotation emitted by codegen for each kind. The NewType wrappers are
#: what make a nano-dollar amount unassignable to a share count under mypy.
_PYTHON_TYPES: Final[dict[FieldKind, str]] = {
    FieldKind.TIMESTAMP_NS: "TimestampNs",
    FieldKind.NANO_DOLLARS: "NanoDollars",
    FieldKind.SHARES: "Shares",
    FieldKind.INSTRUMENT_ID: "InstrumentId",
    FieldKind.EXCHANGE_CODE: "str",
    FieldKind.CONDITIONS: "tuple[str, ...]",
    FieldKind.TAPE: "str",
    FieldKind.SEQUENCE: "int",
    FieldKind.TEXT: "str",
    FieldKind.UUID: "str",
    FieldKind.COUNT: "int",
    FieldKind.BOOL: "bool",
    FieldKind.RATIO: "float",
    FieldKind.DATE: "datetime.date",
}


#: Kinds where misreading the unit silently corrupts money or time, so the unit
#: must be declared and is hashed. This is what recovers decimal128's only real
#: advantage -- a self-describing scale -- without its arithmetic cost.
_REQUIRED_UNITS: Final[dict[FieldKind, str]] = {
    FieldKind.TIMESTAMP_NS: "ns_utc",
    FieldKind.NANO_DOLLARS: "nanodollar",
    FieldKind.SHARES: "share",
}


def emitter_version() -> str:
    """Hash of the kind-to-Arrow mapping itself.

    The canonical form of a contract is written in *our* vocabulary
    (``nano_dollars``), not Arrow's. That is deliberate — it makes a hash immune
    to a pyarrow repr change — but it leaves a hole: silently remapping
    ``NANO_DOLLARS`` from ``int64`` to ``decimal128(38, 9)`` would change every
    file on disk and move no contract hash at all.

    So the mapping is hashed once, into the registry header. Changing it
    invalidates every contract simultaneously, which is correct: it *is* a global
    change to what the bytes mean.
    """
    body = "".join(
        f"{kind.value}={_ARROW_TYPES[kind]}|{_PYTHON_TYPES[kind]}|{_REQUIRED_UNITS.get(kind, '')}\n"
        for kind in sorted(FieldKind, key=lambda k: k.value)
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One field of one contract.

    Args:
        name: Column name. Also the Pydantic field name.
        kind: Which of the closed set of types this field is.
        nullable: Whether the column admits nulls. Defaults to required, so
            nullability is always a deliberate declaration.
        doc: Why the field exists. Emitted into the generated model and into
            Arrow metadata, but deliberately **not** hashed — improving a
            docstring must not force a version bump, or people stop improving
            docstrings.
        unit: Physical unit, hashed. Mandatory for kinds where misreading the
            unit silently corrupts money (see ``_REQUIRED_UNITS``). This is what
            recovers decimal128's one real advantage — a self-describing scale —
            for one line and no arithmetic cost.
        codeset: Versioned vocabulary for a coded field, hashed. Swapping
            ``trade_condition_v1`` for ``v2`` changes how the bytes must be
            interpreted even though the Arrow type is identical.
    """

    name: str
    kind: FieldKind
    nullable: bool = False
    doc: str = ""
    unit: str | None = None
    codeset: str | None = None

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"field name {self.name!r} is not a valid identifier")
        expected = _REQUIRED_UNITS.get(self.kind)
        if expected is not None and self.unit != expected:
            raise ValueError(
                f"field {self.name!r} of kind {self.kind.value} must declare "
                f"unit={expected!r}, got {self.unit!r}"
            )

    def arrow_field(self) -> pa.Field[pa.DataType]:
        return pa.field(self.name, _ARROW_TYPES[self.kind], nullable=self.nullable)

    def python_type(self) -> str:
        base = _PYTHON_TYPES[self.kind]
        return f"{base} | None" if self.nullable else base


@dataclass(frozen=True, slots=True)
class ContractSpec:
    """A versioned contract: the shape of one kind of record.

    Args:
        name: Dotted identifier, e.g. ``normalized.trade``. Also the registry key.
        version: Incremented on any change to the field list. The registry
            refuses a changed contract that did not bump this.
        maturity: See :class:`Maturity`.
        doc: What the record is and where it comes from.
        fields: Ordered. Order is part of the contract — it fixes the Arrow
            column order, therefore the file bytes, therefore the canonical form
            and the hash.
        time_group: Which §6 timestamps this record carries, or ``None`` for a
            contract that is not a time-series record (a manifest, a policy).
    """

    name: str
    version: int
    maturity: Maturity
    doc: str
    fields: tuple[FieldSpec, ...]
    time_group: TimeGroup | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError(f"{self.name}: version must be >= 1")
        if not self.fields:
            raise ValueError(f"{self.name}: a contract needs at least one field")
        seen = [f.name for f in self.fields]
        duplicates = {n for n in seen if seen.count(n) > 1}
        if duplicates:
            raise ValueError(f"{self.name}: duplicate field names {sorted(duplicates)}")

    @property
    def class_name(self) -> str:
        """The generated Pydantic class name, e.g. ``normalized.trade`` -> ``NormalizedTrade``."""
        return "".join(part.title().replace("_", "") for part in self.name.split("."))

    def field(self, name: str) -> FieldSpec:
        for candidate in self.fields:
            if candidate.name == name:
                return candidate
        raise KeyError(f"{self.name} has no field {name!r}")

    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    def arrow_schema(self) -> pa.Schema:
        """The on-disk contract."""
        return pa.schema([f.arrow_field() for f in self.fields])

    def canonical_form(self) -> str:
        """The exact bytes hashed into :meth:`content_hash`.

        Deliberately our own serialization rather than pyarrow's. Arrow's schema
        serialization carries no stability guarantee across library versions, and
        a pyarrow upgrade must not present itself as a contract change — that
        would either mass-invalidate pinned hashes or train everyone to re-pin
        without reading the diff.

        Inspectable on purpose: when a hash check fails, a reviewer needs to see
        which line moved, not that two hex strings differ.
        """
        lines = [
            f"contract={self.name}",
            f"version={self.version}",
            f"maturity={self.maturity.value}",
            f"time_group={self.time_group.value if self.time_group else ''}",
        ]
        lines += [
            # Zero-padded so the ordinal sorts lexicographically in a diff, and
            # so column order -- which decides the file bytes -- is visible.
            f"field={index:03d}:{f.name}:{f.kind.value}:"
            f"{'nullable' if f.nullable else 'required'}:"
            f"unit={f.unit or ''}:codeset={f.codeset or ''}"
            for index, f in enumerate(self.fields)
        ]
        return "".join(f"{line}\n" for line in lines)

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_form().encode("utf-8")).hexdigest()
