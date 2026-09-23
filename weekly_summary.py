"""Manda el resumen semanal a cada chat que cargó gastos en los últimos 7 días.

No corre dentro del bot: se ejecuta una vez y termina. La idea es que lo dispare
un programador de tareas (GitHub Actions, cron, Programador de tareas de Windows),
por ejemplo todos los lunes a la mañana, sin que nadie lo ejecute a mano.
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

import db

load_dotenv()
logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # no imprimir URLs con el token


async def main():
    chats = db.chats_activos()
    logging.info("Chats con gastos esta semana: %d", len(chats))

    enviados = 0
    async with Bot(os.environ["TELEGRAM_TOKEN"]) as bot:
        for chat_id in chats:
            texto = "🗓️ Resumen semanal automático\n\n" + db.armar_resumen(chat_id)
            try:
                await bot.send_message(chat_id, texto)
                enviados += 1
            except TelegramError as e:
                # Por ejemplo, si alguien bloqueó el bot. Seguimos con los demás chats.
                logging.warning("No pude enviarle a %s: %s", chat_id, e)

    logging.info("Resúmenes enviados: %d de %d", enviados, len(chats))


if __name__ == "__main__":
    asyncio.run(main())
