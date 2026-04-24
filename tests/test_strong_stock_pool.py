from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.db.connection import DatabaseConnection
from src.db.schema import TABLE_SCHEMAS
from src.market.ranker.selector import ObservationPoolSelector
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


class StrongStockSelectorTests(unittest.TestCase):
    def _db(self, tmpdir: str) -> DatabaseConnection:
        db = DatabaseConnection(Path(tmpdir) / "market_daily.db")
        conn = db.get_connection()
        try:
            for ddl in TABLE_SCHEMAS.values():
                conn.executescript(ddl)
            conn.commit()
        finally:
            conn.close()
        return db

    def _insert_feature(
        self,
        db: DatabaseConnection,
        symbol: str,
        name: str,
        final_score: float,
        amount: float,
        trend_hit: bool,
        emotion_hit: bool,
    ) -> None:
        feature_json = {
            "strong_metrics": {
                "strong_score": final_score,
                "trend_score": final_score if trend_hit else 0.0,
                "emotion_score": final_score if emotion_hit else 0.0,
                "trend_channel_hit": trend_hit,
                "emotion_channel_hit": emotion_hit,
                "labels": ["trend_strong"] if trend_hit else ["emotion_strong"] if emotion_hit else [],
            }
        }
        import json

        db.execute(
            """
            INSERT INTO daily_stock_features (
                trade_date, symbol, name, primary_board_name, primary_board_type,
                amount, final_score, role_tag, feature_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                "2026-04-24",
                symbol,
                name,
                "人工智能",
                "industry_csrc",
                amount,
                final_score,
                "trend_strong" if trend_hit else "emotion_strong" if emotion_hit else "watchlist",
                json.dumps(feature_json, ensure_ascii=False),
            ),
        )

    def test_selector_keeps_only_strong_channel_hits(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db = self._db(tmpdir)
            self._insert_feature(db, "sz.000003", "弱票", 99.0, 4_000_000_000, False, False)
            self._insert_feature(db, "sz.000001", "趋势票", 90.0, 2_100_000_000, True, False)
            self._insert_feature(db, "sh.600001", "情绪票", 85.0, 1_100_000_000, False, True)

            count = ObservationPoolSelector(db).build("2026-04-24")

            rows = db.fetchall(
                """
                SELECT symbol, role_tag, pool_group
                FROM daily_observation_pool
                ORDER BY stock_rank
                """
            )
            self.assertEqual(count, 2)
            self.assertEqual([row["symbol"] for row in rows], ["sz.000001", "sh.600001"])
            self.assertEqual(rows[0]["pool_group"], "top20")


if __name__ == "__main__":
    unittest.main()
