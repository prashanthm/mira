#!/usr/bin/env bash
# Install Mira's own nightly insight job (independent of Sentinel's trading daemon).
# Runs at 17:40 ET on weekdays — after Sentinel's 17:30 record + 17:35 grade jobs.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PY="$REPO_DIR/.venv/bin/python"
CONFIG="$REPO_DIR/configs/sentinel.yaml"
LABEL="com.pmuniraju.mira.insights"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$REPO_DIR/logs"

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV_PY</string>
    <string>-m</string>
    <string>mira.cli</string>
    <string>insights</string>
    <string>--config</string>
    <string>$CONFIG</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_DIR</string>
  <key>EnvironmentVariables</key>
  <dict><key>TZ</key><string>America/New_York</string><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>40</integer><key>Weekday</key><integer>1</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>40</integer><key>Weekday</key><integer>2</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>40</integer><key>Weekday</key><integer>3</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>40</integer><key>Weekday</key><integer>4</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>40</integer><key>Weekday</key><integer>5</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$LOG_DIR/mira.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/mira.err.log</string>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed $LABEL (weekdays 17:40 ET). Config: $CONFIG"
echo "Logs: $LOG_DIR/mira.{out,err}.log"
