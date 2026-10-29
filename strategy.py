"""TRADER AI PRO — Strategie SMC H4/H1.
Signaux indicatifs uniquement. Aucun ordre n'est envoyé à Deriv.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any


MIN_RR = 1.0
MIN_CANDLES = 30


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
    """Normalise les bougies et élimine les données incohérentes."""
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

            valid = (
                candle["h"] >= candle["l"]
                and candle["h"] >= max(candle["o"], candle["c"])
                and candle["l"] <= min(candle["o"], candle["c"])
            )

            if valid:
                result.append(candle)

        except (ValueError, TypeError):
            continue

    return result


def _pivots(
    rows: list[dict],
    radius: int = 2,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Détecte les sommets et creux locaux confirmés."""
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
    """Détermine la tendance à partir des swings H4."""
    highs, lows = _pivots(h4, 2)

    if len(highs) < 2 or len(lows) < 2:
        return (
            "NEUTRE",
            highs[-1][1] if highs else None,
            lows[-1][1] if lows else None,
        )

    previous_high = highs[-2][1]
    last_high = highs[-1][1]
    previous_low = lows[-2][1]
    last_low = lows[-1][1]
    last_close = h4[-1]["c"]

    higher_high = last_high > previous_high
    higher_low = last_low > previous_low
    lower_high = last_high < previous_high
    lower_low = last_low < previous_low

    if higher_high and higher_low:
        return "HAUSSIERE", last_high, last_low

    if lower_high and lower_low:
        return "BAISSIERE", last_high, last_low

    # Une cassure seule ne suffit pas à confirmer une tendance.
    if last_close > last_high and higher_low:
        return "HAUSSIERE", last_high, last_low

    if last_close < last_low and lower_high:
        return "BAISSIERE", last_high, last_low

    return "NEUTRE", last_high, last_low


def _ob_candidate(
    h1: list[dict],
    direction: str,
) -> tuple[float, float, int] | None:
    """
    Recherche un Order Block potentiel.

    BUY : dernière bougie baissière avant une impulsion haussière
    qui casse un sommet confirmé.

    SELL : dernière bougie haussière avant une impulsion baissière
    qui casse un creux confirmé.

    Recherche élargie aux pivots récents et aux impulsions récentes.
    La validité de la zone doit ensuite être confirmée par le prix.
    """
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

    # Examiner les pivots les plus récents en premier.
    for pivot_index, pivot_level in reversed(pivots):

        start = max(pivot_index + 1, total - 20)

        # La dernière bougie est réservée à la vérification du retour.
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

            # Recherche de la bougie opposée précédant l'impulsion.
            first_index = max(0, impulse_index - 5)

            for index in range(impulse_index - 1, first_index - 1, -1):
                candle = h1[index]

                if direction == "BUY":
                    opposite_candle = candle["c"] < candle["o"]
                else:
                    opposite_candle = candle["c"] > candle["o"]

                if opposite_candle:
                    return (
                        candle["l"],
                        candle["h"],
                        index,
                    )

    return None


def _liquidity_sweep(
    h1: list[dict],
    direction: str,
) -> bool:
    """Détecte un éventuel balayage de liquidité sur la dernière bougie."""
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
    Retourne au maximum un signal SMC.

    diagnostics, s'il est fourni, reçoit :
    - reason : résultat ou motif de rejet ;
    - structure : structure H4 observée ;
    - order_block : zone détectée, si disponible ;
    - rr : ratio risque/rendement calculé, si disponible.

    Le balayage de liquidité est une confluence facultative.
    Le RR minimal reste fixé à 1:1.
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
        return reject(
            "Structure H4 neutre : swings insuffisants ou contradictoires"
        )

    direction = "BUY" if trend == "HAUSSIERE" else "SELL"

    ob = _ob_candidate(h1_rows, direction)

    if ob is None:
        return reject(
            f"Structure H4 {trend}, mais aucun Order Block H1 "
            "correspondant détecté dans la fenêtre étudiée"
        )

    zone_low, zone_high, ob_index = ob

    if diagnostics is not None:
        diagnostics["order_block"] = {
            "low": zone_low,
            "high": zone_high,
            "index": ob_index,
        }

    last = h1_rows[-1]

    try:
        price = (
            float(price_now)
            if price_now is not None
            else last["c"]
        )
    except (TypeError, ValueError):
        return reject("Prix actuel invalide")

    if not isfinite(price):
        return reject("Prix actuel non fini ou invalide")

    overlaps = (
        last["l"] <= zone_high
        and last["h"] >= zone_low
    )
    price_inside = zone_low <= price <= zone_high

    if not overlaps:
        return reject(
            "Order Block détecté, mais la dernière bougie "
            "ne touche pas la zone"
        )

    if not price_inside:
        return reject(
            "La dernière bougie touche la zone, mais le prix "
            "d'entrée indicatif est en dehors de l'Order Block"
        )

    highs, lows = _pivots(h1_rows[:-1], 2)

    if direction == "BUY":
        targets = [
            level for _, level in highs
            if level > price
        ]

        take_profit = (
            min(targets)
            if targets
            else (
                h4_high
                if h4_high is not None and h4_high > price
                else None
            )
        )
        stop_loss = zone_low

    else:
        targets = [
            level for _, level in lows
            if level < price
        ]

        take_profit = (
            max(targets)
            if targets
            else (
                h4_low
                if h4_low is not None and h4_low < price
                else None
            )
        )
        stop_loss = zone_high

    if take_profit is None:
        return reject(
            "Aucune cible technique exploitable trouvée"
        )

    if direction == "BUY":
        valid_levels = stop_loss < price < take_profit
    else:
        valid_levels = take_profit < price < stop_loss

    if not valid_levels:
        return reject(
            "Entrée, stop-loss et take-profit mal ordonnés"
        )

    risk = abs(price - stop_loss)
    reward = abs(take_profit - price)

    if risk <= 0 or reward <= 0:
        return reject(
            "Risque ou récompense nul : niveaux invalides"
        )

    rr = reward / risk

    if diagnostics is not None:
        diagnostics["rr"] = round(rr, 3)

    if rr < MIN_RR:
        return reject(
            f"RR insuffisant : {rr:.2f}, minimum requis : "
            f"{MIN_RR:.2f}"
        )

    sweep = _liquidity_sweep(h1_rows, direction)
    epoch = last.get("epoch")

    signal_id = (
        f"{symbol}-{direction}-{epoch}-"
        f"{price:.8f}-{zone_low:.8f}-{zone_high:.8f}"
    )

    signal = {
        "signal_id": signal_id,
        "symbol": symbol,
        "direction": direction,
        "entry": price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "rr": rr,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "h4_structure": trend,
        "liquidity_sweep": sweep,
        "candle_time": str(epoch),
        "timeframe": "H4 structure / H1 entrée",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
    }

    if diagnostics is not None:
        diagnostics["reason"] = "Signal confirmé"
        diagnostics["direction"] = direction

    return [signal]


def format_message(signal: dict) -> str:
    """Formate un signal pour une lecture humaine."""
    direction = (
        "ACHAT (BUY)"
        if signal["direction"] == "BUY"
        else "VENTE (SELL)"
    )

    sweep = (
        "Oui — confluence présente"
        if signal.get("liquidity_sweep")
        else "Non détecté"
    )

    return (
        "📊 TRADER AI PRO — SIGNAL SMC\n\n"
        f"ID: {signal['signal_id']}\n"
        f"Actif: {signal['symbol']}\n"
        f"Direction: {direction}\n"
        f"Entrée indicative: {signal['entry']:.8f}\n"
        f"Order Block H1: {signal['zone_low']:.8f} – "
        f"{signal['zone_high']:.8f}\n"
        f"Stop-loss indicatif: {signal['stop_loss']:.8f}\n"
        f"Take-profit indicatif: {signal['take_profit']:.8f}\n"
        f"RR estimé: 1:{signal['rr']:.2f}\n"
        f"Structure H4: {signal['h4_structure']}\n"
        f"Balayage de liquidité: {sweep}\n"
        f"Heure UTC: {signal['timestamp_utc']}\n\n"
        "⚠️ Signal indicatif, non garanti. Vérifie le graphique "
        "avant toute entrée. Exécution manuelle uniquement "
        "sur compte démo. Aucun ordre automatique."
)
