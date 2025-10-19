# SC Tips v3.5.5 RealPrecision (Vem e Vê SC) — 3 Roletas + 23 Estratégias + Auto TG
import os, time, json, threading, requests
from collections import deque
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS

# ===================== CONFIG =====================
TG_TOKEN = os.getenv("TG_TOKEN", "7317597605:AAHzvSTxLSIuiyXxvnN9MILaB1FlpHXeEcM")
TG_CHAT  = os.getenv("TG_CHAT",  "-1001483425201")

REFRESH_SECS = int(os.getenv("REFRESH_SECS", "3"))     # coleta REST
SEND_COOLDOWN = int(os.getenv("SEND_COOLDOWN", "18"))  # SmartLoop 18s
WINDOW       = int(os.getenv("WINDOW", "300"))
HOT_WINDOW   = int(os.getenv("HOT_WINDOW", "50"))
SEND_THRESHOLD = float(os.getenv("SEND_THRESHOLD", "0.70"))
AUTO_SEND_DEFAULT = os.getenv("AUTO_SEND_DEFAULT", "1") == "1"

# APIs REST CasinoScores
SOURCES = {
    "immersive": "https://api.casinoscores.com/svc-evolution-game-events/api/immersiveroulette?page=0&size=200&sort=data.settledAt,desc&duration=6",
    "brazilian": "https://api.casinoscores.com/svc-pragmatic-game-events/api/brazilianroulette?page=0&size=200&sort=data.settledAt,desc&duration=6",
    "megafire":  "https://api.casinoscores.com/svc-evolution-game-events/api/megafireblazeroulette?page=0&size=200&sort=data.settledAt,desc&duration=6"
}

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
CACHE = {
    "immersive": {"numbers": deque(maxlen=WINDOW), "last": None, "last_ts": 0.0},
    "brazilian": {"numbers": deque(maxlen=WINDOW), "last": None, "last_ts": 0.0},
    "megafire":  {"numbers": deque(maxlen=WINDOW), "last": None, "last_ts": 0.0},
}
SENT_HISTORY = deque(maxlen=200)
LAST_SEND_TIME = 0.0
AUTO_SEND = AUTO_SEND_DEFAULT

# ===================== HELPERS =====================
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

def freq_score(seq):
    N = max(1, len(seq))
    freq = [0]*37
    for x in seq:
        if 0 <= x <= 36: freq[x] += 1
    base = [f/N for f in freq]
    return base, freq

# ===================== STRATEGIES (23 + IA) =====================
def s_fire_precision(seq, freq):
    base,_ = freq_score(seq)
    if not seq: return base
    last = seq[0]
    for n in neighbors_of(last,2): base[n]+=0.08
    for n in terminal_group(last): base[n]+=0.08
    if last in EURO_WHEEL:
        i = EURO_WHEEL.index(last)
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
    base,counts = freq_score(seq)
    N = max(1,len(seq))
    inv = [1-(c/N) for c in counts]
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
    return {"id": sid, "name": STRATS.get(sid, STRATS["fire"])[0], "last": last, "top5": top5,
            "confidence": round(conf,3), "score": score, "numbers": seq}

# ===================== TELEGRAM =====================
def format_tg_message(roulette, analysis):
    last = analysis.get("last")
    top5 = analysis.get("top5", [])
    conf = int((analysis.get("confidence",0))*100)
    strategy_name = analysis.get("name", "Estratégia")
    ts = datetime.now().strftime("%H:%M:%S")
    status = "✅ GREEN" if last in top5 else "❌ RED"
    lines = []
    lines.append(f"🎯 <b>{roulette.upper()}</b> • {ts}")
    lines.append(f"🔥 Estratégia: <b>{strategy_name}</b>")
    lines.append(f"🎯 Entradas: <code>{', '.join(map(str, top5))}</code>")
    lines.append(f"📊 Confiança: <b>{conf}%</b>")
    lines.append(f"{status} • Último: <b>{last}</b>")
    return "\\n".join(lines)

def send_tg(text):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML"}, timeout=10)
        return r.ok
    except Exception:
        return False

# ===================== COLLECTORS =====================
def fetch_rest(roulette):
    url = SOURCES[roulette]
    try:
        r = requests.get(url, headers={"User-Agent":"SC-Tips/3.5.5"}, timeout=8)
        j = r.json()
        items = j.get("content", [])
        nums = []
        for it in items:
            num = None
            # evolution format
            if isinstance(it, dict):
                res = it.get("result") or {}
                if "value" in res:
                    num = res.get("value")
                if num is None:
                    num = it.get("data", {}).get("result", {}).get("outcome", {}).get("number")
                if num is None:
                    num = it.get("data", {}).get("number") or it.get("number")
            if num is not None:
                try:
                    num = int(num)
                    if 0 <= num <= 36:
                        nums.append(num)
                except Exception:
                    pass
        return nums
    except Exception as e:
        return []

def poller_loop():
    while True:
        for roulette in SOURCES.keys():
            nums = fetch_rest(roulette)
            if nums:
                dq = CACHE[roulette]["numbers"]
                dq.clear()
                for n in nums:
                    dq.appendleft(n)
                CACHE[roulette]["last"] = dq[0] if dq else None
                CACHE[roulette]["last_ts"] = time.time()
        time.sleep(REFRESH_SECS)

def smartloop_sender():
    global LAST_SEND_TIME
    while True:
        now = time.time()
        if AUTO_SEND and (now - LAST_SEND_TIME) >= SEND_COOLDOWN:
            for roulette in SOURCES.keys():
                seq = CACHE[roulette]["numbers"]
                if not seq: continue
                # usar IA Top5 por padrão
                analysis = analyze_with_strategy("ia_top5", list(seq))
                if analysis["confidence"] >= SEND_THRESHOLD:
                    msg = format_tg_message(roulette, analysis)
                    ok = send_tg(msg)
                    if ok:
                        SENT_HISTORY.appendleft({"when": datetime.now().strftime("%H:%M:%S"),
                                                 "roulette": roulette,
                                                 "strategy": analysis["name"],
                                                 "top5": analysis["top5"],
                                                 "conf": analysis["confidence"]})
                        LAST_SEND_TIME = time.time()
                        break  # evita enviar 3 de uma vez no mesmo tick
        time.sleep(1)

threading.Thread(target=poller_loop, daemon=True).start()
threading.Thread(target=smartloop_sender, daemon=True).start()

# ===================== FLASK (UI + API) =====================
app = Flask(__name__)
CORS(app)

@app.get("/")
def index():
    # strategy options
    opts = "\\n".join([f'<option value="{k}">{v[0]}</option>' for k,v in STRATS.items()])
    autos = "checked" if AUTO_SEND_DEFAULT else ""
    return render_template_string(\"\"\"
<!doctype html><html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SC Tips • Real Precision 3R</title>
<style>
:root{--bg:#000;--card:#071407;--muted:#88aa88;--matrix:#00ff6a;--gold:#ffd700;--chip:#0a190a;--red:#ff3b3b}
*{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at 10% 10%,#031003,#000 40%);color:#e6ffe6;font-family:system-ui,Arial}
.wrap{max-width:1000px;margin:0 auto;padding:18px}
.header{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
.card{background:linear-gradient(180deg,#091909,#041004);border:1px solid #0a320a;border-radius:16px;padding:14px;box-shadow:0 8px 24px rgba(0,0,0,.35)}
select,button,input{border-radius:10px;border:1px solid #0b2c0b;background:#0b1f0b;color:#d6ffd6;padding:8px 10px}
button{background:linear-gradient(180deg,#0b360b,#0c520c);font-weight:700}
.grid{display:grid;grid-template-columns:repeat(9,1fr);gap:8px;margin:12px 0}
.cell{background:var(--chip);padding:10px;border-radius:10px;text-align:center;font-weight:700;border:1px solid #0c2c0c}
.cell.hot{background:linear-gradient(0deg,var(--matrix),#a0ffc2);color:#002;box-shadow:0 0 12px rgba(0,255,136,.8)}
.cell.pick{background:linear-gradient(0deg,var(--gold),#fff1b3);color:#220}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.small{color:var(--muted);font-size:13px}
.badge{padding:6px 8px;border-radius:8px;background:#0c1b0c;border:1px solid #164116;color:#9fd29f;font-weight:700}
.list{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px}
.tag{background:#0c1b0c;border:1px solid #1d4d1d;border-radius:100px;padding:4px 8px}
.hr{height:1px;background:#0f2a0f;margin:10px 0}
</style></head>
<body><div class="wrap">
  <div class="header">
    <h2 style="margin:0">🎯 SC Tips • Matrix Real Precision v3.5.5</h2>
    <div class="badge">SmartLoop {{cooldown}}s</div>
    <div class="badge">AutoSend <input id="autosend" type="checkbox" {{autos}}></div>
    <div class="badge">MinConf <input id="minconf" type="number" value="{{minconf}}" min="50" max="99" style="width:62px">%</div>
  </div>

  <div class="card">
    <div class="row">
      <label>Roleta
        <select id="roulette">
          <option value="immersive">Immersive</option>
          <option value="brazilian">Brazilian</option>
          <option value="megafire">Mega Fire Blaze</option>
        </select>
      </label>
      <label>Estratégia
        <select id="strategy">
          {{opts}}
        </select>
      </label>
      <button id="btnAnalyze">Analisar</button>
      <button id="btnSend">Enviar TG</button>
      <span id="status" class="badge">⏳ aguardando dados...</span>
    </div>

    <div id="board" class="grid"></div>
    <div class="row small"><div>Último: <b id="last">-</b></div><div>Top5: <b id="top5">-</b></div><div>Confiança: <b id="conf">-</b></div></div>
    <div class="hr"></div>
    <div class="row small">
      <div>Entradas Ativas:</div>
      <div id="active" class="list"></div>
    </div>
  </div>

  <p class="small">Fonte: CasinoScores REST • Atualiza a cada {{refresh}}s • Envio automático se confiança ≥ {{minconf}}%</p>
</div>

<script>
const board = document.getElementById('board');
const rouletteSel = document.getElementById('roulette');
const stratSel = document.getElementById('strategy');
const lastEl = document.getElementById('last');
const top5El = document.getElementById('top5');
const confEl = document.getElementById('conf');
const statusEl = document.getElementById('status');
const autosend = document.getElementById('autosend');
const minconf = document.getElementById('minconf');
const active = document.getElementById('active');

for(let i=0;i<=36;i++){ const d=document.createElement('div'); d.className='cell'; d.id='cell-'+i; d.textContent=i; board.appendChild(d); }

let lastSeq = [];
let top5 = [];
let lastNumber = null;
let busy = false;
let lastSendAt = 0;

function paint(seq, picks){
  for(let i=0;i<=36;i++){ const c=document.getElementById('cell-'+i); c.classList.remove('hot','pick'); }
  seq.slice(0,12).forEach((n)=>{ const c=document.getElementById('cell-'+n); if(c) c.classList.add('hot'); });
  picks.forEach((n)=>{ const c=document.getElementById('cell-'+n); if(c) c.classList.add('pick'); });
}

async function fetchSeq(){
  try{
    const r = await fetch('/api/seq/'+rouletteSel.value);
    const j = await r.json();
    lastSeq = j.numbers || [];
    lastNumber = lastSeq[0] ?? null;
    statusEl.textContent = '✅ dados';
  }catch(e){
    statusEl.textContent = '❌ erro dados';
  }
}

async function analyze(){
  if(busy) return; busy = true;
  try{
    const r = await fetch(`/api/analyze/${rouletteSel.value}?sid=${stratSel.value}&minconf=${minconf.value}`);
    const j = await r.json();
    top5 = j.top5 || [];
    lastNumber = j.last;
    lastEl.textContent = lastNumber ?? '-';
    top5El.textContent = (top5||[]).join(', ');
    confEl.textContent = Math.round((j.confidence||0)*100)+'%';
    paint(lastSeq, top5);
  } catch(e){
    console.error(e);
  } finally { busy=false; }
}

async function sendTG(){
  try{ await fetch(`/api/send/${rouletteSel.value}?sid=${stratSel.value}`, {method:'POST'}); }catch(e){}
}

document.getElementById('btnAnalyze').onclick = async ()=>{ await fetchSeq(); await analyze(); };
document.getElementById('btnSend').onclick = sendTG;

setInterval(async ()=>{
  await fetchSeq();
  if(autosend.checked){
    const r = await fetch(`/api/analyze/${rouletteSel.value}?sid=ia_top5&minconf=${minconf.value}`);
    const j = await r.json();
    if((j.confidence||0) >= (parseInt(minconf.value)/100)){
      const now = Date.now();
      if(now - lastSendAt > {{cooldown}}*1000){
        lastSendAt = now;
        await fetch(`/api/send/${rouletteSel.value}?sid=ia_top5`, {method:'POST'});
      }
    }
    top5 = j.top5 || [];
    lastSeq = j.numbers || lastSeq;
    lastNumber = j.last;
    lastEl.textContent = lastNumber ?? '-';
    top5El.textContent = (top5||[]).join(', ');
    confEl.textContent = Math.round((j.confidence||0)*100)+'%';
    paint(lastSeq, top5);
  }
}, {{refresh}}*1000);
</script>
</body></html>
\"\"\", opts=opts, autos=autos, cooldown=SEND_COOLDOWN, refresh=REFRESH_SECS, minconf=int(SEND_THRESHOLD*100))

@app.get("/api/seq/<roulette>")
def api_seq(roulette):
    if roulette not in CACHE: return jsonify({"error":"roleta inválida"}), 400
    return jsonify({"numbers": list(CACHE[roulette]["numbers"])})

@app.get("/api/analyze/<roulette>")
def api_analyze(roulette):
    if roulette not in CACHE: return jsonify({"error":"roleta inválida"}), 400
    sid = request.args.get("sid","ia_top5")
    minconf = float(request.args.get("minconf", str(int(SEND_THRESHOLD*100))))/100.0
    seq = list(CACHE[roulette]["numbers"])
    if not seq: return jsonify({"error":"sem dados"}), 400
    analysis = analyze_with_strategy(sid, seq)
    return jsonify({
        "id": analysis["id"],
        "name": analysis["name"],
        "last": analysis["last"],
        "top5": analysis["top5"],
        "confidence": analysis["confidence"],
        "numbers": analysis["numbers"]
    })

@app.post("/api/send/<roulette>")
def api_send(roulette):
    if roulette not in CACHE: return jsonify({"error":"roleta inválida"}), 400
    sid = request.args.get("sid","ia_top5")
    seq = list(CACHE[roulette]["numbers"])
    if not seq: return jsonify({"error":"sem dados"}), 400
    analysis = analyze_with_strategy(sid, seq)
    text = format_tg_message(roulette, analysis)
    ok = send_tg(text)
    if ok:
        SENT_HISTORY.appendleft({"when": datetime.now().strftime("%H:%M:%S"),
                                 "roulette": roulette,
                                 "strategy": analysis["name"],
                                 "top5": analysis["top5"],
                                 "conf": analysis["confidence"]})
    return jsonify({"ok": ok})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 SC Tips RealPrecision 3R na porta {port}")
    app.run(host="0.0.0.0", port=port)
