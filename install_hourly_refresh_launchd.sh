#!/usr/bin/env bash
# Install macOS launchd job to refresh dashboard JSON every 30 minutes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_LABEL="com.backtest.hourlyrefresh"
AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$AGENT_DIR/${AGENT_LABEL}.plist"
LOG_DIR="$ROOT/logs"
OUT_LOG="$LOG_DIR/hourly_refresh.out.log"
ERR_LOG="$LOG_DIR/hourly_refresh.err.log"

mkdir -p "$AGENT_DIR" "$LOG_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${AGENT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${ROOT}/hourly_dashboard_refresh.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${OUT_LOG}</string>
  <key>StandardErrorPath</key>
  <string>${ERR_LOG}</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Installed launchd job: ${AGENT_LABEL}"
echo "plist: ${PLIST_PATH}"
echo "stdout: ${OUT_LOG}"
echo "stderr: ${ERR_LOG}"
echo "Verify: launchctl list | grep ${AGENT_LABEL}"
