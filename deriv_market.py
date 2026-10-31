"""
TRADER AI PRO — DERIV MARKET DATA

Module de récupération des données de marché Deriv.

Fonctions prévues :
- Connexion WebSocket publique.
- Récupération des bougies OHLC.
- Récupération du prix actuel.
- Gestion des erreurs réseau.
- Reconnexion automatique.

Aucune exécution d'ordre.
Aucune connexion à un compte réel.
"""

import json
import time
import logging
import threading

import websocket


# ============================================================
# 1. CONFIGURATION GENERALE
# ============================================================

APP_ID = 1089

URLS = [
    f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}",
    f"wss://ws.binaryws.com/websockets/v3?app_id={APP_ID}",
]

REQUEST_TIMEOUT = 20

MAX_RETRIES = 3

RETRY_DELAY = 2

# Taille maximale des données reçues.
MAX_CANDLES = 1000


# ============================================================
# 2. CONFIGURATION DES JOURNAUX
# ============================================================

logger = logging.getLogger("TRADER_AI_PRO.DERIV")

if not logger.handlers:

    handler = logging.StreamHandler()

    handler.setFormatter(
        logging.Formatter(
            "[DERIV MARKET] %(asctime)s | %(levelname)s | %(message)s"
        )
    )

    logger.addHandler(handler)

logger.setLevel(logging.INFO)


# ============================================================
# 3. EXCEPTION PERSONNALISEE
# ============================================================

class DerivMarketError(Exception):
    """
    Erreur spécifique au module de données Deriv.
    """
    pass


# ============================================================
# 4. VALIDATION DES PARAMETRES
# ============================================================

def _validate_symbol(symbol):
    """
    Vérifie le symbole demandé.
    """

    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Symbole Deriv invalide.")

    return symbol.strip()


def _validate_granularity(granularity):
    """
    Vérifie la durée de la bougie en secondes.
    """

    try:
        granularity = int(granularity)

    except (TypeError, ValueError):
        raise ValueError("Granularité invalide.")

    if granularity <= 0:
        raise ValueError("La granularité doit être positive.")

    return granularity


def _validate_count(count):
    """
    Vérifie le nombre de bougies demandé.
    """

    try:
        count = int(count)

    except (TypeError, ValueError):
        raise ValueError("Nombre de bougies invalide.")

    if count < 1 or count > MAX_CANDLES:
        raise ValueError(
            f"Le nombre de bougies doit être compris entre 1 et {MAX_CANDLES}."
        )

    return count


# ============================================================
# 5. CREATION D'UNE CONNEXION WEBSOCKET
# ============================================================

def _create_connection(url):
    """
    Ouvre une connexion WebSocket vers Deriv.
    """

    try:

        connection = websocket.create_connection(
            url,
            timeout=REQUEST_TIMEOUT,
            enable_multithread=True,
        )

        connection.settimeout(REQUEST_TIMEOUT)

        return connection

    except Exception as exc:

        raise DerivMarketError(
            f"Connexion WebSocket impossible : {exc}"
        ) from exc


# ============================================================
# 6. RECEPTION D'UNE REPONSE WEBSOCKET
# ============================================================

def _receive_json(connection):
    """
    Attend une réponse JSON valide.
    """

    try:

        raw_message = connection.recv()

        if not raw_message:
            raise DerivMarketError(
                "Réponse vide reçue de Deriv."
            )

        response = json.loads(raw_message)

        if not isinstance(response, dict):
            raise DerivMarketError(
                "Format de réponse Deriv invalide."
            )

        return response

    except json.JSONDecodeError as exc:

        raise DerivMarketError(
            "Réponse JSON illisible."
        ) from exc

    except Exception as exc:

        if isinstance(exc, DerivMarketError):
            raise

        raise DerivMarketError(
            f"Erreur de réception WebSocket : {exc}"
        ) from exc
        # ============================================================
# 7. ENVOI D'UNE REQUETE DERIV
# ============================================================

def _send_request(connection, payload):
    """
    Envoie une requête JSON à Deriv.
    """

    if not isinstance(payload, dict):
        raise ValueError("La requête doit être un dictionnaire.")

    try:

        connection.send(
            json.dumps(payload)
        )

    except Exception as exc:

        raise DerivMarketError(
            f"Impossible d'envoyer la requête : {exc}"
        ) from exc


# ============================================================
# 8. VERIFICATION DES ERREURS DERIV
# ============================================================

def _check_deriv_error(response):
    """
    Détecte les erreurs renvoyées par l'API Deriv.
    """

    error = response.get("error")

    if not error:
        return

    message = error.get(
        "message",
        "Erreur Deriv inconnue.",
    )

    code = error.get(
        "code",
        "UNKNOWN",
    )

    raise DerivMarketError(
        f"Erreur Deriv [{code}] : {message}"
    )


# ============================================================
# 9. EXECUTION D'UNE REQUETE SUR UNE CONNEXION
# ============================================================

def _execute_request(connection, payload, expected_key=None):
    """
    Envoie une requête et attend la réponse correspondante.

    Les réponses intermédiaires non pertinentes sont ignorées.
    """

    _send_request(
        connection,
        payload,
    )

    deadline = time.time() + REQUEST_TIMEOUT

    while time.time() < deadline:

        response = _receive_json(connection)

        _check_deriv_error(response)

        if expected_key is None:
            return response

        if expected_key in response:
            return response

        # Ignore les réponses qui ne correspondent pas
        # à la requête attendue.

    raise DerivMarketError(
        "Délai dépassé : aucune réponse exploitable de Deriv."
    )


# ============================================================
# 10. REQUETE AVEC RECONNEXION AUTOMATIQUE
# ============================================================

def _request(payload, expected_key=None):
    """
    Essaie les différents serveurs Deriv.

    Une nouvelle connexion est créée pour chaque tentative.
    """

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        for url in URLS:

            connection = None

            try:

                logger.info(
                    "Connexion au serveur Deriv : %s",
                    url.split("?")[0],
                )

                connection = _create_connection(url)

                response = _execute_request(
                    connection,
                    payload,
                    expected_key=expected_key,
                )

                return response

            except Exception as exc:

                last_error = exc

                logger.warning(
                    "Tentative %s/%s échouée : %s",
                    attempt,
                    MAX_RETRIES,
                    exc,
                )

            finally:

                if connection is not None:

                    try:
                        connection.close()

                    except Exception:
                        pass

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    raise DerivMarketError(
        f"Toutes les connexions Deriv ont échoué : {last_error}"
    )


# ============================================================
# 11. CONVERSION D'UNE BOUGIE DERIV
# ============================================================

def _normalise_candle(candle):
    """
    Convertit une bougie Deriv en format OHLC standard.
    """

    if not isinstance(candle, dict):
        return None

    try:

        timestamp = int(candle["epoch"])

        open_price = float(candle["open"])
        high_price = float(candle["high"])
        low_price = float(candle["low"])
        close_price = float(candle["close"])

    except (KeyError, TypeError, ValueError):
        return None

    values = [
        open_price,
        high_price,
        low_price,
        close_price,
    ]

    if any(value <= 0 for value in values):
        return None

    if high_price < low_price:
        return None

    if high_price < max(open_price, close_price):
        return None

    if low_price > min(open_price, close_price):
        return None

    return {
        "epoch": timestamp,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
    }


# ============================================================
# 12. RECUPERATION DES BOUGIES HISTORIQUES
# ============================================================

def get_candles(
    symbol,
    granularity,
    count=200,
):
    """
    Récupère les bougies historiques d'un indice.

    Retour :
    Liste chronologique de dictionnaires OHLC.
    """

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

    logger.info(
        "Récupération %s | granularité=%s | bougies=%s",
        symbol,
        granularity,
        count,
    )

    response = _request(
        payload,
        expected_key="candles",
    )

    raw_candles = response.get("candles")

    if not isinstance(raw_candles, list):
        raise DerivMarketError(
            f"Réponse bougies invalide pour {symbol}."
        )

    candles = []

    for raw_candle in raw_candles:

        candle = _normalise_candle(
            raw_candle
        )

        if candle is not None:
            candles.append(candle)

    # Suppression des doublons de timestamps.
    unique_candles = {}

    for candle in candles:
        unique_candles[candle["epoch"]] = candle

    candles = sorted(
        unique_candles.values(),
        key=lambda item: item["epoch"],
    )

    if len(candles) < count:

        logger.warning(
            "%s | %s bougies valides reçues sur %s demandées.",
            symbol,
            len(candles),
            count,
        )

    logger.info(
        "%s | %s bougies valides récupérées.",
        symbol,
        len(candles),
    )

    return candles
    # ============================================================
# 13. RECUPERATION DU PRIX ACTUEL
# ============================================================

def get_current_price(symbol):
    """
    Récupère le dernier prix disponible d'un indice Deriv.

    Utilise la requête ticks_history avec un seul tick
    pour éviter les problèmes liés aux abonnements.
    """

    symbol = _validate_symbol(symbol)

    payload = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": 1,
        "end": "latest",
        "style": "ticks",
    }

    logger.info(
        "Récupération du prix actuel : %s",
        symbol,
    )

    response = _request(
        payload,
        expected_key="history",
    )

    history = response.get("history")

    if not isinstance(history, dict):
        raise DerivMarketError(
            f"Historique de prix invalide pour {symbol}."
        )

    prices = history.get("prices")

    if not isinstance(prices, list) or not prices:
        raise DerivMarketError(
            f"Aucun prix reçu pour {symbol}."
        )

    try:

        price = float(prices[-1])

    except (TypeError, ValueError):
        raise DerivMarketError(
            f"Prix non numérique reçu pour {symbol}."
        )

    if price <= 0:
        raise DerivMarketError(
            f"Prix invalide reçu pour {symbol}."
        )

    logger.info(
        "%s | Prix actuel : %s",
        symbol,
        price,
    )

    return price


# ============================================================
# 14. TEST DE CONNEXION DERIV
# ============================================================

def test_connection():
    """
    Vérifie que le serveur Deriv répond.
    """

    payload = {
        "time": 1,
    }

    try:

        response = _request(
            payload,
            expected_key="time",
        )

        server_time = response.get("time")

        logger.info(
            "Connexion Deriv réussie. Heure serveur : %s",
            server_time,
        )

        return True

    except Exception as exc:

        logger.error(
            "Test de connexion Deriv échoué : %s",
            exc,
        )

        return False


# ============================================================
# 15. TEST DE RECUPERATION D'UN INDICE
# ============================================================

def test_symbol(symbol):
    """
    Vérifie la récupération des données d'un indice.
    """

    try:

        symbol = _validate_symbol(symbol)

        price = get_current_price(symbol)

        candles = get_candles(
            symbol=symbol,
            granularity=3600,
            count=10,
        )

        result = {
            "symbol": symbol,
            "price": price,
            "candles_received": len(candles),
            "success": bool(candles),
        }

        logger.info(
            "Test indice %s : %s",
            symbol,
            result,
        )

        return result

    except Exception as exc:

        logger.error(
            "Test de l'indice %s échoué : %s",
            symbol,
            exc,
        )

        return {
            "symbol": symbol,
            "price": None,
            "candles_received": 0,
            "success": False,
            "error": str(exc),
        }


# ============================================================
# 16. TEST DE TOUS LES INDICES
# ============================================================

def test_all_symbols(symbols):
    """
    Teste les symboles fournis sans passer d'ordre.
    """

    results = []

    for symbol in symbols:

        result = test_symbol(symbol)

        results.append(result)

        time.sleep(0.5)

    successful = sum(
        1 for result in results
        if result.get("success")
    )

    logger.info(
        "Test terminé : %s/%s indices accessibles.",
        successful,
        len(results),
    )

    return results
    # ============================================================
# 17. DIAGNOSTIC DU MODULE
# ============================================================

def get_module_information():
    """
    Retourne les paramètres du module Deriv.
    """

    return {
        "module": "TRADER AI PRO DERIV MARKET",
        "app_id": APP_ID,
        "servers": URLS,
        "request_timeout": REQUEST_TIMEOUT,
        "max_retries": MAX_RETRIES,
        "max_candles": MAX_CANDLES,
        "automatic_trading": False,
        "order_execution": False,
    }


# ============================================================
# 18. VERIFICATION DES FONCTIONS PRINCIPALES
# ============================================================

def verify_module():
    """
    Vérifie que les fonctions principales sont disponibles.
    """

    required_functions = [
        get_candles,
        get_current_price,
        test_connection,
        test_symbol,
        test_all_symbols,
    ]

    for function in required_functions:

        if not callable(function):

            raise DerivMarketError(
                f"Fonction indisponible : {function}"
            )

    logger.info(
        "Vérification interne du module réussie."
    )

    return True


# ============================================================
# 19. TEST AUTONOME
# ============================================================

if __name__ == "__main__":

    logger.info("=" * 55)
    logger.info("TRADER AI PRO — TEST DU MODULE DERIV")
    logger.info("=" * 55)

    verify_module()

    information = get_module_information()

    logger.info(
        "Informations du module : %s",
        information,
    )

    if test_connection():

        logger.info(
            "Le serveur Deriv est accessible."
        )

        result = test_symbol("R_50")

        logger.info(
            "Résultat du test : %s",
            result,
        )

    else:

        logger.error(
            "Impossible de communiquer avec Deriv."
        )

    logger.info(
        "Test terminé. Aucun ordre n'a été exécuté."
    )
