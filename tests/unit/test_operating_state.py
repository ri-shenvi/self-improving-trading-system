"""Capital-risking states exist in the enum and are unreachable (§5).

CANARY and LIVE are declared from M1 so the state machine does not have to be
retrofitted later -- a state machine amended under pressure to reach live
trading is exactly the wrong shape. This file is what makes "scaffolded but
inert" a checkable claim.
"""

from __future__ import annotations

import pytest

from trading.schemas.operating_state import (
    CAPITAL_STATES,
    InvalidTransition,
    LiveTradingNotEnabled,
    OperatingState,
    is_capital_at_risk,
    require_transition_allowed,
)

pytestmark = pytest.mark.unit


class TestCapitalIsUnreachable:
    @pytest.mark.parametrize("target", sorted(CAPITAL_STATES))
    def test_every_capital_state_refuses_entry(self, target: OperatingState) -> None:
        with pytest.raises(LiveTradingNotEnabled):
            require_transition_allowed(OperatingState.PAPER, target)

    @pytest.mark.parametrize("source", sorted(OperatingState))
    def test_no_source_state_can_reach_live(self, source: OperatingState) -> None:
        """Unreachable from anywhere, not merely from the expected predecessor."""
        if source is OperatingState.LIVE:
            return
        with pytest.raises(LiveTradingNotEnabled):
            require_transition_allowed(source, OperatingState.LIVE)

    def test_the_refusal_explains_what_is_missing(self) -> None:
        with pytest.raises(LiveTradingNotEnabled, match="canary evidence"):
            require_transition_allowed(OperatingState.PAPER, OperatingState.CANARY)

    def test_capital_states_are_exactly_canary_and_live(self) -> None:
        assert {OperatingState.CANARY, OperatingState.LIVE} == CAPITAL_STATES

    @pytest.mark.parametrize("state", sorted(OperatingState))
    def test_is_capital_at_risk_agrees(self, state: OperatingState) -> None:
        assert is_capital_at_risk(state) == (state in CAPITAL_STATES)


class TestPermittedTransitions:
    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (OperatingState.OFF, OperatingState.RESEARCH),
            (OperatingState.RESEARCH, OperatingState.SHADOW),
            (OperatingState.SHADOW, OperatingState.PAPER),
            (OperatingState.PAPER, OperatingState.SHADOW),
            (OperatingState.SAFE, OperatingState.RESEARCH),
        ],
    )
    def test_allowed(self, source: OperatingState, target: OperatingState) -> None:
        require_transition_allowed(source, target)

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (OperatingState.OFF, OperatingState.PAPER),
            (OperatingState.RESEARCH, OperatingState.PAPER),
            (OperatingState.SHADOW, OperatingState.OFF),
        ],
    )
    def test_skipping_a_stage_is_refused(
        self, source: OperatingState, target: OperatingState
    ) -> None:
        with pytest.raises(InvalidTransition):
            require_transition_allowed(source, target)

    def test_the_refusal_lists_the_permitted_targets(self) -> None:
        with pytest.raises(InvalidTransition, match="permitted targets"):
            require_transition_allowed(OperatingState.OFF, OperatingState.PAPER)

    @pytest.mark.parametrize("source", sorted(OperatingState))
    def test_safe_is_always_reachable(self, source: OperatingState) -> None:
        """A critical invariant failure must never be blocked by the state machine."""
        require_transition_allowed(source, OperatingState.SAFE)

    @pytest.mark.parametrize("state", sorted(OperatingState))
    def test_staying_put_is_allowed(self, state: OperatingState) -> None:
        require_transition_allowed(state, state)
