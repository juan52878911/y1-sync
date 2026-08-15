"""Normaliza las caratulas a un lado maximo comun.

Una portada de 3000x3000 dentro de cada pista infla el archivo y obliga al
MT6572 a escalarla en cada cambio de cancion. 500x500 sobra para su pantalla.
"""
from __future__ import annotations
import io, tempfile
from pathlib import Path
from PIL import Image
from .config import ARTWORK_MAX, ARTWORK_QUALITY
from .util import run, log

def _resize_bytes(data: bytes) -> bytes | None:
    """Devuelve el JPEG reescalado, o None si no hacia falta tocarlo."""
    try:
        im = Image.open(io.BytesIO(data))
    except Exception:
        return None
    if max(im.size) <= ARTWORK_MAX:
        return None
    im = im.convert("RGB")
    im.thumbnail((ARTWORK_MAX, ARTWORK_MAX), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=ARTWORK_QUALITY, optimize=True)
    return out.getvalue()

def process_flac(p: Path) -> tuple[bool, str]:
    """Reescala la caratula embebida de un FLAC. (cambiado, detalle)"""
    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "cover"
        r = run(["metaflac", f"--export-picture-to={img}", str(p)])
        if r.returncode != 0 or not img.exists() or img.stat().st_size == 0:
            return False, "sin caratula"
        data = img.read_bytes()
        try:
            w, h = Image.open(io.BytesIO(data)).size
        except Exception:
            return False, "ilegible"
        new = _resize_bytes(data)
        if new is None:
            return False, f"ya cabe ({w}x{h})"
        small = Path(td) / "cover_small.jpg"
        small.write_bytes(new)
        if run(["metaflac", "--remove", "--block-type=PICTURE", str(p)]).returncode != 0:
            return False, "no se pudo quitar la original"
        if run(["metaflac", f"--import-picture-from={small}", str(p)]).returncode != 0:
            return False, "no se pudo importar la reducida"
        return True, f"{w}x{h} -> {min(w, ARTWORK_MAX)}x{min(h, ARTWORK_MAX)}"

def process_external(folder: Path) -> int:
    """Reescala cover.jpg / folder.jpg sueltos dentro de una carpeta."""
    n = 0
    for name in ("cover.jpg", "cover.png", "folder.jpg", "front.jpg"):
        f = folder / name
        if not f.exists() or f.name.startswith("._"):
            continue
        new = _resize_bytes(f.read_bytes())
        if new:
            f.with_suffix(".jpg").write_bytes(new)
            n += 1
    return n
