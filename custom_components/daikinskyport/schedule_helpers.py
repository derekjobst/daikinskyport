"""Schedule and schedule-override time helpers for Daikin Skyport."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from .thermostat_helpers import thermostat_has_cooling

SCHEDULE_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DAY_DISPLAY_NAMES = {
    "Mon": "Monday",
    "Tue": "Tuesday",
    "Wed": "Wednesday",
    "Thu": "Thursday",
    "Fri": "Friday",
    "Sat": "Saturday",
    "Sun": "Sunday",
}
# API: schedule part Time is 15-minute steps from midnight (4 per hour).
SLOTS_PER_HOUR = 4
SCHEDULE_PARTS = range(1, 7)
# One day of schedule slots (00:00 through 23:45).
MAX_SCHEDULE_SLOT = 24 * SLOTS_PER_HOUR - 1
# Values at or above this are treated as Unix time, not schedule slots.
UNIX_EPOCH_SECONDS_THRESHOLD = 1_000_000_000


def schedule_slot_to_hour_minute(slot: int) -> tuple[int, int]:
    """Convert a Daikin schedule time slot to hour and minute."""
    slot = int(slot)
    hour = slot // SLOTS_PER_HOUR
    minute = (slot % SLOTS_PER_HOUR) * 15
    if hour > 23 or minute > 59:
        raise ValueError(f"invalid schedule slot {slot}")
    return hour, minute


def format_time_friendly(when: datetime) -> str:
    """Format a datetime as e.g. 9:00 PM."""
    return when.strftime("%I:%M %p").lstrip("0")


def format_schedule_slot_clock(time_slot: int) -> str:
    """Format a schedule Time slot as a clock label."""
    try:
        hour, minute = schedule_slot_to_hour_minute(time_slot)
    except ValueError:
        return "Unknown time"
    return format_time_friendly(datetime(2000, 1, 1, hour, minute))


def format_schedule_period_name(day_code: str, time_slot: int, label: str) -> str:
    """Build a display name such as Friday 6:00 AM \"Daytime\"."""
    day = DAY_DISPLAY_NAMES.get(day_code, day_code)
    clock = format_schedule_slot_clock(time_slot)
    clean_label = (label or "").strip()
    if clean_label:
        return f'{day} {clock} "{clean_label}"'
    return f"{day} {clock}"


@dataclass(frozen=True)
class SchedulePeriod:
    """One enabled sched{Day}Part{n} row from the API."""

    day_code: str
    part: int
    prefix: str
    time_slot: int
    label: str
    display_name: str


def iter_enabled_schedule_periods(
    thermostat: dict[str, Any],
) -> Iterator[SchedulePeriod]:
    """Yield each enabled schedule period with a human-readable name."""
    for day_code in SCHEDULE_DAYS:
        for part in SCHEDULE_PARTS:
            prefix = f"sched{day_code}Part{part}"
            enabled_key = f"{prefix}Enabled"
            if enabled_key not in thermostat or not thermostat.get(enabled_key):
                continue
            try:
                time_slot = int(thermostat.get(f"{prefix}Time", 0))
            except (TypeError, ValueError):
                time_slot = 0
            raw_label = thermostat.get(f"{prefix}Label", "")
            label = raw_label.strip() if isinstance(raw_label, str) else str(raw_label)
            yield SchedulePeriod(
                day_code=day_code,
                part=part,
                prefix=prefix,
                time_slot=time_slot,
                label=label,
                display_name=format_schedule_period_name(
                    day_code, time_slot, label
                ),
            )


def thermostat_timezone(thermostat: dict[str, Any]) -> ZoneInfo:
    """Return the thermostat timezone, falling back to UTC."""
    tz_name = thermostat.get("timeZone") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def current_schedule_slot(when: datetime) -> int:
    """Return the schedule slot index for a local datetime."""
    return when.hour * SLOTS_PER_HOUR + when.minute // 15


def slot_to_datetime(on_date: date, slot: int, tz: ZoneInfo) -> datetime | None:
    """Build a timezone-aware datetime for a schedule slot on a given date."""
    try:
        hour, minute = schedule_slot_to_hour_minute(slot)
    except ValueError:
        return None
    return datetime(
        on_date.year,
        on_date.month,
        on_date.day,
        hour,
        minute,
        tzinfo=tz,
    )


def resume_time_from_sched_resume_value(
    resume_value: int, now_local: datetime, tz: ZoneInfo
) -> datetime | None:
    """Parse schedResumeTime as either a schedule slot or Unix resume timestamp."""
    if resume_value <= 0:
        return None
    if resume_value <= MAX_SCHEDULE_SLOT:
        return next_datetime_for_slot(now_local, resume_value)
    if resume_value >= UNIX_EPOCH_SECONDS_THRESHOLD:
        seconds = resume_value
        if resume_value >= UNIX_EPOCH_SECONDS_THRESHOLD * 1000:
            seconds = resume_value // 1000
        try:
            end = datetime.fromtimestamp(seconds, tz=tz)
        except (OSError, OverflowError, ValueError):
            return None
        if end > now_local:
            return end
    return None


def next_datetime_for_slot(now_local: datetime, slot: int) -> datetime | None:
    """Return the next occurrence of a schedule slot at or after now."""
    tz = now_local.tzinfo
    candidate = slot_to_datetime(now_local.date(), slot, tz)
    if candidate is None:
        return None
    if candidate > now_local:
        return candidate
    return slot_to_datetime(now_local.date() + timedelta(days=1), slot, tz)


def iter_enabled_schedule_parts(
    thermostat: dict[str, Any], day_name: str
) -> list[int]:
    """Return enabled schedule part time slots for a weekday, sorted."""
    return [
        time_slot
        for time_slot, _prefix in _sorted_enabled_periods_for_day(
            thermostat, day_name
        )
    ]


def _sorted_enabled_periods_for_day(
    thermostat: dict[str, Any], day_code: str
) -> list[tuple[int, str]]:
    """Return (time_slot, prefix) for enabled schedule parts on a weekday."""
    periods: list[tuple[int, str]] = []
    for part in SCHEDULE_PARTS:
        prefix = f"sched{day_code}Part{part}"
        enabled_key = f"{prefix}Enabled"
        time_key = f"{prefix}Time"
        if enabled_key not in thermostat or time_key not in thermostat:
            continue
        if not thermostat.get(enabled_key):
            continue
        try:
            time_slot = int(thermostat[time_key])
        except (TypeError, ValueError):
            time_slot = 0
        periods.append((time_slot, prefix))
    return sorted(periods, key=lambda item: item[0])


def find_active_schedule_period_prefix(
    thermostat: dict[str, Any], when: datetime
) -> str | None:
    """Return the sched{Day}Part{n} prefix active at a local datetime."""
    tz = thermostat_timezone(thermostat)
    when_local = when.astimezone(tz)
    slot = current_schedule_slot(when_local)

    for day_offset in range(7):
        on_date = when_local.date() - timedelta(days=day_offset)
        day_code = SCHEDULE_DAYS[on_date.weekday()]
        periods = _sorted_enabled_periods_for_day(thermostat, day_code)
        if not periods:
            continue
        if day_offset == 0:
            matching = [prefix for time_slot, prefix in periods if time_slot <= slot]
            if matching:
                return matching[-1]
            continue
        return periods[-1][1]
    return None


def schedule_setpoints_for_prefix(
    thermostat: dict[str, Any], prefix: str
) -> tuple[float | None, float | None]:
    """Return heat/cool setpoints (°C) for a schedule period prefix."""
    heat = cool = None
    try:
        raw_heat = thermostat.get(f"{prefix}hsp")
        if raw_heat is not None:
            heat = float(raw_heat)
    except (TypeError, ValueError):
        heat = None
    try:
        raw_cool = thermostat.get(f"{prefix}csp")
        if raw_cool is not None:
            cool = float(raw_cool)
    except (TypeError, ValueError):
        cool = None
    return heat, cool


def resolve_next_scheduled_setpoints(
    thermostat: dict[str, Any], now: datetime | None = None
) -> tuple[float | None, float | None] | None:
    """Return setpoints that apply when the active schedule override ends."""
    if thermostat.get("schedOverride") != 1:
        return None
    if not thermostat.get("schedEnabled", True):
        return None

    tz = thermostat_timezone(thermostat)
    now_local = datetime.now(tz) if now is None else now.astimezone(tz)

    when = resolve_schedule_override_end(thermostat, now_local)
    if when is None:
        when = find_next_schedule_transition(thermostat, now_local)
    if when is None:
        return None

    prefix = find_active_schedule_period_prefix(thermostat, when)
    if prefix:
        return schedule_setpoints_for_prefix(thermostat, prefix)

    heat = cool = None
    try:
        if thermostat.get("hspSched") is not None:
            heat = float(thermostat["hspSched"])
    except (TypeError, ValueError):
        pass
    try:
        if thermostat.get("cspSched") is not None:
            cool = float(thermostat["cspSched"])
    except (TypeError, ValueError):
        pass
    if heat is None and cool is None:
        return None
    return heat, cool


def format_scheduled_setpoints_display(
    thermostat: dict[str, Any],
    heat: float | None,
    cool: float | None,
    *,
    hass: Any | None = None,
) -> str | None:
    """Format heat/cool schedule setpoints for entity state or attributes."""
    if heat is None and cool is None:
        return None

    from .logbook_helpers import format_temp_dual, format_temperature

    def _fmt(value: float) -> str:
        if hass is not None:
            return format_temperature(hass, value)
        return format_temp_dual(value)

    has_heat = bool(thermostat.get("ctSystemCapHeat"))
    has_cool = thermostat_has_cooling(thermostat)

    if has_heat and has_cool and heat is not None and cool is not None:
        return f"heat {_fmt(heat)} / cool {_fmt(cool)}"
    if has_heat and heat is not None:
        return _fmt(heat)
    if has_cool and cool is not None:
        return _fmt(cool)
    if heat is not None:
        return _fmt(heat)
    if cool is not None:
        return _fmt(cool)
    return None


def format_next_scheduled_temperature(
    thermostat: dict[str, Any],
    now: datetime | None = None,
    *,
    hass: Any | None = None,
) -> str | None:
    """Compact next scheduled temps while a schedule override is active."""
    if thermostat.get("schedOverride") != 1 or not thermostat.get("schedEnabled", True):
        return None
    setpoints = resolve_next_scheduled_setpoints(thermostat, now)
    if not setpoints:
        return None
    return format_scheduled_setpoints_display(
        thermostat, setpoints[0], setpoints[1], hass=hass
    )


def safe_format_next_scheduled_temperature(
    thermostat: dict[str, Any],
    now: datetime | None = None,
    *,
    hass: Any | None = None,
) -> str | None:
    """Like format_next_scheduled_temperature but never raises (entity setup safe)."""
    try:
        return format_next_scheduled_temperature(thermostat, now, hass=hass)
    except (ValueError, OSError, OverflowError, TypeError):
        return None


def find_next_schedule_transition(
    thermostat: dict[str, Any], now: datetime | None = None
) -> datetime | None:
    """Find when the next enabled schedule period starts (hold-until-next-period)."""
    tz = thermostat_timezone(thermostat)
    now_local = datetime.now(tz) if now is None else now.astimezone(tz)
    today_slot = current_schedule_slot(now_local)

    for day_offset in range(7):
        on_date = now_local.date() + timedelta(days=day_offset)
        day_name = SCHEDULE_DAYS[(now_local.weekday() + day_offset) % 7]
        for slot in iter_enabled_schedule_parts(thermostat, day_name):
            if day_offset == 0 and slot <= today_slot:
                continue
            when = slot_to_datetime(on_date, slot, tz)
            if when is not None:
                return when
    return None


def resolve_schedule_override_end(
    thermostat: dict[str, Any], now: datetime | None = None
) -> datetime | None:
    """Return when the active schedule override ends, if known."""
    if thermostat.get("schedOverride") != 1:
        return None
    if not thermostat.get("schedEnabled", True):
        return None

    tz = thermostat_timezone(thermostat)
    now_local = datetime.now(tz) if now is None else now.astimezone(tz)

    resume_value = thermostat.get("schedResumeTime") or 0
    try:
        resume_value = int(resume_value)
    except (TypeError, ValueError):
        resume_value = 0
    if resume_value > 0:
        end = resume_time_from_sched_resume_value(resume_value, now_local, tz)
        if end is not None:
            return end

    duration = thermostat.get("schedOverrideDuration") or 0
    try:
        duration = int(duration)
    except (TypeError, ValueError):
        duration = 0

    if duration == 0:
        return find_next_schedule_transition(thermostat, now_local)

    started = thermostat.get("_override_started_at")
    if started:
        try:
            end = datetime.fromtimestamp(float(started) + duration * 60, tz=tz)
            if end > now_local:
                return end
        except (TypeError, ValueError, OSError):
            pass

    return None


def format_schedule_override_until(
    thermostat: dict[str, Any], now: datetime | None = None
) -> str | None:
    """Compact override end for display (entity/attr name carries context)."""
    if thermostat.get("schedOverride") != 1 or not thermostat.get("schedEnabled", True):
        return None

    try:
        end = resolve_schedule_override_end(thermostat, now)
        if end is not None:
            return format_time_friendly(end)

        duration = thermostat.get("schedOverrideDuration") or 0
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = 0
        if duration > 0:
            hours, minutes = divmod(duration, 60)
            if hours and minutes:
                return f"{hours}h {minutes}m"
            if hours:
                return f"{hours}h"
            return f"{minutes}m"

        tz = thermostat_timezone(thermostat)
        now_local = datetime.now(tz) if now is None else now.astimezone(tz)
        next_transition = find_next_schedule_transition(thermostat, now_local)
        if next_transition is not None:
            return format_time_friendly(next_transition)
    except (ValueError, OSError, OverflowError, TypeError):
        return None
    return None


def safe_format_schedule_override_until(
    thermostat: dict[str, Any], now: datetime | None = None
) -> str | None:
    """Like format_schedule_override_until but never raises (entity setup safe)."""
    try:
        return format_schedule_override_until(thermostat, now)
    except (ValueError, OSError, OverflowError, TypeError):
        return None
