
import os
import requests

from deriv_market import get_candles
from analysis_engine import analyze_candles

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Sécurité : le mode test est activé par défaut.
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

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
    print(
        f"[DONNEES] {symbol} | {timeframe} | "
        "Demande de bougies à Deriv...",
        flush=True,
    )

    data = get_candles(
        symbol=symbol,
        timeframe=timeframe,
        count=100,
        timeout=8,
    )

    if data.get("error"):
        raise RuntimeError(data["error"])

    candles = data.get("candles", [])

    print(
        f"[DONNEES] {symbol} | {timeframe} | "
        f"{len(candles)} bougies clôturées reçues",
        flush=True,
    )

    if len(candles) < 30:
        raise RuntimeError(
            f"Pas assez de bougies : {len(candles)}"
        )

    result = analyze_candles(candles)

    print(
        f"[TENDANCE] {symbol} | {timeframe} | "
        f"{result.get('trend', 'indisponible')}",
        flush=True,
    )

    print(
        f"[ANALYSE] {symbol} | {timeframe} | "
        f"Signal détecté : {result.get('signal')}",
        flush=True,
    )

    return result


def main():
    print("=" * 55, flush=True)
    print("TRADER AI PRO — DIAGNOSTIC", flush=True)
    print(f"Mode test DRY_RUN : {DRY_RUN}", flush=True)
    print(f"Nombre d'indices à analyser : {len(SYMBOLS)}", flush=True)
    print("=" * 55, flush=True)

    messages = []
    errors = []
    analyzed = 0

    for symbol in SYMBOLS:
        print(f"\n[INDICE] Début de l'analyse : {symbol}", flush=True)

        try:
            daily = get_analysis(symbol, "D1")
            four_hour = get_analysis(symbol, "H4")
            hourly = get_analysis(symbol, "H1")
            analyzed += 1

            signal = hourly.get("signal") or {}
            direction = str(
                signal.get("direction", "")
            ).upper()

            if direction not in ("BUY", "SELL"):
                print(
                    f"[REJET] {symbol} : aucun signal H1 "
                    "conforme aux règles actuelles.",
                    flush=True,
                )
                continue

            entry = signal.get("entry")
            stop = signal.get("stop_loss")
            target = signal.get("take_profit")
            zone_low = signal.get("zone_low")
            zone_high = signal.get("zone_high")

            if any(value is None for value in (
                entry, stop, target, zone_low, zone_high
            )):
                print(
                    f"[REJET] {symbol} : signal incomplet.",
                    flush=True,
                )
                continue

            message = (
                f"TRADER AI PRO — {symbol}\n"
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
                "Signal indicatif, non validé par backtest. "
                "Vérifie le graphique avant toute décision."
            )

            messages.append(message)
            print(
                f"[SIGNAL] {symbol} : {direction} détecté.",
                flush=True,
            )

        except Exception as exc:
            error_message = f"{symbol}: {str(exc)[:200]}"
            errors.append(error_message)
            print(f"[ERREUR] {error_message}", flush=True)

    print("\n" + "=" * 55, flush=True)
    print("BILAN DU DIAGNOSTIC", flush=True)
    print(f"Indices entièrement analysés : {analyzed}/{len(SYMBOLS)}", flush=True)
    print(f"Signaux conformes détectés : {len(messages)}", flush=True)
    print(f"Indices en erreur : {len(errors)}", flush=True)
    print(f"Mode test : {DRY_RUN}", flush=True)

    if DRY_RUN:
        print(
            "[TEST] Aucun message Telegram ne sera envoyé.",
            flush=True,
        )

        for message in messages:
            print("\n[SIGNAL SIMULÉ]\n" + message, flush=True)

        for error in errors:
            print(f"[ERREUR DETAILLEE] {error}", flush=True)

    else:
        for message in messages:
            try:
                send_telegram(message)
                print("[TELEGRAM] Signal envoyé.", flush=True)
            except Exception as exc:
                print(
                    f"[TELEGRAM ERREUR] {str(exc)[:200]}",
                    flush=True,
                )

        if errors:
            try:
                send_telegram(
                    "TRADER AI PRO — erreurs sur certains indices :\n"
                    + "\n".join(errors[:10])
                )
            except Exception as exc:
                print(
                    f"[TELEGRAM ERREUR] {str(exc)[:200]}",
                    flush=True,
                )

        if not messages and not errors:
            send_telegram(
                "TRADER AI PRO : analyse terminée. "
                "Aucun signal BUY/SELL conforme détecté."
            )

    print("Fin du diagnostic.", flush=True)


if __name__ == "__main__":
    main()
