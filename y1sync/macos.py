"""Limpieza de metadatos de macOS en volumenes FAT32/exFAT.

macOS guarda atributos extendidos en un archivo compañero `._nombre` cuando
el sistema de archivos no los soporta de forma nativa. El culpable habitual
es `com.apple.quarantine`, que se pone a todo lo descargado. Quitando el
atributo desaparece el motivo por el que se crea el compañero.
"""
from __future__ import annotations
from pathlib import Path
from .util import run, log

def clean(root: Path) -> dict:
    """Elimina xattrs y archivos ._ / .DS_Store. Devuelve cuentas."""
    if not root.exists():
        return {"xattr": 0, "appledouble": 0, "dsstore": 0}
    run(["xattr", "-rc", str(root)])
    run(["dot_clean", "-m", str(root)])
    ad = ds = 0
    for p in root.rglob("._*"):
        try:
            p.unlink(); ad += 1
        except OSError:
            pass
    for p in root.rglob(".DS_Store"):
        try:
            p.unlink(); ds += 1
        except OSError:
            pass
    if ad or ds:
        log.info("Limpieza macOS: %d archivos ._ y %d .DS_Store eliminados", ad, ds)
    return {"appledouble": ad, "dsstore": ds}

def prevent(card_root: Path) -> None:
    """Evita que Spotlight y FSEvents vuelvan a ensuciar la tarjeta."""
    try:
        (card_root / ".metadata_never_index").touch()
        fse = card_root / ".fseventsd"
        fse.mkdir(exist_ok=True)
        (fse / "no_log").touch()
    except OSError as e:
        log.debug("No se pudo escribir marcadores anti-indexado: %s", e)
