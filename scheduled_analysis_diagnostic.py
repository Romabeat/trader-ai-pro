"""
TRADER AI PRO
Analyse automatique des indices Deriv.

Fonctions :
- Recuperation des prix actuels.
- Recuperation des bougies D1, H4, H2 et H1.
- Analyse des 13 indices.
- Envoi des alertes sur Telegram.
- Controle des donnees de marche.
- Execution automatique des ordres interdite.

IMPORTANT :
Ce programme genere des alertes.
Les transactions restent manuelles.
"""

import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional


# ============================================================
# CONFIGURATION GENERALE
# ============================================================

APP_NAME = "TRADER AI PRO"

DRY_RUN = (
    os.getenv("DRY_RUN", "true").strip().lower() == "true"
)

ENABLE_TELEGRAM_ALERTS = (
    os.getenv(
        "ENABLE_TELEGRAM_ALERTS",
        "true",
    ).strip().lower() == "true"
)

# La valeur False est volontairement imposee.
# Aucun ordre automatique ne doit etre execute.
ENABLE_AUTO_TRADING = False

MIN_CANDLES = 200

REQUEST_DELAY = 0.20

TIMEFRAMES = {
    "D1": 86400,
    "H4": 14400,
    "H2": 7200,
    "H1": 3600,
}


# ============================================================
# CONFIGURATION TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    "",
).strip()

if TELEGRAM_BOT_TOKEN:
    TELEGRAM_API_URL = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )
else:
    TELEGRAM_API_URL = ""


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


# ============================================================
# NOMS COMPLETS DES INDICES
# ============================================================

SYMBOL_LABELS = {
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
# CONFIGURATION DU JOURNAL
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

LOGGER = logging.getLogger("TRADER_AI_PRO")


def log(message: str, level: str = "info") -> None:
    """Ecrit un message dans les logs."""

    message = str(message)

    if level == "error":
        LOGGER.error(message)

    elif level == "warning":
        LOGGER.warning(message)

    else:
        LOGGER.info(message)


# ============================================================
# INFORMATIONS DE DEMARRAGE
# ============================================================

def print_startup_information() -> None:
    """Affiche les parametres de fonctionnement."""

    log("=" * 65)
    log("TRADER AI PRO - ANALYSE DES INDICES DERIV")
    log("=" * 65)

    log("Timeframes : D1, H4, H2 et H1")
    log(f"Minimum de bougies par timeframe : {MIN_CANDLES}")
    log(f"Nombre d'indices : {len(SYMBOLS)}")
    log(f"DRY_RUN : {DRY_RUN}")
    log(
        "Alertes Telegram : "
        + str(ENABLE_TELEGRAM_ALERTS)
    )

    log(
        "Execution automatique des ordres : "
        "DESACTIVEE"
    )

    log(
        "Telegram token present : "
        + str(bool(TELEGRAM_BOT_TOKEN))
    )

    log(
        "Telegram chat ID present : "
        + str(bool(TELEGRAM_CHAT_ID))
    )

    log("Aucune valeur de secret ne sera affichee.")
    log("=" * 65)


# ============================================================
# VALIDATION DES PARAMETRES
# ============================================================

def is_positive_number(value) -> bool:
    """Verifie qu'une valeur numerique est finie et positive."""

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False

    return (
        number > 0
        and number == number
        and abs(number) != float("inf")
    )


def validate_configuration() -> bool:
    """Verifie la configuration generale."""

    if ENABLE_AUTO_TRADING is not False:
        log(
            "SECURITE : execution automatique interdite.",
            "error",
        )
        return False

    if len(SYMBOLS) != 13:
        log(
            "Configuration invalide : nombre d'indices incorrect.",
            "error",
        )
        return False

    if len(set(SYMBOLS)) != len(SYMBOLS):
        log(
            "Configuration invalide : symboles en double.",
            "error",
        )
        return False

    if MIN_CANDLES != 200:
        log(
            "Configuration invalide : 200 bougies requises.",
            "error",
        )
        return False

    if not all(symbol in SYMBOL_LABELS for symbol in SYMBOLS):
        log(
            "Un ou plusieurs noms d'indices sont manquants.",
            "error",
        )
        return False

    log("Configuration generale validee.")
    return True
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
        analyze_symbol_completely,
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
# RECUPERATION DES BOUGIES D'UN TIMEFRAME
# ============================================================

def fetch_timeframe_candles(
    symbol: str,
    timeframe: str,
) -> list:
    """Recupere les bougies d'un timeframe."""

    if timeframe not in TIMEFRAMES:
        log(
            f"{symbol} : timeframe inconnu {timeframe}.",
            "error",
        )
        return []

    granularity = TIMEFRAMES[timeframe]

    try:
        candles = get_candles(
            symbol,
            granularity,
            count=MIN_CANDLES,
        )

    except Exception as exc:
        log(
            f"{symbol} : erreur bougies {timeframe} : {exc}",
            "error",
        )
        return []

    if not isinstance(candles, list):
        log(
            f"{symbol} : format de bougies invalide ({timeframe}).",
            "warning",
        )
        return []

    if len(candles) < MIN_CANDLES:
        log(
            f"{symbol} : {len(candles)}/{MIN_CANDLES} bougies "
            f"recues pour {timeframe}.",
            "warning",
        )
        return candles

    log(
        f"{symbol} : {len(candles)} bougies {timeframe} recuperees."
    )

    return candles


# ============================================================
# RECUPERATION DU PRIX ACTUEL
# ============================================================

def fetch_current_price(symbol: str) -> Optional[float]:
    """Recupere et valide le dernier prix disponible."""

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

    price = float(price)

    log(
        f"{SYMBOL_LABELS.get(symbol, symbol)} "
        f"({symbol}) | PRIX ACTUEL : {price}"
    )

    return price


# ============================================================
# RECUPERATION COMPLETE DES DONNEES
# ============================================================

def fetch_market_data(symbol: str) -> Optional[dict]:
    """Recupere le prix et les quatre timeframes."""

    if symbol not in SYMBOLS:
        log(
            f"Symbole non autorise : {symbol}",
            "error",
        )
        return None

    label = SYMBOL_LABELS.get(symbol, symbol)

    log("-" * 65)
    log(f"INDICE : {label}")
    log(f"SYMBOLE : {symbol}")

    market_data = {
        "symbol": symbol,
        "label": label,
    }

    # Recuperation des bougies D1, H4, H2 et H1.
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
            f"{symbol} : prix actuel indisponible. "
            "Analyse abandonnee.",
            "warning",
        )
        return None

    market_data["current_price"] = current_price

    log(
        f"{symbol} : donnees multi-timeframe completes."
    )

    log("-" * 65)

    return market_data
    # ============================================================
# CONFIGURATION ET ENVOI TELEGRAM
# ============================================================

def telegram_is_ready() -> bool:
    """Verifie si Telegram est correctement configure."""

    return (
        ENABLE_TELEGRAM_ALERTS
        and bool(TELEGRAM_BOT_TOKEN)
        and bool(TELEGRAM_CHAT_ID)
    )


def send_telegram_message(message: str) -> bool:
    """Envoie une notification Telegram."""

    if not ENABLE_TELEGRAM_ALERTS:
        log("Alertes Telegram desactivees.")
        return False

    if not telegram_is_ready():
        log(
            "Telegram indisponible : configuration incomplete.",
            "warning",
        )
        return False

    try:
        import requests

        response = requests.post(
            TELEGRAM_API_URL,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=20,
        )

        if response.status_code != 200:
            log(
                f"Erreur Telegram HTTP {response.status_code}.",
                "error",
            )
            return False

        result = response.json()

        if not result.get("ok", False):
            log(
                "Telegram a refuse le message.",
                "error",
            )
            return False

        log("Notification Telegram envoyee.")
        return True

    except Exception as exc:
        log(
            f"Echec envoi Telegram : {exc}",
            "error",
        )
        return False


# ============================================================
# VALIDATION DES SIGNAUX
# ============================================================

def validate_signal(signal: dict) -> bool:
    """Verifie les champs essentiels d'un signal."""

    if not isinstance(signal, dict):
        return False

    required_fields = (
        "entry",
        "stop_loss",
        "take_profit",
        "rr",
    )

    for field in required_fields:
        if field not in signal:
            log(
                f"Signal ignore : champ manquant {field}.",
                "warning",
            )
            return False

    if not all(
        is_positive_number(signal[field])
        for field in required_fields
    ):
        log(
            "Signal ignore : valeurs numeriques invalides.",
            "warning",
        )
        return False

    entry = float(signal["entry"])
    stop_loss = float(signal["stop_loss"])
    take_profit = float(signal["take_profit"])
    rr = float(signal["rr"])

    if entry == stop_loss or entry == take_profit:
        log(
            "Signal ignore : niveaux de prix incoherents.",
            "warning",
        )
        return False

    if rr < 1.0:
        log(
            f"Signal ignore : RR insuffisant ({rr:.2f}).",
            "warning",
        )
        return False

    return True


# ============================================================
# ANALYSE D'UN INDICE
# ============================================================

def process_symbol(symbol: str) -> int:
    """Recupere les donnees et analyse un indice."""

    label = SYMBOL_LABELS.get(symbol, symbol)

    log("=" * 65)
    log(f"ANALYSE : {label} ({symbol})")

    market_data = fetch_market_data(symbol)

    if market_data is None:
        log(
            f"{symbol} : analyse impossible, donnees incompletes.",
            "warning",
        )
        return 0

    log(
        f"{symbol} : prix utilise pour l'analyse = "
        f"{market_data['current_price']}"
    )

    # Diagnostic detaille : on appelle directement le point d'entree
    # officiel de la strategie afin de conserver le motif exact du rejet.
    # Aucun reglage ni critere de la strategie n'est modifie ici.
    snapshot = {
        "symbol": symbol,
        "current_price": market_data.get("current_price"),
        "timeframes": {
            timeframe: market_data.get(timeframe)
            for timeframe in ("D1", "H4", "H2", "H1")
        },
    }

    try:
        analysis_result = analyze_symbol_completely(
            symbol=symbol,
            snapshot=snapshot,
        )

    except Exception as exc:
        log(
            f"{symbol} : erreur de strategie : {exc}",
            "error",
        )
        return 0

    if not isinstance(analysis_result, dict):
        log(
            f"{symbol} : resultat de diagnostic invalide.",
            "error",
        )
        return 0

    analysis_status = analysis_result.get("status", "UNKNOWN")
    analysis_reason = analysis_result.get("reason", "Motif non fourni.")

    if analysis_status != "SIGNAL_CANDIDATE":
        log(
            f"{symbol} : diagnostic = {analysis_status} | "
            f"motif = {analysis_reason}"
        )
        details = analysis_result.get("details")
        if isinstance(details, dict) and details:
            log(f"{symbol} : details = {details}")
        elif isinstance(details, list) and details:
            log(f"{symbol} : details = {'; '.join(str(x) for x in details)}")
        return 0

    log(
        f"{symbol} : candidat detecte | direction = "
        f"{analysis_result.get('direction', 'N/A')} | "
        f"RR = {analysis_result.get('risk_reward', 'N/A')}"
    )
    signals = [dict(analysis_result)]
    signals[0]["rr"] = signals[0].get("risk_reward")
    signals[0]["automatic_execution"] = False

    if not isinstance(signals, (list, tuple)):
        log(
            f"{symbol} : format de signaux invalide.",
            "warning",
        )
        return 0

    valid_count = 0

    for signal in signals:
        if not validate_signal(signal):
            continue

        signal.setdefault("symbol", symbol)
        signal.setdefault("label", label)
        signal.setdefault(
            "current_price",
            market_data["current_price"],
        )

        try:
            message = format_message(signal)

        except Exception as exc:
            log(
                f"{symbol} : erreur de formatage du signal : {exc}",
                "error",
            )
            continue

        if not isinstance(message, str) or not message.strip():
            log(
                f"{symbol} : message de signal vide.",
                "warning",
            )
            continue

        log(
            f"{symbol} : signal valide detecte, "
            f"RR={float(signal['rr']):.2f}."
        )

        if telegram_is_ready():
            send_telegram_message(message)
        else:
            log(
                "Signal non envoye : Telegram non configure.",
                "warning",
            )

        valid_count += 1

    if valid_count == 0:
        log(f"{symbol} : aucun signal valide.")

    return valid_count


# ============================================================
# VERIFICATION DES MODULES
# ============================================================

def check_application_modules() -> bool:
    """Verifie que les modules necessaires sont charges."""

    if not DERIV_MODULE_READY:
        log(
            "Module Deriv indisponible.",
            "error",
        )
        return False

    if not STRATEGY_MODULE_READY:
        log(
            "Module strategie indisponible.",
            "error",
        )
        return False

    log("Modules applicatifs disponibles.")
    return True


# ============================================================
# VERIFICATION DE LA CONFIGURATION
# ============================================================

def run_preflight_checks() -> bool:
    """Effectue les controles avant l'analyse."""

    log("Verification prealable de la configuration.")

    if not validate_configuration():
        return False

    if not check_application_modules():
        return False

    if ENABLE_TELEGRAM_ALERTS and not telegram_is_ready():
        log(
            "Attention : alertes Telegram activees, "
            "mais configuration incomplete.",
            "warning",
        )

    if ENABLE_AUTO_TRADING:
        log(
            "SECURITE : le trading automatique doit rester desactive.",
            "error",
        )
        return False

    log("Tous les controles prealables sont termines.")
    return True


# ============================================================
# RESUME DE L'ANALYSE
# ============================================================

def print_analysis_summary(
    analyzed: int,
    skipped: int,
    signal_count: int,
) -> None:
    """Affiche le bilan de l'execution."""

    log("=" * 65)
    log("RESUME DE L'ANALYSE TRADER AI PRO")
    log(f"Indices prevus : {len(SYMBOLS)}")
    log(f"Indices analyses : {analyzed}")
    log(f"Indices ignores ou en echec : {skipped}")
    log(f"Signaux valides detectes : {signal_count}")
    log(f"DRY_RUN : {DRY_RUN}")
    log("Execution automatique : DESACTIVEE")
    log("=" * 65)


# ============================================================
# LANCEMENT DE L'ANALYSE
# ============================================================

def run_analysis() -> int:
    """Lance l'analyse complete des indices."""

    print_startup_information()

    if not run_preflight_checks():
        log(
            "Analyse interrompue : controles prealables echoues.",
            "error",
        )
        return 1

    started_at = datetime.now(timezone.utc)

    log(
        "Debut de l'analyse : "
        + started_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    )

    analyzed = 0
    skipped = 0
    signal_count = 0

    for index, symbol in enumerate(SYMBOLS, start=1):
        log(
            f"Progression : indice {index}/{len(SYMBOLS)}"
        )

        try:
            count = process_symbol(symbol)

            if count >= 0:
                analyzed += 1
                signal_count += count
            else:
                skipped += 1

        except Exception as exc:
            skipped += 1
            log(
                f"Erreur inattendue pour {symbol} : {exc}",
                "error",
            )

        if index < len(SYMBOLS):
            time.sleep(REQUEST_DELAY)

    print_analysis_summary(
        analyzed,
        skipped,
        signal_count,
    )

    finished_at = datetime.now(timezone.utc)

    log(
        "Fin de l'analyse : "
        + finished_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    )

    # Le programme signale un echec si aucun indice n'a pu etre analyse.
    if analyzed == 0:
        log(
            "Aucun indice n'a pu etre analyse. "
            "Verifier la connexion aux donnees Deriv.",
            "error",
        )
        return 1

    return 0


# ============================================================
# POINT D'ENTREE
# ============================================================

def main() -> None:
    """Point d'entree du programme."""

    try:
        exit_code = run_analysis()
    except KeyboardInterrupt:
        log("Analyse interrompue manuellement.", "warning")
        exit_code = 130
    except Exception as exc:
        log(
            f"Erreur fatale : {exc}",
            "error",
        )
        exit_code = 1

    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
