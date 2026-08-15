"""Lectura de metadatos. metaflac para FLAC, ffprobe para el resto."""
from __future__ import annotations
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .util import run, nfc, device_path

AUDIO_EXT = (".flac", ".mp3", ".m4a", ".ogg", ".wav")


def _num(v) -> int | None:
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None


def read_flac(p: Path) -> dict:
    """Todo en UNA sola llamada a metaflac.

    `--list` vuelca STREAMINFO, VORBIS_COMMENT y PICTURE de golpe (9,6 ms).
    La version anterior gastaba dos procesos, metaflac + ffprobe, y ffprobe
    solo para leer las dimensiones de la caratula costaba 25 ms el.
    No se pueden combinar `--show-*` con `--list` (metaflac rechaza mezclar
    operaciones shorthand y major), de ahi que se parsee la salida de --list.
    """
    r = run(["metaflac", "--list",
             "--block-type=STREAMINFO,VORBIS_COMMENT,PICTURE", str(p)])
    if r.returncode != 0:
        return {}
    d: dict = {"format": "flac"}
    total = rate = 0
    for line in r.stdout.splitlines():
        s = line.strip()
        if s.startswith("sample_rate:"):
            rate = int(s.split(":", 1)[1].split()[0])
        elif s.startswith("bits-per-sample:"):
            d["bits"] = int(s.split(":", 1)[1])
        elif s.startswith("channels:"):
            d["channels"] = int(s.split(":", 1)[1])
        elif s.startswith("total samples:"):
            total = int(s.split(":", 1)[1])
        elif s.startswith("width:") and "art_w" not in d:
            d["art_w"] = int(s.split(":", 1)[1])
        elif s.startswith("height:") and "art_h" not in d:
            d["art_h"] = int(s.split(":", 1)[1])
        elif s.startswith("comment["):
            kv = s.split(":", 1)[1].strip() if ":" in s else ""
            if "=" in kv:
                k, v = kv.split("=", 1)
                d.setdefault(k.strip().upper(), v.strip())
    d["samplerate"] = rate
    d["duration"] = total / rate if rate else 0
    d.setdefault("bits", 0)
    d.setdefault("channels", 0)
    return d


def read_other(p: Path) -> dict:
    r = run(["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration:stream=sample_rate,channels:format_tags=title,artist,"
             "album_artist,album,track,disc,date,genre",
             "-of", "default=noprint_wrappers=1", str(p)])
    d = {"format": p.suffix.lstrip(".").lower(), "bits": 0}
    for line in r.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip().upper().replace("TAG:", "")] = v.strip()
    d["duration"] = float(d.get("DURATION") or 0)
    d["samplerate"] = int(d.get("SAMPLE_RATE") or 0)
    d["channels"] = int(d.get("CHANNELS") or 0)
    return d


def artwork_size(p: Path) -> tuple[int | None, int | None]:
    """Dimensiones de la caratula. Solo para formatos que no son FLAC."""
    r = run(["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)])
    parts = r.stdout.strip().split(",")
    if len(parts) >= 2 and parts[0].isdigit():
        return int(parts[0]), int(parts[1])
    return None, None


def read_track(card: Path, p: Path) -> dict | None:
    """Devuelve la fila lista para insertar en `tracks`."""
    es_flac = p.suffix.lower() == ".flac"
    d = read_flac(p) if es_flac else read_other(p)
    if not d:
        return None
    rel = p.relative_to(card)
    parts = rel.parts
    # En FLAC las dimensiones ya vienen en la misma llamada; para el resto,
    # que son una minoria, se paga el ffprobe extra.
    w, h = (d.get("art_w"), d.get("art_h")) if es_flac else artwork_size(p)
    return {
        "path": str(rel), "device_path": device_path(rel),
        "folder_artist": nfc(parts[1] if len(parts) > 1 else ""),
        "folder_album":  nfc(parts[2] if len(parts) > 2 else ""),
        "filename": p.name,
        "title": d.get("TITLE", ""), "artist": d.get("ARTIST", ""),
        "albumartist": d.get("ALBUMARTIST", d.get("ALBUM_ARTIST", "")),
        "album": d.get("ALBUM", ""),
        "tracknumber": _num(d.get("TRACKNUMBER", d.get("TRACK"))),
        "discnumber": _num(d.get("DISCNUMBER", d.get("DISC"))),
        "year": (d.get("DATE", "") or "")[:4], "genre": d.get("GENRE", ""),
        "duration": round(d.get("duration", 0), 2),
        "samplerate": d.get("samplerate", 0), "bits": d.get("bits", 0),
        "channels": d.get("channels", 0), "filesize": p.stat().st_size,
        "format": d.get("format", ""), "art_w": w, "art_h": h,
    }


def read_many(card: Path, paths: list[Path], workers: int = 8) -> list[dict]:
    """Lee varios archivos en paralelo.

    El coste es esperar a subprocesos y al USB, no calcular, asi que los
    hilos escalan bien pese al GIL.
    """
    if not paths:
        return []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return [r for r in ex.map(lambda x: read_track(card, x), paths) if r]


def walk_music(card: Path):
    """Itera los archivos de audio, ignorando los companeros AppleDouble."""
    music = card / "Music"
    if not music.exists():
        return
    for p in sorted(music.rglob("*")):
        if p.is_file() and p.suffix.lower() in AUDIO_EXT and not p.name.startswith("._"):
            yield p
