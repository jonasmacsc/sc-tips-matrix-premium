import os, time, threading, requests, json
from flask import Flask, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from datetime import datetime

# ============= CONFIGURAÇÕES =============
load_dotenv()
TG_TOKEN = os.getenv("TG_TOKEN", "7317597605:AAHzvSTxLSIuiyXxvnN9MILaB1FlpHXeEcM")
TG_CHAT  = os.getenv("TG_CHAT", "-1001483425201")

# APIs oficiais CasinoScores
SOURCES = {
    "immersive": "https://api.casinoscores.com/svc-evolution-game-events/api/immersiveroulette?page=0&size=40&sort=data.settledAt,desc&duration=6",
    "brazilian": "https://api.casinoscores.com/svc-pragmatic-game-events/api/brazilianroulette?page=0&size=40&sort=data.settledAt,desc&duration=6",
    "megafire":  "https://api.casinoscores.com/svc-evolution-game-events/api/megafireblazeroulette?page=0&size=40&sort=data.settledAt,desc&duration=6"
}

INTERVALS = [12, 18, 60]  # segundos entre cada checagem
HISTORY = {k: [] for k in SOURCES.keys()}
LOCK = threading.Lock()

# ============= APP BASE =============
app = Flask(__name__)
CORS(app)

# ============= FUNÇÕES =============
def send_telegram(msg):
    try:
        requests.get(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            params={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"⚠️ Erro ao enviar Telegram: {e}")

def fetch_results(source):
    url = SOURCES[source]
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            content = data.get("content", [])
            numbers = []
            for g in content:
                result = g.get("result", {})
                num = result.get("value")
                color = result.get("color", "").capitalize()
                when = g.get("data", {}).get("settledAt", "")
                if num is not None:
                    numbers.append({"number": num, "color": color, "settledAt": when})
            return numbers
        else:
            print(f"Erro {r.status_code} - {source}")
    except Exception as e:
        print(f"Erro {source}: {e}")
    return []

def check_new_numbers():
    while True:
        for source in SOURCES:
            new_data = fetch_results(source)
            if not new_data:
                continue

            with LOCK:
                old_numbers = [x["number"] for x in HISTORY[source]]
                latest = new_data[0]["number"]

                if latest not in old_numbers:
                    HISTORY[source] = new_data[:50]
                    color = new_data[0]["color"]
                    settled_at = new_data[0]["settledAt"]
                    hora = datetime.now().strftime("%H:%M:%S")

                    msg = f"🎯 <b>{source.upper()}</b> • {hora}\n🎡 Número: <b>{latest}</b> ({color})"
                    print(msg)
                    send_telegram(msg)
        time.sleep(12)  # intervalo padrão entre as checagens

# ============= ROTAS =============
@app.route("/")
def home():
    return jsonify({
        "status": "✅ SC Tips Matrix Premium Ativo!",
        "roletas": list(SOURCES.keys()),
        "intervalos": INTERVALS
    })

@app.route("/api/results/<source>")
def api_results(source):
    if source not in SOURCES:
        return jsonify({"error": "Roleta inválida"}), 400
    results = fetch_results(source)
    return jsonify(results[:50])

# ============= THREAD =============
threading.Thread(target=check_new_numbers, daemon=True).start()

# ============= MAIN =============
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 SC Tips Matrix Premium rodando na porta {port}")
    app.run(host="0.0.0.0", port=port)
