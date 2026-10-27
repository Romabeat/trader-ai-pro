import json
import re

import websocket

# Adresses essayées dans l'ordre. La première est la nouvelle API publique de Deriv
# (sans compte ni token). Les deux suivantes sont les anciennes adresses, gardées en secours.
URLS = [
    "wss://api.derivws.com/trading/v1/options/ws/public",
    "wss://ws.derivws.com/websockets/v3?app_id=1089",
    "wss://ws.binaryws.com/websockets/v3?app_id=1089",
]

# Indices Volatility : R_10, R_25, R_50, R_75, R_100 et les versions 1s (1HZ10V, 1HZ100V...)
VOLATILITY = re.compile(r"^(R_\d+|1HZ\d+V)$")

# Durée max par adresse (secondes). 3 x 8 s = 24 s, sous la limite de 30 s de Gunicorn.
MAX_PER_ENDPOINT = 8


def _label(url):
    return url.split("?")[0].replace("wss://", "")


def fetch_active_symbols(url, timeout):
    """Se connecte à une adresse et demande la liste des symboles actifs."""
    result = {"endpoint": _label(url)}
    ws = None
    try:
        ws = websocket.create_connection(url, timeout=timeout)
        print("WS_OPEN:", result["endpoint"])
        ws.send(json.dumps({"active_symbols": "brief", "req_id": 1}))
        while True:
            data = json.loads(ws.recv())
            if data.get("error"):
                result["error"] = data["error"].get("message", "Erreur API")
                break
            if data.get("msg_type") == "active_symbols":
                result["status"] = "ok"
                result["raw"] = data.get("active_symbols", [])
                break
    except websocket.WebSocketBadStatusException as e:
        # Cas de l'erreur 520 : le serveur refuse la connexion avant même le WebSocket
        result["error"] = "HTTP %s" % e.status_code
    except Exception as e:
        result["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
    print("WS_TEST_RESULT:", result["endpoint"], result.get("status") or result.get("error"))
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
                        "name": item.get("display_name")
                        or item.get("underlying_symbol_name")
                        or code,
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

    # Échec partout : la cause réelle de chaque adresse est écrite dans le message
    detail = " | ".join(
        "%s -> %s" % (d["endpoint"], d.get("error", "échec")) for d in diagnostic
    )
    return {
        "error": "Connexion Deriv impossible. " + detail,
        "diagnostic": diagnostic,
    }
