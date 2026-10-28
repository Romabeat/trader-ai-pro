
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
    try:
        values = [
            float(candle[k])
            for k in ("open", "high", "low", "close")
        ]
        return (
            all(isfinite(v) and v > 0 for v in values)
            and candle["high"] >= max(candle["open"], candle["close"])
            and candle["low"] <= min(candle["open"], candle["close"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def normalize_candles(candles):
    result = []
    for candle in candles:
        if not valid_candle(candle):
            continue
        result.append({
            "epoch": candle.get("epoch"),
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
        })
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
            and candle["close"] >= candle["low"] + full_range * 0.6
            and body >= full_range * 0.2
        )

    return (
        candle["close"] < candle["open"]
        and candle["close"] <= candle["high"] - full_range * 0.6
        and body >= full_range * 0.2
    )


def build_signal(candles, direction, sr, trendline):
    zone = find_order_block(candles[:-1], direction)
    if not zone:
        return None

    last = candles[-1]
    touched = (
        last["low"] <= zone["high"]
        and last["high"] >= zone["low"]
    )
    if not touched or not candle_confirms(last, direction):
        return None

    support = sr["support"]
    resistance = sr["resistance"]
    midpoint = (zone["low"] + zone["high"]) / 2

    # Confluence simple avec support/résistance.
    tolerance = (zone["high"] - zone["low"]) * 1.5
    if direction == "BUY":
        confluence = support is not None and abs(support - midpoint) <= tolerance
    else:
        confluence = resistance is not None and abs(resistance - midpoint) <= tolerance

    if not confluence:
        return None

    # Trendline contextuelle : elle ne suffit pas à déclencher un signal.
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
        "reason": "OB retest + confirmation + confluence S/R",
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

    # Le contexte de tendance filtre la direction.
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
nsi confirmer un retest.
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
