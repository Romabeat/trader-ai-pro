"""TRADER AI PRO - Scanner SMC H4/H1.

Analyse technique indicative, diagnostics des signaux,
alertes Telegram optionnelles et journal SQLite.

IMPORTANT :
- Aucun ordre automatique n'est envoyé à Deriv.
- Les décisions et exécutions restent manuelles.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import requests

from deriv_market import get_candles
from strategy import find_signals, format_message


# ============================================================
# CONFIGURATION
# ============================================================

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

ENABLE_TELEGRAM_ALERTS = (
    os.environ.get("ENABLE_TELEGRAM_ALERTS", "false").strip().lower()
    == "true"
)

DRY_RUN = (
    os.environ.get("DRY_RUN", "true").strip().lower()
    != "false"
)

DATABASE_PATH = Path(
    os.environ.get(
        "TRADER_DB_PATH",
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

CANDLE_COUNT = 100
REQUEST_TIMEOUT = 15
PAUSE_BETWEEN_SYMBOLS = 1


# ============================================================
# JOURNALISATION
# ============================================================

def log(message: str) -> None:
    timestamp = time.strftime(
        "%Y-%m-%d %H:%M:%S UTC",
        time.gmtime(),
    )
    print(
        f"[TRADER AI PRO] {timestamp} {message}",
        flush=True,
    )


def connect_db() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    db = sqlite3.connect(
        str(DATABASE_PATH),
        timeout=20,
    )

    db.execute("PRAGMA journal_mode=WAL")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            signal_id TEXT PRIMARY KEY,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry REAL,
            stop_loss REAL,
            take_profit REAL,
            rr REAL,
            status TEXT DEFAULT 'ENVOYE',
            outcome TEXT,
            result_r REAL,
            notes TEXT,
            message TEXT
        )
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            event TEXT NOT NULL,
            detail TEXT
        )
        """
    )

    db.commit()
    return db


def log_event(
    db: sqlite3.Connection,
    event: str,
    detail: dict | str,
) -> None:
    if not isinstance(detail, str):
        detail = json.dumps(
            detail,
            ensure_ascii=False,
            default=str,
        )

    db.execute(
        """
        INSERT INTO run_log (event, detail)
        VALUES (?, ?)
        """,
        (event, detail),
    )
    db.commit()


# ============================================================
# DONNÉES DE MARCHÉ
# ============================================================

def fetch_candles(
    symbol: str,
    timeframe: str,
) -> list | None:
    try:
        response = get_candles(
            symbol,
            timeframe,
            count=CANDLE_COUNT,
            timeout=REQUEST_TIMEOUT,
        )

        if not isinstance(response, dict):
            log(
                f"{symbol} {timeframe}: "
                "réponse de marché invalide."
            )
            return None

        candles = response.get("candles")

        if not isinstance(candles, list):
            log(
                f"{symbol} {timeframe}: "
                "champ candles absent ou invalide."
            )
            return None

        if len(candles) < 30:
            log(
                f"{symbol} {timeframe}: "
                f"données insuffisantes ({len(candles)} bougies)."
            )
            return None

        log(
            f"{symbol} {timeframe}: "
            f"{len(candles)} bougies reçues."
        )

        return candles

    except Exception as exc:
        log(
            f"{symbol} {timeframe}: "
            f"erreur de récupération: {exc}"
        )
        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message: str) -> bool:
    if not ENABLE_TELEGRAM_ALERTS:
        log(
            "Alerte Telegram désactivée par la configuration."
        )
        return False

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log(
            "ERREUR TELEGRAM: TELEGRAM_TOKEN ou "
            "TELEGRAM_CHAT_ID manquant dans les secrets."
        )
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
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

        result = response.json()

        if not result.get("ok", False):
            log(
                "Échec Telegram: l'API n'a pas confirmé "
                "l'envoi du message."
            )
            return False

        log("Alerte Telegram envoyée avec succès.")
        return True

    except (requests.RequestException, ValueError) as exc:
        log(f"Erreur d'envoi Telegram: {exc}")
        return False


# ============================================================
# GESTION DES SIGNAUX
# ============================================================

def already_recorded(
    db: sqlite3.Connection,
    signal_id: str,
) -> bool:
    row = db.execute(
        """
        SELECT 1
        FROM signals
        WHERE signal_id = ?
        LIMIT 1
        """,
        (signal_id,),
    ).fetchone()

    return row is not None


def store_signal(
    db: sqlite3.Connection,
    signal: dict,
    message: str,
) -> None:
    db.execute(
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
            notes,
            message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(signal.get("signal_id", "")),
            str(signal.get("symbol", "")),
            str(signal.get("direction", "")),
            signal.get("entry"),
            signal.get("stop_loss"),
            signal.get("take_profit"),
            signal.get("rr"),
            "ENVOYE",
            "Signal technique indicatif; exécution manuelle.",
            message,
        ),
    )

    log_event(
        db,
        "SIGNAL_SENT",
        {
            "signal_id": signal.get("signal_id"),
            "symbol": signal.get("symbol"),
            "direction": signal.get("direction"),
            "rr": signal.get("rr"),
        },
    )

    db.commit()


# ============================================================
# DIAGNOSTICS DE STRATÉGIE
# ============================================================

def log_diagnostics(
    symbol: str,
    diagnostics: dict,
) -> None:
    reason = diagnostics.get(
        "reason",
        "Aucun motif détaillé fourni par strategy.py",
    )

    structure = diagnostics.get(
        "structure",
        "inconnue",
    )

    rr = diagnostics.get(
        "rr",
        "N/A",
    )

    order_block = diagnostics.get("order_block")

    log(
        f"{symbol}: aucun signal SMC confirmé | "
        f"Motif: {reason} | "
        f"Structure H4: {structure} | "
        f"RR: {rr}"
    )

    if order_block is not None:
        log(
            f"{symbol}: diagnostic Order Block: "
            f"{json.dumps(order_block, ensure_ascii=False, default=str)}"
        )


# ============================================================
# ANALYSE D'UN ACTIF
# ============================================================

def analyze_symbol(
    db: sqlite3.Connection,
    symbol: str,
) -> tuple[int, int]:
    log(f"Début de l'analyse de {symbol}.")

    h4 = fetch_candles(symbol, "H4")
    h1 = fetch_candles(symbol, "H1")

    if h4 is None or h1 is None:
        log(
            f"{symbol}: analyse ignorée, "
            "données H4 ou H1 indisponibles."
        )

        log_event(
            db,
            "DATA_ERROR",
            {
                "symbol": symbol,
                "h4_available": h4 is not None,
                "h1_available": h1 is not None,
            },
        )

        return 0, 0

    diagnostics: dict = {}

    try:
        signals = find_signals(
            symbol=symbol,
            h4=h4,
            h1=h1,
            diagnostics=diagnostics,
        )

    except TypeError as exc:
        log(
            f"{symbol}: erreur de compatibilité avec "
            f"strategy.py: {exc}"
        )
        log(
            "Vérifie que strategy.py contient bien "
            "find_signals(..., diagnostics=None)."
        )

        log_event(
            db,
            "STRATEGY_COMPATIBILITY_ERROR",
            {
                "symbol": symbol,
                "error": str(exc),
            },
        )

        return 0, 0

    except Exception as exc:
        log(
            f"{symbol}: erreur pendant l'analyse "
            f"de stratégie: {exc}"
        )

        log_event(
            db,
            "STRATEGY_ERROR",
            {
                "symbol": symbol,
                "error": str(exc),
            },
        )

        return 0, 0

    if not signals:
        log_diagnostics(symbol, diagnostics)

        log_event(
            db,
            "NO_SIGNAL",
            {
                "symbol": symbol,
                "diagnostics": diagnostics,
            },
        )

        return 0, 0

    detected = 0
    sent = 0

    for signal in signals:
        detected += 1

        signal_id = str(
            signal.get("signal_id", "")
        ).strip()

        if not signal_id:
            log(
                f"{symbol}: signal rejeté, "
                "identifiant signal_id manquant."
            )
            continue

        if already_recorded(db, signal_id):
            log(
                f"{symbol}: signal déjà enregistré, "
                f"ignoré pour éviter un doublon ({signal_id})."
            )
            continue

        try:
            message = format_message(signal)
        except Exception as exc:
            log(
                f"{symbol}: impossible de formater "
                f"le signal: {exc}"
            )
            continue

        if not ENABLE_TELEGRAM_ALERTS:
            log(
                f"{symbol}: signal détecté mais Telegram "
                "est désactivé. Aucun message envoyé."
            )
            log(message)
            continue

        if not send_telegram(message):
            log(
                f"{symbol}: signal détecté, mais l'envoi "
                "Telegram a échoué. Signal non enregistré "
                "comme envoyé."
            )
            continue

        store_signal(
            db,
            signal,
            message,
        )

        sent += 1

    return detected, sent


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main() -> None:
    log("=" * 60)
    log("DÉMARRAGE DE TRADER AI PRO")
    log(f"Actifs à analyser: {len(SYMBOLS)}")
    log(f"Nombre de bougies demandé: {CANDLE_COUNT}")
    log(
        "Alertes Telegram: "
        + (
            "ACTIVÉES"
            if ENABLE_TELEGRAM_ALERTS
            else "DÉSACTIVÉES"
        )
    )
    log(
        "Exécution automatique des ordres: "
        "DÉSACTIVÉE"
    )

    if ENABLE_TELEGRAM_ALERTS:
        if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
            log(
                "Configuration Telegram: "
                "secrets présents."
            )
        else:
            log(
                "ATTENTION: Telegram est activé, "
                "mais un ou plusieurs secrets sont absents."
            )

    if not DRY_RUN:
        log(
            "ATTENTION: DRY_RUN=false. "
            "Ce scanner ne contient toutefois aucune "
            "fonction d'envoi d'ordre à Deriv."
        )

    db = connect_db()

    total_detected = 0
    total_sent = 0
    total_errors = 0

    try:
        for index, symbol in enumerate(SYMBOLS):
            try:
                detected, sent = analyze_symbol(
                    db,
                    symbol,
                )

                total_detected += detected
                total_sent += sent

            except Exception as exc:
                total_errors += 1

                log(
                    f"Erreur inattendue sur {symbol}: {exc}"
                )

                log_event(
                    db,
                    "UNEXPECTED_ERROR",
                    {
                        "symbol": symbol,
                        "error": str(exc),
                    },
                )

            if index < len(SYMBOLS) - 1:
                time.sleep(PAUSE_BETWEEN_SYMBOLS)

    finally:
        db.close()

    log("=" * 60)
    log("ANALYSE TERMINÉE")
    log(f"Actifs analysés: {len(SYMBOLS)}")
    log(f"Signaux détectés: {total_detected}")
    log(f"Alertes envoyées: {total_sent}")
    log(f"Erreurs inattendues: {total_errors}")
    log(
        "Ordres envoyés à Deriv: 0 "
        "(exécution manuelle uniquement)"
    )
    log("=" * 60)


if __name__ == "__main__":
    main()
