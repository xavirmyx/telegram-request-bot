import json
import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, JobQueue
from telegram.helpers import escape_markdown
from telegram.error import TelegramError
from dotenv import load_dotenv
import traceback

# === CONSTANTES ===
logging.basicConfig(
    filename='bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = "-1002305997509"  # ID del grupo de administradores
BOT_ID = 7714399570  # ID del bot a añadir como administrador
REQUEST_LIMIT = 2  # Límite de solicitudes por usuario cada 24 horas
DB_FILE = "requests.json"
BLACKLIST_FILE = "blacklist.json"
AUTO_DELETE_TIME = 120  # 2 minutos en segundos

# === FUNCIONES UTILITARIAS ===
def load_requests():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            data = json.load(f)
        now = datetime.now()
        cutoff_time = now - timedelta(days=30)
        original_count = len(data["requests"])
        data["requests"] = [
            req for req in data["requests"]
            if datetime.strptime(req["date"], "%Y-%m-%d %H:%M:%S") > cutoff_time
        ]
        deleted_count = original_count - len(data["requests"])
        if deleted_count > 0:
            save_requests(data)
            logger.info(f"🗑️ Eliminadas {deleted_count} solicitudes antiguas (EntresHijos)")
        return data
    return {"requests": [], "last_ticket": 0}

def save_requests(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

def generate_ticket():
    data = load_requests()
    data["last_ticket"] += 1
    save_requests(data)
    return data["last_ticket"]

def count_user_requests(user_id):
    data = load_requests()
    now = datetime.now()
    cutoff_time = now - timedelta(hours=24)
    user_requests = [req for req in data["requests"] if req["user_id"] == user_id and datetime.strptime(req["date"], "%Y-%m-%d %H:%M:%S") > cutoff_time]
    return len(user_requests), min([datetime.strptime(req["date"], "%Y-%m-%d %H:%M:%S") for req in user_requests], default=None)

def load_blacklist():
    if os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, "r") as f:
            return json.load(f)
    return []

def save_blacklist(blacklist):
    with open(BLACKLIST_FILE, "w") as f:
        json.dump(blacklist, f, indent=4)

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    if chat_id != ADMIN_GROUP_ID:
        await context.bot.send_message(chat_id=chat_id, text="❌ ¡Solo en el grupo de admins de EntresHijos! 😊")
        logger.warning(f"🚫 Intento de comando admin por {user.id} fuera de grupo")
        return False
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        # Asegurar que el bot (BOT_ID) esté en la lista de admins
        bot_admin = any(admin.user.id == BOT_ID for admin in admins)
        if not bot_admin:
            logger.warning(f"⚠️ Bot ID {BOT_ID} no es administrador en {ADMIN_GROUP_ID}")
            await context.bot.send_message(chat_id=chat_id, text="⚠️ El bot necesita ser administrador. Añade al ID 7714399570.")
        return any(admin.user.id == user.id for admin in admins)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error al verificar admins: {str(e)} - EntresHijos")
        logger.error(f"❌ Error al verificar admins: {str(e)}")
        return False

async def clean_admin_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, current_message_id: int):
    try:
        updates = await context.bot.get_updates(offset=-1, limit=50)
        for update in updates:
            if (update.message and update.message.chat_id == chat_id and
                update.message.message_id != current_message_id and
                update.message.from_user and update.message.from_user.is_bot):
                admin_keywords = ["/tickets", "/blacklist", "/unblacklist", "Solicitud - Ticket", "Respuesta Enviada", "Estadísticas"]
                if any(keyword in update.message.text for keyword in admin_keywords):
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
                        logger.info(f"🗑️ Mensaje eliminado (ID: {update.message.message_id}) en grupo admin")
                    except TelegramError as e:
                        logger.warning(f"⚠️ No se pudo eliminar mensaje (ID: {update.message.message_id}): {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error al limpiar mensajes: {str(e)}")

async def auto_delete_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    if job.context:
        try:
            chat_id, message_id = job.context
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"🕒 Mensaje autoeliminado (Chat ID: {chat_id}, Message ID: {message_id})")
        except TelegramError as e:
            logger.warning(f"⚠️ No se pudo autoeliminar mensaje (Chat ID: {chat_id}, Message ID: {message_id}): {str(e)}")

# === MANEJADORES DE ERRORES ===
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    error_details = f"Update {update} caused error {context.error}\n{traceback.format_exc()}"
    logger.error(f"❌ {error_details}")
    if update and update.message:
        msg = await update.message.reply_text("❌ ¡Error en EntresHijos! Intenta de nuevo o contacta a un admin. 😊")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.message.chat_id, msg.message_id))

# === COMANDOS PRINCIPALES ===
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🌟 **¡Bienvenido a EntresHijos Bot!** 🌟\n"
        "📢 Gestiona solicitudes para la comunidad EntresHijos.\n"
        "👥 Usa `/solicito <mensaje>` para enviar una solicitud.\n"
        "👑 Admins, usa `/tickets` o `/blacklist` para gestionar.\n"
        "ℹ️ ¡Estamos aquí para ayudarte! 🙌"
    )
    keyboard = [
        [InlineKeyboardButton("📝 Enviar Solicitud", callback_data="solicito_start")],
        [InlineKeyboardButton("ℹ️ Menú Admin", callback_data="tickets_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode="Markdown")
    context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.message.chat_id, msg.message_id))
    logger.info(f"🌱 Usuario {update.effective_user.id} ejecutó /start")

async def button_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    if action == "solicito_start":
        msg = await query.edit_message_text(
            "📝 **Enviar Solicitud - EntresHijos**\n"
            "Usa `/solicito <tu_mensaje>` (ej. `/solicito Necesito ayuda`). 😊"
        )
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
        logger.info(f"📝 Usuario {update.effective_user.id} accedió a enviar solicitud")
    elif action == "tickets_start":
        await tickets_command(update, context)
        logger.info(f"🔧 Usuario {update.effective_user.id} accedió al menú de tickets")

async def solicito_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    message = " ".join(context.args)

    blacklist = load_blacklist()
    if any(user.id == entry["user_id"] for entry in blacklist):
        msg = await update.message.reply_text(
            f"⛔ @{escape_markdown(user.username or f'Usuario_{user.id}')} estás en la blacklist de EntresHijos. No puedes enviar solicitudes. 😔"
        )
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(chat_id, msg.message_id))
        logger.warning(f"⛔ Usuario {user.id} intentó solicitar estando en blacklist")
        return

    if not message:
        msg = await update.message.reply_text("❌ ¡Ingresa un mensaje! Ejemplo: `/solicito Necesito ayuda` - EntresHijos. 😊")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(chat_id, msg.message_id))
        logger.warning(f"🚫 Intento de solicitud sin mensaje por {user.id}")
        return

    try:
        is_admin_user = await context.bot.get_chat_member(ADMIN_GROUP_ID, user.id)
        is_admin_flag = is_admin_user.status in ["administrator", "creator"]
    except TelegramError as e:
        msg = await update.message.reply_text(f"❌ Error al verificar admin: {str(e)} - EntresHijos.")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(chat_id, msg.message_id))
        logger.error(f"❌ Error al verificar admin: {str(e)}")
        return

    username = user.username or f"Usuario_{user.id}"
    if not is_admin_flag:
        request_count, _ = count_user_requests(user.id)
        if request_count >= REQUEST_LIMIT:
            reset_time = datetime.now() + timedelta(hours=24)
            time_left = reset_time - datetime.now()
            hours_left = int(time_left.total_seconds() // 3600)
            minutes_left = int((time_left.total_seconds() % 3600) // 60)
            msg = await update.message.reply_text(
                f"⛔ @{escape_markdown(username)}, agotaste tus {REQUEST_LIMIT} solicitudes diarias - EntresHijos. 😔\n"
                f"⏳ Vuelve en {hours_left}h {minutes_left}m (a las {reset_time.strftime('%H:%M:%S')})."
            )
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(chat_id, msg.message_id))
            logger.info(f"⏰ Límite alcanzado por {username}")
            return

    ticket = generate_ticket()
    group_name = update.effective_chat.title or "Grupo sin nombre"

    data = load_requests()
    request = {
        "ticket": ticket,
        "user_id": user.id,
        "username": username,
        "message": message,
        "group_id": chat_id,
        "group_name": group_name,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "EntresHijos",
        "priority": False,
        "status": "en espera"
    }
    data["requests"].append(request)
    save_requests(data)

    response_text = (
        f"✅ **Solicitud Registrada - EntresHijos** 🎉\n"
        f"👤 @{escape_markdown(username)}\n"
        f"🎟️ Ticket #{ticket}\n"
        f"📝 Mensaje: {escape_markdown(message)}\n"
        f"🏠 Grupo: {escape_markdown(group_name)}\n"
        f"🕒 Fecha: {request['date']}"
    )
    if not is_admin_flag:
        response_text += f"\n📊 Solicitudes restantes: {REQUEST_LIMIT - request_count - 1}"

    msg = await context.bot.send_message(chat_id=chat_id, text=response_text, parse_mode="Markdown")
    context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(chat_id, msg.message_id))

    queue_msg = await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📢 **Solicitud en Cola - EntresHijos** ⏳\n"
            f"👤 @{escape_markdown(username)}\n"
            f"🎟️ Ticket #{ticket}\n"
            f"📝 Mensaje: {escape_markdown(message)}\n"
            f"🏠 Grupo: {escape_markdown(group_name)}\n"
            f"🕒 Fecha: {request['date']}\n"
            f"📋 Estado: En espera de revisión."
        ),
        parse_mode="Markdown"
    )
    context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(chat_id, queue_msg.message_id))

    admin_msg = await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=(
            f"🔔 **Nueva Solicitud - EntresHijos** 🔔\n"
            f"🎟️ Ticket #{ticket}\n"
            f"👤 @{escape_markdown(username)}\n"
            f"📝 Mensaje: {escape_markdown(message)}\n"
            f"🏠 Grupo: {escape_markdown(group_name)}\n"
            f"🕒 Fecha: {request['date']}\n"
            f"🔧 Usa /tickets para gestionarla."
        ),
        parse_mode="Markdown"
    )
    context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(ADMIN_GROUP_ID, admin_msg.message_id))
    logger.info(f"📥 Solicitud registrada - Ticket #{ticket} por @{username}")

async def tickets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    data = load_requests()
    if not data["requests"]:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📪 **Sin Solicitudes - EntresHijos** 😊\nNo hay tickets pendientes."
        )
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.effective_chat.id, msg.message_id))
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        return

    keyboard = [
        [InlineKeyboardButton("📋 Ver Tickets", callback_data="view_tickets")],
        [InlineKeyboardButton("🔙 Volver", callback_data="tickets_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔧 **Menú de Gestión - EntresHijos** 🔧\nSelecciona una opción:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.effective_chat.id, msg.message_id))
    await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
    logger.info("🔧 Menú de tickets mostrado")

async def blacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    keyboard = [[InlineKeyboardButton("➕ Añadir a Blacklist", callback_data="add_to_blacklist")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="⛔ **Blacklist - EntresHijos** ⛔\nPulsa para añadir un usuario a la blacklist.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.effective_chat.id, msg.message_id))
    await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
    logger.info("⛔ Menú de blacklist mostrado")

async def unblacklist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    blacklist = load_blacklist()
    if not blacklist:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="✅ **Blacklist Vacía - EntresHijos** ✅\nNo hay usuarios bloqueados."
        )
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.effective_chat.id, msg.message_id))
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        return

    keyboard = []
    for entry in blacklist:
        button_text = f"❌ @{escape_markdown(entry['username'])} (ID: {entry['user_id']})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"remove_from_blacklist_{entry['user_id']}")])
    keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="blacklist_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ **Lista de Blacklist - EntresHijos** ✅\nSelecciona un usuario para desbloquear:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.effective_chat.id, msg.message_id))
    await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
    logger.info("✅ Menú de unblacklist mostrado")

async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if not context.args or len(context.args) < 2:
        msg = await update.message.reply_text("❌ Uso: `/reply <ticket> <mensaje>` - EntresHijos.", parse_mode="Markdown")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.effective_chat.id, msg.message_id))
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.warning("🚫 Uso incorrecto de /reply")
        return
    try:
        ticket = int(context.args[0])
    except ValueError:
        msg = await update.message.reply_text("❌ Ticket debe ser numérico. Ejemplo: `/reply 1 Hola` - EntresHijos.", parse_mode="Markdown")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.effective_chat.id, msg.message_id))
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.warning("🚫 Ticket inválido en /reply")
        return
    reply_message = " ".join(context.args[1:])
    data = load_requests()
    request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
    if request:
        user_response = (
            f"📩 **Respuesta - EntresHijos** 📩\n"
            f"🎟️ Ticket #{ticket}\n"
            f"👤 @{escape_markdown(request['username'])}\n"
            f"📝 Respuesta: {escape_markdown(reply_message)}"
        )
        admin_response = (
            f"📢 **Respuesta Enviada - EntresHijos** 📢\n"
            f"🎟️ Ticket #{ticket}\n"
            f"👤 @{escape_markdown(request['username'])}\n"
            f"📝 Mensaje: {escape_markdown(reply_message)}"
        )
        await context.bot.send_message(chat_id=request["group_id"], text=user_response, parse_mode="Markdown")
        msg = await context.bot.send_message(chat_id=update.effective_chat.id, text=admin_response, parse_mode="Markdown")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.effective_chat.id, msg.message_id))
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.info(f"📩 Respuesta enviada para Ticket #{ticket}")
    else:
        msg = await update.message.reply_text(f"❌ Ticket #{ticket} no encontrado - EntresHijos.", parse_mode="Markdown")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.effective_chat.id, msg.message_id))
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.warning(f"🚫 Ticket #{ticket} no encontrado")

async def pendiente_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if not context.args or not context.args[0].isdigit():
        msg = await update.message.reply_text("❌ Uso: `/pendiente <ticket>` - EntresHijos. 😊", parse_mode="Markdown")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(chat_id, msg.message_id))
        logger.warning(f"🚫 Intento de /pendiente sin ticket por {user.id}")
        return
    ticket = int(context.args[0])
    data = load_requests()
    request = next((req for req in data["requests"] if req["ticket"] == ticket and req["user_id"] == user.id), None)
    if request:
        status = request.get("status", "en espera")
        response_text = (
            f"ℹ️ **Estado - EntresHijos** ℹ️\n"
            f"🎟️ Ticket #{ticket}\n"
            f"👤 @{escape_markdown(request['username'])}\n"
            f"📝 Mensaje: {escape_markdown(request['message'])}\n"
            f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
            f"🕒 Fecha: {request['date']}\n"
            f"📋 Estado: {status}"
        )
        if status == "subida":
            response_text += "\n🔍 Busca en el canal correspondiente."
        elif status == "no aceptada":
            response_text += "\n❌ Contacta a un admin si necesitas ayuda."
        msg = await update.message.reply_text(response_text, parse_mode="Markdown")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(chat_id, msg.message_id))
        logger.info(f"ℹ️ Estado de Ticket #{ticket} mostrado a @{request['username']}")
    else:
        msg = await update.message.reply_text(f"❌ Ticket #{ticket} no encontrado o no te pertenece - EntresHijos. 😕", parse_mode="Markdown")
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(chat_id, msg.message_id))
        logger.warning(f"🚫 Ticket #{ticket} no encontrado para {user.id}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == "solicito_start":
        msg = await query.edit_message_text(
            "📝 **Enviar Solicitud - EntresHijos**\n"
            "Usa `/solicito <tu_mensaje>` (ej. `/solicito Necesito ayuda`). 😊"
        )
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
    elif action == "tickets_start":
        await tickets_command(update, context)
    elif action == "view_tickets":
        data = load_requests()
        sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
        if not sorted_requests:
            msg = await query.edit_message_text("📪 **Sin Solicitudes - EntresHijos** 😊\nNo hay tickets pendientes.")
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
            return
        keyboard = []
        for req in sorted_requests:
            status_mark = f" ({req['status']})" if req["status"] != "en espera" else ""
            button_text = f"🎟️ Ticket #{req['ticket']}{status_mark} (@{req['username']})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"manage_{req['ticket']}")])
        keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="tickets_start")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = await query.edit_message_text(
            "📋 **Lista de Tickets - EntresHijos** 📋\nSelecciona un ticket para gestionarlo:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
    elif action.startswith("manage_"):
        ticket = int(action.split("_")[1])
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if not request:
            msg = await query.edit_message_text(f"❌ Ticket #{ticket} no encontrado - EntresHijos. 😕")
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
            return
        keyboard = [
            [InlineKeyboardButton("❌ Denegar", callback_data=f"deny_{ticket}")],
            [InlineKeyboardButton("✅ Aceptar", callback_data=f"accept_{ticket}")],
            [InlineKeyboardButton("📩 Responder", callback_data=f"reply_{ticket}")],
            [InlineKeyboardButton("🔙 Volver", callback_data="view_tickets")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = await query.edit_message_text(
            f"📋 **Ticket #{ticket} - EntresHijos** 📋\n"
            f"👤 @{escape_markdown(request['username'])}\n"
            f"📝 Mensaje: {escape_markdown(request['message'])}\n"
            f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
            f"🕒 Fecha: {request['date']}\n"
            f"📋 Estado: {request.get('status', 'en espera')}\n"
            f"🔧 ¿Qué acción deseas tomar?",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
    elif action.startswith("deny_"):
        ticket = int(action.split("_")[1])
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            request["status"] = "no aceptada"
            data["requests"] = [req for req in data["requests"] if req["ticket"] != ticket]
            save_requests(data)
            notification = (
                f"📢 **Actualización - EntresHijos** 📢\n"
                f"👤 @{escape_markdown(request['username'])}\n"
                f"🎟️ Ticket #{ticket}\n"
                f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                f"🕒 Fecha: {request['date']}\n"
                f"❌ Estado: Solicitud NO Aceptada\n"
                f"Contacta a un admin si necesitas ayuda."
            )
            msg = await context.bot.send_message(chat_id=request["group_id"], text=notification, parse_mode="Markdown")
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(request["group_id"], msg.message_id))
            try:
                updates = await context.bot.get_updates(offset=-1, limit=50)
                for update in updates:
                    if (update.message and update.message.chat_id == request["group_id"] and
                        f"Ticket #{ticket}" in update.message.text and "Solicitud en Cola" in update.message.text):
                        await context.bot.delete_message(chat_id=request["group_id"], message_id=update.message.message_id)
                        logger.info(f"🗑️ Mensaje 'Solicitud en Cola' eliminado (Ticket #{ticket})")
                        break
            except TelegramError as e:
                logger.error(f"⚠️ Error al eliminar mensaje original (Ticket #{ticket}): {str(e)}")
            msg = await query.edit_message_text(
                f"❌ **Solicitud Denegada - EntresHijos** ❌\n"
                f"🎟️ Ticket #{ticket} procesado."
            )
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
            logger.info(f"❌ Ticket #{ticket} denegado")
    elif action.startswith("accept_"):
        ticket = int(action.split("_")[1])
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            request["status"] = "subida"
            data["requests"] = [req for req in data["requests"] if req["ticket"] != ticket]
            save_requests(data)
            notification = (
                f"📢 **Actualización - EntresHijos** 📢\n"
                f"👤 @{escape_markdown(request['username'])}\n"
                f"🎟️ Ticket #{ticket}\n"
                f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                f"🕒 Fecha: {request['date']}\n"
                f"✅ Estado: Solicitud Subida\n"
                f"🔍 Busca en el canal correspondiente."
            )
            msg = await context.bot.send_message(chat_id=request["group_id"], text=notification, parse_mode="Markdown")
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(request["group_id"], msg.message_id))
            try:
                updates = await context.bot.get_updates(offset=-1, limit=50)
                for update in updates:
                    if (update.message and update.message.chat_id == request["group_id"] and
                        f"Ticket #{ticket}" in update.message.text and "Solicitud en Cola" in update.message.text):
                        await context.bot.delete_message(chat_id=request["group_id"], message_id=update.message.message_id)
                        logger.info(f"🗑️ Mensaje 'Solicitud en Cola' eliminado (Ticket #{ticket})")
                        break
            except TelegramError as e:
                logger.error(f"⚠️ Error al eliminar mensaje original (Ticket #{ticket}): {str(e)}")
            msg = await query.edit_message_text(
                f"✅ **Solicitud Aceptada - EntresHijos** ✅\n"
                f"🎟️ Ticket #{ticket} procesado."
            )
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
            logger.info(f"✅ Ticket #{ticket} aceptado")
    elif action.startswith("reply_"):
        ticket = int(action.split("_")[1])
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            msg = await query.edit_message_text(
                f"📩 **Responder - EntresHijos** 📩\n"
                f"🎟️ Ticket #{ticket}\n"
                f"Usa `/reply {ticket} <mensaje>` (ej. `/reply {ticket} Solicitud procesada`)."
            )
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
            logger.info(f"📩 Opción de respuesta para Ticket #{ticket} activada")
    elif action == "add_to_blacklist":
        msg = await query.edit_message_text(
            "⛔ **Añadir a Blacklist - EntresHijos** ⛔\n"
            "Envía el @name del usuario a bloquear (ej. @username).",
            parse_mode="Markdown"
        )
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
        context.user_data["awaiting_blacklist"] = True
        logger.info("⛔ Esperando @name para añadir a blacklist")
    elif action.startswith("remove_from_blacklist_"):
        user_id = int(action.split("_")[2])
        blacklist = load_blacklist()
        blacklist = [entry for entry in blacklist if entry["user_id"] != user_id]
        save_blacklist(blacklist)
        msg = await query.edit_message_text(
            f"✅ **Usuario Desbloqueado - EntresHijos** ✅\n"
            f"ID {user_id} eliminado de la blacklist."
        )
        context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(query.message.chat_id, msg.message_id))
        logger.info(f"✅ Usuario ID {user_id} desbloqueado")

async def reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and context.user_data.get("awaiting_blacklist"):
        username = update.message.text.strip()
        if not username.startswith("@"):
            msg = await update.message.reply_text("❌ El @name debe comenzar con @ - EntresHijos. 😕", parse_mode="Markdown")
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.message.chat_id, msg.message_id))
            return
        try:
            user = await context.bot.get_chat_member(update.message.chat_id, username[1:])
            user_id = user.user.id
            blacklist = load_blacklist()
            if any(entry["user_id"] == user_id for entry in blacklist):
                msg = await update.message.reply_text(f"⛔ @{escape_markdown(username[1:])} ya está en la blacklist - EntresHijos. 😕", parse_mode="Markdown")
                context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.message.chat_id, msg.message_id))
            else:
                blacklist.append({"username": username[1:], "user_id": user_id})
                save_blacklist(blacklist)
                msg = await update.message.reply_text(
                    f"⛔ **Usuario Añadido a Blacklist - EntresHijos** ⛔\n"
                    f"@{escape_markdown(username[1:])} (ID: {user_id}) bloqueado.",
                    parse_mode="Markdown"
                )
                context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.message.chat_id, msg.message_id))
            del context.user_data["awaiting_blacklist"]
            logger.info(f"⛔ @{username[1:]} (ID: {user_id}) añadido a blacklist")
        except TelegramError as e:
            msg = await update.message.reply_text(f"❌ Error al añadir a blacklist: {str(e)} - EntresHijos.", parse_mode="Markdown")
            context.job_queue.run_once(auto_delete_message, AUTO_DELETE_TIME, data=(update.message.chat_id, msg.message_id))
            del context.user_data["awaiting_blacklist"]
            logger.error(f"❌ Error al añadir a blacklist: {str(e)}")
    await update.message.delete()

# === FUNCIÓN PRINCIPAL ===
def main():
    application = Application.builder().token(TOKEN).job_queue(JobQueue()).build()
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("solicito", solicito_command))
    application.add_handler(CommandHandler("tickets", tickets_command))
    application.add_handler(CommandHandler("blacklist", blacklist_command))
    application.add_handler(CommandHandler("unblacklist", unblacklist_command))
    application.add_handler(CommandHandler("reply", reply_command))
    application.add_handler(CommandHandler("pendiente", pendiente_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_handler))
    application.add_error_handler(error_handler)
    logger.info("🚀 Bot de EntresHijos iniciado exitosamente")
    print("🚀 Bot iniciado. Escuchando comandos...")
    application.run_polling()

if __name__ == "__main__":
    main()