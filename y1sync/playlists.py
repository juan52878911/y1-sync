"""Reparacion de playlists .m3u/.m3u8.

Tres fallos habituales, todos vistos en esta biblioteca:
  1. Rutas sin el prefijo /sdcard que Rockbox necesita.
  2. Carpetas o archivos renombrados despues de crear la lista.
  3. Extension .m3u con contenido UTF-8: Rockbox la lee con el codepage
     configurado y destroza los acentos. .m3u8 siempre se lee como UTF-8.
"""
from __future__ import annotations
import collections, re, unicodedata
from pathlib import Path
from .config import DEVICE_PREFIX
from .util import log, device_path

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())

def _index(con) -> tuple[dict, dict]:
    by_title, by_name = collections.defaultdict(list), collections.defaultdict(list)
    for r in con.execute("SELECT device_path, folder_artist, title, filename FROM tracks"):
        if r["title"]:
            by_title[(_norm(r["folder_artist"]), _norm(r["title"]))].append(r["device_path"])
        by_name[r["filename"]].append(r["device_path"])
    return by_title, by_name

def repair(con, card: Path) -> dict:
    pl_dir = card / "Playlists"
    if not pl_dir.is_dir():
        return {"files": 0, "ok": 0, "remapped": 0, "lost": 0}
    by_title, by_name = _index(con)
    valid = {r[0] for r in con.execute("SELECT device_path FROM tracks")}
    stats = collections.Counter()
    backup = card / "Playlists_backup"
    for src in sorted(pl_dir.glob("*.m3u*")):
        if src.name.startswith("._"):
            continue
        out = []
        for line in src.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cand = line if line.startswith(DEVICE_PREFIX) else device_path(line.lstrip("/"))
            if cand in valid:
                out.append(cand); stats["ok"] += 1; continue
            # remapeo por titulo: sobrevive a renombrados de carpeta y archivo
            parts = line.split("/")
            artist = parts[2] if len(parts) >= 5 else (parts[1] if len(parts) > 1 else "")
            base = re.sub(r"^\d+\s*[-.]?\s*", "", Path(line).stem)
            hits = by_title.get((_norm(artist), _norm(base)), [])
            if len(hits) != 1:
                hits = by_name.get(Path(line).name, [])
            if len(hits) == 1:
                out.append(hits[0]); stats["remapped"] += 1
            else:
                stats["lost"] += 1
        dst = pl_dir / (src.stem + ".m3u8")
        dst.write_text("\n".join(out) + "\n", encoding="utf-8")
        if src.suffix.lower() == ".m3u":
            backup.mkdir(exist_ok=True)
            src.replace(backup / src.name)
        stats["files"] += 1
    if stats["files"]:
        log.info("Playlists: %d archivos, %d ok, %d remapeadas, %d perdidas",
                 stats["files"], stats["ok"], stats["remapped"], stats["lost"])
    return dict(stats)

def reindex(con, card: Path) -> None:
    """Vuelca las playlists a la base para poder consultarlas."""
    con.execute("DELETE FROM playlist_tracks"); con.execute("DELETE FROM playlists")
    pl_dir = card / "Playlists"
    if not pl_dir.is_dir():
        return
    for f in sorted(pl_dir.glob("*.m3u8")):
        if f.name.startswith("._"):
            continue
        entries = [l.strip() for l in f.read_text(encoding="utf-8", errors="replace").splitlines()
                   if l.strip() and not l.startswith("#")]
        con.execute("INSERT OR IGNORE INTO playlists(name,n) VALUES(?,?)", (f.stem, len(entries)))
        pid = con.execute("SELECT id FROM playlists WHERE name=?", (f.stem,)).fetchone()[0]
        for i, e in enumerate(entries):
            t = con.execute("SELECT id FROM tracks WHERE device_path=?", (e,)).fetchone()
            if t:
                con.execute("INSERT INTO playlist_tracks VALUES(?,?,?)", (pid, t[0], i))
    con.commit()
