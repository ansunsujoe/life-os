"""Time helpers.

Convention: every datetime stored in SQLite is *naive UTC*. Conversion to the
user's timezone happens only at the edges (day boundaries, display).
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc_naive(dt: datetime) -> datetime:
    """Normalise any datetime to naive UTC. Naive input is assumed to be UTC."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


def parse_iso(value: str) -> datetime:
    """Parse ISO-8601 (including trailing 'Z') into naive UTC."""
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    return to_utc_naive(datetime.fromisoformat(v))


def detect_system_timezone() -> str:
    tz = os.environ.get("TZ")
    if tz:
        return tz
    try:
        target = Path("/etc/localtime").resolve()
        parts = target.parts
        if "zoneinfo" in parts:
            return "/".join(parts[parts.index("zoneinfo") + 1 :])
    except OSError:
        pass
    return "UTC"


def get_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_day_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    """Return [start, end) of a local calendar day as naive UTC datetimes."""
    tz = get_zone(tz_name)
    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return to_utc_naive(start_local), to_utc_naive(end_local)


def local_range_bounds(first: date, last: date, tz_name: str) -> tuple[datetime, datetime]:
    """[start of `first`, end of `last`) as naive UTC."""
    return local_day_bounds(first, tz_name)[0], local_day_bounds(last, tz_name)[1]


def local_today(tz_name: str) -> date:
    return datetime.now(get_zone(tz_name)).date()


def to_local(dt: datetime, tz_name: str) -> datetime:
    return dt.replace(tzinfo=UTC).astimezone(get_zone(tz_name))


def week_start(day: date) -> date:
    """Monday of the ISO week containing `day`."""
    return day - timedelta(days=day.weekday())


def iso_utc(dt: datetime | None) -> str | None:
    """Serialise naive-UTC datetime as an explicit UTC ISO string."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
