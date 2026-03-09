import os
from python_binance import Client
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands
from ta.indicators import ema
from python_telegram_bot import ApplicationBuilder, CommandHandler, filters
import json
import asyncio

TOKEN = os.environ.get("TELEGRAM_TOKEN")
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY")
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET")

client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

async def start(update, context):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Бот для спотовой торговли на Binance. Сканнер запускается каждые 15 минут.")

async def stop(update, context):
    # TODO: реализовать остановку сканера
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Сканер остановлен.")

async def status(update, context):
    # TODO: реализовать показ активных сигналов
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Активные сигналы: ")

async def history(update, context):
    # TODO: реализовать показ последних 10 сигналов
    await context.bot.send_message(chat_id=update.effective_chat.id, text="История сигналов: ")

async def scan(update, context):
    try:
        symbols = client.get_all_tickers()
        for symbol in symbols:
            if symbol["symbol"].endswith("USDT") and float(symbol["price"]) > 0.00001:
                klines = client.get_klines(symbol=symbol["symbol"], interval="1h", limit=24)
                df = pd.DataFrame(klines, columns=["Open time", "Open", "High", "Low", "Close", "Volume", "Close time", "Quote asset volume", "Number of trades", "Taker buy base asset volume", "Taker buy quote asset volume", "Can be ignored"])
                df["Close"] = pd.to_numeric(df["Close"])
                df["Low"] = pd.to_numeric(df["Low"])
                df["High"] = pd.to_numeric(df["High"])
                df["Volume"] = pd.to_numeric(df["Volume"])

                rsi = RSIIndicator(df["Close"])
                macd = MACD(df["Close"])
                bb = BollingerBands(df["Close"])
                ema20 = ema(df["Close"], window=20)

                if (rsi.rsi() < 40 and 
                    macd.macd_diff() > 0 and 
                    df["Volume"].iloc[-1] > df["Volume"].mean() * 2 and 
                    df["Close"].iloc[-1] > ema20[-1] and 
                    df["Low"].iloc[-1] > bb.bollinger_lband()[-1]):
                    signal = {
                        "symbol": symbol["symbol"],
                        "price": df["Close"].iloc[-1],
                        "reason": "RSI < 40, MACD пересечение вверх, объём > 2*среднего, цена выше EMA20, цена отскочила от нижней полосы Боллинджера"
                    }
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=f"🟢 СИГНАЛ ПОКУПКИ (СПОТ)\nМонета: {symbol['symbol']}\nЦена входа: {df['Close'].iloc[-1]}\nСтоп-лосс: {df['Close'].iloc[-1] * 0.95}\nЦель: {df['Close'].iloc[-1] * 1.15}\nПричина: {signal['reason']}")
                    with open("signals.json", "a") as f:
                        json.dump(signal, f)
                        f.write("\n")
    except Exception as e:
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"Ошибка сканера: {str(e)}")

async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("history", history))
    await app.start()
    await asyncio.sleep(15 * 60)
    await scan(None, None)
    await app.stop()

if __name__ == "__main__":
    asyncio.run(main())