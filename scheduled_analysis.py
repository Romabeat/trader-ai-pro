"""TRADER AI PRO - Analyse automatique multi-timeframes.

D1 : contexte general.
H4 : direction de la structure.
H1 : setup.
M30 : confirmation.

Ce programme genere des alertes indicatives.
Il n'execute aucun ordre de trading.
"""

import os
import logging
import requests

from deriv_market import get_candles
from strategy import find_signals, format_message

==================================================

CONFIGURATION

==================================================

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

Le mode test reste actif sauf si DRY_RUN vaut exactement "false".

DRY_RUN = (
os.environ.get("DRY_RUN", "true").strip().lower() != "false"
)

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

TIMEFRAMES = ("D1", "H4", "H1", "M30")

CANDLE_COUNT = 100
REQUEST_TIMEOUT = 15

logging.basicConfig(
level=logging.INFO,
format="%(asctime)s | %(levelname)s | %(message)s",
)

==================================================

RECUPERATION DES BOUGIES

==================================================

def fetch_candles(symbol, timeframe):
"""Recupere les bougies d'un actif et d'une unite de temps."""

try:
    result = get_candles(
        symbol,
        timeframe=timeframe,
        count=CANDLE_COUNT,
    )

except Exception as exc:
    logging.error(
        "%s %s : erreur de recuperation (%s).",
        symbol,
        timeframe,
        type(exc).__name__,
    )
    return []

if not isinstance(result, dict):
    logging.error(
        "%s %s : reponse invalide du fournisseur.",
        symbol,
        timeframe,
    )
    return []

if result.get("error"):
    logging.warning(
        "%s %s : recuperation impossible (%s).",
        symbol,
        timeframe,
        result.get("error"),
    )
    return []

candles = result.get("candles")

if not isinstance(candles, list) or not candles:
    logging.warning(
        "%s %s : aucune bougie disponible.",
        symbol,
        timeframe,
    )
    return []

logging.info(
    "%s %s : %d bougies recues.",
    symbol,
    timeframe,
    len(candles),
)

return candles

==================================================

ENVOI TELEGRAM

==================================================

def send_telegram(message):
"""Envoie une alerte uniquement hors mode test."""

if DRY_RUN:
    logging.info(
        "MODE TEST : message non envoye sur Telegram.\n%s",
        message,
    )
    return False

if not TOKEN or not CHAT_ID:
    logging.error(
        "Envoi impossible : secrets Telegram manquants."
    )
    return False

url = "https://api.telegram.org/bot%s/sendMessage" % TOKEN

try:
    response = requests.post(
        url,
        json={
            "chat_id": CHAT_ID,
            "text": message,
        },
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()
    data = response.json()

    if not data.get("ok"):
        logging.error("Telegram a refuse le message.")
        return False

    logging.info("Alerte Telegram envoyee.")
    return True

except requests.RequestException as exc:
    # Ne jamais afficher l'URL contenant le token.
    logging.error(
        "Echec de l'envoi Telegram (%s).",
        type(exc).__name__,
    )
    return False

except ValueError:
    logging.error("Reponse Telegram invalide.")
    return False

==================================================

ANALYSE D'UN ACTIF

==================================================

def analyze_symbol(symbol):
"""Analyse un actif sur D1, H4, H1 et M30."""

logging.info("=" * 55)
logging.info("ANALYSE DE %s", symbol)

market = {}

for timeframe in TIMEFRAMES:
    candles = fetch_candles(symbol, timeframe)

    if not candles:
        logging.warning(
            "%s : analyse abandonnee, donnees %s indisponibles.",
            symbol,
            timeframe,
        )
        return []

    market[timeframe] = candles

try:
    price_now = float(market["M30"][-1]["close"])

except (KeyError, TypeError, ValueError, IndexError):
    logging.warning(
        "%s : prix de reference M30 invalide.",
        symbol,
    )
    return []

try:
    signals, messages = find_signals(
        symbol=symbol,
        d1=market["D1"],
        h4=market["H4"],
        h1=market["H1"],
        m30=market["M30"],
        price_now=price_now,
    )

except Exception as exc:
    logging.exception(
        "%s : erreur pendant l'analyse (%s).",
        symbol,
        type(exc).__name__,
    )
    return []

for message in messages:
    logging.info("%s", message)

if not signals:
    logging.info("%s : aucun signal valide.", symbol)
    return []

return [
    signal
    for signal in signals
    if isinstance(signal, dict)
]

==================================================

EXECUTION GENERALE

==================================================

def main():
"""Lance une analyse de tous les actifs configures."""

logging.info("=" * 55)
logging.info("TRADER AI PRO - DEMARRAGE")

if DRY_RUN:
    logging.info(
        "MODE TEST ACTIF : aucun message ne sera envoye."
    )
else:
    logging.warning(
        "MODE ENVOI ACTIF : les signaux valides pourront "
        "etre envoyes sur Telegram."
    )

    if not TOKEN or not CHAT_ID:
        logging.error(
            "Configuration Telegram incomplete. "
            "Verifie les secrets TELEGRAM_TOKEN et TELEGRAM_CHAT_ID."
        )
        return

# Cette memoire ne dure que pendant l'execution courante.
seen_keys = set()

total_signals = 0
total_sent = 0

for symbol in SYMBOLS:
    try:
        signals = analyze_symbol(symbol)

        for signal in signals:
            key = signal.get("key")

            # Le doublon est verifie AVANT tout envoi.
            if key and key in seen_keys:
                logging.info(
                    "%s : doublon ignore pendant cette execution.",
                    symbol,
                )
                continue

            if key:
                seen_keys.add(key)

            try:
                message = format_message(signal)

            except (KeyError, TypeError, ValueError) as exc:
                logging.error(
                    "%s : formatage impossible (%s).",
                    symbol,
                    type(exc).__name__,
                )
                continue

            total_signals += 1

            logging.info(
                "%s : signal %s detecte.",
                symbol,
                signal.get("direction", "INCONNUE"),
            )

            if send_telegram(message):
                total_sent += 1

    except Exception as exc:
        # Une erreur sur un actif ne bloque pas les autres.
        logging.exception(
            "%s : erreur inattendue (%s).",
            symbol,
            type(exc).__name__,
        )

logging.info("=" * 55)
logging.info("ANALYSE TERMINEE")
logging.info("Signaux valides : %d", total_signals)
logging.info("Messages Telegram envoyes : %d", total_sent)

if DRY_RUN:
    logging.info(
        "Mode test termine : aucun message Telegram envoye."
    )

if name == "main":
main()
