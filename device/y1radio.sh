#!/system/bin/sh
# Motor de emisoras en el propio Y1.
#
# Lee el historial que escribe Rockbox y regenera las playlists .m3u8 sin
# tocar la tagcache, que es lo que hace reventar el ajuste "Gather runtime
# data" (ver docs/rockbox-skin-render-crash.md).
#
# Se ejecuta desacoplado desde /system/etc/init.d/98Y1Radio.

LOG=/sdcard/.rockbox/playback.log
DIR=/sdcard/Playlists
STAMP=/data/local/tmp/y1radio.stamp
INTERVALO=${Y1RADIO_INTERVAL:-90}   # segundos entre comprobaciones
LIMITE=${Y1RADIO_LIMIT:-150}         # pistas por emisora
COMPLETA=75                          # % a partir del cual cuenta como escucha real
TAB=$(printf '\t')                     # busybox sort -t exige UN caracter real

log() { echo "$(date '+%H:%M:%S') y1radio: $*"; }

# Emite: score \t repros \t completas \t ultima \t ruta
resumen() {
    awk -v C="$COMPLETA" '
    {
        line = $0
        # ts:ms:total:ruta  — la ruta puede llevar ":", asi que se recorta
        i = index(line, ":");            ts  = substr(line, 1, i-1); line = substr(line, i+1)
        i = index(line, ":");            msp = substr(line, 1, i-1); line = substr(line, i+1)
        i = index(line, ":");            mst = substr(line, 1, i-1); ruta = substr(line, i+1)
        if (ruta == "" || ts + 0 <= 0) next
        pct = (mst + 0 > 0) ? 100 * msp / mst : 0
        n[ruta]++
        s[ruta] += pct
        if (ts + 0 > u[ruta]) u[ruta] = ts + 0
        if (pct >= C) f[ruta]++
    }
    END { for (r in n) printf "%.1f\t%d\t%d\t%d\t%s\n", s[r]/n[r], n[r], f[r]+0, u[r], r }
    ' "$LOG"
}

# escribe <nombre> <criterio-awk> <claves de sort...>
escribe() {
    nombre="$1"; filtro="$2"; shift 2
    tmp="$DIR/.$nombre.tmp"
    # El filtro de existencia va DESPUES de head: asi se pagan como mucho
    # $LIMITE comprobaciones por emisora en vez de una por pista del historial.
    # Sin esto quedarian entradas muertas cuando se borran o renombran archivos.
    echo "$RESUMEN" | awk -F'\t' "$filtro" | sort -t"$TAB" "$@" | head -n "$LIMITE" | cut -f5- \
        | while IFS= read -r ruta; do [ -f "$ruta" ] && echo "$ruta"; done > "$tmp" 2>/dev/null
    if [ -s "$tmp" ]; then
        mv "$tmp" "$DIR/Radio - $nombre.m3u8"      # mv es atomico en el mismo fs
    else
        rm -f "$tmp"
    fi
}

genera() {
    [ -r "$LOG" ] || return 1
    mkdir -p "$DIR" 2>/dev/null
    RESUMEN=$(resumen)
    [ -n "$RESUMEN" ] || return 1

    #        nombre           filtro                                   orden
    escribe "Mis favoritas"  '$3>=1 && $1>=60 {print}'  -k3,3nr -k1,1nr
    escribe "Joyas ocultas"  '$1>=70 && $2<=2 {print}'  -k1,1nr
    escribe "Rescate"        '{print}'                   -k4,4n
    escribe "Muy escuchadas" '{print}'                   -k2,2nr
    escribe "Descartes"      '$2>=3 && $1<25 {print}'    -k1,1n

    # Sin estrenar: lo que esta en la tarjeta y no aparece en el historial
    tmp="$DIR/.sin.tmp"
    echo "$RESUMEN" | cut -f5- | sort > /data/local/tmp/y1_oidas.txt
    find /sdcard/Music -name '*.flac' ! -name '._*' 2>/dev/null | sort \
        | comm -23 - /data/local/tmp/y1_oidas.txt 2>/dev/null | head -n "$LIMITE" > "$tmp"
    [ -s "$tmp" ] && mv "$tmp" "$DIR/Radio - Sin estrenar.m3u8" || rm -f "$tmp"
    rm -f /data/local/tmp/y1_oidas.txt
    return 0
}

log "arrancado (intervalo ${INTERVALO}s, limite ${LIMITE})"
while true; do
    if [ -r "$LOG" ]; then
        actual=$(stat -c %Y%s "$LOG" 2>/dev/null)
        previo=$(cat "$STAMP" 2>/dev/null)
        if [ "$actual" != "$previo" ]; then
            if genera; then
                echo "$actual" > "$STAMP"
                log "emisoras regeneradas"
            fi
        fi
    fi
    sleep "$INTERVALO"
done
