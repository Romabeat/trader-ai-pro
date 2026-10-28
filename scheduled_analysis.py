
import os
import requests

from deriv_market import get_candles
from analysis_engine import analyze_candles

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

SYMBOLS = [
    "1HZ100V", "1HZ10V", "1HZ15V", "1HZ25V",
    "1HZ30V", "1HZ50V", "1HZ75V", "1HZ90V",
    "R_10", "R_100", "R_25", "R_50", "R_75",
]

def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Variables Telegram manquantes.")
    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": message},
        timeout=20,
    )
    response.raise_for_status()
    if not response.json().get("ok"):
        raise RuntimeError("Telegram n'a pas confirmé l'envoi.")

def get_analysis(symbol, timeframe):
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
        raise RuntimeError(f"Pas assez de bougies en {timeframe}")

    return analyze_candles(candles)

def main():
    messages = []
    errors = []

    for symbol in SYMBOLS:
        try:
            daily = get_analysis(symbol, "D1")
            four_hour = get_analysis(symbol, "H4")
            hourly = get_analysis(symbol, "H1")

            signal = hourly.get("signal") or {}
            direction = str(signal.get("direction", "")).upper()

            if direction not in ("BUY", "SELL"):
                continue

            entry = signal.get("entry")
            stop = signal.get("stop_loss")
            target = signal.get("take_profit")
            zone_low = signal.get("zone_low")
            zone_high = signal.get("zone_high")

            if any(v is None for v in
                   (entry, stop, target, zone_low, zone_high)):
                continue

            messages.append(
                f"📊 TRADER AI PRO — {symbol}\n"
                f"Signal : {direction}\n"
                f"Unité d'entrée : H1\n"
                f"Contexte H4 : {four_hour.get('trend', 'indisponible')}\n"
                f"Contexte D1 : {daily.get('trend', 'indisponible')}\n"
                f"Zone : {zone_low} – {zone_high}\n"
                f"Entrée indicative : {entry}\n"
                f"SL : {stop}\n"
                f"TP : {target}\n"
                f"Risque/rendement visé : 1:3\n"
                f"Type de zone : {signal.get('zone_type', 'non précisé')}\n"
                f"Motif : {signal.get('reason', 'non précisé')}\n\n"
                "⚠️ Signal indicatif, non validé par backtest. "
                "Vérifie le prix, la zone et la distance du SL avant toute entrée."
            )

        except Exception as exc:
            errors.append(f"{symbol}: {str(exc)[:150]}")

    if messages:
        for message in messages:
            send_telegram(message)

    if errors:
        send_telegram(
            "⚠️ TRADER AI PRO — erreurs sur certains indices :\n"
            + "\n".join(errors[:10])
        )

    if not messages and not errors:
        send_telegram(
            "ℹ️ TRADER AI PRO : analyse terminée. "
            "Aucun signal BUY/SELL conforme détecté."
        )

if __name__ == "__main__":
    main()

