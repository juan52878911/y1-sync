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
    ids = {r[0]: r[1] for r in con.execute("SELECT device_path, id FROM tracks")}
    lote = []
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
        lote.append((ts, 1 if ts >= CLOCK_FIXED_TS else 0, msp, mst, pct,
                     1 if pct >= 50 else 0, path, ids.get(path)))
    antes = con.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
    # INSERT OR IGNORE deja que la restriccion UNIQUE descarte las repetidas;
    # asi la ingesta sigue siendo idempotente sin un try por fila.
    con.executemany(
        "INSERT OR IGNORE INTO plays(ts,ts_reliable,ms_played,ms_total,pct,"
        "completed,device_path,track_id) VALUES(?,?,?,?,?,?,?,?)", lote)
    con.commit()
    nuevas = con.execute("SELECT COUNT(*) FROM plays").fetchone()[0] - antes
    if nuevas:
        log.info("Historial: %d reproducciones nuevas", nuevas)
    return nuevas
