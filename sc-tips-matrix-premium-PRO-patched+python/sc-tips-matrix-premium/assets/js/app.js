
import { STRATEGIES } from './strategies.js';
import { EU_WHEEL, drawRaceBoard } from './race.js';
import { HookBus } from './ws-hooks.js';
import { saveTelegramConfig, loadTelegramConfig, sendTelegram } from './telegram.js';

const $ = (sel, el=document)=>el.querySelector(sel);
const $$ = (sel, el=document)=>[...el.querySelectorAll(sel)];

const state = {
  lastNumbers: [],
  counters: {greens:0, reds:0, alerts:0},
  timer: {running:false, left:18, id:null},
  selectedStrategy: STRATEGIES[0].id,
  neighbors: 2,
  wsUrls: [],
  flags:{ tiroSeco:false, tgOn:false },
};

/* ===== Sounds ===== */
function beep(kind='click'){
  const el = new Audio(`./../audio/${kind}.wav`);
  el.volume = (kind==='alerta')?0.45:(kind==='red'?0.4:0.35);
  el.play().catch(()=>{});
}

/* ===== KPIs ===== */
function renderKpis(){
  $('#kpi-greens .n').textContent = state.counters.greens;
  $('#kpi-reds .n').textContent = state.counters.reds;
  $('#kpi-alerts .n').textContent = state.counters.alerts;
  $('#kpi-ult .n').textContent = state.lastNumbers[0] ?? '-';
}

/* ===== Numbers ===== */
function pushNumber(n){
  state.lastNumbers.unshift(n);
  state.lastNumbers = state.lastNumbers.slice(0,24);
  renderKpis();
  const log = $('#liveLog');
  const li = document.createElement('div');
  li.textContent = `[${new Date().toLocaleTimeString()}] Número: ${n}`;
  log.prepend(li);
}

/* ===== Timer 18s ===== */
function startTimer(){
  if(state.timer.running) return;
  state.timer.running = true;
  state.timer.left = 18;
  $('#btnTimer').textContent = '⏳ Rodando 18s';
  state.timer.id = setInterval(()=>{
    state.timer.left--;
    $('#tLeft').textContent = String(state.timer.left).padStart(2,'0');
    if(state.timer.left<=0){ clearInterval(state.timer.id); state.timer.running=false; $('#btnTimer').textContent='▶️ Iniciar 18s'; $('#tLeft').textContent='18'; beep('alerta'); }
  },1000);
}
function stopTimer(){
  if(!state.timer.running) return;
  clearInterval(state.timer.id);
  state.timer.running=false;
  $('#btnTimer').textContent='▶️ Iniciar 18s';
  $('#tLeft').textContent='18';
}

/* ===== Strategies UI ===== */
function renderStrategies(){
  const sel = $('#strategy');
  sel.innerHTML = STRATEGIES.map(s=>`<option value="${s.id}">${s.nome}</option>`).join('');
  sel.value = state.selectedStrategy;
  showStrategy();
}
function showStrategy(){
  const s = STRATEGIES.find(x=>x.id===state.selectedStrategy);
  if(!s) return;
  $('#str-nome').textContent = s.nome;
  $('#str-gatilho').textContent = s.gatilho;
  $('#str-base').textContent = s.base.join(', ');
  $('#str-prot').textContent = s.protecao?.join(', ') || '-';
}

/* ===== WS URLs ===== */
function renderWsUrls(){
  const box = $('#wsUrls');
  box.innerHTML = state.wsUrls.map(u=>`<div class="pill" title="${u}">${u}</div>`).join('');
}

/* ===== HOOKS ===== */
HookBus.addEventListener('ws:url', (e)=>{
  state.wsUrls.unshift(e.detail.url);
  state.wsUrls = state.wsUrls.slice(0,30);
  renderWsUrls();
});
HookBus.addEventListener('ws:number', (e)=>{
  const n = Number(e.detail.number);
  pushNumber(n);
  evalSpin(n);
});

/* ===== Race ===== */
function initRace(){
  window.addEventListener('resize', ()=>drawRaceBoard($('#raceCanvas')));
  drawRaceBoard($('#raceCanvas'));
}

/* ===== Neighbors / coverage ===== */
function neighborsOf(n,k){
  if(k<=0) return [n];
  const arr = [n];
  const idx = EU_WHEEL.indexOf(n);
  if(idx<0) return [n];
  for(let d=1; d<=k; d++){
    arr.push(EU_WHEEL[(idx+d)%EU_WHEEL.length]);
    arr.push(EU_WHEEL[(idx - d + EU_WHEEL.length) % EU_WHEEL.length]);
  }
  return Array.from(new Set(arr));
}
function coveredSet(strategy, kNeighbors){
  const base = strategy.base||[];
  const prot = strategy.protecao||[];
  let covered = new Set(prot);
  const k = (state.flags.tiroSeco? 0 : (kNeighbors||0));
  for(const b of base){
    for(const x of neighborsOf(b,k)) covered.add(x);
  }
  return covered;
}

/* ===== History ===== */
const history = []; // {at:number, number:int, strategyId, covered:[...], result:'GREEN'|'RED'}
function evalSpin(n){
  const s = STRATEGIES.find(x=>x.id===state.selectedStrategy);
  const cov = coveredSet(s, state.neighbors);
  const hit = cov.has(Number(n));
  const result = hit?'GREEN':'RED';
  history.unshift({ at: Date.now(), number:n, strategyId: s.id, covered:[...cov], result });
  history.splice(0, 120);
  if(hit){ state.counters.greens++; beep('green'); } else { state.counters.reds++; beep('red'); }
  renderKpis(); renderHistory();
  if(state.flags.tgOn){
    sendTelegram(`SC Tips — ${result}\nEstratégia: ${s.nome}\nNúmero: ${n}\nBase: ${s.base.join(', ')}\nProteção: ${(s.protecao||[]).join(', ')||'-'}\nVizinhos: ${state.flags.tiroSeco?0:state.neighbors}`)
      .catch(()=>{});
  }
}
function renderHistory(){
  const box = $('#hist'); if(!box) return;
  box.innerHTML = history.slice(0,30).map(h=>`<div class="row" style="justify-content:space-between;border-bottom:1px dashed var(--stroke2);padding:4px 0">
    <div>#${h.number} <small>(${new Date(h.at).toLocaleTimeString()})</small></div>
    <div class="pill" style="border-color:${h.result==='GREEN'?'#2e9d57':'#8b2d2d'}">${h.result}</div>
  </div>`).join('');
}
function exportHistoryCsv(){
  const rows = [['timestamp','number','result','strategy','neighbors']].concat(
    history.map(h=>[h.at, h.number, h.result, h.strategyId, state.flags.tiroSeco?0:state.neighbors])
  );
  const csv = rows.map(r=>r.join(',')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  a.download = 'sc-history.csv'; a.click(); URL.revokeObjectURL(a.href);
}

/* ===== Theme toggle ===== */
function applyTheme(theme){ // 'navy' | 'gold'
  const root = document.documentElement;
  root.classList.remove('theme-navy','theme-gold');
  const cls = theme==='gold'?'theme-gold':'theme-navy';
  root.classList.add(cls);
  localStorage.setItem('sc.theme', theme);
}
function loadTheme(){
  const t = localStorage.getItem('sc.theme') || 'navy';
  applyTheme(t);
}

/* ===== Telegram UI ===== */
function loadTelegramIntoForm(){
  const cfg = loadTelegramConfig();
  $('#tgToken').value = cfg.token||'';
  $('#tgChat').value = cfg.chat||'';
  $('#tgOn').checked = !!cfg.on;
  state.flags.tgOn = !!cfg.on;
}
function saveTelegramFromForm(){
  const cfg = {
    token: $('#tgToken').value.trim(),
    chat: $('#tgChat').value.trim(),
    on: $('#tgOn').checked
  };
  saveTelegramConfig(cfg);
  state.flags.tgOn = !!cfg.on;
}

/* ===== CSV last numbers export ===== */
function exportCsv(){
  const rows = [['timestamp','number'], ...state.lastNumbers.map((n,i)=>[Date.now()-i*15000, n])];
  const csv = rows.map(r=>r.join(',')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  a.download = 'sc-tips-log.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ===== UI init ===== */
function initUI(){
  loadTheme();
  $('#btnTimer').onclick = ()=> (state.timer.running? stopTimer() : startTimer());
  $('#strategy').onchange = (ev)=>{ state.selectedStrategy = ev.target.value; showStrategy(); beep('click'); };
  $('#neighbors').oninput = (ev)=>{ state.neighbors = Number(ev.target.value)||2; $('#neighborsVal').textContent = state.neighbors; };
  $('#btnExport').onclick = exportCsv;
  // PRO controls
  $('#btnThemeNavy').onclick = ()=>applyTheme('navy');
  $('#btnThemeGold').onclick = ()=>applyTheme('gold');
  $('#swTiroSeco').onchange = (e)=>{ state.flags.tiroSeco = e.target.checked; };
  $('#btnExportHist').onclick = exportHistoryCsv;
  // Telegram
  loadTelegramIntoForm();
  $('#tgSave').onclick = ()=>{ saveTelegramFromForm(); beep('click'); };
  $('#tgTest').onclick = async ()=>{
    try{ await sendTelegram('Teste SC Tips ✅'); alert('Telegram: enviado!'); }
    catch(e){ alert('Falha ao enviar: ' + e.message); }
  };
}
document.addEventListener('DOMContentLoaded', ()=>{
  renderStrategies();
  renderKpis();
  initUI();
  initRace();
});


/* ===== Manual WS Connect ===== */
let manualWS = null;
function setWsStatus(txt){ const el=$('#wsStatus'); if(el) el.textContent = txt; }
function maskUrl(u){
  if(!$('#wsMask')?.checked) return u;
  try{
    const url = new URL(u);
    if(url.search) url.search = '';
    if(url.hash) url.hash = '';
    return url.toString();
  }catch{ return u.replace(/([?&])(JSESSIONID|EVOSESSIONID|token|videoToken)=[^&]+/gi, '$1$2=***'); }
}
function bindWsControls(){
  const input = $('#wsInput');
  const btnC = $('#wsConnect');
  const btnD = $('#wsDisconnect');
  const saved = localStorage.getItem('sc.ws.url')||'';
  if(input && !input.value) input.value = saved;
  if(btnC) btnC.onclick = ()=>{
    const url = input.value.trim();
    if(!url) return alert('Informe a URL wss:// correta');
    try{
      if(manualWS && manualWS.readyState===WebSocket.OPEN) manualWS.close();
    }catch{}
    setWsStatus('conectando...');
    manualWS = new WebSocket(url);
    manualWS.onopen = ()=>{ setWsStatus('conectado'); localStorage.setItem('sc.ws.url', url); };
    manualWS.onclose = ()=>{ setWsStatus('desconectado'); };
    manualWS.onerror = ()=>{ setWsStatus('erro'); };
    manualWS.onmessage = (ev)=>{
      const log = $('#liveLog');
      const div = document.createElement('div');
      const txt = (typeof ev.data==='string'? ev.data: '[binary]');
      div.textContent = `[WS] ${maskUrl(url)} :: ${txt.slice(0,200)}`;
      log.prepend(div);
    };
  };
  if(btnD) btnD.onclick = ()=>{
    try{ manualWS && manualWS.close(); }catch{}
    setWsStatus('desconectado');
  };
}


// Init
window.addEventListener('DOMContentLoaded', ()=>{ try{ initRace(); renderStrategies(); showStrategy(); bindWsControls(); }catch(e){ console.error(e); } });
