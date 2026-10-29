"""TRADER AI PRO - Scanner SMC H4/H1.
Analyse technique indicative, alertes Telegram optionnelles,
journal SQLite. Aucun ordre n'est envoyé à Deriv.
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

# Ce programme ne contient aucune fonction d'exécution d'ordres.
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() != "false"

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

TIMEFRAMES = ("H4", "H1")

CANDLE_COUNT = 100
REQUEST_TIMEOUT = 15
PAUSE_BETWEEN_SYMBOLS = 1


# ============================================================
# JOURNALISATION
# ============================================================

def log(message: str) -> None:
    """Affiche un message horodaté dans les logs."""
    print(
        f"[TRADER AI PRO] {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())} "
        f"{message}",
        flush=True,
    )


def connect_db() -> sqlite3.Connection:
    """Initialise la base de données et ses tables."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(str(DATABASE_PATH), timeout=20)

    db.execute("PRAGMA journal_mode=WAL")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            signal_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry REAL NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL,
            rr REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'ENVOYE',
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
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
    detail: dict,
) -> None:
    """Enregistre un événement du scanner."""
    db.execute(
        "INSERT INTO run_log(event, detail) VALUES (?, ?)",
        (
            event,
            json.dumps(detail, ensure_ascii=False),
        ),
    )
    db.commit()


# ============================================================
# DONNÉES DE MARCHÉ DERIV
# ============================================================

def fetch_candles(
    symbol: str,
    timeframe: str,
) -> list[dict] | None:
    """
    Récupère les bougies depuis deriv_market.py.

    get_candles() renvoie un dictionnaire contenant la clé
    'candles'. Cette fonction extrait la liste attendue
    par strategy.py.
    """
    try:
        result = get_candles(
            symbol,
            timeframe,
            count=CANDLE_COUNT,
            timeout=REQUEST_TIMEOUT,
        )

        if not isinstance(result, dict):
            log(
                f"{symbol} {timeframe}: "
                "réponse Deriv invalide."
            )
            return None

        if result.get("error"):
            log(
                f"{symbol} {timeframe}: "
                f"{result['error']}"
            )
            return None

        rows = result.get("candles")

        if not isinstance(rows, list):
            log(
                f"{symbol} {timeframe}: "
                "liste de bougies absente."
            )
            return None

        if len(rows) < 30:
            log(
                f"{symbol} {timeframe}: "
                f"données insuffisantes ({len(rows)} bougies)."
            )
            return None

        log(
            f"{symbol} {timeframe}: "
            f"{len(rows)} bougies récupérées."
        )

        return rows

    except Exception as exc:
        log(
            f"{symbol} {timeframe}: "
            f"erreur données: {type(exc).__name__}: {exc}"
        )
        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message: str) -> bool:
    """Envoie un message Telegram uniquement si les alertes sont activées."""
    if not ENABLE_TELEGRAM_ALERTS:
        log(
            "Telegram désactivé : "
            "ENABLE_TELEGRAM_ALERTS n'est pas true."
        )
        return False

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log(
            "ERREUR : secrets TELEGRAM_TOKEN ou "
            "TELEGRAM_CHAT_ID manquants."
        )
        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        payload = response.json()

        if not payload.get("ok"):
            log(
                "Erreur Telegram API : "
                f"{payload.get('description', 'réponse invalide')}"
            )
            return False

        return True

    except (requests.RequestException, ValueError) as exc:
        log(
            "Erreur d'envoi Telegram : "
            f"{type(exc).__name__}: {exc}"
        )
        return False


# ============================================================
# GESTION DES SIGNAUX
# ============================================================

def already_recorded(
    db: sqlite3.Connection,
    signal_id: str,
) -> bool:
    """Vérifie si un signal est déjà présent dans la base."""
    row = db.execute(
        "SELECT 1 FROM signals WHERE signal_id = ?",
        (signal_id,),
    ).fetchone()

    return row is not None


def store_signal(
    db: sqlite3.Connection,
    signal: dict,
    message: str,
) -> None:
    """Enregistre un signal après confirmation de son envoi."""
    db.execute(
        """
        INSERT INTO signals (
            signal_id,
            created_at,
            symbol,
            direction,
            entry,
            stop_loss,
            take_profit,
            rr,
            status,
            message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ENVOYE', ?)
        """,
        (
            signal["signal_id"],
            signal["timestamp_utc"],
            signal["symbol"],
            signal["direction"],
            signal["entry"],
            signal["stop_loss"],
            signal["take_profit"],
            signal["rr"],
            message,
        ),
    )

    log_event(
        db,
        "SIGNAL_SENT",
        {
            "signal_id": signal["signal_id"],
            "symbol": signal["symbol"],
            "direction": signal["direction"],
        },
    )

    db.commit()


def analyze_symbol(
    db: sqlite3.Connection,
    symbol: str,
) -> tuple[int, int]:
    """Analyse un actif et traite les éventuels signaux."""
    log(f"Analyse de {symbol}...")

    h4 = fetch_candles(symbol, "H4")
    h1 = fetch_candles(symbol, "H1")

    if h4 is None or h1 is None:
        log(
            f"{symbol}: analyse ignorée, "
            "données H4 ou H1 indisponibles."
        )
        return 0, 1

    try:
        signals = find_signals(
            symbol=symbol,
            h4=h4,
            h1=h1,
        )
    except Exception as exc:
        log(
            f"{symbol}: erreur du moteur SMC : "
            f"{type(exc).__name__}: {exc}"
        )
        return 0, 1

    if not signals:
        log(f"{symbol}: aucun signal SMC confirmé.")
        return 0, 0

    sent = 0

    for signal in signals:
        signal_id = signal.get("signal_id")

        if not signal_id:
            log(f"{symbol}: signal ignoré, identifiant absent.")
            continue

        if already_recorded(db, signal_id):
            log(
                f"{symbol}: doublon ignoré "
                f"({signal_id})."
            )
            continue

        message = format_message(signal)

        if not ENABLE_TELEGRAM_ALERTS:
            log(
                f"{symbol}: signal détecté, "
                "mais Telegram est désactivé. "
                "Aucun message envoyé."
            )
            continue

        if not send_telegram(message):
            log(
                f"{symbol}: envoi non confirmé. "
                "Signal non marqué comme envoyé."
            )
            continue

        try:
            store_signal(db, signal, message)
            sent += 1

            log(
                f"{symbol}: signal envoyé et journalisé "
                f"({signal_id})."
            )

        except sqlite3.IntegrityError:
            log(
                f"{symbol}: doublon empêché "
                "par la base de données."
            )

        except sqlite3.Error as exc:
            log(
                f"{symbol}: erreur SQLite après envoi : "
                f"{exc}. Vérifier le journal."
            )

    return sent, 0


# ============================================================
# SCAN PRINCIPAL
# ============================================================

def main() -> None:
    log("=" * 55)
    log("DÉMARRAGE DE TRADER AI PRO")
    log("Scanner SMC H4/H1")
    log(
        "Alertes Telegram : "
        f"{'ACTIVÉES' if ENABLE_TELEGRAM_ALERTS else 'DÉSACTIVÉES'}"
    )
    log("Exécution automatique des ordres : DÉSACTIVÉE")
    log("=" * 55)

    if not DRY_RUN:
        log(
            "AVERTISSEMENT : DRY_RUN=false détecté. "
            "Ce programme ne contient cependant aucune "
            "fonction d'exécution d'ordres."
        )

    try:
        db = connect_db()
    except sqlite3.Error as exc:
        log(f"Impossible d'ouvrir la base SQLite : {exc}")
        raise

    total_sent = 0
    total_errors = 0

    try:
        for index, symbol in enumerate(SYMBOLS):
            sent, errors = analyze_symbol(db, symbol)

            total_sent += sent
            total_errors += errors

            if index < len(SYMBOLS) - 1:
                time.sleep(PAUSE_BETWEEN_SYMBOLS)

        log_event(
            db,
            "SCAN_FINISHED",
            {
                "sent": total_sent,
                "errors": total_errors,
                "symbols_scanned": len(SYMBOLS),
                "telegram_enabled": ENABLE_TELEGRAM_ALERTS,
            },
        )

    finally:
        db.close()

    log("=" * 55)
    log("SCAN TERMINÉ")
    log(f"Actifs analysés : {len(SYMBOLS)}")
    log(f"Signaux envoyés : {total_sent}")
    log(f"Erreurs de données ou d'analyse : {total_errors}")
    log("Aucun ordre n'a été envoyé à Deriv.")
    log("=" * 55)


if __name__ == "__main__":
    main()
