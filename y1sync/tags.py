"""Correccion de metadatos.

El menu Artists de Rockbox usa `canonicalartist`, que devuelve ALBUMARTIST si
existe y solo cae a ARTIST si falta. Por eso un ALBUMARTIST inconsistente
fragmenta el artista en varias entradas.
"""
from __future__ import annotations
import collections
from pathlib import Path
from .util import run, nfc, log

def write_tag(p: Path, tag: str, value: str) -> bool:
    if p.suffix.lower() == ".flac":
        return run(["metaflac", f"--remove-tag={tag}",
                    f"--set-tag={tag}={value}", str(p)]).returncode == 0
    # ffmpeg necesita remuxear; solo para los pocos no-FLAC
    import shutil, tempfile
    tmp = Path(tempfile.mktemp(suffix=p.suffix))
    r = run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(p),
             "-c", "copy", "-metadata", f"{tag.lower()}={value}", str(tmp)])
    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        shutil.copy(tmp, p); tmp.unlink(missing_ok=True); return True
    tmp.unlink(missing_ok=True)
    return False

def find_contamination(rows: list[dict]) -> list[tuple[dict, str]]:
    """Detecta ALBUMARTIST contaminado.

    Regla: dentro de un mismo album, el valor minoritario es contaminacion.
    Asi se respetan los proyectos colaborativos reales (un album entero
    etiquetado 'Jack Ü') y se corrigen las pistas sueltas mal emparejadas
    por un etiquetador automatico.
    """
    por_album = collections.defaultdict(list)
    for r in rows:
        por_album[(nfc(r["folder_artist"]), nfc(r["album"]))].append(r)
    fixes = []
    for _, grupo in por_album.items():
        if len(grupo) < 2:
            continue
        cnt = collections.Counter(nfc(r["albumartist"]) for r in grupo)
        mayor, n_mayor = cnt.most_common(1)[0]
        if not mayor:
            continue
        for r in grupo:
            actual = nfc(r["albumartist"])
            if actual != mayor and cnt[actual] < n_mayor:
                fixes.append((r, mayor))
    return fixes

def normalize_collab(rows: list[dict], canonical: str) -> list[tuple[dict, str, str]]:
    """Para un artista canonico, mueve la colaboracion de ALBUMARTIST a ARTIST.

    Ej: artist='$uicideboy$', albumartist='$uicideboy$ & Germ'
     -> artist='$uicideboy$ & Germ', albumartist='$uicideboy$'
    Agrupa bien en el menu sin perder el credito de la colaboracion.
    """
    out = []
    for r in rows:
        aa, ar = nfc(r["albumartist"]), nfc(r["artist"])
        if aa and aa != canonical and ar and ar in aa:
            out.append((r, aa, canonical))   # (fila, nuevo_artist, nuevo_albumartist)
        elif aa != canonical:
            out.append((r, ar, canonical))
    return out
