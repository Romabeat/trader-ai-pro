
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


# Priorité à l'API WebSocket v3 pour ticks et bougies historiques.
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
    """Vérifie le format du symbole synthétique."""
    return bool(
        isinstance(symbol, str)
        and VOLATILITY.fullmatch(symbol.strip())
    )


def _request(
    payload: dict[str, Any],
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Essaie les endpoints WebSocket et retourne une réponse exploitable."""
    errors: list[str] = []

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
                    error = response["error"]
                    if isinstance(error, dict):
                        message = error.get(
                            "message",
                            str(error),
                        )
                        code = error.get("code", "")
                        detail = f"{code}: {message}" if code else message
                    else:
                        detail = str(error)

                    errors.append(f"{url}: {detail}")
                    break

                # Accepter uniquement une réponse correspondant
                # au type de données demandé.
                if "ticks" in payload:
                    if (
                        response.get("msg_type") == "tick"
                        and isinstance(response.get("tick"), dict)
                    ):
                        return response

                elif "ticks_history" in payload:
                    if (
                        isinstance(response.get("candles"), list)
                        or isinstance(response.get("history"), dict)
                    ):
                        return response

                elif "active_symbols" in payload:
                    if isinstance(response.get("active_symbols"), list):
                        return response

                # Ignorer les réponses d'initialisation non pertinentes.

            else:
                errors.append(f"{url}: délai dépassé sans réponse exploitable")
                continue

            if not errors or not errors[-1].startswith(url):
                errors.append(f"{url}: aucune réponse exploitable")

        except Exception as exc:
            errors.append(
                f"{url}: {type(exc).__name__}: {exc}"
            )

        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

    message = "Échec des endpoints Deriv : " + " ; ".join(errors)
    return {"error": {"message": message}}


def get_current_price(
    symbol: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> float | None:
    """Retourne le dernier prix reçu, ou None si la cotation échoue."""
    if not _valid_symbol(symbol):
        return None

    response = _request(
        {
            "ticks": symbol.strip(),
            "subscribe": 0,
        },
        timeout=timeout,
    )

    if response.get("error"):
        print(
            f"[DERIV] Prix indisponible pour {symbol}: "
            f"{response['error'].get('message', 'Erreur inconnue')}"
        )
        return None

    tick = response.get("tick")
    if not isinstance(tick, dict):
        print(f"[DERIV] Réponse sans tick valide pour {symbol}.")
        return None

    try:
        quote = float(tick["quote"])
    except (KeyError, TypeError, ValueError):
        print(f"[DERIV] Cotation manquante ou invalide pour {symbol}.")
        return None

    if not math.isfinite(quote) or quote <= 0:
        print(f"[DERIV] Cotation non valide pour {symbol}: {quote}")
        return None

    return quote


def get_candles(
    symbol: str,
    timeframe: str,
    count: int = 50,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Récupère les bougies historiques clôturées."""
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
        message = response["error"].get(
            "message",
            "Erreur inconnue de l'API Deriv",
        )
        return {"error": message}

    raw_candles = response.get("candles")

    if not isinstance(raw_candles, list):
        return {
            "error": (
                f"Réponse Deriv sans liste de bougies valide "
                f"pour {symbol} en {timeframe}."
            )
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
        except (KeyError, TypeError, ValueError, OverflowError):
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

        if any(not math.isfinite(value) or value <= 0 for value in values):
            continue

        if candle["high"] < candle["low"]:
            continue

        if candle["high"] < max(candle["open"], candle["close"]):
            continue

        if candle["low"] > min(candle["open"], candle["close"]):
            continue

        # Exclure les bougies qui ne sont pas encore clôturées.
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
        "count": len(candles[-count:]),
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
        print(
            "[DERIV] Impossible de récupérer les symboles : "
            f"{response['error'].get('message', 'Erreur inconnue')}"
        )
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
    
