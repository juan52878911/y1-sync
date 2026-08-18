"""Emisoras generadas desde el historial propio.

Reemplaza lo que Rockbox hace con `autoscore` y `playcount`, que en el port
del Y1 revienta (ver docs/rockbox-skin-render-crash.md). Aqui la puntuacion se
calcula en el Mac desde la tabla `plays` y se materializa como playlists
.m3u8, que Rockbox reproduce sin tocar la tagcache.
"""
from __future__ import annotations
from pathlib import Path
from .util import log

PREFIJO = "Radio - "

# Umbral de escucha "real": por debajo se considera que se salto la pista.
COMPLETA = 75

def puntuar(con) -> dict[int, dict]:
    """Puntua cada pista con historial.

    `score` es el porcentaje medio escuchado, el mismo principio que el
    autoscore de Rockbox. `completas` da confianza: una pista con una escucha
    entera pesa mas que otra con diez saltos.
    """
    filas = con.execute("""
        SELECT track_id,
               COUNT(*)                                    AS reproducciones,
               ROUND(AVG(pct), 1)                          AS score,
               MAX(ts)                                     AS ultima,
               SUM(CASE WHEN pct >= ? THEN 1 ELSE 0 END)   AS completas
        FROM plays
        WHERE track_id IS NOT NULL
        GROUP BY track_id
    """, (COMPLETA,)).fetchall()
    return {r["track_id"]: dict(r) for r in filas}

def _escribir(card: Path, nombre: str, device_paths: list[str]) -> int:
    if not device_paths:
        return 0
    d = card / "Playlists"
    d.mkdir(exist_ok=True)
    f = d / f"{PREFIJO}{nombre}.m3u8"
    f.write_text("\n".join(device_paths) + "\n", encoding="utf-8")
    return len(device_paths)

def generar(con, card: Path, limite: int = 150) -> dict[str, int]:
    """Genera las emisoras y devuelve cuantas pistas quedo en cada una."""
    st = puntuar(con)
    pistas = {r["id"]: r["device_path"]
              for r in con.execute("SELECT id, device_path FROM tracks")}

    def paths(ids):
        return [pistas[i] for i in ids if i in pistas]

    # --- Mis favoritas: escuchadas enteras al menos una vez y buen promedio
    fav = sorted((t for t in st.values() if t["completas"] >= 1 and t["score"] >= 60),
                 key=lambda t: (-t["completas"], -t["score"]))[:limite]

    # --- Joyas ocultas: te gustan pero casi nunca suenan
    joyas = sorted((t for t in st.values()
                    if t["score"] >= 70 and t["reproducciones"] <= 2),
                   key=lambda t: -t["score"])[:limite]

    # --- Rescate: hace mas tiempo que no suenan
    rescate = sorted(st.values(), key=lambda t: t["ultima"])[:limite]

    # --- Muy escuchadas
    top = sorted(st.values(), key=lambda t: -t["reproducciones"])[:limite]

    # --- Descartes: las saltas sistematicamente
    descartes = sorted((t for t in st.values()
                        if t["reproducciones"] >= 3 and t["score"] < 25),
                       key=lambda t: t["score"])[:limite]

    # --- Sin estrenar: nunca reproducidas
    sin_estrenar = [r["id"] for r in con.execute(
        "SELECT t.id FROM tracks t LEFT JOIN plays p ON p.track_id = t.id "
        "WHERE p.track_id IS NULL ORDER BY RANDOM() LIMIT ?", (limite,))]

    res = {}
    for nombre, ids in [
        ("Mis favoritas",   [t["track_id"] for t in fav]),
        ("Joyas ocultas",   [t["track_id"] for t in joyas]),
        ("Rescate",         [t["track_id"] for t in rescate]),
        ("Muy escuchadas",  [t["track_id"] for t in top]),
        ("Descartes",       [t["track_id"] for t in descartes]),
        ("Sin estrenar",    sin_estrenar),
    ]:
        res[nombre] = _escribir(card, nombre, paths(ids))

    hechas = {k: v for k, v in res.items() if v}
    if hechas:
        log.info("Emisoras: %s", "  ".join(f"{k}={v}" for k, v in hechas.items()))
    vacias = [k for k, v in res.items() if not v]
    if vacias:
        log.info("  (sin datos suficientes todavia: %s)", ", ".join(vacias))
    return res
