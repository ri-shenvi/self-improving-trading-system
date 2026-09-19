"""The total order in which the engine sees events (§16, "Stable priority").

§16 requires that events sharing a timestamp are dispatched in a documented,
reproducible order. This module is that document, and the order is a *total*
one — every pair of distinct events compares, always, the same way on every run.
Anything less makes the event stream non-deterministic, and a non-deterministic
stream makes byte-exact replay (§2) impossible.

The key is ``(event_time, source_rank, vendor_sequence, venue_sequence,
ingest_index)``, compared lexicographically.

Note what this module deliberately does *not* decide. Ordering the quote before
the trade at an identical timestamp is the right *dispatch* order, but it is not
by itself conservative for fills — a tightening quote processed first would make
a simulated fill better than reality. Fill conservatism is a separate rule
enforced by the fill model, which requires the quote to be *strictly* before the
order's submission key. Keeping the two apart matters: overloading the rank table
with fill semantics would make both impossible to reason about.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from trading.schemas.time import TimestampNs

#: Stands in for a sequence number the source does not provide.
#:
#: The alternative — "skip to the next component when either side is missing" —
#: is not transitive across a mixed set, so it is not a total order at all. A
#: sentinel that sorts before every real sequence keeps the order total, and
#: sorting *first* is the conservative choice: an event whose position we cannot
#: pin down is dispatched before those we can.
MISSING_SEQUENCE: Final = -1


class SourceRank(IntEnum):
    """Dispatch priority for events sharing a timestamp.

    The governing principle is **constraints before opportunities**: anything
    that restricts what we may do is applied before anything that tempts us to
    act. A halt that lands in the same nanosecond as a print must be visible to
    risk before the print can generate an order.

    Ranks are a policy decision, not an identity, which is why a source declares
    a rank rather than the engine switching on a source name.
    """

    #: A session boundary must be known before anything inside it.
    SESSION = 0
    #: Never generate an order into a symbol halted at this instant.
    STATUS = 1
    #: Bands constrain executability.
    LULD = 2
    #: Reference state before the prices that depend on it.
    REFERENCE = 3
    #: Quote state precedes the trade evaluated against it.
    QUOTE = 4
    TRADE = 5
    #: Derived from the above, so it follows them.
    BAR = 6
    #: Our own timer ticks and acknowledgements. We react; we do not lead.
    SYNTHETIC = 7


@dataclass(frozen=True, slots=True, order=True)
class OrderingKey:
    """Where one event falls in the total order.

    A frozen slotted dataclass rather than a Pydantic model on purpose: the
    engine constructs one of these per event and will see tens of millions of
    them, where per-instance validation overhead would dominate. Validation
    belongs at the ingestion boundary, which is where the contract row is built.

    Attributes:
        event_time: Venue timestamp, int64 UTC nanoseconds.
        source_rank: See :class:`SourceRank`.
        vendor_sequence: Vendor's own sequence, or :data:`MISSING_SEQUENCE`.
        venue_sequence: Venue's sequence, or :data:`MISSING_SEQUENCE`.
        ingest_index: Position within the raw partition. See
            :func:`assign_ingest_index` for why this is not arrival order.
    """

    event_time: TimestampNs
    source_rank: SourceRank
    vendor_sequence: int = MISSING_SEQUENCE
    venue_sequence: int = MISSING_SEQUENCE
    ingest_index: int = 0


#: Sorts before any real event. For engine boundaries — "everything so far".
BEFORE_ALL: Final = OrderingKey(
    event_time=TimestampNs(-(2**63)),
    source_rank=SourceRank.SESSION,
    vendor_sequence=MISSING_SEQUENCE,
    venue_sequence=MISSING_SEQUENCE,
    ingest_index=-(2**62),
)

#: Sorts after any real event.
AFTER_ALL: Final = OrderingKey(
    event_time=TimestampNs(2**63 - 1),
    source_rank=SourceRank.SYNTHETIC,
    vendor_sequence=2**62,
    venue_sequence=2**62,
    ingest_index=2**62,
)


def is_strictly_after(candidate: OrderingKey, reference: OrderingKey) -> bool:
    """Whether ``candidate`` occurs strictly after ``reference``.

    The predicate behind §16's no-same-event-fill invariant: an order may only
    be filled by an event that arrived strictly after its simulated submission.
    Equality is not "after" — that is the whole point.
    """
    return candidate > reference


def assign_ingest_index(position: int) -> int:
    """Return the ingest index for a message at ``position`` in its raw partition.

    ``ingest_index`` is the zero-based position of a message within its raw
    partition, in the byte order of the raw file, assigned during
    **normalization** — never at capture.

    This is the subtle part of the whole contract. If the index came from
    wall-clock arrival, re-ingesting the same raw bytes would produce a
    different total order, hence different fills, hence a backtest that does not
    reproduce — and no comparison of a run against *itself* would ever catch it.
    Deriving it from position makes the key a pure function of immutable bytes.

    Two preconditions, both already required by §8 and D10: raw partitions are
    append-only and byte-stable, and where a session spans several raw files the
    index is assigned over their concatenation in lexicographic filename order
    (so ordinals must be zero-padded — an unpadded one silently reorders).

    Corrections never renumber anything. A correction arrives in a later
    partition with its own index and refers to the event it supersedes; its
    position in an as-of view is governed by ``revision_time``, not by this.
    """
    if position < 0:
        raise ValueError(f"ingest position must be non-negative, got {position}")
    return position
