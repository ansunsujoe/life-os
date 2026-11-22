"""Specific activity understanding: titles → domain/topic, drift runs, episodes."""

from datetime import date, datetime, timedelta

from sqlalchemy import text

from lifeos.models import ActivityEvent
from lifeos.services.activity import NormalizedEvent, category_summary, upsert_events
from lifeos.services.activitywatch import AWEvent, build_day_events
from lifeos.services.classification import (
    clean_title,
    extract_project,
    infer_domain_from_title,
    load_classifier,
    normalize_app,
    url_kind,
)
from lifeos.services.orchestrator import build_candidates
from lifeos.services.patterns import apply_patterns, build_episodes, recent_drift
from lifeos.services.recovery import RecoveryAssessment
from lifeos.services.settings import DEFAULT_SETTINGS
from lifeos.services.scoring import intentionality_dimension

T0 = datetime(2026, 3, 2, 15, 0)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


# ---- titles & apps (from real ActivityWatch data) ---------------------------------


def test_real_world_titles_and_apps():
    assert normalize_app("‎WhatsApp") == "WhatsApp"
    assert clean_title("(3) Oscar for Best Dramatic Performance goes to… 🏆🐶🤣 - YouTube").startswith("Oscar")
    assert infer_domain_from_title("(3) \"My Heart can't\" part is Insane - YouTube") == "youtube.com"
    assert infer_domain_from_title("youtube.com/watch?is=WXK&v=UaKKTvOA2T0&feature=youtu.be -") == "youtube.com"
    assert infer_domain_from_title("Pull request #12 · GitHub") == "github.com"
    assert infer_domain_from_title("Home / X") == "x.com"
    assert infer_domain_from_title("Some random page") is None


def test_url_kind():
    assert url_kind("https://www.youtube.com/shorts/abc", "youtube.com") == "shorts"
    assert url_kind("https://www.youtube.com/watch?v=abc", "youtube.com") == "watch"
    assert url_kind("https://www.youtube.com/", "youtube.com") == "feed"
    assert url_kind("https://www.youtube.com/results?search_query=x", "youtube.com") == "search"
    assert url_kind("YouTube", "youtube.com") == "feed"
    assert url_kind("https://www.reddit.com/r/python/comments/1/x", "reddit.com") == "post"


def test_project_hints():
    assert extract_project("Code", "Continue previous session — life-os") == "life-os"
    assert extract_project("Code", "orchestrator.py — life-os [SSH: box]") == "life-os"
    assert extract_project("Terminal", "ansun@mac: ~/projects/life-os") == "life-os"
    assert extract_project("Google Chrome", "x — y") is None


def test_video_titles_decide_category(db):
    clf = load_classifier(db)
    c = clf.classify("Google Chrome", "Learn FastAPI in 30 minutes - YouTube", None)
    assert (c.category, c.subcategory, c.confidence) == ("software", "Tech video / thread", "low")
    assert clf.classify("Google Chrome", "Orchestration tips for strings - YouTube", None).category == "music"
    assert clf.classify("Google Chrome", "Options trading for beginners - YouTube", None).category == "trading"
    funny = clf.classify("Google Chrome", "(3) Oscar for Best Dramatic Performance goes to… 🏆🐶🤣 - YouTube", None)
    assert (funny.category, funny.subcategory) == ("leisure", "Watching videos")
    assert clf.classify("Google Chrome", "x", "youtube.com", "shorts").category == "drift"
    assert clf.classify("Google Chrome", "Home / X", None).category == "drift"
    assert clf.classify("WhatsApp", "", None).subcategory == "Messaging & people"
    assert clf.classify("Code", "main.py — life-os", None).subcategory == "Coding"


def test_user_rules_still_win_over_media_step(db):
    from lifeos.models import ClassificationRule

    db.add(ClassificationRule(name="My channel", field="title", match_type="contains", pattern="Oscar", category_key="recovery", priority=1))
    db.commit()
    assert load_classifier(db).classify("Google Chrome", "Oscar for Best - YouTube", None).category == "recovery"


def test_lock_screen_is_not_activity():
    out = build_day_events(bucket_id="b", device_id="d", day=date(2026, 3, 2), day_bounds=(at(-60), at(600)),
                           window_events=[AWEvent(1, at(0), at(15), {"app": "loginwindow", "title": "loginwindow"}),
                                          AWEvent(2, at(15), at(20), {"app": "Code", "title": "a — life-os"})],
                           afk_events=None, web_events=[], store_full_urls=False)
    assert [e.app for e in out] == ["Code"]


# ---- drift detection ---------------------------------------------------------------


def _yt(key: str, start: float, minutes: float, title: str):
    return NormalizedEvent(key, "activitywatch", at(start), at(start + minutes), device_id="personal-mac", app="Google Chrome", title=f"{title} - YouTube")


def test_rapid_hopping_becomes_drift_but_one_long_video_stays_leisure(db):
    hops = [_yt(f"h{i}", i * 1.2, 1.1, f"Funny clip {i}") for i in range(8)]  # ~9.5 min, 8 clips
    long = [_yt("long", 60, 25, "Full concert recording")]
    upsert_events(db, hops + long)
    apply_patterns(db, at(-10), at(120))
    rows = {e.source_key: e for e in db.query(ActivityEvent)}
    assert all(rows[f"h{i}"].effective_category == "drift" for i in range(8))
    assert all(rows[f"h{i}"].category_key == "leisure" for i in range(8))  # rule result kept for transparency
    assert rows["long"].effective_category == "leisure"


def test_brief_hopping_below_threshold_is_not_drift(db):
    upsert_events(db, [_yt(f"h{i}", i, 0.9, f"clip {i}") for i in range(3)])
    apply_patterns(db, at(-10), at(60))
    assert {e.effective_category for e in db.query(ActivityEvent)} == {"leisure"}


def test_user_correction_beats_pattern(db):
    upsert_events(db, [_yt(f"h{i}", i * 1.2, 1.1, f"clip {i}") for i in range(8)])
    e = db.query(ActivityEvent).filter_by(source_key="h0").one()
    e.category_override = "leisure"
    db.commit()
    apply_patterns(db, at(-10), at(60))
    assert db.query(ActivityEvent).filter_by(source_key="h0").one().effective_category == "leisure"


def test_drift_counts_against_intentionality_but_chosen_leisure_does_not(db):
    upsert_events(db, [_yt(f"h{i}", i * 1.2, 1.1, f"clip {i}") for i in range(8)]
                  + [NormalizedEvent("code", "activitywatch", at(20), at(50), device_id="personal-mac", app="Code", title="a — life-os")])
    apply_patterns(db, at(-10), at(120))
    evs = db.query(ActivityEvent).all()
    with_drift = intentionality_dimension(evs, at(-10), at(120), set(), 0.1).score
    for e in evs:
        if e.effective_category == "drift":
            e.category_override = "leisure"  # "that was an intentional break"
    db.commit()
    assert intentionality_dimension(db.query(ActivityEvent).all(), at(-10), at(120), set(), 0.1).score > with_drift


def test_subcategory_totals(db):
    upsert_events(db, [NormalizedEvent("c", "activitywatch", at(0), at(30), device_id="personal-mac", app="Code", title="x — life-os"),
                       NormalizedEvent("t", "activitywatch", at(30), at(40), device_id="personal-mac", app="Terminal", title="claude")])
    s = category_summary(db.query(ActivityEvent).all(), at(-1), at(60))
    assert s["categories"]["software"]["by_subcategory"] == {"Coding": 1800, "Terminal / Claude Code": 600}


# ---- episodes --------------------------------------------------------------------------


def _ep(db):
    return build_episodes(db.query(ActivityEvent).all(), at(-60), at(600), break_gap=timedelta(minutes=5), detour_max=timedelta(minutes=3),
                          names={"software": "Software development"}, productive={"software", "music", "learning", "trading"})


def test_episode_absorbs_short_detours_and_names_project(db):
    upsert_events(db, [
        NormalizedEvent("c1", "activitywatch", at(0), at(20), device_id="personal-mac", app="Code", title="a.py — life-os"),
        _yt("d1", 20, 1.5, "cat video"),
        NormalizedEvent("w", "activitywatch", at(21.5), at(22.5), device_id="personal-mac", app="‎WhatsApp", title=""),
        NormalizedEvent("c2", "activitywatch", at(22.5), at(50), device_id="personal-mac", app="Code", title="b.py — life-os"),
    ])
    eps = _ep(db)
    assert len(eps) == 1
    ep = eps[0]
    assert ep.category == "software" and ep.kind == "focus" and ep.projects == ["life-os"]
    assert {d["label"] for d in ep.detours} == {"youtube.com", "WhatsApp"}
    assert "2 detours" in ep.summary and "life-os" in ep.summary


def test_long_switch_starts_new_episode_and_takes_its_lead_in(db):
    upsert_events(db, [
        NormalizedEvent("c1", "activitywatch", at(0), at(30), device_id="personal-mac", app="Code", title="a — life-os"),
        _yt("y0", 30, 1, "first clip"),
        *[_yt(f"y{i}", 31 + (i - 1) * 1.1, 1.0, f"clip {i}") for i in range(1, 12)],
    ])
    apply_patterns(db, at(-10), at(120))
    eps = _ep(db)
    assert [e.kind for e in eps] == ["focus", "drift"]
    assert eps[1].start == at(30)  # the 1-minute lead-in clip belongs to the drift episode
    assert eps[1].summary.startswith("Hopped through 12 items")


def test_idle_gap_splits_episodes(db):
    upsert_events(db, [
        NormalizedEvent("a", "activitywatch", at(0), at(20), device_id="personal-mac", app="Code", title="x — p"),
        NormalizedEvent("b", "activitywatch", at(40), at(60), device_id="personal-mac", app="Code", title="x — p"),
    ])
    assert len(_ep(db)) == 2


# ---- live nudge ---------------------------------------------------------------------------


def test_live_drift_nudge(db):
    upsert_events(db, [_yt(f"h{i}", i * 1.2, 1.1, f"clip {i}") for i in range(12)])
    apply_patterns(db, at(-10), at(60))
    d = recent_drift(db, at(14.5))
    assert d and d["seconds"] >= 10 * 60 and d["sources"] == ["youtube.com"]
    cands = build_candidates(now=at(14.5), today=date(2026, 3, 2), local_hour=15, sessions=[], tasks=[], stalled=[],
                             recovery=RecoveryAssessment("none", None, None, [], {}), energy=None, goal_progress=[], weekday=0,
                             trading_today=False, trading_note_today=False, review_done=True, current_category="drift",
                             settings=DEFAULT_SETTINGS, drift=d, resume_hint="Coding on life-os")
    top = max(cands, key=lambda c: c.score)
    assert top.kind == "drift" and "Coding on life-os" in top.reason and "no judgement" in top.reason
    assert top.event_ids
    assert recent_drift(db, at(40)) is None  # not nudged once they've moved on


# ---- migration & seed upgrade on an existing (v1) database --------------------------------


def test_migration_and_seed_upgrade_are_idempotent(db):
    from lifeos.db import get_engine
    from lifeos.migrate import migrate
    from lifeos.models import ActivityCategory, ClassificationRule, UserSetting
    from lifeos.seed import seed_defaults

    assert migrate(get_engine()) == []  # fresh schema already has the columns
    # Simulate a v1 database: no leisure/drift, no subcategories, no version marker.
    db.query(ClassificationRule).filter(ClassificationRule.priority >= 200).delete()
    db.query(ActivityCategory).filter(ActivityCategory.key.in_(["leisure", "drift"])).delete()
    db.execute(text("UPDATE classification_rules SET subcategory = NULL"))
    db.query(UserSetting).filter_by(key="_seed_version").delete()
    db.commit()
    seed_defaults(db)
    seed_defaults(db)
    assert db.get(ActivityCategory, "drift") and db.get(ActivityCategory, "leisure")
    assert db.query(ClassificationRule).filter_by(name="Editors & IDEs").one().subcategory == "Coding"
    assert db.query(ClassificationRule).filter_by(name="Personal messaging").count() == 1


def test_fragmented_stretch_is_named_by_what_dominated(db):
    upsert_events(db, [
        NormalizedEvent("blank", "activitywatch", at(0), at(0.5), device_id="personal-mac", app="Google Chrome", title="New Tab"),
        _yt("y1", 0.5, 2.5, "Long-ish clip one"),
        NormalizedEvent("c", "activitywatch", at(3), at(5), device_id="personal-mac", app="Code", title="a — life-os"),
        _yt("y2", 5, 2.5, "Long-ish clip two"),
        NormalizedEvent("w", "activitywatch", at(7.5), at(9.5), device_id="personal-mac", app="WhatsApp", title=""),
    ])
    eps = _ep(db)
    assert len(eps) == 1 and eps[0].category == "leisure" and eps[0].kind == "mixed"
    assert eps[0].summary.startswith("Switching between youtube.com 5m")
    assert eps[0].detours  # hops still counted for the day's detour tally
