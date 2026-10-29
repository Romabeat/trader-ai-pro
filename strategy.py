"""
Trader AI Pro - Strategie SMC D1/H4
------------------------------------
D1 : biais directionnel.
H4 : BOS, displacement et Order Block.
Entree : ouverture de la bougie de l'Order Block.
SL : au-dela de la zone avec marge ATR.
TP : cible structurelle situee au-dela du prix actuel.
RR minimum : 1.5.

Scanner uniquement : aucun ordre n'est execute.
"""

from math import isfinite


# ============================================================
# CONFIGURATION
# ============================================================

MIN_RR = 1.5

MIN_D1_CANDLES = 100
MIN_H4_CANDLES = 200

PIVOT_RADIUS = 2

OB_LOOKBACK = 40
OB_SEARCH_BACK = 5

ATR_PERIOD = 14
SL_ATR_BUFFER = 0.10

MIN_BODY_RATIO = 0.55
MIN_DISPLACEMENT_ATR = 0.80

MAX_BOS_AGE = 20
MAX_ENTRY_DISTANCE_ATR = 1.5


# ============================================================
# OUTILS
# ============================================================

def _number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _first_value(row, keys):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _diagnose(diagnostics, symbol, reason):
    if diagnostics is None:
        return

    if isinstance(diagnostics, dict):
        diagnostics.setdefault(symbol, []).append(reason)

    elif isinstance(diagnostics, list):
        diagnostics.append(f"{symbol}: {reason}")


def _normalize(candles):
    """
    Normalise les bougies et verifie leur coherence.
    Les donnees numeriques d'epoch doivent etre strictement
    chronologiques lorsqu'elles sont disponibles.
    """
    result = []

    if not isinstance(candles, (list, tuple)):
        return result

    for row in candles:
        if not isinstance(row, dict):
            continue

        o = _number(_first_value(row, ("open", "o", "Open")))
        h = _number(_first_value(row, ("high", "h", "High")))
        low = _number(_first_value(row, ("low", "l", "Low")))
        c = _number(_first_value(row, ("close", "c", "Close")))

        if None in (o, h, low, c):
            continue

        if h < max(o, low, c) or low > min(o, h, c):
            continue

        epoch = _first_value(
            row,
            ("epoch", "time", "timestamp", "datetime"),
        )

        result.append({
            "o": o,
            "h": h,
            "l": low,
            "c": c,
            "epoch": epoch,
        })

    numeric_epochs = [_number(row["epoch"]) for row in result]

    # Ne pas inverser silencieusement un historique mal ordonne.
    if (
        len(result) > 1
        and all(value is not None for value in numeric_epochs)
    ):
        if any(
            numeric_epochs[i] >= numeric_epochs[i + 1]
            for i in range(len(numeric_epochs) - 1)
        ):
            return []

    return result


# ============================================================
# INDICATEURS
# ============================================================

def _true_range(current, previous_close):
    return max(
        current["h"] - current["l"],
        abs(current["h"] - previous_close),
        abs(current["l"] - previous_close),
    )


def _atr(rows, period=ATR_PERIOD):
    if len(rows) < period + 1:
        return None

    ranges = [
        _true_range(rows[i], rows[i - 1]["c"])
        for i in range(len(rows) - period, len(rows))
    ]

    if not ranges:
        return None

    value = sum(ranges) / len(ranges)

    if value <= 0 or not isfinite(value):
        return None

    return value


def _body_ratio(candle):
    candle_range = candle["h"] - candle["l"]

    if candle_range <= 0:
        return 0.0

    return abs(candle["c"] - candle["o"]) / candle_range


def _is_bullish(candle):
    return candle["c"] > candle["o"]


def _is_bearish(candle):
    return candle["c"] < candle["o"]


# ============================================================
# PIVOTS ET STRUCTURE
# ============================================================

def _pivots(rows, radius=PIVOT_RADIUS):
    highs = []
    lows = []

    if len(rows) < 2 * radius + 1:
        return highs, lows

    for i in range(radius, len(rows) - radius):
        candle = rows[i]

        left = rows[i - radius:i]
        right = rows[i + 1:i + radius + 1]

        if all(candle["h"] > x["h"] for x in left + right):
            highs.append((i, candle["h"]))

        if all(candle["l"] < x["l"] for x in left + right):
            lows.append((i, candle["l"]))

    return highs, lows


def _structure(rows):
    """
    Renvoie une tendance swing confirmee.
    NEUTRAL ne signifie pas qu'aucun BOS exploitable n'existe.
    """
    highs, lows = _pivots(rows)

    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"

    previous_high = highs[-2][1]
    latest_high = highs[-1][1]

    previous_low = lows[-2][1]
    latest_low = lows[-1][1]

    if (
        latest_high > previous_high
        and latest_low > previous_low
    ):
        return "BULLISH"

    if (
        latest_high < previous_high
        and latest_low < previous_low
    ):
        return "BEARISH"

    return "NEUTRAL"


def _daily_bias(d1):
    return _structure(d1)


# ============================================================
# BREAK OF STRUCTURE ET DISPLACEMENT
# ============================================================

def _find_bos(rows, direction, atr_value):
    """
    Cherche le BOS le plus recent dans le sens du biais D1.

    La cassure doit :
    - etre confirmee par la cloture ;
    - franchir un pivot precedemment confirme ;
    - presenter un corps suffisamment important ;
    - respecter le seuil de displacement ATR.
    """
    start = max(
        PIVOT_RADIUS * 2 + 1,
        len(rows) - OB_LOOKBACK,
    )

    for i in range(len(rows) - 1, start - 1, -1):
        candle = rows[i]

        if direction == "BUY" and not _is_bullish(candle):
            continue

        if direction == "SELL" and not _is_bearish(candle):
            continue

        if _body_ratio(candle) < MIN_BODY_RATIO:
            continue

        body = abs(candle["c"] - candle["o"])

        if body < MIN_DISPLACEMENT_ATR * atr_value:
            continue

        # Seules les bougies precedant le BOS servent a
        # determiner les pivots de reference.
        previous_rows = rows[:i]
        highs, lows = _pivots(previous_rows)

        if direction == "BUY":
            candidates = [
                (index, level)
                for index, level in highs
                if candle["c"] > level
            ]
        else:
            candidates = [
                (index, level)
                for index, level in lows
                if candle["c"] < level
            ]

        if not candidates:
            continue

        # Le pivot casse le plus recent est la reference.
        pivot_index, broken_level = candidates[-1]

        return {
            "index": i,
            "broken_level": broken_level,
            "pivot_index": pivot_index,
            "impulse": candle,
            "age": len(rows) - 1 - i,
        }

    return None


# ============================================================
# ORDER BLOCK
# ============================================================

def _find_order_block(rows, bos, direction):
    """
    Recherche la derniere bougie opposee avant l'impulsion BOS.
    L'entree theorique est l'ouverture de cette bougie.
    """
    impulse_index = bos["index"]
    first_index = max(0, impulse_index - OB_SEARCH_BACK)

    for i in range(impulse_index - 1, first_index - 1, -1):
        candle = rows[i]

        if direction == "BUY" and _is_bearish(candle):
            return {
                "index": i,
                "candle": candle,
                "zone_low": candle["l"],
                "zone_high": candle["h"],
                "entry": candle["o"],
            }

        if direction == "SELL" and _is_bullish(candle):
            return {
                "index": i,
                "candle": candle,
                "zone_low": candle["l"],
                "zone_high": candle["h"],
                "entry": candle["o"],
            }

    return None


def _is_invalidated(rows, ob, direction):
    """
    Une cloture ulterieure au-dela de la limite invalide
    l'Order Block.
    """
    for candle in rows[ob["index"] + 1:]:
        if direction == "BUY" and candle["c"] < ob["zone_low"]:
            return True

        if direction == "SELL" and candle["c"] > ob["zone_high"]:
            return True

    return False


# ============================================================
# CONFLUENCES SECONDAIRES
# ============================================================

def _liquidity_sweep(rows, direction, lookback=20):
    if len(rows) < lookback + 2:
        return False

    previous = rows[-lookback - 1:-1]
    latest = rows[-1]

    if direction == "BUY":
        previous_low = min(c["l"] for c in previous)

        return (
            latest["l"] < previous_low
            and latest["c"] > previous_low
        )

    previous_high = max(c["h"] for c in previous)

    return (
        latest["h"] > previous_high
        and latest["c"] < previous_high
    )


def _engulfing(rows, direction):
    if len(rows) < 2:
        return False

    previous = rows[-2]
    latest = rows[-1]

    if direction == "BUY":
        return (
            _is_bearish(previous)
            and _is_bullish(latest)
            and latest["o"] <= previous["c"]
            and latest["c"] >= previous["o"]
        )

    return (
        _is_bullish(previous)
        and _is_bearish(latest)
        and latest["o"] >= previous["c"]
        and latest["c"] <= previous["o"]
    )


# ============================================================
# TAKE PROFIT STRUCTUREL
# ============================================================

def _target_from_structure(
    rows,
    direction,
    entry,
    stop_loss,
    current_price,
):
    """
    La cible doit respecter le RR minimum et rester au-dela
    du prix actuel. Cela evite de signaler un TP deja depasse.
    """
    highs, lows = _pivots(rows)

    risk = abs(entry - stop_loss)

    if risk <= 0:
        return None, None

    if direction == "BUY":
        candidates = sorted({
            level
            for _, level in highs
            if level > entry and level > current_price
        })

        for target in candidates:
            rr = (target - entry) / risk

            if rr >= MIN_RR:
                return target, rr

    else:
        candidates = sorted(
            {
                level
                for _, level in lows
                if level < entry and level < current_price
            },
            reverse=True,
        )

        for target in candidates:
            rr = (entry - target) / risk

            if rr >= MIN_RR:
                return target, rr

    return None, None


# ============================================================
# DETECTION DES SIGNAUX
# ============================================================

def find_signals(
    symbol,
    d1=None,
    h4=None,
    h1=None,
    m30=None,
    price_now=None,
    diagnostics=None,
):
    """
    Interface compatible avec scheduled_analysis.py.
    Retourne toujours une liste de signaux.
    Aucun ordre n'est execute.
    """
    signals = []

    def reject(reason):
        _diagnose(diagnostics, symbol, reason)

    d1_rows = _normalize(d1)
    h4_rows = _normalize(h4)

    # 1. Historique
    if len(d1_rows) < MIN_D1_CANDLES:
        reject(
            f"Historique D1 insuffisant : "
            f"{len(d1_rows)}/{MIN_D1_CANDLES}."
        )
        return signals

    if len(h4_rows) < MIN_H4_CANDLES:
        reject(
            f"Historique H4 insuffisant : "
            f"{len(h4_rows)}/{MIN_H4_CANDLES}."
        )
        return signals

    # 2. Biais D1
    bias = _daily_bias(d1_rows)

    if bias == "NEUTRAL":
        reject(
            "Biais D1 neutre : structure swing non confirmee."
        )
        return signals

    direction = "BUY" if bias == "BULLISH" else "SELL"

    # 3. Structure H4 informative, sans rejet automatique
    # lorsqu'elle est neutre. Le BOS doit toujours confirmer
    # une cassure dans le sens du biais D1.
    h4_structure = _structure(h4_rows)

    # 4. ATR H4
    atr_value = _atr(h4_rows)

    if atr_value is None:
        reject("ATR H4 indisponible ou invalide.")
        return signals

    # 5. BOS dans le sens du biais D1
    bos = _find_bos(h4_rows, direction, atr_value)

    if bos is None:
        reject(
            f"Aucun BOS H4 recent avec displacement en direction "
            f"du biais D1 ({direction})."
        )
        return signals

    if bos["age"] > MAX_BOS_AGE:
        reject(f"BOS trop ancien : {bos['age']} bougies H4.")
        return signals

    # 6. Order Block
    ob = _find_order_block(h4_rows, bos, direction)

    if ob is None:
        reject("Aucune bougie opposee trouvee avant le BOS.")
        return signals

    if _is_invalidated(h4_rows, ob, direction):
        reject("Order Block invalide par une cloture ulterieure.")
        return signals

    zone_low = ob["zone_low"]
    zone_high = ob["zone_high"]
    entry = ob["entry"]

    if zone_high <= zone_low:
        reject("Zone Order Block invalide.")
        return signals

    # 7. Prix actuel
    current_price = _number(price_now)

    if current_price is None or current_price <= 0:
        reject("Prix actuel absent ou invalide.")
        return signals

    distance = abs(current_price - entry)
    max_distance = MAX_ENTRY_DISTANCE_ATR * atr_value

    if distance > max_distance:
        reject(
            f"Prix trop eloigne de l'entree sniper : "
            f"{distance:.5f}, limite {max_distance:.5f}."
        )
        return signals

    if direction == "BUY" and current_price <= entry:
        reject("BUY : le prix doit etre au-dessus de l'entree.")
        return signals

    if direction == "SELL" and current_price >= entry:
        reject("SELL : le prix doit etre en dessous de l'entree.")
        return signals

    # 8. Stop Loss
    buffer = atr_value * SL_ATR_BUFFER

    if direction == "BUY":
        stop_loss = zone_low - buffer
    else:
        stop_loss = zone_high + buffer

    risk = abs(entry - stop_loss)

    if risk <= 0:
        reject("Risque invalide : calcul du SL impossible.")
        return signals

    # 9. Take Profit : cible encore devant le prix actuel
    take_profit, rr = _target_from_structure(
        h4_rows,
        direction,
        entry,
        stop_loss,
        current_price,
    )

    if take_profit is None or rr is None:
        reject(
            "Aucune cible structurelle encore accessible "
            "ne respecte le RR minimum."
        )
        return signals

    if rr < MIN_RR:
        reject(f"RR insuffisant : {rr:.2f}, minimum {MIN_RR:.2f}.")
        return signals

    # 10. Identifiant du signal
    epoch = ob["candle"].get("epoch")

    if epoch is None:
        epoch = f"index-{ob['index']}"

    safe_epoch = str(epoch).replace(" ", "_").replace(":", "-")

    signal_id = (
        f"{symbol}-{direction}-D1H4-POI-{safe_epoch}-"
        f"{zone_low:.8f}-{zone_high:.8f}"
    )

    # 11. Signal final
    signal = {
        "signal_id": signal_id,
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr": rr,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "current_price": current_price,
        "h4_structure": h4_structure,
        "d1_bias": bias,
        "timeframe": "D1 bias / H4 BOS / H4 POI",
        "order_block_index": ob["index"],
        "bos_index": bos["index"],
        "bos_level": bos["broken_level"],
        "bos_age": bos["age"],
        "atr_h4": atr_value,
        "engulfing": _engulfing(h4_rows, direction),
        "liquidity_sweep": _liquidity_sweep(h4_rows, direction),
        "notes": (
            "Biais D1 confirme ; BOS H4 avec displacement ; "
            "Order Block valide ; cible structurelle accessible."
        ),
    }

    signals.append(signal)

    _diagnose(
        diagnostics,
        symbol,
        "Setup valide : biais D1, BOS H4, Order Block et RR conformes.",
    )

    return signals


# ============================================================
# FORMATAGE TELEGRAM
# ============================================================

def format_message(signal):
    direction = signal.get("direction", "UNKNOWN")
    symbol = signal.get("symbol", "UNKNOWN")

    direction_label = {
        "BUY": "ACHAT",
        "SELL": "VENTE",
    }.get(direction, direction)

    rr = _number(signal.get("rr"))

    rr_text = f"1:{rr:.2f}" if rr is not None else "Indisponible"

    return "\n".join([
        "TRADER AI PRO — SIGNAL SMC",
        "",
        f"Instrument : {symbol}",
        f"Direction : {direction_label}",
        "Biais : Daily (D1)",
        "BOS et Order Block : H4",
        "Méthode : Sniper Entry — ouverture de l'OB",
        "",
        f"Zone OB : {signal.get('zone_low')} - "
        f"{signal.get('zone_high')}",
        f"Entrée théorique : {signal.get('entry')}",
        f"Stop Loss : {signal.get('stop_loss')}",
        f"Take Profit : {signal.get('take_profit')}",
        f"RR estimé : {rr_text}",
        f"Prix observé : {signal.get('current_price')}",
        "",
        f"Biais D1 : {signal.get('d1_bias')}",
        f"Structure H4 : {signal.get('h4_structure')}",
        f"Niveau BOS : {signal.get('bos_level')}",
        f"Âge du BOS : {signal.get('bos_age')} bougies H4",
        f"ATR H4 : {signal.get('atr_h4')}",
        f"Englobement H4 : "
        f"{'Oui' if signal.get('engulfing') else 'Non'}",
        f"Prise de liquidité : "
        f"{'Oui' if signal.get('liquidity_sweep') else 'Non'}",
        "",
        f"Note : {signal.get('notes', '')}",
        "",
        "Scanner uniquement : aucun ordre automatique exécuté.",
        "Vérifier la validité du setup avant toute décision.",
    ])
