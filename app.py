# SC Tips • Vem e Vê SC — RealPrecision v3.6 (Top-12 Agressivo, SmartLoop 18s, 3 roletas, 23+ estratégias)
# Requisitos: pip install -r requirements.txt
import os, time, threading, requests, json
from collections import deque, Counter, defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify
from flask_cors import CORS

# ===================== CONFIG =====================
TG_TOKEN = os.getenv("TG_TOKEN", "7317597605:AAHzvSTxLSIuiyXxvnN9MILaB1FlpHXeEcM")
TG_CHAT  = os.getenv("TG_CHAT",  "-1001483425201")

SOURCES = {
    "immersive": "https://api.casinoscores.com/svc-evolution-game-events/api/immersiveroulette?page=0&size=60&sort=data.settledAt,desc&duration=6",
    "brazilian": "https://api.casinoscores.com/svc-pragmatic-game-events/api/brazilianroulette?page=0&size=60&sort=data.settledAt,desc&duration=6",
    "megafire":  "https://api.casinoscores.com/svc-evolution-game-events/api/megafireblazeroulette?page=0&size=60&sort=data.settledAt,desc&duration=6",
}

SMART_LOOP_SECS = int(os.getenv("SMART_LOOP_SECS", "18"))
POLL_SECS       = int(os.getenv("POLL_SECS", "3"))

MAX_HISTORY = int(os.getenv("MAX_HISTORY", "500"))
EVAL_WINDOW = int(os.getenv("EVAL_WINDOW", "300"))  # janela maior p/ modo agressivo

ENTRY_SIZE     = int(os.getenv("ENTRY_SIZE", "12"))  # Top-12 agressivo
MIN_CONF_SEND  = int(os.getenv("MIN_CONF_SEND", "80"))

FIXOS = [0,10,20,30,36]

BR_TZ  = ZoneInfo("America/Sao_Paulo")
UTC_TZ = ZoneInfo("UTC")

# ===================== ESTADO =====================
HISTORY = {k: deque(maxlen=MAX_HISTORY) for k in SOURCES}     # [{'n':int,'c':str,'br':str}]
LAST_SIGNAL = {k: None for k in SOURCES}                      # sinal pendente p/ avaliar na próxima rodada
SCORES = {k: {"green": 0, "red": 0} for k in SOURCES}         # placar por roleta
LOCK = threading.Lock()

# ===================== DADOS DA ROLETA =====================
EURO_WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
RED   = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK = set(range(1,37)) - RED

# Secret Pull Table (extensível)
SECRET_PULLS = {
  0:[19,6,24,28,8], 1:[11,26,17,7], 2:[22,8,24], 3:[8,20], 4:[7,17,27,14],
  5:[34,1,35], 6:[4,14], 7:[27,23,4,20], 8:[3], 9:[1],
  10:[21,7,22], 11:[8,14,19], 12:[11,6,21,7], 13:[10,29,31], 14:[17,0],
  15:[20,27,28], 16:[2,7,29,11], 17:[1,3], 18:[3], 19:[4,14,16,27,22],
  20:[10,27,15,28], 21:[4,12,14,16,27], 22:[11,25,24,23,7], 23:[27,20,4,7],
  24:[22,26,11,2], 25:[22,27,29], 26:[1,6], 27:[20,4,7], 28:[3,20],
  29:[1,10,13,26], 30:[22,25], 31:[5,13], 32:[0,8,16,34,28],
  33:[34,0,3,22,11], 34:[33,31,0,4], 35:[6,31,7], 36:[1,35,21,19]
}

# ===================== APP =====================
app = Flask(__name__)
CORS(app)

# ===================== HELPERS =====================
def to_br_time_str(dt_utc: datetime | None = None) -> str:
    if dt_utc is None:
        dt_utc = datetime.now(UTC_TZ)
    return dt_utc.astimezone(BR_TZ).strftime("%Y-%m-%d %H:%M:%S")

def send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text},
            timeout=10
        )
    except Exception as e:
        print("send_telegram error:", e)

def true_neighbors(num, dist=1):
    if num not in EURO_WHEEL:
        return []
    i = EURO_WHEEL.index(num)
    seq = []
    for d in range(-dist, dist+1):
        seq.append(EURO_WHEEL[(i+d) % len(EURO_WHEEL)])
    return sorted(set(seq))

def terminal_group(n):
    if n is None: return []
    t = n % 10
    arr = list(range(t, 37, 10))
    if t == 0 and 0 not in arr:
        arr.append(0)
    return arr

def fetch_results(source):
    url = SOURCES[source]
    try:
        r = requests.get(url, headers={"User-Agent":"SC-Tips/3.6"}, timeout=10)
        if r.status_code != 200:
            print(f"Erro {r.status_code} - {source}")
            return []
        data = r.json()
        content = data.get("content", [])
        out = []
        for g in content:
            res   = g.get("result", {})
            num   = res.get("value")
            color = (res.get("color") or "").capitalize()
            settled_raw = (g.get("data") or {}).get("settledAt")
            if settled_raw:
                try:
                    dt_utc = datetime.fromisoformat(settled_raw.replace("Z", "+00:00"))
                except Exception:
                    dt_utc = datetime.now(UTC_TZ)
            else:
                dt_utc = datetime.now(UTC_TZ)
            br = to_br_time_str(dt_utc)
            if isinstance(num, int) and 0 <= num <= 36:
                out.append({"n": num, "c": color, "br": br})
        return out
    except Exception as e:
        print("fetch_results error:", e)
        return []

# ===================== ESTATÍSTICA / IA =====================
def last_window(history_deque, k):
    return list(history_deque)[-k:]

def freq_top(history_deque, k=EVAL_WINDOW, top=10):
    arr = last_window(history_deque, k)
    nums = [x["n"] for x in arr]
    cnt = Counter(nums)
    return [n for n,_ in cnt.most_common(top)]

def transition_after(history_deque, last_n, k=EVAL_WINDOW, top=10):
    arr = last_window(history_deque, k)
    pairs = defaultdict(int)
    for i in range(1, len(arr)):
        prev_n = arr[i-1]["n"]
        cur_n  = arr[i]["n"]
        if prev_n == last_n:
            pairs[cur_n] += 1
    return [n for n,_ in Counter(pairs).most_common(top)]

def confidence(entries, history_deque, k=EVAL_WINDOW):
    arr = last_window(history_deque, k)
    if not arr: return 50
    nums = [x["n"] for x in arr]
    hits = sum(1 for n in nums if n in entries)
    conf = int(round(100 * hits / max(1, len(nums))))
    return max(30, min(99, conf))

def expand_entries(entries, last, hist, target=ENTRY_SIZE):
    """Garante Top-N sem repetição: quentes, vizinhos, terminais, secret pulls."""
    out = list(entries)[:]
    seen = set(out)
    pool = []
    pool += [n for n in freq_top(hist, top=37) if n not in seen]
    pool += [n for n in true_neighbors(last, 2) if n not in seen]
    pool += [n for n in terminal_group(last) if n not in seen]
    pool += [n for n in SECRET_PULLS.get(last, []) if n not in seen]
    pool += [n for n in range(37) if n not in seen]
    out = list(dict.fromkeys(out + pool))[:target]
    return out

# ===================== ESTRATÉGIAS (23 + novas) =====================
def strat_ia_top5(last, hist):
    seq = transition_after(hist, last, top=5)
    if len(seq) < 5:
        extra = [n for n in freq_top(hist, top=10) if n not in seq]
        seq = (seq + extra)[:5]
    return "IA Top 5", seq, confidence(seq, hist)

def strat_fire_precision(last, hist):
    hot = freq_top(hist, top=10)
    seq = sorted(set(true_neighbors(last,2) + terminal_group(last) + hot[:6]))
    return "Fire Precision", seq[:10], min(99, confidence(seq, hist)+4)

def strat_pattern_breaker(last, hist):
    seq = sorted({last, (last+7)%37, (last+14)%37, (last+21)%37, (last+28)%37})
    return "Pattern Breaker", seq, confidence(seq, hist)

def strat_viz1(last, hist):
    seq = true_neighbors(last,1)
    return "Vizinhos 1", seq, confidence(seq, hist)

def strat_viz2(last, hist):
    seq = true_neighbors(last,2)
    return "Vizinhos 2", seq, confidence(seq, hist)

def strat_viz3(last, hist):
    seq = true_neighbors(last,3)
    return "Vizinhos 3", seq, confidence(seq, hist)

def strat_tiro_seco(last, hist):
    top1 = transition_after(hist, last, top=1) or [last]
    seq = list(top1)
    return "Tiro Seco", seq, max(40, confidence(seq, hist)-3)

def strat_linha_finais(last, hist):
    seq = [n for n in range(37) if n % 10 == (last % 10)]
    return "Linha dos Finais", seq, confidence(seq, hist)

def strat_term_v4(last, hist):
    seq = sorted(set(terminal_group(last) + true_neighbors(last,1)))
    return "Terminais v4", seq, min(98, confidence(seq, hist)+2)

def strat_term_secret(last, hist):
    seq = sorted(set(SECRET_PULLS.get(last, []) + true_neighbors(last,1)))
    return "Terminais Secretos", seq, min(98, confidence(seq, hist)+3)

def strat_term_duplo(last, hist):
    arr = last_window(hist, 2)
    a = arr[-1]["n"] if arr else last
    b = arr[-2]["n"] if len(arr) >= 2 else last
    seq = sorted(set(terminal_group(a) + terminal_group(b) + true_neighbors(a,1) + true_neighbors(b,1)))
    return "Terminais Duplos", seq[:18], confidence(seq, hist)

def strat_term_finais(last, hist):
    t = last % 10
    t2 = (t+1) % 10
    seq = sorted(set(list(range(t,37,10)) + list(range(t2,37,10))))
    return "Terminais dos Finais", seq, confidence(seq, hist)

def strat_term_prog(last, hist):
    seen = set((x["n"] % 10) for x in last_window(hist, 50))
    seq = []
    for d in range(10):
        if d not in seen:
            seq += list(range(d,37,10))
    seq = sorted(set(seq))
    return "Terminais Progressivos", seq[:18], confidence(seq, hist)

def strat_formula5x(last, hist):
    seq = sorted({last,(last+3)%37,(last+6)%37,(last+9)%37,(last+12)%37})
    return "Fórmula 5X", seq, confidence(seq, hist)

def strat_alpha6(last, hist):
    seq = freq_top(hist, top=6)
    return "Alpha 6", seq, min(99, confidence(seq, hist)+2)

def strat_quarta_dimensao(last, hist):
    a = true_neighbors(last,2)
    col = []
    if last != 0:
        r = last % 3
        col = [x for x in range(1,37) if x % 3 == (r if r!=0 else 3)%3]
    target_color = BLACK if last in RED else (RED if last in BLACK else set())
    seq = sorted(set(a + col[:12] + list(target_color)))
    return "Quarta Dimensão", seq[:18], min(99, confidence(seq, hist)+1)

def strat_cavalos_147(last, hist):
    base = [1,4,7,21,24,27,31,34]
    seq = sorted(set(base + FIXOS))
    return "Cavalo 147", seq, confidence(seq, hist)

def strat_cavalos_258(last, hist):
    base = [2,5,8,12,15,18,22,25,28,32,35]
    seq = sorted(set(base + FIXOS))
    return "Cavalo 258", seq, confidence(seq, hist)

def strat_cavalos_369(last, hist):
    base = [3,6,9,13,16,19,23,26,29,33,36]
    seq = sorted(set(base + FIXOS))
    return "Cavalo 369", seq, confidence(seq, hist)

def strat_setor_par(last, hist):
    seq = [n for n in range(37) if n % 2 == 0]
    return "Setor Par", seq, confidence(seq, hist)

def strat_setor_impar(last, hist):
    seq = [n for n in range(37) if n % 2 == 1]
    return "Setor Ímpar", seq, confidence(seq, hist)

def strat_black_bias(last, hist):
    hot = freq_top(hist, top=12)
    seq = [n for n in hot if n in BLACK][:6] or hot[:6]
    return "Black Bias", seq, confidence(seq, hist)

def strat_red_bias(last, hist):
    hot = freq_top(hist, top=12)
    seq = [n for n in hot if n in RED][:6] or hot[:6]
    return "Red Bias", seq, confidence(seq, hist)

def strat_duzia_quente(last, hist):
    arr = last_window(hist, EVAL_WINDOW)
    buckets = {1:0,2:0,3:0}
    for x in arr:
        n = x["n"]
        if n==0: continue
        b = 1 if n<=12 else (2 if n<=24 else 3)
        buckets[b]+=1
    best = max(buckets, key=buckets.get)
    if best == 1: seq = list(range(1,13))
    elif best == 2: seq = list(range(13,25))
    else: seq = list(range(25,37))
    return "Dúzia Quente", seq, confidence(seq, hist)

def strat_coluna_quente(last, hist):
    cols = {1:0,2:0,3:0}
    for x in last_window(hist, EVAL_WINDOW):
        n = x["n"]
        if n==0: continue
        c = 1 + ((n-1)%3)
        cols[c]+=1
    best = max(cols, key=cols.get)
    seq = [n for n in range(1,37) if 1+((n-1)%3)==best]
    return "Coluna Quente", seq, confidence(seq, hist)

def strat_setor_12x(last, hist):
    seq = freq_top(hist, top=12)
    return "Setor 12X", seq, confidence(seq, hist)

def strat_pull_table(last, hist):
    arr = last_window(hist, 3)
    candidates = []
    for x in arr:
        candidates += transition_after(hist, x["n"], top=4)
    seq = sorted(set(candidates))[:10]
    return "Secret Pull Table", seq, min(99, confidence(seq, hist)+2)

def strat_mix_precision(last, hist):
    a = (transition_after(hist, last, top=3) or [])[:3]
    b = true_neighbors(last,1)
    c = [n for n in freq_top(hist, top=6) if n not in a+b][:3]
    seq = sorted(set(a+b+c))
    return "Mix Precision", seq, min(99, confidence(seq, hist)+2)

# lista final — 23 originais + reforços
STRATEGIES = [
    strat_ia_top5, strat_fire_precision, strat_pattern_breaker,
    strat_viz1, strat_viz2, strat_viz3,
    strat_tiro_seco, strat_linha_finais,
    strat_term_v4, strat_term_secret, strat_term_duplo, strat_term_finais, strat_term_prog,
    strat_formula5x, strat_alpha6, strat_quarta_dimensao,
    strat_cavalos_147, strat_cavalos_258, strat_cavalos_369,
    strat_setor_par, strat_setor_impar,
    strat_black_bias, strat_red_bias,
    strat_duzia_quente, strat_coluna_quente,
    strat_setor_12x, strat_pull_table, strat_mix_precision
]

def choose_best(last, hist):
    evals = []
    for fn in STRATEGIES:
        name, entries, conf = fn(last, hist)
        evals.append((conf, name, entries))
    evals.sort(reverse=True)
    top3 = evals[:3]
    conf, name, entries = top3[0]
    if len(entries) < ENTRY_SIZE:
        entries = expand_entries(entries, last, hist, ENTRY_SIZE)
    conf = max(conf, confidence(entries, hist))
    return name, entries, conf, [t[1] for t in top3]

# ===================== MENSAGENS =====================
def msg_recommendation(source, last_num, last_color, br_time, name, entries, conf, top_names):
    return (
        "🎯 SC Tips – Vem e Vê SC\n"
        f"🎰 {source.upper()}\n"
        f"🌀 Último: {last_num} ({last_color})\n"
        f"🔥 Estratégia: 🎯 {name}\n"
        f"🎯 Entradas: {', '.join(map(str, entries[:ENTRY_SIZE]))}\n"
        f"📊 Confiança: {conf}%\n"
        f"💡 Top IA: {', '.join(top_names)}\n\n"
        f"🎯 📌 Fixos\n{', '.join('#'+str(x) for x in FIXOS)}\n\n"
        f"🕓 Horário: {br_time} (BR)\n"
        "────────────────────────────"
    )

def msg_result(source, prev_signal, new_num, new_color, br_time):
    entries = prev_signal["entries"][:ENTRY_SIZE]
    hit = (new_num in entries) or (new_num in FIXOS)
    status = "✅ GREEN" if hit else "❌ RED"
    return (
        f"{status}\n"
        f"🎰 {source.upper()}\n"
        f"📦 Estratégia: {prev_signal['name']}\n"
        f"🎯 Entradas: {', '.join(map(str, entries))}\n"
        f"🌀 Saiu: {new_num} ({new_color})\n"
        f"🕓 Horário: {br_time} (BR)\n"
        "────────────────────────────"
    ), hit

# ===================== PIPELINE =====================
def update_history_with(source, fetched):
    for item in reversed(fetched):  # antigo -> novo
        if not HISTORY[source] or HISTORY[source][-1]["n"] != item["n"]:
            HISTORY[source].append(item)

def process_source(source):
    fetched = fetch_results(source)
    if not fetched:
        return
    with LOCK:
        update_history_with(source, fetched)
        latest = HISTORY[source][-1] if HISTORY[source] else None
        if not latest:
            return
        latest_n, latest_c, latest_br = latest["n"], latest["c"], latest["br"]

        # 1) Resultado do sinal anterior
        prev = LAST_SIGNAL[source]
        if prev is not None and prev.get("evaluated_num") != latest_n:
            res, hit = msg_result(source, prev, latest_n, latest_c, latest_br)
            print(res)
            send_telegram(res)
            SCORES[source]["green" if hit else "red"] += 1
            LAST_SIGNAL[source] = None

        # 2) Novo sinal
        name, entries, conf, topnames = choose_best(latest_n, HISTORY[source])
        if conf >= MIN_CONF_SEND:
            rec = msg_recommendation(source, latest_n, latest_c, latest_br, name, entries, conf, topnames)
            print(rec)
            send_telegram(rec)
            LAST_SIGNAL[source] = {
                "name": name,
                "entries": entries,
                "conf": conf,
                "sent_at": latest_br,
                "last_num": latest_n
            }

def poller_loop():
    while True:
        for s in SOURCES:
            try:
                fetched = fetch_results(s)
                if fetched:
                    with LOCK:
                        update_history_with(s, fetched)
            except Exception as e:
                print("poller error:", e)
        time.sleep(POLL_SECS)

def smartloop_loop():
    while True:
        for s in SOURCES:
            try:
                process_source(s)
            except Exception as e:
                print("smartloop error:", e)
        time.sleep(SMART_LOOP_SECS)

# ===================== ROTAS =====================
@app.route("/")
def home():
    return jsonify({
        "status": "✅ SC Tips • RealPrecision v3.6 (Top-12) ativo",
        "roletas": list(SOURCES.keys()),
        "smartloop_secs": SMART_LOOP_SECS,
        "poll_secs": POLL_SECS,
        "min_conf": MIN_CONF_SEND,
        "entry_size": ENTRY_SIZE,
        "placar": SCORES,
        "hist_sizes": {k: len(v) for k,v in HISTORY.items()},
        "now_br": to_br_time_str()
    })

@app.route("/api/history/<source>")
def api_history(source):
    if source not in SOURCES:
        return jsonify({"error": "roleta inválida"}), 400
    return jsonify(list(HISTORY[source])[-60:])

@app.route("/api/score")
def api_score():
    return jsonify(SCORES)

# ===================== THREADS =====================
threading.Thread(target=poller_loop, daemon=True).start()
threading.Thread(target=smartloop_loop, daemon=True).start()

# ===================== MAIN =====================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    print(f"🚀 SC Tips • Vem e Vê SC — RealPrecision v3.6 Top-12 na porta {port}")
    print("▶️ 3 roletas ativas: immersive • brazilian • megafire")
    print("🕓 Fuso: America/Sao_Paulo")
    try:
        from waitress import serve as _serve  # opcional
    except Exception:
        _serve = None
    if os.getenv("USE_WAITRESS", "0") == "1" and _serve:
        _serve(app, host="0.0.0.0", port=port)
    else:
        app.run(host="0.0.0.0", port=port)
