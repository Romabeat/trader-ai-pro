
import os
import requests

from deriv_market import get_candles
from analysis_engine import analyze_candles


TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Sécurité : les messages ne sont pas envoyés par défaut.
# Pour autoriser l'envoi Telegram, définir DRY_RUN=false.
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() != "false"

SYMBOLS = [
    "1HZ100V", "1HZ10V", "1HZ15V", "1HZ25V",
    "1HZ30V", "1HZ50V", "1HZ75V", "1HZ90V",
    "R_10", "R_100", "R_25", "R_50", "R_75",
]

TIMEFRAMES = ["D1", "H4", "H1"]


def send_telegram(message):
    """Envoie un message Telegram et vérifie la réponse."""
    if not TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Variables TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquantes."
        )

    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message,
        },
        timeout=20,
    )

    response.raise_for_status()

    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "Réponse Telegram non valide."
        ) from exc

    if not result.get("ok"):
        raise RuntimeError(
            "Telegram n'a pas confirmé l'envoi."
        )


def get_analysis(symbol, timeframe):
    """Récupère les bougies et lance le moteur d'analyse."""
    data = get_candles(
        symbol=symbol,
        timeframe=timeframe,
        count=100,
        timeout=15,
    )

    if data.get("error"):
        raise RuntimeError(data["error"])

    candles = data.get("candles", [])

    if len(candles) < 30:
        raise RuntimeError(
            f"Pas assez de bougies en {timeframe}: {len(candles)}."
        )

    analysis = analyze_candles(candles)

    if not isinstance(analysis, dict):
        raise RuntimeError("Format d'analyse inattendu.")

    return analysis


def valid_number(value):
    """Vérifie qu'une valeur est numérique et finie."""
    try:
        number = float(value)
        return number == number and abs(number) != float("inf")
    except (TypeError, ValueError, OverflowError):
        return False


def format_signal(symbol, signal, hourly, four_hour, daily):
    """Construit un message à partir du signal H1 confirmé par le moteur."""
    direction = str(signal.get("direction", "")).upper()

    entry = signal.get("entry")
    stop = signal.get("stop_loss")
    target = signal.get("take_profit")
    zone = signal.get("zone") or {}

    zone_low = zone.get("low")
    zone_high = zone.get("high")
    zone_type = zone.get("type", "non précisé")

    required_values = [
        entry, stop, target, zone_low, zone_high
    ]

    if not all(valid_number(value) for value in required_values):
        raise ValueError(
            "Signal incomplet : entrée, SL, TP ou zone invalide."
        )

    entry = float(entry)
    stop = float(stop)
    target = float(target)
    zone_low = float(zone_low)
    zone_high = float(zone_high)

    if zone_low > zone_high:
        raise ValueError("Limites de zone incohérentes.")

    if direction == "BUY":
        if not stop < entry < target:
            raise ValueError("Niveaux BUY incohérents.")
    elif direction == "SELL":
        if not target < entry < stop:
            raise ValueError("Niveaux SELL incohérents.")
    else:
        raise ValueError("Direction de signal invalide.")

    trendline_context = signal.get(
        "trendline_context", "Non précisé"
    )
    trendline_direction = signal.get(
        "trendline_direction",
        (hourly.get("trendline") or {}).get(
            "direction", "Indéterminée"
        ),
    )

    liquidity = signal.get("liquidity_context") or {}

    liquidity_details = []
    if liquidity.get("nearby_equal_level"):
        liquidity_details.append("niveau EQH/EQL proche")
    if liquidity.get("matching_sweep"):
        liquidity_details.append("sweep récent détecté")
    if liquidity.get("target_liquidity"):
        liquidity_details.append("liquidité cible potentielle")

    liquidity_text = (
        ", ".join(liquidity_details)
        if liquidity_details
        else "Contexte de liquidité détecté par le moteur"
    )

    return (
        f"📊 TRADER AI PRO — {symbol}\n"
        f"Signal : {direction}\n"
        f"Unité d'entrée : H1\n"
        f"Tendance H4 : {four_hour.get('trend', 'indisponible')}\n"
        f"Tendance D1 : {daily.get('trend', 'indisponible')}\n"
        f"Trendline H1 : {trendline_direction}\n"
        f"Contexte trendline : {trendline_context}\n"
        f"Zone : {zone_low:g} – {zone_high:g}\n"
        f"Type de zone : {zone_type}\n"
        f"Entrée indicative : {entry:g}\n"
        f"SL : {stop:g}\n"
        f"TP : {target:g}\n"
        f"Risque/rendement visé : 1:3\n"
        f"Liquidité : {liquidity_text}\n"
        f"Motif : {signal.get('reason', 'non précisé')}\n\n"
        "⚠️ Signal indicatif, non validé par backtest. "
        "Vérifie les niveaux et le risque avant toute décision."
    )


def main():
    messages = []
    errors = []

    print("TRADER AI PRO — démarrage de l'analyse")
    print(f"Mode test sans envoi Telegram : {DRY_RUN}")

    for symbol in SYMBOLS:
        try:
            print(f"Analyse de {symbol}...")

            # Contexte des unités supérieures.
            daily = get_analysis(symbol, "D1")
            four_hour = get_analysis(symbol, "H4")

            # L'unité H1 fournit le signal d'entrée.
            hourly = get_analysis(symbol, "H1")

            signal = hourly.get("signal") or {}
            direction = str(
                signal.get("direction", "")
            ).upper()

            if direction not in ("BUY", "SELL"):
                print(
                    f"{symbol}: aucun signal — "
                    f"{signal.get('reason', 'conditions non réunies')}"
                )
                continue

            message = format_signal(
                symbol,
                signal,
                hourly,
                four_hour,
                daily,
            )

            messages.append(message)
            print(f"{symbol}: signal {direction} détecté.")

        except Exception as exc:
            error_message = f"{symbol}: {str(exc)[:200]}"
            errors.append(error_message)
            print(f"ERREUR — {error_message}")

    print(
        f"Analyse terminée : {len(messages)} signal(aux), "
        f"{len(errors)} erreur(s)."
    )

    # Mode test : afficher les résultats, sans envoyer de message.
    if DRY_RUN:
        for message in messages:
            print("\n" + "=" * 40)
            print(message)

        if errors:
            print("\nErreurs rencontrées :")
            for error in errors:
                print("- " + error)

        print(
            "\nMODE TEST : aucun message Telegram n'a été envoyé."
        )
        return

    # Envoi autorisé uniquement si DRY_RUN=false.
    if not TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Envoi annulé : variables Telegram manquantes."
        )

    for message in messages:
        try:
            send_telegram(message)
            print("Signal envoyé sur Telegram.")
        except Exception as exc:
            print(f"Échec d'envoi Telegram : {str(exc)[:200]}")

    if errors:
        error_report = (
            "⚠️ TRADER AI PRO — erreurs sur certains indices :\n"
            + "\n".join(errors[:10])
        )

        try:
            send_telegram(error_report)
        except Exception as exc:
            print(
                "Impossible d'envoyer le rapport d'erreurs : "
                + str(exc)[:200]
            )

    if not messages and not errors:
        try:
            send_telegram(
                "ℹ️ TRADER AI PRO : analyse terminée. "
                "Aucun signal BUY/SELL conforme détecté."
            )
        except Exception as exc:
            print(
                "Impossible d'envoyer le bilan : "
                + str(exc)[:200]
            )


if __name__ == "__main__":
    main()
