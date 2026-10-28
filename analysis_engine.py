
from statistics import mean

# IMPORTANT :
# Cette valeur est provisoire. Vérifier la valeur d'un pip
# pour chaque indice Deriv avant toute utilisation réelle.
PIP_SIZE = 0.01
SL_BUFFER_PIPS = 10
RISK_REWARD_RATIO = 3


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

    po = float(prev["open"])
    pc = float(prev["close"])
    o = float(last["open"])
    c = float(last["close"])
    h = float(last["high"])
    l = float(last["low"])

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

    first = recent[:half]
    second = recent[half:]

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
    """Repère des sommets et creux proches."""
    if len(candles) < 3:
        return {
            "equal_highs": [],
            "equal_lows": [],
        }

    recent = candles[-min(lookback, len(candles)):]

    def cluster_levels(values):
        values = sorted(values)
        clusters = []

        for value in values:
            if not clusters:
                clusters.append([value])
                continue

            center = mean(clusters[-1])
            scale = max(abs(center), 1e-9)

            if abs(value - center) / scale <= tolerance:
                clusters[-1].append(value)
            else:
                clusters.append([value])

        levels = [
            round(mean(cluster), 5)
            for cluster in clusters
            if len(cluster) >= 2
        ]

        levels.sort()
        return levels[:5]

    return {
        "equal_highs": cluster_levels(
            [float(c["high"]) for c in recent]
        ),
        "equal_lows": cluster_levels(
            [float(c["low"]) for c in recent]
        ),
    }


def detect_liquidity_sweep(candles, lookback=20):
    """Détecte un dépassement suivi d'une clôture de réintégration."""
    if len(candles) < 3:
        return None

    previous = candles[-min(lookback + 1, len(candles)):-1]
    if not previous:
        return None

    last = candles[-1]

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


def generate_signal(candles):
    """
    Génère un signal indicatif si une prise de liquidité,
    un retournement et une zone de réaction concordent.
    Le SL est placé à 10 pips au-delà de la zone.
    Le TP vise un ratio risque/rendement de 1:3.
    """
    if len(candles) < 30:
        return {
            "direction": "AUCUN SIGNAL",
            "reason": "Données insuffisantes",
        }

    sweep = detect_liquidity_sweep(candles)
    reversal = detect_candle_reversal(candles)
    order_block = find_order_block(candles)
    zones = find_supply_demand_zones(candles)

    if not sweep or not reversal:
        return {
            "direction": "AUCUN SIGNAL",
            "reason": "Pas de confirmation suffisante",
        }

    bullish = sweep["direction_potentielle"] == "Haussière"

    if bullish:
        confirms = (
            "haussier" in reversal.lower()
            or "vers le haut" in reversal.lower()
        )
        expected_ob = "Order Block haussier potentiel"
        expected_zone = "Demand potentielle"
    else:
        confirms = (
            "baissier" in reversal.lower()
            or "vers le bas" in reversal.lower()
        )
        expected_ob = "Order Block baissier potentiel"
        expected_zone = "Supply potentielle"

    if not confirms:
        return {
            "direction": "AUCUN SIGNAL",
            "reason": "Le retournement ne confirme pas la prise de liquidité",
        }

    # Priorité à l'Order Block correspondant.
    zone = (
        order_block
        if order_block and order_block["type"] == expected_ob
        else None
    )

    # Sinon, utiliser une zone d'offre ou de demande correspondante.
    if zone is None:
        matching_zones = [
            item for item in zones
            if item["type"] == expected_zone
        ]
        if matching_zones:
            zone = matching_zones[-1]

    if zone is None:
        return {
            "direction": "AUCUN SIGNAL",
            "reason": "Aucune zone de réaction correspondante détectée",
        }

    entry = float(candles[-1]["close"])
    buffer = SL_BUFFER_PIPS * PIP_SIZE

    if bullish:
        sl = float(zone["low"]) - buffer
        risk = entry - sl

        if risk <= 0:
            return {
                "direction": "AUCUN SIGNAL",
                "reason": "Le prix d'entrée ne permet pas un SL cohérent",
            }

        tp = entry + RISK_REWARD_RATIO * risk

    else:
        sl = float(zone["high"]) + buffer
        risk = sl - entry

        if risk <= 0:
            return {
                "direction": "AUCUN SIGNAL",
                "reason": "Le prix d'entrée ne permet pas un SL cohérent",
            }

        tp = entry - RISK_REWARD_RATIO * risk

    return {
        "direction": "BUY" if bullish else "SELL",
        "entry": round(entry, 5),
        "zone": {
            "type": zone["type"],
            "low": round(float(zone["low"]), 5),
            "high": round(float(zone["high"]), 5),
        },
        "stop_loss": round(sl, 5),
        "sl_buffer_pips": SL_BUFFER_PIPS,
        "pip_size_used": PIP_SIZE,
        "take_profit": round(tp, 5),
        "risk_reward": "1:3",
        "reason": sweep["type"] + " + " + reversal,
        "status": "Signal indicatif à confirmer",
    }


def analyze_candles(candles):
    """Regroupe les éléments d'analyse et le signal potentiel."""
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
            "signal": {
                "direction": "AUCUN SIGNAL",
                "reason": "Aucune bougie disponible",
            },
        }

    support, resistance = find_support_resistance(candles)

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
        "signal": generate_signal(candles),
    }
