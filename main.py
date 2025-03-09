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
        await update.message.reply_text("❌ ¡Ups! Este comando solo funciona en el grupo de administradores. 😊")
        return False
    admins = await context.bot.get_chat_administrators(chat_id)
    return any(admin.user.id == user.id for admin in admins)

# Comando /solicito - Cualquier usuario (con límite según modo)
async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    message = " ".join(context.args)

    if not message:
        await update.message.reply_text("❌ ¡Hey! Necesitas escribir un mensaje. Ejemplo: `/solicito Quiero ayuda`. 😊")
        return

    # Verificar si el usuario es administrador
    is_admin_user = await context.bot.get_chat_member(ADMIN_GROUP_ID, user.id)
    is_admin_flag = is_admin_user.status in ["administrator", "creator"]
    username = user.username or f"Usuario_{user.id}"

    # Aplicar límite según el modo
    apply_limit = TEST_MODE["enabled"] or not is_admin_flag  # Límite en modo prueba o para no admins en modo normal
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
            remaining_requests = REQUEST_LIMIT - request_count - 1  # Restantes después de esta solicitud

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
        f"📋 **Ticket #{ticket}**\n"
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

# Comando /onp - Activar modo prueba (solo administradores)
async def enable_test_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    TEST_MODE["enabled"] = True
    await update.message.reply_text(
        "🛠️ **Modo Prueba Activado** ✨\n"
        "📢 Ahora todos, incluidos administradores, tienen un límite de 2 solicitudes diarias con `/solicito`.\n"
        "Usa `/ofp` para volver al modo normal. 😊",
        parse_mode="Markdown"
    )

# Comando /ofp - Desactivar modo prueba (solo administradores)
async def disable_test_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    TEST_MODE["enabled"] = False
    await update.message.reply_text(
        "✅ **Modo Normal Restaurado** 🌟\n"
        "📢 Los administradores ahora están exentos del límite de solicitudes diarias.\n"
        "¡Todo listo para seguir! 🙌",
        parse_mode="Markdown"
    )

# Comando /vp - Solo administradores
async def view_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    data = load_requests()
    if not data["requests"]:
        await update.message.reply_text("📪 **¡Todo limpio!** No hay solicitudes pendientes por ahora. 😊")
        return

    sorted_requests = sorted(data["requests"], key=lambda x: x["date"])
    message = (
        "📋 **Solicitudes Pendientes - EntresHijos** 🌟\n"
        "📅 Ordenadas de más antiguas a más recientes:\n\n"
    )
    for req in sorted_requests:
        priority_mark = "🔥 **Prioridad**" if req["priority"] else ""
        message += (
            f"🎟️ **Ticket #{req['ticket']}** {priority_mark}\n"
            f"👤 @{req['username']}\n"
            f"📝 **Mensaje**: {req['message']}\n"
            f"🏠 **Grupo**: {req['group_name']}\n"
            f"🌐 **Fuente**: {req['source']}\n"
            f"🕒 **Fecha**: {req['date']}\n"
            f"➖➖➖➖➖➖➖\n"
        )

    await update.message.reply_text(message, parse_mode="Markdown")

# Comando /bp - Solo administradores (con botones)
async def delete_request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not context.args or not context.args[0].startswith("@"):
        await update.message.reply_text("❌ ¡Oops! Usa: `/bp @username` para eliminar una solicitud. 😊")
        return

    username = context.args[0][1:]
    data = load_requests()
    request_to_delete = None
    for req in data["requests"]:
        if req["username"] == username:
            request_to_delete = req
            break

    if not request_to_delete:
        await update.message.reply_text(f"❌ No encontramos ninguna solicitud de @{username}. ¿Seguro que existe? 🤔")
        return

    keyboard = [
        [InlineKeyboardButton("🚫 1 - NO Aceptada", callback_data=f"delete_{request_to_delete['ticket']}_not_accepted")],
        [InlineKeyboardButton("✅ 2 - Subida", callback_data=f"delete_{request_to_delete['ticket']}_uploaded")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🗑️ **Eliminar Solicitud - Ticket #{request_to_delete['ticket']}** 🛠️\n"
        f"👤 @{username}\n"
        f"📝 Mensaje: {request_to_delete['message']}\n"
        f"🏠 Grupo: {request_to_delete['group_name']}\n"
        f"🌐 Fuente: EntresHijos\n"
        f"🕒 Fecha: {request_to_delete['date']}\n\n"
        f"¿Qué hacemos con esta solicitud? 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Manejar las acciones de los botones
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    ticket = int(action.split("_")[1])
    status = action.split("_")[2]

    data = load_requests()
    request_to_delete = None
    for req in data["requests"]:
        if req["ticket"] == ticket:
            request_to_delete = req
            break

    if not request_to_delete:
        await query.edit_message_text("❌ ¡Ups! Esa solicitud ya no existe. 😅")
        return

    data["requests"] = [req for req in data["requests"] if req["ticket"] != ticket]
    save_requests(data)

    status_message = "🚫 Petición NO Aceptada" if status == "not_accepted" else "✅ Petición Subida"
    await context.bot.send_message(
        chat_id=request_to_delete["group_id"],
        text=(
            f"📢 **Actualización de Solicitud** 📩\n"
            f"👤 @{request_to_delete['username']}\n"
            f"🎟️ **Ticket #{ticket}**\n"
            f"📝 Mensaje: {request_to_delete['message']}\n"
            f"🏠 Grupo: {request_to_delete['group_name']}\n"
            f"🌐 Fuente: EntresHijos\n"
            f"{status_message}\n"
            f"¡Gracias por tu paciencia! 🙌"
        ),
        parse_mode="Markdown"
    )

    await query.edit_message_text(
        f"✅ **Solicitud Procesada** 🎉\n"
        f"👤 @{request_to_delete['username']}\n"
        f"🎟️ Ticket #{ticket}\n"
        f"📝 Mensaje: {request_to_delete['message']}\n"
        f"🏠 Grupo: {request_to_delete['group_name']}\n"
        f"🌐 Fuente: EntresHijos\n"
        f"{status_message}"
    )

# Comando /rs - Solo administradores
async def refresh_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    data = load_requests()
    await update.message.reply_text(
        "🔄 **¡Base de Datos Refrescada!** ✨\n"
        "✅ Todo está actualizado. Usa `/vp` para ver las solicitudes. 😊",
        parse_mode="Markdown"
    )

# Comando /menu - Solo administradores
async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    menu_text = (
        "📖 **Menú de Comandos - EntresHijos** 🌟\n\n"
        "👤 **Para todos:**\n"
        "🔹 `/solicito <mensaje>` - Envía una solicitud (máx. 2 por día, admins exentos en modo normal).\n\n"
        "👑 **Solo administradores:**\n"
        "🔹 `/vp` - Lista todas las solicitudes pendientes.\n"
        "🔹 `/bp @username` - Elimina una solicitud con opciones.\n"
        "🔹 `/rs` - Refresca la base de datos.\n"
        "🔹 `/stats` - Muestra estadísticas de solicitudes.\n"
        "🔹 `/priority @username` - Marca una solicitud como prioritaria.\n"
        "🔹 `/backup` - Descarga una copia de la base de datos.\n"
        "🔹 `/onp` - Activa modo prueba (límite para todos).\n"
        "🔹 `/ofp` - Desactiva modo prueba (vuelve a normal).\n"
        "🔹 `/menu` - Este menú.\n\n"
        "ℹ️ **Nota:** Solo admins pueden usar estos comandos aquí."
    )
    await update.message.reply_text(menu_text, parse_mode="Markdown")

# Comando /stats - Solo administradores
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

    await update.message.reply_text(
        f"📊 **Estadísticas - EntresHijos** 🌟\n\n"
        f"🔢 **Total de Solicitudes**: {total_requests}\n\n"
        f"🏡 **Por Grupo**:\n{group_stats}\n\n"
        f"👥 **Usuarios Más Activos (Top 3)**:\n{top_users}\n"
        f"¡Gracias por mantener todo en marcha! 🙌",
        parse_mode="Markdown"
    )

# Comando /priority - Solo administradores (con botones)
async def priority_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

    if not context.args or not context.args[0].startswith("@"):
        await update.message.reply_text("❌ ¡Hey! Usa: `/priority @username` para marcar una solicitud. 😊")
        return

    username = context.args[0][1:]
    data = load_requests()
    request_to_prioritize = None
    for req in data["requests"]:
        if req["username"] == username:
            request_to_prioritize = req
            break

    if not request_to_prioritize:
        await update.message.reply_text(f"❌ No hay solicitudes de @{username} para priorizar. 🤔")
        return

    keyboard = [
        [InlineKeyboardButton("🔥 Sí, Marcar como Prioridad", callback_data=f"priority_{request_to_prioritize['ticket']}_yes")],
        [InlineKeyboardButton("❌ No, Cancelar", callback_data=f"priority_{request_to_prioritize['ticket']}_no")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🔍 **Marcar como Prioridad - Ticket #{request_to_prioritize['ticket']}** ✨\n"
        f"👤 @{username}\n"
        f"📝 Mensaje: {request_to_prioritize['message']}\n"
        f"🏠 Grupo: {request_to_prioritize['group_name']}\n"
        f"🌐 Fuente: EntresHijos\n"
        f"🕒 Fecha: {request_to_prioritize['date']}\n\n"
        f"¿Quieres marcar esta solicitud como prioritaria? 👇",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Manejar botones de prioridad
async def priority_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action = query.data
    ticket = int(action.split("_")[1])
    choice = action.split("_")[2]

    data = load_requests()
    request_to_prioritize = None
    for req in data["requests"]:
        if req["ticket"] == ticket:
            request_to_prioritize = req
            break

    if not request_to_prioritize:
        await query.edit_message_text("❌ ¡Ups! Esa solicitud ya no existe. 😅")
        return

    if choice == "yes":
        request_to_prioritize["priority"] = True
        save_requests(data)
        await query.edit_message_text(
            f"✅ **Prioridad Activada** 🔥\n"
            f"👤 @{request_to_prioritize['username']}\n"
            f"🎟️ Ticket #{ticket}\n"
            f"📝 Mensaje: {request_to_prioritize['message']}\n"
            f"🏠 Grupo: {request_to_prioritize['group_name']}\n"
            f"🌐 Fuente: EntresHijos\n"
            f"¡Marcada como prioritaria con éxito! 🙌"
        )
    else:
        await query.edit_message_text("❌ Operación cancelada. La solicitud sigue sin prioridad. 😊")

# Comando /backup - Solo administradores
async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return

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
    os.remove(backup_file)  # Eliminar archivo temporal

# Función principal
def main():
    application = Application.builder().token(TOKEN).build()

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

    application.add_handler(CallbackQueryHandler(button_handler, pattern="^delete_"))
    application.add_handler(CallbackQueryHandler(priority_button_handler, pattern="^priority_"))

    application.run_polling()

if __name__ == "__main__":
    main().