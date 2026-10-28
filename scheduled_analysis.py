"""
TRADER AI PRO - Analyse automatique Deriv.

- Analyse multi-timeframe : D1, H4, H1 et M30.
- Envoie des alertes Telegram uniquement si le mode test est désactivé.
- N'exécute aucun ordre de trading.
"""

import os
import time
import requests

from deriv_market import get_candles
from strategy import find_signals, format_message


# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# Le mode test reste actif sauf si DRY_RUN vaut exactement "false".
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() != "false"

CANDLE_COUNT = 100
TIMEFRAMES = ("D1", "H4", "H1", "M30")

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

REQUEST_TIMEOUT = 15
PAUSE_BETWEEN_SYMBOLS = 1


# ============================================================
# JOURNALISATION
# ============================================================

def log(message):
    """Affiche un message avec l'heure UTC."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    print(f"[{timestamp} UTC] {message}", flush=True)


# ============================================================
# RECUPERATION DES BOUGIES
# ============================================================

def fetch_candles(symbol, timeframe):
    """Recupere et valide les bougies d'un actif."""
    try:
        response = get_candles(
            symbol,
            timeframe,
            count=CANDLE_COUNT,
        )
    except Exception as exc:
        log(
            f"[ERREUR] Recuperation {symbol} "
            f"{timeframe}: {type(exc).__name__}: {exc}"
        )
        return []

    if isinstance(response, dict):
        error = response.get("error")

        if error:
            log(f"[ERREUR] {symbol} {timeframe}: {error}")

        candles = response.get("candles", [])
    elif isinstance(response, list):
        candles = response
    else:
        log(
            f"[ERREUR] Reponse inattendue pour "
            f"{symbol} {timeframe}: {type(response).__name__}"
        )
        return []

    if not isinstance(candles, list):
        log(f"[ERREUR] Liste de bougies invalide : {symbol} {timeframe}")
        return []

    if len(candles) < 30:
        log(
            f"[INFO] Pas assez de bougies pour "
            f"{symbol} {timeframe}: {len(candles)}"
        )
        return []

    return candles


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    """Envoie une alerte Telegram si le mode test est desactive."""
    if DRY_RUN:
        log("[MODE TEST] Alerte non envoyee :")
        log(message)
        return False

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log(
            "[ERREUR] TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID "
            "manquant dans les secrets."
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            log(
                f"[ERREUR TELEGRAM] HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
            return False

        result = response.json()

        if not result.get("ok", False):
            log(f"[ERREUR TELEGRAM] {result}")
            return False

        log("[OK] Alerte Telegram envoyee.")
        return True

    except (requests.RequestException, ValueError) as exc:
        log(f"[ERREUR TELEGRAM] {type(exc).__name__}: {exc}")
        return False


# ============================================================
# ANALYSE D'UN ACTIF
# ============================================================

def analyze_symbol(symbol):
    """Analyse un actif sur les quatre unites de temps."""
    log(f"Debut de l'analyse : {symbol}")

    market_data = {}

    for timeframe in TIMEFRAMES:
        candles = fetch_candles(symbol, timeframe)

        if not candles:
            log(
                f"[INFO] Analyse ignoree pour {symbol} : "
                f"donnees {timeframe} indisponibles."
            )
            return 0

        market_data[timeframe] = candles

    try:
        signals = find_signals(
            symbol=symbol,
            d1=market_data["D1"],
            h4=market_data["H4"],
            h1=market_data["H1"],
            m30=market_data["M30"],
        )
    except Exception as exc:
        log(
            f"[ERREUR] Analyse de {symbol}: "
            f"{type(exc).__name__}: {exc}"
        )
        return 0

    if not signals:
        log(f"Aucun signal confirme pour {symbol}.")
        return 0

    if isinstance(signals, dict):
        signals = [signals]

    sent_count = 0

    for signal in signals:
        if not isinstance(signal, dict):
            log(f"[AVERTISSEMENT] Signal invalide pour {symbol}.")
            continue

        try:
            message = format_message(signal)
        except Exception as exc:
            log(
                f"[ERREUR] Formatage du signal {symbol}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        log(f"[SIGNAL] Signal detecte pour {symbol}.")

        if send_telegram(message):
            sent_count += 1

    return sent_count


# ============================================================
# LANCEMENT GENERAL
# ============================================================

def main():
    """Execute un cycle complet d'analyse."""
    log("=" * 55)
    log("TRADER AI PRO - DEMARRAGE")
    log(f"Mode test : {'ACTIVE' if DRY_RUN else 'DESACTIVE'}")
    log(f"Nombre d'actifs : {len(SYMBOLS)}")
    log(f"Unites de temps : {', '.join(TIMEFRAMES)}")
    log("=" * 55)

    total_signals_sent = 0
    successful_analyses = 0
    failed_analyses = 0

    for index, symbol in enumerate(SYMBOLS):
        try:
            sent = analyze_symbol(symbol)
            total_signals_sent += sent
            successful_analyses += 1

        except Exception as exc:
            failed_analyses += 1
            log(
                f"[ERREUR INATTENDUE] {symbol}: "
                f"{type(exc).__name__}: {exc}"
            )

        if index < len(SYMBOLS) - 1:
            time.sleep(PAUSE_BETWEEN_SYMBOLS)

    log("=" * 55)
    log("TRADER AI PRO - FIN DU CYCLE")
    log(f"Actifs traites : {successful_analyses}")
    log(f"Erreurs inattendues : {failed_analyses}")
    log(f"Alertes Telegram envoyees : {total_signals_sent}")

    if DRY_RUN:
        log("Mode test actif : aucune alerte Telegram reelle envoyee.")

    log("=" * 55)


if __name__ == "__main__":
    main()
