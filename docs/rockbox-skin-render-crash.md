# Propuesta de corrección: SIGSEGV en `skin_render` con "Gather runtime data"

**Objetivo**: que el ajuste *Gather runtime data* funcione en el Innioasis Y1
sin que Rockbox reviente, corrigiendo el código fuente en lugar de rodearlo.

**Build afectada**: `13861b2e0e-251028` — commit `13861b2e0ead` (2025-10-28),
target `ipod6g` compilado como aplicación Android (port comunitario del Y1).

---

## 1. Evidencia

Capturado con `adb logcat -v threadtime`, reproducido **2 de 2 veces**
idénticamente:

```
signal 11 (SIGSEGV), code 1 (SEGV_MAPERR), fault addr 33428f00
#00  pc 00050c80  /system/lib/librockbox.so (skin_render+16)
#01  pc 0004696c  /system/lib/librockbox.so (gui_wps_show+296)
```

La segunda ocurrencia falló en la misma dirección de código con
`fault addr 00000000`.

Secuencia previa al fallo:

```
RunForegroundManager$1.run   → arranca la reproducción
RockboxButton isNotRoot      → entra en la pantalla de reproducción (WPS)
SurfaceView: Locking canvas  → el motor de temas empieza a dibujar
libc: Fatal signal 11        → SIGSEGV
```

Descartado por comprobación directa: el tema activo (`OneBit_OLED.wps` +
`SNARTY.sbs`) **no usa** etiquetas de datos de reproducción (`%rp`, `%rr`,
`%ra`, `%rt`), y su peso es medio (1,4 MB frente a los 14,7 MB de FreshOS).

---

## 2. Causa raíz

### La cadena

En `apps/gui/skin_engine/wps_internals.h:394`:

```c
static inline char* get_skin_buffer(struct wps_data* data)
{
    if (data->buflib_handle > 0)
        return core_get_data(data->buflib_handle);
    return NULL;                      /* <-- puede devolver NULL */
}
```

En `apps/gui/skin_engine/skin_render.c`, **dos llamadas sin validar**:

```c
741: void skin_render_viewport(struct skin_element* viewport, struct gui_wps *gwps, ...)
763:     skin_buffer = get_skin_buffer(gwps->data);      /* sin comprobar */

840: void skin_render(struct gui_wps *gwps, unsigned refresh_mode)
851:     skin_buffer = get_skin_buffer(gwps->data);      /* sin comprobar */
```

`skin_buffer` se usa después como base para resolver desplazamientos, 60 veces
en el archivo, mediante la macro de `lib/skin_parser/skin_parser.h:45`:

```c
#define SKINOFFSETTOPTR(base, offset) \
    ({ void *__p = ((offset) < 0 ? NULL : ((void*)&base[offset])); __p; })
```

### Por qué las guardas existentes no sirven

El código ya comprueba los resultados:

```c
viewport = SKINOFFSETTOPTR(skin_buffer, data->tree);
if (!viewport) return;
```

Pero con `base == NULL` y `offset >= 0`, la macro devuelve **la dirección
`offset`**: un número pequeño **distinto de cero**. La guarda `if (!viewport)`
lo deja pasar, y la desreferencia siguiente revienta.

Eso explica exactamente las dos direcciones observadas: `0x00000000` para
offset 0 sobre base nula, y `0x33428f00` para una base obsoleta más offset.

### Por qué lo dispara "Gather runtime data"

Rockbox usa **buflib**, un asignador compactador con manejadores. Con el ajuste
activo, la caché de etiquetas escribe datos de reproducción en cada cambio de
pista, lo que provoca asignaciones y compactación. Bajo presión, buflib puede
mover o liberar el bloque del tema, dejando `data->buflib_handle <= 0`. La
siguiente entrada al WPS llama a `get_skin_buffer()`, recibe NULL, y cae.

Con el ajuste desactivado esa presión no existe y el fallo no aparece, que es
justo lo observado.

---

## 3. Parche propuesto

### Capa 1 — Guarda defensiva (mínima, segura, enviable a upstream)

```diff
--- a/apps/gui/skin_engine/skin_render.c
+++ b/apps/gui/skin_engine/skin_render.c
@@ -760,7 +760,12 @@ void skin_render_viewport(struct skin_element* viewport,
     struct align_pos * align = &info.align;
     bool needs_update, update_all = false;
     skin_buffer = get_skin_buffer(gwps->data);
+    /* El bloque del tema vive en buflib y puede ser liberado o movido por la
+     * compactacion (p.ej. al escribir runtime data en la tagcache). Con base
+     * NULL, SKINOFFSETTOPTR devuelve la propia direccion `offset`, que NO es
+     * NULL y por tanto burla las guardas `if (!ptr)` de mas abajo. */
+    if (!skin_buffer)
+        return;
     /* Set images to not to be displayed */
     struct skin_token_list *imglist = SKINOFFSETTOPTR(skin_buffer, gwps->data->images);

@@ -848,7 +853,10 @@ void skin_render(struct gui_wps *gwps, unsigned refresh_mode)
     int old_refresh_mode = refresh_mode;
     skin_buffer = get_skin_buffer(gwps->data);
+    /* Ver comentario en skin_render_viewport(): base NULL produce punteros
+     * pequenos no nulos que pasan las guardas y luego segfaultean. */
+    if (!skin_buffer)
+        return;
```

Efecto: convierte un SIGSEGV en un fotograma no dibujado. La pantalla puede
parpadear una vez mientras el tema se recarga, pero **no se cae la aplicación**.

### Capa 2 — Causa de fondo (requiere más trabajo)

La guarda evita el crash pero no explica por qué el manejador queda inválido.
Hay que instrumentar `skin_load()` y el callback de buflib del tema:

- ¿El bloque tiene `shrink_callback` que lo libera bajo presión sin avisar al
  WPS? Revisar `skin_buffer.c` y `skin_parser.c`.
- ¿`skin_load()` falla en silencio y deja `wps_loaded == false` con
  `buflib_handle` inválido? En `skin_engine.c:311` la recarga se intenta pero
  **no se comprueba el resultado**:

```c
if (skins[skin][screen].data.wps_loaded == false)
{
    cpu_boost(true);
    skin_load(skin, screen, buf, true);   /* valor de retorno ignorado */
    cpu_boost(false);
}
return &skins[skin][screen].gui_wps;      /* se devuelve pase lo que pase */
```

Una segunda guarda razonable sería que `skin_get_gwps()` devuelva el tema
integrado (built-in) si la recarga falla, en lugar de una estructura rota.

---

## 4. Cómo compilarlo

**Aviso honesto**: no conozco la receta exacta del port del Y1. Es un port
comunitario y el árbol de Rockbox oficial no lo incluye. Habría que partir del
repositorio del port, no del oficial, o localizar sus parches.

Con el árbol correcto, el flujo estándar de Rockbox para Android es:

```bash
git clone https://github.com/Rockbox/rockbox.git && cd rockbox
git checkout 13861b2e0ead          # misma base que tu build
mkdir build && cd build
../tools/configure                 # elegir target y "Android" como tipo
make -j8 && make apk
```

Requiere el SDK y NDK de Android y la toolchain ARM de Rockbox
(`../tools/rockboxdev.sh`). El NDK que soporta API 17 es antiguo (r14b o
similar), lo que en un Mac con Apple Silicon puede obligar a usar Docker.

**Alternativa más barata para validar**: compilar el simulador y reproducir
allí primero.

```bash
../tools/configure    # elegir target y "Simulator"
make -j8 && ./rockboxui
```

Si el simulador reproduce el fallo, el ciclo de prueba baja de horas a minutos.

---

## 5. Plan de verificación

1. **Reproducir sin parche** en el simulador con una biblioteca grande y
   *Gather runtime data* activo. Confirmar el SIGSEGV en `skin_render`.
2. **Aplicar la capa 1** y comprobar que ya no cae, aunque parpadee.
3. **Instrumentar** con `logf` en `get_skin_buffer()` cuando devuelva NULL,
   para medir con qué frecuencia ocurre y confirmar la hipótesis de buflib.
4. **En el aparato real**: instalar el APK, activar el ajuste, reproducir 20-30
   pistas seguidas y verificar que `playcount` y `autoscore` se incrementan en
   `Database → Playback History → Most played`.
5. Comprobar que las emisoras de `tagnavi_custom.config` que dependen de
   `autoscore` empiezan a poblarse.

---

## 6. Enviarlo a upstream

La capa 1 es genuinamente enviable: corrige una desreferencia de puntero real,
es de dos líneas por sitio, no cambia comportamiento cuando el buffer es
válido, y el razonamiento sobre la macro es verificable.

Rockbox usa **Gerrit**, no pull requests de GitHub:
`https://gerrit.rockbox.org` — hace falta cuenta y `git-review`.

Merece la pena adjuntar la traza de pila y la explicación de por qué
`SKINOFFSETTOPTR` con base nula burla las guardas: ese es el detalle no obvio
que justifica el parche.
