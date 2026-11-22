# Claude Code → LifeOS hooks (optional, Level 3)

LifeOS works fine with manual session updates. These hooks just save clicks for
**Claude Code** sessions. Claude Desktop and claude.ai in the browser have no
equivalent hook interface, so keep using the Sessions board for those.

Reference: https://docs.claude.com/en/docs/claude-code/hooks

## State mapping

| Claude Code hook   | LifeOS session state                                         |
| ------------------ | ------------------------------------------------------------ |
| `SessionStart`     | `ready` (registered automatically, project = folder name)     |
| `UserPromptSubmit` | `generating`                                                  |
| `PostToolUse`      | `generating` (keeps "last interaction" fresh)                 |
| `Notification`     | permission request → `waiting` + needs attention; idle → needs attention |
| `Stop`             | `ready` + needs attention ("review Claude's output")         |
| `SessionEnd`       | `completed`                                                   |

## Install

Add to `~/.claude/settings.json` (merge with any hooks you already have, and
replace the path with your checkout's absolute path):

```json
{
  "hooks": {
    "SessionStart":     [{ "hooks": [{ "type": "command", "command": "python3 /ABS/PATH/life-os/hooks/lifeos_hook.py" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python3 /ABS/PATH/life-os/hooks/lifeos_hook.py" }] }],
    "Notification":     [{ "hooks": [{ "type": "command", "command": "python3 /ABS/PATH/life-os/hooks/lifeos_hook.py" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "python3 /ABS/PATH/life-os/hooks/lifeos_hook.py" }] }],
    "SessionEnd":       [{ "hooks": [{ "type": "command", "command": "python3 /ABS/PATH/life-os/hooks/lifeos_hook.py" }] }]
  }
}
```

`PostToolUse` is optional: it fires on every tool call, so add it only if you
want "last interaction" to stay fresh during long tool loops.

Run `/hooks` inside Claude Code to confirm they are registered.

## Privacy

- Only `hook_event_name`, `session_id`, `cwd`, and notification text are sent.
- Prompts are **not** sent unless you set `LIFEOS_HOOK_SEND_PROMPT=1`, and LifeOS
  only stores the first line as the session objective when
  *Settings → Privacy → Capture first prompt line* is on.
- Requests go to `http://127.0.0.1:8765` only (override with `LIFEOS_URL`).
- The hook times out after 0.8s and always exits 0.

## Test it

```bash
echo '{"hook_event_name":"Stop","session_id":"test-1","cwd":"'"$PWD"'"}' | python3 hooks/lifeos_hook.py
```

The session should appear on the Sessions board as *Ready — needs attention*.
