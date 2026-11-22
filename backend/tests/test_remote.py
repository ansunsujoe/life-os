"""Multi-device collection: guard, tokens, work-device content stripping, collector."""

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from lifeos.collector import build_batches, classify_locally
from lifeos.models import ActivityEvent, Device
from lifeos.services.activity import NormalizedEvent
from lifeos.services.activitywatch import AWEvent
from lifeos.services.classification import is_away_app, is_browser, load_classifier, normalize_app
from lifeos.services.remote import collector_config, issue_token

DAY = date(2026, 3, 2)
T0 = datetime(2026, 3, 2, 15, 0)  # 09:00 Chicago


def at(m: float) -> datetime:
    return T0 + timedelta(minutes=m)


def iso(dt: datetime) -> str:
    return dt.isoformat() + "Z"


@pytest.fixture()
def lan(db):
    from lifeos.main import app

    app.state.skip_init = True
    with TestClient(app, client=("192.168.1.50", 50123)) as c:
        yield c


def _work_laptop(db, approved=True) -> tuple[Device, str]:
    d = Device(id="work-laptop", name="Work laptop", kind="windows", is_work=True, monitoring_approved=approved, aggregate_only=True, store_titles=False)
    db.add(d)
    db.commit()
    return d, issue_token(db, d)


def _personal_pc(db) -> tuple[Device, str]:
    d = Device(id="home-pc", name="Home PC", kind="windows", is_work=False, monitoring_approved=True, store_titles=True)
    db.add(d)
    db.commit()
    return d, issue_token(db, d)


# ---- Windows app names ----------------------------------------------------------


def test_windows_executables_normalise(db):
    assert normalize_app("chrome.exe") == "Google Chrome" and is_browser(normalize_app("msedge.exe"))
    assert normalize_app("Code.exe") == "Code"
    assert normalize_app("SomeInternalTool.exe") == "SomeInternalTool"
    assert is_away_app("LockApp.exe")
    clf = load_classifier(db)
    assert clf.classify("Code.exe", "main.py - proj - Visual Studio Code", None).subcategory == "Coding"
    assert clf.classify("WindowsTerminal.exe", "pwsh", None).category == "software"
    assert clf.classify("chrome.exe", "Funny cat - YouTube", None).category == "leisure"


# ---- network guard -----------------------------------------------------------------


def test_lan_clients_can_only_reach_collector_endpoints(db, lan):
    _, token = _work_laptop(db)
    assert lan.get("/api/health").status_code == 200
    for path in ["/api/today", "/api/settings", "/api/export", "/api/collect/hub-info", "/api/devices"]:
        assert lan.get(path).status_code == 403, path
    assert lan.post("/api/devices/work-laptop/token").status_code == 403
    assert lan.get("/api/collect/config").status_code == 401
    assert lan.get("/api/collect/config", headers={"Authorization": "Bearer nope"}).status_code == 401
    r = lan.get("/api/collect/config", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["device"]["content_free"] is True
    assert all("pattern" in rule for rule in r.json()["rules"])


def test_public_internet_clients_are_refused(db):
    from lifeos.main import app

    _, token = _work_laptop(db)
    with TestClient(app, client=("8.8.8.8", 1)) as c:
        assert c.get("/api/collect/config", headers={"Authorization": f"Bearer {token}"}).status_code == 403


def test_token_is_hashed_and_revocable(db, client, lan):
    d, token = _personal_pc(db)
    assert d.token_hash and token not in d.token_hash
    assert "token_hash" not in json.dumps(client.get("/api/devices").json())
    client.delete("/api/devices/home-pc/token")
    assert lan.get("/api/collect/config", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    new = client.post("/api/devices/home-pc/token").json()["token"]
    assert lan.get("/api/collect/config", headers={"Authorization": f"Bearer {new}"}).status_code == 200


# ---- work device: nothing but categories and times ---------------------------------------


def test_work_device_content_is_stripped_on_the_hub_even_if_sent(db, lan):
    _, token = _work_laptop(db)
    batch = {"format": "lifeos-batch/1", "device_id": "work-laptop", "day": DAY.isoformat(), "bucket_id": "aw-watcher-window_WORK",
             "events": [
                 {"aw_event_id": 1, "piece": 0, "start_time": iso(at(0)), "end_time": iso(at(30)), "category": "software",
                  "subcategory": "Coding", "confidence": "medium",
                  # A misbehaving collector leaking content:
                  "app": "AcmeSecret.exe", "title": "Project Falcon — customer list.xlsx", "domain": "jira.acme.com",
                  "evidence": {"project": "falcon", "url": "https://jira.acme.com/FALCON-1", "afk_filtered": True}},
                 {"aw_event_id": 2, "piece": 0, "start_time": iso(at(30)), "end_time": iso(at(40)), "category": "falcon-secret",
                  "subcategory": "Project Falcon review", "confidence": "high"},
             ]}
    r = lan.post("/api/collect/batch", json=batch, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    rows = db.query(ActivityEvent).order_by(ActivityEvent.start_time).all()
    blob = json.dumps([{c.key: str(getattr(e, c.key)) for c in ActivityEvent.__table__.columns} for e in rows])
    for secret in ["Falcon", "falcon", "acme", "Acme", "customer"]:
        assert secret not in blob
    assert (rows[0].category_key, rows[0].subcategory, rows[0].app, rows[0].title, rows[0].domain) == ("software", "Coding", None, None, None)
    assert (rows[1].category_key, rows[1].subcategory) == ("other", None)  # unknown category / free-text subcategory dropped


def test_collector_classifies_locally_and_sends_no_content(db):
    _work_laptop(db)
    cfg = collector_config(db, db.get(Device, "work-laptop"))
    evs = [NormalizedEvent(f"aw:b:{DAY}:{i}:0", "activitywatch", at(i * 1.2), at(i * 1.2 + 1.1), device_id="work-laptop",
                           app="chrome.exe", title=f"clip {i} - YouTube") for i in range(8)]
    evs.append(NormalizedEvent(f"aw:b:{DAY}:99:0", "activitywatch", at(20), at(50), device_id="work-laptop", app="Code.exe",
                               title="falcon.py - Project Falcon - Visual Studio Code"))
    out = classify_locally(evs, cfg)
    assert {tuple(sorted(e)) for e in out} == {("aw_event_id", "category", "confidence", "end_time", "evidence", "piece", "start_time", "subcategory")}
    assert "Falcon" not in json.dumps(out) and "YouTube" not in json.dumps(out)
    assert [e["category"] for e in out[:8]] == ["drift"] * 8 and out[8]["subcategory"] == "Coding"


# ---- personal device: full detail, hub classifies, idempotent -------------------------------


def test_personal_device_batches_are_classified_and_idempotent(db, lan):
    _, token = _personal_pc(db)
    h = {"Authorization": f"Bearer {token}"}
    ev = lambda i, title, m0, m1: {"aw_event_id": i, "piece": 0, "start_time": iso(at(m0)), "end_time": iso(at(m1)), "app": "chrome.exe", "title": title}  # noqa: E731
    batch = {"device_id": "home-pc", "day": DAY.isoformat(), "bucket_id": "aw-watcher-window_HOMEPC",
             "events": [ev(1, "Learn FastAPI in 30 minutes - YouTube", 0, 20), ev(2, "Cat - YouTube", 20, 25)]}
    assert lan.post("/api/collect/batch", json=batch, headers=h).json()["added"] == 2
    again = lan.post("/api/collect/batch", json=batch, headers=h).json()
    assert (again["added"], again["updated"], again["removed"]) == (0, 0, 0)
    rows = {e.title: e for e in db.query(ActivityEvent)}
    assert rows["Learn FastAPI in 30 minutes - YouTube"].category_key == "software"
    assert rows["Cat - YouTube"].app == "Google Chrome" and rows["Cat - YouTube"].device_id == "home-pc"
    batch["events"] = batch["events"][:1]  # event 2 no longer exists in AW → removed
    assert lan.post("/api/collect/batch", json=batch, headers=h).json()["removed"] == 1


def test_paused_hub_and_disabled_device(db, lan, client):
    d, token = _personal_pc(db)
    h = {"Authorization": f"Bearer {token}"}
    batch = {"day": DAY.isoformat(), "bucket_id": "aw-watcher-window_X", "events": []}
    client.post("/api/privacy/pause", json={"paused": True})
    assert lan.post("/api/collect/batch", json=batch, headers=h).status_code == 423
    client.post("/api/privacy/pause", json={"paused": False})
    d.collection_enabled = False
    db.commit()
    assert lan.post("/api/collect/batch", json=batch, headers=h).status_code == 403


def test_batch_validation(db, lan):
    _, token = _personal_pc(db)
    h = {"Authorization": f"Bearer {token}"}
    assert lan.post("/api/collect/batch", json={"day": DAY.isoformat(), "bucket_id": "evil", "events": []}, headers=h).status_code == 400
    assert lan.post("/api/collect/batch", json={"device_id": "other", "day": DAY.isoformat(), "bucket_id": "aw-watcher-window_X", "events": []}, headers=h).status_code == 403


# ---- collector end to end with a fake ActivityWatch ----------------------------------------


class FakeAW:
    def buckets(self):
        return {"aw-watcher-window_LAPTOP": {"type": "currentwindow"}, "aw-watcher-afk_LAPTOP": {"type": "afkstatus"}}

    def events(self, bucket, start, end):
        if "afk" in bucket:
            return [AWEvent(1, at(-10), at(120), {"status": "not-afk"})]
        return [AWEvent(10, at(0), at(30), {"app": "Code.exe", "title": "secret.py - Falcon - Visual Studio Code"}),
                AWEvent(11, at(30), at(35), {"app": "LockApp.exe", "title": ""})]


def test_collector_batches_flow_into_hub(db, lan):
    _work_laptop(db)
    token = issue_token(db, db.get(Device, "work-laptop"))
    cfg = lan.get("/api/collect/config", headers={"Authorization": f"Bearer {token}"}).json()
    batches = build_batches(FakeAW(), cfg, [DAY])
    assert len(batches) == 1 and len(batches[0]["events"]) == 1  # lock screen dropped
    assert "Falcon" not in json.dumps(batches)
    assert lan.post("/api/collect/batch", json=batches[0], headers={"Authorization": f"Bearer {token}"}).status_code == 200
    e = db.query(ActivityEvent).one()
    assert (e.device_id, e.category_key, e.subcategory, e.title) == ("work-laptop", "software", "Coding", None)


def test_file_drop_import(db, client, tmp_path, monkeypatch):
    import lifeos.routers.collect as collect_router

    _work_laptop(db)
    monkeypatch.setattr(collect_router, "config", SimpleNamespace(imports_dir=tmp_path))
    folder = tmp_path / "devices"
    folder.mkdir()
    (folder / "work-laptop_2026-03-02.json").write_text(json.dumps({
        "format": "lifeos-batch/1", "device_id": "work-laptop", "day": DAY.isoformat(), "bucket_id": "aw-watcher-window_W",
        "events": [{"aw_event_id": 5, "piece": 0, "start_time": iso(at(0)), "end_time": iso(at(10)), "category": "learning", "subcategory": "Courses"}],
    }))
    (folder / "bogus.json").write_text(json.dumps({"device_id": "ghost", "day": DAY.isoformat(), "bucket_id": "aw-watcher-window_G", "events": []}))
    res = {r["file"]: r for r in client.post("/api/imports/devices/scan").json()["results"]}
    assert res["work-laptop_2026-03-02.json"]["status"] == "ok" and res["bogus.json"]["status"] == "error"
    assert (folder / "imported" / "work-laptop_2026-03-02.json").exists()
    assert db.query(ActivityEvent).one().category_key == "learning"


def test_remote_batch_can_never_touch_another_devices_events(db, lan):
    """Regression: a remote device reporting the same AW bucket name as the hub
    must create its own events, not overwrite the hub's."""
    from lifeos.services.activity import upsert_events

    upsert_events(db, [NormalizedEvent(f"aw:aw-watcher-window_Mac:{DAY}:1:0", "activitywatch", at(0), at(30), device_id="personal-mac",
                                       app="Code", title="secret — life-os")])
    _, token = _personal_pc(db)
    batch = {"day": DAY.isoformat(), "bucket_id": "aw-watcher-window_Mac",
             "events": [{"aw_event_id": 1, "piece": 0, "start_time": iso(at(0)), "end_time": iso(at(30)), "app": "chrome.exe", "title": "x"}]}
    r = lan.post("/api/collect/batch", json=batch, headers={"Authorization": f"Bearer {token}"}).json()
    assert r["added"] == 1 and r["updated"] == 0 and r["removed"] == 0
    mac = db.query(ActivityEvent).filter_by(device_id="personal-mac").one()
    assert mac.title == "secret — life-os" and mac.app == "Code"


def test_collector_package_downloadable_from_lan_and_contains_no_data(db, lan):
    import io
    import zipfile

    r = lan.get("/api/collect/package")
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "lifeos-collector/install-collector-windows.ps1" in names
    assert any(n.endswith("lifeos/collector.py") for n in names)
    assert not any(n.endswith((".db", ".json")) or "LifeOS/" in n for n in names)
