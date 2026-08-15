#!/bin/bash
# Se ejecuta al montarse cualquier volumen. Sale en silencio si no es el Y1.
set -uo pipefail
CARD="/Volumes/NO NAME"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="/tmp/y1sync.lock"

[ -d "$CARD/Music" ] || exit 0
# Evita ejecuciones solapadas si el volumen rebota
if ! mkdir "$LOCK" 2>/dev/null; then exit 0; fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

echo "=== $(date '+%Y-%m-%d %H:%M:%S')  tarjeta detectada ==="
# El volumen puede tardar en estar listo del todo
sleep 5
cd "$REPO"
PY="$(command -v python3)"
"$PY" -m y1sync sync --path "$CARD" 2>&1 | grep -vE "blake2|hashlib|unsupported hash"
echo "=== fin ==="
