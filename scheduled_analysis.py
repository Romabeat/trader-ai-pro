"""
TRADER AI PRO
Analyse automatique des indices Deriv.
Analyse multi-timeframe : D1 / H4 / H2 / H1.
Alertes Telegram uniquement.
Aucune execution automatique d'ordres.
"""

import os
import sys
import time
import logging
import traceback
import requests


# ==================================================
# CONFIGURATION GENERALE
# ==================================================

APP_NAME = "TRADER AI PRO"

DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() == "true"

ENABLE_TELEGRAM_ALERTS = (
    os.getenv("ENABLE_TELEGRAM_ALERTS", "true").strip().lower()
    == "true"
)

# La passation automatique d'ordres reste interdite.
ENABLE_AUTO_TRADING = False

MIN_CANDLES = 200

TIMEFRAMES = {
    "D1": 86400,
    "H4": 14400,
    "H2": 7200,
    "H1": 3600,
}
# ==================================================
# INDICES DERIV
# ==================================================

SYMBOLS = [
    "1HZ10V",
    "1HZ15V",
    "1HZ25V",
    "1HZ30V",
    "1HZ50V",
    "1HZ75V",
    "1HZ90V",
    "1HZ100V",
    "R_10",
    "R_25",
    "R_50",
    "R_75",
    "R_100",
]

SYMBOL_NAMES = {
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
# ==================================================
# CONFIGURATION TELEGRAM
# ==================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()

TELEGRAM_TIMEOUT = 15
TELEGRAM_MAX_RETRIES = 2

TELEGRAM_API_URL = (
    "https://api.telegram.org/bot"
    + TELEGRAM_BOT_TOKEN
    + "/sendMessage"
)


# ==================================================
# CONFIGURATION DES DELAIS
# ==================================================

REQUEST_DELAY = 1
SYMBOL_DELAY = 1
# ==================================================
# CONFIGURATION DES JOURNAUX
# ==================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

LOGGER = logging.getLogger(APP_NAME)


def log(message, level="INFO"):
    """Enregistre un message dans les journaux."""
    level = str(level).upper()

    if level == "ERROR":
        LOGGER.error(message)
    elif level == "WARNING":
        LOGGER.warning(message)
    elif level == "DEBUG":
        LOGGER.debug(message)
    else:
        LOGGER.info(message)
        # ==================================================
# INFORMATIONS AU DEMARRAGE
# ==================================================

def print_startup_information():
    """Affiche la configuration du programme."""

    log("=" * 45)
    log(APP_NAME + " — ANALYSE AUTOMATIQUE")
    log("=" * 45)

    log("Timeframes : D1 / H4 / H2 / H1")
    log("Minimum de bougies par timeframe : "
        + str(MIN_CANDLES))

    log("Nombre d'indices : " + str(len(SYMBOLS)))
    log("DRY_RUN : " + str(DRY_RUN))

    log("Alertes Telegram : "
        + str(ENABLE_TELEGRAM_ALERTS))

    log("Execution automatique des ordres : "
        + "DESACTIVEE")

    log("=" * 45)
    # ==================================================
# VERIFICATION DE LA CONFIGURATION
# ==================================================

def validate_configuration():
    """Verifie la configuration avant l'analyse."""

    errors = []

    if not SYMBOLS:
        errors.append("Aucun indice configure.")

    if MIN_CANDLES < 200:
        errors.append(
            "Le nombre minimum de bougies doit etre "
            "au moins egal a 200."
        )

    if ENABLE_TELEGRAM_ALERTS:
        if not TELEGRAM_BOT_TOKEN:
            errors.append(
                "Token Telegram absent."
            )

        if not TELEGRAM_CHAT_ID:
            errors.append(
                "Identifiant du chat Telegram absent."
            )

    if errors:
        for error in errors:
            log(error, "ERROR")
        return False

    log("Configuration valide.")
    return True
    # ==================================================
# IMPORTATION DU MODULE DERIV
# ==================================================

try:
    from deriv_market import (
        get_candles,
        get_current_price,
    )

    DERIV_MODULE_READY = True
    log("Module Deriv charge.")

except Exception as error:
    DERIV_MODULE_READY = False

    log(
        "Erreur de chargement du module Deriv : "
        + str(error),
        "ERROR",
    )


# ==================================================
# IMPORTATION DU MODULE STRATEGIE
# ==================================================

try:
    from strategy import (
        find_signals,
        format_message,
    )

    STRATEGY_MODULE_READY = True
    log("Module strategie charge.")

except Exception as error:
    STRATEGY_MODULE_READY = False

    log(
        "Erreur de chargement du module strategie : "
        + str(error),
        "ERROR",
        )
    # ==================================================
# VERIFICATION DES VALEURS NUMERIQUES
# ==================================================

import math


def is_valid_number(value):
    """Verifie qu'une valeur est numerique et finie."""

    try:
        number = float(value)

        if not math.isfinite(number):
            return False

        return True

    except (TypeError, ValueError, OverflowError):
        return False


# ==================================================
# VALIDATION DES BOUGIES
# ==================================================

def validate_candles(candles, timeframe, symbol):
    """Verifie les donnees recues avant leur analyse."""

    if not isinstance(candles, list):
        log(
            f"{symbol} {timeframe} : donnees invalides.",
            "WARNING",
        )
        return None

    if len(candles) < MIN_CANDLES:
        log(
            f"{symbol} {timeframe} : "
            f"{len(candles)} bougies recues, "
            f"{MIN_CANDLES} necessaires.",
            "WARNING",
        )
        return None
        validated.sort(key=lambda item: item["epoch"])

    if len(validated) < MIN_CANDLES:
        log(
            f"{symbol} {timeframe} : seulement "
            f"{len(validated)} bougies valides.",
            "WARNING",
        )
        return None

    return validated


# ==================================================
# RECUPERATION DES BOUGIES
# ==================================================

def fetch_timeframe_candles(
    symbol,
    timeframe,
    granularity,
):
    """Recupere et valide les bougies d'une unite de temps."""

    if not DERIV_MODULE_READY:
        log("Module Deriv indisponible.", "ERROR")
        return None

    try:
        candles = get_candles(
            symbol,
            granularity,
            count=MIN_CANDLES,
        )

        return validate_candles(
            candles,
            timeframe,
            symbol,
        )

    except Exception as error:
        log(
            f"Erreur bougies {symbol} {timeframe} : "
            f"{error}",
            "WARNING",
        )
        return None
        # ==================================================
# RECUPERATION DU PRIX ACTUEL
# ==================================================

def fetch_current_price(symbol):
    """Recupere le dernier prix connu de l'indice."""

    if not DERIV_MODULE_READY:
        return None

    try:
        price = get_current_price(symbol)

        if not is_valid_number(price):
            log(
                f"{symbol} : prix actuel invalide.",
                "WARNING",
            )
            return None

        price = float(price)

        if price <= 0:
            log(
                f"{symbol} : prix non positif.",
                "WARNING",
            )
            return None

        return price

    except Exception as error:
        log(
            f"Erreur prix actuel {symbol} : {error}",
            "WARNING",
        )
        return None
        # ==================================================
# RECUPERATION DES DONNEES MULTI-TIMEFRAMES
# ==================================================

def fetch_market_data(symbol):
    """Recupere les donnees D1, H4, H2 et H1."""

    market_data = {}

    for timeframe, granularity in TIMEFRAMES.items():
        log(
            f"{symbol} : recuperation des bougies "
            f"{timeframe}."
        )

        candles = fetch_timeframe_candles(
            symbol,
            timeframe,
            granularity,
        )

        if candles is None:
            log(
                f"{symbol} : analyse abandonnee, "
                f"donnees {timeframe} insuffisantes.",
                "WARNING",
            )
            return None

        market_data[timeframe] = candles

        time.sleep(REQUEST_DELAY)

    current_price = fetch_current_price(symbol)

    if current_price is None:
        log(
            f"{symbol} : prix actuel indisponible.",
            "WARNING",
        )
        return None

    market_data["current_price"] = current_price
    market_data["symbol"] = symbol

    return market_data
    # ==================================================
# VERIFICATION DE TELEGRAM
# ==================================================

def telegram_is_ready():
    """Verifie si les alertes Telegram sont configurées."""

    if not ENABLE_TELEGRAM_ALERTS:
        log("Alertes Telegram desactivees.")
        return False

    if not TELEGRAM_BOT_TOKEN:
        log("Token Telegram manquant.", "ERROR")
        return False

    if not TELEGRAM_CHAT_ID:
        log("Chat ID Telegram manquant.", "ERROR")
        return False

    return True


# ==================================================
# ENVOI D'UN MESSAGE TELEGRAM
# ==================================================

def send_telegram_message(message):
    """Envoie une alerte Telegram avec plusieurs tentatives."""

    if not telegram_is_ready():
        return False

    if not isinstance(message, str) or not message.strip():
        log("Message Telegram vide ou invalide.", "WARNING")
        return False
        payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    for attempt in range(1, TELEGRAM_MAX_RETRIES + 2):
        try:
            response = requests.post(
                TELEGRAM_API_URL,
                json=payload,
                timeout=TELEGRAM_TIMEOUT,
            )

            response.raise_for_status()
            result = response.json()

            if result.get("ok") is True:
                log("Message Telegram envoye.")
                return True

            log(
                "Telegram a refuse le message : "
                + str(result),
                "WARNING",
            )

        except Exception as error:
            log(
                f"Tentative Telegram {attempt} : {error}",
                "WARNING",
            )

        if attempt <= TELEGRAM_MAX_RETRIES:
            time.sleep(2)

    log("Echec definitif de l'envoi Telegram.", "ERROR")
    return False
    # ==================================================
# ANALYSE D'UN INDICE
# ==================================================

def analyze_symbol(symbol):
    """Recupere les donnees et recherche des signaux."""

    if not STRATEGY_MODULE_READY:
        log("Module strategie indisponible.", "ERROR")
        return []

    log("-" * 40)
    log(f"Debut de l'analyse : {symbol}")

    market_data = fetch_market_data(symbol)

    if market_data is None:
        log(
            f"{symbol} : donnees insuffisantes.",
            "WARNING",
        )
        return []

    log(f"{symbol} : donnees recuperees.")

    try:
        signals = find_signals(symbol, market_data)

        if signals is None:
            return []

        if isinstance(signals, dict):
            signals = [signals]

        if not isinstance(signals, list):
            log(
                f"{symbol} : format de signaux invalide.",
                "WARNING",
            )
            return []

        log(
            f"{symbol} : {len(signals)} signal(aux) detecte(s)."
        )

        return signals

    except Exception as error:
        log(
            f"Erreur d'analyse pour {symbol} : {error}",
            "ERROR",
        )
        return []
        # ==================================================
# PREPARATION DU MESSAGE D'ALERTE
# ==================================================

def prepare_signal_message(signal):
    """Formate un signal pour Telegram."""

    if not isinstance(signal, dict):
        log("Signal invalide : dictionnaire attendu.", "WARNING")
        return None

    try:
        message = format_message(signal)

        if not isinstance(message, str):
            log(
                "Le formatage du signal n'a pas "
                "produit de texte.",
                "WARNING",
            )
            return None

        if not message.strip():
            log("Message de signal vide.", "WARNING")
            return None

        return message

    except Exception as error:
        log(
            "Erreur de formatage du signal : "
            + str(error),
            "ERROR",
        )
        return None
        # ==================================================
# TRAITEMENT DES SIGNAUX
# ==================================================

def process_signals(symbol, signals):
    """Traite les signaux detectes et envoie les alertes."""

    if not signals:
        log(f"{symbol} : aucun signal exploitable.")
        return 0

    sent_count = 0

    for signal in signals:
        if not isinstance(signal, dict):
            log("Signal ignore : format invalide.", "WARNING")
            continue

        message = prepare_signal_message(signal)

        if message is None:
            continue

        log(f"{symbol} : signal prepare.")

        if send_telegram_message(message):
            sent_count += 1

        time.sleep(REQUEST_DELAY)

    log(
        f"{symbol} : {sent_count} alerte(s) envoyee(s)."
    )

    return sent_count
    # ==================================================
# ANALYSE COMPLETE DES INDICES
# ==================================================

def run_analysis():
    """Lance l'analyse de tous les indices configures."""

    print_startup_information()

    if not validate_configuration():
        log(
            "Configuration invalide. "
            "Analyse interrompue.",
            "ERROR",
        )
        return False

    if not DERIV_MODULE_READY:
        log(
            "Module Deriv indisponible. "
            "Analyse impossible.",
            "ERROR",
        )
        return False

    if not STRATEGY_MODULE_READY:
        log(
            "Module strategie indisponible. "
            "Analyse impossible.",
            "ERROR",
        )
        return False

    total_signals = 0
    analyzed_symbols = 0
    failed_symbols = 0

    log("Debut du cycle d'analyse.")
    for index, symbol in enumerate(SYMBOLS, start=1):
        symbol_name = SYMBOL_NAMES.get(symbol, symbol)

        log(
            f"[{index}/{len(SYMBOLS)}] "
            f"Analyse de {symbol_name} ({symbol})."
        )

        try:
            signals = analyze_symbol(symbol)

            if signals is None:
                signals = []

            if signals:
                total_signals += process_signals(
                    symbol,
                    signals,
                )

            analyzed_symbols += 1

        except Exception as error:
            failed_symbols += 1

            log(
                f"Erreur pendant l'analyse de {symbol} : "
                f"{error}",
                "ERROR",
            )

            log(traceback.format_exc(), "DEBUG")

        if index < len(SYMBOLS):
            time.sleep(SYMBOL_DELAY)
            log("=" * 45)
    log("RESUME DU CYCLE D'ANALYSE")
    log(f"Indices configures : {len(SYMBOLS)}")
    log(f"Indices analyses : {analyzed_symbols}")
    log(f"Indices en erreur : {failed_symbols}")
    log(f"Alertes envoyees : {total_signals}")
    log("Execution automatique des ordres : DESACTIVEE")
    log("=" * 45)

    return failed_symbols == 0


# ==================================================
# POINT D'ENTREE DU PROGRAMME
# ==================================================

def main():
    """Point d'entree principal."""

    try:
        success = run_analysis()

        if success:
            log("Cycle d'analyse termine.")
            return 0

        log(
            "Cycle termine avec des erreurs.",
            "WARNING",
        )
        return 1

    except KeyboardInterrupt:
        log("Analyse interrompue manuellement.", "WARNING")
        return 130
        # ==================================================
# LANCEMENT DU PROGRAMME
# ==================================================

if __name__ == "__main__":
    sys.exit(main())
        
        
