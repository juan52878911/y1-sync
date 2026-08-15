#!/bin/bash
DEST="$HOME/Library/LaunchAgents/com.y1sync.automount.plist"
launchctl unload "$DEST" 2>/dev/null || true
rm -f "$DEST"
echo "Agente desinstalado."
