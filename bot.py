"""Bot de Telegram: recibe gastos en texto libre, pide confirmación, los guarda y responde /resumen."""

import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import db
from ai_extract import ErrorExtraccion, extraer_gasto

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
# La librería httpx loguea cada consulta a Telegram, y esas URLs llevan el token adentro.
# La silenciamos para que el token no quede impreso en la terminal ni en ningún log.
logging.getLogger("httpx").setLevel(logging.WARNING)

PREGUNTA = (
    "¿Guardo este gasto?\n\n"
    "💰 {monto}\n"
    "🏷 {categoria}\n"
    "📝 {descripcion}\n\n"
    "Si algo está mal, editá tu mensaje y lo recalculo."
)


# --- Gastos pendientes de confirmar -------------------------------------------------------
# Se guardan en la memoria del bot (context.chat_data), no en la base: hasta que el usuario
# toca "Confirmar" no son gastos de verdad. Si el bot se reinicia, los pendientes se pierden
# y hay que volver a mandar el mensaje.
#   pendientes: {id del mensaje del usuario: {"gasto": {...}, "respuesta_id": id del mensaje del bot}}
#   resueltos:  ids de mensajes ya confirmados o cancelados (para no procesarlos dos veces)

def pendientes(context):
    return context.chat_data.setdefault("pendientes", {})


def resueltos(context):
    return context.chat_data.setdefault("resueltos", set())


def texto_pregunta(gasto):
    return PREGUNTA.format(
        monto=db.formato_pesos(gasto["monto"]),
        categoria=gasto["categoria"],
        descripcion=gasto["descripcion"] or "-",
    )


def botones(mensaje_id):
    # callback_data es lo que Telegram nos devuelve cuando tocan el botón: "ok:123" o "no:123".
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Confirmar", callback_data=f"ok:{mensaje_id}"),
        InlineKeyboardButton("❌ Cancelar", callback_data=f"no:{mensaje_id}"),
    ]])


async def interpretar(texto):
    # db y ai_extract son funciones "lentas" (esperan a la red). asyncio.to_thread las corre
    # aparte para que el bot pueda seguir atendiendo otros mensajes mientras tanto.
    categorias = await asyncio.to_thread(db.obtener_categorias)
    return await asyncio.to_thread(extraer_gasto, texto, categorias)


async def proponer(mensaje, context):
    """Interpreta el mensaje y responde con la propuesta y los botones de confirmar/cancelar."""
    await context.bot.send_chat_action(mensaje.chat_id, ChatAction.TYPING)  # muestra "escribiendo..."
    try:
        gasto = await interpretar(mensaje.text)
    except ErrorExtraccion as e:
        await mensaje.reply_text(f"🤔 {e}")
        return
    respuesta = await mensaje.reply_text(texto_pregunta(gasto), reply_markup=botones(mensaje.message_id))
    pendientes(context)[mensaje.message_id] = {"gasto": gasto, "respuesta_id": respuesta.message_id}


# --- Handlers -----------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Mandame tus gastos en texto libre, por ejemplo:\n"
        "  • gasté 30000 en el super\n"
        "  • uber al laburo 4 mil\n\n"
        "Te muestro cómo lo entendí y lo guardo cuando toques ✅ Confirmar.\n"
        "Si me equivoqué, editá tu mensaje y lo recalculo.\n\n"
        "Con /resumen te muestro lo que gastaste en los últimos 7 días."
    )


async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    texto = await asyncio.to_thread(db.armar_resumen, update.effective_chat.id)
    await update.message.reply_text(texto)


async def nuevo_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await proponer(update.message, context)


async def mensaje_editado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """El usuario corrigió un mensaje ya enviado: recalculamos la propuesta."""
    mensaje = update.edited_message

    if mensaje.message_id in resueltos(context):
        await mensaje.reply_text(
            "Ese gasto ya estaba confirmado o cancelado, así que no cambié nada. "
            "Si querés cargar otro, mandá un mensaje nuevo."
        )
        return

    pendiente = pendientes(context).get(mensaje.message_id)
    if pendiente is None:
        # Nunca llegó a ser propuesta (por ejemplo decía "hola"): lo tratamos como mensaje nuevo.
        await proponer(mensaje, context)
        return

    try:
        gasto = await interpretar(mensaje.text)
    except ErrorExtraccion as e:
        del pendientes(context)[mensaje.message_id]
        await context.bot.edit_message_text(
            f"🤔 {e}", chat_id=mensaje.chat_id, message_id=pendiente["respuesta_id"]
        )
        return

    # Actualizamos la MISMA respuesta del bot, en lugar de mandar una nueva.
    pendiente["gasto"] = gasto
    await context.bot.edit_message_text(
        texto_pregunta(gasto),
        chat_id=mensaje.chat_id,
        message_id=pendiente["respuesta_id"],
        reply_markup=botones(mensaje.message_id),
    )


async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """El usuario tocó ✅ Confirmar o ❌ Cancelar."""
    consulta = update.callback_query
    accion, mensaje_id = consulta.data.split(":")
    mensaje_id = int(mensaje_id)

    # pop = sacarlo de pendientes en el mismo paso: si tocan "Confirmar" dos veces rápido,
    # el segundo toque ya no lo encuentra y el gasto no se guarda duplicado.
    pendiente = pendientes(context).pop(mensaje_id, None)
    if pendiente is None:
        await consulta.answer("Este gasto ya no está pendiente. Mandá el mensaje de nuevo.")
        await consulta.edit_message_reply_markup(reply_markup=None)
        return
    resueltos(context).add(mensaje_id)

    if accion == "ok":
        gasto = pendiente["gasto"]
        await asyncio.to_thread(
            db.guardar_gasto, consulta.message.chat_id,
            gasto["monto"], gasto["categoria"], gasto["descripcion"],
        )
        await consulta.edit_message_text(
            f"✅ Guardado: {db.formato_pesos(gasto['monto'])} en {gasto['categoria']}"
            f" ({gasto['descripcion']})"
        )
    else:
        await consulta.edit_message_text("❌ Cancelado. No se guardó nada.")
    await consulta.answer()  # le avisa a Telegram que procesamos el toque (saca el "cargando" del botón)


async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Cualquier error inesperado: lo anotamos en la terminal y avisamos al usuario."""
    logging.error("Error inesperado", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("😵 Algo falló de mi lado. Probá de nuevo en un rato.")


def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("resumen", resumen))
    # Mensajes nuevos y mensajes editados llegan como tipos de actualización distintos.
    app.add_handler(MessageHandler(filters.UpdateType.MESSAGE & filters.TEXT & ~filters.COMMAND, nuevo_mensaje))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED_MESSAGE & filters.TEXT & ~filters.COMMAND, mensaje_editado))
    app.add_handler(CallbackQueryHandler(boton, pattern=r"^(ok|no):\d+$"))
    app.add_error_handler(manejar_error)

    logging.info("Bot andando. Mandale un mensaje por Telegram. Ctrl+C para apagarlo.")
    app.run_polling()


if __name__ == "__main__":
    main()
