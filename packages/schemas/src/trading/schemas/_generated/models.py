"""Pydantic models generated from the contract declarations.

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
]
