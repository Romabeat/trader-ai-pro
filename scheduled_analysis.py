"""TRADER AI PRO — Scanner SMC H4/H1 avec alertes Telegram.

Détecte les POI, suit leurs états et conserve un journal SQLite.
Aucun ordre n'est envoyé à Deriv.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from deriv_market import get_candles, get_current_price
from strategy import find_signals, format_message


DB_PATH = Path(
    os.environ.get("TRADER_DB_PATH", "state/trader_ai_pro.sqlite3")
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

ENABLE_TELEGRAM_ALERTS = (
    os.environ.get("ENABLE_TELEGRAM_ALERTS", "false").lower()
    in ("1", "true", "yes", "oui")
)

DRY_RUN = (
    os.environ.get("DRY_RUN", "true").lower()
    in ("1", "true", "yes", "oui")
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

VALID_STATES = {
    "POI_DETECTED",
    "PRICE_IN_ZONE",
    "CONFIRMED",
    "INVALIDATED",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(message: str) -> None:
    print(f"[TRADER AI PRO] {utc_now()} {message}", flush=True)


def initialize_database(db: sqlite3.Connection) -> None:
    """Crée les tables et ajoute les structures nécessaires au suivi des POI."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            signal_id TEXT PRIMARY KEY,
            created_at TEXT,
            symbol TEXT,
            direction TEXT,
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
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            event TEXT,
            detail TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS poi_states (
            signal_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            zone_low REAL NOT NULL,
            zone_high REAL NOT NULL,
            entry REAL NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL,
            rr REAL NOT NULL,
            state TEXT NOT NULL,
            alerted_states TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            invalid_reason TEXT DEFAULT ''
        )
    """)

    # Compatibilité avec une ancienne base de données.
    existing_columns = {
        row[1]
        for row in db.execute("PRAGMA table_info(signals)").fetchall()
    }

    required_columns = {
        "outcome": "TEXT",
        "result_r": "REAL",
        "notes": "TEXT",
        "message": "TEXT",
        "status": "TEXT DEFAULT 'ENVOYE'",
    }

    for name, sql_type in required_columns.items():
        if name not in existing_columns:
            db.execute(
                f"ALTER TABLE signals ADD COLUMN {name} {sql_type}"
            )

    db.commit()


def record_event(
    db: sqlite3.Connection,
    event: str,
    detail: str,
) -> None:
    db.execute(
        "INSERT INTO run_log(event, detail) VALUES (?, ?)",
        (event, detail),
    )


def fetch_candles(symbol: str, timeframe: str) -> list[dict] | None:
    """Récupère les bougies et rejette les réponses insuffisantes."""
    try:
        result = get_candles(
            symbol,
            timeframe,
            count=CANDLE_COUNT,
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as exc:
        log(f"{symbol} {timeframe}: erreur API: {exc}")
        return None

    if not isinstance(result, dict) or result.get("error"):
        error = result.get("error", "Réponse invalide") if isinstance(
            result, dict
        ) else "Réponse invalide"

        log(f"{symbol} {timeframe}: {error}")
        return None

    candles = result.get("candles")

    if not isinstance(candles, list) or len(candles) < 30:
        log(f"{symbol} {timeframe}: données insuffisantes")
        return None

    return candles


def fetch_current_price(symbol: str) -> float | None:
    """Récupère le dernier prix coté, sans placer d'ordre."""
    try:
        price = get_current_price(symbol, timeout=REQUEST_TIMEOUT)

        if price is None:
            log(f"{symbol}: prix courant indisponible")
            return None

        return float(price)

    except Exception as exc:
        log(f"{symbol}: impossible de récupérer le prix courant: {exc}")
        return None


def send_telegram(message: str) -> bool:
    """Envoie un message Telegram. Retourne True uniquement en cas de succès."""
    if not ENABLE_TELEGRAM_ALERTS:
        log("Telegram désactivé par ENABLE_TELEGRAM_ALERTS.")
        return False

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram indisponible : secrets manquants.")
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
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            log(
                "Échec Telegram HTTP "
                f"{response.status_code}: {response.text[:300]}"
            )
            return False

        data = response.json()

        if not data.get("ok"):
            log(f"Telegram a refusé le message: {data}")
            return False

        log("Alerte Telegram envoyée.")
        return True

    except Exception as exc:
        log(f"Erreur d'envoi Telegram: {exc}")
        return False


def store_signal(
    db: sqlite3.Connection,
    signal: dict,
    message: str,
) -> None:
    """Enregistre ou actualise les informations d'un signal."""
    db.execute(
        """
        INSERT INTO signals (
            signal_id, created_at, symbol, direction,
            entry, stop_loss, take_profit, rr, status, message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(signal_id) DO UPDATE SET
            entry = excluded.entry,
            stop_loss = excluded.stop_loss,
            take_profit = excluded.take_profit,
            rr = excluded.rr,
            status = excluded.status,
            message = excluded.message
        """,
        (
            signal["signal_id"],
            signal.get("timestamp_utc", utc_now()),
            signal["symbol"],
            signal["direction"],
            signal["entry"],
            signal["stop_loss"],
            signal["take_profit"],
            signal["rr"],
            signal.get("status", "POI_DETECTED"),
            message,
        ),
    )


def get_poi(
    db: sqlite3.Connection,
    signal_id: str,
) -> dict | None:
    db.row_factory = sqlite3.Row

    row = db.execute(
        "SELECT * FROM poi_states WHERE signal_id = ?",
        (signal_id,),
    ).fetchone()

    return dict(row) if row else None


def save_poi(
    db: sqlite3.Connection,
    signal: dict,
    state: str,
    alerted_states: list[str],
    invalid_reason: str = "",
) -> None:
    """Sauvegarde l'état actuel d'une POI."""
    now = utc_now()

    db.execute(
        """
        INSERT INTO poi_states (
            signal_id, symbol, direction,
            zone_low, zone_high, entry,
            stop_loss, take_profit, rr,
            state, alerted_states,
            created_at, updated_at, invalid_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(signal_id) DO UPDATE SET
            state = excluded.state,
            alerted_states = excluded.alerted_states,
            updated_at = excluded.updated_at,
            invalid_reason = excluded.invalid_reason
        """,
        (
            signal["signal_id"],
            signal["symbol"],
            signal["direction"],
            signal["zone_low"],
            signal["zone_high"],
            signal["entry"],
            signal["stop_loss"],
            signal["take_profit"],
            signal["rr"],
            state,
            json.dumps(sorted(set(alerted_states))),
            now,
            now,
            invalid_reason,
        ),
    )

    db.commit()


def alert_message(signal: dict, state: str) -> str:
    """Construit un message spécifique à chaque transition d'état."""
    updated = dict(signal)
    updated["status"] = state

    if state == "INVALIDATED":
        reason = updated.get(
            "invalid_reason",
            "Les conditions de validité de la zone ne sont plus réunies.",
        )

        return (
            "⛔ TRADER AI PRO — POI INVALIDÉE\n\n"
            f"Actif : {updated['symbol']}\n"
            f"Direction : {updated['direction']}\n"
            f"ID : {updated['signal_id']}\n"
            f"Zone : {updated['zone_low']:.8f} – "
            f"{updated['zone_high']:.8f}\n"
            f"Motif : {reason}\n\n"
            "Ne traite plus cette zone comme un setup valide. "
            "Aucun ordre automatique n'a été envoyé."
        )

    if state == "PRICE_IN_ZONE":
        heading = "🎯 LE PRIX ENTRE DANS LA POI"
        explanation = (
            "Le prix observé se trouve dans la zone. "
            "Vérifie le graphique avant toute décision."
        )
    elif state == "CONFIRMED":
        heading = "✅ CONFLUENCE TECHNIQUE DÉTECTÉE"
        explanation = (
            "Une confluence de confirmation est détectée. "
            "Elle ne garantit pas le succès du setup."
        )
    else:
        heading = "🔎 NOUVELLE POI SMC DÉTECTÉE"
        explanation = (
            "La zone est identifiée avant un éventuel retour du prix. "
            "L'entrée reste planifiée, pas exécutée."
        )

    return (
        f"{heading}\n\n"
        f"Actif : {updated['symbol']}\n"
        f"ID : {updated['signal_id']}\n"
        f"Direction : {updated['direction']}\n"
        f"Structure H4 : {updated['h4_structure']}\n"
        f"Zone H1 : {updated['zone_low']:.8f} – "
        f"{updated['zone_high']:.8f}\n"
        f"Entrée planifiée : {updated['entry']:.8f}\n"
        f"Stop-loss indicatif : {updated['stop_loss']:.8f}\n"
        f"Take-profit indicatif : {updated['take_profit']:.8f}\n"
        f"RR planifié : 1:{updated['rr']:.2f}\n"
        f"Prix observé : {updated.get('price_now', 0):.8f}\n\n"
        f"{explanation}\n\n"
        "Exécution manuelle uniquement sur compte démo. "
        "Aucun ordre automatique."
    )


def transition_poi(
    db: sqlite3.Connection,
    signal: dict,
    new_state: str,
) -> None:
    """Enregistre une transition et envoie au plus une alerte par état."""
    if new_state not in VALID_STATES:
        log(f"État inconnu ignoré : {new_state}")
        return

    signal_id = signal["signal_id"]
    existing = get_poi(db, signal_id)

    if existing:
        try:
            alerted = json.loads(existing["alerted_states"] or "[]")
        except (ValueError, TypeError):
            alerted = []

        old_state = existing["state"]
    else:
        alerted = []
        old_state = None

    # Une POI nouvelle est toujours annoncée comme détectée en premier.
    if existing is None:
        first_message = alert_message(signal, "POI_DETECTED")

        if send_telegram(first_message):
            alerted.append("POI_DETECTED")

        store_signal(db, signal, first_message)
        save_poi(
            db,
            signal,
            "POI_DETECTED",
            alerted,
        )

        record_event(
            db,
            "POI_DETECTED",
            f"{signal_id} | RR={signal['rr']:.2f}",
        )

        db.commit()
        old_state = "POI_DETECTED"

    if new_state == "INVALIDATED":
        if "INVALIDATED" not in alerted:
            message = alert_message(signal, "INVALIDATED")

            if send_telegram(message):
                alerted.append("INVALIDATED")

        store_signal(db, {**signal, "status": "INVALIDATED"}, message)
        save_poi(
            db,
            signal,
            "INVALIDATED",
            alerted,
            signal.get("invalid_reason", ""),
        )

        record_event(db, "POI_INVALIDATED", signal_id)
        db.commit()
        return

    if new_state == "POI_DETECTED":
        return

    # Ne pas renvoyer une alerte si cet état a déjà été notifié.
    if new_state not in alerted:
        message = alert_message(signal, new_state)

        if send_telegram(message):
            alerted.append(new_state)

        store_signal(db, {**signal, "status": new_state}, message)

        record_event(
            db,
            "POI_STATE_CHANGED",
            f"{signal_id} | {old_state} -> {new_state}",
        )

    save_poi(
        db,
        signal,
        new_state,
        alerted,
    )

    db.commit()


def invalidate_broken_zones(
    db: sqlite3.Connection,
    symbol: str,
    h1: list[dict],
) -> None:
    """Invalide les zones existantes si une clôture H1 les traverse."""
    if not h1:
        return

    last_close = float(h1[-1]["close"])

    rows = db.execute(
        """
        SELECT * FROM poi_states
        WHERE symbol = ?
          AND state != 'INVALIDATED'
        """,
        (symbol,),
    ).fetchall()

    for row in rows:
        signal = dict(row)

        if signal["direction"] == "BUY":
            broken = last_close < signal["zone_low"]
        else:
            broken = last_close > signal["zone_high"]

        if not broken:
            continue

        signal["invalid_reason"] = (
            f"Clôture H1 à {last_close:.8f} au-delà de la zone."
        )

        transition_poi(db, signal, "INVALIDATED")

        log(
            f"{symbol}: zone invalidée après clôture H1. "
            f"ID={signal['signal_id']}"
        )


def analyze_symbol(db: sqlite3.Connection, symbol: str) -> int:
    """Analyse un actif et suit les changements d'état de sa POI."""
    log(f"Analyse de {symbol}")

    h4 = fetch_candles(symbol, "H4")
    h1 = fetch_candles(symbol, "H1")

    if h4 is None or h1 is None:
        record_event(db, "DATA_ERROR", symbol)
        db.commit()
        return 0

    # Vérifier les zones déjà suivies, même si la stratégie ne les
    # retourne plus comme candidates.
    invalidate_broken_zones(db, symbol, h1)

    price = fetch_current_price(symbol)

    if price is None:
        # La stratégie peut encore identifier une POI à partir des bougies,
        # mais le dernier close ne doit pas être présenté comme un tick.
        log(
            f"{symbol}: analyse POI maintenue, "
            "suivi d'entrée limité par l'absence de prix courant."
        )

    diagnostics = {}

    try:
        signals = find_signals(
            symbol=symbol,
            h4=h4,
            h1=h1,
            price_now=price,
            diagnostics=diagnostics,
        )
    except Exception as exc:
        log(f"{symbol}: erreur stratégie: {exc}")
        record_event(db, "STRATEGY_ERROR", f"{symbol}: {exc}")
        db.commit()
        return 0

    if not signals:
        log(
            f"{symbol}: aucun nouveau setup. "
            f"Diagnostic : {diagnostics.get('reason', 'non disponible')}"
        )
        record_event(
            db,
            "NO_SIGNAL",
            f"{symbol} | {diagnostics.get('reason', '')}",
        )
        db.commit()
        return 0

    processed = 0

    for signal in signals:
        signal["symbol"] = symbol

        # Si le prix courant est indisponible, on ne prétend pas connaître
        # l'état d'entrée à partir d'une cotation instantanée.
        if price is None:
            new_state = "POI_DETECTED"
        elif signal["zone_low"] <= price <= signal["zone_high"]:
            new_state = (
                "CONFIRMED"
                if signal.get("engulfing") or signal.get("liquidity_sweep")
                else "PRICE_IN_ZONE"
            )
        else:
            new_state = "POI_DETECTED"

        transition_poi(db, signal, new_state)
        processed += 1

    return processed


def main() -> None:
    """Point d'entrée de l'analyse programmée."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    log("=" * 55)
    log("DÉMARRAGE DE TRADER AI PRO")
    log(f"Mode DRY_RUN : {DRY_RUN}")
    log(f"Alertes Telegram activées : {ENABLE_TELEGRAM_ALERTS}")
    log(f"Secrets Telegram présents : {bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)}")
    log("Ordres automatiques : désactivés")

    if not DRY_RUN:
        log(
            "ATTENTION : DRY_RUN est désactivé, mais ce programme "
            "ne contient aucune fonction d'envoi d'ordre."
        )

    total = 0
    failures = 0

    with sqlite3.connect(DB_PATH, timeout=30) as db:
        initialize_database(db)

        for symbol in SYMBOLS:
            try:
                total += analyze_symbol(db, symbol)
            except Exception as exc:
                failures += 1
                log(f"Erreur inattendue pour {symbol}: {exc}")
                record_event(db, "UNEXPECTED_ERROR", f"{symbol}: {exc}")
                db.commit()

            time.sleep(PAUSE_BETWEEN_SYMBOLS)

        record_event(
            db,
            "RUN_FINISHED",
            f"POI traitées={total}; erreurs={failures}",
        )
        db.commit()

    log(
        f"FIN DE L'ANALYSE : POI traitées={total}, "
        f"erreurs={failures}"
    )
    log("Aucun ordre envoyé à Deriv.")


if __name__ == "__main__":
    main()
