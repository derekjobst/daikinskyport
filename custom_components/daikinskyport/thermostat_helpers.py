"""Shared thermostat capability and temperature display helpers."""
from __future__ import annotations

from typing import Any

from homeassistant.const import UnitOfTemperature

try:
    from homeassistant.const import PRECISION_TENTHS
except ImportError:  # Home Assistant < 2024.2
    from homeassistant.components.climate.const import PRECISION_TENTHS
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_conversion import TemperatureConverter

# Native-unit step matching 1°F when HA displays Fahrenheit.
FAHRENHEIT_PRECISION_CELSIUS = 5 / 9

# API setpoint limits (°C) for away and schedule period climates.
SETPOINT_MIN_C = 7.0
SETPOINT_MAX_C = 35.0


def thermostat_has_heat(thermostat: dict[str, Any]) -> bool:
    """Return True when the system supports heating."""
    return bool(thermostat.get("ctSystemCapHeat"))


def thermostat_has_cooling(thermostat: dict[str, Any]) -> bool:
    """Return True when the system supports cooling."""
    return (
        thermostat.get("ctOutdoorNoofCoolStages", 0) > 0
        or thermostat.get("P1P2S21CoolingCapability") is True
    )


def thermostat_supports_setpoint_climate(thermostat: dict[str, Any]) -> bool:
    """Return True when away or schedule setpoint climates may be exposed."""
    return thermostat_has_heat(thermostat) or thermostat_has_cooling(thermostat)


def climate_precision(hass: HomeAssistant) -> float:
    """Return climate precision in native °C (whole °F step when user prefers F)."""
    if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT:
        return FAHRENHEIT_PRECISION_CELSIUS
    return PRECISION_TENTHS


def temperature_for_display(
    hass: HomeAssistant, temp_c: float | None
) -> float | None:
    """Round API Celsius for HA UI (whole °F, 0.1 °C)."""
    if temp_c is None:
        return None
    if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT:
        fahrenheit = TemperatureConverter.convert(
            temp_c,
            UnitOfTemperature.CELSIUS,
            UnitOfTemperature.FAHRENHEIT,
        )
        fahrenheit = round(fahrenheit)
        return TemperatureConverter.convert(
            fahrenheit,
            UnitOfTemperature.FAHRENHEIT,
            UnitOfTemperature.CELSIUS,
        )
    return round(temp_c, 1)
