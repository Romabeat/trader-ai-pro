"""
TRADER AI PRO — Couche de données Deriv
Version corrigée : endpoint public officiel en priorité, endpoints legacy en secours.
Aucune fonction de ce module ne passe d'ordre.
"""

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

# Endpoint public officiel actuel, documenté par Deriv pour les données de marché.
PUBLIC_WEBSOCKET_URL = (
    "wss://api.derivws.com/trading/v1/options/ws/public"
)

# Endpoints WebSocket legacy conservés uniquement comme secours.
LEGACY_WEBSOCKET_URLS = [
    f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}",
    f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}",
]

# L'ordre de tentative est important : public actuel, puis endpoints legacy.
WEBSOCKET_URLS = [PUBLIC_WEBSOCKET_URL] + LEGACY_WEBSOCKET_URLS

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
ALLOWED_GRANULARITIES = set(GRANULARITY.values())


class DerivMarketError(Exception):
    """Erreur générale de données Deriv."""


class DerivConnectionError(DerivMarketError):
    """Erreur de transport WebSocket."""


class DerivDataError(DerivMarketError):
    """Réponse de données invalide."""


def _validate_symbol(symbol: str) -> str:
    if not isinstance(symbol, str):
        raise ValueError("Le symbole doit être une chaîne de caractères.")
    symbol = symbol.strip()
    if not symbol:
        raise ValueError("Le symbole Deriv est vide.")
    if len(symbol) > 40:
        raise ValueError("Le symbole Deriv est trop long.")
    return symbol


def _validate_granularity(granularity: int) -> int:
    try:
        granularity = int(granularity)
    except (TypeError, ValueError) as exc:
        raise ValueError("La granularité doit être un entier.") from exc
    if granularity not in ALLOWED_GRANULARITIES:
        raise ValueError(f"Granularité non autorisée : {granularity}")
    return granularity


def _validate_count(count: int) -> int:
    try:
        count = int(count)
    except (TypeError, ValueError) as exc:
        raise ValueError("Le nombre de bougies doit être un entier.") from exc
    if count < 1 or count > MAX_CANDLE_COUNT:
        raise ValueError(f"Le nombre de bougies doit être compris entre 1 et {MAX_CANDLE_COUNT}.")
    return count


def _to_finite_float(value: Any, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise DerivDataError(f"Valeur numérique invalide : {field_name}") from exc
    if not math.isfinite(result):
        raise DerivDataError(f"Valeur numérique non finie : {field_name}")
    return result


def _close_connection(connection: Optional[Any]) -> None:
    if connection is not None:
        try:
            connection.close()
        except Exception as exc:
            LOGGER.debug("Erreur de fermeture WebSocket : %s", exc)


def _open_connection(url: str) -> Any:
    LOGGER.info("Connexion au serveur Deriv : %s", url.split("?")[0])
    try:
        connection = websocket.create_connection(
            url,
            timeout=DEFAULT_TIMEOUT,
            enable_multithread=False,
            # Certains environnements intermédiaires refusent un handshake
            # sans Origin. La valeur reste générique et ne contient aucun secret.
            origin="https://deriv.com",
        )
        connection.settimeout(DEFAULT_TIMEOUT)
        LOGGER.info("Connexion WebSocket établie : %s", url.split("?")[0])
        return connection
    except Exception as exc:
        raise DerivConnectionError(
            f"Connexion impossible à {url.split('?')[0]} : {exc}"
        ) from exc


def _send_request(connection: Any, payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("La requête Deriv doit être un dictionnaire.")
    try:
        connection.send(json.dumps(payload, separators=(",", ":"), ensure_ascii=True))
    except Exception as exc:
        raise DerivConnectionError(f"Échec d'envoi de la requête : {exc}") from exc


def _receive_response(connection: Any) -> Dict[str, Any]:
    try:
        raw_response = connection.recv()
    except Exception as exc:
        raise DerivConnectionError(f"Échec de réception de Deriv : {exc}") from exc
    if not raw_response:
        raise DerivConnectionError("Le serveur Deriv a renvoyé une réponse vide.")
    try:
        response = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DerivDataError("La réponse reçue n'est pas un JSON valide.") from exc
    if not isinstance(response, dict):
        raise DerivDataError("Format de réponse Deriv inattendu.")
    error = response.get("error")
    if isinstance(error, dict):
        code = error.get("code", "UNKNOWN")
        message = error.get("message", "Erreur inconnue")
        raise DerivMarketError(f"Erreur API Deriv [{code}] : {message}")
    return response


def _execute_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Envoie une requête et essaie les endpoints dans l'ordre configuré."""
    if not isinstance(payload, dict):
        raise ValueError("La requête doit être un dictionnaire.")

    last_error = None
    for endpoint in WEBSOCKET_URLS:
        connection = None
        try:
            connection = _open_connection(endpoint)
            _send_request(connection, payload)
            response = _receive_response(connection)
            return response
        except Exception as exc:
            last_error = exc
            LOGGER.warning("Échec de la requête via %s : %s", endpoint.split("?")[0], exc)
        finally:
            _close_connection(connection)

    raise DerivConnectionError(
        "Impossible de récupérer les données Deriv après tous les endpoints : "
        f"{last_error}"
    )


def _normalize_candles(raw_candles: Any) -> List[Dict[str, Any]]:
    """
    Normalise les bougies et journalise les pertes de données.
    Le format de retour reste identique pour ne casser aucun appelant.
    """
    if not isinstance(raw_candles, list):
        raise DerivDataError("La réponse ne contient pas une liste de bougies.")

    stats = {
        "raw": len(raw_candles),
        "kept": 0,
        "not_dict": 0,
        "invalid_epoch": 0,
        "duplicate_epoch": 0,
        "invalid_numeric": 0,
        "non_finite": 0,
        "invalid_ohlc": 0,
    }
    raw_epochs = []
    normalized = []
    seen_epochs = set()

    for candle in raw_candles:
        if not isinstance(candle, dict):
            stats["not_dict"] += 1
            continue

        try:
            epoch = int(candle["epoch"])
            if epoch <= 0:
                stats["invalid_epoch"] += 1
                continue
            raw_epochs.append(epoch)
        except (KeyError, TypeError, ValueError, OverflowError):
            stats["invalid_epoch"] += 1
            continue

        if epoch in seen_epochs:
            stats["duplicate_epoch"] += 1
            continue

        try:
            raw_values = [
                candle["open"], candle["high"],
                candle["low"], candle["close"],
            ]
            values = [float(value) for value in raw_values]
        except (KeyError, TypeError, ValueError, OverflowError):
            stats["invalid_numeric"] += 1
            continue

        if not all(math.isfinite(value) for value in values):
            stats["non_finite"] += 1
            continue

        open_price, high_price, low_price, close_price = values

        if (
            high_price < low_price
            or high_price < max(open_price, close_price)
            or low_price > min(open_price, close_price)
        ):
            stats["invalid_ohlc"] += 1
            continue

        normalized.append({
            "epoch": epoch,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
        })
        seen_epochs.add(epoch)

    normalized.sort(key=lambda item: item["epoch"])
    stats["kept"] = len(normalized)

    raw_first = min(raw_epochs) if raw_epochs else None
    raw_last = max(raw_epochs) if raw_epochs else None
    valid_first = normalized[0]["epoch"] if normalized else None
    valid_last = normalized[-1]["epoch"] if normalized else None

    LOGGER.info(
        "DIAGNOSTIC BOUGIES | brutes=%s | conservées=%s | "
        "non_dict=%s | epoch_invalides=%s | doublons=%s | "
        "numériques_invalides=%s | non_finies=%s | OHLC_invalides=%s | "
        "epochs_brutes=%s..%s | epochs_valides=%s..%s",
        stats["raw"], stats["kept"], stats["not_dict"],
        stats["invalid_epoch"], stats["duplicate_epoch"],
        stats["invalid_numeric"], stats["non_finite"],
        stats["invalid_ohlc"], raw_first, raw_last,
        valid_first, valid_last,
    )

    if not normalized:
        raise DerivDataError("Aucune bougie valide après normalisation.")
    return normalized


def _extract_candles(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    candles = response.get("candles")
    if isinstance(candles, list):
        return candles
    history = response.get("history")
    if isinstance(history, dict) and isinstance(history.get("candles"), list):
        return history["candles"]
    # Certaines réponses de ticks_history exposent prices/times au lieu
    # de bougies OHLC. Elles ne sont pas suffisantes pour l'analyse OHLC.
    raise DerivDataError(
        "La réponse Deriv ne contient pas de bougies OHLC. "
        "Vérifier le format de l'endpoint et la réponse API."
    )


def _request_candle_page(
    symbol: str,
    granularity: int,
    page_count: int,
    end: Any = "latest",
) -> List[Dict[str, Any]]:
    """Récupère et normalise une page d'historique OHLC."""
    payload = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": page_count,
        "end": end,
        "granularity": granularity,
        "style": "candles",
    }
    response = _execute_request(payload)
    raw_candles = _extract_candles(response)
    LOGGER.info(
        "RÉPONSE DERIV | %s | granularité=%s | bougies_brutes=%s | "
        "bougies_demandées=%s | end=%s",
        symbol, granularity, len(raw_candles), page_count, end,
    )
    return _normalize_candles(raw_candles)


def get_candles(
    symbol: str,
    granularity: int,
    count: int = DEFAULT_CANDLE_COUNT,
) -> List[Dict[str, Any]]:
    """
    Retourne les `count` dernières bougies OHLC valides.

    Deriv peut renvoyer moins de bougies que demandé lorsque la période
    inclut des week-ends, des jours fériés ou des fermetures de marché.
    On sur-échantillonne d'abord l'historique (2x), puis on remonte dans
    le temps par pages si le nombre de bougies valides reste insuffisant.
    Aucune bougie artificielle n'est créée.
    """
    symbol = _validate_symbol(symbol)
    granularity = _validate_granularity(granularity)
    count = _validate_count(count)

    # Deux fois la quantité demandée couvre notamment les jours sans séance.
    # La limite API locale reste respectée.
    page_count = min(MAX_CANDLE_COUNT, max(count, count * 2))
    max_pages = 6
    collected: Dict[int, Dict[str, Any]] = {}
    end: Any = "latest"
    last_error = None

    for page_number in range(1, max_pages + 1):
        page = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                LOGGER.info(
                    "Récupération des bougies : %s | granularité=%s | "
                    "quantité_page=%s | page=%s/%s",
                    symbol, granularity, page_count, page_number, max_pages,
                )
                page = _request_candle_page(
                    symbol=symbol,
                    granularity=granularity,
                    page_count=page_count,
                    end=end,
                )
                break
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "Tentative %s/%s échouée pour %s (page %s) : %s",
                    attempt, MAX_RETRIES, symbol, page_number, exc,
                )
                if attempt < MAX_RETRIES:
                    delay = min(
                        RETRY_DELAY * (2 ** (attempt - 1)),
                        MAX_RETRY_DELAY,
                    )
                    time.sleep(delay + random.uniform(0.0, 0.5))

        if page is None:
            if collected:
                break
            raise DerivDataError(
                f"Échec de récupération des bougies pour {symbol} : {last_error}"
            )

        previous_size = len(collected)
        for candle in page:
            collected[candle["epoch"]] = candle

        ordered = sorted(collected.values(), key=lambda item: item["epoch"])
        LOGGER.info(
            "HISTORIQUE CUMULÉ | %s | granularité=%s | page=%s | "
            "bougies_uniques=%s/%s",
            symbol, granularity, page_number, len(ordered), count,
        )

        if len(ordered) >= count:
            result = ordered[-count:]
            LOGGER.info(
                "%s : %s/%s bougies valides retenues après %s page(s).",
                symbol, len(result), count, page_number,
            )
            return result

        # La page suivante doit se terminer juste avant la plus ancienne
        # bougie reçue. Si l'API ne remonte pas davantage, on arrête proprement.
        if not ordered or len(collected) == previous_size:
            break
        oldest_epoch = ordered[0]["epoch"]
        end = oldest_epoch - 1

    ordered = sorted(collected.values(), key=lambda item: item["epoch"])
    if len(ordered) < count:
        raise DerivDataError(
            f"Historique insuffisant pour {symbol} (granularité={granularity}) : "
            f"{len(ordered)} bougies valides sur {count} requises après "
            f"récupération complémentaire. Aucune bougie artificielle ajoutée."
        )

    result = ordered[-count:]
    LOGGER.info(
        "%s : %s/%s bougies valides retenues après récupération complémentaire.",
        symbol, len(result), count,
    )
    return result


def get_current_price(symbol: str) -> float:
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
            prices = history.get("prices", []) if isinstance(history, dict) else []
            if not isinstance(prices, list) or not prices:
                # Tolère une réponse contenant un tick direct si l'API l'utilise.
                tick = response.get("tick", {})
                quote = tick.get("quote") if isinstance(tick, dict) else None
                if quote is None:
                    raise DerivDataError(f"Aucun prix disponible pour {symbol}.")
                prices = [quote]
            price = _to_finite_float(prices[-1], "current_price")
            if price <= 0:
                raise DerivDataError(f"Prix actuel invalide pour {symbol}.")
            LOGGER.info("PRIX ACTUEL | %s | %.8f", symbol, price)
            return price
        except Exception as exc:
            last_error = exc
            LOGGER.warning(
                "Prix actuel indisponible pour %s (tentative %s/%s) : %s",
                symbol, attempt, MAX_RETRIES, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(min(RETRY_DELAY * (2 ** (attempt - 1)), MAX_RETRY_DELAY) + random.uniform(0, 0.5))
    raise DerivDataError(f"Impossible de récupérer le prix actuel de {symbol} : {last_error}")


def get_active_symbols() -> List[Dict[str, Any]]:
    """Retourne les symboles actifs avec les anciens et nouveaux noms de champs."""
    response = _execute_request({"active_symbols": "brief"})
    raw_symbols = response.get("active_symbols", [])
    if not isinstance(raw_symbols, list):
        raise DerivDataError("Liste des marchés actifs invalide.")

    symbols = []
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
    raw_symbols = get_active_symbols()
    symbols = [
        item for item in raw_symbols
        if item.get("market") == "synthetic_index" and item.get("symbol")
    ]
    return {"symbols": symbols, "count": len(symbols)}


def fetch_candles(
    symbol: str,
    timeframe: Any,
    count: int = DEFAULT_CANDLE_COUNT,
) -> List[Dict[str, Any]]:
    """Adaptateur de compatibilité : accepte H1/H2/H4/D1 ou secondes."""
    if isinstance(timeframe, str):
        key = timeframe.strip().upper()
        if key not in GRANULARITY:
            raise ValueError(f"Timeframe non autorisé : {timeframe}")
        granularity = GRANULARITY[key]
    else:
        granularity = _validate_granularity(timeframe)
    return get_candles(symbol, granularity, count=count)


def get_candles_compat(
    symbol: str,
    timeframe: str,
    count: int = DEFAULT_CANDLE_COUNT,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Any]:
    timeframe = str(timeframe).upper()
    if timeframe not in GRANULARITY:
        raise ValueError(f"Timeframe non autorisé : {timeframe}")
    rows = get_candles(symbol, GRANULARITY[timeframe], count=count)
    return {"symbol": symbol, "timeframe": timeframe, "count": len(rows), "candles": rows}


def validate_candles(
    candles: List[Dict[str, Any]],
    expected_count: int = DEFAULT_CANDLE_COUNT,
) -> bool:
    if not isinstance(candles, list) or len(candles) < expected_count:
        return False
    previous_epoch = 0
    for candle in candles:
        if not isinstance(candle, dict):
            return False
        try:
            epoch = int(candle["epoch"])
            values = [float(candle[key]) for key in ("open", "high", "low", "close")]
        except (KeyError, TypeError, ValueError, OverflowError):
            return False
        if not all(math.isfinite(value) for value in values):
            return False
        open_price, high_price, low_price, close_price = values
        if epoch <= previous_epoch or low_price > high_price:
            return False
        if not (low_price <= min(open_price, close_price) <= max(open_price, close_price) <= high_price):
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
    for timeframe, granularity in GRANULARITY.items():
        try:
            candles = get_candles(symbol, granularity, count=candle_count)
            if not validate_candles(candles, expected_count=candle_count):
                raise DerivDataError(f"Données {timeframe} insuffisantes ou invalides.")
            snapshot["candles"][timeframe] = candles
        except Exception as exc:
            message = f"{symbol} : erreur {timeframe} : {exc}"
            snapshot["errors"].append(message)
            LOGGER.error("%s", message)
    try:
        snapshot["current_price"] = get_current_price(symbol)
    except Exception as exc:
        message = f"{symbol} : prix actuel indisponible : {exc}"
        snapshot["errors"].append(message)
        LOGGER.error("%s", message)
    snapshot["success"] = (
        len(snapshot["candles"]) == len(GRANULARITY)
        and snapshot["current_price"] is not None
        and not snapshot["errors"]
    )
    return snapshot


def test_connection() -> bool:
    try:
        response = _execute_request({"ping": 1})
        if "ping" not in response:
            raise DerivDataError("La réponse au ping Deriv est inattendue.")
        LOGGER.info("Test de connexion Deriv réussi.")
        return True
    except Exception as exc:
        LOGGER.error("Test de connexion Deriv échoué : %s", exc)
        return False


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    if test_connection():
        LOGGER.info("Connexion validée. Aucun ordre ne sera exécuté.")
        try:
            symbols = get_active_symbols()
            LOGGER.info("Nombre de marchés reçus : %s", len(symbols))
        except Exception as exc:
            LOGGER.error("Échec de la découverte des marchés : %s", exc)
    else:
        LOGGER.error("Connexion non disponible. Aucune analyse ne doit être considérée comme réussie.")
