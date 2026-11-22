"""Pure interval arithmetic used for time aggregation.

Intervals are (start, end) tuples of naive-UTC datetimes with start <= end.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

Interval = tuple[datetime, datetime]


def clip(iv: Interval, lo: datetime, hi: datetime) -> Interval | None:
    s, e = max(iv[0], lo), min(iv[1], hi)
    return (s, e) if s < e else None


def union(intervals: Iterable[Interval]) -> list[Interval]:
    """Merge overlapping/touching intervals."""
    out: list[Interval] = []
    for s, e in sorted(i for i in intervals if i[0] < i[1]):
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return out


def total_seconds(intervals: Iterable[Interval]) -> float:
    """Total covered time — overlaps are counted once."""
    return sum((e - s).total_seconds() for s, e in union(intervals))


def intersect(a: Sequence[Interval], b: Sequence[Interval]) -> list[Interval]:
    """Intersection of two interval sets (each is unioned first)."""
    a, b = union(a), union(b)
    out: list[Interval] = []
    i = j = 0
    while i < len(a) and j < len(b):
        s, e = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if s < e:
            out.append((s, e))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def subtract(a: Sequence[Interval], b: Sequence[Interval]) -> list[Interval]:
    """Parts of `a` not covered by `b`."""
    out: list[Interval] = []
    b = union(b)
    for s, e in union(a):
        cur = s
        for bs, be in b:
            if be <= cur or bs >= e:
                continue
            if bs > cur:
                out.append((cur, bs))
            cur = max(cur, be)
            if cur >= e:
                break
        if cur < e:
            out.append((cur, e))
    return out


def gaps(intervals: Sequence[Interval], min_gap: timedelta) -> list[Interval]:
    """Gaps of at least `min_gap` between consecutive merged intervals."""
    u = union(intervals)
    return [(u[i][1], u[i + 1][0]) for i in range(len(u) - 1) if u[i + 1][0] - u[i][1] >= min_gap]


def continuous_stretches(intervals: Sequence[Interval], break_gap: timedelta) -> list[Interval]:
    """Group activity into stretches separated by breaks of at least `break_gap`."""
    out: list[Interval] = []
    for s, e in union(intervals):
        if out and s - out[-1][1] < break_gap:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out
