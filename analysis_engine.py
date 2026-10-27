
from statistics import mean


def candle_trend(candles):
    """Estime la tendance à partir des clôtures récentes."""
    if len(candles) < 30:
        return "Données insuffisantes"

    closes = [float(c["close"]) for c in candles]
    recent_avg = mean(closes[-20:])
    previous_avg = mean(closes[-30:-10])

    if recent_avg > previous_avg:
        return "Haussière"
    if recent_avg < previous_avg:
        return "Baissière"
    return "Neutre"


def find_support_resistance(candles, window=50):
    """Repère les extrêmes récents comme niveaux potentiels."""
    if len(candles) < 2:
        return None, None

    recent = candles[-min(window, len(candles)):]
    support = min(float(c["low"]) for c in recent)
    resistance = max(float(c["high"]) for c in recent)
    return support, resistance


def detect_candle_reversal(candles):
    """Détecte des configurations simples de retournement."""
    if len(candles) < 2:
        return None

    prev, last = candles[-2], candles[-1]
    po, pc = float(prev["open"]), float(prev["close"])
    o, c = float(last["open"]), float(last["close"])
    h, l = float(last["high"]), float(last["low"])

    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    if pc < po and c > o and c >= po and o <= pc:
        return "Possible retournement haussier"
    if pc > po and c < o and c <= po and o >= pc:
        return "Possible retournement baissier"
    if body > 0 and lower_wick >= 2 * body:
        return "Rejet possible vers le haut"
    if body > 0 and upper_wick >= 2 * body:
        return "Rejet possible vers le bas"

    return None


def find_trendline(candles, lookback=30):
    """Estime la direction des sommets et des creux."""
    if len(candles) < 10:
        return {"direction": "Indéterminée"}

    recent = candles[-min(lookback, len(candles)):]
    half = len(recent) // 2
    first, second = recent[:half], recent[half:]

    first_lows = mean(float(c["low"]) for c in first)
    second_lows = mean(float(c["low"]) for c in second)
    first_highs = mean(float(c["high"]) for c in first)
    second_highs = mean(float(c["high"]) for c in second)

    if second_lows > first_lows and second_highs > first_highs:
        direction = "Haussière"
    elif second_lows < first_lows and second_highs < first_highs:
        direction = "Baissière"
    else:
        direction = "Latérale ou incertaine"

    return {"direction": direction}


def find_equal_levels(candles, lookback=50, tolerance=0.001):
    """Repère les sommets et creux proches, candidats à la liquidité."""
    recent = candles[-min(lookback, len(candles)):]

    highs = [float(c["high"]) for c in recent]
    lows = [float(c["low"]) for c in recent]

    equal_highs = []
    equal_lows = []

    for i in range(len(recent)):
        for j in range(i + 1, len(recent)):
            high_scale = max(abs(highs[i]), abs(highs[j]), 1e-9)
            low_scale = max(abs(lows[i]), abs(lows[j]), 1e-9)

            if abs(highs[i] - highs[j]) / high_scale <= tolerance:
                equal_highs.append(round((highs[i] + highs[j]) / 2, 5))

            if abs(lows[i] - lows[j]) / low_scale <= tolerance:
                equal_lows.append(round((lows[i] + lows[j]) / 2, 5))

    return {
        "equal_highs": sorted(set(equal_highs)),
        "equal_lows": sorted(set(equal_lows)),
    }


def detect_liquidity_sweep(candles, lookback=20):
    """Détecte un dépassement suivi d'une clôture de réintégration."""
    if len(candles) < 3:
        return None

    previous = candles[-lookback - 1:-1] if len(candles) > lookback else candles[:-1]
    last = candles[-1]

    if not previous:
        return None

    prior_high = max(float(c["high"]) for c in previous)
    prior_low = min(float(c["low"]) for c in previous)

    high = float(last["high"])
    low = float(last["low"])
    close = float(last["close"])

    if high > prior_high and close < prior_high:
        return {
            "type": "Prise de liquidité au-dessus des sommets",
            "niveau": prior_high,
            "direction_potentielle": "Baissière",
        }

    if low < prior_low and close > prior_low:
        return {
            "type": "Prise de liquidité sous les creux",
            "niveau": prior_low,
            "direction_potentielle": "Haussière",
        }

    return None


def find_order_block(candles, lookback=20):
    """Cherche une bougie opposée avant une impulsion."""
    if len(candles) < 3:
        return None

    recent = candles[-min(lookback, len(candles)):]

    for i in range(len(recent) - 1, 0, -1):
        origin = recent[i - 1]
        impulse = recent[i]

        oo = float(origin["open"])
        oc = float(origin["close"])
        io = float(impulse["open"])
        ic = float(impulse["close"])

        origin_body = abs(oc - oo)
        impulse_body = abs(ic - io)

        if origin_body == 0 or impulse_body < 1.5 * origin_body:
            continue

        if oc < oo and ic > io:
            return {
                "type": "Order Block haussier potentiel",
                "low": min(oo, oc),
                "high": max(oo, oc),
            }

        if oc > oo and ic < io:
            return {
                "type": "Order Block baissier potentiel",
                "low": min(oo, oc),
                "high": max(oo, oc),
            }

    return None


def find_supply_demand_zones(candles, lookback=30):
    """Repère des zones candidates avant des mouvements impulsifs."""
    zones = []

    if len(candles) < 3:
        return zones

    recent = candles[-min(lookback, len(candles)):]

    for i in range(1, len(recent)):
        base = recent[i - 1]
        move = recent[i]

        bo = float(base["open"])
        bc = float(base["close"])
        mo = float(move["open"])
        mc = float(move["close"])

        base_body = abs(bc - bo)
        move_body = abs(mc - mo)

        if base_body == 0 or move_body < 1.5 * base_body:
            continue

        if bc < bo and mc > mo:
            zones.append({
                "type": "Demand potentielle",
                "low": min(bo, bc),
                "high": max(bo, bc),
            })

        elif bc > bo and mc < mo:
            zones.append({
                "type": "Supply potentielle",
                "low": min(bo, bc),
                "high": max(bo, bc),
            })

    return zones[-5:]


def analyze_candles(candles):
    """Regroupe les éléments de l'analyse technique."""
    support, resistance = find_support_resistance(candles)

    if not candles:
        return {
            "trend": "Données insuffisantes",
            "support": None,
            "resistance": None,
            "reversal": None,
            "trendline": {"direction": "Indéterminée"},
            "liquidity": None,
            "liquidity_levels": {
                "equal_highs": [],
                "equal_lows": [],
            },
            "order_block": None,
            "supply_demand_zones": [],
        }

    return {
        "trend": candle_trend(candles),
        "support": support,
        "resistance": resistance,
        "reversal": detect_candle_reversal(candles),
        "trendline": find_trendline(candles),
        "liquidity": detect_liquidity_sweep(candles),
        "liquidity_levels": find_equal_levels(candles),
        "order_block": find_order_block(candles),
        "supply_demand_zones": find_supply_demand_zones(candles),
    }
