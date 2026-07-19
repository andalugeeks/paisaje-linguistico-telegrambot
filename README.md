# Bot Paisaje Lingüístico Andaluz

Bot de Telegram que detecta fotos compartidas en el grupo y guía a la persona
por privado para completar y subir su aportación a andaluh.ushahidi.io.

## Configuración en BotFather

1. Habla con @BotFather → `/newbot` → guarda el token.
2. **Importante**: `/setprivacy` → tu bot → `Disable`. Sin esto el bot no ve
   las fotos del grupo (solo vería comandos).
3. Añade el bot al grupo t.me/paisajeand.

## Variables de entorno

```bash
export TELEGRAM_TOKEN="123456:ABC..."
export USHAHIDI_EMAIL="usuario@ejemplo.com"      # cuenta en andaluh.ushahidi.io
export USHAHIDI_PASSWORD="********"
```

## Ejecución

```bash
pip install -r requirements.txt
python bot.py
```

## Estructura

- `bot.py` — handlers de Telegram y máquina de estados de la conversación
- `ushahidi.py` — cliente de la API (OAuth2, subida de media, creación de posts)
- `config.py` — ids y claves de los campos de la encuesta "Corpus"

## Notas para la primera prueba

- Los posts entran como *pendientes de revisión* (`require_approval: true` en
  la encuesta), así que hay que aprobarlos desde la web de Ushahidi.
- Si `create_post` devuelve un 422, el cuerpo de la respuesta indica campo a
  campo qué no le ha gustado: los formatos del valor de `media` y de los
  `checkbox` son los dos candidatos a necesitar un pequeño ajuste.
- El estado se guarda en memoria: si el bot se reinicia a mitad de una
  conversación, esa aportación se pierde. Se puede añadir persistencia con
  `PicklePersistence` de python-telegram-bot más adelante.
