"""
TRADER AI PRO — STRATEGIE TRENDLINE + CONFLUENCE

Principes :
- Analyse D1, H4, H2 et H1.
- Priorité : D1 -> H4 -> H2 -> H1.
- Identification des tendances et trendlines.
- Identification des supports et résistances horizontaux.
- Recherche de confluences entre trendline et niveau horizontal.
- Détection anticipée des configurations.
- Aucun RR minimum imposé.
- Aucun ordre exécuté automatiquement.

Cette stratégie est indépendante de SMC, BOS et Order Blocks.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any


# ============================================================
# CONFIGURATION
# ============================================================

STRATEGY_NAME = "TRENDLINE_SUPPORT_RESISTANCE"

TIMEFRAME_PRIORITY = ("D1", "H4", "H2", "H1")

PIVOT_RADIUS = 3
ATR_PERIOD = 14

# Distance maximale entre la trendline et le niveau horizontal.
CONFLUENCE_ATR = 0.60

# Distance maximale du prix actuel à la confluence.
MAX_ENTRY_DISTANCE_ATR = 1.50

# Marge supplémentaire au-delà de la zone pour le stop-loss.
SL_ATR_BUFFER = 0.35

# Distance minimale entre un pivot et un autre pour limiter
# les faux niveaux horizontaux.
MIN_LEVEL_SEPARATION_ATR = 0.30

# Si aucun niveau opposé exploitable n'est détecté,
# un objectif technique de remplacement est calculé.
FALLBACK_TARGET_R = 3.0

INDEX_NAMES = {
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
# OUTILS NUMÉRIQUES
# ============================================================

def _finite_positive(value: Any) -> float | None:
    """Convertit une valeur en nombre positif valide."""

    try:
        result = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(result) or result <= 0:
        return None

    return result


def _normalize_candles(
    candles: Any,
) -> list[dict[str, float]]:
    """Normalise les bougies et les trie par ordre chronologique."""

    if not isinstance(candles, list):
        return []

    normalized = []
    seen_epochs = set()

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        try:
            epoch = int(candle["epoch"])
            opening = float(candle["open"])
            high = float(candle["high"])
            low = float(candle["low"])
            close = float(candle["close"])
        except (KeyError, TypeError, ValueError):
            continue

        values = [opening, high, low, close]

        if any(not math.isfinite(value) for value in values):
            continue

        if min(values) <= 0:
            continue

        if high < max(opening, close):
            continue

        if low > min(opening, close):
            continue

        if high < low or epoch in seen_epochs:
            continue

        seen_epochs.add(epoch)

        normalized.append({
            "epoch": float(epoch),
            "open": opening,
            "high": high,
            "low": low,
            "close": close,
        })

    normalized.sort(key=lambda item: item["epoch"])

    return normalized


def _calculate_atr(
    candles: list[dict[str, float]],
    period: int = ATR_PERIOD,
) -> float | None:
    """Calcule l'Average True Range."""

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]

        true_range = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )

        if math.isfinite(true_range) and true_range > 0:
            true_ranges.append(true_range)

    if len(true_ranges) < period:
        return None

    # Moyenne des dernières périodes disponibles.
    atr = sum(true_ranges[-period:]) / period

    if not math.isfinite(atr) or atr <= 0:
        return None

    return atr


# ============================================================
# PIVOTS ET STRUCTURE DU PRIX
# ============================================================

def _find_pivots(
    candles: list[dict[str, float]],
    radius: int = PIVOT_RADIUS,
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    """
    Identifie les sommets et creux locaux.

    Un pivot n'est retenu qu'après l'existence des bougies
    nécessaires à sa confirmation. On n'utilise donc pas les
    dernières bougies comme si leurs pivots étaient confirmés.
    """

    highs = []
    lows = []

    if len(candles) < 2 * radius + 5:
        return highs, lows

    for index in range(radius, len(candles) - radius):
        candle = candles[index]

        left = candles[index - radius:index]
        right = candles[index + 1:index + radius + 1]

        is_pivot_high = all(
            candle["high"] > other["high"]
            for other in left + right
        )

        is_pivot_low = all(
            candle["low"] < other["low"]
            for other in left + right
        )

        if is_pivot_high:
            highs.append({
                "index": float(index),
                "epoch": candle["epoch"],
                "price": candle["high"],
            })

        if is_pivot_low:
            lows.append({
                "index": float(index),
                "epoch": candle["epoch"],
                "price": candle["low"],
            })

    return highs, lows


def _line_value(
    first: dict[str, float],
    second: dict[str, float],
    target_index: float,
) -> float | None:
    """Extrapole une droite passant par deux pivots."""

    x1 = first["index"]
    x2 = second["index"]
    y1 = first["price"]
    y2 = second["price"]

    if x2 <= x1:
        return None

    slope = (y2 - y1) / (x2 - x1)
    value = y1 + slope * (target_index - x1)

    if not math.isfinite(value) or value <= 0:
        return None

    return value


def _find_trendline(
    pivots: list[dict[str, float]],
    direction: str,
    atr: float,
) -> dict[str, Any] | None:
    """
    Recherche une trendline cohérente.

    BUY : trendline de support ascendante reliant des creux.
    SELL : trendline de résistance descendante reliant des sommets.
    """

    if len(pivots) < 2:
        return None

    recent = pivots[-8:]

    # On privilégie les deux derniers pivots confirmés.
    first = recent[-2]
    second = recent[-1]

    if second["index"] <= first["index"]:
        return None

    difference = second["price"] - first["price"]

    if direction == "BUY":
        # Les creux doivent monter suffisamment.
        if difference < atr * 0.05:
            return None

    elif direction == "SELL":
        # Les sommets doivent descendre suffisamment.
        if difference > -atr * 0.05:
            return None

    else:
        return None

    # Évite les droites presque verticales ou excessivement
    # inclinées, souvent peu pertinentes pour une anticipation.
    bars_between = second["index"] - first["index"]
    slope_per_bar = difference / bars_between

    if abs(slope_per_bar) > atr * 0.80:
        return None

    return {
        "first": first,
        "second": second,
        "slope": slope_per_bar,
    }


# ============================================================
# SUPPORTS ET RÉSISTANCES HORIZONTAUX
# ============================================================

def _cluster_levels(
    pivots: list[dict[str, float]],
    atr: float,
    recent_limit: int = 12,
) -> list[dict[str, Any]]:
    """
    Regroupe les pivots proches pour identifier des niveaux
    horizontaux approximatifs.

    Un niveau touché plusieurs fois est privilégié.
    """

    if not pivots:
        return []

    tolerance = atr * 0.35
    recent_pivots = pivots[-recent_limit:]

    clusters: list[dict[str, Any]] = []

    for pivot in recent_pivots:
        price = pivot["price"]

        matching = None

        for cluster in clusters:
            if abs(price - cluster["level"]) <= tolerance:
                matching = cluster
                break

        if matching is None:
            clusters.append({
                "level": price,
                "touches": 1,
                "last_epoch": pivot["epoch"],
                "last_index": pivot["index"],
                "prices": [price],
            })
        else:
            matching["prices"].append(price)
            matching["touches"] += 1
            matching["level"] = (
                sum(matching["prices"])
                / len(matching["prices"])
            )

            if pivot["epoch"] > matching["last_epoch"]:
                matching["last_epoch"] = pivot["epoch"]
                matching["last_index"] = pivot["index"]

    result = []

    for cluster in clusters:
        result.append({
            "level": float(cluster["level"]),
            "touches": int(cluster["touches"]),
            "last_epoch": float(cluster["last_epoch"]),
            "last_index": float(cluster["last_index"]),
        })

    return result


def _nearest_level(
    levels: list[dict[str, Any]],
    reference_price: float,
    direction: str,
    atr: float,
) -> dict[str, Any] | None:
    """
    Sélectionne un niveau situé du côté attendu du marché.

    BUY : niveau de support proche, sous le prix ou à proximité.
    SELL : niveau de résistance proche, au-dessus du prix
    ou à proximité.
    """

    if not levels:
        return None

    candidates = []

    for level in levels:
        price = float(level["level"])

        if direction == "BUY":
            if price > reference_price + atr * 0.75:
                continue

        elif direction == "SELL":
            if price < reference_price - atr * 0.75:
                continue

        distance = abs(price - reference_price)

        candidates.append((
            distance,
            -int(level["touches"]),
            level,
        ))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]))

    return candidates[0][2]


def _next_opposing_level(
    levels: list[dict[str, Any]],
    entry: float,
    direction: str,
) -> float | None:
    """Cherche le niveau horizontal opposé le plus proche."""

    if direction == "BUY":
        candidates = [
            float(level["level"])
            for level in levels
            if float(level["level"]) > entry
        ]

        return min(candidates) if candidates else None

    candidates = [
        float(level["level"])
        for level in levels
        if float(level["level"]) < entry
    ]

    return max(candidates) if candidates else None


# ============================================================
# ANALYSE D'UNE UNITÉ DE TEMPS
# ============================================================

def _analyze_timeframe(
    symbol: str,
    timeframe: str,
    raw_candles: Any,
    price_now: float,
) -> tuple[dict[str, Any] | None, str]:
    """
    Recherche une configuration anticipée de confluence.

    BUY :
    - trendline ascendante sur les creux ;
    - support horizontal proche de cette trendline ;
    - prix proche de la zone de confluence.

    SELL :
    - trendline descendante sur les sommets ;
    - résistance horizontale proche de cette trendline ;
    - prix proche de la zone de confluence.
    """

    candles = _normalize_candles(raw_candles)

    if len(candles) < 40:
        return None, (
            f"Historique insuffisant : {len(candles)} bougies."
        )

    atr = _calculate_atr(candles)

    if atr is None:
        return None, "ATR indisponible."

    highs, lows = _find_pivots(candles)

    if len(highs) < 2 or len(lows) < 2:
        return None, "Pas assez de pivots confirmés."

    # Les valeurs de trendline sont évaluées à la dernière
    # bougie clôturée, sans utiliser de pivot futur.
    target_index = float(len(candles) - 1)

    support_levels = _cluster_levels(lows, atr)
    resistance_levels = _cluster_levels(highs, atr)

    candidates: list[dict[str, Any]] = []

    # --------------------------------------------------------
    # Configuration haussière : trendline de support + support
    # --------------------------------------------------------

    bullish_line = _find_trendline(
        lows,
        direction="BUY",
        atr=atr,
    )

    if bullish_line:
        line_price = _line_value(
            bullish_line["first"],
            bullish_line["second"],
            target_index,
        )

        if line_price is not None:
            horizontal = _nearest_level(
                support_levels,
                line_price,
                direction="BUY",
                atr=atr,
            )

            if horizontal is not None:
                level_price = float(horizontal["level"])

                confluence_distance = abs(
                    line_price - level_price
                )

                price_distance = abs(
                    price_now - line_price
                )

                if (
                    confluence_distance <= atr * CONFLUENCE_ATR
                    and price_distance <= atr * MAX_ENTRY_DISTANCE_ATR
                    and price_now >= line_price - atr * 0.75
                ):
                    candidates.append({
                        "direction": "BUY",
                        "line_price": line_price,
                        "level_price": level_price,
                        "horizontal": horizontal,
                        "line": bullish_line,
                        "distance": price_distance,
                        "confluence_distance": confluence_distance,
                    })

    # --------------------------------------------------------
    # Configuration baissière : trendline de résistance
    # + résistance horizontale
    # --------------------------------------------------------

    bearish_line = _find_trendline(
        highs,
        direction="SELL",
        atr=atr,
    )

    if bearish_line:
        line_price = _line_value(
            bearish_line["first"],
            bearish_line["second"],
            target_index,
        )

        if line_price is not None:
            horizontal = _nearest_level(
                resistance_levels,
                line_price,
                direction="SELL",
                atr=atr,
            )

            if horizontal is not None:
                level_price = float(horizontal["level"])

                confluence_distance = abs(
                    line_price - level_price
                )

                price_distance = abs(
                    price_now - line_price
                )

                if (
                    confluence_distance <= atr * CONFLUENCE_ATR
                    and price_distance <= atr * MAX_ENTRY_DISTANCE_ATR
                    and price_now <= line_price + atr * 0.75
                ):
                    candidates.append({
                        "direction": "SELL",
                        "line_price": line_price,
                        "level_price": level_price,
                        "horizontal": horizontal,
                        "line": bearish_line,
                        "distance": price_distance,
                        "confluence_distance": confluence_distance,
                    })

    if not candidates:
        return None, (
            "Aucune confluence exploitable à proximité du prix."
        )

    # Priorité à la confluence la plus proche du prix actuel.
    # Les configurations proches de la zone sont préférées.
    candidates.sort(
        key=lambda item: (
            item["distance"] / atr
            + item["confluence_distance"] / atr
        )
    )

    selected = candidates[0]

    direction = selected["direction"]
    line_price = float(selected["line_price"])
    level_price = float(selected["level_price"])

    # L'entrée est proposée au prix actuel pour permettre une
    # anticipation. Ce n'est pas une garantie d'exécution au prix.
    entry = float(price_now)

    zone_low = min(line_price, level_price)
    zone_high = max(line_price, level_price)

    # Marge de sécurité autour de la zone.
    buffer = atr * SL_ATR_BUFFER

    if direction == "BUY":
        stop_loss = min(zone_low, entry) - buffer

        # Empêche un stop situé au-dessus ou au niveau de l'entrée.
        if stop_loss >= entry:
            stop_loss = entry - atr * 0.50

        risk = entry - stop_loss

        opposing_level = _next_opposing_level(
            resistance_levels,
            entry,
            direction="BUY",
        )

        # On ne place pas un TP structurel trop proche ou derrière
        # l'entrée. Dans ce cas, on utilise une projection technique.
        if (
            opposing_level is not None
            and opposing_level > entry + risk * 0.25
        ):
            take_profit = opposing_level
            target_type = "Résistance horizontale"
        else:
            take_profit = entry + risk * FALLBACK_TARGET_R
            target_type = "Projection technique 3R"

    else:
        stop_loss = max(zone_high, entry) + buffer

        if stop_loss <= entry:
            stop_loss = entry + atr * 0.50

        risk = stop_loss - entry

        opposing_level = _next_opposing_level(
            support_levels,
            entry,
            direction="SELL",
        )

        if (
            opposing_level is not None
            and opposing_level < entry - risk * 0.25
        ):
            take_profit = opposing_level
            target_type = "Support horizontal"
        else:
            take_profit = entry - risk * FALLBACK_TARGET_R
            target_type = "Projection technique 3R"

    if risk <= 0:
        return None, "Risque calculé invalide."

    if direction == "BUY":
        if not stop_loss < entry < take_profit:
            return None, "Niveaux BUY incohérents."

        rr = (take_profit - entry) / risk

    else:
        if not take_profit < entry < stop_loss:
            return None, "Niveaux SELL incohérents."

        rr = (entry - take_profit) / risk

    if not math.isfinite(rr) or rr <= 0:
        return None, "Ratio risque/rendement invalide."

    first_pivot = selected["line"]["first"]
    second_pivot = selected["line"]["second"]

    # Identifiant stable pour ce couple de pivots et cette zone.
    # Il aide à éviter de renvoyer le même signal à chaque scan,
    # sous réserve que la base de données soit persistante.
    identity = (
        f"{symbol}|{timeframe}|{direction}|"
        f"{int(first_pivot['epoch'])}|"
        f"{int(second_pivot['epoch'])}|"
        f"{round(level_price, 5)}"
    )

    signal_id = hashlib.sha256(
        identity.encode("utf-8")
    ).hexdigest()[:24]

    signal = {
        "signal_id": signal_id,
        "strategy": STRATEGY_NAME,
        "symbol": symbol,
        "direction": direction,
        "timeframe": timeframe,
        "entry": round(entry, 5),
        "stop_loss": round(stop_loss, 5),
        "take_profit": round(take_profit, 5),
        "rr": round(rr, 4),
        "current_price": round(price_now, 5),
        "trendline_level": round(line_price, 5),
        "horizontal_level": round(level_price, 5),
        "confluence_level": round(
            (line_price + level_price) / 2,
            5,
        ),
        "zone_low": round(zone_low, 5),
        "zone_high": round(zone_high, 5),
        "atr": round(atr, 5),
        "distance_atr": round(
            abs(price_now - line_price) / atr,
     
