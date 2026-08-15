#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
#include <setjmp.h>
typedef long skinoffset_t;
#include "macro.inc"

static jmp_buf jb;
static void on_segv(int s){ (void)s; longjmp(jb, 1); }

int main(void)
{
    char *base_ok  = malloc(256);          /* buffer valido   */
    char *base_bad = NULL;                 /* lo que devuelve get_skin_buffer() al fallar */

    printf("Comportamiento de SKINOFFSETTOPTR segun la base:\n\n");
    printf("  %-34s %-14s %-22s\n", "CASO", "RESULTADO", "¿PASA if(!ptr)?");
    void *p;

    p = SKINOFFSETTOPTR(base_ok, 8);
    printf("  %-34s %-14p %-22s\n", "base valida, offset 8", p, p ? "si (correcto)" : "no");

    p = SKINOFFSETTOPTR(base_bad, -1);
    printf("  %-34s %-14p %-22s\n", "base NULL, offset -1", p, p ? "si" : "NO -> guarda funciona");

    p = SKINOFFSETTOPTR(base_bad, 0);
    printf("  %-34s %-14p %-22s\n", "base NULL, offset 0", p, p ? "SI -> BURLA LA GUARDA" : "no");

    p = SKINOFFSETTOPTR(base_bad, 0x1234);
    printf("  %-34s %-14p %-22s\n", "base NULL, offset 0x1234", p, p ? "SI -> BURLA LA GUARDA" : "no");

    printf("\nAhora se hace lo que hace skin_render(): comprobar y desreferenciar.\n");
    void *viewport = SKINOFFSETTOPTR(base_bad, 0x1234);
    if (!viewport) { printf("  la guarda lo atrapo, no hay fallo\n"); return 0; }
    printf("  la guarda NO lo atrapo (ptr=%p); desreferenciando...\n", viewport);

    signal(SIGSEGV, on_segv);
    if (setjmp(jb) == 0) {
        volatile int leido = *(int*)viewport;
        printf("  leido: %d (sin fallo)\n", leido);
    } else {
        printf("  >>> SIGSEGV en %p — exactamente el fallo del aparato\n", viewport);
    }
    return 0;
}
