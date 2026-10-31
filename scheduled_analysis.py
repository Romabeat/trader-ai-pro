"""
TRADER AI PRO
Analyse automatique multi-timeframe
Strategie : Supports, Resistances et Trendlines
Alertes Telegram uniquement
Aucune execution automatique des ordres
"""

# ============================================================
# 1. IMPORTATIONS
# ============================================================

import os
import sys
import time
import logging
import traceback
import requests

from datetime import datetime, timezone

from strategy import (
    STRATEGY_NAME,
    MIN_CANDLES,
    find_signals,
    format_message,
)


# ============================================================
# 2. CONFIGURATION GENERALE
# ============================================================

DRY_RUN = os.getenv(
    "DRY_RUN",
    "true"
).lower() == "true"

ENABLE_TELEGRAM_ALERTS = os.getenv(
    "ENABLE_TELEGRAM_ALERTS",
    "true"
).lower() == "true"

# Securite : le trading automatique reste interdit.
ENABLE_AUTO_TRADING = False

MAX_RETRIES = 3
RETRY_DELAY = 3

SYMBOL_DELAY = 1
REQUEST_TIMEOUT = 20


# ============================================================
# 3. CONFIGURATION DES UNITES DE TEMPS
# ============================================================

TIMEFRAMES = {
    "D1": {
        "granularity": 86400,
        "candles": 200,
    },

    "H4": {
        "granularity": 14400,
        "candles": 200,
    },

    "H2": {
        "granularity": 7200,
        "candles": 200,
    },

    "H1": {
        "granularity": 3600,
        "candles": 200,
    },
}


# ============================================================
# 4. INDICES A ANALYSER
# ============================================================

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


# ============================================================
# 5. CONFIGURATION TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# 6. CONFIGURATION DES JOURNAUX
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("TRADER_AI_PRO")


# ============================================================
# 7. INFORMATIONS SUR L'EXECUTION
# ============================================================

def get_runtime_information():

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version.split()[0],
        "strategy": STRATEGY_NAME,
        "symbols_count": len(SYMBOLS),
        "timeframes": list(TIMEFRAMES.keys()),
        "dry_run": DRY_RUN,
        "telegram_enabled": ENABLE_TELEGRAM_ALERTS,
        "auto_trading": ENABLE_AUTO_TRADING,
    }


# ============================================================
# 8. AFFICHAGE DES INFORMATIONS DE DEMARRAGE
# ============================================================

def print_startup_information():

    info = get_runtime_information()

    logger.info("=" * 60)
    logger.info("TRADER AI PRO - DEMARRAGE")
    logger.info("=" * 60)

    logger.info(
        "Date UTC : %s",
        info["timestamp"],
    )

    logger.info(
        "Version Python : %s",
        info["python_version"],
    )

    logger.info(
        "Strategie : %s",
        info["strategy"],
    )

    logger.info(
        "Nombre d'indices : %s",
        info["symbols_count"],
    )

    logger.info(
        "Unites de temps : D1 / H4 / H2 / H1"
    )

    logger.info(
        "Bougies minimum : 200 par unite de temps"
    )

    logger.info(
        "DRY_RUN : %s",
        DRY_RUN,
    )

    logger.info(
        "Alertes Telegram : %s",
        ENABLE_TELEGRAM_ALERTS,
    )

    logger.info(
        "Execution automatique : DESACTIVEE"
    )

    logger.info("=" * 60)
    # ============================================================
# 14. VERIFICATION DE LA CONFIGURATION TELEGRAM
# ============================================================

def telegram_is_ready():

    if not ENABLE_TELEGRAM_ALERTS:
        logger.warning(
            "Les alertes Telegram sont desactivees."
        )
        return False

    if not TELEGRAM_BOT_TOKEN:
        logger.error(
            "TELEGRAM_BOT_TOKEN absent des secrets GitHub."
        )
        return False

    if not TELEGRAM_CHAT_ID:
        logger.error(
            "TELEGRAM_CHAT_ID absent des secrets GitHub."
        )
        return False

    return True


# ============================================================
# 15. ENVOI D'UN MESSAGE TELEGRAM
# ============================================================

def send_telegram_message(message):

    if not telegram_is_ready():
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        result = response.json()

        if not result.get("ok", False):

            logger.error(
                "Telegram a refuse le message : %s",
                result,
            )

            return False

        logger.info(
            "Message Telegram envoye avec succes."
        )

        return True

    except requests.RequestException as error:

        logger.error(
            "Erreur d'envoi Telegram : %s",
            error,
        )

        return False

    except ValueError as error:

        logger.error(
            "Reponse Telegram invalide : %s",
            error,
        )

        return False


# ============================================================
# 16. ANALYSE D'UN INDICE
# ============================================================

def analyze_symbol(symbol):

    logger.info("")
    logger.info("=" * 55)

    logger.info(
        "ANALYSE DE L'INDICE : %s",
        symbol,
    )

    logger.info("=" * 55)

    diagnostics = {}

    try:

        market_data = fetch_market_data(symbol)

        if market_data is None:

            logger.warning(
                "%s : donnees de marche indisponibles.",
                symbol,
            )

            return []

        signals = find_signals(
            symbol=symbol,
            d1_candles=market_data["d1"],
            h4_candles=market_data["h4"],
            h2_candles=market_data["h2"],
            h1_candles=market_data["h1"],
            price_now=market_data["price_now"],
            diagnostics=diagnostics,
        )

        logger.info(
            "%s | Statut analyse : %s",
            symbol,
            diagnostics.get("status", "INCONNU"),
        )

        if diagnostics.get("error"):

            logger.error(
                "%s | Erreur strategie : %s",
                symbol,
                diagnostics["error"],
            )

        logger.info(
            "%s | Nombre de signaux : %s",
            symbol,
            len(signals),
        )

        return signals

    except Exception:

        logger.error(
            "%s | Erreur pendant l'analyse :\n%s",
            symbol,
            traceback.format_exc(),
        )

        return []


# ============================================================
# 17. TRAITEMENT DES SIGNAUX
# ============================================================

def process_signals(signals):

    statistics = {
        "detected": len(signals),
        "sent": 0,
        "failed": 0,
    }

    if not signals:

        logger.info(
            "Aucun nouveau signal a envoyer."
        )

        return statistics

    for signal in signals:

        try:

            message = format_message(signal)

            logger.info(
                "Signal detecte : %s %s",
                signal.get("symbol"),
                signal.get("direction"),
            )

            if not ENABLE_TELEGRAM_ALERTS:

                logger.info(
                    "Telegram desactive : signal non envoye."
                )

                continue

            if send_telegram_message(message):
                statistics["sent"] += 1

            else:
                statistics["failed"] += 1

            time.sleep(1)

        except Exception:

            statistics["failed"] += 1

            logger.error(
                "Erreur pendant le traitement du signal :\n%s",
                traceback.format_exc(),
            )

    return statistics
    # ============================================================
# ANALYSE DE TOUS LES INDICES
# ============================================================

def analyze_all_symbols():
    results = {
        "symbols_total": len(SYMBOLS),
        "symbols_analyzed": 0,
        "symbols_failed": 0,
        "signals_detected": 0,
        "signals_sent": 0,
        "signals_failed": 0,
    }

    all_signals = []

    log("=" * 65)
    log("DÉBUT DE L'ANALYSE DES INDICES")
    log("=" * 65)

    for index, symbol in enumerate(SYMBOLS, start=1):
        log("")
        log(f"[{index}/{len(SYMBOLS)}] Analyse : {symbol}")

        try:
            signals = analyze_symbol(symbol)

            results["symbols_analyzed"] += 1

            if signals:
                all_signals.extend(signals)
                log(
                    f"{len(signals)} signal(aux) "
                    f"détecté(s) sur {symbol}"
                )
            else:
                log(f"Aucun signal valide sur {symbol}")

        except Exception as error:
            results["symbols_failed"] += 1
            log(
                f"ERREUR pendant l'analyse de {symbol} : "
                f"{error}",
                level="ERROR"
            )

    results["signals_detected"] = len(all_signals)

    log("")
    log("=" * 65)
    log("ANALYSE DES INDICES TERMINÉE")
    log("=" * 65)

    return all_signals, results


# ============================================================
# RÉSUMÉ FINAL
# ============================================================

def print_analysis_summary(results, start_time):
    duration = time.time() - start_time

    log("")
    log("=" * 65)
    log("RÉSUMÉ DE TRADER AI PRO")
    log("=" * 65)

    log(
        f"Indices prévus : "
        f"{results['symbols_total']}"
    )

    log(
        f"Indices analysés : "
        f"{results['symbols_analyzed']}"
    )

    log(
        f"Échecs d'analyse : "
        f"{results['symbols_failed']}"
    )

    log(
        f"Signaux détectés : "
        f"{results['signals_detected']}"
    )

    log(
        f"Alertes Telegram envoyées : "
        f"{results['signals_sent']}"
    )

    log(
        f"Échecs d'envoi Telegram : "
        f"{results['signals_failed']}"
    )

    log(
        f"Durée totale : "
        f"{duration:.2f} secondes"
    )

    log("=" * 65)


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():
    start_time = time.time()

    log("")
    log("=" * 65)
    log("TRADER AI PRO — SCANNER TECHNIQUE")
    log("=" * 65)

    log(f"Date de lancement : {time.strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Timeframes : {', '.join(TIMEFRAMES.keys())}")
    log(f"Bougies minimum : {MIN_CANDLES}")
    log(f"Nombre d'indices : {len(SYMBOLS)}")

    log(f"DRY_RUN : {DRY_RUN}")
    log("Exécution automatique des ordres : DÉSACTIVÉE")
    log("Mode : ALERTES UNIQUEMENT")
    log("")

    if ENABLE_TELEGRAM_ALERTS:
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
            log("Telegram : CONFIGURATION DÉTECTÉE")
        else:
            log(
                "Telegram activé mais secrets manquants.",
                level="WARNING"
            )
    else:
        log("Telegram : DÉSACTIVÉ")

    try:
        all_signals, results = analyze_all_symbols()

        if all_signals:
            log("")
            log(
                f"{len(all_signals)} signal(aux) "
                "à traiter."
            )

            process_signals(all_signals, results)
        else:
            log("")
            log("Aucun signal à envoyer.")

        print_analysis_summary(results, start_time)

        if results["symbols_analyzed"] == 0:
            log(
                "Aucun indice n'a pu être analysé.",
                level="ERROR"
            )
            return 1

        return 0

    except KeyboardInterrupt:
        log(
            "Arrêt demandé par l'utilisateur.",
            level="WARNING"
        )
        return 130

    except Exception as error:
        log(
            f"ERREUR GÉNÉRALE : {error}",
            level="ERROR"
        )
        return 1


# ============================================================
# POINT D'ENTRÉE
# ============================================================

if __name__ == "__main__":
    sys.exit(main())
