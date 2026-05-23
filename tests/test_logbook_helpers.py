"""Unit tests for logbook_helpers."""
from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.const import UnitOfTemperature

from daikinskyport.logbook_helpers import (
    celsius_to_fahrenheit_whole,
    format_dict_temps_for_log,
    format_temp_dual,
    format_temperature,
    format_temps_dict_for_log,
    temps_differ,
)


class TestFormatTempDual:
    def test_none(self) -> None:
        assert format_temp_dual(None) == "—"

    def test_celsius_dual(self) -> None:
        assert format_temp_dual(22.2) == "22.2 (72F)"

    def test_celsius_to_fahrenheit_whole(self) -> None:
        assert celsius_to_fahrenheit_whole(0) == 32
        assert celsius_to_fahrenheit_whole(100) == 212


class TestTempsDiffer:
    def test_both_none(self) -> None:
        assert temps_differ(None, None) is False

    def test_one_none(self) -> None:
        assert temps_differ(20.0, None) is True

    def test_within_threshold(self) -> None:
        assert temps_differ(20.0, 20.04) is False

    def test_outside_threshold(self) -> None:
        assert temps_differ(20.0, 20.1) is True


class TestFormatTempsForLog:
    def test_format_temps_dict_for_log(self) -> None:
        result = format_temps_dict_for_log({"hspHome": 21.0, "cspHome": 24.0})
        assert result == "cspHome=24.0 (75F), hspHome=21.0 (70F)"

    def test_format_dict_temps_for_log(self) -> None:
        out = format_dict_temps_for_log(
            {"hspActive": 20.5, "schedEnabled": True, "schedMonPart1hsp": 19.0}
        )
        assert out["schedEnabled"] is True
        assert out["hspActive"] == "20.5 (69F)"
        assert out["schedMonPart1hsp"] == "19.0 (66F)"


class TestFormatTemperature:
    def _hass(self, unit: str) -> MagicMock:
        hass = MagicMock()
        hass.config.units.temperature_unit = unit
        return hass

    def test_fahrenheit(self) -> None:
        hass = self._hass(UnitOfTemperature.FAHRENHEIT)
        assert format_temperature(hass, 22.2) == "72°F"

    def test_celsius(self) -> None:
        hass = self._hass(UnitOfTemperature.CELSIUS)
        assert format_temperature(hass, 22.2) == "22.2°C"

    def test_none(self) -> None:
        hass = self._hass(UnitOfTemperature.CELSIUS)
        assert format_temperature(hass, None) == "—"
