"""Tests automatisés de compatibilité de Trader AI Pro."""

import inspect
import unittest
from unittest.mock import patch

import analysis_engine
import strategy
import deriv_market
import scheduled_analysis


class TestTraderAIProCompatibility(unittest.TestCase):

    def test_analysis_engine_functions_exist(self):
        """Vérifie les fonctions principales du moteur technique."""
        self.assertTrue(
            callable(getattr(analysis_engine, "analyze_candles", None))
        )
        self.assertTrue(
            callable(getattr(analysis_engine, "normalize_candles", None))
        )
        self.assertTrue(
            callable(getattr(analysis_engine, "candle_confirms", None))
        )

    def test_strategy_functions_exist(self):
        """Vérifie les fonctions publiques de la stratégie."""
        self.assertTrue(callable(strategy.find_signals))
        self.assertTrue(callable(strategy.format_message))

    def test_deriv_market_function_exists(self):
        """Vérifie la présence du récupérateur de bougies."""
        self.assertTrue(callable(deriv_market.get_candles))

    def test_scheduled_analysis_main_exists(self):
        """Vérifie la présence du point d'entrée du scanner."""
        self.assertTrue(callable(scheduled_analysis.main))

    def test_strategy_parameters(self):
        """Vérifie les paramètres attendus par find_signals."""
        parameters = inspect.signature(
            strategy.find_signals
        ).parameters

        for name in ("symbol", "h1", "h4", "d1", "m30"):
            self.assertIn(name, parameters)

    def test_deriv_timeframes(self):
        """Vérifie les granularités des unités de temps."""
        expected = {
            "M30": 1800,
            "H1": 3600,
            "H2": 7200,
            "H4": 14400,
            "D1": 86400,
        }

        for timeframe, seconds in expected.items():
            with self.subTest(timeframe=timeframe):
                self.assertEqual(
                    deriv_market.GRANULARITY.get(timeframe),
                    seconds,
                )

    def test_scanner_symbols_exist(self):
        """Vérifie que le scanner possède une liste d'actifs."""
        self.assertIsInstance(
            scheduled_analysis.SYMBOLS,
            list,
        )
        self.assertGreater(
            len(scheduled_analysis.SYMBOLS),
            0,
        )

    def test_dry_run_is_defined(self):
        """Vérifie que le mode de sécurité est défini."""
        self.assertIsInstance(
            scheduled_analysis.DRY_RUN,
            bool,
        )

    def test_market_data_response_compatibility(self):
        """Vérifie que le scanner extrait la liste de bougies."""
        fake_candles = [
            {
                "epoch": 1700000000 + i * 3600,
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
            }
            for i in range(40)
        ]

        with patch.object(
            scheduled_analysis,
            "get_candles",
            return_value={
                "symbol": "R_10",
                "timeframe": "H1",
                "count": len(fake_candles),
                "candles": fake_candles,
            },
        ):
            rows = scheduled_analysis.fetch_candles(
                "R_10",
                "H1",
            )

        self.assertIsInstance(rows, list)
        self.assertEqual(len(rows), 40)
        self.assertEqual(rows[0]["open"], 100.0)

    def test_market_data_api_error_is_rejected(self):
        """Vérifie qu'une erreur Deriv ne devient pas une liste de bougies."""
        with patch.object(
            scheduled_analysis,
            "get_candles",
            return_value={"error": "Erreur simulée"},
        ):
            rows = scheduled_analysis.fetch_candles(
                "R_10",
                "H1",
            )

        self.assertIsNone(rows)

    def test_strategy_rejects_insufficient_data(self):
        """Vérifie que le moteur rejette les données insuffisantes."""
        signals = strategy.find_signals(
            symbol="R_10",
            h4=[],
            h1=[],
        )

        self.assertEqual(signals, [])

    def test_format_message(self):
        """Vérifie le formatage d'un signal valide."""
        signal = {
            "signal_id": "TEST-R10-BUY-001",
            "symbol": "R_10",
            "direction": "BUY",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": 106.0,
            "rr": 3.0,
            "zone_low": 98.0,
            "zone_high": 101.0,
            "h4_structure": "HAUSSIERE",
            "liquidity_sweep": True,
            "timestamp_utc": "2026-10-29T10:00:00+00:00",
        }

        message = strategy.format_message(signal)

        self.assertIn("TRADER AI PRO", message)
        self.assertIn("R_10", message)
        self.assertIn("ACHAT (BUY)", message)
        self.assertIn("Stop-loss", message)
        self.assertIn("Take-profit", message)
        self.assertIn("Aucun ordre automatique", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
