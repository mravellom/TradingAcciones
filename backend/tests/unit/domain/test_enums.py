from app.domain.enums import (
    AggregateType,
    EventType,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
    PositionStatus,
    RiskAction,
    SignalType,
)


class TestEnums:
    def test_signal_types(self):
        assert SignalType.BUY.value == "BUY"
        assert SignalType.SELL.value == "SELL"
        assert SignalType.HOLD.value == "HOLD"

    def test_order_statuses(self):
        assert len(OrderStatus) == 11
        assert OrderStatus.PENDING.value == "PENDING"
        assert OrderStatus.FILLED.value == "FILLED"

    def test_position_statuses(self):
        assert len(PositionStatus) == 4
        assert PositionStatus.STOPPED_OUT.value == "STOPPED_OUT"

    def test_execution_modes(self):
        assert ExecutionMode.PAPER.value == "PAPER"
        assert ExecutionMode.LIVE.value == "LIVE"

    def test_risk_actions(self):
        assert RiskAction.HALT_SYSTEM.value == "HALT_SYSTEM"

    def test_position_side_only_long_for_spot(self):
        assert PositionSide.LONG.value == "LONG"

    def test_order_sides(self):
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"

    def test_order_types(self):
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"

    def test_event_types_exist(self):
        assert EventType.SIGNAL_GENERATED.value == "SIGNAL_GENERATED"
        assert EventType.RISK_REJECTED.value == "RISK_REJECTED"
        assert EventType.SYSTEM_HALTED.value == "SYSTEM_HALTED"

    def test_aggregate_types(self):
        assert AggregateType.ORDER.value == "ORDER"
        assert AggregateType.SYSTEM.value == "SYSTEM"

    def test_enums_are_strings(self):
        """All enums should be str enums for JSON serialization."""
        assert isinstance(SignalType.BUY, str)
        assert isinstance(OrderStatus.PENDING, str)
        assert isinstance(PositionStatus.OPEN, str)
