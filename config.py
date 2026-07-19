"""Configuración del bot Paisaje Lingüístico Andaluz."""
import os

# --- Telegram ---
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]  # de @BotFather

# --- Ushahidi ---
USHAHIDI_BASE = "https://andaluh.api.ushahidi.io"
USHAHIDI_EMAIL = os.environ["USHAHIDI_EMAIL"]        # usuario del despliegue
USHAHIDI_PASSWORD = os.environ["USHAHIDI_PASSWORD"]
# Credenciales de cliente OAuth2 públicas estándar de la plataforma Ushahidi
USHAHIDI_CLIENT_ID = os.environ.get("USHAHIDI_CLIENT_ID", "ushahidiui")
USHAHIDI_CLIENT_SECRET = os.environ.get(
    "USHAHIDI_CLIENT_SECRET", "35e7f0bca957836d05ca0492211b0ac707671261"
)

# --- Estructura de la encuesta "Corpus" (obtenida de /api/v5/surveys) ---
FORM_ID = 1
TASK_ID = 1          # tarea "Structure"
FIELD_LOCATION = {"id": 1, "key": "location_default", "type": "point", "input": "location"}
FIELD_TITLE_ID = 3   # "Transcripción" -> title del post
FIELD_DESC_ID = 4    # "Descripción"   -> content del post
FIELD_PHOTO = {"id": 6, "key": "5b4b6286-8eac-4473-b57d-783bb2d8d860", "type": "media", "input": "upload"}
FIELD_LETRERO = {"id": 12, "key": "8bb3bf4d-2258-4109-9095-65d4b9f72ad7", "type": "varchar", "input": "checkbox"}
FIELD_DISCURSO = {"id": 13, "key": "f0d6e149-95de-4df5-b4a9-22dfe3db6485", "type": "varchar", "input": "checkbox"}

OPCIONES_LETRERO = [
    "Grafiti", "Pegatina", "Rótulo", "Póster", "Expositor",
    "Pizarra", "Señal", "Pantalla", "Otro",
]
OPCIONES_DISCURSO = [
    "Político/social", "Informativo", "Publicitario",
    "Lingüística", "Expresivo/artístico", "Otro",
]

MAX_TITLE_LEN = 150  # límite del campo title en Ushahidi
