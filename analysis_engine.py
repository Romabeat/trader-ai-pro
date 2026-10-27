
def candle_trend(candles):
    """Estime la tendance à partir des dernières bougies."""
    if len(candles) < 30:
        return "Données insuffisantes"

    closes = [float(c["close"]) for c in candles]
    recent = closes[-20:]
    previous = closes[-30:-10]

    recent_avg = sum(recent) / len(recent)
    previous_avg = sum(previous) / len(previous)

    if recent_avg > previous_avg:
        return "Haussière"
    if recent_avg < previous_avg:
        return "Baissière"
    return "Neutre"


def find_support_resistance(candles, window=50):
    """Repère des niveaux simples sur les bougies récentes."""
    if len(candles) < window:
        return None, None

    recent = candles[-window:]
    lows = [float(c["low"]) for c in recent]
    highs = [float(c["high"]) for c in recent]

    return min(lows), max(highs)


def detect_candle_reversal(candles):
    """Détecte une possible bougie de retournement."""
    if len(candles) < 2:
        return None

    prev = candles[-2]
    last = candles[-1]

    o = float(last["open"])
    c = float(last["close"])
    h = float(last["high"])
    l = float(last["low"])

    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l

    prev_o = float(prev["open"])
    prev_c = float(prev["close"])

    bullish_engulfing = (
        prev_c < prev_o and c > o
        and c >= prev_o and o <= prev_c
    )
    bearish_engulfing = (
        prev_c > prev_o and c < o
        and c <= prev_o and o >= prev_c
    )

    if bullish_engulfing:
        return "Possible retournement haussier"
    if bearish_engulfing:
        return "Possible retournement baissier"

    if body > 0 and lower_wick >= 2 * body:
        return "Rejet possible vers le haut"
    if body > 0 and upper_wick >= 2 * body:
        return "Rejet possible vers le bas"

    return None


def analyze_candles(candles):
    """Retourne une première synthèse, sans produire d'ordre."""
    support, resistance = find_support_resistance(candles)

    return {
        "trend": candle_trend(candles),
        "support": support,
        "resistance": resistance,
        "reversal": detect_candle_reversal(candles)
  }

