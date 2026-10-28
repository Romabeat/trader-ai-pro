
"""TRADER AI PRO - moteur d'analyse technique.

Strategie: trendlines, supports/resistances, order blocks et confirmation.
Aucune transaction n'est ouverte par ce module. Ratio cible indicatif: 1:3.
"""

from math import isfinite

MIN_CANDLES = 30
PIVOT_RADIUS = 2
ZONE_LOOKBACK = 40
RR_RATIO = 3.0


def valid_candle(candle):
    try:
        o = float(candle["open"])
        h = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        return (
            all(isfinite(v) and v > 0 for v in (o, h, low, close))
            and h >= max(o, close)
            and low <= min(o, close)
            and h >= low
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def normalize_candles(candles):
    normalized = []
    if not isinstance(candles, (list, tuple)):
        return normalized

    for candle in candles:
        if not isinstance(candle, dict) or not valid_candle(candle):
            continue
        normalized.append({
            "epoch": candle.get("epoch"),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
        })
    return normalized


def candle_trend(candles):
    if len(candles) < 10:
        return "INCONNU"

    recent = candles[-10:]
    first_close = recent[0]["close"]
    last_close = recent[-1]["close"]
    average_close = sum(c["close"] for c in recent) / len(recent)

    if last_close > first_close and last_close > average_close:
        return "HAUSSIERE"
    if last_close < first_close and last_close < average_close:
        return "BAISSIERE"
    return "LATERALE"


def find_pivots(candles, kind):
    if kind not in ("high", "low"):
        return []

    pivots = []
    r = PIVOT_RADIUS

    for i in range(r, len(candles) - r):
        value = candles[i][kind]
        left = candles[i-r:i]
        right = candles[i+1:i+r+1]

        if kind == "high":
            is_pivot = (
                all(value >= c["high"] for c in left)
                and all(value > c["high"] for c in right)
            )
        else:
            is_pivot = (
                all(value <= c["low"] for c in left)
                and all(value < c["low"] for c in right)
            )

        if is_pivot:
            pivots.append((i, value))

    return pivots


def find_trendline(candles, direction):
    if direction not in ("BUY", "SELL") or len(candles) < 6:
        return None

    kind = "low" if direction == "BUY" else "high"
    pivots = find_pivots(candles[:-1], kind)

    if len(pivots) < 2:
        return None

    i1, p1 = pivots[-2]
    i2, p2 = pivots[-1]

    if i2 == i1:
        return None
    if direction == "BUY" and p2 <= p1:
        return None
    if direction == "SELL" and p2 >= p1:
        return None

    slope = (p2 - p1) / (i2 - i1)
    projected = p2 + slope * (len(candles) - 1 - i2)

    return {
        "direction": direction,
        "price": projected,
        "pivot_1": p1,
        "pivot_2": p2,
    }


def find_support_resistance(candles):
    if not candles:
        return {"support": None, "resistance": None}

    highs = find_pivots(candles[:-1], "high")
    lows = find_pivots(candles[:-1], "low")
    current = candles[-1]["close"]

    supports = [price for _, price in lows if price < current]
    resistances = [price for _, price in highs if price > current]

    return {
        "support": max(supports) if supports else None,
        "resistance": min(resistances) if resistances else None,
    }


def find_order_block(candles, direction):
    """Repere un bloc candidat: bougie opposee puis impulsion qui la depasse."""
    if direction not in ("BUY", "SELL") or len(candles) < 4:
        return None

    start = max(1, len(candles) - ZONE_LOOKBACK - 1)

    for i in range(len(candles) - 2, start - 1, -1):
        origin = candles[i]
        impulse = candles[i + 1]
        later = candles[i + 2:]

        if direction == "BUY":
            opposite = origin["close"] < origin["open"]
            displacement = (
                impulse["close"] > impulse["open"]
                and impulse["close"] > origin["high"]
            )
            retest = any(
                c["low"] <= origin["high"]
                and c["high"] >= origin["low"]
                for c in later
            )
        else:
            opposite = origin["close"] > origin["open"]
            displacement = (
                impulse["close"] < impulse["open"]
                and impulse["close"] < origin["low"]
            )
            retest = any(
                c["high"] >= origin["low"]
                and c["low"] <= origin["high"]
                for c in later
            )

        if opposite and displacement and retest:
            return {
                "type": "OB_ACHAT" if direction == "BUY" else "OB_VENTE",
                "low": origin["low"],
                "high": origin["high"],
                "index": i,
            }

    return None


def candle_confirms(candle, direction):
    body = abs(candle["close"] - candle["open"])
    candle_range = candle["high"] - candle["low"]

    if candle_range <= 0:
        return False

    if direction == "BUY":
        return (
            candle["close"] > candle["open"]
            and candle["close"] >= candle["low"] + candle_range * 0.6
            and body >= candle_range * 0.2
        )

    if direction == "SELL":
        return (
            candle["close"] < candle["open"]
            and candle["close"] <= candle["high"] - candle_range * 0.6
            and body >= candle_range * 0.2
        )

    return False


def build_signal(candles, direction, sr, trendline):
    if len(candles) < MIN_CANDLES:
        return None

    zone = find_order_block(candles[:-1], direction)
    if zone is None:
        return None

    last = candles[-1]
    touched = (
        last["low"] <= zone["high"]
        and last["high"] >= zone["low"]
    )

    if not touched or not candle_confirms(last, direction):
        return None

    midpoint = (zone["low"] + zone["high"]) / 2
    tolerance = max(
        (zone["high"] - zone["low"]) * 1.5,
        last["close"] * 0.0001,
    )

    if direction == "BUY":
        level = sr["support"]
        if level is None or abs(level - midpoint) > tolerance:
            return None
    else:
        level = sr["resistance"]
        if level is None or abs(level - midpoint) > tolerance:
            return None

    if trendline is not None:
        if direction == "BUY" and last["close"] < trendline["price"]:
            return None
        if direction == "SELL" and last["close"] > trendline["price"]:
            return None

    entry = last["close"]
    zone_size = zone["high"] - zone["low"]
    buffer = max(zone_size * 0.1, entry * 0.0001)

    if direction == "BUY":
        stop = zone["low"] - buffer
        risk = entry - stop
        if risk <= 0:
            return None
        target = entry + RR_RATIO * risk
    else:
        stop = zone["high"] + buffer
        risk = stop - entry
        if risk <= 0:
            return None
        target = entry - RR_RATIO * risk

    return {
        "direction": direction,
        "entry": entry,
        "stop_loss": stop,
        "take_profit": target,
        "zone": zone,
        "zone_low": zone["low"],
        "zone_high": zone["high"],
        "zone_type": zone["type"],
        "reason": "Retest OB + confirmation + confluence support/resistance",
        "risk_reward": RR_RATIO,
    }


def analyze_candles(raw_candles):
    candles = normalize_candles(raw_candles)

    if len(candles) < MIN_CANDLES:
        return {
            "trend": "INCONNU",
            "support": None,
            "resistance": None,
            "trendline": None,
            "order_block": None,
            "signal": None,
            "status": "DONNEES_INSUFFISANTES",
            "candle_count": len(candles),
        }

    trend = candle_trend(candles)
    sr = find_support_resistance(candles)
    buy_line = find_trendline(candles, "BUY")
    sell_line = find_trendline(candles, "SELL")
    signal = None
    order_block = None

    if trend == "HAUSSIERE":
        order_block = find_order_block(candles[:-1], "BUY")
        signal = build_signal(candles, "BUY", sr, buy_line)
    elif trend == "BAISSIERE":
        order_block = find_order_block(candles[:-1], "SELL")
        signal = build_signal(candles, "SELL", sr, sell_line)

    return {
        "trend": trend,
        "support": sr["support"],
        "resistance": sr["resistance"],
        "trendline": buy_line or sell_line,
        "order_block": order_block,
        "signal": signal,
        "status": "OK",
        "candle_count": len(candles),
    }
