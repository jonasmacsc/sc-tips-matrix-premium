SC TIPS • RealPrecision v3.5.5 — 3 Roletas + 23 Estratégias + Auto Telegram

▶️ Rodar local
  pip install -r requirements.txt
  python main.py

🌐 Deploy Vercel
  vercel --prod

Rotas úteis
  /                  → página com painel
  /api/seq/<roleta> → sequência capturada (immersive|brazilian|megafire)
  /api/analyze/<roleta>?sid=ia_top5&minconf=70 → análise
  /api/send/<roleta>?sid=ia_top5 → envia mensagem formatada ao Telegram

Env (padrões incluídos em vercel.json)
  TG_TOKEN, TG_CHAT, REFRESH_SECS, SEND_COOLDOWN, SEND_THRESHOLD, AUTO_SEND_DEFAULT
