"""TRADER AI PRO — Connexion publique aux marchés Deriv.

Récupère les bougies historiques et le prix courant des indices.
Ce module ne passe aucun ordre.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import websocket


URLS = [
    "wss://api.derivws.com/trading/v1/options/ws/public",
    "wss://ws.derivws.com/websockets/v3?app_id=1089",
    "wss://ws.binaryws.com/websockets/v3?app_id=1089",
]

VOLATILITY = re.compile(r"^(R_\d+|1HZ\d+V)$")

GRANULARITY = {
    "M30": 1800,
    "H1": 3600,
    "H2": 7200,
    "H4": 14400,
    "D1": 86400,
}

MAX_CANDLES = 5000
DEFAULT_TIMEOUT = 10


def _valid_symbol(symbol: str) -> bool:
    """Vérifie que le symbole correspond à un indice synthétique pris en charge."""
    return bool(
        isinstance(symbol, str)
        and VOLATILITY.fullmatch(symbol.strip())
    )


def _request(
    payload: dict,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Envoie une requête WebSocket et essaie les endpoints disponibles."""
    errors = []

    for url in URLS:
        ws = None

        try:
            ws = websocket.create_connection(
                url,
                timeout=timeout,
                enable_multithread=True,
            )

            ws.send(json.dumps(payload))
            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                ws.settimeout(max(0.5, deadline - time.monotonic()))
                raw = ws.recv()

                if not raw:
                    continue

                try:
                    response = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if not isinstance(response, dict):
                    continue

                if response.get("error"):
                    error = response["error"]
                    message = (
                        error.get("message", str(error))
                        if isinstance(error, dict)
                        else str(error)
                    )
                    errors.append(f"{url}: {message}")
                    break

                # Une réponse Deriv utile contient normalement le type
                # demandé, ou un objet "error" traité ci-dessus.
                expected = (
                    "ticks_history" in payload
                    or "ticks" in payload
                    or "active_symbols" in payload
                )

                if expected and any(
                    key in response
                    for key in (
                        "history",
                        "candles",
                        "tick",
                        "active_symbols",
                    )
                ):
                    return response

                if response.get("msg_type") in (
                    "ticks",
                    "candles",
                    "history",
                    "active_symbols",
                ):
                    return response

            errors.append(f"{url}: aucune réponse exploitable")

        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")

        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    return {
        "error": {
            "message": "Échec des endpoints Deriv : " + " ; ".join(errors)
        }
    }


def get_current_price(
    symbol: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> float | None:
    """Retourne le dernier prix coté par Deriv, ou None en cas d'échec.

    Ce prix est une observation ponctuelle, pas un flux temps réel continu.
    """
    if not _valid_symbol(symbol):
        return None

    response = _request(
        {
            "ticks": symbol,
            "subscribe": 0,
        },
        timeout=timeout,
    )

    if response.get("error"):
        return None

    tick = response.get("tick")

    if not isinstance(tick, dict):
        return None

    try:
        quote = float(tick["quote"])
    except (KeyError, TypeError, ValueError):
        return None

    if quote <= 0:
        return None

    return quote


def get_candles(
    symbol: str,
    timeframe: str,
    count: int = 50,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Récupère les bougies historiques clôturées d'un indice synthétique."""
    timeframe = str(timeframe).upper()

    if not _valid_symbol(symbol):
        return {"error": f"Symbole non pris en charge : {symbol}"}

    if timeframe not in GRANULARITY:
        return {"error": f"Timeframe non pris en charge : {timeframe}"}

    try:
        count = int(count)
    except (TypeError, ValueError):
        return {"error": "Le nombre de bougies doit être un entier."}

    if count < 1:
        return {"error": "Le nombre de bougies doit être positif."}

    count = min(count, MAX_CANDLES)
    granularity = GRANULARITY[timeframe]

    response = _request(
        {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "style": "candles",
        },
        timeout=timeout,
    )

    if response.get("error"):
        return {
            "error": response["error"].get(
                "message",
                "Erreur inconnue de l'API Deriv",
            )
        }

    raw_candles = response.get("candles")

    if not isinstance(raw_candles, list):
        return {"error": "Réponse Deriv sans liste de bougies valide."}

    now = time.time()
    candles = []
    seen = set()

    for item in raw_candles:
        if not isinstance(item, dict):
            continue

        try:
            epoch = int(item["epoch"])
            candle = {
                "epoch": epoch,
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
            }
        except (KeyError, TypeError, ValueError):
            continue

        if epoch in seen:
            continue

        seen.add(epoch)

        values = [
            candle["open"],
            candle["high"],
            candle["low"],
            candle["close"],
        ]

        if any(value <= 0 for value in values):
            continue

        if candle["high"] < candle["low"]:
            continue

        if candle["high"] < max(candle["open"], candle["close"]):
            continue

        if candle["low"] > min(candle["open"], candle["close"]):
            continue

        # Exclure la bougie encore en formation.
        if epoch + granularity > now:
            continue

        candles.append(candle)

    candles.sort(key=lambda item: item["epoch"])

    if not candles:
        return {
            "error": (
                f"Aucune bougie clôturée disponible pour "
                f"{symbol} en {timeframe}."
            )
        }

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles[-count:],
    }


def get_synthetic_symbols(
    timeout: int = DEFAULT_TIMEOUT,
) -> list[str]:
    """Retourne les symboles synthétiques reconnus par le scanner."""
    response = _request(
        {
            "active_symbols": "brief",
            "product_type": "basic",
        },
        timeout=timeout,
    )

    if response.get("error"):
        return []

    symbols = response.get("active_symbols", [])

    if not isinstance(symbols, list):
        return []

    result = []

    for item in symbols:
        if not isinstance(item, dict):
            continue

        symbol = item.get("symbol", "")

        if _valid_symbol(symbol):
            result.append(symbol)

    return sorted(set(result))
