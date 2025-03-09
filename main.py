import json
import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.helpers import escape_markdown
from telegram.error import TelegramError
from dotenv import load_dotenv

# Configurar logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = "-1002305997509"  # ID del grupo de administradores
REQUEST_LIMIT = 2  # Límite de solicitudes por usuario cada 24 horas

# Archivo para la base de datos de solicitudes
DB_FILE = "requests.json"

# Cargar o inicializar la base de datos
def load_requests():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            return json.load(f)
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
        return False
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        return any(admin.user.id == user.id for admin in admins)
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Error al verificar administradores: {str(e)}")
        return False

# Manejador de errores global
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text("❌ ¡Ups! Ocurrió un error. Por favor, intenta de nuevo o contacta a un administrador. 😊")

# Mensaje de bienvenida al iniciar el bot
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = (
        "🌟 **¡Bienvenido a Grupos-EntresHijos Bot!** 🌟\n"
        "📢 Este bot está diseñado exclusivamente para gestionar solicitudes en los grupos de EntresHijos.\n"
        "👥 **Para todos:** Usa `/solicito <mensaje>` para enviar una solicitud.\n"
        "👑 **Solo administradores:** Usa `/menu` para ver los comandos disponibles.\n"
        "ℹ️ ¡Estamos aquí para ayudarte! 🙌"
    )
    keyboard = [
        [InlineKeyboardButton("📝 Enviar Solicitud", callback_data="solicito_start")],
        [InlineKeyboardButton("ℹ️ Ver Menú", callback_data="menu_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode="Markdown")

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
    elif action == "menu_start":
        await menu_command(update, context)

# Comando /solicito - Cualquier usuario (con límite para no administradores)
async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    message = " ".join(context.args)

    if not message:
        await update.message.reply_text(
            "❌ ¡Hey! Necesitas escribir un mensaje. Ejemplo: `/solicito Quiero ayuda`. 😊"
        )
        return

    # Verificar si el usuario es administrador
    try:
        is_admin_user = await context.bot.get_chat_member(ADMIN_GROUP_ID, user.id)
        is_admin_flag = is_admin_user.status in ["administrator", "creator"]
    except TelegramError as e:
        await update.message.reply_text(f"❌ Error al verificar estado de administrador: {str(e)}")
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
        "priority": False
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

    await context.bot.send_message(
        chat_id=chat_id,
        text=response_text,
        parse_mode="Markdown"
    )

    # Notificación de "Solicitud en cola"
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

# Comando /vp - Solo administradores (usando número de ticket con botones)
async def view_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    data = load_requests()
    if not data["requests"]:
        keyboard = [
            [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📪 **¡Todo limpio!** No hay solicitudes pendientes por ahora. 😊",
            reply_markup=reply_markup
        )
        return

    if context.args and context.args[0].isdigit():
        ticket = int(context.args[0])
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            priority_mark = "🔥 **Prioridad**" if request["priority"] else ""
            keyboard = [
                [InlineKeyboardButton("🗑️ Eliminar", callback_data=f"delete_{ticket}_view")],
                [InlineKeyboardButton("🔥 Priorizar", callback_data=f"pri_{ticket}_view")],
                [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📋 **Solicitud - Ticket #{ticket}** {priority_mark}\n"
                     f"👤 @{escape_markdown(request['username'])}\n"
                     f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                     f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                     f"🌐 Fuente: {request['source']}\n"
                     f"🕒 Fecha: {request['date']}\n\n"
                     f"Acciones disponibles: 👇",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            keyboard = [
                [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"❌ No se encontró el Ticket #{ticket}. 😕",
                reply_markup=reply_markup
            )
        return

    # Vista general si no se especifica ticket
    sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
    message = "📋 **Solicitudes Pendientes - EntresHijos** 🌟\n📅 Ordenadas de más antiguas a más recientes:\n\n"
    for req in sorted_requests:
        priority_mark = "🔥 **Prioridad**" if req["priority"] else ""
        message += f"🎟️ Ticket #{req['ticket']} {priority_mark}\n"
    keyboard = [
        [InlineKeyboardButton("🔍 Ver Detalles", callback_data="view_all")],
        [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=message + "\nSelecciona una acción: 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Comando /bp - Solo administradores (lista de tickets con botones)
async def delete_request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    data = load_requests()
    if not data["requests"]:
        keyboard = [
            [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📪 **¡Todo limpio!** No hay solicitudes pendientes por ahora. 😊",
            reply_markup=reply_markup
        )
        return

    # Mostrar lista de tickets para seleccionar
    keyboard = []
    sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
    for req in sorted_requests:
        button_text = f"🎟️ Ticket #{req['ticket']} (@{req['username']})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"delete_select_{req['ticket']}")])
    keyboard.append([InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🗑️ **Seleccionar Solicitud para Eliminar** 🛠️\nElige un ticket para procesar: 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Comando /pri - Solo administradores (lista detallada de tickets con botones para priorizar)
async def pri_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    data = load_requests()
    if not data["requests"]:
        keyboard = [
            [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="📪 **¡Todo limpio!** No hay solicitudes pendientes por ahora. 😊",
            reply_markup=reply_markup
        )
        return

    # Mostrar lista detallada de tickets
    sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
    message = "🔥 **Priorizar Solicitudes - EntresHijos** 🌟\n📅 Ordenadas de más antiguas a más recientes:\n\n"
    for req in sorted_requests:
        priority_mark = "🔥 **Prioridad**" if req["priority"] else ""
        message += (
            f"🎟️ **Ticket #{req['ticket']}** {priority_mark}\n"
            f"👤 @{escape_markdown(req['username'])}\n"
            f"📝 Mensaje: {escape_markdown(req['message'])}\n"
            f"🏠 Grupo: {escape_markdown(req['group_name'])}\n"
            f"🌐 Fuente: {req['source']}\n"
            f"🕒 Fecha: {req['date']}\n"
            f"➖➖➖➖➖➖➖\n"
        )
        # Botón para priorizar cada ticket
        keyboard = [[InlineKeyboardButton(f"🔥 Priorizar Ticket #{req['ticket']}", callback_data=f"pri_select_{req['ticket']}")]]
        keyboard.append([InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

# Comando /add - Solo administradores (añadir administrador al grupo)
async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not context.args or len(context.args) != 1:
        await update.message.reply_text(
            "❌ Uso incorrecto. Usa: `/add @username` para añadir un administrador. 😊",
            parse_mode="Markdown"
        )
        return

    username = context.args[0]
    if not username.startswith("@"):
        await update.message.reply_text(
            "❌ Por favor, proporciona un nombre de usuario válido con @. Ejemplo: `/add @username`. 😊",
            parse_mode="Markdown"
        )
        return

    username = username[1:]  # Quitar el @

    try:
        # Buscar al usuario en el chat para obtener su ID
        chat_members = await context.bot.get_chat_administrators(ADMIN_GROUP_ID)
        user_id = None
        for member in chat_members:
            if member.user.username == username:
                user_id = member.user.id
                break

        if not user_id:
            # Si no está en los administradores, intentar buscarlo en el chat
            chat = await context.bot.get_chat(ADMIN_GROUP_ID)
            async for member in chat.get_members():
                if member.user.username == username:
                    user_id = member.user.id
                    break

        if not user_id:
            await update.message.reply_text(
                f"❌ No se encontró al usuario @{escape_markdown(username)} en el grupo. Asegúrate de que esté presente. 😊",
                parse_mode="Markdown"
            )
            return

        # Promover al usuario a administrador
        await context.bot.promote_chat_member(
            chat_id=ADMIN_GROUP_ID,
            user_id=user_id,
            can_change_info=True,
            can_delete_messages=True,
            can_invite_users=True,
            can_restrict_members=True,
            can_pin_messages=True,
            can_promote_members=False
        )

        await update.message.reply_text(
            f"✅ ¡Éxito! @{escape_markdown(username)} ha sido promovido a administrador. 🙌",
            parse_mode="Markdown"
        )

    except TelegramError as e:
        await update.message.reply_text(
            f"❌ Error al añadir administrador: {str(e)}. Asegúrate de que el bot tenga permisos para promover miembros. 😊",
            parse_mode="Markdown"
        )

# Comando /rs - Solo administradores con botones
async def refresh_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("🔄 Refrescar Ahora", callback_data="rs_yes")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="rs_no")],
        [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔄 **Refrescar Base de Datos** ✨\n"
             "📢 ¿Deseas refrescar la base de datos de solicitudes? Esto actualizará los datos actuales. 😊\n"
             "Confirma tu elección: 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Comando /menu - Solo administradores con botones
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    menu_text = (
        "📖 **Menú de Comandos - EntresHijos** 🌟\n\n"
        "👤 **Para todos:**\n"
        "🔹 `/solicito <mensaje>` - Envía una solicitud (máx. 2 por día para no admins).\n\n"
        "👑 **Solo administradores:**\n"
        "🔹 `/vp <número_de_ticket>` - Muestra detalles de una solicitud o lista todas.\n"
        "🔹 `/bp` - Elimina una solicitud seleccionando un ticket.\n"
        "🔹 `/rs` - Refresca la base de datos.\n"
        "🔹 `/stats` - Muestra estadísticas de solicitudes.\n"
        "🔹 `/pri` - Marca una solicitud como prioritaria.\n"
        "🔹 `/add @username` - Añade un administrador al grupo.\n"
        "🔹 `/menu` - Este menú.\n\n"
        "ℹ️ **Nota:** Solo admins pueden usar estos comandos aquí."
    )
    keyboard = [
        [InlineKeyboardButton("📋 Ver Solicitudes", callback_data="vp_start")],
        [InlineKeyboardButton("🗑️ Eliminar Solicitud", callback_data="bp_start")],
        [InlineKeyboardButton("🔥 Priorizar Solicitud", callback_data="pri_start")],
        [InlineKeyboardButton("🔄 Refrescar", callback_data="rs_start")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="stats_start")],
        [InlineKeyboardButton("👑 Añadir Admin", callback_data="add_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=menu_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

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

    keyboard = [
        [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"📊 **Estadísticas - EntresHijos** 🌟\n\n"
             f"🔢 **Total de Solicitudes**: {total_requests}\n\n"
             f"🏡 **Por Grupo**:\n{group_stats}\n\n"
             f"👥 **Usuarios Más Activos (Top 3)**:\n{top_users}\n"
             f"¡Gracias por mantener todo en marcha! 🙌",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Manejar las acciones de los botones
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data

    # Manejar botones que no tienen un ticket
    if action == "view_all":
        data = load_requests()
        sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
        message = "📋 **Solicitudes Detalladas - EntresHijos** 🌟\n📅 Ordenadas de más antiguas a más recientes:\n\n"
        for req in sorted_requests:
            priority_mark = "🔥 **Prioridad**" if req["priority"] else ""
            message += (
                f"🎟️ **Ticket #{req['ticket']}** {priority_mark}\n"
                f"👤 @{escape_markdown(req['username'])}\n"
                f"📝 Mensaje: {escape_markdown(req['message'])}\n"
                f"🏠 Grupo: {escape_markdown(req['group_name'])}\n"
                f"🕒 Fecha: {req['date']}\n"
                f"➖➖➖➖➖➖➖\n"
            )
        keyboard = [
            [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup, parse_mode="Markdown")
        return
    elif action == "menu_start":
        await menu_command(update, context)
        return
    elif action in ["rs_yes", "rs_no"]:
        if action == "rs_yes":
            data = load_requests()
            await query.edit_message_text(
                "🔄 **¡Base de Datos Refrescada!** ✨\n"
                "✅ Todo está actualizado. Usa `/vp` para ver las solicitudes. 😊",
                parse_mode="Markdown"
            )
        elif action == "rs_no":
            await query.edit_message_text("❌ Operación cancelada. No se refrescó la base de datos. 😊", parse_mode="Markdown")
        return

    # Manejar botones que tienen un ticket (delete_ o pri_)
    if action.startswith("delete_select_"):
        ticket = int(action.split("_")[2])
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            keyboard = [
                [InlineKeyboardButton("🚫 Solicitud NO Aceptada", callback_data=f"delete_{ticket}_not_accepted")],
                [InlineKeyboardButton("✅ Solicitud Subida", callback_data=f"delete_{ticket}_uploaded")],
                [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
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
    elif action.startswith("pri_select_"):
        ticket = int(action.split("_")[2])
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            keyboard = [
                [InlineKeyboardButton("🔥 Marcar como Prioridad", callback_data=f"pri_{ticket}_yes")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"pri_{ticket}_no")],
                [InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
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
    elif action.startswith("delete_"):
        parts = action.split("_")
        if len(parts) < 3:
            await query.edit_message_text("❌ Error: Acción no válida. Por favor, intenta de nuevo. 😊")
            return
        ticket = int(parts[1])
        status = parts[2]
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            data["requests"] = [req for req in data["requests"] if req["ticket"] != ticket]
            save_requests(data)

            status_message = "🚫 Solicitud NO Aceptada" if status == "not_accepted" else "✅ Solicitud Subida"
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
                notification += "Por favor, usa la lupa en el canal correspondiente para encontrar tu solicitud. 🔍"
            elif status == "not_accepted":
                notification += "Tu solicitud no fue aceptada. Contacta a un administrador si necesitas ayuda. 😊"

            await context.bot.send_message(
                chat_id=request["group_id"],
                text=notification,
                parse_mode="Markdown"
            )

            await query.edit_message_text(
                f"✅ **Solicitud Procesada** 🎉\n"
                f"👤 @{escape_markdown(request['username'])}\n"
                f"🎟️ Ticket #{ticket}\n"
                f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                f"🌐 Fuente: EntresHijos\n"
                f"📋 Estado: {status_message}",
                parse_mode="Markdown"
            )
    elif action.startswith("pri_"):
        parts = action.split("_")
        if len(parts) < 3:
            await query.edit_message_text("❌ Error: Acción no válida. Por favor, intenta de nuevo. 😊")
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
                await context.bot.send_message(
                    chat_id=request["group_id"],
                    text=notification,
                    parse_mode="Markdown"
                )
                await query.edit_message_text(
                    f"✅ **Prioridad Activada** 🔥\n"
                    f"👤 @{escape_markdown(request['username'])}\n"
                    f"🎟️ Ticket #{ticket}\n"
                    f"📝 Mensaje: {escape_markdown(request['message'])}\n"
                    f"🏠 Grupo: {escape_markdown(request['group_name'])}\n"
                    f"🌐 Fuente: EntresHijos\n"
                    f"¡Marcada como prioritaria con éxito! 🙌",
                    parse_mode="Markdown"
                )
            else:
                await query.edit_message_text("❌ Operación cancelada. La solicitud sigue sin prioridad. 😊", parse_mode="Markdown")

# Manejar botones de acciones específicas
async def action_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    if action == "vp_start":
        await view_requests_command(update, context)
    elif action == "bp_start":
        await delete_request_command(update, context)
    elif action == "pri_start":
        await pri_command(update, context)
    elif action == "rs_start":
        await refresh_requests_command(update, context)
    elif action == "stats_start":
        await stats_command(update, context)
    elif action == "add_start":
        await query.edit_message_text(
            "👑 **Añadir Administrador**\n"
            "Por favor, usa el comando `/add @username` para añadir un administrador. Ejemplo: `/add @username`. 😊"
        )

# Función principal
def main():
    application = Application.builder().token(TOKEN).build()

    # Añadir handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("solicito", request_command))
    application.add_handler(CommandHandler("vp", view_requests_command))
    application.add_handler(CommandHandler("bp", delete_request_command))
    application.add_handler(CommandHandler("rs", refresh_requests_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("pri", pri_command))
    application.add_handler(CommandHandler("add", add_admin_command))

    # Handlers para botones
    application.add_handler(CallbackQueryHandler(button_start_handler, pattern="^solicito_start$|^menu_start$"))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^view_all$|^rs_|^delete_|^pri_"))
    application.add_handler(CallbackQueryHandler(action_button_handler, pattern="^vp_start$|^bp_start$|^pri_start$|^rs_start$|^stats_start$|^add_start$"))

    # Añadir manejador de errores
    application.add_error_handler(error_handler)

    # Iniciar el bot
    print("Bot iniciado exitosamente. Escuchando comandos...")
    application.run_polling()

if __name__ == "__main__":
    main()