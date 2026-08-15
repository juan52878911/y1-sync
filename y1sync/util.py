"""Utilidades transversales."""
from __future__ import annotations
import logging, subprocess, unicodedata, sys
from pathlib import Path

log = logging.getLogger("y1sync")

def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

def nfc(s: str | None) -> str:
    """Normaliza a NFC.

    macOS entrega los nombres del sistema de archivos en NFD (descompuesto),
    mientras que los literales de Python estan en NFC. Sin esto, 'León' del
    disco no casa con 'León' del codigo aunque se vean identicos.
    """
    return unicodedata.normalize("NFC", s or "")

def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Ejecuta un comando sin shell (inmune a comillas y apostrofes en rutas)."""
    return subprocess.run(cmd, capture_output=True, text=True, **kw)

def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

def device_path(rel: str) -> str:
    """Convierte una ruta relativa a la tarjeta en la que ve Rockbox."""
    from .config import DEVICE_PREFIX
    rel = str(rel).replace("\\", "/")
    return f"{DEVICE_PREFIX}/{rel}"
