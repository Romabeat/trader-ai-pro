"""
Trader AI Pro - Scanner automatique D1/H4
-----------------------------------------
D1 : 100 bougies pour le biais directionnel.
H4 : 200 bougies pour la structure et les Order Blocks.

Fonctions :
- Recuperation des bougies et du prix.
- Detection des signaux SMC.
- Enregistrement SQLite.
- Alertes Telegram.
- Suivi des zones H4.
- Invalidation des zones cassees.

SECURITE :
- Aucun ordre n'est execute.
- Le scanner genere uniquement des analyses et alertes.
"""

import os
import time
import sqlite3
import logging

from pathlib import Path
from datetime import datetime, timezone

import requests

from deriv_market import get_candles, get_current_price
from strategy import find_signals, format_message


# ============================================================
# CONFIGURATION
# ============================================================

D1_CANDLE_COUNT = 100
H4_CANDLE_COUNT = 200

REQUEST_TIMEOUT = 20
PAUSE_BETWEEN_SYMBOLS = 1

MIN_D1_CANDLES = 100
MIN_H4_CANDLES = 200

DB_PATH = Path(
    os.environ.get(
        "TRADER_DB_PATH",
        "state/trader_ai_pro.sqlite3",
    )
)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

VALID_STATES = {
    "POI_DETECTED",
    "PRICE_IN_ZONE",
    "CONFIRMED",
    "INVALIDATED",
}

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
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger("trader_ai_pro")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


# ============================================================
# SQLITE
# ============================================================

def connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    db = sqlite3.connect(
        str(DB_PATH),
        timeout=30,
    )

    db.row_factory = sqlite3.Row

    db.execute("PRAGMA busy_timeout = 30000")
    db.execute("PRAGMA journal_mode = WAL")

    return db


def init_db(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS signals (
            signal_id TEXT PRIMARY KEY,
            created_at TEXT,
            symbol TEXT,
            direction TEXT,
            entry REAL,
            stop_loss REAL,
            take_profit REAL,
            rr REAL,
            status TEXT,
            outcome TEXT,
            result_r REAL,
            notes TEXT,
            message TEXT
        );

        CREATE TABLE IF NOT EXISTS run_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT,
            symbol TEXT,
            status TEXT,
            details TEXT
        );

        CREATE TABLE IF NOT EXISTS poi_states (
            signal_id TEXT PRIMARY KEY,
            symbol TEXT,
            direction TEXT,
            zone_low REAL,
            zone_high REAL,
            entry REAL,
            stop_loss REAL,
            take_profit REAL,
            rr REAL,
            state TEXT,
            alerted_states TEXT,
            created_at TEXT,
            updated_at TEXT,
            invalid_reason TEXT
        );
        """
    )

    db.commit()


def log_run(db, symbol, status, details=""):
    db.execute(
        """
        INSERT INTO run_log (
            run_at, symbol, status, details
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            utc_now(),
            symbol,
            status,
            str(details)[:2000],
        ),
    )

    db.commit()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    """
    Envoie une alerte Telegram si les secrets sont configures.

    Aucun ordre de trading n'est envoye.
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(
            "Telegram non configure : alerte non envoyee."
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
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        payload = response.json()

        if not payload.get("ok"):
            logger.error(
                "Telegram a refuse le message : %s",
                payload,
            )
            return False

        return True

    except requests.RequestException as exc:
        logger.error("Erreur Telegram : %s", exc)
        return False


# ============================================================
# RECUPERATION DES DONNEES
# ============================================================

def fetch_candles(symbol, timeframe, required_count):
    """
    Recupere les bougies et refuse un historique insuffisant.

    Une bougie supplementaire est demandee afin de compenser
    une eventuelle bougie encore en formation. Le module
    deriv_market doit lui aussi gerer correctement les
    bougies fermees.

    Les bougies doivent etre fournies de la plus ancienne
    a la plus recente.
    """
    requested_count = required_count + 1

    try:
        candles = get_candles(
            symbol,
            timeframe,
            count=requested_count,
            timeout=REQUEST_TIMEOUT,
        )

    except Exception as exc:
        logger.warning(
            "%s %s : erreur de recuperation : %s",
            symbol,
            timeframe,
            exc,
        )
        return None

    if not isinstance(candles, (list, tuple)):
        logger.warning(
            "%s %s : format de bougies invalide.",
            symbol,
            timeframe,
        )
        return None

    if len(candles) < required_count:
        logger.warning(
            "%s %s : historique insuffisant (%s/%s).",
            symbol,
            timeframe,
            len(candles),
            required_count,
        )
        return None

    # On conserve les N bougies les plus recentes.
    result = list(candles[-required_count:])

    logger.info(
        "%s %s : %s bougies disponibles.",
        symbol,
        timeframe,
        len(result),
    )

    return result


def fetch_current_price(symbol):
    try:
        price = get_current_price(
            symbol,
            timeout=REQUEST_TIMEOUT,
        )

    except TypeError:
        # Compatibilite si la fonction n'accepte pas timeout.
        try:
            price = get_current_price(symbol)
        except Exception as exc:
            logger.warning(
                "%s : prix indisponible : %s",
                symbol,
                exc,
            )
            return None

    except Exception as exc:
        logger.warning(
            "%s : prix indisponible : %s",
            symbol,
            exc,
        )
        return None

    try:
        price = float(price)
    except (TypeError, ValueError):
        return None

    if price <= 0:
        return None

    return price


# ============================================================
# ENREGISTREMENT DES SIGNAUX
# ============================================================

def store_signal(db, signal, message):
    """
    Enregistre un nouveau signal sans creer de doublon.

    Retourne True si le signal a ete ajoute, False s'il
    existait deja.
    """
    cursor = db.execute(
        """
        INSERT OR IGNORE INTO signals (
            signal_id,
            created_at,
            symbol,
            direction,
            entry,
            stop_loss,
            take_profit,
            rr,
            status,
            outcome,
            result_r,
            notes,
            message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal["signal_id"],
            utc_now(),
            signal["symbol"],
            signal["direction"],
            signal["entry"],
            signal["stop_loss"],
            signal["take_profit"],
            signal["rr"],
            "POI_DETECTED",
            None,
            None,
            signal.get("notes", ""),
            message,
        ),
    )

    db.commit()

    return cursor.rowcount > 0


def save_poi(db, signal, state="POI_DETECTED"):
    """
    Enregistre l'etat d'une zone H4.

    Les nouveaux identifiants D1H4 permettent de distinguer
    ces zones des anciens signaux H4/H1.
    """
    if state not in VALID_STATES:
        raise ValueError(f"Etat POI invalide : {state}")

    db.execute(
        """
        INSERT OR IGNORE INTO poi_states (
            signal_id,
            symbol,
            direction,
            zone_low,
            zone_high,
            entry,
            stop_loss,
            take_profit,
            rr,
            state,
            alerted_states,
            created_at,
            updated_at,
            invalid_reason
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            state,
            utc_now(),
            utc_now(),
            None,
        ),
    )

    db.commit()


def alert_message(signal, state):
    """
    Produit un message adapte a la transition de la zone.
    """
    if state == "PRICE_IN_ZONE":
        return (
            "TRADER AI PRO — PRIX DANS LA ZONE H4\n\n"
            f"Instrument : {signal['symbol']}\n"
            f"Direction : {signal['direction']}\n"
            f"Zone OB : {signal['zone_low']} - "
            f"{signal['zone_high']}\n"
            f"Entree prevue : {signal['entry']}\n"
            f"Stop Loss : {signal['stop_loss']}\n"
            f"Take Profit : {signal['take_profit']}\n"
            f"RR initial : 1:{float(signal['rr']):.2f}\n\n"
            "Le prix se trouve dans la zone suivie. "
            "Verifie les conditions avant toute decision."
        )

    if state == "INVALIDATED":
        return (
            "TRADER AI PRO — ORDER BLOCK INVALIDE\n\n"
            f"Instrument : {signal['symbol']}\n"
            f"Direction : {signal['direction']}\n"
            f"Zone : {signal['zone_low']} - "
            f"{signal['zone_high']}\n"
            "La zone a ete invalidee par une cloture H4.\n"
            "Le signal ne doit plus etre utilise."
        )

    return format_message(signal)


# ============================================================
# TRANSITIONS DES ZONES
# ============================================================

def get_poi(db, signal_id):
    row = db.execute(
        """
        SELECT *
        FROM poi_states
        WHERE signal_id = ?
        """,
        (signal_id,),
    ).fetchone()

    return dict(row) if row else None


def transition_poi(db, signal, new_state, invalid_reason=None):
    """
    Met a jour l'etat d'une zone et evite les alertes
    de transition en double.
    """
    if new_state not in VALID_STATES:
        logger.warning(
            "Etat inconnu pour %s : %s",
            signal.get("signal_id"),
            new_state,
        )
        return

    current = get_poi(db, signal["signal_id"])

    if current is None:
        save_poi(db, signal, state=new_state)
        current = get_poi(db, signal["signal_id"])

    if current is None:
        return

    if current["state"] == "INVALIDATED":
        return

    alerted = set(
        filter(
            None,
            (current.get("alerted_states") or "").split(","),
        )
    )

    # Construire le message avant toute condition :
    # cela evite une variable non definie lors d'une
    # invalidation deja signalee.
    message = alert_message(signal, new_state)

    should_alert = new_state not in alerted

    db.execute(
        """
        UPDATE poi_states
        SET state = ?,
            updated_at = ?,
            alerted_states = ?,
            invalid_reason = ?
        WHERE signal_id = ?
        """,
        (
            new_state,
            utc_now(),
            ",".join(sorted(alerted | {new_state})),
            invalid_reason,
            signal["signal_id"],
        ),
    )

    db.execute(
        """
        UPDATE signals
        SET status = ?
        WHERE signal_id = ?
        """,
        (
            new_state,
            signal["signal_id"],
        ),
    )

    db.commit()

    if should_alert:
        send_telegram(message)


def invalidate_broken_zones(db, symbol, h4):
    """
    Invalide uniquement les nouvelles zones D1/H4.

    Les anciens POI H4/H1 ne sont pas touches par cette
    logique afin d'eviter de melanger les strategies.
    """
    if not h4:
        return

    last = h4[-1]

    try:
        close_price = float(
            last.get(
                "close",
                last.get("c"),
            )
        )
    except (TypeError, ValueError, AttributeError):
        return

    rows = db.execute(
        """
        SELECT *
        FROM poi_states
        WHERE symbol = ?
          AND signal_id LIKE '%-D1H4-POI-%'
          AND state != 'INVALIDATED'
        """,
        (symbol,),
    ).fetchall()

    for row in rows:
        poi = dict(row)

        direction = poi["direction"]

        broken = (
            direction == "BUY"
            and close_price < poi["zone_low"]
        ) or (
            direction == "SELL"
            and close_price > poi["zone_high"]
        )

        if not broken:
            continue

        signal = {
            "signal_id": poi["signal_id"],
            "symbol": poi["symbol"],
            "direction": poi["direction"],
            "zone_low": poi["zone_low"],
            "zone_high": poi["zone_high"],
            "entry": poi["entry"],
            "stop_loss": poi["stop_loss"],
            "take_profit": poi["take_profit"],
            "rr": poi["rr"],
        }

        transition_poi(
            db,
            signal,
            "INVALIDATED",
            invalid_reason=(
                f"Cloture H4 a {close_price} au-dela de la zone."
            ),
        )


# ============================================================
# SUIVI DES ZONES EXISTANTES
# ============================================================

def update_existing_pois(db, symbol, price):
    """
    Signale lorsque le prix entre dans une zone encore active.
    """
    if price is None:
        return

    rows = db.execute(
        """
        SELECT *
        FROM poi_states
        WHERE symbol = ?
          AND signal_id LIKE '%-D1H4-POI-%'
          AND state = 'POI_DETECTED'
        """,
        (symbol,),
    ).fetchall()

    for row in rows:
        poi = dict(row)

        if poi["zone_low"] <= price <= poi["zone_high"]:
            transition_poi(
                db,
                poi,
                "PRICE_IN_ZONE",
            )


# ============================================================
# ANALYSE D'UN INSTRUMENT
# ============================================================

def analyze_symbol(db, symbol):
    logger.info("=" * 55)
    logger.info("Analyse de %s", symbol)

    try:
        # 1. Historique Daily : 100 bougies.
        d1 = fetch_candles(
            symbol,
            "D1",
            D1_CANDLE_COUNT,
        )

        if d1 is None or len(d1) < MIN_D1_CANDLES:
            log_run(
                db,
                symbol,
                "SKIPPED",
                "Historique Daily insuffisant.",
            )
            return

        # 2. Historique H4 : 200 bougies.
        h4 = fetch_candles(
            symbol,
            "H4",
            H4_CANDLE_COUNT,
        )

        if h4 is None or len(h4) < MIN_H4_CANDLES:
            log_run(
                db,
                symbol,
                "SKIPPED",
                "Historique H4 insuffisant.",
            )
            return

        # 3. Invalidation des anciennes zones H4 de la
        # strategie D1/H4 uniquement.
        invalidate_broken_zones(
            db,
            symbol,
            h4,
        )

        # 4. Recuperation du prix actuel.
        price = fetch_current_price(symbol)

        if price is None:
            log_run(
                db,
                symbol,
                "SKIPPED",
                "Prix actuel indisponible.",
            )
            return

        # 5. Mise a jour des POI existants.
        update_existing_pois(
            db,
            symbol,
            price,
        )

        # 6. Analyse de la strategie.
        diagnostics = []

        signals = find_signals(
            symbol=symbol,
            d1=d1,
            h4=h4,
            price_now=price,
            diagnostics=diagnostics,
        )

        if not signals:
            details = (
                "; ".join(diagnostics)
                if diagnostics
                else "Aucun signal valide."
            )

            logger.info(
                "%s : aucun signal. %s",
                symbol,
                details,
            )

            log_run(
                db,
                symbol,
                "NO_SIGNAL",
                details,
            )

            return

        # 7. Enregistrement et alerte.
        for signal in signals:
            message = format_message(signal)

            inserted = store_signal(
                db,
                signal,
                message,
            )

            if not inserted:
                logger.info(
                    "%s : signal deja enregistre (%s).",
                    symbol,
                    signal["signal_id"],
                )
                continue

            save_poi(
                db,
                signal,
                state="POI_DETECTED",
            )

            logger.info(
                "%s : signal %s, RR=%.2f",
                symbol,
                signal["direction"],
                float(signal["rr"]),
            )

            # L'alerte Telegram est conservee.
            send_telegram(message)

        log_run(
            db,
            symbol,
            "SUCCESS",
            f"{len(signals)} signal(s) valide(s).",
        )

    except Exception as exc:
        logger.exception(
            "Erreur pendant l'analyse de %s",
            symbol,
        )

        log_run(
            db,
            symbol,
            "ERROR",
            str(exc),
        )


# ============================================================
# PROGRAMME PRINCIPAL
# ============================================================

def main():
    logger.info("=" * 60)
    logger.info("TRADER AI PRO — SCANNER D1/H4")
    logger.info("D1 : %s bougies", D1_CANDLE_COUNT)
    logger.info("H4 : %s bougies", H4_CANDLE_COUNT)
    logger.info("RR minimum : 1:1.5")
    logger.info("DRY_RUN : %s", DRY_RUN)
    logger.info("Execution automatique des ordres : DESACTIVEE")
    logger.info("Telegram configure : %s", bool(
        TELEGRAM_TOKEN and TELEGRAM_CHAT_ID
    ))
    logger.info("=" * 60)

    db = connect_db()

    try:
        init_db(db)

        for symbol in SYMBOLS:
            analyze_symbol(
                db,
                symbol,
            )

            time.sleep(PAUSE_BETWEEN_SYMBOLS)

    finally:
        db.close()

    logger.info("Analyse terminee.")


if __name__ == "__main__":
    main()
