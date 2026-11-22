"""Deterministic, user-configurable activity classification.

Order of evaluation for an event (first match wins):
1. User rules with priority < MEDIA_STEP_PRIORITY (e.g. "always classify X" rules, priority 1).
2. The built-in media step: video / social / news sites are classified by what
   is on screen — a video's title is matched against topic keywords (Python
   tutorial → software, orchestration → music); otherwise short-form video and
   feeds → drift, a regular video → leisure.
3. The remaining rules in priority order (seeded defaults start at 10).
4. Fallback: other / low confidence.

Sequence-level judgements (e.g. hopping through many short videos) are made
afterwards by `lifeos.services.patterns`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from lifeos.models import ActivityEvent, ClassificationRule

MEDIA_STEP_PRIORITY = 10

BROWSER_APPS = {
    "google chrome", "chrome", "safari", "firefox", "arc", "brave browser", "microsoft edge", "msedge",
    "opera", "vivaldi", "chromium", "orion", "zen browser", "dia", "brave",
}

# Lock screen / screensaver: the person is away even if the AFK watcher hasn't noticed yet.
AWAY_APPS = {"loginwindow", "screensaverengine", "lockapp", "logonui"}

# Windows reports executables ("chrome.exe"); map common ones to the names the
# rules use. Unknown executables just lose the ".exe".
WINDOWS_APPS = {
    "chrome": "Google Chrome", "msedge": "Microsoft Edge", "firefox": "Firefox", "brave": "Brave Browser", "opera": "Opera",
    "vivaldi": "Vivaldi", "arc": "Arc", "code": "Code", "cursor": "Cursor", "windowsterminal": "Windows Terminal",
    "wt": "Windows Terminal", "powershell": "Terminal", "pwsh": "Terminal", "cmd": "Terminal", "wsl": "Terminal",
    "slack": "Slack", "ms-teams": "Microsoft Teams", "teams": "Microsoft Teams", "zoom": "zoom.us", "outlook": "Outlook",
    "olk": "Outlook", "whatsapp": "WhatsApp", "telegram": "Telegram", "discord": "Discord", "spotify": "Spotify",
    "claude": "Claude", "notion": "Notion", "obsidian": "Obsidian", "explorer": "File Explorer", "pycharm64": "PyCharm",
    "idea64": "IntelliJ IDEA", "devenv": "Visual Studio", "steam": "Steam", "applicationframehost": "Windows app",
}

VIDEO_DOMAINS = {"youtube.com", "m.youtube.com", "youtu.be", "twitch.tv", "vimeo.com", "netflix.com", "primevideo.com", "disneyplus.com", "hulu.com", "max.com"}
SHORT_FORM_DOMAINS = {"tiktok.com"}
SOCIAL_DOMAINS = {"x.com", "twitter.com", "reddit.com", "old.reddit.com", "instagram.com", "facebook.com", "threads.net", "bsky.app"}
NEWS_DOMAINS = {"news.ycombinator.com", "cnn.com", "nytimes.com", "bbc.com", "theverge.com", "foxnews.com", "apnews.com"}
STREAMING_DOMAINS = {"netflix.com", "primevideo.com", "disneyplus.com", "hulu.com", "max.com"}

# Browser window titles carry the site name as a suffix; used when no browser
# extension reports the URL. (pattern, domain)
TITLE_DOMAIN_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(^|\s[-–—]\s)YouTube$|^youtube\.com/", re.I), "youtube.com"),
    (re.compile(r"\s/\sX$|\son X:\s|^X$", re.I), "x.com"),
    (re.compile(r"(\s[-:]\s|^)r/\w+|\s[-–]\sReddit$|^Reddit\b", re.I), "reddit.com"),
    (re.compile(r"Instagram$|•\sInstagram", re.I), "instagram.com"),
    (re.compile(r"TikTok", re.I), "tiktok.com"),
    (re.compile(r"Netflix$", re.I), "netflix.com"),
    (re.compile(r"\s[-–]\sTwitch$", re.I), "twitch.tv"),
    (re.compile(r"\|\s?LinkedIn$", re.I), "linkedin.com"),
    (re.compile(r"·\sGitHub$|^GitHub\b", re.I), "github.com"),
    (re.compile(r"\s[-–]\sStack Overflow$", re.I), "stackoverflow.com"),
    (re.compile(r"\s[-–]\sClaude$|^Claude$", re.I), "claude.ai"),
    (re.compile(r"\s[-–]\sGmail$|Gmail$", re.I), "mail.google.com"),
    (re.compile(r"\s[-–]\sGoogle (Docs|Sheets|Slides)$", re.I), "docs.google.com"),
    (re.compile(r"Robinhood", re.I), "robinhood.com"),
    (re.compile(r"TradingView", re.I), "tradingview.com"),
    (re.compile(r"\|\sHacker News$|^Hacker News$", re.I), "news.ycombinator.com"),
]

_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")
_NOTIF_PREFIX = re.compile(r"^\(\d+\+?\)\s*")


def normalize_app(app: str | None) -> str | None:
    if not app:
        return None
    a = _INVISIBLE.sub("", app).strip()
    if a.lower().endswith(".exe"):
        base = a[:-4]
        a = WINDOWS_APPS.get(base.lower(), base)
    return a or None


def clean_title(title: str | None) -> str:
    """Strip unread-count prefixes like '(3) ' and invisible characters."""
    if not title:
        return ""
    return _NOTIF_PREFIX.sub("", _INVISIBLE.sub("", title)).strip()


def is_browser(app: str | None) -> bool:
    return bool(app) and app.strip().lower() in BROWSER_APPS


def is_away_app(app: str | None) -> bool:
    a = (app or "").strip().lower().removesuffix(".exe")
    return a in AWAY_APPS


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url if "://" in url else f"https://{url}").hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.lower().removeprefix("www.")


def infer_domain_from_title(title: str | None) -> str | None:
    t = clean_title(title)
    if not t:
        return None
    for pat, dom in TITLE_DOMAIN_HINTS:
        if pat.search(t):
            return dom
    # Some pages show their URL as the title, e.g. "youtube.com/watch?v=…".
    m = re.match(r"^([a-z0-9-]+(\.[a-z0-9-]+)+)/", t, re.I)
    return m.group(1).lower().removeprefix("www.") if m else None


def url_kind(url_or_title: str | None, domain: str | None) -> str | None:
    """Privacy-preserving page type ('shorts', 'feed', 'watch', 'search', 'post').
    Only this label is stored, never the URL itself (unless the user opts in)."""
    if not url_or_title or not domain:
        return None
    s = url_or_title.lower()
    path = ""
    if "/" in s and ("." in s.split("/")[0] or s.startswith("http")):
        try:
            path = urlparse(s if "://" in s else f"https://{s}").path or "/"
        except ValueError:
            path = ""
    if domain.endswith("youtube.com") or domain == "youtu.be":
        if "/shorts/" in s:
            return "shorts"
        if path.startswith("/watch") or "watch?" in s or domain == "youtu.be":
            return "watch"
        if path.startswith("/results"):
            return "search"
        if path == "/" or path.startswith("/feed"):
            return "feed"
        if clean_title(url_or_title).lower() == "youtube":
            return "feed"
        return None
    if domain == "instagram.com" and ("/reels/" in s or "/reel/" in s):
        return "shorts"
    if domain in {"tiktok.com"}:
        return "shorts"
    if domain in {"x.com", "twitter.com"} and (path.startswith("/home") or clean_title(url_or_title).lower().startswith("home /")):
        return "feed"
    if "reddit.com" in domain:
        return "post" if "/comments/" in s else ("feed" if path else None)
    return None


# ---- project hints -------------------------------------------------------------

EDITOR_APPS = {"code", "visual studio code", "cursor", "zed", "windsurf", "pycharm", "intellij idea", "webstorm", "xcode", "sublime text"}
TERMINAL_APPS = {"terminal", "iterm", "iterm2", "warp", "ghostty", "alacritty", "kitty", "wezterm"}


def extract_project(app: str | None, title: str | None) -> str | None:
    """Best-effort project name from editor/terminal titles, e.g.
    'main.py — life-os' → 'life-os', 'user@mac: ~/projects/life-os' → 'life-os'."""
    a = (app or "").strip().lower()
    t = clean_title(title)
    if not t:
        return None
    if a in EDITOR_APPS:
        parts = [p.strip() for p in re.split(r"\s[—–]\s", t) if p.strip()]
        parts = [p for p in parts if p.lower() not in {"visual studio code", "cursor", "zed", "xcode"}]
        if len(parts) >= 2:
            cand = parts[-1]
            cand = re.sub(r"\s*\[.*?\]$", "", cand)  # e.g. "[SSH: host]"
            return cand[:64] or None
        return None
    if a in TERMINAL_APPS:
        m = re.search(r"(?:~|/)[\w./-]*/([\w.-]+)/?(?:\s|$)", t)
        if m:
            return m.group(1)[:64]
        parts = [p.strip() for p in re.split(r"\s[—–]\s", t) if p.strip()]
        if len(parts) >= 2 and re.fullmatch(r"[\w.-]{2,64}", parts[-1]) and parts[-1].lower() not in {"zsh", "bash", "fish"}:
            return parts[-1]
    return None


# ---- classifier ----------------------------------------------------------------


@dataclass(frozen=True)
class RuleSpec:
    id: int | None
    field: str
    match_type: str
    pattern: str
    category: str
    confidence: str
    label: str | None = None
    subcategory: str | None = None
    priority: int = 100


@dataclass(frozen=True)
class Classification:
    category: str
    confidence: str
    rule_id: int | None
    label: str
    subcategory: str | None = None


@dataclass
class MediaConfig:
    topics: dict[str, list[str]] = field(default_factory=dict)
    _compiled: dict[str, re.Pattern[str]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for cat, words in self.topics.items():
            words = [w.strip() for w in words if w and w.strip()]
            if words:
                alt = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
                self._compiled[cat] = re.compile(rf"(?<!\w)({alt})(?!\w)", re.IGNORECASE)

    def topic(self, text: str) -> tuple[str, str] | None:
        for cat, pat in self._compiled.items():
            m = pat.search(text)
            if m:
                return cat, m.group(1).lower()
        return None


TOPIC_SUBCATEGORY = {
    "software": "Tech video / thread",
    "music": "Music video / lesson",
    "trading": "Market video / thread",
    "learning": "Video lesson",
    "health": "Workout video",
}


class Classifier:
    """Evaluates user rules, then the media step, then remaining rules."""

    def __init__(self, rules: list[RuleSpec], media: MediaConfig | None = None):
        self.media = media or MediaConfig()
        self._rules: list[tuple[RuleSpec, re.Pattern[str] | None]] = []
        for r in sorted(rules, key=lambda r: r.priority):
            compiled = None
            if r.match_type == "regex":
                try:
                    compiled = re.compile(r.pattern, re.IGNORECASE)
                except re.error:
                    continue  # invalid user regex: skip rather than crash ingestion
            self._rules.append((r, compiled))

    @staticmethod
    def _matches(rule: RuleSpec, compiled: re.Pattern[str] | None, value: str | None) -> bool:
        if not value:
            return False
        v = value.strip()
        if rule.match_type == "equals":
            return v.lower() == rule.pattern.strip().lower()
        if rule.match_type == "regex":
            return bool(compiled and compiled.search(v))
        return rule.pattern.strip().lower() in v.lower()

    def _media(self, app: str | None, title: str, domain: str | None, kind: str | None) -> Classification | None:
        if not domain:
            return None
        is_video = domain in VIDEO_DOMAINS
        is_short = domain in SHORT_FORM_DOMAINS
        is_social = domain in SOCIAL_DOMAINS
        is_news = domain in NEWS_DOMAINS
        if not (is_video or is_short or is_social or is_news):
            return None
        site = domain.split(".")[-2].capitalize() if "." in domain else domain
        site = {"Youtube": "YouTube", "Ycombinator": "Hacker News", "X": "X", "Youtu": "YouTube"}.get(site, site)
        # What's on screen decides: a Python tutorial is software, not leisure.
        hit = self.media.topic(title) if title else None
        if hit and kind not in {"shorts"}:
            cat, word = hit
            return Classification(cat, "low", None, f"{site}: {word}", TOPIC_SUBCATEGORY.get(cat, "Topic video"))
        if kind == "shorts" or is_short:
            return Classification("drift", "medium", None, f"{site} shorts", "Short-form video")
        if is_video:
            if domain in STREAMING_DOMAINS:
                return Classification("leisure", "medium", None, site, "Streaming")
            if kind in {"feed", "search"}:
                return Classification("drift", "low", None, f"{site} feed", "Browsing video feed")
            return Classification("leisure", "low", None, site, "Watching videos")
        if is_social:
            if kind == "post":
                return Classification("leisure", "low", None, site, "Social media")
            return Classification("drift", "low", None, site, "Social feed")
        return Classification("leisure", "low", None, site, "News")

    def classify(self, app: str | None, title: str | None, domain: str | None, kind: str | None = None) -> Classification:
        app = normalize_app(app)
        ctitle = clean_title(title)
        if domain is None and is_browser(app):
            domain = infer_domain_from_title(title)
        if kind is None and domain:
            kind = url_kind(title, domain)
        fields = {"app": app, "title": ctitle, "domain": domain}
        media_done = False
        for rule, compiled in self._rules:
            if not media_done and rule.priority >= MEDIA_STEP_PRIORITY:
                media_done = True
                m = self._media(app, ctitle, domain, kind)
                if m:
                    return m
            candidates = [app, ctitle, domain] if rule.field == "any" else [fields.get(rule.field)]
            if any(self._matches(rule, compiled, c) for c in candidates):
                return Classification(rule.category, rule.confidence, rule.id, rule.label or default_label(app, domain), rule.subcategory)
        if not media_done:
            m = self._media(app, ctitle, domain, kind)
            if m:
                return m
        return Classification("other", "low", None, default_label(app, domain))


def default_label(app: str | None, domain: str | None) -> str:
    if domain and is_browser(app):
        return domain
    return app or domain or "Unknown"


def load_classifier(db: Session) -> Classifier:
    from lifeos.services.settings import get_settings

    rows = (
        db.query(ClassificationRule)
        .filter(ClassificationRule.enabled.is_(True))
        .order_by(ClassificationRule.priority, ClassificationRule.id)
        .all()
    )
    topics = get_settings(db)["attention"]["topics"]
    return Classifier(
        [RuleSpec(r.id, r.field, r.match_type, r.pattern, r.category_key, r.confidence, r.activity_label, r.subcategory, r.priority) for r in rows],
        MediaConfig(topics),
    )


def validate_rule_pattern(match_type: str, pattern: str) -> None:
    if match_type == "regex":
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression: {exc}") from exc


def enrich(app: str | None, title: str | None, domain: str | None, evidence: dict[str, Any] | None) -> tuple[str | None, str | None, dict[str, Any]]:
    """Normalise app, infer a missing browser domain, add url_kind/project hints."""
    app = normalize_app(app)
    ev = dict(evidence or {})
    if domain is None and is_browser(app):
        domain = infer_domain_from_title(title)
        if domain:
            ev["domain_from_title"] = True
    if domain and "url_kind" not in ev:
        k = url_kind(ev.get("url") or title, domain)
        if k:
            ev["url_kind"] = k
    proj = extract_project(app, title)
    if proj:
        ev["project"] = proj
    return app, domain, ev


def reclassify_events(db: Session, pattern_days: int = 60) -> int:
    """Re-apply rules to rule-classified events. Events that arrived with an
    explicit category (workouts, summaries) and user overrides are untouched.
    Sequence patterns (drift detection) are then recomputed."""
    from lifeos.services.patterns import apply_patterns_since

    clf = load_classifier(db)
    changed = 0
    for ev in db.query(ActivityEvent).all():
        if (ev.evidence or {}).get("explicit_category"):
            continue
        evidence = ev.evidence or {}
        if ev.domain is None and is_browser(ev.app) and ev.title:
            app, dom, evidence = enrich(ev.app, ev.title, None, evidence)
            ev.domain, ev.evidence = dom, evidence
        c = clf.classify(ev.app, ev.title, ev.domain, evidence.get("url_kind"))
        if (ev.category_key, ev.confidence, ev.rule_id, ev.subcategory, ev.activity) != (c.category, c.confidence, c.rule_id, c.subcategory, c.label):
            ev.category_key, ev.confidence, ev.rule_id, ev.subcategory = c.category, c.confidence, c.rule_id, c.subcategory
            ev.activity = c.label
            changed += 1
    db.commit()
    apply_patterns_since(db, pattern_days)
    return changed
