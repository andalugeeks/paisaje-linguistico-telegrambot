# CLAUDE.md — Bot Paisaje Lingüístico Andaluz

## Qué es este proyecto

Bot de Telegram que automatiza la subida de aportaciones al despliegue Ushahidi
del Paisaje Lingüístico Andaluz (https://andaluh.ushahidi.io). La gente comparte
fotos de letreros en lengua andaluza en el grupo de Telegram (t.me/paisajeand);
el bot las detecta, guía a la persona por chat privado para completar los
metadatos, y crea el post en Ushahidi vía API.

## Flujo funcional (ya implementado)

1. **Grupo**: `MessageHandler((filters.PHOTO | filters.Document.IMAGE) & GROUPS)`
   detecta la imagen (foto comprimida o enviada como archivo: copiar-pegar de
   escritorio y "sin compresión" llegan como document), guarda `file_id` +
   autor + filename/mime en `bot_data["pending"][token]` y responde con un
   botón deep-link `t.me/<bot>?start=<token>`.
2. **Privado** (ConversationHandler, estados en este orden):
   - `CONFIRM_PHOTO`: muestra la foto, confirma que es la correcta.
   - `AUTH_CHOICE` / `AUTH_EMAIL` / `AUTH_PASSWORD`: elección de cuenta de
     Ushahidi — (a) cuenta por defecto del bot (env vars, identifica subidas
     vía Telegram), (b) cuenta propia (login validado con `check_login()`),
     (c) crear cuenta (`register_user()`, POST /api/v3/register). El mensaje
     con la contraseña se borra del chat; los clientes por usuario viven en
     el dict en memoria `user_clients` (se pierden al reiniciar → se
     repregunta). La elección se recuerda entre aportaciones; `/cuenta` la
     olvida. ⚠️ El registro está DESACTIVADO en el despliegue
     (`disable_registration: enabled` en /api/v3/config/features): la opción
     (c) fallará hasta activarlo en el panel de Ushahidi.
   - `LOCATION`: acepta ubicación compartida de Telegram, enlaces de Google
     Maps, el nombre/dirección del sitio escrito, o coordenadas "lat, lon".
     ⚠️ Los enlaces compartidos desde el móvil YA NO llevan coordenadas:
     `maps.app.goo.gl` redirige a `/maps/place/<dirección>` y `share.google`
     a una búsqueda de Google con `q=<nombre>` (y Google bloquea con captcha
     el scraping desde servidores). Por eso el bot extrae el nombre/dirección
     de la URL final y lo geocodifica con Nominatim (OSM, sin API key,
     sesgo hacia Andalucía, probando variantes: consulta entera → nombre →
     dirección). Como geocodificar por nombre puede fallar, el bot enseña el
     pin en el mapa y pide confirmación (estado `LOCATION_CONFIRM`) antes de
     seguir. Verificado (jul-2026) con enlaces reales del grupo.
   - `TRANSCRIPTION`: texto libre, máx. 150 chars (es el `title` del post).
   - `DESCRIPTION`: texto libre (es el `content` del post).
   - `LETRERO` y `DISCURSO`: teclados inline multi-selección con toggle ✅.
   - `REVIEW`: resumen + Enviar/Cancelar. Al enviar: descarga la foto de
     Telegram → sube a Ushahidi media (v3) → crea post (v5) → confirma en
     privado y avisa en el grupo respondiendo a la foto original.
3. **Entrada alternativa (histórico)**: enviar/reenviar una foto directamente
   al bot por privado arranca el mismo flujo desde LOCATION (sin token, sin
   confirmación de foto y sin aviso en el grupo: `group_chat_id=None`). Al
   terminar, el bot invita a mandar la siguiente foto, pensado para vaciar el
   histórico del grupo en cadena. Ojo: si se reenvía un álbum entero, cada foto
   intenta entrar como conversación nueva pero solo la primera arranca (las
   demás se ignoran mientras hay conversación activa) → reenviar de una en una.
4. `/cancelar` como fallback en cualquier punto.

## Arquitectura

- `bot.py` — handlers de Telegram y máquina de estados. python-telegram-bot v21+ (async).
- `ushahidi.py` — `UshahidiClient(email=None, password=None)`: OAuth2 password
  grant con caché de token (sin args usa la cuenta por defecto de config),
  `check_login()`, `upload_media()` (POST /api/v3/media, multipart),
  `create_post()` (POST /api/v5/posts). Función suelta `register_user()`
  (POST /api/v3/register, sin auth).
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
1. ~~Formato del campo media~~ RESUELTO (jul-2026): la API exige que
   `value.value` de un campo media sea una **lista** de ids
   (`{"value": [<media_id>]}`) — validación en PostRequest.php del platform
   (`media_field_must_be_array`). El primer 422 real solo se quejó del media,
   así que el formato de los checkbox (lista de strings) pasa la validación.
   Queda confirmar que el post entero entra y se ve bien en la web.
2. Verificar que el aviso en grupo funciona (el bot necesita privacidad
   desactivada en BotFather: `/setprivacy` → Disable).
3. Probar el flujo de cuentas: login con cuenta propia y, si se quiere ofrecer
   el alta desde el bot, activar el registro en los ajustes de Ushahidi
   (ahora `disable_registration` está activo y /api/v3/register devuelve 500
   con cuerpo vacío — sin activarlo no se puede validar el formato del body).

**Backlog acordado con el usuario**:
- Persistencia (PicklePersistence o SQLite) para no perder conversaciones a
  medias si el bot se reinicia; recordatorio a las 24h de borradores abandonados.
  ⚠️ Al añadirla, NO persistir contraseñas ni el dict `user_clients` (contiene
  credenciales y un httpx client no picklable): mejor guardar solo el email y
  repedir la contraseña tras un reinicio, o pasar a tokens.
- Álbumes: la foto tiene cardinality 1 en Ushahidi; si alguien manda un álbum,
  tratar cada foto como aportación separada (ahora cada foto del álbum genera
  su propio botón, lo cual ya funciona pero puede ser ruidoso: valorar agrupar).
- Si el usuario marca "Otro" en letrero/discurso, pedir texto que lo especifique
  (idea de diseño comentada, no implementada).
- Despliegue 24/7: Docker Compose YA LISTO (Dockerfile + docker-compose.yml,
  `env_file: .env`, `restart: unless-stopped`); falta solo elegir dónde
  hospedarlo (VPS / Railway / Fly.io).

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
