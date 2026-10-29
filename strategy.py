"""
Trader AI Pro - Strategie SMC D1/H4
------------------------------------
D1 : biais directionnel.
H4 : structure, BOS, displacement et Order Block.
Entree : ouverture de la bougie de l'Order Block.
SL : au-dela de la zone avec marge ATR.
TP : cible structurelle H4.
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

# Eviter les configurations trop anciennes.
MAX_BOS_AGE = 20

# Eviter une entree devenue trop eloignee du prix.
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
    """
    Compatible avec un dictionnaire ou une liste.

    Avec un dictionnaire :
        diagnostics[symbol] = [motifs de rejet]

    Avec une liste :
        ajout d'un message texte.
    """
    if diagnostics is None:
        return

    message = f"{symbol}: {reason}"

    if isinstance(diagnostics, dict):
        diagnostics.setdefault(symbol, []).append(reason)

    elif isinstance(diagnostics, list):
        diagnostics.append(message)


def _normalize(candles):
    """
    Accepte les formats open/high/low/close et o/h/l/c.
    Les bougies doivent etre chronologiques.
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

    # Refuser un historique mal ordonne plutot que d'inverser
    # silencieusement les bougies.
    epochs = [
        _number(row["epoch"])
        for row in result
    ]

    valid_epochs = [
        value for value in epochs
        if value is not None
    ]

    if len(valid_epochs) == len(result) and len(result) > 1:
        if any(
            valid_epochs[i] >= valid_epochs[i + 1]
            for i in range(len(valid_epochs) - 1)
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

    ranges = []

    for i in range(len(rows) - period, len(rows)):
        ranges.append(
            _true_range(rows[i], rows[i - 1]["c"])
        )

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
# BREAK OF STRUCTURE
# ============================================================

def _find_bos(rows, direction, atr_value):
    """
    Recherche une cassure confirmee par cloture et accompagnee
    d'un displacement.

    Les pivots de reference sont calcules uniquement sur les
    bougies precedant la bougie de cassure.
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

        previous_rows = rows[:i]
        highs, lows = _pivots(previous_rows)

        if direction == "BUY":
            candidates = [
                (index, level)
                for index, level in highs
                if rows[index]["h"] < candle["c"]
            ]
        else:
            candidates = [
                (index, level)
                for index, level in lows
                if rows[index]["l"] > candle["c"]
            ]

        if not candidates:
            continue

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
    Verifie les clotures ulterieures a l'Order Block.
    Une cloture au-dela de la zone invalide le setup.
    """
    for candle in rows[ob["index"] + 1:]:
        if (
            direction == "BUY"
            and candle["c"] < ob["zone_low"]
        ):
            return True

        if (
            direction == "SELL"
            and candle["c"] > ob["zone_high"]
        ):
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

def _target_from_structure(rows, direction, entry, stop_loss):
    highs, lows = _pivots(rows)

    risk = abs(entry - stop_loss)

    if risk <= 0:
        return None, None

    if direction == "BUY":
        candidates = sorted({
            level
            for _, level in highs
            if level > entry
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
                if level < entry
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
    Compatible avec l'interface de scheduled_analysis.py.

    diagnostics accepte un dictionnaire ou une liste.
    Retourne toujours une liste de signaux.
    """

    signals = []

    def reject(reason):
        _diagnose(
            diagnostics,
            symbol,
            reason,
        )

    d1_rows = _normalize(d1)
    h4_rows = _normalize(h4)

    # --------------------------------------------------------
    # 1. Historique
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # 2. Biais Daily
    # --------------------------------------------------------

    bias = _daily_bias(d1_rows)

    if bias == "NEUTRAL":
        reject(
            "Biais D1 neutre : structure directionnelle non confirmee."
        )
        return signals

    direction = "BUY" if bias == "BULLISH" else "SELL"

    # --------------------------------------------------------
    # 3. Structure H4
    # --------------------------------------------------------

    h4_structure = _structure(h4_rows)

    if h4_structure != bias:
        reject(
            f"Desaccord D1/H4 : D1={bias}, H4={h4_structure}."
        )
        return signals

    # --------------------------------------------------------
    # 4. ATR H4
    # --------------------------------------------------------

    atr_value = _atr(h4_rows)

    if atr_value is None:
        reject("ATR H4 indisponible ou invalide.")
        return signals

    # --------------------------------------------------------
    # 5. BOS et displacement
    # --------------------------------------------------------

    bos = _find_bos(
        h4_rows,
        direction,
        atr_value,
    )

    if bos is None:
        reject(
            "Aucun BOS H4 recent avec displacement suffisant."
        )
        return signals

    if bos["age"] > MAX_BOS_AGE:
        reject(
            f"BOS trop ancien : {bos['age']} bougies H4."
        )
        return signals

    # --------------------------------------------------------
    # 6. Order Block
    # --------------------------------------------------------

    ob = _find_order_block(
        h4_rows,
        bos,
        direction,
    )

    if ob is None:
        reject(
            "Aucune bougie opposee valide avant le BOS."
        )
        return signals

    if _is_invalidated(
        h4_rows,
        ob,
        direction,
    ):
        reject(
            "Order Block invalide par une cloture ulterieure."
        )
        return signals

    zone_low = ob["zone_low"]
    zone_high = ob["zone_high"]
    entry = ob["entry"]

    if zone_high <= zone_low:
        reject("Zone Order Block invalide.")
        return signals

    # --------------------------------------------------------
    # 7. Prix actuel et entree sniper
    # --------------------------------------------------------

    current_price = _number(price_now)

    if current_price is None or current_price <= 0:
        reject("Prix actuel absent ou invalide.")
        return signals

    distance = abs(current_price - entry)

    if distance > MAX_ENTRY_DISTANCE_ATR * atr_value:
        reject(
            "Prix trop eloigne de l'entree sniper : "
            f"{distance:.5f}, limite "
            f"{MAX_ENTRY_DISTANCE_ATR * atr_value:.5f}."
        )
        return signals

    if direction == "BUY" and current_price <= entry:
        reject(
            "BUY : prix au niveau de l'entree ou en dessous."
        )
        return signals

    if direction == "SELL" and current_price >= entry:
        reject(
            "SELL : prix au niveau de l'entree ou au-dessus."
        )
        return signals

    # --------------------------------------------------------
    # 8. Stop Loss
    # --------------------------------------------------------

    buffer = atr_value * SL_ATR_BUFFER

    if direction == "BUY":
        stop_loss = zone_low - buffer
    else:
        stop_loss = zone_high + buffer

    risk = abs(entry - stop_loss)

    if risk <= 0:
        reject("Risque invalide : impossible de calculer le SL.")
        return signals

    # --------------------------------------------------------
    # 9. Take Profit et RR
    # --------------------------------------------------------

    take_profit, rr = _target_from_structure(
        h4_rows,
        direction,
        entry,
        stop_loss,
    )

    if take_profit is None or rr is None:
        reject(
            "Aucune cible structurelle ne respecte le RR minimum."
        )
        return signals

    if rr < MIN_RR:
        reject(
            f"RR insuffisant : {rr:.2f}, minimum {MIN_RR:.2f}."
        )
        return signals

    # --------------------------------------------------------
    # 10. Identifiant unique
    # --------------------------------------------------------

    epoch = ob["candle"].get("epoch")

    if epoch is None:
        epoch = f"index-{ob['index']}"

    safe_epoch = str(epoch).replace(" ", "_").replace(":", "-")

    signal_id = (
        f"{symbol}-{direction}-D1H4-POI-{safe_epoch}-"
        f"{zone_low:.8f}-{zone_high:.8f}"
    )

    # --------------------------------------------------------
    # 11. Signal final
    # --------------------------------------------------------

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
        "timeframe": "D1 bias / H4 structure / H4 POI",
        "order_block_index": ob["index"],
        "bos_index": bos["index"],
        "bos_level": bos["broken_level"],
        "bos_age": bos["age"],
        "atr_h4": atr_value,
        "engulfing": _engulfing(h4_rows, direction),
        "liquidity_sweep": _liquidity_sweep(h4_rows, direction),
        "notes": (
            "Biais D1 et structure H4 alignes ; "
            "BOS avec displacement ; "
            "entree a l'ouverture de l'Order Block."
        ),
    }

    signals.append(signal)

    if isinstance(diagnostics, dict):
        diagnostics.setdefault(symbol, []).append(
            "Setup valide : BOS, Order Block et RR conformes."
        )

    elif isinstance(diagnostics, list):
        diagnostics.append(
            f"{symbol}: setup valide."
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

    rr_text = (
        f"1:{rr:.2f}"
        if rr is not None
        else "Indisponible"
    )

    return "\n".join([
        "TRADER AI PRO — SIGNAL SMC",
        "",
        f"Instrument : {symbol}",
        f"Direction : {direction_label}",
        "Biais : Daily (D1)",
        "Structure et Order Block : H4",
        "Méthode : Sniper Entry — ouverture de l'OB",
        "",
        f"Zone OB : {signal.get('zone_low')} - "
        f"{signal.get('zone_high')}",
        f"Entrée : {signal.get('entry')}",
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
        "Vérifier le signal avant toute décision de trading.",
    ])
