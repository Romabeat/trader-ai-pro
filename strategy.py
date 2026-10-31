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
# CONFIGURATION
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
# NOMS COMPLETS DES INDICES
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
# OUTILS NUMERIQUES
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
# NORMALISATION DES BOUGIES
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
# CALCUL DE L'ATR
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
# DETECTION DES PIVOTS
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
# REGROUPEMENT DES NIVEAUX HORIZONTAUX
# ============================================================

def _cluster_values(values, tolerance):

    valid_values = sorted(
        value
        for value in values
        if _number(value) is not None
    )

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
# DETECTION DES SUPPORTS ET RESISTANCES
# ============================================================

def _find_horizontal_levels(candles, atr):

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
# ZONES DE REFERENCE D1
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
# VERIFICATION DE L'APPARTENANCE A UNE ZONE
# ============================================================

def _zone_contains(zone, price):

    if not zone or price is None:
        return False

    return (
        zone["low"] <= price <= zone["high"]
    )


# ============================================================
# DETECTION DES REACTIONS INDEPENDANTES EN H4
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

        # Une réaction est représentée par le prix
        # extrême réellement rejeté par la bougie.

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

    # Regroupement des réactions proches dans le temps.
    # Plusieurs bougies consécutives d'une même réaction
    # ne doivent pas être comptées comme plusieurs touches.

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

            old_distance = abs(
                previous["price"] - d1_zone["mid"]
            )

            new_distance = abs(
                reaction["price"] - d1_zone["mid"]
            )

            if new_distance < old_distance:
                independent[-1] = reaction

        else:
            independent.append(reaction)

    return independent


# ============================================================
# AFFINAGE D1 PAR LES REACTIONS H4
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

    # Une zone doit rester suffisamment étroite.
    if refined_high - refined_low > maximum_width:
        return None

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

    # Vérification de la concentration des réactions.
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
# CALCUL DE LA VALEUR D'UNE TRENDLINE
# ============================================================

def _line_value(line, index):

    if not line:
        return None

    return (
        line["slope"] * index
        + line["intercept"]
    )


# ============================================================
# DETECTION ET VALIDATION DES TRENDLINES
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

            # Vérification des contacts indépendants.

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
            # Une cassure importante invalide la droite.

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
# TRENDLINE POUR UNE DIRECTION DONNEE
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
# PARTIE 3/4 — CONFLUENCE MULTI-TIMEFRAME ET CALCUL DU TRADE
# ============================================================

def _levels_near_zone(candles, zone, atr):
    """
    Recherche les niveaux horizontaux H2/H1 proches
    de la zone affinée en H4.
    """
    if not candles or not zone or atr <= 0:
        return []

    levels = _find_horizontal_levels(candles, atr)

    zone_mid = (zone["low"] + zone["high"]) / 2
    max_distance = atr * MAX_CONFLUENCE_DISTANCE_ATR

    return [
        level
        for level in levels
        if abs(level["price"] - zone_mid) <= max_distance
    ]


def _find_next_target(entry, direction, levels, zone):
    """
    Cherche le prochain objectif technique réel
    au-delà du prix d'entrée.
    """
    if not levels:
        return None

    candidates = []

    for level in levels:
        price = level.get("price")

        if price is None:
            continue

        if direction == "BUY" and price > entry:
            if price > zone["high"]:
                candidates.append(price)

        elif direction == "SELL" and price < entry:
            if price < zone["low"]:
                candidates.append(price)

    if not candidates:
        return None

    if direction == "BUY":
        return min(candidates)

    return max(candidates)


def _calculate_trade(
    direction,
    entry,
    zone,
    atr,
    target_levels,
):
    """
    Calcule SL et TP à partir des limites de la zone
    et du prochain objectif technique disponible.
    """
    if atr <= 0 or entry <= 0:
        return None

    buffer = atr * SL_BUFFER_ATR

    if direction == "BUY":
        stop_loss = zone["low"] - buffer
    else:
        stop_loss = zone["high"] + buffer

    take_profit = _find_next_target(
        entry=entry,
        direction=direction,
        levels=target_levels,
        zone=zone,
    )

    if take_profit is None:
        return None

    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)

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


def _build_candidate(
    symbol,
    direction,
    price_now,
    d1_zone,
    h4_zone,
    h4_atr,
    h4_candles,
    h2_candles,
    h1_candles,
    d1_levels,
    h4_levels,
):
    """
    Construit un signal uniquement si :
    - la zone H4 reste dans la zone D1 ;
    - une trendline H4 cohérente existe ;
    - le prix est suffisamment proche de la zone ;
    - une confluence horizontale H2 ou H1 existe ;
    - un objectif technique et un RR acceptable existent.
    """
    if price_now <= 0 or h4_atr <= 0:
        return None

    if not _zone_contains(d1_zone, h4_zone):
        return None

    trendline = _trendline_for_direction(
        h4_candles,
        direction,
        h4_atr,
    )

    if trendline is None:
        return None

    zone_mid = (h4_zone["low"] + h4_zone["high"]) / 2

    trendline_at_price = _line_value(
        trendline,
        len(h4_candles) - 1,
    )

    if trendline_at_price is None:
        return None

    trendline_distance = abs(trendline_at_price - zone_mid)

    if trendline_distance > h4_atr * MAX_CONFLUENCE_DISTANCE_ATR:
        return None

    # Le prix doit être dans la zone ou du bon côté
    # et suffisamment proche pour permettre une entrée.
    if direction == "BUY":
        if price_now < h4_zone["low"] - h4_atr * 0.10:
            return None

        distance = max(0, price_now - h4_zone["high"])

    else:
        if price_now > h4_zone["high"] + h4_atr * 0.10:
            return None

        distance = max(0, h4_zone["low"] - price_now)

    if distance > h4_atr * MAX_ENTRY_DISTANCE_ATR:
        return None

    # Confluences horizontales sur H2 et H1.
    h2_confluences = _levels_near_zone(
        h2_candles,
        h4_zone,
        h4_atr,
    )

    h1_confluences = _levels_near_zone(
        h1_candles,
        h4_zone,
        h4_atr,
    )

    # Il faut au moins une confluence locale.
    if not h2_confluences and not h1_confluences:
        return None

    # Les niveaux des quatre unités de temps peuvent
    # servir à identifier un objectif technique.
    target_levels = (
        d1_levels
        + h4_levels
        + _find_horizontal_levels(h2_candles, h4_atr)
        + _find_horizontal_levels(h1_candles, h4_atr)
    )

    trade = _calculate_trade(
        direction=direction,
        entry=price_now,
        zone=h4_zone,
        atr=h4_atr,
        target_levels=target_levels,
    )

    if trade is None:
        return None

    confluence_score = (
        len(h2_confluences)
        + len(h1_confluences)
    )

    return {
        "symbol": symbol,
        "direction": direction,
        "strategy": STRATEGY_NAME,
        "timeframe": "H4",
        "analysis_timeframes": ["D1", "H4", "H2", "H1"],
        "entry": trade["entry"],
        "stop_loss": trade["stop_loss"],
        "take_profit": trade["take_profit"],
        "rr": trade["rr"],
        "zone_low": round(h4_zone["low"], 5),
        "zone_high": round(h4_zone["high"], 5),
        "d1_zone_low": round(d1_zone["low"], 5),
        "d1_zone_high": round(d1_zone["high"], 5),
        "trendline_price": round(trendline_at_price, 5),
        "h2_confluences": len(h2_confluences),
        "h1_confluences": len(h1_confluences),
        "confluence_score": confluence_score,
        "price_distance_atr": round(distance / h4_atr, 3),
        }
    # ============================================================
# PARTIE 4/4 — ANALYSE PRINCIPALE ET MESSAGES TELEGRAM
# ============================================================

def _make_signal_id(signal):
    """
    Identifiant stable pour éviter les alertes répétées
    sur une même configuration.
    """
    raw = "|".join([
        str(signal.get("symbol", "")),
        str(signal.get("direction", "")),
        str(round(signal.get("zone_low", 0), 2)),
        str(round(signal.get("zone_high", 0), 2)),
        str(signal.get("strategy", "")),
    ])

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]


def find_signals(
    symbol,
    d1,
    h4,
    h2,
    h1,
    price_now,
    diagnostics=None,
):
    """
    Analyse les quatre unités de temps :

    D1 : identification des grandes zones.
    H4 : affinage des zones et trendlines.
    H2 : confluences intermédiaires.
    H1 : confluences locales et précision.

    Aucune confirmation complète n'est obligatoire.
    Les alertes sont anticipées.
    """

    if diagnostics is None:
        diagnostics = {}

    diagnostics["strategy"] = STRATEGY_NAME
    diagnostics["symbol"] = symbol
    diagnostics["status"] = "ANALYSIS_STARTED"

    datasets = {
        "D1": d1,
        "H4": h4,
        "H2": h2,
        "H1": h1,
    }

    # Vérification des historiques disponibles.
    for timeframe, candles in datasets.items():
        if not isinstance(candles, list):
            diagnostics["status"] = "INVALID_CANDLES"
            diagnostics["reason"] = (
                f"Données {timeframe} invalides"
            )
            return []

        if len(candles) < MIN_CANDLES[timeframe]:
            diagnostics["status"] = "INSUFFICIENT_CANDLES"
            diagnostics["reason"] = (
                f"Historique {timeframe} insuffisant"
            )
            return []

    try:
        price_now = _number(price_now)

        if price_now <= 0:
            diagnostics["status"] = "INVALID_PRICE"
            return []

        # Normalisation des données.
        candles = {
            timeframe: _normalise_candles(data)
            for timeframe, data in datasets.items()
        }

        for timeframe, data in candles.items():
            if len(data) < MIN_CANDLES[timeframe]:
                diagnostics["status"] = "INSUFFICIENT_VALID_CANDLES"
                diagnostics["reason"] = (
                    f"Bougies exploitables insuffisantes en {timeframe}"
                )
                return []

        # Calcul des volatilités.
        atr = {
            timeframe: _calculate_atr(
                candles[timeframe],
                ATR_PERIOD,
            )
            for timeframe in ("D1", "H4", "H2", "H1")
        }

        if any(value <= 0 for value in atr.values()):
            diagnostics["status"] = "INVALID_ATR"
            return []

        d1_atr = atr["D1"]
        h4_atr = atr["H4"]

        # Identification des zones principales D1.
        d1_zones = _d1_zones(
            candles["D1"],
            d1_atr,
        )

        if not d1_zones:
            diagnostics["status"] = "NO_D1_ZONE"
            diagnostics["reason"] = (
                "Aucune zone horizontale D1 exploitable"
            )
            return []

        # Niveaux horizontaux utilisables comme objectifs.
        d1_levels = _find_horizontal_levels(
            candles["D1"],
            d1_atr,
        )

        h4_levels = _find_horizontal_levels(
            candles["H4"],
            h4_atr,
        )

        candidates = []

        refined_count = 0

        for d1_zone in d1_zones:

            # Affinage de la zone D1 avec les réactions H4.
            h4_zone = _refine_d1_zone_with_h4(
                d1_zone,
                candles["H4"],
                h4_atr,
            )

            if h4_zone is None:
                continue

            refined_count += 1

            # Chaque zone est évaluée dans les deux directions.
            # Les trendlines et confluences déterminent
            # si une configuration est réellement exploitable.
            for direction in ("BUY", "SELL"):

                candidate = _build_candidate(
                    symbol=symbol,
                    direction=direction,
                    price_now=price_now,
                    d1_zone=d1_zone,
                    h4_zone=h4_zone,
                    h4_atr=h4_atr,
                    h4_candles=candles["H4"],
                    h2_candles=candles["H2"],
                    h1_candles=candles["H1"],
                    d1_levels=d1_levels,
                    h4_levels=h4_levels,
                )

                if candidate is not None:
                    candidates.append(candidate)

        diagnostics["d1_zones_found"] = len(d1_zones)
        diagnostics["h4_zones_refined"] = refined_count
        diagnostics["candidates_found"] = len(candidates)

        if not candidates:
            diagnostics["status"] = "NO_VALID_SIGNAL"
            diagnostics["reason"] = (
                "Aucune configuration ne respecte "
                "les critères de confluence et de risque"
            )
            return []

        # Priorité à la meilleure confluence,
        # puis à la proximité du prix.
        candidates.sort(
            key=lambda item: (
                item["confluence_score"],
                item["rr"],
                -item["price_distance_atr"],
            ),
            reverse=True,
        )

        # Un seul signal par direction et par zone.
        unique_signals = []
        seen = set()

        for signal in candidates:
            signal["signal_id"] = _make_signal_id(signal)

            if signal["signal_id"] in seen:
                continue

            seen.add(signal["signal_id"])
            unique_signals.append(signal)

        diagnostics["signals_returned"] = len(unique_signals)
        diagnostics["status"] = "SIGNALS_FOUND"

        return unique_signals

    except Exception as error:
        diagnostics["status"] = "ANALYSIS_ERROR"
        diagnostics["reason"] = str(error)
        return []


def format_message(signal):
    """
    Prépare le message Telegram.
    Format HTML : scheduled_analysis.py devra envoyer
    le message avec parse_mode='HTML'.
    """

    symbol = signal.get("symbol", "Unknown")
    full_name = SYMBOL_NAMES.get(symbol, symbol)

    direction = signal.get("direction", "UNKNOWN")

    if direction == "BUY":
        direction_label = "ACHAT"
        direction_icon = "🟢"
    else:
        direction_label = "VENTE"
        direction_icon = "🔴"

    entry = signal.get("entry", 0)
    stop_loss = signal.get("stop_loss", 0)
    take_profit = signal.get("take_profit", 0)
    rr = signal.get("rr", 0)

    zone_low = signal.get("zone_low", 0)
    zone_high = signal.get("zone_high", 0)

    h2_count = signal.get("h2_confluences", 0)
    h1_count = signal.get("h1_confluences", 0)

    return (
        f"🚨 <b>TRADER AI PRO — SIGNAL</b>\n\n"
        f"📊 <b>Indice :</b> {full_name}\n"
        f"🔎 <b>Symbole :</b> {symbol}\n"
        f"{direction_icon} <b>Direction :</b> {direction_label}\n\n"
        f"📍 <b>Zone affinée H4 :</b>\n"
        f"{zone_low} — {zone_high}\n\n"
        f"🎯 <b>Entrée indicative :</b> {entry}\n"
        f"🛑 <b>Stop Loss :</b> {stop_loss}\n"
        f"🏁 <b>Take Profit :</b> {take_profit}\n"
        f"⚖️ <b>Risk/Reward :</b> 1:{rr}\n\n"
        f"📐 <b>Confluences :</b>\n"
        f"• H2 : {h2_count}\n"
        f"• H1 : {h1_count}\n"
        f"• Trendline H4 + zone horizontale\n\n"
        f"⏳ <b>Unités analysées :</b> D1 / H4 / H2 / H1\n"
        f"⚠️ <b>Signal anticipé — exécution manuelle uniquement.</b>"
    )
    
    
