import json
import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, JobQueue
from telegram.helpers import escape_markdown
from telegram.error import TelegramError
from dotenv import load_dotenv
import traceback

# Configurar logging con detalles de errores
logging.basicConfig(
    filename='bot.log',  # Guardar logs en un archivo
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = "-1002305997509"  # ID del grupo de administradores
REQUEST_LIMIT = 2  # Límite de solicitudes por usuario cada 24 horas

# Archivo para la base de datos de solicitudes
DB_FILE = "requests.json"

# Cargar o inicializar la base de datos con limpieza de solicitudes antiguas
def load_requests():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            data = json.load(f)
        now = datetime.now()
        cutoff_time = now - timedelta(days=30)  # Eliminar solicitudes mayores a 30 días
        original_count = len(data["requests"])
        data["requests"] = [
            req for req in data["requests"]
            if datetime.strptime(req["date"], "%Y-%m-%d %H:%M:%S") > cutoff_time
        ]
        deleted_count = original_count - len(data["requests"])
        if deleted_count > 0:
            save_requests(data)  # Guardar cambios después de eliminar
            logger.info(f"Se eliminaron {deleted_count} solicitudes antiguas (mayores a 30 días)")
        return data
    return {"requests": [], "last_ticket": 0}

# Guardar la base de datos
def save_requests(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Generar un nuevo número de ticket
def generate_ticket():
    data = load_requests()
    data["last_ticket"] += 1
    save_requests(data)
    return data["last_ticket"]

# Contar solicitudes de un usuario en las últimas 24 horas y obtener la primera fecha
def count_user_requests(user_id):
    data = load_requests()
    now = datetime.now()
    cutoff_time = now - timedelta(hours=24)
    user_requests = [req for req in data["requests"] if req["user_id"] == user_id and datetime.strptime(req["date"], "%Y-%m-%d %H:%M:%S") > cutoff_time]
    first_request_time = min([datetime.strptime(req["date"], "%Y-%m-%d %H:%M:%S") for req in user_requests], default=None)
    return len(user_requests), first_request_time

# Verificar si el usuario es administrador en el grupo de admins
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = str(update.effective_chat.id)
    if chat_id != ADMIN_GROUP_ID:
        await context.bot.send_message(chat_id=chat_id, text="❌ ¡Ups! Este comando solo funciona en el grupo de administradores. 😊")
        logger.warning(f"Intento de uso de comando admin fuera de grupo permitido por usuario {user.id}")
        return False
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        return any(admin.user.id == user.id for admin in admins)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error al verificar administradores: {str(e)}")
        logger.error(f"Error al verificar administradores: {str(e)}")
        return False

# Eliminar mensajes anteriores de comandos de administrador
async def clean_admin_messages(context: ContextTypes.DEFAULT_TYPE, chat_id: int, current_message_id: int):
    try:
        async for message in context.bot.get_chat_history(chat_id=chat_id, limit=50):
            if message.message_id != current_message_id and message.from_user and message.from_user.is_bot:
                # Identificar mensajes de comandos de administrador por contenido o comando
                admin_commands = ["/vp", "/bp", "/reply", "/rs", "/stats", "/infosolic"]
                if any(cmd in message.text for cmd in admin_commands) or "Acciones disponibles" in message.text or "Solicitud - Ticket" in message.text:
                    try:
                        await context.bot.delete_message(chat_id=chat_id, message_id=message.message_id)
                        logger.info(f"Mensaje eliminado (ID: {message.message_id}) para mantener el grupo limpio")
                    except TelegramError as e:
                        logger.warning(f"No se pudo eliminar mensaje (ID: {message.message_id}): {str(e)}")
    except Exception as e:
        logger.error(f"Error al limpiar mensajes: {str(e)}")

# Autoeliminar mensaje después de 2 minutos
def auto_delete_message(context: ContextTypes.DEFAULT_TYPE):
    """Callback para eliminar un mensaje después de 2 minutos."""
    job = context.job
    if job.context:
        try:
            chat_id, message_id = job.context
            context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            logger.info(f"Mensaje autoeliminado (Chat ID: {chat_id}, Message ID: {message_id})")
        except TelegramError as e:
            logger.warning(f"No se pudo autoeliminar mensaje (Chat ID: {chat_id}, Message ID: {message_id}): {str(e)}")

# Manejador de errores global con detalles
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    error_details = f"Update {update} caused error {context.error}\n{traceback.format_exc()}"
    logger.error(error_details)
    if update and update.message:
        await update.message.reply_text("❌ ¡Ups! Ocurrió un error. Por favor, intenta de nuevo o contacta a un administrador. 😊")

# Mensaje de bienvenida al iniciar el bot
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        "🌟 **¡Bienvenido a Grupos-EntresHijos Bot!** 🌟\n"
        "📢 Este bot está diseñado exclusivamente para gestionar solicitudes en los grupos de EntresHijos.\n"
        "👥 Usa `/solicito <mensaje>` para enviar una solicitud.\n"
        "👑 Los administradores pueden usar `/menu` para ver los comandos disponibles.\n"
        "ℹ️ ¡Estamos aquí para ayudarte! 🙌"
    )
    keyboard = [
        [InlineKeyboardButton("📝 Enviar Solicitud", callback_data="solicito_start")],
        [InlineKeyboardButton("ℹ️ Ver Menú", callback_data="menu_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")
    logger.info(f"Usuario {update.effective_user.id} ejecutó comando /start")

# Manejar acciones de botones iniciales
async def button_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    if action == "solicito_start":
        await query.edit_message_text(
            "📝 **Enviar Solicitud**\n"
            "Por favor, usa el comando `/solicito <tu_mensaje>` para enviar tu solicitud. Ejemplo: `/solicito Necesito ayuda`. 😊"
        )
        logger.info(f"Usuario {update.effective_user.id} accedió a enviar solicitud desde botón")
    elif action == "menu_start":
        await menu_command(update, context)
        logger.info(f"Usuario {update.effective_user.id} accedió al menú desde botón")

# Comando /solicito - Cualquier usuario (con límite para no administradores)
async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    message = " ".join(context.args)

    if not message:
        await update.message.reply_text(
            "❌ ¡Hey! Necesitas escribir un mensaje. Ejemplo: `/solicito Quiero ayuda`. 😊"
        )
        logger.warning(f"Intento de solicitud sin mensaje por usuario {user.id}")
        return

    # Verificar si el usuario es administrador
    try:
        is_admin_user = await context.bot.get_chat_member(ADMIN_GROUP_ID, user.id)
        is_admin_flag = is_admin_user.status in ["administrator", "creator"]
    except TelegramError as e:
        await update.message.reply_text(f"❌ Error al verificar estado de administrador: {str(e)}")
        logger.error(f"Error al verificar administrador en solicitud: {str(e)}")
        return

    username = user.username or f"Usuario_{user.id}"

    # Aplicar límite solo a no administradores
    if not is_admin_flag:
        request_count, first_request_time = count_user_requests(user.id)

        if request_count >= REQUEST_LIMIT:
            if first_request_time:
                reset_time = first_request_time + timedelta(hours=24)
                time_left = reset_time - datetime.now()
                hours_left = int(time_left.total_seconds() // 3600)
                minutes_left = int((time_left.total_seconds() % 3600) // 60)

                await update.message.reply_text(
                    f"⛔ ¡Lo siento, @{escape_markdown(username)}! Has agotado tus {REQUEST_LIMIT} solicitudes diarias. 😔\n"
                    f"⏳ Podrás hacer más en {hours_left}h {minutes_left}m (a las {reset_time.strftime('%H:%M:%S')}).\n"
                    f"¡Paciencia! 🌟"
                )
                logger.info(f"Usuario {username} alcanzó el límite de solicitudes")
                if request_count > REQUEST_LIMIT:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"/warn @{escape_markdown(username)} Abuso de peticiones diarias."
                    )
            return
        else:
            remaining_requests = REQUEST_LIMIT - request_count - 1

    # Generar ticket
    ticket = generate_ticket()
    group_name = update.effective_chat.title or "Grupo sin nombre"

    # Guardar la solicitud
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
        "status": "en espera"  # Nuevo campo para rastrear el estado
    }
    data["requests"].append(request)
    save_requests(data)

    # Confirmación con solicitudes restantes si aplica
    response_text = (
        f"✅ **¡Solicitud Registrada!** 🎉\n"
        f"👤 @{escape_markdown(username)}\n"
        f"🎟️ **Ticket #{ticket}**\n"
        f"📝 Mensaje: {escape_markdown(message)}\n"
        f"🏠 Grupo: {escape_markdown(group_name)}\n"
        f"🌐 Fuente: EntresHijos\n"
        f"🕒 Fecha: {request['date']}\n"
        f"¡Gracias por tu paciencia! 🙌"
    )
    if not is_admin_flag:
        response_text += f"\n📊 **Solicitudes restantes hoy**: {remaining_requests}"

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=response_text,
        parse_mode="Markdown"
    )

    # Notificación de "Solicitud en cola" al grupo
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"📢 **Solicitud en Cola** ⏳\n"
            f"👤 @{escape_markdown(username)}\n"
            f"🎟️ **Ticket #{ticket}**\n"
            f"📝 Mensaje: {escape_markdown(message)}\n"
            f"🏠 Grupo: {escape_markdown(group_name)}\n"
            f"🌐 Fuente: EntresHijos\n"
            f"🕒 Fecha: {request['date']}\n"
            f"📋 Estado: En espera de revisión por los administradores.\n"
            f"¡Te avisaremos cuando haya actualizaciones! 🙌"
        ),
        parse_mode="Markdown"
    )

    # Notificación automática a los administradores
    await context.bot.send_message(
        chat_id=ADMIN_GROUP_ID,
        text=(
            f"🔔 **Nueva Solicitud Registrada** 🔔\n"
            f"🎟️ **Ticket #{ticket}**\n"
            f"👤 @{escape_markdown(username)}\n"
            f"📝 Mensaje: {escape_markdown(message)}\n"
            f"🏠 Grupo: {escape_markdown(group_name)}\n"
            f"🕒 Fecha: {request['date']}\n"
            f"Usa `/vp {ticket}` para ver detalles. 📋"
        ),
        parse_mode="Markdown"
    )
    logger.info(f"Solicitud registrada - Ticket #{ticket} por @{username}")

# Comando /vp - Solo administradores (usando número de ticket con botones)
async def view_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    data = load_requests()
    if not data["requests"]:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📪 **¡Todo limpio!** No hay solicitudes pendientes por ahora. 😊"
        )
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.info("No hay solicitudes pendientes")
        return

    if context.args and context.args[0].isdigit():
        ticket = int(context.args[0])
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            status_mark = f"📋 Estado: {request['status']}" if request["status"] else "📋 Estado: En espera"
            priority_mark = "🔥 **Prioridad**" if request["priority"] else ""
            keyboard = [
                [InlineKeyboardButton("🗑️ Eliminar", callback_data=f"delete_{ticket}_view")],
                [InlineKeyboardButton("🔥 Priorizar", callback_data=f"priority_{ticket}_view")],
                [InlineKeyboardButton("📩 Enviar Mensaje", callback_data=f"send_message_{ticket}_view")],
                [InlineKeyboardButton("🔙 Volver", callback_data="menu_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📋 **Solicitud - Ticket #{ticket}** {priority_mark}\n"
                     f"👤 @{escape_markdown(request['username'])}\n"
                     f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                     f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                     f"🌐 Fuente: {request['source']}\n"
                     f"🕒 Fecha: {request['date']}\n"
                     f"{status_mark}\n",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
            logger.info(f"Visualización de solicitud - Ticket #{ticket}")
        else:
            msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ No se encontró el Ticket #{ticket}. 😕"
            )
            await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
            logger.warning(f"Ticket #{ticket} no encontrado")
        return
    else:
        # Mostrar lista de tickets si no se especifica un ticket
        sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
        keyboard = []
        for req in sorted_requests:
            status_mark = f" ({req['status']})" if req["status"] != "en espera" else ""
            button_text = f"🎟️ Ticket #{req['ticket']}{status_mark} (@{req['username']})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"view_select_{req['ticket']}")])
        keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="menu_start")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📋 **Lista de Solicitudes Pendientes** 🌟\nSelecciona un ticket para ver detalles: 👇",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.info("Lista de solicitudes mostrada")

# Comando /bp - Solo administradores (lista de tickets con botones)
async def delete_request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    data = load_requests()
    if not data["requests"]:
        msg = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📪 **¡Todo limpio!** No hay solicitudes pendientes por ahora. 😊"
        )
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.info("No hay solicitudes para eliminar")
        return

    # Mostrar lista de tickets para seleccionar
    keyboard = []
    sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
    for req in sorted_requests:
        status_mark = f" ({req['status']})" if req["status"] != "en espera" else ""
        button_text = f"🎟️ Ticket #{req['ticket']}{status_mark} (@{req['username']})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_select_{req['ticket']}")])
    keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="menu_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🗑️ **Seleccionar Solicitud para Eliminar** 🛠️\nElige un ticket para procesar: 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
    logger.info("Lista de solicitudes para eliminar mostrada")

# Comando /reply - Solo administradores (responder a una solicitud)
async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not context.args or len(context.args) < 2:
        msg = await update.message.reply_text("❌ Uso: `/reply <ticket> <mensaje>`", parse_mode="Markdown")
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.warning("Uso incorrecto del comando /reply")
        return

    try:
        ticket = int(context.args[0])
    except ValueError:
        msg = await update.message.reply_text("❌ El número de ticket debe ser un valor numérico. Ejemplo: `/reply 1 Hola`")
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.warning("Número de ticket inválido en comando /reply")
        return

    reply_message = " ".join(context.args[1:])

    data = load_requests()
    request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
    if request:
        try:
            user_response = (
                f"📩 **Respuesta a tu Solicitud** 📩\n"
                f"🎟️ Ticket #{ticket}\n"
                f"👤 @{escape_markdown(request['username'])}\n"
                f"📝 Respuesta: {escape_markdown(reply_message)}"
            )
            admin_response = (
                f"📢 **Respuesta Enviada** 📩\n"
                f"🎟️ Ticket #{ticket}\n"
                f"👤 @{escape_markdown(request['username'])}\n"
                f"📝 Mensaje: {escape_markdown(reply_message)}"
            )
            await context.bot.send_message(
                chat_id=request["group_id"],
                text=user_response,
                parse_mode="Markdown"
            )
            msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=admin_response,
                parse_mode="Markdown"
            )
            await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
            logger.info(f"Respuesta enviada para Ticket #{ticket}: {reply_message}")
        except TelegramError as e:
            msg = await update.message.reply_text(f"❌ Error al enviar la respuesta: {str(e)}")
            await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
            logger.error(f"Error al enviar respuesta para Ticket #{ticket}: {str(e)}")
    else:
        msg = await update.message.reply_text(f"❌ Ticket #{ticket} no encontrado", parse_mode="Markdown")
        await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
        logger.warning(f"Ticket #{ticket} no encontrado para responder")

# Comando /rs - Solo administradores con botones
async def refresh_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("🔄 Refrescar Ahora", callback_data="rs_yes")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="rs_no")],
        [InlineKeyboardButton("🔙 Volver", callback_data="menu_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔄 **Refrescar Base de Datos** ✨\n"
             "📢 ¿Deseas refrescar la base de datos de solicitudes? Esto actualizará los datos actuales. 😊\n"
             "Confirma tu elección: 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
    logger.info("Comando /rs ejecutado, esperando confirmación")

# Comando /menu - Solo administradores con botones
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    menu_text = (
        "📖 **Menú de Comandos - EntresHijos** 🌟\n\n"
        "👤 **Para todos:**\n"
        "🔹 `/solicito <mensaje>` - Envía una solicitud (máx. 2 por día para no admins).\n"
        "🔹 `/infosolic <ticket>` - Consulta el estado de tu solicitud.\n\n"
        "👑 **Solo administradores:**\n"
        "🔹 `/vp <número_de_ticket>` - Muestra detalles de una solicitud o lista todas.\n"
        "🔹 `/bp` - Elimina una solicitud seleccionando un ticket.\n"
        "🔹 `/reply <ticket> <mensaje>` - Responde a una solicitud específica.\n"
        "🔹 `/rs` - Refresca la base de datos.\n"
        "🔹 `/stats` - Muestra estadísticas de solicitudes.\n"
        "🔹 `/menu` - Este menú.\n\n"
        "ℹ️ **Nota:** Solo admins pueden usar estos comandos aquí."
    )
    keyboard = [
        [InlineKeyboardButton("📋 Ver Solicitudes", callback_data="vp_start")],
        [InlineKeyboardButton("🗑️ Eliminar Solicitud", callback_data="bp_start")],
        [InlineKeyboardButton("📩 Responder Solicitud", callback_data="reply_start")],
        [InlineKeyboardButton("🔄 Refrescar", callback_data="rs_start")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="stats_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=menu_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
    logger.info("Menú mostrado al usuario")

# Comando /stats - Solo administradores con botones
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    data = load_requests()
    total_requests = len(data["requests"])
    groups = {}
    users = {}
    for req in data["requests"]:
        groups[req["group_name"]] = groups.get(req["group_name"], 0) + 1
        users[req["username"]] = users.get(req["username"], 0) + 1

    group_stats = "\n".join([f"🏠 {escape_markdown(group)}: {count} solicitudes" for group, count in groups.items()])
    top_users = "\n".join([f"👤 @{escape_markdown(user)}: {count} solicitudes" for user, count in sorted(users.items(), key=lambda x: x[1], reverse=True)[:3]])

    msg = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"📊 **Estadísticas - EntresHijos** 🌟\n\n"
             f"🔢 **Total de Solicitudes**: {total_requests}\n\n"
             f"🏡 **Por Grupo**:\n{group_stats}\n\n"
             f"👥 **Usuarios Más Activos (Top 3)**:\n{top_users}\n"
             f"¡Gracias por mantener todo en marcha! 🙌",
        parse_mode="Markdown"
    )
    await clean_admin_messages(context, update.effective_chat.id, msg.message_id)
    logger.info("Estadísticas mostradas")

# Comando /infosolic - Para usuarios
async def infosolic_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    if not context.args or not context.args[0].isdigit():
        msg = await update.message.reply_text("❌ Uso: `/infosolic <ticket>`. Proporciona el número de ticket. 😊")
        context.job_queue.run_once(auto_delete_message, 120, data=(chat_id, msg.message_id))
        logger.warning(f"Intento de /infosolic sin ticket válido por usuario {user.id}")
        return

    ticket = int(context.args[0])
    data = load_requests()
    request = next((req for req in data["requests"] if req["ticket"] == ticket and req["user_id"] == user.id), None)
    if request:
        status = request.get("status", "en espera")
        response_text = (
            f"ℹ️ **Información de Solicitud - Ticket #{ticket}** ℹ️\n"
            f"👤 @{escape_markdown(request['username'])}\n"
            f"📝 Mensaje: {escape_markdown(request['message'])}\n"
            f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
            f"🕒 Fecha: {request['date']}\n"
            f"📋 Estado: {status}\n"
        )
        if status == "subida":
            response_text += "🔍 Usa la lupa en el canal correspondiente para encontrar tu solicitud."
        elif status == "no aceptada":
            response_text += "❌ Tu solicitud no fue aceptada. Contacta a un administrador si necesitas ayuda."
        msg = await update.message.reply_text(response_text, parse_mode="Markdown")
        context.job_queue.run_once(auto_delete_message, 120, data=(chat_id, msg.message_id))
        logger.info(f"Información de solicitud mostrada - Ticket #{ticket} para @{request['username']}")
    else:
        msg = await update.message.reply_text(f"❌ Ticket #{ticket} no encontrado o no te pertenece. 😕", parse_mode="Markdown")
        context.job_queue.run_once(auto_delete_message, 120, data=(chat_id, msg.message_id))
        logger.warning(f"Ticket #{ticket} no encontrado o no pertenece a usuario {user.id}")

# Manejar las acciones de los botones
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data

    # Manejar botones que no tienen un ticket
    if action == "view_all":
        data = load_requests()
        sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
        message = "📋 **Solicitudes Detalladas** 🌟\n📅 Ordenadas de más antiguas a más recientes:\n\n"
        for req in sorted_requests:
            priority_mark = "🔥 **Prioridad**" if req["priority"] else ""
            status_mark = f" (Estado: {req['status']})" if req["status"] != "en espera" else ""
            message += (
                f"🎟️ **Ticket #{req['ticket']}** {priority_mark}{status_mark}\n"
                f"👤 @{escape_markdown(req['username'])}\n"
                f"📝 Mensaje: {escape_markdown(req['message'])}\n"
                f"🏠 Grupo: {escape_markdown(req['group_name'])}\n"
                f"🕒 Fecha: {req['date']}\n"
                f"➖➖➖➖➖➖➖\n"
            )
        keyboard = [
            [InlineKeyboardButton("🔙 Volver", callback_data="menu_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        await clean_admin_messages(context, query.message.chat_id, msg.message_id)
        logger.info("Vista detallada de solicitudes mostrada")
        return
    elif action == "menu_start":
        await menu_command(update, context)
        logger.info("Regreso al menú desde botón")
        return
    elif action in ["rs_yes", "rs_no"]:
        if action == "rs_yes":
            data = load_requests()  # Recargar la base de datos
            msg = await query.edit_message_text(
                "🔄 **¡Base de Datos Refrescada!** ✨\n"
                "✅ Todo está actualizado. Usa `/vp` para ver las solicitudes. 😊",
                parse_mode="Markdown"
            )
            await clean_admin_messages(context, query.message.chat_id, msg.message_id)
            logger.info("Base de datos refrescada")
        elif action == "rs_no":
            msg = await query.edit_message_text("❌ Operación cancelada. No se refrescó la base de datos. 😊", parse_mode="Markdown")
            await clean_admin_messages(context, query.message.chat_id, msg.message_id)
            logger.info("Refresco de base de datos cancelado")
        return
    elif action.startswith("view_select_"):
        ticket = int(action.split("_")[2])
        context.args = [str(ticket)]
        await view_requests_command(update, context)
        logger.info(f"Selección de ticket #{ticket} para ver detalles")

    # Manejar botones que tienen un ticket (delete_, priority_, send_message_)
    if action.startswith("delete_select_"):
        ticket = int(action.split("_")[2])
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            keyboard = [
                [InlineKeyboardButton("🚫 Solicitud NO Aceptada", callback_data=f"delete_{ticket}_not_accepted")],
                [InlineKeyboardButton("✅ Solicitud Subida", callback_data=f"delete_{ticket}_uploaded")],
                [InlineKeyboardButton("🔙 Volver", callback_data="menu_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            msg = await query.edit_message_text(
                f"🗑️ **Eliminar Solicitud - Ticket #{ticket}** 🛠️\n"
                f"👤 @{escape_markdown(request['username'])}\n"
                f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                f"🌐 Fuente: {request['source']}\n"
                f"🕒 Fecha: {request['date']}\n\n"
                f"¿Qué hacemos con esta solicitud? 👇",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            await clean_admin_messages(context, query.message.chat_id, msg.message_id)
            logger.info(f"Selección para eliminar Ticket #{ticket}")
    elif action.startswith("priority_select_"):
        ticket = int(action.split("_")[2])
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            keyboard = [
                [InlineKeyboardButton("🔥 Marcar como Prioridad", callback_data=f"priority_{ticket}_yes")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"priority_{ticket}_no")],
                [InlineKeyboardButton("🔙 Volver", callback_data="menu_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            msg = await query.edit_message_text(
                f"🔥 **Priorizar Solicitud - Ticket #{ticket}** ✨\n"
                f"👤 @{escape_markdown(request['username'])}\n"
                f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                f"🌐 Fuente: {request['source']}\n"
                f"🕒 Fecha: {request['date']}\n\n"
                f"¿Quieres marcar esta solicitud como prioritaria? 👇",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            await clean_admin_messages(context, query.message.chat_id, msg.message_id)
            logger.info(f"Selección para priorizar Ticket #{ticket}")
    elif action.startswith("send_message_"):
        ticket = int(action.split("_")[2])
        msg = await query.edit_message_text(
            f"📩 **Enviar Mensaje - Ticket #{ticket}** 📩\n"
            "Por favor, usa el comando `/reply {ticket} <mensaje>` para enviar un mensaje al usuario. Ejemplo: `/reply {ticket} Hola, tu solicitud fue procesada.` 😊",
            parse_mode="Markdown"
        )
        await clean_admin_messages(context, query.message.chat_id, msg.message_id)
        logger.info(f"Botón de enviar mensaje para Ticket #{ticket} activado")
    elif action.startswith("delete_"):
        parts = action.split("_")
        if len(parts) < 3:
            msg = await query.edit_message_text("❌ Error: Acción no válida. Por favor, intenta de nuevo. 😊")
            await clean_admin_messages(context, query.message.chat_id, msg.message_id)
            logger.error("Formato de acción delete_ inválido")
            return
        ticket = int(parts[1])
        status = parts[2]
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            if status in ["not_accepted", "uploaded"]:
                request["status"] = "subida" if status == "uploaded" else "no aceptada"
                data["requests"] = [req for req in data["requests"] if req["ticket"] != ticket]
                save_requests(data)
                status_message = "✅ Solicitud Subida" if status == "uploaded" else "🚫 Solicitud NO Aceptada"
                notification = (
                    f"📢 **Actualización de Solicitud** 📩\n"
                    f"👤 @{escape_markdown(request['username'])}\n"
                    f"🎟️ **Ticket #{ticket}**\n"
                    f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                    f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                    f"🌐 Fuente: EntresHijos\n"
                    f"🕒 Fecha: {request['date']}\n"
                    f"📋 Estado: {status_message}\n"
                )
                if status == "uploaded":
                    notification += "🔍 Usa la lupa en el canal correspondiente para encontrar tu solicitud."
                elif status == "not_accepted":
                    notification += "❌ Tu solicitud no fue aceptada. Contacta a un administrador si necesitas ayuda."
                msg = await context.bot.send_message(
                    chat_id=request["group_id"],
                    text=notification,
                    parse_mode="Markdown"
                )
                context.job_queue.run_once(auto_delete_message, 120, data=(request["group_id"], msg.message_id))
            else:
                data["requests"].remove(request)
                save_requests(data)
                status_message = "Solicitud Eliminada"
                msg = await query.edit_message_text(
                    f"✅ **{status_message}** 🎉\n"
                    f"👤 @{escape_markdown(request['username'])}\n"
                    f"🎟️ Ticket #{ticket}\n"
                    f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                    f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                    f"🌐 Fuente: EntresHijos\n"
                    f"🕒 Fecha: {request['date']}",
                    parse_mode="Markdown"
                )
                await clean_admin_messages(context, query.message.chat_id, msg.message_id)

            logger.info(f"Solicitud procesada - Ticket #{ticket}, Estado: {status_message}")
    elif action.startswith("priority_"):
        parts = action.split("_")
        if len(parts) < 3:
            msg = await query.edit_message_text("❌ Error: Acción no válida. Por favor, intenta de nuevo. 😊")
            await clean_admin_messages(context, query.message.chat_id, msg.message_id)
            logger.error("Formato de acción priority_ inválido")
            return
        ticket = int(parts[1])
        status = parts[2]
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            if status == "yes":
                request["priority"] = True
                save_requests(data)
                notification = (
                    f"📢 **Solicitud Priorizada** 🔥\n"
                    f"👤 @{escape_markdown(request['username'])}\n"
                    f"🎟️ **Ticket #{ticket}**\n"
                    f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                    f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                    f"🌐 Fuente: EntresHijos\n"
                    f"🕒 Fecha: {request['date']}\n"
                    f"📋 Estado: Marcada como prioritaria.\n"
                    f"¡Se procesará pronto! 🚀"
                )
                msg = await context.bot.send_message(
                    chat_id=request["group_id"],
                    text=notification,
                    parse_mode="Markdown"
                )
                context.job_queue.run_once(auto_delete_message, 120, data=(request["group_id"], msg.message_id))
                msg = await query.edit_message_text(
                    f"✅ **Prioridad Activada** 🔥\n"
                    f"👤 @{escape_markdown(request['username'])}\n"
                    f"🎟️ Ticket #{ticket}\n"
                    f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                    f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                    f"🌐 Fuente: EntresHijos\n"
                    f"¡Marcada como prioritaria con éxito! 🙌",
                    parse_mode="Markdown"
                )
                await clean_admin_messages(context, query.message.chat_id, msg.message_id)
                logger.info(f"Prioridad activada para Ticket #{ticket}")
            else:
                msg = await query.edit_message_text("❌ Operación cancelada. La solicitud sigue sin prioridad. 😊", parse_mode="Markdown")
                await clean_admin_messages(context, query.message.chat_id, msg.message_id)
                logger.info(f"Priorización cancelada para Ticket #{ticket}")

# Manejar botones de acciones específicas
async def action_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    if action == "vp_start":
        await view_requests_command(update, context)
        logger.info("Botón Ver Solicitudes activado")
    elif action == "bp_start":
        await delete_request_command(update, context)
        logger.info("Botón Eliminar Solicitud activado")
    elif action == "reply_start":
        await query.edit_message_text(
            "📩 **Responder a una Solicitud**\n"
            "Por favor, usa el comando `/reply <ticket> <mensaje>` para enviar una respuesta. Ejemplo: `/reply 1 Hola, tu solicitud fue procesada.` 😊",
            parse_mode="Markdown"
        )
        logger.info("Botón Responder Solicitud activado")
    elif action == "rs_start":
        await refresh_requests_command(update, context)
        logger.info("Botón Refrescar activado")
    elif action == "stats_start":
        await stats_command(update, context)
        logger.info("Botón Estadísticas activado")

# Función principal
def main():
    application = Application.builder().token(TOKEN).build()

    # Añadir handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("solicito", request_command))
    application.add_handler(CommandHandler("vp", view_requests_command))
    application.add_handler(CommandHandler("bp", delete_request_command))
    application.add_handler(CommandHandler("reply", reply_command))
    application.add_handler(CommandHandler("rs", refresh_requests_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("infosolic", infosolic_command))

    # Handlers para botones
    application.add_handler(CallbackQueryHandler(button_start_handler, pattern="^solicito_start$|^menu_start$"))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^view_all$|^rs_|^delete_|^priority_|^send_message_|^view_select_"))
    application.add_handler(CallbackQueryHandler(action_button_handler, pattern="^vp_start$|^bp_start$|^reply_start$|^rs_start$|^stats_start$"))

    # Añadir manejador de errores
    application.add_error_handler(error_handler)

    # Iniciar el bot
    logger.info("Bot iniciado exitosamente")
    print("Bot iniciado exitosamente. Escuchando comandos...")
    application.run_polling()

if __name__ == "__main__":
    main()