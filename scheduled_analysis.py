"""
TRADER AI PRO
Analyse automatique des indices synthetiques Deriv.

Timeframes : D1 / H4 / H2 / H1
Alertes : Telegram
Execution automatique : DESACTIVEE
Mode securite : DRY_RUN
"""

import os
import sys
import time
import math
import logging
import traceback
import requests

from typing import Any, Optional


# ============================================================
# CONFIGURATION GENERALE
# ============================================================

APP_NAME = "TRADER AI PRO"

DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() == "true"

ENABLE_TELEGRAM_ALERTS = (
    os.getenv("ENABLE_TELEGRAM_ALERTS", "true").strip().lower()
    == "true"
)

# Aucune execution automatique autorisee.
ENABLE_AUTO_TRADING = False

MIN_CANDLES = 200

TIMEFRAMES = {
    "D1": 86400,
    "H4": 14400,
    "H2": 7200,
    "H1": 3600,
}


# ============================================================
# INDICES DERIV
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


# ============================================================
# CONFIGURATION TELEGRAM
# ============================================================

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
    if TELEGRAM_BOT_TOKEN
    else ""
)

REQUEST_DELAY = 1
SYMBOL_DELAY = 1


# ============================================================
# JOURNALISATION
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | %(message)s"
    ),
    datefmt="%Y-%m-%d %H:%M:%S",
)

LOGGER = logging.getLogger(APP_NAME)


def log(message: str, level: str = "info") -> None:
    """Enregistre un message dans les logs."""

    method = getattr(LOGGER, level.lower(), LOGGER.info)
    method(message)


# ============================================================
# INFORMATIONS DE DEMARRAGE
# ============================================================

def print_startup_information() -> None:
    """Affiche la configuration generale du bot."""

    log("=" * 45)
    log("TRADER AI PRO — ANALYSE AUTOMATIQUE")
    log("=" * 45)

    log("Timeframes : D1 / H4 / H2 / H1")
    log(f"Minimum de bougies par timeframe : {MIN_CANDLES}")
    log(f"Nombre d'indices : {len(SYMBOLS)}")
    log(f"DRY_RUN : {DRY_RUN}")
    log(f"Alertes Telegram : {ENABLE_TELEGRAM_ALERTS}")
    log("Execution automatique des ordres : DESACTIVEE")

    log("=" * 45)
    # ============================================================
# VERIFICATION DE LA CONFIGURATION
# ============================================================

def validate_configuration() -> bool:
    """Verifie les parametres indispensables au fonctionnement."""

    valid = True

    if not DRY_RUN:
        log(
            "ERREUR : DRY_RUN doit obligatoirement etre True.",
            "error",
        )
        valid = False

    if ENABLE_AUTO_TRADING:
        log(
            "ERREUR : execution automatique interdite.",
            "error",
        )
        valid = False

    if ENABLE_TELEGRAM_ALERTS:
        if not TELEGRAM_BOT_TOKEN:
            log("Token Telegram absent.", "error")
            valid = False

        if not TELEGRAM_CHAT_ID:
            log("Chat ID Telegram absent.", "error")
            valid = False

    if valid:
        log("Configuration generale validee.")
    else:
        log("Configuration invalide.", "error")

    return valid


# ============================================================
# DIAGNOSTIC DES SECRETS
# ============================================================

def print_secret_status() -> None:
    """Affiche uniquement la presence des secrets."""

    token_present = bool(TELEGRAM_BOT_TOKEN)
    chat_present = bool(TELEGRAM_CHAT_ID)

    log(
        "Telegram token present : "
        + str(token_present)
    )

    log(
        "Telegram chat ID present : "
        + str(chat_present)
    )

    # Ne jamais afficher les valeurs des secrets.


# ============================================================
# CHARGEMENT DU MODULE DERIV
# ============================================================

try:
    from deriv_market import (
        get_candles,
        get_current_price,
    )

    DERIV_MODULE_READY = True

    log("Module Deriv charge.")

except Exception as exc:
    DERIV_MODULE_READY = False

    log(
        f"Erreur de chargement du module Deriv : {exc}",
        "error",
    )


# ============================================================
# CHARGEMENT DU MODULE STRATEGIE
# ============================================================

try:
    from strategy import (
        find_signals,
        format_message,
    )

    STRATEGY_MODULE_READY = True

    log("Module strategie charge.")

except Exception as exc:
    STRATEGY_MODULE_READY = False

    log(
        f"Erreur de chargement du module strategie : {exc}",
        "error",
    )


# ============================================================
# VERIFICATION DES MODULES
# ============================================================

def validate_modules() -> bool:
    """Verifie que les modules indispensables sont disponibles."""

    if not DERIV_MODULE_READY:
        log("Module Deriv indisponible.", "error")
        return False

    if not STRATEGY_MODULE_READY:
        log("Module strategie indisponible.", "error")
        return False

    log("Tous les modules sont charges.")

    return True


# ============================================================
# VALIDATION DES VALEURS NUMERIQUES
# ============================================================

def is_valid_number(value: Any) -> bool:
    """Verifie qu'une valeur est numerique et finie."""

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False

    return math.isfinite(number)


def is_positive_number(value: Any) -> bool:
    """Verifie qu'une valeur numerique est strictement positive."""

    if not is_valid_number(value):
        return False

    return float(value) > 0


# ============================================================
# VALIDATION DES BOUGIES
# ============================================================

def validate_candles(candles: Any) -> list:
    """Nettoie et valide une liste de bougies."""

    if not isinstance(candles, list):
        return []

    validated = []

    for candle in candles:

        if not isinstance(candle, dict):
            continue

        try:
            epoch = int(candle.get("epoch"))
            open_price = float(candle.get("open"))
            high = float(candle.get("high"))
            low = float(candle.get("low"))
            close = float(candle.get("close"))

        except (TypeError, ValueError, OverflowError):
            continue

        values = (
            open_price,
            high,
            low,
            close,
        )

        if not all(math.isfinite(value) for value in values):
            continue

        if min(values) <= 0:
            continue

        if high < low:
            continue

        if high < max(open_price, close):
            continue

        if low > min(open_price, close):
            continue

        validated.append({
            "epoch": epoch,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
        })

    validated.sort(key=lambda item: item["epoch"])

    # Suppression des doublons temporels.
    unique = {}

    for candle in validated:
        unique[candle["epoch"]] = candle

    result = list(unique.values())

    if len(result) < MIN_CANDLES:
        log(
            "Bougies insuffisantes : "
            f"{len(result)}/{MIN_CANDLES}.",
            "warning",
        )
        return []

    return result
    # ============================================================
# RECUPERATION DES BOUGIES PAR TIMEFRAME
# ============================================================

def fetch_timeframe_candles(
    symbol: str,
    timeframe: str,
) -> list:
    """Recupere et valide les bougies d'une unite de temps."""

    if timeframe not in TIMEFRAMES:
        log(
            f"{symbol} : timeframe invalide : {timeframe}",
            "error",
        )
        return []

    granularity = TIMEFRAMES[timeframe]

    try:
        raw_candles = get_candles(
            symbol,
            granularity,
            count=MIN_CANDLES,
        )

    except Exception as exc:
        log(
            f"{symbol} {timeframe} : erreur Deriv : {exc}",
            "error",
        )
        return []

    candles = validate_candles(raw_candles)

    if not candles:
        log(
            f"{symbol} {timeframe} : aucune donnee valide.",
            "warning",
        )
        return []

    log(
        f"{symbol} {timeframe} : "
        f"{len(candles)} bougies recuperees."
    )

    return candles


# ============================================================
# RECUPERATION DU PRIX ACTUEL
# ============================================================

def fetch_current_price(symbol: str) -> Optional[float]:
    """Recupere le dernier prix disponible sur Deriv."""

    try:
        price = get_current_price(symbol)

    except Exception as exc:
        log(
            f"{symbol} : erreur recuperation du prix : {exc}",
            "error",
        )
        return None

    if not is_positive_number(price):
        log(
            f"{symbol} : prix actuel invalide.",
            "warning",
        )
        return None

    return float(price)


# ============================================================
# RECUPERATION COMPLETE DES DONNEES
# ============================================================

def fetch_market_data(symbol: str) -> Optional[dict]:
    """Recupere les quatre timeframes et le prix actuel."""

    if symbol not in SYMBOLS:
        log(
            f"Symbole non autorise : {symbol}",
            "error",
        )
        return None

    market_data = {
        "symbol": symbol,
    }

    # Recuperation D1, H4, H2 et H1.
    for timeframe in ("D1", "H4", "H2", "H1"):

        candles = fetch_timeframe_candles(
            symbol,
            timeframe,
        )

        if len(candles) < MIN_CANDLES:
            log(
                f"{symbol} : analyse abandonnee, "
                f"donnees {timeframe} insuffisantes.",
                "warning",
            )
            return None

        market_data[timeframe] = candles

        time.sleep(REQUEST_DELAY)

    # Recuperation du prix actuel.
    current_price = fetch_current_price(symbol)

    if current_price is None:
        log(
            f"{symbol} : prix actuel indisponible.",
            "warning",
        )
        return None

    market_data["current_price"] = current_price

    log(
        f"{symbol} : donnees multi-timeframe complete."
    )

    return market_data


# ============================================================
# VERIFICATION DES DONNEES DE MARCHE
# ============================================================

def validate_market_data(market_data: dict) -> bool:
    """Verifie que toutes les donnees necessaires sont presentes."""

    if not isinstance(market_data, dict):
        return False

    if not is_positive_number(
        market_data.get("current_price")
    ):
        return False

    for timeframe in ("D1", "H4", "H2", "H1"):

        candles = market_data.get(timeframe)

        if not isinstance(candles, list):
            return False

        if len(candles) < MIN_CANDLES:
            return False

    return True


# ============================================================
# ANALYSE DES DONNEES D'UN SYMBOLE
# ============================================================

def analyze_symbol(symbol: str) -> list:
    """Recupere les donnees puis appelle la strategie."""

    log(
        f"Debut de l'analyse : "
        f"{SYMBOL_NAMES.get(symbol, symbol)}"
    )

    market_data = fetch_market_data(symbol)

    if market_data is None:
        return []

    if not validate_market_data(market_data):
        log(
            f"{symbol} : donnees de marche invalides.",
            "warning",
        )
        return []

    try:
        signals = find_signals(
            symbol,
            market_data,
        )

    except Exception as exc:
        log(
            f"{symbol} : erreur dans la strategie : {exc}",
            "error",
        )
        LOGGER.exception("Detail de l'erreur strategique.")
        return []

    if signals is None:
        return []

    if isinstance(signals, dict):
        signals = [signals]

    if not isinstance(signals, list):
        log(
            f"{symbol} : format de signal invalide.",
            "warning",
        )
        return []

    valid_signals = [
        signal
        for signal in signals
        if isinstance(signal, dict)
    ]

    log(
        f"{symbol} : {len(valid_signals)} signal(aux) detecte(s)."
    )

    return valid_signals
    # ============================================================
# VERIFICATION DE LA DISPONIBILITE TELEGRAM
# ============================================================

def telegram_is_ready() -> bool:
    """Verifie que Telegram est correctement configure."""

    if not ENABLE_TELEGRAM_ALERTS:
        log("Alertes Telegram desactivees.")
        return False

    if not TELEGRAM_BOT_TOKEN:
        log("Token Telegram absent.", "error")
        return False

    if not TELEGRAM_CHAT_ID:
        log("Chat ID Telegram absent.", "error")
        return False

    return True


# ============================================================
# ENVOI D'UN MESSAGE TELEGRAM
# ============================================================

def send_telegram_message(message: str) -> bool:
    """Envoie un message Telegram avec plusieurs tentatives."""

    if not telegram_is_ready():
        return False

    if not isinstance(message, str) or not message.strip():
        log("Message Telegram vide.", "warning")
        return False

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    for attempt in range(1, TELEGRAM_MAX_RETRIES + 1):

        try:
            response = requests.post(
                TELEGRAM_API_URL,
                json=payload,
                timeout=TELEGRAM_TIMEOUT,
            )

            if response.status_code == 200:
                result = response.json()

                if result.get("ok") is True:
                    log("Message Telegram envoye.")
                    return True

                log(
                    "Telegram a refuse le message.",
                    "error",
                )

            else:
                log(
                    "Erreur HTTP Telegram : "
                    f"{response.status_code}",
                    "error",
                )

        except requests.RequestException as exc:
            log(
                f"Erreur reseau Telegram : {exc}",
                "error",
            )

        if attempt < TELEGRAM_MAX_RETRIES:
            time.sleep(2)

    log(
        "Echec definitif de l'envoi Telegram.",
        "error",
    )

    return False


# ============================================================
# PREPARATION DU MESSAGE DU SIGNAL
# ============================================================

def prepare_signal_message(signal: dict) -> Optional[str]:
    """Formate un signal avec la fonction de strategie."""

    if not isinstance(signal, dict):
        return None

    try:
        message = format_message(signal)

    except Exception as exc:
        log(
            f"Erreur de formatage du signal : {exc}",
            "error",
        )
        return None

    if not isinstance(message, str) or not message.strip():
        return None

    return message


# ============================================================
# VALIDATION DE SECURITE DU SIGNAL
# ============================================================

def validate_signal(signal: dict) -> bool:
    """Verifie les donnees essentielles avant notification."""

    if not isinstance(signal, dict):
        return False

    direction = str(
        signal.get("direction", "")
    ).upper()

    if direction not in ("BUY", "SELL"):
        return False

    required_fields = (
        "entry",
        "stop_loss",
        "take_profit",
        "rr",
    )

    for field in required_fields:
        if not is_valid_number(signal.get(field)):
            return False

    entry = float(signal["entry"])
    stop_loss = float(signal["stop_loss"])
    take_profit = float(signal["take_profit"])
    rr = float(signal["rr"])

    if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
        return False

    if rr < 1.0:
        return False

    if direction == "BUY":
        if not stop_loss < entry < take_profit:
            return False

    if direction == "SELL":
        if not take_profit < entry < stop_loss:
            return False

    return True


# ============================================================
# TRAITEMENT DES SIGNAUX
# ============================================================

def process_signals(
    symbol: str,
    signals: list,
) -> int:
    """Valide et transmet les signaux trouves."""

    if not isinstance(signals, list):
        return 0

    sent_count = 0

    for signal in signals:

        if not validate_signal(signal):
            log(
                f"{symbol} : signal invalide rejete.",
                "warning",
            )
            continue

        message = prepare_signal_message(signal)

        if message is None:
            continue

        if not ENABLE_TELEGRAM_ALERTS:
            log(
                f"{symbol} : signal detecte, "
                "mais alertes desactivees."
            )
            continue

        if send_telegram_message(message):
            sent_count += 1

        time.sleep(REQUEST_DELAY)

    return sent_count
    # ============================================================
# ANALYSE COMPLETE D'UN INDICE
# ============================================================

def process_symbol(symbol: str) -> int:
    """Execute toutes les etapes d'analyse pour un indice."""

    log("-" * 45)
    log(
        f"ANALYSE : {SYMBOL_NAMES.get(symbol, symbol)}"
    )

    try:
        signals = analyze_symbol(symbol)

        if not signals:
            log(
                f"{symbol} : aucun signal valide detecte."
            )
            return 0

        sent_count = process_signals(
            symbol,
            signals,
        )

        log(
            f"{symbol} : {len(signals)} signal(aux) "
            f"valide(s), {sent_count} alerte(s) envoyee(s)."
        )

        return sent_count

    except Exception as exc:
        log(
            f"{symbol} : erreur inattendue : {exc}",
            "error",
        )
        LOGGER.exception(
            "Detail de l'erreur pendant le traitement."
        )
        return 0


# ============================================================
# CONTROLE DES MODULES
# ============================================================

def check_application_modules() -> bool:
    """Verifie la disponibilite des modules necessaires."""

    if not DERIV_MODULE_READY:
        log(
            "Module deriv_market indisponible.",
            "error",
        )
        return False

    if not STRATEGY_MODULE_READY:
        log(
            "Module strategy indisponible.",
            "error",
        )
        return False

    log("Modules Deriv et Strategy disponibles.")

    return True


# ============================================================
# RAPPORT FINAL DU CYCLE
# ============================================================

def print_analysis_summary(
    analyzed_count: int,
    alert_count: int,
    error_count: int,
) -> None:
    """Affiche le bilan du cycle d'analyse."""

    log("=" * 45)
    log("BILAN DU CYCLE TRADER AI PRO")
    log("=" * 45)

    log(f"Indices traites : {analyzed_count}")
    log(f"Alertes Telegram envoyees : {alert_count}")
    log(f"Erreurs detectees : {error_count}")

    log(f"DRY_RUN : {DRY_RUN}")
    log("Execution automatique des ordres : DESACTIVEE")

    log("=" * 45)


# ============================================================
# EXECUTION PRINCIPALE
# ============================================================

def run_analysis() -> int:
    """Lance un cycle complet d'analyse des indices."""

    print_startup_information()

    # Diagnostic sans afficher les secrets.
    print_secret_status()

    # Verification des modules.
    # Controles prealables complets.
    if not run_preflight_checks():
       return 1

    # Verification de la configuration.
    if not validate_configuration():
        log(
            "Configuration invalide. Analyse interrompue.",
            "error",
        )
        return 1

    analyzed_count = 0
    alert_count = 0
    error_count = 0

    log("Demarrage du scanner des indices Deriv.")

    for index, symbol in enumerate(SYMBOLS, start=1):

        log(
            f"Progression : {index}/{len(SYMBOLS)}"
        )

        try:
            alert_count += process_symbol(symbol)
            analyzed_count += 1

        except Exception as exc:
            error_count += 1

            log(
                f"Erreur generale pour {symbol} : {exc}",
                "error",
            )

            LOGGER.exception(
                "Erreur detaillee du traitement."
            )

        if index < len(SYMBOLS):
            time.sleep(SYMBOL_DELAY)

    print_analysis_summary(
        analyzed_count,
        alert_count,
        error_count,
    )

    log("Cycle d'analyse termine.")

    return 0


# ============================================================
# POINT D'ENTREE DU PROGRAMME
# ============================================================

def main() -> None:
    """Point d'entree principal."""

    try:
        exit_code = run_analysis()

    except KeyboardInterrupt:
        log(
            "Analyse interrompue manuellement.",
            "warning",
        )
        exit_code = 130

    except Exception as exc:
        log(
            f"Erreur critique : {exc}",
            "error",
        )
        LOGGER.exception(
            "Erreur critique non geree."
        )
        exit_code = 1

    sys.exit(exit_code)
    # ============================================================
# CONTROLES FINAUX DE SECURITE
# ============================================================

def final_security_check() -> bool:
    """Verifie les conditions de securite avant le scanner."""

    log("Verification finale de securite.")

    # Le mode DRY_RUN doit obligatoirement rester actif.
    if DRY_RUN is not True:
        log(
            "SECURITE : DRY_RUN doit etre active.",
            "error",
        )
        return False

    # Aucun ordre automatique ne doit etre autorise.
    if ENABLE_AUTO_TRADING is not False:
        log(
            "SECURITE : execution automatique interdite.",
            "error",
        )
        return False

    # Les identifiants Telegram ne sont jamais affiches.
    if ENABLE_TELEGRAM_ALERTS:
        if not TELEGRAM_BOT_TOKEN:
            log(
                "SECURITE : token Telegram absent.",
                "error",
            )
            return False

        if not TELEGRAM_CHAT_ID:
            log(
                "SECURITE : identifiant Telegram absent.",
                "error",
            )
            return False

    log("Verification finale de securite reussie.")

    return True


# ============================================================
# CONTROLE DE COHERENCE DES TIMEFRAMES
# ============================================================

def check_timeframe_configuration() -> bool:
    """Verifie la configuration des quatre timeframes."""

    expected = {
        "D1": 86400,
        "H4": 14400,
        "H2": 7200,
        "H1": 3600,
    }

    if TIMEFRAMES != expected:
        log(
            "Configuration des timeframes incorrecte.",
            "error",
        )
        return False

    if MIN_CANDLES < 200:
        log(
            "Nombre minimum de bougies insuffisant.",
            "error",
        )
        return False

    log(
        "Timeframes D1/H4/H2/H1 : configuration valide."
    )

    log(
        f"Minimum de bougies par timeframe : {MIN_CANDLES}"
    )

    return True


# ============================================================
# CONTROLE DE LA LISTE DES INDICES
# ============================================================

def check_symbols_configuration() -> bool:
    """Verifie les symboles et leurs noms complets."""

    if not SYMBOLS:
        log(
            "Aucun indice configure.",
            "error",
        )
        return False

    if len(SYMBOLS) != len(set(SYMBOLS)):
        log(
            "Des symboles sont dupliques.",
            "error",
        )
        return False

    missing_names = [
        symbol
        for symbol in SYMBOLS
        if symbol not in SYMBOL_NAMES
    ]

    if missing_names:
        log(
            "Noms complets manquants : "
            + ", ".join(missing_names),
            "error",
        )
        return False

    log(
        f"Configuration des {len(SYMBOLS)} indices valide."
    )

    return True


# ============================================================
# CONTROLE GLOBAL AVANT ANALYSE
# ============================================================

def run_preflight_checks() -> bool:
    """Execute tous les controles avant le scanner."""

    log("=" * 45)
    log("CONTROLES PREALABLES")
    log("=" * 45)

    checks = [
        final_security_check(),
        check_timeframe_configuration(),
        check_symbols_configuration(),
        check_application_modules(),
    ]

    if not all(checks):
        log(
            "Echec des controles prealables.",
            "error",
        )
        return False

    log("Tous les controles prealables sont valides.")
    log("=" * 45)

    return True


if __name__ == "__main__":
    main()
