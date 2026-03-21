from app.core.exceptions import InvalidStateTransitionError
from app.domain.enums import OrderStatus, PositionStatus

# Allowed transitions: current_state -> set of valid next states
ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {
        OrderStatus.VALIDATED,
        OrderStatus.REJECTED,
    },
    OrderStatus.VALIDATED: {
        OrderStatus.SIZED,
        OrderStatus.REJECTED,
    },
    OrderStatus.SIZED: {
        OrderStatus.PENDING_APPROVAL,  # Human-in-the-loop mode
        OrderStatus.SUBMITTED,         # Auto mode
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.PENDING_APPROVAL: {
        OrderStatus.SUBMITTED,   # Human approved
        OrderStatus.REJECTED,    # Human rejected
        OrderStatus.EXPIRED,     # Approval timeout
    },
    OrderStatus.SUBMITTED: {
        OrderStatus.SUBMITTING,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.SUBMITTING: {
        OrderStatus.FILLED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
    },
    OrderStatus.PARTIALLY_FILLED: {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
    },
    # Terminal states - no transitions out
    OrderStatus.FILLED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
    OrderStatus.EXPIRED: set(),
}

POSITION_TRANSITIONS: dict[PositionStatus, set[PositionStatus]] = {
    PositionStatus.OPEN: {
        PositionStatus.PARTIALLY_CLOSED,
        PositionStatus.CLOSED,
        PositionStatus.STOPPED_OUT,
    },
    PositionStatus.PARTIALLY_CLOSED: {
        PositionStatus.CLOSED,
        PositionStatus.STOPPED_OUT,
    },
    # Terminal states
    PositionStatus.CLOSED: set(),
    PositionStatus.STOPPED_OUT: set(),
}

ORDER_TERMINAL_STATES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
}

POSITION_TERMINAL_STATES = {
    PositionStatus.CLOSED,
    PositionStatus.STOPPED_OUT,
}


def validate_order_transition(current: OrderStatus, target: OrderStatus) -> None:
    """Validate that an order state transition is allowed.

    Raises InvalidStateTransitionError if the transition is not allowed.
    """
    current_enum = OrderStatus(current) if isinstance(current, str) else current
    target_enum = OrderStatus(target) if isinstance(target, str) else target

    allowed = ORDER_TRANSITIONS.get(current_enum, set())
    if target_enum not in allowed:
        raise InvalidStateTransitionError(
            message=f"Order transition {current_enum.value} -> {target_enum.value} not allowed",
            code="INVALID_ORDER_TRANSITION",
        )


def validate_position_transition(current: PositionStatus, target: PositionStatus) -> None:
    """Validate that a position state transition is allowed.

    Raises InvalidStateTransitionError if the transition is not allowed.
    """
    current_enum = PositionStatus(current) if isinstance(current, str) else current
    target_enum = PositionStatus(target) if isinstance(target, str) else target

    allowed = POSITION_TRANSITIONS.get(current_enum, set())
    if target_enum not in allowed:
        raise InvalidStateTransitionError(
            message=f"Position transition {current_enum.value} -> {target_enum.value} not allowed",
            code="INVALID_POSITION_TRANSITION",
        )


def is_order_terminal(status: OrderStatus) -> bool:
    return OrderStatus(status) in ORDER_TERMINAL_STATES


def is_position_terminal(status: PositionStatus) -> bool:
    return PositionStatus(status) in POSITION_TERMINAL_STATES
