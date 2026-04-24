from __future__ import annotations

import unittest

from src.market.features.stock_feature_builder import StockFeatureBuilder
from src.specs import load_market_daily_spec


class StrongStockMetricTests(unittest.TestCase):
    def _builder(self) -> StockFeatureBuilder:
        spec = load_market_daily_spec()
        builder = StockFeatureBuilder.__new__(StockFeatureBuilder)
        builder.spec = spec.strategy["stock_feature"]
        builder.strong_spec = spec.strategy["strong_stock_pool"]
        return builder

    def test_trend_channel_hit_adds_trend_and_capacity_labels(self) -> None:
        builder = self._builder()

        metrics = builder._compute_strong_stock_metrics(
            amount=2_100_000_000,
            pct_chg_5d=11.0,
            pct_chg_10d=16.0,
            pct_chg_20d=30.0,
            limit_up=0,
            limit_up_streak=0,
        )

        self.assertTrue(metrics["trend_channel_hit"])
        self.assertFalse(metrics["emotion_channel_hit"])
        self.assertEqual(metrics["labels"], ["trend_strong", "capacity_strong"])
        self.assertGreaterEqual(metrics["strong_score"], 70.0)

    def test_emotion_channel_hit_can_enter_without_trend(self) -> None:
        builder = self._builder()

        metrics = builder._compute_strong_stock_metrics(
            amount=1_100_000_000,
            pct_chg_5d=1.0,
            pct_chg_10d=2.0,
            pct_chg_20d=3.0,
            limit_up=0,
            limit_up_streak=2,
        )

        self.assertFalse(metrics["trend_channel_hit"])
        self.assertTrue(metrics["emotion_channel_hit"])
        self.assertEqual(metrics["labels"], ["emotion_strong"])
        self.assertEqual(metrics["emotion_score"], 85.0)


if __name__ == "__main__":
    unittest.main()
