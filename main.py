import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_GROUP_ID = "-1002305997509"  # ID del grupo de administradores
REQUEST_LIMIT = 2  # Límite de solicitudes por usuario cada 24 horas en modo normal o prueba

# Archivo para la base de datos de solicitudes
DB_FILE = "requests.json"

# Variable global para el modo de prueba
TEST_MODE = {"enabled": False}  # Estado del modo de prueba

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
    admins = await context.bot.get_chat_administrators(chat_id)
    return any(admin.user.id == user.id for admin in admins)

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

# Comando /solicito - Cualquier usuario (con límite según modo, sin botones)
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
    is_admin_user = await context.bot.get_chat_member(ADMIN_GROUP_ID, user.id)
    is_admin_flag = is_admin_user.status in ["administrator", "creator"]
    username = user.username or f"Usuario_{user.id}"

    # Aplicar límite según el modo
    apply_limit = TEST_MODE["enabled"] or not is_admin_flag
    if apply_limit:
        request_count, first_request_time = count_user_requests(user.id)

        if request_count >= REQUEST_LIMIT:
            if first_request_time:
                reset_time = first_request_time + timedelta(hours=24)
                time_left = reset_time - datetime.now()
                hours_left = int(time_left.total_seconds() // 3600)
                minutes_left = int((time_left.total_seconds() % 3600) // 60)

                await update.message.reply_text(
                    f"⛔ ¡Lo siento, @{username}! Has agotado tus {REQUEST_LIMIT} solicitudes diarias. 😔\n"
                    f"⏳ Podrás hacer más en {hours_left}h {minutes_left}m (a las {reset_time.strftime('%H:%M:%S')}).\n"
                    f"¡Paciencia! 🌟"
                )

                if request_count > REQUEST_LIMIT:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"/warn @{username} Abuso de peticiones diarias."
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
        f"👤 @{username}\n"
        f"🎟️ **Ticket #{ticket}**\n"
        f"📝 Mensaje: {message}\n"
        f"🏠 Grupo: {group_name}\n"
        f"🌐 Fuente: EntresHijos\n"
        f"🕒 Fecha: {request['date']}\n"
        f"¡Gracias por tu paciencia! 🙌"
    )
    if apply_limit:
        response_text += f"\n📊 **Solicitudes restantes hoy**: {remaining_requests}"

    await context.bot.send_message(
        chat_id=chat_id,
        text=response_text,
        parse_mode="Markdown"
    )

# Comando /onp - Activar modo prueba (solo administradores con botones)
async def enable_test_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("✅ Activar Modo Prueba", callback_data="onp_yes")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="onp_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🛠️ **Activar Modo Prueba** ✨\n"
             "📢 ¿Deseas activar el modo prueba? Todos, incluidos administradores, tendrán un límite de 2 solicitudes diarias con `/solicito`. Usa `/ofp` para desactivar después. 😊\n"
             "Confirma tu elección: 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Comando /ofp - Desactivar modo prueba (solo administradores con botones)
async def disable_test_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("✅ Desactivar Modo Prueba", callback_data="ofp_yes")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="ofp_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="✅ **Desactivar Modo Prueba** 🌟\n"
             "📢 ¿Deseas restaurar el modo normal? Los administradores quedarán exentos del límite de solicitudes diarias. 😊\n"
             "Confirma tu elección: 👇",
        reply_markup=reply_markup,
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
                [InlineKeyboardButton("🔥 Priorizar", callback_data=f"priority_{ticket}_view")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=f"📋 **Solicitud - Ticket #{ticket}** {priority_mark}\n"
                     f"👤 @{request['username']}\n"
                     f"📝 Mensaje: {request['message']}\n"
                     f"🏠 Grupo: {request['group_name']}\n"
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

# Comando /priority - Solo administradores (lista de tickets con botones)
async def priority_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # Mostrar lista de tickets para priorizar
    keyboard = []
    sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
    for req in sorted_requests:
        button_text = f"🎟️ Ticket #{req['ticket']} (@{req['username']})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"priority_select_{req['ticket']}")])
    keyboard.append([InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_start")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="🔥 **Seleccionar Solicitud para Priorizar** ✨\nElige un ticket para marcar como prioritario: 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Comando /rs - Solo administradores con botones
async def refresh_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("🔄 Refrescar Ahora", callback_data="rs_yes")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="rs_no")]
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
        "🔹 `/solicito <mensaje>` - Envía una solicitud (máx. 2 por día, admins exentos en modo normal).\n\n"
        "👑 **Solo administradores:**\n"
        "🔹 `/vp <número_de_ticket>` - Muestra detalles de una solicitud o lista todas.\n"
        "🔹 `/bp` - Elimina una solicitud seleccionando un ticket.\n"
        "🔹 `/rs` - Refresca la base de datos.\n"
        "🔹 `/stats` - Muestra estadísticas de solicitudes.\n"
        "🔹 `/priority` - Marca una solicitud como prioritaria seleccionando un ticket.\n"
        "🔹 `/backup` - Descarga una copia de la base de datos.\n"
        "🔹 `/onp` - Activa modo prueba (límite para todos).\n"
        "🔹 `/ofp` - Desactiva modo prueba (vuelve a normal).\n"
        "🔹 `/menu` - Este menú.\n\n"
        "ℹ️ **Nota:** Solo admins pueden usar estos comandos aquí."
    )
    keyboard = [
        [InlineKeyboardButton("📋 Ver Solicitudes", callback_data="vp_start")],
        [InlineKeyboardButton("🗑️ Eliminar Solicitud", callback_data="bp_start")],
        [InlineKeyboardButton("🔥 Priorizar Solicitud", callback_data="priority_start")],
        [InlineKeyboardButton("🔄 Refrescar", callback_data="rs_start")],
        [InlineKeyboardButton("📊 Estadísticas", callback_data="stats_start")],
        [InlineKeyboardButton("💾 Backup", callback_data="backup_start")],
        [InlineKeyboardButton("🛠️ Modo Prueba ON", callback_data="onp_start")],
        [InlineKeyboardButton("✅ Modo Prueba OFF", callback_data="ofp_start")]
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

    group_stats = "\n".join([f"🏠 {group}: {count} solicitudes" for group, count in groups.items()])
    top_users = "\n".join([f"👤 @{user}: {count} solicitudes" for user, count in sorted(users.items(), key=lambda x: x[1], reverse=True)[:3]])

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

# Comando /backup - Solo administradores con botones
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    keyboard = [
        [InlineKeyboardButton("💾 Descargar Backup", callback_data="backup_yes")],
        [InlineKeyboardButton("❌ Cancelar", callback_data="backup_no")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="💾 **Generar Copia de Seguridad - EntresHijos** ✨\n"
             "📢 ¿Deseas descargar una copia de la base de datos de solicitudes? 😊\n"
             "Confirma tu elección: 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Manejar las acciones de los botones
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    if action == "view_all":
        data = load_requests()
        sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
        message = "📋 **Solicitudes Detalladas - EntresHijos** 🌟\n📅 Ordenadas de más antiguas a más recientes:\n\n"
        for req in sorted_requests:
            priority_mark = "🔥 **Prioridad**" if req["priority"] else ""
            message += (
                f"🎟️ **Ticket #{req['ticket']}** {priority_mark}\n"
                f"👤 @{req['username']}\n"
                f"📝 Mensaje: {req['message']}\n"
                f"🏠 Grupo: {req['group_name']}\n"
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
    elif action in ["onp_yes", "ofp_yes", "rs_yes", "backup_yes"]:
        if action == "onp_yes":
            TEST_MODE["enabled"] = True
            await query.edit_message_text(
                "🛠️ **Modo Prueba Activado** ✨\n"
                "📢 Ahora todos, incluidos administradores, tienen un límite de 2 solicitudes diarias con `/solicito`.\n"
                "Usa `/ofp` para volver al modo normal. 😊",
                parse_mode="Markdown"
            )
        elif action == "ofp_yes":
            TEST_MODE["enabled"] = False
            await query.edit_message_text(
                "✅ **Modo Normal Restaurado** 🌟\n"
                "📢 Los administradores ahora están exentos del límite de solicitudes diarias.\n"
                "¡Todo listo para seguir! 🙌",
                parse_mode="Markdown"
            )
        elif action == "rs_yes":
            data = load_requests()
            await query.edit_message_text(
                "🔄 **¡Base de Datos Refrescada!** ✨\n"
                "✅ Todo está actualizado. Usa `/vp` para ver las solicitudes. 😊",
                parse_mode="Markdown"
            )
        elif action == "backup_yes":
            data = load_requests()
            backup_file = "backup_requests.json"
            with open(backup_file, "w") as f:
                json.dump(data, f, indent=4)
            await context.bot.send_document(
                chat_id=ADMIN_GROUP_ID,
                document=open(backup_file, "rb"),
                caption="💾 **Copia de Seguridad - EntresHijos** ✨\nAquí tienes el respaldo de todas las solicitudes. ¡Guárdalo bien! 😊",
                filename="backup_requests.json"
            )
            os.remove(backup_file)
            await query.edit_message_text("✅ **Backup enviado con éxito!** 💾", parse_mode="Markdown")
        return
    elif action in ["onp_no", "ofp_no", "rs_no", "backup_no"]:
        if action == "onp_no":
            await query.edit_message_text("❌ Operación cancelada. El modo prueba no se activó. 😊", parse_mode="Markdown")
        elif action == "ofp_no":
            await query.edit_message_text("❌ Operación cancelada. El modo normal no se restauró. 😊", parse_mode="Markdown")
        elif action == "rs_no":
            await query.edit_message_text("❌ Operación cancelada. No se refresco la base de datos. 😊", parse_mode="Markdown")
        elif action == "backup_no":
            await query.edit_message_text("❌ Operación cancelada. No se generó backup. 😊", parse_mode="Markdown")
        return
    elif action.startswith("delete_select_"):
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
                f"👤 @{request['username']}\n"
                f"📝 Mensaje: {request['message']}\n"
                f"🏠 Grupo: {request['group_name']}\n"
                f"🌐 Fuente: {request['source']}\n"
                f"🕒 Fecha: {request['date']}\n\n"
                f"¿Qué hacemos con esta solicitud? 👇",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    elif action.startswith("priority_select_"):
        ticket = int(action.split("_")[2])
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            keyboard = [
                [InlineKeyboardButton("🔥 Marcar como Prioridad", callback_data=f"priority_{ticket}_yes")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"priority_{ticket}_no")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"🔥 **Priorizar Solicitud - Ticket #{ticket}** ✨\n"
                f"👤 @{request['username']}\n"
                f"📝 Mensaje: {request['message']}\n"
                f"🏠 Grupo: {request['group_name']}\n"
                f"🌐 Fuente: {request['source']}\n"
                f"🕒 Fecha: {request['date']}\n\n"
                f"¿Quieres marcar esta solicitud como prioritaria? 👇",
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    elif action.startswith("delete_"):
        ticket = int(action.split("_")[1])
        status = action.split("_")[2]
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            data["requests"] = [req for req in data["requests"] if req["ticket"] != ticket]
            save_requests(data)

            status_message = "🚫 Solicitud NO Aceptada" if status == "not_accepted" else "✅ Solicitud Subida"
            notification = (
                f"📢 **Actualización de Solicitud** 📩\n"
                f"👤 @{request['username']}\n"
                f"🎟️ **Ticket #{ticket}**\n"
                f"📝 Mensaje: {request['message']}\n"
                f"🏠 Grupo: {request['group_name']}\n"
                f"🌐 Fuente: EntresHijos\n"
                f"{status_message}\n"
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
            await context.bot.send_message(
                chat_id=request["user_id"],
                text=notification,
                parse_mode="Markdown"
            )

            await query.edit_message_text(
                f"✅ **Solicitud Procesada** 🎉\n"
                f"👤 @{request['username']}\n"
                f"🎟️ Ticket #{ticket}\n"
                f"📝 Mensaje: {request['message']}\n"
                f"🏠 Grupo: {request['group_name']}\n"
                f"🌐 Fuente: EntresHijos\n"
                f"{status_message}",
                parse_mode="Markdown"
            )
    elif action.startswith("priority_"):
        ticket = int(action.split("_")[1])
        status = action.split("_")[2]
        data = load_requests()
        request = next((req for req in data["requests"] if req["ticket"] == ticket), None)
        if request:
            if status == "yes":
                request["priority"] = True
                save_requests(data)
                await query.edit_message_text(
                    f"✅ **Prioridad Activada** 🔥\n"
                    f"👤 @{request['username']}\n"
                    f"🎟️ Ticket #{ticket}\n"
                    f"📝 Mensaje: {request['message']}\n"
                    f"🏠 Grupo: {request['group_name']}\n"
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
    elif action == "priority_start":
        await priority_command(update, context)
    elif action == "stats_start":
        await stats_command(update, context)
    elif action == "onp_start":
        await enable_test_mode(update, context)
    elif action == "ofp_start":
        await disable_test_mode(update, context)

# Función principal
def main():
    application = Application.builder().token(TOKEN).build()

    # Añadir handlers
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("solicito", request_command))
    application.add_handler(CommandHandler("onp", enable_test_mode))
    application.add_handler(CommandHandler("ofp", disable_test_mode))
    application.add_handler(CommandHandler("vp", view_requests_command))
    application.add_handler(CommandHandler("bp", delete_request_command))
    application.add_handler(CommandHandler("rs", refresh_requests_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("priority", priority_command))
    application.add_handler(CommandHandler("backup", backup_command))

    # Handlers para botones
    application.add_handler(CallbackQueryHandler(button_start_handler, pattern="^solicito_start$|^menu_start$"))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^view_all$|^onp_|^ofp_|^rs_|^backup_|^delete_|^priority_"))
    application.add_handler(CallbackQueryHandler(action_button_handler, pattern="^vp_start$|^bp_start$|^priority_start$|^stats_start$|^onp_start$|^ofp_start$"))

    # Iniciar el bot
    print("Bot iniciado exitosamente. Escuchando comandos...")
    application.run_polling()

if __name__ == "__main__":
    main()