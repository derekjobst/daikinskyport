"""Support for displaying weather info from Daikin Skyport API."""
from datetime import timedelta

from homeassistant.components.weather import (
    ATTR_FORECAST_CONDITION,
    ATTR_FORECAST_NATIVE_TEMP,
    ATTR_FORECAST_HUMIDITY,
    ATTR_FORECAST_TIME,
    Forecast,
    WeatherEntity,
    WeatherEntityFeature,
)
from homeassistant.const import (
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import (
    _LOGGER,
    DAIKIN_WEATHER_ICON_TO_HASS,
    COORDINATOR,
    DOMAIN,
)
from . import DaikinSkyportData

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add a Daikin Skyport Weather entity from a config_entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaikinSkyportData = data[COORDINATOR]

    for index in range(len(coordinator.daikinskyport.thermostats)):
        thermostat = coordinator.daikinskyport.get_thermostat(index)
        async_add_entities([DaikinSkyportWeather(coordinator, thermostat["name"], index)], True)

class DaikinSkyportWeather(CoordinatorEntity, WeatherEntity):
    """Representation of Daikin Skyport weather data."""

    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = WeatherEntityFeature.FORECAST_DAILY

    def __init__(self, coordinator, name, index):
        """Initialize the Daikin Skyport weather platform."""
        super().__init__(coordinator)
        self.data = coordinator
        self._name = name
        self._attr_unique_id = (
            f"{coordinator.daikinskyport.thermostats[index]['id']}-{self._name}"
        )
        self._index = index
        self._attr_device_info = coordinator.outdoor_weather_device_info(index)
        self.weather = None
        self._update_weather_cache()

    def _update_weather_cache(self) -> None:
        """Load weather fields from the coordinator thermostat cache."""
        self.weather = {}
        thermostat = self.coordinator.daikinskyport.get_thermostat(self._index)
        for key in thermostat:
            if key.startswith("weather"):
                self.weather[key] = thermostat[key]
        self.weather["tz"] = thermostat["timeZone"]

    async def async_forecast_daily(self) -> list[Forecast] | None:
        """Return the daily forecast in native units.
        
        Only implement this method if `WeatherEntityFeature.FORECAST_DAILY` is set
        """
        
        if not self.weather:
            return None

        forecasts: list[Forecast] = []
        date = dt_util.utcnow()
        for day in ["Today", "Day1", "Day2", "Day3", "Day4", "Day5"]:
            forecast = {}
            try:
                forecast[ATTR_FORECAST_CONDITION] = DAIKIN_WEATHER_ICON_TO_HASS[self.weather["weather" + day + "Icon"]]
                forecast[ATTR_FORECAST_NATIVE_TEMP] = self.weather["weather" + day + "TempC"]
                forecast[ATTR_FORECAST_HUMIDITY] = self.weather["weather" + day + "Hum"]
                _LOGGER.debug("Weather icon for weather%sIcon: %s", day, self.weather["weather" + day + "Icon"])
            except (TypeError, ValueError, IndexError, KeyError) as e:
                _LOGGER.error("Key not found for weather icon: %s", e)
                date += timedelta(days=1)
                continue
            if forecast is None:
                date += timedelta(days=1)
                continue
            forecast[ATTR_FORECAST_TIME] = date.isoformat()
            date += timedelta(days=1)
            forecasts.append(forecast)

        if forecasts:
            return forecasts
        return None

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def condition(self):
        """Return the current condition."""
        if not self.weather:
            return None
        try:
            _LOGGER.debug("Weather icon for weatherTodayIcon: %s", self.weather["weatherTodayIcon"])
            return DAIKIN_WEATHER_ICON_TO_HASS[self.weather["weatherTodayIcon"]]
        except (KeyError, TypeError) as e:
            _LOGGER.error("Key not found for weather condition: %s", e)
            return None

    @property
    def native_temperature(self):
        """Return the temperature."""
        if not self.weather:
            return None
        try:
            return float(self.weather["weatherTodayTempC"])
        except (KeyError, TypeError, ValueError):
            return None

    @property
    def humidity(self):
        """Return the humidity."""
        if not self.weather:
            return None
        try:
            return int(self.weather["weatherTodayHum"])
        except (KeyError, TypeError, ValueError):
            return None

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_weather_cache()
        self.async_write_ha_state()
