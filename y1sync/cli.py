"""Orquestador. `y1sync sync` hace todo el trabajo de una pasada."""
from __future__ import annotations
import argparse, collections, sys, time
from pathlib import Path
from . import db, scan, audio, tags, genres, artwork, playlists, plays, macos, stations, doctor
from .config import CARD_ROOT, MUSIC_DIR, ARTWORK_MAX
from .util import setup_logging, log, nfc, human

def wait_for_card(timeout: int = 0) -> Path | None:
    """Espera a que la tarjeta se monte. timeout 0 = no esperar."""
    deadline = time.time() + timeout
    while True:
        if (CARD_ROOT / MUSIC_DIR).is_dir():
            return CARD_ROOT
        if time.time() >= deadline:
            return None
        time.sleep(2)

def sync(card: Path, *, dry: bool = False, no_mb: bool = False,
         no_convert: bool = False, no_art: bool = False) -> int:
    con = db.connect()
    stats = collections.Counter()
    prefijo = "[simulacion] " if dry else ""

    if not dry:
        macos.clean(card / MUSIC_DIR)
        macos.prevent(card)

    tocados: list[Path] = []
    conocidas = db.known_paths(con)
    nuevos = [p for p in scan.walk_music(card) if str(p.relative_to(card)) not in conocidas]
    log.info("%sArchivos nuevos detectados: %d", prefijo, len(nuevos))

    por_album = collections.defaultdict(list)
    for p in nuevos:
        rel = p.relative_to(card).parts
        por_album[(nfc(rel[1] if len(rel) > 1 else ""),
                   nfc(rel[2] if len(rel) > 2 else ""))].append(p)

    for (artista, album), rutas in sorted(por_album.items()):
        log.info("%sAlbum nuevo: %s / %s  (%d pistas)", prefijo, artista, album, len(rutas))
        filas = []
        leidas = {f["path"]: f for f in scan.read_many(card, rutas)}
        for p in rutas:
            fila = leidas.get(str(p.relative_to(card)))
            if not fila:
                log.warning("  no se pudo leer %s", p.name); continue

            if not no_convert and audio.needs_conversion(fila["samplerate"], fila["bits"]):
                log.info("  %s esta a %d Hz/%d bits", p.name, fila["samplerate"], fila["bits"])
                if not dry:
                    ok, antes, despues = audio.convert(p, card, fila["samplerate"], fila["bits"])
                    tocados.append(p)
                    if ok:
                        stats["converted"] += 1
                        stats["bytes_saved"] += antes - despues
                        fila = scan.read_track(card, p) or fila
                else:
                    stats["converted"] += 1

            if not no_art and fila.get("art_w") and fila["art_w"] > ARTWORK_MAX:
                if not dry:
                    cambiado, detalle = artwork.process_flac(p)
                    tocados.append(p)
                    if cambiado:
                        log.info("  caratula %s: %s", p.name, detalle)
                        stats["art_resized"] += 1
                        fila = scan.read_track(card, p) or fila
                else:
                    stats["art_resized"] += 1
            filas.append(fila)

        if not filas:
            continue

        # ALBUMARTIST contaminado dentro del propio album
        for fila, correcto in tags.find_contamination(filas):
            log.info("  albumartist %r -> %r en %s",
                     fila["albumartist"], correcto, fila["filename"])
            if not dry and tags.write_tag(card / fila["path"], "ALBUMARTIST", correcto):
                tocados.append(card / fila["path"])
                fila["albumartist"] = correcto
                stats["tags_fixed"] += 1

        # Genero
        if not no_mb and not any(f["genre"] for f in filas):
            g = genres.resolve(con, artista, filas[0]["album"] or album)
            if g:
                log.info("  genero -> %s", g)
                for fila in filas:
                    if not dry and tags.write_tag(card / fila["path"], "GENRE", g):
                        tocados.append(card / fila["path"])
                        fila["genre"] = g
                        stats["tags_fixed"] += 1
                    elif dry:
                        fila["genre"] = g

        if not dry:
            for fila in filas:
                cols = ",".join(fila)
                con.execute(f"INSERT OR REPLACE INTO tracks({cols}) "
                            f"VALUES({','.join('?' * len(fila))})", tuple(fila.values()))
            con.commit()
        stats["new_tracks"] += len(filas)
        stats["new_albums"] += 1

    if not dry:
        playlists.repair(con, card)
        playlists.reindex(con, card)
        stats["plays_added"] = plays.ingest(con, card)
        stations.generar(con, card)
        # La segunda limpieza solo hace falta si escribimos en la tarjeta;
        # cada pasada recorre el arbol entero por USB.
        if tocados:
            n = macos.clean_paths(tocados)
            if n:
                log.info("Limpieza dirigida: %d companeros ._ eliminados", n)
        con.execute("INSERT INTO sync_log(new_tracks,converted,art_resized,tags_fixed,"
                    "plays_added,notes) VALUES(?,?,?,?,?,?)",
                    (stats["new_tracks"], stats["converted"], stats["art_resized"],
                     stats["tags_fixed"], stats["plays_added"],
                     f"{stats['new_albums']} albumes nuevos"))
        con.commit()

    total = con.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    log.info("-" * 58)
    log.info("%sAlbumes nuevos   : %d", prefijo, stats["new_albums"])
    log.info("%sPistas nuevas    : %d", prefijo, stats["new_tracks"])
    log.info("%sConvertidas      : %d  (%s recuperados)", prefijo,
             stats["converted"], human(stats["bytes_saved"]))
    log.info("%sCaratulas ajustadas: %d", prefijo, stats["art_resized"])
    log.info("%sEtiquetas corregidas: %d", prefijo, stats["tags_fixed"])
    log.info("%sReproducciones nuevas: %d", prefijo, stats["plays_added"])
    log.info("Biblioteca total : %d pistas", total)
    con.close()
    return 0

def normalize(card: Path, *, dry: bool = False, workers: int = 4) -> int:
    """Lleva TODA la biblioteca a 44,1 kHz / 16 bits.

    El Y1 entrega 16 bits fijos, asi que los 24 bits de origen se descartan en
    la reproduccion de todos modos: reducirlos no cambia lo que se oye en este
    aparato y libera bastante espacio. Los originales quedan en BACKUP_DIR.
    """
    con = db.connect()
    filas = con.execute(
        "SELECT path, samplerate, bits FROM tracks "
        "WHERE samplerate>0 AND (samplerate<>? OR bits>?) ORDER BY path",
        (44100, 16)).fetchall()
    items, faltan = [], 0
    for r in filas:
        p = card / r["path"]
        if p.exists():
            items.append((p, r["samplerate"], r["bits"]))
        else:
            faltan += 1
    total = sum(p.stat().st_size for p, _, _ in items)
    log.info("Pistas a normalizar: %d  (%s)%s", len(items), human(total),
             f"  [{faltan} ya no estan en la tarjeta]" if faltan else "")
    if not items:
        return 0
    if dry:
        for p, rate, bits in items[:10]:
            log.info("  [simulacion] %s  %d Hz / %d bits", p.name[:52], rate, bits)
        if len(items) > 10:
            log.info("  ... y %d mas", len(items) - 10)
        return 0

    ok, antes, despues = audio.convert_many(items, card, workers)
    # refrescar la base con los valores reales tras convertir
    actualizadas = 0
    for p, _, _ in items:
        fila = scan.read_track(card, p)
        if fila:
            con.execute("UPDATE tracks SET samplerate=?, bits=?, filesize=? WHERE path=?",
                        (fila["samplerate"], fila["bits"], fila["filesize"], fila["path"]))
            actualizadas += 1
    con.commit()
    macos.clean_paths([p for p, _, _ in items])
    log.info("-" * 58)
    log.info("Convertidas   : %d de %d", ok, len(items))
    log.info("Espacio       : %s -> %s  (%s liberados)",
             human(antes), human(despues), human(antes - despues))
    log.info("Base al dia   : %d filas", actualizadas)
    con.close()
    return 0

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="y1sync", description="Gestor de la biblioteca del Innioasis Y1")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="sincroniza la tarjeta")
    s.add_argument("--path", type=Path, help="ruta de la tarjeta (por defecto la detecta)")
    s.add_argument("--wait", type=int, default=0, metavar="SEG", help="espera a que se monte")
    s.add_argument("--dry-run", action="store_true", help="no escribe nada, solo informa")
    s.add_argument("--no-musicbrainz", action="store_true")
    s.add_argument("--no-convert", action="store_true")
    s.add_argument("--no-artwork", action="store_true")
    s.add_argument("-v", "--verbose", action="store_true")
    st = sub.add_parser("stats", help="resumen de la biblioteca")
    st.add_argument("-v", "--verbose", action="store_true")
    ra = sub.add_parser("stations", help="regenera las emisoras desde el historial")
    ra.add_argument("--path", type=Path)
    ra.add_argument("--limit", type=int, default=150)
    ra.add_argument("-v", "--verbose", action="store_true")
    dc = sub.add_parser("doctor", help="revisa la salud de la biblioteca")
    dc.add_argument("--path", type=Path)
    dc.add_argument("--deep", action="store_true",
                    help="decodifica cada archivo para detectar corrupcion (lento)")
    dc.add_argument("--detail", type=int, default=5, metavar="N",
                    help="cuantos ejemplos mostrar por problema")
    dc.add_argument("-j", "--workers", type=int, default=8)
    dc.add_argument("-v", "--verbose", action="store_true")
    nz = sub.add_parser("normalize", help="lleva toda la biblioteca a 44,1 kHz / 16 bits")
    nz.add_argument("--path", type=Path)
    nz.add_argument("--dry-run", action="store_true")
    nz.add_argument("-j", "--workers", type=int, default=4)
    nz.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    setup_logging(getattr(a, "verbose", False))

    if a.cmd == "stats":
        con = db.connect()
        for q, t in [("SELECT COUNT(*) FROM tracks", "pistas"),
                     ("SELECT COUNT(DISTINCT folder_artist) FROM tracks", "artistas"),
                     ("SELECT COUNT(*) FROM plays", "reproducciones")]:
            print(f"  {t:<16}{con.execute(q).fetchone()[0]}")
        print("\n  Por genero:")
        for r in con.execute("SELECT genre,COUNT(*) c FROM tracks WHERE genre<>'' "
                             "GROUP BY genre ORDER BY c DESC"):
            print(f"    {r[0]:<20}{r[1]}")
        return 0

    if a.cmd == "doctor":
        card = a.path or CARD_ROOT
        if not (card / MUSIC_DIR).is_dir():
            log.error("Tarjeta no encontrada en %s", card)
            return 1
        h = doctor.revisar(card, profundo=a.deep, workers=a.workers)
        # Codigo de salida distinto de cero si hay algo que mirar: asi sirve
        # dentro de un script de sincronizacion automatica.
        return 1 if doctor.informe(h, detalle=a.detail) else 0

    if a.cmd == "stations":
        card = a.path or CARD_ROOT
        if not (card / MUSIC_DIR).is_dir():
            log.error("Tarjeta no encontrada.")
            return 1
        con = db.connect()
        stations.generar(con, card, a.limit)
        con.close()
        return 0

    if a.cmd == "normalize":
        card = a.path or CARD_ROOT
        if not (card / MUSIC_DIR).is_dir():
            log.error("Tarjeta no encontrada.")
            return 1
        return normalize(card, dry=a.dry_run, workers=a.workers)

    card = a.path or wait_for_card(a.wait)
    if not card or not (card / MUSIC_DIR).is_dir():
        log.error("Tarjeta no encontrada. ¿Esta el Y1 conectado en modo almacenamiento?")
        return 1
    return sync(card, dry=a.dry_run, no_mb=a.no_musicbrainz,
                no_convert=a.no_convert, no_art=a.no_artwork)

if __name__ == "__main__":
    sys.exit(main())
