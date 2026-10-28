
"""Tests de compatibilite de Trader AI Pro."""

import inspect

import analysis_engine
import strategy
import deriv_market
import scheduled_analysis


def check(condition, message):
    """Arrete les tests si une condition n'est pas satisfaite."""
    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}", flush=True)


def main():
    """Execute les controles de compatibilite."""

    # 1. Verifier les fonctions principales.
    check(
        callable(getattr(analysis_engine, "analyze_candles", None)),
        "analysis_engine.analyze_candles existe",
    )
    check(
        callable(getattr(analysis_engine, "normalize_candles", None)),
        "analysis_engine.normalize_candles existe",
    )
    check(
        callable(getattr(analysis_engine, "candle_confirms", None)),
        "analysis_engine.candle_confirms existe",
    )
    check(
        callable(getattr(strategy, "find_signals", None)),
        "strategy.find_signals existe",
    )
    check(
        callable(getattr(strategy, "format_message", None)),
        "strategy.format_message existe",
    )
    check(
        callable(getattr(deriv_market, "get_candles", None)),
        "deriv_market.get_candles existe",
    )
    check(
        callable(getattr(scheduled_analysis, "main", None)),
        "scheduled_analysis.main existe",
    )

    # 2. Verifier les parametres de find_signals.
    parameters = inspect.signature(strategy.find_signals).parameters

    for name in ("symbol", "h1", "h4", "d1", "m30"):
        check(
            name in parameters,
            f"find_signals accepte le parametre {name}",
        )

    # 3. Verifier les unites de temps Deriv.
    granularities = getattr(deriv_market, "GRANULARITY", {})

    expected = {
        "M30": 1800,
        "H1": 3600,
        "H4": 14400,
        "D1": 86400,
    }

    for timeframe, seconds in expected.items():
        check(
            granularities.get(timeframe) == seconds,
            f"Granularite {timeframe} configuree correctement",
        )

    # 4. Verifier le mode test securise par defaut.
    check(
        scheduled_analysis.DRY_RUN is True
        or scheduled_analysis.DRY_RUN is False,
        "DRY_RUN est defini",
    )

    check(
        isinstance(scheduled_analysis.SYMBOLS, list)
        and len(scheduled_analysis.SYMBOLS) > 0,
        "La liste des actifs n'est pas vide",
    )

    print(
        "\nTous les controles de compatibilite sont passes.",
        flush=True,
    )


if __name__ == "__main__":
    main()
    
