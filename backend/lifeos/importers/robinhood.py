"""Robinhood account-activity CSV parser (user-downloaded report).

No credentials, no unofficial API, no brokerage actions (spec §5.4).
Expected columns (Robinhood "Account activity" report):
    Activity Date, Process Date, Settle Date, Instrument, Description,
    Trans Code, Quantity, Price, Amount
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime

REQUIRED = {"activity date", "trans code", "amount"}
TRADE_CODES = {"Buy", "Sell", "BTO", "STC", "STO", "BTC", "OEXP", "OASGN", "OEXCS"}


@dataclass
class RobinhoodRow:
    source_key: str
    activity_date: date
    settle_date: date | None
    instrument: str
    description: str
    trans_code: str
    quantity: float | None
    price: float | None
    amount: float | None


def parse_money(value: str | None) -> float | None:
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    neg = v.startswith("(") and v.endswith(")") or v.startswith("-")
    num = re.sub(r"[^0-9.]", "", v)
    if not num or num == ".":
        return None
    try:
        f = float(num)
    except ValueError:
        return None
    return -f if neg else f


def parse_qty(value: str | None) -> float | None:
    if not value:
        return None
    m = re.match(r"^\s*(-?[0-9.,]+)", value)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    v = value.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def parse_csv(text: str) -> tuple[list[RobinhoodRow], int]:
    """Return (rows, skipped). Dedup keys are content hashes plus an occurrence
    index, so genuinely identical rows in one report are both kept while
    re-importing an overlapping report adds nothing."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or not REQUIRED <= {f.strip().lower() for f in reader.fieldnames}:
        raise ValueError("This doesn't look like a Robinhood account activity CSV (missing Activity Date / Trans Code / Amount columns).")
    fields = {f.strip().lower(): f for f in reader.fieldnames}

    def g(row: dict[str, str], name: str) -> str:
        key = fields.get(name)
        return (row.get(key) or "").strip() if key else ""

    rows: list[RobinhoodRow] = []
    seen: Counter[str] = Counter()
    skipped = 0
    for raw in reader:
        ad = parse_date(g(raw, "activity date"))
        if ad is None:
            skipped += 1  # footer/disclaimer lines
            continue
        norm = "|".join(g(raw, k) for k in ("activity date", "process date", "settle date", "instrument", "description", "trans code", "quantity", "price", "amount"))
        h = hashlib.sha256(norm.encode()).hexdigest()[:32]
        seen[h] += 1
        rows.append(
            RobinhoodRow(
                source_key=f"rh:{h}:{seen[h]}",
                activity_date=ad,
                settle_date=parse_date(g(raw, "settle date")),
                instrument=g(raw, "instrument"),
                description=g(raw, "description")[:500],
                trans_code=g(raw, "trans code"),
                quantity=parse_qty(g(raw, "quantity")),
                price=parse_money(g(raw, "price")),
                amount=parse_money(g(raw, "amount")),
            )
        )
    return rows, skipped
