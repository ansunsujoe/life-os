"""Default categories, classification rules, and the local device.

Seeding is idempotent and never overwrites user edits. Later additions are
applied once per database through numbered seed versions.
"""

from __future__ import annotations

import re
import socket

from sqlalchemy.orm import Session

from lifeos.models import ActivityCategory, ClassificationRule, CollectorStatus, Device, UserSetting

DEFAULT_CATEGORIES = [
    # key, name, color, productive, description
    ("software", "Software development", "blue", True, "Professional work, coding, Claude sessions"),
    ("trading", "Trading", "yellow", True, "Research, monitoring, and trade review"),
    ("music", "Music production", "grape", True, "Composition, arrangement, sound design, mixing"),
    ("learning", "Learning", "cyan", True, "Courses, study, practice of new skills"),
    ("faith", "Faith & Christian action", "orange", True, "Scripture, prayer, service, community"),
    ("health", "Health & exercise", "green", True, "Exercise, movement, health routines"),
    ("recovery", "Recovery & offline life", "teal", False, "Breaks, rest, relationships, offline time"),
    ("leisure", "Leisure & entertainment", "violet", False, "Chosen downtime: a show, a video you meant to watch"),
    ("drift", "Drift & scrolling", "pink", False, "Feeds, shorts and quick hopping between things"),
    ("other", "Other / unclassified", "gray", False, "Not yet classified"),
]

# (name, field, match_type, pattern, category, confidence, subcategory)
# Deliberately no faith or health rules: those domains are never inferred from
# device usage (spec §5.7). Users may add their own rules if they want labels.
DEFAULT_RULES = [
    ("Editors & IDEs", "app", "regex", r"^(code|visual studio code|cursor|xcode|pycharm|intellij idea|webstorm|zed|sublime text|nova|windsurf)$", "software", "medium", "Coding"),
    ("Terminals", "app", "regex", r"^(terminal|iterm2?|warp|ghostty|alacritty|kitty|wezterm|windows terminal)$", "software", "medium", "Terminal / Claude Code"),
    ("Claude desktop", "app", "equals", "claude", "software", "medium", "AI assistant"),
    ("Dev tools", "app", "regex", r"^(docker desktop|postman|insomnia|tableplus|github desktop|sourcetree|simulator)$", "software", "medium", "Dev tools"),
    ("Dev websites", "domain", "regex", r"(^|\.)(github\.com|gitlab\.com|stackoverflow\.com|claude\.ai|docs\.anthropic\.com|vercel\.com|npmjs\.com|pypi\.org|localhost)$", "software", "medium", "Docs & code hosting"),
    ("Work chat", "app", "regex", r"^(slack|microsoft teams|zoom\.us)$", "software", "low", "Communication"),
    ("Logic Pro", "app", "regex", r"^logic pro( x)?$", "music", "medium", "Logic Pro"),
    ("Music tools", "app", "regex", r"^(mainstage|native access|kontakt.*|ableton live.*|spitfire audio|musescore.*|sibelius|dorico.*)$", "music", "medium", "Music tools"),
    ("Music websites", "domain", "regex", r"(^|\.)(splice\.com|soundcloud\.com|musescore\.com)$", "music", "low", "Music websites"),
    ("Brokerage & charts", "domain", "regex", r"(^|\.)(robinhood\.com|tradingview\.com|finviz\.com|stocktwits\.com)$", "trading", "medium", "Charts & brokerage"),
    ("Trading apps", "app", "regex", r"^(robinhood|tradingview|thinkorswim)$", "trading", "medium", "Charts & brokerage"),
    ("Course platforms", "domain", "regex", r"(^|\.)(coursera\.org|udemy\.com|edx\.org|khanacademy\.org|brilliant\.org|frontendmasters\.com|egghead\.io|leetcode\.com|exercism\.org)$", "learning", "medium", "Courses"),
    ("Reading apps", "app", "regex", r"^(books|kindle|anki|obsidian)$", "learning", "low", "Reading & notes"),
    ("Educational-looking titles", "title", "regex", r"\b(tutorial|course|lecture|lesson|how to|explained|documentation)\b", "learning", "low", "Study"),
]

# Seed version 2: more specific "what are you actually doing" rules.
SEED_V2_RULES = [
    ("Personal messaging", "app", "regex", r"^(whatsapp|messages|telegram|signal|discord|facetime)$", "recovery", "low", "Messaging & people"),
    ("Messaging websites", "domain", "regex", r"(^|\.)(web\.whatsapp\.com|messenger\.com|discord\.com)$", "recovery", "low", "Messaging & people"),
    ("Email", "domain", "regex", r"^(mail\.google\.com|outlook\.live\.com|outlook\.office\.com)$", "software", "low", "Email"),
    ("Mail app", "app", "regex", r"^(mail|outlook|spark|superhuman)$", "software", "low", "Email"),
    ("Docs & writing", "domain", "regex", r"^(docs\.google\.com|notion\.so|www\.notion\.so)$", "software", "low", "Docs & writing"),
    ("Shopping", "domain", "regex", r"(^|\.)(amazon\.com|ebay\.com|etsy\.com|walmart\.com|target\.com|bestbuy\.com)$", "drift", "low", "Shopping"),
    ("Games", "app", "regex", r"^(steam|epic games launcher|minecraft|league of legends)$", "leisure", "medium", "Games"),
    ("Streaming apps", "app", "regex", r"^(netflix|tv|spotify|music|podcasts|prime video|disney\+)$", "leisure", "low", "Media apps"),
]

SEED_VERSION = 2


def detect_local_device_id() -> str:
    host = socket.gethostname().split(".")[0].lower()
    return re.sub(r"[^a-z0-9-]+", "-", host).strip("-") or "personal-mac"


def _add_categories(db: Session) -> None:
    existing = {c.key for c in db.query(ActivityCategory)}
    for i, (key, name, color, productive, desc) in enumerate(DEFAULT_CATEGORIES):
        if key not in existing:
            db.add(ActivityCategory(key=key, name=name, color=color, is_productive=productive, description=desc, sort_order=i))
    db.flush()


def _upgrade_v2(db: Session) -> None:
    """Add Leisure/Drift categories, subcategories on default rules, new rules."""
    _add_categories(db)
    # Keep "Other" last in the list.
    other = db.get(ActivityCategory, "other")
    if other:
        other.sort_order = 99
    subcats = {name: sub for name, *_rest, sub in DEFAULT_RULES}
    for r in db.query(ClassificationRule):
        if r.subcategory is None and r.name in subcats:
            r.subcategory = subcats[r.name]
    names = {r.name for r in db.query(ClassificationRule)}
    base = 200
    for i, (name, field, mt, pattern, cat, conf, sub) in enumerate(SEED_V2_RULES):
        if name not in names:
            db.add(ClassificationRule(name=name, field=field, match_type=mt, pattern=pattern, category_key=cat, confidence=conf, subcategory=sub, priority=base + i * 10))


def seed_defaults(db: Session) -> None:
    fresh = db.query(ActivityCategory).count() == 0
    if fresh:
        _add_categories(db)

    if db.query(ClassificationRule).count() == 0:
        for i, (name, field, mt, pattern, cat, conf, sub) in enumerate(DEFAULT_RULES):
            db.add(ClassificationRule(name=name, field=field, match_type=mt, pattern=pattern, category_key=cat, confidence=conf, subcategory=sub, priority=(i + 1) * 10))
        db.flush()

    ver_row = db.get(UserSetting, "_seed_version")
    version = int(ver_row.value) if ver_row else 1
    if version < 2:
        _upgrade_v2(db)
    if ver_row:
        ver_row.value = SEED_VERSION
    else:
        db.add(UserSetting(key="_seed_version", value=SEED_VERSION))

    local_id = detect_local_device_id()
    if db.get(Device, local_id) is None and db.query(Device).filter_by(is_work=False, kind="mac").count() == 0:
        db.add(Device(id=local_id, name="Personal Mac", kind="mac", is_work=False, monitoring_approved=True, store_titles=True))

    if db.get(CollectorStatus, "activitywatch") is None:
        db.add(CollectorStatus(key="activitywatch", enabled=True))
    db.commit()
