"""TRADER AI PRO - analyse multi-unites et alertes Telegram.

D1 : contexte general.
H4 : direction de la structure.
H1 : detection du setup.
M30 : confirmation.

Aucun ordre n'est execute.
Le mode test est actif par defaut.
"""

import os
import logging
import requests

from deriv_market import get_candles
from strategy import find_signals, format_message

--------------------------------------------------

CONFIGURATION

--------------------------------------------------

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

La securite prime : seul DRY_RUN=false active l'envoi Telegram.

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

--------------------------------------------------

DONNEES DE MARCHE

--------------------------------------------------

def fetch_candles(symbol, timeframe):
"""Recupere et verifie les bougies d'un actif."""

try:
    result = get_candles(
        symbol,
        timeframe=timeframe,
        count=CANDLE_COUNT,
    )
except Exception as exc:
    logging.error(
        "%s %s : erreur de recuperation (%s)",
        symbol,
        timeframe,
        type(exc).__name__,
    )
    return []

if not isinstance(result, dict):
    logging.error(
        "%s %s : reponse inattendue du fournisseur.",
        symbol,
        timeframe,
    )
    return []

candles = result.get("candles", [])

if not isinstance(candles, list):
    logging.error(
        "%s %s : format de bougies invalide.",
        symbol,
        timeframe,
    )
    return []

if result.get("error"):
    logging.warning(
        "%s %s : %s",
        symbol,
        timeframe,
        result.get("error"),
    )
    return []

if not candles:
    logging.warning(
        "%s %s : aucune bougie disponible.",
        symbol,
        timeframe,
    )
    return []

logging.info(
    "%s %s : %s bougies recues.",
    symbol,
    timeframe,
    len(candles),
)

return candles

--------------------------------------------------

TELEGRAM

--------------------------------------------------

def send_telegram(message):
"""Envoie un message uniquement si le mode test est desactive."""

if DRY_RUN:
    logging.info(
        "MODE TEST : aucun message Telegram envoye.\n%s",
        message,
    )
    return False

if not TOKEN or not CHAT_ID:
    logging.error(
        "Envoi impossible : TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID "
        "manquant dans les variables d'environnement."
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
        logging.error(
            "Telegram a refuse le message."
        )
        return False

    logging.info("Message Telegram envoye avec succes.")
    return True

except requests.RequestException as exc:
    # Ne jamais afficher le token dans les journaux.
    logging.error(
        "Erreur d'envoi Telegram : %s",
        type(exc).__name__,
    )
    return False

except ValueError:
    logging.error("Reponse Telegram invalide.")
    return False

--------------------------------------------------

ANALYSE D'UN ACTIF

--------------------------------------------------

def analyze_symbol(symbol):
"""Analyse un actif sur D1, H4, H1 et M30."""

logging.info("=" * 55)
logging.info("DEBUT ANALYSE : %s", symbol)

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

# La derniere cloture M30 sert de prix de reference.
try:
    price_now = float(market["M30"][-1]["close"])
except (KeyError, TypeError, ValueError, IndexError):
    logging.warning(
        "%s : impossible de determiner le prix M30.",
        symbol,
    )
    return []

signals, logs = find_signals(
    symbol=symbol,
    d1=market["D1"],
    h4=market["H4"],
    h1=market["H1"],
    m30=market["M30"],
    price_now=price_now,
)

for entry in logs:
    logging.info("%s", entry)

if not signals:
    logging.info("%s : aucun signal exploitable.", symbol)
    return []

valid_signals = []

for signal in signals:
    if not isinstance(signal, dict):
        continue

    try:
        message = format_message(signal)
    except (KeyError, TypeError, ValueError) as exc:
        logging.error(
            "%s : formatage du signal impossible (%s).",
            symbol,
            type(exc).__name__,
        )
        continue

    logging.info(
        "%s : signal %s valide.",
        symbol,
        signal.get("direction", "INCONNUE"),
    )

    send_telegram(message)
    valid_signals.append(signal)

return valid_signals

--------------------------------------------------

EXECUTION GENERALE

--------------------------------------------------

def main():
logging.info("TRADER AI PRO - demarrage")
logging.info(
"Mode : %s",
"TEST (aucun envoi Telegram)"
if DRY_RUN
else "ENVOI TELEGRAM ACTIVE",
)

if not DRY_RUN and (not TOKEN or not CHAT_ID):
    logging.error(
        "Configuration incomplete : ajoute TELEGRAM_TOKEN et "
        "TELEGRAM_CHAT_ID aux secrets avant de lancer le bot."
    )
    return

total_signals = 0
seen_keys = set()

for symbol in SYMBOLS:
    try:
        signals = analyze_symbol(symbol)

        for signal in signals:
            key = signal.get("key")

            # Evite les doublons pour un meme signal durant cette execution.
            if key and key in seen_keys:
                logging.info(
                    "%s : doublon ignore pendant cette execution.",
                    symbol,
                )
                continue

            if key:
                seen_keys.add(key)

            total_signals += 1

    except Exception as exc:
        # Un actif en erreur ne doit pas interrompre toute l'analyse.
        logging.exception(
            "%s : erreur inattendue (%s).",
            symbol,
            type(exc).__name__,
        )

logging.info("-" * 55)
logging.info("ANALYSE TERMINEE")
logging.info("Nombre de signaux valides : %s", total_signals)

if DRY_RUN:
    logging.info(
        "Mode test : aucun signal n'a ete envoye sur Telegram."
    )

if name == "main":
main()
