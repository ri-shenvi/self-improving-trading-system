"""Frozen contracts: the shapes every on-disk format and API boundary embeds.

Importing this package registers every contract, so
``trading.schemas.registry.all_contracts()`` is complete after ``import
trading.schemas``. Contract modules are imported here for that side effect; add
new ones to the list below or they will be absent from the lock and from codegen.
"""

from trading.schemas.identifiers import InstrumentId, RawPartitionId
from trading.schemas.money import NanoDollars, RoundedMoney, Shares, dollars, narrow, shares
from trading.schemas.registry import all_contracts, get, register
from trading.schemas.spec import ContractSpec, FieldKind, FieldSpec, Maturity, TimeGroup
from trading.schemas.time import TimestampNs, format_ns, parse_rfc3339_ns

__all__ = [
    "ContractSpec",
    "FieldKind",
    "FieldSpec",
    "InstrumentId",
    "Maturity",
    "NanoDollars",
    "RawPartitionId",
    "RoundedMoney",
    "Shares",
    "TimeGroup",
    "TimestampNs",
    "all_contracts",
    "dollars",
    "format_ns",
    "get",
    "narrow",
    "parse_rfc3339_ns",
    "register",
    "shares",
]
