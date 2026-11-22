"""Tiny additive migrations for SQLite (new nullable columns only).

`create_all` creates missing tables but never alters existing ones, so columns
added after a database was first created are applied here, idempotently.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("activity_events", "subcategory", "VARCHAR(64)"),
    ("activity_events", "pattern_category", "VARCHAR(32)"),
    ("classification_rules", "subcategory", "VARCHAR(64)"),
    ("devices", "token_hash", "VARCHAR(64)"),
    ("devices", "last_seen_at", "DATETIME"),
    ("devices", "collector_info", "JSON"),
]


def migrate(engine: Engine) -> list[str]:
    applied = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, column, ddl in ADDED_COLUMNS:
            if table not in insp.get_table_names():
                continue
            if column not in {c["name"] for c in insp.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                applied.append(f"{table}.{column}")
    return applied
