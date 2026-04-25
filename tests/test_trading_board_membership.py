from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.db.connection import DatabaseConnection
from src.db.schema import TABLE_SCHEMAS
from src.market.collectors.boards_collector import BoardsCollector


class TradingBoardMembershipTests(unittest.TestCase):
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

    def test_selects_ranked_boards_and_keyword_matches(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db = self._db(tmpdir)
            self._insert_board_feature(db, "低分概念", "concept", 1.0, 1.0)
            self._insert_board_feature(db, "高分概念", "concept", 90.0, 1.0)
            self._insert_board_feature(db, "次高概念", "concept", 80.0, 3.0)
            self._insert_board_feature(db, "PCB概念", "concept", 2.0, -1.0)
            self._insert_board_feature(db, "高分行业", "industry", 70.0, 2.0)
            self._insert_board_feature(db, "低分行业", "industry", 10.0, 9.0)
            self._insert_board_feature(db, "半导体", "industry", 3.0, -2.0)
            self._insert_board_feature(db, "证监会行业", "industry_csrc", 100.0, 5.0)

            candidates = BoardsCollector(db)._select_trading_board_candidates(
                "2026-04-24",
                concept_limit=2,
                industry_limit=1,
            )

            pairs = [(item["board_name"], item["board_type"]) for item in candidates]
            self.assertEqual(
                pairs,
                [
                    ("高分概念", "concept"),
                    ("次高概念", "concept"),
                    ("高分行业", "industry"),
                    ("PCB概念", "concept"),
                    ("半导体", "industry"),
                ],
            )


if __name__ == "__main__":
    unittest.main()
