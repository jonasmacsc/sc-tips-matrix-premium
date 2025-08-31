
export function saveTelegramConfig(cfg){
  localStorage.setItem('sc.tg', JSON.stringify(cfg||{}));
}
export function loadTelegramConfig(){
  try{ return JSON.parse(localStorage.getItem('sc.tg')||'{}'); }catch{ return {}; }
}
export async function sendTelegram(msg){
  const cfg = loadTelegramConfig();
  if(!cfg.token || !cfg.chat) throw new Error('Telegram não configurado');
  const url = `https://api.telegram.org/bot${cfg.token}/sendMessage`;
  const res = await fetch(url, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({ chat_id: cfg.chat, text: msg })
  });
  if(!res.ok) throw new Error('Falha ao enviar Telegram');
  return await res.json();
}
