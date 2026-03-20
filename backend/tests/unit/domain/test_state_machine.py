import pytest

from app.core.exceptions import InvalidStateTransitionError
from app.domain.enums import OrderStatus, PositionStatus
from app.domain.state_machine import (
    is_order_terminal,
    is_position_terminal,
    validate_order_transition,
    validate_position_transition,
)


# ── Order transitions ──


class TestOrderStateMachine:
    def test_pending_to_validated(self):
        validate_order_transition(OrderStatus.PENDING, OrderStatus.VALIDATED)

    def test_pending_to_rejected(self):
        validate_order_transition(OrderStatus.PENDING, OrderStatus.REJECTED)

    def test_validated_to_sized(self):
        validate_order_transition(OrderStatus.VALIDATED, OrderStatus.SIZED)

    def test_validated_to_rejected(self):
        validate_order_transition(OrderStatus.VALIDATED, OrderStatus.REJECTED)

    def test_sized_to_submitted(self):
        validate_order_transition(OrderStatus.SIZED, OrderStatus.SUBMITTED)

    def test_sized_to_cancelled(self):
        validate_order_transition(OrderStatus.SIZED, OrderStatus.CANCELLED)

    def test_submitted_to_filled(self):
        validate_order_transition(OrderStatus.SUBMITTED, OrderStatus.FILLED)

    def test_submitted_to_partially_filled(self):
        validate_order_transition(OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED)

    def test_submitted_to_cancelled(self):
        validate_order_transition(OrderStatus.SUBMITTED, OrderStatus.CANCELLED)

    def test_submitted_to_expired(self):
        validate_order_transition(OrderStatus.SUBMITTED, OrderStatus.EXPIRED)

    def test_partially_filled_to_filled(self):
        validate_order_transition(OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED)

    def test_partially_filled_to_cancelled(self):
        validate_order_transition(OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELLED)

    # Invalid transitions

    def test_pending_to_filled_invalid(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_order_transition(OrderStatus.PENDING, OrderStatus.FILLED)

    def test_pending_to_submitted_invalid(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_order_transition(OrderStatus.PENDING, OrderStatus.SUBMITTED)

    def test_filled_to_anything_invalid(self):
        for target in OrderStatus:
            if target != OrderStatus.FILLED:
                with pytest.raises(InvalidStateTransitionError):
                    validate_order_transition(OrderStatus.FILLED, target)

    def test_rejected_to_anything_invalid(self):
        for target in OrderStatus:
            if target != OrderStatus.REJECTED:
                with pytest.raises(InvalidStateTransitionError):
                    validate_order_transition(OrderStatus.REJECTED, target)

    def test_cancelled_to_anything_invalid(self):
        for target in OrderStatus:
            if target != OrderStatus.CANCELLED:
                with pytest.raises(InvalidStateTransitionError):
                    validate_order_transition(OrderStatus.CANCELLED, target)

    def test_accepts_string_values(self):
        validate_order_transition("PENDING", "VALIDATED")

    def test_invalid_string_raises(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_order_transition("PENDING", "FILLED")


# ── Position transitions ──


class TestPositionStateMachine:
    def test_open_to_partially_closed(self):
        validate_position_transition(PositionStatus.OPEN, PositionStatus.PARTIALLY_CLOSED)

    def test_open_to_closed(self):
        validate_position_transition(PositionStatus.OPEN, PositionStatus.CLOSED)

    def test_open_to_stopped_out(self):
        validate_position_transition(PositionStatus.OPEN, PositionStatus.STOPPED_OUT)

    def test_partially_closed_to_closed(self):
        validate_position_transition(PositionStatus.PARTIALLY_CLOSED, PositionStatus.CLOSED)

    def test_partially_closed_to_stopped_out(self):
        validate_position_transition(
            PositionStatus.PARTIALLY_CLOSED, PositionStatus.STOPPED_OUT
        )

    # Invalid

    def test_open_to_open_invalid(self):
        with pytest.raises(InvalidStateTransitionError):
            validate_position_transition(PositionStatus.OPEN, PositionStatus.OPEN)

    def test_closed_to_anything_invalid(self):
        for target in PositionStatus:
            if target != PositionStatus.CLOSED:
                with pytest.raises(InvalidStateTransitionError):
                    validate_position_transition(PositionStatus.CLOSED, target)

    def test_stopped_out_to_anything_invalid(self):
        for target in PositionStatus:
            if target != PositionStatus.STOPPED_OUT:
                with pytest.raises(InvalidStateTransitionError):
                    validate_position_transition(PositionStatus.STOPPED_OUT, target)


# ── Terminal state checks ──


class TestTerminalStates:
    def test_order_terminal_states(self):
        assert is_order_terminal(OrderStatus.FILLED)
        assert is_order_terminal(OrderStatus.CANCELLED)
        assert is_order_terminal(OrderStatus.REJECTED)
        assert is_order_terminal(OrderStatus.EXPIRED)

    def test_order_non_terminal_states(self):
        assert not is_order_terminal(OrderStatus.PENDING)
        assert not is_order_terminal(OrderStatus.VALIDATED)
        assert not is_order_terminal(OrderStatus.SIZED)
        assert not is_order_terminal(OrderStatus.SUBMITTED)
        assert not is_order_terminal(OrderStatus.PARTIALLY_FILLED)

    def test_position_terminal_states(self):
        assert is_position_terminal(PositionStatus.CLOSED)
        assert is_position_terminal(PositionStatus.STOPPED_OUT)

    def test_position_non_terminal_states(self):
        assert not is_position_terminal(PositionStatus.OPEN)
        assert not is_position_terminal(PositionStatus.PARTIALLY_CLOSED)
