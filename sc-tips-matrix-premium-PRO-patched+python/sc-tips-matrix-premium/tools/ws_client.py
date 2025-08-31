#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SC Tips • WS Client (Python)
---------------------------------
Cliente WebSocket simples para conectar em uma URL wss:// de roleta,
registrar mensagens, tentar extrair o número vencedor e (opcionalmente)
enviar alertas no Telegram.

Uso básico:
  python3 ws_client.py --url "wss://..."
  python3 ws_client.py --url "wss://..." --csv out.csv --mask

Telegram (opcional):
  export TG_TOKEN="123456:ABC..."
  export TG_CHAT="-1002211353341"
  python3 ws_client.py --url "wss://..." --tg

Dependências:
  pip install websockets requests

Obs.: este script é educativo. Respeite os Termos de Uso das plataformas.
"""
import os
import re
import csv
import json
import time
import argparse
import asyncio
from datetime import datetime

try:
    import websockets  # type: ignore
except Exception as e:
    print("[WARN] Biblioteca 'websockets' não instalada. Rode: pip install websockets")
    raise

try:
    import requests  # type: ignore
except Exception:
    requests = None  # só necessário se usar Telegram


RE_JSON_NUMBER_FIELDS = re.compile(r'\"(?:number|winningNumber)\"\s*:\s*(\d+)', re.I)
RE_EVOLUTION_TYPE      = re.compile(r'\"type\"\s*:\s*\"roulette\.winSpots\"', re.I)
RE_EVOLUTION_RESULT    = re.compile(r'\"number\"\s*:\s*(\d+)', re.I)
RE_DEALER              = re.compile(r'\"dealer\"\s*:\s*\"([^\"]+)\"', re.I)


def mask_url(u: str) -> str:
    try:
        # remove query e hash para não vazar tokens
        from urllib.parse import urlparse, urlunparse
        p = urlparse(u)
        return urlunparse((p.scheme, p.netloc, p.path, '', '', ''))
    except Exception:
        return re.sub(r'([?&])(JSESSIONID|EVOSESSIONID|token|videoToken)=[^&]+', r'\1\2=***', u, flags=re.I)


def parse_number_and_dealer(msg: str):
    """
    Tenta extrair número vencedor e dealer de mensagens comuns de Evolution/Pragmatic.
    Retorna (numero:int|None, dealer:str|None).
    """
    num = None
    dealer = None

    # Evolution "roulette.winSpots"
    if RE_EVOLUTION_TYPE.search(msg):
        m = RE_EVOLUTION_RESULT.search(msg)
        if m:
            num = int(m.group(1))
        d = RE_DEALER.search(msg)
        if d:
            dealer = d.group(1)

    # Campos genéricos "number" ou "winningNumber"
    if num is None:
        m2 = RE_JSON_NUMBER_FIELDS.search(msg)
        if m2:
            num = int(m2.group(1))

    if dealer is None:
        d2 = RE_DEALER.search(msg)
        if d2:
            dealer = d2.group(1)

    return num, dealer


async def send_telegram(text: str):
    token = os.environ.get("TG_TOKEN")
    chat  = os.environ.get("TG_CHAT")
    if not token or not chat:
        print("[TG] Variáveis TG_TOKEN / TG_CHAT não definidas — pulando envio.")
        return
    if requests is None:
        print("[TG] 'requests' não está disponível. Instale com: pip install requests")
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={"chat_id": chat, "text": text})
        if not r.ok:
            print(f"[TG] Falha ao enviar: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[TG] Erro: {e}")


async def run_ws(url: str, csv_path: str = None, mask: bool = False, tg: bool = False):
    backoff = 1
    while True:
        try:
            show_url = mask_url(url) if mask else url
            print(f"[WS] Conectando: {show_url}")
            async with websockets.connect(url, max_size=None) as ws:
                print("[WS] Conectado.")
                backoff = 1
                # prepara CSV se solicitado
                writer = None
                fcsv = None
                if csv_path:
                    fcsv = open(csv_path, "a", newline="", encoding="utf-8")
                    writer = csv.writer(fcsv)
                    if fcsv.tell() == 0:
                        writer.writerow(["timestamp", "number", "dealer", "rawPreview"])

                while True:
                    raw = await ws.recv()
                    if isinstance(raw, bytes):
                        try:
                            msg = raw.decode("utf-8", "ignore")
                        except Exception:
                            msg = "<binary>"
                    else:
                        msg = str(raw)

                    # log básico
                    tstamp = datetime.now().strftime("%H:%M:%S")
                    preview = msg[:300].replace("\n", " ")
                    print(f"[{tstamp}] {preview}")

                    # parse
                    n, dealer = parse_number_and_dealer(msg)
                    if n is not None:
                        print(f"   → Número detectado: {n}  Dealer: {dealer or '-'}")
                        if writer:
                            writer.writerow([int(time.time()*1000), n, dealer or "", preview])
                            fcsv.flush()
                        if tg:
                            await send_telegram(f"🎯 Número detectado: {n}  Dealer: {dealer or '-'}")

        except (asyncio.CancelledError, KeyboardInterrupt):
            print("[WS] Encerrado pelo usuário.")
            break
        except Exception as e:
            print(f"[WS] Erro: {e}. Reconnect em {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)


def main():
    ap = argparse.ArgumentParser(description="SC Tips • WS Client (Python)")
    ap.add_argument("--url", required=True, help="URL wss:// para conectar")
    ap.add_argument("--csv", default=None, help="Caminho do CSV de saída (opcional)")
    ap.add_argument("--mask", action="store_true", help="Mascarar tokens na URL ao exibir logs")
    ap.add_argument("--tg", action="store_true", help="Enviar alertas para Telegram (usa TG_TOKEN / TG_CHAT)")
    args = ap.parse_args()

    asyncio.run(run_ws(args.url, args.csv, args.mask, args.tg))


if __name__ == "__main__":
    main()
