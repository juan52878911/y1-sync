"""Limpieza de metadatos de macOS en volumenes FAT32/exFAT.

macOS guarda atributos extendidos en un archivo companero `._nombre` cuando
el sistema de archivos no los soporta de forma nativa. El culpable habitual
es `com.apple.quarantine`, que se pone a todo lo descargado. Quitando el
atributo desaparece el motivo por el que se crea el companero.
"""
from __future__ import annotations
from pathlib import Path
from .util import run, log


def _sweep(root: Path) -> tuple[list[Path], int]:
    """UN solo recorrido del arbol.

    La version anterior hacia cuatro pasadas (xattr, dot_clean y dos rglob).
    Sobre una microSD por USB cada pasada se paga en tiempo real.
    """
    basura: list[Path] = []
    con_xattr = 0
    for p in root.rglob("*"):
        n = p.name
        if n.startswith("._") or n == ".DS_Store":
            basura.append(p)
    return basura, con_xattr


def clean(root: Path, *, strip_xattr: bool = True) -> dict:
    """Elimina archivos ._ y .DS_Store; opcionalmente purga los xattrs.

    `strip_xattr=False` sirve para la pasada final de una sincronizacion que
    no escribio nada: si no tocamos archivos, no hay atributos nuevos que
    quitar y `xattr -rc` sobre 79 GB es puro gasto.
    """
    if not root.exists():
        return {"appledouble": 0, "dsstore": 0}
    if strip_xattr:
        run(["xattr", "-rc", str(root)])
        run(["dot_clean", "-m", str(root)])
    basura, _ = _sweep(root)
    ad = ds = 0
    for p in basura:
        try:
            p.unlink()
            if p.name == ".DS_Store":
                ds += 1
            else:
                ad += 1
        except OSError:
            pass
    if ad or ds:
        log.info("Limpieza macOS: %d archivos ._ y %d .DS_Store eliminados", ad, ds)
    return {"appledouble": ad, "dsstore": ds}


def clean_paths(paths: list[Path]) -> int:
    """Purga xattrs solo en las rutas que acabamos de tocar.

    Mucho mas barato que recorrer la biblioteca entera cuando solo se
    escribieron un punado de albumes nuevos.
    """
    n = 0
    for p in paths:
        if p.exists():
            run(["xattr", "-c", str(p)])
            comp = p.with_name("._" + p.name)
            if comp.exists():
                try:
                    comp.unlink()
                    n += 1
                except OSError:
                    pass
    return n


def prevent(card_root: Path) -> None:
    """Evita que Spotlight y FSEvents vuelvan a ensuciar la tarjeta."""
    try:
        (card_root / ".metadata_never_index").touch()
        fse = card_root / ".fseventsd"
        fse.mkdir(exist_ok=True)
        (fse / "no_log").touch()
    except OSError as e:
        log.debug("No se pudo escribir marcadores anti-indexado: %s", e)
