"""Constantes y reglas. Todo lo especifico del Y1 vive aqui."""
from pathlib import Path

# --- Rutas -------------------------------------------------------------
# La tarjeta se monta en el Mac cuando el Y1 entra en modo almacenamiento USB.
CARD_NAME = "NO NAME"
CARD_ROOT = Path("/Volumes") / CARD_NAME
# Rockbox ve la tarjeta aqui. Verificado leyendo su indice database_4.tcd.
DEVICE_PREFIX = "/sdcard"

MUSIC_DIR = "Music"
PLAYLIST_DIR = "Playlists"
ROCKBOX_DIR = ".rockbox"
PLAYBACK_LOG = "playback.log"

DB_PATH = Path.home() / "Music" / "y1_biblioteca.db"
BACKUP_DIR = Path.home() / "Music" / "y1_backups"

# --- Audio -------------------------------------------------------------
# AudioFlinger del MT6572 entrega 44100 Hz / 16 bits fijos. Cualquier otra
# cosa se remuestrea en tiempo real en un Cortex-A7 de 2013.
TARGET_RATE = 44100
TARGET_BITS = 16
# ffmpeg de Homebrew no trae libsoxr; swr con precision 33 es equivalente
# a efectos practicos para salida de 16 bits.
RESAMPLER_ARGS = (
    "aresample=out_sample_rate=44100:out_sample_fmt=s16"
    ":resampler=swr:precision=33:dither_method=triangular_hp"
)

# --- Caratulas ---------------------------------------------------------
ARTWORK_MAX = 500          # lado maximo en pixeles
ARTWORK_QUALITY = 90

# --- MusicBrainz -------------------------------------------------------
MB_BASE = "https://musicbrainz.org/ws/2"
MB_UA = "Y1Sync/1.0 ( https://github.com/juan52878911/y1-sync )"
MB_DELAY = 1.1             # la API exige 1 req/s; margen de seguridad
MB_MIN_SCORE = 70          # por debajo, la coincidencia no es fiable

# --- Generos -----------------------------------------------------------
# Ruido habitual en los tags de la comunidad de MusicBrainz.
GENRE_NOISE = (
    r"on cover|seen live|favorit|wochen|owned|vinyl|albums i|"
    r"male vocal|female vocal|^\d"
)
# (cubo, patron, peso). Puntuacion ponderada, NO primera coincidencia:
# con orden simple, `dance` y `electro` (tags secundarios de medio catalogo)
# mandaban a Electronica artistas de pop y R&B.
GENRE_RULES = [
    ("Trap Underground", r"cloud rap|horrorcore|memphis rap|phonk|trap metal|hardcore hip hop", 5),
    ("Trap Underground", r"\btrap\b", 3),
    ("Metalcore",        r"metalcore|deathcore|post-hardcore|screamo", 5),
    ("Nu Metal",         r"nu metal|rap metal|funk metal", 5),
    ("Metal Industrial", r"industrial metal|neue deutsche härte|industrial rock", 5),
    ("Metal Extremo",    r"death metal|black metal|melodic death|grindcore|doom metal", 5),
    ("Metal Extremo",    r"thrash metal", 3),
    ("Metal",            r"groove metal|heavy metal|progressive metal|power metal", 4),
    ("Metal",            r"\bmetal\b", 1),
    ("Latino",           r"reggaeton|latin trap|dembow|bachata|salsa|cumbia|bolero|ranchera", 5),
    ("Latino",           r"\blatin\b", 2),
    ("Rap",              r"boom bap|conscious hip hop|pop rap|gangsta rap", 4),
    ("Rap",              r"hip hop|\brap\b", 2),
    ("Electronica",      r"dubstep|brostep|drum and bass|techno|trance|idm|breakbeat|electro house|edm", 5),
    ("Electronica",      r"electronica|electronic|\bhouse\b|synthwave", 2),
    ("Rock Alternativo", r"indie rock|art rock|post-punk|shoegaze|grunge|britpop|garage rock", 4),
    ("Rock Alternativo", r"alternative rock", 3),
    ("Rock",             r"pop punk|punk|hard rock|classic rock|psychedelic rock|blues rock|\bska\b", 4),
    ("Rock",             r"pop rock|\brock\b", 1),
    ("R&B y Soul",       r"neo soul|motown|contemporary r&b|\bsoul\b|\bfunk\b", 4),
    ("R&B y Soul",       r"r&b", 3),
    ("Pop",              r"dance-pop|synth-pop|electropop|art pop", 3),
    ("Pop",              r"\bpop\b", 1),
    ("Folk y Cantautor", r"folk|trova|nueva canci|acoustic|singer-songwriter", 4),
]
# Artistas donde MusicBrainz no acierta o no tiene datos.
GENRE_OVERRIDES = {
    "Skrillex": "Electronica", "The Weeknd": "R&B y Soul", "Muse": "Rock Alternativo",
    "Radiohead": "Rock Alternativo", "Deftones": "Nu Metal", "Seal": "Pop",
    "No Doubt": "Rock", "Metallica": "Metal", "Pantera": "Metal",
    "Alcolirykoz": "Rap Espanol", "Oblivion's Mighty Trash": "Rap Espanol",
    "Noiseferatu": "Rap Espanol", "Buhodermia": "Rap Espanol", "Chite": "Rock",
    "Thaissa": "Indie Latino", "Laura Pérez": "Folk y Cantautor",
    "Celeste": "R&B y Soul", "Duplat": "Indie Latino", "León Larregui": "Indie Latino",
    "Zoé": "Indie Latino", "La gusana ciega": "Indie Latino", "Rupatrupa": "Indie Latino",
    "Daniel, Me Estás Matando": "Latino", "CA7RIEL": "Latino", "Tokischa": "Latino",
    "Nathy Peluso": "Latino", "Milo J": "Latino", "Bad Bunny": "Latino",
    "Silvio Rodríguez": "Folk y Cantautor", "Roberto Carlos": "Folk y Cantautor",
    "The sacred souls": "R&B y Soul", "$uicideboy$": "Trap Underground",
}
