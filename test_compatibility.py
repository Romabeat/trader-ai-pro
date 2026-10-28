"""Verification de compatibilite de TRADER AI PRO."""

import inspect
import sys

def check(condition, message):
if not condition:
raise AssertionError(message)
print("[OK] " + message)

def main():
print("=" * 55)
print("TEST DE COMPATIBILITE - TRADER AI PRO")
print("=" * 55)

try:
    import analysis_engine
    import strategy
    import deriv_market
    import scheduled_analysis
except Exception as exc:
    print("[ECHEC] Impossible de charger les modules.")
    print("Erreur :", type(exc).__name__, str(exc))
    return 1

print("\n1. Verification des modules")

check(
    callable(getattr(analysis_engine, "analyze_candles", None)),
    "analysis_engine.analyze_candles disponible",
)

check(
    callable(getattr(analysis_engine, "normalize_candles", None)),
    "analysis_engine.normalize_candles disponible",
)

check(
    callable(getattr(analysis_engine, "candle_confirms", None)),
    "analysis_engine.candle_confirms disponible",
)

check(
    callable(getattr(strategy, "find_signals", None)),
    "strategy.find_signals disponible",
)

check(
    callable(getattr(strategy, "format_message", None)),
    "strategy.format_message disponible",
)

check(
    callable(getattr(deriv_market, "get_candles", None)),
    "deriv_market.get_candles disponible",
)

check(
    callable(getattr(scheduled_analysis, "main", None)),
    "scheduled_analysis.main disponible",
)

print("\n2. Verification des signatures")

parameters = inspect.signature(strategy.find_signals).parameters

for name in ("symbol", "h1", "h4", "d1", "m30", "price_now"):
    check(
        name in parameters,
        "find_signals accepte le parametre " + name,
    )

print("\n3. Test du format des bougies")

sample = [
    {
        "epoch": 1000 + i * 1800,
        "open": 100.0 + i,
        "high": 102.0 + i,
        "low": 99.0 + i,
        "close": 101.0 + i,
    }
    for i in range(40)
]

normalized = analysis_engine.normalize_candles(sample)

check(
    isinstance(normalized, list),
    "normalisation : resultat de type liste",
)

check(
    len(normalized) >= 30,
    "normalisation : au moins 30 bougies conservees",
)

analysis = analysis_engine.analyze_candles(normalized)

check(
    isinstance(analysis, dict),
    "analyse : resultat de type dictionnaire",
)

check(
    "trend" in analysis,
    "analyse : champ trend present",
)

check(
    "signal" in analysis,
    "analyse : champ signal present",
)

print("\n4. Verification des unites de temps")

expected = {
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}

actual = getattr(deriv_market, "GRANULARITY", {})

for timeframe, seconds in expected.items():
    check(
        actual.get(timeframe) == seconds,
        "%s : granularite correcte" % timeframe,
    )

print("\n" + "=" * 55)
print("TOUS LES TESTS DE COMPATIBILITE SONT PASSES.")
print("Attention : cela ne valide pas la rentabilite des signaux.")
print("=" * 55)

return 0

if name == "main":
sys.exit(main())
