"""LifeOS collector — runs on another computer and feeds the hub.

    lifeos-collect setup --hub http://MacBook-Pro-3.local:8765 --token lfs_…
    lifeos-collect test            # checks every step and says which one fails
    lifeos-collect show            # prints exactly what would be sent for today
    lifeos-collect run --every 300 # keep syncing every 5 minutes
    lifeos-collect run --once

It reads *this* computer's ActivityWatch (http://localhost:5600) and sends one
batch per day. ActivityWatch keeps its data locally, so if the hub is asleep,
away, or blocked by a VPN, nothing is lost: the next successful run catches up.

Work devices ("content-free"): activity is classified **on this computer** with
the hub's rules, and only category, generic subcategory, confidence and times
are sent. Window titles, websites, app and project names never leave.

File mode (`--export-dir`): writes the same batches as JSON files for a synced
folder / manual copy into the hub's ~/LifeOS/imports/devices/ folder.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import httpx

from lifeos.services.activitywatch import AWClient, build_day_events
from lifeos.services.classification import Classifier, MediaConfig, RuleSpec, enrich
from lifeos.services.patterns import find_hop_runs
from lifeos.timeutil import local_day_bounds, to_local, utcnow

VERSION = "0.2.0"
BATCH_FORMAT = "lifeos-batch/1"


# ---- local config & state -------------------------------------------------------


def home_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "LifeOS"
    return Path.home() / ".lifeos-collector"


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(path: Path, data: dict[str, Any], secret: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    if secret and sys.platform != "win32":
        os.chmod(tmp, 0o600)
    tmp.replace(path)


def settings_path() -> Path:
    return home_dir() / "collector.json"


def state_path() -> Path:
    return home_dir() / "state.json"


# ---- hub client ------------------------------------------------------------------


class Hub:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.http = httpx.Client(timeout=15.0, headers={
            "Authorization": f"Bearer {token}",
            "X-LifeOS-Collector": VERSION,
            "X-LifeOS-Platform": f"{platform.system()} {platform.release()}",
            "X-LifeOS-Hostname": socket.gethostname()[:64],
        })

    def config(self, aw_version: str | None = None) -> dict[str, Any]:
        r = self.http.get(f"{self.url}/api/collect/config", headers={"X-LifeOS-AW": aw_version or ""})
        _raise(r)
        return r.json()

    def send(self, batch: dict[str, Any]) -> dict[str, Any]:
        r = self.http.post(f"{self.url}/api/collect/batch", json=batch)
        _raise(r)
        return r.json()


class HubError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"{status}: {detail}")
        self.status, self.detail = status, detail


def _raise(r: httpx.Response) -> None:
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise HubError(r.status_code, str(detail)[:300])


# ---- building batches ----------------------------------------------------------------


def make_classifier(cfg: dict[str, Any]) -> Classifier:
    rules = [RuleSpec(r["id"], r["field"], r["match_type"], r["pattern"], r["category"], r["confidence"], r.get("label"),
                      r.get("subcategory"), r.get("priority", 100)) for r in cfg["rules"]]
    return Classifier(rules, MediaConfig(cfg["attention"]["topics"]))


def classify_locally(events: list, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Content-free mode: classify here, detect drift here, return only categories + times."""
    clf = make_classifier(cfg)
    items = []
    for n in events:
        app, domain, evidence = enrich(n.app, n.title, n.domain, n.evidence)
        c = clf.classify(app, n.title, domain, evidence.get("url_kind"))
        items.append(SimpleNamespace(
            n=n, category_key=c.category, category_override=None, subcategory=c.subcategory, confidence=c.confidence,
            start_time=n.start_time, end_time=n.end_time, app=app, title=n.title, domain=domain, evidence=evidence,
        ))
    for run in find_hop_runs(items, cfg["attention"]):
        if run.is_drift:
            for it in run.events:
                if it.category_key == "leisure":
                    it.category_key, it.subcategory = "drift", "Quick hopping"
    out = []
    for it in items:
        ev_id, piece = it.n.source_key.rsplit(":", 2)[-2:]
        out.append({
            "aw_event_id": ev_id, "piece": int(piece),
            "start_time": it.start_time.isoformat() + "Z", "end_time": it.end_time.isoformat() + "Z",
            "category": it.category_key, "subcategory": it.subcategory, "confidence": it.confidence,
            "evidence": {"afk_filtered": bool(it.n.evidence.get("afk_filtered"))},
        })
    return out


def full_detail(events: list) -> list[dict[str, Any]]:
    out = []
    for n in events:
        ev_id, piece = n.source_key.rsplit(":", 2)[-2:]
        evidence = {k: v for k, v in n.evidence.items() if k in {"url", "url_kind", "incognito", "afk_filtered"}}
        out.append({
            "aw_event_id": ev_id, "piece": int(piece),
            "start_time": n.start_time.isoformat() + "Z", "end_time": n.end_time.isoformat() + "Z",
            "app": n.app, "title": n.title, "domain": n.domain, "evidence": evidence,
        })
    return out


def build_batches(aw: AWClient, cfg: dict[str, Any], days: list[date]) -> list[dict[str, Any]]:
    tz_name = cfg["timezone"]
    content_free = cfg["device"]["content_free"]
    buckets = aw.buckets()
    kinds: dict[str, list[str]] = {}
    for bid, meta in buckets.items():
        t = meta.get("type", "")
        k = "window" if t == "currentwindow" else "afk" if t == "afkstatus" else "web" if t.startswith("web.tab") else None
        if k:
            kinds.setdefault(k, []).append(bid)
    now = utcnow()
    batches = []
    for day in days:
        lo, hi = local_day_bounds(day, tz_name)
        hi = min(hi, now)
        if hi <= lo:
            continue
        afk = [e for b in kinds.get("afk", []) for e in aw.events(b, lo, hi)] if kinds.get("afk") else None
        web = [e for b in kinds.get("web", []) for e in aw.events(b, lo, hi)]
        for wb in kinds.get("window", []):
            evs = build_day_events(bucket_id=wb, device_id=cfg["device"]["id"], day=day, day_bounds=(lo, hi),
                                   window_events=aw.events(wb, lo, hi), afk_events=afk, web_events=web,
                                   store_full_urls=cfg.get("store_full_urls", False))
            payload = classify_locally(evs, cfg) if content_free else full_detail(evs)
            batches.append({"format": BATCH_FORMAT, "device_id": cfg["device"]["id"], "day": day.isoformat(),
                            "bucket_id": wb, "content_free": content_free, "collector": VERSION, "events": payload})
    return batches


def days_to_sync(state: dict[str, Any], cfg: dict[str, Any], days_back: int | None) -> list[date]:
    tz_name = cfg["timezone"]
    now = utcnow()
    if days_back is not None:
        since = now - timedelta(days=days_back)
    elif state.get("synced_until"):
        since = datetime.fromisoformat(str(state["synced_until"]).rstrip("Z")) - timedelta(hours=1)
    else:
        since = now - timedelta(hours=cfg.get("first_sync_lookback_hours", 48))
    d0, d1 = to_local(since, tz_name).date(), to_local(now, tz_name).date()
    return [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]


# ---- commands ------------------------------------------------------------------------


def _settings_or_exit() -> dict[str, Any]:
    s = _load(settings_path())
    if not s.get("hub") and not s.get("export_dir"):
        sys.exit(f"Not set up yet. Run: lifeos-collect setup --hub http://<mac>.local:8765 --token <token>\n(settings file: {settings_path()})")
    return s


def _get_config(s: dict[str, Any], aw_version: str | None) -> dict[str, Any]:
    """Live config from the hub, else the cached/offline config file."""
    state = _load(state_path())
    if s.get("hub") and s.get("token"):
        try:
            cfg = Hub(s["hub"], s["token"]).config(aw_version)
            state["config"] = cfg
            _save(state_path(), state)
            return cfg
        except (httpx.HTTPError, HubError):
            if not state.get("config") and not s.get("config_file"):
                raise
    if s.get("config_file"):
        return _load(Path(s["config_file"]))
    if state.get("config"):
        return state["config"]
    sys.exit("No configuration available: connect to the hub once, or pass --config-file from the hub's Devices page.")


def run_once(days_back: int | None = None, quiet: bool = False) -> dict[str, Any]:
    s = _settings_or_exit()
    aw = AWClient(s.get("aw", "http://localhost:5600"))
    try:
        aw_info = aw.info()
    except httpx.HTTPError:
        return {"status": "error", "message": "ActivityWatch isn't running on this computer (http://localhost:5600)."}
    try:
        cfg = _get_config(s, aw_info.get("version"))
    except (httpx.HTTPError, HubError) as exc:
        return {"status": "offline", "message": f"Hub not reachable ({type(exc).__name__}); will catch up later."}
    if cfg.get("paused"):
        return {"status": "paused", "message": "Collection is paused on the hub."}
    if not cfg["device"]["collection_enabled"]:
        return {"status": "disabled", "message": "This device is disabled on the hub."}
    state = _load(state_path())
    days = days_to_sync(state, cfg, days_back)
    started = utcnow()
    batches = build_batches(aw, cfg, days)
    aw.close()
    sent = 0
    if s.get("export_dir"):
        out = Path(s["export_dir"]).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        for b in batches:
            name = f"{b['device_id']}_{b['day']}_{b['bucket_id'].split('_')[0]}.json"
            _save(out / name, b)
            sent += 1
    else:
        hub = Hub(s["hub"], s["token"])
        try:
            for b in batches:
                hub.send(b)
                sent += 1
        except (httpx.HTTPError, HubError) as exc:
            return {"status": "offline", "message": f"Stopped after {sent} batch(es): {exc}. Will retry; nothing is lost."}
    state["synced_until"] = started.isoformat()
    state["last_ok"] = utcnow().isoformat()
    _save(state_path(), state)
    msg = {"status": "ok", "days": [d.isoformat() for d in days], "batches": sent, "events": sum(len(b["events"]) for b in batches)}
    if not quiet:
        print(json.dumps(msg))
    return msg


def cmd_setup(a: argparse.Namespace) -> None:
    s = _load(settings_path())
    if a.hub:
        s["hub"] = a.hub.rstrip("/")
    if a.token:
        s["token"] = a.token.strip()
    if a.aw:
        s["aw"] = a.aw
    if a.export_dir is not None:
        s["export_dir"] = a.export_dir or None
    if a.config_file:
        s["config_file"] = str(Path(a.config_file).resolve())
    _save(settings_path(), s, secret=True)
    print(f"Saved settings to {settings_path()}. Next: lifeos-collect test")


def _check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'OK' if ok else '!!'}] {label}{(' — ' + detail) if detail else ''}")
    return ok


def cmd_test(_: argparse.Namespace) -> None:
    s = _load(settings_path())
    print(f"LifeOS collector {VERSION} on {socket.gethostname()} ({platform.system()})")
    _check("Settings file", bool(s), str(settings_path()))
    aw = AWClient(s.get("aw", "http://localhost:5600"), timeout=3)
    try:
        info, buckets = aw.info(), aw.buckets()
        types = sorted({b.get("type", "") for b in buckets.values()})
        _check("ActivityWatch running", True, f"{info.get('version')} — buckets: {', '.join(types) or 'none yet'}")
        _check("Window watcher present", any(t == "currentwindow" for t in types), "" if "currentwindow" in types else "start ActivityWatch's window watcher")
    except httpx.HTTPError:
        _check("ActivityWatch running", False, "start ActivityWatch on this computer")
        info = {}
    if s.get("export_dir"):
        _check("File mode", True, f"batches go to {s['export_dir']}")
    if not s.get("hub"):
        return
    host = urlparse(s["hub"]).hostname or ""
    try:
        addr = socket.getaddrinfo(host, None)[0][4][0]
        _check("Hub name resolves", True, f"{host} → {addr}")
    except OSError:
        _check("Hub name resolves", False, f"can't resolve {host}: use the Mac's IP address instead, e.g. http://192.168.1.x:8765")
        return
    try:
        r = httpx.get(f"{s['hub']}/api/health", timeout=4)
        _check("Hub reachable", r.status_code == 200, f"HTTP {r.status_code}")
    except httpx.HTTPError as exc:
        _check("Hub reachable", False, f"{type(exc).__name__}: is the Mac awake, on the same network, and is a work VPN blocking local traffic?")
        return
    try:
        cfg = Hub(s["hub"], s.get("token", "")).config(info.get("version"))
        d = cfg["device"]
        mode = "content-free (categories and times only)" if d["content_free"] else "full detail"
        _check("Token accepted", True, f"device '{d['id']}' — {mode}")
        _check("Collection enabled", d["collection_enabled"] and not cfg["paused"], "paused on hub" if cfg["paused"] else "")
    except HubError as exc:
        _check("Token accepted", False, exc.detail)


def cmd_show(a: argparse.Namespace) -> None:
    s = _settings_or_exit()
    aw = AWClient(s.get("aw", "http://localhost:5600"))
    cfg = _get_config(s, None)
    today = to_local(utcnow(), cfg["timezone"]).date()
    batches = build_batches(aw, cfg, [today])
    print(f"Mode: {'content-free' if cfg['device']['content_free'] else 'full detail'} — this is exactly what would be sent:")
    for b in batches:
        sample = b["events"][-a.limit:]
        print(json.dumps({**b, "events": sample, "events_total": len(b["events"])}, indent=1))


def cmd_run(a: argparse.Namespace) -> None:
    if a.once or not a.every:
        r = run_once(a.days_back)
        sys.exit(0 if r["status"] in {"ok", "paused", "disabled", "offline"} else 1)
    print(f"LifeOS collector {VERSION}: syncing every {a.every}s. Ctrl-C to stop.")
    first = True
    while True:
        try:
            r = run_once(a.days_back if first else None, quiet=True)
            print(f"{datetime.now():%H:%M:%S} {r['status']}: {r.get('message') or str(r.get('events', 0)) + ' events'}", flush=True)
        except Exception as exc:  # noqa: BLE001 — keep the loop alive
            print(f"{datetime.now():%H:%M:%S} error: {type(exc).__name__}: {exc}", flush=True)
        first = False
        time.sleep(a.every)


def main() -> None:
    p = argparse.ArgumentParser(prog="lifeos-collect", description="Send this computer's ActivityWatch data to a LifeOS hub.")
    sub = p.add_subparsers(dest="cmd", required=True)
    ps = sub.add_parser("setup", help="save hub URL and token")
    ps.add_argument("--hub")
    ps.add_argument("--token")
    ps.add_argument("--aw", help="ActivityWatch URL (default http://localhost:5600)")
    ps.add_argument("--export-dir", help="file mode: write batches here instead of sending ('' to turn off)")
    ps.add_argument("--config-file", help="offline config downloaded from the hub (file mode)")
    ps.set_defaults(fn=cmd_setup)
    pt = sub.add_parser("test", help="check every step")
    pt.set_defaults(fn=cmd_test)
    pw = sub.add_parser("show", help="print what would be sent for today")
    pw.add_argument("--limit", type=int, default=5)
    pw.set_defaults(fn=cmd_show)
    pr = sub.add_parser("run", help="sync now, or keep syncing with --every")
    pr.add_argument("--once", action="store_true")
    pr.add_argument("--every", type=int, default=0, help="seconds between syncs (e.g. 300)")
    pr.add_argument("--days-back", type=int, default=None, help="re-send the last N days")
    pr.set_defaults(fn=cmd_run)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
