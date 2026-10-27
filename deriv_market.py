
import json
import threading
import websocket

URLS = [
    "wss://ws.derivws.com/websockets/v3?app_id=1089",
    "wss://ws.binaryws.com/websockets/v3?app_id=1089",
]

def test_endpoint(url, timeout=12):
    result = {"endpoint": url.split("/")[2]}
    done = threading.Event()

    def on_open(ws):
        print("WS_OPEN:", result["endpoint"])
        ws.send(json.dumps({
            "active_symbols": "brief",
            "product_type": "basic",
            "req_id": 1
        }))

    def on_message(ws, message):
        data = json.loads(message)

        if data.get("msg_type") == "active_symbols":
            result["status"] = "ok"
            result["count"] = len(data.get("active_symbols", []))
            done.set()
            ws.close()
        elif data.get("error"):
            result["error"] = data["error"].get(
                "message", "Erreur API"
            )
            done.set()
            ws.close()

    def on_error(ws, error):
        result["error"] = str(error)
        print("WS_ERROR:", result["endpoint"], error)
        done.set()

    def on_close(ws, code, message):
        print("WS_CLOSE:", result["endpoint"], code, message)
        done.set()

    ws = websocket.WebSocketApp(
        url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )

    thread = threading.Thread(
        target=lambda: ws.run_forever(
            ping_interval=20,
            ping_timeout=10
        ),
        daemon=True
    )
    thread.start()

    if not done.wait(timeout):
        result["error"] = "Délai dépassé"
        ws.close()

    return result

def get_synthetic_symbols(timeout=12):
    diagnostic = []

    for url in URLS:
        result = test_endpoint(url, timeout)
        diagnostic.append(result)
        print("WS_TEST_RESULT:", json.dumps(result))

        if result.get("status") == "ok":
            return {
                "symbols": [],
                "diagnostic": diagnostic
            }

    return {
        "error": "Les connexions WebSocket ont échoué.",
        "diagnostic": diagnostic
    }

