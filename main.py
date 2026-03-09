import os
import json
import asyncio
import requests
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import BollingerBands
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue

# ──────────────────────────────────────────────────────────────────
#  ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ──────────────────────────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# ──────────────────────────────────────────────────────────────────
#  BINANCE REST API — без python-binance, только requests
# ──────────────────────────────────────────────────────────────────
BINANCE_URL = "https://api.binance.com"


def get_all_symbols() -> list:
    """Возвращает список всех активных USDT-пар."""
    r = requests.get(f"{BINANCE_URL}/api/v3/exchangeInfo", timeout=30)
    r.raise_for_status()
    return [
        s["symbol"]
        for s in r.json()["symbols"]
        if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
    ]


def get_klines(symbol: str, interval: str = "1h", limit: int = 100) -> list:
    """Возвращает свечи для указанного символа."""
    r = requests.get(
        f"{BINANCE_URL}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def get_ticker(symbol: str) -> dict:
    """Возвращает 24-часовую статистику по символу."""
    r = requests.get(
        f"{BINANCE_URL}/api/v3/ticker/24hr",
        params={"symbol": symbol},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ──────────────────────────────────────────────────────────────────
#  ЛОГИКА СКАНЕРА
# ──────────────────────────────────────────────────────────────────

def build_dataframe(klines: list) -> pd.DataFrame:
    """Строит DataFrame из сырых свечей Binance."""
    columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(klines, columns=columns)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col])
    return df


def check_signal(symbol: str) -> dict:
    """
    Проверяет одну монету на сигнал покупки.
    Условия:
      - RSI < 40
      - MACD-гистограмма > 0  (пересечение вверх)
      - Объём последней свечи > 2× средний объём
      - Цена выше EMA20
      - Цена отскочила от нижней полосы Боллинджера
    Возвращает dict с сигналом или None.
    """
    try:
        klines = get_klines(symbol, interval="1h", limit=100)
        if len(klines) < 30:
            return None

        df = build_dataframe(klines)

        # Технические индикаторы
        rsi_val   = RSIIndicator(df["close"]).rsi().iloc[-1]
        macd_diff = MACD(df["close"]).macd_diff().iloc[-1]
        bb_low    = BollingerBands(df["close"]).bollinger_lband().iloc[-1]
        ema20     = df["close"].ewm(span=20, adjust=False).mean().iloc[-1]

        last_close  = df["close"].iloc[-1]
        last_low    = df["low"].iloc[-1]
        last_volume = df["volume"].iloc[-1]
        avg_volume  = df["volume"].mean()

        if (
            rsi_val < 40
            and macd_diff > 0
            and last_volume > avg_volume * 2
            and last_close > ema20
            and last_low > bb_low
        ):
            ticker = get_ticker(symbol)
            return {
                "symbol":     symbol,
                "price":      last_close,
                "volume_24h": float(ticker.get("quoteVolume", 0)),
                "change_24h": float(ticker.get("priceChangePercent", 0)),
                "stop_loss":  round(last_close * 0.95, 8),
                "target":     round(last_close * 1.15, 8),
                "reason": (
                    "RSI < 40, MACD пересечение вверх, "
                    "объём > 2×среднего, цена выше EMA20, "
                    "отскок от нижней полосы Боллинджера"
                ),
            }
    except Exception:
        pass  # Пропускаем монеты с ошибками (делистинг, нет данных и т.д.)

    return None


def run_scan() -> list:
    """
    Синхронный полный скан всех USDT-пар.
    Вызывается через run_in_executor чтобы не блокировать бота.
    Возвращает список найденных сигналов.
    """
    symbols = get_all_symbols()
    signals = []
    for symbol in symbols:
        signal = check_signal(symbol)
        if signal:
            signals.append(signal)
            # Сохраняем каждый сигнал в файл
            with open("signals.json", "a", encoding="utf-8") as f:
                json.dump(signal, f, ensure_ascii=False)
                f.write("\n")
    return signals


# ──────────────────────────────────────────────────────────────────
#  TELEGRAM HANDLERS
# ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветственное сообщение."""
    await update.message.reply_text(
        "📊 *Бот для спотовой торговли на Binance*\n\n"
        "Сканирует все USDT-пары и ищет сигналы покупки.\n\n"
        "*Команды:*\n"
        "/scan — запустить сканер прямо сейчас\n"
        "/status — последние 5 сигналов\n"
        "/history — последние 10 сигналов\n"
        "/stop — остановить автосканер",
        parse_mode="Markdown",
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Останавливает фоновый автосканер."""
    jobs = context.job_queue.get_jobs_by_name("auto_scan")
    for job in jobs:
        job.schedule_removal()
    count = len(jobs)
    if count:
        await update.message.reply_text(f"🛑 Автосканер остановлен.")
    else:
        await update.message.reply_text("ℹ️ Автосканер не был запущен.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает последние 5 сигналов."""
    try:
        with open("signals.json", "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            await update.message.reply_text("ℹ️ Сигналов ещё не было.")
            return
        recent = [json.loads(l) for l in lines[-5:]]
        text = "📋 *Последние сигналы:*\n\n"
        for s in recent:
            text += (
                f"🟢 *{s['symbol']}* — `{s['price']}`\n"
                f"   Стоп: `{s['stop_loss']}` | Цель: `{s['target']}`\n\n"
            )
        await update.message.reply_text(text, parse_mode="Markdown")
    except FileNotFoundError:
        await update.message.reply_text("ℹ️ Сигналов ещё не было.")


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает последние 10 сигналов."""
    try:
        with open("signals.json", "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines:
            await update.message.reply_text("ℹ️ История пуста.")
            return
        recent = [json.loads(l) for l in lines[-10:]]
        text = "📜 *История сигналов (последние 10):*\n\n"
        for s in recent:
            text += (
                f"• *{s['symbol']}* — вход: `{s['price']}`\n"
                f"  Стоп: `{s['stop_loss']}` | Цель: `{s['target']}`\n"
            )
        await update.message.reply_text(text, parse_mode="Markdown")
    except FileNotFoundError:
        await update.message.reply_text("ℹ️ История пуста.")


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запускает сканер вручную по команде /scan."""
    await update.message.reply_text(
        "🔍 Запускаю сканер всех USDT-пар... Это займёт 1–3 минуты."
    )
    loop = asyncio.get_event_loop()
    try:
        # run_in_executor — синхронный скан не блокирует event loop бота
        signals = await loop.run_in_executor(None, run_scan)
    except Exception as exc:
        await update.message.reply_text(f"❌ Ошибка сканера:\n{exc}")
        return

    if not signals:
        await update.message.reply_text("😶 Сигналов не найдено.")
        return

    for s in signals:
        await update.message.reply_text(
            f"🟢 *СИГНАЛ ПОКУПКИ (СПОТ)*\n\n"
            f"Монета: `{s['symbol']}`\n"
            f"Цена входа: `{s['price']}`\n"
            f"Стоп-лосс: `{s['stop_loss']}` (−5%)\n"
            f"Цель: `{s['target']}` (+15%)\n"
            f"Объём 24ч: `{s['volume_24h']:,.0f} USDT`\n"
            f"Изменение 24ч: `{s['change_24h']}%`\n\n"
            f"📌 *Причина:* {s['reason']}",
            parse_mode="Markdown",
        )


# ──────────────────────────────────────────────────────────────────
#  АВТОСКАНИРОВАНИЕ КАЖДЫЕ 15 МИНУТ (JobQueue)
# ──────────────────────────────────────────────────────────────────

async def auto_scan_job(context) -> None:
    """
    Фоновая задача — каждые 15 минут.
    Результаты шлёт в чат если задана переменная CHAT_ID.
    """
    chat_id = os.environ.get("CHAT_ID")
    if not chat_id:
        return

    loop = asyncio.get_event_loop()
    try:
        signals = await loop.run_in_executor(None, run_scan)
    except Exception as exc:
        await context.bot.send_message(
            chat_id=chat_id, text=f"❌ Ошибка автоскана:\n{exc}"
        )
        return

    for s in signals:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🟢 *СИГНАЛ ПОКУПКИ (СПОТ)*\n\n"
                f"Монета: `{s['symbol']}`\n"
                f"Цена входа: `{s['price']}`\n"
                f"Стоп-лосс: `{s['stop_loss']}` (−5%)\n"
                f"Цель: `{s['target']}` (+15%)\n\n"
                f"📌 {s['reason']}"
            ),
            parse_mode="Markdown",
        )


# ──────────────────────────────────────────────────────────────────
#  ТОЧКА ВХОДА
# ──────────────────────────────────────────────────────────────────

def main() -> None:
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .job_queue(JobQueue())
        .build()
    )

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("stop",    stop))
    app.add_handler(CommandHandler("status",  status))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("scan",    scan))

    # Автосканирование каждые 15 минут через встроенный JobQueue
    app.job_queue.run_repeating(
        auto_scan_job,
        interval=15 * 60,   # каждые 15 минут
        first=60,           # первый запуск через 60 секунд после старта
        name="auto_scan",
    )

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
