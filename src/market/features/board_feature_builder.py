"""
Daily board feature builder.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd

from src.db import (
    DatabaseConnection,
    DailyBoardFeaturesRepository,
)
from src.specs import load_market_daily_spec


class BoardFeatureBuilder:
    """Build board-level daily features from collected market data."""

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.repo = DailyBoardFeaturesRepository(db)
        self.spec = load_market_daily_spec().strategy["board_feature"]

    def build(self, trade_date: str) -> int:
        """Build and store board features for a trade date."""
        print(f"Building board features for {trade_date}...", flush=True)

        rows = self.db.fetchall(
            """
            SELECT
                trade_date,
                board_name,
                board_type,
                pct_chg,
                up_count,
                down_count,
                leader_symbol,
                leader_name,
                leader_pct_chg,
                source
            FROM daily_board_quotes
            WHERE trade_date = ?
            ORDER BY board_type, board_name
            """,
            (trade_date,),
        )
        if not rows:
            print(f"No daily_board_quotes found for {trade_date}", flush=True)
            return 0

        records: List[Dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            record = self._build_record(dict(row), trade_date)
            records.append(record)
            if index <= 3:
                print(
                    f"[sample {index}] {record['board_type']}:{record['board_name']} "
                    f"board_score={record['board_score']} phase={record['phase_hint']}",
                    flush=True,
                )

        unique_keys = self.repo.get_unique_keys()
        count = self.repo.upsert_many(records, unique_keys)
        print(f"Stored {count} board features for {trade_date}", flush=True)
        return count

    def _build_record(self, row: Dict[str, Any], trade_date: str) -> Dict[str, Any]:
        board_name = row["board_name"]
        board_type = row.get("board_type")
        pct_chg = self._to_float(row.get("pct_chg"))
        up_count = self._to_int(row.get("up_count"))
        down_count = self._to_int(row.get("down_count"))
        leader_pct_chg = self._to_float(row.get("leader_pct_chg"))

        member_metrics = self._get_board_member_metrics(
            trade_date=trade_date,
            board_name=board_name,
            board_type=board_type,
        )
        news_metrics = self._get_board_news_metrics(
            trade_date=trade_date,
            board_name=board_name,
            board_type=board_type,
        )
        continuity_score = self._compute_continuity_score(
            trade_date=trade_date,
            board_name=board_name,
            board_type=board_type,
        )

        breadth_score = self._compute_breadth_score(
            pct_chg=pct_chg,
            up_count=up_count,
            down_count=down_count,
        )
        dragon_strength = self._compute_dragon_strength(
            leader_pct_chg=leader_pct_chg,
            max_streak=member_metrics["max_streak"],
            limit_up_count=member_metrics["limit_up_count"],
        )
        center_strength = self._compute_center_strength(
            total_amount=member_metrics["total_amount"],
            top_amount=member_metrics["top_amount"],
        )
        board_score = self._compute_board_score(
            pct_chg=pct_chg,
            breadth_score=breadth_score,
            limit_up_count=member_metrics["limit_up_count"],
            dragon_strength=dragon_strength,
            center_strength=center_strength,
            continuity_score=continuity_score,
            news_heat_score=news_metrics["news_heat_score"],
        )
        phase_hint = self._infer_phase_hint(
            board_score=board_score,
            pct_chg=pct_chg,
            limit_up_count=member_metrics["limit_up_count"],
            continuity_score=continuity_score,
        )

        feature_json = json.dumps(
            {
                "leader_symbol": row.get("leader_symbol"),
                "leader_name": row.get("leader_name"),
                "leader_pct_chg": leader_pct_chg,
                "source": row.get("source"),
                "member_stock_count": member_metrics["member_stock_count"],
                "total_amount": member_metrics["total_amount"],
            },
            ensure_ascii=False,
        )

        return {
            "trade_date": trade_date,
            "board_name": board_name,
            "board_type": board_type,
            "pct_chg": pct_chg,
            "up_count": up_count,
            "down_count": down_count,
            "limit_up_count": member_metrics["limit_up_count"],
            "core_stock_count": member_metrics["core_stock_count"],
            "news_count": news_metrics["news_count"],
            "news_heat_score": news_metrics["news_heat_score"],
            "dragon_strength": dragon_strength,
            "center_strength": center_strength,
            "breadth_score": breadth_score,
            "continuity_score": continuity_score,
            "board_score": board_score,
            "phase_hint": phase_hint,
            "feature_json": feature_json,
        }

    def _get_board_member_metrics(
        self,
        trade_date: str,
        board_name: str,
        board_type: str,
    ) -> Dict[str, Any]:
        if board_type != "industry_csrc":
            return {
                "member_stock_count": 0,
                "limit_up_count": 0,
                "core_stock_count": 0,
                "max_streak": 0,
                "total_amount": 0.0,
                "top_amount": 0.0,
            }

        rows = self.db.fetchall(
            """
            SELECT
                q.symbol,
                q.amount,
                q.pct_chg,
                COALESCE(l.limit_up, 0) AS limit_up,
                COALESCE(l.limit_up_streak, 0) AS limit_up_streak
            FROM stock_board_membership m
            JOIN daily_stock_quotes q
              ON m.trade_date = q.trade_date
             AND m.symbol = q.symbol
            LEFT JOIN daily_stock_limits l
              ON q.trade_date = l.trade_date
             AND q.symbol = l.symbol
            WHERE m.trade_date = ?
              AND m.board_name = ?
              AND m.board_type = ?
            """,
            (trade_date, board_name, board_type),
        )
        if not rows:
            return {
                "member_stock_count": 0,
                "limit_up_count": 0,
                "core_stock_count": 0,
                "max_streak": 0,
                "total_amount": 0.0,
                "top_amount": 0.0,
            }

        amounts = [self._to_float(row["amount"]) or 0.0 for row in rows]
        limit_ups = [self._to_int(row["limit_up"]) or 0 for row in rows]
        streaks = [self._to_int(row["limit_up_streak"]) or 0 for row in rows]
        pct_chgs = [self._to_float(row["pct_chg"]) or 0.0 for row in rows]

        core_stock_count = sum(
            1
            for pct, amount, limit_up in zip(pct_chgs, amounts, limit_ups)
            if limit_up or pct >= 5 or amount >= 2_000_000_000
        )

        return {
            "member_stock_count": len(rows),
            "limit_up_count": sum(limit_ups),
            "core_stock_count": core_stock_count,
            "max_streak": max(streaks) if streaks else 0,
            "total_amount": round(sum(amounts), 2),
            "top_amount": round(max(amounts) if amounts else 0.0, 2),
        }

    def _get_board_news_metrics(self, trade_date: str, board_name: str, board_type: str | None) -> Dict[str, Any]:
        if board_type == "industry_csrc":
            return self._get_industry_board_news_metrics(trade_date, board_name)
        return self._get_theme_board_news_metrics(trade_date, board_name)

    def _get_industry_board_news_metrics(self, trade_date: str, board_name: str) -> Dict[str, Any]:
        start_ts, end_ts = self._day_ts_range(trade_date)
        row = self.db.fetchone(
            """
            SELECT
                COUNT(DISTINCT ni.id) AS news_count,
                COUNT(DISTINCT nis.symbol) AS core_symbol_count,
                COUNT(DISTINCT CASE WHEN ni.source = 'jygs' THEN ni.id END) AS jygs_news_count
            FROM stock_board_membership m
            JOIN news_item_symbols nis
              ON m.symbol = nis.symbol
            JOIN news_items ni
              ON nis.news_id = ni.id
            WHERE m.trade_date = ?
              AND m.board_name = ?
              AND m.board_type = 'industry_csrc'
              AND ni.publish_ts >= ?
              AND ni.publish_ts < ?
            """,
            (trade_date, board_name, start_ts, end_ts),
        )
        news_count = int(row["news_count"]) if row and row["news_count"] is not None else 0
        core_symbol_count = int(row["core_symbol_count"]) if row and row["core_symbol_count"] is not None else 0
        jygs_news_count = int(row["jygs_news_count"]) if row and row["jygs_news_count"] is not None else 0
        news_heat_score = min(news_count * 6.0 + core_symbol_count * 8.0 + jygs_news_count * 6.0, 100.0)
        return {
            "news_count": news_count,
            "news_heat_score": round(news_heat_score, 2),
        }

    def _get_theme_board_news_metrics(self, trade_date: str, board_name: str) -> Dict[str, Any]:
        start_ts, end_ts = self._day_ts_range(trade_date)
        row = self.db.fetchone(
            """
            SELECT
                COUNT(DISTINCT ni.id) AS news_count
            FROM news_items ni
            JOIN news_item_themes nit
              ON ni.id = nit.news_id
            WHERE ni.publish_ts >= ?
              AND ni.publish_ts < ?
              AND nit.theme_name = ?
            """,
            (start_ts, end_ts, board_name),
        )
        news_count = int(row["news_count"]) if row and row["news_count"] is not None else 0
        news_heat_score = min(news_count * 10.0, 100.0)
        return {
            "news_count": news_count,
            "news_heat_score": round(news_heat_score, 2),
        }

    def _compute_continuity_score(
        self,
        trade_date: str,
        board_name: str,
        board_type: str,
    ) -> float:
        rows = self.db.fetchall(
            """
            SELECT pct_chg
            FROM daily_board_quotes
            WHERE board_name = ?
              AND board_type = ?
              AND trade_date < ?
            ORDER BY trade_date DESC
            LIMIT 5
            """,
            (board_name, board_type, trade_date),
        )
        if not rows:
            return 0.0
        pct_values = [self._to_float(row["pct_chg"]) or 0.0 for row in rows]
        positive_count = sum(1 for value in pct_values if value > 0)
        avg_pct = sum(pct_values) / len(pct_values)
        score = positive_count * 15 + max(min(avg_pct * 5, 25), -10)
        return round(max(score, 0.0), 2)

    def _compute_breadth_score(
        self,
        pct_chg: float | None,
        up_count: int | None,
        down_count: int | None,
    ) -> float:
        pct_score = max(min((pct_chg or 0.0) * 8, 40), -20)
        up = up_count or 0
        down = down_count or 0
        total = up + down
        breadth_ratio = (up / total) if total > 0 else 0.0
        breadth_ratio_score = breadth_ratio * 60
        return round(max(pct_score + breadth_ratio_score, 0.0), 2)

    def _compute_dragon_strength(
        self,
        leader_pct_chg: float | None,
        max_streak: int,
        limit_up_count: int,
    ) -> float:
        score = max((leader_pct_chg or 0.0) * 2.5, 0.0)
        score += max_streak * 12
        score += min(limit_up_count * 4, 20)
        return round(min(score, 100.0), 2)

    def _compute_center_strength(self, total_amount: float, top_amount: float) -> float:
        score = min(total_amount / 8_000_000_000, 50.0)
        score += min(top_amount / 2_000_000_000, 50.0)
        return round(min(score, 100.0), 2)

    def _compute_board_score(
        self,
        pct_chg: float | None,
        breadth_score: float,
        limit_up_count: int,
        dragon_strength: float,
        center_strength: float,
        continuity_score: float,
        news_heat_score: float,
    ) -> float:
        pct_value = pct_chg or 0.0
        pct_strength = max(min((pct_chg or 0.0) * 10, 100.0), -30.0)
        limit_strength = min(limit_up_count * 8, 100.0)
        weights = self.spec["weights"]
        board_score = (
            float(weights["pct_strength"]) * max(pct_strength, 0.0)
            + float(weights["limit_strength"]) * limit_strength
            + float(weights["breadth_score"]) * breadth_score
            + float(weights["news_heat_score"]) * news_heat_score
            + float(weights["dragon_strength"]) * dragon_strength
            + float(weights["center_strength"]) * center_strength
            + float(weights["continuity_score"]) * continuity_score
        )
        penalties = self.spec["negative_pct_penalties"]
        if pct_value < 0:
            board_score *= float(penalties["pct_lt_0"])
        if pct_value <= -1.5:
            board_score *= float(penalties["pct_lte_neg_1_5"])
        if limit_up_count <= 1 and pct_value < 0:
            board_score *= float(penalties["limit_up_lte_1_and_pct_lt_0"])
        return round(board_score, 2)

    def _infer_phase_hint(
        self,
        board_score: float,
        pct_chg: float | None,
        limit_up_count: int,
        continuity_score: float,
    ) -> str:
        pct_chg = pct_chg or 0.0
        thresholds = self.spec["phase_thresholds"]
        fade = thresholds["fade"]
        if pct_chg < float(fade["pct_chg_lt"]) and limit_up_count <= int(fade["limit_up_count_lte"]):
            return "fade"
        if pct_chg < float(fade["pct_chg_lt"]) and continuity_score < float(fade["continuity_score_lt"]):
            return "fade"
        accelerate = thresholds["accelerate"]
        if (
            board_score >= float(accelerate["board_score_gte"])
            and limit_up_count >= int(accelerate["limit_up_count_gte"])
            and continuity_score >= float(accelerate["continuity_score_gte"])
        ):
            return "accelerate"
        expand_primary = thresholds["expand_primary"]
        if (
            board_score >= float(expand_primary["board_score_gte"])
            and limit_up_count >= int(expand_primary["limit_up_count_gte"])
            and pct_chg >= float(expand_primary["pct_chg_gte"])
        ):
            return "expand"
        expand_secondary = thresholds["expand_secondary"]
        if board_score >= float(expand_secondary["board_score_gte"]) and pct_chg > float(expand_secondary["pct_chg_gt"]):
            return "expand"
        start_primary = thresholds["start_primary"]
        if (
            board_score >= float(start_primary["board_score_gte"])
            and limit_up_count >= int(start_primary["limit_up_count_gte"])
            and pct_chg >= float(start_primary["pct_chg_gte"])
        ):
            return "start"
        start_secondary = thresholds["start_secondary"]
        if board_score >= float(start_secondary["board_score_gte"]) and pct_chg > float(start_secondary["pct_chg_gt"]):
            return "start"
        return "fade"

    def _day_ts_range(self, trade_date: str) -> Tuple[int, int]:
        start_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start_ts = int(start_dt.timestamp())
        end_ts = int((start_dt + pd.Timedelta(days=1)).timestamp())
        return start_ts, end_ts

    def _to_float(self, value: Any) -> float | None:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _to_int(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(float(value))
        except Exception:
            return None
