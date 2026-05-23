"""Shared pytest fixtures for Daikin Skyport unit tests."""
from __future__ import annotations

import sys
import types
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

# Importing `daikinskyport` loads __init__.py and const.py, which expect Home Assistant.
# Stub minimal HA modules so unit tests run without a full HA install.


def _install_ha_stubs() -> None:
    if "homeassistant" in sys.modules:
        return

    ha = types.ModuleType("homeassistant")
    ha_const = types.ModuleType("homeassistant.const")

    class _UnitOfTemperature:
        CELSIUS = "°C"
        FAHRENHEIT = "°F"

    ha_const.UnitOfTemperature = _UnitOfTemperature
    ha_const.Platform = MagicMock()
    ha_const.CONF_PASSWORD = "password"
    ha_const.CONF_EMAIL = "email"
    ha_const.CONF_NAME = "name"
    ha_const.PERCENTAGE = "%"
    ha_const.CONCENTRATION_PARTS_PER_MILLION = "ppm"
    ha_const.CONCENTRATION_PARTS_PER_BILLION = "ppb"
    ha_const.CONCENTRATION_MICROGRAMS_PER_CUBIC_METER = "µg/m³"
    ha_const.UnitOfPower = MagicMock(WATT="W")
    ha_const.UnitOfVolumeFlowRate = MagicMock(CUBIC_FEET_PER_MINUTE="ft³/min")
    ha_const.PRECISION_TENTHS = 0.1

    ha_exceptions = types.ModuleType("homeassistant.exceptions")
    ha_exceptions.ConfigEntryNotReady = Exception

    ha_config_entries = types.ModuleType("homeassistant.config_entries")
    ha_config_entries.ConfigEntry = MagicMock()

    ha_core = types.ModuleType("homeassistant.core")
    ha_core.HomeAssistant = MagicMock()
    ha_core.callback = lambda fn: fn

    ha_helpers = types.ModuleType("homeassistant.helpers")
    ha_helpers_event = types.ModuleType("homeassistant.helpers.event")
    ha_helpers_event.async_call_later = MagicMock()
    ha_helpers_update = types.ModuleType("homeassistant.helpers.update_coordinator")
    ha_helpers_update.DataUpdateCoordinator = MagicMock()
    ha_helpers_update.UpdateFailed = Exception
    ha_helpers_entity = types.ModuleType("homeassistant.helpers.entity")
    ha_helpers_entity.DeviceInfo = MagicMock()

    ha_components = types.ModuleType("homeassistant.components")
    ha_logbook = types.ModuleType("homeassistant.components.logbook")
    ha_logbook.async_log_entry = MagicMock()
    ha_climate_const = types.ModuleType("homeassistant.components.climate.const")
    ha_weather = types.ModuleType("homeassistant.components.weather")
    for name in (
        "ATTR_CONDITION_CLEAR_NIGHT",
        "ATTR_CONDITION_CLOUDY",
        "ATTR_CONDITION_EXCEPTIONAL",
        "ATTR_CONDITION_FOG",
        "ATTR_CONDITION_HAIL",
        "ATTR_CONDITION_LIGHTNING",
        "ATTR_CONDITION_LIGHTNING_RAINY",
        "ATTR_CONDITION_PARTLYCLOUDY",
        "ATTR_CONDITION_POURING",
        "ATTR_CONDITION_RAINY",
        "ATTR_CONDITION_SNOWY",
        "ATTR_CONDITION_SNOWY_RAINY",
        "ATTR_CONDITION_SUNNY",
        "ATTR_CONDITION_WINDY",
        "ATTR_CONDITION_WINDY_VARIANT",
    ):
        setattr(ha_weather, name, name.lower())

    ha_util = types.ModuleType("homeassistant.util")
    ha_util_unit = types.ModuleType("homeassistant.util.unit_conversion")

    class _TemperatureConverter:
        @staticmethod
        def convert(value: float, from_unit: str, to_unit: str) -> float:
            if from_unit == to_unit:
                return value
            if to_unit == _UnitOfTemperature.FAHRENHEIT:
                return value * 9 / 5 + 32
            return (value - 32) * 5 / 9

    ha_util_unit.TemperatureConverter = _TemperatureConverter
    ha_util.unit_conversion = ha_util_unit

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.const"] = ha_const
    sys.modules["homeassistant.exceptions"] = ha_exceptions
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.event"] = ha_helpers_event
    sys.modules["homeassistant.helpers.update_coordinator"] = ha_helpers_update
    sys.modules["homeassistant.helpers.entity"] = ha_helpers_entity
    sys.modules["homeassistant.components"] = ha_components
    sys.modules["homeassistant.components.climate"] = types.ModuleType(
        "homeassistant.components.climate"
    )
    sys.modules["homeassistant.components.climate.const"] = ha_climate_const
    sys.modules["homeassistant.components.logbook"] = ha_logbook
    sys.modules["homeassistant.components.weather"] = ha_weather
    sys.modules["homeassistant.util"] = ha_util
    sys.modules["homeassistant.util.unit_conversion"] = ha_util_unit


_install_ha_stubs()


@pytest.fixture
def tz_eastern() -> ZoneInfo:
    """US Eastern timezone for schedule tests."""
    return ZoneInfo("America/New_York")


@pytest.fixture
def monday_morning_eastern(tz_eastern: ZoneInfo) -> datetime:
    """Monday 2024-06-03 07:00 in Eastern (for active-period tests)."""
    return datetime(2024, 6, 3, 7, 0, tzinfo=tz_eastern)


@pytest.fixture
def monday_schedule_thermostat() -> dict:
    """Thermostat with Monday wake/day periods enabled."""
    from tests.helpers import make_monday_schedule_thermostat

    return make_monday_schedule_thermostat()
