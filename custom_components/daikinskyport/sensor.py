"""Support for Daikin Skyport sensors."""
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
    CONCENTRATION_PARTS_PER_MILLION,
    CONCENTRATION_PARTS_PER_BILLION,
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    UnitOfPower,
    UnitOfVolumeFlowRate,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from . import DaikinSkyportData
from .schedule_helpers import (
    safe_format_next_scheduled_temperature,
    safe_format_schedule_override_until,
)

from .const import (
    COORDINATOR,
    DOMAIN,
    OUTDOOR_WEATHER_SENSOR_KEYS,
)

DEVICE_CLASS_DEMAND = "demand"
DEVICE_CLASS_FAULT_CODE = "Code"
DEVICE_CLASS_FREQ_PERCENT = "frequency in percent"
DEVICE_CLASS_ACTUAL_STATUS = "actual"
DEVICE_CLASS_AIR_FLOW = "airflow"

# Sentinel values from the Daikin API meaning "no reading".
INVALID_SENSOR_VALUES = frozenset({127.5, 65535, 655350})

SENSOR_TYPES = {
    "temperature": {
        "device_class": SensorDeviceClass.TEMPERATURE,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:thermometer",
        "label": "Temperature",
    },
    "humidity": {
        "device_class": SensorDeviceClass.HUMIDITY,
        "native_unit_of_measurement": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:water-percent",
        "label": "Humidity",
    },
    "CO2": {
        "device_class": SensorDeviceClass.CO2,
        "native_unit_of_measurement": CONCENTRATION_PARTS_PER_MILLION,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:periodic-table-co2",
        "label": "CO2",
    },
    "VOC": {
        "device_class": SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS,
        "native_unit_of_measurement": CONCENTRATION_PARTS_PER_BILLION,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:cloud",
        "label": "VOC",
    },
    "ozone": {
        "device_class": SensorDeviceClass.OZONE,
        "native_unit_of_measurement": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:cloud",
        "label": "Ozone",
    },
    "particle": {
        "device_class": SensorDeviceClass.PM1,
        "native_unit_of_measurement": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:cloud",
        "label": "PM1",
    },
    "PM25": {
        "device_class": SensorDeviceClass.PM25,
        "native_unit_of_measurement": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:cloud",
        "label": "PM2.5",
    },
    "PM10": {
        "device_class": SensorDeviceClass.PM10,
        "native_unit_of_measurement": CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:cloud",
        "label": "PM10",
    },
    "score": {
        "device_class": SensorDeviceClass.AQI,
        "native_unit_of_measurement": None,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:cloud",
        "label": "AQI",
    },
    "demand": {
        "device_class": DEVICE_CLASS_DEMAND,
        "native_unit_of_measurement": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:percent",
        "label": "Demand",
    },
    "power": {
        "device_class": SensorDeviceClass.POWER,
        "native_unit_of_measurement": UnitOfPower.WATT,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:lightning-bolt",
        "label": "Power",
    },
    "frequency_percent": {
        "device_class": DEVICE_CLASS_FREQ_PERCENT,
        "native_unit_of_measurement": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:percent",
        "label": "Frequency",
    },
    "actual_status": {
        "device_class": DEVICE_CLASS_ACTUAL_STATUS,
        "native_unit_of_measurement": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:percent",
        "label": "Actual status",
    },
    "airflow": {
        "device_class": DEVICE_CLASS_AIR_FLOW,
        "native_unit_of_measurement": UnitOfVolumeFlowRate.CUBIC_FEET_PER_MINUTE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:air-filter",
        "label": "Airflow",
    },
    "fault_code": {
        "device_class": DEVICE_CLASS_FAULT_CODE,
        "native_unit_of_measurement": None,
        "state_class": None,
        "icon": "mdi:alert-circle",
        "label": "Fault",
    },
}

# API uses 255 when a fault channel does not apply to this equipment.
FAULT_NOT_PRESENT = 255

ENABLED_SENSOR_TYPES = frozenset(SENSOR_TYPES.keys())


def _fault_code_int(value) -> int | None:
    """Parse a Daikin fault code field to an integer."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_fault_code_state(value) -> str | int | None:
    """Map API fault codes to a display state."""
    code = _fault_code_int(value)
    if code is None:
        return None
    if code == FAULT_NOT_PRESENT:
        return None
    if code == 0:
        return "Clear"
    return code


def is_valid_sensor_value(value, sensor_type: str) -> bool:
    """Return True when an API value should be exposed as sensor state."""
    if value is None:
        return False
    if sensor_type == "fault_code":
        code = _fault_code_int(value)
        return code is not None and code != FAULT_NOT_PRESENT
    try:
        return float(value) not in INVALID_SENSOR_VALUES
    except (TypeError, ValueError):
        return False


def _legacy_unique_id(device_id: str, sensor_name: str, sensor_type: str) -> str:
    """Match unique_ids used before sensor keys were introduced."""
    device_class = SENSOR_TYPES[sensor_type]["device_class"]
    return f"{device_id}-{sensor_name} {device_class}"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add Daikin Skyport sensor entities from a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaikinSkyportData = data[COORDINATOR]

    entities = []
    seen_unique_ids = set()
    for index in range(len(coordinator.daikinskyport.thermostats)):
        thermostat = coordinator.daikinskyport.get_thermostat(index)
        entities.append(
            DaikinSkyportScheduleOverrideUntilSensor(
                coordinator, thermostat["name"], index
            )
        )
        entities.append(
            DaikinSkyportNextScheduledTemperatureSensor(
                coordinator, thermostat["name"], index
            )
        )
        for sensor in coordinator.daikinskyport.get_sensors(index):
            if sensor["type"] not in ENABLED_SENSOR_TYPES:
                continue
            device_id = coordinator.daikinskyport.thermostats[index]["id"]
            unique_id = _legacy_unique_id(
                device_id, sensor["name"], sensor["type"]
            )
            if unique_id in seen_unique_ids:
                continue
            seen_unique_ids.add(unique_id)
            entities.append(
                DaikinSkyportSensor(
                    coordinator,
                    sensor["key"],
                    sensor["name"],
                    sensor["type"],
                    index,
                )
            )
    async_add_entities(entities, True)


class DaikinSkyportScheduleOverrideUntilSensor(CoordinatorEntity, SensorEntity):
    """Shows when the active schedule override ends."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:calendar-clock"
    _attr_has_entity_name = True
    _attr_translation_key = "schedule_override_until"

    def __init__(self, coordinator, thermostat_name: str, index: int) -> None:
        """Initialize the schedule override until sensor."""
        super().__init__(coordinator)
        self._index = index
        device_id = coordinator.daikinskyport.thermostats[index]["id"]
        self._attr_unique_id = f"{device_id}-schedule_override_until"
        self._attr_device_info = coordinator.device_info

    def _schedule_override_active(self) -> bool:
        thermostat = self.coordinator.daikinskyport.get_thermostat(self._index)
        return (
            thermostat.get("schedOverride") == 1
            and thermostat.get("schedEnabled", True)
        )

    @property
    def available(self) -> bool:
        """Available only while a schedule override is active with a display value."""
        if not self._schedule_override_active():
            return False
        thermostat = self.coordinator.daikinskyport.get_thermostat(self._index)
        return safe_format_schedule_override_until(thermostat) is not None

    @property
    def native_value(self) -> str | None:
        """Return override end time only, e.g. '9:00 PM'."""
        if not self._schedule_override_active():
            return None
        thermostat = self.coordinator.daikinskyport.get_thermostat(self._index)
        return safe_format_schedule_override_until(thermostat)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self._write_state_from_coordinator()

    @callback
    def _write_state_from_coordinator(self) -> None:
        """Push coordinator data to the entity state."""
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._write_state_from_coordinator()


class DaikinSkyportNextScheduledTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Shows heat/cool setpoints when the active schedule override ends."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:thermometer-lines"
    _attr_has_entity_name = True
    _attr_translation_key = "next_scheduled_temperature"

    def __init__(self, coordinator, thermostat_name: str, index: int) -> None:
        """Initialize the next scheduled temperature sensor."""
        super().__init__(coordinator)
        self._index = index
        device_id = coordinator.daikinskyport.thermostats[index]["id"]
        self._attr_unique_id = f"{device_id}-next_scheduled_temperature"
        self._attr_device_info = coordinator.device_info

    def _schedule_override_active(self) -> bool:
        thermostat = self.coordinator.daikinskyport.get_thermostat(self._index)
        return (
            thermostat.get("schedOverride") == 1
            and thermostat.get("schedEnabled", True)
        )

    @property
    def available(self) -> bool:
        """Available only while override is active and setpoints are known."""
        if not self._schedule_override_active():
            return False
        thermostat = self.coordinator.daikinskyport.get_thermostat(self._index)
        return (
            safe_format_next_scheduled_temperature(thermostat, hass=self.hass)
            is not None
        )

    @property
    def native_value(self) -> str | None:
        """Return scheduled setpoints at override end, e.g. heat 21°C / cool 24°C."""
        if not self._schedule_override_active():
            return None
        thermostat = self.coordinator.daikinskyport.get_thermostat(self._index)
        return safe_format_next_scheduled_temperature(thermostat, hass=self.hass)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self._write_state_from_coordinator()

    @callback
    def _write_state_from_coordinator(self) -> None:
        """Push coordinator data to the entity state."""
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._write_state_from_coordinator()


class DaikinSkyportSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Daikin sensor."""

    def __init__(
        self,
        coordinator,
        sensor_key: str,
        sensor_name: str,
        sensor_type: str,
        sensor_index: int,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.data = coordinator
        self._sensor_key = sensor_key
        self._sensor_name = sensor_name
        self._type = sensor_type
        self._index = sensor_index

        meta = SENSOR_TYPES[sensor_type]
        device_id = coordinator.daikinskyport.thermostats[sensor_index]["id"]
        # Keep legacy unique_id so existing entity registry entries keep working.
        self._attr_unique_id = _legacy_unique_id(
            device_id, sensor_name, sensor_type
        )
        # Fault labels already include "Fault" (e.g. "Thermostat Minor Fault").
        if sensor_type == "fault_code":
            self._attr_name = sensor_name
        elif sensor_key == "indoor_power":
            self._attr_name = "Power"
        else:
            self._attr_name = f"{sensor_name} {meta['label']}"
        self._attr_device_class = meta["device_class"]
        self._attr_icon = meta["icon"]
        self._attr_native_unit_of_measurement = meta["native_unit_of_measurement"]
        self._attr_state_class = meta["state_class"]
        if sensor_key in OUTDOOR_WEATHER_SENSOR_KEYS:
            self._attr_device_info = coordinator.outdoor_weather_device_info(
                sensor_index
            )
        else:
            self._attr_device_info = coordinator.device_info

    @property
    def available(self) -> bool:
        """Return True when the API is providing a valid reading."""
        return self.native_value is not None

    @property
    def native_value(self):
        """Return the current reading from the coordinator cache."""
        for sensor in self.coordinator.daikinskyport.get_sensors(self._index):
            if sensor["key"] != self._sensor_key:
                continue
            if self._type == "fault_code":
                return format_fault_code_state(sensor["value"])
            if is_valid_sensor_value(sensor["value"], self._type):
                return sensor["value"]
            return None
        return None

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        self._write_state_from_coordinator()

    @callback
    def _write_state_from_coordinator(self) -> None:
        """Push coordinator data to the entity state."""
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._write_state_from_coordinator()
