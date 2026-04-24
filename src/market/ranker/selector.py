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
from src.specs import load_market_daily_spec
from .board_ranker import BoardRanker
from .stock_ranker import StockRanker


class ObservationPoolSelector:
    """Select the daily observation pool from ranked features."""

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.repo = DailyObservationPoolRepository(db)
        self.board_ranker = BoardRanker(db)
        self.stock_ranker = StockRanker(db)
        strategy = load_market_daily_spec().strategy
        self.spec = strategy["observation_pool"]
        self.strong_spec = strategy["strong_stock_pool"]

    def build(self, trade_date: str) -> int:
        print(f"Selecting observation pool for {trade_date}...", flush=True)

        board_rows = self.board_ranker.rank(trade_date)
        stock_rows = self.stock_ranker.rank(trade_date)
        if not stock_rows:
            print(f"No stock features found for {trade_date}", flush=True)
            return 0

        self.db.execute(
            "DELETE FROM daily_observation_pool WHERE trade_date = ?",
            (trade_date,),
        )

        board_rank_map = {
            (row["board_name"], row["board_type"]): row
            for row in board_rows
        }
        candidates = self._strong_candidates(stock_rows)
        main_limit = int(self.strong_spec["selection"]["main_pool_limit"])
        backup_size = int(self.strong_spec["selection"]["backup_size"])
        main_pool_group = str(self.strong_spec["selection"]["main_pool_group"])
        selected = [
            self._build_pool_record(
                trade_date=trade_date,
                stock_row=candidate,
                board_rank_map=board_rank_map,
                pool_group=main_pool_group,
            )
            for candidate in candidates[:main_limit]
        ]
        backup_candidates = [
            self._build_pool_record(
                trade_date=trade_date,
                stock_row=candidate,
                board_rank_map=board_rank_map,
                pool_group="backup",
            )
            for candidate in candidates[main_limit: main_limit + backup_size]
        ]

        records = selected + backup_candidates
        unique_keys = self.repo.get_unique_keys()
        count = self.repo.upsert_many(records, unique_keys)

        role_summary = self._role_summary(selected)
        print(
            f"Stored {count} observation pool rows for {trade_date}; "
            f"{main_pool_group}={len(selected)} backup={len(backup_candidates)} roles={role_summary}",
            flush=True,
        )
        return count

    def _strong_candidates(self, stock_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates = []
        for row in stock_rows:
            strong_metrics = self._strong_metrics(row)
            if not (
                strong_metrics.get("trend_channel_hit")
                or strong_metrics.get("emotion_channel_hit")
            ):
                continue
            enriched = dict(row)
            enriched["strong_metrics"] = strong_metrics
            candidates.append(enriched)
        return sorted(
            candidates,
            key=lambda row: (
                -float(row.get("final_score") or 0.0),
                -float(row.get("amount") or 0.0),
                str(row.get("symbol") or ""),
            ),
        )

    def _strong_metrics(self, stock_row: Dict[str, Any]) -> Dict[str, Any]:
        feature_json = stock_row.get("feature_json")
        if not feature_json:
            return {}
        try:
            feature_data = json.loads(feature_json)
        except Exception:
            return {}
        metrics = feature_data.get("strong_metrics")
        return metrics if isinstance(metrics, dict) else {}

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

    def _can_select(
        self,
        board_key: Tuple[str | None, str | None],
        role_tag: str | None,
        board_counts: Dict[Tuple[str | None, str | None], int],
        board_role_counts: Dict[Tuple[str | None, str | None, str], int],
    ) -> bool:
        if board_key[0] is None:
            return True
        if board_counts.get(board_key, 0) >= int(self.spec["max_per_board"]):
            return False
        if role_tag is None:
            return True
        role_key = (board_key[0], board_key[1], role_tag)
        if board_role_counts.get(role_key, 0) >= int(self.spec["max_per_board_role"]):
            return False
        return True

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
        if role_tag == "trend_strong":
            parts.append("趋势强势候选")
        elif role_tag == "emotion_strong":
            parts.append("情绪强势候选")
        elif role_tag == "dragon":
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
        feature_json = stock_row.get("feature_json")
        if feature_json:
            try:
                feature_data = json.loads(feature_json)
            except Exception:
                feature_data = {}
            jygs_themes = feature_data.get("jygs_theme_names") or []
            jygs_reason = feature_data.get("jygs_reason_summary") or ""
            jygs_signal_flags = feature_data.get("jygs_signal_flags") or []
            effective_limit_reason = feature_data.get("effective_limit_reason") or ""
            effective_reason_source = feature_data.get("effective_reason_source") or ""
            if jygs_themes:
                parts.append(f"韭菜公社题材={','.join(jygs_themes[:3])}")
            if "core_signal" in jygs_signal_flags:
                parts.append("韭菜公社=核心信号")
            elif "follow_signal" in jygs_signal_flags:
                parts.append("韭菜公社=扩散信号")
            if effective_limit_reason:
                if effective_reason_source.startswith("jygs"):
                    parts.append(f"涨停原因(韭菜公社)={effective_limit_reason[:60]}")
                else:
                    parts.append(f"涨停原因={effective_limit_reason[:60]}")
            if jygs_reason:
                parts.append(f"异动逻辑={jygs_reason[:60]}")
            hot_rank_em = feature_data.get("hot_rank_em")
            hot_up_rank_em = feature_data.get("hot_up_rank_em")
            attention_score = feature_data.get("attention_score")
            is_new_high_ths = feature_data.get("is_new_high_ths")
            consecutive_up_days_ths = feature_data.get("consecutive_up_days_ths")
            breakout_labels = feature_data.get("breakout_labels_ths") or []
            if hot_rank_em:
                parts.append(f"东财热股排名={hot_rank_em}")
            if hot_up_rank_em:
                parts.append(f"东财飙升排名={hot_up_rank_em}")
            if is_new_high_ths:
                parts.append("THS=创新高")
            if consecutive_up_days_ths:
                parts.append(f"THS连涨={consecutive_up_days_ths}天")
            if breakout_labels:
                parts.append(f"THS突破={','.join(str(item) for item in breakout_labels[:2])}")
            if attention_score:
                parts.append(f"热度分={round(float(attention_score), 2)}")
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
        feature_json = stock_row.get("feature_json")
        if feature_json:
            try:
                feature_data = json.loads(feature_json)
            except Exception:
                feature_data = {}
            jygs_signal_flags = feature_data.get("jygs_signal_flags") or []
            effective_reason_source = feature_data.get("effective_reason_source") or ""
            if "core_signal" in jygs_signal_flags:
                points.append("结合韭菜公社核心信号看承接强度")
            if "risk_signal" in jygs_signal_flags:
                points.append("韭菜公社提示博弈/分歧风险")
            if effective_reason_source.startswith("jygs"):
                points.append("优先按韭菜公社涨停逻辑跟踪是否兑现")
            hot_rank_em = feature_data.get("hot_rank_em")
            is_new_high_ths = feature_data.get("is_new_high_ths")
            consecutive_up_days_ths = feature_data.get("consecutive_up_days_ths")
            breakout_labels = feature_data.get("breakout_labels_ths") or []
            if hot_rank_em and int(hot_rank_em) <= 20:
                points.append("留意东财热股前排是否继续强化")
            if is_new_high_ths:
                points.append("观察创新高后是否继续放量承接")
            if consecutive_up_days_ths and int(consecutive_up_days_ths) >= 3:
                points.append("留意连续上涨后是否出现分歧")
            if breakout_labels:
                points.append("观察均线突破后的回踩确认")
        return "；".join(points)

    def _role_summary(self, records: List[Dict[str, Any]]) -> str:
        summary: Dict[str, int] = {}
        for record in records:
            role_tag = record.get("role_tag") or "unknown"
            summary[role_tag] = summary.get(role_tag, 0) + 1
        return json.dumps(summary, ensure_ascii=False)
