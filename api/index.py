import os, json, requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT  = os.getenv("TG_CHAT", "")
APP_NAME = os.getenv("APP_NAME", "SC Tips • Pull Analyzer")

app = Flask(__name__)
CORS(app)

# ======= Estratégias básicas de exemplo =======
def estrategias_basicas(ultimo):
    puxam = {
        0:[26,32,15,3,19],
        1:[33,20,14,31,9],
        2:[17,25,21,4,15],
        3:[26,35,0,12,19],
        4:[19,21,36,16,2],
        5:[10,24,30,33,27],
        6:[34,9,29,17,11],
        7:[28,18,22,13,29],
        8:[30,23,10,11,23],
        9:[31,22,33,18,6],
    }
    return puxam.get(ultimo, [])

# ======= IA principal =======
@app.post("/api/suggest")
def suggest():
    data = request.get_json(force=True)
    hist = data.get("history", [])
    auto_send = data.get("auto_send", False)
    roulette = data.get("roulette", "Immersive")

    if not hist:
        return jsonify({"error":"sem histórico"}),400

    ultimo = hist[-1]
    sugest = estrategias_basicas(ultimo)
    breakdown = {"basica": sugest}

    msg = f"🎯 <b>{APP_NAME}</b>\n🎡 Roleta: {roulette}\nÚltimo: <b>{ultimo}</b>\nSugestão: {', '.join(map(str, sugest))}"
    if auto_send and TG_TOKEN and TG_CHAT:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                json={"chat_id":TG_CHAT,"text":msg,"parse_mode":"HTML"},
                timeout=5
            )
        except Exception as e:
            print("Erro Telegram:", e)

    return jsonify({
        "ultimo": ultimo,
        "alvos": sugest,
        "breakdown": breakdown
    })

# ======= Proxy interno para evitar CORS =======
@app.get("/api/proxy")
def proxy():
    url = request.args.get("url")
    if not url:
        return jsonify({"error": "missing url"}), 400
    try:
        r = requests.get(url, timeout=8)
        try:
            return r.json()
        except Exception:
            return r.text, r.status_code, {"Content-Type": r.headers.get("Content-Type", "text/plain")}
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ======= Rotas front =======
@app.get("/")
def index_html():
    return send_from_directory("public", "index.html")

@app.get("/matrix-premium")
def matrix_html():
    return send_from_directory("public", "matrix-premium.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
