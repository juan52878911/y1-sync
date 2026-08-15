#!/bin/bash
# Instala el agente que sincroniza sola la tarjeta al conectarla.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HOME/Library/LaunchAgents/com.y1sync.automount.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" -e "s|__SHELL__|/bin/bash|g" \
    "$REPO/scripts/com.y1sync.automount.plist" > "$DEST"
launchctl unload "$DEST" 2>/dev/null || true
launchctl load "$DEST"
echo "Agente instalado. Conecta el Y1 y mira el registro:"
echo "   tail -f ~/Library/Logs/y1sync.log"
