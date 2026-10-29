
"""TRADER AI PRO — Connexion publique aux marchés Deriv.

Récupère les bougies historiques et le prix courant des indices.
Ce module ne passe aucun ordre.
"""

from __future__ import annotations

import json
import math
import re
import time
from typing import Any

import websocket


URLS = [
    "wss://ws.derivws.com/websockets/v3?app_id=1089",
    "wss://ws.binaryws.com/websockets/v3?app_id=1089",
    "wss://api.derivws.com/trading/v1/options/ws/public",
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
    """Vérifie que le symbole est pris en charge."""
    return bool(
        isinstance(symbol, str)
        and VOLATILITY.fullmatch(symbol.strip())
    )


def _extract_error(response: dict[str, Any]) -> str:
    """Extrait un message d'erreur lisible."""
    error = response.get("error", {})

    if isinstance(error, dict):
        return str(error.get("message", error))

    return str(error)


def _request(
    payload: dict[str, Any],
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Envoie une requête WebSocket et essaie les endpoints disponibles."""

    errors: list[str] = []

    expected_keys = {
        "ticks": ("tick",),
        "ticks_history": ("history", "candles"),
        "active_symbols": ("active_symbols",),
    }

    request_type = next(
        (key for key in expected_keys if key in payload),
        None,
    )

    for url in URLS:
        ws = None

        try:
            print(f"[DERIV] Connexion : {url}")

            ws = websocket.create_connection(
                url,
                timeout=timeout,
                enable_multithread=True,
                origin="https://app.deriv.com",
            )

            ws.settimeout(timeout)
            ws.send(json.dumps(payload))

            deadline = time.monotonic() + timeout

            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                ws.settimeout(max(0.5, remaining))

                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    break

                if not raw:
                    continue

                try:
                    response = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                if not isinstance(response, dict):
                    continue

                if response.get("error"):
                    message = _extract_error(response)
                    errors.append(f"{url}: {message}")
                    print(f"[DERIV] Erreur API : {message}")
                    break

                if request_type:
                    if any(
                        key in response
                        for key in expected_keys[request_type]
                    ):
                        return response

                if response.get("msg_type") in (
                    "tick",
                    "ticks",
                    "candles",
                    "history",
                    "active_symbols",
                ):
                    return response

            else:
                errors.append(f"{url}: délai dépassé")
                print("[DERIV] Délai dépassé.")

        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            errors.append(f"{url}: {message}")
            print(f"[DERIV] Connexion échouée : {message}")

        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    summary = " | ".join(errors) or "Aucune réponse exploitable."

    print(f"[DERIV] Échec de toutes les connexions : {summary}")

    return {
        "error": {
            "message": summary,
        }
    }


def get_current_price(
    symbol: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> float | None:
    """Retourne le dernier prix reçu, ou None si indisponible.

    Il s'agit d'une cotation ponctuelle, pas d'un flux continu.
    """
    if not _valid_symbol(symbol):
        print(f"[DERIV] Symbole invalide : {symbol}")
        return None

    response = _request(
        {
            "ticks": symbol.strip(),
        },
        timeout=timeout,
    )

    if response.get("error"):
        return None

    tick = response.get("tick")

    if not isinstance(tick, dict):
        print(f"[DERIV] Réponse sans cotation pour {symbol}.")
        return None

    try:
        quote = float(tick["quote"])
    except (KeyError, TypeError, ValueError):
        print(f"[DERIV] Prix absent ou invalide pour {symbol}.")
        return None

    if not math.isfinite(quote) or quote <= 0:
        print(f"[DERIV] Prix non valide pour {symbol} : {quote}")
        return None

    print(f"[DERIV] Prix reçu — {symbol}: {quote}")
    return quote


def get_candles(
    symbol: str,
    timeframe: str,
    count: int = 50,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Récupère les bougies historiques clôturées d'un indice."""

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
            "ticks_history": symbol.strip(),
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "style": "candles",
        },
        timeout=timeout,
    )

    if response.get("error"):
        return {"error": _extract_error(response)}

    raw_candles = response.get("candles")

    if not isinstance(raw_candles, list):
        return {
            "error": f"Réponse Deriv sans liste de bougies valide pour {symbol}."
        }

    now = time.time()
    candles: list[dict[str, float | int]] = []
    seen: set[int] = set()

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

        if any(
            not math.isfinite(value) or value <= 0
            for value in values
        ):
            continue

        if candle["high"] < candle["low"]:
            continue

        if candle["high"] < max(candle["open"], candle["close"]):
            continue

        if candle["low"] > min(candle["open"], candle["close"]):
            continue

        # Ne conserve que les bougies entièrement clôturées.
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

    result = candles[-count:]

    print(
        f"[DERIV] {symbol} {timeframe} : "
        f"{len(result)} bougies récupérées."
    )

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(result),
        "candles": result,
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

    result: list[str] = []

    for item in symbols:
        if not isinstance(item, dict):
            continue

        symbol = item.get("symbol", "")

        if _valid_symbol(symbol):
            result.append(symbol)

    return sorted(set(result))
