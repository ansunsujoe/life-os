#!/usr/bin/env bash
# Install the LifeOS collector on another Mac (not the hub).
#   ./install-collector-mac.sh --hub http://MacBook-Pro-3.local:8765 --token lfs_xxx
#   ./install-collector-mac.sh --export-dir ~/LifeOS-outbox --config-file ./lifeos-collector-config-<id>.json
#   ./install-collector-mac.sh --uninstall
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"; [ -d "$BACKEND" ] || BACKEND="$ROOT/../backend"
LABEL="com.lifeos.collector"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.lifeos-collector/collector.log"

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true; rm -f "$PLIST"
  echo "Collector removed (settings remain in ~/.lifeos-collector)."; exit 0
fi

curl -sf -m 3 http://localhost:5600/api/0/info >/dev/null || { echo "Start ActivityWatch first (brew install --cask activitywatch)."; exit 1; }
UV="$(command -v uv)" || { echo "Install uv first: https://docs.astral.sh/uv/"; exit 1; }
cd "$BACKEND" && "$UV" sync --no-dev -q
"$UV" run --no-dev lifeos-collect setup "$@"
"$UV" run --no-dev lifeos-collect test

mkdir -p "$(dirname "$LOG")" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$BACKEND</string>
  <key>ProgramArguments</key><array><string>$UV</string><string>run</string><string>--no-dev</string><string>lifeos-collect</string><string>run</string><string>--every</string><string>300</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string><key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Collector running. Log: $LOG"
