"""Unit tests for thermostat_helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.const import UnitOfTemperature

from daikinskyport.thermostat_helpers import (
    FAHRENHEIT_PRECISION_CELSIUS,
    SETPOINT_MAX_C,
    SETPOINT_MIN_C,
    climate_precision,
    temperature_for_display,
    thermostat_has_cooling,
    thermostat_has_heat,
    thermostat_supports_setpoint_climate,
)


class TestThermostatCapabilities:
    def test_thermostat_has_heat(self) -> None:
        assert thermostat_has_heat({"ctSystemCapHeat": True}) is True
        assert thermostat_has_heat({"ctSystemCapHeat": False}) is False
        assert thermostat_has_heat({}) is False

    def test_thermostat_has_cooling_stages(self) -> None:
        assert thermostat_has_cooling({"ctOutdoorNoofCoolStages": 1}) is True

    def test_thermostat_has_cooling_p1p2(self) -> None:
        assert thermostat_has_cooling({"P1P2S21CoolingCapability": True}) is True

    def test_thermostat_no_cooling(self) -> None:
        assert thermostat_has_cooling({}) is False

    def test_supports_setpoint_climate(self) -> None:
        assert thermostat_supports_setpoint_climate({"ctSystemCapHeat": True}) is True
        assert thermostat_supports_setpoint_climate(
            {"ctOutdoorNoofCoolStages": 1}
        ) is True
        assert thermostat_supports_setpoint_climate({}) is False


class TestSetpointConstants:
    def test_limits(self) -> None:
        assert SETPOINT_MIN_C < SETPOINT_MAX_C

    def test_fahrenheit_precision(self) -> None:
        assert FAHRENHEIT_PRECISION_CELSIUS == pytest.approx(5 / 9)


class TestTemperatureDisplay:
    def _hass(self, unit: str) -> MagicMock:
        hass = MagicMock()
        hass.config.units.temperature_unit = unit
        return hass

    def test_none(self) -> None:
        assert temperature_for_display(self._hass(UnitOfTemperature.CELSIUS), None) is None

    def test_celsius_rounding(self) -> None:
        assert temperature_for_display(self._hass(UnitOfTemperature.CELSIUS), 22.24) == 22.2

    def test_fahrenheit_whole_degree_round_trip(self) -> None:
        # 22.2°C ≈ 72°F; display uses whole °F then converts back.
        result = temperature_for_display(
            self._hass(UnitOfTemperature.FAHRENHEIT), 22.2
        )
        assert result is not None
        assert round(result * 9 / 5 + 32) == 72

    def test_climate_precision(self) -> None:
        assert climate_precision(self._hass(UnitOfTemperature.CELSIUS)) == 0.1
        assert climate_precision(self._hass(UnitOfTemperature.FAHRENHEIT)) == pytest.approx(
            5 / 9
        )
