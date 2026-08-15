"""Normalizacion al formato nativo de la salida del Y1: 44,1 kHz / 16 bits."""
from __future__ import annotations
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .config import TARGET_RATE, TARGET_BITS, BACKUP_DIR
from .util import run, log, human


def needs_conversion(rate: int, bits: int) -> bool:
    return bool(rate) and (rate != TARGET_RATE or (bits and bits > TARGET_BITS))


def _filter(rate: int, bits: int) -> str:
    """Construye el filtro minimo necesario.

    Remuestrear 44100 -> 44100 seria una pasada inutil por el resampler, asi
    que solo se pide cuando la frecuencia difiere de verdad. Para los archivos
    que ya estan a 44,1 kHz basta con reducir la profundidad de bits, y ahi el
    dithering triangular es lo correcto para no introducir distorsion de
    cuantizacion.
    """
    partes = ["aresample"]
    opts = [f"out_sample_fmt=s{TARGET_BITS}", "dither_method=triangular_hp"]
    if rate != TARGET_RATE:
        opts.insert(0, f"out_sample_rate={TARGET_RATE}")
        opts += ["resampler=swr", "precision=33"]
    return partes[0] + "=" + ":".join(opts)


def convert(p: Path, card: Path, rate: int = 0, bits: int = 0,
            backup: bool = True) -> tuple[bool, int, int]:
    """Convierte in situ. Solo reemplaza el original si la salida es valida.

    Devuelve (exito, bytes_antes, bytes_despues).
    """
    before = p.stat().st_size
    if backup:
        dest = BACKUP_DIR / p.relative_to(card)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copy2(p, dest)
    # mktemp sin extension: en macOS las X deben ir al final de la plantilla y
    # con sufijo colisiona al ejecutarse en paralelo. El formato se fuerza con
    # -f flac.
    fd = tempfile.NamedTemporaryFile(delete=False, suffix="")
    tmp = Path(fd.name)
    fd.close()
    r = run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(p),
             "-map", "0", "-map_metadata", "0", "-c:v", "copy",
             "-af", _filter(rate or TARGET_RATE, bits or 24),
             "-c:a", "flac", "-compression_level", "8",
             "-f", "flac", str(tmp)])
    ok = False
    after = before
    if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
        # Se verifica frecuencia Y profundidad antes de tocar el original.
        chk = run(["ffprobe", "-v", "quiet", "-select_streams", "a:0",
                   "-show_entries", "stream=sample_rate,bits_per_raw_sample",
                   "-of", "csv=p=0", str(tmp)])
        campos = chk.stdout.strip().split(",")
        if (len(campos) >= 2 and campos[0] == str(TARGET_RATE)
                and campos[1] == str(TARGET_BITS)):
            after = tmp.stat().st_size
            shutil.copy(tmp, p)      # cp respeta COPYFILE_DISABLE, rsync no
            ok = True
    tmp.unlink(missing_ok=True)
    if ok:
        log.info("  %s  %s -> %s", p.name[:52], human(before), human(after))
    else:
        log.warning("  FALLO en %s (original intacto)", p.name)
    return ok, before, after


def convert_many(items: list[tuple[Path, int, int]], card: Path,
                 workers: int = 4) -> tuple[int, int, int]:
    """Convierte en paralelo. items = [(ruta, rate, bits), ...]

    ffmpeg satura un nucleo por proceso; con 4 se aprovecha el M4 sin ahogar
    la escritura por USB, que es el otro cuello.
    Devuelve (convertidos, bytes_antes, bytes_despues).
    """
    if not items:
        return 0, 0, 0
    def _one(it):
        p, rate, bits = it
        return convert(p, card, rate, bits)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(_one, items))
    ok = sum(1 for r in res if r[0])
    antes = sum(r[1] for r in res if r[0])
    despues = sum(r[2] for r in res if r[0])
    return ok, antes, despues
