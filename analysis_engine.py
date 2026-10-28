"""
TRADER AI PRO - Moteur d'analyse
Strategie : trendlines, supports/resistances et order blocks.
Aucun ordre n'est envoyé par ce fichier.
"""

from math import isfinite


MIN_CANDLES = 30
PIVOT_RADIUS = 2
ZONE_LOOKBACK = 40
RR_RATIO = 3.0


def valid_candle(candle):
    """Vérifie qu'une bougie a des prix cohérents."""
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
    )


def normalize_candles(candles):
    """Nettoie les bougies et les trie de la plus ancienne à la plus récente."""
    result = []
    for candle in candles or []:
        if not isinstance(candle, dict) or not valid_candle(candle):
            continue
        result.append({
            "epoch": candle.get("epoch", candle.get("time")),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
        })

    if result and all(c["epoch"] is not None for c in result):
        result.sort(key=lambda c: c["epoch"])

    return result


def candle_trend(candles):
    if len(candles) < 10:
        return "INCONNU"

    recent = candles[-10:]
    first = recent[0]["close"]
    last = recent[-1]["close"]
    middle = sum(c["close"] for c in recent) / len(recent)

    if last > first and last > middle:
        return "HAUSSIERE"
    if last < first and last < middle:
        return "BAISSIERE"
    return "LATERALE"


def find_pivots(candles, kind):
    pivots = []
    radius = PIVOT_RADIUS

    for i in range(radius, len(candles) - radius):
        value = candles[i][kind]
        left = candles[i - radius:i]
        right = candles[i + 1:i + radius + 1]

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
    kind = "low" if direction == "BUY" else "high"
    pivots = find_pivots(candles[:-1], kind)

    if len(pivots) < 2:
        return None

    first_i, first_price = pivots[-2]
    second_i, second_price = pivots[-1]

    if direction == "BUY" and second_price <= first_price:
        return None
    if direction == "SELL" and second_price >= first_price:
        return None

    slope = (
        (second_price - first_price)
        / (second_i - first_i)
    )
    projected = second_price + slope * (
        len(candles) - 1 - second_i
    )

    return {
        "direction": direction,
        "price": projected,
        "pivot_1": first_price,
        "pivot_2": second_price,
    }


def find_support_resistance(candles):
    highs = find_pivots(candles[:-1], "high")
    lows = find_pivots(candles[:-1], "low")
    current = candles[-1]["close"]

    supports = [
        price for _, price in lows if price < current
    ]
    resistances = [
        price for _, price in highs if price > current
    ]

    return {
        "support": max(supports) if supports else None,
        "resistance": min(resistances) if resistances else None,
    }


def find_order_block(candles, direction):
    """
    Recherche simple d'une bougie opposée suivie d'un mouvement
    impulsif. C'est une zone candidate, pas une garantie de réaction.
    """
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
    full_range = candle["high"] - candle["low"]

    if full_range <= 0:
        return False

    if direction == "BUY":
        return (
            candle["close"] > candle["open"]
            and candle["close"] >= candle[
