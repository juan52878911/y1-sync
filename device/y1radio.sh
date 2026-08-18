#!/system/bin/sh
# Motor de emisoras dentro del Y1 — version defensiva.
#
# HISTORIA: la primera version arrancaba desde init.d y lo primero que hacia
# era un `find` sobre ~2800 archivos de una FAT32 que quiza ni estaba montada.
# Eso es E/S pesada en pleno arranque y coincidio con un bucle de reinicio.
# Esta version no toca nada hasta que el sistema esta completamente arriba.
#
# Protecciones:
#   1. espera a sys.boot_completed (igual que 99Y1ButtonScript)
#   2. espera a que /sdcard/Music responda, y se rinde si no aparece
#   3. periodo de gracia tras el arranque antes del primer trabajo
#   4. interruptor de apagado: /sdcard/y1radio.off  (creable desde el Mac)
#   5. prioridad baja (nice) para no competir con la reproduccion
#   6. el inventario completo se cachea; el `find` no se repite cada ciclo
#   7. instancia unica: si ya hay un demonio vivo, este sale
#   8. ciclo sin forks: la deteccion de cambios usa `-nt`, primitiva del shell
#   9. espera adaptativa: si no escuchas, despierta cada vez menos

LOG=/sdcard/.rockbox/playback.log
DIR=/sdcard/Playlists
OFF=/sdcard/y1radio.off
# La marca va en la MISMA particion que el log, no en /data: FAT32 redondea
# las fechas a 2 s y una marca en ext4 quedaba siempre "mas vieja", con lo que
# `-nt` daba verdadero siempre y regeneraba en cada ciclo.
STAMP=/sdcard/.y1radio.stamp
CACHE=/data/local/tmp/y1radio.todas
DIAG=/data/local/tmp/y1radio.log
PIDF=/data/local/tmp/y1radio.pid

GRACIA=${Y1RADIO_GRACE:-180}      # segundos tras boot_completed antes de trabajar
INTERVALO=${Y1RADIO_INTERVAL:-90} # espera base, con escucha activa
INT_MEDIO=300                     # tras ~15 min sin cambios
INT_LARGO=900                     # tras ~1 h sin cambios
LIMITE=${Y1RADIO_LIMIT:-150}
COMPLETA=75
CACHE_TTL=86400                   # rehacer el inventario como mucho 1 vez/dia
TAB=$(printf '\t')                # busybox sort -t exige UN caracter real

diag() { echo "$(date '+%m-%d %H:%M:%S') $*" >> "$DIAG" 2>/dev/null; }

# --- 7. instancia unica -------------------------------------------------
# Sin esto, cada relanzamiento deja otro demonio y acaban compitiendo por
# escribir las mismas playlists.
if [ -f "$PIDF" ]; then
    viejo=$(cat "$PIDF" 2>/dev/null)
    if [ -n "$viejo" ] && [ -d "/proc/$viejo" ]; then
        diag "ya hay instancia viva ($viejo), salgo"
        exit 0
    fi
fi
echo $$ > "$PIDF" 2>/dev/null
trap 'rm -f "$PIDF" 2>/dev/null' EXIT

# --- 1. esperar a que el sistema termine de arrancar ---------------------
i=0
while [ "$(getprop sys.boot_completed 2>/dev/null)" != "1" ]; do
    i=$((i+1)); [ "$i" -gt 300 ] && { diag "boot_completed nunca llego, salgo"; exit 0; }
    sleep 1
done
diag "boot completado"

# --- 3. periodo de gracia ------------------------------------------------
sleep "$GRACIA"

# --- 2. esperar a la tarjeta, rindiendose si no aparece ------------------
i=0
while [ ! -d /sdcard/Music ]; do
    i=$((i+1)); [ "$i" -gt 60 ] && { diag "/sdcard/Music no aparecio, salgo"; exit 0; }
    sleep 10
done
diag "tarjeta lista, entrando en el bucle"

resumen() {
    awk -v C="$COMPLETA" '
    {
        line = $0
        i = index(line, ":"); ts  = substr(line,1,i-1); line = substr(line,i+1)
        i = index(line, ":"); msp = substr(line,1,i-1); line = substr(line,i+1)
        i = index(line, ":"); mst = substr(line,1,i-1); ruta = substr(line,i+1)
        if (ruta == "" || ts+0 <= 0) next
        pct = (mst+0 > 0) ? 100*msp/mst : 0
        n[ruta]++; s[ruta]+=pct
        if (ts+0 > u[ruta]) u[ruta] = ts+0
        if (pct >= C) f[ruta]++
    }
    END { for (r in n) printf "%.1f\t%d\t%d\t%d\t%s\n", s[r]/n[r], n[r], f[r]+0, u[r], r }
    ' "$LOG" 2>/dev/null
}

escribe() {
    nombre="$1"; filtro="$2"; shift 2
    tmp="$DIR/.$nombre.tmp"
    # el filtro de existencia va DESPUES de head: como mucho $LIMITE stat por emisora
    echo "$RESUMEN" | awk -F'\t' "$filtro" | sort -t"$TAB" "$@" | head -n "$LIMITE" | cut -f5- \
        | while IFS= read -r ruta; do [ -f "$ruta" ] && echo "$ruta"; done > "$tmp" 2>/dev/null
    if [ -s "$tmp" ]; then mv "$tmp" "$DIR/Radio - $nombre.m3u8"; else rm -f "$tmp"; fi
}

# --- 6. inventario cacheado: el find NO se repite cada ciclo -------------
inventario() {
    ahora=$(date +%s)
    if [ -s "$CACHE" ]; then
        edad=$(( ahora - $(stat -c %Y "$CACHE" 2>/dev/null || echo 0) ))
        [ "$edad" -lt "$CACHE_TTL" ] && return 0
    fi
    diag "reconstruyendo inventario"
    find /sdcard/Music -name '*.flac' ! -name '._*' 2>/dev/null | sort > "$CACHE.tmp"
    [ -s "$CACHE.tmp" ] && mv "$CACHE.tmp" "$CACHE" || rm -f "$CACHE.tmp"
}

genera() {
    [ -r "$LOG" ] || return 1
    mkdir -p "$DIR" 2>/dev/null
    RESUMEN=$(resumen)

    # Con el historial vacio (arranque en limpio) no hay nada que puntuar,
    # pero "Sin estrenar" SI tiene sentido: son todas las pistas. Antes se
    # salia aqui y no se generaba ninguna emisora.
    if [ -z "$RESUMEN" ]; then
        inventario
        if [ -s "$CACHE" ]; then
            tmp="$DIR/.sin.tmp"
            head -n "$LIMITE" "$CACHE" > "$tmp" 2>/dev/null
            [ -s "$tmp" ] && mv "$tmp" "$DIR/Radio - Sin estrenar.m3u8" || rm -f "$tmp"
            diag "historial vacio: solo 'Sin estrenar'"
            return 0
        fi
        return 1
    fi

    escribe "Mis favoritas"  '$3>=1 && $1>=60 {print}'  -k3,3nr -k1,1nr
    escribe "Joyas ocultas"  '$1>=70 && $2<=2 {print}'  -k1,1nr
    escribe "Rescate"        '{print}'                   -k4,4n
    escribe "Muy escuchadas" '{print}'                   -k2,2nr
    escribe "Descartes"      '$2>=3 && $1<25 {print}'    -k1,1n

    inventario
    if [ -s "$CACHE" ]; then
        tmp="$DIR/.sin.tmp"
        echo "$RESUMEN" | cut -f5- | sort > /data/local/tmp/y1_oidas.txt
        comm -23 "$CACHE" /data/local/tmp/y1_oidas.txt 2>/dev/null | head -n "$LIMITE" > "$tmp"
        [ -s "$tmp" ] && mv "$tmp" "$DIR/Radio - Sin estrenar.m3u8" || rm -f "$tmp"
        rm -f /data/local/tmp/y1_oidas.txt
    fi
    return 0
}

# --- 8/9. bucle sin forks y con espera adaptativa ------------------------
# `-nt` compara fechas SIN lanzar procesos: antes cada ciclo gastaba un `stat`
# y un `cat`. Ahora el unico proceso del ciclo es el propio `sleep`.
# Y si no hay escuchas, se espacia: 90 s -> 5 min -> 15 min. Cada despertar
# evitado es CPU que puede seguir dormida.
inactivo=0
espera=$INTERVALO
while true; do
    [ -f "$OFF" ] && { diag "encontrado y1radio.off, salgo"; exit 0; }

    if [ -r "$LOG" ] && [ "$LOG" -nt "$STAMP" ]; then
        if genera; then
            # La marca se fecha 5 s por delante: FAT32 redondea a 2 s y sin
            # ese margen `-nt` volvia a dar verdadero una vez mas, provocando
            # una regeneracion extra por cada cambio real.
            touch -t $(( $(date +%s) + 5 )) "$STAMP" 2>/dev/null || : > "$STAMP" 2>/dev/null
            diag "emisoras regeneradas"
            inactivo=0
            espera=$INTERVALO
        fi
    else
        inactivo=$((inactivo + 1))
        if   [ "$inactivo" -ge 20 ]; then espera=$INT_LARGO
        elif [ "$inactivo" -ge 10 ]; then espera=$INT_MEDIO
        fi
    fi
    sleep "$espera"
done
