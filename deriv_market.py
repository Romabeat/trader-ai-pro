
import json
import threading
import time
import websocket
print("TEST : le module Deriv est chargé")

APP_ID = "1089"
WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
def get_synthetic_symbols(timeout=15):
    """Récupère les symboles synthétiques proposés par Deriv."""
    result = {}
    finished = threading.Event()

    def on_message(ws, message):
        data = json.loads(message)

        if data.get("msg_type") == "active_symbols":
            symbols = data.get("active_symbols", [])
            selected = []

            for item in symbols:
                market = str(item.get("market", "")).lower()
                submarket = str(item.get("submarket", "")).lower()
                name = str(item.get("display_name", ""))
                symbol = str(item.get("symbol", ""))

                # Exclut les marchés financiers traditionnels.
                text = f"{market} {submarket} {name} {symbol}".lower()
                if "synthetic" in text or "derived" in text:
                    selected.append({
                        "symbol": symbol,
                        "name": name,
                        "market": market,
                        "submarket": submarket,
                        "priority": (
                            1 if "volatility" in name.lower()
                            else 2
                        )
                    })

            selected.sort(key=lambda x: (x["priority"], x["name"]))
            result["symbols"] = selected
            finished.set()
            ws.close()

        elif data.get("error"):
            result["error"] = data["error"].get("message", "Erreur Deriv")
            finished.set()
            ws.close()

    def on_error(ws, error):
        result["error"] = str(error)
        finished.set()

    def on_close(ws, close_status_code, close_msg):
        finished.set()

    def on_open(ws):
        ws.send(json.dumps({
            "active_symbols": "full",
            "product_type": "basic"
        }))

    ws = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    thread = threading.Thread(target=ws.run_forever, daemon=True)
    thread.start()

    if not finished.wait(timeout):
        ws.close()
        result["error"] = "Délai dépassé pendant la connexion à Deriv."

    return result

if __name__ == "__main__":
    data = get_synthetic_symbols()
    print(json.dumps(data, indent=2, ensure_ascii=False))
  
