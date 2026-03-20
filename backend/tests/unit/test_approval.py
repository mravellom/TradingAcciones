import pytest

from app.domain.enums import OrderStatus
from app.domain.state_machine import validate_order_transition
from app.core.exceptions import InvalidStateTransitionError


class TestApprovalStateMachine:
    """Test the PENDING_APPROVAL state transitions."""

    def test_sized_to_pending_approval(self):
        validate_order_transition(OrderStatus.SIZED, OrderStatus.PENDING_APPROVAL)

    def test_pending_approval_to_submitted(self):
        """Human approves → SUBMITTED."""
        validate_order_transition(OrderStatus.PENDING_APPROVAL, OrderStatus.SUBMITTED)

    def test_pending_approval_to_rejected(self):
        """Human rejects → REJECTED."""
        validate_order_transition(OrderStatus.PENDING_APPROVAL, OrderStatus.REJECTED)

    def test_pending_approval_to_expired(self):
        """Approval timeout → EXPIRED."""
        validate_order_transition(OrderStatus.PENDING_APPROVAL, OrderStatus.EXPIRED)

    def test_pending_approval_to_filled_invalid(self):
        """Cannot skip to FILLED from PENDING_APPROVAL."""
        with pytest.raises(InvalidStateTransitionError):
            validate_order_transition(OrderStatus.PENDING_APPROVAL, OrderStatus.FILLED)

    def test_pending_to_pending_approval_invalid(self):
        """Cannot go from PENDING directly to PENDING_APPROVAL."""
        with pytest.raises(InvalidStateTransitionError):
            validate_order_transition(OrderStatus.PENDING, OrderStatus.PENDING_APPROVAL)

    def test_sized_still_goes_to_submitted(self):
        """Auto mode: SIZED → SUBMITTED still works."""
        validate_order_transition(OrderStatus.SIZED, OrderStatus.SUBMITTED)
