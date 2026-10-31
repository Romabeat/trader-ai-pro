"""
TRADER AI PRO
Strategie : SUPPORTS / RESISTANCES + TRENDLINES
Analyse multi-timeframe : D1 / H4 / H2 / H1

Objectif :
- Determiner la direction generale avec D1.
- Identifier les zones techniques sur H4.
- Affiner les niveaux avec H2 et H1.
- Rechercher la confluence entre niveaux horizontaux
  et trendlines.
- Detecter les opportunites anticipees.
- Calculer entree, stop-loss, take-profit et ratio RR.
- Produire des signaux destines aux alertes Telegram.

Aucune execution automatique d'ordres.
"""

import hashlib
import html
import json
import logging
import math
from typing import Any, Optional


# ============================================================
# CONFIGURATION GENERALE
# ============================================================

LOGGER = logging.getLogger("TRADER_AI_PRO.STRATEGY")

MIN_CANDLES = {
    "D1": 200,
    "H4": 200,
    "H2": 200,
    "H1": 200,
}

MIN_RR = 1.0

ATR_PERIOD = 14

PIVOT_RADIUS = 2

LEVEL_CLUSTER_ATR = 0.25

ZONE_ATR_BUFFER = 0.10

MIN_TRENDLINE_CONTACTS = 3

MAX_LEVEL_DISTANCE_ATR = 3.0

MIN_BODY_RATIO = 0.35

MIN_DISPLACEMENT_ATR = 0.50

SIGNAL_VERSION = "SR_TRENDLINE_V1"


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
# OUTILS DE VALIDATION
# ============================================================

def _number(value: Any) -> Optional[float]:
    """Convertit une valeur en nombre fini."""

    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if not math.isfinite(result):
        return None

    return result


def _positive_number(value: Any) -> Optional[float]:
    """Retourne un nombre strictement positif."""

    result = _number(value)

    if result is None or result <= 0:
        return None

    return result


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convertit une valeur avec une valeur de secours."""

    result = _number(value)

    if result is None:
        return default

    return result


def _normalise_direction(value: Any) -> Optional[str]:
    """Normalise la direction d'un signal."""

    if not isinstance(value, str):
        return None

    direction = value.strip().upper()

    if direction in ("BUY", "LONG", "BULLISH"):
        return "BUY"

    if direction in ("SELL", "SHORT", "BEARISH"):
        return "SELL"

    return None


# ============================================================
# NORMALISATION DES BOUGIES
# ============================================================

def _normalise_candles(
    candles: Any,
    timeframe: str = "",
) -> list:
    """
    Valide les bougies OHLC et les trie chronologiquement.

    Chaque bougie doit contenir :
    epoch, open, high, low, close.
    """

    if not isinstance(candles, list):
        return []

    normalised = []

    required = (
        "epoch",
        "open",
        "high",
        "low",
        "close",
    )

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        if not all(key in candle for key in required):
            continue

        epoch = _number(candle.get("epoch"))
        open_price = _number(candle.get("open"))
        high_price = _number(candle.get("high"))
        low_price = _number(candle.get("low"))
        close_price = _number(candle.get("close"))

        values = (
            epoch,
            open_price,
            high_price,
            low_price,
            close_price,
        )

        if any(value is None for value in values):
            continue

        if high_price < low_price:
            continue

        if high_price < max(open_price, close_price):
            continue

        if low_price > min(open_price, close_price):
            continue

        normalised.append({
            "epoch": int(epoch),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
        })

    normalised.sort(key=lambda item: item["epoch"])

    # Elimine les doublons de timestamp.
    unique = []
    seen_epochs = set()

    for candle in normalised:
        epoch = candle["epoch"]

        if epoch in seen_epochs:
            continue

        seen_epochs.add(epoch)
        unique.append(candle)

    minimum = MIN_CANDLES.get(timeframe, 1)

    if len(unique) < minimum:
        LOGGER.warning(
            "Bougies insuffisantes pour %s : %s/%s",
            timeframe or "timeframe inconnu",
            len(unique),
            minimum,
        )
        return []

    return unique
    # ============================================================
# CALCUL DE L'ATR
# ============================================================

def _calculate_atr(
    candles: list,
    period: int = ATR_PERIOD,
) -> Optional[float]:
    """Calcule l'Average True Range."""

    if not isinstance(candles, list):
        return None

    if period < 1 or len(candles) < period + 1:
        return None

    true_ranges = []

    for index in range(1, len(candles)):
        previous_close = candles[index - 1]["close"]
        current = candles[index]

        high = current["high"]
        low = current["low"]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        if math.isfinite(true_range):
            true_ranges.append(true_range)

    if len(true_ranges) < period:
        return None

    recent_ranges = true_ranges[-period:]
    atr = sum(recent_ranges) / period

    if not math.isfinite(atr) or atr <= 0:
        return None

    return atr


# ============================================================
# IDENTIFICATION DES PIVOTS
# ============================================================

def _find_pivots(
    candles: list,
    radius: int = PIVOT_RADIUS,
) -> dict:
    """
    Identifie les sommets et creux locaux.

    Un pivot n'est retenu que si son prix est distinct
    des prix observes autour de lui.
    """

    result = {
        "highs": [],
        "lows": [],
    }

    if not isinstance(candles, list):
        return result

    if radius < 1:
        return result

    if len(candles) < radius * 2 + 1:
        return result

    for index in range(radius, len(candles) - radius):
        current = candles[index]

        left = candles[index - radius:index]
        right = candles[index + 1:index + radius + 1]

        surrounding = left + right

        current_high = current["high"]
        current_low = current["low"]

        is_high = all(
            current_high >= item["high"]
            for item in surrounding
        )

        is_low = all(
            current_low <= item["low"]
            for item in surrounding
        )

        if is_high:
            result["highs"].append({
                "index": index,
                "epoch": current["epoch"],
                "price": current_high,
            })

        if is_low:
            result["lows"].append({
                "index": index,
                "epoch": current["epoch"],
                "price": current_low,
            })

    return result


# ============================================================
# REGROUPEMENT DES NIVEAUX PROCHES
# ============================================================

def _cluster_values(
    values: list,
    tolerance: float,
) -> list:
    """
    Regroupe les prix proches pour identifier
    des zones de support et de resistance.
    """

    if not values or tolerance <= 0:
        return []

    sorted_values = sorted(
        value
        for value in values
        if _number(value) is not None
    )

    if not sorted_values:
        return []

    clusters = []
    current_cluster = [sorted_values[0]]

    for value in sorted_values[1:]:
        cluster_mean = (
            sum(current_cluster) / len(current_cluster)
        )

        if abs(value - cluster_mean) <= tolerance:
            current_cluster.append(value)
        else:
            clusters.append(current_cluster)
            current_cluster = [value]

    clusters.append(current_cluster)

    results = []

    for cluster in clusters:
        results.append({
            "price": sum(cluster) / len(cluster),
            "touches": len(cluster),
            "low": min(cluster),
            "high": max(cluster),
        })

    return results


# ============================================================
# RECHERCHE DES SUPPORTS ET RESISTANCES
# ============================================================

def _find_horizontal_levels(
    candles: list,
    atr: Optional[float] = None,
) -> dict:
    """
    Detecte les niveaux horizontaux a partir des pivots.
    """

    empty_result = {
        "supports": [],
        "resistances": [],
    }

    if not candles:
        return empty_result

    if atr is None:
        atr = _calculate_atr(candles)

    if atr is None or atr <= 0:
        return empty_result

    pivots = _find_pivots(candles)

    tolerance = atr * LEVEL_CLUSTER_ATR

    support_clusters = _cluster_values(
        [item["price"] for item in pivots["lows"]],
        tolerance,
    )

    resistance_clusters = _cluster_values(
        [item["price"] for item in pivots["highs"]],
        tolerance,
    )

    for level in support_clusters:
        level["type"] = "SUPPORT"

    for level in resistance_clusters:
        level["type"] = "RESISTANCE"

    return {
        "supports": support_clusters,
        "resistances": resistance_clusters,
}
    # ============================================================
# DETERMINATION DE LA DIRECTION SUR D1
# ============================================================

def _d1_zones(candles: list) -> dict:
    """
    Analyse D1 pour identifier les zones techniques
    et determiner le biais directionnel general.
    """

    result = {
        "direction": None,
        "atr": None,
        "levels": {
            "supports": [],
            "resistances": [],
        },
        "last_close": None,
    }

    candles = _normalise_candles(candles, "D1")

    if not candles:
        return result

    atr = _calculate_atr(candles)

    if atr is None:
        return result

    levels = _find_horizontal_levels(candles, atr)

    result["atr"] = atr
    result["levels"] = levels
    result["last_close"] = candles[-1]["close"]

    # Utilise les dernieres bougies pour estimer
    # la direction generale, sans garantir le mouvement.
    recent = candles[-20:]

    first_close = recent[0]["close"]
    last_close = recent[-1]["close"]

    movement = last_close - first_close

    if movement > atr * 0.5:
        result["direction"] = "BUY"

    elif movement < -atr * 0.5:
        result["direction"] = "SELL"

    return result


# ============================================================
# RECHERCHE DES REACTIONS SUR H4
# ============================================================

def _find_h4_reactions(
    candles: list,
    levels: dict,
    atr: Optional[float] = None,
) -> list:
    """
    Recherche les reactions du prix autour des niveaux
    horizontaux sur H4.
    """

    candles = _normalise_candles(candles, "H4")

    if not candles or not isinstance(levels, dict):
        return []

    if atr is None:
        atr = _calculate_atr(candles)

    if atr is None or atr <= 0:
        return []

    reactions = []

    all_levels = (
        levels.get("supports", [])
        + levels.get("resistances", [])
    )

    recent_candles = candles[-60:]

    for level in all_levels:
        if not isinstance(level, dict):
            continue

        price = _number(level.get("price"))

        if price is None:
            continue

        touches = 0
        last_touch = None

        for index, candle in enumerate(recent_candles):
            distance = min(
                abs(candle["high"] - price),
                abs(candle["low"] - price),
                abs(candle["close"] - price),
            )

            if distance <= atr * LEVEL_CLUSTER_ATR:
                touches += 1
                last_touch = index

        if touches == 0:
            continue

        reactions.append({
            "price": price,
            "type": level.get("type", "LEVEL"),
            "touches": touches,
            "last_touch": last_touch,
            "strength": touches,
        })

    reactions.sort(
        key=lambda item: (
            item["strength"],
            item["last_touch"]
            if item["last_touch"] is not None
            else -1,
        ),
        reverse=True,
    )

    return reactions


# ============================================================
# AFFINAGE D'UNE ZONE D1 AVEC H4
# ============================================================

def _refine_d1_zone_with_h4(
    d1_zone: dict,
    h4_candles: list,
    atr: Optional[float] = None,
) -> Optional[dict]:
    """
    Affine une zone technique D1 en utilisant
    les reactions observees sur H4.
    """

    if not isinstance(d1_zone, dict):
        return None

    low = _number(d1_zone.get("low"))
    high = _number(d1_zone.get("high"))

    if low is None or high is None or high < low:
        return None

    candles = _normalise_candles(h4_candles, "H4")

    if not candles:
        return None

    if atr is None:
        atr = _calculate_atr(candles)

    if atr is None or atr <= 0:
        return None

    relevant = []

    for candle in candles[-60:]:
        if candle["high"] < low or candle["low"] > high:
            continue

        relevant.append(candle)

    if not relevant:
        return {
            "low": low,
            "high": high,
            "source": "D1",
        }

    refined_low = max(
        low,
        min(item["low"] for item in relevant),
    )

    refined_high = min(
        high,
        max(item["high"] for item in relevant),
    )

    if refined_high < refined_low:
        return None

    return {
        "low": refined_low,
        "high": refined_high,
        "source": "D1_H4",
    }
    # ============================================================
# CALCUL DE LA VALEUR D'UNE TRENDLINE
# ============================================================

def _line_value(
    point_a: dict,
    point_b: dict,
    index: int,
) -> Optional[float]:
    """Calcule le prix estime d'une droite entre deux pivots."""

    if not isinstance(point_a, dict):
        return None

    if not isinstance(point_b, dict):
        return None

    x1 = _number(point_a.get("index"))
    y1 = _number(point_a.get("price"))
    x2 = _number(point_b.get("index"))
    y2 = _number(point_b.get("price"))

    if any(value is None for value in (x1, y1, x2, y2)):
        return None

    if x1 == x2:
        return None

    slope = (y2 - y1) / (x2 - x1)

    value = y1 + slope * (index - x1)

    if not math.isfinite(value):
        return None

    return value


# ============================================================
# DETECTION DES TRENDLINES
# ============================================================

def _find_trendline(
    candles: list,
    pivot_type: str,
    atr: Optional[float] = None,
) -> Optional[dict]:
    """
    Recherche une trendline a partir des pivots.

    pivot_type :
    - lows : trendline potentiellement haussiere.
    - highs : trendline potentiellement baissiere.
    """

    candles = _normalise_candles(candles)

    if len(candles) < 20:
        return None

    if atr is None:
        atr = _calculate_atr(candles)

    if atr is None or atr <= 0:
        return None

    pivots = _find_pivots(candles)

    if pivot_type == "lows":
        points = pivots["lows"]
        direction = "BUY"

    elif pivot_type == "highs":
        points = pivots["highs"]
        direction = "SELL"

    else:
        return None

    if len(points) < 2:
        return None

    tolerance = atr * LEVEL_CLUSTER_ATR
    best_line = None

    # Examine les paires de pivots recents.
    recent_points = points[-12:]

    for first_index in range(len(recent_points) - 1):
        for second_index in range(
            first_index + 1,
            len(recent_points),
        ):
            point_a = recent_points[first_index]
            point_b = recent_points[second_index]

            if point_b["index"] <= point_a["index"]:
                continue

            # La ligne doit avoir une pente coherente.
            if direction == "BUY":
                if point_b["price"] <= point_a["price"]:
                    continue
            else:
                if point_b["price"] >= point_a["price"]:
                    continue

            contacts = []

            for point in points:
                line_price = _line_value(
                    point_a,
                    point_b,
                    point["index"],
                )

                if line_price is None:
                    continue

                if abs(point["price"] - line_price) <= tolerance:
                    contacts.append(point)

            if len(contacts) < 2:
                continue

            current_index = len(candles) - 1

            current_value = _line_value(
                point_a,
                point_b,
                current_index,
            )

            if current_value is None:
                continue

            candidate = {
                "direction": direction,
                "point_a": point_a,
                "point_b": point_b,
                "value": current_value,
                "contacts": len(contacts),
                "slope": (
                    point_b["price"] - point_a["price"]
                ) / (
                    point_b["index"] - point_a["index"]
                ),
            }

            if (
                best_line is None
                or candidate["contacts"] > best_line["contacts"]
            ):
                best_line = candidate

    return best_line
    # ============================================================
# SELECTION DE LA TRENDLINE SELON LA DIRECTION
# ============================================================

def _trendline_for_direction(
    candles: list,
    direction: str,
    atr: Optional[float] = None,
) -> Optional[dict]:
    """Selectionne la trendline correspondant au biais."""

    direction = _normalise_direction(direction)

    if direction is None:
        return None

    pivot_type = "lows" if direction == "BUY" else "highs"

    trendline = _find_trendline(
        candles,
        pivot_type,
        atr,
    )

    if trendline is None:
        return None

    if trendline.get("direction") != direction:
        return None

    # Exige au moins trois contacts distincts.
    if trendline.get("contacts", 0) < MIN_TRENDLINE_CONTACTS:
        return None

    return trendline


# ============================================================
# PROXIMITE ENTRE LE PRIX ET UNE ZONE
# ============================================================

def _price_near_zone(
    price: float,
    zone: dict,
    atr: Optional[float] = None,
) -> bool:
    """Verifie si le prix se trouve pres d'une zone."""

    price = _number(price)

    if price is None or not isinstance(zone, dict):
        return False

    low = _number(zone.get("low"))
    high = _number(zone.get("high"))

    if low is None or high is None or high < low:
        return False

    if low <= price <= high:
        return True

    if atr is None or atr <= 0:
        return False

    distance = atr * MAX_LEVEL_DISTANCE_ATR

    return (
        price >= low - distance
        and price <= high + distance
    )


# ============================================================
# PROXIMITE ENTRE TRENDLINE ET ZONE
# ============================================================

def _trendline_near_zone(
    trendline: Optional[dict],
    zone: dict,
    atr: Optional[float] = None,
) -> bool:
    """Verifie la convergence d'une trendline et d'une zone."""

    if not isinstance(trendline, dict):
        return False

    if not isinstance(zone, dict):
        return False

    value = _number(trendline.get("value"))
    low = _number(zone.get("low"))
    high = _number(zone.get("high"))

    if any(item is None for item in (value, low, high)):
        return False

    if high < low:
        return False

    if low <= value <= high:
        return True

    if atr is None or atr <= 0:
        return False

    return (
        abs(value - low) <= atr * LEVEL_CLUSTER_ATR
        or abs(value - high) <= atr * LEVEL_CLUSTER_ATR
    )


# ============================================================
# VALIDATION DU BIAIS DIRECTIONNEL
# ============================================================

def _direction_valid(
    direction: str,
    d1_analysis: dict,
) -> bool:
    """Verifie que le signal respecte le biais D1."""

    direction = _normalise_direction(direction)

    if direction is None or not isinstance(d1_analysis, dict):
        return False

    d1_direction = _normalise_direction(
        d1_analysis.get("direction")
    )

    if d1_direction is None:
        return False

    return direction == d1_direction 
# ============================================================
# CONFLUENCE DES NIVEAUX HORIZONTAUX
# ============================================================

def _levels_near_zone(
    levels: dict,
    zone: dict,
    atr: Optional[float] = None,
) -> list:
    """Recupere les niveaux horizontaux proches d'une zone."""

    if not isinstance(levels, dict):
        return []

    if not isinstance(zone, dict):
        return []

    low = _number(zone.get("low"))
    high = _number(zone.get("high"))

    if low is None or high is None or high < low:
        return []

    tolerance = 0.0

    if atr is not None and atr > 0:
        tolerance = atr * LEVEL_CLUSTER_ATR

    nearby = []

    for level_type in ("supports", "resistances"):
        for level in levels.get(level_type, []):
            if not isinstance(level, dict):
                continue

            price = _number(level.get("price"))

            if price is None:
                continue

            if low - tolerance <= price <= high + tolerance:
                nearby.append({
                    "price": price,
                    "type": level.get("type", level_type),
                    "touches": int(
                        _safe_float(level.get("touches"), 0)
                    ),
                })

    return nearby


# ============================================================
# VERIFICATION DE LA CONFLUENCE HORIZONTALE
# ============================================================

def _has_horizontal_confluence(
    levels: dict,
    zone: dict,
    atr: Optional[float] = None,
) -> bool:
    """Determine si une zone coincide avec un niveau horizontal."""

    nearby = _levels_near_zone(
        levels,
        zone,
        atr,
    )

    return len(nearby) > 0


# ============================================================
# RECHERCHE DU PROCHAIN OBJECTIF TECHNIQUE
# ============================================================

def _find_next_target(
    entry: float,
    direction: str,
    levels: dict,
    zone: dict,
) -> Optional[float]:
    """
    Recherche le prochain niveau technique exploitable
    dans le sens du trade.
    """

    entry = _number(entry)
    direction = _normalise_direction(direction)

    if entry is None or direction is None:
        return None

    if not isinstance(levels, dict):
        return None

    if not isinstance(zone, dict):
        return None

    low = _number(zone.get("low"))
    high = _number(zone.get("high"))

    if low is None or high is None or high < low:
        return None

    candidates = []

    target_key = (
        "resistances"
        if direction == "BUY"
        else "supports"
    )

    for level in levels.get(target_key, []):
        if not isinstance(level, dict):
            continue

        price = _number(level.get("price"))

        if price is None:
            continue

        if direction == "BUY":
            if price > entry and price > high:
                candidates.append(price)

        else:
            if price < entry and price < low:
                candidates.append(price)

    if not candidates:
        return None

    if direction == "BUY":
        return min(candidates)

    return max(candidates)
    # ============================================================
# CALCUL DU TRADE
# ============================================================

def _calculate_trade(
    direction: str,
    entry: float,
    zone: dict,
    atr: float,
    target_levels: dict,
) -> Optional[dict]:
    """Calcule entree, stop-loss, take-profit et ratio risque/rendement."""

    direction = _normalise_direction(direction)
    entry = _number(entry)
    atr = _positive_number(atr)

    if direction is None or entry is None or atr is None:
        return None

    if not isinstance(zone, dict):
        return None

    low = _number(zone.get("low"))
    high = _number(zone.get("high"))

    if low is None or high is None or high < low:
        return None

    buffer = atr * ZONE_ATR_BUFFER

    if direction == "BUY":
        stop_loss = low - buffer

        if stop_loss >= entry:
            return None

    else:
        stop_loss = high + buffer

        if stop_loss <= entry:
            return None

    take_profit = _find_next_target(
        entry,
        direction,
        target_levels,
        zone,
    )

    if take_profit is None:
        return None

    if direction == "BUY":
        risk = entry - stop_loss
        reward = take_profit - entry
    else:
        risk = stop_loss - entry
        reward = entry - take_profit

    if risk <= 0 or reward <= 0:
        return None

    rr = reward / risk

    if not math.isfinite(rr) or rr < MIN_RR:
        return None

    return {
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk": risk,
        "reward": reward,
        "rr": rr,
        "zone": {
            "low": low,
            "high": high,
        },
    }


# ============================================================
# RECHERCHE D'UNE BOUGIE DE DEPLACEMENT
# ============================================================

def _has_displacement(
    candles: list,
    direction: str,
    atr: float,
) -> bool:
    """Detecte un mouvement recent suffisamment marque."""

    direction = _normalise_direction(direction)
    atr = _positive_number(atr)

    if direction is None or atr is None:
        return False

    if not isinstance(candles, list) or not candles:
        return False

    for candle in candles[-3:]:
        open_price = _number(candle.get("open"))
        close_price = _number(candle.get("close"))
        high = _number(candle.get("high"))
        low = _number(candle.get("low"))

        if any(
            value is None
            for value in (
                open_price,
                close_price,
                high,
                low,
            )
        ):
            continue

        candle_range = high - low

        if candle_range <= 0:
            continue

        body = abs(close_price - open_price)
        body_ratio = body / candle_range

        if body_ratio < MIN_BODY_RATIO:
            continue

        if body < atr * MIN_DISPLACEMENT_ATR:
            continue

        if direction == "BUY" and close_price > open_price:
            return True

        if direction == "SELL" and close_price < open_price:
            return True

    return False
    # ============================================================
# VERIFICATION DE LA CONFLUENCE MULTI-TIMEFRAME
# ============================================================

def _timeframe_direction(
    candles: list,
    timeframe: str,
) -> Optional[str]:
    """Determine la direction generale d'une unite de temps."""

    normalized = _normalise_candles(candles, timeframe)

    if len(normalized) < MIN_CANDLES.get(timeframe, 200):
        return None

    atr = _calculate_atr(normalized)

    if atr is None or atr <= 0:
        return None

    recent = normalized[-20:]
    first_close = _number(recent[0].get("close"))
    last_close = _number(recent[-1].get("close"))

    if first_close is None or last_close is None:
        return None

    movement = last_close - first_close

    if movement >= atr * 0.5:
        return "BUY"

    if movement <= -atr * 0.5:
        return "SELL"

    return None


def _multi_timeframe_agreement(
    market_data: dict,
    direction: str,
) -> bool:
    """Verifie que les grandes unites ne contredisent pas le signal."""

    direction = _normalise_direction(direction)

    if direction is None or not isinstance(market_data, dict):
        return False

    d1_direction = _timeframe_direction(
        market_data.get("D1", []),
        "D1",
    )

    h4_direction = _timeframe_direction(
        market_data.get("H4", []),
        "H4",
    )

    # Le Daily doit obligatoirement soutenir la direction.
    if d1_direction != direction:
        return False

    # H4 ne doit pas contredire la direction.
    if h4_direction is not None and h4_direction != direction:
        return False

    return True


# ============================================================
# VALIDATION DU PRIX D'ENTREE
# ============================================================

def _validate_entry_price(
    current_price: float,
    zone: dict,
    atr: float,
) -> bool:
    """Verifie que le prix reste suffisamment proche de la zone."""

    current_price = _positive_number(current_price)
    atr = _positive_number(atr)

    if current_price is None or atr is None:
        return False

    if not isinstance(zone, dict):
        return False

    low = _number(zone.get("low"))
    high = _number(zone.get("high"))

    if low is None or high is None or high < low:
        return False

    # Accepte un prix dans la zone ou proche de celle-ci.
    tolerance = atr * MAX_LEVEL_DISTANCE_ATR

    return low - tolerance <= current_price <= high + tolerance
    # ============================================================
# ANALYSE D'UN SYMBOLE
# ============================================================

def _analyze_symbol(
    symbol: str,
    market_data: dict,
) -> Optional[dict]:
    """Recherche un signal base sur supports, resistances et trendline."""

    if not isinstance(symbol, str) or not symbol.strip():
        return None

    if not isinstance(market_data, dict):
        return None

    # Recuperation des donnees multi-timeframe.
    d1_candles = _normalise_candles(
        market_data.get("D1", []),
        "D1",
    )
    h4_candles = _normalise_candles(
        market_data.get("H4", []),
        "H4",
    )
    h2_candles = _normalise_candles(
        market_data.get("H2", []),
        "H2",
    )
    h1_candles = _normalise_candles(
        market_data.get("H1", []),
        "H1",
    )

    # Toutes les unites de temps sont obligatoires.
    if any(
        len(candles) < MIN_CANDLES[timeframe]
        for timeframe, candles in (
            ("D1", d1_candles),
            ("H4", h4_candles),
            ("H2", h2_candles),
            ("H1", h1_candles),
        )
    ):
        LOGGER.info(
            "%s : donnees insuffisantes pour l'analyse.",
            symbol,
        )
        return None

    current_price = _positive_number(
        market_data.get("current_price")
    )

    if current_price is None:
        current_price = _positive_number(
            h1_candles[-1].get("close")
        )

    if current_price is None:
        return None

    # Le Daily determine le biais directionnel.
    d1_analysis = _d1_zones(d1_candles)

    if not isinstance(d1_analysis, dict):
        return None

    direction = _normalise_direction(
        d1_analysis.get("direction")
    )

    if direction is None:
        return None

    # Le prix doit rester dans une zone technique exploitable.
    d1_atr = _positive_number(d1_analysis.get("atr"))

    if d1_atr is None:
        return None

    d1_levels = d1_analysis.get("levels", {})

    if not isinstance(d1_levels, dict):
        return None

    # Verification du contexte H4.
    if not _multi_timeframe_agreement(
        {
            "D1": d1_candles,
            "H4": h4_candles,
        },
        direction,
    ):
        return None

    # Calcul des niveaux techniques sur H4.
    h4_atr = _calculate_atr(h4_candles)

    if h4_atr is None or h4_atr <= 0:
        return None

    h4_levels = _find_horizontal_levels(
        h4_candles,
        h4_atr,
    )

    if not isinstance(h4_levels, dict):
        return None

    # Les prochaines parties completeront la selection
    # de la zone, la trendline et la validation du signal.
    return {
        "symbol": symbol,
        "direction": direction,
        "current_price": current_price,
        "d1_analysis": d1_analysis,
        "d1_levels": d1_levels,
        "h4_levels": h4_levels,
        "h4_atr": h4_atr,
        "d1_candles": d1_candles,
        "h4_candles": h4_candles,
        "h2_candles": h2_candles,
        "h1_candles": h1_candles,
    }
    # ============================================================
# SELECTION DE LA ZONE TECHNIQUE
# ============================================================

def _select_candidate_zone(
    direction: str,
    current_price: float,
    levels: dict,
    atr: float,
) -> Optional[dict]:
    """Selectionne le niveau horizontal le plus proche du prix."""

    direction = _normalise_direction(direction)
    current_price = _positive_number(current_price)
    atr = _positive_number(atr)

    if (
        direction is None
        or current_price is None
        or atr is None
        or not isinstance(levels, dict)
    ):
        return None

    if direction == "BUY":
        candidates = levels.get("supports", [])
        expected_type = "support"
    else:
        candidates = levels.get("resistances", [])
        expected_type = "resistance"

    if not isinstance(candidates, list):
        return None

    valid_zones = []

    for level in candidates:
        if not isinstance(level, dict):
            continue

        price = _positive_number(level.get("price"))

        if price is None:
            continue

        distance = abs(current_price - price)

        if distance > atr * MAX_LEVEL_DISTANCE_ATR:
            continue

        valid_zones.append({
            "type": expected_type,
            "low": _number(level.get("low"))
            if _number(level.get("low")) is not None
            else price,
            "high": _number(level.get("high"))
            if _number(level.get("high")) is not None
            else price,
            "price": price,
            "touches": int(
                _safe_float(level.get("touches"), 0)
            ),
            "distance": distance,
        })

    if not valid_zones:
        return None

    # Priorite au niveau le plus proche du prix actuel.
    valid_zones.sort(
        key=lambda item: (
            item["distance"],
            -item["touches"],
        )
    )

    return valid_zones[0]


# ============================================================
# VERIFICATION DE LA QUALITE DE LA ZONE
# ============================================================

def _validate_candidate_zone(
    zone: dict,
    current_price: float,
    direction: str,
) -> bool:
    """Rejette les zones incoherentes avec le sens du trade."""

    if not isinstance(zone, dict):
        return False

    direction = _normalise_direction(direction)
    current_price = _positive_number(current_price)
    low = _number(zone.get("low"))
    high = _number(zone.get("high"))
    level_price = _number(zone.get("price"))

    if (
        direction is None
        or current_price is None
        or low is None
        or high is None
        or level_price is None
    ):
        return False

    if high < low:
        return False

    if not low <= level_price <= high:
        return False

    if direction == "BUY":
        # Un support doit etre situe sous le prix ou
        # pouvoir etre teste depuis sa zone superieure.
        if level_price > current_price:
            return False
    else:
        # Une resistance doit etre situee au-dessus du prix
        # ou pouvoir etre testee depuis sa zone inferieure.
        if level_price < current_price:
            return False

    return True
    # ============================================================
# RECHERCHE DE LA CONFLUENCE SUPPORT / RESISTANCE + TRENDLINE
# ============================================================

def _build_confluence_zone(
    analysis: dict,
) -> Optional[dict]:
    """Combine une zone horizontale et une trendline exploitable."""

    if not isinstance(analysis, dict):
        return None

    direction = _normalise_direction(
        analysis.get("direction")
    )
    current_price = _positive_number(
        analysis.get("current_price")
    )
    h4_atr = _positive_number(
        analysis.get("h4_atr")
    )
    h4_levels = analysis.get("h4_levels")
    h4_candles = analysis.get("h4_candles")

    if (
        direction is None
        or current_price is None
        or h4_atr is None
        or not isinstance(h4_levels, dict)
        or not isinstance(h4_candles, list)
    ):
        return None

    # Selection du support pour un achat ou de la resistance
    # pour une vente.
    zone = _select_candidate_zone(
        direction,
        current_price,
        h4_levels,
        h4_atr,
    )

    if zone is None:
        return None

    if not _validate_candidate_zone(
        zone,
        current_price,
        direction,
    ):
        return None

    # La trendline doit avoir au moins trois contacts.
    trendline = _trendline_for_direction(
        h4_candles,
        direction,
        h4_atr,
    )

    if not isinstance(trendline, dict):
        LOGGER.debug(
            "%s : trendline insuffisante pour %s.",
            analysis.get("symbol", "UNKNOWN"),
            direction,
        )
        return None

    if not _trendline_near_zone(
        trendline,
        zone,
        h4_atr,
    ):
        return None

    # La zone doit egalement etre proche du prix actuel.
    if not _price_near_zone(
        current_price,
        zone,
        h4_atr,
    ):
        return None

    zone["trendline_value"] = _number(
        trendline.get("value")
    )
    zone["trendline_contacts"] = int(
        _safe_float(trendline.get("contacts"), 0)
    )
    zone["confluence"] = True

    return zone


# ============================================================
# VALIDATION DE LA REACTION DU PRIX
# ============================================================

def _validate_price_reaction(
    candles: list,
    direction: str,
    zone: dict,
) -> bool:
    """Verifie si les bougies recentes montrent une reaction exploitable."""

    direction = _normalise_direction(direction)

    if (
        direction is None
        or not isinstance(candles, list)
        or not candles
        or not isinstance(zone, dict)
    ):
        return False

    low = _number(zone.get("low"))
    high = _number(zone.get("high"))

    if low is None or high is None or high < low:
        return False

    # Examiner les trois dernieres bougies disponibles.
    for candle in candles[-3:]:
        candle_low = _number(candle.get("low"))
        candle_high = _number(candle.get("high"))
        open_price = _number(candle.get("open"))
        close_price = _number(candle.get("close"))

        if any(
            value is None
            for value in (
                candle_low,
                candle_high,
                open_price,
                close_price,
            )
        ):
            continue

        # La bougie doit avoir touche ou traverse la zone.
        touched_zone = (
            candle_low <= high
            and candle_high >= low
        )

        if not touched_zone:
            continue

        # Une reaction haussiere pour BUY.
        if direction == "BUY" and close_price > open_price:
            return True

        # Une reaction baissiere pour SELL.
        if direction == "SELL" and close_price < open_price:
            return True

    return False
    # ============================================================
# GENERATION DU SIGNAL
# ============================================================

def _generate_signal(
    symbol: str,
    analysis: dict,
) -> Optional[dict]:
    """Construit un signal a partir des confluences detectees."""

    if not isinstance(analysis, dict):
        return None

    direction = _normalise_direction(
        analysis.get("direction")
    )

    current_price = _positive_number(
        analysis.get("current_price")
    )

    h4_atr = _positive_number(
        analysis.get("h4_atr")
    )

    h4_levels = analysis.get("h4_levels")
    h4_candles = analysis.get("h4_candles")

    if (
        direction is None
        or current_price is None
        or h4_atr is None
        or not isinstance(h4_levels, dict)
        or not isinstance(h4_candles, list)
    ):
        return None

    # Rechercher la confluence entre niveau horizontal
    # et trendline.
    zone = _build_confluence_zone(analysis)

    if zone is None:
        return None

    # Le prix doit rester proche de la zone d'entree.
    if not _validate_entry_price(
        current_price,
        zone,
        h4_atr,
    ):
        return None

    # La reaction recente est une confluence supplementaire.
    # Elle n'est pas obligatoire pour conserver une entree
    # anticipative.
    reaction_confirmed = _validate_price_reaction(
        h4_candles,
        direction,
        zone,
    )

    # Chercher un niveau horizontal exploitable pour le TP.
    trade = _calculate_trade(
        direction,
        current_price,
        zone,
        h4_atr,
        h4_levels,
    )

    if trade is None:
        return None

    # Controle supplementaire du biais Daily.
    d1_analysis = analysis.get("d1_analysis", {})

    if not _direction_valid(direction, d1_analysis):
        return None

    # Identifiant stable pour faciliter la detection
    # des doublons dans le programme appelant.
    identity = "|".join([
        SIGNAL_VERSION,
        symbol,
        direction,
        f"{trade['entry']:.8f}",
        f"{trade['stop_loss']:.8f}",
        f"{trade['take_profit']:.8f}",
    ])

    signal_id = hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()[:20]

    return {
        "signal_id": signal_id,
        "strategy": SIGNAL_VERSION,
        "symbol": symbol,
        "symbol_name": SYMBOL_NAMES.get(
            symbol,
            symbol,
        ),
        "direction": direction,
        "entry": trade["entry"],
        "stop_loss": trade["stop_loss"],
        "take_profit": trade["take_profit"],
        "risk_reward": trade["rr"],
        "rr": trade["rr"],
        "zone": trade["zone"],
        "trendline_contacts": zone.get(
            "trendline_contacts",
            0,
        ),
        "reaction_confirmed": reaction_confirmed,
        "current_price": current_price,
        "timeframes": ["D1", "H4", "H2", "H1"],
        "automatic_execution": False,
        "dry_run": True,
            }
    # ============================================================
# FONCTION PUBLIQUE : RECHERCHE DES SIGNAUX
# ============================================================

def find_signals(
    symbol: str,
    market_data: dict,
) -> list:
    """
    Analyse un symbole et retourne les signaux exploitables.

    Cette fonction est appelee par scheduled_analysis.py.
    Elle ne passe aucun ordre sur le compte Deriv.
    """

    if not isinstance(symbol, str) or not symbol.strip():
        LOGGER.warning("Symbole invalide : %r", symbol)
        return []

    if not isinstance(market_data, dict):
        LOGGER.warning(
            "%s : donnees de marche invalides.",
            symbol,
        )
        return []

    try:
        analysis = _analyze_symbol(
            symbol.strip(),
            market_data,
        )

        if analysis is None:
            LOGGER.info(
                "%s : aucune configuration exploitable.",
                symbol,
            )
            return []

        signal = _generate_signal(
            symbol.strip(),
            analysis,
        )

        if signal is None:
            LOGGER.info(
                "%s : aucune confluence valide.",
                symbol,
            )
            return []

        LOGGER.info(
            "%s : signal %s detecte ; RR=%.2f.",
            symbol,
            signal["direction"],
            signal["rr"],
        )

        return [signal]

    except Exception:
        LOGGER.exception(
            "%s : erreur pendant l'analyse strategique.",
            symbol,
        )
        return []


# ============================================================
# FONCTION PUBLIQUE : FORMATAGE TELEGRAM
# ============================================================

def format_message(signal: dict) -> str:
    """Prepare un message lisible pour Telegram."""

    if not isinstance(signal, dict):
        return "TRADER AI PRO : signal invalide."

    symbol = str(signal.get("symbol", "UNKNOWN"))
    symbol_name = str(
        signal.get("symbol_name", symbol)
    )
    direction = str(
        signal.get("direction", "UNKNOWN")
    ).upper()

    entry = _number(signal.get("entry"))
    stop_loss = _number(signal.get("stop_loss"))
    take_profit = _number(signal.get("take_profit"))
    rr = _number(signal.get("rr"))

    if any(
        value is None
        for value in (
            entry,
            stop_loss,
            take_profit,
            rr,
        )
    ):
        return (
            "TRADER AI PRO\n"
            "Signal incomplet : donnees numeriques invalides."
        )

    if direction not in ("BUY", "SELL"):
        return (
            "TRADER AI PRO\n"
            "Signal incomplet : direction invalide."
        )

    if rr < MIN_RR:
        return (
            "TRADER AI PRO\n"
            "Signal rejete : ratio risque/rendement insuffisant."
        )
        # Construction du message Telegram.
    separator = "━━━━━━━━━━━━━━━━━━━━"

    lines = [
        "🎯 TRADER AI PRO",
        separator,
        f"📊 Indice : {symbol_name}",
        f"🔎 Symbole : {symbol}",
        f"📈 Direction : {direction}",
        separator,
        f"💰 Entrée indicative : {entry:.5f}",
        f"🛑 Stop-loss : {stop_loss:.5f}",
        f"🎯 Take-profit : {take_profit:.5f}",
        f"⚖️ Ratio risque/rendement : 1:{rr:.2f}",
        separator,
        (
            "📍 Contacts trendline : "
            f"{signal.get('trendline_contacts', 0)}"
        ),
        (
            "🔔 Réaction récente : "
            + (
                "détectée"
                if signal.get("reaction_confirmed")
                else "non confirmée"
            )
        ),
        "",
        "⏳ Signal à vérifier manuellement sur Deriv.",
        "🧪 Mode : analyse / DRY_RUN",
        "🚫 Exécution automatique : désactivée",
        "",
        "⚠️ Signal indicatif, sans garantie de résultat.",
    ]

    return "\n".join(lines)


# ============================================================
# FONCTIONS UTILITAIRES PUBLIQUES
# ============================================================

def get_symbol_name(symbol: str) -> str:
    """Retourne le nom complet d'un indice connu."""

    if not isinstance(symbol, str):
        return "Indice inconnu"

    return SYMBOL_NAMES.get(
        symbol.strip(),
        symbol.strip(),
    )


def get_strategy_info() -> dict:
    """Expose les principaux parametres de la strategie."""

    return {
        "name": "TRADER AI PRO",
        "version": SIGNAL_VERSION,
        "strategy": "Supports / Resistances + Trendlines",
        "timeframes": ["D1", "H4", "H2", "H1"],
        "minimum_candles": dict(MIN_CANDLES),
        "minimum_risk_reward": MIN_RR,
        "minimum_trendline_contacts": MIN_TRENDLINE_CONTACTS,
        "automatic_execution": False,
        "dry_run": True,
    }
