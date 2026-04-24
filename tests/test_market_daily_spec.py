from __future__ import annotations

import unittest

from src.specs import load_market_daily_spec


class MarketDailySpecTests(unittest.TestCase):
    def test_load_market_daily_spec_returns_expected_sections(self) -> None:
        spec = load_market_daily_spec()

        self.assertIn("board_feature", spec.strategy)
        self.assertIn("stock_feature", spec.strategy)
        self.assertIn("observation_pool", spec.strategy)
        self.assertIn("quality", spec.runtime)
        self.assertIn("pipeline", spec.runtime)
        self.assertIn("roles", spec.presentation)
        self.assertIn("markdown", spec.presentation)
        self.assertIn("html", spec.presentation)
        self.assertIn("tables", spec.data)
        self.assertIn("rebuild_dependencies", spec.data)

    def test_observation_pool_baseline_matches_current_shape(self) -> None:
        spec = load_market_daily_spec()
        pool_spec = spec.strategy["observation_pool"]

        self.assertEqual(pool_spec["top20_size"], 20)
        self.assertEqual(pool_spec["backup_size"], 10)
        self.assertEqual(pool_spec["max_per_board"], 6)
        self.assertEqual(pool_spec["max_per_board_role"], 2)
        self.assertEqual(sum(pool_spec["role_targets"].values()), 20)

    def test_strong_stock_pool_spec_matches_design(self) -> None:
        spec = load_market_daily_spec()
        strong = spec.strategy["strong_stock_pool"]

        self.assertEqual(strong["trend_channel"]["min_amount"], 1_500_000_000.0)
        self.assertEqual(strong["emotion_channel"]["min_amount"], 1_000_000_000.0)
        self.assertEqual(strong["selection"]["main_pool_limit"], 30)
        self.assertEqual(spec.presentation["roles"]["trend_strong"], "趋势强")
        self.assertEqual(spec.presentation["roles"]["emotion_strong"], "情绪强")
        self.assertEqual(spec.presentation["roles"]["capacity_strong"], "容量强")


if __name__ == "__main__":
    unittest.main()
