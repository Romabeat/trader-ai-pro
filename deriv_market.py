
import json
import re
import time

import websocket

URLS = [
    "wss://api.derivws.com/trading/v1/options/ws/public",
    "wss://ws.derivws.com/websockets/v3?app_id=1089",
    "wss://ws.binaryws.com/websockets/v3?app_id=1089",
]

VOLATILITY = re.compile(r"^(R_\d+|1HZ\d+V)$")
MAX_PER_ENDPOINT = 8

GRANULARITY = {
    "M30": 1800,
    "H1": 3600,
    "H2": 7200,
    "H4": 14400,
    "D1": 86400,
}


def _label(url):
    return url.split("?")[0].replace("wss://", "")


def fetch_active_symbols(url, timeout):
    result = {"endpoint": _label(url)}
    ws = None

    try:
        ws = websocket.create_connection(url, timeout=timeout)
        ws.send(json.dumps({
            "active_symbols": "brief",
            "req_id": 1,
        }))

        while True:
            data = json.loads(ws.recv())

            if data.get("error"):
                result["error"] = data["error"].get(
                    "message", "Erreur API"
                )
                break

            if data.get("msg_type") == "active_symbols":
                result["status"] = "ok"
                result["raw"] = data.get("active_symbols", [])
                break

    except websocket.WebSocketBadStatusException as e:
        result["error"] = "HTTP %s" % e.status_code

    except Exception as e:
        result["error"] = "%s: %s" % (type(e).__name__, e)

    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    print(
        "WS_TEST_RESULT:",
        result["endpoint"],
        result.get("status") or result.get("error")
    )
    return result


def get_synthetic_symbols(timeout=12):
    per_endpoint = min(timeout, MAX_PER_ENDPOINT)
    diagnostic = []

    for url in URLS:
        result = fetch_active_symbols(url, per_endpoint)

        if result.get("status") == "ok":
            raw = result.pop("raw")
            symbols = []

            for item in raw:
                code = item.get("underlying_symbol") or item.get("symbol")

                if code and VOLATILITY.match(code):
                    symbols.append({
                        "symbol": code,
                        "name": (
                            item.get("display_name")
                            or item.get("underlying_symbol_name")
                            or code
                        ),
                    })

            symbols.sort(key=lambda s: s["symbol"])
            diagnostic.append(result)

            return {
                "symbols": symbols,
                "endpoint": result["endpoint"],
                "total_active": len(raw),
                "diagnostic": diagnostic,
            }

        result.pop("raw", None)
        diagnostic.append(result)

    detail = " | ".join(
        "%s -> %s" % (
            d["endpoint"],
            d.get("error", "échec")
        )
        for d in diagnostic
    )

    return {
        "error": "Connexion Deriv impossible. " + detail,
        "diagnostic": diagnostic,
    }


def get_candles(symbol, timeframe="H1", count=50, timeout=8):
    """Récupère les bougies clôturées d'un indice Deriv."""

    if not VOLATILITY.match(symbol or ""):
        return {"error": "Symbole non valide : %s" % symbol}

    if timeframe not in GRANULARITY:
        return {"error": "Unité de temps non valide : %s" % timeframe}

    granularity = GRANULARITY[timeframe]
    ws = None
    errors = []

    # Essaye les adresses dans l'ordre, comme pour les symboles.
    for url in URLS:
        try:
            ws = websocket.create_connection(url, timeout=timeout)
            break
        except Exception as error:
            errors.append(
                "%s -> %s: %s"
                % (_label(url), type(error).__name__, error)
            )

    if ws is None:
        return {
            "error": "Connexion WebSocket impossible. " + " | ".join(errors)
        }

    try:
        ws.send(json.dumps({
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": int(count),
            "end": "latest",
            "style": "candles",
            "granularity": granularity,
            "req_id": 2,
        }))

        while True:
            data = json.loads(ws.recv())

            if data.get("error"):
                return {
                    "error": data["error"].get(
                        "message", "Erreur API Deriv"
                    )
                }

            if data.get("msg_type") == "candles":
                break

        now = time.time()
        candles = []

        for candle in data.get("candles", []):
            epoch = int(candle["epoch"])

            if epoch + granularity <= now:
                candles.append({
                    "epoch": epoch,
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                })

        candles.sort(key=lambda candle: candle["epoch"])

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(candles),
            "candles": candles,
        }

    except Exception as error:
        return {
            "error": "%s: %s" % (type(error).__name__, error)
        }

    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
