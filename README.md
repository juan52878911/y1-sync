# y1-sync

Gestor automático de la biblioteca musical del **Innioasis Y1** (un reproductor
con Android 4.2.2 y Rockbox). Al conectar el aparato, detecta lo que has
descargado nuevo, arregla los metadatos, normaliza el audio y las carátulas,
y lo registra todo en una base de datos.

## Qué hace en cada sincronización

1. **Limpia** los archivos `._` que macOS siembra en FAT32.
2. **Detecta álbumes nuevos** comparando contra la base.
3. **Convierte a 44,1 kHz / 16 bits** lo que no lo esté (con copia de seguridad).
4. **Reduce las carátulas** a 500×500 si son más grandes.
5. **Corrige `ALBUMARTIST`** contaminado.
6. **Asigna género** consultando MusicBrainz.
7. **Repara playlists** rotas.
8. **Importa el historial** de reproducción de Rockbox.
9. **Registra** todo en SQLite.

## Instalación

```bash
git clone https://github.com/juan52878911/y1-sync.git
cd y1-sync
pip3 install -r requirements.txt
brew install flac ffmpeg          # metaflac y ffmpeg
./scripts/install-agent.sh        # sincroniza sola al conectar
```

## Uso manual

```bash
./bin/y1sync sync --dry-run   # ver qué haría, sin tocar nada
./bin/y1sync sync             # sincronizar
./bin/y1sync stats            # resumen de la biblioteca
```

`bin/y1sync` es un lanzador que filtra ruido de `hashlib`; `python3 -m y1sync`
funciona igual.

### Si ves tracebacks de `blake2b` / `blake2s`

Tu Python fue compilado contra una OpenSSL sin esos algoritmos (frecuente con
pyenv). Son inofensivos, pero tienen un efecto que no lo es: `hashlib` llama a
`logging.error()` al importarse, lo que **deja el logger raíz ya configurado**
y convierte cualquier `logging.basicConfig()` posterior en un no-op. Por eso
`setup_logging()` usa `force=True`; sin ello el programa no imprimía nada.

Para eliminarlo de raíz, recompila el intérprete:

```bash
brew install openssl@3
PYTHON_CONFIGURE_OPTS="--with-openssl=$(brew --prefix openssl@3)" \
  pyenv install -f 3.13.11
```

Opciones: `--no-convert`, `--no-artwork`, `--no-musicbrainz`, `--wait 60`.

---

## Por qué el código hace lo que hace

Cada decisión aquí salió de un problema real diagnosticado en el aparato.

### El audio sale a 44,1 kHz / 16 bits, fijo

`AudioFlinger` del MT6572 entrega exactamente eso. Un FLAC a 96 kHz se
remuestrea en tiempo real en un Cortex-A7 de 2013. Convertir en el Mac quita
ese trabajo y ahorra espacio: 290 archivos pasaron de 15,40 GB a 6,48 GB.

El `ffmpeg` de Homebrew **no trae libsoxr**; se usa `swr` con precisión 33,
indistinguible en una salida de 16 bits.

### `ALBUMARTIST` es lo que agrupa, no `ARTIST`

El menú *Artists* de Rockbox usa `canonicalartist`: devuelve `ALBUMARTIST` si
existe y solo cae a `ARTIST` si falta. Un `ALBUMARTIST` inconsistente parte un
artista en varias entradas.

Para distinguir un error de una colaboración real: **dentro de un mismo álbum,
el valor minoritario es contaminación**. Así un disco entero de "Jack Ü" se
respeta, y una pista suelta mal emparejada se corrige.

### El género se puntúa, no se decide por orden

MusicBrainz devuelve unos 300 términos distintos. Colapsarlos por primera
coincidencia **falla**: `dance` y `alternative metal` son etiquetas secundarias
de medio catálogo, y mandaban a Skrillex a *Metalcore* y a Muse a *Metal*. Se
usa puntuación ponderada (términos específicos pesan 5, genéricos 1).

Y hay que consultar **a nivel de álbum, no solo de artista**: `$uicideboy$` no
tiene género como artista, pero cada disco devuelve `cloud rap, horrorcore`.

### Las playlists necesitan tres arreglos

1. Prefijo `/sdcard` (Rockbox indexa ahí; se confirma leyendo `database_4.tcd`).
2. Remapeo **por título de la etiqueta**, que sobrevive a renombrados.
3. Extensión `.m3u8`: con `.m3u`, Rockbox aplica el codepage configurado y
   destroza los acentos.

### Los archivos `._` de macOS

Aparecen porque FAT32 no guarda atributos extendidos y macOS los vuelca a un
compañero. El culpable es `com.apple.quarantine`. Se quita el atributo con
`xattr -rc`, que elimina el motivo, no solo el síntoma.

> **Ojo**: en macOS reciente `/usr/bin/rsync` es **openrsync** e **ignora
> `COPYFILE_DISABLE=1`**. Por eso el código usa `cp`, que sí lo respeta.

### Unicode en macOS

El sistema de archivos entrega los nombres en **NFD** y los literales de Python
están en NFC. `León` no casa con `León` aunque se vean idénticos. Todo
comparativo pasa por `util.nfc()`.

### El reloj del aparato

Venía de fábrica en 2022 con zona `Asia/Shanghai` y se reiniciaba en cada
arranque. Las reproducciones anteriores al ajuste se marcan `ts_reliable=0`:
qué canción y cuánto siguen siendo válidos, la fecha no.

```bash
adb shell setprop persist.sys.timezone America/Bogota
adb shell date "$(date +%Y%m%d.%H%M%S)"
```

## Rendimiento

Medido sobre una biblioteca de 2.864 pistas en una microSD por USB.

| Operación | Antes | Después | Mejora |
|---|---:|---:|---:|
| Lectura de un archivo | 177 ms | **11,9 ms** | 15× |
| `playlists.reindex` | 0,36 s | **0,00 s** | — |
| `plays.ingest` | 0,21 s | **0,01 s** | 21× |
| Sync sin novedades | 1,99 s | **0,65 s** | 3× |
| Reescaneo completo (2.864) | ~8,5 min | **~34 s** | 15× |

Uso de memoria: **38 MB**, constante — nada se carga entero en RAM.

### De dónde salió cada mejora

**Un solo subproceso por archivo.** Se usaban dos: `metaflac` para las
etiquetas y `ffprobe` solo para las dimensiones de la carátula. Medido:
metaflac 5,4 ms contra ffprobe 25,5 ms. Pero `metaflac --list` ya expone
`width`/`height` del bloque PICTURE, así que basta una llamada. (No se pueden
combinar `--show-*` con `--list`: metaflac rechaza mezclar operaciones
shorthand y major.)

**Paralelismo donde el coste es esperar.** La lectura secuencial se quedaba en
142 ms/archivo aun con un solo subproceso: el cuello es la latencia del USB,
no la CPU. Con 8 hilos solapando esperas baja a 11,9 ms. El GIL no estorba
porque el tiempo se pasa esperando, no calculando.

**Consultas por lote.** `reindex` hacía un `SELECT` por vínculo — 2.919
consultas. Ahora carga un diccionario de una vez y usa `executemany`. Lo mismo
en la ingesta del historial, donde además `INSERT OR IGNORE` sustituye a un
`try/except` por fila sin perder idempotencia.

**Un recorrido en lugar de cuatro.** `macos.clean` caminaba el árbol cuatro
veces (`xattr`, `dot_clean` y dos `rglob`). Ahora es un barrido, y la limpieza
posterior a escribir es **dirigida a los archivos tocados** en vez de a los
79 GB completos.

## Estructura

```
y1sync/
  config.py     constantes, reglas de género, anulaciones
  scan.py       lectura de metadatos (metaflac / ffprobe)
  audio.py      conversión a 44,1/16 con verificación previa
  artwork.py    reducción de carátulas
  tags.py       corrección de ALBUMARTIST
  genres.py     MusicBrainz + mapeo ponderado (con caché)
  playlists.py  reparación de .m3u8
  plays.py      ingesta del historial
  macos.py      limpieza de AppleDouble
  cli.py        orquestador
```

## Seguridad de los datos

Nada se sobrescribe sin verificar antes. La conversión escribe a un temporal,
comprueba que la salida sea 44.100 Hz válida y **solo entonces** reemplaza.
Los originales van a `~/Music/y1_backups/`. La ingesta del historial es
idempotente por restricción `UNIQUE`.

## Licencia

MIT
