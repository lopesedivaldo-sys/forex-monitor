#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║       FOREX HAMMER MONITOR — Alertas via Telegram            ║
║  Pares: CAD/CHF, USD/JPY, USD/CAD, USD/CHF, NZD/USD         ║
║  Timeframe: 15 minutos                                       ║
╚══════════════════════════════════════════════════════════════╝

CONFIGURAÇÃO RÁPIDA:
  1. Crie um bot no Telegram: fale com @BotFather → /newbot
  2. Copie o TOKEN gerado e cole em TELEGRAM_TOKEN abaixo
  3. Envie uma mensagem para seu bot e acesse:
     https://api.telegram.org/bot<TOKEN>/getUpdates
     Copie o "chat_id" e cole em TELEGRAM_CHAT_ID abaixo
  4. Instale as dependências:
     pip install yfinance requests pandas
  5. Execute:
     python forex_hammer_monitor.py

DEPENDÊNCIAS:
  pip install yfinance requests pandas
"""

import time
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone

# ─────────────────────────────────────────────
#  ⚙️  CONFIGURAÇÕES — EDITE AQUI
# ─────────────────────────────────────────────
TELEGRAM_TOKEN   = "8745834512:AAHDW1FJuMKQSVVP4o1ZACkynihRKY6jQOo"
TELEGRAM_CHAT_ID = "6797608165"

# Pares monitorados (Yahoo Finance usa sufixo =X para Forex)
PAIRS = {
    "CAD/CHF": "CADCHF=X",
    "USD/JPY": "USDJPY=X",
    "USD/CAD": "USDCAD=X",
    "USD/CHF": "USDCHF=X",
    "NZD/USD": "NZDUSD=X",
}

TIMEFRAME        = "15m"          # Intervalo das velas
CHECK_INTERVAL   = 60 * 15       # Verifica a cada 15 minutos (em segundos)
CANDLES_HISTORY  = 50            # Velas anteriores para contexto de tendência
# ─────────────────────────────────────────────


def send_telegram(message: str) -> bool:
    """Envia mensagem via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_notification": False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[ERRO Telegram] {e}")
        return False


def fetch_candles(ticker: str, period: str = "1d", interval: str = "15m") -> pd.DataFrame:
    """Busca candles do Yahoo Finance."""
    try:
        df = yf.download(ticker, period=period, interval=interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return pd.DataFrame()
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df = df[["Open", "High", "Low", "Close"]].dropna()
        df.columns = ["open", "high", "low", "close"]
        return df
    except Exception as e:
        print(f"[ERRO fetch {ticker}] {e}")
        return pd.DataFrame()


def classify_hammer(open_: float, high: float, low: float, close: float) -> dict | None:
    """
    Detecta todos os tipos de martelo (hammer):

    ┌────────────────────────────────────────────────────────┐
    │  TIPOS DETECTADOS                                      │
    │                                                        │
    │  1. Hammer (Martelo)          — corpo no topo,         │
    │     sombra inferior longa (≥ 2x corpo)                 │
    │                                                        │
    │  2. Inverted Hammer           — corpo na base,         │
    │  (Martelo Invertido)            sombra superior longa  │
    │                                                        │
    │  3. Hanging Man               — igual ao Hammer        │
    │  (Homem Enforcado)              mas em tendência alta   │
    │                                                        │
    │  4. Shooting Star             — igual ao Inverted      │
    │  (Estrela Cadente)              Hammer em tendência alta│
    │                                                        │
    │  5. Short Wick Hammer         — Martelo com pavil      │
    │  (Martelo Pavil Curto)          inferior moderado      │
    │                                                        │
    │  6. Dragonfly Doji            — corpo mínimo + sombra  │
    │     inferior muito longa                               │
    │                                                        │
    │  7. Gravestone Doji           — corpo mínimo + sombra  │
    │     superior muito longa                               │
    └────────────────────────────────────────────────────────┘
    """
    total_range = high - low
    if total_range < 1e-10:
        return None

    body        = abs(close - open_)
    upper_wick  = high - max(open_, close)
    lower_wick  = min(open_, close) - low
    body_ratio  = body / total_range
    bullish     = close >= open_

    # ── PARÂMETROS ───────────────────────────────────────────
    BODY_MAX       = 0.35   # corpo pequeno (< 35% do range)
    WICK_LONG      = 0.55   # sombra longa (≥ 55% do range)
    WICK_SHORT_MAX = 0.20   # sombra oposta pequena (< 20%)
    SHORT_WICK_MIN = 0.30   # pavil curto: sombra ≥ 30%
    DOJI_BODY_MAX  = 0.08   # corpo doji < 8%
    # ─────────────────────────────────────────────────────────

    lower_ratio = lower_wick / total_range
    upper_ratio = upper_wick / total_range

    # 6. Dragonfly Doji
    if body_ratio <= DOJI_BODY_MAX and lower_ratio >= WICK_LONG and upper_ratio <= WICK_SHORT_MAX:
        return {
            "name": "Dragonfly Doji",
            "emoji": "🐉",
            "signal": "ALTA (reversão bullish)",
            "strength": "Forte",
            "confidence": 8,
        }

    # 7. Gravestone Doji
    if body_ratio <= DOJI_BODY_MAX and upper_ratio >= WICK_LONG and lower_ratio <= WICK_SHORT_MAX:
        return {
            "name": "Gravestone Doji",
            "emoji": "🪦",
            "signal": "BAIXA (reversão bearish)",
            "strength": "Forte",
            "confidence": 8,
        }

    # Exige corpo pequeno para os demais tipos
    if body_ratio > BODY_MAX:
        return None

    # 1. Hammer (Martelo clássico)
    if lower_ratio >= WICK_LONG and upper_ratio <= WICK_SHORT_MAX:
        return {
            "name": "Hammer (Martelo)",
            "emoji": "🔨",
            "signal": "ALTA (reversão bullish)",
            "strength": "Forte",
            "confidence": 9,
        }

    # 2. Inverted Hammer (Martelo Invertido)
    if upper_ratio >= WICK_LONG and lower_ratio <= WICK_SHORT_MAX:
        return {
            "name": "Inverted Hammer (Martelo Invertido)",
            "emoji": "🔨↑",
            "signal": "ALTA (possível reversão)",
            "strength": "Moderada",
            "confidence": 7,
        }

    # 3. Hanging Man / 4. Shooting Star — identificados pela tendência
    # (detectamos o shape; a tendência é verificada fora)
    if lower_ratio >= WICK_LONG and upper_ratio <= WICK_SHORT_MAX:
        return {
            "name": "Hanging Man (Homem Enforcado)",
            "emoji": "🪢",
            "signal": "BAIXA (atenção — em topo)",
            "strength": "Moderada",
            "confidence": 7,
        }

    if upper_ratio >= WICK_LONG and lower_ratio <= WICK_SHORT_MAX:
        return {
            "name": "Shooting Star (Estrela Cadente)",
            "emoji": "⭐",
            "signal": "BAIXA (reversão bearish)",
            "strength": "Forte",
            "confidence": 8,
        }

    # 5. Short Wick Hammer (Martelo Pavil Curto)
    if lower_ratio >= SHORT_WICK_MIN and lower_ratio < WICK_LONG and upper_ratio <= WICK_SHORT_MAX:
        return {
            "name": "Short Wick Hammer (Martelo Pavil Curto)",
            "emoji": "🔩",
            "signal": "ALTA (sinal fraco — confirmar)",
            "strength": "Fraca",
            "confidence": 5,
        }

    return None


def get_trend(df: pd.DataFrame, idx: int, lookback: int = 10) -> str:
    """Tendência simples: compara média das últimas N velas."""
    if idx < lookback:
        return "indefinida"
    window = df["close"].iloc[idx - lookback: idx]
    first_half  = window[:lookback // 2].mean()
    second_half = window[lookback // 2:].mean()
    if second_half > first_half * 1.001:
        return "alta"
    elif second_half < first_half * 0.999:
        return "baixa"
    return "lateral"


def format_alert(pair: str, candle: pd.Series, pattern: dict, trend: str) -> str:
    """Formata a mensagem de alerta para o Telegram."""
    ts  = candle.name
    if hasattr(ts, "strftime"):
        ts_str = ts.strftime("%d/%m/%Y %H:%M") + " UTC"
    else:
        ts_str = str(ts)

    variation = (candle["close"] - candle["open"]) / candle["open"] * 100
    candle_type = "🟢 Alta" if candle["close"] >= candle["open"] else "🔴 Baixa"

    msg = (
        f"<b>📊 ALERTA FOREX — {pattern['emoji']} {pair}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Padrão:</b> {pattern['name']}\n"
        f"<b>Sinal:</b> {pattern['signal']}\n"
        f"<b>Força:</b> {pattern['strength']}  |  <b>Confiança:</b> {pattern['confidence']}/10\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Vela:</b> {candle_type}  ({variation:+.3f}%)\n"
        f"<b>Abertura:</b>  {candle['open']:.5f}\n"
        f"<b>Máxima:</b>   {candle['high']:.5f}\n"
        f"<b>Mínima:</b>   {candle['low']:.5f}\n"
        f"<b>Fechamento:</b> {candle['close']:.5f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Tendência:</b> {trend.upper()}\n"
        f"<b>Timeframe:</b> 15 minutos\n"
        f"<b>Horário:</b> {ts_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>Use sempre Stop Loss. Não é recomendação de investimento.</i>"
    )
    return msg


def check_pair(pair_name: str, ticker: str, last_alerts: dict) -> None:
    """Verifica um par e envia alerta se detectar padrão de martelo."""
    df = fetch_candles(ticker, period="1d", interval=TIMEFRAME)
    if df is None or len(df) < 5:
        print(f"  [{pair_name}] Sem dados suficientes.")
        return

    # Analisa a penúltima vela (a última pode estar incompleta)
    idx    = len(df) - 2
    candle = df.iloc[idx]
    ts_key = str(candle.name)

    # Evita alertar a mesma vela duas vezes
    if last_alerts.get(pair_name) == ts_key:
        print(f"  [{pair_name}] Vela já alertada: {ts_key}")
        return

    pattern = classify_hammer(
        candle["open"], candle["high"], candle["low"], candle["close"]
    )

    if pattern:
        trend   = get_trend(df, idx)
        message = format_alert(pair_name, candle, pattern, trend)
        print(f"\n  🔔 PADRÃO DETECTADO em {pair_name}: {pattern['name']}")
        if send_telegram(message):
            last_alerts[pair_name] = ts_key
            print(f"  ✅ Alerta enviado ao Telegram!")
        else:
            print(f"  ❌ Falha ao enviar alerta.")
    else:
        print(f"  [{pair_name}] Nenhum padrão de martelo detectado.")


def validate_config() -> bool:
    """Valida configurações básicas antes de iniciar."""
    if "SEU_TOKEN" in TELEGRAM_TOKEN or "SEU_CHAT" in TELEGRAM_CHAT_ID:
        print("❌ ERRO: Configure TELEGRAM_TOKEN e TELEGRAM_CHAT_ID no início do script!")
        print("   Veja as instruções no topo do arquivo.")
        return False
    return True


def startup_message() -> None:
    """Envia mensagem de inicialização."""
    pairs_list = "\n".join([f"  • {p}" for p in PAIRS.keys()])
    msg = (
        "🚀 <b>Forex Hammer Monitor — INICIADO</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Pares monitorados:</b>\n{pairs_list}\n"
        f"<b>Timeframe:</b> 15 minutos\n"
        f"<b>Padrões:</b> Todos os tipos de Martelo\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Bot ativo. Alertas serão enviados aqui."
    )
    send_telegram(msg)


def main() -> None:
    print("=" * 60)
    print("  FOREX HAMMER MONITOR")
    print(f"  Pares: {', '.join(PAIRS.keys())}")
    print(f"  Timeframe: {TIMEFRAME} | Verificação: a cada {CHECK_INTERVAL // 60} min")
    print("=" * 60)

    if not validate_config():
        return

    startup_message()
    last_alerts: dict[str, str] = {}

    while True:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n🔍 Verificando às {now}")
        print("-" * 40)

        for pair_name, ticker in PAIRS.items():
            check_pair(pair_name, ticker, last_alerts)
            time.sleep(2)  # Respeita rate limit do Yahoo Finance

        next_check = datetime.now(timezone.utc)
        print(f"\n⏳ Próxima verificação em {CHECK_INTERVAL // 60} minutos...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
