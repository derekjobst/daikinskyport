"""Daikin Skyport integration."""
import time
from datetime import timedelta

from homeassistant.const import (
    CONF_PASSWORD,
    CONF_EMAIL,
    CONF_NAME,
    Platform,
)
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.entity import DeviceInfo

from .daikinskyport import DaikinSkyport, ExpiredTokenError
from .logbook_helpers import LOCAL_CHANGE_SUPPRESS_SECONDS, write_climate_logbook_entry
from .const import (
    _LOGGER,
    DOMAIN,
    MANUFACTURER,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    COORDINATOR,
    HOLD_PENDING_SECONDS,
    RAPID_POLL_AFTER_PUT_COUNT,
    RAPID_POLL_AFTER_PUT_INTERVAL,
    UPDATE_INTERVAL,
)

# Force a coordinator refresh once the hold-merge window has had time to finish.
POST_WRITE_REFRESH_DELAY = HOLD_PENDING_SECONDS
UNDO_UPDATE_LISTENER = "undo_update_listener"

PLATFORMS = [
    Platform.SENSOR,
    Platform.WEATHER,
    Platform.CLIMATE,
    Platform.SWITCH,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up DaikinSkyport as config entry."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info("Daikin Skyport Starting")

    email: str = entry.data[CONF_EMAIL]
    password: str = entry.data[CONF_PASSWORD]
    try:
        name: str = entry.options[CONF_NAME]
    except KeyError:
        name: str = entry.data[CONF_NAME]
    try:
        access_token: str = entry.data[CONF_ACCESS_TOKEN]
        refresh_token: str = entry.data[CONF_REFRESH_TOKEN]
    except KeyError:
        _LOGGER.debug("Tokens not in config for Daikin Skyport")
        access_token = ""
        refresh_token = ""
    config = {
        "EMAIL": email,
        "PASSWORD": password,
        "ACCESS_TOKEN": access_token,
        "REFRESH_TOKEN": refresh_token,
    }

    assert entry.unique_id is not None
    unique_id = entry.unique_id

    _LOGGER.debug("Using email: %s", email)

    coordinator = DaikinSkyportData(hass, config, unique_id, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ExpiredTokenError:
        _LOGGER.warning("Unable to refresh auth token.")
        raise ConfigEntryNotReady("Unable to refresh token.") from None

    if coordinator.daikinskyport.thermostats is None:
        _LOGGER.error("No Daikin Skyport devices found to set up")
        return False

    undo_listener = entry.add_update_listener(update_listener)

    hass.data[DOMAIN][entry.entry_id] = {
        COORDINATOR: coordinator,
        UNDO_UPDATE_LISTENER: undo_listener,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unload Entry: %s", str(entry))
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    hass.data[DOMAIN][entry.entry_id][UNDO_UPDATE_LISTENER]()

    if unload_ok:
        coordinator = hass.data[DOMAIN][entry.entry_id][COORDINATOR]
        coordinator.cancel_rapid_poll_burst()
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    _LOGGER.debug("Reload Entry: %s", str(entry))
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


class DaikinSkyportData(DataUpdateCoordinator):
    """Poll Daikin Skyport once and push updates to all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        config,
        unique_id: str,
        entry: ConfigEntry,
    ) -> None:
        """Init the Daikin Skyport data coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        try:
            self.name: str = entry.options[CONF_NAME]
        except KeyError:
            self.name: str = entry.data[CONF_NAME]
        self.entry = entry
        self.unique_id = unique_id
        self.daikinskyport = DaikinSkyport(config=config)
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            manufacturer=MANUFACTURER,
            name=self.name,
        )
        self._post_write_refresh_unsub = None
        self._force_next_update = False
        self._suppress_cloud_log_until: dict[int, float] = {}
        self.rapid_poll_after_put_enabled = False
        self._rapid_poll_unsub = None
        self._rapid_poll_index: int | None = None
        self._rapid_poll_sample = 0
        self.daikinskyport.on_put_success = self._on_put_success
        self._climate_log_targets: dict[int, tuple[str, str]] = {}

    def register_climate_entity(
        self, thermostat_index: int, entity_id: str, name: str
    ) -> None:
        """Register the main climate entity for logbook messages."""
        self._climate_log_targets[thermostat_index] = (entity_id, name)

    def outdoor_weather_device_info(self, thermostat_index: int) -> DeviceInfo:
        """Device for cloud outdoor weather and related outdoor air readings."""
        thermostat = self.daikinskyport.thermostats[thermostat_index]
        device_id = thermostat["id"]
        thermostat_name = thermostat.get("name", "Thermostat")
        return DeviceInfo(
            identifiers={(DOMAIN, device_id, "outdoor_weather")},
            manufacturer=MANUFACTURER,
            name=f"{thermostat_name} Outdoor Weather",
            via_device=(DOMAIN, self.unique_id),
        )

    def mark_ha_control_change(self, thermostat_index: int) -> None:
        """Suppress cloud logbook entries while HA/API changes settle."""
        self._suppress_cloud_log_until[thermostat_index] = (
            time.time() + LOCAL_CHANGE_SUPPRESS_SECONDS
        )

    def should_log_cloud_change(self, thermostat_index: int) -> bool:
        """Return True when a poll change is likely external (thermostat/cloud)."""
        if time.time() < self._suppress_cloud_log_until.get(thermostat_index, 0):
            return False
        if self.daikinskyport.has_pending_writes(thermostat_index):
            return False
        return True

    @callback
    def _dispatch_sync_log_events(self) -> None:
        """Write logbook entries for confirmed or timed-out cloud sync batches."""
        from .sync_helpers import format_sync_event_message, pop_sync_log_events

        for index, thermostat in enumerate(self.daikinskyport.thermostats):
            events = pop_sync_log_events(thermostat)
            if not events:
                continue
            target = self._climate_log_targets.get(index)
            if not target:
                continue
            entity_id, name = target
            for event in events:
                self.log_climate_entry(
                    entity_id,
                    name,
                    format_sync_event_message(event, hass=self.hass),
                )

    @callback
    def _write_logbook_entry(
        self, entity_id: str, name: str, message: str
    ) -> None:
        write_climate_logbook_entry(self.hass, entity_id, name, message)

    def log_climate_entry(
        self, entity_id: str, name: str, message: str
    ) -> None:
        """Schedule a logbook entry (safe from sync climate service handlers)."""
        # climate.set_temperature runs in an executor thread; never use
        # hass.async_create_task here — use hass.add_job instead.
        self.hass.add_job(
            self._write_logbook_entry, entity_id, name, message
        )

    @callback
    def _schedule_post_write_refresh(self) -> None:
        """Poll the server shortly after a write once the API has settled."""
        if self._post_write_refresh_unsub:
            self._post_write_refresh_unsub()
            self._post_write_refresh_unsub = None

        @callback
        def _refresh(_now):
            self._force_next_update = True
            self.async_request_refresh()

        self._post_write_refresh_unsub = async_call_later(
            self.hass, POST_WRITE_REFRESH_DELAY, _refresh
        )

    def schedule_post_write_refresh(self) -> None:
        """Schedule a delayed refresh (safe from sync or async context)."""
        self.hass.add_job(self._schedule_post_write_refresh)

    def _rapid_poll_refresh(self, thermostat_index: int, context: str) -> bool:
        """Executor helper: raw cloud GET for one diagnostic burst sample."""
        return self.daikinskyport.refresh_thermostat_from_cloud(
            thermostat_index,
            apply_hold_merge=False,
            context=context,
        )

    def _on_put_success(self, thermostat_index: int) -> None:
        """Run diagnostic rapid GET burst after a successful PUT."""
        if not self.rapid_poll_after_put_enabled:
            return
        self.hass.add_job(self._start_rapid_poll_burst, thermostat_index)

    def cancel_rapid_poll_burst(self) -> None:
        """Cancel any in-flight diagnostic rapid poll sequence."""
        if self._rapid_poll_unsub:
            self._rapid_poll_unsub()
            self._rapid_poll_unsub = None
        self._rapid_poll_index = None
        self._rapid_poll_sample = 0

    @callback
    def _start_rapid_poll_burst(self, thermostat_index: int) -> None:
        """Schedule GET every second for RAPID_POLL_AFTER_PUT_COUNT samples."""
        self.cancel_rapid_poll_burst()
        self._rapid_poll_index = thermostat_index
        self._rapid_poll_sample = 0
        _LOGGER.info(
            "Starting rapid poll after PUT: %s GETs every %ss for thermostat index %s",
            RAPID_POLL_AFTER_PUT_COUNT,
            RAPID_POLL_AFTER_PUT_INTERVAL,
            thermostat_index,
        )
        self._schedule_rapid_poll_sample()

    @callback
    def _schedule_rapid_poll_sample(self, _now=None) -> None:
        """Fire one burst sample and queue the next."""
        if self._rapid_poll_index is None:
            return
        self._rapid_poll_sample += 1
        if self._rapid_poll_sample > RAPID_POLL_AFTER_PUT_COUNT:
            self.cancel_rapid_poll_burst()
            return
        self.hass.async_create_task(
            self._run_rapid_poll_sample(
                self._rapid_poll_index, self._rapid_poll_sample
            )
        )
        if self._rapid_poll_sample < RAPID_POLL_AFTER_PUT_COUNT:
            self._rapid_poll_unsub = async_call_later(
                self.hass,
                RAPID_POLL_AFTER_PUT_INTERVAL,
                self._schedule_rapid_poll_sample,
            )

    async def _run_rapid_poll_sample(
        self, thermostat_index: int, sample: int
    ) -> None:
        """GET raw cloud data for one burst sample and push to entities."""
        context = f"PUT burst {sample}/{RAPID_POLL_AFTER_PUT_COUNT}"
        try:
            ok = await self.hass.async_add_executor_job(
                self._rapid_poll_refresh,
                thermostat_index,
                context,
            )
            if ok:
                self.async_set_updated_data(self.daikinskyport.thermostats)
            else:
                _LOGGER.warning("Rapid poll sample %s: device offline or missing", context)
        except ExpiredTokenError:
            _LOGGER.warning("Rapid poll sample %s: token expired", context)
            if await self.async_refresh_tokens():
                ok = await self.hass.async_add_executor_job(
                    self._rapid_poll_refresh,
                    thermostat_index,
                    context,
                )
                if ok:
                    self.async_set_updated_data(self.daikinskyport.thermostats)
        except Exception as err:
            _LOGGER.warning("Rapid poll sample %s failed: %s", context, err)

    async def _async_update_data(self):
        """Update data via library."""
        force = self._force_next_update
        self._force_next_update = False
        try:
            await self.hass.async_add_executor_job(
                self.daikinskyport.update, force, True
            )
            _LOGGER.debug("Daikin Skyport data updated successfully")
        except ExpiredTokenError as err:
            _LOGGER.debug("Daikin Skyport tokens expired")
            if not await self.async_refresh_tokens():
                raise UpdateFailed("Unable to refresh Daikin Skyport tokens") from err
            await self.hass.async_add_executor_job(
                self.daikinskyport.update, force, True
            )
        self._dispatch_sync_log_events()
        return self.daikinskyport.thermostats

    async def async_force_cloud_refresh(
        self, thermostat_index: int, *, raw_cloud: bool = False
    ) -> None:
        """Force GET from Daikin cloud and push state to all entities.

        raw_cloud: when True, do not apply pending-hold merge (raw API values).
        """
        context = (
            "manual button refresh (raw cloud)"
            if raw_cloud
            else "manual button refresh"
        )
        _LOGGER.info(
            "Starting forced cloud refresh for thermostat index %s (raw_cloud=%s)",
            thermostat_index,
            raw_cloud,
        )
        await self.hass.async_add_executor_job(
            self.daikinskyport.update, True, not raw_cloud
        )
        if not raw_cloud:
            self._dispatch_sync_log_events()
        self.daikinskyport.log_cloud_snapshot(thermostat_index, context)
        self.async_set_updated_data(self.daikinskyport.thermostats)

    async def async_refresh_tokens(self) -> bool:
        """Refresh API tokens and update config entry."""
        _LOGGER.debug("Refreshing Daikin Skyport tokens and updating config entry")
        if await self.hass.async_add_executor_job(self.daikinskyport.refresh_tokens):
            self.hass.config_entries.async_update_entry(
                self.entry,
                data={
                    CONF_NAME: self.name,
                    CONF_REFRESH_TOKEN: self.daikinskyport.refresh_token,
                    CONF_ACCESS_TOKEN: self.daikinskyport.access_token,
                    CONF_EMAIL: self.daikinskyport.user_email,
                    CONF_PASSWORD: self.daikinskyport.user_password,
                },
            )
            return True
        _LOGGER.error("Error refreshing Daikin Skyport tokens")
        return False
