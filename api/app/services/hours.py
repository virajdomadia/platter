"""Opening hours in Bengaluru time. `hours = {"mon": [["11:00", "23:00"]], …}`; a range whose end is
before its start runs past midnight (["18:00", "02:00"]); ["00:00", "24:00"] is all day."""

import datetime as dt
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def is_open_at(hours: dict[str, list[list[str]]], at: dt.datetime) -> bool:
    local = at.astimezone(IST)
    minute = local.hour * 60 + local.minute
    today = DAYS[local.weekday()]
    yesterday = DAYS[(local.weekday() - 1) % 7]
    for start, end in hours.get(today, []):
        s, e = _minutes(start), _minutes(end)
        if (s <= e and s <= minute < e) or (s > e and minute >= s):
            return True
    for start, end in hours.get(yesterday, []):
        s, e = _minutes(start), _minutes(end)
        if s > e and minute < e:
            return True
    return False


def next_opening(hours: dict[str, list[list[str]]], at: dt.datetime) -> str | None:
    """ "Opens at 11:00" / "Opens tomorrow at 11:00" for a closed restaurant, else None."""
    local = at.astimezone(IST)
    minute = local.hour * 60 + local.minute
    for offset in range(8):
        day = DAYS[(local.weekday() + offset) % 7]
        for start, _ in sorted(hours.get(day, []), key=lambda r: _minutes(r[0])):
            if offset == 0 and _minutes(start) <= minute:
                continue
            if offset == 0:
                return f"Opens at {start}"
            if offset == 1:
                return f"Opens tomorrow at {start}"
            return f"Opens {day.capitalize()} at {start}"
    return None


def label(hours: dict[str, list[list[str]]], at: dt.datetime) -> str:
    """Today's hours as one line: "Open 24 hours" / "11:00–23:00"."""
    today = DAYS[at.astimezone(IST).weekday()]
    ranges = hours.get(today, [])
    if not ranges:
        return "Closed today"
    if any(r == ["00:00", "24:00"] for r in ranges):
        return "Open 24 hours"
    return ", ".join(f"{s}–{e}" for s, e in ranges)
