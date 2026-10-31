"""
TRADER AI PRO — STRATEGIE TRENDLINE + CONFLUENCE

- Analyse D1, H4, H2 et H1.
- Minimum 200 bougies par timeframe.
- Zones horizontales D1 affinées par les réactions indépendantes H4.
- Trendlines validées par plusieurs contacts.
- Confluence entre supports, résistances et trendlines.
- Entrées anticipées.
- RR minimum : 1:1.
- Aucun SMC, BOS ou Order Block.
- Alertes Telegram uniquement.
- Aucune exécution automatique.
"""

import hashlib
import math


# ============================================================
# 1. CONFIGURATION
# ============================================================

STRATEGY_NAME = "TRENDLINE_SUPPORT_RESISTANCE"

MIN_CANDLES = {
    "D1": 200,
    "H4": 200,
    "H2": 200,
    "H1": 200,
}

ATR_PERIOD = 14

PIVOT_RADIUS = 2
PIVOT_LOOKBACK = 200
LEVEL_LOOKBACK = 200
TRENDLINE_LOOKBACK = 20

LEVEL_CLUSTER_DISTANCE_ATR = 0.22

MAX_CONFLUENCE_DISTANCE_ATR = 0.65
MAX_ENTRY_DISTANCE_ATR = 1.25

SL_BUFFER_ATR = 0.15

MAX_D1_ZONE_WIDTH_ATR = 1.80
MAX_H4_REFINED_WIDTH_ATR = 0.90

MIN_REACTION_TOUCHES = 2
MIN_RR = 1.0

MAX_TARGET_DISTANCE_ATR = 12.0

REACTION_SEPARATION_CANDLES = 2

MIN_TRENDLINE_TOUCHES = 3
TRENDLINE_TOUCH_TOLERANCE_ATR = 0.25

MAX_TRENDLINE_BREAK_ATR = 0.35


# ============================================================
# 2. NOMS COMPLETS DES INDICES
# ============================================================

SYMBOL_NAMES = {
    "1HZ10V": "Volatility 10 (1s) Index",
    "1HZ15V": "Volatility 15 (1s) Index",
    "1HZ25V": "Volatility 25 (1s) Index",
    "1HZ30V": "Volatility 30 (1s) Index",
    "1HZ50V": "Volatility 50 (1s) Index",
    "1HZ75V": "Volatility 75 (1s) Index",
    "1HZ90V": "Volatility 90 (1s) Index",
    "1HZ100V": "Volatility 100 (1s) Index",
    "R_10": "Volatility 10 Index",
    "R_25": "Volatility 25 Index",
    "R_50": "Volatility 50 Index",
    "R_75": "Volatility 75 Index",
    "R_100": "Volatility 100 Index",
}


# ============================================================
# 3. OUTILS NUMERIQUES
# ============================================================

def _number(value):
    try:
        result = float(value)

        if math.isfinite(result):
            return result

        return None

    except (TypeError, ValueError):
        return None


def _get_value(candle, names):

    if not isinstance(candle, dict):
        return None

    for name in names:

        if name in candle:

            value = _number(candle[name])

            if value is not None:
                return value

    return None


# ============================================================
# 4. NORMALISATION DES BOUGIES
# ============================================================

def _normalise_candles(candles):

    result = []

    if not isinstance(candles, (list, tuple)):
        return result

    for candle in candles:

        if not isinstance(candle, dict):
            continue

        opening = _get_value(
            candle,
            ("open", "OPEN", "o"),
        )

        high = _get_value(
            candle,
            ("high", "HIGH", "h"),
        )

        low = _get_value(
            candle,
            ("low", "LOW", "l"),
        )

        close = _get_value(
            candle,
            ("close", "CLOSE", "c"),
        )

        if None in (
            opening,
            high,
            low,
            close,
        ):
            continue

        if min(opening, high, low, close) <= 0:
            continue

        if high < low:
            continue

        if high < max(opening, close):
            continue

        if low > min(opening, close):
            continue

        result.append({
            "open": opening,
            "high": high,
            "low": low,
            "close": close,
        })

    return result


# ============================================================
# 5. CALCUL DE L'ATR
# ============================================================

def _calculate_atr(
    candles,
    period=ATR_PERIOD,
):

    if len(candles) < period + 1:
        return 0.0

    ranges = []

    for index in range(1, len(candles)):

        current = candles[index]
        previous = candles[index - 1]

        true_range = max(
            current["high"] - current["low"],
            abs(
                current["high"] - previous["close"]
            ),
            abs(
                current["low"] - previous["close"]
            ),
        )

        ranges.append(true_range)

    recent_ranges = ranges[-period:]

    if not recent_ranges:
        return 0.0

    atr = (
        sum(recent_ranges)
        / len(recent_ranges)
    )

    if not math.isfinite(atr) or atr <= 0:
        return 0.0

    return atr


# ============================================================
# 6. DETECTION DES PIVOTS
# ============================================================

def _find_pivots(
    candles,
    radius=PIVOT_RADIUS,
):

    highs = []
    lows = []

    if len(candles) < radius * 2 + 5:
        return highs, lows

    start = max(
        radius,
        len(candles) - PIVOT_LOOKBACK,
    )

    end = len(candles) - radius

    for index in range(start, end):

        candle = candles[index]

        left = candles[
            index - radius:index
        ]

        right = candles[
            index + 1:index + radius + 1
        ]

        neighbours = left + right

        is_pivot_high = all(
            candle["high"] >= item["high"]
            for item in neighbours
        )

        is_pivot_low = all(
            candle["low"] <= item["low"]
            for item in neighbours
        )

        if is_pivot_high:

            highs.append((
                index,
                candle["high"],
            ))

        if is_pivot_low:

            lows.append((
                index,
                candle["low"],
            ))

    return highs, lows


# ============================================================
# 7. REGROUPEMENT DES NIVEAUX HORIZONTAUX
# ============================================================

def _cluster_values(values, tolerance):

    valid_values = []

    for value in values:

        number = _number(value)

        if number is not None:
            valid_values.append(number)

    valid_values.sort()

    clusters = []

    for value in valid_values:

        if not clusters:
            clusters.append([value])
            continue

        current = clusters[-1]

        mean = sum(current) / len(current)

        if abs(value - mean) <= tolerance:
            current.append(value)
        else:
            clusters.append([value])

    result = []

    for cluster in clusters:

        result.append({
            "price": sum(cluster) / len(cluster),
            "low": min(cluster),
            "high": max(cluster),
            "touches": len(cluster),
        })

    return result


# ============================================================
# 8. DETECTION DES SUPPORTS ET RESISTANCES
# ============================================================

def _find_horizontal_levels(candles, atr):

    if not candles or atr <= 0:
        return [], []

    highs, lows = _find_pivots(candles)

    tolerance = max(
        atr * LEVEL_CLUSTER_DISTANCE_ATR,
        1e-10,
    )

    supports = _cluster_values(
        [price for _, price in lows],
        tolerance,
    )

    resistances = _cluster_values(
        [price for _, price in highs],
        tolerance,
    )

    return supports, resistances
    # ============================================================
# 9. ZONES DE REFERENCE D1
# ============================================================

def _d1_zones(candles, atr):

    supports, resistances = _find_horizontal_levels(
        candles,
        atr,
    )

    maximum_width = (
        atr * MAX_D1_ZONE_WIDTH_ATR
    )

    supports = [
        zone
        for zone in supports
        if zone["high"] - zone["low"] <= maximum_width
    ]

    resistances = [
        zone
        for zone in resistances
        if zone["high"] - zone["low"] <= maximum_width
    ]

    return supports, resistances


# ============================================================
# 10. VERIFICATION DE L'APPARTENANCE A UNE ZONE
# ============================================================

def _zone_contains(zone, price):

    if not zone or price is None:
        return False

    return (
        zone["low"] <= price <= zone["high"]
    )


# ============================================================
# 11. DETECTION DES REACTIONS INDEPENDANTES EN H4
# ============================================================

def _find_h4_reactions(
    d1_zone,
    h4_candles,
    h4_atr,
):

    if not d1_zone or not h4_candles:
        return []

    d1_low = d1_zone["low"]
    d1_high = d1_zone["high"]

    if d1_high <= d1_low:
        return []

    reactions = []

    recent = h4_candles[-LEVEL_LOOKBACK:]

    for index, candle in enumerate(recent):

        lower_rejection = (
            d1_low <= candle["low"] <= d1_high
            and candle["close"] > candle["low"]
        )

        upper_rejection = (
            d1_low <= candle["high"] <= d1_high
            and candle["close"] < candle["high"]
        )

        if lower_rejection:

            reactions.append({
                "index": index,
                "price": candle["low"],
                "type": "LOWER",
            })

        if upper_rejection:

            reactions.append({
                "index": index,
                "price": candle["high"],
                "type": "UPPER",
            })

    # Les réactions proches dans le temps sont
    # regroupées pour éviter les fausses touches multiples.

    independent = []

    for reaction in reactions:

        if not independent:
            independent.append(reaction)
            continue

        previous = independent[-1]

        separation = (
            reaction["index"] - previous["index"]
        )

        if separation <= REACTION_SEPARATION_CANDLES:

            if reaction["type"] == previous["type"]:

                if reaction["type"] == "LOWER":

                    if reaction["price"] < previous["price"]:
                        independent[-1] = reaction

                else:

                    if reaction["price"] > previous["price"]:
                        independent[-1] = reaction

            else:
                independent.append(reaction)

        else:
            independent.append(reaction)

    return independent


# ============================================================
# 12. AFFINAGE D1 PAR LES REACTIONS H4
# ============================================================

def _refine_d1_zone_with_h4(
    d1_zone,
    h4_candles,
    h4_atr,
):

    if not d1_zone or h4_atr <= 0:
        return None

    reactions = _find_h4_reactions(
        d1_zone,
        h4_candles,
        h4_atr,
    )

    if len(reactions) < MIN_REACTION_TOUCHES:
        return None

    maximum_width = (
        h4_atr * MAX_H4_REFINED_WIDTH_ATR
    )

    tolerance = max(
        h4_atr * 0.12,
        1e-10,
    )

    # Regroupement des réactions selon leur prix.
    prices = sorted(
        reaction["price"]
        for reaction in reactions
    )

    best_cluster = []

    for start in range(len(prices)):

        cluster = []

        for price in prices[start:]:

            if (
                cluster
                and price - cluster[0] > maximum_width
            ):
                break

            cluster.append(price)

        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    if len(best_cluster) < MIN_REACTION_TOUCHES:
        return None

    refined_low = min(best_cluster)
    refined_high = max(best_cluster)

    if refined_high - refined_low > maximum_width:
        return None

    # La zone affinée doit rester dans la zone D1.

    refined_low = max(
        refined_low,
        d1_zone["low"],
    )

    refined_high = min(
        refined_high,
        d1_zone["high"],
    )

    if refined_high <= refined_low:
        return None

    if refined_high - refined_low > tolerance * 8:
        return None

    return {
        "low": refined_low,
        "high": refined_high,
        "mid": (
            refined_low + refined_high
        ) / 2,
        "touches": len(best_cluster),
        "source": "D1_H4_INDEPENDENT_REACTIONS",
    }


# ============================================================
# 13. CALCUL DE LA VALEUR D'UNE TRENDLINE
# ============================================================

def _line_value(line, index):

    if not line:
        return None

    return (
        line["slope"] * index
        + line["intercept"]
    )


# ============================================================
# 14. DETECTION ET VALIDATION DES TRENDLINES
# ============================================================

def _find_trendline(
    pivots,
    candles,
    direction,
    atr,
):

    if len(pivots) < MIN_TRENDLINE_TOUCHES:
        return None

    if atr <= 0 or not candles:
        return None

    recent_pivots = pivots[
        -TRENDLINE_LOOKBACK:
    ]

    if len(recent_pivots) < MIN_TRENDLINE_TOUCHES:
        return None

    last_index = len(candles) - 1

    tolerance = (
        atr * TRENDLINE_TOUCH_TOLERANCE_ATR
    )

    maximum_break = (
        atr * MAX_TRENDLINE_BREAK_ATR
    )

    best_line = None
    best_score = -1

    for first in range(len(recent_pivots) - 2):

        for second in range(
            first + 1,
            len(recent_pivots) - 1,
        ):

            index1, price1 = recent_pivots[first]
            index2, price2 = recent_pivots[second]

            if index2 <= index1:
                continue

            slope = (
                price2 - price1
            ) / (
                index2 - index1
            )

            if direction == "BUY" and slope <= 0:
                continue

            if direction == "SELL" and slope >= 0:
                continue

            intercept = (
                price1 - slope * index1
            )

            line = {
                "slope": slope,
                "intercept": intercept,
                "start_index": index1,
                "end_index": index2,
            }

            touches = 0

            for pivot_index, pivot_price in recent_pivots:

                if not (
                    index1 <= pivot_index <= last_index
                ):
                    continue

                expected = _line_value(
                    line,
                    pivot_index,
                )

                if abs(
                    pivot_price - expected
                ) <= tolerance:

                    touches += 1

            if touches < MIN_TRENDLINE_TOUCHES:
                continue

            # Vérification des cassures par les clôtures.

            broken = False

            for index in range(
                index1,
                len(candles),
            ):

                candle = candles[index]

                expected = _line_value(
                    line,
                    index,
                )

                if direction == "BUY":

                    if candle["close"] < (
                        expected - maximum_break
                    ):
                        broken = True
                        break

                else:

                    if candle["close"] > (
                        expected + maximum_break
                    ):
                        broken = True
                        break

            if broken:
                continue

            current_line_price = _line_value(
                line,
                last_index,
            )

            current_price = candles[-1]["close"]

            distance = abs(
                current_price - current_line_price
            )

            if distance > atr * MAX_ENTRY_DISTANCE_ATR:
                continue

            span = index2 - index1

            score = (
                touches * 100
                + span
                - distance / max(atr, 1e-10)
            )

            if score > best_score:

                best_score = score

                best_line = {
                    "slope": slope,
                    "intercept": intercept,
                    "start_index": index1,
                    "end_index": index2,
                    "touches": touches,
                    "current_price": current_line_price,
                    "distance": distance,
                }

    return best_line


# ============================================================
# 15. TRENDLINE POUR UNE DIRECTION DONNEE
# ============================================================

def _trendline_for_direction(
    candles,
    direction,
    atr,
):

    highs, lows = _find_pivots(candles)

    if direction == "BUY":
        pivots = lows

    elif direction == "SELL":
        pivots = highs

    else:
        return None

    return _find_trendline(
        pivots,
        candles,
        direction,
        atr,
    )
    # ============================================================
# 16. RECHERCHE DES NIVEAUX PROCHES D'UNE ZONE
# ============================================================

def _levels_near_zone(candles, zone, atr):
    """
    Recherche les supports et résistances proches
    de la zone affinée en H4.

    IMPORTANT :
    _find_horizontal_levels retourne deux listes :
    supports et résistances.
    """

    if not candles or not zone or atr <= 0:
        return []

    supports, resistances = _find_horizontal_levels(
        candles,
        atr,
    )

    # On réunit les deux listes pour éviter
    # de traiter une liste comme un dictionnaire.

    levels = supports + resistances

    zone_mid = (
        zone["low"] + zone["high"]
    ) / 2

    max_distance = (
        atr * MAX_CONFLUENCE_DISTANCE_ATR
    )

    nearby = []

    for level in levels:

        price = level["price"]

        if abs(price - zone_mid) <= max_distance:
            nearby.append(level)

    return nearby


# ============================================================
# 17. RECHERCHE DU PROCHAIN OBJECTIF TECHNIQUE
# ============================================================

def _find_next_target(
    entry,
    direction,
    levels,
    zone,
):
    """
    Recherche un support ou une résistance réel(le)
    situé(e) au-delà de la zone et de l'entrée.
    """

    if not levels:
        return None

    candidates = []

    for level in levels:

        if not isinstance(level, dict):
            continue

        price = _number(
            level.get("price")
        )

        if price is None:
            continue

        if direction == "BUY":

            if (
                price > entry
                and price > zone["high"]
            ):
                candidates.append(price)

        elif direction == "SELL":

            if (
                price < entry
                and price < zone["low"]
            ):
                candidates.append(price)

    if not candidates:
        return None

    if direction == "BUY":
        return min(candidates)

    return max(candidates)


# ============================================================
# 18. CALCUL DU STOP LOSS ET TAKE PROFIT
# ============================================================

def _calculate_trade(
    direction,
    entry,
    zone,
    atr,
    target_levels,
):
    """
    Calcule le SL au-delà de la zone affinée
    et le TP sur un objectif technique réel.

    Le signal est rejeté si le RR est inférieur à 1:1.
    """

    if atr <= 0 or entry <= 0:
        return None

    buffer = atr * SL_BUFFER_ATR

    if direction == "BUY":

        stop_loss = (
            zone["low"] - buffer
        )

    elif direction == "SELL":

        stop_loss = (
            zone["high"] + buffer
        )

    else:
        return None

    take_profit = _find_next_target(
        entry=entry,
        direction=direction,
        levels=target_levels,
        zone=zone,
    )

    if take_profit is None:
        return None

    risk = abs(
        entry - stop_loss
    )

    reward = abs(
        take_profit - entry
    )

    if risk <= 0 or reward <= 0:
        return None

    rr = reward / risk

    if rr < MIN_RR:
        return None

    if reward > atr * MAX_TARGET_DISTANCE_ATR:
        return None

    return {
        "entry": round(entry, 5),
        "stop_loss": round(stop_loss, 5),
        "take_profit": round(take_profit, 5),
        "rr": round(rr, 2),
    }


# ============================================================
# 19. VERIFICATION DE LA CONFLUENCE H2 / H1
# ============================================================

def _has_horizontal_confluence(
    h2_levels,
    h1_levels,
    zone,
    atr,
):
    """
    Vérifie qu'au moins un niveau horizontal H2 ou H1
    se trouve à proximité de la zone affinée.
    """

    if atr <= 0:
        return False, []

    zone_mid = zone["mid"]

    maximum_distance = (
        atr * MAX_CONFLUENCE_DISTANCE_ATR
    )

    matches = []

    for timeframe, levels in (
        ("H2", h2_levels),
        ("H1", h1_levels),
    ):

        for level in levels:

            distance = abs(
                level["price"] - zone_mid
            )

            if distance <= maximum_distance:

                matches.append({
                    "timeframe": timeframe,
                    "price": level["price"],
                    "touches": level["touches"],
                    "distance": distance,
                })

    return bool(matches), matches


# ============================================================
# 20. VERIFICATION DE LA PROXIMITE DU PRIX
# ============================================================

def _price_near_zone(
    price,
    zone,
    atr,
):
    """
    Autorise une entrée anticipée lorsque le prix
    approche suffisamment de la zone.
    """

    if price is None or atr <= 0:
        return False

    if zone["low"] <= price <= zone["high"]:
        return True

    distance = min(
        abs(price - zone["low"]),
        abs(price - zone["high"]),
    )

    return (
        distance <= atr * MAX_ENTRY_DISTANCE_ATR
    )


# ============================================================
# 21. VALIDATION DE LA DIRECTION
# ============================================================

def _direction_valid(
    direction,
    price,
    zone,
    trendline,
):
    """
    Vérifie la cohérence entre le côté du prix,
    la zone horizontale et la trendline.
    """

    if not trendline:
        return False

    if direction == "BUY":

        if price > zone["high"]:
            return False

        if price < zone["low"] - 0.5 * abs(
            zone["high"] - zone["low"]
        ):
            return False

        return True

    if direction == "SELL":

        if price < zone["low"]:
            return False

        if price > zone["high"] + 0.5 * abs(
            zone["high"] - zone["low"]
        ):
            return False

        return True

    return False
    # ============================================================
# 22. CONSTRUCTION D'UNE OPPORTUNITE DE TRADING
# ============================================================

def _build_candidate(
    symbol,
    direction,
    refined_zone,
    h4_candles,
    h2_candles,
    h1_candles,
    h4_atr,
    h2_atr,
    h1_atr,
    price_now,
):
    """
    Construit une opportunité à partir de :

    - Zone horizontale D1 affinée par les réactions H4.
    - Trendline H4 validée par au moins 3 contacts.
    - Confluence horizontale H2 ou H1.
    - Entrée anticipée.
    - Objectif technique réel.
    """

    if not refined_zone:
        return None

    if price_now is None or price_now <= 0:
        return None

    if h4_atr <= 0 or h2_atr <= 0 or h1_atr <= 0:
        return None

    zone = refined_zone

    # --------------------------------------------------------
    # A. Vérification de la zone
    # --------------------------------------------------------

    if zone["low"] <= 0 or zone["high"] <= zone["low"]:
        return None

    zone_mid = (
        zone["low"] + zone["high"]
    ) / 2

    zone = {
        "low": zone["low"],
        "high": zone["high"],
        "mid": zone_mid,
        "touches": zone.get("touches", 0),
        "source": zone.get("source", "D1_H4"),
    }

    # --------------------------------------------------------
    # B. Vérification de l'approche du prix
    # --------------------------------------------------------

    if not _price_near_zone(
        price_now,
        zone,
        h4_atr,
    ):
        return None

    # BUY : le prix doit approcher la zone par le dessus.
    if direction == "BUY":

        if price_now < zone["low"] - h4_atr * 0.25:
            return None

    # SELL : le prix doit approcher la zone par le dessous.
    elif direction == "SELL":

        if price_now > zone["high"] + h4_atr * 0.25:
            return None

    else:
        return None

    # --------------------------------------------------------
    # C. Validation de la trendline H4
    # --------------------------------------------------------

    trendline = _trendline_for_direction(
        h4_candles,
        direction,
        h4_atr,
    )

    if not trendline:
        return None

    if trendline.get("touches", 0) < MIN_TRENDLINE_TOUCHES:
        return None

    trendline_price = trendline.get("current_price")

    if trendline_price is None:
        return None

    # La trendline doit se rapprocher de la zone horizontale.
    trendline_distance = abs(
        trendline_price - zone_mid
    )

    if trendline_distance > (
        h4_atr * MAX_CONFLUENCE_DISTANCE_ATR
    ):
        return None

    # --------------------------------------------------------
    # D. Recherche des niveaux H2 et H1
    # --------------------------------------------------------

    h2_levels = _levels_near_zone(
        h2_candles,
        zone,
        h2_atr,
    )

    h1_levels = _levels_near_zone(
        h1_candles,
        zone,
        h1_atr,
    )

    has_confluence, confluence_matches = (
        _has_horizontal_confluence(
            h2_levels,
            h1_levels,
            zone,
            h4_atr,
        )
    )

    if not has_confluence:
        return None

    # --------------------------------------------------------
    # E. Détermination du prix d'entrée anticipé
    # --------------------------------------------------------

    entry = zone_mid

    # Le prix doit encore être suffisamment proche
    # de l'entrée envisagée.

    if abs(price_now - entry) > (
        h4_atr * MAX_ENTRY_DISTANCE_ATR
    ):
        return None

    # --------------------------------------------------------
    # F. Recherche des objectifs techniques
    # --------------------------------------------------------

    h4_supports, h4_resistances = (
        _find_horizontal_levels(
            h4_candles,
            h4_atr,
        )
    )

    h2_supports, h2_resistances = (
        _find_horizontal_levels(
            h2_candles,
            h2_atr,
        )
    )

    h1_supports, h1_resistances = (
        _find_horizontal_levels(
            h1_candles,
            h1_atr,
        )
    )

    target_levels = (
        h4_supports
        + h4_resistances
        + h2_supports
        + h2_resistances
        + h1_supports
        + h1_resistances
    )

    trade = _calculate_trade(
        direction=direction,
        entry=entry,
        zone=zone,
        atr=h4_atr,
        target_levels=target_levels,
    )

    if not trade:
        return None

    # --------------------------------------------------------
    # G. Construction du signal
    # --------------------------------------------------------

    return {
        "symbol": symbol,
        "direction": direction,
        "strategy": STRATEGY_NAME,

        "entry": trade["entry"],
        "stop_loss": trade["stop_loss"],
        "take_profit": trade["take_profit"],
        "rr": trade["rr"],

        "zone_low": round(zone["low"], 5),
        "zone_high": round(zone["high"], 5),
        "zone_mid": round(zone["mid"], 5),

        "zone_touches": zone["touches"],
        "zone_source": zone["source"],

        "trendline_price": round(
            trendline_price,
            5,
        ),

        "trendline_touches": trendline["touches"],

        "trendline_distance": round(
            trendline_distance,
            5,
        ),

        "confluence": confluence_matches,

        "price_at_analysis": round(
            price_now,
            5,
        ),

        "timeframes": [
            "D1",
            "H4",
            "H2",
            "H1",
        ],
    }


# ============================================================
# 23. IDENTIFIANT UNIQUE DU SIGNAL
# ============================================================

def _make_signal_id(signal):
    """
    Génère un identifiant stable pour éviter
    les doublons de signaux.
    """

    content = "|".join([
        str(signal.get("symbol", "")),
        str(signal.get("direction", "")),
        str(signal.get("entry", "")),
        str(signal.get("stop_loss", "")),
        str(signal.get("take_profit", "")),
        STRATEGY_NAME,
    ])

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()[:16]


# ============================================================
# 24. VERIFICATION FINALE DU SIGNAL
# ============================================================

def _validate_signal(signal):
    """
    Dernière vérification de cohérence
    avant de transmettre le signal.
    """

    if not isinstance(signal, dict):
        return False

    entry = _number(signal.get("entry"))
    stop_loss = _number(signal.get("stop_loss"))
    take_profit = _number(signal.get("take_profit"))
    rr = _number(signal.get("rr"))

    if None in (
        entry,
        stop_loss,
        take_profit,
        rr,
    ):
        return False

    if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
        return False

    if rr < MIN_RR:
        return False

    if signal.get("direction") == "BUY":

        if not (
            stop_loss < entry < take_profit
        ):
            return False

    elif signal.get("direction") == "SELL":

        if not (
            take_profit < entry < stop_loss
        ):
            return False

    else:
        return False

    return True
    # ============================================================
# 25. IMPORT POUR SECURISER LES MESSAGES TELEGRAM
# ============================================================

import html


# ============================================================
# 26. FONCTION PRINCIPALE D'ANALYSE MULTI-TIMEFRAME
# ============================================================

def find_signals(
    symbol,
    d1_candles,
    h4_candles,
    h2_candles,
    h1_candles,
    price_now,
    diagnostics=None,
):
    """
    Analyse un indice synthétique sur quatre unités de temps.

    D1 : détection des supports et résistances.
    H4 : affinage des zones et validation des trendlines.
    H2 : recherche de confluence horizontale.
    H1 : recherche de confluence horizontale.

    Les entrées sont anticipées.
    Aucun ordre n'est exécuté automatiquement.
    """

    if diagnostics is None:
        diagnostics = {}

    diagnostics.update({
        "symbol": symbol,
        "strategy": STRATEGY_NAME,
        "status": "ANALYZING",
        "reason": "",
        "signals_found": 0,
    })

    try:

        # ----------------------------------------------------
        # A. NORMALISATION DES DONNEES
        # ----------------------------------------------------

        d1 = _normalise_candles(d1_candles)
        h4 = _normalise_candles(h4_candles)
        h2 = _normalise_candles(h2_candles)
        h1 = _normalise_candles(h1_candles)

        candle_counts = {
            "D1": len(d1),
            "H4": len(h4),
            "H2": len(h2),
            "H1": len(h1),
        }

        diagnostics["candles"] = candle_counts

        # ----------------------------------------------------
        # B. VERIFICATION DU NOMBRE DE BOUGIES
        # ----------------------------------------------------

        for timeframe, candles in (
            ("D1", d1),
            ("H4", h4),
            ("H2", h2),
            ("H1", h1),
        ):

            minimum = MIN_CANDLES[timeframe]

            if len(candles) < minimum:

                diagnostics.update({
                    "status": "INSUFFICIENT_DATA",
                    "reason": (
                        f"{timeframe}: {len(candles)} bougies "
                        f"disponibles, {minimum} nécessaires."
                    ),
                })

                return []

        # ----------------------------------------------------
        # C. VERIFICATION DU PRIX ACTUEL
        # ----------------------------------------------------

        current_price = _number(price_now)

        if current_price is None or current_price <= 0:

            diagnostics.update({
                "status": "INVALID_PRICE",
                "reason": "Prix actuel absent ou invalide.",
            })

            return []

        # ----------------------------------------------------
        # D. CALCUL DES ATR
        # ----------------------------------------------------

        d1_atr = _calculate_atr(d1)
        h4_atr = _calculate_atr(h4)
        h2_atr = _calculate_atr(h2)
        h1_atr = _calculate_atr(h1)

        atr_values = {
            "D1": d1_atr,
            "H4": h4_atr,
            "H2": h2_atr,
            "H1": h1_atr,
        }

        for timeframe, atr in atr_values.items():

            if atr is None or atr <= 0:

                diagnostics.update({
                    "status": "INVALID_ATR",
                    "reason": (
                        f"ATR invalide sur {timeframe}."
                    ),
                })

                return []

        # ----------------------------------------------------
        # E. DETECTION DES ZONES D1
        # ----------------------------------------------------

        d1_supports, d1_resistances = _d1_zones(
            d1,
            d1_atr,
        )

        diagnostics["d1_supports"] = len(d1_supports)
        diagnostics["d1_resistances"] = len(d1_resistances)

        if not d1_supports and not d1_resistances:

            diagnostics.update({
                "status": "NO_VALID_ZONE",
                "reason": (
                    "Aucune zone horizontale D1 suffisamment "
                    "valide n'a été détectée."
                ),
            })

            return []

        # ----------------------------------------------------
        # F. AFFINAGE DES ZONES D1 AVEC LES REACTIONS H4
        # ----------------------------------------------------

        refined_supports = []
        refined_resistances = []

        for zone in d1_supports:

            refined = _refine_d1_zone_with_h4(
                zone,
                h4,
                h4_atr,
            )

            if refined:
                refined_supports.append(refined)

        for zone in d1_resistances:

            refined = _refine_d1_zone_with_h4(
                zone,
                h4,
                h4_atr,
            )

            if refined:
                refined_resistances.append(refined)

        diagnostics["refined_supports"] = len(
            refined_supports
        )

        diagnostics["refined_resistances"] = len(
            refined_resistances
        )

        if not refined_supports and not refined_resistances:

            diagnostics.update({
                "status": "NO_VALID_REFINEMENT",
                "reason": (
                    "Les réactions H4 ne permettent pas "
                    "d'affiner suffisamment les zones D1."
                ),
            })

            return []

        # ----------------------------------------------------
        # G. CONSTRUCTION DES OPPORTUNITES BUY ET SELL
        # ----------------------------------------------------

        candidates = []

        for zone in refined_supports:

            candidate = _build_candidate(
                symbol=symbol,
                direction="BUY",
                refined_zone=zone,
                h4_candles=h4,
                h2_candles=h2,
                h1_candles=h1,
                h4_atr=h4_atr,
                h2_atr=h2_atr,
                h1_atr=h1_atr,
                price_now=current_price,
            )

            if candidate:
                candidates.append(candidate)

        for zone in refined_resistances:

            candidate = _build_candidate(
                symbol=symbol,
                direction="SELL",
                refined_zone=zone,
                h4_candles=h4,
                h2_candles=h2,
                h1_candles=h1,
                h4_atr=h4_atr,
                h2_atr=h2_atr,
                h1_atr=h1_atr,
                price_now=current_price,
            )

            if candidate:
                candidates.append(candidate)

        # ----------------------------------------------------
        # H. VALIDATION ET IDENTIFICATION DES SIGNAUX
        # ----------------------------------------------------

        valid_signals = []

        for candidate in candidates:

            if not _validate_signal(candidate):
                continue

            candidate["signal_id"] = _make_signal_id(
                candidate
            )

            candidate["status"] = "NEW"

            valid_signals.append(candidate)

        # ----------------------------------------------------
        # I. RESULTAT FINAL
        # ----------------------------------------------------

        if not valid_signals:

            diagnostics.update({
                "status": "NO_SIGNAL",
                "reason": (
                    "Aucune configuration ne satisfait "
                    "tous les critères de la stratégie."
                ),
                "signals_found": 0,
            })

            return []

        diagnostics.update({
            "status": "SIGNALS_FOUND",
            "reason": "Configuration(s) valide(s) détectée(s).",
            "signals_found": len(valid_signals),
        })

        return valid_signals

    except Exception as exc:

        diagnostics.update({
            "status": "ANALYSIS_ERROR",
            "reason": (
                f"{type(exc).__name__}: {str(exc)}"
            ),
            "signals_found": 0,
        })

        return []


# ============================================================
# 27. FORMATAGE DU MESSAGE TELEGRAM
# ============================================================

def format_message(signal):
    """
    Produit un message Telegram au format HTML.
    """

    symbol = str(
        signal.get("symbol", "UNKNOWN")
    )

    symbol_name = SYMBOL_NAMES.get(
        symbol,
        symbol,
    )

    direction = signal.get(
        "direction",
        "UNKNOWN",
    )

    direction_label = (
        "ACHAT / BUY"
        if direction == "BUY"
        else "VENTE / SELL"
    )

    emoji = (
        "🟢"
        if direction == "BUY"
        else "🔴"
    )

    entry = signal.get("entry", 0)
    stop_loss = signal.get("stop_loss", 0)
    take_profit = signal.get("take_profit", 0)
    rr = signal.get("rr", 0)

    zone_low = signal.get("zone_low", 0)
    zone_high = signal.get("zone_high", 0)

    trendline_touches = signal.get(
        "trendline_touches",
        0,
    )

    zone_touches = signal.get(
        "zone_touches",
        0,
    )

    signal_id = html.escape(
        str(signal.get("signal_id", "N/A"))
    )

    safe_symbol = html.escape(symbol_name)

    lines = [
        "🚨 <b>TRADER AI PRO</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"📊 <b>Indice :</b> {safe_symbol}",
        f"🔎 <b>Symbole :</b> {html.escape(symbol)}",
        f"{emoji} <b>Direction :</b> {direction_label}",
        "",
        "🎯 <b>PLAN DE TRADING</b>",
        f"📍 Entrée : <code>{entry}</code>",
        f"🛑 Stop Loss : <code>{stop_loss}</code>",
        f"🏁 Take Profit : <code>{take_profit}</code>",
        f"⚖️ Risk/Reward : <b>1:{rr}</b>",
        "",
        "📐 <b>ANALYSE TECHNIQUE</b>",
        f"• Zone affinée : {zone_low} - {zone_high}",
        f"• Réactions de la zone : {zone_touches}",
        f"• Contacts trendline : {trendline_touches}",
        "• Confluence : D1 + H4 + H2 + H1",
        "• Entrée : anticipée",
        "",
        f"🆔 Signal : <code>{signal_id}</code>",
        "",
        "⚠️ <b>ALERTE UNIQUEMENT</b>",
        "Aucun ordre automatique n'est exécuté.",
        "Vérifiez le graphique avant toute prise de position.",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "Trader AI Pro — Analyse technique",
    ]

    return "\n".join(lines)
