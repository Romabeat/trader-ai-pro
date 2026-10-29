"""Scanner programmé Trader AI Pro : Telegram réel, journal SQLite, aucune exécution d'ordres."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import requests
from deriv_market import get_candles
from strategy import find_signals, format_message

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
ENABLE_TELEGRAM_ALERTS = os.environ.get("ENABLE_TELEGRAM_ALERTS", "false").strip().lower() == "true"
# DRY_RUN concerne uniquement l'exécution d'ordres : aucune fonction d'ordre n'existe dans ce projet.
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() != "false"
DATABASE_PATH = Path(os.environ.get("TRADER_DB_PATH", "state/trader_ai_pro.sqlite3"))
SYMBOLS = ["1HZ10V", "1HZ15V", "1HZ25V", "1HZ30V", "1HZ50V", "1HZ75V", "1HZ90V",
           "1HZ100V", "R_10", "R_25", "R_50", "R_75", "R_100"]
TIMEFRAMES = ("H4", "H1")
CANDLE_COUNT = 100
REQUEST_TIMEOUT = 15
PAUSE_BETWEEN_SYMBOLS = 1


def log(message: str) -> None:
    print(f"[TRADER AI PRO] {message}", flush=True)


def connect_db() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATABASE_PATH, timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(""" CREATE TABLE IF NOT EXISTS signals ( signal_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL, entry REAL NOT NULL, stop_loss REAL NOT NULL, take_profit REAL NOT NULL, rr REAL NOT NULL, status TEXT NOT NULL DEFAULT 'ENVOYE', outcome TEXT, result_r REAL, notes TEXT, message TEXT ) """)
    db.execute(""" CREATE TABLE IF NOT EXISTS run_log ( id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, event TEXT NOT NULL, detail TEXT ) """)
    db.commit()
    return db


def send_telegram(message: str) -> bool:
    if not ENABLE_TELEGRAM_ALERTS:
        log("Telegram désactivé (ENABLE_TELEGRAM_ALERTS n'est pas true).")
        return False
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("ERREUR: secrets TELEGRAM_TOKEN / TELEGRAM_CHAT_ID manquants.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "disable_web_page_preview": True},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("ok"):
            log(f"Erreur Telegram API: {payload.get('description', 'réponse non valide')}")
            return False
        return True
    except (requests.RequestException, ValueError) as exc:
        log(f"Erreur d'envoi Telegram: {exc}")
        return False


def fetch_candles(symbol: str, timeframe: str) -> list[dict] | None:
    try:
        rows = get_candles(symbol, timeframe, count=CANDLE_COUNT, timeout=REQUEST_TIMEOUT)
        if not isinstance(rows, list) or len(rows) < 30:
            log(f"{symbol} {timeframe}: données insuffisantes.")
            return None
        return rows
    except Exception as exc:
        log(f"{symbol} {timeframe}: erreur données: {exc}")
        return None


def already_recorded(db: sqlite3.Connection, signal_id: str) -> bool:
    return db.execute("SELECT 1 FROM signals WHERE signal_id = ?", (signal_id,)).fetchone() is not None


def store_signal(db: sqlite3.Connection, signal: dict, message: str) -> None:
    db.execute(
        """INSERT INTO signals (signal_id, created_at, symbol, direction, entry, stop_loss, take_profit, rr, status, message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ENVOYE', ?)""",
        (signal["signal_id"], signal["timestamp_utc"], signal["symbol"], signal["direction"],
         signal["entry"], signal["stop_loss"], signal["take_profit"], signal["rr"], message),
    )
    db.execute("INSERT INTO run_log(event, detail) VALUES (?, ?)",
               ("SIGNAL_SENT", json.dumps({"signal_id": signal["signal_id"], "symbol": signal["symbol"]})))
    db.commit()


def analyze_symbol(db: sqlite3.Connection, symbol: str) -> tuple[int, int]:
    h4 = fetch_candles(symbol, "H4")
    h1 = fetch_candles(symbol, "H1")
    if h4 is None or h1 is None:
        return 0, 1
    signals = find_signals(symbol=symbol, h4=h4, h1=h1)
    if not signals:
        log(f"{symbol}: aucun signal SMC confirmé.")
        return 0, 0
    sent = 0
    for signal in signals:
        if already_recorded(db, signal["signal_id"]):
            log(f"{symbol}: doublon ignoré ({signal['signal_id']}).")
            continue
        message = format_message(signal)
        if send_telegram(message):
            try:
                store_signal(db, signal, message)
                sent += 1
                log(f"{symbol}: signal envoyé et journalisé ({signal['signal_id']}).")
            except sqlite3.IntegrityError:
                log(f"{symbol}: doublon empêché par la base de données.")
        else:
            log(f"{symbol}: signal non journalisé car Telegram n'a pas confirmé l'envoi.")
    return sent, 0


def main() -> None:
    log("Démarrage du scan SMC H4/H1.")
    log(f"Alertes Telegram activées: {ENABLE_TELEGRAM_ALERTS}; exécution automatique des ordres: DÉSACTIVÉE.")
    if not DRY_RUN:
        log("AVERTISSEMENT: DRY_RUN=false détecté, mais ce programme ne contient aucune fonction d'exécution d'ordres.")
    db = connect_db()
    total_sent = errors = 0
    try:
        for index, symbol in enumerate(SYMBOLS):
            sent, err = analyze_symbol(db, symbol)
            total_sent += sent
            errors += err
            if index < len(SYMBOLS) - 1:
                time.sleep(PAUSE_BETWEEN_SYMBOLS)
        db.execute("INSERT INTO run_log(event, detail) VALUES (?, ?)",
                   ("SCAN_FINISHED", json.dumps({"sent": total_sent, "errors": errors})))
        db.commit()
    finally:
        db.close()
    log(f"Fin du scan. Signaux envoyés: {total_sent}; erreurs de données: {errors}.")
    log("Aucun ordre n'a été envoyé à Deriv.")


if __name__ == "__main__":
    main()
