"""
TRADER AI PRO — Scanner multi-marchés Deriv
Analyse D1/H4/H2/H1, 200 bougies par unité de temps.
Alertes uniquement : aucun ordre n'est exécuté automatiquement.

Les codes des marchés sont découverts depuis active_symbols afin d'éviter
de supposer des symboles Deriv qui pourraient ne pas être disponibles.
"""

import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

APP_NAME = "TRADER AI PRO"
MIN_CANDLES = 200
MIN_RISK_REWARD = 2.0
REQUEST_DELAY = 0.25
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() == "true"
ENABLE_TELEGRAM_ALERTS = (
    os.getenv("ENABLE_TELEGRAM_ALERTS", "true").strip().lower() == "true"
)
# Sécurité imposée : le scanner n'exécute jamais d'ordre.
ENABLE_AUTO_TRADING = False

TIMEFRAMES = {"D1": 86400, "H4": 14400, "H2": 7200, "H1": 3600}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_API_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    if TELEGRAM_BOT_TOKEN else ""
)

# Les actifs synthétiques restent connus, mais ne sont pas scannés pendant
# cette expérience d'une semaine.
SYNTHETIC_SYMBOLS_DISABLED = (
    "1HZ10V", "1HZ15V", "1HZ25V", "1HZ30V", "1HZ50V",
    "1HZ75V", "1HZ90V", "1HZ100V", "R_10", "R_25",
    "R_50", "R_75", "R_100",
)

# Nom logique -> noms d'affichage/codes possibles. Le code final est résolu
# à l'exécution à partir de la réponse officielle active_symbols de Deriv.
ASSET_ALIASES = {
    "XAUUSD": {
        "label": "Gold (XAU/USD)",
        "aliases": {"XAUUSD", "GOLDUSD", "GOLD"},
    },
    "NAS100": {
        "label": "Nasdaq 100 (US Tech 100)",
        "aliases": {"NAS100", "NASDAQ100", "USTECH100", "US100"},
    },
    "US30": {
        "label": "Dow Jones 30 (Wall Street 30)",
        "aliases": {"US30", "DOWJONES30", "WALLSTREET30", "WS30"},
    },
    "GBPUSD": {
        "label": "GBP/USD",
        "aliases": {"GBPUSD"},
    },
    "USDJPY": {
        "label": "USD/JPY",
        "aliases": {"USDJPY"},
    },
    "EURGBP": {
        "label": "EUR/GBP",
        "aliases": {"EURGBP"},
    },
    "AUDUSD": {
        "label": "AUD/USD",
        "aliases": {"AUDUSD"},
    },
    "BTCUSD": {
        "label": "Bitcoin (BTC/USD)",
        "aliases": {"BTCUSD", "BITCOINUSD", "BITCOIN", "BTC"},
    },
    "EURUSD": {
        "label": "EUR/USD",
        "aliases": {"EURUSD"},
    },
}

SYMBOLS: List[str] = []
SYMBOL_LABELS: Dict[str, str] = {}
SYMBOL_LOGICAL_NAMES: Dict[str, str] = {}

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
LOGGER = logging.getLogger("TRADER_AI_PRO.SCANNER")


def log(message: str, level: str = "info") -> None:
    getattr(LOGGER, level if level in {"info", "warning", "error"} else "info")(
        str(message)
    )


def is_positive_number(value: Any) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number) and number > 0


def normalize_name(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _get_active_symbol_rows() -> List[dict]:
    """Récupère les symboles actifs depuis l'API publique Deriv."""
    try:
        # Préférer le transport déjà centralisé dans deriv_market.
        from deriv_market import _execute_request
        response = _execute_request({"active_symbols": "brief"})
    except Exception as first_exc:
        # Compatibilité si une version de deriv_market ne publie pas
        # _execute_request : utiliser le WebSocket public documenté par Deriv.
        connection = None
        try:
            import json
            import websocket
            from deriv_market import PUBLIC_WEBSOCKET_URL
            connection = websocket.create_connection(
                PUBLIC_WEBSOCKET_URL, timeout=20
            )
            connection.send(json.dumps({"active_symbols": "brief", "req_id": 1}))
            response = json.loads(connection.recv())
        except Exception as exc:
            raise RuntimeError(
                "Impossible de récupérer active_symbols depuis Deriv. "
                f"Transport principal : {first_exc}; secours : {exc}"
            ) from exc
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    rows = response.get("active_symbols") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("Réponse active_symbols invalide ou vide.")
    return [row for row in rows if isinstance(row, dict)]


def resolve_active_symbols(rows: List[dict]) -> Dict[str, str]:
    """
    Résout les neuf actifs souhaités à partir du code et du nom Deriv.
    Aucun code n'est inventé : un actif non trouvé est signalé.
    """
    resolved: Dict[str, str] = {}

    for logical_name, config in ASSET_ALIASES.items():
        aliases = set(config["aliases"])
        matches = []

        for row in rows:
            code = row.get("symbol") or row.get("underlying_symbol")
            display_name = (
                row.get("display_name")
                or row.get("underlying_symbol_name")
                or ""
            )
            if not isinstance(code, str) or not code.strip():
                continue

            normalized_code = normalize_name(code)
            normalized_name = normalize_name(display_name)

            if normalized_code in aliases or normalized_name in aliases:
                matches.append((code.strip(), display_name))

        # Si plusieurs correspondances existent, choisir uniquement une
        # correspondance exacte sur le code ou le nom; sinon signaler l'ambiguïté.
        unique_codes = sorted({item[0] for item in matches})
        if len(unique_codes) == 1:
            resolved[logical_name] = unique_codes[0]
        elif len(unique_codes) > 1:
            exact_code = [
                code for code, _ in matches
                if normalize_name(code) in aliases
            ]
            exact_code = sorted(set(exact_code))
            if len(exact_code) == 1:
                resolved[logical_name] = exact_code[0]
            else:
                log(
                    f"{config['label']} : correspondance ambiguë "
                    f"({', '.join(unique_codes)}), actif ignoré.",
                    "warning",
                )
        else:
            log(
                f"{config['label']} : introuvable dans active_symbols; "
                "actif ignoré.",
                "warning",
            )

    return resolved


def configure_symbols() -> bool:
    """Découvre les symboles, construit la liste active et actualise les noms."""
    global SYMBOLS, SYMBOL_LABELS, SYMBOL_LOGICAL_NAMES

    rows = _get_active_symbol_rows()
    resolved = resolve_active_symbols(rows)

    SYMBOLS = list(resolved.values())
    SYMBOL_LABELS = {
        code: ASSET_ALIASES[logical]["label"]
        for logical, code in resolved.items()
    }
    SYMBOL_LOGICAL_NAMES = {code: logical for logical, code in resolved.items()}

    # La stratégie historique peut vérifier les symboles via SYMBOL_NAMES.
    # Ajouter les codes découverts lui permet d'accepter les marchés résolus.
    try:
        import strategy
        symbol_names = getattr(strategy, "SYMBOL_NAMES", None)
        if isinstance(symbol_names, dict):
            for code, label in SYMBOL_LABELS.items():
                symbol_names[code] = label
    except Exception as exc:
        log(f"Impossible d'actualiser les noms de stratégie : {exc}", "warning")

    for logical_name, config in ASSET_ALIASES.items():
        if logical_name not in resolved:
            log(f"Marché non disponible pour ce test : {config['label']}", "warning")

    log(f"Marchés demandés : {len(ASSET_ALIASES)}")
    log(f"Marchés résolus : {len(SYMBOLS)}")
    for code in SYMBOLS:
        log(f"Marché actif : {SYMBOL_LABELS[code]} — code Deriv : {code}")

    return bool(SYMBOLS)


try:
    from deriv_market import get_candles, get_current_price
    DERIV_MODULE_READY = True
except Exception as exc:
    DERIV_MODULE_READY = False
    log(f"Module Deriv indisponible : {exc}", "error")

try:
    from strategy import analyze_symbol_completely, format_message
    STRATEGY_MODULE_READY = True
except Exception as exc:
    STRATEGY_MODULE_READY = False
    log(f"Module stratégie indisponible : {exc}", "error")


def print_startup_information() -> None:
    log("=" * 68)
    log("TRADER AI PRO — SCANNER MULTI-MARCHÉS D1/H4/H2/H1")
    log(f"Bougies par timeframe : {MIN_CANDLES}")
    log(f"Timeframes : {', '.join(TIMEFRAMES.keys())}")
    log(f"Ratio risque/rendement minimum : 1:{MIN_RISK_REWARD:.1f}")
    log(f"DRY_RUN : {DRY_RUN}")
    log(f"Alertes Telegram activées : {ENABLE_TELEGRAM_ALERTS}")
    log("Exécution automatique des ordres : DÉSACTIVÉE")
    log("Exécution des transactions : manuelle uniquement")
    log("=" * 68)


def telegram_is_ready() -> bool:
    return (
        ENABLE_TELEGRAM_ALERTS
        and bool(TELEGRAM_BOT_TOKEN)
        and bool(TELEGRAM_CHAT_ID)
    )


def send_telegram_message(message: str) -> bool:
    if not ENABLE_TELEGRAM_ALERTS:
        log("Alertes Telegram désactivées.")
        return False
    if not telegram_is_ready():
        log("Telegram non configuré : alerte non envoyée.", "warning")
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
            log(f"Erreur Telegram HTTP {response.status_code}.", "error")
            return False
        payload = response.json()
        if not payload.get("ok", False):
            log(f"Telegram a refusé le message : {payload}", "error")
            return False
        log("Alerte Telegram envoyée.")
        return True
    except Exception as exc:
        log(f"Échec de l'envoi Telegram : {exc}", "error")
        return False


def fetch_timeframe_candles(symbol: str, timeframe: str) -> List[dict]:
    if timeframe not in TIMEFRAMES:
        log(f"{symbol} : timeframe inconnu {timeframe}.", "error")
        return []
    try:
        candles = get_candles(symbol, TIMEFRAMES[timeframe], count=MIN_CANDLES)
    except Exception as exc:
        log(f"{symbol} : erreur bougies {timeframe} : {exc}", "warning")
        return []
    if not isinstance(candles, list):
        log(f"{symbol} : format de bougies invalide pour {timeframe}.", "warning")
        return []
    if len(candles) < MIN_CANDLES:
        log(
            f"{symbol} : seulement {len(candles)}/{MIN_CANDLES} bougies "
            f"en {timeframe}; analyse abandonnée.",
            "warning",
        )
        return []
    return candles


def fetch_market_data(symbol: str) -> Optional[dict]:
    if symbol not in SYMBOLS:
        log(f"Symbole non autorisé : {symbol}", "error")
        return None

    label = SYMBOL_LABELS.get(symbol, symbol)
    market_data: Dict[str, Any] = {"symbol": symbol, "label": label}

    log("-" * 68)
    log(f"Analyse de {label} ({symbol})")

    for timeframe in ("D1", "H4", "H2", "H1"):
        candles = fetch_timeframe_candles(symbol, timeframe)
        if len(candles) < MIN_CANDLES:
            return None
        market_data[timeframe] = candles
        time.sleep(REQUEST_DELAY)

    try:
        price = get_current_price(symbol)
    except Exception as exc:
        log(f"{symbol} : prix actuel indisponible : {exc}", "warning")
        return None

    if not is_positive_number(price):
        log(f"{symbol} : prix actuel invalide.", "warning")
        return None

    market_data["current_price"] = float(price)
    return market_data


def validate_signal(signal: dict) -> bool:
    """Valide les niveaux et recalcule le RR réel avant tout envoi."""
    if not isinstance(signal, dict):
        return False

    entry = signal.get("entry")
    stop_loss = signal.get("stop_loss")
    take_profit = signal.get("take_profit")
    reported_rr = signal.get("rr", signal.get("risk_reward"))

    if not all(is_positive_number(v) for v in (entry, stop_loss, take_profit)):
        log("Signal rejeté : prix d'entrée/SL/TP invalide.", "warning")
        return False

    entry, stop_loss, take_profit = map(float, (entry, stop_loss, take_profit))
    if entry == stop_loss or entry == take_profit:
        log("Signal rejeté : niveaux confondus.", "warning")
        return False

    direction = str(
        signal.get("direction", signal.get("signal_type", ""))
    ).strip().upper()
    is_buy = direction in {"BUY", "LONG", "CALL", "HAUSSIER", "HAUSSIÈRE"}
    is_sell = direction in {"SELL", "SHORT", "PUT", "BAISSIER", "BAISSIÈRE"}

    if is_buy and not (stop_loss < entry < take_profit):
        log("Signal BUY rejeté : il faut SL < entrée < TP.", "warning")
        return False
    if is_sell and not (take_profit < entry < stop_loss):
        log("Signal SELL rejeté : il faut TP < entrée < SL.", "warning")
        return False
    if not (is_buy or is_sell):
        log(f"Signal rejeté : direction inconnue ({direction!r}).", "warning")
        return False

    actual_rr = abs(take_profit - entry) / abs(entry - stop_loss)
    try:
        claimed_rr = float(reported_rr)
    except (TypeError, ValueError, OverflowError):
        claimed_rr = 0.0

    if not math.isfinite(actual_rr) or actual_rr < MIN_RISK_REWARD:
        log(
            f"Signal rejeté : RR calculé {actual_rr:.2f}, "
            f"minimum requis 2.00.",
            "warning",
        )
        return False
    if not math.isfinite(claimed_rr) or claimed_rr < MIN_RISK_REWARD:
        log(
            f"Signal rejeté : RR annoncé {claimed_rr:.2f}, "
            f"minimum requis 2.00.",
            "warning",
        )
        return False

    # Le RR affiché doit correspondre au ratio calculé depuis les prix.
    if abs(claimed_rr - actual_rr) > max(0.15, actual_rr * 0.10):
        log(
            f"Signal rejeté : RR annoncé ({claimed_rr:.2f}) incohérent "
            f"avec le RR calculé ({actual_rr:.2f}).",
            "warning",
        )
        return False

    signal["rr"] = round(actual_rr, 2)
    signal["risk_reward"] = round(actual_rr, 2)
    signal["automatic_execution"] = False
    return True


def process_symbol(symbol: str) -> int:
    label = SYMBOL_LABELS.get(symbol, symbol)
    market_data = fetch_market_data(symbol)
    if market_data is None:
        log(f"{label} : données insuffisantes, analyse ignorée.", "warning")
        return 0

    snapshot = {
        "symbol": symbol,
        "current_price": market_data["current_price"],
        "timeframes": {
            timeframe: market_data[timeframe]
            for timeframe in ("D1", "H4", "H2", "H1")
        },
    }

    try:
        result = analyze_symbol_completely(symbol=symbol, snapshot=snapshot)
    except Exception as exc:
        log(f"{label} : erreur stratégie : {exc}", "error")
        return 0

    if not isinstance(result, dict):
        log(f"{label} : résultat stratégie invalide.", "warning")
        return 0
    if result.get("status") != "SIGNAL_CANDIDATE":
        log(
            f"{label} : aucun signal conforme — "
            f"{result.get('status', 'UNKNOWN')} / "
            f"{result.get('reason', 'motif non précisé')}"
        )
        return 0

    signal = dict(result)
    signal["symbol"] = symbol
    signal["label"] = label
    signal["current_price"] = market_data["current_price"]
    signal["rr"] = signal.get("rr", signal.get("risk_reward"))
    signal["automatic_execution"] = False

    if not validate_signal(signal):
        return 0

    try:
        message = format_message(signal)
    except Exception as exc:
        log(f"{label} : erreur formatage message : {exc}", "error")
        return 0

    if not isinstance(message, str) or not message.strip():
        log(f"{label} : message vide, signal non envoyé.", "warning")
        return 0

    # Le label complet et le RR validé sont ajoutés même si le formateur
    # de stratégie ne connaît pas encore le nouvel actif.
    message = (
        f"📊 {label} ({symbol})\n"
        f"RR vérifié : 1:{signal['rr']:.2f}\n"
        f"Exécution automatique : DÉSACTIVÉE\n\n"
        f"{message}"
    )

    if telegram_is_ready():
        send_telegram_message(message)
    else:
        log("Signal valide mais Telegram n'est pas configuré.", "warning")

    return 1


def run_preflight_checks() -> bool:
    if not DERIV_MODULE_READY:
        log("Module Deriv indisponible.", "error")
        return False
    if not STRATEGY_MODULE_READY:
        log("Module stratégie indisponible.", "error")
        return False
    if ENABLE_AUTO_TRADING:
        log("ERREUR DE SÉCURITÉ : trading automatique activé.", "error")
        return False
    if MIN_CANDLES != 200 or MIN_RISK_REWARD != 2.0:
        log("Configuration invalide : vérifier bougies/RR.", "error")
        return False
    if ENABLE_TELEGRAM_ALERTS and not telegram_is_ready():
        log("Telegram activé mais token/chat ID absent.", "warning")
    return True


def run_analysis() -> int:
    print_startup_information()
    if not run_preflight_checks():
        return 1

    try:
        if not configure_symbols():
            log("Aucun des neuf marchés demandés n'a été résolu.", "error")
            return 1
    except Exception as exc:
        log(f"Découverte des symboles Deriv impossible : {exc}", "error")
        return 1

    if len(SYMBOLS) < len(ASSET_ALIASES):
        log(
            f"ATTENTION : {len(SYMBOLS)}/{len(ASSET_ALIASES)} marchés "
            "seulement sont disponibles. Les marchés absents ne seront pas "
            "analysés; vérifier les accès et la plateforme Deriv.",
            "warning",
        )

    started_at = datetime.now(timezone.utc)
    log(f"Début : {started_at:%Y-%m-%d %H:%M:%S UTC}")
    analyzed = 0
    skipped = 0
    signals = 0

    for index, symbol in enumerate(SYMBOLS, start=1):
        log(f"Progression : marché {index}/{len(SYMBOLS)}")
        try:
            count = process_symbol(symbol)
            analyzed += 1
            signals += count
        except Exception as exc:
            skipped += 1
            log(f"{symbol} : erreur inattendue : {exc}", "error")
        if index < len(SYMBOLS):
            time.sleep(REQUEST_DELAY)

    log("=" * 68)
    log("BILAN DE L'ANALYSE")
    log(f"Marchés résolus : {len(SYMBOLS)}/{len(ASSET_ALIASES)}")
    log(f"Marchés tentés : {analyzed}")
    log(f"Erreurs inattendues : {skipped}")
    log(f"Signaux valides RR >= 1:2 : {signals}")
    log(f"DRY_RUN : {DRY_RUN}")
    log("Exécution automatique : DÉSACTIVÉE")
    log("=" * 68)
    log(f"Fin : {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S UTC}")
    return 0 if analyzed > 0 else 1


def main() -> None:
    try:
        raise SystemExit(run_analysis())
    except KeyboardInterrupt:
        log("Analyse interrompue manuellement.", "warning")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
