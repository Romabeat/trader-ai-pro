import logging
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from deriv_market import get_candles, get_current_price
from strategy import find_signals, format_message


# ============================================================
# CONFIGURATION
# ============================================================

BOT_NAME = "TRADER AI PRO"

D1_CANDLE_COUNT = 100
H4_CANDLE_COUNT = 200

MIN_RR = 1.5
REQUEST_TIMEOUT = 20
PAUSE_BETWEEN_SYMBOLS = 1

DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() != "false"
AUTO_EXECUTION_ENABLED = False

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DB_PATH = Path(
    os.getenv("TRADER_AI_DB_PATH", "state/trader_ai_pro.sqlite3")
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


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(BOT_NAME)


# ============================================================
# DATABASE
# ============================================================

def connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row

    return connection


def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                symbols_checked INTEGER DEFAULT 0,
                signals_found INTEGER DEFAULT 0,
                details TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE,
                symbol TEXT NOT NULL,
                direction TEXT,
                entry REAL,
                stop_loss REAL,
                take_profit REAL,
                rr REAL,
                status TEXT DEFAULT 'DETECTED',
                created_at TEXT NOT NULL,
                message TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS poi_zones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT UNIQUE,
                symbol TEXT NOT NULL,
                direction TEXT,
                zone_low REAL,
                zone_high REAL,
                entry REAL,
                stop_loss REAL,
                take_profit REAL,
                status TEXT DEFAULT 'POI_DETECTED',
                created_at TEXT NOT NULL,
                updated_at TEXT
            )
        """)

        conn.commit()


def log_run(started_at, status, symbols_checked, signals_found, details=""):
    with connect_db() as conn:
        conn.execute("""
            INSERT INTO analysis_runs (
                started_at,
                finished_at,
                status,
                symbols_checked,
                signals_found,
                details
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            started_at,
            datetime.now(timezone.utc).isoformat(),
            status,
            symbols_checked,
            signals_found,
            details[:2000],
        ))
        conn.commit()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram non configuré : notification non envoyée."
        )
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
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

        response.raise_for_status()
        data = response.json()

        if not data.get("ok"):
            logger.error(
                "Telegram a refusé le message : %s",
                data,
            )
            return False

        logger.info("Notification Telegram envoyée.")
        return True

    except (requests.RequestException, ValueError) as exc:
        logger.error("Erreur Telegram : %s", exc)
        return False


# ============================================================
# NORMALISATION DES BOUGIES
# ============================================================

def normalize_candles(candles):
    """
    Accepte les clés open/high/low/close ou o/h/l/c.
    Retourne les bougies normalisées par ordre chronologique.
    """

    if not isinstance(candles, list):
        return []

    unique = {}

    for candle in candles:
        if not isinstance(candle, dict):
            continue

        try:
            epoch = int(candle["epoch"])

            open_price = float(
                candle.get("open", candle.get("o"))
            )
            high_price = float(
                candle.get("high", candle.get("h"))
            )
            low_price = float(
                candle.get("low", candle.get("l"))
            )
            close_price = float(
                candle.get("close", candle.get("c"))
            )

            prices = (
                open_price,
                high_price,
                low_price,
                close_price,
            )

            if not all(math.isfinite(value) for value in prices):
                continue

            if high_price < max(open_price, low_price, close_price):
                continue

            if low_price > min(open_price, high_price, close_price):
                continue

            unique[epoch] = {
                "epoch": epoch,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
            }

        except (KeyError, TypeError, ValueError, OverflowError):
            continue

    return [
        unique[epoch]
        for epoch in sorted(unique)
    ]


def fetch_candles(symbol, timeframe, required_count):
    """
    Récupère et valide les bougies retournées par deriv_market.py.
    """

    try:
        response = get_candles(
            symbol,
            timeframe,
            count=required_count + 1,
            timeout=REQUEST_TIMEOUT,
        )

    except Exception as exc:
        logger.warning(
            "%s %s : erreur de récupération : %s",
            symbol,
            timeframe,
            exc,
        )
        return None

    if not isinstance(response, dict):
        logger.warning(
            "%s %s : réponse inattendue de type %s.",
            symbol,
            timeframe,
            type(response).__name__,
        )
        return None

    if response.get("error"):
        logger.warning(
            "%s %s : erreur Deriv : %s",
            symbol,
            timeframe,
            response["error"],
        )
        return None

    raw_candles = response.get("candles")

    if not isinstance(raw_candles, list):
        logger.warning(
            "%s %s : clé 'candles' absente ou invalide.",
            symbol,
            timeframe,
        )
        return None

    candles = normalize_candles(raw_candles)

    if len(candles) < required_count:
        logger.warning(
            "%s %s : historique insuffisant après validation "
            "(%s/%s). Bougies reçues : %s.",
            symbol,
            timeframe,
            len(candles),
            required_count,
            len(raw_candles),
        )
        return None

    candles = candles[-required_count:]

    logger.info(
        "%s %s : %s bougies valides.",
        symbol,
        timeframe,
        len(candles),
    )

    return candles


# ============================================================
# PRIX ACTUEL
# ============================================================

def fetch_current_price(symbol):
    try:
        result = get_current_price(
            symbol,
            timeout=REQUEST_TIMEOUT,
        )

        if isinstance(result, dict):
            if result.get("error"):
                logger.warning(
                    "%s : erreur de prix : %s",
                    symbol,
                    result["error"],
                )
                return None

            result = result.get(
                "price",
                result.get("quote"),
            )

        if result is None:
            logger.warning(
                "%s : prix actuel indisponible.",
                symbol,
            )
            return None

        price = float(result)

        if not math.isfinite(price) or price <= 0:
            logger.warning(
                "%s : prix actuel invalide.",
                symbol,
            )
            return None

        return price

    except (TypeError, ValueError, OverflowError) as exc:
        logger.warning(
            "%s : format de prix invalide : %s",
            symbol,
            exc,
        )
        return None

    except Exception as exc:
        logger.warning(
            "%s : erreur de récupération du prix : %s",
            symbol,
            exc,
        )
        return None


# ============================================================
# SIGNAUX ET ZONES
# ============================================================

def get_signal_value(signal, *keys, default=None):
    if not isinstance(signal, dict):
        return default

    for key in keys:
        if key in signal and signal[key] is not None:
            return signal[key]

    return default


def store_signal(signal, message):
    signal_id = str(
        get_signal_value(
            signal,
            "signal_id",
            "id",
            default="",
        )
    )

    symbol = str(
        get_signal_value(signal, "symbol", default="")
    )

    direction = str(
        get_signal_value(
            signal,
            "direction",
            "type",
            "side",
            default="",
        )
    )

    try:
        entry = float(
            get_signal_value(signal, "entry", "entry_price")
        )
        stop_loss = float(
            get_signal_value(signal, "stop_loss", "sl")
        )
        take_profit = float(
            get_signal_value(signal, "take_profit", "tp")
        )
        rr = float(
            get_signal_value(
                signal,
                "rr",
                "risk_reward",
                default=0,
            )
        )
    except (TypeError, ValueError, OverflowError):
        logger.warning(
            "%s : niveaux du signal invalides, signal ignoré.",
            symbol or "Symbole inconnu",
        )
        return False

    if not signal_id or not symbol:
        logger.warning("Signal sans identifiant ou symbole.")
        return False

    if not all(map(math.isfinite, (entry, stop_loss, take_profit, rr))):
        logger.warning("%s : valeurs non finies.", symbol)
        return False

    if entry <= 0 or stop_loss <= 0 or take_profit <= 0:
        logger.warning("%s : niveaux de prix non positifs.", symbol)
        return False

    if rr < MIN_RR:
        logger.info(
            "%s : signal rejeté, RR %.2f inférieur à %.2f.",
            symbol,
            rr,
            MIN_RR,
        )
        return False

    now = datetime.now(timezone.utc).isoformat()

    zone_low = get_signal_value(signal, "zone_low")
    zone_high = get_signal_value(signal, "zone_high")

    with connect_db() as conn:
        cursor = conn.execute("""
            INSERT OR IGNORE INTO signals (
                signal_id,
                symbol,
                direction,
                entry,
                stop_loss,
                take_profit,
                rr,
                status,
                created_at,
                message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'DETECTED', ?, ?)
        """, (
            signal_id,
            symbol,
            direction,
            entry,
            stop_loss,
            take_profit,
            rr,
            now,
            message,
        ))

        inserted = cursor.rowcount == 1

        if inserted:
            conn.execute("""
                INSERT OR IGNORE INTO poi_zones (
                    signal_id,
                    symbol,
                    direction,
                    zone_low,
                    zone_high,
                    entry,
                    stop_loss,
                    take_profit,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'POI_DETECTED', ?, ?)
            """, (
                signal_id,
                symbol,
                direction,
                zone_low,
                zone_high,
                entry,
                stop_loss,
                take_profit,
                now,
                now,
            ))

        conn.commit()

    if not inserted:
        logger.info(
            "%s : signal déjà enregistré, aucune répétition.",
            symbol,
        )
        return False

    return True


# ============================================================
# ANALYSE D'UN SYMBOLE
# ============================================================

def analyze_symbol(symbol):
    logger.info("=" * 55)
    logger.info("Analyse de %s", symbol)

    d1 = fetch_candles(
        symbol,
        "D1",
        D1_CANDLE_COUNT,
    )

    if d1 is None:
        logger.warning(
            "%s : analyse ignorée, données D1 insuffisantes.",
            symbol,
        )
        return 0

    h4 = fetch_candles(
        symbol,
        "H4",
        H4_CANDLE_COUNT,
    )

    if h4 is None:
        logger.warning(
            "%s : analyse ignorée, données H4 insuffisantes.",
            symbol,
        )
        return 0

    price = fetch_current_price(symbol)

    if price is None:
        logger.warning(
            "%s : analyse ignorée, prix indisponible.",
            symbol,
        )
        return 0

    diagnostics = {}

    try:
        signals = find_signals(
            symbol=symbol,
            d1=d1,
            h4=h4,
            price_now=price,
            diagnostics=diagnostics,
        )

    except Exception:
        logger.exception(
            "%s : erreur pendant l'analyse stratégique.",
            symbol,
        )
        return 0

    if not signals:
        logger.info(
            "%s : aucun setup D1/H4 valide. "
            "Diagnostics : %s",
            symbol,
            diagnostics,
        )
        return 0

    if isinstance(signals, dict):
        signals = [signals]

    stored_count = 0

    for signal in signals:
        if not isinstance(signal, dict):
            logger.warning(
                "%s : signal ignoré, format inattendu.",
                symbol,
            )
            continue

        try:
            message = format_message(signal)
        except Exception:
            logger.exception(
                "%s : impossible de formater le signal.",
                symbol,
            )
            continue

        if not store_signal(signal, message):
            continue

        stored_count += 1

        # Le scanner ne passe jamais d'ordre.
        logger.info(
            "%s : signal enregistré. "
            "DRY_RUN=%s ; exécution automatique désactivée.",
            symbol,
            DRY_RUN,
        )

        send_telegram(message)

    return stored_count


# ============================================================
# MAIN
# ============================================================

def main():
    started_at = datetime.now(timezone.utc).isoformat()

    logger.info("=" * 60)
    logger.info("%s — SCANNER D1/H4", BOT_NAME)
    logger.info("D1 : %s bougies", D1_CANDLE_COUNT)
    logger.info("H4 : %s bougies", H4_CANDLE_COUNT)
    logger.info("RR minimum : 1:%.1f", MIN_RR)
    logger.info("DRY_RUN : %s", DRY_RUN)
    logger.info("Exécution automatique des ordres : DÉSACTIVÉE")
    logger.info(
        "Telegram configuré : %s",
        bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
    )
    logger.info("=" * 60)

    init_db()

    checked = 0
    found = 0
    errors = []

    try:
        for symbol in SYMBOLS:
            checked += 1

            try:
                found += analyze_symbol(symbol)

            except Exception as exc:
                errors.append(f"{symbol}: {exc}")
                logger.exception(
                    "%s : erreur inattendue.",
                    symbol,
                )

            time.sleep(PAUSE_BETWEEN_SYMBOLS)

        status = "SUCCESS" if not errors else "PARTIAL"

        log_run(
            started_at,
            status,
            checked,
            found,
            "; ".join(errors),
        )

        logger.info("=" * 60)
        logger.info("Analyse terminée.")
        logger.info("Symboles parcourus : %s", checked)
        logger.info("Nouveaux signaux enregistrés : %s", found)
        logger.info("Erreurs : %s", len(errors))
        logger.info("Ordres envoyés : 0")
        logger.info("=" * 60)

    except Exception as exc:
        logger.exception("Échec général de l'analyse.")

        log_run(
            started_at,
            "FAILED",
            checked,
            found,
            str(exc),
        )

        raise


if __name__ == "__main__":
    main()
