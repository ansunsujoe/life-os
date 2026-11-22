from datetime import date, datetime, timedelta

import pytest

from lifeos.models import ActivityEvent, Device
from lifeos.services.activity import (
    IngestRejected,
    NormalizedEvent,
    category_summary,
    check_device_allowed,
    timeline_blocks,
    upsert_events,
)
from lifeos.services.activitywatch import AWEvent, build_day_events, sync_activitywatch
from lifeos.services.classification import Classifier, RuleSpec, domain_from_url, load_classifier, reclassify_events
from lifeos.timeutil import local_day_bounds


def t(h: int, m: int = 0, s: int = 0) -> datetime:
    return datetime(2026, 3, 2, h, m, s)


# ---- classification ----------------------------------------------------------


def test_default_rules_classify_common_apps(db):
    clf = load_classifier(db)
    assert clf.classify("Code", "main.py", None).category == "software"
    assert clf.classify("Logic Pro", "Song.logicx", None).category == "music"
    c = clf.classify("Google Chrome", "Chart", "tradingview.com")
    assert (c.category, c.confidence) == ("trading", "medium")
    # Weak inference is labelled low confidence.
    assert clf.classify("Safari", "Rust tutorial - part 2", "example.com").confidence == "low"
    assert clf.classify("Finder", None, None).category == "other"


def test_no_default_rule_infers_faith_or_health(db):
    clf = load_classifier(db)
    assert clf.classify("Google Chrome", "Bible Gateway", "biblegateway.com").category not in {"faith", "health"}


def test_invalid_regex_rules_are_skipped():
    clf = Classifier([RuleSpec(1, "app", "regex", "([", "software", "medium"), RuleSpec(2, "app", "contains", "code", "software", "medium")])
    assert clf.classify("Code", None, None).rule_id == 2


def test_domain_from_url():
    assert domain_from_url("https://www.github.com/x/y") == "github.com"
    assert domain_from_url("localhost:3000/page") == "localhost"
    assert domain_from_url(None) is None


# ---- upsert / dedup ----------------------------------------------------------


def _ev(key: str, start: datetime, end: datetime, app: str = "Code", **kw) -> NormalizedEvent:
    return NormalizedEvent(source_key=key, source="activitywatch", device_id="personal-mac", start_time=start, end_time=end, app=app, **kw)


def test_upsert_is_idempotent_and_preserves_corrections(db):
    r1 = upsert_events(db, [_ev("k1", t(15), t(16)), _ev("k1", t(15), t(16))])
    assert (r1.added, r1.skipped) == (1, 1)
    ev = db.query(ActivityEvent).one()
    ev.category_override = "learning"
    ev.excluded = True
    db.commit()
    r2 = upsert_events(db, [_ev("k1", t(15), t(16, 30))])
    assert r2.updated == 1
    ev = db.query(ActivityEvent).one()
    assert ev.end_time == t(16, 30)
    assert ev.category_override == "learning" and ev.excluded
    assert ev.effective_category == "learning" and ev.effective_confidence == "high"


def test_work_device_titles_never_stored(db):
    db.add(Device(id="work-mac", name="Work", is_work=True, monitoring_approved=True, store_titles=True))
    db.commit()
    upsert_events(db, [NormalizedEvent("w1", "activity_json", t(15), t(16), device_id="work-mac", app="Code", title="secret.py")])
    assert db.query(ActivityEvent).filter_by(source_key="w1").one().title is None


def test_unapproved_work_device_only_accepts_aggregates():
    dev = Device(id="work-win", name="Work Win", is_work=True, monitoring_approved=False, collection_enabled=True)
    with pytest.raises(IngestRejected):
        check_device_allowed(dev, aggregate=False)
    check_device_allowed(dev, aggregate=True)
    with pytest.raises(IngestRejected):
        check_device_allowed(None)


def test_reclassify_respects_overrides(db):
    upsert_events(db, [_ev("a", t(15), t(16), app="Notion"), _ev("b", t(16), t(17), app="Notion")])
    a = db.query(ActivityEvent).filter_by(source_key="a").one()
    a.category_override = "music"
    db.commit()
    from lifeos.models import ClassificationRule

    db.add(ClassificationRule(field="app", match_type="equals", pattern="notion", category_key="learning", priority=1))
    db.commit()
    assert reclassify_events(db) == 2  # rule-level classification updated for both...
    rows = {e.source_key: e for e in db.query(ActivityEvent)}
    assert rows["a"].effective_category == "music"  # ...but the user's override still wins
    assert rows["b"].effective_category == "learning"


# ---- aggregation ---------------------------------------------------------------


def test_category_summary_counts_overlaps_once_and_tracks_confidence(db):
    upsert_events(db, [
        _ev("1", t(15), t(16)),
        _ev("2", t(15, 30), t(16, 30), app="Terminal"),
        NormalizedEvent("3", "manual", t(17), t(18), category="health", confidence="high", activity="Run"),
    ])
    evs = db.query(ActivityEvent).all()
    s = category_summary(evs, t(0), t(23))
    assert s["categories"]["software"]["seconds"] == 90 * 60
    assert s["categories"]["software"]["by_confidence"] == {"medium": 90 * 60}
    assert s["categories"]["health"]["seconds"] == 3600
    assert s["active_computer_seconds"] == 90 * 60  # manual health event isn't screen time


def test_timeline_blocks_merge_same_category_with_small_gaps(db):
    upsert_events(db, [
        _ev("1", t(15), t(15, 10)),
        _ev("2", t(15, 11), t(15, 20), app="Terminal"),
        _ev("3", t(15, 21), t(15, 30), app="Logic Pro"),
        _ev("4", t(15, 50), t(16), app="Code"),
    ])
    blocks = timeline_blocks(db.query(ActivityEvent).all(), t(0), t(23), timedelta(minutes=5))
    assert [(b.category, b.start, b.end) for b in blocks] == [
        ("software", t(15), t(15, 20)),
        ("music", t(15, 21), t(15, 30)),
        ("software", t(15, 50), t(16)),
    ]
    assert blocks[0].seconds == 19 * 60


# ---- ActivityWatch -------------------------------------------------------------


def test_build_day_events_filters_afk_and_attaches_domain():
    day = date(2026, 3, 2)
    bounds = local_day_bounds(day, "America/Chicago")  # 06:00Z → next 06:00Z
    win = [
        AWEvent(1, t(15), t(16), {"app": "Google Chrome", "title": "Repo"}),
        AWEvent(2, t(5), t(6, 30), {"app": "Code", "title": "x"}),  # straddles local midnight
    ]
    afk = [AWEvent(10, t(5), t(15, 20), {"status": "not-afk"}), AWEvent(11, t(15, 20), t(15, 40), {"status": "afk"}), AWEvent(12, t(15, 40), t(17), {"status": "not-afk"})]
    web = [AWEvent(20, t(15), t(16), {"url": "https://github.com/a/b", "title": "Repo"})]
    out = build_day_events(bucket_id="aw-watcher-window_mac", device_id="personal-mac", day=day, day_bounds=bounds,
                           window_events=win, afk_events=afk, web_events=web, store_full_urls=False)
    spans = sorted((e.start_time, e.end_time, e.domain) for e in out)
    assert spans == [(t(6), t(6, 30), None), (t(15), t(15, 20), "github.com"), (t(15, 40), t(16), "github.com")]
    assert all("url" not in e.evidence for e in out)


def test_incognito_tabs_keep_no_details():
    day = date(2026, 3, 2)
    out = build_day_events(bucket_id="b", device_id="d", day=day, day_bounds=(t(0), t(23)),
                           window_events=[AWEvent(1, t(15), t(16), {"app": "Firefox", "title": "Private"})], afk_events=None,
                           web_events=[AWEvent(2, t(15), t(16), {"url": "https://x.com", "incognito": True})], store_full_urls=True)
    assert out[0].domain is None and out[0].title is None and out[0].evidence.get("incognito")


class FakeAW:
    def __init__(self, hostname="personal-mac"):
        self.hostname = hostname
        self.window = [AWEvent(1, t(15), t(15, 30), {"app": "Code", "title": "a"}), AWEvent(2, t(15, 30), t(16), {"app": "Logic Pro", "title": "b"})]

    def buckets(self):
        return {
            f"aw-watcher-window_{self.hostname}": {"type": "currentwindow", "hostname": self.hostname},
            f"aw-watcher-afk_{self.hostname}": {"type": "afkstatus", "hostname": self.hostname},
            "aw-watcher-window_work-laptop": {"type": "currentwindow", "hostname": "work-laptop"},
        }

    def events(self, bucket_id, start, end):
        if "afk" in bucket_id:
            return [AWEvent(9, t(14), t(17), {"status": "not-afk"})]
        return [e for e in self.window if e.end > start and e.start < end] if "work" not in bucket_id else [AWEvent(1, t(15), t(16), {"app": "Outlook"})]

    def close(self):
        pass


def test_sync_is_idempotent_carries_corrections_and_quarantines_unknown_hosts(db):
    days = [date(2026, 3, 2)]
    r = sync_activitywatch(db, client=FakeAW(), days=days)
    assert r["status"] == "ok" and r["added"] == 2
    assert "work-laptop" in r["skipped_devices"]
    work = db.get(Device, "work-laptop")
    assert work and not work.collection_enabled and work.is_work  # registered but disabled

    ev = db.query(ActivityEvent).filter_by(app="Code").one()
    ev.category_override = "learning"
    db.commit()

    fake = FakeAW()
    fake.window[1] = AWEvent(2, t(15, 30), t(16, 15), {"app": "Logic Pro", "title": "b"})  # heartbeat extended
    r2 = sync_activitywatch(db, client=fake, days=days)
    assert r2["added"] == 0 and r2["updated"] == 1
    assert db.query(ActivityEvent).count() == 2
    assert db.query(ActivityEvent).filter_by(app="Code").one().category_override == "learning"


def test_sync_respects_global_pause(db):
    from lifeos.services.settings import update_settings

    update_settings(db, {"privacy": {"collection_paused": True}})
    assert sync_activitywatch(db, client=FakeAW(), days=[date(2026, 3, 2)])["status"] == "paused"
    assert db.query(ActivityEvent).count() == 0
