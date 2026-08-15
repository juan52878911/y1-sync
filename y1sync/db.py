"""Esquema y acceso a la base SQLite."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks(
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE,            -- relativa a la raiz de la tarjeta
  device_path TEXT,            -- /sdcard/... tal como la ve Rockbox
  folder_artist TEXT, folder_album TEXT, filename TEXT,
  title TEXT, artist TEXT, albumartist TEXT, album TEXT,
  tracknumber INT, discnumber INT, year TEXT, genre TEXT,
  duration REAL, samplerate INT, bits INT, channels INT,
  filesize INT, format TEXT,
  art_w INT, art_h INT,
  added_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS i_fa  ON tracks(folder_artist);
CREATE INDEX IF NOT EXISTS i_aa  ON tracks(albumartist);
CREATE INDEX IF NOT EXISTS i_alb ON tracks(album);
CREATE INDEX IF NOT EXISTS i_gen ON tracks(genre);

CREATE TABLE IF NOT EXISTS playlists(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE, n INT);
CREATE TABLE IF NOT EXISTS playlist_tracks(
  playlist_id INT, track_id INT, position INT);

CREATE TABLE IF NOT EXISTS plays(
  id INTEGER PRIMARY KEY,
  ts INTEGER, ts_reliable INTEGER,
  ms_played INTEGER, ms_total INTEGER, pct REAL, completed INTEGER,
  device_path TEXT, track_id INTEGER,
  UNIQUE(ts, device_path, ms_played));
CREATE INDEX IF NOT EXISTS i_pl_track ON plays(track_id);
CREATE INDEX IF NOT EXISTS i_pl_ts    ON plays(ts);

-- Cache de MusicBrainz para no repetir consultas entre sincronizaciones.
CREATE TABLE IF NOT EXISTS mb_cache(
  key TEXT PRIMARY KEY,        -- 'artist|X' o 'album|X|Y'
  payload TEXT,                -- JSON con genres y tags
  fetched_at TEXT DEFAULT (datetime('now')));

-- Registro de cada sincronizacion, para poder auditar que hizo.
CREATE TABLE IF NOT EXISTS sync_log(
  id INTEGER PRIMARY KEY,
  started_at TEXT DEFAULT (datetime('now')),
  new_tracks INT, converted INT, art_resized INT,
  tags_fixed INT, plays_added INT, notes TEXT);
"""

# Columnas anadidas despues de la primera version del esquema. CREATE TABLE
# IF NOT EXISTS no toca una tabla existente, asi que hay que migrarla a mano.
MIGRATIONS = {
    "tracks": [
        ("art_w", "INTEGER"),
        ("art_h", "INTEGER"),
        ("added_at", "TEXT"),
    ],
}

def _migrate(con: sqlite3.Connection) -> list[str]:
    aplicadas = []
    for tabla, columnas in MIGRATIONS.items():
        existe = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tabla,)
        ).fetchone()
        if not existe:
            continue
        actuales = {r[1] for r in con.execute(f"PRAGMA table_info({tabla})")}
        for nombre, tipo in columnas:
            if nombre not in actuales:
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {tipo}")
                aplicadas.append(f"{tabla}.{nombre}")
    if aplicadas:
        con.commit()
    return aplicadas

def connect(path: Path | None = None) -> sqlite3.Connection:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    nuevas = _migrate(con)
    if nuevas:
        from .util import log
        log.info("Base migrada: columnas anadidas %s", ", ".join(nuevas))
    return con

def known_paths(con: sqlite3.Connection) -> set[str]:
    return {r[0] for r in con.execute("SELECT path FROM tracks")}

def known_albums(con: sqlite3.Connection) -> set[tuple[str, str]]:
    return {(r[0], r[1]) for r in
            con.execute("SELECT DISTINCT folder_artist, folder_album FROM tracks")}
