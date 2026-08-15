"""Asignacion de genero: MusicBrainz + mapeo ponderado a cubos usables."""
from __future__ import annotations
import collections, json, re, time, urllib.parse, urllib.request
from .config import (MB_BASE, MB_UA, MB_DELAY, MB_MIN_SCORE,
                     GENRE_RULES, GENRE_NOISE, GENRE_OVERRIDES)
from .util import nfc, log

_NOISE = re.compile(GENRE_NOISE, re.I)
_OVR = {nfc(k): v for k, v in GENRE_OVERRIDES.items()}

def _get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": MB_UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as f:
            return json.load(f)
    except Exception as e:
        log.debug("MusicBrainz falló: %s", e)
        return None

def _q(s: str) -> str:
    return urllib.parse.quote(s.replace('"', "").replace("\\", ""))

def _terms(entity: dict) -> list[str]:
    return ([g["name"] for g in entity.get("genres", [])] +
            [t["name"] for t in sorted(entity.get("tags", []),
                                       key=lambda x: -x.get("count", 0))][:8])

def lookup(con, kind: str, artist: str, album: str = "") -> list[str]:
    """Consulta con cache en la base. kind: 'artist' | 'album'."""
    key = f"{kind}|{artist}" + (f"|{album}" if album else "")
    row = con.execute("SELECT payload FROM mb_cache WHERE key=?", (key,)).fetchone()
    if row:
        return json.loads(row[0])
    terms: list[str] = []
    if kind == "artist":
        d = _get(f"{MB_BASE}/artist?query=artist:%22{_q(artist)}%22&fmt=json&limit=1")
        time.sleep(MB_DELAY)
        if d and d.get("artists"):
            a = d["artists"][0]
            if a.get("score", 0) >= MB_MIN_SCORE:
                det = _get(f"{MB_BASE}/artist/{a['id']}?inc=genres+tags&fmt=json")
                time.sleep(MB_DELAY)
                if det:
                    terms = _terms(det)
    else:
        d = _get(f"{MB_BASE}/release-group?query=artist:%22{_q(artist)}%22"
                 f"%20AND%20releasegroup:%22{_q(album)}%22&fmt=json&limit=1")
        time.sleep(MB_DELAY)
        if d and d.get("release-groups"):
            rg = d["release-groups"][0]
            if rg.get("score", 0) >= MB_MIN_SCORE:
                det = _get(f"{MB_BASE}/release-group/{rg['id']}?inc=genres+tags&fmt=json")
                time.sleep(MB_DELAY)
                if det:
                    terms = _terms(det)
    con.execute("INSERT OR REPLACE INTO mb_cache(key,payload) VALUES(?,?)",
                (key, json.dumps(terms, ensure_ascii=False)))
    con.commit()
    return terms

def bucket(terms: list[str]) -> str | None:
    """Colapsa terminos crudos a un cubo por puntuacion ponderada.

    Se usa puntuacion y no primera coincidencia porque tags secundarios como
    `dance` o `alternative metal` aparecen en medio catalogo y, con orden
    simple, arrastraban a Skrillex a Metalcore y a Muse a Metal.
    """
    txt = " | ".join(t.lower() for t in terms if not _NOISE.search(t))
    if not txt:
        return None
    score: collections.Counter[str] = collections.Counter()
    for name, pat, weight in GENRE_RULES:
        if re.search(pat, txt):
            score[name] += weight
    return score.most_common(1)[0][0] if score else None

def resolve(con, artist: str, album: str) -> str | None:
    """Genero definitivo para un album. Anulacion > album > artista."""
    a = nfc(artist)
    if a in _OVR:
        return _OVR[a]
    terms = lookup(con, "album", artist, album)
    g = bucket(terms)
    if g:
        return g
    return bucket(lookup(con, "artist", artist))
