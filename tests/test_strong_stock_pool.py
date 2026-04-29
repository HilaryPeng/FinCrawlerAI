from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.db.connection import DatabaseConnection
from src.db.schema import TABLE_SCHEMAS
from src.market.ranker.selector import ObservationPoolSelector
from src.market.features.stock_feature_builder import StockFeatureBuilder
from src.market.report.daily_report_generator import DailyReportGenerator
from src.specs import load_market_daily_spec
from scripts.generate_market_daily_index import build_html, load_report_rows


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


class StrongStockWindowReturnTests(unittest.TestCase):
    def test_window_return_requires_full_window_history(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db = DatabaseConnection(Path(tmpdir) / "market_daily.db")
            conn = db.get_connection()
            try:
                conn.executescript(TABLE_SCHEMAS["daily_stock_quotes"])
                for day in range(1, 20):
                    conn.execute(
                        """
                        INSERT INTO daily_stock_quotes (
                            trade_date, symbol, name, close, created_at
                        )
                        VALUES (?, ?, ?, ?, datetime('now'))
                        """,
                        (f"2026-04-{day:02d}", "sz.000001", "测试股", 100 + day, ),
                    )
                conn.commit()
            finally:
                conn.close()

            builder = StockFeatureBuilder.__new__(StockFeatureBuilder)
            builder.db = db

            self.assertIsNone(builder._get_window_return("2026-04-19", "sz.000001", 20))

            db.execute(
                """
                INSERT INTO daily_stock_quotes (
                    trade_date, symbol, name, close, created_at
                )
                VALUES (?, ?, ?, ?, datetime('now'))
                """,
                ("2026-04-20", "sz.000001", "测试股", 120.0),
            )

            self.assertEqual(builder._get_window_return("2026-04-20", "sz.000001", 20), 18.8119)


class StrongStockDbMixin:
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
                "trend_window_scores": (
                    {"5d": 82.0, "10d": 86.0, "20d": 74.0}
                    if trend_hit
                    else {"5d": 0.0, "10d": 0.0, "20d": 0.0}
                ),
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

    def _insert_board_feature(
        self,
        db: DatabaseConnection,
        board_name: str,
        board_type: str,
        board_score: float,
        pct_chg: float,
    ) -> None:
        db.execute(
            """
            INSERT INTO daily_board_features (
                trade_date, board_name, board_type, pct_chg, up_count, down_count,
                limit_up_count, core_stock_count, news_count, news_heat_score,
                dragon_strength, center_strength, breadth_score, continuity_score,
                board_score, phase_hint, feature_json, created_at
            )
            VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ?, 'expand', '{}', datetime('now'))
            """,
            ("2026-04-24", board_name, board_type, pct_chg, board_score),
        )

    def _insert_membership(
        self,
        db: DatabaseConnection,
        symbol: str,
        board_name: str,
        board_type: str,
    ) -> None:
        db.execute(
            """
            INSERT INTO stock_board_membership (
                trade_date, symbol, board_name, board_type, is_primary, source, created_at
            )
            VALUES (?, ?, ?, ?, 1, 'test', datetime('now'))
            """,
            ("2026-04-24", symbol, board_name, board_type),
        )

    def _insert_market_breadth(self, db: DatabaseConnection) -> None:
        db.execute(
            """
            INSERT INTO daily_market_breadth (
                trade_date, sh_index_pct, sz_index_pct, cyb_index_pct, total_amount,
                up_count, down_count, limit_up_count, limit_down_count,
                broken_limit_count, highest_streak, created_at
            )
            VALUES (?, 0.6, 0.8, 1.1, 1100000000000, 2800, 2300, 55, 4, 21, 5, datetime('now'))
            """,
            ("2026-04-24",),
        )


class StrongStockSelectorTests(StrongStockDbMixin, unittest.TestCase):
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


class StrongStockReportTests(StrongStockDbMixin, unittest.TestCase):
    def test_report_data_includes_strong_board_summary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db = self._db(tmpdir)
            self._insert_feature(db, "sz.000001", "趋势票A", 90.0, 2_100_000_000, True, False)
            self._insert_feature(db, "sz.000002", "趋势票B", 80.0, 1_900_000_000, True, False)
            ObservationPoolSelector(db).build("2026-04-24")

            report_data = DailyReportGenerator(db)._build_report_data("2026-04-24")

            summary = report_data["strong_board_summary"]
            self.assertEqual(summary[0]["board_name"], "人工智能")
            self.assertEqual(summary[0]["strong_count"], 2)
            self.assertEqual(summary[0]["strong_amount"], 4_000_000_000)
            self.assertEqual(summary[0]["top_stock_name"], "趋势票A")
            self.assertEqual(summary[0]["avg_strong_score"], 85.0)

    def test_report_prefers_trading_board_over_csrc_board(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db = self._db(tmpdir)
            self._insert_feature(db, "sz.000001", "趋势票A", 90.0, 2_100_000_000, True, False)
            self._insert_feature(db, "sz.000002", "趋势票B", 80.0, 1_900_000_000, True, False)
            self._insert_board_feature(db, "半导体", "industry", 90.0, 2.0)
            self._insert_board_feature(db, "共封装光学(CPO)", "concept", 80.0, 1.5)
            self._insert_board_feature(db, "PCB概念", "concept", 95.0, 3.0)
            self._insert_membership(db, "sz.000001", "半导体", "industry")
            self._insert_membership(db, "sz.000001", "共封装光学(CPO)", "concept")
            self._insert_membership(db, "sz.000002", "PCB概念", "concept")
            ObservationPoolSelector(db).build("2026-04-24")

            report_data = DailyReportGenerator(db)._build_report_data("2026-04-24")

            pool = report_data["observation_pool"]
            self.assertEqual(pool[0]["board_name"], "共封装光学(CPO)")
            self.assertEqual(pool[0]["csrc_board_name"], "人工智能")
            self.assertEqual(pool[0]["related_board_names"], ["半导体"])
            self.assertEqual(pool[1]["board_name"], "PCB概念")
            self.assertEqual(report_data["strong_board_summary"][0]["board_name"], "共封装光学(CPO)")
            self.assertEqual(report_data["strong_board_summary"][1]["board_name"], "PCB概念")

    def test_report_data_includes_environment_and_mainlines(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db = self._db(tmpdir)
            self._insert_market_breadth(db)
            self._insert_feature(db, "sz.000001", "东山精密", 90.0, 2_100_000_000, True, False)
            self._insert_board_feature(db, "AI手机", "concept", 70.0, 4.0)
            self._insert_membership(db, "sz.000001", "AI手机", "concept")
            ObservationPoolSelector(db).build("2026-04-24")

            report_data = DailyReportGenerator(db)._build_report_data("2026-04-24")

            self.assertEqual(report_data["environment"]["state"], "结构性机会")
            self.assertGreaterEqual(report_data["environment"]["score"], 60)
            self.assertEqual(report_data["mainlines"][0]["board_name"], "AI手机")
            self.assertEqual(report_data["mainlines"][0]["status"], "主线明确")
            self.assertEqual(report_data["observation_pool"][0]["primary_role"], "容量票")
            self.assertIn("成交额继续保持 15 亿以上", report_data["observation_pool"][0]["watch_conditions"])

    def test_html_report_uses_workbench_layout(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db = self._db(tmpdir)
            self._insert_market_breadth(db)
            self._insert_feature(db, "sz.000001", "东山精密", 90.0, 2_100_000_000, True, False)
            self._insert_board_feature(db, "AI手机", "concept", 70.0, 4.0)
            self._insert_membership(db, "sz.000001", "AI手机", "concept")
            ObservationPoolSelector(db).build("2026-04-24")

            result = DailyReportGenerator(db).generate("2026-04-24")
            html = Path(result["html_path"]).read_text(encoding="utf-8")

            self.assertIn("workbench-shell", html)
            self.assertIn("强势股池日报", html)
            self.assertIn("环境强度", html)
            self.assertIn("强势方向", html)
            self.assertIn("个股证据", html)
            self.assertIn("观察条件", html)
            self.assertIn("AI手机", html)
            self.assertIn("容量票", html)
            self.assertNotIn("gauge-dial", html)


class MarketDailyIndexTests(unittest.TestCase):
    def test_index_uses_workbench_overview_fields(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            (output_dir / "market_daily_20260424.html").write_text("<html></html>", encoding="utf-8")
            (output_dir / "market_daily_20260424.json").write_text(
                """
                {
                  "metadata": {"trade_date": "2026-04-24", "generated_at": "2026-04-24 18:00:00"},
                  "market_summary": {"sh_index_pct": 0.5, "sz_index_pct": 1.1, "cyb_index_pct": 1.8, "up_count": 3100, "down_count": 1900, "limit_up_count": 65, "broken_limit_count": 12},
                  "environment": {"score": 72, "state": "结构性机会"},
                  "mainlines": [{"board_name": "AI手机", "mainline_score": 78, "status": "主线明确"}],
                  "observation_pool": [{"name": "东山精密", "primary_role": "容量票"}]
                }
                """,
                encoding="utf-8",
            )

            rows = load_report_rows(output_dir)
            html = build_html(rows)

            self.assertEqual(rows[0]["environment_score"], 72)
            self.assertEqual(rows[0]["top_mainline_name"], "AI手机")
            self.assertIn("强势股池日报总览", html)
            self.assertIn("结构性机会", html)
            self.assertIn("AI手机", html)
            self.assertIn("打开日报", html)


if __name__ == "__main__":
    unittest.main()
