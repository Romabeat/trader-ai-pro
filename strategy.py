"""
TRADER AI PRO — STRATEGIE TRENDLINE + CONFLUENCE

- Analyse D1, H4, H2 et H1.
- Minimum 200 bougies par unité de temps.
- Zones D1 affinées par les réactions réelles en H4.
- Confluence entre trendlines et niveaux horizontaux.
- Alertes anticipatives.
- RR minimum : 1:1.
- Aucun SMC, BOS ou Order Block.
- Aucun ordre automatique.
"""

import hashlib
import math


# ============================================================
# CONFIGURATION GENERALE
# ============================================================

STRATEGY_NAME = "TRENDLINE_SUPPORT_RESISTANCE"

TIMEFRAME_PRIORITY = ("D1", "H4", "H2", "H1")

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

        if None in (opening, high, low, close):
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

def _calculate_atr(candles, period=ATR_PERIOD):

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

    atr = sum(recent_ranges) / len(recent_ranges)

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

        current_cluster = clusters[-1]

        mean = (
            sum(current_cluster)
            / len(current_cluster)
        )

        if abs(value - mean) <= tolerance:
            current_cluster.append(value)

        else:
            clusters.append([value])

    result = []

    for cluster in clusters:

        result.append({
            "price": (
                sum(cluster)
                / len(cluster)
            ),
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
        [
            price
            for _, price in lows
        ],
        tolerance,
    )

    resistances = _cluster_values(
        [
            price
            for _, price in highs
        ],
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
        if (
            zone["high"] - zone["low"]
            <= maximum_width
        )
    ]

    resistances = [
        zone
        for zone in resistances
        if (
            zone["high"] - zone["low"]
            <= maximum_width
        )
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
# AFFINAGE DES ZONES D1 AVEC LES REACTIONS H4
# ============================================================

def _refine_d1_zone_with_h4(
    d1_zone,
    h4_candles,
    h4_atr,
):

    if not d1_zone or not h4_candles:
        return None

    d1_low = d1_zone["low"]
    d1_high = d1_zone["high"]

    if d1_high <= d1_low:
        return None

    tolerance = max(
        h4_atr * 0.12,
        1e-10,
    )

    maximum_width = (
        h4_atr * MAX_H4_REFINED_WIDTH_ATR
    )

    # On ne conserve que les bougies H4 qui ont
    # réellement réagi à l'intérieur de la zone D1.

    reactions = []

    recent_candles = h4_candles[
        -LEVEL_LOOKBACK:
    ]

    for index, candle in enumerate(recent_candles):

        reaction_prices = []

        # Réaction par mèche basse
        if d1_low <= candle["low"] <= d1_high:
            reaction_prices.append(candle["low"])

        # Réaction par mèche haute
        if d1_low <= candle["high"] <= d1_high:
            reaction_prices.append(candle["high"])

        # Réaction par clôture
        if d1_low <= candle["close"] <= d1_high:
            reaction_prices.append(candle["close"])

        # Réaction par ouverture
        if d1_low <= candle["open"] <= d1_high:
            reaction_prices.append(candle["open"])

        for price in reaction_prices:
            reactions.append({
                "index": index,
                "price": price,
            })

    if len(reactions) < MIN_REACTION_TOUCHES:
        return None

    # Regroupement des réactions proches.
    # Les réactions doivent être concentrées dans
    # une zone relativement étroite.

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

    # Protection contre les zones trop larges.
    if refined_high - refined_low > maximum_width:
        return None

    # Une zone affinée doit rester dans la zone D1.
    refined_low = max(refined_low, d1_low)
    refined_high = min(refined_high, d1_high)

    if refined_high <= refined_low:
        return None

    return {
        "low": refined_low,
        "high": refined_high,
        "mid": (
            refined_low + refined_high
        ) / 2,
        "touches": len(best_cluster),
        "source": "D1_H4_REACTION_REFINEMENT",
    }


# ============================================================
# CALCUL DE LA VALEUR D'UNE TRENDLINE
# ============================================================

def _line_value(line, index):

    if not line:
        return None

    slope = line["slope"]
    intercept = line["intercept"]

    return (
        slope * index + intercept
    )


# ============================================================
# DETECTION D'UNE TRENDLINE
# ============================================================

def _find_trendline(
    pivots,
    candles,
    direction,
    atr,
):

    if len(pivots) < 2:
        return None

    recent_pivots = pivots[
        -TRENDLINE_LOOKBACK:
    ]

    if len(recent_pivots) < 2:
        return None

    best_line = None
    best_score = -1

    last_index = len(candles) - 1

    tolerance = max(
        atr * 0.25,
        1e-10,
    )

    for first in range(
        len(recent_pivots) - 1
    ):

        for second in range(
            first + 1,
            len(recent_pivots)
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

            # Vérification des réactions des pivots
            # sur la trendline.

            touches = 0

            for pivot_index, pivot_price in recent_pivots:

                if (
                    pivot_index < index1
                    or pivot_index > last_index
                ):
                    continue

                expected_price = _line_value(
                    line,
                    pivot_index,
                )

                if abs(
                    pivot_price - expected_price
                ) <= tolerance:

                    touches += 1

            if touches < 2:
                continue

            # Vérification de la proximité actuelle
            # du prix avec la trendline.

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
# RECHERCHE DU PROCHAIN OBJECTIF TECHNIQUE
# ============================================================

def _nearest_target(
    price,
    direction,
    all_levels,
    atr,
):

    if price is None or atr <= 0:
        return None

    candidates = []

    maximum_distance = (
        atr * MAX_TARGET_DISTANCE_ATR
    )

    for level in all_levels:

        if isinstance(level, dict):
            target_price = _number(
                level.get("price")
            )
        else:
            target_price = _number(level)

        if target_price is None:
            continue

        distance = abs(
            target_price - price
        )

        if distance <= 0:
            continue

        if distance > maximum_distance:
            continue

        if direction == "BUY":
            if target_price <= price:
                continue

        elif direction == "SELL":
            if target_price >= price:
                continue

        else:
            continue

        candidates.append(target_price)

    if not candidates:
        return None

    if direction == "BUY":
        return min(candidates)

    return max(candidates)


# ============================================================
# CALCUL DU STOP LOSS, TAKE PROFIT ET RR
# ============================================================

def _calculate_trade(
    direction,
    entry,
    zone,
    atr,
    all_levels,
):

    if direction not in ("BUY", "SELL"):
        return None

    if entry is None or atr <= 0:
        return None

    zone_low = zone.get("low")
    zone_high = zone.get("high")

    if zone_low is None or zone_high is None:
        return None

    if zone_low >= zone_high:
        return None

    buffer = atr * SL_BUFFER_ATR

    if direction == "BUY":

        if entry <= zone_low:
            return None

        stop_loss = zone_low - buffer

        risk = entry - stop_loss

        if risk <= 0:
            return None

        take_profit = _nearest_target(
            entry,
            direction,
            all_levels,
            atr,
        )

        if take_profit is None:
            return None

        reward = take_profit - entry

    else:

        if entry >= zone_high:
            return None

        stop_loss = zone_high + buffer

        risk = stop_loss - entry

        if risk <= 0:
            return None

        take_profit = _nearest_target(
            entry,
            direction,
            all_levels,
            atr,
        )

        if take_profit is None:
            return None

        reward = entry - take_profit

    if reward <= 0:
        return None

    rr = reward / risk

    if rr < MIN_RR:
        return None

    return {
        "entry": round(entry, 8),
        "stop_loss": round(stop_loss, 8),
        "take_profit": round(take_profit, 8),
        "risk": round(risk, 8),
        "reward": round(reward, 8),
        "rr": round(rr, 2),
        "target_touches": (
            take_profit
        ),
    }


# ============================================================
# VERIFICATION DE LA CONFLUENCE
# ============================================================

def _check_confluence(
    zone,
    trendline,
    price,
    atr,
):

    if not zone or not trendline:
        return False

    if atr <= 0:
        return False

    line_price = trendline.get(
        "current_price"
    )

    if line_price is None:
        return False

    zone_low = zone["low"]
    zone_high = zone["high"]

    if zone_low <= line_price <= zone_high:
        distance = 0

    elif line_price < zone_low:
        distance = zone_low - line_price

    else:
        distance = line_price - zone_high

    if distance > (
        atr * MAX_CONFLUENCE_DISTANCE_ATR
    ):
        return False

    price_distance = abs(
        price - line_price
    )

    if price_distance > (
        atr * MAX_ENTRY_DISTANCE_ATR
    ):
        return False

    return True


# ============================================================
# CONSTRUCTION D'UNE CONFIGURATION
# ============================================================

def _build_candidate(
    symbol,
    d1,
    h4,
    h2,
    h1,
    price_now,
):

    d1 = _normalise_candles(d1)
    h4 = _normalise_candles(h4)
    h2 = _normalise_candles(h2)
    h1 = _normalise_candles(h1)

    if len(d1) < MIN_CANDLES["D1"]:
        return None

    if len(h4) < MIN_CANDLES["H4"]:
        return None

    if len(h2) < MIN_CANDLES["H2"]:
        return None

    if len(h1) < MIN_CANDLES["H1"]:
        return None

    price = _number(price_now)

    if price is None or price <= 0:
        return None

    d1_atr = _calculate_atr(d1)
    h4_atr = _calculate_atr(h4)
    h2_atr = _calculate_atr(h2)
    h1_atr = _calculate_atr(h1)

    if min(d1_atr, h4_atr, h2_atr, h1_atr) <= 0:
        return None

    # --------------------------------------------------------
    # 1. ZONES HORIZONTALES D1
    # --------------------------------------------------------

    d1_supports, d1_resistances = _d1_zones(
        d1,
        d1_atr,
    )

    if not d1_supports and not d1_resistances:
        return None

    candidates = []

    # --------------------------------------------------------
    # 2. ANALYSE DES SUPPORTS POUR UN BUY
    # --------------------------------------------------------

    for d1_zone in d1_supports:

        refined_zone = _refine_d1_zone_with_h4(
            d1_zone,
            h4,
            h4_atr,
        )

        if not refined_zone:
            continue

        if price <= refined_zone["low"]:
            continue

        distance = price - refined_zone["high"]

        if distance < 0:
            distance = 0

        if distance > (
            h4_atr * MAX_ENTRY_DISTANCE_ATR
        ):
            continue

        trendline = _trendline_for_direction(
            h4,
            "BUY",
            h4_atr,
        )

        if not trendline:
            continue

        if not _check_confluence(
            refined_zone,
            trendline,
            price,
            h4_atr,
        ):
            continue

        # ----------------------------------------------------
        # Niveaux techniques disponibles pour le TP
        # ----------------------------------------------------

        all_levels = []

        for candles, atr in (
            (d1, d1_atr),
            (h4, h4_atr),
            (h2, h2_atr),
            (h1, h1_atr),
        ):

            supports, resistances = (
                _find_horizontal_levels(
                    candles,
                    atr,
                )
            )

            all_levels.extend(resistances)

        trade = _calculate_trade(
            "BUY",
            price,
            refined_zone,
            h4_atr,
            all_levels,
        )

        if not trade:
            continue

        candidates.append({
            "symbol": symbol,
            "direction": "BUY",
            "zone_low": round(
                refined_zone["low"],
                8,
            ),
            "zone_high": round(
                refined_zone["high"],
                8,
            ),
            "zone_mid": round(
                refined_zone["mid"],
                8,
            ),
            "zone_touches": refined_zone["touches"],
            "trendline_price": round(
                trendline["current_price"],
                8,
            ),
            "trendline_touches": trendline["touches"],
            "trendline_distance": round(
                trendline["distance"],
                8,
            ),
            "timeframe": "H4",
            "analysis_timeframes": [
                "D1",
                "H4",
                "H2",
                "H1",
            ],
            "strategy": STRATEGY_NAME,
            **trade,
        })

    # --------------------------------------------------------
    # 3. ANALYSE DES RESISTANCES POUR UN SELL
    # --------------------------------------------------------

    for d1_zone in d1_resistances:

        refined_zone = _refine_d1_zone_with_h4(
            d1_zone,
            h4,
            h4_atr,
        )

        if not refined_zone:
            continue

        if price >= refined_zone["high"]:
            continue

        distance = refined_zone["low"] - price

        if distance < 0:
            distance = 0

        if distance > (
            h4_atr * MAX_ENTRY_DISTANCE_ATR
        ):
            continue

        trendline = _trendline_for_direction(
            h4,
            "SELL",
            h4_atr,
        )

        if not trendline:
            continue

        if not _check_confluence(
            refined_zone,
            trendline,
            price,
            h4_atr,
        ):
            continue

        all_levels = []

        for candles, atr in (
            (d1, d1_atr),
            (h4, h4_atr),
            (h2, h2_atr),
            (h1, h1_atr),
        ):

            supports, resistances = (
                _find_horizontal_levels(
                    candles,
                    atr,
                )
            )

            all_levels.extend(supports)

        trade = _calculate_trade(
            "SELL",
            price,
            refined_zone,
            h4_atr,
            all_levels,
        )

        if not trade:
            continue

        candidates.append({
            "symbol": symbol,
            "direction": "SELL",
            "zone_low": round(
                refined_zone["low"],
                8,
            ),
            "zone_high": round(
                refined_zone["high"],
                8,
            ),
            "zone_mid": round(
                refined_zone["mid"],
                8,
            ),
            "zone_touches": refined_zone["touches"],
            "trendline_price": round(
                trendline["current_price"],
                8,
            ),
            "trendline_touches": trendline["touches"],
            "trendline_distance": round(
                trendline["distance"],
                8,
            ),
            "timeframe": "H4",
            "analysis_timeframes": [
                "D1",
                "H4",
                "H2",
                "H1",
            ],
            "strategy": STRATEGY_NAME,
            **trade,
        })

    if not candidates:
        return None

    # On conserve la configuration ayant le meilleur RR.
    candidates.sort(
        key=lambda item: item["rr"],
        reverse=True,
    )

    return candidates[0]
    # ============================================================
# GENERATION D'UN IDENTIFIANT UNIQUE
# ============================================================

def _generate_signal_id(signal):

    raw = "|".join([
        str(signal.get("symbol", "")),
        str(signal.get("direction", "")),
        str(signal.get("entry", "")),
        str(signal.get("stop_loss", "")),
        str(signal.get("take_profit", "")),
        str(signal.get("strategy", "")),
    ])

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:16]


# ============================================================
# RECHERCHE DES SIGNAUX
# ============================================================

def find_signals(
    symbol,
    d1,
    h4,
    h2,
    h1,
    price_now,
    diagnostics=None,
):

    if diagnostics is not None:
        if isinstance(diagnostics, dict):
            diagnostics["analysed"] = (
                diagnostics.get("analysed", 0) + 1
            )

    try:

        signal = _build_candidate(
            symbol=symbol,
            d1=d1,
            h4=h4,
            h2=h2,
            h1=h1,
            price_now=price_now,
        )

        if not signal:
            if diagnostics is not None:
                if isinstance(diagnostics, dict):
                    diagnostics["no_signal"] = (
                        diagnostics.get("no_signal", 0) + 1
                    )

            return []

        # Vérification finale des niveaux
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
            return []

        if rr < MIN_RR:
            return []

        if signal["direction"] == "BUY":

            if not (
                stop_loss < entry < take_profit
            ):
                return []

        elif signal["direction"] == "SELL":

            if not (
                take_profit < entry < stop_loss
            ):
                return []

        else:
            return []

        signal["signal_id"] = (
            _generate_signal_id(signal)
        )

        signal["strategy"] = STRATEGY_NAME

        if diagnostics is not None:
            if isinstance(diagnostics, dict):
                diagnostics["signals_found"] = (
                    diagnostics.get("signals_found", 0) + 1
                )

        return [signal]

    except Exception as error:

        if diagnostics is not None:
            if isinstance(diagnostics, dict):
                diagnostics["errors"] = (
                    diagnostics.get("errors", 0) + 1
                )

                diagnostics.setdefault(
                    "error_messages",
                    [],
                ).append(str(error))

        return []


# ============================================================
# FORMATAGE DU MESSAGE TELEGRAM
# ============================================================

def format_message(signal):

    symbol = signal.get(
        "symbol",
        "Indice inconnu",
    )

    full_name = SYMBOL_NAMES.get(
        symbol,
        symbol,
    )

    direction = signal.get(
        "direction",
        "UNKNOWN",
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

    trendline_price = signal.get(
        "trendline_price",
        0,
    )

    zone_touches = signal.get(
        "zone_touches",
        0,
    )

    trendline_touches = signal.get(
        "trendline_touches",
        0,
    )

    timeframe = signal.get(
        "analysis_timeframes",
        ["D1", "H4", "H2", "H1"],
    )

    timeframe_text = " / ".join(timeframe)

    return (
        f"🚨 <b>TRADER AI PRO</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>SIGNAL {direction}</b>\n\n"
        f"📊 <b>Indice :</b> {full_name}\n"
        f"🔎 <b>Symbole :</b> {symbol}\n"
        f"⏱ <b>Analyse :</b> {timeframe_text}\n\n"
        f"📍 <b>ZONE DE CONFLUENCE</b>\n"
        f"Bas : <code>{zone_low}</code>\n"
        f"Haut : <code>{zone_high}</code>\n"
        f"Réactions H4 : {zone_touches}\n"
        f"Trendline : <code>{trendline_price}</code>\n"
        f"Contacts trendline : {trendline_touches}\n\n"
        f"💰 <b>PLAN DE TRADE</b>\n"
        f"Entrée : <code>{entry}</code>\n"
        f"Stop Loss : <code>{stop_loss}</code>\n"
        f"Take Profit : <code>{take_profit}</code>\n"
        f"Risk/Reward : <b>1:{rr}</b>\n\n"
        f"🧭 <b>Stratégie :</b> Trendline + Support/Résistance\n"
        f"🆔 <b>ID :</b> <code>{signal.get('signal_id', '')}</code>\n\n"
        f"⚠️ Signal d'analyse uniquement.\n"
        f"Exécution manuelle sur compte démo.\n"
        f"⛔ Aucun ordre automatique.\n"
        f"━━━━━━━━━━━━━━━━━━"
)
    
    
