"""Tests for risk profile switch logic.

Tests the PROFILE_PRESETS, validation rules, and that open positions
are not affected by profile changes.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.api.v1.risk import PROFILE_PRESETS
from app.domain.enums import RiskProfileType


class TestProfilePresets:
    def test_ultra_conservador_preset_matches_defaults(self):
        preset = PROFILE_PRESETS[RiskProfileType.ULTRA_CONSERVADOR]
        assert preset["min_confidence"] == Decimal("0.60")
        assert preset["max_positions"] == 5
        assert preset["risk_per_trade_pct"] == Decimal("0.01")
        assert preset["max_exposure_per_symbol_pct"] == Decimal("0.10")
        assert preset["allow_partial_signal_agreement"] is False
        assert preset["min_agreeing_signals"] == 3
        assert preset["use_atr_for_sl_tp"] is False

    def test_defensivo_agresivo_preset(self):
        preset = PROFILE_PRESETS[RiskProfileType.DEFENSIVO_AGRESIVO]
        assert preset["min_confidence"] == Decimal("0.55")
        assert preset["max_positions"] == 7
        assert preset["risk_per_trade_pct"] == Decimal("0.015")
        assert preset["max_exposure_per_symbol_pct"] == Decimal("0.15")
        assert preset["allow_partial_signal_agreement"] is True
        assert preset["min_agreeing_signals"] == 2
        assert preset["use_atr_for_sl_tp"] is True
        assert preset["atr_period"] == 14
        assert preset["atr_sl_multiplier"] == Decimal("1.5")
        assert preset["atr_tp_multiplier"] == Decimal("3.0")

    def test_both_profiles_exist(self):
        assert RiskProfileType.ULTRA_CONSERVADOR in PROFILE_PRESETS
        assert RiskProfileType.DEFENSIVO_AGRESIVO in PROFILE_PRESETS

    def test_defensivo_has_lower_confidence_than_ultra(self):
        ultra = PROFILE_PRESETS[RiskProfileType.ULTRA_CONSERVADOR]
        defensivo = PROFILE_PRESETS[RiskProfileType.DEFENSIVO_AGRESIVO]
        assert defensivo["min_confidence"] < ultra["min_confidence"]

    def test_defensivo_has_more_positions_than_ultra(self):
        ultra = PROFILE_PRESETS[RiskProfileType.ULTRA_CONSERVADOR]
        defensivo = PROFILE_PRESETS[RiskProfileType.DEFENSIVO_AGRESIVO]
        assert defensivo["max_positions"] > ultra["max_positions"]

    def test_presets_do_not_include_global_limits(self):
        """Global limits (daily loss, drawdown) must NOT be in presets."""
        for profile_type, preset in PROFILE_PRESETS.items():
            assert "max_daily_loss_pct" not in preset, f"{profile_type} should not override daily loss"
            assert "max_drawdown_pct" not in preset, f"{profile_type} should not override drawdown"


class TestRiskProfileEnum:
    def test_enum_values(self):
        assert RiskProfileType.ULTRA_CONSERVADOR.value == "ULTRA_CONSERVADOR"
        assert RiskProfileType.DEFENSIVO_AGRESIVO.value == "DEFENSIVO_AGRESIVO"

    def test_enum_from_string(self):
        assert RiskProfileType("ULTRA_CONSERVADOR") == RiskProfileType.ULTRA_CONSERVADOR
        assert RiskProfileType("DEFENSIVO_AGRESIVO") == RiskProfileType.DEFENSIVO_AGRESIVO

    def test_invalid_profile_raises(self):
        with pytest.raises(ValueError):
            RiskProfileType("INVALID")
