
"""TRADER AI PRO — Stratégie SMC H4/H1.
Détection anticipée des POI et suivi indicatif des setups.
Aucun ordre n'est envoyé à Deriv.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any


MIN_RR = 1.0
MIN_CANDLES = 30


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


def _num(row: dict, *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            number = float(value)
            if isfinite(number):
                return number
        except (TypeError, ValueError):
            continue

    raise ValueError(f"Valeur OHLC manquante : {keys}")


def _normalize(rows: Any) -> list[dict]:
    """Normalise les bougies OHLC."""
    if not isinstance(rows, (list, tuple)):
        return []

    result = []

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue

        try:
            candle = {
                "o": _num(row, "o", "open"),
                "h": _num(row, "h", "high"),
                "l": _num(row, "l", "low"),
                "c": _num(row, "c", "close"),
                "epoch": row.get(
                    "epoch",
                    row.get("time", row.get("timestamp", index)),
                ),
            }

            if (
                candle["h"] >= candle["l"]
                and candle["h"] >= max(candle["o"], candle["c"])
                and candle["l"] <= min(candle["o"], candle["c"])
            ):
                result.append(candle)

        except (ValueError, TypeError):
            continue

    return result


def _pivots(
    rows: list[dict],
    radius: int = 2,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Identifie les sommets et creux locaux confirmés."""
    highs = []
    lows = []

    if len(rows) < radius * 2 + 1:
        return highs, lows

    for i in range(radius, len(rows) - radius):
        high = rows[i]["h"]
        low = rows[i]["l"]

        other_highs = [
            rows[j]["h"]
            for j in range(i - radius, i + radius + 1)
            if j != i
        ]
        other_lows = [
            rows[j]["l"]
            for j in range(i - radius, i + radius + 1)
            if j != i
        ]

        if all(high > value for value in other_highs):
            highs.append((i, high))

        if all(low < value for value in other_lows):
            lows.append((i, low))

    return highs, lows


def _structure(
    h4: list[dict],
) -> tuple[str, float | None, float | None]:
    """Détermine la structure de marché à partir des swings H4."""
    highs, lows = _pivots(h4, 2)

    last_high = highs[-1][1] if highs else None
    last_low = lows[-1][1] if lows else None

    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRE", last_high, last_low

    previous_high = highs[-2][1]
    previous_low = lows[-2][1]

    higher_high = last_high > previous_high
    higher_low = last_low > previous_low
    lower_high = last_high < previous_high
    lower_low = last_low < previous_low

    if higher_high and higher_low:
        return "HAUSSIERE", last_high, last_low

    if lower_high and lower_low:
        return "BAISSIERE", last_high, last_low

    last_close = h4[-1]["c"]

    if last_close > last_high and higher_low:
        return "HAUSSIERE", last_high, last_low

    if last_close < last_low and lower_high:
        return "BAISSIERE", last_high, last_low

    return "NEUTRE", last_high, last_low


def _ob_candidate(
    h1: list[dict],
    direction: str,
) -> tuple[float, float, int] | None:
    """Recherche un Order Block avant une cassure de structure H1."""
    if len(h1) < MIN_CANDLES:
        return None

    highs, lows = _pivots(h1[:-1], 2)
    total = len(h1)

    if direction == "BUY":
        pivots = [
            (index, level)
            for index, level in highs
            if index >= total - 35
        ]
    else:
        pivots = [
            (index, level)
            for index, level in lows
            if index >= total - 35
        ]

    for pivot_index, pivot_level in reversed(pivots):
        start = max(pivot_index + 1, total - 20)

        for impulse_index in range(total - 2, start - 1, -1):
            impulse = h1[impulse_index]

            if direction == "BUY":
                broke_structure = (
                    impulse["c"] > pivot_level
                    and impulse["c"] > impulse["o"]
                )
            else:
                broke_structure = (
                    impulse["c"] < pivot_level
                    and impulse["c"] < impulse["o"]
                )

            if not broke_structure:
                continue

            first_index = max(0, impulse_index - 5)

            for index in range(
                impulse_index - 1,
                first_index - 1,
                -1,
            ):
                candle = h1[index]

                if direction == "BUY":
                    opposite = candle["c"] < candle["o"]
                else:
                    opposite = candle["c"] > candle["o"]

                if opposite:
                    return candle["l"], candle["h"], index

    return None


def _is_invalidated(
    h1: list[dict],
    direction: str,
    zone_low: float,
    zone_high: float,
    ob_index: int,
) -> bool:
    """Invalide la zone si une clôture H1 la traverse."""
    for candle in h1[ob_index + 1:]:
        if direction == "BUY" and candle["c"] < zone_low:
            return True

        if direction == "SELL" and candle["c"] > zone_high:
            return True

    return False


def _liquidity_sweep(
    h1: list[dict],
    direction: str,
) -> bool:
    """Détecte un balayage de liquidité éventuel."""
    if len(h1) < 6:
        return False

    highs, lows = _pivots(h1[:-1], 2)
    last = h1[-1]

    if direction == "BUY" and lows:
        level = lows[-1][1]
        return last["l"] < level and last["c"] > level

    if direction == "SELL" and highs:
        level = highs[-1][1]
        return last["h"] > level and last["c"] < level

    return False


def _engulfing(h1: list[dict], direction: str) -> bool:
    """Détecte un englobement simple sur les deux dernières bougies."""
    if len(h1) < 2:
        return False

    previous = h1[-2]
    last = h1[-1]

    if direction == "BUY":
        return (
            previous["c"] < previous["o"]
            and last["c"] > last["o"]
            and last["o"] <= previous["c"]
            and last["c"] >= previous["o"]
        )

    return (
        previous["c"] > previous["o"]
        and last["c"] < last["o"]
        and last["o"] >= previous["c"]
        and last["c"] <= previous["o"]
    )


def find_signals(
    symbol: str,
    d1=None,
    h4=None,
    h1=None,
    m30=None,
    price_now=None,
    diagnostics: dict | None = None,
) -> list[dict]:
    """
    Retourne au maximum une POI SMC.

    États :
      POI_DETECTED : zone repérée, en attente d'un éventuel retour.
      PRICE_IN_ZONE : prix courant dans la zone.
      CONFIRMED : prix dans la zone avec englobement ou sweep.

    Un prix courant absent ne doit jamais être remplacé
    par la dernière clôture H1.
    """
    if diagnostics is not None:
        diagnostics.clear()
        diagnostics["reason"] = "Analyse non terminée"

    def reject(reason: str) -> list[dict]:
        if diagnostics is not None:
            diagnostics["reason"] = reason
        return []

    h4_rows = _normalize(h4)
    h1_rows = _normalize(h1)

    if len(h4_rows) < MIN_CANDLES:
        return reject(
            f"Données H4 insuffisantes : {len(h4_rows)} bougies valides"
        )

    if len(h1_rows) < MIN_CANDLES:
        return reject(
            f"Données H1 insuffisantes : {len(h1_rows)} bougies valides"
        )

    trend, h4_high, h4_low = _structure(h4_rows)

    if diagnostics is not None:
        diagnostics["structure"] = trend

    if trend not in ("HAUSSIERE", "BAISSIERE"):
        return reject("Structure H4 neutre ou contradictoire")

    direction = "BUY" if trend == "HAUSSIERE" else "SELL"
    ob = _ob_candidate(h1_rows, direction)

    if ob is None:
        return reject("Aucun Order Block H1 valide détecté")

    zone_low, zone_high, ob_index = ob

    if diagnostics is not None:
        diagnostics["order_block"] = {
            "low": zone_low,
            "high": zone_high,
            "index": ob_index,
        }

    if _is_invalidated(
        h1_rows,
        direction,
        zone_low,
        zone_high,
        ob_index,
    ):
        return reject("Order Block invalidé par une clôture H1")

    entry = (zone_low + zone_high) / 2.0
    stop_loss = zone_low if direction == "BUY" else zone_high
    risk = abs(entry - stop_loss)

    if risk <= 0:
        return reject("Risque nul : zone d'entrée invalide")

    highs, lows = _pivots(h1_rows[:-1], 2)

    if direction == "BUY":
        candidates = [
            level for _, level in highs
            if level > entry
        ]

        if h4_high is not None and h4_high > entry:
            candidates.append(h4_high)

        valid_targets = [
            level for level in set(candidates)
            if (level - entry) / risk >= MIN_RR
        ]

        take_profit = min(valid_targets) if valid_targets else None

    else:
        candidates = [
            level for _, level in lows
            if level < entry
        ]

        if h4_low is not None and h4_low < entry:
            candidates.append(h4_low)

        valid_targets = [
            level for level in set(candidates)
            if (entry - level) / risk >= MIN_RR
        ]

        take_profit = max(valid_targets) if valid_targets else None

    if take_profit is None:
        return reject("Aucune cible technique avec un RR minimum de 1:1")

    reward = abs(take_profit - entry)
    rr = reward / risk

    # Un prix manquant reste manquant : ne pas utiliser la clôture H1
    # comme substitut à une cotation courante.
    if price_now is None:
        price = None
    else:
        try:
            price = float(price_now)
        except (TypeError, ValueError):
            return reject("Prix actuel invalide")

        if not isfinite(price):
            return reject("Prix actuel non fini ou invalide")

    price_inside = (
        price is not None
        and zone_low <= price <= zone_high
    )

    sweep = _liquidity_sweep(h1_rows, direction)
    engulfing = _engulfing(h1_rows, direction)

    if price_inside and (sweep or engulfing):
        state = "CONFIRMED"
    elif price_inside:
        state = "PRICE_IN_ZONE"
    else:
        state = "POI_DETECTED"

    last = h1_rows[-1]
    epoch = h1_rows[ob_index].get("epoch", ob_index)

    signal_id = (
        f"{symbol}-{direction}-POI-{epoch}-"
        f"{zone_low:.8f}-{zone_high:.8f}"
    )

    signal = {
        "signal_id": signal_id,
        "symbol": symbol,
        "index_name": INDEX_NAMES.get(symbol, symbol),
        "direction": direction,
        "entry": entry,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr": rr,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "h4_structure": trend,
        "liquidity_sweep": sweep,
        "engulfing": engulfing,
        "status": state,
        "price_now": price,
        "price_inside_zone": price_inside,
        "candle_time": str(last.get("epoch", "")),
        "poi_epoch": str(epoch),
        "timeframe": "H4 structure / H1 POI",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
    }

    if diagnostics is not None:
        diagnostics["reason"] = f"POI détectée : {state}"

        if price is None:
            diagnostics["price_warning"] = (
                "Prix courant indisponible ; confirmation impossible"
            )

        diagnostics["direction"] = direction
        diagnostics["rr"] = round(rr, 3)
        diagnostics["status"] = state

    return [signal]


def format_message(signal: dict) -> str:
    """Formate une alerte POI destinée à Telegram."""
    direction = (
        "ACHAT (BUY)"
        if signal["direction"] == "BUY"
        else "VENTE (SELL)"
    )

    state = signal.get("status", "POI_DETECTED")

    labels = {
        "POI_DETECTED": "NOUVELLE POI SMC DÉTECTÉE",
        "PRICE_IN_ZONE": "PRIX DANS LA ZONE POI",
        "CONFIRMED": "SETUP AVEC CONFIRMATION TECHNIQUE",
        "INVALIDATED": "ZONE INVALIDÉE",
    }

    symbol = signal.get("symbol", "Inconnu")
    index_name = signal.get(
        "index_name",
        INDEX_NAMES.get(symbol, symbol),
    )

    price = signal.get("price_now")
    if price is None:
        price_text = "INDISPONIBLE — cotation non reçue"
    else:
        price_text = f"{price:.8f}"

    sweep = (
        "Oui"
        if signal.get("liquidity_sweep")
        else "Non détecté (facultatif)"
    )

    engulfing = (
        "Oui"
        if signal.get("engulfing")
        else "Non détecté"
    )

    return (
        "🔎 TRADER AI PRO — SMC H4/H1\n\n"
        f"{labels.get(state, state)}\n\n"
        f"Indice : {index_name}\n"
        f"Symbole Deriv : {symbol}\n"
        f"ID : {signal['signal_id']}\n"
        f"Direction : {direction}\n"
        f"Structure H4 : {signal['h4_structure']}\n"
        f"Zone POI H1 : {signal['zone_low']:.8f} – "
        f"{signal['zone_high']:.8f}\n"
        f"Entrée planifiée : {signal['entry']:.8f}\n"
        f"Prix observé : {price_text}\n"
        f"Stop-loss indicatif : {signal['stop_loss']:.8f}\n"
        f"Take-profit indicatif : {signal['take_profit']:.8f}\n"
        f"RR planifié : 1:{signal['rr']:.2f}\n"
        f"Englobement H1 : {engulfing}\n"
        f"Sweep de liquidité : {sweep}\n"
        f"Heure UTC : {signal['timestamp_utc']}\n\n"
        "⚠️ Une POI détectée n'est pas une entrée exécutée. "
        "Si le prix courant est indisponible, la confirmation "
        "du retour dans la zone n'est pas possible.\n"
        "Vérifie le graphique avant toute entrée. "
        "Compte démo uniquement. Aucun ordre automatique."
            )
                                       
