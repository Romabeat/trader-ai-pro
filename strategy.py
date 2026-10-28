
"""Strategie multi-timeframe pour Trader AI Pro.
Les signaux sont indicatifs. Aucun ordre n'est execute.
"""

from analysis_engine import analyze_candles, normalize_candles, candle_confirms

MIN_CANDLES = 30
MAX_ENTRY_DRIFT = 0.5


def _get_candles(data):
    """Accepte une liste de bougies ou la reponse de get_candles."""
    if isinstance(data, dict):
        data = data.get("candles", [])
    if not isinstance(data, list):
        return []
    return normalize_candles(data)


def _last_close(candles):
    if not candles:
        return None
    return float(candles[-1]["close"])


def _trend(result):
    """Recupere une direction de tendance depuis le resultat d'analyse."""
    if not isinstance(result, dict):
        return "NEUTRAL"

    for key in ("trend", "direction", "bias"):
        value = result.get(key)
        if isinstance(value, str):
            value = value.upper()
            if value in ("BUY", "BULLISH", "UP", "LONG"):
                return "BUY"
            if value in ("SELL", "BEARISH", "DOWN", "SHORT"):
                return "SELL"

    return "NEUTRAL"


def _analyze(candles):
    if len(candles) < MIN_CANDLES:
        return {}
    try:
        result = analyze_candles(candles)
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError, KeyError, IndexError):
        return {}


def find_signals(symbol, h1, h2=None, h4=None, d1=None,
                 price_now=None, m30=None):
    """Cherche un signal concordant D1/H4/H1 avec confirmation M30."""
    candles_h1 = _get_candles(h1)
    candles_h4 = _get_candles(h4)
    candles_d1 = _get_candles(d1)
    candles_m30 = _get_candles(m30)

    if any(len(c) < MIN_CANDLES for c in
           (candles_h1, candles_h4, candles_d1, candles_m30)):
        return []

    analysis_h1 = _analyze(candles_h1)
    analysis_h4 = _analyze(candles_h4)
    analysis_d1 = _analyze(candles_d1)

    trend_h4 = _trend(analysis_h4)
    trend_d1 = _trend(analysis_d1)

    if trend_h4 not in ("BUY", "SELL"):
        return []

    if trend_d1 in ("BUY", "SELL") and trend_d1 != trend_h4:
        return []

    setup_direction = _trend(analysis_h1)
    if setup_direction != trend_h4:
        return []

    last_m30 = candles_m30[-1]
    try:
        confirmed = candle_confirms(last_m30, trend_h4)
    except (TypeError, ValueError, KeyError, IndexError):
        return []

    if not confirmed:
        return []

    current_close = _last_close(candles_m30)
    if current_close is None:
        return []

    entry = float(price_now) if price_now is not None else current_close

    # Refuse une entree trop eloignee de la derniere cloture M30.
    if entry <= 0 or current_close <= 0:
        return []

    if entry != current_close:
        if abs(entry - current_close) / current_close > 0.005:
            return []

    stop_loss = None
    take_profit = None

    for key in ("stop_loss", "sl"):
        value = analysis_h1.get(key)
        if isinstance(value, (int, float)) and value > 0:
            stop_loss = float(value)
            break

    for key in ("take_profit", "tp"):
        value = analysis_h1.get(key)
        if isinstance(value, (int, float)) and value > 0:
            take_profit = float(value)
            break

    # Si l'analyse ne fournit pas des niveaux coherents, aucun signal.
    if stop_loss is None or take_profit is None:
        return []

    if trend_h4 == "BUY":
        if not stop_loss < entry < take_profit:
            return []
    else:
        if not take_profit < entry < stop_loss:
            return []

    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)

    if risk <= 0 or reward / risk < 2.9:
        return []

    return [{
        "symbol": symbol,
        "direction": trend_h4,
        "signal": trend_h4,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr": round(reward / risk, 2),
        "timeframe": "H1",
        "confirmation_timeframe": "M30",
        "trend_h4": trend_h4,
        "trend_d1": trend_d1,
        "status": "CONFIRMED",
    }]


def format_message(signal):
    """Formate un signal pour Telegram."""
    if not isinstance(signal, dict):
        return "Signal invalide."

    symbol = signal.get("symbol", "Inconnu")
    direction = signal.get("direction", signal.get("signal", "UNKNOWN"))
    entry = signal.get("entry")
    stop_loss = signal.get("stop_loss")
    take_profit = signal.get("take_profit")
    rr = signal.get("rr", "N/A")

    return (
        f"TRADER AI PRO\n"
        f"Actif : {symbol}\n"
        f"Direction : {direction}\n"
        f"Entree : {entry}\n"
        f"Stop Loss : {stop_loss}\n"
        f"Take Profit : {take_profit}\n"
        f"Risk/Reward : 1:{rr}\n"
        f"Confirmation : H4 + D1 + H1 + M30\n"
        f"Signal indicatif - aucun ordre execute."
                     )
                     
