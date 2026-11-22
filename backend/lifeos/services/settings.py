"""User-editable settings stored in `user_settings`, merged over safe defaults."""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from lifeos.models import UserSetting
from lifeos.timeutil import detect_system_timezone

DEFAULT_SETTINGS: dict[str, Any] = {
    "timezone": detect_system_timezone(),
    # Spec §4.2 — a starting point, not a permanent truth.
    "score_weights": {
        "progress": 0.50,
        "maintenance": 0.20,
        "recovery": 0.20,
        "intentionality": 0.10,
    },
    # Spec §4.5 — exploratory, shown separately from productivity.
    "orchestration_weights": {"P": 0.30, "W": 0.25, "C": 0.20, "T": 0.15, "A": 0.10},
    "domains": {
        # Which dimension each domain's weekly goals contribute to.
        "progress": ["software", "trading", "music", "learning"],
        "maintenance": ["health", "faith"],
        "recovery": ["recovery"],
    },
    "include_faith_in_score": True,
    "recovery": {
        "break_gap_minutes": 5,  # idle gap that counts as a break
        "micro_break_after_minutes": 50,
        "short_break_after_minutes": 90,
        "long_break_after_minutes": 150,
        "deep_work_switches_per_hour": 12,  # below this, treat as focused work — don't interrupt early
        "high_switches_per_hour": 40,
        "daily_screen_soft_limit_hours": 9,
        "end_of_day_hour": 21,
        "stall_days": 3,
    },
    "activitywatch": {
        "enabled": True,
        "url": "http://localhost:5600",
        "interval_minutes": 5,
        "first_sync_lookback_hours": 48,
        "merge_gap_seconds": 60,
    },
    "privacy": {
        "store_window_titles": True,  # personal Mac only; work devices never store titles
        "store_full_urls": False,  # domain only by default
        "collection_paused": False,  # global pause switch
        "claude_hook_capture_prompt": False,
    },
    # Attention & context: what's on screen, drift detection, episodes.
    "attention": {
        # Video/social titles matching these words count toward that category
        # (low confidence). Faith is intentionally empty: never inferred by default.
        "topics": {
            "software": ["programming", "coding", "python", "javascript", "typescript", "react", "next.js", "nextjs", "rust", "golang",
                         "docker", "kubernetes", "system design", "leetcode", "claude code", "llm", "llms", "ai agent", "ai agents",
                         "machine learning", "fastapi", "sql", "postgres", "devops", "git", "neovim", "vscode", "api design", "software engineering"],
            "music": ["logic pro", "orchestration", "orchestral", "mixing", "mastering", "music theory", "composition", "composing",
                      "arrangement", "arranging", "film score", "film scoring", "sound design", "synth", "synthesizer", "chord progression",
                      "harmony", "counterpoint", "kontakt", "spitfire", "string writing", "music production"],
            "trading": ["stock market", "stocks", "options trading", "day trading", "swing trading", "earnings", "technical analysis",
                        "candlestick", "fomc", "s&p 500", "investing", "portfolio", "risk management", "price action"],
            "learning": ["tutorial", "lecture", "course", "lesson", "explained", "masterclass", "crash course", "documentation", "how it works"],
            "health": ["workout", "stretching", "mobility routine", "yoga", "physiotherapy"],
            "faith": [],
        },
        "drift_min_run_minutes": 5,  # a hopping run must last at least this long
        "drift_min_distinct_items": 4,  # …and touch at least this many videos/pages
        "drift_max_median_item_minutes": 3,  # …spending this little on each
        "detour_max_minutes": 3,  # short hops inside another episode are "detours"
        "nudge_after_drift_minutes": 10,  # live gentle nudge threshold (last 20 min)
    },
    "music": {"project_dirs": ["~/Music/Logic"], "bounce_extensions": [".wav", ".mp3", ".aif", ".aiff", ".m4a", ".flac"]},
    "apple_health": {"lookback_days": 120},
    "sessions": {"idle_after_minutes": 45, "attention_stale_minutes": 15},
    # Phase 0 open decisions (spec §16) with safe defaults.
    "preferences": {
        "claude_clients": ["claude_code"],
        "break_style": "adaptive",  # adaptive|interval|excessive_only
        "orchestrator_autonomy": "suggest",  # suggest only — never acts on its own
        "onboarding_complete": False,
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def get_settings(db: Session) -> dict[str, Any]:
    # Keys starting with "_" are internal bookkeeping (e.g. seed version).
    stored = {row.key: row.value for row in db.query(UserSetting).all() if not row.key.startswith("_")}
    return _deep_merge(DEFAULT_SETTINGS, stored)


def get_setting(db: Session, key: str) -> Any:
    return get_settings(db)[key]


def update_settings(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge `patch` into stored settings. Only known top-level keys are accepted."""
    unknown = set(patch) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ValueError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    for key, value in patch.items():
        row = db.get(UserSetting, key)
        if isinstance(value, dict) and isinstance(DEFAULT_SETTINGS[key], dict):
            current = row.value if row else {}
            value = _deep_merge(current or {}, value)
        if row:
            row.value = value
        else:
            db.add(UserSetting(key=key, value=value))
    db.commit()
    return get_settings(db)


def tz(db: Session) -> str:
    return get_setting(db, "timezone")
