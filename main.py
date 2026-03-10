import requests
import time
import threading
from flask import Flask, request

TOKEN = "8686664882:AAHRg3lQpcoWwEeCkAVrAB3YIF2-fskOqyc"
CHAT_ID = "750202787"

BINANCE = "https://api.binance.com/api/v3/ticker/24hr"

app = Flask(__name__)

scanner_running = False
history = []
active_signals = []

# -------- TELEGRAM --------

def send(text):

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": text
    }

    requests.post(url, data=data)

# -------- COMMANDS --------

def handle_command(cmd):

    global scanner_running

    if cmd == "/start":

        send(
"""🤖 Binance SPOT Trading Bot

Команды:
/scan — запустить сканирование
/stop — остановить сканирование
/status — статус бота
/history — история сигналов
/active — активные сигналы
/ping — проверка бота"""
)

    elif cmd == "/scan":

        scanner_running = True
        send("🔍 Сканирование рынка запущено")

    elif cmd == "/stop":

        scanner_running = False
        send("⛔ Сканирование остановлено")

    elif cmd == "/status":

        status = "ON" if scanner_running else "OFF"

        send(f"📊 Scanner status: {status}")

    elif cmd == "/history":

        if not history:
            send("История сигналов пустая")
        else:

            msg = "📈 Последние сигналы\n\n"

            for h in history[-5:]:
                msg += h + "\n"

            send(msg)

    elif cmd == "/active":

        if not active_signals:
            send("Активных сигналов нет")
        else:

            msg = "🔥 Активные сигналы\n\n"

            for s in active_signals:
                msg += s + "\n"

            send(msg)

    elif cmd == "/ping":

        send("🏓 Bot alive")

# -------- MARKET SCANNER --------

def scan_market():

    global active_signals

    while True:

        if scanner_running:

            try:

                data = requests.get(BINANCE).json()

                signals = []

                for coin in data:

                    symbol = coin["symbol"]

                    if not symbol.endswith("USDT"):
                        continue

                    volume = float(coin["quoteVolume"])
                    change = float(coin["priceChangePercent"])

                    if volume > 5000000 and change > 4:

                        signals.append((symbol, change))

                signals = sorted(signals, key=lambda x: x[1], reverse=True)[:2]

                for s in signals:

                    text = f"🔥 BUY SIGNAL\n\n{s[0]} +{round(s[1],2)}%"

                    if s[0] not in active_signals:

                        active_signals.append(s[0])
                        history.append(s[0])

                        send(text)

                time.sleep(900)

            except:

                time.sleep(60)

        else:

            time.sleep(10)

# -------- TELEGRAM WEBHOOK --------

@app.route("/", methods=["POST"])
def webhook():

    data = request.json

    if "message" in data:

        text = data["message"].get("text")

        if text and text.startswith("/"):

            handle_command(text)

    return "ok"

# -------- START --------

threading.Thread(target=scan_market).start()

if __name__ == "__main__":

    app.run(host="0.0.0.0", port=10000)
