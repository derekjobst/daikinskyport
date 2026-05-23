"""Pending cloud-write batches and sync status helpers."""
from __future__ import annotations

import time
import uuid
from typing import Any

from .const import (
    DAIKIN_HVAC_MODE_AUTO,
    DAIKIN_HVAC_MODE_AUXHEAT,
    DAIKIN_HVAC_MODE_COOL,
    DAIKIN_HVAC_MODE_HEAT,
    DAIKIN_HVAC_MODE_OFF,
    HOLD_PENDING_SECONDS,
    _LOGGER,
)

PENDING_BATCHES_KEY = "_pending_write_batches"
PENDING_KEYS_KEY = "_pending_write_keys"
PENDING_UNTIL_KEY = "_hold_pending_until"
SYNC_LOG_EVENTS_KEY = "_sync_log_events"

LOGBOOK_SKIP_ACTIONS = frozenset({"reset P1P2 fields"})

ACTIVE_HOME_MISMATCH_THRESHOLD = 0.15

_HVAC_MODE_LABELS = {
    DAIKIN_HVAC_MODE_OFF: "off",
    DAIKIN_HVAC_MODE_HEAT: "heat",
    DAIKIN_HVAC_MODE_COOL: "cool",
    DAIKIN_HVAC_MODE_AUTO: "auto",
    DAIKIN_HVAC_MODE_AUXHEAT: "aux heat",
}

_FIELD_LABELS = {
    "mode": "HVAC mode",
    "hspHome": "heat setpoint",
    "cspHome": "cool setpoint",
    "hspActive": "active heat",
    "cspActive": "active cool",
    "hspAway": "away heat",
    "cspAway": "away cool",
    "geofencingAway": "away mode",
    "schedOverride": "schedule override",
    "schedEnabled": "schedule enabled",
    "schedOverrideDuration": "override duration",
    "fanCirculate": "fan mode",
    "fanCirculateSpeed": "fan speed",
    "humSP": "humidity setpoint",
    "dehumSP": "dehumidify setpoint",
    "oneCleanFanActive": "OneClean",
    "ctDualFuelFurnaceLockoutEnable": "efficiency mode",
    "nightModeEnabled": "night mode",
    "nightModeStart": "night mode start",
    "nightModeStop": "night mode stop",
}


def pending_values_match(expected: Any, actual: Any) -> bool:
    """Return True when a polled cloud value matches an optimistic write."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= ACTIVE_HOME_MISMATCH_THRESHOLD
    return expected == actual


def has_pending_write_batches(thermostat: dict[str, Any]) -> bool:
    """Return True while any PUT batch is awaiting cloud confirmation."""
    return bool(thermostat.get(PENDING_BATCHES_KEY))


def pop_sync_log_events(thermostat: dict[str, Any]) -> list[dict[str, Any]]:
    """Return and clear sync log events queued on the last poll."""
    events = thermostat.pop(SYNC_LOG_EVENTS_KEY, [])
    return events if isinstance(events, list) else []


def append_write_batch(
    thermostat: dict[str, Any], body: dict[str, Any], action: str
) -> None:
    """Record a successful PUT as a pending batch (supports overlapping writes)."""
    if not body:
        return

    now = time.time()
    new_keys = {key for key in body if not key.startswith("_")}
    batches: list[dict[str, Any]] = list(thermostat.get(PENDING_BATCHES_KEY) or [])

    if new_keys:
        pruned: list[dict[str, Any]] = []
        for batch in batches:
            keys = batch.get("keys") or {}
            remaining = {
                key: value for key, value in keys.items() if key not in new_keys
            }
            if remaining:
                pruned.append({**batch, "keys": remaining})
        batches = pruned

    batches.append(
        {
            "id": uuid.uuid4().hex[:12],
            "action": action,
            "created_at": now,
            "until": now + HOLD_PENDING_SECONDS,
            "keys": dict(body),
        }
    )
    thermostat[PENDING_BATCHES_KEY] = batches
    _rebuild_flat_pending(thermostat)


def _rebuild_flat_pending(thermostat: dict[str, Any]) -> None:
    """Derive flat pending keys and deadline from active batches."""
    batches: list[dict[str, Any]] = list(thermostat.get(PENDING_BATCHES_KEY) or [])
    pending: dict[str, Any] = {}
    until = 0.0
    for batch in batches:
        until = max(until, float(batch.get("until") or 0))
        for key, value in (batch.get("keys") or {}).items():
            pending[key] = value
    if pending:
        thermostat[PENDING_KEYS_KEY] = pending
        thermostat[PENDING_UNTIL_KEY] = until
    else:
        thermostat.pop(PENDING_KEYS_KEY, None)
        thermostat.pop(PENDING_UNTIL_KEY, None)


def _batch_confirmed(batch: dict[str, Any], cloud: dict[str, Any]) -> bool:
    keys = batch.get("keys") or {}
    return all(pending_values_match(expected, cloud.get(key)) for key, expected in keys.items())


def reconcile_pending_batches(
    thermostat: dict[str, Any], cloud: dict[str, Any]
) -> list[dict[str, Any]]:
    """Update batch queue from a raw cloud poll; return new log-worthy events."""
    batches: list[dict[str, Any]] = list(thermostat.get(PENDING_BATCHES_KEY) or [])
    if not batches:
        thermostat.pop(PENDING_KEYS_KEY, None)
        thermostat.pop(PENDING_UNTIL_KEY, None)
        return []

    now = time.time()
    events: list[dict[str, Any]] = []
    remaining: list[dict[str, Any]] = []

    for batch in batches:
        action = batch.get("action") or "update"
        keys = batch.get("keys") or {}
        skip_log = action in LOGBOOK_SKIP_ACTIONS

        if _batch_confirmed(batch, cloud):
            if not skip_log:
                events.append(
                    {"type": "confirmed", "action": action, "keys": dict(keys)}
                )
            continue

        if now > float(batch.get("until") or 0):
            if not skip_log:
                events.append({"type": "timeout", "action": action, "keys": dict(keys)})
            _LOGGER.warning(
                "Cloud sync timed out for %s (%s): %s",
                thermostat.get("name", thermostat.get("id")),
                action,
                ", ".join(sorted(keys)),
            )
            continue

        remaining.append(batch)

    thermostat[PENDING_BATCHES_KEY] = remaining
    _rebuild_flat_pending(thermostat)
    return events


def merge_pending_fields(
    old: dict[str, Any], cloud: dict[str, Any]
) -> dict[str, Any]:
    """Overlay optimistic pending fields onto a raw cloud payload."""
    until = old.get(PENDING_UNTIL_KEY)
    pending = old.get(PENDING_KEYS_KEY) or {}
    if not until or time.time() > until or not pending:
        return dict(cloud)
    if all(pending_values_match(expected, cloud.get(key)) for key, expected in pending.items()):
        return dict(cloud)

    merged = dict(cloud)
    for key, expected in pending.items():
        if not pending_values_match(expected, cloud.get(key)):
            merged[key] = expected
    return merged


def copy_pending_internal_state(source: dict[str, Any], target: dict[str, Any]) -> None:
    """Preserve pending-write metadata on the thermostat cache entry."""
    for key in (
        PENDING_BATCHES_KEY,
        PENDING_KEYS_KEY,
        PENDING_UNTIL_KEY,
        "_override_started_at",
    ):
        if key in source:
            target[key] = source[key]
        else:
            target.pop(key, None)


def pending_batch_summaries(thermostat: dict[str, Any]) -> list[str]:
    """Return human-readable pending action labels for sensor attributes."""
    batches: list[dict[str, Any]] = thermostat.get(PENDING_BATCHES_KEY) or []
    return [batch.get("action") or "update" for batch in batches]


def _field_label(key: str) -> str:
    if key in _FIELD_LABELS:
        return _FIELD_LABELS[key]
    if key.endswith("hsp"):
        return f"{key} heat"
    if key.endswith("csp"):
        return f"{key} cool"
    if key.endswith("Enabled"):
        return key
    if key.endswith("Time"):
        return key
    if key.endswith("Label"):
        return key
    return key


def _format_field_value(hass: Any | None, key: str, value: Any) -> str:
    if value is None:
        return "—"
    if key == "mode" and isinstance(value, int):
        return _HVAC_MODE_LABELS.get(value, str(value))
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, (int, float)) and (
        key in _FIELD_LABELS
        or key.endswith("hsp")
        or key.endswith("csp")
        or key.endswith("SP")
    ):
        if hass is not None:
            from .logbook_helpers import format_temperature

            return format_temperature(hass, value)
    return str(value)


def format_batch_keys_for_logbook(
    keys: dict[str, Any], *, hass: Any | None = None, max_fields: int = 4
) -> str:
    """Compact description of fields in a pending batch."""
    if not keys:
        return ""
    items = []
    for key in sorted(keys):
        label = _field_label(key)
        items.append(f"{label} {_format_field_value(hass, key, keys[key])}")
    if len(items) > max_fields:
        extra = len(items) - max_fields
        items = items[:max_fields]
        items.append(f"+{extra} more")
    return ", ".join(items)


def format_sync_event_message(event: dict[str, Any], *, hass: Any | None = None) -> str:
    """Build a logbook line for a batch confirm or timeout event."""
    action = event.get("action") or "update"
    keys = event.get("keys") or {}
    detail = format_batch_keys_for_logbook(keys, hass=hass)
    if event.get("type") == "timeout":
        if detail:
            return f"[Cloud sync] Timed out waiting for {action} ({detail})"
        return f"[Cloud sync] Timed out waiting for {action}"
    if detail:
        return f"[Cloud sync] Confirmed {action} ({detail})"
    return f"[Cloud sync] Confirmed {action}"
