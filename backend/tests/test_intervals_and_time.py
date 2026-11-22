from datetime import date, datetime, timedelta

from lifeos.services.intervals import clip, continuous_stretches, gaps, intersect, subtract, total_seconds, union
from lifeos.timeutil import local_day_bounds, parse_iso, week_start


def t(h: int, m: int = 0) -> datetime:
    return datetime(2026, 3, 2, h, m)


def test_union_merges_overlaps_and_touching():
    assert union([(t(9), t(10)), (t(9, 30), t(11)), (t(11), t(12)), (t(13), t(14))]) == [(t(9), t(12)), (t(13), t(14))]


def test_total_seconds_counts_overlap_once():
    assert total_seconds([(t(9), t(10)), (t(9, 30), t(10, 30))]) == 90 * 60


def test_intersect_and_subtract():
    a = [(t(9), t(12))]
    b = [(t(10), t(11)), (t(11, 30), t(13))]
    assert intersect(a, b) == [(t(10), t(11)), (t(11, 30), t(12))]
    assert subtract(a, b) == [(t(9), t(10)), (t(11), t(11, 30))]


def test_clip():
    assert clip((t(8), t(10)), t(9), t(12)) == (t(9), t(10))
    assert clip((t(8), t(9)), t(9), t(12)) is None


def test_continuous_stretches_respect_break_gap():
    ivs = [(t(9), t(10)), (t(10, 3), t(11)), (t(11, 20), t(12))]
    assert continuous_stretches(ivs, timedelta(minutes=5)) == [(t(9), t(11)), (t(11, 20), t(12))]
    assert gaps(ivs, timedelta(minutes=5)) == [(t(11), t(11, 20))]


def test_local_day_bounds_handle_dst():
    # US DST starts 2026-03-08: that local day is 23 hours long.
    lo, hi = local_day_bounds(date(2026, 3, 8), "America/Chicago")
    assert (hi - lo) == timedelta(hours=23)
    assert lo == datetime(2026, 3, 8, 6, 0)


def test_parse_iso_normalises_to_naive_utc():
    assert parse_iso("2026-03-02T09:00:00-06:00") == datetime(2026, 3, 2, 15, 0)
    assert parse_iso("2026-03-02T15:00:00Z") == datetime(2026, 3, 2, 15, 0)
    assert parse_iso("2026-03-02T15:00:00") == datetime(2026, 3, 2, 15, 0)


def test_week_start_is_monday():
    assert week_start(date(2026, 3, 8)) == date(2026, 3, 2)
    assert week_start(date(2026, 3, 2)) == date(2026, 3, 2)
