"""Logbook helpers for Daikin Skyport climate changes."""
from __future__ import annotations

from typing import Any

from homeassistant.components import logbook
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import DOMAIN

# Suppress cloud-detected logbook entries shortly after an HA-initiated change.
LOCAL_CHANGE_SUPPRESS_SECONDS = 20

# API / debug log fields stored as Celsius on the wire.
_TEMP_LOG_FIELD_NAMES = frozenset({
    "hspHome",
    "cspHome",
    "hspActive",
    "cspActive",
    "hspAway",
    "cspAway",
    "tempIndoor",
    "tempOutdoor",
})


def celsius_to_fahrenheit_whole(celsius: float) -> int:
    """Round API Celsius to a whole Fahrenheit value for logs."""
    return int(round(float(celsius) * 9 / 5 + 32))


def format_temp_dual(value: Any) -> str:
    """Format a Celsius API value for logs, e.g. 22.2 (72F)."""
    if value is None:
        return "—"
    celsius = float(value)
    return f"{round(celsius, 1)} ({celsius_to_fahrenheit_whole(celsius)}F)"


def format_temps_dict_for_log(temps: dict[str, Any]) -> str:
    """Format a dict of Celsius temps for debug/INFO logs."""
    if not temps:
        return ""
    return ", ".join(
        f"{key}={format_temp_dual(value)}"
        for key, value in sorted(temps.items())
    )


def format_dict_temps_for_log(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a dict with temperature fields shown as dual-unit strings."""
    if not isinstance(data, dict):
        return data
    formatted: dict[str, Any] = {}
    for key, value in data.items():
        if key in _TEMP_LOG_FIELD_NAMES or (
            isinstance(value, (int, float))
            and (key.endswith("hsp") or key.endswith("csp"))
        ):
            formatted[key] = format_temp_dual(value)
        else:
            formatted[key] = value
    return formatted


@callback
def write_climate_logbook_entry(
    hass: HomeAssistant,
    entity_id: str,
    name: str,
    message: str,
) -> None:
    """Write a manual logbook entry for a climate entity."""
    # HA signature: async_log_entry(hass, name, message, domain, entity_id)
    logbook.async_log_entry(hass, name, message, DOMAIN, entity_id)


def format_temperature(hass: HomeAssistant, value: Any) -> str:
    """Format a Celsius API value for logbook messages in the user's unit."""
    if value is None:
        return "—"
    celsius = float(value)
    if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT:
        fahrenheit = TemperatureConverter.convert(
            celsius,
            UnitOfTemperature.CELSIUS,
            UnitOfTemperature.FAHRENHEIT,
        )
        # Whole degrees match the thermostat / HA UI for Fahrenheit.
        return f"{round(fahrenheit)}°F"
    return f"{round(celsius, 1)}°C"


def temps_differ(previous: Any, current: Any) -> bool:
    """Return True when two temperatures are meaningfully different."""
    if previous is None and current is None:
        return False
    if previous is None or current is None:
        return True
    return abs(float(previous) - float(current)) > 0.05
