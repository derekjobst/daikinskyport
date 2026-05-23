"""Test data builders (no Home Assistant imports)."""

SCHEDULE_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def make_monday_schedule_thermostat(
    *,
    part1_slot: int = 26,
    part1_label: str = "wake",
    part2_slot: int = 40,
    part2_label: str = "day",
    part1_hsp: float = 20.0,
    part1_csp: float = 24.0,
    part2_hsp: float = 21.0,
    part2_csp: float = 25.0,
) -> dict:
    """Minimal thermostat dict with two enabled Monday schedule periods."""
    return {
        "timeZone": "America/New_York",
        "ctSystemCapHeat": True,
        "ctOutdoorNoofCoolStages": 1,
        "schedMonPart1Enabled": True,
        "schedMonPart1Time": part1_slot,
        "schedMonPart1Label": part1_label,
        "schedMonPart1hsp": part1_hsp,
        "schedMonPart1csp": part1_csp,
        "schedMonPart2Enabled": True,
        "schedMonPart2Time": part2_slot,
        "schedMonPart2Label": part2_label,
        "schedMonPart2hsp": part2_hsp,
        "schedMonPart2csp": part2_csp,
        **{
            f"sched{day}Part1Enabled": False
            for day in SCHEDULE_DAYS
            if day != "Mon"
        },
    }
