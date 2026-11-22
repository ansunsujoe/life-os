#!/usr/bin/env bash
# Install LifeOS as macOS launchd user agents (personal Mac only).
#   scripts/install-launchd.sh          API + UI on 127.0.0.1 only
#   scripts/install-launchd.sh --lan    also accept collectors from other computers on the
#                                       home network (only the token-protected /api/collect
#                                       endpoints are reachable; the dashboard stays local)
#   scripts/install-launchd.sh --uninstall
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="${LIFEOS_HOME:-$HOME/LifeOS}/logs"
API_LABEL="com.lifeos.api"
WEB_LABEL="com.lifeos.web"

uninstall() {
  for l in "$API_LABEL" "$WEB_LABEL"; do
    launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true
    rm -f "$AGENTS/$l.plist"
  done
  echo "LifeOS launchd agents removed."
}

if [[ "${1:-}" == "--uninstall" ]]; then uninstall; exit 0; fi
API_HOST="127.0.0.1"
if [[ "${1:-}" == "--lan" ]]; then API_HOST="0.0.0.0"; fi

UV="$(command -v uv)"; PNPM="$(command -v pnpm || command -v npm)"
mkdir -p "$AGENTS" "$LOGS"

echo "Building frontend…"
(cd "$ROOT/frontend" && "$PNPM" install && "$PNPM" run build)

write_plist() { # label, workdir, host, command...
  local label=$1 wd=$2 host=$3; shift 3
  local args=""
  for a in "$@"; do args+="    <string>$a</string>"$'\n'; done
  cat > "$AGENTS/$label.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>WorkingDirectory</key><string>$wd</string>
  <key>ProgramArguments</key>
  <array>
$args  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>LIFEOS_HOST</key><string>$host</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOGS/$label.log</string>
  <key>StandardErrorPath</key><string>$LOGS/$label.err.log</string>
</dict>
</plist>
EOF
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  # Wait until the old instance is really gone, or bootstrap fails with "Input/output error".
  for _ in $(seq 1 30); do launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1 || break; sleep 0.5; done
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$label.plist"
}

write_plist "$API_LABEL" "$ROOT/backend" "$API_HOST" "$UV" run lifeos
write_plist "$WEB_LABEL" "$ROOT/frontend" "127.0.0.1" "$PNPM" run start

echo "LifeOS is running: http://localhost:3000  (API on $API_HOST:8765)"
if [[ "$API_HOST" == "0.0.0.0" ]]; then
  echo "Collectors on your home network can use: http://$(scutil --get LocalHostName).local:8765  or  http://$(ipconfig getifaddr en0 2>/dev/null):8765"
fi
echo "Logs: $LOGS"
