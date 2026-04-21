"""
Daily market data quality checks.
"""

from __future__ import annotations

from typing import Any, Dict

from src.db import DatabaseConnection
from src.specs import load_market_daily_spec


class DataQualityChecker:
    """Check whether a trade date has enough data for downstream processing."""

    DEFAULT_QUOTES_THRESHOLD = 4000
    DEFAULT_BOARD_THRESHOLD = 400
    DEFAULT_LIMITS_THRESHOLD = 10

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.spec = load_market_daily_spec().runtime["quality"]

    def check(self, trade_date: str) -> Dict[str, Any]:
        quote_count = self._count("daily_stock_quotes", trade_date)
        board_count = self._count("daily_board_quotes", trade_date)
        limit_count = self._count("daily_stock_limits", trade_date)
        breadth_count = self._count("daily_market_breadth", trade_date)
        membership_count = self._count("stock_board_membership", trade_date)
        news_count = self._count("news_items", trade_date, by_publish_date=True)

        baseline_quotes = self._baseline_quotes()
        thresholds = self.spec["thresholds"]
        required_quotes = max(
            int(baseline_quotes * float(self.spec["baseline_quote_ratio"])),
            int(thresholds["quotes"]),
        )
        quote_ratio = round((quote_count / baseline_quotes), 4) if baseline_quotes > 0 else None

        checks = {
            "quotes": quote_count >= required_quotes,
            "boards": board_count >= int(thresholds["boards"]),
            "limits": limit_count >= int(thresholds["limits"]),
            "breadth": breadth_count >= int(thresholds["breadth"]),
            "membership": membership_count >= int(thresholds["membership"]),
        }
        passed_checks = sum(1 for passed in checks.values() if passed)

        status = "complete"
        blocked_checks = set(self.spec["blocked_checks"])
        if any(not checks.get(name, False) for name in blocked_checks):
            status = "blocked"
        elif passed_checks < len(checks):
            status = "partial"

        return {
            "trade_date": trade_date,
            "status": status,
            "quote_count": quote_count,
            "board_count": board_count,
            "limit_count": limit_count,
            "breadth_count": breadth_count,
            "membership_count": membership_count,
            "news_count": news_count,
            "baseline_quotes": baseline_quotes,
            "required_quotes": required_quotes,
            "quote_ratio": quote_ratio,
            "checks": checks,
        }

    def _count(self, table_name: str, trade_date: str, by_publish_date: bool = False) -> int:
        if by_publish_date:
            row = self.db.fetchone(
                """
                SELECT COUNT(*) AS cnt
                FROM news_items
                WHERE DATE(publish_time) = ?
                """,
                (trade_date,),
            )
        else:
            row = self.db.fetchone(
                f"SELECT COUNT(*) AS cnt FROM {table_name} WHERE trade_date = ?",
                (trade_date,),
            )
        return int(row["cnt"]) if row and row["cnt"] is not None else 0

    def _baseline_quotes(self) -> int:
        row = self.db.fetchone(
            """
            SELECT MAX(cnt) AS max_cnt
            FROM (
                SELECT trade_date, COUNT(*) AS cnt
                FROM daily_stock_quotes
                GROUP BY trade_date
            )
            """
        )
        max_cnt = int(row["max_cnt"]) if row and row["max_cnt"] is not None else 0
        return max_cnt if max_cnt > 0 else self.DEFAULT_QUOTES_THRESHOLD
