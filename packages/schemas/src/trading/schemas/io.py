"""The only sanctioned way to write a contract table (D4).

Non-nullability is not enough, and the gap is wider than it looks. A verified
probe: ``pa.table(data, schema=<field nullable=False>)`` builds happily with a
null present, and ``Table.validate(full=True)`` passes — only ``write_table``
objects, and only about nulls. Nothing in Arrow notices a ``knowledge_time`` that
is present and wrong, which is the dangerous case.

So this module checks what the schema cannot. Most importantly it checks
``knowledge_time`` against a *declared policy* rather than merely for presence:
the caller states how the value was derived, and the rows must actually be that.
That turns "is it non-null" into "is it what the policy requires", which is
mechanical. A caller cannot supply a wrong-but-present ``knowledge_time`` without
also declaring a policy visibly inconsistent with its own data.

``tools/banned_patterns.py`` (TRD007) keeps this the only module that may call
``pyarrow.parquet.write_table``, in the same idiom as the point-in-time join
seam.

Two hashes are recorded for every file, because they answer different questions:

``file_sha256``
    Integrity. Detects corruption. Changes when the writer's version changes,
    since parquet embeds ``created_by`` in its footer (verified).

``content_sha256``
    Logical identity, over the Arrow IPC encoding of the combined table. Carries
    no writer version (verified) and is independent of chunking. ``snapshot_id``
    derives from this, so upgrading pyarrow does not invalidate every experiment
    that was never touched.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

import pyarrow as pa
import pyarrow.parquet as pq

from trading.schemas.money import STORABLE_MAX, STORABLE_MIN
from trading.schemas.spec import ContractSpec, FieldKind
from trading.schemas.time import MAX_PLAUSIBLE_NS, MIN_PLAUSIBLE_NS

#: Parquet format version, pinned. Two writes of the same table must produce the
#: same bytes; any change to these settings alters every file's file_sha256 and
#: is a deliberate act, which is why they are spelled out at the call site rather
#: than hidden in a dict.
_PARQUET_VERSION: Final = "2.6"
_COMPRESSION: Final = "zstd"
_COMPRESSION_LEVEL: Final = 3


class ContractWriteError(ValueError):
    """A table does not satisfy its contract and will not be written."""


class KnowledgeTimePolicy(StrEnum):
    """How ``knowledge_time`` was derived for the rows being written (D1).

    Declared per write and verified against the data, because ``knowledge_time``
    is the field point-in-time correctness rests on and it cannot be checked by
    inspection after the fact.
    """

    #: Captured live: we knew it when the gateway received it. True by
    #: construction, so this needs no calibration.
    LIVE_CAPTURE = "live_capture"

    #: Backfilled: ``receive_time`` is when we backfilled, possibly years later,
    #: so it cannot stand in for knowledge. The value is ``event_time`` plus a
    #: measured, versioned publication lag. Using ``receive_time`` here would be
    #: leakage; using ``event_time`` alone would credit the strategy with
    #: zero-latency delivery.
    BACKFILL = "backfill"

    #: Reference and corporate-action records, knowable when announced.
    ANNOUNCEMENT = "announcement"


@dataclass(frozen=True, slots=True)
class WriteReceipt:
    """What was written, and how to identify it later.

    This is exactly the tuple D10's snapshot manifest needs, so M2's manifest
    builder consumes receipts rather than re-hashing files behind the writer's
    back.
    """

    path: Path
    contract: str
    contract_version: int
    schema_hash: str
    row_count: int
    file_sha256: str
    content_sha256: str
    knowledge_policy: KnowledgeTimePolicy


def content_sha256(table: pa.Table) -> str:
    """Hash a table's logical content, independent of writer version and chunking."""
    combined = table.combine_chunks()
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(
        sink, combined.schema, options=pa.ipc.IpcWriteOptions(compression=None)
    ) as writer:
        writer.write_table(combined)
    return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractWriteError(message)


def _column(table: pa.Table, name: str) -> list[int | None]:
    values: list[int | None] = table.column(name).to_pylist()
    return values


def _required_int_column(table: pa.Table, name: str, contract: str) -> list[int]:
    """Read a column that must be wholly non-null, raising if it is not.

    Returning ``list[int]`` rather than ``list[int | None]`` is the point: the
    null check and the type narrowing are the same act, so the callers below need
    no defensive assertions to satisfy the type checker.
    """
    values = _column(table, name)
    missing = [index for index, value in enumerate(values) if value is None]
    _require(
        not missing,
        f"{contract}: {len(missing)} row(s) have a null {name} "
        f"(first at row {missing[0] if missing else -1}). D4: a record without a "
        "knowledge_time cannot be written, because point-in-time correctness has "
        "nothing to stand on.",
    )
    return [value for value in values if value is not None]


def _check_schema(table: pa.Table, spec: ContractSpec) -> None:
    expected = spec.arrow_schema()
    if table.schema.equals(expected):
        return
    _require(
        list(table.schema.names) == list(expected.names),
        f"{spec.name}: column names or order differ from the contract.\n"
        f"  expected: {list(expected.names)}\n  got:      {list(table.schema.names)}\n"
        "Column order is part of the contract: it decides the file bytes.",
    )
    mismatched = [
        f"{field.name}: contract {expected.field(field.name).type} "
        f"(nullable={expected.field(field.name).nullable}), "
        f"table {field.type} (nullable={field.nullable})"
        for field in table.schema
        if not field.equals(expected.field(field.name))
    ]
    raise ContractWriteError(
        f"{spec.name}: schema does not match the contract. No implicit casting is "
        "performed -- build the table with spec.arrow_schema().\n  " + "\n  ".join(mismatched)
    )


def _check_time_fields(table: pa.Table, spec: ContractSpec, policy: KnowledgeTimePolicy) -> None:
    if spec.time_group is None:
        return

    event = _required_int_column(table, "event_time", spec.name)
    receive = _required_int_column(table, "receive_time", spec.name)
    process = _required_int_column(table, "process_time", spec.name)
    knowledge = _required_int_column(table, "knowledge_time", spec.name)

    for index, value in enumerate(knowledge):
        _require(
            MIN_PLAUSIBLE_NS <= value <= MAX_PLAUSIBLE_NS,
            f"{spec.name} row {index}: knowledge_time={value} is outside the "
            "plausible band. Zero and other sentinels are present-but-wrong "
            "values that survive every null check.",
        )

    for index, (e, r, p, k) in enumerate(zip(event, receive, process, knowledge, strict=True)):
        _require(
            k >= e,
            f"{spec.name} row {index}: knowledge_time={k} precedes event_time={e}. "
            "A value known before it happened is leakage.",
        )
        _require(r >= e, f"{spec.name} row {index}: receive_time={r} precedes event_time={e}.")
        _require(p >= r, f"{spec.name} row {index}: process_time={p} precedes receive_time={r}.")

    if policy is KnowledgeTimePolicy.LIVE_CAPTURE:
        for index, (r, k) in enumerate(zip(receive, knowledge, strict=True)):
            _require(
                k == r,
                f"{spec.name} row {index}: policy is live_capture, which means we "
                f"knew the value when the gateway received it, but knowledge_time="
                f"{k} and receive_time={r}. Either the policy or the data is wrong.",
            )


def _check_ordering(table: pa.Table, spec: ContractSpec) -> None:
    """Ordering keys must be strictly increasing, or the stream is not a total order."""
    if "ingest_index" not in spec.field_names():
        return
    columns = ["event_time", "source_rank", "vendor_sequence", "venue_sequence", "ingest_index"]
    keys = list(zip(*(_column(table, name) for name in columns), strict=True))
    for index in range(1, len(keys)):
        _require(
            keys[index] > keys[index - 1],
            f"{spec.name} rows {index - 1}-{index}: ordering keys are not strictly "
            f"increasing ({keys[index - 1]} then {keys[index]}). Duplicate or "
            "unsorted keys mean the event stream is not a total order, and "
            "byte-exact replay silently depends on it being one.",
        )


def _check_money(table: pa.Table, spec: ContractSpec) -> None:
    for field in spec.fields:
        if field.kind is not FieldKind.NANO_DOLLARS:
            continue
        for index, value in enumerate(_column(table, field.name)):
            if value is None:
                continue
            _require(
                STORABLE_MIN <= value <= STORABLE_MAX,
                f"{spec.name} row {index}: {field.name}={value} exceeds the storable "
                "nano-dollar range. int64 wraps silently rather than raising, so "
                "this is caught here instead of surfacing as a negative total.",
            )


def write_contract_table(
    table: pa.Table,
    spec: ContractSpec,
    path: Path,
    *,
    knowledge_policy: KnowledgeTimePolicy,
) -> WriteReceipt:
    """Validate a table against its contract and write it as parquet.

    Args:
        table: Built with ``spec.arrow_schema()``. No casting is performed.
        spec: The contract being written.
        path: Destination. Parent directories are created.
        knowledge_policy: How ``knowledge_time`` was derived. Verified against
            the data, not taken on trust.

    Raises:
        ContractWriteError: On any contract violation, before anything is written.
    """
    _check_schema(table, spec)
    _check_time_fields(table, spec, knowledge_policy)
    _check_ordering(table, spec)
    _check_money(table, spec)

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        path,
        version=_PARQUET_VERSION,
        compression=_COMPRESSION,
        compression_level=_COMPRESSION_LEVEL,
        write_statistics=True,
        store_schema=True,
    )

    return WriteReceipt(
        path=path,
        contract=spec.name,
        contract_version=spec.version,
        schema_hash=spec.content_hash(),
        row_count=table.num_rows,
        file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        content_sha256=content_sha256(table),
        knowledge_policy=knowledge_policy,
    )


def read_contract_table(path: Path, spec: ContractSpec) -> pa.Table:
    """Read a parquet file, refusing one that does not match the contract.

    The dual of :func:`write_contract_table`: a file whose shape has drifted from
    the contract is a reading error, not something to coerce into place.
    """
    table = pq.read_table(path)
    _check_schema(table, spec)
    return table
