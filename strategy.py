
"""TRADER AI PRO - Strategie multi-timeframe.
Contexte D1, direction H4 et setup H1.
La confirmation M30 et le RR minimal ne sont pas obligatoires.
Les signaux sont indicatifs. Aucun ordre n'est execute.
"""

from analysis_engine import analyze_candles, normalize_candles

MIN_CANDLES = 30
MAX_ENTRY_DRIFT = 0.005


def _get_candles(data):
    """Accepte une liste de bougies ou la reponse de get_candles."""
    if isinstance(data, dict):
        data = data.get("candles", [])

    if not isinstance(data, list):
        return []

    return normalize_candles(data)


def _direction(value):
    """Convertit les tendances en BUY, SELL ou NEUTRAL."""
    if not isinstance(value, str):
        return "NEUTRAL"

    value = value.strip().upper()

    if value in (
        "BUY", "BULLISH", "UP", "LONG",
        "HAUSSIERE", "HAUSSIER",
    ):
        return "BUY"

    if value in (
        "SELL", "BEARISH", "DOWN", "SHORT",
        "BAISSIERE", "BAISSIER",
    ):
        return "SELL"

    return "NEUTRAL"


def _analyze(candles):
    """Execute l'analyse technique."""
    if len(candles) < MIN_CANDLES:
        return {}

    try:
        result = analyze_candles(candles)
    except (TypeError, ValueError, KeyError, IndexError):
        return {}

    return result if isinstance(result, dict) else {}


def _extract_setup(result):
    """Extrait et valide le setup H1 produit par le moteur."""
    if not isinstance(result, dict):
        return None

    setup = result.get("signal")

    if not isinstance(setup, dict):
        return None

    direction = _direction(setup.get("direction"))

    if direction not in ("BUY", "SELL"):
        return None

    try:
        entry = float(setup["entry"])
        stop_loss = float(setup["stop_loss"])
        take_profit = float(setup["take_profit"])
    except (KeyError, TypeError, ValueError):
        return None

    if min(entry, stop_loss, take_profit) <= 0:
        return None

    if direction == "BUY":
        if not stop_loss < entry < take_profit:
            return None
    else:
        if not take_profit < entry < stop_loss:
            return None

    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)

    if risk <= 0:
        return None

    # Aucun RR minimal : on calcule simplement le ratio réel.
    rr = reward / risk

    return {
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr": rr,
        "reason": setup.get("reason", ""),
        "bar_time": setup.get("bar_time", 0),
        "level": setup.get("level"),
    }


def find_signals(
    symbol,
    h1,
    h2=None,
    h4=None,
    d1=None,
    price_now=None,
    m30=None,
):
    """Recherche un setup H1 concordant avec H4 et D1.
    M30 est facultatif et aucune confirmation M30 n'est exigée.
    Aucun ratio Reward/Risk minimal n'est impose.
    """

    candles_h1 = _get_candles(h1)
    candles_h4 = _get_candles(h4)
    candles_d1 = _get_candles(d1)

    # Seuls H1, H4 et D1 sont obligatoires.
    if any(
        len(candles) < MIN_CANDLES
        for candles in (candles_h1, candles_h4, candles_d1)
    ):
        return []

    analysis_d1 = _analyze(candles_d1)
    analysis_h4 = _analyze(candles_h4)
    analysis_h1 = _analyze(candles_h1)

    direction_d1 = _direction(analysis_d1.get("trend"))
    direction_h4 = _direction(analysis_h4.get("trend"))
    direction_h1 = _direction(analysis_h1.get("trend"))

    # H4 doit fournir une direction exploitable.
    if direction_h4 not in ("BUY", "SELL"):
        return []

    # D1 ne doit pas contredire H4 lorsqu'il donne une direction claire.
    if (
        direction_d1 in ("BUY", "SELL")
        and direction_d1 != direction_h4
    ):
        return []

    # H1 doit être dans le même sens que H4.
    if direction_h1 != direction_h4:
        return []

    # Le moteur H1 doit fournir un setup avec des niveaux valides.
    setup = _extract_setup(analysis_h1)

    if setup is None:
        return []

    if setup["direction"] != direction_h4:
        return []

    entry = setup["entry"]

    # Si un prix actuel est fourni, éviter une entrée trop éloignée.
    if price_now is not None:
        try:
            current_price = float(price_now)
        except (TypeError, ValueError):
            return []

        if current_price <= 0:
            return []

        drift = abs(current_price - entry) / entry

        if drift > MAX_ENTRY_DRIFT:
            return []

    stop_loss = setup["stop_loss"]
    take_profit = setup["take_profit"]

    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)

    if risk <= 0:
        return []

    rr = reward / risk

    return [{
        "symbol": symbol,
        "direction": setup["direction"],
        "signal": setup["direction"],
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr": round(rr, 2),
        "timeframe": "H1",
        "confirmation_timeframe": "Aucune confirmation M30 obligatoire",
        "trend_h4": direction_h4,
        "trend_d1": direction_d1,
        "trend_h1": direction_h1,
        "status": "CONFIRMED",
        "reason": setup["reason"],
        "bar_time": setup["bar_time"],
    }]


def format_message(signal):
    """Formate le signal pour Telegram."""
    if not isinstance(signal, dict):
        return "Signal invalide."

    symbol = signal.get("symbol", "Inconnu")
    direction = signal.get(
        "direction",
        signal.get("signal", "UNKNOWN"),
    )

    entry = signal.get("entry")
    stop_loss = signal.get("stop_loss")
    take_profit = signal.get("take_profit")
    rr = signal.get("rr", "N/A")
    reason = signal.get("reason", "")

    message = (
        "TRADER AI PRO\n"
        "--------------------\n"
        f"Actif : {symbol}\n"
        f"Direction : {direction}\n"
        f"Entree : {entry}\n"
        f"Stop Loss : {stop_loss}\n"
        f"Take Profit : {take_profit}\n"
        f"Risk/Reward : 1:{rr}\n"
        "Analyse : D1 + H4 + H1\n"
        "Confirmation M30 : non obligatoire\n"
        "RR minimal : aucun\n"
        "Signal indicatif - aucun ordre execute."
    )

    if reason:
        message += f"\nConfluences : {reason}"

    return message
        
