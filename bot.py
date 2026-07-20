"""Bot de Telegram del Paisaje Lingüístico Andaluz.

Flujo:
1. Detecta fotos en el grupo y responde con un botón de enlace profundo.
2. En privado guía al usuario: cuenta de Ushahidi (propia, nueva o la del
   bot) → localización → transcripción → descripción → tipo de letrero
   → tipo de discurso → resumen y envío.
3. Sube la aportación a Ushahidi y confirma en el grupo.
"""
import re
import logging
from uuid import uuid4

import httpx
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters,
)

import config
from ushahidi import UshahidiClient, UshahidiError, register_user

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
# httpx loguea cada petición con la URL completa, que incluye el token del bot
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("paisajebot")

# Estados de la conversación
(CONFIRM_PHOTO, AUTH_CHOICE, AUTH_EMAIL, AUTH_PASSWORD,
 LOCATION, TRANSCRIPTION, DESCRIPTION, LETRERO, DISCURSO, REVIEW) = range(10)

# Cuenta por defecto (variables de entorno): identifica las subidas desde Telegram
ushahidi = UshahidiClient()
# Clientes con cuenta propia, por id de usuario de Telegram (solo en memoria:
# se pierden al reiniciar el bot y se vuelve a preguntar)
user_clients: dict[int, UshahidiClient] = {}

# --------------------------------------------------------------------------
# 1) Detección de fotos en el grupo
# --------------------------------------------------------------------------
async def group_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    token = uuid4().hex[:12]
    context.bot_data.setdefault("pending", {})[token] = {
        "file_id": msg.photo[-1].file_id,
        "user_id": msg.from_user.id,
        "group_chat_id": msg.chat_id,
        "group_message_id": msg.message_id,
        "user_name": msg.from_user.first_name,
    }
    url = f"https://t.me/{context.bot.username}?start={token}"
    await msg.reply_text(
        f"📸 ¡Gracias, {msg.from_user.first_name}! Para subir tu foto al mapa "
        "del Paisaje Lingüístico Andaluz, pulsa el botón y completa los datos "
        "en privado conmigo.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Completar aportación ➡️", url=url)]]
        ),
    )


# --------------------------------------------------------------------------
# 2) Conversación privada
# --------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "¡Hola! 👋 Soy el bot del Paisaje Lingüístico Andaluz.\n"
            "Comparte una foto en el grupo y te ayudaré a subirla al mapa."
        )
        return ConversationHandler.END

    token = context.args[0]
    pending = context.bot_data.get("pending", {}).get(token)
    if not pending:
        await update.message.reply_text(
            "🤔 No encuentro esa aportación (puede que ya se haya completado). "
            "Vuelve a compartir la foto en el grupo si hace falta."
        )
        return ConversationHandler.END
    if pending["user_id"] != update.effective_user.id:
        await update.message.reply_text("Esa foto la compartió otra persona 😉")
        return ConversationHandler.END

    context.user_data["draft"] = dict(pending, token=token,
                                      letrero=set(), discurso=set())
    await update.message.reply_photo(
        pending["file_id"],
        caption="¿Es esta la foto que quieres subir al mapa?",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Sí, seguir", callback_data="photo:ok"),
            InlineKeyboardButton("❌ Cancelar", callback_data="photo:no"),
        ]]),
    )
    return CONFIRM_PHOTO


async def private_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entrada alternativa: el usuario envía/reenvía una foto por privado
    (útil para subir el histórico del grupo). Sin token ni aviso en grupo."""
    msg = update.effective_message
    context.user_data["draft"] = {
        "file_id": msg.photo[-1].file_id,
        "user_name": update.effective_user.first_name,
        "token": None,
        "group_chat_id": None,
        "group_message_id": None,
        "letrero": set(),
        "discurso": set(),
    }
    await msg.reply_text("📸 ¡Foto recibida! Vamos a subirla al mapa.")
    return await _maybe_ask_account(update, context)


async def confirm_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "photo:no":
        await q.message.reply_text("Sin problema, aportación cancelada. 👋")
        context.user_data.clear()
        return ConversationHandler.END
    return await _maybe_ask_account(update, context)


# --------------------------------------------------------------------------
# 2b) Elección de cuenta de Ushahidi
# --------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _account_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Seguir sin cuenta propia (lo más fácil)",
                              callback_data="acc:default")],
        [InlineKeyboardButton("🙋 Usar mi cuenta de Ushahidi",
                              callback_data="acc:login")],
        [InlineKeyboardButton("✨ Crear una cuenta nueva",
                              callback_data="acc:signup")],
    ])


async def _goto_location(chat) -> int:
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Compartir mi ubicación", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    await chat.send_message(
        "📍 *¿Dónde está el letrero?*\n\n"
        "• Pulsa el botón para compartir tu ubicación, o\n"
        "• pega un enlace de Google Maps, o\n"
        "• escribe las coordenadas (ej. `37.1603, -4.2187`)",
        parse_mode="Markdown", reply_markup=kb,
    )
    return LOCATION


async def _maybe_ask_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pregunta con qué cuenta subir la aportación, o salta el paso si el
    usuario ya eligió en una aportación anterior (mientras el bot siga vivo)."""
    chat = update.effective_chat
    account = context.user_data.get("account")
    if account == "default":
        return await _goto_location(chat)
    if account and update.effective_user.id in user_clients:
        await chat.send_message(
            f"ℹ️ Subiré la aportación con tu cuenta {account} "
            "(usa /cuenta si quieres cambiarla)."
        )
        return await _goto_location(chat)
    await chat.send_message(
        "👤 ¿Con qué cuenta de andaluh.ushahidi.io quieres subir tu aportación?\n\n"
        "Si no tienes cuenta o te da igual, elige la primera opción: se subirá "
        "con la cuenta colectiva del bot y saldrá en el mapa exactamente igual.",
        reply_markup=_account_kb(),
    )
    return AUTH_CHOICE


async def account_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    choice = q.data.split(":")[1]
    if choice == "default":
        context.user_data["account"] = "default"
        user_clients.pop(update.effective_user.id, None)
        await q.message.reply_text(
            "👍 Perfecto, tu aportación se subirá con la cuenta colectiva del bot."
        )
        return await _goto_location(update.effective_chat)

    context.user_data["auth_mode"] = choice  # "login" o "signup"
    if choice == "signup":
        await q.message.reply_text(
            "✨ ¡Vamos a crearte una cuenta en andaluh.ushahidi.io!\n\n"
            "📧 Escribe el *email* que quieres usar:",
            parse_mode="Markdown",
        )
    else:
        await q.message.reply_text(
            "📧 Escribe el *email* de tu cuenta de andaluh.ushahidi.io:",
            parse_mode="Markdown",
        )
    return AUTH_EMAIL


async def auth_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    if not EMAIL_RE.match(email):
        await update.message.reply_text(
            "Mmm, eso no parece un email 😅. Escríbelo de nuevo (ej. `nombre@ejemplo.com`):",
            parse_mode="Markdown",
        )
        return AUTH_EMAIL
    context.user_data["auth_email"] = email
    if context.user_data.get("auth_mode") == "signup":
        texto = "🔑 Ahora elige una *contraseña* para tu cuenta nueva."
    else:
        texto = "🔑 Ahora escribe tu *contraseña*."
    await update.message.reply_text(
        texto + "\n\n🔒 Borraré tu mensaje en cuanto la lea, para que no quede "
        "en el chat. Aun así, mejor no uses una contraseña que ya uses en "
        "sitios importantes.",
        parse_mode="Markdown",
    )
    return AUTH_PASSWORD


async def auth_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text
    try:
        await update.message.delete()
    except Exception:
        log.warning("No se pudo borrar el mensaje con la contraseña")

    email = context.user_data["auth_email"]
    mode = context.user_data.get("auth_mode", "login")
    chat = update.effective_chat
    status = await chat.send_message("⏳ Comprobando...")
    try:
        if mode == "signup":
            await register_user(email, password,
                                realname=update.effective_user.first_name)
        client = UshahidiClient(email, password)
        await client.check_login()
    except UshahidiError as e:
        log.warning("Fallo de autenticación en Ushahidi: %s", e)
        if mode == "signup":
            texto = (
                "😔 No he podido crear la cuenta. Puede que el registro esté "
                "desactivado en andaluh.ushahidi.io o que ese email ya exista.\n\n"
                "¿Probamos otra opción?"
            )
        else:
            texto = "😔 Ese email y contraseña no funcionan. ¿Probamos otra vez?"
        await status.edit_text(texto)
        await chat.send_message(
            "👤 ¿Con qué cuenta quieres subir tu aportación?",
            reply_markup=_account_kb(),
        )
        return AUTH_CHOICE

    user_clients[update.effective_user.id] = client
    context.user_data["account"] = email
    if mode == "signup":
        await status.edit_text(
            f"✅ ¡Cuenta creada! Subirás tus aportaciones como {email} "
            "(también te sirve para entrar en andaluh.ushahidi.io)."
        )
    else:
        await status.edit_text(f"✅ ¡Dentro! Subirás tus aportaciones como {email}.")
    return await _goto_location(chat)


async def cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /cuenta: olvida la cuenta elegida para volver a preguntar."""
    user_clients.pop(update.effective_user.id, None)
    context.user_data.pop("account", None)
    context.user_data.pop("auth_mode", None)
    context.user_data.pop("auth_email", None)
    await update.message.reply_text(
        "👤 Cuenta olvidada. En tu próxima aportación te volveré a preguntar "
        "con qué cuenta quieres subirla."
    )


COORD_RE = re.compile(r"(-?\d{1,2}\.\d+)[,\s]+(-?\d{1,3}\.\d+)")
GMAPS_RE = re.compile(r"[@!]3d(-?\d+\.\d+)!4d(-?\d+\.\d+)|@(-?\d+\.\d+),(-?\d+\.\d+)")


async def _resolve_short_link(url: str) -> str:
    """Sigue la redirección de enlaces cortos maps.app.goo.gl."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as c:
        r = await c.get(url)
        return str(r.url)


async def location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft = context.user_data["draft"]
    lat = lon = None

    if update.message.location:
        lat = update.message.location.latitude
        lon = update.message.location.longitude
    else:
        text = update.message.text or ""
        if "maps.app.goo.gl" in text or "goo.gl/maps" in text:
            try:
                text = await _resolve_short_link(text.strip())
            except Exception:
                pass
        m = GMAPS_RE.search(text) or COORD_RE.search(text)
        if m:
            groups = [g for g in m.groups() if g is not None]
            lat, lon = float(groups[0]), float(groups[1])

    if lat is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        await update.message.reply_text(
            "No he podido entender esa ubicación 😅. Prueba a compartirla con "
            "el botón, o pega un enlace de Google Maps."
        )
        return LOCATION

    draft["lat"], draft["lon"] = lat, lon
    await update.message.reply_text(
        f"📍 Ubicación registrada: `{lat:.5f}, {lon:.5f}`\n\n"
        "✍️ *Transcripción*: escribe exactamente lo que pone en el letrero.",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove(),
    )
    return TRANSCRIPTION


async def transcription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if len(text) > config.MAX_TITLE_LEN:
        await update.message.reply_text(
            f"Uy, la transcripción no puede pasar de {config.MAX_TITLE_LEN} "
            f"caracteres (la tuya tiene {len(text)}). ¿Puedes acortarla?"
        )
        return TRANSCRIPTION
    context.user_data["draft"]["title"] = text
    await update.message.reply_text(
        "📝 *Descripción*: ¿qué hace andaluz a este letrero? Describe el "
        "fenómeno lingüístico que reconoces en el texto.\n\n"
        "Por ejemplo: pérdida de la «d» («asalvajá», «pescaíto»), seseo o "
        "ceceo escrito («sielo», «zeñora»), aspiración o pérdida de la «s» "
        "(«ehtamo», «vamo»), vocabulario propio andaluz...",
        parse_mode="Markdown",
    )
    return DESCRIPTION


async def description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["draft"]["description"] = update.message.text.strip()
    await update.message.reply_text(
        "🪧 *Tipo de letrero* (puedes marcar varios):",
        parse_mode="Markdown",
        reply_markup=_multi_kb("let", config.OPCIONES_LETRERO, set()),
    )
    return LETRERO


def _multi_kb(prefix: str, options: list[str], selected: set) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(options), 2):
        row = []
        for j, opt in enumerate(options[i:i + 2]):
            idx = i + j
            mark = "✅ " if opt in selected else ""
            row.append(InlineKeyboardButton(f"{mark}{opt}",
                                            callback_data=f"{prefix}:{idx}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("Listo ➡️", callback_data=f"{prefix}:done")])
    return InlineKeyboardMarkup(rows)


async def _toggle(update: Update, context: ContextTypes.DEFAULT_TYPE,
                  prefix: str, options: list[str], key: str) -> bool:
    """Marca/desmarca opciones. Devuelve True si el usuario pulsó Listo."""
    q = update.callback_query
    await q.answer()
    _, val = q.data.split(":")
    if val == "done":
        return True
    selected = context.user_data["draft"][key]
    opt = options[int(val)]
    selected.symmetric_difference_update({opt})
    await q.edit_message_reply_markup(_multi_kb(prefix, options, selected))
    return False


async def letrero(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _toggle(update, context, "let", config.OPCIONES_LETRERO, "letrero"):
        await update.callback_query.message.reply_text(
            "💬 *Tipo de discurso*: ¿sobre qué trata el contenido del letrero? "
            "(puedes marcar varios)",
            parse_mode="Markdown",
            reply_markup=_multi_kb("dis", config.OPCIONES_DISCURSO, set()),
        )
        return DISCURSO
    return LETRERO


async def discurso(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _toggle(update, context, "dis", config.OPCIONES_DISCURSO, "discurso"):
        d = context.user_data["draft"]
        resumen = (
            "🔎 *Resumen de tu aportación*\n\n"
            f"✍️ Transcripción: {d['title']}\n"
            f"📝 Descripción: {d['description']}\n"
            f"📍 Ubicación: {d['lat']:.5f}, {d['lon']:.5f}\n"
            f"🪧 Tipo de letrero: {', '.join(sorted(d['letrero'])) or 'Sin aportar'}\n"
            f"💬 Tipo de discurso: {', '.join(sorted(d['discurso'])) or 'Sin aportar'}"
        )
        await update.callback_query.message.reply_text(
            resumen, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🚀 Enviar", callback_data="rev:send"),
                InlineKeyboardButton("❌ Cancelar", callback_data="rev:cancel"),
            ]]),
        )
        return REVIEW
    return DISCURSO


async def review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "rev:cancel":
        await q.message.reply_text("Aportación cancelada. ¡Hasta la próxima! 👋")
        context.user_data.clear()
        return ConversationHandler.END

    d = context.user_data["draft"]
    # Cuenta propia si el usuario inició sesión; si no, la colectiva del bot
    client = user_clients.get(update.effective_user.id, ushahidi)
    await q.message.reply_text("⏳ Subiendo tu aportación al mapa...")
    try:
        tg_file = await context.bot.get_file(d["file_id"])
        image = bytes(await tg_file.download_as_bytearray())
        media_id = await client.upload_media(image, caption=d["title"])
        await client.create_post(
            title=d["title"], description=d["description"],
            lat=d["lat"], lon=d["lon"], media_id=media_id,
            letrero=sorted(d["letrero"]), discurso=sorted(d["discurso"]),
        )
    except Exception as e:
        # UshahidiError o cualquier otro fallo (p. ej. descargando de Telegram):
        # no perdemos el borrador, ofrecemos reintentar desde el mismo punto
        log.error("Fallo subiendo a Ushahidi: %s", e, exc_info=True)
        await q.message.reply_text(
            "😔 Ha fallado la subida (el servidor no respondió a tiempo o dio "
            "un error). Tu aportación NO se ha perdido: dale a «Reintentar» "
            "en un momento, o cancela y avisa a los administradores si sigue "
            "fallando.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Reintentar", callback_data="rev:send"),
                InlineKeyboardButton("❌ Cancelar", callback_data="rev:cancel"),
            ]]),
        )
        return REVIEW

    await q.message.reply_text(
        "✅ ¡Aportación enviada! Quedará visible en el mapa en cuanto el "
        "equipo la revise. ¡Gracias por contribuir al Paisaje Lingüístico "
        "Andaluz! 💚\n\n"
        "Si quieres subir otra, mándame la siguiente foto cuando quieras. 📸"
    )
    # Aviso en el grupo solo si la aportación se originó allí
    if d.get("group_chat_id"):
        try:
            await context.bot.send_message(
                chat_id=d["group_chat_id"],
                reply_to_message_id=d["group_message_id"],
                text=f"✅ Aportación de {d['user_name']} completada y enviada al mapa 🗺️",
            )
        except Exception:
            log.warning("No se pudo avisar en el grupo", exc_info=True)

    if d.get("token"):
        context.bot_data.get("pending", {}).pop(d["token"], None)
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Aportación cancelada. 👋",
                                    reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# --------------------------------------------------------------------------
def main():
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start, filters.ChatType.PRIVATE),
            MessageHandler(filters.PHOTO & filters.ChatType.PRIVATE, private_photo),
        ],
        states={
            CONFIRM_PHOTO: [CallbackQueryHandler(confirm_photo, pattern="^photo:")],
            AUTH_CHOICE: [CallbackQueryHandler(account_choice, pattern="^acc:")],
            AUTH_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_email)],
            AUTH_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, auth_password)],
            LOCATION: [MessageHandler(
                (filters.LOCATION | filters.TEXT) & ~filters.COMMAND, location)],
            TRANSCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, transcription)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, description)],
            LETRERO: [CallbackQueryHandler(letrero, pattern="^let:")],
            DISCURSO: [CallbackQueryHandler(discurso, pattern="^dis:")],
            REVIEW: [CallbackQueryHandler(review, pattern="^rev:")],
        },
        fallbacks=[CommandHandler("cancelar", cancel)],
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("cuenta", cuenta, filters.ChatType.PRIVATE))
    app.add_handler(MessageHandler(filters.PHOTO & filters.ChatType.GROUPS, group_photo))

    log.info("Bot arrancado")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
