import asyncio

from telegram import Bot

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from database import init_db
from sources.ismea_market import (
    parse_ovicaprini,
    parse_lattiero_caseari,
)
from sources.sardegna_bandi import fetch_bandi
from engines.intelligence import report


def collect():
    prices = (
        parse_ovicaprini()
        + parse_lattiero_caseari()
    )
    grants = fetch_bandi()
    return prices, grants


async def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN non configurato")
        return

    if not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_CHAT_ID non configurato")
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    async with bot:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text=message,
        )


def main():
    init_db()

    prices, grants = collect()
    message = report(prices, grants)

    print(message)

    asyncio.run(send_telegram(message))


if __name__ == "__main__":
    main()