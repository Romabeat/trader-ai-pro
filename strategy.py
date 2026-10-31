"""
TRADER AI PRO — STRATEGIE TRENDLINE + CONFLUENCE

Strategie :
- Analyse des unites de temps : D1, H4, H2, H1.
- Priorite : D1 -> H4 -> H2 -> H1.
- Detection des tendances haussieres et baissieres.
- Detection des trendlines a partir des pivots.
- Detection des supports et resistances horizontaux.
- Recherche de confluence entre trendline et niveau horizontal.
- Detection anticipee : pas besoin d'attendre le contact exact.
- Aucun RR minimum impose.
- Alertes uniquement : aucun ordre automatique.

Interface attendue par scheduled_analysis.py :
    find_signals(...)
    format_message(...)

Compatible avec des bougies sous forme de dictionnaires.
"""

import hashlib
import math
from collections import defaultdict


STRATEGY_NAME = "TRENDLINE_SUPPORT_RESISTANCE"

TIMEFRAME_PRIORITY = ("D1", "H4", "H2", "H1")

# Nombre minimal de bougies pour analyser une unite de temps.
MIN_CANDLES = {
    "D1": 30,
    "H4": 40,
    "H2": 40,
    "H1": 40,
}

# Parametres de detection.
ATR_PERIOD = 14
PIVOT_RADIUS = 2
PIVOT_LOOKBACK = 80
LEVEL_LOOKBACK = 100
TRENDLINE_LOOKBACK = 8

# Distances exprimees en ATR.
MAX_CONFLUENCE_DISTANCE_ATR = 0.80
MAX_ENTRY_DISTANCE_ATR = 1.50
LEVEL_CLUSTER_DISTANCE_ATR = 0.20
SL_BUFFER_ATR = 0.15

# On evite les zones trop eloignees du prix actuel.
MAX_ZONE_DISTANCE_ATR = 1.50

# Noms complets des indices Deriv.
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
    """Convertit une valeur en nombre, sinon retourne None."""
    try:
        result = float(value)
        if math.isfinite(result):
            return result
    except (TypeError, ValueError):
        pass
    return None


def _get_value(candle, names):
    """Recupere la premiere cle disponible dans une bougie."""
    if not isinstance(candle, dict):
        return None

    for name in names:
        if name in candle:
            value = _number(candle[name])
            if value is not None:
                return value

    return None


def _normalise_candles(candles):
    """
    Normalise les bougies.
    Accepte notamment :
      {"open": ..., "high": ..., "low": ..., "close": ...}
    ainsi que les variantes en majuscules.
    """
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

        if None in (o, h, l, c):
            continue

        if h < l:
            continue

        result.append({
            "open": o,
            "high": h,
            "low": l,
            "close": c,
        })

    return result


# ============================================================
# INDICATEURS
# ============================================================

def _calculate_atr(candles, period=ATR_PERIOD):
    """Calcule l'ATR a partir des bougies disponibles."""
    if len(candles) < 2:
        return 0.0

    true_ranges = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )

        if math.isfinite(tr):
            true_ranges.append(max(0.0, tr))

    if not true_ranges:
        return 0.0

    recent = true_ranges[-period:]
    atr = sum(recent) / len(recent)

    return atr if atr > 0 else 0.0


def _find_pivots(candles, radius=PIVOT_RADIUS):
    """
    Detecte les sommets et creux locaux.
    Les pivots sont utilises pour construire les trendlines.
    """
    highs = []
    lows = []

    if len(candles) < radius * 2 + 5:
        return highs, lows

    start = max(radius, len(candles) - PIVOT_LOOKBACK)
    end = len(candles) - radius

    for i in range(start, end):
        high = candles[i]["high"]
        low = candles[i]["low"]

        left = candles[i - radius:i]
        right = candles[i + 1:i + radius + 1]

        if all(high >= item["high"] for item in left + right):
            highs.append((i, high))

        if all(low <= item["low"] for item in left + right):
            lows.append((i, low))

    return highs, lows


# ============================================================
# TRENDLINES
# ============================================================

def _line_value(point_a, point_b, x):
    """Calcule la valeur d'une droite au point x."""
    x1, y1 = point_a
    x2, y2 = point_b

    if x1 == x2:
        return None

    slope = (y2 - y1) / (x2 - x1)
    return y1 + slope * (x - x1)


def _find_trendline(pivots, direction, atr, last_index):
    """
    Cherche une trendline simple a partir de pivots recents.

    BUY :
        trendline haussiere passant par deux creux croissants.

    SELL :
        trendline baissiere passant par deux sommets decroissants.
    """
    if len(pivots) < 2:
        return None

    recent = pivots[-TRENDLINE_LOOKBACK:]

    # On examine les paires recentes pour eviter de dependre
    # uniquement des deux derniers pivots.
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

            projected = _line_value(point_a, point_b, last_index)

            if projected is None:
                continue

            # Exclut les droites dont la projection est aberrante.
            if not math.isfinite(projected):
                continue

            if atr > 0 and abs(projected - y2) > atr * 20:
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

    # Priorite aux trendlines fondees sur des pivots plus eloignes,
    # sans penaliser excessivement les lignes recentes.
    candidates.sort(
        key=lambda item: (
            item["span"],
            item["point_b"][0],
        ),
        reverse=True,
    )

    return candidates[0]


# ============================================================
# SUPPORTS ET RESISTANCES
# ============================================================

def _cluster_levels(values, tolerance):
    """
    Regroupe les niveaux de prix proches.
    Chaque groupe represente une zone horizontale potentielle.
    """
    if not values:
        return []

    values = sorted(values)
    clusters = []

    for value in values:
        if not clusters:
            clusters.append([value])
            continue

        current_mean = sum(clusters[-1]) / len(clusters[-1])

        if abs(value - current_mean) <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])

    levels = []

    for cluster in clusters:
        levels.append({
            "price": sum(cluster) / len(cluster),
            "touches": len(cluster),
            "low": min(cluster),
            "high": max(cluster),
        })

    return levels


def _find_horizontal_levels(candles, atr):
    """Construit des zones horizontales a partir des pivots."""
    highs, lows = _find_pivots(candles)

    tolerance = max(
        atr * LEVEL_CLUSTER_DISTANCE_ATR,
        1e-8,
    )

    resistance_levels = _cluster_levels(
        [price for _, price in highs],
        tolerance,
    )

    support_levels = _cluster_levels(
        [price for _, price in lows],
        tolerance,
    )

    return support_levels, resistance_levels


def _nearest_level(levels, reference_price, direction):
    """
    BUY : recherche le support le plus proche sous le prix.
    SELL : recherche la resistance la plus proche au-dessus du prix.
    """
    if direction == "BUY":
        candidates = [
            level for level in levels
            if level["price"] <= reference_price
        ]
        candidates.sort(
            key=lambda level: reference_price - level["price"]
        )
    else:
        candidates = [
            level for level in levels
            if level["price"] >= reference_price
        ]
        candidates.sort(
            key=lambda level: level["price"] - reference_price
        )

    return candidates[0] if candidates else None


def _nearest_target(levels, entry, direction):
    """Recherche le prochain niveau horizontal oppose a l'entree."""
    if direction == "BUY":
        candidates = [
            level for level in levels
            if level["price"] > entry
        ]
        candidates.sort(key=lambda level: level["price"])
    else:
        candidates = [
            level for level in levels
            if level["price"] < entry
        ]
        candidates.sort(
            key=lambda level: level["price"],
            reverse=True,
        )

    return candidates[0] if candidates else None


# ============================================================
# DETECTION D'UNE CONFIGURATION
# ============================================================

def _build_candidate(symbol, timeframe, candles, price_now):
    """
    Detecte une configuration anticipative de confluence
    trendline + support/resistance.
    """
    if len(candles) < MIN_CANDLES.get(timeframe, 30):
        return None

    atr = _calculate_atr(candles)

    if atr <= 0:
        return None

    last_index = len(candles) - 1
    last_close = candles[-1]["close"]

    price = _number(price_now)

    if price is None or price <= 0:
        price = last_close

    highs, lows = _find_pivots(candles)

    supports, resistances = _find_horizontal_levels(
        candles,
        atr,
    )

    directions = (
        ("BUY", lows, supports, resistances),
        ("SELL", highs, resistances, supports),
    )

    candidates = []

    for direction, pivots, relevant_levels, opposite_levels in directions:
        trendline = _find_trendline(
            pivots=pivots,
            direction=direction,
            atr=atr,
            last_index=last_index,
        )

        if trendline is None:
            continue

        line_price = trendline["price"]

        # Selection du support ou de la resistance proche
        # de la projection de la trendline.
        level = _nearest_level(
            relevant_levels,
            line_price,
            direction,
        )

        # Si aucun niveau n'existe du bon cote, on cherche
        # le niveau le plus proche sans imposer le cote.
        if level is None and relevant_levels:
            level = min(
                relevant_levels,
                key=lambda item: abs(item["price"] - line_price),
            )

        if level is None:
            continue

        confluence_distance = abs(
            line_price - level["price"]
        )

        if confluence_distance > atr * MAX_CONFLUENCE_DISTANCE_ATR:
            continue

        # La zone de confluence se situe entre la trendline
        # et le niveau horizontal.
        zone_low = min(line_price, level["low"])
        zone_high = max(line_price, level["high"])
        zone_center = (zone_low + zone_high) / 2

        distance_to_zone = abs(price - zone_center)

        # On accepte l'approche de la zone, sans attendre
        # obligatoirement que le prix la touche.
        if distance_to_zone > atr * MAX_ENTRY_DISTANCE_ATR:
            continue

        # BUY doit rester dans une structure haussiere.
        # SELL doit rester dans une structure baissiere.
        if direction == "BUY" and price < zone_low - atr * 0.50:
            continue

        if direction == "SELL" and price > zone_high + atr * 0.50:
            continue

        # Le prix d'entree est le prix observe au moment
        # de l'analyse. L'alerte peut donc etre anticipee.
        entry = price

        if direction == "BUY":
            stop_loss = min(zone_low, level["low"]) - atr * SL_BUFFER_ATR
            risk = entry - stop_loss
        else:
            stop_loss = max(zone_high, level["high"]) + atr * SL_BUFFER_ATR
            risk = stop_loss - entry

        if risk <= 0:
            continue

        target = _nearest_target(
            opposite_levels,
            entry,
            direction,
        )

        if target is not None:
            take_profit = target["price"]
            target_type = "Niveau horizontal oppose"
        else:
            # Si aucun niveau oppose n'est disponible,
            # projection de 3R comme objectif technique.
            # Cela ne constitue PAS un filtre de RR minimum.
            if direction == "BUY":
                take_profit = entry + 3.0 * risk
            else:
                take_profit = entry - 3.0 * risk

            target_type = "Projection technique 3R (sans niveau oppose detecte)"

        if direction == "BUY" and take_profit <= entry:
            continue

        if direction == "SELL" and take_profit >= entry:
            continue

        reward = abs(take_profit - entry)
        rr = reward / risk if risk > 0 else 0.0

        # Score indicatif : proximite de la confluence,
        # nombre de contacts et distance au prix.
        proximity_score = max(
            0.0,
            1.0 - confluence_distance / max(
                atr * MAX_CONFLUENCE_DISTANCE_ATR,
                1e-8,
            ),
        )

        distance_score = max(
            0.0,
            1.0 - distance_to_zone / max(
                atr * MAX_ENTRY_DISTANCE_ATR,
                1e-8,
            ),
        )

        touch_score = min(level["touches"], 5) / 5.0

        score = round(
            100 * (
                0.45 * proximity_score
                + 0.35 * distance_score
                + 0.20 * touch_score
            ),
            1,
        )

        candidates.append({
            "strategy": STRATEGY_NAME,
            "symbol": symbol,
            "symbol_name": SYMBOL_NAMES.get(symbol, symbol),
            "timeframe": timeframe,
            "direction": direction,
            "entry": round(entry, 8),
            "stop_loss": round(stop_loss, 8),
            "take_profit": round(take_profit, 8),
            "rr": round(rr, 2),
            "atr": round(atr, 8),
            "trendline_price": round(line_price, 8),
            "horizontal_level": round(level["price"], 8),
            "zone_low": round(zone_low, 8),
            "zone_high": round(zone_high, 8),
            "distance_to_zone_atr": round(
                distance_to_zone / atr,
                3,
            ),
            "confluence_distance_atr": round(
                confluence_distance / atr,
                3,
            ),
            "level_touches": int(level["touches"]),
            "score": score,
            "target_type": target_type,
            "status": "ANTICIPATION",
            "price_at_analysis": round(price, 8),
        })

    if not candidates:
        return None

    # Priorite au meilleur score.
    candidates.sort(
        key=lambda item: (
            item["score"],
            item["rr"],
        ),
        reverse=True,
    )

    return candidates[0]


# ============================================================
# IDENTIFIANT ET FONCTION PUBLIQUE
# ============================================================

def _make_signal_id(signal):
    """
    Identifiant reproductible pour eviter les doublons.
    Le prix est arrondi pour limiter les changements
    d'identifiant provoques par de petites variations.
    """
    raw = "|".join([
        str(signal.get("symbol", "")),
        str(signal.get("timeframe", "")),
        str(signal.get("direction", "")),
        str(round(float(signal.get("zone_low", 0)), 3)),
        str(round(float(signal.get("zone_high", 0)), 3)),
    ])

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


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
    Fonction appelee par scheduled_analysis.py.

    Examine les unites de temps dans l'ordre D1, H4, H2, H1.
    Retourne la meilleure configuration de la premiere unite
    de temps ou une confluence exploitable est detectee.

    Retour :
        [] si aucune configuration n'est trouvee ;
        [signal] si une configuration est detectee.
    """
    raw_by_timeframe = {
        "D1": d1,
        "H4": h4,
        "H2": h2,
        "H1": h1,
    }

    if diagnostics is not None and not isinstance(diagnostics, dict):
        diagnostics = None

    if diagnostics is not None:
        diagnostics.setdefault("timeframes_checked", [])
        diagnostics.setdefault("signals_found", [])
        diagnostics.setdefault("reasons", [])

    for timeframe in TIMEFRAME_PRIORITY:
        raw_candles = raw_by_timeframe.get(timeframe)
        candles = _normalise_candles(raw_candles)

        if diagnostics is not None:
            diagnostics["timeframes_checked"].append(timeframe)

        if len(candles) < MIN_CANDLES.get(timeframe, 30):
            if diagnostics is not None:
                diagnostics["reasons"].append(
                    f"{timeframe}: pas assez de bougies "
                    f"({len(candles)} disponibles)."
                )
            continue

        signal = _build_candidate(
            symbol=symbol,
            timeframe=timeframe,
            candles=candles,
            price_now=price_now,
        )

        if signal is None:
            if diagnostics is not None:
                diagnostics["reasons"].append(
                    f"{timeframe}: aucune confluence exploitable."
                )
            continue

        signal["signal_id"] = _make_signal_id(signal)

        if diagnostics is not None:
            diagnostics["signals_found"].append({
                "timeframe": timeframe,
                "direction": signal["direction"],
                "score": signal["score"],
            })
            diagnostics["selected_timeframe"] = timeframe

        # On privilegie la premiere unite de temps valide.
        return [signal]

    return []


# ============================================================
# MESSAGE TELEGRAM
# ============================================================

def _format_price(value):
    """Affiche le prix avec une precision adaptee."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return str(value)

    if abs(value) >= 1000:
        return f"{value:.3f}"

    if abs(value) >= 10:
        return f"{value:.4f}"

    return f"{value:.5f}"


def format_message(signal):
    """
    Formate une alerte Telegram en francais.
    Ne passe aucun ordre : le message est informatif.
    """
    symbol = signal.get("symbol", "Indice inconnu")
    symbol_name = signal.get(
        "symbol_name",
        SYMBOL_NAMES.get(symbol, symbol),
    )

    direction = str(signal.get("direction", "")).upper()
    timeframe = signal.get("timeframe", "?")

    if direction == "BUY":
        direction_text = "ACHAT (BUY)"
        emoji = "🟢"
    elif direction == "SELL":
        direction_text = "VENTE (SELL)"
        emoji = "🔴"
    else:
        direction_text = direction
        emoji = "📊"

    entry = signal.get("entry", 0)
    stop_loss = signal.get("stop_loss", 0)
    take_profit = signal.get("take_profit", 0)
    rr = signal.get("rr", 0)
    score = signal.get("score", 0)

    zone_low = signal.get("zone_low")
    zone_high = signal.get("zone_high")
    level = signal.get("horizontal_level")
    trendline = signal.get("trendline_price")
    distance = signal.get("distance_to_zone_atr")
    touches = signal.get("level_touches")
    target_type = signal.get("target_type", "Objectif technique")
    signal_id = signal.get("signal_id", "N/A")

    lines = [
        "━━━━━━━━━━━━━━━━━━",
        "🚨 TRADER AI PRO",
        "STRATEGIE : TRENDLINE + CONFLUENCE",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"{emoji} Direction : {direction_text}",
        f"📈 Indice : {symbol_name}",
        f"⏱ Unite de temps : {timeframe}",
        "",
        "🎯 PLAN TECHNIQUE",
        f"Entree indicative : {_format_price(entry)}",
        f"Stop Loss : {_format_price(stop_loss)}",
        f"Take Profit : {_format_price(take_profit)}",
        f"Risque/Rendement estime : 1:{rr}",
        "",
        "📐 CONFLUENCE DETECTEE",
    ]

    if zone_low is not None and zone_high is not None:
        lines.append(
            f"Zone de confluence : "
            f"{_format_price(zone_low)} - {_format_price(zone_high)}"
        )

    if level is not None:
        lines.append(f"Niveau horizontal : {_format_price(level)}")

    if trendline is not None:
        lines.append(f"Projection trendline : {_format_price(trendline)}")

    if distance is not None:
        lines.append(f"Distance a la zone : {distance} ATR")

    if touches is not None:
        lines.append(f"Contacts du niveau : {touches}")

    lines.extend([
        f"Score technique indicatif : {score}/100",
        f"Objectif : {target_type}",
        "",
        "⚠️ ALERTE ANTICIPEE",
        "La confluence est detectee, mais le prix peut encore",
        "evoluer avant d'atteindre ou de quitter la zone.",
        "Le signal n'est pas une garantie de resultat.",
        "",
        "Execution automatique : DESACTIVEE",
        "Ordre a executer manuellement sur le compte DEMO.",
        "",
        f"ID : {signal_id}",
        "━━━━━━━━━━━━━━━━━━",
    ])

    return "\n".join(lines)
