
import os
import requests
from deriv_market import get_candles
from analysis_engine import analyze_candles

TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"

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


def send_telegram(message):
    if DRY_RUN:
        print("[MODE TEST] Envoi Telegram désactivé.")
        print(message)
        return

    if not TOKEN or not CHAT_ID:
        print("[ERREUR] TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID manquant.")
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": message,
            },
            timeout=15,
        )
        response.raise_for_status()

        result = response.json()
        if not result.get("ok"):
            print("[ERREUR TELEGRAM]", result)
        else:
            print("[TELEGRAM] Message envoyé.")
    except Exception as exc:
        print(f"[ERREUR TELEGRAM] {exc}")


def show_analysis(symbol, timeframe, result):
    print(
        f"[ANALYSE] {symbol} | {timeframe} "
        f"| statut={result.get('status')} "
        f"| bougies={result.get('candle_count')} "
        f"| tendance={result.get('trend')}"
    )
    print(
        f"[NIVEAUX] {symbol} | {timeframe} "
        f"| support={result.get('support')} "
        f"| résistance={result.get('resistance')}"
    )

    trendline = result.get("trendline")
    if trendline:
        print(
            f"[TRENDLINE] {symbol} | {timeframe} "
            f"| direction={trendline.get('direction')} "
            f"| prix={trendline.get('price')}"
        )
    else:
        print(f"[TRENDLINE] {symbol} | {timeframe} | aucune")

    order_block = result.get("order_block")
    if order_block:
        print(
            f"[ORDER BLOCK] {symbol} | {timeframe} "
            f"| type={order_block.get('type')} "
            f"| bas={order_block.get('low')} "
            f"| haut={order_block.get('high')}"
        )
    else:
        print(f"[ORDER BLOCK] {symbol} | {timeframe} | aucun")

    signal = result.get("signal")
    if signal:
        print(
            f"[SIGNAL] {symbol} | {timeframe} "
            f"| {signal.get('direction')} "
            f"| entrée={signal.get('entry')} "
            f"| SL={signal.get('stop_loss')} "
            f"| TP={signal.get('take_profit')} "
            f"| RR=1:{signal.get('risk_reward')}"
        )
    else:
        print(f"[AUCUN SIGNAL] {symbol} | {timeframe}")


def format_signal(symbol, daily, h4, h1, signal):
    return (
        f"TRADER AI PRO\n\n"
        f"Actif : {symbol}\n"
        f"Direction : {signal['direction']}\n"
        f"Entrée : {signal['entry']:.5f}\n"
        f"Stop Loss : {signal['stop_loss']:.5f}\n"
        f"Take Profit : {signal['take_profit']:.5f}\n"
        f"Ratio risque/rendement : 1:{signal['risk_reward']:.0f}\n\n"
        f"Tendance D1 : {daily.get('trend')}\n"
        f"Tendance H4 : {h4.get('trend')}\n"
        f"Tendance H1 : {h1.get('trend')}\n"
        f"Zone : {signal.get('zone_type')}\n"
        f"Bas de zone : {signal.get('zone_low'):.5f}\n"
        f"Haut de zone : {signal.get('zone_high'):.5f}\n"
        f"Motif : {signal.get('reason')}\n\n"
        f"Mode test : {'OUI' if DRY_RUN else 'NON'}\n"
        f"Signal à vérifier avant toute décision."
    )


def main():
    print("=" * 60)
    print("TRADER AI PRO - DÉMARRAGE")
    print(f"Mode test : {DRY_RUN}")
    print(f"Nombre d'actifs : {len(SYMBOLS)}")
    print("=" * 60)

    signals_found = 0
    errors_found = 0

    for symbol in SYMBOLS:
        print(f"\n{'-' * 45}\n[ACTIF] {symbol}")

        analyses = {}

        for timeframe in ("D1", "H4", "H1"):
            try:
                print(f"[TÉLÉCHARGEMENT] {symbol} | {timeframe}")

                candles_data = get_candles(
                    symbol,
                    timeframe,
                    count=100,
                    timeout=8,
                )

                if isinstance(candles_data, dict):
                    candles = candles_data.get("candles", [])
                else:
                    candles = candles_data or []

                print(
                    f"[DONNÉES] {symbol} | {timeframe} "
                    f"| bougies reçues={len(candles)}"
                )

                result = analyze_candles(candles)
                show_analysis(symbol, timeframe, result)
                analyses[timeframe] = result

            except Exception as exc:
                errors_found += 1
                print(
                    f"[ERREUR ANALYSE] {symbol} | "
                    f"{timeframe} | {type(exc).__name__}: {exc}"
                )
                analyses[timeframe] = {
                    "trend": "INCONNU",
                    "signal": None,
                    "status": "ERREUR",
                    "candle_count": 0,
                }

        daily = analyses.get("D1", {})
        h4 = analyses.get("H4", {})
        h1 = analyses.get("H1", {})

        signal = h1.get("signal")

        if signal:
            signals_found += 1
            message = format_signal(symbol, daily, h4, h1, signal)
            print("[SIGNAL RETENU] Signal H1 trouvé.")

            if daily.get("trend") not in ("INCONNU", "LATERALE"):
                if daily.get("trend") != h4.get("trend"):
                    print(
                        "[AVERTISSEMENT] Les tendances D1 et H4 "
                        "ne concordent pas."
                    )

            send_telegram(message)
        else:
            print(
                f"[RÉSULTAT] {symbol} : aucun signal H1 "
                "conforme aux règles actuelles."
            )

    print("\n" + "=" * 60)
    print("TRADER AI PRO - FIN DE L'ANALYSE")
    print(f"Signaux trouvés : {signals_found}")
    print(f"Erreurs rencontrées : {errors_found}")
    print(f"Mode test actif : {DRY_RUN}")
    print("=" * 60)


if __name__ == "__main__":
    main()
