"""Strategie multi-unites de temps de TRADER AI PRO.

D1 : contexte general.
H4 : direction de la structure.
H1 : detection du setup.
M30 : confirmation de la bougie.

Le programme genere des signaux indicatifs et n'execute aucun ordre.
"""

import time
from datetime import datetime, timezone

from analysis_engine import (
analyze_candles,
normalize_candles,
candle_confirms,
)

RR = 3.0

MIN_CANDLES = 30
MAX_SIGNAL_AGE_SECONDS = 2 * 60 * 60
MAX_ENTRY_DRIFT_ATR = 0.5

def _to_engine_candles(candles):
"""Convertit les formats Deriv ou o/h/l/c vers le format du moteur."""
converted = []

for candle in candles or []:
    if not isinstance(candle, dict):
        continue

    if all(
        key in candle
        for key in ("open", "high", "low", "close")
    ):
        converted.append(dict(candle))

    elif all(key in candle for key in ("o", "h", "l", "c")):
        converted.append({
            "epoch": candle.get("t", candle.get("epoch")),
            "open": candle["o"],
            "high": candle["h"],
            "low": candle["l"],
            "close": candle["c"],
        })

if len(converted) > 1:
    epochs = [
        candle.get("epoch", candle.get("time", candle.get("t")))
        for candle in converted
    ]

    try:
        if (
            all(epoch is not None for epoch in epochs)
            and float(epochs[0]) > float(epochs[-1])
        ):
            converted.reverse()
    except (TypeError, ValueError):
        pass

return normalize_candles(converted)

def _trend(candles):
"""Retourne la tendance détectée par le moteur."""
result = analyze_candles(candles)
return result.get("trend", "INDETERMINEE")

def trend_bias(candles):
"""Compatibilité avec les fonctions qui utilisent un biais numérique."""
trend = _trend(_to_engine_candles(candles))

if trend == "HAUSSIERE":
    return 1

if trend == "BAISSIERE":
    return -1

return 0

def _average_range(candles, period=14):
"""Estimation simple de la volatilité moyenne des dernières bougies."""
recent = candles[-period:]

if not recent:
    return 0.0

ranges = []

for candle in recent:
    try:
        high = float(candle["high"])
        low = float(candle["low"])
        candle_range = high - low

        if candle_range > 0:
            ranges.append(candle_range)
    except (KeyError, TypeError, ValueError):
        continue

return sum(ranges) / len(ranges) if ranges else 0.0

def _reject(message):
"""Retourne une liste vide de signaux et un motif de rejet."""
return [], [message]

def find_signals(
symbol,
h1,
h2=None,
h4=None,
d1=None,
price_now=None,
m30=None,
):
"""
Recherche un signal validé par D1, H4, H1 et M30.

h2 est conservé pour compatibilité avec l'ancienne interface.
Il n'est pas utilisé dans cette stratégie.
"""

logs = []

candles_d1 = _to_engine_candles(d1)
candles_h4 = _to_engine_candles(h4)
candles_h1 = _to_engine_candles(h1)
candles_m30 = _to_engine_candles(m30)

datasets = {
    "D1": candles_d1,
    "H4": candles_h4,
    "H1": candles_h1,
    "M30": candles_m30,
}

for timeframe, candles in datasets.items():
    if len(candles) < MIN_CANDLES:
        return _reject(
            "%s : donnees insuffisantes en %s (%s bougies valides)."
            % (symbol, timeframe, len(candles))
        )

trend_d1 = _trend(candles_d1)
trend_h4 = _trend(candles_h4)

# Le D1 ne doit pas contredire la direction envisagee.
# Le H4 doit avoir une direction clairement identifiable.
if trend_h4 not in ("HAUSSIERE", "BAISSIERE"):
    return _reject(
        "%s : tendance H4 indeterminee; signal refuse." % symbol
    )

analysis_h1 = analyze_candles(candles_h1)
signal_h1 = analysis_h1.get("signal")

if not signal_h1:
    return _reject(
        "%s : aucun setup confirme en H1." % symbol
    )

direction = signal_h1.get("direction")

if direction not in ("BUY", "SELL"):
    return _reject(
        "%s : direction H1 invalide." % symbol
    )

expected_trend = (
    "HAUSSIERE" if direction == "BUY" else "BAISSIERE"
)

if trend_h4 != expected_trend:
    return _reject(
        "%s : signal %s refuse, tendance H4 opposee ou incompatible."
        % (symbol, direction)
    )

if trend_d1 in ("HAUSSIERE", "BAISSIERE"):
    if trend_d1 != expected_trend:
        return _reject(
            "%s : signal %s refuse, tendance D1 opposee."
            % (symbol, direction)
        )

# La bougie M30 doit confirmer le sens du signal H1.
last_m30 = candles_m30[-1]

try:
    confirmed = candle_confirms(last_m30, direction)
except (TypeError, ValueError, KeyError):
    confirmed = False

if not confirmed:
    return _reject(
        "%s : setup H1 detecte, mais confirmation M30 absente."
        % symbol
    )

signal = dict(signal_h1)

try:
    entry = float(signal["entry"])
    stop_loss = float(signal["stop_loss"])
    take_profit = float(signal["take_profit"])
except (KeyError, TypeError, ValueError):
    return _reject(
        "%s : entree, Stop Loss ou Take Profit invalide." % symbol
    )

if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
    return _reject(
        "%s : niveaux de prix invalides." % symbol
    )

risk = abs(entry - stop_loss)
reward = abs(take_profit - entry)

if risk <= 0:
    return _reject(
        "%s : risque nul; signal refuse." % symbol
    )

actual_rr = reward / risk

if direction == "BUY":
    if not stop_loss < entry < take_profit:
        return _reject(
            "%s : niveaux BUY incoherents." % symbol
        )
else:
    if not take_profit < entry < stop_loss:
        return _reject(
            "%s : niveaux SELL incoherents." % symbol
        )

# Verifie l'age de la bougie H1 ayant produit le setup.
stamp = candles_h1[-1].get("epoch")

try:
    bar_time = int(float(stamp))
except (TypeError, ValueError):
    return _reject(
        "%s : heure de bougie H1 indisponible." % symbol
    )

age = time.time() - bar_time

if age < 0 or age > MAX_SIGNAL_AGE_SECONDS:
    return _reject(
        "%s : signal H1 trop ancien ou horodatage invalide." % symbol
    )

# Le prix de reference par defaut est la derniere cloture M30.
if price_now is None:
    price_now = candles_m30[-1].get("close")

try:
    current_price = float(price_now)
except (TypeError, ValueError):
    return _reject(
        "%s : prix actuel indisponible." % symbol
    )

if current_price <= 0:
    return _reject(
        "%s : prix actuel invalide." % symbol
    )

# Refuse un signal si le SL ou le TP a deja ete atteint.
if direction == "BUY":
    if current_price <= stop_loss:
        return _reject(
            "%s : le prix a deja atteint ou depasse le SL theorique."
            % symbol
        )
    if current_price >= take_profit:
        return _reject(
            "%s : le TP theorique est deja atteint." % symbol
        )
else:
    if current_price >= stop_loss:
        return _reject(
            "%s : le prix a deja atteint ou depasse le SL theorique."
            % symbol
        )
    if current_price <= take_profit:
        return _reject(
            "%s : le TP theorique est deja atteint." % symbol
        )

# Evite de proposer un setup si le prix s'est trop eloigne de l'entree.
volatility = _average_range(candles_h1)

if volatility > 0:
    drift = abs(current_price - entry)

    if drift > volatility * MAX_ENTRY_DRIFT_ATR:
        return _reject(
            "%s : prix trop eloigne de l'entree H1; signal ignore."
            % symbol
        )

signal.update({
    "symbol": symbol,
    "tf": "H1",
    "confirmation_tf": "M30",
    "bar_time": bar_time,
    "entry": entry,
    "stop_loss": stop_loss,
    "take_profit": take_profit,
    "risk": risk,
    "rr": actual_rr,
    "bias_d1": (
        1 if trend_d1 == "HAUSSIERE"
        else -1 if trend_d1 == "BAISSIERE"
        else 0
    ),
    "bias_h4": (
        1 if trend_h4 == "HAUSSIERE"
        else -1
    ),
    "trend_d1": trend_d1,
    "trend_h4": trend_h4,
    "trend_h1": analysis_h1.get("trend"),
    "trend_m30": _trend(candles_m30),
    "zones": [
        (signal.get("zone_type", "Zone technique"), "H1"),
        ("Confirmation de bougie", "M30"),
    ],
    "key": "%s|%s|H1|%s" % (symbol, direction, bar_time),
})

logs.append(
    "%s : signal %s valide apres controles D1/H4/H1/M30."
    % (symbol, direction)
)

return [signal], logs

def format_message(sig):
"""Prepare le message a envoyer sur Telegram."""
decimals = int(sig.get("decimals", 5))

def fmt(value):
    if value is None:
        return "N/D"
    return ("%.*f" % (decimals, float(value)))

stamp = sig.get("bar_time")

if stamp:
    when = datetime.fromtimestamp(
        int(stamp), timezone.utc
    ).strftime("%d/%m/%Y %H:%M UTC")
else:
    when = "heure indisponible"

zones = sig.get("zones") or []
zones_text = ", ".join(
    "%s (%s)" % (zone[0], zone[1]) for zone in zones
) or "Zone technique"

return (
    "TRADER AI PRO\n\n"
    "Actif : {symbol}\n"
    "Direction : {direction}\n"
    "Setup : H1 confirme par M30\n"
    "Tendance D1 : {d1}\n"
    "Tendance H4 : {h4}\n"
    "Entree indicative : {entry}\n"
    "Stop Loss : {sl}\n"
    "Take Profit : {tp}\n"
    "RR estime : 1:{rr:.2f}\n"
    "Confluences : {zones}\n"
    "Bougie du setup : {when}\n\n"
    "Signal indicatif uniquement. Aucun ordre n'est execute. "
    "Verifier le graphique, les frais et le risque avant toute decision."
).format(
    symbol=sig.get("symbol", "N/D"),
    direction=sig.get("direction", "N/D"),
    d1=sig.get("trend_d1", "INDETERMINEE"),
    h4=sig.get("trend_h4", "INDETERMINEE"),
    entry=fmt(sig.get("entry")),
    sl=fmt(sig.get("stop_loss")),
    tp=fmt(sig.get("take_profit")),
    rr=float(sig.get("rr", RR)),
    zones=zones_text,
    when=when,
)
