from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from signal_engine import scan_market

import schedule
import threading
import time

TOKEN = "8686664882:AAHRg3lQpcoWwEeCkAVrAB3YIF2-fskOqyc"

scanning = False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global scanning

    if scanning:
        await update.message.reply_text("⚠️ Сканер уже запущен")
        return

    scanning = True

    await update.message.reply_text(
        "🚀 Сканирование SPOT рынка Binance запущено!\n"
        "Бот проверяет все USDT пары каждые 15 минут."
    )

    def scanner_loop():

        schedule.every(15).minutes.do(scan_market)

        while scanning:
            schedule.run_pending()
            time.sleep(1)

    thread = threading.Thread(target=scanner_loop)
    thread.start()


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global scanning

    scanning = False

    await update.message.reply_text("⛔ Сканирование остановлено")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("📊 Проверка активных сигналов пока не реализована")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text("📜 История сигналов пока пустая")


app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("stop", stop))
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("history", history))

print("Бот запущен...")

app.run_polling()
