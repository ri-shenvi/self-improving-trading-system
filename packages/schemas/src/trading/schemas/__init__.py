"""Frozen contracts: the shapes every on-disk format and API boundary embeds.

Importing this package registers every contract, so
:func:`trading.schemas.registry.all_contracts` is complete after ``import
trading.schemas``.

Contract modules are discovered and imported automatically rather than listed
here. A hand-maintained list has a silent failure mode that this package cannot
afford: forgetting one line would leave a contract out of the lock and out of
codegen, so it would be neither hash-pinned nor type-checked, and nothing would
say so. Discovery removes the possibility rather than documenting it.
"""

import importlib
import pkgutil

from trading.schemas.identifiers import InstrumentId, RawPartitionId
from trading.schemas.money import NanoDollars, RoundedMoney, Shares, dollars, narrow, shares
from trading.schemas.registry import all_contracts, get, register
from trading.schemas.spec import ContractSpec, FieldKind, FieldSpec, Maturity, TimeGroup
from trading.schemas.time import TimestampNs, format_ns, parse_rfc3339_ns

#: Modules that hold no contracts and must not be imported for side effects.
#: ``_generated`` in particular imports the models, which would be circular.
_NOT_CONTRACT_MODULES = frozenset(
    {"_generated", "identifiers", "io", "money", "ordering", "registry", "spec", "time"}
)


def _import_contract_modules() -> None:
    for module in pkgutil.iter_modules(__path__):
        if module.name in _NOT_CONTRACT_MODULES or module.name.startswith("_"):
            continue
        importlib.import_module(f"{__name__}.{module.name}")


_import_contract_modules()

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
