# SC Tips v3.5.5 RealPrecision (Vem e Vê SC) — SmartLoop 18s
import os, time, json, threading, asyncio, requests
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template_string, request

# ===================== CONFIG =====================
TG_TOKEN = os.getenv("TG_TOKEN", "7317597605:AAHzvSTxLSIuiyXxvnN9MILaB1FlpHXeEcM")
TG_CHAT  = os.getenv("TG_CHAT",  "-1001483425201")

# Fallback REST (Evolution espelhado)
EVO_URL = os.getenv(
    "EVO_URL",
    "https://api.casinoscores.com/svc-evolution-game-events/api/immersiveroulette?page=0&size=200&sort=data.settledAt,desc&duration=6"
)

# WebSocket (pode precisar ajuste/conteúdo; manteremos tentativa + fallback)
EVO_WS = os.getenv("EVO_WS", "wss://a8-latam.evo-games.com/api/game-events/immersiveroulette")

REFRESH_SECS = int(os.getenv("REFRESH_SECS", "3"))
WINDOW       = int(os.getenv("WINDOW", "300"))
HOT_WINDOW   = int(os.getenv("HOT_WINDOW", "50"))
SEND_THRESHOLD = float(os.getenv("SEND_THRESHOLD", "0.85"))
AUTO_SEND_DEFAULT = os.getenv("AUTO_SEND_DEFAULT", "1") == "1"

# ⏱️ Cooldown entre sinais (ajuste aqui: 12–18s recomendado)
SEND_COOLDOWN = int(os.getenv("SEND_COOLDOWN", "18"))

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

# ===================== WHEEL DATA =====================
EURO_WHEEL = [0,32,15,19,4,21,2,25,17,34,6,27,13,36,11,30,8,23,10,5,24,16,33,1,20,14,31,9,22,18,29,7,28,12,35,3,26]
RED   = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
BLACK = set(range(1,37)) - RED

# ===================== SECRET PULL TABLE (ampliável) =====================
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

# ===================== STATE =====================
CACHE = {"numbers": deque(maxlen=WINDOW), "last_fetch": 0.0, "source": "init"}
SENT_HISTORY = deque(maxlen=500)
WS_CONNECTED = threading.Event()
USE_WS = False
WS_LAST_SEEN = None

# Anti-duplicação / SmartLoop
LAST_SENT_NUMBER = None
LAST_SEND_TIME   = 0.0

# ===================== HELPERS =====================
def now_br_str():
    return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")

def neighbors_of(n, k=1):
    if n not in EURO_WHEEL: return []
    i = EURO_WHEEL.index(n)
    res = {n}
    for d in range(1, k+1):
        res.add(EURO_WHEEL[(i+d) % len(EURO_WHEEL)])
        res.add(EURO_WHEEL[(i-d) % len(EURO_WHEEL)])
    return list(res)

def terminal_group(n):
    if n is None: return []
    t = n % 10
    arr = list(range(t, 37, 10))
    if t == 0 and 0 not in arr: arr.append(0)
    return arr

def column_of(n):
    if n == 0: return 0
    r = n % 3
    return {1:1, 2:2, 0:3}[r]

def freq_score(seq):
    N = max(1, len(seq))
    freq = [0]*37
    for x in seq:
        if 0 <= x <= 36: freq[x] += 1
    return [f/N for f in freq], freq

# ===================== STRATEGIES (23 + IA) =====================
def s_fire_precision(seq, freq):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    for n in neighbors_of(last,2): base[n]+=0.08
    for n in terminal_group(last): base[n]+=0.08
    i = EURO_WHEEL.index(last) if last in EURO_WHEEL else -1
    if i >= 0:
        for d in range(-2,3):
            base[EURO_WHEEL[(i+d)%len(EURO_WHEEL)]] += 0.06
    return base

def s_cacador_repeticoes(seq, freq):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    base[last] += 0.28
    for n in neighbors_of(last,1): base[n]+=0.08
    return base

def s_nb(seq, freq, k):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    bump = 0.12 if k==1 else (0.10 if k==2 else 0.08)
    for n in neighbors_of(last,k): base[n]+=bump
    return base

def s_terminais_v4(seq, freq):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    for n in terminal_group(last): base[n]+=0.18
    for n in neighbors_of(last,1): base[n]+=0.06
    return [x*0.9 for x in base]

def s_terminais_secretos(seq, freq):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    for n in SECRET_PULLS.get(last, []): base[n]+=0.16
    for n in neighbors_of(last,1): base[n]+=0.05
    return base

def s_terminais_duplos(seq, freq):
    base,_ = freq_score(seq)
    if len(seq) >= 2:
        a,b = seq[0], seq[1]
        for n in terminal_group(a)+terminal_group(b): base[n]+=0.08
        for n in neighbors_of(a,1)+neighbors_of(b,1): base[n]+=0.05
    return base

def s_terminais_finais(seq, freq):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    t = last % 10
    for n in range(t,37,10): base[n]+=0.09
    t2 = (t+1) % 10
    for n in range(t2,37,10): base[n]+=0.04
    return base

def s_terminais_prog(seq, freq):
    base,_ = freq_score(seq)
    recent = seq[:HOT_WINDOW]
    seen = set(x%10 for x in recent if x is not None)
    for d in [dd for dd in range(10) if dd not in seen]:
        for n in range(d,37,10): base[n]+=0.07
    return base

def s_tiro_seco(seq, freq):
    base,_ = freq_score(seq)
    ranked = sorted(range(37), key=lambda n: base[n], reverse=True)
    if ranked:
        top = ranked[0]
        base[top]+=0.20
        for n in neighbors_of(top,1): base[n]+=0.06
    return base

def s_formula5x(seq, freq):
    base,_ = freq_score(seq)
    ranked = sorted(range(37), key=lambda n: base[n], reverse=True)
    for n in ranked[:5]: base[n]+=0.08
    if seq:
        for n in terminal_group(seq[0]): base[n]+=0.05
    return base

def s_alpha6(seq, freq):
    base,_ = freq_score(seq)
    ranked = sorted(range(37), key=lambda n: base[n], reverse=True)
    for n in ranked[:6]: base[n]+=0.08
    return base

def s_linha_finais(seq, freq):
    base,_ = freq_score(seq)
    for start in (1,2,3):
        for g in [start, start+3, start+6]:
            for n in range(g,37,10): base[n]+=0.05
    return base

def s_quarta_dimensao(seq, freq):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    for n in neighbors_of(last,2): base[n]+=0.07
    if last != 0:
        r = last % 3
        col = [x for x in range(1,37) if x%3 == (r if r!=0 else 3)%3]
        for n in col: base[n]+=0.04
    targets = (BLACK if last in RED else (RED if last in BLACK else set()))
    for n in targets: base[n]+=0.03
    return base

def s_pattern_breaker(seq, freq):
    base,_ = freq_score(seq)
    N = max(1,len(seq))
    inv = [1-(f/N) for f in freq]
    if seq:
        for n in neighbors_of(seq[0],2): inv[n]+=0.06
    return inv

def s_cavalo_sc_premium(seq, freq):
    base,_ = freq_score(seq)
    if len(seq)>=2:
        a,b = seq[0], seq[1]
        for n in {a,b}: base[n]+=0.08
        for n in neighbors_of(a,1)+neighbors_of(b,1): base[n]+=0.05
    return base

def s_cavalo_set(seq, freq, st):
    base,_ = freq_score(seq)
    sets = {
        "147": {1,4,7,10,13,16,19,22,25,28,31,34},
        "258": {2,5,8,11,14,17,20,23,26,29,32,35},
        "369": {3,6,9,12,15,18,21,24,27,30,33,36},
    }
    for n in sets[st]: base[n]+=0.06
    return base

def s_sector_target(seq, freq):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    if last in EURO_WHEEL:
        i = EURO_WHEEL.index(last)
        arc = [EURO_WHEEL[(i+d)%len(EURO_WHEEL)] for d in range(-4,5)]
        for n in arc: base[n]+=0.08
    return base

def s_ia_top5(seq, freq):
    mix = [0.0]*37
    comps = [s_fire_precision, lambda s,f: s_nb(s,f,1), lambda s,f: s_nb(s,f,2),
             s_terminais_secretos, s_sector_target, s_alpha6]
    for comp in comps:
        sc = comp(seq,freq)
        for i in range(37): mix[i]+=sc[i]
    m = max(mix) if mix else 1.0
    return [x/(m or 1.0) for x in mix]

def s_ia_secret_pattern(seq, freq):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    for n in SECRET_PULLS.get(last, []): base[n]+=0.20
    if len(seq)>=2 and seq[0]==seq[1]:
        for n in neighbors_of(last,1): base[n]+=0.05
    return base

STRATS = {
    "fire": ("Fire Precision", s_fire_precision),
    "rep": ("Caçador de Repetições", s_cacador_repeticoes),
    "nb1": ("Vizinho 1", lambda s,f: s_nb(s,f,1)),
    "nb2": ("Vizinho 2", lambda s,f: s_nb(s,f,2)),
    "nb3": ("Vizinho 3", lambda s,f: s_nb(s,f,3)),
    "term_v4": ("Terminais v4", s_terminais_v4),
    "term_secret": ("Terminais Secretos", s_terminais_secretos),
    "term_duplo": ("Terminais Duplos", s_terminais_duplos),
    "term_finais": ("Terminais dos Finais", s_terminais_finais),
    "term_prog": ("Terminais Progressivos", s_terminais_prog),
    "tiro": ("Tiro Seco", s_tiro_seco),
    "f5x": ("Fórmula 5X", s_formula5x),
    "a6": ("Alpha 6", s_alpha6),
    "linha_finais": ("Linha dos Finais", s_linha_finais),
    "q4d": ("Quarta Dimensão", s_quarta_dimensao),
    "pb": ("Pattern Breaker", s_pattern_breaker),
    "cavalo_sc": ("Cavalo SC Premium", s_cavalo_sc_premium),
    "cavalo_147": ("Cavalo 147", lambda s,f: s_cavalo_set(s,f,"147")),
    "cavalo_258": ("Cavalo 258", lambda s,f: s_cavalo_set(s,f,"258")),
    "cavalo_369": ("Cavalo 369", lambda s,f: s_cavalo_set(s,f,"369")),
    "sector": ("Sector Target", s_sector_target),
    "ia_top5": ("IA Top 5", s_ia_top5),
    "ia_secret": ("IA Secret Pattern", s_ia_secret_pattern),
}

# ===================== CORE ANALYSIS =====================
def analyze_with_strategy(sid, seq_list):
    seq = list(seq_list)[:WINDOW]
    score_func = STRATS.get(sid, STRATS["fire"])[1]
    _, freq = freq_score(seq)
    score = score_func(seq, freq)
    ranked = sorted(range(37), key=lambda n: score[n], reverse=True)
    top5 = ranked[:5]
    top1 = score[ranked[0]] if ranked else 0.0
    conf = min(0.99, max(0.0, top1))
    last = seq[0] if seq else None
    return {"name": STRATS.get(sid, STRATS["fire"])[0], "last": last, "top5": top5,
            "confidence": round(conf,3), "score": score, "numbers": seq}

# ===================== TELEGRAM (VIP FORMAT) =====================
def format_vem_e_ve_message(analysis):
    name = "Vem e Vê SC"
    last = analysis.get("last")
    top5 = analysis.get("top5", [])
    conf = int((analysis.get("confidence",0))*100)
    strategy_name = analysis.get("name", "Estratégia")
    ts = now_br_str()
    neighbors_info = f"💡 Vizinhos de {last}" if last is not None else ""

    status_block = ("\n\n✅ GREEN\n🎯 📌 Fixos\n#0"
                    if last in top5 else
                    f"\n\n❌ RED\nNúmero: {last} fora das previsões")

    lines = []
    lines.append("Vip - Vem e Ve SC:")
    lines.append(f"🎯 SC Tips – {name}")
    lines.append(f"🌀 Último: {last}")
    lines.append(f"🔥 Estratégia: 🎯 {strategy_name}")
    lines.append(f"🎯 Entradas: {', '.join(map(str, top5))}")
    lines.append(f"📊 Confiança: {conf}%")
    if neighbors_info: lines.append(neighbors_info)
    lines.append(status_block)
    lines.append(f"\n🕓 Horário: {ts} (BR)")
    return "\n".join(lines)

def send_tg(text):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TG_CHAT, "text": text}, timeout=10)
        return r.ok
    except Exception as e:
        print("send_tg error:", e)
        return False

# ===================== BACKGROUND COLLECTORS =====================
def poller_fallback():
    while True:
        try:
            r = requests.get(EVO_URL, headers={"User-Agent":"SC-Tips/3.5.5"}, timeout=8)
            j = r.json()
            items = j if isinstance(j, list) else (j.get("content") or j.get("results") or [])
            nums = []
            for it in items:
                n = None
                if isinstance(it, dict):
                    n = it.get("data", {}).get("result", {}).get("outcome", {}).get("number")
                    if n is None:
                        n = it.get("data", {}).get("number") or it.get("number")
                if n is not None and str(n).lstrip('-').isdigit():
                    n = int(n)
                    if 0 <= n <= 36: nums.append(n)
            if nums:
                CACHE["numbers"].clear()
                for n in nums:
                    CACHE["numbers"].append(n)
                CACHE["last_fetch"] = time.time()
                CACHE["source"] = "casinoscores"
        except Exception as e:
            print("poller_fallback error:", e)
        time.sleep(REFRESH_SECS)

async def ws_listener_loop():
    global USE_WS, WS_LAST_SEEN
    try:
        import websockets
    except Exception as e:
        print("websockets lib missing:", e); return

    while True:
        try:
            async with websockets.connect(EVO_WS, ping_interval=20, ping_timeout=10) as ws:
                print("WS connected:", EVO_WS)
                USE_WS = True
                WS_CONNECTED.set()
                CACHE["source"] = "ws"
                async for msg in ws:
                    num = None
                    try:
                        data = json.loads(msg)
                        if isinstance(data, dict):
                            if "number" in data:
                                num = int(data["number"])
                            elif "data" in data and isinstance(data["data"], dict) and "number" in data["data"]:
                                num = int(data["data"]["number"])
                            else:
                                for k in ("payload","body","gameEvent"):
                                    if k in data and isinstance(data[k], dict) and "number" in data[k]:
                                        num = int(data[k]["number"]); break
                    except Exception:
                        num = None
                    if num is not None and 0 <= num <= 36:
                        CACHE["numbers"].appendleft(num)
                        CACHE["last_fetch"] = time.time()
                        WS_LAST_SEEN = time.time()
        except Exception as e:
            print("WS listener error; reconnect:", e)
            USE_WS = False
            WS_CONNECTED.clear()
            CACHE["source"] = "ws-down"
            await asyncio.sleep(2.0)

def start_ws_thread():
    def runner():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(ws_listener_loop())
        except Exception as e:
            print("WS runner exception:", e)
    threading.Thread(target=runner, daemon=True).start()

threading.Thread(target=poller_fallback, daemon=True).start()
start_ws_thread()

# ===================== FLASK =====================
app = Flask(__name__)

@app.route("/")
def index():
    opts = "\n".join([f'<option value="{k}">{v[0]}</option>' for k,v in STRATS.items()])
    autos = "checked" if AUTO_SEND_DEFAULT else ""
    return render_template_string("""
<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SC Tips • Vem e Vê SC — Real Precision</title>
<style>
:root{--bg:#040404;--panel:#0b0b0b;--text:#ffd84d;--muted:#9aa;--neonG:#00ff88;--neonR:#ff3b3b;--chip:#111}
[data-theme="light"]{--bg:#f6f6f6;--panel:#fff;--text:#111;--muted:#666;--neonG:#0b8f4a;--neonR:#d33}
body{background:var(--bg);color:var(--text);font-family:Arial,monospace;margin:0;padding:14px}
.container{max-width:780px;margin:0 auto}
.card{background:var(--panel);border-radius:12px;padding:14px;border:1px solid rgba(0,255,0,.06)}
.top{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
select,input,button{border-radius:8px;padding:8px 10px;border:1px solid rgba(255,255,255,.06)}
button{background:var(--text);color:var(--bg);font-weight:bold}
.grid{display:grid;grid-template-columns:repeat(9,1fr);gap:8px;margin:12px 0}
.cell{background:var(--chip);padding:10px;border-radius:8px;text-align:center;color:#fff;font-weight:bold}
.cell.hot{background:linear-gradient(0deg,var(--neonR),#ff7777);box-shadow:0 0 12px rgba(255,59,59,.9),0 0 32px rgba(255,59,59,.25);animation:hotPulse 1s infinite}
@keyframes hotPulse{0%{filter:brightness(0.9)}50%{filter:brightness(1.2)}100%{filter:brightness(0.95)}}
.cell.bet{background:linear-gradient(0deg,var(--neonG),#b0ffcc);color:#002;box-shadow:0 0 12px rgba(0,255,136,.9),0 0 28px rgba(0,255,136,.18);animation:betGlow 1.4s infinite alternate}
@keyframes betGlow{from{transform:translateY(0)}to{transform:translateY(-2px)}}
.info{color:var(--muted);margin-top:8px}
.badge{padding:6px 8px;border-radius:8px;background:#111;color:var(--muted);font-weight:bold;font-size:12px}
.progress{height:10px;background:#111;border-radius:8px;overflow:hidden;margin-top:8px}
.bar{height:100%;background:linear-gradient(90deg,var(--neonG),#8affc2);width:0%;transition:width .5s}
.history{margin-top:12px;background:rgba(255,255,255,0.02);padding:8px;border-radius:8px;color:var(--muted);font-size:13px;max-height:180px;overflow-y:auto}
.small{font-size:13px;color:var(--muted)}
</style></head>
<body>
<div class="container" id="root">
  <div class="card">
    <div class="top">
      <h3 style="margin:0">🎯 SC Tips • Vem e Vê SC</h3>
      <select id="strategy">{{opts}}</select>
      <button id="btnSend">Enviar TG</button>
      <label style="display:flex;gap:6px;align-items:center">AutoSend
        <input id="autosend" type="checkbox" {{autos}}>
      </label>
      <label style="display:flex;gap:6px;align-items:center">MinConf
        <input id="minconf" type="number" value="{{minconf}}" min="10" max="99" style="width:70px">%
      </label>
      <div class="badge" id="realtime_status">Status: inicializando...</div>
      <div class="badge">⏱️ Cooldown: {{cooldown}}s</div>
      <button id="btnTheme">🌗</button>
    </div>

    <div id="grid" class="grid"></div>
    <div class="info" id="info">Último: - • Confiança: -% • Top5: -</div>
    <div class="progress"><div id="bar" class="bar"></div></div>

    <div class="history">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <strong>Entradas Ativas</strong><small class="small">Histórico dos últimos sinais enviados</small>
      </div>
      <div id="sent" style="margin-top:8px">— nenhum —</div>
    </div>

    <div style="margin-top:10px" class="small">
      <div>🎰 Abrir roleta: <a href="https://donald.bet.br/games/evolution/immersive-roulette" target="_blank">donald.bet • Immersive Roulette</a></div>
      <div>Fonte: Evolution (WS preferencial) • Fallback: casinoscores • Atualiza a cada {{refresh}}s</div>
    </div>
  </div>
</div>

<script>
const grid = document.getElementById('grid');
const info = document.getElementById('info');
const bar = document.getElementById('bar');
const sentDiv = document.getElementById('sent');
const sel = document.getElementById('strategy');
const btnSend = document.getElementById('btnSend');
const autosend = document.getElementById('autosend');
const minconfInput = document.getElementById('minconf');
const realtimeBadge = document.getElementById('realtime_status');
const btnTheme = document.getElementById('btnTheme');
const root = document.getElementById('root');

const COOLDOWN_MS = {{cooldown}} * 1000;
let lastSentAt = 0;
let lastNumberSent = null;

for(let i=0;i<=36;i++){ const d=document.createElement('div'); d.className='cell'; d.id='cell-'+i; d.textContent=i; grid.appendChild(d); }

let audioCtx;
function beep(f=440,t='sine',dur=0.12){ try{ audioCtx = audioCtx || new (window.AudioContext||window.webkitAudioContext)();
  const o=audioCtx.createOscillator(), g=audioCtx.createGain(); o.type=t; o.frequency.value=f; g.gain.value=0.05;
  o.connect(g); g.connect(audioCtx.destination); o.start(); setTimeout(()=>o.stop(), dur*1000);
}catch(e){}}
const ding = ()=>beep(880,'square',0.16);
const tick = ()=>beep(520,'sine',0.1);

async function notify(title,body){ if(!("Notification" in window)) return; if(Notification.permission==="granted") new Notification(title,{body}); else if(Notification.permission!=="denied"){ const p=await Notification.requestPermission(); if(p==="granted") new Notification(title,{body}); }}

async function loadOnce(){
  try{
    const resp = await fetch('/api/analyze?strategy='+encodeURIComponent(sel.value), {cache:'no-store'});
    const j = await resp.json();
    const recent = j.numbers || [];
    const hotSet = new Set(recent.slice(0, {{hot_window}}));
    const bets = j.top5 || [];
    for(let i=0;i<=36;i++){ const el=document.getElementById('cell-'+i); el.classList.remove('hot','bet'); }
    hotSet.forEach(n=>{ const el=document.getElementById('cell-'+n); if(el) el.classList.add('hot'); });
    bets.forEach(n=>{ const el=document.getElementById('cell-'+n); if(el) el.classList.add('bet'); });

    const conf = Math.round((j.confidence||0)*100);
    info.textContent = `Último: ${j.last} • Confiança: ${conf}% • Top5: ${j.top5.join(', ')}`;
    bar.style.width = Math.min(100, conf) + "%";

    const src = j.source || "api";
    realtimeBadge.textContent = src==="ws" ? "✅ WS Live" : (src==="casinoscores" ? "📡 API" : "⏳ Init");

    const now = Date.now();
    const minconf = parseInt(minconfInput.value||"85");
    const elapsed = now - lastSentAt;
    const canSend = elapsed >= COOLDOWN_MS && j.last !== lastNumberSent;
    
    if(autosend.checked && j.confidence >= (minconf/100) && canSend){
      await sendSignal(sel.value, j, true);
      lastSentAt = now;
      lastNumberSent = j.last;
    }
  }catch(e){
    console.error("loadOnce error", e);
    info.textContent = "Erro ao buscar dados";
  }
}

async function sendSignal(strategy, analysis, isAuto=false){
  try{
    const body = { strategy: strategy };
    const resp = await fetch('/api/force_send', { method:'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const j = await resp.json();
    const ts = new Date().toLocaleTimeString();
    const conf = Math.round((analysis.confidence||0)*100);
    const txt = `<div style="margin-bottom:6px"><b>${ts}</b> • <em>${analysis.name}</em> • <strong>${conf}%</strong><br>Entrar: ${analysis.top5.join(', ')} • Últ: ${analysis.last}${isAuto?' 🤖':''}</div>`;
    sentDiv.innerHTML = txt + sentDiv.innerHTML;
    ding();
    return j;
  }catch(e){
    console.error("sendSignal error", e);
    return null;
  }
}

btnSend.onclick = async ()=>{
  const now = Date.now();
  const elapsed = now - lastSentAt;
  if(elapsed < COOLDOWN_MS){
    const wait = Math.ceil((COOLDOWN_MS - elapsed)/1000);
    alert(`⏱️ Aguarde ${wait}s antes de enviar novamente (cooldown ${{{cooldown}}}s)`);
    return;
  }
  tick();
  const r = await fetch('/api/analyze?strategy='+encodeURIComponent(sel.value), {cache:'no-store'});
  const j = await r.json();
  await sendSignal(sel.value, j, false);
  lastSentAt = now;
  lastNumberSent = j.last;
};

sel.onchange = ()=>{ tick(); loadOnce(); };
btnTheme.onclick = ()=>{ root.setAttribute('data-theme', root.getAttribute('data-theme')==='light' ? '' : 'light') };

loadOnce();
setInterval(loadOnce, {{refresh}}*1000);
</script>
</body>
</html>
    """.replace("{{opts}}", opts)
        .replace("{{minconf}}", str(int(SEND_THRESHOLD*100)))
        .replace("{{autos}}", autos)
        .replace("{{cooldown}}", str(SEND_COOLDOWN))
        .replace("{{hot_window}}", str(HOT_WINDOW))
        .replace("{{refresh}}", str(REFRESH_SECS)))

@app.route("/api/analyze")
def api_analyze():
    sid = request.args.get("strategy", "fire")
    seq = list(CACHE["numbers"])
    a = analyze_with_strategy(sid, seq)
    a["numbers"] = seq
    a["source"] = CACHE["source"]
    return jsonify(a)

@app.route("/api/force_send", methods=["POST"])
def api_force_send():
    global LAST_SENT_NUMBER, LAST_SEND_TIME
    data = request.get_json(silent=True) or {}
    sid = data.get("strategy", "fire")
    seq = list(CACHE["numbers"])
    a = analyze_with_strategy(sid, seq)
    
    now = time.time()
    last_num = a["last"]
    
    # SmartLoop: prevent duplicate sends
    if last_num == LAST_SENT_NUMBER and (now - LAST_SEND_TIME) < SEND_COOLDOWN:
        return jsonify({"ok": False, "reason": "cooldown", "name": a["name"], "top5": a["top5"], "conf": int((a["confidence"])*100)})
    
    msg = format_vem_e_ve_message(a)
    ok = send_tg(msg)
    
    if ok:
        LAST_SENT_NUMBER = last_num
        LAST_SEND_TIME = now
    
    ts = now_br_str()
    SENT_HISTORY.appendleft({"ts": ts, "name": a["name"], "top5": a["top5"], "conf": int((a["confidence"])*100), "auto": False})
    return jsonify({"ok": ok, "name": a["name"], "top5": a["top5"], "conf": int((a["confidence"])*100)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
