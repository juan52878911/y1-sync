# "Gather runtime data" en el Innioasis Y1: causa real y correccion

**Estado: RESUELTO Y VERIFICADO EN EL APARATO** (2026-08-18).
33 minutos de reproduccion continua con el ajuste activo, cero SIGSEGV y cero
panics, sobre el commit `13861b2e0ead` del fork.

## La causa no estaba donde parecia

El diagnostico anterior (`rockbox-skin-render-crash.md`) culpaba a
`SKINOFFSETTOPTR` con base nula. Ese mecanismo **existe y es real**, pero no
era la causa. La evidencia solo aparecio al ejecutar el parche en el aparato:
cada guarda anadida movia el fallo un paso mas cerca del origen.

```
1. skin_render+8                     fault addr 0x00000000   <- puntero salvaje
2. skin_data_free_buflib_allocs+196  fault addr 0x6c663313   <- puntero salvaje
3. *PANIC* buflib error :: block len wacky                   <- el origen
```

El tercero es buflib detectando que **sus propios metadatos estan corrompidos**.
Los dos primeros eran sintomas de leer estructuras ya pisadas.

## La causa: desbordamiento de pila sin pagina de guarda

Medido, no supuesto:

| Dato | Valor |
|---|---:|
| `MINSIGSTKSZ` en bionic | 2.048 |
| `DEFAULT_STACK_SIZE` | 14.336 |
| `audio_stack` original | **18.432** |
| marco de `find_entry_disk` | **4.724** |
| cadena `tagtree_buffer_event`+`tagcache_find_index`+`find_entry_disk` | ~5.712 |

Con `runtimedb` activo, `PLAYBACK_EVENT_TRACK_BUFFER` entra **en el hilo de
audio** a `tagtree_buffer_event` -> `tagcache_find_index` -> `find_entry_disk`,
que en builds `APPLICATION` reserva `char pathbuf[PATH_MAX]` (4 KB) para
`realpath()`. El propio codigo lo admite: *"Don't use MAX_PATH here, it's too
small"*.

Los hilos de los ports *hosted* corren sobre **arrays estaticos de BSS sin
pagina de guarda** (`HAVE_SIGALTSTACK_THREADS`). El desbordamiento no falla
limpiamente: escribe sobre el BSS vecino, donde vive el pool de buflib.

**El propio Rockbox ya lo sabia**: el hilo de la tagcache lleva `+0x4000`
(`tagcache.c:305`) justo por esto. El de audio se quedo con `+0x1000` pese a
ejecutar la misma ruta.

## Correccion

`apps/audio_thread.c` — la misma holgura que ya tiene el hilo de la tagcache:

```c
#if defined(APPLICATION) && !defined(SIMULATOR)
static long audio_stack[(DEFAULT_STACK_SIZE + 0x4000)/sizeof(long)];
#else
static long audio_stack[(DEFAULT_STACK_SIZE + 0x1000)/sizeof(long)];
#endif
```

Verificado en la tabla de simbolos: `audio_stack` pasa de `0x4800` a `0x7800`.

## Dos bugs independientes encontrados por el camino

Son reales, verificables y merecen ir a upstream aunque no causaran este fallo.

**1. Puntero rancio en `skin_data_free_buflib_allocs`** (`skin_parser.c:1911`).
`skin_buffer` es un estatico de fichero (linea 87). Solo se reasignaba si
`wps_loaded` era cierto; si no, conservaba el puntero de un parseo anterior ya
liberado y lo usaba como base. El destino `abort:` dice *"Safe if skin_buffer
is NULL"* — pero nunca se ponia a NULL.

**2. `skin_data_load` devolvia `true` siempre** (`skin_parser.c:2740`), incluso
al fallar `core_alloc`, dejando `wps_loaded=false`, handle invalido y `tree`
apuntando al buffer temporal. `skin_load()` lo daba por cargado y **nunca caia
al tema de emergencia**.

## Guardas defensivas

`get_skin_buffer()` (`wps_internals.h:394`) no comprobaba `data`. La guarda va
ahi y no en los llamadores porque tiene **51**. Mas las de `skin_render` y
`skin_render_viewport`, necesarias porque `SKINOFFSETTOPTR(NULL, off>=0)`
devuelve un puntero pequeno **no nulo** que burla los `if (!ptr)`.

Son defensa, no la causa. Sin la correccion de pila no bastan.

## Correccion de un error del analisis previo

El comentario que afirmaba que `skin_load()` deja `gwps->data` sin asignar
**no lo sostiene el codigo**: ese campo se escribe en un unico sitio
(`skin_engine.c`, `gui_skin_reset`) y siempre apunta a la `wps_data` estatica
de `skins[][]`. Que llegara a cero era consecuencia de la corrupcion de BSS.

## Como compilar

Entorno en `docs/build-entorno.md`. Resumen: contenedor `linux/amd64` con NDK
**r10e** y JDK 17; `SHELL=/bin/bash` es obligatorio (el r10e deduce la
arquitectura del anfitrion con `file -L "$SHELL"`, y bajo `sh` esa variable
esta vacia); build-tools **30.0.3** por `dx`, que desaparecio en la 31.

```bash
cd android/build
../../tools/configure --target=201 --lcdwidth=480 --lcdheight=360 --type=n
make && make classes && make zip && make unsigned-apk
```
