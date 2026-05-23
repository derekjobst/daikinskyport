"""Unit tests for pending cloud-write batch helpers."""
from __future__ import annotations

import time

from daikinskyport.sync_helpers import (
    LOGBOOK_SKIP_ACTIONS,
    PENDING_BATCHES_KEY,
    PENDING_KEYS_KEY,
    PENDING_UNTIL_KEY,
    append_write_batch,
    format_batch_keys_for_logbook,
    format_sync_event_message,
    has_pending_write_batches,
    merge_pending_fields,
    pending_values_match,
    pop_sync_log_events,
    reconcile_pending_batches,
)


class TestPendingValuesMatch:
    def test_mismatch_types(self) -> None:
        assert pending_values_match(1, None) is False
        assert pending_values_match(None, 1) is False


class TestAppendWriteBatch:
    def test_creates_batch_and_flat_pending(self) -> None:
        thermostat: dict = {}
        append_write_batch(
            thermostat,
            {"hspHome": 21.0, "cspHome": 24.0},
            "set hold temp",
        )
        assert has_pending_write_batches(thermostat)
        assert thermostat[PENDING_KEYS_KEY]["hspHome"] == 21.0
        assert thermostat[PENDING_UNTIL_KEY] > time.time()

    def test_supersedes_keys_in_older_batches(self) -> None:
        thermostat: dict = {}
        append_write_batch(thermostat, {"hspHome": 20.0}, "first")
        append_write_batch(thermostat, {"hspHome": 21.0}, "second")
        batches = thermostat[PENDING_BATCHES_KEY]
        assert len(batches) == 1
        assert batches[0]["action"] == "second"
        assert batches[0]["keys"]["hspHome"] == 21.0
        assert thermostat[PENDING_KEYS_KEY]["hspHome"] == 21.0


class TestReconcilePendingBatches:
    def test_confirmed_batch_removed_and_event_emitted(self) -> None:
        thermostat: dict = {}
        append_write_batch(thermostat, {"mode": 1}, "set HVAC mode")
        events = reconcile_pending_batches(thermostat, {"mode": 1})
        assert len(events) == 1
        assert events[0]["type"] == "confirmed"
        assert events[0]["action"] == "set HVAC mode"
        assert not has_pending_write_batches(thermostat)

    def test_still_pending_when_cloud_stale(self) -> None:
        thermostat: dict = {}
        append_write_batch(thermostat, {"hspHome": 21.0}, "set hold temp")
        events = reconcile_pending_batches(thermostat, {"hspHome": 20.0})
        assert events == []
        assert has_pending_write_batches(thermostat)

    def test_timeout_emits_event_and_clears_batch(self) -> None:
        thermostat: dict = {}
        append_write_batch(thermostat, {"hspHome": 21.0}, "set hold temp")
        thermostat[PENDING_BATCHES_KEY][0]["until"] = time.time() - 1
        events = reconcile_pending_batches(thermostat, {"hspHome": 20.0})
        assert len(events) == 1
        assert events[0]["type"] == "timeout"
        assert not has_pending_write_batches(thermostat)

    def test_skips_logbook_for_p1p2_reset(self) -> None:
        thermostat: dict = {}
        action = next(iter(LOGBOOK_SKIP_ACTIONS))
        append_write_batch(
            thermostat,
            {"P1P2FieldSettingModeNumber": 0},
            action,
        )
        events = reconcile_pending_batches(
            thermostat, {"P1P2FieldSettingModeNumber": 0}
        )
        assert events == []
        assert not has_pending_write_batches(thermostat)

    def test_independent_batches_confirm_separately(self) -> None:
        thermostat: dict = {}
        append_write_batch(thermostat, {"mode": 1}, "set HVAC mode")
        append_write_batch(thermostat, {"hspHome": 21.0}, "set hold temp")
        events = reconcile_pending_batches(thermostat, {"mode": 1, "hspHome": 20.0})
        assert len(events) == 1
        assert events[0]["action"] == "set HVAC mode"
        assert has_pending_write_batches(thermostat)
        assert len(thermostat[PENDING_BATCHES_KEY]) == 1


class TestMergePendingFields:
    def test_overlays_stale_cloud_values(self) -> None:
        old = {PENDING_KEYS_KEY: {"hspHome": 21.0}, PENDING_UNTIL_KEY: time.time() + 60}
        merged = merge_pending_fields(old, {"hspHome": 20.0})
        assert merged["hspHome"] == 21.0

    def test_returns_cloud_when_confirmed(self) -> None:
        old = {PENDING_KEYS_KEY: {"hspHome": 21.0}, PENDING_UNTIL_KEY: time.time() + 60}
        merged = merge_pending_fields(old, {"hspHome": 21.0})
        assert merged["hspHome"] == 21.0


class TestSyncLogFormatting:
    def test_format_batch_keys_for_logbook(self) -> None:
        text = format_batch_keys_for_logbook({"hspHome": 21.0, "mode": 1})
        assert "heat setpoint" in text
        assert "HVAC mode" in text

    def test_format_sync_event_message_confirmed(self) -> None:
        message = format_sync_event_message(
            {
                "type": "confirmed",
                "action": "set hold temp",
                "keys": {"hspHome": 21.0},
            }
        )
        assert message.startswith("[Cloud sync] Confirmed set hold temp")

    def test_pop_sync_log_events(self) -> None:
        thermostat = {"_sync_log_events": [{"type": "confirmed"}]}
        events = pop_sync_log_events(thermostat)
        assert len(events) == 1
        assert "_sync_log_events" not in thermostat
