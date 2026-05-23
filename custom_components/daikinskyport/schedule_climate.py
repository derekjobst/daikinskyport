"""Minimal climate entities for per-period schedule setpoints."""
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.climate.const import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .logbook_helpers import format_temp_dual
from .schedule_helpers import SchedulePeriod, iter_enabled_schedule_periods
from .thermostat_helpers import (
    SETPOINT_MAX_C,
    SETPOINT_MIN_C,
    climate_precision,
    temperature_for_display,
    thermostat_has_cooling,
    thermostat_has_heat,
    thermostat_supports_setpoint_climate,
)


def build_schedule_period_climate_entities(
    coordinator, thermostat_index: int, thermostat: dict
) -> list[ClimateEntity]:
    """Create one setpoint climate entity per enabled schedule period."""
    if not thermostat_supports_setpoint_climate(thermostat):
        return []
    device_id = thermostat["id"]
    has_heat = thermostat_has_heat(thermostat)
    has_cool = thermostat_has_cooling(thermostat)
    entities: list[ClimateEntity] = []
    for period in iter_enabled_schedule_periods(thermostat):
        entities.append(
            DaikinSkyportSchedulePeriodClimate(
                coordinator,
                thermostat_index,
                device_id,
                period,
                has_heat=has_heat,
                has_cool=has_cool,
            )
        )
    return entities


class DaikinSkyportSchedulePeriodClimate(CoordinatorEntity, ClimateEntity):
    """Edit heat/cool setpoints for one enabled schedule period."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_min_temp = SETPOINT_MIN_C
    _attr_max_temp = SETPOINT_MAX_C
    _attr_hvac_action = None
    _attr_preset_mode = None
    _attr_current_temperature = None

    def __init__(
        self,
        coordinator,
        thermostat_index: int,
        device_id: str,
        period: SchedulePeriod,
        *,
        has_heat: bool,
        has_cool: bool,
    ) -> None:
        """Initialize a schedule period setpoint entity."""
        super().__init__(coordinator)
        self.thermostat_index = thermostat_index
        self._period = period
        self._has_heat = has_heat
        self._has_cool = has_cool
        self._use_range = has_heat and has_cool
        self._hsp_key = f"{period.prefix}hsp"
        self._csp_key = f"{period.prefix}csp"
        self._attr_name = period.display_name
        self._attr_unique_id = (
            f"{device_id}-sched-{period.day_code.lower()}-part{period.part}"
        )
        if self._use_range:
            self._attr_hvac_modes = [HVACMode.HEAT_COOL]
            self._attr_hvac_mode = HVACMode.HEAT_COOL
        elif has_heat:
            self._attr_hvac_modes = [HVACMode.HEAT]
            self._attr_hvac_mode = HVACMode.HEAT
        else:
            self._attr_hvac_modes = [HVACMode.COOL]
            self._attr_hvac_mode = HVACMode.COOL
        self.thermostat = coordinator.daikinskyport.get_thermostat(thermostat_index)
        self._attr_device_info = coordinator.device_info

    @property
    def supported_features(self) -> ClimateEntityFeature:
        if self._use_range:
            return ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        return ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def precision(self) -> float:
        return climate_precision(self.hass)

    @property
    def target_temperature_low(self) -> float | None:
        if not self._use_range:
            return None
        return temperature_for_display(
            self.hass, self.thermostat.get(self._hsp_key)
        )

    @property
    def target_temperature_high(self) -> float | None:
        if not self._use_range:
            return None
        return temperature_for_display(
            self.hass, self.thermostat.get(self._csp_key)
        )

    @property
    def target_temperature(self) -> float | None:
        if self._use_range:
            return None
        if self._has_heat:
            return temperature_for_display(
                self.hass, self.thermostat.get(self._hsp_key)
            )
        return temperature_for_display(
            self.hass, self.thermostat.get(self._csp_key)
        )

    async def async_set_temperature(self, **kwargs) -> None:
        """Write setpoints for this schedule period only."""
        low_temp = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high_temp = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        temp = kwargs.get(ATTR_TEMPERATURE)
        thermostat = self.coordinator.daikinskyport.get_thermostat(self.thermostat_index)

        if self._use_range:
            heat_temp = (
                low_temp if low_temp is not None else thermostat.get(self._hsp_key)
            )
            cool_temp = (
                high_temp if high_temp is not None else thermostat.get(self._csp_key)
            )
        elif self._has_heat:
            heat_temp = temp if temp is not None else thermostat.get(self._hsp_key)
            cool_temp = None
        else:
            heat_temp = None
            cool_temp = temp if temp is not None else thermostat.get(self._csp_key)

        if heat_temp is None and cool_temp is None:
            raise HomeAssistantError("No schedule setpoint temperature provided")

        self.coordinator.mark_ha_control_change(self.thermostat_index)
        ok = await self.hass.async_add_executor_job(
            self.coordinator.daikinskyport.set_schedule_part_setpoints,
            self.thermostat_index,
            self._period.prefix,
            heat_temp,
            cool_temp,
        )
        if not ok:
            raise HomeAssistantError(
                f"Failed to set schedule period {self._period.display_name}"
            )

        self.thermostat = self.coordinator.daikinskyport.get_thermostat(
            self.thermostat_index
        )
        self.coordinator.log_climate_entry(
            self.entity_id,
            self._period.display_name,
            (
                f"[Home Assistant] Set {self._period.display_name} to heat "
                f"{format_temp_dual(heat_temp)} / cool {format_temp_dual(cool_temp)}"
            ),
        )
        self.coordinator.async_set_updated_data(
            self.coordinator.daikinskyport.thermostats
        )
        self.coordinator.schedule_post_write_refresh()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.thermostat = self.coordinator.daikinskyport.get_thermostat(
            self.thermostat_index
        )
        self.async_write_ha_state()
