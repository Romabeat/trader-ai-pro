"""
TRADER AI PRO
Strategie : SUPPORTS / RESISTANCES + TRENDLINES
Analyse multi-timeframe : D1 / H4 / H2 / H1
"""

import hashlib
import math
import html


# ============================================================
# 1. PARAMETRES GENERAUX
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
TRENDLINE_LOOKBACK = 100

LEVEL_CLUSTER_DISTANCE_ATR = 0.22
MAX_CONFLUENCE_DISTANCE_ATR = 0.65
MAX_ENTRY_DISTANCE_ATR = 1.25

SL_BUFFER_ATR = 0.15

MAX_D1_ZONE_WIDTH_ATR = 1.80
MAX_H4_REFINED_WIDTH_ATR = 0.90

MIN_REACTION_TOUCHES = 2
MIN_TRENDLINE_TOUCHES = 3

TRENDLINE_TOUCH_TOLERANCE_ATR = 0.25
MAX_TRENDLINE_BREAK_ATR = 0.35

MIN_RR = 1.0
MAX_TARGET_DISTANCE_ATR = 12.0

REACTION_SEPARATION_CANDLES = 2


# ============================================================
# 2. NOMS DES INDICES DERIV
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
# 3. CONVERSION ET VALIDATION DES NOMBRES
# ============================================================

def _number(value, default=None):
    try:
        result = float(value)

        if not math.isfinite(result):
            return default

        return result

    except (TypeError, ValueError):
        return default


def _get_value(item, key, default=None):
    if isinstance(item, dict):
        return item.get(key, default)

    return default


# ============================================================
# 4. NORMALISATION DES BOUGIES
# ============================================================

def _normalise_candles(candles):
    if not isinstance(candles, list):
        return []

    result = []

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        open_price = _number(_get_value(candle, "open"))
        high_price = _number(_get_value(candle, "high"))
        low_price = _number(_get_value(candle, "low"))
        close_price = _number(_get_value(candle, "close"))

        if None in (
            open_price,
            high_price,
            low_price,
            close_price,
        ):
            continue

        if high_price < low_price:
            continue

        if high_price < max(open_price, close_price):
            continue

        if low_price > min(open_price, close_price):
            continue

        result.append({
            "epoch": _get_value(candle, "epoch"),
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
        })

    result.sort(
        key=lambda item: (
            item["epoch"]
            if isinstance(item["epoch"], (int, float))
            else 0
        )
    )

    return result


# ============================================================
# 5. CALCUL DE L'ATR
# ============================================================

def _calculate_atr(candles, period=ATR_PERIOD):
    if len(candles) < period + 1:
        return None

    true_ranges = []

    for index in range(1, len(candles)):
        current = candles[index]
        previous = candles[index - 1]

        high = current["high"]
        low = current["low"]
        previous_close = previous["close"]

        true_range = max(
            high - low,
            abs(high - previous_close),
            abs(low - previous_close),
        )

        true_ranges.append(true_range)

    if len(true_ranges) < period:
        return None

    atr = sum(true_ranges[-period:]) / period

    if not math.isfinite(atr) or atr <= 0:
        return None

    return atr


# ============================================================
# 6. DETECTION DES PIVOTS
# ============================================================

def _find_pivots(candles, radius=PIVOT_RADIUS):
    highs = []
    lows = []

    if len(candles) < (radius * 2 + 1):
        return highs, lows

    start_index = max(
        radius,
        len(candles) - PIVOT_LOOKBACK
    )

    end_index = len(candles) - radius

    for index in range(start_index, end_index):

        current = candles[index]

        left = candles[index - radius:index]
        right = candles[index + 1:index + radius + 1]

        is_high = all(
            current["high"] > item["high"]
            for item in left + right
        )

        is_low = all(
            current["low"] < item["low"]
            for item in left + right
        )

        if is_high:
            highs.append({
                "index": index,
                "price": current["high"],
            })

        if is_low:
            lows.append({
                "index": index,
                "price": current["low"],
            })

    return highs, lows
    # ============================================================
# 7. REGROUPEMENT DES NIVEAUX PROCHES
# ============================================================

def _cluster_values(values, distance):
    if not values:
        return []

    values = sorted(values)

    clusters = []
    current_cluster = [values[0]]

    for value in values[1:]:
        if value - current_cluster[-1] <= distance:
            current_cluster.append(value)
        else:
            clusters.append(current_cluster)
            current_cluster = [value]

    clusters.append(current_cluster)

    result = []

    for cluster in clusters:
        result.append({
            "price": sum(cluster) / len(cluster),
            "touches": len(cluster),
            "low": min(cluster),
            "high": max(cluster),
        })

    return result


# ============================================================
# 8. DETECTION DES SUPPORTS ET RESISTANCES
# ============================================================

def _find_horizontal_levels(candles, atr):
    if not candles or atr is None or atr <= 0:
        return [], []

    recent_candles = candles[-LEVEL_LOOKBACK:]

    highs, lows = _find_pivots(recent_candles)

    support_values = [
        pivot["price"] for pivot in lows
    ]

    resistance_values = [
        pivot["price"] for pivot in highs
    ]

    cluster_distance = atr * LEVEL_CLUSTER_DISTANCE_ATR

    supports = _cluster_values(
        support_values,
        cluster_distance,
    )

    resistances = _cluster_values(
        resistance_values,
        cluster_distance,
    )

    supports.sort(key=lambda item: item["price"])
    resistances.sort(key=lambda item: item["price"])

    return supports, resistances


# ============================================================
# 9. DETECTION DES ZONES PRINCIPALES EN D1
# ============================================================

def _d1_zones(candles, atr):
    if not candles or atr is None or atr <= 0:
        return []

    supports, resistances = _find_horizontal_levels(
        candles,
        atr,
    )

    zones = []

    for level in supports:
        if level["touches"] < MIN_REACTION_TOUCHES:
            continue

        zones.append({
            "type": "SUPPORT",
            "low": level["low"] - atr * 0.08,
            "high": level["high"] + atr * 0.08,
            "mid": level["price"],
            "touches": level["touches"],
            "timeframe": "D1",
        })

    for level in resistances:
        if level["touches"] < MIN_REACTION_TOUCHES:
            continue

        zones.append({
            "type": "RESISTANCE",
            "low": level["low"] - atr * 0.08,
            "high": level["high"] + atr * 0.08,
            "mid": level["price"],
            "touches": level["touches"],
            "timeframe": "D1",
        })

    zones.sort(
        key=lambda zone: zone["touches"],
        reverse=True,
    )

    return zones


# ============================================================
# 10. VERIFICATION DU PRIX DANS UNE ZONE
# ============================================================

def _zone_contains(zone, price):
    if not zone or price is None:
        return False

    return (
        zone["low"] <= price <= zone["high"]
    )


# ============================================================
# 11. RECHERCHE DES REACTIONS H4
# ============================================================

def _find_h4_reactions(d1_zone, h4_candles, h4_atr):
    if (
        not d1_zone
        or not h4_candles
        or h4_atr is None
        or h4_atr <= 0
    ):
        return []

    reactions = []

    tolerance = h4_atr * 0.20

    for index, candle in enumerate(h4_candles):

        if (
            candle["high"] < d1_zone["low"] - tolerance
            or candle["low"] > d1_zone["high"] + tolerance
        ):
            continue

        if d1_zone["type"] == "SUPPORT":
            reaction = (
                candle["low"] <= d1_zone["high"] + tolerance
                and candle["close"] > candle["open"]
            )

            price = candle["low"]

        else:
            reaction = (
                candle["high"] >= d1_zone["low"] - tolerance
                and candle["close"] < candle["open"]
            )

            price = candle["high"]

        if reaction:
            reactions.append({
                "index": index,
                "price": price,
                "close": candle["close"],
            })

    # Eviter de compter plusieurs bougies d'une meme reaction.
    independent_reactions = []

    for reaction in reactions:
        if not independent_reactions:
            independent_reactions.append(reaction)
            continue

        previous = independent_reactions[-1]

        if (
            reaction["index"] - previous["index"]
            >= REACTION_SEPARATION_CANDLES
        ):
            independent_reactions.append(reaction)

    return independent_reactions


# ============================================================
# 12. AFFINAGE DES ZONES D1 AVEC H4
# ============================================================

def _refine_d1_zone_with_h4(d1_zone, h4_candles, h4_atr):
    reactions = _find_h4_reactions(
        d1_zone,
        h4_candles,
        h4_atr,
    )

    if len(reactions) < MIN_REACTION_TOUCHES:
        return None

    prices = [
        reaction["price"]
        for reaction in reactions
    ]

    low = min(prices)
    high = max(prices)

    # La zone doit rester techniquement exploitable.
    maximum_width = h4_atr * MAX_H4_REFINED_WIDTH_ATR

    if high - low > maximum_width:
        center = sum(prices) / len(prices)
        half_width = maximum_width / 2

        low = center - half_width
        high = center + half_width

    refined_zone = {
        "type": d1_zone["type"],
        "low": low,
        "high": high,
        "mid": (low + high) / 2,
        "touches": len(reactions),
        "timeframe": "D1/H4",
        "d1_zone": d1_zone,
    }

    if refined_zone["high"] <= refined_zone["low"]:
        return None

    return refined_zone
    # ============================================================
# 13. CALCUL DE LA VALEUR D'UNE TRENDLINE
# ============================================================

def _line_value(line, index):
    if not line:
        return None

    first_index = line["first_index"]
    first_price = line["first_price"]

    last_index = line["last_index"]
    last_price = line["last_price"]

    if last_index == first_index:
        return last_price

    slope = (
        (last_price - first_price)
        / (last_index - first_index)
    )

    return first_price + slope * (index - first_index)


# ============================================================
# 14. RECHERCHE D'UNE TRENDLINE
# ============================================================

def _find_trendline(pivots, candles, direction, atr):
    if (
        not pivots
        or not candles
        or atr is None
        or atr <= 0
    ):
        return None

    if direction == "BUY":
        selected_pivots = [
            pivot for pivot in pivots
            if pivot["type"] == "LOW"
        ]

    elif direction == "SELL":
        selected_pivots = [
            pivot for pivot in pivots
            if pivot["type"] == "HIGH"
        ]

    else:
        return None

    if len(selected_pivots) < MIN_TRENDLINE_TOUCHES:
        return None

    selected_pivots = selected_pivots[-TRENDLINE_LOOKBACK:]

    tolerance = atr * TRENDLINE_TOUCH_TOLERANCE_ATR
    maximum_break = atr * MAX_TRENDLINE_BREAK_ATR

    best_line = None
    best_score = -1

    for first_position in range(len(selected_pivots) - 2):

        for last_position in range(
            first_position + 2,
            len(selected_pivots),
        ):

            first = selected_pivots[first_position]
            last = selected_pivots[last_position]

            if last["index"] <= first["index"]:
                continue

            if direction == "BUY" and last["price"] <= first["price"]:
                continue

            if direction == "SELL" and last["price"] >= first["price"]:
                continue

            candidate = {
                "first_index": first["index"],
                "first_price": first["price"],
                "last_index": last["index"],
                "last_price": last["price"],
            }

            touches = 0
            broken = False

            for pivot in selected_pivots:

                if (
                    pivot["index"] < first["index"]
                    or pivot["index"] > last["index"]
                ):
                    continue

                expected_price = _line_value(
                    candidate,
                    pivot["index"],
                )

                difference = pivot["price"] - expected_price

                if abs(difference) <= tolerance:
                    touches += 1

                if direction == "BUY" and difference < -maximum_break:
                    broken = True

                if direction == "SELL" and difference > maximum_break:
                    broken = True

            if broken:
                continue

            if touches < MIN_TRENDLINE_TOUCHES:
                continue

            current_index = len(candles) - 1

            current_line_price = _line_value(
                candidate,
                current_index,
            )

            current_candle = candles[-1]

            if direction == "BUY":
                if current_candle["close"] < current_line_price - maximum_break:
                    continue

            else:
                if current_candle["close"] > current_line_price + maximum_break:
                    continue

            score = touches

            if score > best_score:
                best_score = score

                best_line = {
                    **candidate,
                    "touches": touches,
                    "current_price": current_line_price,
                    "direction": direction,
                }

    return best_line


# ============================================================
# 15. PREPARATION DES PIVOTS POUR LES TRENDLINES
# ============================================================

def _trendline_for_direction(candles, direction, atr):
    if not candles:
        return None

    highs, lows = _find_pivots(candles)

    pivots = []

    for pivot in highs:
        pivots.append({
            "index": pivot["index"],
            "price": pivot["price"],
            "type": "HIGH",
        })

    for pivot in lows:
        pivots.append({
            "index": pivot["index"],
            "price": pivot["price"],
            "type": "LOW",
        })

    pivots.sort(key=lambda item: item["index"])

    return _find_trendline(
        pivots,
        candles,
        direction,
        atr,
    )


# ============================================================
# 16. VERIFICATION DE LA CONFLUENCE AVEC LA ZONE
# ============================================================

def _trendline_near_zone(trendline, zone, atr):
    if (
        not trendline
        or not zone
        or atr is None
        or atr <= 0
    ):
        return False

    distance = abs(
        trendline["current_price"] - zone["mid"]
    )

    return distance <= atr * MAX_CONFLUENCE_DISTANCE_ATR


# ============================================================
# 17. VALIDATION DE LA DIRECTION
# ============================================================

def _direction_valid(direction, price, zone, trendline):
    if not zone or not trendline or price is None:
        return False

    if direction == "BUY":
        return (
            zone["type"] == "SUPPORT"
            and price >= zone["low"]
            and trendline["direction"] == "BUY"
        )

    if direction == "SELL":
        return (
            zone["type"] == "RESISTANCE"
            and price <= zone["high"]
            and trendline["direction"] == "SELL"
        )

    return False
    # ============================================================
# 18. RECHERCHE DES NIVEAUX PROCHES D'UNE ZONE
# ============================================================

def _levels_near_zone(candles, zone, atr):
    if not candles or not zone or atr is None or atr <= 0:
        return []

    supports, resistances = _find_horizontal_levels(
        candles,
        atr,
    )

    levels = supports + resistances

    maximum_distance = atr * MAX_CONFLUENCE_DISTANCE_ATR

    result = []

    for level in levels:
        if abs(level["price"] - zone["mid"]) <= maximum_distance:
            result.append({
                "price": level["price"],
                "touches": level["touches"],
                "type": (
                    "SUPPORT"
                    if level in supports
                    else "RESISTANCE"
                ),
            })

    return result


# ============================================================
# 19. CONFLUENCE H2 / H1
# ============================================================

def _has_horizontal_confluence(
    h2_levels,
    h1_levels,
    zone,
    atr,
):
    if not zone or atr is None or atr <= 0:
        return False

    if not h2_levels or not h1_levels:
        return False

    tolerance = atr * MAX_CONFLUENCE_DISTANCE_ATR

    h2_match = any(
        abs(level["price"] - zone["mid"]) <= tolerance
        for level in h2_levels
    )

    h1_match = any(
        abs(level["price"] - zone["mid"]) <= tolerance
        for level in h1_levels
    )

    return h2_match and h1_match


# ============================================================
# 20. VERIFICATION DE LA PROXIMITE DU PRIX
# ============================================================

def _price_near_zone(price, zone, atr):
    if (
        price is None
        or not zone
        or atr is None
        or atr <= 0
    ):
        return False

    distance = 0

    if price < zone["low"]:
        distance = zone["low"] - price

    elif price > zone["high"]:
        distance = price - zone["high"]

    return distance <= atr * MAX_ENTRY_DISTANCE_ATR


# ============================================================
# 21. RECHERCHE DU PROCHAIN OBJECTIF TECHNIQUE
# ============================================================

def _find_next_target(entry, direction, levels, zone):
    if entry is None or not levels or not zone:
        return None

    candidates = []

    for level in levels:
        price = _number(level.get("price"))

        if price is None:
            continue

        if direction == "BUY":
            if price > zone["high"] and price > entry:
                candidates.append(price)

        elif direction == "SELL":
            if price < zone["low"] and price < entry:
                candidates.append(price)

    if not candidates:
        return None

    if direction == "BUY":
        return min(candidates)

    return max(candidates)


# ============================================================
# 22. CALCUL DU TRADE
# ============================================================

def _calculate_trade(direction, entry, zone, atr, target_levels):
    if (
        direction not in ("BUY", "SELL")
        or entry is None
        or not zone
        or atr is None
        or atr <= 0
    ):
        return None

    buffer = atr * SL_BUFFER_ATR

    if direction == "BUY":
        stop_loss = zone["low"] - buffer

    else:
        stop_loss = zone["high"] + buffer

    target = _find_next_target(
        entry,
        direction,
        target_levels,
        zone,
    )

    if target is None:
        return None

    if direction == "BUY":
        risk = entry - stop_loss
        reward = target - entry

    else:
        risk = stop_loss - entry
        reward = entry - target

    if risk <= 0 or reward <= 0:
        return None

    if reward > atr * MAX_TARGET_DISTANCE_ATR:
        return None

    rr = reward / risk

    if rr < MIN_RR:
        return None

    return {
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": target,
        "risk": risk,
        "reward": reward,
        "rr": rr,
    }


# ============================================================
# 23. CONSTRUCTION D'UN SIGNAL CANDIDAT
# ============================================================

def _build_candidate(
    symbol,
    direction,
    zone,
    h4_candles,
    h4_atr,
    h2_candles,
    h2_atr,
    h1_candles,
    h1_atr,
    price_now,
):
    if not _price_near_zone(price_now, zone, h4_atr):
        return None

    if direction == "BUY":
        if zone["type"] != "SUPPORT":
            return None

        if price_now < zone["low"] - h4_atr * MAX_ENTRY_DISTANCE_ATR:
            return None

    elif direction == "SELL":
        if zone["type"] != "RESISTANCE":
            return None

        if price_now > zone["high"] + h4_atr * MAX_ENTRY_DISTANCE_ATR:
            return None

    else:
        return None

    trendline = _trendline_for_direction(
        h4_candles,
        direction,
        h4_atr,
    )

    if not trendline:
        return None

    if trendline["touches"] < MIN_TRENDLINE_TOUCHES:
        return None

    if not _trendline_near_zone(
        trendline,
        zone,
        h4_atr,
    ):
        return None

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

    if not _has_horizontal_confluence(
        h2_levels,
        h1_levels,
        zone,
        h4_atr,
    ):
        return None

    entry = zone["mid"]

    target_levels = []

    for candles, atr in (
        (h4_candles, h4_atr),
        (h2_candles, h2_atr),
        (h1_candles, h1_atr),
    ):
        supports, resistances = _find_horizontal_levels(
            candles,
            atr,
        )

        target_levels.extend(supports)
        target_levels.extend(resistances)

    trade = _calculate_trade(
        direction,
        entry,
        zone,
        h4_atr,
        target_levels,
    )

    if not trade:
        return None

    signal = {
        "symbol": symbol,
        "symbol_name": SYMBOL_NAMES.get(symbol, symbol),
        "strategy": STRATEGY_NAME,
        "direction": direction,
        "entry": trade["entry"],
        "stop_loss": trade["stop_loss"],
        "take_profit": trade["take_profit"],
        "rr": trade["rr"],
        "zone": zone,
        "trendline": trendline,
        "h2_confluence": h2_levels,
        "h1_confluence": h1_levels,
        "price_at_analysis": price_now,
    }

    return signal
    # ============================================================
# 24. IDENTIFIANT UNIQUE DU SIGNAL
# ============================================================

def _make_signal_id(signal):
    raw = "|".join([
        str(signal.get("symbol")),
        str(signal.get("direction")),
        str(signal.get("entry")),
        str(signal.get("stop_loss")),
        str(signal.get("take_profit")),
        str(signal.get("strategy")),
    ])

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:20]


# ============================================================
# 25. VALIDATION FINALE DU SIGNAL
# ============================================================

def _validate_signal(signal):
    if not isinstance(signal, dict):
        return False

    direction = signal.get("direction")

    if direction not in ("BUY", "SELL"):
        return False

    entry = _number(signal.get("entry"))
    stop_loss = _number(signal.get("stop_loss"))
    take_profit = _number(signal.get("take_profit"))
    rr = _number(signal.get("rr"))

    if None in (entry, stop_loss, take_profit, rr):
        return False

    if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
        return False

    if rr < MIN_RR:
        return False

    if direction == "BUY":
        if not stop_loss < entry < take_profit:
            return False

    if direction == "SELL":
        if not take_profit < entry < stop_loss:
            return False

    zone = signal.get("zone")

    if not isinstance(zone, dict):
        return False

    if zone.get("high", 0) <= zone.get("low", 0):
        return False

    trendline = signal.get("trendline")

    if not isinstance(trendline, dict):
        return False

    if trendline.get("touches", 0) < MIN_TRENDLINE_TOUCHES:
        return False

    return True


# ============================================================
# 26. FONCTION PRINCIPALE D'ANALYSE
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
    if diagnostics is None:
        diagnostics = {}

    diagnostics.clear()

    try:
        data = {
            "D1": _normalise_candles(d1_candles),
            "H4": _normalise_candles(h4_candles),
            "H2": _normalise_candles(h2_candles),
            "H1": _normalise_candles(h1_candles),
        }

        for timeframe, candles in data.items():
            minimum = MIN_CANDLES[timeframe]

            if len(candles) < minimum:
                diagnostics["status"] = "INSUFFICIENT_DATA"
                diagnostics["timeframe"] = timeframe
                diagnostics["received"] = len(candles)
                diagnostics["required"] = minimum

                return []

        price_now = _number(price_now)

        if price_now is None or price_now <= 0:
            diagnostics["status"] = "INVALID_PRICE"
            return []

        atr_values = {
            timeframe: _calculate_atr(candles)
            for timeframe, candles in data.items()
        }

        for timeframe, atr in atr_values.items():
            if atr is None or atr <= 0:
                diagnostics["status"] = "INVALID_ATR"
                diagnostics["timeframe"] = timeframe

                return []

        d1_zones = _d1_zones(
            data["D1"],
            atr_values["D1"],
        )

        if not d1_zones:
            diagnostics["status"] = "NO_VALID_ZONE"
            return []

        refined_zones = []

        for d1_zone in d1_zones:
            refined = _refine_d1_zone_with_h4(
                d1_zone,
                data["H4"],
                atr_values["H4"],
            )

            if refined:
                refined_zones.append(refined)

        if not refined_zones:
            diagnostics["status"] = "NO_VALID_REFINEMENT"
            return []

        signals = []

        for zone in refined_zones:

            direction = (
                "BUY"
                if zone["type"] == "SUPPORT"
                else "SELL"
            )

            signal = _build_candidate(
                symbol=symbol,
                direction=direction,
                zone=zone,
                h4_candles=data["H4"],
                h4_atr=atr_values["H4"],
                h2_candles=data["H2"],
                h2_atr=atr_values["H2"],
                h1_candles=data["H1"],
                h1_atr=atr_values["H1"],
                price_now=price_now,
            )

            if not signal:
                continue

            if not _validate_signal(signal):
                continue

            signal["signal_id"] = _make_signal_id(signal)

            signals.append(signal)

        diagnostics["status"] = (
            "SIGNALS_FOUND"
            if signals
            else "NO_SIGNAL"
        )

        diagnostics["zones_detected"] = len(d1_zones)
        diagnostics["refined_zones"] = len(refined_zones)
        diagnostics["signals_found"] = len(signals)

        return signals

    except Exception as error:
        diagnostics["status"] = "ANALYSIS_ERROR"
        diagnostics["error"] = str(error)

        return []


# ============================================================
# 27. FORMATAGE DU MESSAGE TELEGRAM
# ============================================================

def format_message(signal):
    if not isinstance(signal, dict):
        return "Erreur : signal invalide."

    symbol = html.escape(
        str(signal.get("symbol_name", signal.get("symbol", "Index")))
    )

    direction = signal.get("direction", "UNKNOWN")

    if direction == "BUY":
        direction_label = "ACHAT"
        emoji = "🟢"

    elif direction == "SELL":
        direction_label = "VENTE"
        emoji = "🔴"

    else:
        direction_label = "INCONNU"
        emoji = "⚪"

    entry = _number(signal.get("entry"), 0)
    stop_loss = _number(signal.get("stop_loss"), 0)
    take_profit = _number(signal.get("take_profit"), 0)
    rr = _number(signal.get("rr"), 0)

    zone = signal.get("zone", {})
    trendline = signal.get("trendline", {})

    return (
        "🚨 <b>TRADER AI PRO</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{emoji} <b>Signal : {direction_label}</b>\n"
        f"📊 <b>Indice :</b> {symbol}\n"
        f"📍 <b>Entrée :</b> {entry:.5f}\n"
        f"🛑 <b>Stop Loss :</b> {stop_loss:.5f}\n"
        f"🎯 <b>Take Profit :</b> {take_profit:.5f}\n"
        f"⚖️ <b>Risk/Reward :</b> 1:{rr:.2f}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📐 <b>Zone :</b> {zone.get('timeframe', 'D1/H4')}\n"
        f"📈 <b>Trendline :</b> {trendline.get('touches', 0)} contacts\n"
        "🔎 <b>Confluence :</b> D1 + H4 + H2 + H1\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Signal d'analyse uniquement.\n"
        "Exécution manuelle sur compte démo.\n"
        "Aucun ordre automatique."
    )
    
