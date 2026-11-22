import io
import zipfile
from datetime import date

from lifeos.timeutil import local_today


def test_timestamps_are_explicit_utc(client):
    r = client.get("/api/today").json()
    assert r["range"]["start"].endswith("Z")


def test_ingest_correct_and_create_rule_from_event(client):
    today = local_today("America/Chicago").isoformat()
    body = {"device_id": "personal-mac", "events": [
        {"start_time": f"{today}T10:00:00-06:00", "end_time": f"{today}T10:30:00-06:00", "app": "Notion", "title": "Notes"},
    ]}
    assert client.post("/api/activity/ingest", json=body).status_code == 200
    evs = client.get("/api/activity/events", params={"start": today}).json()
    assert len(evs) == 1 and evs[0]["effective_category"] == "other" and evs[0]["effective_confidence"] == "low"

    client.patch("/api/activity/events", json={"ids": [evs[0]["id"]], "category": "learning"})
    ev = client.get("/api/activity/events", params={"start": today}).json()[0]
    assert ev["effective_category"] == "learning" and ev["effective_confidence"] == "high"

    r = client.post("/api/rules/from-event", json={"event_id": ev["id"], "field": "app", "category_key": "music"}).json()
    assert r["reclassified"] == 1
    ev = client.get("/api/activity/events", params={"start": today}).json()[0]
    assert ev["category_key"] == "music" and ev["effective_category"] == "learning"  # override still wins

    client.patch("/api/activity/events", json={"ids": [ev["id"]], "excluded": True})
    today_view = client.get("/api/today").json()
    assert today_view["blocks"] == [] and today_view["excluded_count"] == 1


def test_unknown_or_unapproved_devices_are_rejected(client):
    ev = {"start_time": "2026-03-02T10:00:00Z", "end_time": "2026-03-02T11:00:00Z", "app": "Outlook"}
    assert client.post("/api/activity/ingest", json={"device_id": "nope", "events": [ev]}).status_code == 400
    client.post("/api/devices", json={"id": "work-win", "name": "Work PC", "kind": "windows", "is_work": True})
    assert client.post("/api/activity/ingest", json={"device_id": "work-win", "events": [ev]}).status_code == 400
    r = client.post("/api/imports/summary", json={"device_id": "work-win", "day": "2026-03-02", "entries": [{"category": "software", "minutes": 240}, {"category": "other", "minutes": 30}]})
    assert r.status_code == 200 and r.json()["records_added"] == 2


def test_invalid_rule_regex_rejected(client):
    r = client.post("/api/rules", json={"field": "app", "match_type": "regex", "pattern": "([", "category_key": "software"})
    assert r.status_code == 400


def test_tasks_milestones_goals_flow(client):
    t = client.post("/api/tasks", json={"title": "Build timeline", "milestones": ["Schema", "API"], "priority": 3}).json()
    assert t["status"] == "todo" and len(t["milestones"]) == 2
    t = client.patch(f"/api/milestones/{t['milestones'][0]['id']}", json={"done": True}).json()
    assert t["status"] == "in_progress" and t["milestones_done"] == 1
    g = client.post("/api/goals", json={"domain": "software", "title": "Ship LifeOS", "measure": "milestones", "target": 2}).json()
    goals = client.get("/api/goals").json()["goals"]
    assert goals[0]["id"] == g["id"] and goals[0]["progress"]["value"] == 1 and goals[0]["progress"]["ratio"] == 0.5
    t = client.patch(f"/api/tasks/{t['id']}", json={"status": "done"}).json()
    assert t["completed_at"]
    scores = client.get("/api/scores").json()
    prog = next(d for d in scores["score"]["dimensions"] if d["key"] == "progress")
    assert prog["included"] and prog["score"] == 50.0


def test_sessions_api_and_hook(client):
    s = client.post("/api/sessions", json={"project": "lifeos", "objective": "frontend", "state": "generating"}).json()
    s = client.post(f"/api/sessions/{s['id']}/state", json={"state": "ready"}).json()
    assert s["needs_attention"]
    client.post("/api/sessions/hook", json={"hook_event_name": "Stop", "session_id": "cc-1", "cwd": "/x/proj"})
    data = client.get("/api/sessions").json()
    assert data["needs_attention"] == 2
    rec = client.get("/api/recommendations").json()
    assert rec["top"]["kind"] == "session"
    fb = client.post("/api/recommendations/feedback", json={"key": rec["top"]["key"], "kind": "session", "title": rec["top"]["title"], "action": "snoozed", "snooze_minutes": 10})
    assert fb.status_code == 200
    assert client.get("/api/recommendations").json()["top"]["key"] != rec["top"]["key"]


def test_daily_review_creates_and_removes_derived_checkins(client):
    day = local_today("America/Chicago").isoformat()
    client.put(f"/api/reviews/{day}", json={"scripture_prayer": True, "learned": "SQLAlchemy events", "energy": 3})
    cks = client.get("/api/checkins").json()
    assert {(c["domain"], c["kind"]) for c in cks} == {("faith", "scripture_prayer"), ("learning", "checkpoint"), ("self", "energy")}
    client.put(f"/api/reviews/{day}", json={"scripture_prayer": None, "learned": "", "energy": 3})
    assert {(c["domain"], c["kind"]) for c in client.get("/api/checkins").json()} == {("self", "energy")}
    assert client.get(f"/api/reviews/{day}").json()["energy"] == 3


def test_settings_validation_and_pause(client):
    assert client.patch("/api/settings", json={"nonsense": 1}).status_code == 400
    r = client.patch("/api/settings", json={"score_weights": {"progress": 0.4}}).json()
    assert r["settings"]["score_weights"] == {"progress": 0.4, "maintenance": 0.2, "recovery": 0.2, "intentionality": 0.1}
    assert client.post("/api/privacy/pause", json={"paused": True}).json() == {"paused": True}
    assert client.get("/api/status").json()["paused"] is True


def test_export_and_delete_require_confirmation(client):
    r = client.get("/api/export")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "activity_events.json" in names and "user_settings.json" in names
    assert client.delete("/api/data/activity").status_code == 400
    assert client.delete("/api/data/activity", params={"confirm": "DELETE"}).status_code == 200


def test_trading_summary_never_judges_by_pnl(client):
    client.post("/api/trading/notes", json={"instrument": "AAPL", "followed_plan": True, "risk_sized": False})
    s = client.get("/api/trading/summary").json()
    assert s["process_adherence"]["followed_plan"] == {"yes": 1, "answered": 1}
    assert any("never used to judge" in n for n in s["data_notes"])


def test_insights_endpoint(client):
    r = client.get("/api/insights", params={"days": 7, "weeks": 2}).json()
    assert len(r["days"]) == 7 and len(r["weekly_scores"]) == 2
    assert r["orchestration"]["exploratory"] is True
    _ = date
