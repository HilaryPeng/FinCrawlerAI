"""
Observation pool selector.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Set, Tuple

from src.db import (
    DatabaseConnection,
    DailyObservationPoolRepository,
)
from .board_ranker import BoardRanker
from .stock_ranker import StockRanker


class ObservationPoolSelector:
    """Select the daily observation pool from ranked features."""

    ROLE_TARGETS = {
        "dragon": 6,
        "center": 6,
        "follow": 6,
        "watchlist": 2,
    }

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.repo = DailyObservationPoolRepository(db)
        self.board_ranker = BoardRanker(db)
        self.stock_ranker = StockRanker(db)

    def build(self, trade_date: str) -> int:
        print(f"Selecting observation pool for {trade_date}...", flush=True)

        board_rows = self.board_ranker.rank(trade_date)
        stock_rows = self.stock_ranker.rank(trade_date)
        if not stock_rows:
            print(f"No stock features found for {trade_date}", flush=True)
            return 0

        board_rank_map = {
            (row["board_name"], row["board_type"]): row
            for row in board_rows
        }
        top_board_keys = {
            (row["board_name"], row["board_type"])
            for row in board_rows[:10]
        }

        selected: List[Dict[str, Any]] = []
        selected_symbols: Set[str] = set()

        for role_tag, target in self.ROLE_TARGETS.items():
            candidates = self._role_candidates(
                stock_rows=stock_rows,
                role_tag=role_tag,
                top_board_keys=top_board_keys,
            )
            taken = 0
            for candidate in candidates:
                symbol = candidate["symbol"]
                if symbol in selected_symbols:
                    continue
                selected.append(
                    self._build_pool_record(
                        trade_date=trade_date,
                        stock_row=candidate,
                        board_rank_map=board_rank_map,
                        pool_group="top20",
                    )
                )
                selected_symbols.add(symbol)
                taken += 1
                if taken >= target:
                    break

        if len(selected) < 20:
            for candidate in stock_rows:
                symbol = candidate["symbol"]
                if symbol in selected_symbols:
                    continue
                selected.append(
                    self._build_pool_record(
                        trade_date=trade_date,
                        stock_row=candidate,
                        board_rank_map=board_rank_map,
                        pool_group="top20",
                    )
                )
                selected_symbols.add(symbol)
                if len(selected) >= 20:
                    break

        backup_candidates = []
        for candidate in stock_rows:
            symbol = candidate["symbol"]
            if symbol in selected_symbols:
                continue
            backup_candidates.append(
                self._build_pool_record(
                    trade_date=trade_date,
                    stock_row=candidate,
                    board_rank_map=board_rank_map,
                    pool_group="backup",
                )
            )
            if len(backup_candidates) >= 10:
                break

        records = selected + backup_candidates
        unique_keys = self.repo.get_unique_keys()
        count = self.repo.upsert_many(records, unique_keys)

        role_summary = self._role_summary(selected)
        print(
            f"Stored {count} observation pool rows for {trade_date}; "
            f"top20={len(selected)} backup={len(backup_candidates)} roles={role_summary}",
            flush=True,
        )
        return count

    def _role_candidates(
        self,
        stock_rows: List[Dict[str, Any]],
        role_tag: str,
        top_board_keys: Set[Tuple[str | None, str | None]],
    ) -> List[Dict[str, Any]]:
        candidates = [
            row
            for row in stock_rows
            if row.get("role_tag") == role_tag
            and (row.get("primary_board_name"), row.get("primary_board_type")) in top_board_keys
        ]
        if candidates:
            return candidates
        return [row for row in stock_rows if row.get("role_tag") == role_tag]

    def _build_pool_record(
        self,
        trade_date: str,
        stock_row: Dict[str, Any],
        board_rank_map: Dict[Tuple[str | None, str | None], Dict[str, Any]],
        pool_group: str,
    ) -> Dict[str, Any]:
        board_name = stock_row.get("primary_board_name")
        board_type = stock_row.get("primary_board_type")
        board_row = board_rank_map.get((board_name, board_type), {})
        board_rank = board_row.get("board_rank")
        phase_hint = board_row.get("phase_hint")
        board_score = board_row.get("board_score")

        selected_reason = self._build_selected_reason(stock_row, board_rank, board_score, phase_hint)
        watch_points = self._build_watch_points(stock_row, phase_hint)

        return {
            "trade_date": trade_date,
            "symbol": stock_row["symbol"],
            "name": stock_row.get("name"),
            "role_tag": stock_row.get("role_tag"),
            "board_name": board_name,
            "board_rank": board_rank,
            "stock_rank": stock_row.get("stock_rank"),
            "final_score": stock_row.get("final_score"),
            "selected_reason": selected_reason,
            "watch_points": watch_points,
            "risk_flags": stock_row.get("risk_flags"),
            "pool_group": pool_group,
        }

    def _build_selected_reason(
        self,
        stock_row: Dict[str, Any],
        board_rank: int | None,
        board_score: float | None,
        phase_hint: str | None,
    ) -> str:
        parts = []
        role_tag = stock_row.get("role_tag")
        if role_tag == "dragon":
            parts.append("高强度龙头候选")
        elif role_tag == "center":
            parts.append("容量中军候选")
        elif role_tag == "follow":
            parts.append("板块扩散跟随候选")
        else:
            parts.append("观察补位候选")

        board_name = stock_row.get("primary_board_name")
        if board_name:
            parts.append(f"所属板块={board_name}")
        if board_rank:
            parts.append(f"板块排名={board_rank}")
        if board_score is not None:
            parts.append(f"板块分={round(float(board_score), 2)}")
        if phase_hint:
            parts.append(f"阶段={phase_hint}")
        parts.append(f"总分={stock_row.get('final_score')}")
        return "；".join(parts)

    def _build_watch_points(self, stock_row: Dict[str, Any], phase_hint: str | None) -> str:
        points = []
        if stock_row.get("role_tag") == "dragon":
            points.append("观察是否继续涨停或维持高辨识度")
        elif stock_row.get("role_tag") == "center":
            points.append("观察成交额与趋势承接是否延续")
        elif stock_row.get("role_tag") == "follow":
            points.append("观察是否获得主线扩散承接")
        else:
            points.append("观察是否从观察股转强")

        if phase_hint == "accelerate":
            points.append("留意加速后分歧风险")
        elif phase_hint == "fade":
            points.append("留意板块热度回落")
        return "；".join(points)

    def _role_summary(self, records: List[Dict[str, Any]]) -> str:
        summary: Dict[str, int] = {}
        for record in records:
            role_tag = record.get("role_tag") or "unknown"
            summary[role_tag] = summary.get(role_tag, 0) + 1
        return json.dumps(summary, ensure_ascii=False)
