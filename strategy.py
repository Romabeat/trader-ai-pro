"""
Trader AI Pro - Strategie SMC D1/H4
------------------------------------
D1 : filtre directionnel
H4 : structure, BOS, displacement et Order Block
Entree : ouverture de la bougie de l'Order Block
RR minimum : 1.5

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

# Le prix doit rester du bon cote de l'entree en attente.
# BUY : prix actuel au-dessus de l'entree.
# SELL : prix actuel en dessous de l'entree.


# ============================================================
# NORMALISATION DES BOUGIES
# ============================================================

def _number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _first_value(row, keys):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _normalize(candles):
    """
    Accepte notamment les formats :
    open/high/low/close
    o/h/l/c
    OHLC issus d'API de marche.

    Retourne une liste de bougies normalisees.
    """
    result = []

    if not isinstance(candles, (list, tuple)):
        return result

    for row in candles:
        if not isinstance(row, dict):
            continue

        o = _number(_first_value(row, ("open", "o", "Open")))
        h = _number(_first_value(row, ("high", "h", "High")))
        l = _number(_first_value(row, ("low", "l", "Low")))
        c = _number(_first_value(row, ("close", "c", "Close")))

        if None in (o, h, l, c):
            continue

        if h < l or h < max(o, c) or l > min(o, c):
            continue

        epoch = _first_value(
            row,
            ("epoch", "time", "timestamp", "datetime")
        )

        result.append({
            "o": o,
            "h": h,
            "l": l,
            "c": c,
            "epoch": epoch,
        })

    # Les donnees doivent etre chronologiques.
    # On ne les inverse pas automatiquement : le module de marche
    # doit fournir les bougies de la plus ancienne a la plus recente.
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
        previous_close = rows[i - 1]["c"]
        ranges.append(_true_range(rows[i], previous_close))

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
    """
    Identifie les pivots locaux.

    Un pivot n'est confirme qu'apres la cloture des bougies
    situees a sa droite.
    """
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
    Determine une structure haussiere, baissiere ou neutre
    a partir des deux derniers pivots hauts et bas confirmes.
    """
    highs, lows = _pivots(rows)

    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"

    previous_high = highs[-2][1]
    latest_high = highs[-1][1]

    previous_low = lows[-2][1]
    latest_low = lows[-1][1]

    higher_high = latest_high > previous_high
    higher_low = latest_low > previous_low

    lower_high = latest_high < previous_high
    lower_low = latest_low < previous_low

    if higher_high and higher_low:
        return "BULLISH"

    if lower_high and lower_low:
        return "BEARISH"

    return "NEUTRAL"


def _daily_bias(d1):
    """
    Le Daily doit presenter une structure identifiable.
    En cas de structure neutre, aucun signal n'est autorise.
    """
    return _structure(d1)


# ============================================================
# RECHERCHE DE BOS ET D'ORDER BLOCK
# ============================================================

def _find_bos(rows, direction, atr_value):
    """
    Recherche une cassure de structure accompagnee d'une bougie
    impulsive.

    La cassure est comparee aux pivots confirmes AVANT la bougie
    de cassure, afin d'eviter d'utiliser des informations futures.
    """
    start = max(PIVOT_RADIUS * 2 + 1, len(rows) - OB_LOOKBACK)

    for i in range(len(rows) - 1, start - 1, -1):
        candle = rows[i]

        # La bougie doit montrer un deplacement directionnel.
        if direction == "BUY":
            if not _is_bullish(candle):
                continue
        else:
            if not _is_bearish(candle):
                continue

        if _body_ratio(candle) < MIN_BODY_RATIO:
            continue

        body = abs(candle["c"] - candle["o"])

        if body < MIN_DISPLACEMENT_ATR * atr_value:
            continue

        # Les pivots sont calcules uniquement avec les bougies
        # precedant la bougie de cassure.
        previous_rows = rows[:i]
        highs, lows = _pivots(previous_rows)

        if direction == "BUY":
            candidates = [
                (index, level)
                for index, level in highs
                if index < i and candle["c"] > level
            ]
        else:
            candidates = [
                (index, level)
                for index, level in lows
                if index < i and candle["c"] < level
            ]

        if not candidates:
            continue

        # Le pivot casse le plus recent est privilegie.
        broken_pivot_index, broken_level = candidates[-1]

        return {
            "index": i,
            "broken_level": broken_level,
            "pivot_index": broken_pivot_index,
            "impulse": candle,
        }

    return None


def _find_order_block(rows, bos, direction):
    """
    Recherche la derniere bougie opposee precedant l'impulsion
    ayant casse la structure.

    BUY  : derniere bougie baissiere.
    SELL : derniere bougie haussiere.

    La bougie de l'Order Block est identifiee par son ouverture,
    son plus haut et son plus bas.
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
    Invalidation conservatrice :
    une cloture ulterieure a l'Order Block au-dela de la zone
    rend la configuration inutilisable.
    """
    candle_index = ob["index"]

    for candle in rows[candle_index + 1:]:
        if direction == "BUY" and candle["c"] < ob["zone_low"]:
            return True

        if direction == "SELL" and candle["c"] > ob["zone_high"]:
            return True

    return False


# ============================================================
# LIQUIDITE ET ENGLOBEMENT
# ============================================================

def _liquidity_sweep(rows, direction, lookback=20):
    """
    Detection simple d'une prise de liquidite sur les bougies
    recentes. Cette information reste un filtre secondaire.
    """
    if len(rows) < lookback + 2:
        return False

    previous = rows[-lookback - 1:-1]
    latest = rows[-1]

    if direction == "BUY":
        previous_low = min(c["l"] for c in previous)
        return latest["l"] < previous_low and latest["c"] > previous_low

    previous_high = max(c["h"] for c in previous)
    return latest["h"] > previous_high and latest["c"] < previous_high


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
# OBJECTIF STRUCTUREL ET GESTION DU RISQUE
# ============================================================

def _target_from_structure(rows, direction, entry, stop_loss):
    """
    Recherche un pivot H4 dans le sens du trade.

    Le premier objectif structurel valide doit egalement offrir
    un RR d'au moins MIN_RR.
    """
    highs, lows = _pivots(rows)

    risk = abs(entry - stop_loss)

    if risk <= 0:
        return None, None

    if direction == "BUY":
        candidates = sorted(
            {
                level
                for _, level in highs
                if level > entry
            }
        )

        for target in candidates:
            reward = target - entry
            rr = reward / risk

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
            reward = entry - target
            rr = reward / risk

            if rr >= MIN_RR:
                return target, rr

    return None, None


# ============================================================
# CONSTRUCTION DU SIGNAL
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
    API conservee pour rester compatible avec le scanner.

    Parametres principaux :
        d1 : 100 bougies Daily
        h4 : 200 bougies H4
        price_now : dernier prix disponible

    h1 et m30 sont conserves pour compatibilite, mais ne sont
    pas utilises par cette strategie D1/H4.
    """
    signals = []

    def reject(reason):
        if isinstance(diagnostics, list):
            diagnostics.append(f"{symbol}: {reason}")

    d1_rows = _normalize(d1)
    h4_rows = _normalize(h4)

    if len(d1_rows) < MIN_D1_CANDLES:
        reject(
            f"Historique D1 insuffisant : {len(d1_rows)}/"
            f"{MIN_D1_CANDLES} bougies."
        )
        return signals

    if len(h4_rows) < MIN_H4_CANDLES:
        reject(
            f"Historique H4 insuffisant : {len(h4_rows)}/"
            f"{MIN_H4_CANDLES} bougies."
        )
        return signals

    # --------------------------------------------------------
    # 1. Biais Daily
    # --------------------------------------------------------

    bias = _daily_bias(d1_rows)

    if bias == "NEUTRAL":
        reject("Structure Daily neutre ou insuffisamment claire.")
        return signals

    direction = "BUY" if bias == "BULLISH" else "SELL"

    # --------------------------------------------------------
    # 2. Volatilite H4
    # --------------------------------------------------------

    atr_value = _atr(h4_rows)

    if atr_value is None:
        reject("ATR H4 indisponible.")
        return signals

    # --------------------------------------------------------
    # 3. Structure H4 et BOS
    # --------------------------------------------------------

    h4_structure = _structure(h4_rows)

    if h4_structure != bias:
        reject(
            "Desaccord entre le biais Daily et la structure H4."
        )
        return signals

    bos = _find_bos(h4_rows, direction, atr_value)

    if bos is None:
        reject("Aucun BOS H4 accompagne d'un deplacement valide.")
        return signals

    # --------------------------------------------------------
    # 4. Order Block H4
    # --------------------------------------------------------

    ob = _find_order_block(h4_rows, bos, direction)

    if ob is None:
        reject("Aucun Order Block valide avant le BOS.")
        return signals

    if _is_invalidated(h4_rows, ob, direction):
        reject("Order Block H4 deja invalide.")
        return signals

    zone_low = ob["zone_low"]
    zone_high = ob["zone_high"]
    entry = ob["entry"]

    if zone_high <= zone_low:
        reject("Dimensions de l'Order Block invalides.")
        return signals

    # --------------------------------------------------------
    # 5. Verification du prix actuel
    # --------------------------------------------------------

    current_price = _number(price_now)

    if current_price is None or current_price <= 0:
        reject("Prix actuel indisponible : entree non validee.")
        return signals

    # Refuser une entree deja depassee.
    if direction == "BUY" and current_price <= entry:
        reject("Entree BUY deja atteinte ou depassee.")
        return signals

    if direction == "SELL" and current_price >= entry:
        reject("Entree SELL deja atteinte ou depassee.")
        return signals

    # --------------------------------------------------------
    # 6. Stop Loss avec marge ATR
    # --------------------------------------------------------

    buffer = atr_value * SL_ATR_BUFFER

    if direction == "BUY":
        stop_loss = zone_low - buffer
    else:
        stop_loss = zone_high + buffer

    risk = abs(entry - stop_loss)

    if risk <= 0:
        reject("Risque nul ou invalide.")
        return signals

    # --------------------------------------------------------
    # 7. Take Profit structurel et RR
    # --------------------------------------------------------

    take_profit, rr = _target_from_structure(
        h4_rows,
        direction,
        entry,
        stop_loss,
    )

    if take_profit is None or rr is None:
        reject("Aucun objectif structurel ne respecte le RR minimum.")
        return signals

    if rr < MIN_RR:
        reject(f"RR insuffisant : {rr:.2f}.")
        return signals

    # --------------------------------------------------------
    # 8. Identifiant de signal
    # --------------------------------------------------------

    epoch = ob["candle"].get("epoch")

    if epoch is None:
        epoch = bos["index"]

    safe_epoch = str(epoch).replace(" ", "_").replace(":", "-")

    signal_id = (
        f"{symbol}-{direction}-D1H4-POI-{safe_epoch}-"
        f"{zone_low:.8f}-{zone_high:.8f}"
    )

    # --------------------------------------------------------
    # 9. Signal final
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
        "atr_h4": atr_value,
        "engulfing": _engulfing(h4_rows, direction),
        "liquidity_sweep": _liquidity_sweep(h4_rows, direction),
        "notes": (
            "Order Block H4 identifie avant le BOS ; "
            "entree a l'ouverture de la bougie OB ; "
            "biais Daily et structure H4 alignes."
        ),
    }

    signals.append(signal)
    return signals


# ============================================================
# FORMATAGE DES ALERTES
# ============================================================

def format_message(signal):
    """
    Formate un signal pour Telegram ou les journaux.
    """
    direction = signal.get("direction", "UNKNOWN")
    symbol = signal.get("symbol", "UNKNOWN")

    direction_label = {
        "BUY": "ACHAT",
        "SELL": "VENTE",
    }.get(direction, direction)

    entry = signal.get("entry")
    stop_loss = signal.get("stop_loss")
    take_profit = signal.get("take_profit")
    rr = signal.get("rr")

    lines = [
        "TRADER AI PRO — SIGNAL SMC",
        "",
        f"Instrument : {symbol}",
        f"Direction : {direction_label}",
        "Analyse : Daily (D1)",
        "Structure et Order Block : H4",
        "Methode : Sniper Entry — ouverture de l'OB",
        "",
        f"Zone OB : {signal.get('zone_low')} - "
        f"{signal.get('zone_high')}",
        f"Entree : {entry}",
        f"Stop Loss : {stop_loss}",
        f"Take Profit : {take_profit}",
        f"RR estime : 1:{rr:.2f}" if isinstance(rr, (int, float))
        else f"RR estime : {rr}",
        f"Prix observe : {signal.get('current_price')}",
        "",
        f"Biais D1 : {signal.get('d1_bias')}",
        f"Structure H4 : {signal.get('h4_structure')}",
        f"BOS : {signal.get('bos_level')}",
        f"ATR H4 : {signal.get('atr_h4')}",
        f"Englobement H4 : {'Oui' if signal.get('engulfing') else 'Non'}",
        f"Prise de liquidite : {'Oui' if signal.get('liquidity_sweep') else 'Non'}",
        "",
        f"Note : {signal.get('notes', '')}",
        "",
        "Scanner uniquement : aucun ordre automatique execute.",
        "Signal a verifier avant toute decision de trading.",
    ]

    return "\n".join(lines)
