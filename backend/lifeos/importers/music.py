"""Logic Pro project-folder signals: saves, creation, and bounces.

Only file metadata (names, timestamps) is read — never musical content.
Time in Logic is context, not proof of creative progress (spec §5.5).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass
class MusicFileSignal:
    source_key: str
    project_name: str
    path: str
    kind: str  # project_saved|project_created|bounce
    at: datetime  # naive UTC


def _utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, UTC).replace(tzinfo=None)


def _bundle_mtime(bundle: Path, limit: int = 400) -> float:
    latest = bundle.stat().st_mtime
    n = 0
    for root, _dirs, files in os.walk(bundle):
        for f in files:
            try:
                latest = max(latest, (Path(root) / f).stat().st_mtime)
            except OSError:
                pass
            n += 1
            if n >= limit:
                return latest
    return latest


def scan_dirs(dirs: list[str], bounce_exts: list[str], since: datetime | None = None, max_depth: int = 5) -> list[MusicFileSignal]:
    exts = {e.lower() for e in bounce_exts}
    out: list[MusicFileSignal] = []
    for d in dirs:
        base = Path(d).expanduser()
        if not base.is_dir():
            continue
        base_depth = len(base.parts)
        for root, dirnames, files in os.walk(base):
            rp = Path(root)
            if len(rp.parts) - base_depth >= max_depth:
                dirnames[:] = []
            bundles = [n for n in dirnames if n.lower().endswith(".logicx")]
            for b in bundles:
                bp = rp / b
                name = b[: -len(".logicx")]
                try:
                    st = bp.stat()
                    mtime = _bundle_mtime(bp)
                except OSError:
                    continue
                saved = _utc(mtime)
                if since is None or saved >= since:
                    out.append(MusicFileSignal(f"music:saved:{bp}:{int(mtime)}", name, str(bp), "project_saved", saved))
                birth = getattr(st, "st_birthtime", None)
                if birth and (since is None or _utc(birth) >= since):
                    out.append(MusicFileSignal(f"music:created:{bp}", name, str(bp), "project_created", _utc(birth)))
            dirnames[:] = [n for n in dirnames if not n.lower().endswith(".logicx") and not n.startswith(".")]
            for f in files:
                if Path(f).suffix.lower() in exts:
                    fp = rp / f
                    try:
                        mtime = fp.stat().st_mtime
                    except OSError:
                        continue
                    at = _utc(mtime)
                    if since is None or at >= since:
                        project = rp.parent.name if rp.name.lower() == "bounces" else rp.name
                        out.append(MusicFileSignal(f"music:bounce:{fp}:{int(mtime)}", project, str(fp), "bounce", at))
    return out
