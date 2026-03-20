"""
Board ranking utilities.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.db import DatabaseConnection


class BoardRanker:
    """Rank boards for a specific trade date."""

    def __init__(self, db: DatabaseConnection):
        self.db = db

    def rank(self, trade_date: str) -> List[Dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT
                board_name,
                board_type,
                board_score,
                phase_hint,
                pct_chg,
                limit_up_count,
                core_stock_count
            FROM daily_board_features
            WHERE trade_date = ?
            ORDER BY board_score DESC, pct_chg DESC, board_name ASC
            """,
            (trade_date,),
        )
        ranked: List[Dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            record = dict(row)
            record["board_rank"] = index
            ranked.append(record)
        return ranked
