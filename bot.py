"""Bot de Telegram: recibe gastos en texto libre, los guarda en la base y responde /resumen."""

import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

import db
from ai_extract import ErrorExtraccion, extraer_gasto

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
# La librería httpx loguea cada consulta a Telegram, y esas URLs llevan el token adentro.
# La silenciamos para que el token no quede impreso en la terminal ni en ningún log.
logging.getLogger("httpx").setLevel(logging.WARNING)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Mandame tus gastos en texto libre, por ejemplo:\n"
        "  • gasté 30000 en el super\n"
        "  • uber al laburo 4 mil\n\n"
        "Con /resumen te muestro lo que gastaste en los últimos 7 días."
    )


async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # db y ai_extract son funciones "lentas" (esperan a la red). asyncio.to_thread las corre
    # aparte para que el bot pueda seguir atendiendo otros mensajes mientras tanto.
    texto = await asyncio.to_thread(db.armar_resumen, update.effective_chat.id)
    await update.message.reply_text(texto)


async def registrar_gasto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)  # muestra "escribiendo..."

    try:
        categorias = await asyncio.to_thread(db.obtener_categorias)
        gasto = await asyncio.to_thread(extraer_gasto, update.message.text, categorias)
    except ErrorExtraccion as e:
        await update.message.reply_text(f"🤔 {e}")
        return

    await asyncio.to_thread(
        db.guardar_gasto, chat_id, gasto["monto"], gasto["categoria"], gasto["descripcion"]
    )
    await update.message.reply_text(
        f"✅ Guardado: {db.formato_pesos(gasto['monto'])} en {gasto['categoria']}"
        f" ({gasto['descripcion']})"
    )


async def manejar_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Cualquier error inesperado: lo anotamos en la terminal y avisamos al usuario."""
    logging.error("Error inesperado", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("😵 Algo falló de mi lado. Probá de nuevo en un rato.")


def main():
    app = Application.builder().token(os.environ["TELEGRAM_TOKEN"]).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("resumen", resumen))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, registrar_gasto))
    app.add_error_handler(manejar_error)

    logging.info("Bot andando. Mandale un mensaje por Telegram. Ctrl+C para apagarlo.")
    app.run_polling()


if __name__ == "__main__":
    main()
