
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
MAX_CANDLES = 5000

GRANULARITY = {
    "M30": 1800,
    "H1": 3600,
    "H2": 7200,
    "H4": 14400,
    "D1": 86400,
}


def _label(url):
    return url.split("?")[0].replace("wss://", "")


def _close_socket(ws):
    if ws is not None:
        try:
            ws.close()
        except Exception:
            pass


def _receive_response(ws, expected_type, timeout):
    """
    Attend le type de réponse demandé.
    Retourne une erreur si l'API signale un problème
    ou si le délai expire.
    """
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            data = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            break
        except json.JSONDecodeError:
            continue

        if not isinstance(data, dict):
            continue

        if data.get("error"):
            error = data["error"]
            message = error.get("message", "Erreur API Deriv")
            return None, message

        if data.get("msg_type") == expected_type:
            return data, None

    return None, (
        "Délai dépassé en attendant la réponse "
        + expected_type
    )


def fetch_active_symbols(url, timeout):
    result = {"endpoint": _label(url)}
    ws = None

    try:
        ws = websocket.create_connection(
            url,
            timeout=timeout,
        )

        ws.send(json.dumps({
            "active_symbols": "brief",
            "req_id": 1,
        }))

        data, error = _receive_response(
            ws,
            "active_symbols",
            timeout,
        )

        if error:
            result["error"] = error
        else:
            result["status"] = "ok"
            result["raw"] = data.get("active_symbols", [])

    except websocket.WebSocketBadStatusException as error:
        result["error"] = "HTTP %s" % error.status_code

    except Exception as error:
        result["error"] = (
            "%s: %s" % (type(error).__name__, error)
        )

    finally:
        _close_socket(ws)

    print(
        "WS_TEST_RESULT:",
        result["endpoint"],
        result.get("status") or result.get("error"),
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
                if not isinstance(item, dict):
                    continue

                code = (
                    item.get("underlying_symbol")
                    or item.get("symbol")
                )

                if code and VOLATILITY.fullmatch(code):
                    symbols.append({
                        "symbol": code,
                        "name": (
                            item.get("display_name")
                            or item.get("underlying_symbol_name")
                            or code
                        ),
                    })

            # Supprime les doublons éventuels.
            unique = {
                item["symbol"]: item
                for item in symbols
            }

            symbols = sorted(
                unique.values(),
                key=lambda item: item["symbol"],
            )

            diagnostic.append({
                "endpoint": result["endpoint"],
                "status": "ok",
            })

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
            item["endpoint"],
            item.get("error", "échec"),
        )
        for item in diagnostic
    )

    return {
        "error": "Connexion Deriv impossible. " + detail,
        "diagnostic": diagnostic,
    }


def get_candles(
    symbol,
    timeframe="H1",
    count=50,
    timeout=8,
):
    """
    Récupère les bougies clôturées d'un indice Deriv.

    Format retourné :
    {
        "symbol": "...",
        "timeframe": "H1",
        "count": 100,
        "candles": [
            {
                "epoch": 1234567890,
                "open": 1.0,
                "high": 1.2,
                "low": 0.9,
                "close": 1.1
            }
        ]
    }
    """
    if not isinstance(symbol, str) or not VOLATILITY.fullmatch(symbol):
        return {
            "error": "Symbole non valide : %s" % symbol
        }

    if timeframe not in GRANULARITY:
        return {
            "error": "Unité de temps non valide : %s" % timeframe
        }

    try:
        count = int(count)
    except (TypeError, ValueError):
        return {"error": "Le nombre de bougies doit être un entier"}

    if count < 1 or count > MAX_CANDLES:
        return {
            "error": (
                "Nombre de bougies invalide : "
                "choisir entre 1 et %s" % MAX_CANDLES
            )
        }

    try:
        timeout = max(1, float(timeout))
    except (TypeError, ValueError):
        return {"error": "Délai d'attente invalide"}

    granularity = GRANULARITY[timeframe]
    errors = []

    # Essaye chaque endpoint jusqu'à obtenir des bougies valides.
    for url in URLS:
        ws = None

        try:
            ws = websocket.create_connection(
                url,
                timeout=timeout,
            )

            ws.send(json.dumps({
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count,
                "end": "latest",
                "style": "candles",
                "granularity": granularity,
                "req_id": 2,
            }))

            data, error = _receive_response(
                ws,
                "candles",
                timeout,
            )

            if error:
                errors.append(
                    "%s -> %s" % (_label(url), error)
                )
                continue

            raw_candles = data.get("candles", [])

            if not isinstance(raw_candles, list):
                errors.append(
                    "%s -> Format des bougies invalide"
                    % _label(url)
                )
                continue

            now = time.time()
            candles = []

            for candle in raw_candles:
                try:
                    epoch = int(candle["epoch"])
                    open_price = float(candle["open"])
                    high = float(candle["high"])
                    low = float(candle["low"])
                    close = float(candle["close"])

                    values = [
                        open_price,
                        high,
                        low,
                        close,
                    ]

                    # Refuse les valeurs non finies ou incohérentes.
                    if not all(
                        value == value
                        and abs(value) != float("inf")
                        for value in values
                    ):
                        continue

                    if min(values) <= 0:
                        continue

                    if high < max(open_price, close, low):
                        continue

                    if low > min(open_price, close, high):
                        continue

                    # Ne conserve que les bougies entièrement clôturées.
                    if epoch + granularity > now:
                        continue

                    candles.append({
                        "epoch": epoch,
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                    })

                except (KeyError, TypeError, ValueError, OverflowError):
                    continue

            # Trie les bougies et élimine les doublons temporels.
            candles.sort(key=lambda item: item["epoch"])

            unique_candles = {}
            for candle in candles:
                unique_candles[candle["epoch"]] = candle

            candles = sorted(
                unique_candles.values(),
                key=lambda item: item["epoch"],
            )

            if not candles:
                errors.append(
                    "%s -> Aucune bougie clôturée valide"
                    % _label(url)
                )
                continue

            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "count": len(candles),
                "candles": candles,
            }

        except websocket.WebSocketBadStatusException as error:
            errors.append(
                "%s -> HTTP %s"
                % (_label(url), error.status_code)
            )

        except Exception as error:
            errors.append(
                "%s -> %s: %s"
                % (
                    _label(url),
                    type(error).__name__,
                    str(error)[:150],
                )
            )

        finally:
            _close_socket(ws)

    return {
        "error": (
            "Impossible de récupérer les bougies pour "
            + symbol
            + " en "
            + timeframe
            + ". "
            + " | ".join(errors)
        )
    }
