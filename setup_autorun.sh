#!/bin/bash
# Installs the World Cup 2026 notifier as a macOS LaunchAgent so it runs
# automatically in the background, starts at login, and restarts if it crashes.
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.azzam.wc2026notifier"
PLIST_SRC="$DIR/$LABEL.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$DIR/data"

# Substitute the real directory into the plist template.
sed "s#__DIR__#$DIR#g" "$PLIST_SRC" > "$PLIST_DEST"

# Reload cleanly.
launchctl unload "$PLIST_DEST" 2>/dev/null || true
launchctl load "$PLIST_DEST"

echo "Installed and started: $LABEL"
echo "Logs:    $DIR/data/notifier.log"
echo "Stop:    launchctl unload \"$PLIST_DEST\""
echo "Start:   launchctl load \"$PLIST_DEST\""
echo "Status:  launchctl list | grep $LABEL"
