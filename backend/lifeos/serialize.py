"""Serialisation helpers: ORM rows → dicts, naive-UTC datetimes → 'Z' ISO strings."""

from __future__ import annotations

import dataclasses
import json
from datetime import date, datetime
from typing import Any

from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.responses import JSONResponse
from sqlalchemy import inspect

from lifeos.timeutil import iso_utc, to_utc_naive

# FastAPI runs jsonable_encoder on every returned value before the response
# class sees it. Register our convention there: datetimes are UTC and say so.
ENCODERS_BY_TYPE[datetime] = lambda d: iso_utc(to_utc_naive(d))


def jsonify(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return iso_utc(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [jsonify(v) for v in obj]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return jsonify(dataclasses.asdict(obj))
    if hasattr(obj, "__table__"):
        return jsonify(row(obj))
    return obj


HIDDEN_COLUMNS = {"token_hash"}


def row(obj: Any, *extra: str) -> dict[str, Any]:
    out = {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs if c.key not in HIDDEN_COLUMNS}
    for name in extra:
        out[name] = getattr(obj, name)
    return out


class UTCJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(jsonify(content), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
