"""Unit tests for schedule_helpers (pure logic, no Home Assistant runtime)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from daikinskyport.schedule_helpers import (
    MAX_SCHEDULE_SLOT,
    UNIX_EPOCH_SECONDS_THRESHOLD,
    current_schedule_slot,
    find_active_schedule_period_prefix,
    find_next_schedule_transition,
    format_schedule_override_until,
    format_schedule_period_name,
    format_schedule_slot_clock,
    iter_enabled_schedule_periods,
    iter_enabled_schedule_parts,
    next_datetime_for_slot,
    resume_time_from_sched_resume_value,
    safe_format_schedule_override_until,
    schedule_setpoints_for_prefix,
    schedule_slot_to_hour_minute,
    thermostat_has_cooling,
    thermostat_timezone,
)
from tests.helpers import make_monday_schedule_thermostat


class TestScheduleSlotTime:
    """15-minute slot index conversions."""

    @pytest.mark.parametrize(
        ("slot", "hour", "minute"),
        [
            (0, 0, 0),
            (4, 1, 0),
            (26, 6, 30),
            (95, 23, 45),
        ],
    )
    def test_schedule_slot_to_hour_minute(self, slot, hour, minute) -> None:
        assert schedule_slot_to_hour_minute(slot) == (hour, minute)

    def test_invalid_slot_raises(self) -> None:
        with pytest.raises(ValueError):
            schedule_slot_to_hour_minute(96)

    def test_format_schedule_slot_clock(self) -> None:
        assert format_schedule_slot_clock(26) == "6:30 AM"

    def test_format_schedule_period_name_with_label(self) -> None:
        name = format_schedule_period_name("Fri", 26, "wake")
        assert name == 'Friday 6:30 AM "wake"'

    def test_format_schedule_period_name_without_label(self) -> None:
        assert format_schedule_period_name("Mon", 0, "") == "Monday 12:00 AM"


class TestResumeTimeParsing:
    """schedResumeTime as slot vs Unix timestamp (regression for large values)."""

    def test_zero_returns_none(self, tz_eastern: ZoneInfo) -> None:
        now = datetime(2024, 6, 3, 12, 0, tzinfo=tz_eastern)
        assert resume_time_from_sched_resume_value(0, now, tz_eastern) is None

    def test_schedule_slot_same_day(self, tz_eastern: ZoneInfo) -> None:
        now = datetime(2024, 6, 3, 6, 0, tzinfo=tz_eastern)
        end = resume_time_from_sched_resume_value(26, now, tz_eastern)
        assert end == datetime(2024, 6, 3, 6, 30, tzinfo=tz_eastern)

    def test_schedule_slot_next_day(self, tz_eastern: ZoneInfo) -> None:
        now = datetime(2024, 6, 3, 20, 0, tzinfo=tz_eastern)
        end = resume_time_from_sched_resume_value(26, now, tz_eastern)
        assert end == datetime(2024, 6, 4, 6, 30, tzinfo=tz_eastern)

    def test_unix_seconds_not_treated_as_slot(self, tz_eastern: ZoneInfo) -> None:
        """Values above MAX_SCHEDULE_SLOT must not use hour=slot logic."""
        now = datetime(2024, 6, 3, 12, 0, tzinfo=tz_eastern)
        # Would be invalid as slot 444877200; must parse as Unix time.
        bogus_slot = 444_877_200
        assert bogus_slot > MAX_SCHEDULE_SLOT
        assert bogus_slot < UNIX_EPOCH_SECONDS_THRESHOLD
        assert resume_time_from_sched_resume_value(bogus_slot, now, tz_eastern) is None

    def test_unix_seconds_future(self, tz_eastern: ZoneInfo) -> None:
        now = datetime(2024, 6, 3, 12, 0, tzinfo=tz_eastern)
        ts = int(datetime(2024, 6, 3, 21, 0, tzinfo=tz_eastern).timestamp())
        end = resume_time_from_sched_resume_value(ts, now, tz_eastern)
        assert end == datetime(2024, 6, 3, 21, 0, tzinfo=tz_eastern)

    def test_unix_milliseconds(self, tz_eastern: ZoneInfo) -> None:
        now = datetime(2024, 6, 3, 12, 0, tzinfo=tz_eastern)
        target = datetime(2024, 6, 3, 21, 0, tzinfo=tz_eastern)
        ms = int(target.timestamp() * 1000)
        assert ms >= UNIX_EPOCH_SECONDS_THRESHOLD * 1000
        end = resume_time_from_sched_resume_value(ms, now, tz_eastern)
        assert end == target

    def test_past_unix_timestamp_returns_none(self, tz_eastern: ZoneInfo) -> None:
        now = datetime(2024, 6, 3, 12, 0, tzinfo=tz_eastern)
        past = int(datetime(2024, 6, 3, 8, 0, tzinfo=tz_eastern).timestamp())
        assert resume_time_from_sched_resume_value(past, now, tz_eastern) is None


class TestEnabledSchedulePeriods:
    """Iteration and active-period resolution."""

    def test_iter_enabled_schedule_periods(self, monday_schedule_thermostat) -> None:
        periods = list(iter_enabled_schedule_periods(monday_schedule_thermostat))
        assert len(periods) == 2
        assert periods[0].part == 1
        assert periods[0].prefix == "schedMonPart1"
        assert periods[0].display_name == 'Monday 6:30 AM "wake"'

    def test_iter_enabled_schedule_parts_sorted(
        self, monday_schedule_thermostat
    ) -> None:
        slots = iter_enabled_schedule_parts(monday_schedule_thermostat, "Mon")
        assert slots == [26, 40]

    def test_find_active_period_between_parts(
        self, monday_schedule_thermostat, monday_morning_eastern
    ) -> None:
        prefix = find_active_schedule_period_prefix(
            monday_schedule_thermostat, monday_morning_eastern
        )
        assert prefix == "schedMonPart1"

    def test_find_active_period_after_second_start(
        self, monday_schedule_thermostat, tz_eastern
    ) -> None:
        when = datetime(2024, 6, 3, 11, 0, tzinfo=tz_eastern)
        assert current_schedule_slot(when) == 44
        prefix = find_active_schedule_period_prefix(
            monday_schedule_thermostat, when
        )
        assert prefix == "schedMonPart2"

    def test_schedule_setpoints_for_prefix(self, monday_schedule_thermostat) -> None:
        heat, cool = schedule_setpoints_for_prefix(
            monday_schedule_thermostat, "schedMonPart2"
        )
        assert heat == 21.0
        assert cool == 25.0


class TestThermostatCapabilities:
    def test_thermostat_has_cooling_stages(self) -> None:
        assert thermostat_has_cooling({"ctOutdoorNoofCoolStages": 1}) is True

    def test_thermostat_has_cooling_p1p2(self) -> None:
        assert thermostat_has_cooling({"P1P2S21CoolingCapability": True}) is True

    def test_thermostat_no_cooling(self) -> None:
        assert thermostat_has_cooling({}) is False

    def test_thermostat_timezone_fallback(self) -> None:
        assert thermostat_timezone({}) == ZoneInfo("UTC")
        assert thermostat_timezone({"timeZone": "America/Toronto"}) == ZoneInfo(
            "America/Toronto"
        )


class TestScheduleOverrideDisplay:
    """Override-until formatting (entity sensor regression cases)."""

    def test_override_until_unix_resume_time(self, tz_eastern: ZoneInfo) -> None:
        now = datetime(2024, 6, 3, 12, 0, tzinfo=tz_eastern)
        resume_ts = int(datetime(2024, 6, 3, 21, 0, tzinfo=tz_eastern).timestamp())
        thermostat = {
            "timeZone": "America/New_York",
            "schedOverride": 1,
            "schedEnabled": True,
            "schedResumeTime": resume_ts,
        }
        assert format_schedule_override_until(thermostat, now) == "9:00 PM"

    def test_safe_format_never_raises_on_bad_resume(self) -> None:
        thermostat = {
            "timeZone": "America/New_York",
            "schedOverride": 1,
            "schedEnabled": True,
            "schedResumeTime": "not-a-number",
        }
        assert safe_format_schedule_override_until(thermostat) is None

    def test_override_duration_fallback_label(self, tz_eastern: ZoneInfo) -> None:
        """When end time is unknown, show remaining duration from API field."""
        now = datetime(2024, 6, 3, 12, 0, tzinfo=tz_eastern)
        thermostat = {
            "timeZone": "America/New_York",
            "schedOverride": 1,
            "schedEnabled": True,
            "schedOverrideDuration": 90,
        }
        assert format_schedule_override_until(thermostat, now) == "1h 30m"

    def test_override_until_from_started_at(self, tz_eastern: ZoneInfo) -> None:
        now = datetime(2024, 6, 3, 12, 0, tzinfo=tz_eastern)
        thermostat = {
            "timeZone": "America/New_York",
            "schedOverride": 1,
            "schedEnabled": True,
            "schedOverrideDuration": 90,
            "_override_started_at": now.timestamp(),
        }
        assert format_schedule_override_until(thermostat, now) == "1:30 PM"

    def test_not_in_override_returns_none(self) -> None:
        assert (
            format_schedule_override_until({"schedOverride": 0, "schedEnabled": True})
            is None
        )


class TestNextScheduleTransition:
    def test_find_next_transition_later_today(
        self, monday_schedule_thermostat, tz_eastern
    ) -> None:
        now = datetime(2024, 6, 3, 6, 0, tzinfo=tz_eastern)
        nxt = find_next_schedule_transition(monday_schedule_thermostat, now)
        assert nxt == datetime(2024, 6, 3, 6, 30, tzinfo=tz_eastern)

    def test_next_datetime_for_slot(self, tz_eastern: ZoneInfo) -> None:
        now = datetime(2024, 6, 3, 7, 0, tzinfo=tz_eastern)
        assert next_datetime_for_slot(now, 26) == datetime(
            2024, 6, 4, 6, 30, tzinfo=tz_eastern
        )
