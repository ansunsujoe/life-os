#!/usr/bin/env python3
"""Claude Code hook → LifeOS session state.

Install by adding this script to the hook events in ~/.claude/settings.json
(see hooks/README.md). It is deliberately tiny, stdlib-only, and non-blocking:

- forwards only the fields LifeOS needs (event name, session id, cwd,
  notification message); transcript paths and tool inputs are never sent;
- the prompt text is sent only if LIFEOS_HOOK_SEND_PROMPT=1;
- talks to localhost only, with a sub-second timeout;
- always exits 0, so a stopped LifeOS server can never interfere with Claude.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

URL = os.environ.get("LIFEOS_URL", "http://127.0.0.1:8765") + "/api/sessions/hook"
FIELDS = ("hook_event_name", "session_id", "cwd", "message", "notification_type", "source", "reason")


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return
    body = {k: payload[k] for k in FIELDS if k in payload}
    if os.environ.get("LIFEOS_HOOK_SEND_PROMPT") == "1" and "prompt" in payload:
        body["prompt"] = str(payload["prompt"])[:500]
    if os.environ.get("LIFEOS_DEVICE_ID"):
        body["lifeos_device_id"] = os.environ["LIFEOS_DEVICE_ID"]
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=0.8).close()
    except Exception:  # noqa: BLE001 — never disturb Claude Code
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
