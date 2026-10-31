"""
TRADER AI PRO
Module de récupération des données de marché Deriv.

Fonctions principales :
- Récupération des bougies OHLC.
- Récupération du prix actuel.
- Connexion WebSocket publique.
- Gestion des erreurs et des délais d'attente.

IMPORTANT :
Ce module utilise uniquement les données publiques.
Aucune authentification de compte.
Aucun ordre n'est envoyé.
"""

import json
import logging
import time

import websocket


# ============================================================
# CONFIGURATION
# ============================================================

LOGGER = logging.getLogger("TRADER_AI_PRO.DERIV")

APP_ID = 1089

WEBSOCKET_URLS = [
    f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}",
    f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}",
]

DEFAULT_TIMEOUT = 15
MAX_RETRIES = 2

ALLOWED_GRANULARITIES = {
    3600,    # H1
    7200,    # H2
    14400,   # H4
    86400,   # D1
}


# ============================================================
# VALIDATION DES PARAMÈTRES
# ============================================================

def _validate_symbol(symbol):
    """
    Vérifie que le symbole Deriv est valide.
    """

    if not isinstance(symbol, str):
        raise ValueError("Le symbole doit être une chaîne.")

    symbol = symbol.strip()

    if not symbol:
        raise ValueError("Le symbole ne peut pas être vide.")

    if len(symbol) > 30:
        raise ValueError("Symbole trop long.")

    return symbol


def _validate_granularity(granularity):
    """
    Vérifie l'unité de temps demandée.
    """

    try:
        granularity = int(granularity)
    except (TypeError, ValueError):
        raise ValueError("Granularité invalide.")

    if granularity not in ALLOWED_GRANULARITIES:
        raise ValueError(
            f"Granularité non autorisée : {granularity}"
        )

    return granularity


def _validate_count(count):
    """
    Vérifie le nombre de bougies demandé.
    """

    try:
        count = int(count)
    except (TypeError, ValueError):
        raise ValueError("Nombre de bougies invalide.")

    if count < 1 or count > 1000:
        raise ValueError(
            "Le nombre de bougies doit être compris entre 1 et 1000."
        )

    return count


# ============================================================
# CONNEXION WEBSOCKET
# ============================================================

def _open_connection(url):
    """
    Ouvre une connexion WebSocket Deriv.
    """

    connection = websocket.create_connection(
        url,
        timeout=DEFAULT_TIMEOUT,
        enable_multithread=False,
    )

    connection.settimeout(DEFAULT_TIMEOUT)

    return connection


def _close_connection(connection):
    """
    Ferme proprement une connexion WebSocket.
    """

    if connection is None:
        return

    try:
        connection.close()
    except Exception:
        pass


# ============================================================
# ENVOI ET RÉCEPTION DES REQUÊTES
# ============================================================

def _send_request(connection, payload):
    """
    Envoie une requête JSON à Deriv.
    """

    message = json.dumps(payload)

    connection.send(message)


def _receive_response(connection):
    """
    Récupère et décode la réponse JSON de Deriv.
    """

    raw_response = connection.recv()

    if not raw_response:
        raise ConnectionError(
            "Réponse vide reçue du serveur Deriv."
        )

    try:
        response = json.loads(raw_response)
    except json.JSONDecodeError as error:
        raise ValueError(
            "Réponse JSON invalide reçue de Deriv."
        ) from error

    if not isinstance(response, dict):
        raise ValueError(
            "Format de réponse Deriv inattendu."
        )

    if "error" in response:
        error_data = response["error"]

        error_message = (
            error_data.get("message", "Erreur inconnue")
            if isinstance(error_data, dict)
            else str(error_data)
        )

        raise RuntimeError(
            f"Erreur API Deriv : {error_message}"
        )

    return response
    # ============================================================
# NORMALISATION DES BOUGIES
# ============================================================

def _normalize_candles(raw_candles):
    """
    Convertit les bougies Deriv au format interne :
    epoch, open, high, low, close.
    """

    if not isinstance(raw_candles, list):
        raise ValueError(
            "Les données de bougies reçues sont invalides."
        )

    normalized = []
    seen_epochs = set()

    for candle in raw_candles:
        if not isinstance(candle, dict):
            continue

        try:
            epoch = int(candle["epoch"])
            open_price = float(candle["open"])
            high_price = float(candle["high"])
            low_price = float(candle["low"])
            close_price = float(candle["close"])

        except (KeyError, TypeError, ValueError):
            continue

        values = [
            open_price,
            high_price,
            low_price,
            close_price,
        ]

        if not all(
            value == value and abs(value) != float("inf")
            for value in values
        ):
            continue

        if high_price < low_price:
            continue

        if epoch in seen_epochs:
            continue

        seen_epochs.add(epoch)

        normalized.append({
            "epoch": epoch,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
        })

    normalized.sort(key=lambda item: item["epoch"])

    return normalized


# ============================================================
# EXÉCUTION D'UNE REQUÊTE WEBSOCKET
# ============================================================

def _execute_request(payload):
    """
    Exécute une requête sur les serveurs WebSocket Deriv.

    Essaie les différentes URL en cas d'échec.
    """

    last_error = None

    for url in WEBSOCKET_URLS:
        connection = None

        try:
            LOGGER.info(
                "Connexion au serveur Deriv : %s",
                url.split("?")[0]
            )

            connection = _open_connection(url)

            _send_request(connection, payload)

            response = _receive_response(connection)

            return response

        except Exception as error:
            last_error = error

            LOGGER.warning(
                "Échec de la requête Deriv : %s",
                error
            )

        finally:
            _close_connection(connection)

    raise ConnectionError(
        f"Impossible de récupérer les données Deriv : {last_error}"
    )


# ============================================================
# RÉCUPÉRATION DES BOUGIES HISTORIQUES
# ============================================================

def get_candles(symbol, granularity, count=200):
    """
    Récupère les bougies historiques d'un indice Deriv.

    Paramètres :
        symbol       : symbole Deriv
        granularity  : 3600, 7200, 14400 ou 86400
        count        : nombre de bougies souhaitées

    Retour :
        Liste chronologique de bougies OHLC.
    """

    symbol = _validate_symbol(symbol)
    granularity = _validate_granularity(granularity)
    count = _validate_count(count)

    payload = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "granularity": granularity,
        "style": "candles",
    }

    LOGGER.info(
        "Récupération des bougies : %s | granularité=%s | quantité=%s",
        symbol,
        granularity,
        count,
    )

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = _execute_request(payload)

            candles_data = response.get("candles")

            candles = _normalize_candles(candles_data)

            if not candles:
                raise ValueError(
                    f"Aucune bougie valide reçue pour {symbol}."
                )

            LOGGER.info(
                "%s : %s bougies récupérées.",
                symbol,
                len(candles),
            )

            return candles

        except Exception as error:
            last_error = error

            LOGGER.warning(
                "Tentative %s/%s échouée pour %s : %s",
                attempt,
                MAX_RETRIES,
                symbol,
                error,
            )

            if attempt < MAX_RETRIES:
                time.sleep(1)

    raise RuntimeError(
        f"Échec de récupération des bougies pour {symbol} : "
        f"{last_error}"
)
    # ============================================================
# RÉCUPÉRATION DU PRIX ACTUEL
# ============================================================

def get_current_price(symbol):
    """
    Récupère le dernier prix connu d'un indice Deriv.

    Utilise uniquement les données publiques.
    Aucun ordre n'est envoyé.
    """

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

            prices = history.get("prices", [])

            if not prices:
                raise ValueError(
                    f"Aucun prix reçu pour {symbol}."
                )

            price = float(prices[-1])

            if price <= 0 or not (
                price == price
                and abs(price) != float("inf")
            ):
                raise ValueError(
                    f"Prix invalide reçu pour {symbol}."
                )

            LOGGER.info(
                "Prix actuel de %s : %s",
                symbol,
                price,
            )

            return price

        except Exception as error:
            last_error = error

            LOGGER.warning(
                "Tentative prix %s/%s échouée pour %s : %s",
                attempt,
                MAX_RETRIES,
                symbol,
                error,
            )

            if attempt < MAX_RETRIES:
                time.sleep(1)

    raise RuntimeError(
        f"Impossible de récupérer le prix de {symbol} : "
        f"{last_error}"
    )


# ============================================================
# TEST DE CONNEXION
# ============================================================

def test_connection():
    """
    Vérifie que le serveur Deriv répond.

    Retourne True si la connexion fonctionne.
    """

    payload = {
        "ping": 1,
    }

    try:
        response = _execute_request(payload)

        if "ping" in response:
            LOGGER.info("Connexion Deriv opérationnelle.")
            return True

        LOGGER.warning(
            "Réponse inattendue lors du test Deriv."
        )

        return False

    except Exception as error:
        LOGGER.error(
            "Test de connexion Deriv échoué : %s",
            error,
        )

        return False


# ============================================================
# FIN DU MODULE
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    LOGGER.info("Test du module Deriv Market.")

    if test_connection():
        LOGGER.info("Test réussi.")
    else:
        LOGGER.error("Test échoué.")
