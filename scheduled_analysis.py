# ============================================================
# TRADER AI PRO — SCANNER MULTI-TIMEFRAME
# STRATEGIE TRENDLINE + SUPPORTS / RESISTANCES
# ============================================================

import logging
import os
import sqlite3
import time

from datetime import datetime, timezone
from pathlib import Path

import requests

from deriv_market import get_candles, get_current_price
from strategy import find_signals, format_message


# ============================================================
# CONFIGURATION GENERALE
# ============================================================

BOT_NAME = "TRADER AI PRO"

STRATEGY_NAME = "TRENDLINE_SUPPORT_RESISTANCE"

TIMEFRAMES = {
    "D1": 200,
    "H4": 200,
    "H2": 200,
    "H1": 200,
}

MIN_RR = 1.0

DRY_RUN = (
    os.getenv("DRY_RUN", "true").strip().lower()
    == "true"
)

AUTO_EXECUTION_ENABLED = False

ENABLE_TELEGRAM_ALERTS = (
    os.getenv("ENABLE_TELEGRAM_ALERTS", "true").strip().lower()
    == "true"
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

REQUEST_TIMEOUT = 20
PAUSE_BETWEEN_SYMBOLS = 2

DATABASE_PATH = Path(
    os.getenv(
        "DATABASE_PATH",
        "state/trader_ai_pro.sqlite3"
    )
)

DATABASE_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)


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
# JOURNALISATION
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(BOT_NAME)


# ============================================================
# BASE DE DONNEES
# ============================================================

def get_database_connection():
    connection = sqlite3.connect(
        str(DATABASE_PATH),
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    return connection


def initialize_database():
    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                strategy TEXT,
                timeframe TEXT,
                entry REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                rr REAL NOT NULL,
                zone_low REAL,
                zone_high REAL,
                status TEXT DEFAULT 'DETECTED',
                message TEXT,
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS run_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                symbols_scanned INTEGER DEFAULT 0,
                signals_found INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                status TEXT
            )
        """)

        connection.commit()

    finally:
        connection.close()
        # ============================================================
# PARTIE 2/4 — RECUPERATION ET VALIDATION DES DONNEES
# ============================================================

import math


# ============================================================
# NORMALISATION DES BOUGIES
# ============================================================

def normalize_candles(candles):
    """
    Nettoie les bougies :
    - vérifie les valeurs OHLC ;
    - élimine les données invalides ;
    - supprime les doublons ;
    - classe les bougies par ordre chronologique.
    """

    if not isinstance(candles, list):
        return []

    normalized = []
    seen_epochs = set()

    for candle in candles:

        if not isinstance(candle, dict):
            continue

        try:
            epoch = int(candle["epoch"])

            open_price = float(candle["open"])
            high_price = float(candle["high"])
            low_price = float(candle["low"])
            close_price = float(candle["close"])

        except (KeyError, TypeError, ValueError, OverflowError):
            continue

        values = [
            open_price,
            high_price,
            low_price,
            close_price,
        ]

        if not all(math.isfinite(value) for value in values):
            continue

        if min(values) <= 0:
            continue

        if high_price < low_price:
            continue

        if high_price < max(open_price, close_price):
            continue

        if low_price > min(open_price, close_price):
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
# RECUPERATION DES BOUGIES
# ============================================================

def fetch_candles(symbol, timeframe):
    """
    Récupère les bougies Deriv pour une unité de temps.

    Demande une bougie supplémentaire pour disposer
    d'une marge de sécurité.
    """

    required_count = TIMEFRAMES.get(timeframe)

    if required_count is None:
        logger.error(
            "%s | Unité de temps inconnue : %s",
            symbol,
            timeframe,
        )
        return []

    try:
        result = get_candles(
            symbol,
            timeframe=timeframe,
            count=required_count + 1,
            timeout=REQUEST_TIMEOUT,
        )

        if not isinstance(result, dict):
            logger.error(
                "%s | Réponse Deriv invalide en %s",
                symbol,
                timeframe,
            )
            return []

        if result.get("error"):
            logger.error(
                "%s | Erreur bougies %s : %s",
                symbol,
                timeframe,
                result.get("error"),
            )
            return []

        raw_candles = result.get("candles", [])

        candles = normalize_candles(raw_candles)

        if len(candles) < required_count:
            logger.warning(
                "%s | %s : seulement %s bougies valides sur %s requises",
                symbol,
                timeframe,
                len(candles),
                required_count,
            )
            return []

        # On conserve les bougies les plus récentes.
        candles = candles[-required_count:]

        logger.info(
            "%s | %s : %s bougies valides",
            symbol,
            timeframe,
            len(candles),
        )

        return candles

    except Exception:
        logger.exception(
            "%s | Erreur récupération bougies %s",
            symbol,
            timeframe,
        )
        return []


# ============================================================
# RECUPERATION DU PRIX ACTUEL
# ============================================================

def fetch_current_price(symbol):
    """
    Récupère le dernier prix disponible sur Deriv.
    Aucun ordre n'est envoyé.
    """

    try:
        result = get_current_price(
            symbol,
            timeout=REQUEST_TIMEOUT,
        )

        if isinstance(result, dict):
            result = result.get(
                "price",
                result.get("quote"),
            )

        if result is None:
            logger.warning(
                "%s | Prix actuel indisponible",
                symbol,
            )
            return None

        price = float(result)

        if not math.isfinite(price) or price <= 0:
            logger.warning(
                "%s | Prix actuel invalide",
                symbol,
            )
            return None

        return price

    except Exception:
        logger.exception(
            "%s | Impossible de récupérer le prix actuel",
            symbol,
        )
        return None


# ============================================================
# RECUPERATION DES QUATRE UNITES DE TEMPS
# ============================================================

def fetch_market_data(symbol):
    """
    Récupère D1, H4, H2 et H1.

    Si une seule unité de temps ne possède pas
    les 200 bougies nécessaires, l'analyse est arrêtée.
    """

    market_data = {}

    for timeframe in ("D1", "H4", "H2", "H1"):

        candles = fetch_candles(
            symbol,
            timeframe,
        )

        if len(candles) < TIMEFRAMES[timeframe]:
            logger.warning(
                "%s | Analyse interrompue : données %s insuffisantes",
                symbol,
                timeframe,
            )
            return None

        market_data[timeframe] = candles

    return market_data
    # ============================================================
# PARTIE 3/4 — SECURITE ET GESTION DES SIGNAUX
# ============================================================


# ============================================================
# HORODATAGE
# ============================================================

def current_timestamp():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# DEMARRAGE D'UNE ANALYSE
# ============================================================

def start_analysis_run():
    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT INTO run_log (
                started_at,
                status
            )
            VALUES (?, ?)
        """, (
            current_timestamp(),
            "RUNNING",
        ))

        connection.commit()

        return cursor.lastrowid

    finally:
        connection.close()


# ============================================================
# FIN D'UNE ANALYSE
# ============================================================

def finish_analysis_run(
    run_id,
    symbols_scanned,
    signals_found,
    errors,
    status="COMPLETED",
):
    connection = get_database_connection()

    try:
        connection.execute("""
            UPDATE run_log
            SET
                finished_at = ?,
                symbols_scanned = ?,
                signals_found = ?,
                errors = ?,
                status = ?
            WHERE id = ?
        """, (
            current_timestamp(),
            symbols_scanned,
            signals_found,
            errors,
            status,
            run_id,
        ))

        connection.commit()

    finally:
        connection.close()


# ============================================================
# VALIDATION INDEPENDANTE DU SIGNAL
# ============================================================

def validate_signal(signal):
    """
    Vérifie les données du signal avant tout enregistrement
    ou envoi Telegram.

    Aucun ordre n'est exécuté ici.
    """

    if not isinstance(signal, dict):
        return False, "Signal invalide"

    if signal.get("strategy") != STRATEGY_NAME:
        return False, "Stratégie non autorisée"

    if signal.get("direction") not in ("BUY", "SELL"):
        return False, "Direction invalide"

    if signal.get("timeframe") not in TIMEFRAMES:
        return False, "Unité de temps invalide"

    if signal.get("symbol") not in SYMBOLS:
        return False, "Indice non autorisé"

    try:
        entry = float(signal["entry"])
        stop_loss = float(signal["stop_loss"])
        take_profit = float(signal["take_profit"])

    except (KeyError, TypeError, ValueError, OverflowError):
        return False, "Prix du signal invalides"

    prices = (entry, stop_loss, take_profit)

    if not all(math.isfinite(value) and value > 0 for value in prices):
        return False, "Prix non valides"

    if signal["direction"] == "BUY":
        if stop_loss >= entry:
            return False, "Stop Loss incorrect pour un BUY"

        if take_profit <= entry:
            return False, "Take Profit incorrect pour un BUY"

    else:
        if stop_loss <= entry:
            return False, "Stop Loss incorrect pour un SELL"

        if take_profit >= entry:
            return False, "Take Profit incorrect pour un SELL"

    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)

    if risk <= 0 or reward <= 0:
        return False, "Risque ou rendement nul"

    calculated_rr = reward / risk

    if calculated_rr < MIN_RR:
        return False, (
            f"RR insuffisant : {calculated_rr:.2f}"
        )

    if not signal.get("signal_id"):
        return False, "Identifiant du signal absent"

    return True, calculated_rr


# ============================================================
# ENREGISTREMENT DU SIGNAL
# ============================================================

def store_signal(signal, message):
    """
    Enregistre un signal valide dans SQLite.

    INSERT OR IGNORE empêche l'enregistrement
    d'un signal dont l'identifiant existe déjà.
    """

    valid, result = validate_signal(signal)

    if not valid:
        logger.warning(
            "%s | Signal rejeté : %s",
            signal.get("symbol", "UNKNOWN"),
            result,
        )
        return False

    calculated_rr = result

    connection = get_database_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            INSERT OR IGNORE INTO signals (
                signal_id,
                symbol,
                direction,
                strategy,
                timeframe,
                entry,
                stop_loss,
                take_profit,
                rr,
                zone_low,
                zone_high,
                status,
                message,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            signal["signal_id"],
            signal["symbol"],
            signal["direction"],
            signal["strategy"],
            signal["timeframe"],
            float(signal["entry"]),
            float(signal["stop_loss"]),
            float(signal["take_profit"]),
            round(calculated_rr, 4),
            signal.get("zone_low"),
            signal.get("zone_high"),
            "DETECTED",
            message,
            current_timestamp(),
        ))

        connection.commit()

        if cursor.rowcount == 0:
            logger.info(
                "%s | Signal déjà enregistré : %s",
                signal["symbol"],
                signal["signal_id"],
            )
            return False

        logger.info(
            "%s | Signal enregistré | %s | RR 1:%.2f",
            signal["symbol"],
            signal["direction"],
            calculated_rr,
        )

        return True

    except sqlite3.Error:
        logger.exception(
            "%s | Erreur SQLite lors de l'enregistrement",
            signal.get("symbol", "UNKNOWN"),
        )
        return False

    finally:
        connection.close()
        # ============================================================
# PARTIE 4/4 — TELEGRAM ET SCANNER PRINCIPAL
# ============================================================


# ============================================================
# ENVOI DES ALERTES TELEGRAM
# ============================================================

def send_telegram(message):
    """
    Envoie une alerte Telegram.
    Aucun ordre Deriv n'est exécuté.
    """

    if not ENABLE_TELEGRAM_ALERTS:
        logger.info("Alertes Telegram désactivées.")
        return False

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error(
            "Configuration Telegram incomplète."
        )
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
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

        if not result.get("ok"):
            logger.error(
                "Telegram a refusé le message : %s",
                result,
            )
            return False

        logger.info("Alerte Telegram envoyée.")
        return True

    except requests.RequestException:
        logger.exception(
            "Erreur lors de l'envoi Telegram."
        )
        return False


# ============================================================
# ANALYSE D'UN INDICE
# ============================================================

def analyze_symbol(symbol):
    """
    Analyse un indice avec les quatre unités de temps.
    """

    logger.info(
        "========== ANALYSE DE %s ==========",
        symbol,
    )

    market_data = fetch_market_data(symbol)

    if market_data is None:
        return [], 1

    current_price = fetch_current_price(symbol)

    if current_price is None:
        return [], 1

    diagnostics = {}

    signals = find_signals(
        symbol=symbol,
        d1=market_data["D1"],
        h4=market_data["H4"],
        h2=market_data["H2"],
        h1=market_data["H1"],
        price_now=current_price,
        diagnostics=diagnostics,
    )

    logger.info(
        "%s | Résultat stratégie : %s",
        symbol,
        diagnostics.get("status", "UNKNOWN"),
    )

    if diagnostics.get("reason"):
        logger.info(
            "%s | Motif : %s",
            symbol,
            diagnostics["reason"],
        )

    valid_signals = []

    for signal in signals:

        valid, result = validate_signal(signal)

        if not valid:
            logger.warning(
                "%s | Signal rejeté : %s",
                symbol,
                result,
            )
            continue

        valid_signals.append(signal)

    return valid_signals, 0


# ============================================================
# TRAITEMENT D'UN SIGNAL
# ============================================================

def process_signal(signal):
    """
    Vérifie, enregistre et transmet un signal.

    L'enregistrement est effectué avant l'envoi Telegram
    afin d'éviter les doublons.
    """

    valid, result = validate_signal(signal)

    if not valid:
        logger.warning(
            "%s | Signal ignoré : %s",
            signal.get("symbol", "UNKNOWN"),
            result,
        )
        return False

    message = format_message(signal)

    saved = store_signal(
        signal,
        message,
    )

    if not saved:
        return False

    if ENABLE_TELEGRAM_ALERTS:
        sent = send_telegram(message)

        if not sent:
            logger.error(
                "%s | Signal enregistré mais Telegram non envoyé.",
                signal["symbol"],
            )
            return False

    else:
        logger.info(
            "%s | Signal enregistré, Telegram désactivé.",
            signal["symbol"],
        )

    return True


# ============================================================
# SCANNER PRINCIPAL
# ============================================================

def main():

    logger.info("=" * 60)
    logger.info("TRADER AI PRO — SCANNER MULTI-TIMEFRAME")
    logger.info("Stratégie : TRENDLINE + CONFLUENCE")
    logger.info("=" * 60)

    logger.info("D1 : %s bougies", TIMEFRAMES["D1"])
    logger.info("H4 : %s bougies", TIMEFRAMES["H4"])
    logger.info("H2 : %s bougies", TIMEFRAMES["H2"])
    logger.info("H1 : %s bougies", TIMEFRAMES["H1"])

    logger.info("RR minimum : 1:%.1f", MIN_RR)
    logger.info("DRY_RUN : %s", DRY_RUN)
    logger.info("Exécution automatique des ordres : DÉSACTIVÉE")
    logger.info(
        "Alertes Telegram : %s",
        ENABLE_TELEGRAM_ALERTS,
    )

    if not DRY_RUN:
        logger.critical(
            "DRY_RUN doit obligatoirement rester à true."
        )
        return

    initialize_database()

    run_id = start_analysis_run()

    symbols_scanned = 0
    signals_found = 0
    errors = 0

    try:
        for symbol in SYMBOLS:

            try:
                signals, error_count = analyze_symbol(symbol)

                symbols_scanned += 1
                errors += error_count

                for signal in signals:

                    if process_signal(signal):
                        signals_found += 1

            except Exception:
                errors += 1

                logger.exception(
                    "%s | Erreur pendant l'analyse",
                    symbol,
                )

            time.sleep(PAUSE_BETWEEN_SYMBOLS)

        status = (
            "COMPLETED_WITH_ERRORS"
            if errors > 0
            else "COMPLETED"
        )

        finish_analysis_run(
            run_id=run_id,
            symbols_scanned=symbols_scanned,
            signals_found=signals_found,
            errors=errors,
            status=status,
        )

        logger.info("=" * 60)
        logger.info("ANALYSE TERMINÉE")
        logger.info("Indices analysés : %s", symbols_scanned)
        logger.info("Signaux transmis : %s", signals_found)
        logger.info("Erreurs : %s", errors)
        logger.info("=" * 60)

    except Exception:
        finish_analysis_run(
            run_id=run_id,
            symbols_scanned=symbols_scanned,
            signals_found=signals_found,
            errors=errors + 1,
            status="FAILED",
        )

        logger.exception(
            "Erreur générale du scanner."
        )


# ============================================================
# POINT D'ENTREE
# ============================================================

if __name__ == "__main__":
    main()
    
        
