
import os
from flask import Flask, jsonify, request
import requests

from deriv_market import get_synthetic_symbols, get_candles
from analysis_engine import analyze_candles

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

ALLOWED_SYMBOLS = {
    "1HZ100V", "1HZ10V", "1HZ15V", "1HZ25V",
    "1HZ30V", "1HZ50V", "1HZ75V", "1HZ90V",
    "R_10", "R_100", "R_25", "R_50", "R_75",
}

ALLOWED_TIMEFRAMES = {"H1", "H2", "H4", "D1"}


@app.get("/")
def home():
    return jsonify({
        "bot": "TRADER AI PRO",
        "status": "online",
        "mode": "alerts_only",
        "routes": [
            "/health",
            "/symbols",
            "/candles?symbol=R_100&timeframe=H1&count=50",
            "/analyze?symbol=R_100&timeframe=H1&count=50",
        ],
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
                "message": data["error"],
            }), 502

        found = data.get("symbols", [])

        return jsonify({
            "status": "ok",
            "count": len(found),
            "symbols": found,
        })

    except Exception:
        app.logger.exception("Erreur de récupération des indices")
        return jsonify({
            "status": "error",
            "message": "Impossible de récupérer les indices.",
        }), 500


def fetch_candles(symbol, timeframe, count):
    """Récupère les bougies et renvoie une erreur exploitable si nécessaire."""
    data = get_candles(
        symbol=symbol,
        timeframe=timeframe,
        count=count,
        timeout=8,
    )

    if data.get("error"):
        raise ValueError(data["error"])

    return data


@app.get("/candles")
def candles():
    symbol = request.args.get("symbol", "R_100").strip().upper()
    timeframe = request.args.get("timeframe", "H1").strip().upper()

    try:
        count = int(request.args.get("count", "50"))
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "count doit être un entier.",
        }), 400

    if symbol not in ALLOWED_SYMBOLS:
        return jsonify({
            "status": "error",
            "message": "Indice non autorisé.",
        }), 400

    if timeframe not in ALLOWED_TIMEFRAMES:
        return jsonify({
            "status": "error",
            "message": "Unité autorisée : H1, H2, H4 ou D1.",
        }), 400

    if not 1 <= count <= 200:
        return jsonify({
            "status": "error",
            "message": "count doit être compris entre 1 et 200.",
        }), 400

    try:
        data = fetch_candles(symbol, timeframe, count)

        return jsonify({
            "status": "ok",
            "symbol": data.get("symbol", symbol),
            "timeframe": data.get("timeframe", timeframe),
            "count": data.get("count", len(data.get("candles", []))),
            "candles": data.get("candles", []),
        })

    except ValueError as exc:
        return jsonify({
            "status": "error",
            "message": str(exc),
        }), 502

    except Exception:
        app.logger.exception("Erreur de récupération des bougies")
        return jsonify({
            "status": "error",
            "message": "Impossible de récupérer les bougies.",
        }), 500


def send_telegram(message):
    """Envoie un message Telegram si les variables Render sont configurées."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
        },
        timeout=15,
    )
    response.raise_for_status()
    return True


@app.get("/analyze")
def analyze():
    symbol = request.args.get("symbol", "R_100").strip().upper()
    timeframe = request.args.get("timeframe", "H1").strip().upper()

    try:
        count = int(request.args.get("count", "100"))
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "count doit être un entier.",
        }), 400

    if symbol not in ALLOWED_SYMBOLS:
        return jsonify({
            "status": "error",
            "message": "Indice non autorisé.",
        }), 400

    if timeframe not in ALLOWED_TIMEFRAMES:
        return jsonify({
            "status": "error",
            "message": "Unité autorisée : H1, H2, H4 ou D1.",
        }), 400

    if not 30 <= count <= 200:
        return jsonify({
            "status": "error",
            "message": "Pour l'analyse, count doit être entre 30 et 200.",
        }), 400

    try:
        data = fetch_candles(symbol, timeframe, count)
        candles_data = data.get("candles", [])

        if len(candles_data) < 30:
            return jsonify({
                "status": "error",
                "message": "Pas assez de bougies pour analyser ce marché.",
                "received": len(candles_data),
            }), 422

        analysis = analyze_candles(candles_data)

        return jsonify({
            "status": "ok",
            "symbol": symbol,
            "timeframe": timeframe,
            "analysis": analysis,
            "note": (
                "Analyse technique indicative. "
                "Aucun ordre n'est exécuté automatiquement."
            ),
        })

    except ValueError as exc:
        return jsonify({
            "status": "error",
            "message": str(exc),
        }), 502

    except Exception:
        app.logger.exception("Erreur pendant l'analyse")
        return jsonify({
            "status": "error",
            "message": "Impossible d'analyser cet indice.",
        }), 500


@app.get("/analyze_multi")
def analyze_multi():
    symbol = request.args.get("symbol", "R_100").strip().upper()
    entry_tf = request.args.get("entry_tf", "H1").strip().upper()

    if symbol not in ALLOWED_SYMBOLS:
        return jsonify({
            "status": "error",
            "message": "Indice non autorisé."
        }), 400

    if entry_tf not in {"H1", "H2"}:
        return jsonify({
            "status": "error",
            "message": "entry_tf doit être H1 ou H2."
        }), 400

    results = {}

    try:
        for timeframe in ("D1", "H4", entry_tf):
            data = fetch_candles(symbol, timeframe, 100)
            candles_data = data.get("candles", [])

            if len(candles_data) < 30:
                return jsonify({
                    "status": "error",
                    "message": f"Pas assez de bougies en {timeframe}.",
                    "received": len(candles_data)
                }), 422

            results[timeframe] = analyze_candles(candles_data)

        return jsonify({
            "status": "ok",
            "symbol": symbol,
            "analysis": results,
            "note": (
                "Comparaison multi-unités de temps. "
                "Ce résultat ne constitue pas encore un signal d'entrée."
            )
        })

    except ValueError as exc:
        return jsonify({
            "status": "error",
            "message": str(exc)
        }), 502

    except Exception:
        app.logger.exception("Erreur d'analyse multi-unités")
        return jsonify({
            "status": "error",
            "message": "Échec de l'analyse multi-unités."
        }), 500
    

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
