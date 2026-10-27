
import os
from flask import Flask, jsonify, request
import requests
from deriv_market import get_synthetic_symbols, get_candles

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


@app.get("/")
def home():
    return jsonify({
        "bot": "TRADER AI PRO",
        "status": "online",
        "mode": "alerts_only",
        "symbols_test": "/symbols",
        "candles_test": "/candles?symbol=R_100&timeframe=H1&count=50"
    })


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/symbols")
def symbols():
    try:
        data = get_synthetic_symbols(timeout=15)

        if data.get("error"):
            return jsonify({
                "status": "error",
                "message": data["error"]
            }), 502

        found = data.get("symbols", [])

        return jsonify({
            "status": "ok",
            "count": len(found),
            "symbols": found
        })

    except Exception:
        app.logger.exception("Erreur pendant la récupération des indices")
        return jsonify({
            "status": "error",
            "message": "Impossible de récupérer les indices."
        }), 500


@app.get("/candles")
def candles():
    symbol = request.args.get("symbol", "R_100").strip()
    timeframe = request.args.get("timeframe", "H1").upper()
    try:
        count = int(request.args.get("count", "50"))
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "count doit être un nombre entier."
        }), 400

    if not 1 <= count <= 200:
        return jsonify({
            "status": "error",
            "message": "count doit être compris entre 1 et 200."
        }), 400

    try:
        data = get_candles(
            symbol=symbol,
            timeframe=timeframe,
            count=count,
            timeout=8
        )

        if data.get("error"):
            return jsonify({
                "status": "error",
                "message": data["error"]
            }), 502

        return jsonify({
            "status": "ok",
            "symbol": data["symbol"],
            "timeframe": data["timeframe"],
            "count": data["count"],
            "candles": data["candles"]
        })

    except Exception:
        app.logger.exception("Erreur pendant la récupération des bougies")
        return jsonify({
            "status": "error",
            "message": "Impossible de récupérer les bougies."
        }), 500


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=15
    )
    response.raise_for_status()
    return True


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
