"""Daikin Skyport switch"""
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity


from .const import (
    _LOGGER,
    COORDINATOR,
    DOMAIN,
    DAIKIN_HVAC_MODE_AUXHEAT,
    DAIKIN_HVAC_MODE_HEAT
)
from . import DaikinSkyportData

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add a Daikin Skyport Switch entity from a config_entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaikinSkyportData = data[COORDINATOR]

    entities = [DaikinSkyportRapidPollAfterPutSwitch(coordinator)]
    for index in range(len(coordinator.daikinskyport.thermostats)):
        thermostat = coordinator.daikinskyport.get_thermostat(index)
        entities.append(DaikinSkyportAuxHeat(coordinator, thermostat["name"], index))
    async_add_entities(entities, True)


class DaikinSkyportRapidPollAfterPutSwitch(CoordinatorEntity, SwitchEntity):
    """Diagnostic: GET cloud data every second for 15s after each PUT."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "rapid_poll_after_writes"
    _attr_icon = "mdi:timer-sync"

    def __init__(self, coordinator) -> None:
        """Initialize the diagnostic rapid-poll switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.unique_id}-rapid-poll-after-put"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        """Return whether rapid polling after PUT is enabled."""
        return self.coordinator.rapid_poll_after_put_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable rapid polling after each successful PUT."""
        self.coordinator.rapid_poll_after_put_enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable rapid polling and cancel any in-flight burst."""
        self.coordinator.rapid_poll_after_put_enabled = False
        self.coordinator.cancel_rapid_poll_burst()
        self.async_write_ha_state()

class DaikinSkyportAuxHeat(CoordinatorEntity, SwitchEntity):
    """Representation of Daikin Skyport aux_heat data."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator, name, index):
        """Initialize the Daikin Skyport aux_heat platform."""
        super().__init__(coordinator)
        self.data = coordinator
        self._name = f"{name} Aux Heat"
        self._attr_unique_id = f"{coordinator.daikinskyport.thermostats[index]['id']}-{self._name}"
        self._index = index
        self.aux_on = False

    @property
    def name(self) -> str:
        """Name of the switch."""
        return self._name

    @property
    def is_on(self) -> bool:
        """Status of the switch."""
        return self.aux_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        send_command = await self.hass.async_add_executor_job(
            self.data.daikinskyport.set_hvac_mode,
            self._index,
            DAIKIN_HVAC_MODE_AUXHEAT,
        )
        if send_command:
            self.aux_on = True
            self.coordinator.async_set_updated_data(
                self.coordinator.daikinskyport.thermostats
            )
            self.coordinator.schedule_post_write_refresh()
            self.async_write_ha_state()
        else:
            raise HomeAssistantError(f"Failed to turn on {self._name}")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        def _turn_off() -> None:
            if (
                self.data.daikinskyport.get_thermostat(self._index)["mode"]
                == DAIKIN_HVAC_MODE_AUXHEAT
            ):
                self.data.daikinskyport.set_hvac_mode(
                    self._index, DAIKIN_HVAC_MODE_HEAT
                )

        await self.hass.async_add_executor_job(_turn_off)
        self.aux_on = False
        self.coordinator.async_set_updated_data(
            self.coordinator.daikinskyport.thermostats
        )
        self.coordinator.schedule_post_write_refresh()
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return self.data.device_info

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("Updating switch entity")
        thermostat = self.coordinator.daikinskyport.get_thermostat(self._index)
        if thermostat['mode'] == DAIKIN_HVAC_MODE_AUXHEAT:
            self.aux_on = True
        else:
            self.aux_on = False
        self.async_write_ha_state()
