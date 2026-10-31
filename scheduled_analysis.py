"""
TRADER AI PRO — SCANNER TRENDLINE + CONFLUENCE

Stratégie :
- Analyse des tendances.
- Droites de tendance.
- Supports et résistances horizontaux.
- Recherche de confluences.
- Entrées anticipées.
- Analyse D1, H4, H2 et H1.
- Alertes Telegram uniquement.
- Aucune exécution automatique d'ordres.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
import time

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from deriv_market import get_candles, get_current_price
from strategy import find_signals, format_message


# ============================================================
# CONFIGURATION
# ============================================================

BOT_NAME = "TRADER AI PRO"

D1_CANDLE_COUNT = 200
H4_CANDLE_COUNT = 200
H2_CANDLE_COUNT = 200
H1_CANDLE_COUNT = 200

TIMEFRAMES = {
    "D1": D1_CANDLE_COUNT,
    "H4": H4_CANDLE_COUNT,
    "H2": H2_CANDLE_COUNT,
    "H1": H1_CANDLE_COUNT,
}

REQUEST_TIMEOUT = 20
PAUSE_BETWEEN_SYMBOLS = 1.0

DRY_RUN = (
    os.getenv("DRY_RUN", "true").strip().lower() != "false"
)

# Sécurité : aucun ordre automatique.
AUTO_EXECUTION_ENABLED = False

ENABLE_TELEGRAM_ALERTS = (
    os.getenv(
        "ENABLE_TELEGRAM_ALERTS",
        "true",
    ).strip().lower() == "true"
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

DB_PATH = Path(
    os.getenv(
        "TRADER_AI_DB_PATH",
        "state/trader_ai_pro.sqlite3",
    )
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
# JOURNALISATION
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(BOT_NAME)


# ============================================================
# BASE DE DONNÉES
# ============================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=30,
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_db() -> None:
    """Initialise les tables du scanner."""

    with connect_db() as connection:
        connection.execute("""
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

        connection.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry REAL NOT NULL,
                stop_loss REAL NOT NULL,
                take_profit REAL NOT NULL,
                rr REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'DETECTED',
                created_at TEXT NOT NULL,
                message TEXT
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_symbol
            ON signals(symbol)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_created_at
            ON signals(created_at)
        """)

        connection.commit()


def start_analysis_run() -> int:
    with connect_db() as connection:
        cursor = connection.execute(
            """
            INSERT INTO analysis_runs (
                started_at,
                status,
                details
            )
            VALUES (?, ?, ?)
            """,
            (
                utc_now(),
                "RUNNING",
                "TRENDLINE + CONFLUENCE",
            ),
        )

        return int(cursor.lastrowid)


def finish_analysis_run(
    run_id: int,
    status: str,
    symbols_checked: int,
    signals_found: int,
    details: str = "",
) -> None:
    with connect_db() as connection:
        connection.execute(
            """
            UPDATE analysis_runs
            SET finished_at = ?,
                status = ?,
                symbols_checked = ?,
                signals_found = ?,
                details = ?
            WHERE id = ?
            """,
            (
                utc_now(),
                status,
                symbols_checked,
                signals_found,
                details[:4000],
                run_id,
            ),
        )

        connection.commit()


def store_signal(
    signal: dict[str, Any],
    message: str,
) -> bool:
    """
    Enregistre un signal valide.

    Aucun RR minimum arbitraire n'est imposé.
    """

    try:
        signal_id = str(signal["signal_id"])
        symbol = str(signal["symbol"])
        direction = str(signal["direction"]).upper()

        entry = float(signal["entry"])
        stop_loss = float(signal["stop_loss"])
        take_profit = float(signal["take_profit"])
        rr = float(signal["rr"])

    except (KeyError, TypeError, ValueError):
        logger.warning("Signal ignoré : données manquantes.")
        return False

    if not signal_id or not symbol:
        return False

    if direction not in ("BUY", "SELL"):
        return False

    values = [entry, stop_loss, take_profit, rr]

    if any(not math.isfinite(value) for value in values):
        return False

    if min(entry, stop_loss, take_profit) <= 0 or rr <= 0:
        return False

    if direction == "BUY":
        if not stop_loss < entry < take_profit:
            logger.warning(
                "Niveaux BUY incohérents pour %s.",
                symbol,
            )
            return False

        calculated_rr = (
            (take_profit - entry) / (entry - stop_loss)
        )

    else:
        if not take_profit < entry < stop_loss:
            logger.warning(
                "Niveaux SELL incohérents pour %s.",
                symbol,
            )
            return False

        calculated_rr = (
            (entry - take_profit) / (stop_loss - entry)
        )

    if not math.isfinite(calculated_rr) or calculated_rr <= 0:
        return False

    rr = round(calculated_rr, 4)

    with connect_db() as connection:
        cursor = connection.execute(
            """
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id,
                symbol,
                direction,
                entry,
                stop_loss,
                take_profit,
                rr,
                "DETECTED",
                utc_now(),
                message,
            ),
        )

        connection.commit()

        inserted = cursor.rowcount == 1

    if not inserted:
        logger.info(
            "Signal déjà enregistré : %s %s",
            symbol,
            direction,
        )

    return inserted


# ============================================================
# TELEGRAM
# ============================================================

def telegram_is_configured() -> bool:
    return bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)


def send_telegram(message: str) -> bool:
    if not ENABLE_TELEGRAM_ALERTS:
        logger.info("Alertes Telegram désactivées.")
        return False

    if not telegram_is_configured():
        logger.warning(
            "Telegram non configuré : token ou chat ID absent."
        )
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
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

        logger.info("Alerte Telegram envoyée.")
        return True

    except Exception as exc:
        logger.error(
            "Échec de l'envoi Telegram : %s",
            exc,
        )
        return False


# ============================================================
# NORMALISATION DES BOUGIES
# ============================================================

def normalize_candles(
    candles: Any,
) -> list[dict[str, Any]]:
    if isinstance(candles, dict):
        candles = candles.get("candles", [])

    if not isinstance(candles, list):
        return []

    result = []
    seen_epochs = set()

    for item in candles:
        if not isinstance(item, dict):
            continue

        try:
            epoch = int(item["epoch"])
            opening = float(item["open"])
            high = float(item["high"])
            low = float(item["low"])
            close = float(item["close"])

        except (KeyError, TypeError, ValueError):
            continue

        values = [opening, high, low, close]

        if any(
            not math.isfinite(value) or value <= 0
            for value in values
        ):
            continue

        if high < max(opening, close):
            continue

        if low > min(opening, close):
            continue

        if high < low or epoch in seen_epochs:
            continue

        seen_epochs.add(epoch)

        result.append({
            "epoch": epoch,
            "open": opening,
            "high": high,
            "low": low,
            "close": close,
        })

    result.sort(key=lambda candle: candle["epoch"])

    return result


# ============================================================
# RÉCUPÉRATION DES BOUGIES
# ============================================================

def fetch_candles(
    symbol: str,
    timeframe: str,
    required_count: int,
) -> list[dict[str, Any]]:
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
        return []

    if not isinstance(response, dict):
        logger.warning(
            "%s %s : réponse Deriv invalide.",
            symbol,
            timeframe,
        )
        return []

    if response.get("error"):
        logger.warning(
            "%s %s : %s",
            symbol,
            timeframe,
            response["error"],
        )
        return []

    candles = normalize_candles(
        response.get("candles", [])
    )

    if len(candles) < required_count:
        logger.warning(
            "%s %s : %s/%s bougies disponibles.",
            symbol,
            timeframe,
            len(candles),
            required_count,
        )
        return []

    candles = candles[-required_count:]

    logger.info(
        "%s %s : %s bougies utilisables.",
        symbol,
        timeframe,
        len(candles),
    )

    return candles


# ============================================================
# PRIX COURANT
# ============================================================

def fetch_current_price(
    symbol: str,
) -> float | None:
    try:
        response = get_current_price(
            symbol,
            timeout=REQUEST_TIMEOUT,
        )

    except Exception as exc:
        logger.warning(
            "%s : erreur de récupération du prix : %s",
            symbol,
            exc,
        )
        return None

    if isinstance(response, dict):
        if response.get("error"):
            logger.warning(
                "%s : %s",
                symbol,
                response["error"],
            )
            return None

        response = response.get(
            "price",
            response.get("quote"),
        )

    try:
        price = float(response)

    except (TypeError, ValueError):
        logger.warning(
            "%s : prix indisponible.",
            symbol,
        )
        return None

    if not math.isfinite(price) or price <= 0:
        return None

    return price


# ============================================================
# ANALYSE D'UN INDICE
# ============================================================

def analyze_symbol(
    symbol: str,
) -> list[dict[str, Any]]:
    logger.info("=" * 60)
    logger.info("Analyse de %s", symbol)

    candles_by_timeframe = {}

    for timeframe, count in TIMEFRAMES.items():
        candles_by_timeframe[timeframe] = fetch_candles(
            symbol,
            timeframe,
            count,
        )

    current_price = fetch_current_price(symbol)

    if current_price is None:
        logger.warning(
            "%s : analyse ignorée, prix courant indisponible.",
            symbol,
        )
        return []

    diagnostics: dict[str, Any] = {}

    try:
        signals = find_signals(
            symbol=symbol,
            d1=candles_by_timeframe.get("D1"),
            h4=candles_by_timeframe.get("H4"),
            h2=candles_by_timeframe.get("H2"),
            h1=candles_by_timeframe.get("H1"),
            price_now=current_price,
            diagnostics=diagnostics,
        )

    except Exception:
        logger.exception(
            "%s : erreur dans le moteur de stratégie.",
            symbol,
        )
        return []

    for timeframe, detail in diagnostics.items():
        logger.info(
            "%s | %s : %s",
            symbol,
            timeframe,
            detail,
        )

    if not signals:
        logger.info(
            "%s : aucune configuration valide.",
            symbol,
        )
        return []

    valid_signals = []

    for signal in signals:
        if not isinstance(signal, dict):
            continue

        if (
            signal.get("strategy")
            != "TRENDLINE_SUPPORT_RESISTANCE"
        ):
            logger.warning(
                "%s : signal ignoré, stratégie non conforme.",
                symbol,
            )
            continue

        if signal.get("direction") not in ("BUY", "SELL"):
            continue

        if signal.get("timeframe") not in TIMEFRAMES:
            continue

        valid_signals.append(signal)

    return valid_signals


# ============================================================
# TRAITEMENT DES SIGNAUX
# ============================================================

def process_signal(
    signal: dict[str, Any],
) -> bool:
    try:
        message = format_message(signal)

    except Exception:
        logger.exception(
            "Impossible de formater le signal."
        )
        return False

    is_new = store_signal(signal, message)

    if not is_new:
        return False

    logger.info(
        "NOUVEAU SIGNAL : %s %s | TF=%s | RR=1:%s",
        signal["symbol"],
        signal["direction"],
        signal["timeframe"],
        signal["rr"],
    )

    # Aucun ordre n'est envoyé à Deriv.
    if ENABLE_TELEGRAM_ALERTS:
        send_telegram(message)

    return True


# ============================================================
# EXÉCUTION PRINCIPALE
# ============================================================

def main() -> None:
    started_at = utc_now()

    logger.info("=" * 65)
    logger.info(
        "%s — SCANNER TRENDLINE + CONFLUENCE",
        BOT_NAME,
    )
    logger.info("=" * 65)

    logger.info("Début : %s", started_at)
    logger.info("Timeframes : D1 → H4 → H2 → H1")

    for timeframe, count in TIMEFRAMES.items():
        logger.info(
            "Bougies %s : %s",
            timeframe,
            count,
        )

    logger.info(
        "Alertes Telegram : %s",
        ENABLE_TELEGRAM_ALERTS,
    )

    logger.info(
        "Telegram configuré : %s",
        telegram_is_configured(),
    )

    logger.info("DRY_RUN : %s", DRY_RUN)
    logger.info("Exécution automatique : DÉSACTIVÉE")
    logger.info("Nombre d'indices : %s", len(SYMBOLS))
    logger.info("RR minimum imposé : aucun")

    if AUTO_EXECUTION_ENABLED:
        raise RuntimeError(
            "L'exécution automatique doit rester désactivée."
        )

    init_db()

    run_id = start_analysis_run()

    symbols_checked = 0
    signals_found = 0
    errors = []

    try:
        for index, symbol in enumerate(
            SYMBOLS,
            start=1,
        ):
            logger.info(
                "[%s/%s] %s",
                index,
                len(SYMBOLS),
                symbol,
            )

            try:
                signals = analyze_symbol(symbol)

                symbols_checked += 1

                for signal in signals:
                    if process_signal(signal):
                        signals_found += 1

            except Exception as exc:
                errors.append(f"{symbol}: {exc}")

                logger.exception(
                    "Erreur pendant l'analyse de %s.",
                    symbol,
                )

            if index < len(SYMBOLS):
                time.sleep(PAUSE_BETWEEN_SYMBOLS)

        status = "PARTIAL" if errors else "SUCCESS"

        details = (
            "Stratégie=TRENDLINE+CONFLUENCE; "
            f"erreurs={len(errors)}; "
            f"alertes_nouvelles={signals_found}"
        )

        if errors:
            details += "; " + " | ".join(errors[:10])

        finish_analysis_run(
            run_id=run_id,
            status=status,
            symbols_checked=symbols_checked,
            signals_found=signals_found,
            details=details,
        )

    except Exception as exc:
        finish_analysis_run(
            run_id=run_id,
            status="FAILED",
            symbols_checked=symbols_checked,
            signals_found=signals_found,
            details=str(exc),
        )
        raise

    logger.info("=" * 65)
    logger.info("ANALYSE TERMINÉE")
    logger.info("Indices analysés : %s", symbols_checked)
    logger.info("Nouveaux signaux : %s", signals_found)
    logger.info("Erreurs : %s", len(errors))
    logger.info("Exécution automatique : DÉSACTIVÉE")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
