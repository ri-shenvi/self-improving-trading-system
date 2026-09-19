"""The operating states, and the one place capital can be reached (§5).

§5 defines seven states from OFF through LIVE. This module encodes them, the
transitions between them, and — importantly — the single guarded call site where
a transition into a capital-risking state would happen.

CANARY and LIVE exist in the enum from M1 because leaving them out would mean
retrofitting the state machine later, and a state machine amended under deadline
pressure to reach live trading is exactly the wrong shape. They are unreachable:
:func:`require_transition_allowed` raises for them, at one place, which is what
makes "the live path is scaffolded but inert" a checkable claim rather than an
intention.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class OperatingState(StrEnum):
    """Where the system is, and therefore what it may do (§5)."""

    #: Read historical data and inspect prior artifacts only.
    OFF = "off"
    #: Historical experiments. No broker session.
    RESEARCH = "research"
    #: Live data in, hypothetical orders out. Nothing reaches a broker.
    SHADOW = "shadow"
    #: Submits to an isolated paper account.
    PAPER = "paper"
    #: Tightly capped live orders. Requires explicit human approval.
    CANARY = "canary"
    #: Trades within a signed allocation and risk policy.
    LIVE = "live"
    #: No new risk; cancel open orders; optional guarded flatten.
    SAFE = "safe"


#: States in which an order can reach real capital. Unreachable in v1.
CAPITAL_STATES: Final = frozenset({OperatingState.CANARY, OperatingState.LIVE})

#: Permitted transitions (§5). SAFE is reachable from everywhere: a critical
#: invariant failure must never be blocked by the state machine.
_ALLOWED: Final[dict[OperatingState, frozenset[OperatingState]]] = {
    OperatingState.OFF: frozenset({OperatingState.RESEARCH}),
    OperatingState.RESEARCH: frozenset({OperatingState.SHADOW, OperatingState.OFF}),
    OperatingState.SHADOW: frozenset({OperatingState.PAPER, OperatingState.RESEARCH}),
    OperatingState.PAPER: frozenset({OperatingState.CANARY, OperatingState.SHADOW}),
    OperatingState.CANARY: frozenset({OperatingState.LIVE, OperatingState.PAPER}),
    OperatingState.LIVE: frozenset({OperatingState.CANARY}),
    OperatingState.SAFE: frozenset({OperatingState.OFF, OperatingState.RESEARCH}),
}


class LiveTradingNotEnabled(RuntimeError):
    """A transition into a capital-risking state was attempted.

    The implementation plan scopes this build to research, shadow and paper.
    Reaching live requires evidence the validation gauntlet is meant to produce
    and a human approval this system does not implement, so the transition fails
    loudly rather than being quietly permitted by an unset flag.
    """


class InvalidTransition(RuntimeError):
    """A transition not permitted by §5 was attempted."""


def require_transition_allowed(current: OperatingState, target: OperatingState) -> None:
    """Raise unless the system may move from ``current`` to ``target``.

    The single guarded call site. Every state change in the system routes
    through it, so "live is unreachable" is enforced in one place that a test
    can point at.

    Raises:
        LiveTradingNotEnabled: If ``target`` risks capital.
        InvalidTransition: If §5 does not permit the transition.
    """
    if target is current:
        return

    if target in CAPITAL_STATES:
        raise LiveTradingNotEnabled(
            f"refusing to enter {target.value.upper()}. Capital-risking states are "
            "scaffolded but not enabled: reaching one requires canary evidence, a "
            "signed allocation and risk policy, and a documented human approval "
            "(§23), none of which this build implements."
        )

    if target is OperatingState.SAFE:
        return  # always reachable: a critical failure must never be blocked

    permitted = _ALLOWED.get(current, frozenset())
    if target not in permitted:
        raise InvalidTransition(
            f"§5 does not permit {current.value} -> {target.value}. "
            f"From {current.value} the permitted targets are "
            f"{sorted(s.value for s in permitted)}, plus safe."
        )


def is_capital_at_risk(state: OperatingState) -> bool:
    """Whether real money can move in this state."""
    return state in CAPITAL_STATES
