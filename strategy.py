"""
TRADER AI PRO — STRATEGIE TRENDLINE + CONFLUENCE

- Analyse D1, H4, H2 et H1.
- Les zones D1 sont affinées grâce aux réactions réelles observées en H4.
- Recherche de confluences entre trendlines et supports/résistances.
- Alertes anticipées, sans confirmation obligatoire.
- RR minimum : 1:1.
- Aucun SMC, BOS ou Order Block.
- Aucun ordre automatique.
"""

import hashlib
import math

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
PIVOT_LOOKBACK = 100
LEVEL_LOOKBACK = 120
TRENDLINE_LOOKBACK = 10

LEVEL_CLUSTER_DISTANCE_ATR = 0.22
MAX_CONFLUENCE_DISTANCE_ATR = 0.65
MAX_ENTRY_DISTANCE_ATR = 1.25
SL_BUFFER_ATR = 0.15
MAX_D1_ZONE_WIDTH_ATR = 1.80
MIN_REACTION_TOUCHES = 2
MIN_RR = 1.0
MAX_TARGET_DISTANCE_ATR = 12.0

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
# NORMALISATION DES BOUGIES
# ============================================================

def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
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


def _normalise_candles(candles):
    result = []

    if not isinstance(candles, (list, tuple)):
        return result

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        o = _get_value(candle, ("open", "OPEN", "o"))
        h = _get_value(candle, ("high", "HIGH", "h"))
        l = _get_value(candle, ("low", "LOW", "l"))
        c = _get_value(candle, ("close", "CLOSE", "c"))

        if None in (o, h, l, c) or h < l:
            continue

        if h < max(o, c) or l > min(o, c):
            continue

        result.append({
            "open": o,
            "high": h,
            "low": l,
            "close": c,
        })

    return result


# ============================================================
# ATR ET PIVOTS
# ============================================================

def _calculate_atr(candles, period=ATR_PERIOD):
    if len(candles) < 2:
        return 0.0

    ranges = []

    for i in range(1, len(candles)):
        cur = candles[i]
        prev = candles[i - 1]

        tr = max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        )

        ranges.append(max(0.0, tr))

    recent = ranges[-period:]
    atr = sum(recent) / len(recent) if recent else 0.0

    return atr if math.isfinite(atr) and atr > 0 else 0.0


def _find_pivots(candles, radius=PIVOT_RADIUS):
    highs = []
    lows = []

    if len(candles) < radius * 2 + 5:
        return highs, lows

    start = max(radius, len(candles) - PIVOT_LOOKBACK)
    end = len(candles) - radius

    for i in range(start, end):
        candle = candles[i]
        left = candles[i - radius:i]
        right = candles[i + 1:i + radius + 1]

        if all(candle["high"] >= x["high"] for x in left + right):
            highs.append((i, candle["high"]))

        if all(candle["low"] <= x["low"] for x in left + right):
            lows.append((i, candle["low"]))

    return highs, lows
    # ============================================================
# SUPPORTS, RESISTANCES ET CLUSTERS DE REACTIONS
# ============================================================

def _cluster_values(values, tolerance):
    """Regroupe les prix proches en zones de réactions."""
    values = sorted(
        v for v in values
        if _number(v) is not None
    )

    clusters = []

    for value in values:
        if not clusters:
            clusters.append([value])
            continue

        mean = sum(clusters[-1]) / len(clusters[-1])

        if abs(value - mean) <= tolerance:
            clusters[-1].append(value)
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


def _find_horizontal_levels(candles, atr):
    """Détecte les supports et résistances à partir des pivots."""
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


def _d1_zones(candles, atr):
    """Construit les zones horizontales de référence en D1."""
    supports, resistances = _find_horizontal_levels(
        candles,
        atr,
    )

    max_width = atr * MAX_D1_ZONE_WIDTH_ATR

    supports = [
        zone for zone in supports
        if zone["high"] - zone["low"] <= max_width
    ]

    resistances = [
        zone for zone in resistances
        if zone["high"] - zone["low"] <= max_width
    ]

    return supports, resistances


def _zone_contains(outer, inner_low, inner_high, tolerance=1e-9):
    """Vérifie qu'une zone affinée reste dans sa zone de référence."""
    return (
        inner_low >= outer["low"] - tolerance
        and inner_high <= outer["high"] + tolerance
    )


def _refine_d1_zone_with_h4(
    d1_zone,
    h4_candles,
    h4_atr,
    direction,
):
    """
    Affine une zone D1 à partir des réactions H4.

    BUY :
        Recherche des réactions concentrées autour du support.

    SELL :
        Recherche des réactions concentrées autour de la résistance.

    L'affinage se base sur les prix des réactions répétées.
    Il ne cherche pas les bougies supposées avoir lancé un mouvement.
    """

    h4_highs, h4_lows = _find_pivots(h4_candles)

    d1_low = d1_zone["low"]
    d1_high = d1_zone["high"]

    tolerance = max(
        h4_atr * LEVEL_CLUSTER_DISTANCE_ATR,
        1e-10,
    )

    recent_candles = h4_candles[-LEVEL_LOOKBACK:]

    if direction == "BUY":
        pivot_values = [
            price for _, price in h4_lows
            if d1_low <= price <= d1_high
        ]

        wick_values = [
            candle["low"]
            for candle in recent_candles
            if d1_low <= candle["low"] <= d1_high
        ]

    else:
        pivot_values = [
            price for _, price in h4_highs
            if d1_low <= price <= d1_high
        ]

        wick_values = [
            candle["high"]
            for candle in recent_candles
            if d1_low <= candle["high"] <= d1_high
        ]

    values = pivot_values + wick_values

    if len(values) < MIN_REACTION_TOUCHES:
        return None

    clusters = _cluster_values(values, tolerance)

    max_refined_width = max(
        h4_atr * 0.90,
        tolerance,
    )

    valid_zones = [
        zone for zone in clusters
        if zone["touches"] >= MIN_REACTION_TOUCHES
        and zone["high"] - zone["low"] <= max_refined_width
        and _zone_contains(
            d1_zone,
            zone["low"],
            zone["high"],
        )
    ]

    if not valid_zones:
        return None

    # Priorité aux réactions répétées et aux zones étroites.
    valid_zones.sort(
        key=lambda zone: (
            zone["touches"],
            -(zone["high"] - zone["low"]),
        ),
        reverse=True,
    )

    refined = dict(valid_zones[0])

    refined["low"] = max(d1_low, refined["low"])
    refined["high"] = min(d1_high, refined["high"])

    if refined["low"] > refined["high"]:
        return None

    refined["d1_zone_low"] = d1_low
    refined["d1_zone_high"] = d1_high

    return refined


# ============================================================
# TRENDLINES
# ============================================================

def _line_value(point_a, point_b, x):
    x1, y1 = point_a
    x2, y2 = point_b

    if x1 == x2:
        return None

    slope = (y2 - y1) / (x2 - x1)

    return y1 + slope * (x - x1)


def _find_trendline(
    pivots,
    direction,
    atr,
    last_index,
):
    """
    Recherche une trendline à partir de pivots récents.

    BUY :
        Droite haussière fondée sur des creux croissants.

    SELL :
        Droite baissière fondée sur des sommets décroissants.
    """

    if len(pivots) < 2:
        return None

    recent = pivots[-TRENDLINE_LOOKBACK:]
    candidates = []

    for i in range(len(recent) - 1):
        for j in range(i + 1, len(recent)):
            point_a = recent[i]
            point_b = recent[j]

            x1, y1 = point_a
            x2, y2 = point_b

            if x2 <= x1:
                continue

            slope = (y2 - y1) / (x2 - x1)

            if direction == "BUY" and slope <= 0:
                continue

            if direction == "SELL" and slope >= 0:
                continue

            projected = _line_value(
                point_a,
                point_b,
                last_index,
            )

            if projected is None:
                continue

            if not math.isfinite(projected):
                continue

            # Rejette les projections manifestement excessives.
            if atr > 0 and abs(projected - y2) > atr * 15:
                continue

            candidates.append({
                "point_a": point_a,
                "point_b": point_b,
                "price": projected,
                "slope": slope,
                "span": x2 - x1,
            })

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item["span"],
            item["point_b"][0],
        ),
        reverse=True,
    )

    return candidates[0]


def _trendline_for_direction(candles, direction, atr):
    """Sélectionne les pivots adaptés à la direction recherchée."""
    highs, lows = _find_pivots(candles)

    if direction == "BUY":
        pivots = lows
    else:
        pivots = highs

    return _find_trendline(
        pivots=pivots,
        direction=direction,
        atr=atr,
        last_index=len(candles) - 1,
    )


# ============================================================
# OBJECTIFS TECHNIQUES
# ============================================================

def _nearest_target(levels, entry, direction, atr):
    """Cherche un niveau horizontal opposé, réel et suffisamment proche."""

    if direction == "BUY":
        candidates = [
            level for level in levels
            if level["price"] > entry
        ]

        candidates.sort(
            key=lambda level: level["price"]
        )

    else:
        candidates = [
            level for level in levels
            if level["price"] < entry
        ]

        candidates.sort(
            key=lambda level: level["price"],
            reverse=True,
        )

    for target in candidates:
        distance = abs(target["price"] - entry)

        if distance <= atr * MAX_TARGET_DISTANCE_ATR:
            return target

    return None


def _calculate_trade(
    direction,
    entry,
    zone_low,
    zone_high,
    atr,
    target_levels,
):
    """
    Calcule le stop loss et le take profit.

    Aucun objectif artificiel à 3R :
    si aucun niveau technique cohérent n'existe, le signal est rejeté.
    """

    if direction == "BUY":
        stop_loss = zone_low - atr * SL_BUFFER_ATR
        risk = entry - stop_loss

    else:
        stop_loss = zone_high + atr * SL_BUFFER_ATR
        risk = stop_loss - entry

    if risk <= 0 or not math.isfinite(risk):
        return None

    target = _nearest_target(
        target_levels,
        entry,
        direction,
        atr,
    )

    if target is None:
        return None

    take_profit = target["price"]

    if direction == "BUY":
        reward = take_profit - entry
    else:
        reward = entry - take_profit

    if reward <= 0:
        return None

    rr = reward / risk

    # Règle obligatoire : RR minimal de 1:1.
    if rr < MIN_RR:
        return None

    return {
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk": risk,
        "reward": reward,
        "rr": rr,
        "target_type": "Niveau horizontal opposé",
        "target_touches": target.get("touches", 1),
        }
    def _build_candidate(symbol, d1, h4, h2, h1, price_now):
    """Construit un signal à partir des zones D1 affinées en H4
    et de leur confluence avec une trendline.
    """
    d1_atr = _calculate_atr(d1)
    h4_atr = _calculate_atr(h4)
    h2_atr = _calculate_atr(h2)
    h1_atr = _calculate_atr(h1)

    if min(d1_atr, h4_atr) <= 0:
        return None

    price = _number(price_now)

    if price is None or price <= 0:
        if h1:
            price = h1[-1]["close"]
        else:
            price = h4[-1]["close"]

    # 1. Zones horizontales de référence en D1.
    d1_supports, d1_resistances = _d1_zones(d1, d1_atr)

    # 2. Niveaux horizontaux complémentaires sur les unités inférieures.
    h4_supports, h4_resistances = _find_horizontal_levels(h4, h4_atr)

    if h2 and h2_atr > 0:
        h2_supports, h2_resistances = _find_horizontal_levels(h2, h2_atr)
    else:
        h2_supports, h2_resistances = [], []

    if h1 and h1_atr > 0:
        h1_supports, h1_resistances = _find_horizontal_levels(h1, h1_atr)
    else:
        h1_supports, h1_resistances = [], []

    all_supports = (
        d1_supports
        + h4_supports
        + h2_supports
        + h1_supports
    )

    all_resistances = (
        d1_resistances
        + h4_resistances
        + h2_resistances
        + h1_resistances
    )

    candidates = []

    setups = [
        ("BUY", d1_supports, all_resistances),
        ("SELL", d1_resistances, all_supports),
    ]

    # 3. Chaque zone D1 doit être affinée par les réactions observées en H4.
    for direction, d1_zones, target_levels in setups:
        for d1_zone in d1_zones:

            # Écarte les zones situées du mauvais côté du prix.
            if direction == "BUY":
                if d1_zone["price"] > price + d1_atr * 0.75:
                    continue
            else:
                if d1_zone["price"] < price - d1_atr * 0.75:
                    continue

            # Ne conserve pas une zone D1 beaucoup trop éloignée.
            if abs(price - d1_zone["price"]) > d1_atr * 3.0:
                continue

            # 4. Affinage : recherche d'une sous-zone de réactions en H4.
            refined = _refine_d1_zone_with_h4(
                d1_zone,
                h4,
                h4_atr,
                direction,
            )

            if refined is None:
                continue

            zone_low = refined["low"]
            zone_high = refined["high"]
            zone_center = (zone_low + zone_high) / 2

            # 5. Recherche d'une trendline correspondant au sens du signal.
            trendline = _trendline_for_direction(
                h4,
                direction,
                h4_atr,
            )

            if trendline is None:
                continue

            line_price = trendline["price"]

            # La trendline doit passer dans la zone affinée
            # ou suffisamment près de celle-ci.
            if line_price < zone_low:
                line_distance = zone_low - line_price
            elif line_price > zone_high:
                line_distance = line_price - zone_high
            else:
                line_distance = 0.0

            if line_distance > h4_atr * MAX_CONFLUENCE_DISTANCE_ATR:
                continue

            # 6. Le prix doit encore être suffisamment proche de la zone.
            distance_to_zone = abs(price - zone_center)

            entry_atr = max(
                h1_atr,
                h2_atr,
                h4_atr * 0.35,
            )

            if entry_atr <= 0:
                entry_atr = h4_atr

            if distance_to_zone > entry_atr * MAX_ENTRY_DISTANCE_ATR:
                continue

            # Évite d'alerter si le prix a déjà nettement dépassé
            # la limite opposée de la zone.
            if direction == "BUY":
                if price < zone_low - h4_atr * 0.35:
                    continue
            else:
                if price > zone_high + h4_atr * 0.35:
                    continue

            # 7. Calcul du stop et de l'objectif technique.
            # Aucun objectif artificiel basé uniquement sur un multiple de risque.
            trade = _calculate_trade(
                direction,
                price,
                zone_low,
                zone_high,
                h4_atr,
                target_levels,
            )

            if trade is None:
                continue

            # 8. Score de qualité de la configuration.
            max_line_distance = max(
                h4_atr * MAX_CONFLUENCE_DISTANCE_ATR,
                1e-10,
            )

            max_entry_distance = max(
                entry_atr * MAX_ENTRY_DISTANCE_ATR,
                1e-10,
            )

            line_score = max(
                0.0,
                1.0 - line_distance / max_line_distance,
            )

            distance_score = max(
                0.0,
                1.0 - distance_to_zone / max_entry_distance,
            )

            reaction_score = min(
                refined["touches"],
                5,
            ) / 5.0

            score = round(
                100
                * (
                    0.40 * line_score
                    + 0.35 * distance_score
                    + 0.25 * reaction_score
                ),
                1,
            )

            # Une confluence H2/H1 peut renforcer le score,
            # mais ne remplace pas les conditions D1/H4 obligatoires.
            lower_levels = (
                h2_supports
                + h2_resistances
                + h1_supports
                + h1_resistances
            )

            lower_confluence = any(
                abs(level["price"] - zone_center) <= h4_atr * 0.30
                for level in lower_levels
            )

            if lower_confluence:
                score = min(
                    100.0,
                    round(score + 5.0, 1),
                )

            candidates.append(
                {
                    "strategy": STRATEGY_NAME,
                    "symbol": symbol,
                    "symbol_name": SYMBOL_NAMES.get(symbol, symbol),
                    "timeframe": (
                        "D1/H4"
                        + ("/H2" if h2 else "")
                        + ("/H1" if h1 else "")
                    ),
                    "direction": direction,
                    "entry": round(price, 8),
                    "stop_loss": round(trade["stop_loss"], 8),
                    "take_profit": round(trade["take_profit"], 8),
                    "rr": round(trade["rr"], 2),
                    "atr": round(h4_atr, 8),
                    "trendline_price": round(line_price, 8),
                    "horizontal_level": round(refined["price"], 8),
                    "zone_low": round(zone_low, 8),
                    "zone_high": round(zone_high, 8),
                    "d1_zone_low": round(d1_zone["low"], 8),
                    "d1_zone_high": round(d1_zone["high"], 8),
                    "distance_to_zone_atr": round(
                        distance_to_zone / h4_atr,
                        3,
                    ),
                    "confluence_distance_atr": round(
                        line_distance / h4_atr,
                        3,
                    ),
                    "level_touches": int(refined["touches"]),
                    "score": score,
                    "target_type": trade["target_type"],
                    "status": "ANTICIPATION",
                    "price_at_analysis": round(price, 8),
                    "lower_timeframe_confluence": lower_confluence,
                }
            )

    if not candidates:
        return None

    # Priorité au score de confluence, puis au meilleur RR.
    candidates.sort(
        key=lambda item: (
            item["score"],
            item["rr"],
        ),
        reverse=True,
    )

    return candidates[0]
    def _make_signal_id(signal):
    """Crée un identifiant stable pour reconnaître un signal."""
    raw = "|".join(
        str(signal.get(key, ""))
        for key in (
            "symbol",
            "direction",
            "zone_low",
            "zone_high",
            "trendline_price",
            "take_profit",
        )
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:16]


def find_signals(
    symbol,
    d1=None,
    h4=None,
    h2=None,
    h1=None,
    price_now=None,
    diagnostics=None,
):
    """
    Point d'entrée public utilisé par scheduled_analysis.py.

    Conditions essentielles :
    - contexte D1 ;
    - affinage de la zone par les réactions H4 ;
    - confluence avec une trendline H4 ;
    - prix encore suffisamment proche de la zone ;
    - objectif technique réaliste ;
    - RR minimum respecté.

    H2 et H1 sont des confluences complémentaires.
    Ils ne remplacent jamais les conditions obligatoires D1/H4.
    """
    if diagnostics is None:
        diagnostics = {}

    if not d1 or not h4:
        diagnostics[symbol] = (
            "Données insuffisantes : D1 et H4 sont nécessaires."
        )
        return []

    if len(d1) < MIN_D1_CANDLES:
        diagnostics[symbol] = (
            f"Historique D1 insuffisant : "
            f"{len(d1)}/{MIN_D1_CANDLES} bougies."
        )
        return []

    if len(h4) < MIN_H4_CANDLES:
        diagnostics[symbol] = (
            f"Historique H4 insuffisant : "
            f"{len(h4)}/{MIN_H4_CANDLES} bougies."
        )
        return []

    try:
        signal = _build_candidate(
            symbol=symbol,
            d1=d1,
            h4=h4,
            h2=h2 or [],
            h1=h1 or [],
            price_now=price_now,
        )

    except (KeyError, TypeError, ValueError, IndexError) as exc:
        diagnostics[symbol] = (
            f"Erreur d'analyse des données : {exc}"
        )
        return []

    if signal is None:
        diagnostics[symbol] = (
            "Aucun signal : absence de confluence exploitable "
            "entre zone D1 affinée en H4 et trendline, "
            "ou objectif technique/RR insuffisant."
        )
        return []

    signal["signal_id"] = _make_signal_id(signal)

    diagnostics[symbol] = (
        f"Signal {signal['direction']} détecté ; "
        f"score={signal['score']}/100 ; "
        f"RR={signal['rr']} ; "
        f"zone H4={signal['zone_low']}–{signal['zone_high']}."
    )

    return [signal]


def format_message(signal):
    """Formate le signal pour un envoi Telegram en français."""
    direction = str(
        signal.get("direction", "INCONNU")
    ).upper()

    if direction == "BUY":
        direction_label = "ACHAT 🟢"
    elif direction == "SELL":
        direction_label = "VENTE 🔴"
    else:
        direction_label = direction

    symbol_name = signal.get(
        "symbol_name",
        signal.get("symbol", "Indice inconnu"),
    )

    timeframe = signal.get(
        "timeframe",
        "D1/H4",
    )

    entry = signal.get("entry", 0)
    stop_loss = signal.get("stop_loss", 0)
    take_profit = signal.get("take_profit", 0)
    rr = signal.get("rr", 0)
    score = signal.get("score", 0)

    zone_low = signal.get("zone_low", 0)
    zone_high = signal.get("zone_high", 0)

    d1_zone_low = signal.get(
        "d1_zone_low",
        zone_low,
    )

    d1_zone_high = signal.get(
        "d1_zone_high",
        zone_high,
    )

    trendline_price = signal.get(
        "trendline_price",
        0,
    )

    horizontal_level = signal.get(
        "horizontal_level",
        0,
    )

    touches = signal.get(
        "level_touches",
        0,
    )

    target_type = signal.get(
        "target_type",
        "Niveau technique",
    )

    distance = signal.get(
        "distance_to_zone_atr",
        0,
    )

    lower_confluence = signal.get(
        "lower_timeframe_confluence",
        False,
    )

    lower_text = (
        "Oui"
        if lower_confluence
        else "Non"
    )

    return (
        "📊 TRADER AI PRO\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📍 Indice : {symbol_name}\n"
        f"📈 Direction : {direction_label}\n"
        f"🕒 Analyse : {timeframe}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🎯 PLAN DE TRADE ANTICIPATIF\n"
        f"💰 Prix observé : {entry}\n"
        f"🛑 Stop Loss : {stop_loss}\n"
        f"🏁 Take Profit : {take_profit}\n"
        f"⚖️ Ratio risque/rendement : 1:{rr}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🔎 CONFLUENCE TECHNIQUE\n"
        f"📅 Zone de référence D1 : "
        f"{d1_zone_low} – {d1_zone_high}\n"
        f"🎯 Zone affinée H4 : "
        f"{zone_low} – {zone_high}\n"
        f"📏 Niveau horizontal : {horizontal_level}\n"
        f"📐 Prix de la trendline : {trendline_price}\n"
        f"🔁 Réactions dans la zone : {touches}\n"
        f"📍 Distance à la zone (ATR) : {distance}\n"
        f"🔗 Confluence H2/H1 : {lower_text}\n"
        f"🎯 Type d'objectif : {target_type}\n"
        f"⭐ Score technique : {score}/100\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ Signal anticipatif : attendre que le prix "
        "respecte la configuration sur le graphique.\n"
        "✅ Exécution manuelle uniquement sur le compte démo.\n"
        "🔒 Exécution automatique désactivée."
    )
