"""Revision de salud de la biblioteca.

Cada comprobacion existe porque el fallo correspondiente ya ocurrio de verdad
en esta biblioteca y costo horas encontrarlo a mano. El objetivo es que la
proxima vez sea un comando.
"""
from __future__ import annotations
import collections
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import MUSIC_DIR, PLAYLIST_DIR, TARGET_RATE, TARGET_BITS
from .util import run, log, nfc

# Etiquetas que metaflac devuelve en una sola llamada de cabecera.
_CAMPOS = ("TITLE", "ARTIST", "ALBUM", "ALBUMARTIST", "DATE", "TRACKNUMBER",
           "REPLAYGAIN_TRACK_GAIN", "REPLAYGAIN_ALBUM_GAIN")


def _lee(p: Path) -> dict:
    """Una sola invocacion por archivo: cabecera + comentarios.

    Se usa `--list` en vez de varios `--show-tag` porque cada proceso extra
    se paga en tiempo real sobre una tarjeta que va a 3 MB/s por USB.
    """
    r = run(["metaflac", "--no-utf8-convert", "--list",
             "--block-type=STREAMINFO,VORBIS_COMMENT", str(p)])
    if r.returncode != 0:
        return {"ruta": p, "ilegible": True}
    d: dict = {"ruta": p, "ilegible": False}
    total = rate = 0
    for linea in r.stdout.splitlines():
        s = linea.strip()
        if s.startswith("sample_rate:"):
            rate = int(s.split(":", 1)[1].split()[0])
        elif s.startswith("bits-per-sample:"):
            d["bits"] = int(s.split(":", 1)[1])
        elif s.startswith("total samples:"):
            total = int(s.split(":", 1)[1])
        elif s.startswith("MD5 signature:"):
            d["md5"] = s.split(":", 1)[1].strip()
        elif s.startswith("comment["):
            kv = s.split(":", 1)[1].strip() if ":" in s else ""
            if "=" in kv:
                k, v = kv.split("=", 1)
                k = k.strip().upper()
                if k in _CAMPOS:
                    d.setdefault(k, v.strip())
    d["rate"] = rate
    d["bits"] = d.get("bits", 0)
    d["dur"] = total / rate if rate else 0
    if rate == 0:
        d["ilegible"] = True
    return d


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFC", s or "").replace("’", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


def revisar(card: Path, *, profundo: bool = False, workers: int = 8) -> dict:
    """Recorre la biblioteca y devuelve los hallazgos agrupados por tipo."""
    musica = card / MUSIC_DIR
    rutas = sorted(p for p in musica.rglob("*.flac") if not p.name.startswith("._"))
    log.info("Revisando %d archivos FLAC...", len(rutas))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        datos = list(ex.map(_lee, rutas))

    h: dict[str, list] = collections.defaultdict(list)

    # --- por archivo ---------------------------------------------------
    for d in datos:
        p: Path = d["ruta"]
        rel = p.relative_to(musica)
        if d["ilegible"]:
            h["ilegibles"].append(str(rel))
            continue
        if d["rate"] != TARGET_RATE or d["bits"] != TARGET_BITS:
            h["formato"].append(f"{rel}  ({d['rate']} Hz / {d['bits']} bit)")
        if not d.get("REPLAYGAIN_TRACK_GAIN"):
            h["sin_replaygain"].append(str(rel))
        if "nan" in (d.get("REPLAYGAIN_ALBUM_GAIN") or "").lower():
            h["replaygain_nan"].append(str(rel))
        for campo, etiqueta in (("TITLE", "titulo"), ("ARTIST", "artista"),
                                ("ALBUM", "album"), ("DATE", "año")):
            if not d.get(campo):
                h[f"sin_{etiqueta}"].append(str(rel))

    # --- por carpeta de album ------------------------------------------
    por_carpeta: dict[Path, list[dict]] = collections.defaultdict(list)
    for d in datos:
        if not d["ilegible"]:
            por_carpeta[d["ruta"].parent].append(d)

    for carpeta, pistas in sorted(por_carpeta.items()):
        rel = carpeta.relative_to(musica)
        if len(pistas) < 2:
            continue

        # Todas con el mismo titulo: el etiquetador copio una pista al resto.
        # Paso exactamente con REI AMI / FOIL, donde las 10 decian "F.R.A.".
        titulos = {_norm(d.get("TITLE", "")) for d in pistas}
        if len(titulos) == 1 and titulos != {""}:
            h["titulo_repetido"].append(f"{rel}  ({len(pistas)} pistas: "
                                        f"{pistas[0].get('TITLE')!r})")

        # Artista discordante: pistas de Slipknot venian atribuidas a "Darby"
        # y "The Bloodclan". Solo se marca cuando el artista no comparte NINGUNA
        # palabra con el dominante; de lo contrario las colaboraciones normales
        # ("Architects; Winston McCall", "$uicideboy$ & Germ") darian falsos
        # positivos a cientos.
        cuenta = collections.Counter(_norm(d.get("ARTIST", "")) for d in pistas)
        if len(cuenta) > 1:
            dominante, n = cuenta.most_common(1)[0]
            if n >= max(3, len(pistas) * 0.7) and dominante:
                palabras_dom = set(re.findall(r"\w+", dominante))
                for d in pistas:
                    otro = _norm(d.get("ARTIST", ""))
                    if not otro or otro == dominante:
                        continue
                    if palabras_dom & set(re.findall(r"\w+", otro)):
                        continue        # comparten nombre: es una colaboracion
                    h["artista_discordante"].append(
                        f"{rel}/{d['ruta'].name}  {d.get('ARTIST')!r} "
                        f"(el resto del album es {dominante!r})")

        # Numeros de pista repetidos o todos iguales.
        nums = [d.get("TRACKNUMBER", "") for d in pistas if d.get("TRACKNUMBER")]
        if nums:
            rep = [n for n, c in collections.Counter(nums).items() if c > 1]
            if len(set(nums)) == 1 and len(nums) > 1:
                h["pistas_iguales"].append(f"{rel}  (todas la {nums[0]})")
            elif rep:
                h["pistas_repetidas"].append(f"{rel}  (repite {', '.join(sorted(rep))})")

    # --- duplicados reales, por MD5 del audio ---------------------------
    # Agrupar por titulo+artista da falsos positivos masivos cuando las
    # etiquetas estan mal. El MD5 que FLAC guarda del audio decodificado es
    # prueba directa de que dos archivos suenan igual.
    por_md5: dict[str, list[Path]] = collections.defaultdict(list)
    for d in datos:
        md5 = d.get("md5", "")
        if not d["ilegible"] and md5 and set(md5) != {"0"}:
            por_md5[md5].append(d["ruta"])
    for md5, ps in por_md5.items():
        if len(ps) > 1:
            ps = sorted(ps, key=lambda x: len(str(x)))
            sobra = sum(p.stat().st_size for p in ps[1:])
            h["duplicados"].append(
                f"{sobra // 1048576} MB  " +
                "  |  ".join(str(p.relative_to(musica)) for p in ps))

    # --- suciedad de macOS ----------------------------------------------
    basura = [p for p in card.rglob("._*")] + [p for p in card.rglob(".DS_Store")]
    if basura:
        h["basura_macos"].append(f"{len(basura)} archivos")

    # --- playlists que apuntan a nada ------------------------------------
    pl_dir = card / PLAYLIST_DIR
    if pl_dir.is_dir():
        # Los companeros ._ de macOS no son playlists: son metadatos
        # binarios y su contenido nunca resuelve a rutas validas.
        for pl in sorted(x for x in pl_dir.glob("*.m3u8")
                         if not x.name.startswith("._")):
            rotas = 0
            try:
                for linea in pl.read_text(encoding="utf-8", errors="replace").splitlines():
                    linea = linea.strip()
                    if not linea or linea.startswith("#"):
                        continue
                    destino = card / linea.lstrip("/").replace("sdcard/", "", 1)
                    if not destino.exists():
                        rotas += 1
            except OSError:
                continue
            if rotas:
                h["playlists_rotas"].append(f"{pl.name}  ({rotas} entradas muertas)")

    # --- comprobacion profunda opcional ----------------------------------
    if profundo:
        log.info("Comprobacion profunda: decodificando cada archivo...")
        sanos = [d["ruta"] for d in datos if not d["ilegible"]]
        def _test(p: Path):
            return p if run(["flac", "-t", str(p)]).returncode != 0 else None
        with ThreadPoolExecutor(max_workers=max(2, workers // 2)) as ex:
            for p in ex.map(_test, sanos):
                if p:
                    h["corruptos"].append(str(p.relative_to(musica)))

    h["_total"] = [str(len(rutas))]
    return dict(h)


# Orden de presentacion: primero lo que impide reproducir, luego lo cosmetico.
_ORDEN = [
    ("ilegibles",           "Archivos ilegibles (no suenan)"),
    ("corruptos",           "Archivos que fallan al decodificar"),
    ("playlists_rotas",     "Playlists con entradas muertas"),
    ("duplicados",          "Duplicados reales (mismo audio, verificado por MD5)"),
    ("titulo_repetido",     "Carpetas con el mismo titulo en todas las pistas"),
    ("artista_discordante", "Pistas con artista ajeno al album"),
    ("pistas_iguales",      "Albumes con el mismo numero en todas las pistas"),
    ("pistas_repetidas",    "Albumes con numeros de pista repetidos"),
    ("sin_replaygain",      "Sin ReplayGain (volumen desigual)"),
    ("replaygain_nan",      "ReplayGain de album invalido (NaN)"),
    ("formato",             "Fuera de 44,1 kHz / 16 bits"),
    ("sin_titulo",          "Sin titulo"),
    ("sin_artista",         "Sin artista"),
    ("sin_album",           "Sin album"),
    ("sin_año",             "Sin año"),
    ("basura_macos",        "Restos de macOS en la tarjeta"),
]


def informe(h: dict, *, detalle: int = 5) -> int:
    """Imprime el informe. Devuelve el numero de problemas encontrados."""
    total = int(h.get("_total", ["0"])[0])
    print(f"\n  Biblioteca: {total} archivos FLAC\n")
    problemas = 0
    for clave, titulo in _ORDEN:
        items = h.get(clave, [])
        if not items:
            continue
        problemas += len(items)
        print(f"  {titulo}: {len(items)}")
        for x in items[:detalle]:
            print(f"      {x}")
        if len(items) > detalle:
            print(f"      ... y {len(items) - detalle} mas")
        print()
    if not problemas:
        print("  Sin problemas detectados.\n")
    return problemas
