#!/bin/bash
# Wait until macOS WindowServer (the GUI) is fully up before starting the menu bar app
while ! pgrep -x "WindowServer" > /dev/null 2>&1; do
    sleep 2
done
sleep 8   # extra buffer for login to settle

# Resolve the app path relative to this script so it survives the project moving.
HERE="$(cd "$(dirname "$0")" && pwd)"
exec /usr/local/bin/python3.11 "$HERE/claude_usage_bar.py"
