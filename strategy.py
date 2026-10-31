import logging
import math
from typing import Any, Dict, List, Optional, Tuple


LOGGER = logging.getLogger("TRADER_AI_PRO.STRATEGY")
logger = LOGGER  # Alias de compatibilite utilise par les fonctions du module.


SYMBOL_NAMES = {
    "1HZ10V": "Volatility 10 (1s) Index",
    "1HZ15V": "Volatility 15 (1s) Index",
    "1HZ25V": "Volatility 25 (1s) Index",
    "1HZ30V": "Volatility 30 (1s) Index",
    "1HZ50V": "Volatility 50 (1s) Index",
    "1HZ75V": "Volatility 75 (1s) Index",
    "1HZ90V": "Volatility 90 (1s) Index",
    "1HZ100V": "Volatility 100 (1s) Index",
    "R_10": "Volatility 10 Index",
    "R_25": "Volatility 25 Index",
    "R_50": "Volatility 50 Index",
    "R_75": "Volatility 75 Index",
    "R_100": "Volatility 100 Index",
}


TIMEFRAME_REQUIREMENTS = {
    "D1": 200,
    "H4": 200,
    "H2": 200,
    "H1": 200,
}


MIN_TRENDLINE_TOUCHES = 3
ATR_PERIOD = 14
MIN_RISK_REWARD = 1.0
ATR_STOP_BUFFER = 0.15
ZONE_ATR_TOLERANCE = 0.25
MIN_CANDLE_COUNT = 200
MAX_PRICE_DISTANCE_ATR = 1.5


class StrategyError(Exception):
    pass


def get_symbol_name(symbol: str) -> str:
    """Renvoie le nom lisible d'un indice Deriv."""
    symbol = str(symbol).strip()
    return SYMBOL_NAMES.get(symbol, symbol)


def _finite_number(
    value: Any,
    field_name: str = "valeur",
) -> float:
    """Convertit une valeur en nombre fini."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise StrategyError(
            f"Valeur numérique invalide pour {field_name}."
        ) from exc

    if not math.isfinite(number):
        raise StrategyError(
            f"Valeur non finie pour {field_name}."
        )

    return number


def _validate_candle(
    candle: Dict[str, Any],
) -> Dict[str, float]:
    """Valide et normalise une bougie OHLC."""
    if not isinstance(candle, dict):
        raise StrategyError(
            "Une bougie doit être un dictionnaire."
        )

    try:
        epoch = int(candle["epoch"])
        open_price = _finite_number(
            candle["open"],
            "open",
        )
        high_price = _finite_number(
            candle["high"],
            "high",
        )
        low_price = _finite_number(
            candle["low"],
            "low",
        )
        close_price = _finite_number(
            candle["close"],
            "close",
        )
    except KeyError as exc:
        raise StrategyError(
            f"Champ de bougie manquant : {exc}"
        ) from exc

    if epoch <= 0:
        raise StrategyError(
            "Horodatage de bougie invalide."
        )

    if low_price > high_price:
        raise StrategyError(
            "Le minimum dépasse le maximum de la bougie."
        )

    if not (
        low_price
        <= min(open_price, close_price)
        <= max(open_price, close_price)
        <= high_price
    ):
        raise StrategyError(
            "Les prix OHLC de la bougie sont incohérents."
        )

    return {
        "epoch": epoch,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
    }


def validate_candle_series(
    candles: List[Dict[str, Any]],
    minimum_count: int = MIN_CANDLE_COUNT,
) -> List[Dict[str, float]]:
    """Vérifie une série de bougies ordonnée et exploitable."""
    if not isinstance(candles, list):
        raise StrategyError(
            "La série de bougies doit être une liste."
        )

    if len(candles) < minimum_count:
        raise StrategyError(
            f"Historique insuffisant : {len(candles)} bougies "
            f"reçues, {minimum_count} nécessaires."
        )

    normalized = [
        _validate_candle(candle)
        for candle in candles
    ]

    normalized.sort(
        key=lambda candle: candle["epoch"]
    )

    previous_epoch = 0

    for candle in normalized:
        if candle["epoch"] <= previous_epoch:
            raise StrategyError(
                "Les horodatages des bougies doivent être uniques."
            )

        previous_epoch = int(candle["epoch"])

    return normalized


def calculate_true_range(
    current: Dict[str, float],
    previous_close: Optional[float],
) -> float:
    """Calcule le True Range d'une bougie."""
    high_price = float(current["high"])
    low_price = float(current["low"])

    if previous_close is None:
        return high_price - low_price

    return max(
        high_price - low_price,
        abs(high_price - previous_close),
        abs(low_price - previous_close),
    )


def calculate_atr(
    candles: List[Dict[str, Any]],
    period: int = ATR_PERIOD,
) -> float:
    """Calcule l'ATR à partir des dernières bougies."""
    if period < 1:
        raise StrategyError(
            "La période ATR doit être positive."
)
            normalized = validate_candle_series(
        candles,
        minimum_count=period + 1,
    )

    true_ranges = []

    for index, candle in enumerate(normalized):
        previous_close = None

        if index > 0:
            previous_close = normalized[index - 1]["close"]

        true_ranges.append(
            calculate_true_range(
                candle,
                previous_close,
            )
        )

    recent_ranges = true_ranges[-period:]

    if not recent_ranges:
        raise StrategyError(
            "Impossible de calculer l'ATR."
        )

    atr = sum(recent_ranges) / len(recent_ranges)

    if not math.isfinite(atr) or atr <= 0:
        raise StrategyError(
            "La valeur ATR calculée est invalide."
        )

    return atr


def candle_body_ratio(
    candle: Dict[str, Any],
) -> float:
    """Mesure la proportion du corps dans l'amplitude totale."""
    normalized = _validate_candle(candle)

    total_range = (
        normalized["high"] - normalized["low"]
    )

    if total_range <= 0:
        return 0.0

    body = abs(
        normalized["close"] - normalized["open"]
    )

    return body / total_range


def candle_direction(
    candle: Dict[str, Any],
) -> str:
    """Détermine la direction d'une bougie."""
    normalized = _validate_candle(candle)

    if normalized["close"] > normalized["open"]:
        return "BULLISH"

    if normalized["close"] < normalized["open"]:
        return "BEARISH"

    return "DOJI"


def is_bullish_candle(
    candle: Dict[str, Any],
) -> bool:
    return (
        candle_direction(candle) == "BULLISH"
    )


def is_bearish_candle(
    candle: Dict[str, Any],
) -> bool:
    return (
        candle_direction(candle) == "BEARISH"
    )


def candle_upper_wick(
    candle: Dict[str, Any],
) -> float:
    normalized = _validate_candle(candle)

    return (
        normalized["high"]
        - max(
            normalized["open"],
            normalized["close"],
        )
    )


def candle_lower_wick(
    candle: Dict[str, Any],
) -> float:
    normalized = _validate_candle(candle)

    return (
        min(
            normalized["open"],
            normalized["close"],
        )
        - normalized["low"]
    )


def is_doji(
    candle: Dict[str, Any],
    maximum_body_ratio: float = 0.10,
) -> bool:
    """Détecte un doji selon la proportion de son corps."""
    if not 0 <= maximum_body_ratio <= 1:
        raise StrategyError(
            "Le ratio maximal du doji doit être compris entre 0 et 1."
        )

    return (
        candle_body_ratio(candle)
        <= maximum_body_ratio
    )
def find_pivot_highs(
    candles: List[Dict[str, Any]],
    radius: int = 2,
) -> List[Dict[str, Any]]:
    """Identifie les sommets locaux servant aux résistances."""
    if radius < 1:
        raise StrategyError(
            "Le rayon des pivots doit être positif."
        )

    normalized = validate_candle_series(
        candles,
        minimum_count=(radius * 2) + 1,
    )

    pivots = []

    for index in range(
        radius,
        len(normalized) - radius,
    ):
        current = normalized[index]
        current_high = current["high"]

        left_highs = [
            candle["high"]
            for candle in normalized[
                index - radius:index
            ]
        ]

        right_highs = [
            candle["high"]
            for candle in normalized[
                index + 1:index + radius + 1
            ]
        ]

        if (
            current_high >= max(left_highs)
            and current_high >= max(right_highs)
            and (
                current_high > max(left_highs)
                or current_high > max(right_highs)
            )
        ):
            pivots.append(
                {
                    "index": index,
                    "epoch": current["epoch"],
                    "price": current_high,
                    "type": "HIGH",
                }
            )

    return pivots


def find_pivot_lows(
    candles: List[Dict[str, Any]],
    radius: int = 2,
) -> List[Dict[str, Any]]:
    """Identifie les creux locaux servant aux supports."""
    if radius < 1:
        raise StrategyError(
            "Le rayon des pivots doit être positif."
        )

    normalized = validate_candle_series(
        candles,
                minimum_count=(radius * 2) + 1,
    )

    pivots = []

    for index in range(
        radius,
        len(normalized) - radius,
    ):
        current = normalized[index]
        current_low = current["low"]

        left_lows = [
            candle["low"]
            for candle in normalized[
                index - radius:index
            ]
        ]

        right_lows = [
            candle["low"]
            for candle in normalized[
                index + 1:index + radius + 1
            ]
        ]

        if (
            current_low <= min(left_lows)
            and current_low <= min(right_lows)
            and (
                current_low < min(left_lows)
                or current_low < min(right_lows)
            )
        ):
            pivots.append(
                {
                    "index": index,
                    "epoch": current["epoch"],
                    "price": current_low,
                    "type": "LOW",
                }
            )

    return pivots


def cluster_price_levels(
    pivots: List[Dict[str, Any]],
    tolerance: float,
    level_type: str,
) -> List[Dict[str, Any]]:
    """Regroupe les pivots proches en zones techniques."""
    tolerance = _finite_number(
        tolerance,
        "tolerance",
    )

    if tolerance < 0:
        raise StrategyError(
            "La tolérance ne peut pas être négative."
        )

    if level_type not in ("SUPPORT", "RESISTANCE"):
        raise StrategyError(
            "Type de niveau technique invalide."
        )

    valid_pivots = []

    for pivot in pivots:
        if not isinstance(pivot, dict):
            continue

        try:
            price = _finite_number(
                pivot["price"],
                "pivot.price",
            )

            index = int(pivot["index"])
            epoch = int(pivot["epoch"])

        except (KeyError, TypeError, ValueError, StrategyError):
            continue

        if price <= 0 or index < 0 or epoch <= 0:
            continue

        valid_pivots.append(
            {
                "price": price,
                "index": index,
                "epoch": epoch,
            }
        )

    valid_pivots.sort(
        key=lambda pivot: pivot["price"]
    )

    clusters = []

    for pivot in valid_pivots:
        matching_cluster = None

        for cluster in clusters:
            center = (
                sum(cluster["prices"])
                / len(cluster["prices"])
            )

            if abs(pivot["price"] - center) <= tolerance:
                matching_cluster = cluster
                break

        if matching_cluster is None:
            clusters.append(
                {
                    "prices": [pivot["price"]],
                    "indices": [pivot["index"]],
                    "epochs": [pivot["epoch"]],
                }
            )
        else:
            matching_cluster["prices"].append(
                pivot["price"]
            )

            matching_cluster["indices"].append(
                pivot["index"]
            )

            matching_cluster["epochs"].append(
                pivot["epoch"]
            )

    levels = []

    for cluster in clusters:
        prices = cluster["prices"]

        lower = min(prices)
        upper = max(prices)
        center = sum(prices) / len(prices)

        levels.append(
            {
                "type": level_type,
                "lower": lower,
                "upper": upper,
                "price": center,
                "touches": len(prices),
                "indices": sorted(cluster["indices"]),
                "epochs": sorted(cluster["epochs"]),
                "strength": len(prices),
            }
        )

    levels.sort(
        key=lambda level: level["price"]
    )

    return levels


def find_supports(
    candles: List[Dict[str, Any]],
    atr: Optional[float] = None,
    radius: int = 2,
) -> List[Dict[str, Any]]:
    """Détecte les zones de support à partir des creux."""
    normalized = validate_candle_series(
        candles,
        minimum_count=(radius * 2) + 1,
    )

    if atr is None:
        atr = calculate_atr(normalized)

    atr = _finite_number(atr, "ATR")

    if atr <= 0:
        raise StrategyError(
            "L'ATR doit être positif pour détecter les supports."
        )

    pivots = find_pivot_lows(
        normalized,
        radius=radius,
    )

    return cluster_price_levels(
        pivots=pivots,
        tolerance=atr * ZONE_ATR_TOLERANCE,
        level_type="SUPPORT",
    )


def find_resistances(
    candles: List[Dict[str, Any]],
        atr: Optional[float] = None,
    radius: int = 2,
) -> List[Dict[str, Any]]:
    """Détecte les zones de résistance à partir des sommets."""
    normalized = validate_candle_series(
        candles,
        minimum_count=(radius * 2) + 1,
    )

    if atr is None:
        atr = calculate_atr(normalized)

    atr = _finite_number(atr, "ATR")

    if atr <= 0:
        raise StrategyError(
            "L'ATR doit être positif pour détecter les résistances."
        )

    pivots = find_pivot_highs(
        normalized,
        radius=radius,
    )

    return cluster_price_levels(
        pivots=pivots,
        tolerance=atr * ZONE_ATR_TOLERANCE,
        level_type="RESISTANCE",
    )


def level_distance(
    price: float,
    level: Dict[str, Any],
) -> float:
    """Distance entre un prix et une zone de support/résistance."""
    price = _finite_number(price, "price")

    lower = _finite_number(
        level["lower"],
        "level.lower",
    )

    upper = _finite_number(
        level["upper"],
        "level.upper",
    )

    if lower > upper:
        raise StrategyError(
            "Les limites de la zone sont inversées."
        )

    if lower <= price <= upper:
        return 0.0

    if price < lower:
        return lower - price

    return price - upper


def find_nearest_level(
    price: float,
    levels: List[Dict[str, Any]],
    level_type: Optional[str] = None,
    direction: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Renvoie le niveau le plus proche respectant les filtres."""
    price = _finite_number(price, "price")

    candidates = []

    for level in levels:
        if not isinstance(level, dict):
            continue

        if (
            level_type is not None
            and level.get("type") != level_type
        ):
            continue

        level_price = _finite_number(
            level.get("price"),
            "level.price",
        )

        if direction == "ABOVE" and level_price <= price:
            continue

        if direction == "BELOW" and level_price >= price:
            continue

        if direction not in (
            None,
            "ABOVE",
            "BELOW",
        ):
            raise StrategyError(
                "Direction de recherche de niveau invalide."
            )

        candidates.append(level)

    if not candidates:
        return None

    return min(
        candidates,
        key=lambda level: level_distance(
            price,
            level,
        ),
    )


def filter_levels_by_strength(
    levels: List[Dict[str, Any]],
    minimum_touches: int = 2,
) -> List[Dict[str, Any]]:
    """Écarte les zones trop peu testées."""
    if minimum_touches < 1:
        raise StrategyError(
            "Le nombre minimal de touches doit être positif."
        )

    return [
        level
        for level in levels
        if int(level.get("touches", 0))
        >= minimum_touches
          ]
def calculate_linear_regression(
    points: List[Tuple[float, float]],
) -> Tuple[float, float]:
    """Calcule la pente et l'ordonnée à l'origine d'une droite."""
    if len(points) < 2:
        raise StrategyError(
            "Au moins deux points sont nécessaires."
        )

    x_values = [
        _finite_number(point[0], "point.x")
        for point in points
    ]

    y_values = [
        _finite_number(point[1], "point.y")
        for point in points
    ]

    mean_x = sum(x_values) / len(x_values)
    mean_y = sum(y_values) / len(y_values)

    denominator = sum(
        (x - mean_x) ** 2
        for x in x_values
    )

    if denominator == 0:
        raise StrategyError(
            "Impossible de calculer la pente."
        )

    numerator = sum(
        (x - mean_x) * (y - mean_y)
        for x, y in zip(x_values, y_values)
    )

    slope = numerator / denominator
    intercept = mean_y - slope * mean_x

    if not (
        math.isfinite(slope)
        and math.isfinite(intercept)
    ):
        raise StrategyError(
            "La droite calculée est invalide."
        )

    return slope, intercept


def line_value_at(
    slope: float,
    intercept: float,
    index: float,
) -> float:
    """Calcule la valeur d'une droite à un index donné."""
    slope = _finite_number(slope, "slope")
    intercept = _finite_number(
        intercept,
        "intercept",
    )
    index = _finite_number(index, "index")

    value = slope * index + intercept

    if not math.isfinite(value):
                raise StrategyError(
            "Valeur de trendline non finie."
        )

    return value


def count_trendline_touches(
    candles: List[Dict[str, Any]],
    pivots: List[Dict[str, Any]],
    slope: float,
    intercept: float,
    tolerance: float,
) -> List[Dict[str, Any]]:
    """Compte les contacts entre pivots et une trendline."""
    normalized = validate_candle_series(
        candles,
        minimum_count=3,
    )

    tolerance = _finite_number(
        tolerance,
        "tolerance",
    )

    if tolerance < 0:
        raise StrategyError(
            "La tolérance ne peut pas être négative."
        )

    touches = []

    for pivot in pivots:
        try:
            index = int(pivot["index"])
            price = _finite_number(
                pivot["price"],
                "pivot.price",
            )
        except (KeyError, TypeError, ValueError, StrategyError):
            continue

        if index < 0 or index >= len(normalized):
            continue

        expected_price = line_value_at(
            slope,
            intercept,
            index,
        )

        distance = abs(
            price - expected_price
        )

        if distance <= tolerance:
            touches.append(
                {
                    "index": index,
                    "epoch": int(
                        normalized[index]["epoch"]
                    ),
                    "price": price,
                    "line_price": expected_price,
                    "distance": distance,
                }
            )

    return touches


def detect_trendlines(
    candles: List[Dict[str, Any]],
    atr: Optional[float] = None,
    radius: int = 2,
    minimum_touches: int = MIN_TRENDLINE_TOUCHES,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Détecte des trendlines haussières et baissières.

    Les lignes ne sont retenues que si elles présentent
    suffisamment de contacts avec des pivots.
    """
    normalized = validate_candle_series(
        candles,
        minimum_count=max(
            MIN_CANDLE_COUNT,
            (radius * 2) + 1,
        ),
    )

    if minimum_touches < 3:
        raise StrategyError(
            "Une trendline doit avoir au moins trois touches."
        )

    if atr is None:
        atr = calculate_atr(normalized)

    atr = _finite_number(
        atr,
        "ATR",
    )

    if atr <= 0:
        raise StrategyError(
            "L'ATR doit être positif."
        )

    tolerance = atr * ZONE_ATR_TOLERANCE

    low_pivots = find_pivot_lows(
        normalized,
        radius=radius,
    )

    high_pivots = find_pivot_highs(
        normalized,
        radius=radius,
    )

    result = {
        "uptrend": [],
        "downtrend": [],
    }

    def build_candidates(
        pivots: List[Dict[str, Any]],
        trend_type: str,
    ) -> List[Dict[str, Any]]:
        candidates = []

        if len(pivots) < minimum_touches:
            return candidates

        pivot_count = len(pivots)

        for start in range(pivot_count - 1):
            for end in range(
                start + 1,
                pivot_count,
            ):
                first = pivots[start]
                last = pivots[end]

                if last["index"] <= first["index"]:
                    continue

                slope = (
                    last["price"] - first["price"]
                ) / (
                    last["index"] - first["index"]
                )

                if trend_type == "UPTREND" and slope <= 0:
                    continue

                if trend_type == "DOWNTREND" and slope >= 0:
                    continue

                intercept = (
                    first["price"]
                    - slope * first["index"]
                )

                touches = count_trendline_touches(
                    normalized,
                    pivots,
                    slope,
                    intercept,
                    tolerance,
                )

                if len(touches) < minimum_touches:
                    continue

                indices = [
                    touch["index"]
                    for touch in touches
                ]

                if len(set(indices)) < minimum_touches:
                    continue

                current_index = len(normalized) - 1

                current_line_price = line_value_at(
                    slope,
                    intercept,
                    current_index,
                )

                candidate = {
                    "type": trend_type,
                    "slope": slope,
                    "intercept": intercept,
                    "start_index": min(indices),
                    "end_index": max(indices),
                    "touches": len(touches),
                    "touch_points": touches,
                                        "current_value": current_line_price,
                    "tolerance": tolerance,
                }

                candidates.append(candidate)

        candidates.sort(
            key=lambda candidate: (
                candidate["touches"],
                candidate["end_index"],
                -abs(candidate["slope"]),
            ),
            reverse=True,
        )

        unique = []
        signatures = set()

        for candidate in candidates:
            signature = (
                round(candidate["slope"], 8),
                round(candidate["intercept"], 6),
            )

            if signature in signatures:
                continue

            signatures.add(signature)
            unique.append(candidate)

            if len(unique) >= 10:
                break

        return unique

    result["uptrend"] = build_candidates(
        low_pivots,
        "UPTREND",
    )

    result["downtrend"] = build_candidates(
        high_pivots,
        "DOWNTREND",
    )

    LOGGER.debug(
        "Trendlines détectées : haussières=%s, baissières=%s",
        len(result["uptrend"]),
        len(result["downtrend"]),
    )

    return result


def get_nearest_trendline(
    trendlines: Dict[str, List[Dict[str, Any]]],
    current_price: float,
    trend_type: str,
) -> Optional[Dict[str, Any]]:
    """Retourne la trendline valide la plus proche du prix."""
    current_price = _finite_number(
        current_price,
        "current_price",
    )

    if trend_type == "UPTREND":
        key = "uptrend"
    elif trend_type == "DOWNTREND":
        key = "downtrend"
    else:
        raise StrategyError(
            "Type de trendline inconnu."
        )

    candidates = trendlines.get(key, [])

    if not candidates:
        return None

    valid_candidates = [
        line
        for line in candidates
        if int(line.get("touches", 0))
        >= MIN_TRENDLINE_TOUCHES
    ]

    if not valid_candidates:
        return None

    return min(
        valid_candidates,
        key=lambda line: abs(
            current_price - float(
                line["current_value"]
            )
        ),
    )


def trendline_distance(
    current_price: float,
    trendline: Dict[str, Any],
) -> float:
    """Mesure la distance absolue entre le prix et une trendline."""
    current_price = _finite_number(
        current_price,
        "current_price",
    )

    line_price = _finite_number(
        trendline["current_value"],
        "trendline.current_value",
    )

    return abs(
        current_price - line_price
    )


def is_price_near_trendline(
    current_price: float,
    trendline: Dict[str, Any],
    atr: float,
    maximum_distance_atr: float = MAX_PRICE_DISTANCE_ATR,
) -> bool:
    """Vérifie si le prix approche suffisamment une trendline."""
    current_price = _finite_number(
        current_price,
        "current_price",
    )

    atr = _finite_number(
        atr,
        "ATR",
    )

    maximum_distance_atr = _finite_number(
        maximum_distance_atr,
        "maximum_distance_atr",
    )

    if atr <= 0 or maximum_distance_atr < 0:
        return False

    if int(
        trendline.get("touches", 0)
    ) < MIN_TRENDLINE_TOUCHES:
        return False

    distance = trendline_distance(
        current_price,
        trendline,
    )

    return distance <= (
        atr * maximum_distance_atr
      )
def determine_market_trend(
    candles: List[Dict[str, Any]],
    short_period: int = 20,
    long_period: int = 50,
) -> Dict[str, Any]:
    """Détermine une tendance simple à partir des moyennes mobiles."""
    normalized = validate_candle_series(
        candles,
        minimum_count=long_period + 1,
    )

    if short_period < 2 or long_period <= short_period:
        raise StrategyError(
            "Les périodes des moyennes mobiles sont invalides."
        )

    closes = [
        candle["close"]
        for candle in normalized
    ]

    short_average = sum(
        closes[-short_period:]
    ) / short_period

    long_average = sum(
        closes[-long_period:]
    ) / long_period

    recent_close = closes[-1]

    if short_average > long_average and recent_close > short_average:
        direction = "BULLISH"

    elif short_average < long_average and recent_close < short_average:
        direction = "BEARISH"

    else:
        direction = "NEUTRAL"

    return {
        "direction": direction,
        "short_average": short_average,
                "long_average": long_average,
        "last_close": recent_close,
    }


def detect_market_structure(
    candles: List[Dict[str, Any]],
    radius: int = 2,
) -> Dict[str, Any]:
    """Analyse les derniers sommets et creux significatifs."""
    normalized = validate_candle_series(
        candles,
        minimum_count=max(
            MIN_CANDLE_COUNT,
            (radius * 2) + 1,
        ),
    )

    highs = find_pivot_highs(
        normalized,
        radius=radius,
    )

    lows = find_pivot_lows(
        normalized,
        radius=radius,
    )

    last_two_highs = highs[-2:]
    last_two_lows = lows[-2:]

    higher_high = False
    lower_high = False
    higher_low = False
    lower_low = False

    if len(last_two_highs) == 2:
        higher_high = (
            last_two_highs[-1]["price"]
            > last_two_highs[-2]["price"]
        )

        lower_high = (
            last_two_highs[-1]["price"]
            < last_two_highs[-2]["price"]
        )

    if len(last_two_lows) == 2:
        higher_low = (
            last_two_lows[-1]["price"]
            > last_two_lows[-2]["price"]
        )

        lower_low = (
            last_two_lows[-1]["price"]
            < last_two_lows[-2]["price"]
        )

    if higher_high and higher_low:
        direction = "BULLISH"

    elif lower_high and lower_low:
        direction = "BEARISH"

    else:
        direction = "RANGE"

    return {
        "direction": direction,
        "higher_high": higher_high,
        "lower_high": lower_high,
        "higher_low": higher_low,
        "lower_low": lower_low,
        "pivot_highs": highs,
        "pivot_lows": lows,
    }


def find_nearest_support(
    current_price: float,
    supports: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Trouve le support situé au niveau ou sous le prix."""
    return find_nearest_level(
        price=current_price,
        levels=supports,
        level_type="SUPPORT",
        direction="BELOW",
    )


def find_nearest_resistance(
    current_price: float,
    resistances: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Trouve la résistance située au niveau ou au-dessus du prix."""
    return find_nearest_level(
        price=current_price,
        levels=resistances,
        level_type="RESISTANCE",
        direction="ABOVE",
    )


def calculate_confluence_score(
    current_price: float,
    atr: float,
    level: Dict[str, Any],
    trendline: Optional[Dict[str, Any]],
    expected_direction: str,
) -> Dict[str, Any]:
    """
    Évalue la proximité entre une zone technique et une trendline.

    Le score exprime une confluence géométrique, pas une probabilité
    de réussite du trade.
    """
    current_price = _finite_number(
        current_price,
        "current_price",
    )

    atr = _finite_number(
        atr,
        "ATR",
    )

    if atr <= 0:
        raise StrategyError(
            "L'ATR doit être positif."
        )

    if expected_direction not in ("BUY", "SELL"):
        raise StrategyError(
            "La direction attendue doit être BUY ou SELL."
        )

    level_price = _finite_number(
        level["price"],
        "level.price",
    )

    level_type = level.get("type")

    if expected_direction == "BUY" and level_type != "SUPPORT":
        return {
            "score": 0,
            "confluence": False,
            "reasons": [
                "La zone n'est pas un support."
            ],
        }

    if expected_direction == "SELL" and level_type != "RESISTANCE":
        return {
            "score": 0,
            "confluence": False,
            "reasons": [
                "La zone n'est pas une résistance."
            ],
        }

    reasons = []
    score = 0

    distance_to_level = level_distance(
        current_price,
        level,
    )

    if distance_to_level <= atr * MAX_PRICE_DISTANCE_ATR:
        score += 1
        reasons.append(
            "Prix proche de la zone technique."
        )

    touches = int(
        level.get("touches", 0)
    )

    if touches >= 3:
        score += 1
        reasons.append(
            "Zone testée au moins trois fois."
        )

    trendline_distance_value = None

    if trendline is not None:
        trendline_distance_value = trendline_distance(
            current_price,
            trendline,
        )

        if (
            trendline.get("type")
            == (
                "UPTREND"
                if expected_direction == "BUY"
                else "DOWNTREND"
                            )
            and touches >= 1
        ):
            if trendline_distance_value <= atr * MAX_PRICE_DISTANCE_ATR:
                score += 1
                reasons.append(
                    "Trendline compatible avec la direction."
                )

            line_price = _finite_number(
                trendline["current_value"],
                "trendline.current_value",
            )

            level_line_gap = abs(
                line_price - level_price
            )

            if level_line_gap <= atr * ZONE_ATR_TOLERANCE:
                score += 1
                reasons.append(
                    "Trendline proche de la zone technique."
                )

    return {
        "score": score,
        "confluence": score >= 3,
        "reasons": reasons,
        "distance_to_level": distance_to_level,
        "trendline_distance": trendline_distance_value,
        "level_price": level_price,
    }


def build_anticipatory_zone(
    level: Dict[str, Any],
    trendline: Optional[Dict[str, Any]],
    atr: float,
    direction: str,
) -> Dict[str, Any]:
    """Construit une zone de surveillance anticipée."""
    atr = _finite_number(
        atr,
        "ATR",
    )

    if atr <= 0:
        raise StrategyError(
            "L'ATR doit être positif."
        )

    if direction not in ("BUY", "SELL"):
        raise StrategyError(
            "Direction invalide pour la zone anticipée."
        )

    lower = _finite_number(
        level["lower"],
        "level.lower",
    )

    upper = _finite_number(
        level["upper"],
        "level.upper",
    )

    if lower > upper:
        raise StrategyError(
            "Les limites de la zone sont inversées."
        )

    level_price = _finite_number(
        level["price"],
        "level.price",
    )

    zone_lower = lower
    zone_upper = upper

    if trendline is not None:
        line_price = _finite_number(
            trendline["current_value"],
            "trendline.current_value",
        )

        line_lower = (
            line_price - atr * ZONE_ATR_TOLERANCE
        )

        line_upper = (
            line_price + atr * ZONE_ATR_TOLERANCE
        )

        intersection_lower = max(
            zone_lower,
            line_lower,
        )

        intersection_upper = min(
            zone_upper,
            line_upper,
        )

        if intersection_lower <= intersection_upper:
            zone_lower = intersection_lower
            zone_upper = intersection_upper

    approach_buffer = atr * ZONE_ATR_TOLERANCE

    if direction == "BUY":
        entry_min = zone_lower - approach_buffer
        entry_max = zone_upper + approach_buffer
    else:
        entry_min = zone_lower - approach_buffer
        entry_max = zone_upper + approach_buffer

    return {
        "direction": direction,
        "level_type": level.get("type"),
        "level_price": level_price,
        "zone_lower": zone_lower,
        "zone_upper": zone_upper,
        "entry_zone_lower": entry_min,
        "entry_zone_upper": entry_max,
        "atr": atr,
        "trendline_value": (
            trendline.get("current_value")
            if trendline is not None
            else None
        ),
        "anticipatory": True,
    }


def is_price_approaching_zone(
    current_price: float,
    zone: Dict[str, Any],
    atr: float,
    maximum_distance_atr: float = MAX_PRICE_DISTANCE_ATR,
) -> bool:
    """Indique si le prix est dans la zone ou s'en approche."""
    current_price = _finite_number(
        current_price,
        "current_price",
    )

    atr = _finite_number(
        atr,
        "ATR",
    )

    maximum_distance_atr = _finite_number(
        maximum_distance_atr,
        "maximum_distance_atr",
    )

    if atr <= 0 or maximum_distance_atr < 0:
        return False

    lower = _finite_number(
        zone["entry_zone_lower"],
        "entry_zone_lower",
    )

    upper = _finite_number(
        zone["entry_zone_upper"],
        "entry_zone_upper",
    )

    if lower > upper:
        return False

    if lower <= current_price <= upper:
        return True

    if current_price < lower:
        return (lower - current_price) <= (
            atr * maximum_distance_atr
        )

    return (current_price - upper) <= (
        atr * maximum_distance_atr
  )
def calculate_stop_loss(
    direction: str,
    entry_price: float,
    zone: Dict[str, Any],
    atr: float,
    atr_buffer: float = ATR_STOP_BUFFER,
) -> float:
    """Place le Stop Loss au-delà de la zone technique."""
    entry_price = _finite_number(
        entry_price,
        "entry_price",
    )
    atr = _finite_number(atr, "ATR")
    atr_buffer = _finite_number(
        atr_buffer,
        "atr_buffer",
    )
        if entry_price <= 0 or atr <= 0:
        raise StrategyError(
            "Le prix d'entrée et l'ATR doivent être positifs."
        )

    if atr_buffer < 0:
        raise StrategyError(
            "La marge ATR ne peut pas être négative."
        )

    zone_lower = _finite_number(
        zone["zone_lower"],
        "zone_lower",
    )
    zone_upper = _finite_number(
        zone["zone_upper"],
        "zone_upper",
    )

    if zone_lower > zone_upper:
        raise StrategyError(
            "Les limites de la zone sont inversées."
        )

    buffer = atr * atr_buffer

    if direction == "BUY":
        stop_loss = zone_lower - buffer

        if stop_loss >= entry_price:
            raise StrategyError(
                "Le Stop Loss BUY doit être sous l'entrée."
            )

    elif direction == "SELL":
        stop_loss = zone_upper + buffer

        if stop_loss <= entry_price:
            raise StrategyError(
                "Le Stop Loss SELL doit être au-dessus de l'entrée."
            )

    else:
        raise StrategyError(
            "Direction invalide pour le Stop Loss."
        )

    if stop_loss <= 0:
        raise StrategyError(
            "Le Stop Loss calculé est invalide."
        )

    return stop_loss


def calculate_take_profit(
    direction: str,
    entry_price: float,
    supports: List[Dict[str, Any]],
    resistances: List[Dict[str, Any]],
    minimum_rr: float = MIN_RISK_REWARD,
    stop_loss: Optional[float] = None,
) -> float:
    """Recherche un objectif technique respectant le RR minimal."""
    entry_price = _finite_number(
        entry_price,
        "entry_price",
    )
    minimum_rr = _finite_number(
        minimum_rr,
        "minimum_rr",
    )
    if entry_price <= 0 or atr <= 0:
        raise StrategyError(
            "Le prix d'entrée et l'ATR doivent être positifs."
        )

    if atr_buffer < 0:
        raise StrategyError(
            "La marge ATR ne peut pas être négative."
        )

    zone_lower = _finite_number(
        zone["zone_lower"],
        "zone_lower",
    )
    zone_upper = _finite_number(
        zone["zone_upper"],
        "zone_upper",
    )

    if zone_lower > zone_upper:
        raise StrategyError(
            "Les limites de la zone sont inversées."
        )

    buffer = atr * atr_buffer

    if direction == "BUY":
        stop_loss = zone_lower - buffer

        if stop_loss >= entry_price:
            raise StrategyError(
                "Le Stop Loss BUY doit être sous l'entrée."
            )

    elif direction == "SELL":
        stop_loss = zone_upper + buffer

        if stop_loss <= entry_price:
            raise StrategyError(
                "Le Stop Loss SELL doit être au-dessus de l'entrée."
            )

    else:
        raise StrategyError(
            "Direction invalide pour le Stop Loss."
        )

    if stop_loss <= 0:
        raise StrategyError(
            "Le Stop Loss calculé est invalide."
        )

    return stop_loss


def calculate_take_profit(
    direction: str,
    entry_price: float,
    supports: List[Dict[str, Any]],
    resistances: List[Dict[str, Any]],
    minimum_rr: float = MIN_RISK_REWARD,
    stop_loss: Optional[float] = None,
) -> float:
    """Recherche un objectif technique respectant le RR minimal."""
    entry_price = _finite_number(
        entry_price,
        "entry_price",
    )
    minimum_rr = _finite_number(
        minimum_rr,
        "minimum_rr",
    )

    if entry_price <= 0:
        raise StrategyError(
            "Le prix d'entrée doit être positif."
        )

    if minimum_rr <= 0:
        raise StrategyError(
            "Le ratio risque/rendement doit être positif."
        )

    if stop_loss is None:
        raise StrategyError(
            "Le Stop Loss est obligatoire pour calculer le TP."
        )

    stop_loss = _finite_number(
        stop_loss,
        "stop_loss",
    )

    if direction == "BUY":
        if stop_loss >= entry_price:
            raise StrategyError(
                "Pour un BUY, le SL doit être sous l'entrée."
            )

        risk = entry_price - stop_loss
        candidates = [
            level
            for level in resistances
            if float(level.get("price", 0)) > entry_price
        ]

        candidates.sort(
            key=lambda level: float(level["price"])
        )

        for level in candidates:
            target = float(level["price"])

            if target <= entry_price:
                continue

            reward = target - entry_price

            if reward / risk >= minimum_rr:
                return target

        return entry_price + risk * minimum_rr

    if direction == "SELL":
        if stop_loss <= entry_price:
            raise StrategyError(
                "Pour un SELL, le SL doit être au-dessus de l'entrée."
            )

        risk = stop_loss - entry_price
        candidates = [
            level
            for level in supports
            if float(level.get("price", 0)) < entry_price
        ]

        candidates.sort(
            key=lambda level: float(level["price"]),
            reverse=True,
        )

        for level in candidates:
            target = float(level["price"])

            if target >= entry_price:
                continue

            reward = entry_price - target

            if reward / risk >= minimum_rr:
                return target

        return max(
            entry_price - risk * minimum_rr,
            entry_price * 0.000001,
        )

    raise StrategyError(
        "Direction invalide pour le Take Profit."
    )


def calculate_risk_reward(
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
) -> float:
    """Calcule le ratio entre le gain potentiel et le risque."""
    entry_price = _finite_number(
        entry_price,
        "entry_price",
    )
    stop_loss = _finite_number(
        stop_loss,
        "stop_loss",
    )
    take_profit = _finite_number(
        take_profit,
        "take_profit",
    )

    if direction == "BUY":
        risk = entry_price - stop_loss
        reward = take_profit - entry_price

    elif direction == "SELL":
        risk = stop_loss - entry_price
        reward = entry_price - take_profit

    else:
        raise StrategyError(
            "Direction invalide pour le calcul du RR."
        )

    if risk <= 0:
        raise StrategyError(
            "Le risque doit être strictement positif."
            )
            if reward <= 0:
        raise StrategyError(
            "Le gain potentiel doit être strictement positif."
        )

    ratio = reward / risk

    if not math.isfinite(ratio):
        raise StrategyError(
            "Le ratio risque/rendement est invalide."
        )

    return ratio


def validate_trade_levels(
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    minimum_rr: float = MIN_RISK_REWARD,
) -> Dict[str, Any]:
    """Vérifie la cohérence des niveaux avant de produire un signal."""
    entry_price = _finite_number(
        entry_price,
        "entry_price",
    )
    stop_loss = _finite_number(
        stop_loss
  )
    take_profit = _finite_number(
        take_profit,
        "take_profit",
    )

    if direction == "BUY":
        risk = entry_price - stop_loss
        reward = take_profit - entry_price

    elif direction == "SELL":
        risk = stop_loss - entry_price
        reward = entry_price - take_profit

    else:
        raise StrategyError(
            "Direction invalide pour le calcul du RR."
        )

    if risk <= 0:
        raise StrategyError(
            "Le risque doit être strictement positif."
        )

    if reward <= 0:
        raise StrategyError(
            "Le gain potentiel doit être strictement positif."
        )

    ratio = reward / risk

    if not math.isfinite(ratio):
        raise StrategyError(
            "Le ratio risque/rendement est invalide."
        )

    return ratio


def validate_trade_levels(
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    minimum_rr: float = MIN_RISK_REWARD,
) -> Dict[str, Any]:
    """Vérifie la cohérence des niveaux avant de produire un signal."""
    entry_price = _finite_number(
        entry_price,
        "entry_price",
    )
    stop_loss = _finite_number(
        stop_loss,
        "stop_loss",
    )
    take_profit = _finite_number(
        take_profit,
        "take_profit",
    )
    minimum_rr = _finite_number(
        minimum_rr,
        "minimum_rr",
    )

    if min(entry_price, stop_loss, take_profit) <= 0:
        raise StrategyError(
            "Les niveaux de prix doivent être positifs."
        )

    ratio = calculate_risk_reward(
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )

    if ratio < minimum_rr:
        raise StrategyError(
            f"RR insuffisant : {ratio:.2f}, "
            f"minimum requis : {minimum_rr:.2f}."
        )

    return {
        "valid": True,
        "direction": direction,
        "entry": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": ratio,
        "minimum_rr": minimum_rr,
    }


def calculate_entry_price(
    direction: str,
    zone: Dict[str, Any],
    current_price: float,
) -> float:
    """Détermine un prix indicatif dans la zone d'entrée."""
    current_price = _finite_number(
        current_price,
        "current_price",
    )

    if current_price <= 0:
        raise StrategyError(
            "Le prix actuel doit être positif."
        )

    lower = _finite_number(
        zone["entry_zone_lower"],
        "entry_zone_lower",
    )
    upper = _finite_number(
        zone["entry_zone_upper"],
        "entry_zone_upper",
    )

    if lower > upper:
        raise StrategyError(
            "Les limites de la zone d'entrée sont inversées."
        )

    if direction not in ("BUY", "SELL"):
        raise StrategyError(
            "Direction invalide pour l'entrée."
        )

    if lower <= current_price <= upper:
        return current_price

    if current_price < lower:
        return lower

    return upper


def check_minimum_rr(
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    minimum_rr: float = MIN_RISK_REWARD,
) -> bool:
    """Retourne True uniquement si le RR minimal est respecté."""
    try:
        result = validate_trade_levels(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            minimum_rr=minimum_rr,
        )

        return bool(result["valid"])

    except (StrategyError, TypeError, ValueError):
        return False
def analyze_d1_direction(
    d1_candles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Détermine la direction générale à partir du Daily."""
    candles = validate_candle_series(
        d1_candles,
        minimum_count=TIMEFRAME_REQUIREMENTS["D1"],
    )

    trend = determine_market_trend(candles)
    structure = detect_market_structure(candles)
    if reward <= 0:
        raise StrategyError(
            "Le gain potentiel doit être strictement positif."
        )

    ratio = reward / risk

    if not math.isfinite(ratio):
        raise StrategyError(
            "Le ratio risque/rendement est invalide."
        )

    return ratio


def validate_trade_levels(
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    minimum_rr: float = MIN_RISK_REWARD,
) -> Dict[str, Any]:
    """Vérifie la cohérence des niveaux avant de produire un signal."""
    entry_price = _finite_number(
        entry_price,
        "entry_price",
    )
    stop_loss = _finite_number(
        stop_loss
  )
    take_profit = _finite_number(
        take_profit,
        "take_profit",
    )

    if direction == "BUY":
        risk = entry_price - stop_loss
        reward = take_profit - entry_price

    elif direction == "SELL":
        risk = stop_loss - entry_price
        reward = entry_price - take_profit

    else:
        raise StrategyError(
            "Direction invalide pour le calcul du RR."
        )

    if risk <= 0:
        raise StrategyError(
            "Le risque doit être strictement positif."
        )

    if reward <= 0:
        raise StrategyError(
            "Le gain potentiel doit être strictement positif."
        )

    ratio = reward / risk

    if not math.isfinite(ratio):
        raise StrategyError(
            "Le ratio risque/rendement est invalide."
        )

    return ratio


def validate_trade_levels(
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    minimum_rr: float = MIN_RISK_REWARD,
) -> Dict[str, Any]:
    """Vérifie la cohérence des niveaux avant de produire un signal."""
    entry_price = _finite_number(
        entry_price,
        "entry_price",
    )
    stop_loss = _finite_number(
        stop_loss,
        "stop_loss",
    )
    take_profit = _finite_number(
        take_profit,
        "take_profit",
    )
    minimum_rr = _finite_number(
        minimum_rr,
        "minimum_rr",
    )

    if min(entry_price, stop_loss, take_profit) <= 0:
        raise StrategyError(
            "Les niveaux de prix doivent être positifs."
        )

    ratio = calculate_risk_reward(
        direction=direction,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )

    if ratio < minimum_rr:
        raise StrategyError(
            f"RR insuffisant : {ratio:.2f}, "
            f"minimum requis : {minimum_rr:.2f}."
        )

    return {
        "valid": True,
        "direction": direction,
        "entry": entry_price,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_reward": ratio,
        "minimum_rr": minimum_rr,
    }


def calculate_entry_price(
    direction: str,
    zone: Dict[str, Any],
    current_price: float,
) -> float:
    """Détermine un prix indicatif dans la zone d'entrée."""
    current_price = _finite_number(
        current_price,
        "current_price",
    )

    if current_price <= 0:
        raise StrategyError(
            "Le prix actuel doit être positif."
        )

    lower = _finite_number(
        zone["entry_zone_lower"],
        "entry_zone_lower",
    )
    upper = _finite_number(
        zone["entry_zone_upper"],
        "entry_zone_upper",
    )

    if lower > upper:
        raise StrategyError(
            "Les limites de la zone d'entrée sont inversées."
        )

    if direction not in ("BUY", "SELL"):
        raise StrategyError(
            "Direction invalide pour l'entrée."
        )

    if lower <= current_price <= upper:
        return current_price

    if current_price < lower:
        return lower

    return upper


def check_minimum_rr(
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    minimum_rr: float = MIN_RISK_REWARD,
) -> bool:
    """Retourne True uniquement si le RR minimal est respecté."""
    try:
        result = validate_trade_levels(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            minimum_rr=minimum_rr,
        )

        return bool(result["valid"])

    except (StrategyError, TypeError, ValueError):
        return False
def analyze_d1_direction(
    d1_candles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Détermine la direction générale à partir du Daily."""
    candles = validate_candle_series(
        d1_candles,
        minimum_count=TIMEFRAME_REQUIREMENTS["D1"],
    )

    trend = determine_market_trend(candles)
    structure = detect_market_structure(candles)
    if (
        trend["direction"] == "BULLISH"
        and structure["direction"] == "BULLISH"
    ):
        direction = "BULLISH"
    elif (
        trend["direction"] == "BEARISH"
        and structure["direction"] == "BEARISH"
    ):
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"

    return {
        "timeframe": "D1",
        "direction": direction,
        "trend": trend,
        "structure": structure,
        "candles_count": len(candles),
    }


def analyze_h4_structure(
    h4_candles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Analyse la structure principale sur H4."""
    candles = validate_candle_series(
        h4_candles,
        minimum_count=TIMEFRAME_REQUIREMENTS["H4"],
    )

    atr = calculate_atr(candles)
    trend = determine_market_trend(candles)
    structure = detect_market_structure(candles)

    supports = find_supports(
        candles,
        atr=atr,
    )

    resistances = find_resistances(
        candles,
        atr=atr,
    )

    trendlines = detect_trendlines(
        candles,
        atr=atr,
    )

    return {
        "timeframe": "H4",
        "atr": atr,
        "trend": trend,
        "structure": structure,
        "supports": supports,
        "resistances": resistances,
        "trendlines": trendlines,
        "candles_count": len(candles),
    }


def analyze_h2_confirmation(
    h2_candles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Analyse la tendance intermédiaire sur H2."""
    candles = validate_candle_series(
        h2_candles,
        minimum_count=TIMEFRAME_REQUIREMENTS["H2"],
    )

    trend = determine_market_trend(candles)
    structure = detect_market_structure(candles)
    atr = calculate_atr(candles)

    return {
        "timeframe": "H2",
        "direction": trend["direction"],
        "trend": trend,
        "structure": structure,
        "atr": atr,
        "candles_count": len(candles),
    }


def analyze_h1_entry_context(
    h1_candles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Prépare les données H1 pour affiner la zone d'entrée."""
    candles = validate_candle_series(
        h1_candles,
        minimum_count=TIMEFRAME_REQUIREMENTS["H1"],
    )

    atr = calculate_atr(candles)
    trend = determine_market_trend(candles)
    structure = detect_market_structure(candles)

    supports = find_supports(
        candles,
        atr=atr,
    )

    resistances = find_resistances(
        candles,
        atr=atr,
    )

    trendlines = detect_trendlines(
        candles,
        atr=atr,
    )

    return {
        "timeframe": "H1",
        "atr": atr,
        "trend": trend,
        "structure": structure,
        "supports": supports,
        "resistances": resistances,
        "trendlines": trendlines,
        "candles_count": len(candles),
    }


def check_timeframe_alignment(
    d1_analysis: Dict[str, Any],
    h4_analysis: Dict[str, Any],
    h2_analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """Vérifie l'accord entre Daily, H4 et H2."""
    d1_direction = d1_analysis.get(
        "direction",
        "NEUTRAL",
    )

    h4_direction = h4_analysis.get(
        "structure",
        {},
    ).get(
        "direction",
        "RANGE",
    )

    h2_direction = h2_analysis.get(
        "direction",
        "NEUTRAL",
    )

    if d1_direction == "BULLISH":
        expected = "BUY"
        h4_aligned = h4_direction == "BULLISH"
        h2_aligned = h2_direction == "BULLISH"

    elif d1_direction == "BEARISH":
        expected = "SELL"
        h4_aligned = h4_direction == "BEARISH"
        h2_aligned = h2_direction == "BEARISH"

    else:
        return {
            "aligned": False,
            "direction": None,
            "score": 0,
            "reasons": [
                "La direction D1 n'est pas suffisamment claire."
            ],
        }

    score = 1
    reasons = [
        f"Direction générale D1 : {d1_direction}.",
    ]

    if h4_aligned:
        score += 1
        reasons.append(
            "La structure H4 est alignée."
        )
    else:
        reasons.append(
            "La structure H4 n'est pas alignée."
        )

    if h2_aligned:
        score += 1
        reasons.append(
            "La tendance H2 est alignée."
        )
    else:
        reasons.append(
            "La tendance H2 n'est pas alignée."
        )

    return {
        "aligned": h4_aligned and h2_aligned,
        "direction": expected,
        "score": score,
        "reasons": reasons,
}
def detect_bos(
    candles: List[Dict[str, Any]],
    radius: int = 2,
) -> Dict[str, Any]:
    """Détecte une éventuelle cassure de structure."""
    normalized = validate_candle_series(
        candles,
        minimum_count=max(
            MIN_CANDLE_COUNT,
            (radius * 2) + 1,
        ),
    )

    highs = find_pivot_highs(
        normalized,
        radius=radius,
    )

    lows = find_pivot_lows(
        normalized,
        radius=radius,
    )

    last_close = normalized[-1]["close"]

    bullish_bos = False
    bearish_bos = False
    broken_level = None

    if highs:
        latest_high = highs[-1]

        if (
            last_close > latest_high["price"]
            and normalized[-2]["close"]
            <= latest_high["price"]
        ):
            bullish_bos = True
            broken_level = latest_high["price"]

    if lows:
        latest_low = lows[-1]

        if (
            last_close < latest_low["price"]
            and normalized[-2]["close"]
            >= latest_low["price"]
        ):
            bearish_bos = True
            broken_level = latest_low["price"]

    if bullish_bos and not bearish_bos:
        direction = "BULLISH"
    elif bearish_bos and not bullish_bos:
        direction = "BEARISH"
    else:
        direction = "NONE"

    return {
        "detected": direction != "NONE",
        "direction": direction,
        "broken_level": broken_level,
        "last_close": last_close,
    }


def detect_displacement(
    candles: List[Dict[str, Any]],
    atr: Optional[float] = None,
    minimum_body_ratio: float = 0.55,
    minimum_range_atr: float = 0.80,
) -> Dict[str, Any]:
    """Détecte une bougie impulsive relativement à l'ATR."""
    normalized = validate_candle_series(
        candles,
        minimum_count=ATR_PERIOD + 1,
    )

    if atr is None:
        atr = calculate_atr(normalized)

    atr = _finite_number(atr, "ATR")

    if atr <= 0:
        raise StrategyError(
            "ATR invalide pour détecter le displacement."
        )

    candle = normalized[-1]

    candle_range = (
        candle["high"] - candle["low"]
    )

    body_ratio = candle_body_ratio(candle)

    if candle_range <= 0:
        return {
            "detected": False,
            "direction": "NONE",
            "range": candle_range,
            "body_ratio": body_ratio,
            "range_atr": 0.0,
        }

    range_atr = candle_range / atr

    detected = (
        body_ratio >= minimum_body_ratio
        and range_atr >= minimum_range_atr
    )

    direction = (
        candle_direction(candle)
        if detected
        else "NONE"
    )

    if direction == "DOJI":
        direction = "NONE"
        detected = False

    return {
        "detected": detected,
        "direction": direction,
        "range": candle_range,
        "body_ratio": body_ratio,
        "range_atr": range_atr,
        "candle": candle,
}
def detect_order_blocks(
    candles: List[Dict[str, Any]],
    lookback: int = 40,
    search_back: int = 5,
    atr: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Recherche les Order Blocks potentiels avant un déplacement.

    Un Order Block reste une zone candidate : sa présence seule
    ne constitue pas un signal d'entrée.
    """
    normalized = validate_candle_series(
        candles,
        minimum_count=max(
            MIN_CANDLE_COUNT,
            search_back + 2,
        ),
    )

    if lookback < 1 or search_back < 1:
        raise StrategyError(
            "Les paramètres de recherche des Order Blocks "
            "doivent être positifs."
        )

    if atr is None:
        atr = calculate_atr(normalized)

    atr = _finite_number(
        atr,
        "ATR",
    )

    if atr <= 0:
        raise StrategyError(
            "L'ATR doit être positif."
        )

    start_index = max(
        1,
        len(normalized) - lookback,
    )

    order_blocks = []

    for displacement_index in range(
        start_index,
        len(normalized),
    ):
        displacement_candle = normalized[
            displacement_index
        ]

        candle_range = (
            displacement_candle["high"]
            - displacement_candle["low"]
        )

        if candle_range <= 0:
            continue

        body_ratio = candle_body_ratio(
            displacement_candle
        )

        if (
            body_ratio < 0.55
                        or candle_range < atr * 0.80
        ):
            continue

        displacement_direction = candle_direction(
            displacement_candle
        )

        if displacement_direction == "DOJI":
            continue

        search_start = max(
            0,
            displacement_index - search_back,
        )

        candidate_index = None

        for index in range(
            displacement_index - 1,
            search_start - 1,
            -1,
        ):
            previous_candle = normalized[index]
            previous_direction = candle_direction(
                previous_candle
            )

            if (
                displacement_direction == "BULLISH"
                and previous_direction == "BEARISH"
            ):
                candidate_index = index
                break

            if (
                displacement_direction == "BEARISH"
                and previous_direction == "BULLISH"
            ):
                candidate_index = index
                break

        if candidate_index is None:
            continue

        block = normalized[candidate_index]

        if displacement_direction == "BULLISH":
            block_type = "BULLISH"
        else:
            block_type = "BEARISH"

        order_blocks.append(
            {
                "type": block_type,
                "index": candidate_index,
                "epoch": block["epoch"],
                "open": block["open"],
                "high": block["high"],
                "low": block["low"],
                "close": block["close"],
                "zone_lower": block["low"],
                "zone_upper": block["high"],
                "displacement_index": displacement_index,
                "displacement_epoch": (
                    displacement_candle["epoch"]
                ),
                "displacement_range_atr": (
                    candle_range / atr
                ),
                "body_ratio": body_ratio,
                "entry_reference": block["open"],
                "status": "CANDIDATE",
            }
        )

    unique_blocks = []
    seen = set()

    for block in sorted(
        order_blocks,
        key=lambda item: item["displacement_index"],
    ):
        key = (
            block["type"],
            block["index"],
        )

        if key in seen:
            continue

        seen.add(key)
        unique_blocks.append(block)

    return unique_blocks


def is_price_inside_order_block(
    current_price: float,
    order_block: Dict[str, Any],
) -> bool:
    """Vérifie si le prix se trouve dans un Order Block."""
    current_price = _finite_number(
        current_price,
        "current_price",
    )

    lower = _finite_number(
        order_block["zone_lower"],
        "zone_lower",
    )

    upper = _finite_number(
        order_block["zone_upper"],
        "zone_upper",
    )

    if lower > upper:
        raise StrategyError(
            "Les limites de l'Order Block sont inversées."
        )

    return lower <= current_price <= upper


def is_price_near_order_block(
    current_price: float,
    order_block: Dict[str, Any],
    atr: float,
    maximum_distance_atr: float = MAX_PRICE_DISTANCE_ATR,
) -> bool:
    """Vérifie si le prix approche d'un Order Block."""
    current_price = _finite_number(
        current_price,
        "current_price",
    )

    atr = _finite_number(
        atr,
        "ATR",
    )

    maximum_distance_atr = _finite_number(
        maximum_distance_atr,
        "maximum_distance_atr",
    )

    if atr <= 0 or maximum_distance_atr < 0:
        return False

    lower = _finite_number(
        order_block["zone_lower"],
        "zone_lower",
    )

    upper = _finite_number(
        order_block["zone_upper"],
        "zone_upper",
    )

    if lower > upper:
        return False

    if lower <= current_price <= upper:
        return True

    if current_price < lower:
        distance = lower - current_price
    else:
        distance = current_price - upper

    return distance <= (
        atr * maximum_distance_atr
    )


def filter_order_blocks_by_direction(
    order_blocks: List[Dict[str, Any]],
    direction: str,
) -> List[Dict[str, Any]]:
    """Conserve les Order Blocks compatibles avec la direction."""
    if direction == "BUY":
        expected_type = "BULLISH"
    elif direction == "SELL":
        expected_type = "BEARISH"
    else:
        raise StrategyError(
            "Direction invalide pour filtrer les Order Blocks."
        )

    return [
        block
        for block in order_blocks
        if block.get("type") == expected_type
    ]


def select_nearest_order_block(
    current_price: float,
    order_blocks: List[Dict[str, Any]],
    

