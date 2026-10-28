"""TRADER AI PRO - moteur d'analyse technique indicatif. Règles : tendance simple, pivots/supports/résistances, lignes de tendance, Order Blocks candidats et confirmation de bougie. Aucun ordre n'est exécuté. Les signaux sont indicatifs et ne constituent pas une garantie de résultat. """
from math import isfinite

MIN_CANDLES = 30
PIVOT_RADIUS = 2
ZONE_LOOKBACK = 40
RR_RATIO = 3.0


def valid_candle(candle):
    """Vérifie la cohérence OHLC d'une bougie."""
    try:
        o, h, l, c = (float(candle[k]) for k in ("open", "high", "low", "close"))
    except (KeyError, TypeError, ValueError):
        return False
    return (all(isfinite(v) and v > 0 for v in (o, h, l, c))
            and h >= max(o, c) and l <= min(o, c) and h >= l)


def normalize_candles(candles):
    """Nettoie les bougies et les classe de la plus ancienne à la plus récente."""
    result = []
    for candle in candles or []:
        if not isinstance(candle, dict) or not valid_candle(candle):
            continue
        epoch = candle.get("epoch", candle.get("time", candle.get("t")))
        try:
            epoch = float(epoch) if epoch is not None else None
        except (TypeError, ValueError):
            epoch = None
        result.append({"epoch": epoch, "open": float(candle["open"]),
                       "high": float(candle["high"]), "low": float(candle["low"]),
                       "close": float(candle["close"])})
    if result and all(c["epoch"] is not None for c in result):
        result.sort(key=lambda c: c["epoch"])
        deduped = {}
        for candle in result:
            deduped[candle["epoch"]] = candle
        result = [deduped[t] for t in sorted(deduped)]
    return result


def candle_trend(candles):
    """Estimation volontairement simple de tendance à partir des 10 dernières clôtures."""
    if len(candles) < 10:
        return "INCONNU"
    closes = [c["close"] for c in candles[-10:]]
    middle = sum(closes) / len(closes)
    if closes[-1] > closes[0] and closes[-1] > middle:
        return "HAUSSIERE"
    if closes[-1] < closes[0] and closes[-1] < middle:
        return "BAISSIERE"
    return "LATERALE"


def find_pivots(candles, kind):
    pivots = []
    r = PIVOT_RADIUS
    for i in range(r, len(candles) - r):
        value = candles[i][kind]
        left, right = candles[i-r:i], candles[i+1:i+r+1]
        if kind == "high":
            valid = all(value >= c["high"] for c in left) and all(value > c["high"] for c in right)
        else:
            valid = all(value <= c["low"] for c in left) and all(value < c["low"] for c in right)
        if valid:
            pivots.append((i, value))
    return pivots


def find_trendline(candles, direction):
    kind = "low" if direction == "BUY" else "high"
    pivots = find_pivots(candles[:-1], kind)
    if len(pivots) < 2:
        return None
    (i1, p1), (i2, p2) = pivots[-2:]
    if i2 == i1 or (direction == "BUY" and p2 <= p1) or (direction == "SELL" and p2 >= p1):
        return None
    projected = p2 + ((p2-p1)/(i2-i1)) * (len(candles)-1-i2)
    return {"direction": direction, "price": projected, "pivot_1": p1, "pivot_2": p2}


def find_support_resistance(candles):
    current = candles[-1]["close"]
    lows = [p for _, p in find_pivots(candles[:-1], "low") if p < current]
    highs = [p for _, p in find_pivots(candles[:-1], "high") if p > current]
    return {"support": max(lows) if lows else None,
            "resistance": min(highs) if highs else None}


def find_order_block(candles, direction):
    """Trouve une bougie opposée suivie d'une impulsion; zone candidate uniquement."""
    start = max(1, len(candles) - ZONE_LOOKBACK - 1)
    for i in range(len(candles)-2, start-1, -1):
        origin, impulse = candles[i], candles[i+1]
        if direction == "BUY":
            opposite = origin["close"] < origin["open"]
            displacement = impulse["close"] > impulse["open"] and impulse["close"] > origin["high"]
        else:
            opposite = origin["close"] > origin["open"]
            displacement = impulse["close"] < impulse["open"] and impulse["close"] < origin["low"]
        if opposite and displacement:
            # Une zone n'est pertinente que si le prix récent la reteste ou reste proche.
            later = candles[i+2:]
            touched = any(c["low"] <= origin["high"] and c["high"] >= origin["low"] for c in later)
            if touched:
                return {"type": "OB_ACHAT" if direction == "BUY" else "OB_VENTE",
                        "low": origin["low"], "high": origin["high"], "index": i}
    return None


def candle_confirms(candle, direction):
    span = candle["high"] - candle["low"]
    if span <= 0:
        return False
    body = abs(candle["close"] - candle["open"])
    if direction == "BUY":
        return candle["close"] > candle["open"] and candle["close"] >= candle["low"] + 0.65*span and body >= 0.25*span
    return candle["close"] < candle["open"] and candle["close"] <= candle["high"] - 0.65*span and body >= 0.25*span


def _round_price(value):
    return round(float(value), 6)


def analyze_candles(candles):
    """Analyse une liste de bougies OHLC et renvoie un dictionnaire stable. Champs garantis : status, candle_count, trend, support, resistance, trendline, order_block et signal. Le signal reste None si les conditions minimales ne sont pas réunies. """
    data = normalize_candles(candles)
    result = {"status": "INSUFFISANT", "candle_count": len(data),
              "trend": "INCONNU", "support": None, "resistance": None,
              "trendline": None, "order_block": None, "signal": None,
              "rr_target": RR_RATIO, "message": "Pas assez de bougies valides."}
    if len(data) < MIN_CANDLES:
        return result

    trend = candle_trend(data)
    levels = find_support_resistance(data)
    result.update(status="OK", trend=trend, support=levels["support"],
                  resistance=levels["resistance"], message="Analyse indicative terminée.")

    current = data[-1]
    # Dernière bougie = bougie la plus récente reçue. L'appelant doit fournir
    # des bougies clôturées; le connecteur Deriv est responsable de ce filtre.
    candidates = []
    for direction, level in (("BUY", levels["support"]), ("SELL", levels["resistance"])):
        if level is None or not candle_confirms(current, direction):
            continue
        # Confirmation proche du niveau : évite de signaler une bougie éloignée.
        span = max(current["high"] - current["low"], current["close"] * 0.0001)
        if direction == "BUY" and current["low"] > level + 1.5*span:
            continue
        if direction == "SELL" and current["high"] < level - 1.5*span:
            continue
        ob = find_order_block(data, direction)
        line = find_trendline(data, direction)
        # Le SL est placé derrière la mèche de confirmation, avec une marge
        # basée sur la plage de la bougie, plutôt qu'une valeur de pip fixe.
        buffer = max(span * 0.15, current["close"] * 0.00005)
        entry = current["close"]
        if direction == "BUY":
            stop = min(current["low"], ob["low"] if ob else current["low"]) - buffer
            risk = entry - stop
            target = entry + RR_RATIO*risk
            zone_low, zone_high = (ob["low"], ob["high"]) if ob else (level-span*0.25, level+span*0.25)
        else:
            stop = max(current["high"], ob["high"] if ob else current["high"]) + buffer
            risk = stop - entry
            target = entry - RR_RATIO*risk
            zone_low, zone_high = (ob["low"], ob["high"]) if ob else (level-span*0.25, level+span*0.25)
        if risk <= 0 or target <= 0:
            continue
        # Confluence stricte : niveau technique et confirmation; OB/trendline
        # sont ajoutés au résultat mais ne sont pas inventés s'ils sont absents.
        reason_parts = ["confirmation de bougie", "proximité d'un niveau technique"]
        if ob:
            reason_parts.append("Order Block candidat")
        if line:
            reason_parts.append("ligne de tendance candidate")
        candidates.append({"direction": direction, "entry": _round_price(entry),
                           "stop_loss": _round_price(stop), "take_profit": _round_price(target),
                           "risk_reward": RR_RATIO, "zone_type": ob["type"] if ob else "SUPPORT_RESISTANCE",
                           "zone_low": _round_price(zone_low), "zone_high": _round_price(zone_high),
                           "reason": "; ".join(reason_parts), "order_block": ob,
                           "trendline": line, "level": _round_price(level)})

    # Ne jamais renvoyer deux directions contradictoires pour la même bougie.
    if len(candidates) == 1:
        result["signal"] = candidates[0]
    elif len(candidates) > 1:
        result["message"] = "Conditions contradictoires : aucun signal retenu."
    direction = result["signal"]["direction"] if result["signal"] else ("BUY" if trend == "HAUSSIERE" else "SELL")
    result["trendline"] = find_trendline(data, direction)
    result["order_block"] = find_order_block(data, direction)
    return result
