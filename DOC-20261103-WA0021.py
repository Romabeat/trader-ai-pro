import json
import logging
import math
import os
import random
import time
from typing import Any, Dict, List, Optional

import websocket


LOGGER = logging.getLogger("TRADER_AI_PRO.DERIV")

APP_ID = os.getenv("DERIV_APP_ID", "1089").strip()

# Endpoints WebSocket standards de l'API de marché Deriv.
# Le premier est prioritaire ; le second sert de secours.
LEGACY_WEBSOCKET_URLS = [
    f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}",
    f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}",
]

DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_DELAY = 2.0
MAX_RETRY_DELAY = 10.0

DEFAULT_CANDLE_COUNT = 200
MAX_CANDLE_COUNT = 5000

GRANULARITY = {
    "H1": 3600,
    "H2": 7200,
    "H4": 14400,
    "D1": 86400,
}

ALLOWED_GRANULARITIES = {
    3600,
    7200,
    14400,
    86400,
}


class DerivMarketError(Exception):
    pass


class DerivConnectionError(DerivMarketError):
    pass


class DerivDataError(DerivMarketError):
    pass


def _validate_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise ValueError(
            "Le symbole doit être une chaîne de caractères."
        )

    symbol = symbol.strip()

    if not symbol:
        raise ValueError(
            "Le symbole Deriv est vide."
        )

    if len(symbol) > 40:
        raise ValueError(
            "Le symbole Deriv est trop long."
        )

    return symbol


def _validate_granularity(granularity: int) -> int:
    try:
        granularity = int(granularity)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "La granularité doit être un entier."
        ) from exc

    if granularity not in ALLOWED_GRANULARITIES:
        raise ValueError(
            f"Granularité non autorisée : {granularity}"
        )

    return granularity


def _validate_count(count: int) -> int:
    try:
        count = int(count)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Le nombre de bougies doit être un entier."
        ) from exc

    if count < 1:
        raise ValueError(
            "Le nombre de bougies doit être positif."
        )

    if count > MAX_CANDLE_COUNT:
        raise ValueError(
            f"Maximum autorisé : {MAX_CANDLE_COUNT} bougies."
        )

    return count


def _to_finite_float(
    value: Any,
    field_name: str,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DerivDataError(
            f"Valeur numérique invalide : {field_name}"
        ) from exc

    if not math.isfinite(result):
        raise DerivDataError(
            f"Valeur numérique non finie : {field_name}"
        )

    return result


def _close_connection(
    connection: Optional[Any],
) -> None:
    if connection is None:
        return

    try:
        connection.close()
    except Exception as exc:
        LOGGER.debug(
            "Erreur de fermeture WebSocket : %s",
            exc,
        )


def _open_connection(url: str) -> Any:
    LOGGER.info(
        "Connexion au serveur Deriv : %s",
        url.split("?")[0],
    )

    try:
        connection = websocket.create_connection(
            url,
            timeout=DEFAULT_TIMEOUT,
            enable_multithread=False,
        )

        connection.settimeout(DEFAULT_TIMEOUT)

        LOGGER.info(
            "Connexion WebSocket établie : %s",
            url.split("?")[0],
        )

        return connection

    except Exception as exc:
        raise DerivConnectionError(
            f"Connexion impossible à {url.split('?')[0]} : {exc}"
        ) from exc


def _send_request(
    connection: Any,
    payload: Dict[str, Any],
) -> None:
    if not isinstance(payload, dict):
        raise ValueError(
            "La requête Deriv doit être un dictionnaire."
        )

    try:
        connection.send(
            json.dumps(
                payload,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        )

    except Exception as exc:
        raise DerivConnectionError(
            f"Échec d'envoi de la requête : {exc}"
        ) from exc


def _receive_response(
    connection: Any,
) -> Dict[str, Any]:
    try:
        raw_response = connection.recv()

    except Exception as exc:
        raise DerivConnectionError(
            f"Échec de réception de Deriv : {exc}"
        ) from exc

    if not raw_response:
        raise DerivConnectionError(
            "Le serveur Deriv a renvoyé une réponse vide."
        )

    try:
        response = json.loads(raw_response)

    except (TypeError, json.JSONDecodeError) as exc:
        raise DerivDataError(
            "La réponse reçue n'est pas un JSON valide."
        ) from exc

    if not isinstance(response, dict):
        raise DerivDataError(
            "Format de réponse Deriv inattendu."
        )

    error = response.get("error")

    if isinstance(error, dict):
        code = error.get("code", "UNKNOWN")
        message = error.get(
            "message",
            "Erreur inconnue",
        )

        raise DerivMarketError(
            f"Erreur API Deriv [{code}] : {message}"
        )

    return response
def _execute_request(
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(
            "La requête doit être un dictionnaire."
        )

    last_error = None

    # Essayer les endpoints standards l'un après l'autre. L'endpoint
    # options/public n'est pas utilisé pour ticks_history/active_symbols.
    endpoints = list(LEGACY_WEBSOCKET_URLS)

    for endpoint in endpoints:
        connection = None

        try:
            connection = _open_connection(endpoint)

            _send_request(
                connection,
                payload,
            )

            response = _receive_response(
                connection,
            )

            return response

        except Exception as exc:
            last_error = exc

            LOGGER.warning(
                "Échec de la requête Deriv : %s",
                exc,
            )

        finally:
            _close_connection(connection)

    raise DerivConnectionError(
        "Impossible de récupérer les données Deriv : "
        f"{last_error}"
    )


def _normalize_candles(
    raw_candles: Any,
) -> List[Dict[str, Any]]:
    if not isinstance(raw_candles, list):
        raise DerivDataError(
            "La réponse ne contient pas une liste de bougies."
        )

    normalized = []
    seen_epochs = set()

    for candle in raw_candles:
        if not isinstance(candle, dict):
            continue

        try:
            epoch = int(candle["epoch"])

            open_price = _to_finite_float(
                candle["open"],
                "open",
            )

            high_price = _to_finite_float(
                candle["high"],
                "high",
            )

            low_price = _to_finite_float(
                candle["low"],
                "low",
            )

            close_price = _to_finite_float(
                candle["close"],
                "close",
            )

        except (
            KeyError,
            TypeError,
            ValueError,
            DerivDataError,
        ) as exc:
            LOGGER.debug(
                "Bougie ignorée : %s",
                exc,
            )
            continue

        if epoch <= 0:
            continue

        if epoch in seen_epochs:
            continue

        if high_price < low_price:
            continue

        if high_price < max(
            open_price,
            close_price,
        ):
            continue

        if low_price > min(
            open_price,
            close_price,
        ):
            continue

        normalized.append(
            {
                "epoch": epoch,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
            }
        )

        seen_epochs.add(epoch)

    normalized.sort(
        key=lambda item: item["epoch"]
    )

    if not normalized:
        raise DerivDataError(
            "Aucune bougie valide après normalisation."
        )

    return normalized


def _extract_history(
    response: Dict[str, Any],
) -> Dict[str, Any]:
    history = response.get("history")

    if isinstance(history, dict):
        return history

    candles = response.get("candles")

    if isinstance(candles, list):
        return {
            "candles": candles,
        }

    raise DerivDataError(
        "La réponse Deriv ne contient pas "
        "d'historique exploitable."
    )


def get_candles(
    symbol: str,
    granularity: int,
    count: int = DEFAULT_CANDLE_COUNT,
) -> List[Dict[str, Any]]:
    symbol = _validate_symbol(symbol)

    granularity = _validate_granularity(
        granularity
    )

    count = _validate_count(count)

    payload = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "granularity": granularity,
        "style": "candles",
    }

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1,
    ):
        try:
            LOGGER.info(
                "Récupération des bougies : "
                "%s | granularité=%s | quantité=%s",
                symbol,
                granularity,
                count,
            )

            response = _execute_request(
                payload
            )

            history = _extract_history(
                response
            )

            raw_candles = history.get(
                "candles",
                response.get("candles"),
            )

            candles = _normalize_candles(
                raw_candles
            )

            if len(candles) < count:
                LOGGER.warning(
                    "%s : %s bougies reçues sur %s demandées.",
                    symbol,
                    len(candles),
                    count,
                )

            LOGGER.info(
                "%s : %s bougies valides récupérées.",
                symbol,
                len(candles),
            )

            return candles

        except Exception as exc:
            last_error = exc

            LOGGER.warning(
                "Tentative %s/%s échouée pour %s : %s",
                attempt,
                MAX_RETRIES,
                symbol,
                exc,
            )

            if attempt < MAX_RETRIES:
                delay = min(
                    RETRY_DELAY * (2 ** (attempt - 1)),
                    MAX_RETRY_DELAY,
                )

                delay += random.uniform(
                    0.0,
                    0.5,
                )

                time.sleep(delay)

    raise DerivDataError(
        f"Échec de récupération des bougies "
        f"pour {symbol} : {last_error}"
)
def get_current_price(
    symbol: str,
) -> float:
    symbol = _validate_symbol(symbol)

    payload = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": 1,
        "end": "latest",
        "style": "ticks",
    }

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _execute_request(payload)

            history = response.get("history", {})

            if not isinstance(history, dict):
                raise DerivDataError(
                    "Historique de prix absent ou invalide."
                )

            prices = history.get("prices", [])

            if not isinstance(prices, list) or not prices:
                raise DerivDataError(
                    f"Aucun prix disponible pour {symbol}."
                )

            price = _to_finite_float(
                prices[-1],
                "current_price",
            )

            if price <= 0:
                raise DerivDataError(
                    f"Prix actuel invalide pour {symbol}."
                )

            LOGGER.info(
                "PRIX ACTUEL | %s | %.8f",
                symbol,
                price,
            )

            return price

        except Exception as exc:
            last_error = exc

            LOGGER.warning(
                "Prix actuel indisponible pour %s "
                "(tentative %s/%s) : %s",
                symbol,
                attempt,
                MAX_RETRIES,
                exc,
            )

            if attempt < MAX_RETRIES:
                delay = min(
                    RETRY_DELAY * (2 ** (attempt - 1)),
                    MAX_RETRY_DELAY,
                )

                time.sleep(
                    delay + random.uniform(0.0, 0.5)
                )

    raise DerivDataError(
        f"Impossible de récupérer le prix actuel "
        f"de {symbol} : {last_error}"
    )


def test_connection() -> bool:
    """Teste les endpoints standards de l'API WebSocket Deriv."""
    try:
        response = _execute_request({"ping": 1})
        if "ping" not in response:
            raise DerivDataError(
                "La réponse au ping Deriv est inattendue."
            )

        LOGGER.info("Test de connexion Deriv réussi.")
        return True

    except Exception as exc:
        LOGGER.error("Test de connexion Deriv échoué : %s", exc)
        return False


def validate_candles(
    candles: List[Dict[str, Any]],
    expected_count: int = DEFAULT_CANDLE_COUNT,
) -> bool:
    if not isinstance(candles, list):
        return False

    if len(candles) < expected_count:
        return False

    previous_epoch = 0

    for candle in candles:
        if not isinstance(candle, dict):
            return False

        required_fields = (
            "epoch",
            "open",
            "high",
            "low",
            "close",
        )

        if any(
            field not in candle
            for field in required_fields
        ):
            return False

        try:
            epoch = int(candle["epoch"])
            open_price = float(candle["open"])
            high_price = float(candle["high"])
            low_price = float(candle["low"])
            close_price = float(candle["close"])

        except (TypeError, ValueError):
            return False

        values = (
            open_price,
            high_price,
            low_price,
            close_price,
        )

        if not all(
            math.isfinite(value)
            for value in values
        ):
            return False

        if epoch <= previous_epoch:
            return False

        if low_price > high_price:
            return False

        if not (
            low_price
            <= min(open_price, close_price)
            <= max(open_price, close_price)
            <= high_price
        ):
            return False

        previous_epoch = epoch

    return True


def get_market_snapshot(
    symbol: str,
    candle_count: int = DEFAULT_CANDLE_COUNT,
) -> Dict[str, Any]:
    symbol = _validate_symbol(symbol)
    candle_count = _validate_count(candle_count)

    snapshot = {
        "symbol": symbol,
        "current_price": None,
        "candles": {},
        "errors": [],
        "success": False,
    }

    timeframe_map = {
        "D1": 86400,
        "H4": 14400,
        "H2": 7200,
        "H1": 3600,
    }

    for timeframe, granularity in timeframe_map.items():
        try:
            candles = get_candles(
                symbol,
                granularity,
                count=candle_count,
            )

            if not validate_candles(
                candles,
                expected_count=candle_count,
            ):
                raise DerivDataError(
                    f"Données {timeframe} insuffisantes "
                    f"ou invalides."
                )

            snapshot["candles"][timeframe] = candles

        except Exception as exc:
            message = (
                f"{symbol} : erreur {timeframe} : {exc}"
            )

            snapshot["errors"].append(message)

            LOGGER.error("%s", message)

    try:
        snapshot["current_price"] = get_current_price(
            symbol
        )

    except Exception as exc:
        message = (
            f"{symbol} : prix actuel indisponible : {exc}"
        )

        snapshot["errors"].append(message)

        LOGGER.error("%s", message)

    snapshot["success"] = (
        len(snapshot["candles"]) == len(timeframe_map)
        and snapshot["current_price"] is not None
        and not snapshot["errors"]
    )

    if snapshot["success"]:
        LOGGER.info(
            "%s : données de marché complètes.",
            symbol,
        )
    else:
        LOGGER.warning(
            "%s : données de marché incomplètes.",
            symbol,
        )

    return snapshot


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | %(levelname)s | %(message)s"
        ),
    )

    if test_connection():
        LOGGER.info(
            "Connexion validée. Test des données en cours."
        )

        try:
            price = get_current_price("1HZ10V")

            LOGGER.info(
                "Prix de test : %.8f",
                price,
            )

        except Exception as exc:
            LOGGER.error(
                "Échec du test des données : %s",
                exc,
            )

    else:
        LOGGER.error(
            "Connexion non disponible. "
            "Aucune analyse ne doit être considérée comme réussie."
            )


def get_active_symbols() -> List[Dict[str, Any]]:
    """
    Retourne les marchés actifs publiés par l'API WebSocket publique Deriv.

    Les versions de l'API peuvent nommer le code `symbol` ou
    `underlying_symbol`. Les consommateurs doivent accepter les deux formes.
    """
    response = _execute_request({"active_symbols": "brief"})
    raw_symbols = response.get("active_symbols", [])
    if not isinstance(raw_symbols, list):
        raise DerivDataError("Liste des marchés actifs invalide.")

    symbols: List[Dict[str, Any]] = []
    for item in raw_symbols:
        if not isinstance(item, dict):
            continue
        code = item.get("underlying_symbol") or item.get("symbol")
        name = item.get("underlying_symbol_name") or item.get("display_name")
        if not isinstance(code, str) or not code.strip():
            continue
        normalized = dict(item)
        normalized["symbol"] = code.strip()
        normalized["display_name"] = str(name or code).strip()
        normalized["market"] = item.get("market", "")
        symbols.append(normalized)

    if not symbols:
        raise DerivDataError("Deriv n'a retourné aucun marché actif exploitable.")
    return symbols


def get_synthetic_symbols(timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """Retourne les indices synthétiques actifs via l'API publique Deriv."""
    raw_symbols = get_active_symbols()
    symbols = [
        item for item in raw_symbols
        if item.get("market") == "synthetic_index"
        and item.get("symbol")
    ]
    return {"symbols": symbols, "count": len(symbols)}


def get_candles_compat(
    symbol: str, timeframe: str, count: int = DEFAULT_CANDLE_COUNT,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    """Adaptateur pour l'API HTTP de app.py; la stratégie utilise la forme historique en liste."""
    timeframe = str(timeframe).upper()
    if timeframe not in GRANULARITY:
        raise ValueError(f"Timeframe non autorisé : {timeframe}")
    rows = get_candles(symbol, GRANULARITY[timeframe], count=count)
    return {"symbol": symbol, "timeframe": timeframe, "count": len(rows), "candles": rows}



def fetch_candles(
    symbol: str,
    timeframe: Any,
    count: int = DEFAULT_CANDLE_COUNT,
) -> List[Dict[str, Any]]:
    """
    Adaptateur de compatibilité.

    Accepte soit une granularité en secondes, soit H1/H2/H4/D1.
    Retourne les bougies normalisées sous forme de liste.
    """
    if isinstance(timeframe, str):
        key = timeframe.strip().upper()
        if key not in GRANULARITY:
            raise ValueError(f"Timeframe non autorisé : {timeframe}")
        granularity = GRANULARITY[key]
    else:
        granularity = _validate_granularity(timeframe)

    return get_candles(symbol, granularity, count=count)
