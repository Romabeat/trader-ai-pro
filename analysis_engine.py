
from statistics import mean

# ============================================================
# TRADER AI PRO — MOTEUR D'ANALYSE
# Order Blocks + Support/Résistance + Liquidité + Trendline
# ============================================================
#
# ATTENTION :
# PIP_SIZE est provisoire. Il faut vérifier la cotation de
# chaque indice avant toute utilisation réelle.
#
# Le moteur produit des signaux indicatifs, pas des garanties.
# ============================================================

PIP_SIZE = 0.01
SL_BUFFER_PIPS = 20
RISK_REWARD_RATIO = 3.0

MIN_CANDLES = 30
OB_LOOKBACK = 50
SR_LOOKBACK = 50
LIQUIDITY_LOOKBACK = 50
SWEEP_LOOKBACK = 20
EQUAL_LEVEL_TOLERANCE = 0.001
IMPULSE_BODY_RATIO = 1.5


# ------------------------------------------------------------
# OUTILS DE BASE
# ------------------------------------------------------------

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


def find_trendline(candles, lookback=30):
    """
    Donne un contexte directionnel approximatif.
    Cette fonction ne bloque pas les trades à contre-tendance.
    """
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


def find_support_resistance(candles, window=SR_LOOKBACK):
    """Repère les extrêmes récents comme niveaux potentiels."""
    if len(candles) < 2:
        return None, None

    recent = candles[-min(window, len(candles)):]

    support = min(float(c["low"]) for c in recent)
    resistance = max(float(c["high"]) for c in recent)

    return support, resistance


def find_swing_levels(candles, lookback=SR_LOOKBACK):
    """Repère des sommets et creux locaux potentiels."""
    recent = candles[-min(lookback, len(candles)):]

    swing_highs = []
    swing_lows = []

    if len(recent) < 5:
        return swing_highs, swing_lows

    for i in range(2, len(recent) - 2):
        high = float(recent[i]["high"])
        low = float(recent[i]["low"])

        left_highs = [
            float(c["high"]) for c in recent[i - 2:i]
        ]
        right_highs = [
            float(c["high"]) for c in recent[i + 1:i + 3]
        ]

        left_lows = [
            float(c["low"]) for c in recent[i - 2:i]
        ]
        right_lows = [
            float(c["low"]) for c in recent[i + 1:i + 3]
        ]

        if high > max(left_highs) and high >= max(right_highs):
            swing_highs.append(high)

        if low < min(left_lows) and low <= min(right_lows):
            swing_lows.append(low)

    return swing_highs, swing_lows


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


# ------------------------------------------------------------
# LIQUIDITÉ : EQH, EQL ET SWEEPS
# ------------------------------------------------------------

def find_equal_levels(
    candles,
    lookback=LIQUIDITY_LOOKBACK,
    tolerance=EQUAL_LEVEL_TOLERANCE,
):
    """
    Repère les Equal Highs (EQH) et Equal Lows (EQL).

    Ce sont des niveaux de liquidité potentielle, pas une
    observation directe des ordres réellement présents.
    """
    if len(candles) < 3:
        return {"equal_highs": [], "equal_lows": []}

    recent = candles[-min(lookback, len(candles)):]

    def cluster_levels(values):
        values = sorted(float(v) for v in values)
        clusters = []

        for value in values:
            if not clusters:
                clusters.append([value])
                continue

            center = mean(clusters[-1])
            scale = max(abs(center), abs(value), 1e-9)

            if abs(value - center) / scale <= tolerance:
                clusters[-1].append(value)
            else:
                clusters.append([value])

        levels = [
            round(mean(cluster), 5)
            for cluster in clusters
            if len(cluster) >= 2
        ]

        return sorted(set(levels))

    return {
        "equal_highs": cluster_levels(
            [c["high"] for c in recent]
        ),
        "equal_lows": cluster_levels(
            [c["low"] for c in recent]
        ),
    }


def detect_liquidity_sweep(candles, lookback=SWEEP_LOOKBACK):
    """
    Détecte un dépassement d'un ancien sommet ou creux,
    suivi d'une clôture de réintégration.
    """
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
            "type": "BSL balayée puis réintégrée",
            "niveau": prior_high,
            "direction_potentielle": "Baissière",
        }

    if low < prior_low and close > prior_low:
        return {
            "type": "SSL balayée puis réintégrée",
            "niveau": prior_low,
            "direction_potentielle": "Haussière",
        }

    return None


def find_recent_sweeps(candles, bars=10):
    """Recherche les sweeps récents sans se limiter à la dernière bougie."""
    sweeps = []
    start = max(2, len(candles) - bars)

    for end in range(start, len(candles)):
        sweep = detect_liquidity_sweep(candles[:end + 1])

        if sweep:
            sweeps.append(sweep)

    return sweeps


def level_near_zone(level, zone, tolerance):
    """Vérifie si un niveau se trouve dans ou près d'une zone."""
    return (
        float(zone["low"]) - tolerance
        <= float(level)
        <= float(zone["high"]) + tolerance
    )


def has_liquidity_context(
    candles,
    zone,
    direction,
    entry,
    equal_levels=None,
):
    """
    Cherche un indice de liquidité pertinent :
    - EQH près d'une zone de SELL ;
    - EQL près d'une zone de BUY ;
    - sweep récent dans le sens du retournement ;
    - ou une cible de liquidité potentielle devant le prix.
    """
    if equal_levels is None:
        equal_levels = find_equal_levels(candles[:-1])

    width = max(
        float(zone["high"]) - float(zone["low"]),
        abs(float(entry)) * 0.0005,
    )
    tolerance = max(width * 2, abs(float(entry)) * 0.001)

    sweeps = find_recent_sweeps(candles[:-1])

    if direction == "SELL":
        relevant_levels = equal_levels["equal_highs"]

        nearby_eqh = any(
            level_near_zone(level, zone, tolerance)
            for level in relevant_levels
        )

        matching_sweep = any(
            sweep["direction_potentielle"] == "Baissière"
            for sweep in sweeps
        )

        target_liquidity = any(
            level < entry and level < zone["low"]
            for level in equal_levels["equal_lows"]
        )

    else:
        relevant_levels = equal_levels["equal_lows"]

        nearby_eql = any(
            level_near_zone(level, zone, tolerance)
            for level in relevant_levels
        )

        matching_sweep = any(
            sweep["direction_potentielle"] == "Haussière"
            for sweep in sweeps
        )

        target_liquidity = any(
            level > entry and level > zone["high"]
            for level in equal_levels["equal_highs"]
        )

        nearby_eqh = False
        nearby_eql = nearby_eql

    if direction == "SELL":
        nearby_level = nearby_eqh
    else:
        nearby_level = nearby_eql

    return {
        "valid": nearby_level or matching_sweep or target_liquidity,
        "nearby_equal_level": nearby_level,
        "matching_sweep": matching_sweep,
        "target_liquidity": target_liquidity,
    }


# ------------------------------------------------------------
# ORDER BLOCKS ET ZONES D'OFFRE / DEMANDE
# ------------------------------------------------------------

def find_order_blocks(candles, lookback=OB_LOOKBACK):
    """
    Recherche les bougies opposées précédant une impulsion.

    Les zones sont des candidates : elles ne sont pas toutes
    nécessairement valides ou encore exploitables.
    """
    if len(candles) < 3:
        return []

    recent = candles[-min(lookback, len(candles)):]
    blocks = []

    # L'impulsion doit être suivie d'au moins une bougie :
    # la dernière bougie pourra ainsi confirmer un retest.
    for i in range(len(recent) - 2, 0, -1):
        origin = recent[i - 1]
        impulse = recent[i]

        oo = float(origin["open"])
        oc = float(origin["close"])
        io = float(impulse["open"])
        ic = float(impulse["close"])

        origin_body = abs(oc - oo)
        impulse_body = abs(ic - io)

        if origin_body <= 0:
            continue

        if impulse_body < IMPULSE_BODY_RATIO * origin_body:
            continue

        # Bougie baissière suivie d'une impulsion haussière.
        if oc < oo and ic > io:
            blocks.append({
                "type": "Order Block haussier potentiel",
                "direction": "BUY",
                "low": min(oo, oc),
                "high": max(oo, oc),
                "origin_index": i - 1,
                "impulse_index": i,
            })

        # Bougie haussière suivie d'une impulsion baissière.
        elif oc > oo and ic < io:
            blocks.append({
                "type": "Order Block baissier potentiel",
                "direction": "SELL",
                "low": min(oo, oc),
                "high": max(oo, oc),
                "origin_index": i - 1,
                "impulse_index": i,
            })

    return blocks


def find_order_block(candles, lookback=OB_LOOKBACK):
    """Renvoie l'Order Block candidat le plus récent."""
    blocks = find_order_blocks(candles, lookback)

    return blocks[0] if blocks else None


def find_supply_demand_zones(candles, lookback=30):
    """Expose les Order Blocks sous forme de zones d'offre/demande."""
    zones = []

    for block in find_order_blocks(candles, lookback):
        if block["direction"] == "BUY":
            zone_type = "Demand potentielle"
        else:
            zone_type = "Supply potentielle"

        zones.append({
            "type": zone_type,
            "low": block["low"],
            "high": block["high"],
            "direction": block["direction"],
        })

    return zones[:5]


# ------------------------------------------------------------
# CONFLUENCE ORDER BLOCK + SUPPORT / RÉSISTANCE
# ------------------------------------------------------------

def zone_has_sr_confluence(candles, zone, direction):
    """
    Vérifie si l'OB est proche d'un swing low (BUY)
    ou d'un swing high (SELL).
    """
    swing_highs, swing_lows = find_swing_levels(candles)

    midpoint = (
        float(zone["low"]) + float(zone["high"])
    ) / 2

    zone_width = abs(
        float(zone["high"]) - float(zone["low"])
    )

    tolerance = max(
        zone_width * 2,
        abs(midpoint) * 0.0015,
    )

    if direction == "BUY":
        levels = swing_lows
    else:
        levels = swing_highs

    matching = [
        level for level in levels
        if level_near_zone(level, zone, tolerance)
    ]

    return {
        "valid": bool(matching),
        "levels": matching,
        "type": "Support" if direction == "BUY" else "Résistance",
    }


# ------------------------------------------------------------
# CONFIRMATION DU RETOUR DANS LA ZONE
# ------------------------------------------------------------

def candle_touches_zone(candle, zone):
    """Vérifie si la bougie intersecte la zone."""
    high = float(candle["high"])
    low = float(candle["low"])

    return (
        low <= float(zone["high"])
        and high >= float(zone["low"])
    )


def candle_confirms_rejection(candles, zone, direction):
    """
    Exige que la dernière bougie touche la zone et confirme
    un rejet dans le sens du signal.
    """
    if len(candles) < 2:
        return False, "Pas assez de bougies"

    last = candles[-1]

    if not candle_touches_zone(last, zone):
        return False, "Le prix ne reteste pas la zone"

    reversal = detect_candle_reversal(candles)

    if not reversal:
        return False, "Pas de confirmation par bougie"

    if direction == "BUY":
        confirms = (
            "haussier" in reversal.lower()
            or "vers le haut" in reversal.lower()
        )
    else:
        confirms = (
            "baissier" in reversal.lower()
            or "vers le bas" in reversal.lower()
        )

    if not confirms:
        return False, "La bougie ne confirme pas le sens attendu"

    return True, reversal


# ------------------------------------------------------------
# GÉNÉRATION DU SIGNAL
# ------------------------------------------------------------

def no_signal(reason):
    return {
        "direction": "AUCUN SIGNAL",
        "reason": reason,
        "status": "Aucun signal confirmé",
    }


def generate_signal(candles):
    """
    Règles principales :
    1. Identifier un Order Block candidat.
    2. Exiger une confluence avec support/résistance.
    3. Vérifier un contexte de liquidité SMC.
    4. Attendre le retest et une confirmation par bougie.
    5. Utiliser la trendline comme contexte, pas comme blocage.
    6. SL : 20 pips au-delà de la zone.
    7. TP : ratio risque/rendement de 1:3.

    Les signaux doivent être validés par backtest.
    """
    if len(candles) < MIN_CANDLES:
        return no_signal("Données insuffisantes")

    entry = float(candles[-1]["close"])
    trendline = find_trendline(candles)
    equal_levels = find_equal_levels(candles[:-1])
    blocks = find_order_blocks(candles)

    if not blocks:
        return no_signal("Aucun Order Block candidat détecté")

    buffer = SL_BUFFER_PIPS * PIP_SIZE
    rejected_reasons = []

    # Les blocs sont parcourus du plus récent au plus ancien.
    for block in blocks:
        direction = block["direction"]

        # La zone doit avoir un contexte de support/résistance.
        sr = zone_has_sr_confluence(candles[:-1], block, direction)

        if not sr["valid"]:
            rejected_reasons.append(
                "Order Block sans confluence support/résistance"
            )
            continue

        # La zone doit présenter un indice de liquidité pertinent.
        liquidity = has_liquidity_context(
            candles,
            block,
            direction,
            entry,
            equal_levels,
        )

        if not liquidity["valid"]:
            rejected_reasons.append(
                "Pas d'indice de liquidité pertinent autour de l'OB"
            )
            continue

        # Le prix doit revenir dans la zone et confirmer le rejet.
        confirmed, confirmation = candle_confirms_rejection(
            candles,
            block,
            direction,
        )

        if not confirmed:
            rejected_reasons.append(confirmation)
            continue

        if direction == "BUY":
            sl = float(block["low"]) - buffer
            risk = entry - sl

            if risk <= 0:
                rejected_reasons.append(
                    "Risque BUY incohérent avec le prix d'entrée"
                )
                continue

            tp = entry + RISK_REWARD_RATIO * risk

        else:
            sl = float(block["high"]) + buffer
            risk = sl - entry

            if risk <= 0:
                rejected_reasons.append(
                    "Risque SELL incohérent avec le prix d'entrée"
                )
                continue

            tp = entry - RISK_REWARD_RATIO * risk

        # La trendline est informative : elle ne bloque pas le signal.
        trend_direction = trendline["direction"]

        if trend_direction == "Haussière":
            trend_context = (
                "Dans le sens de la tendance"
                if direction == "BUY"
                else "À contre-tendance"
            )
        elif trend_direction == "Baissière":
            trend_context = (
                "Dans le sens de la tendance"
                if direction == "SELL"
                else "À contre-tendance"
            )
        else:
            trend_context = "Tendance incertaine"

        return {
            "direction": direction,
            "entry": round(entry, 5),
            "zone": {
                "type": block["type"],
                "low": round(float(block["low"]), 5),
                "high": round(float(block["high"]), 5),
            },
            "stop_loss": round(sl, 5),
            "sl_buffer_pips": SL_BUFFER_PIPS,
            "pip_size_used": PIP_SIZE,
            "take_profit": round(tp, 5),
            "risk_reward": "1:3",
            "reason": (
                f"{sr['type']} + contexte de liquidité + "
                f"rejet confirmé ({confirmation})"
            ),
            "liquidity_context": liquidity,
            "trendline_context": trend_context,
            "trendline_direction": trend_direction,
            "status": "Signal indicatif à confirmer",
        }

    reason = (
        rejected_reasons[0]
        if rejected_reasons
        else "Aucune configuration complète"
    )

    return no_signal(reason)


# ------------------------------------------------------------
# INTERFACE UTILISÉE PAR scheduled_analysis.py
# ------------------------------------------------------------

def analyze_candles(candles):
    """Retourne l'analyse et un signal au format attendu par le bot."""
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
            "signal": no_signal("Aucune bougie disponible"),
        }

    support, resistance = find_support_resistance(candles)

    return {
        "trend": candle_trend(candles),
        "support": support,
        "resistance": resistance,
        "reversal": detect_candle_reversal(candles),
        "trendline": find_trendline(candles),
        "liquidity": detect_liquidity_sweep(candles),
        "liquidiound(tp, 5),
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
