"""
Stock ranking utilities.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.db import DatabaseConnection


class StockRanker:
    """Rank stocks for a specific trade date."""

    def __init__(self, db: DatabaseConnection):
        self.db = db

    def rank(self, trade_date: str) -> List[Dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT
                symbol,
                name,
                primary_board_name,
                primary_board_type,
                role_tag,
                dragon_score,
                center_score,
                follow_score,
                risk_score,
                final_score,
                board_score_ref,
                risk_flags
            FROM daily_stock_features
            WHERE trade_date = ?
            ORDER BY final_score DESC, symbol ASC
            """,
            (trade_date,),
        )
        ranked: List[Dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            record = dict(row)
            record["stock_rank"] = index
            ranked.append(record)
        return ranked
