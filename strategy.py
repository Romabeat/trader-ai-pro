"""Interface de stratégie TRADER AI PRO. Cette version n'exécute aucun ordre et ne fait aucun appel réseau. Elle réutilise le moteur principal analysis_engine pour éviter deux logiques de trading qui se contredisent. Les arguments H1/H2/H4/D1 peuvent être fournis sous forme Deriv (chronologique, clés open/high/low/close/epoch) ou en série (clés o/h/l/c/t). """
from datetime import datetime, timezone
from analysis_engine import analyze_candles, normalize_candles

TRIGGER_TFS = ("H1", "H2")
RR = 3.0


def _to_engine_candles(candles):
    converted = []
    for c in candles or []:
        if not isinstance(c, dict):
            continue
        if all(k in c for k in ("open", "high", "low", "close")):
            converted.append(c)
        elif all(k in c for k in ("o", "h", "l", "c")):
            converted.append({"epoch": c.get("t", c.get("epoch")), "open": c["o"],
                              "high": c["h"], "low": c["l"], "close": c["c"]})
    # L'ancien moteur strategy recevait des séries récentes -> anciennes.
    # Détection prudente via le timestamp, puis normalisation chronologique.
    if len(converted) > 1:
        epochs = [c.get("epoch", c.get("time", c.get("t"))) for c in converted]
        try:
            if all(x is not None for x in epochs) and float(epochs[0]) > float(epochs[-1]):
                converted.reverse()
        except (TypeError, ValueError):
            pass
    return normalize_candles(converted)


def trend_bias(candles):
    """Renvoie +1 haussier, -1 baissier, 0 neutre/indisponible."""
    result = analyze_candles(_to_engine_candles(candles))
    trend = result.get("trend")
    return 1 if trend == "HAUSSIERE" else -1 if trend == "BAISSIERE" else 0


def find_signals(symbol, h1, h2, h4, d1, price_now=None):
    """Retourne (liste_de_signaux, journaux), compatible avec l'ancienne API. Les signaux sont issus du moteur principal. D1/H4 servent de contexte; si ces tendances sont connues et opposées à l'entrée, le signal est écarté. """
    logs, signals = [], []
    context_d1 = analyze_candles(_to_engine_candles(d1))
    context_h4 = analyze_candles(_to_engine_candles(h4))
    context_trends = (context_d1.get("trend"), context_h4.get("trend"))

    for tf, raw in (("H1", h1), ("H2", h2)):
        if tf not in TRIGGER_TFS:
            continue
        candles = _to_engine_candles(raw)
        analysis = analyze_candles(candles)
        signal = analysis.get("signal")
        if not signal:
            logs.append("%s : aucun signal confirmé en %s (%s bougies valides)" %
                        (symbol, tf, analysis.get("candle_count", 0)))
            continue
        direction = signal["direction"]
        wanted = "HAUSSIERE" if direction == "BUY" else "BAISSIERE"
        known = [t for t in context_trends if t in ("HAUSSIERE", "BAISSIERE")]
        if known and any(t != wanted for t in known):
            logs.append("%s : signal %s en %s écarté, tendance D1/H4 non concordante" %
                        (symbol, direction, tf))
            continue
        stamp = candles[-1].get("epoch") if candles else None
        signal = dict(signal)
        signal.update({"symbol": symbol, "tf": tf, "bar_time": int(stamp or 0),
                       "decimals": 5, "risk": abs(signal["entry"]-signal["stop_loss"]),
                       "risk_atr": None, "zones": [(signal.get("zone_type", "Zone technique"), tf)],
                       "bias_d1": trend_bias(d1), "bias_w1": 0,
                       "level": signal.get("level", signal["entry"]),
                       "depth_atr": None, "sl_buffer_pips": None, "pip_size_used": None,
                       "key": "%s|%s|%s" % (symbol, direction, signal["entry"])})
        if price_now is not None:
            try:
                price = float(price_now)
                if (direction == "BUY" and price >= signal["take_profit"]) or (direction == "SELL" and price <= signal["take_profit"]):
                    logs.append("%s : signal %s déjà arrivé au TP théorique; ignoré" % (symbol, direction))
                    continue
            except (TypeError, ValueError):
                pass
        signals.append(signal)

    if len({s["direction"] for s in signals}) > 1:
        logs.append("%s : signaux BUY et SELL contradictoires; aucun signal retenu" % symbol)
        return [], logs
    return signals, logs


def format_message(sig):
    """Formate un signal pour Telegram sans exposer de données sensibles."""
    decimals = int(sig.get("decimals", 5))
    fmt = lambda value: ("%.*f" % (decimals, float(value))) if value is not None else "N/D"
    stamp = sig.get("bar_time")
    when = datetime.fromtimestamp(stamp, timezone.utc).strftime("%d/%m/%Y %H:%M UTC") if stamp else "heure indisponible"
    zones = sig.get("zones") or []
    zones_text = ", ".join("%s (%s)" % (z[0], z[1]) for z in zones) or sig.get("zone_type", "Zone technique")
    return (
        "TRADER AI PRO\n\n"
        "Actif : {symbol}\nDirection : {direction}\nUnité : {tf}\n"
        "Entrée indicative : {entry}\nStop Loss : {sl}\nTake Profit : {tp}\n"
        "Risque/rendement visé : 1:3\nZone : {zones}\nBougie : {when}\n\n"
        "Signal indicatif uniquement. Vérifier le graphique et le risque avant toute décision."
    ).format(symbol=sig.get("symbol", "N/D"), direction=sig.get("direction", "N/D"),
             tf=sig.get("tf", "N/D"), entry=fmt(sig.get("entry")), sl=fmt(sig.get("stop_loss")),
             tp=fmt(sig.get("take_profit")), zones=zones_text, when=when)
