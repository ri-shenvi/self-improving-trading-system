"""Execution contracts carry what the OMS and the accounting identity need."""

from __future__ import annotations

import pytest

from trading.schemas.execution import (
    TERMINAL_STATES,
    OrderState,
    RiskReason,
    Side,
)
from trading.schemas.registry import get

pytestmark = pytest.mark.unit


class TestOrderStateMachine:
    def test_every_section_30_state_exists(self) -> None:
        expected = {
            "created",
            "risk_approved",
            "submitting",
            "acknowledged",
            "partially_filled",
            "filled",
            "rejected",
            "canceling",
            "canceled",
            "unknown",
        }
        assert {s.value for s in OrderState} == expected

    def test_unknown_is_not_terminal(self) -> None:
        """An UNKNOWN order must be reconciled, not abandoned -- or retried (§30)."""
        assert OrderState.UNKNOWN not in TERMINAL_STATES

    def test_terminal_states(self) -> None:
        assert {OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELED} == TERMINAL_STATES


class TestRiskReasons:
    def test_reasons_are_closed_and_include_approval(self) -> None:
        """§25 requires a reason-coded approval *or* rejection before any broker call."""
        assert RiskReason.APPROVED in set(RiskReason)

    @pytest.mark.parametrize(
        "reason",
        [
            RiskReason.DUPLICATE_CLIENT_ORDER_ID,
            RiskReason.SYMBOL_HALTED,
            RiskReason.OUTSIDE_LULD_BAND,
            RiskReason.STALE_MARKET_DATA,
            RiskReason.PRICE_COLLAR,
            RiskReason.DAILY_LOSS_LIMIT,
            RiskReason.SHORT_NOT_SUPPORTED,
            RiskReason.FRACTIONAL_NOT_SUPPORTED,
        ],
    )
    def test_section_25_checks_have_a_code(self, reason: RiskReason) -> None:
        assert reason.value


class TestContractShapes:
    def test_fill_decomposes_costs_rather_than_blending_them(self) -> None:
        """§17: never a single blended basis-point number."""
        names = set(get("execution.fill").field_names())
        assert {"commission_nano", "regulatory_fees_nano"} <= names
        assert "arrival_price_nano" in names, "implementation shortfall needs it (§22)"

    def test_order_event_carries_an_execution_id(self) -> None:
        """Divergence 1: without it, two same-timestamp partial fills collide."""
        assert "broker_exec_id" in get("execution.order_event").field_names()

    def test_order_event_records_the_risk_reason(self) -> None:
        assert "risk_reason" in get("execution.order_event").field_names()

    def test_position_separates_realized_from_unrealized(self) -> None:
        names = set(get("execution.position").field_names())
        assert {"realized_pnl_nano", "unrealized_pnl_nano"} <= names

    def test_account_state_records_its_operating_state(self) -> None:
        """A paper row must never be mistakable for a live one (§40)."""
        assert "operating_state" in get("execution.account_state").field_names()

    def test_intent_carries_the_decision_time(self) -> None:
        """The submission key derives from it; no fill may precede it (§16)."""
        assert "decision_time" in get("execution.order_intent").field_names()

    def test_sides(self) -> None:
        assert {s.value for s in Side} == {"buy", "sell"}
