"""TRADER AI PRO - moteur d'analyse technique.
Analyse indicative uniquement : aucun ordre n'est exécuté.
Le SMC constitue une confluence, jamais un déclencheur autonome.
"""

from math import isfinite

MIN_CANDLES = 30
PIVOT_RADIUS = 2
ZONE_LOOKBACK = 40
RR_RATIO = 3.0


def valid_candle(candle):
    """Vérifie la cohérence des données OHLC."""
    try:
        o, h, l, c = (
            float(candle[k])
            for k in ("open", "high", "low", "close")
        )
    except (KeyError, TypeError, ValueError):
        return False

    return (
        all(isfinite(v) and v > 0 for v in (o, h, l, c))
        and h >= max(o, c)
        and l <= min(o, c)
        and h >= l
    )


def normalize_candles(candles):
    """Nettoie les bougies et les classe chronologiquement."""
    result = []

    for candle in candles or []:
        if not isinstance(candle, dict) or not valid_candle(candle):
            continue

        epoch = candle.get(
            "epoch",
            candle.get("time", candle.get("t"))
        )

        try:
            epoch = float(epoch) if epoch is not None else None
        except (TypeError, ValueError):
            epoch = None

        result.append({
            "epoch": epoch,
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
        })

    if result and all(c["epoch"] is not None for c in result):
        result.sort(key=lambda c: c["epoch"])

        deduped = {}
        for candle in result:
            deduped[candle["epoch"]] = candle

        result = [deduped[t] for t in sorted(deduped)]

    return result


def candle_trend(candles):
    """Estimation indicative de tendance."""
    if len(candles) < 10:
        return "INCONNU"

    recent = candles[-10:]
    closes = [c["close"] for c in recent]
    middle = sum(closes) / len(closes)

    if closes[-1] > closes[0] and closes[-1] > middle:
        return "HAUSSIERE"

    if closes[-1] < closes[0] and closes[-1] < middle:
        return "BAISSIERE"

    return "LATERALE"


def find_pivots(candles, kind):
    """Identifie les pivots confirmés par des bougies à gauche et à droite."""
    if kind not in ("high", "low"):
        return []

    pivots = []
    radius = PIVOT_RADIUS

    for i in range(radius, len(candles) - radius):
        value = candles[i][kind]

        left = candles[i - radius:i]
        right = candles[i + 1:i + radius + 1]

        if kind == "high":
            valid = (
                all(value >= c["high"] for c in left)
                and all(value > c["high"] for c in right)
            )
        else:
            valid = (
                all(value <= c["low"] for c in left)
                and all(value < c["low"] for c in right)
            )

        if valid:
            pivots.append((i, value))

    return pivots


def find_support_resistance(candles):
    """Retourne le support et la résistance les plus proches du cours."""
    if not candles:
        return {"support": None, "resistance": None}

    current = candles[-1]["close"]

    lows = [
        price
        for _, price in find_pivots(candles[:-1], "low")
        if price < current
    ]

    highs = [
        price
        for _, price in find_pivots(candles[:-1], "high")
        if price > current
    ]

    return {
        "support": max(lows) if lows else None,
        "resistance": min(highs) if highs else None,
    }


def find_trendline(candles, direction):
    """Calcule une ligne de tendance candidate."""
    if direction not in ("BUY", "SELL"):
        return None

    kind = "low" if direction == "BUY" else "high"
    pivots = find_pivots(candles[:-1], kind)

    if len(pivots) < 2:
        return None

    (i1, p1), (i2, p2) = pivots[-2:]

    if i2 == i1:
        return None

    if direction == "BUY" and p2 <= p1:
        return None

    if direction == "SELL" and p2 >= p1:
        return None

    projected = p2 + (
        (p2 - p1) / (i2 - i1)
    ) * (len(candles) - 1 - i2)

    return {
        "direction": direction,
        "price": projected,
        "pivot_1": p1,
        "pivot_2": p2,
    }


def average_range(candles, period=14):
    """Moyenne simple des plages high-low."""
    recent = candles[-period:]

    if not recent:
        return None

    return sum(
        c["high"] - c["low"] for c in recent
    ) / len(recent)


def find_order_block(candles, direction):
    """Détecte un Order Block candidat après une impulsion."""
    if direction not in ("BUY", "SELL") or len(candles) < 5:
        return None

    start = max(1, len(candles) - ZONE_LOOKBACK - 1)

    # On recherche une origine suivie d'une impulsion.
    for i in range(len(candles) - 2, start - 1, -1):
        origin = candles[i]
        impulse = candles[i + 1]

        if direction == "BUY":
            opposite = origin["close"] < origin["open"]
            displacement = (
                impulse["close"] > impulse["open"]
                and impulse["close"] > origin["high"]
            )
        else:
            opposite = origin["close"] > origin["open"]
            displacement = (
                impulse["close"] < impulse["open"]
                and impulse["close"] < origin["low"]
            )

        if not (opposite and displacement):
            continue

        later = candles[i + 2:]

        touched = any(
            c["low"] <= origin["high"]
            and c["high"] >= origin["low"]
            for c in later
        )

        if touched:
            return {
                "type": (
                    "OB_ACHAT"
                    if direction == "BUY"
                    else "OB_VENTE"
                ),
                "low": origin["low"],
                "high": origin["high"],
                "index": i,
                "epoch": origin["epoch"],
            }

    return None


def detect_structure(candles):
    """Détecte une cassure récente de pivot, candidate BOS ou CHoCH."""
    if len(candles) < MIN_CANDLES:
        return {
            "event": None,
            "direction": None,
            "level": None,
        }

    # La bougie actuelle est exclue des pivots de référence.
    reference = candles[:-1]
    current = candles[-1]

    highs = find_pivots(reference, "high")
    lows = find_pivots(reference, "low")

    last_high = highs[-1][1] if highs else None
    last_low = lows[-1][1] if lows else None

    previous_trend = candle_trend(reference)

    if last_high is not None and current["close"] > last_high:
        event = (
            "CHoCH"
            if previous_trend == "BAISSIERE"
            else "BOS"
        )
        return {
            "event": event,
            "direction": "BUY",
            "level": last_high,
        }

    if last_low is not None and current["close"] < last_low:
        event = (
            "CHoCH"
            if previous_trend == "HAUSSIERE"
            else "BOS"
        )
        return {
            "event": event,
            "direction": "SELL",
            "level": last_low,
        }

    return {
        "event": None,
        "direction": None,
        "level": None,
    }


def detect_liquidity_sweep(candles):
    """Détecte un balayage candidat d'un pivot récent."""
    if len(candles) < MIN_CANDLES:
        return None

    reference = candles[:-1]
    current = candles[-1]

    highs = find_pivots(reference, "high")
    lows = find_pivots(reference, "low")

    last_high = highs[-1][1] if highs else None
    last_low = lows[-1][1] if lows else None

    # Mèche sous le support, clôture revenue au-dessus.
    if (
        last_low is not None
        and current["low"] < last_low
        and current["close"] > last_low
    ):
        return {
            "type": "SWEEP_BAISSIER",
            "direction": "BUY",
            "level": last_low,
        }

    # Mèche au-dessus de la résistance, clôture revenue en dessous.
    if (
        last_high is not None
        and current["high"] > last_high
        and current["close"] < last_high
    ):
        return {
            "type": "SWEEP_HAUSSIER",
            "direction": "SELL",
            "level": last_high,
        }

    return None


def candle_confirms(candle, direction):
    """Vérifie la direction et la position de clôture de la bougie."""
    span = candle["high"] - candle["low"]

    if span <= 0:
        return False

    body = abs(candle["close"] - candle["open"])

    if direction == "BUY":
        return (
            candle["close"] > candle["open"]
            and candle["close"] >= candle["low"] + 0.65 * span
            and body >= 0.25 * span
        )

    if direction == "SELL":
        return (
            candle["close"] < candle["open"]
            and candle["close"] <= candle["high"] - 0.65 * span
            and body >= 0.25 * span
        )

    return False


def _round_price(value):
    return round(float(value), 8)


def analyze_candles(candles):
    """Analyse les bougies et produit zéro ou un signal indicatif."""
    data = normalize_candles(candles)

    result = {
        "status": "INSUFFISANT",
        "candle_count": len(data),
        "trend": "INCONNU",
        "support": None,
        "resistance": None,
        "trendline": None,
        "order_block": None,
        "structure": None,
        "liquidity_sweep": None,
        "signal": None,
        "rr_target": RR_RATIO,
        "message": "Pas assez de bougies valides.",
    }

    if len(data) < MIN_CANDLES:
        return result

    trend = candle_trend(data)
    levels = find_support_resistance(data)
    structure = detect_structure(data)
    sweep = detect_liquidity_sweep(data)

    result.update({
        "status": "OK",
        "trend": trend,
        "support": levels["support"],
        "resistance": levels["resistance"],
        "structure": structure,
        "liquidity_sweep": sweep,
        "message": "Analyse indicative terminée.",
    })

    current = data[-1]
    atr = average_range(data)

    if atr is None or atr <= 0:
        result["message"] = "Plage de marché invalide."
        return result

    # Le niveau technique et la bougie restent les critères de base.
    candidates = []

    for direction, level in (
        ("BUY", levels["support"]),
        ("SELL", levels["resistance"]),
    ):
        if level is None or not candle_confirms(current, direction):
            continue

        span = max(
            current["high"] - current["low"],
            current["close"] * 0.00001,
        )

        if direction == "BUY":
            if current["low"] > level + 1.5 * span:
                continue
        else:
            if current["high"] < level - 1.5 * span:
                continue

        ob = find_order_block(data, direction)
        line = find_trendline(data, direction)

        # Le balayage de liquidité et la cassure sont des confluences,
        # pas des déclencheurs autonomes.
        sweep_matches = bool(
            sweep and sweep["direction"] == direction
        )
        structure_matches = bool(
            structure
            and structure["direction"] == direction
        )

        buffer = max(
            atr * 0.10,
            span * 0.10,
            current["close"] * 0.00001,
        )

        entry = current["close"]

        if direction == "BUY":
            structural_low = current["low"]

            if ob:
                structural_low = min(structural_low, ob["low"])

            stop = structural_low - buffer
            risk = entry - stop
            target = entry + RR_RATIO * risk
        else:
            structural_high = current["high"]

            if ob:
                structural_high = max(structural_high, ob["high"])

            stop = structural_high + buffer
            risk = stop - entry
            target = entry - RR_RATIO * risk

        # Contrôle strict de la géométrie du signal.
        if not all(isfinite(v) and v > 0 for v in (
            entry, stop, target, risk
        )):
            continue

        if direction == "BUY" and not stop < entry < target:
            continue

        if direction == "SELL" and not target < entry < stop:
            continue

        actual_rr = abs(target - entry) / abs(entry - stop)

        if abs(actual_rr - RR_RATIO) > 0.01:
            continue

        reason_parts = [
            "confirmation de bougie",
            "proximité d'un support/résistance",
        ]

        if ob:
            reason_parts.append("Order Block candidat")

        if line:
            reason_parts.append("ligne de tendance candidate")

        if sweep_matches:
            reason_parts.append("balayage de liquidité candidat")

        if structure_matches:
            reason_parts.append(
                "%s candidat" % structure["event"]
            )

        zone_low, zone_high = (
            (ob["low"], ob["high"])
            if ob
            else (
                level - span * 0.25,
                level + span * 0.25,
            )
        )

        candidates.append({
            "direction": direction,
            "entry": _round_price(entry),
            "stop_loss": _round_price(stop),
            "take_profit": _round_price(target),
            "risk_reward": RR_RATIO,
            "zone_type": (
                ob["type"] if ob else "SUPPORT_RESISTANCE"
            ),
            "zone_low": _round_price(zone_low),
            "zone_high": _round_price(zone_high),
            "reason": "; ".join(reason_parts),
            "order_block": ob,
            "trendline": line,
            "level": _round_price(level),
            "bar_time": int(current["epoch"] or 0),
            "atr": _round_price(atr),
            "structure": structure,
            "liquidity_sweep": sweep,
        })

    if len(candidates) == 1:
        result["signal"] = candidates[0]
        result["message"] = "Signal technique candidat détecté."
    elif len(candidates) > 1:
        result["message"] = (
            "Conditions contradictoires : aucun signal retenu."
        )

    direction = (
        result["signal"]["direction"]
        if result["signal"]
        else ("BUY" if trend == "HAUSSIERE" else "SELL")
    )

    result["trendline"] = find_trendline(data, direction)
    result["order_block"] = find_order_block(data, direction)

    return result
