"""
tests.test_polymarket_weather
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for the Polymarket weather trading pipeline nodes:
  - WeatherEnsembleNode
  - PolymarketPricingNode
  - EdgeDetectionNode
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from omega.core.node import NodeInput
from omega.nodes.polymarket.edge_detection import EdgeDetectionNode
from omega.nodes.polymarket.pricing import PolymarketPricingNode
from omega.nodes.polymarket.weather_ensemble import WeatherEnsembleNode

# ---------------------------------------------------------------------------
# WeatherEnsembleNode tests
# ---------------------------------------------------------------------------


class TestWeatherEnsembleNode(unittest.TestCase):
    def _make_mock_response(
        self,
        member_temps: list[float],
        target_hour: int = 12,
    ) -> dict:
        """Build a synthetic Open-Meteo ensemble API response."""
        from datetime import datetime

        today = datetime.now().strftime("%Y-%m-%d")
        times = [f"{today}T{h:02d}:00" for h in range(48)]

        hourly: dict = {"time": times}
        for i, temp in enumerate(member_temps):
            key = f"temperature_2m_member{i + 1:02d}"
            values = [temp] * len(times)  # same temp at all hours for simplicity
            hourly[key] = values

        return {"hourly": hourly}

    def test_probability_above_threshold(self):
        """All 5 members exceed threshold → probability = 1.0"""
        node = WeatherEnsembleNode()
        mock_data = self._make_mock_response([35.0, 36.0, 37.0, 38.0, 39.0])

        with patch.object(node, "_fetch_raw_ensemble", return_value=mock_data):
            out = node.execute(
                NodeInput(
                    action="probability",
                    parameters={"city": "NYC", "threshold_c": 30.0, "target_hour": 12},
                )
            )

        self.assertTrue(out.success, out.errors)
        result = out.result
        self.assertEqual(result["probability"], 1.0)
        self.assertEqual(result["member_count"], 5)
        self.assertEqual(result["members_exceeding"], 5)

    def test_probability_partial(self):
        """3 of 5 members exceed threshold → probability = 0.60"""
        node = WeatherEnsembleNode()
        mock_data = self._make_mock_response([35.0, 36.0, 37.0, 28.0, 25.0])

        with patch.object(node, "_fetch_raw_ensemble", return_value=mock_data):
            out = node.execute(
                NodeInput(
                    action="probability",
                    parameters={"city": "NYC", "threshold_c": 30.0, "target_hour": 12},
                )
            )

        self.assertTrue(out.success, out.errors)
        self.assertAlmostEqual(out.result["probability"], 0.60)
        self.assertEqual(out.result["members_exceeding"], 3)

    def test_probability_none_exceed(self):
        """No members exceed threshold → probability = 0.0"""
        node = WeatherEnsembleNode()
        mock_data = self._make_mock_response([20.0, 21.0, 22.0])

        with patch.object(node, "_fetch_raw_ensemble", return_value=mock_data):
            out = node.execute(
                NodeInput(
                    action="probability",
                    parameters={"city": "NYC", "threshold_c": 30.0, "target_hour": 12},
                )
            )

        self.assertTrue(out.success, out.errors)
        self.assertEqual(out.result["probability"], 0.0)

    def test_cache_ttl(self):
        """Second call with same params hits cache; patched fetch called once."""
        node = WeatherEnsembleNode()
        mock_data = self._make_mock_response([35.0, 36.0])

        with patch.object(node, "_fetch_raw_ensemble", return_value=mock_data) as mock_fetch:
            out1 = node.execute(
                NodeInput(
                    action="probability",
                    parameters={"city": "NYC", "threshold_c": 30.0, "target_hour": 12},
                )
            )
            out2 = node.execute(
                NodeInput(
                    action="probability",
                    parameters={"city": "NYC", "threshold_c": 30.0, "target_hour": 12},
                )
            )

        self.assertTrue(out1.success)
        self.assertTrue(out2.success)
        # Fetch should have been called exactly once; second call hits cache
        mock_fetch.assert_called_once()
        self.assertEqual(node._cache_hits, 1)
        self.assertEqual(node._cache_misses, 1)

    def test_cache_expiry(self):
        """After TTL expires the cache is missed and fetch is called again."""
        node = WeatherEnsembleNode()
        mock_data = self._make_mock_response([35.0])

        with patch.object(node, "_fetch_raw_ensemble", return_value=mock_data) as mock_fetch:
            node.execute(
                NodeInput(
                    action="probability",
                    parameters={"city": "NYC", "threshold_c": 30.0, "target_hour": 12},
                )
            )
            # Artificially expire the cache entry
            for entry in node._cache.values():
                entry.expires_at = time.time() - 1

            node.execute(
                NodeInput(
                    action="probability",
                    parameters={"city": "NYC", "threshold_c": 30.0, "target_hour": 12},
                )
            )

        self.assertEqual(mock_fetch.call_count, 2)

    def test_unknown_city_returns_error(self):
        node = WeatherEnsembleNode()
        out = node.execute(
            NodeInput(
                action="probability",
                parameters={"city": "ATLANTIS", "threshold_c": 30.0, "target_hour": 12},
            )
        )
        self.assertFalse(out.success)
        self.assertTrue(any("ATLANTIS" in e for e in out.errors))

    def test_list_cities(self):
        node = WeatherEnsembleNode()
        out = node.execute(NodeInput(action="list_cities"))
        self.assertTrue(out.success)
        self.assertIn("NYC", out.result["cities"])
        self.assertIn("CHICAGO", out.result["cities"])

    def test_evaluate_metrics(self):
        node = WeatherEnsembleNode()
        mock_data = self._make_mock_response([35.0])
        with patch.object(node, "_fetch_raw_ensemble", return_value=mock_data):
            node.execute(
                NodeInput(
                    action="probability",
                    parameters={"city": "NYC", "threshold_c": 30.0, "target_hour": 12},
                )
            )
        metrics = node.evaluate()
        self.assertIn("error_rate", metrics)
        self.assertIn("cache_hit_rate", metrics)
        self.assertIn("avg_latency_ms", metrics)
        self.assertEqual(metrics["error_rate"], 0.0)


# ---------------------------------------------------------------------------
# PolymarketPricingNode tests
# ---------------------------------------------------------------------------


class TestPolymarketPricingNode(unittest.TestCase):
    def _make_market(
        self,
        question: str = "Will NYC reach 95°F on July 4?",
        yes_price: float = 0.62,
        no_price: float = 0.38,
        volume: float = 50000.0,
        condition_id: str = "test-condition-001",
    ) -> dict:
        return {
            "conditionId": condition_id,
            "question": question,
            "tokens": [
                {"outcome": "Yes", "price": yes_price},
                {"outcome": "No", "price": no_price},
            ],
            "volume": volume,
            "active": True,
        }

    def test_fetch_weather_markets_filters_correctly(self):
        node = PolymarketPricingNode()
        raw_list = [
            self._make_market("Will NYC reach 95°F on July 4?"),
            self._make_market(
                "Will BTC exceed $100k?", condition_id="btc-001"
            ),  # should be filtered
            self._make_market(
                "Will Chicago temperature drop below 32°F?", condition_id="chicago-001"
            ),
        ]

        with patch.object(node, "_get_json", return_value=raw_list):
            out = node.execute(NodeInput(action="fetch_weather_markets"))

        self.assertTrue(out.success, out.errors)
        questions = [m["question"] for m in out.result]
        self.assertIn("Will NYC reach 95°F on July 4?", questions)
        # BTC market should be filtered out
        self.assertNotIn("Will BTC exceed $100k?", questions)
        self.assertIn("Will Chicago temperature drop below 32°F?", questions)

    def test_market_price_parsing(self):
        node = PolymarketPricingNode()
        raw_list = [self._make_market(yes_price=0.72, no_price=0.28)]

        with patch.object(node, "_get_json", return_value=raw_list):
            out = node.execute(NodeInput(action="fetch_weather_markets"))

        self.assertTrue(out.success)
        market = out.result[0]
        self.assertAlmostEqual(market["yes_price"], 0.72)
        self.assertAlmostEqual(market["no_price"], 0.28)

    def test_cache_hit_on_repeat_call(self):
        node = PolymarketPricingNode()
        raw_list = [self._make_market()]

        with patch.object(node, "_get_json", return_value=raw_list) as mock_get:
            node.execute(NodeInput(action="fetch_weather_markets"))
            node.execute(NodeInput(action="fetch_weather_markets"))

        mock_get.assert_called_once()

    def test_empty_weather_markets(self):
        node = PolymarketPricingNode()
        raw_list = [
            {"conditionId": "x", "question": "Will BTC hit $200k?", "tokens": [], "volume": 0}
        ]
        with patch.object(node, "_get_json", return_value=raw_list):
            out = node.execute(NodeInput(action="fetch_weather_markets"))
        self.assertTrue(out.success)
        self.assertEqual(out.result, [])

    def test_unknown_action(self):
        node = PolymarketPricingNode()
        out = node.execute(NodeInput(action="nonexistent_action"))
        self.assertFalse(out.success)


# ---------------------------------------------------------------------------
# EdgeDetectionNode tests
# ---------------------------------------------------------------------------


class TestEdgeDetectionNode(unittest.TestCase):
    def test_clear_edge_opportunity(self):
        """model_prob=0.80, market_price=0.50 → edge=0.30, opportunity=True"""
        node = EdgeDetectionNode()
        out = node.execute(
            NodeInput(
                action="detect",
                parameters={
                    "model_prob": 0.80,
                    "market_price": 0.50,
                    "city": "NYC",
                    "market_id": "test-001",
                    "question": "Will NYC hit 95°F?",
                },
            )
        )

        self.assertTrue(out.success, out.errors)
        result = out.result
        self.assertAlmostEqual(result["edge"], 0.30)
        self.assertTrue(result["opportunity"])
        self.assertEqual(result["direction"], "YES")

    def test_no_edge_below_threshold(self):
        """edge=0.03 < threshold=0.08 → opportunity=False"""
        node = EdgeDetectionNode(edge_threshold=0.08)
        out = node.execute(
            NodeInput(
                action="detect",
                parameters={
                    "model_prob": 0.53,
                    "market_price": 0.50,
                    "city": "NYC",
                    "market_id": "test-002",
                    "question": "Will NYC hit 95°F?",
                },
            )
        )

        self.assertTrue(out.success)
        result = out.result
        self.assertAlmostEqual(result["edge"], 0.03)
        self.assertFalse(result["opportunity"])

    def test_negative_edge_direction_no(self):
        """model_prob=0.30, market_price=0.70 → edge=-0.40, direction=NO"""
        node = EdgeDetectionNode()
        out = node.execute(
            NodeInput(
                action="detect",
                parameters={
                    "model_prob": 0.30,
                    "market_price": 0.70,
                    "city": "MIAMI",
                    "market_id": "test-003",
                    "question": "Will Miami heat wave persist?",
                },
            )
        )

        self.assertTrue(out.success)
        result = out.result
        self.assertAlmostEqual(result["edge"], -0.40)
        self.assertEqual(result["direction"], "NO")
        self.assertTrue(result["opportunity"])

    def test_kelly_sizing(self):
        """Kelly fraction: edge=0.30, model_prob=0.80 → f*=0.30/0.20=1.50 → capped at 0.25"""
        node = EdgeDetectionNode(max_kelly_fraction=0.25)
        kelly = node.kelly_fraction(0.30, 0.80, 0.25)
        # Raw Kelly = 0.30 / 0.20 = 1.50, capped at 0.25
        self.assertAlmostEqual(kelly, 0.25)

    def test_kelly_moderate_edge(self):
        """Kelly fraction: edge=0.10, model_prob=0.60 → f*=0.10/0.40=0.25"""
        node = EdgeDetectionNode(max_kelly_fraction=0.25)
        kelly = node.kelly_fraction(0.10, 0.60, 0.25)
        self.assertAlmostEqual(kelly, 0.25)

    def test_kelly_small_edge(self):
        """Kelly fraction: edge=0.08, model_prob=0.55 → f*=0.08/0.45≈0.178"""
        node = EdgeDetectionNode(max_kelly_fraction=0.25)
        kelly = node.kelly_fraction(0.08, 0.55, 0.25)
        expected = 0.08 / 0.45
        self.assertAlmostEqual(kelly, min(expected, 0.25), places=3)

    def test_kelly_zero_edge(self):
        """Kelly fraction with zero edge = 0"""
        node = EdgeDetectionNode()
        kelly = node.kelly_fraction(0.0, 0.55, 0.25)
        self.assertAlmostEqual(kelly, 0.0)

    def test_batch_detect(self):
        node = EdgeDetectionNode(edge_threshold=0.08)
        items = [
            {"model_prob": 0.80, "market_price": 0.50, "city": "NYC", "market_id": "a"},
            {"model_prob": 0.52, "market_price": 0.50, "city": "LA", "market_id": "b"},
            {"model_prob": 0.20, "market_price": 0.50, "city": "CHICAGO", "market_id": "c"},
        ]
        out = node.execute(
            NodeInput(
                action="batch_detect",
                parameters={"items": items},
            )
        )
        self.assertTrue(out.success)
        results = out.result
        self.assertEqual(len(results), 3)

        # First: edge=0.30 → opportunity
        self.assertTrue(results[0]["opportunity"])
        # Second: edge=0.02 → no opportunity
        self.assertFalse(results[1]["opportunity"])
        # Third: edge=-0.30 → opportunity (NO side)
        self.assertTrue(results[2]["opportunity"])

    def test_evaluate_tracks_opportunities(self):
        node = EdgeDetectionNode()
        node.execute(
            NodeInput(
                action="detect",
                parameters={
                    "model_prob": 0.80,
                    "market_price": 0.50,
                    "city": "NYC",
                    "market_id": "x",
                },
            )
        )
        node.execute(
            NodeInput(
                action="detect",
                parameters={
                    "model_prob": 0.51,
                    "market_price": 0.50,
                    "city": "LA",
                    "market_id": "y",
                },
            )
        )
        metrics = node.evaluate()
        self.assertEqual(metrics["opportunities_detected"], 1.0)
        self.assertEqual(metrics["execution_count"], 2.0)


if __name__ == "__main__":
    unittest.main()
