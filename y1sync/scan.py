"""Lectura de metadatos. metaflac para FLAC, ffprobe para el resto."""
from __future__ import annotations
import json, re
from pathlib import Path
from .util import run, nfc, device_path

AUDIO_EXT = (".flac", ".mp3", ".m4a", ".ogg", ".wav")

def _num(v) -> int | None:
    m = re.match(r"\s*(\d+)", str(v or ""))
    return int(m.group(1)) if m else None

def read_flac(p: Path) -> dict:
    r = run(["metaflac", "--show-total-samples", "--show-sample-rate",
             "--show-bps", "--show-channels", "--export-tags-to=-", str(p)])
    if r.returncode != 0:
        return {}
    lines = r.stdout.split("\n")
    try:
        total, rate, bps, ch = (int(lines[i]) for i in range(4))
        tags = lines[4:]
    except (ValueError, IndexError):
        return {}
    d = {"samplerate": rate, "bits": bps, "channels": ch,
         "duration": total / rate if rate else 0, "format": "flac"}
    for line in tags:
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip().upper()] = v.strip()
    return d

def read_other(p: Path) -> dict:
    r = run(["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration:stream=sample_rate,channels:format_tags=title,artist,"
             "album_artist,album,track,disc,date,genre",
             "-of", "default=noprint_wrappers=1", str(p)])
    d = {"format": p.suffix.lstrip(".").lower(), "bits": 0}
    for line in r.stdout.split("\n"):
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip().upper().replace("TAG:", "")] = v.strip()
    d["duration"] = float(d.get("DURATION") or 0)
    d["samplerate"] = int(d.get("SAMPLE_RATE") or 0)
    d["channels"] = int(d.get("CHANNELS") or 0)
    return d

def artwork_size(p: Path) -> tuple[int | None, int | None]:
    """Dimensiones de la caratula embebida, si la hay."""
    r = run(["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(p)])
    parts = r.stdout.strip().split(",")
    if len(parts) >= 2 and parts[0].isdigit():
        return int(parts[0]), int(parts[1])
    return None, None

def read_track(card: Path, p: Path) -> dict | None:
    """Devuelve la fila lista para insertar en `tracks`."""
    d = read_flac(p) if p.suffix.lower() == ".flac" else read_other(p)
    if not d:
        return None
    rel = p.relative_to(card)
    parts = rel.parts
    w, h = artwork_size(p)
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

def walk_music(card: Path):
    """Itera los archivos de audio, ignorando los compañeros AppleDouble."""
    music = card / "Music"
    if not music.exists():
        return
    for p in sorted(music.rglob("*")):
        if p.is_file() and p.suffix.lower() in AUDIO_EXT and not p.name.startswith("._"):
            yield p
