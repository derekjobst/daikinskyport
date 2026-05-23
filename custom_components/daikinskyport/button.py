"""Button entities for Daikin Skyport."""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DaikinSkyportData
from .const import COORDINATOR, DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add refresh buttons for each thermostat."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaikinSkyportData = data[COORDINATOR]

    entities = []
    for index in range(len(coordinator.daikinskyport.thermostats)):
        thermostat = coordinator.daikinskyport.get_thermostat(index)
        entities.append(DaikinSkyportRefreshCloudButton(coordinator, index))

    async_add_entities(entities)


class DaikinSkyportRefreshCloudButton(CoordinatorEntity, ButtonEntity):
    """Force a cloud GET and update HA state (for tuning/debugging)."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_name = "Refresh Cloud Data"
    _attr_icon = "mdi:cloud-sync"

    def __init__(self, coordinator, index) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator)
        self._index = index
        self._attr_unique_id = (
            f"{coordinator.daikinskyport.thermostats[index]['id']}-refresh-cloud"
        )
        self._attr_device_info = coordinator.device_info

    async def async_press(self) -> None:
        """Fetch raw cloud state, log snapshot, and update entities."""
        await self.coordinator.async_force_cloud_refresh(
            self._index, raw_cloud=True
        )
