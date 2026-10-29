"""TRADER AI PRO — SMC indicatif, H4 structure + H1 entry.
Aucun ordre n'est envoyé à Deriv. Ce module ne fait que détecter et formater des signaux.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any


def _num(row: dict, *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is not None:
            try:
                value = float(value)
                if isfinite(value):
                    return value
            except (TypeError, ValueError):
                pass
    raise ValueError(f"Valeur OHLC manquante: {keys}")


def _normalize(rows: Any) -> list[dict]:
    if not isinstance(rows, (list, tuple)):
        return []
    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        try:
            candle = {
                "o": _num(row, "o", "open"),
                "h": _num(row, "h", "high"),
                "l": _num(row, "l", "low"),
                "c": _num(row, "c", "close"),
                "epoch": row.get("epoch", row.get("time", row.get("timestamp", i))),
            }
            if candle["h"] >= candle["l"] and candle["h"] >= max(candle["o"], candle["c"]) and candle["l"] <= min(candle["o"], candle["c"]):
                out.append(candle)
        except ValueError:
            continue
    return out


def _pivots(rows: list[dict], radius: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs, lows = [], []
    for i in range(radius, len(rows) - radius):
        h, lo = rows[i]["h"], rows[i]["l"]
        if all(h > rows[j]["h"] for j in range(i-radius, i+radius+1) if j != i):
            highs.append((i, h))
        if all(lo < rows[j]["l"] for j in range(i-radius, i+radius+1) if j != i):
            lows.append((i, lo))
    return highs, lows


def _structure(h4: list[dict]) -> tuple[str, float | None, float | None]:
    highs, lows = _pivots(h4, 2)
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRE", highs[-1][1] if highs else None, lows[-1][1] if lows else None
    close = h4[-1]["c"]
    last_high, last_low = highs[-1][1], lows[-1][1]
    if close > last_high and highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1]:
        return "HAUSSIERE", last_high, last_low
    if close < last_low and highs[-1][1] < highs[-2][1] and lows[-1][1] < lows[-2][1]:
        return "BAISSIERE", last_high, last_low
    # Structure progressive sans cassure récente : direction de swing, mais moins forte.
    if highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1]:
        return "HAUSSIERE", last_high, last_low
    if highs[-1][1] < highs[-2][1] and lows[-1][1] < lows[-2][1]:
        return "BAISSIERE", last_high, last_low
    return "NEUTRE", last_high, last_low


def _ob_candidate(h1: list[dict], direction: str) -> tuple[float, float, int] | None:
    """Repère une bougie opposée précédant une impulsion qui casse un pivot récent."""
    if len(h1) < 25:
        return None
    highs, lows = _pivots(h1[:-1], 2)
    if direction == "BUY":
        candidates = [(i, p) for i, p in highs if i >= len(h1) - 18]
        if not candidates:
            return None
        pivot_i, pivot = candidates[-1]
        for impulse_i in range(max(pivot_i + 1, len(h1) - 8), len(h1)):
            candle = h1[impulse_i]
            prior = h1[impulse_i - 1]
            if candle["c"] > pivot and candle["c"] > candle["o"]:
                for j in range(impulse_i - 1, max(-1, impulse_i - 6), -1):
                    if h1[j]["c"] < h1[j]["o"]:
                        return h1[j]["l"], h1[j]["h"], j
    else:
        candidates = [(i, p) for i, p in lows if i >= len(h1) - 18]
        if not candidates:
            return None
        pivot_i, pivot = candidates[-1]
        for impulse_i in range(max(pivot_i + 1, len(h1) - 8), len(h1)):
            candle = h1[impulse_i]
            if candle["c"] < pivot and candle["c"] < candle["o"]:
                for j in range(impulse_i - 1, max(-1, impulse_i - 6), -1):
                    if h1[j]["c"] > h1[j]["o"]:
                        return h1[j]["l"], h1[j]["h"], j
    return None


def _liquidity_sweep(h1: list[dict], direction: str) -> bool:
    highs, lows = _pivots(h1[:-1], 2)
    last = h1[-1]
    if direction == "BUY" and lows:
        level = lows[-1][1]
        return last["l"] < level and last["c"] > level
    if direction == "SELL" and highs:
        level = highs[-1][1]
        return last["h"] > level and last["c"] < level
    return False


def find_signals(symbol: str, d1=None, h4=None, h1=None, m30=None, price_now=None) -> list[dict]:
    """Retourne une liste vide ou un seul signal confirmé par structure H4 et retour dans OB H1."""
    h4_rows, h1_rows = _normalize(h4), _normalize(h1)
    if len(h4_rows) < 30 or len(h1_rows) < 30:
        return []
    trend, h4_high, h4_low = _structure(h4_rows)
    if trend not in ("HAUSSIERE", "BAISSIERE"):
        return []
    direction = "BUY" if trend == "HAUSSIERE" else "SELL"
    ob = _ob_candidate(h1_rows, direction)
    if not ob:
        return []
    zone_low, zone_high, ob_index = ob
    last = h1_rows[-1]
    price = float(price_now) if price_now is not None else last["c"]
    # Signal uniquement au retour réel dans la zone de l'OB.
    overlaps = last["l"] <= zone_high and last["h"] >= zone_low
    price_inside = zone_low <= price <= zone_high
    if not overlaps or not price_inside:
        return []

    highs, lows = _pivots(h1_rows[:-1], 2)
    if direction == "BUY":
        targets = [p for _, p in highs if p > price]
        tp = min(targets) if targets else (h4_high if h4_high and h4_high > price else None)
        sl = zone_low
    else:
        targets = [p for _, p in lows if p < price]
        tp = max(targets) if targets else (h4_low if h4_low and h4_low < price else None)
        sl = zone_high
    if tp is None or (direction == "BUY" and not (sl < price < tp)) or (direction == "SELL" and not (tp < price < sl)):
        return []
    risk = abs(price - sl)
    reward = abs(tp - price)
    if risk <= 0 or reward <= 0:
        return []
    # Filtre anti-bruit : cible au moins aussi éloignée que le stop.
    rr = reward / risk
    if rr < 1.0:
        return []
    sweep = _liquidity_sweep(h1_rows, direction)
    epoch = last.get("epoch")
    signal_id = f"{symbol}-{direction}-{epoch}-{price:.8f}-{zone_low:.8f}-{zone_high:.8f}"
    return [{
        "signal_id": signal_id,
        "symbol": symbol,
        "direction": direction,
        "entry": price,
        "stop_loss": sl,
        "take_profit": tp,
        "rr": rr,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "h4_structure": trend,
        "liquidity_sweep": sweep,
        "candle_time": str(epoch),
        "timeframe": "H4 structure / H1 entrée",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }]


def format_message(signal: dict) -> str:
    direction = "ACHAT (BUY)" if signal["direction"] == "BUY" else "VENTE (SELL)"
    sweep = "Oui — confluence présente" if signal.get("liquidity_sweep") else "Non détecté"
    return (
        "📊 TRADER AI PRO — SIGNAL SMC\n\n"
        f"ID: {signal['signal_id']}\n"
        f"Actif: {signal['symbol']}\n"
        f"Direction: {direction}\n"
        f"Entrée indicative: {signal['entry']:.8f}\n"
        f"Order Block H1: {signal['zone_low']:.8f} – {signal['zone_high']:.8f}\n"
        f"Stop-loss indicatif: {signal['stop_loss']:.8f}\n"
        f"Take-profit (liquidité/structure opposée): {signal['take_profit']:.8f}\n"
        f"RR estimé: 1:{signal['rr']:.2f}\n"
        f"Structure H4: {signal['h4_structure']}\n"
        f"Balayage de liquidité: {sweep}\n"
        f"Heure UTC: {signal['timestamp_utc']}\n\n"
        "⚠️ Signal indicatif, non garanti. Vérifie le graphique avant toute entrée. "
        "Exécution manuelle uniquement sur compte démo. Aucun ordre automatique."
                )
