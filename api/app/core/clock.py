"""The one clock. Every rule reads `clock.now()` (never `datetime.now()` or SQL `now()`), so tests
move time with `clock.set_fake(...)` / `clock.advance(...)`. A rider position's `recorded_at` is
this server time — never the phone's clock (04 §3)."""

import datetime as dt

_fake: dt.datetime | None = None


def now() -> dt.datetime:
    return _fake if _fake is not None else dt.datetime.now(dt.UTC)


def set_fake(at: dt.datetime | None) -> None:
    global _fake
    _fake = at


def advance(seconds: float) -> dt.datetime:
    global _fake
    _fake = now() + dt.timedelta(seconds=seconds)
    return _fake


def ms(at: dt.datetime) -> int:
    return int(at.timestamp() * 1000)


def from_ms(value: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(value / 1000, dt.UTC)
