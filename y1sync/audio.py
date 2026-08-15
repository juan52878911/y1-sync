"""Conversion a 44.1 kHz / 16 bits, el formato nativo de la salida del Y1."""
from __future__ import annotations
import shutil, tempfile
from pathlib import Path
from .config import TARGET_RATE, TARGET_BITS, RESAMPLER_ARGS, BACKUP_DIR
from .util import run, log, human

def needs_conversion(rate: int, bits: int) -> bool:
    return bool(rate) and (rate != TARGET_RATE or (bits and bits > TARGET_BITS))

def convert(p: Path, card: Path, backup: bool = True) -> tuple[bool, int, int]:
    """Convierte in situ. Solo reemplaza el original si la salida es valida.

    Devuelve (exito, bytes_antes, bytes_despues).
    """
    before = p.stat().st_size
    if backup:
        dest = BACKUP_DIR / p.relative_to(card)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(p, dest)
    # mktemp sin extension: en macOS las X deben ir al final de la plantilla,
    # y con sufijo colisiona al ejecutarse en paralelo. El formato se fuerza
    # con -f flac.
    fd = tempfile.NamedTemporaryFile(delete=False, suffix="")
    tmp = Path(fd.name); fd.close()
    r = run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(p),
             "-map", "0", "-map_metadata", "0", "-c:v", "copy",
             "-af", RESAMPLER_ARGS, "-c:a", "flac", "-compression_level", "8",
             "-f", "flac", str(tmp)])
    ok = False
    after = before
    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        chk = run(["ffprobe", "-v", "quiet", "-select_streams", "a:0",
                   "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(tmp)])
        if chk.stdout.strip().split(",")[0] == str(TARGET_RATE):
            after = tmp.stat().st_size
            shutil.copy(tmp, p)          # cp respeta COPYFILE_DISABLE, rsync no
            ok = True
    tmp.unlink(missing_ok=True)
    if ok:
        log.info("  convertido %s  %s -> %s", p.name, human(before), human(after))
    else:
        log.warning("  FALLO al convertir %s (original intacto)", p.name)
    return ok, before, after
