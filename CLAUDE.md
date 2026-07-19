# CLAUDE.md — Bot Paisaje Lingüístico Andaluz

## Qué es este proyecto

Bot de Telegram que automatiza la subida de aportaciones al despliegue Ushahidi
del Paisaje Lingüístico Andaluz (https://andaluh.ushahidi.io). La gente comparte
fotos de letreros en lengua andaluza en el grupo de Telegram (t.me/paisajeand);
el bot las detecta, guía a la persona por chat privado para completar los
metadatos, y crea el post en Ushahidi vía API.

## Flujo funcional (ya implementado)

1. **Grupo**: `MessageHandler(filters.PHOTO & GROUPS)` detecta la foto, guarda
   `file_id` + autor en `bot_data["pending"][token]` y responde con un botón
   deep-link `t.me/<bot>?start=<token>`.
2. **Privado** (ConversationHandler, estados en este orden):
   - `CONFIRM_PHOTO`: muestra la foto, confirma que es la correcta.
   - `LOCATION`: acepta ubicación compartida de Telegram, enlaces de Google
     Maps (resuelve cortos maps.app.goo.gl siguiendo la redirección) o
     coordenadas escritas "lat, lon".
   - `TRANSCRIPTION`: texto libre, máx. 150 chars (es el `title` del post).
   - `DESCRIPTION`: texto libre (es el `content` del post).
   - `LETRERO` y `DISCURSO`: teclados inline multi-selección con toggle ✅.
   - `REVIEW`: resumen + Enviar/Cancelar. Al enviar: descarga la foto de
     Telegram → sube a Ushahidi media (v3) → crea post (v5) → confirma en
     privado y avisa en el grupo respondiendo a la foto original.
3. `/cancelar` como fallback en cualquier punto.

## Arquitectura

- `bot.py` — handlers de Telegram y máquina de estados. python-telegram-bot v21+ (async).
- `ushahidi.py` — `UshahidiClient`: OAuth2 password grant con caché de token,
  `upload_media()` (POST /api/v3/media, multipart), `create_post()` (POST /api/v5/posts).
- `config.py` — token, credenciales (por env vars) y **estructura de la
  encuesta "Corpus"** con los ids/keys reales obtenidos de
  `GET https://andaluh.api.ushahidi.io/api/v5/surveys`.

## Datos clave del despliegue Ushahidi (verificados contra la API real)

- Web: `andaluh.ushahidi.io` — **API: `andaluh.api.ushahidi.io`** (dominios distintos).
- Encuesta única "Corpus": `form_id=1`, una tarea "Structure" `task_id=1`.
- Campos (id / key / tipo):
  - 1 / `location_default` / point — Localización (obligatorio)
  - 3 / (uuid) / **title** — "Transcripción" → va como `title` a nivel raíz del post
  - 4 / (uuid) / **description** — "Descripción" → va como `content` a nivel raíz
  - 6 / `5b4b6286-...` / media, cardinality 1 — Foto (obligatorio, 1 sola)
  - 12 / `8bb3bf4d-...` / checkbox — Tipo de letrero, 9 opciones, default "Sin aportar"
  - 13 / `f0d6e149-...` / checkbox — Tipo de discurso, 6 opciones
- Las opciones de checkbox se envían como **strings literales con tildes**
  ("Rótulo", "Póster", "Político/social"...).
- `require_approval: true` → los posts entran pendientes de revisión (correcto,
  es el comportamiento deseado).
- OAuth2: grant password contra `/oauth/token` con client_id `ushahidiui` y el
  client_secret público estándar de la plataforma (ya en config.py como default).

## Estado actual y qué falta

**Hecho**: todo el flujo de conversación, cliente Ushahidi, mapeo de campos.
Compila; NO se ha probado aún contra Telegram ni Ushahidi reales.

**Pendiente inmediato (primera sesión de pruebas)**:
1. Probar el flujo end-to-end. Los dos puntos con riesgo de necesitar ajuste
   son el formato del `value` en `post_content` para el campo **media**
   (¿`{"value": <media_id>}` o lista?) y para los **checkbox**
   (¿`{"value": ["Rótulo"]}` o `{"value": {"value": [...]}}`). Si el POST
   devuelve 422, el body detalla campo a campo el problema: ajustar
   `_field_entry()` / `create_post()` en ushahidi.py según eso.
2. Verificar que el aviso en grupo funciona (el bot necesita privacidad
   desactivada en BotFather: `/setprivacy` → Disable).

**Backlog acordado con el usuario**:
- Persistencia (PicklePersistence o SQLite) para no perder conversaciones a
  medias si el bot se reinicia; recordatorio a las 24h de borradores abandonados.
- Álbumes: la foto tiene cardinality 1 en Ushahidi; si alguien manda un álbum,
  tratar cada foto como aportación separada (ahora cada foto del álbum genera
  su propio botón, lo cual ya funciona pero puede ser ruidoso: valorar agrupar).
- Si el usuario marca "Otro" en letrero/discurso, pedir texto que lo especifique
  (idea de diseño comentada, no implementada).
- Geocodificación de direcciones escritas (Nominatim) como cuarta vía de
  localización.
- Despliegue 24/7 (VPS / Railway / Fly.io) con systemd o Docker.

## Cómo ejecutar

```bash
pip install -r requirements.txt
export TELEGRAM_TOKEN=...        # de @BotFather
export USHAHIDI_EMAIL=...        # cuenta en andaluh.ushahidi.io
export USHAHIDI_PASSWORD=...
python bot.py
```

## Convenciones

- Todo el texto de cara al usuario en español, tono cercano, con emojis.
- El usuario del proyecto no es programador profesional: explicar los cambios
  con claridad y proponer un paso cada vez.
