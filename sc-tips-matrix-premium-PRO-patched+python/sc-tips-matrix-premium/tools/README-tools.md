
# SC Tips – Ferramentas (Python)

## 1) WS Client (ws_client.py)
Cliente WebSocket que conecta em uma URL `wss://`, registra mensagens, tenta extrair o **número vencedor** e (opcionalmente) envia alertas no **Telegram**.

### Dependências
```bash
pip install websockets requests
```

### Uso mínimo
```bash
python3 tools/ws_client.py --url "wss://SEU_ENDPOINT_AQUI"
```

### CSV + mascarar URL
```bash
python3 tools/ws_client.py --url "wss://SEU_ENDPOINT_AQUI" --csv out.csv --mask
```

### Telegram opcional
```bash
export TG_TOKEN="SEU_BOT_TOKEN"
export TG_CHAT="-1002211353341"
python3 tools/ws_client.py --url "wss://SEU_ENDPOINT_AQUI" --tg
```

> O script tenta reconhecer padrões comuns do Evolution/Pragmatic (e.g. `roulette.winSpots`, `winningNumber`, `dealer`).
> Use de forma ética e dentro dos Termos de Uso dos provedores.
