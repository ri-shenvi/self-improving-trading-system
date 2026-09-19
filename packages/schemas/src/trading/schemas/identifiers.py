"""Stable identifiers that are never a ticker (D6).

§7 is explicit: "Never join solely on ticker." Tickers are reassigned and reused
— a symbol that meant one company in 2019 can mean another in 2024 — so joining
on one silently mixes two instruments' histories. The resulting survivorship and
symbol-reuse bugs are the worst kind: they produce plausible, publishable
backtests, and §41 lists survivorship as its own failure mode.

So every row keys on a surrogate assigned by the instrument master, and the
ticker is resolved through an effective-dated history only at the edges.

The surrogate is an ``int64`` rather than the UUID named in the approved plan.
It appears on every row of the largest tables in the system, where a 36-byte
string would cost more than the rest of a trade print combined, and it joins and
sorts faster. D6's requirement is a permanent, never-reused surrogate; it does
not require a particular width.
"""

from __future__ import annotations

from typing import NewType

#: Permanent surrogate key for a tradable instrument. Assigned by the instrument
#: master, never reused, never derived from a ticker.
InstrumentId = NewType("InstrumentId", int)

#: Identifies a raw partition, for provenance on every normalized row.
RawPartitionId = NewType("RawPartitionId", str)
