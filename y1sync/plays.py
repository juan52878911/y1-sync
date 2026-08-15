"""Ingesta del historial de reproduccion que escribe Rockbox.

Formato de .rockbox/playback.log:
    unix_ts:ms_escuchados:ms_totales:/sdcard/ruta
"""
from __future__ import annotations
from pathlib import Path
from .util import log

# El reloj del Y1 venia de fabrica en 2022 y se reiniciaba en cada arranque.
# Las marcas anteriores al ajuste no son fiables, pero que canción y cuanto si.
CLOCK_FIXED_TS = 1786757400   # 2026-08-14 21:00 COT

def ingest(con, card: Path) -> int:
    logf = card / ".rockbox" / "playback.log"
    if not logf.exists():
        return 0
    nuevas = 0
    for line in logf.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split(":", 3)
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        ts = int(parts[0])
        msp = int(parts[1]) if parts[1].isdigit() else 0
        mst = int(parts[2]) if parts[2].isdigit() else 0
        path = parts[3].strip()
        if not path:
            continue
        pct = round(100 * msp / mst, 1) if mst else 0
        row = con.execute("SELECT id FROM tracks WHERE device_path=?", (path,)).fetchone()
        try:
            con.execute(
                "INSERT INTO plays(ts,ts_reliable,ms_played,ms_total,pct,completed,"
                "device_path,track_id) VALUES(?,?,?,?,?,?,?,?)",
                (ts, 1 if ts >= CLOCK_FIXED_TS else 0, msp, mst, pct,
                 1 if pct >= 50 else 0, path, row[0] if row else None))
            nuevas += 1
        except Exception:
            pass   # UNIQUE: ya estaba registrada, la ingesta es idempotente
    con.commit()
    if nuevas:
        log.info("Historial: %d reproducciones nuevas", nuevas)
    return nuevas
