"""
Daily stock feature builder.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd

from src.db import (
    DatabaseConnection,
    DailyStockFeaturesRepository,
)
from src.specs import load_market_daily_spec


class StockFeatureBuilder:
    """Build stock-level daily features from collected market data."""

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.repo = DailyStockFeaturesRepository(db)
        strategy = load_market_daily_spec().strategy
        self.spec = strategy["stock_feature"]
        self.strong_spec = strategy["strong_stock_pool"]

    def build(self, trade_date: str) -> int:
        """Build and store stock features for a trade date."""
        print(f"Building stock features for {trade_date}...", flush=True)

        rows = self.db.fetchall(
            """
            SELECT
                q.trade_date,
                q.symbol,
                q.name,
                q.pct_chg,
                q.amount,
                q.turnover,
                q.amplitude,
                q.total_mv,
                q.circ_mv,
                q.close,
                l.limit_up,
                l.broken_limit,
                l.limit_up_streak,
                l.limit_reason,
                m.board_name AS primary_board_name,
                m.board_type AS primary_board_type,
                bf.board_score AS board_score_ref,
                bf.phase_hint AS board_phase_hint
            FROM daily_stock_quotes q
            LEFT JOIN daily_stock_limits l
              ON q.trade_date = l.trade_date
             AND q.symbol = l.symbol
            LEFT JOIN stock_board_membership m
              ON q.trade_date = m.trade_date
             AND q.symbol = m.symbol
             AND m.board_type = 'industry_csrc'
            LEFT JOIN daily_board_features bf
              ON m.trade_date = bf.trade_date
             AND m.board_name = bf.board_name
             AND m.board_type = bf.board_type
            WHERE q.trade_date = ?
            ORDER BY q.symbol
            """,
            (trade_date,),
        )
        if not rows:
            print(f"No daily_stock_quotes found for {trade_date}", flush=True)
            return 0

        amount_rank_by_board = self._get_amount_rank_by_board(trade_date)
        records: List[Dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            row_dict = dict(row)
            record = self._build_record(
                row=row_dict,
                trade_date=trade_date,
                amount_rank_by_board=amount_rank_by_board,
            )
            records.append(record)
            if index <= 3:
                print(
                    f"[sample {index}] {record['symbol']} role={record['role_tag']} "
                    f"final_score={record['final_score']} board={record['primary_board_name']}",
                    flush=True,
                )

        unique_keys = self.repo.get_unique_keys()
        count = self.repo.upsert_many(records, unique_keys)
        print(f"Stored {count} stock features for {trade_date}", flush=True)
        return count

    def _build_record(
        self,
        row: Dict[str, Any],
        trade_date: str,
        amount_rank_by_board: Dict[Tuple[str, str], int],
    ) -> Dict[str, Any]:
        symbol = row["symbol"]
        board_name = row.get("primary_board_name")
        board_type = row.get("primary_board_type")
        board_phase_hint = row.get("board_phase_hint")
        pct_chg = self._to_float(row.get("pct_chg")) or 0.0
        amount = self._to_float(row.get("amount")) or 0.0
        turnover = self._to_float(row.get("turnover")) or 0.0
        amplitude = self._to_float(row.get("amplitude")) or 0.0
        total_mv = self._to_float(row.get("total_mv")) or 0.0
        circ_mv = self._to_float(row.get("circ_mv")) or 0.0
        limit_up = self._to_int(row.get("limit_up")) or 0
        broken_limit = self._to_int(row.get("broken_limit")) or 0
        limit_up_streak = self._to_int(row.get("limit_up_streak")) or 0
        limit_reason = (row.get("limit_reason") or "").strip()
        board_score_ref = self._to_float(row.get("board_score_ref")) or 0.0

        days_in_limit_up_last_20 = self._count_limit_up_days(trade_date, symbol, 20)
        news_metrics = self._get_stock_news_metrics(trade_date, symbol)
        attention_metrics = self._get_stock_attention_metrics(trade_date, symbol)
        effective_limit_reason, effective_reason_source = self._resolve_effective_limit_reason(
            base_limit_reason=limit_reason,
            news_metrics=news_metrics,
        )
        pct_chg_3d = self._get_window_return(trade_date, symbol, 3)
        pct_chg_5d = self._get_window_return(trade_date, symbol, 5)
        pct_chg_10d = self._get_window_return(trade_date, symbol, 10)
        pct_chg_20d = self._get_window_return(trade_date, symbol, 20)
        amount_rank_in_board = amount_rank_by_board.get((board_name or "", symbol), 0)
        strong_metrics = self._compute_strong_stock_metrics(
            amount=amount,
            pct_chg_5d=pct_chg_5d,
            pct_chg_10d=pct_chg_10d,
            pct_chg_20d=pct_chg_20d,
            limit_up=limit_up,
            limit_up_streak=limit_up_streak,
        )

        dragon_score = self._compute_dragon_score(
            pct_chg=pct_chg,
            limit_up=limit_up,
            limit_up_streak=limit_up_streak,
            board_score_ref=board_score_ref,
            news_heat_score=news_metrics["news_heat_score"],
            jygs_signal_score=news_metrics["jygs_signal_score"],
            board_phase_hint=board_phase_hint,
            attention_score=attention_metrics["attention_score"],
        )
        center_score = self._compute_center_score(
            pct_chg=pct_chg,
            amount=amount,
            total_mv=total_mv,
            board_score_ref=board_score_ref,
            news_heat_score=news_metrics["news_heat_score"],
            jygs_signal_score=news_metrics["jygs_signal_score"],
            board_phase_hint=board_phase_hint,
            amount_rank_in_board=amount_rank_in_board,
            pct_chg_3d=pct_chg_3d,
            attention_score=attention_metrics["attention_score"],
            tech_bonus=attention_metrics["tech_bonus"],
        )
        follow_score = self._compute_follow_score(
            pct_chg=pct_chg,
            board_score_ref=board_score_ref,
            days_in_limit_up_last_20=days_in_limit_up_last_20,
            pct_chg_3d=pct_chg_3d,
            board_phase_hint=board_phase_hint,
            limit_up=limit_up,
            jygs_signal_score=news_metrics["jygs_signal_score"],
            attention_score=attention_metrics["attention_score"],
        )
        risk_flags = self._build_risk_flags(
            pct_chg=pct_chg,
            turnover=turnover,
            amplitude=amplitude,
            limit_up_streak=limit_up_streak,
            board_score_ref=board_score_ref,
            board_phase_hint=board_phase_hint,
        )
        risk_score = self._compute_risk_score(risk_flags)
        role_tag = self._pick_role_tag(
            dragon_score=dragon_score,
            center_score=center_score,
            follow_score=follow_score,
            limit_up=limit_up,
            limit_up_streak=limit_up_streak,
            board_phase_hint=board_phase_hint,
            amount=amount,
            amount_rank_in_board=amount_rank_in_board,
            pct_chg_3d=pct_chg_3d,
            risk_flags=risk_flags,
        )
        legacy_final_score = self._compute_final_score(
            role_tag=role_tag,
            dragon_score=dragon_score,
            center_score=center_score,
            follow_score=follow_score,
            board_score_ref=board_score_ref,
            news_heat_score=news_metrics["news_heat_score"],
            risk_score=risk_score,
        )
        strong_role_tag = self._pick_strong_role_tag(strong_metrics)
        final_role_tag = strong_role_tag if strong_role_tag != "watchlist" else role_tag
        final_score = strong_metrics["strong_score"]

        feature_json = json.dumps(
            {
                "pct_chg_3d": pct_chg_3d,
                "pct_chg_5d": pct_chg_5d,
                "pct_chg_10d": pct_chg_10d,
                "pct_chg_20d": pct_chg_20d,
                "amount_rank_in_board": amount_rank_in_board,
                "close": self._to_float(row.get("close")),
                "days_in_limit_up_last_20": days_in_limit_up_last_20,
                "legacy_role_tag": role_tag,
                "legacy_final_score": legacy_final_score,
                "board_phase_hint": board_phase_hint,
                "jygs_signal_score": news_metrics["jygs_signal_score"],
                "jygs_signal_flags": news_metrics["jygs_signal_flags"],
                "jygs_reason_summary": news_metrics["jygs_reason_summary"],
                "jygs_theme_names": news_metrics["jygs_theme_names"],
                "attention_score": attention_metrics["attention_score"],
                "hot_rank_em": attention_metrics["hot_rank_em"],
                "hot_up_rank_em": attention_metrics["hot_up_rank_em"],
                "xq_follow_count": attention_metrics["xq_follow_count"],
                "xq_tweet_count": attention_metrics["xq_tweet_count"],
                "is_new_high_ths": attention_metrics["is_new_high_ths"],
                "consecutive_up_days_ths": attention_metrics["consecutive_up_days_ths"],
                "is_breakout_ths": attention_metrics["is_breakout_ths"],
                "breakout_labels_ths": attention_metrics["breakout_labels_ths"],
                "base_limit_reason": limit_reason,
                "effective_limit_reason": effective_limit_reason,
                "effective_reason_source": effective_reason_source,
                "strong_metrics": strong_metrics,
            },
            ensure_ascii=False,
        )

        return {
            "trade_date": trade_date,
            "symbol": symbol,
            "name": row.get("name"),
            "primary_board_name": board_name,
            "primary_board_type": board_type,
            "pct_chg": round(pct_chg, 4),
            "amount": amount,
            "turnover": round(turnover, 6),
            "amplitude": round(amplitude, 4),
            "total_mv": total_mv,
            "circ_mv": circ_mv,
            "limit_up": limit_up,
            "broken_limit": broken_limit,
            "limit_up_streak": limit_up_streak,
            "days_in_limit_up_last_20": days_in_limit_up_last_20,
            "news_count": news_metrics["news_count"],
            "cls_news_count": news_metrics["cls_news_count"],
            "jygs_news_count": news_metrics["jygs_news_count"],
            "news_heat_score": news_metrics["news_heat_score"],
            "board_score_ref": board_score_ref,
            "dragon_score": dragon_score,
            "center_score": center_score,
            "follow_score": follow_score,
            "risk_score": risk_score,
            "final_score": final_score,
            "role_tag": final_role_tag,
            "risk_flags": json.dumps(risk_flags, ensure_ascii=False),
            "feature_json": feature_json,
        }

    def _get_amount_rank_by_board(self, trade_date: str) -> Dict[Tuple[str, str], int]:
        rows = self.db.fetchall(
            """
            SELECT
                m.board_name,
                q.symbol,
                q.amount
            FROM stock_board_membership m
            JOIN daily_stock_quotes q
              ON m.trade_date = q.trade_date
             AND m.symbol = q.symbol
            WHERE m.trade_date = ?
              AND m.board_type = 'industry_csrc'
            ORDER BY m.board_name, q.amount DESC
            """,
            (trade_date,),
        )
        rank_map: Dict[Tuple[str, str], int] = {}
        current_board = None
        rank = 0
        for row in rows:
            board_name = row["board_name"]
            symbol = row["symbol"]
            if board_name != current_board:
                current_board = board_name
                rank = 1
            else:
                rank += 1
            rank_map[(board_name, symbol)] = rank
        return rank_map

    def _count_limit_up_days(self, trade_date: str, symbol: str, lookback: int) -> int:
        row = self.db.fetchone(
            """
            SELECT COUNT(*) AS cnt
            FROM (
                SELECT trade_date
                FROM daily_stock_limits
                WHERE symbol = ?
                  AND limit_up = 1
                  AND trade_date <= ?
                ORDER BY trade_date DESC
                LIMIT ?
            )
            """,
            (symbol, trade_date, lookback),
        )
        return int(row["cnt"]) if row and row["cnt"] is not None else 0

    def _get_stock_news_metrics(self, trade_date: str, symbol: str) -> Dict[str, Any]:
        start_ts, end_ts = self._day_ts_range(trade_date)
        row = self.db.fetchone(
            """
            SELECT
                COUNT(DISTINCT ni.id) AS news_count,
                COUNT(DISTINCT CASE WHEN ni.source = 'cailian' THEN ni.id END) AS cls_news_count,
                COUNT(DISTINCT CASE WHEN ni.source = 'jygs' THEN ni.id END) AS jygs_news_count
            FROM news_items ni
            JOIN news_item_symbols nis
              ON ni.id = nis.news_id
            WHERE ni.publish_ts >= ?
              AND ni.publish_ts < ?
              AND nis.symbol = ?
            """,
            (start_ts, end_ts, symbol),
        )
        if not row:
            return {
                "news_count": 0,
                "cls_news_count": 0,
                "jygs_news_count": 0,
                "news_heat_score": 0.0,
                "jygs_signal_score": 0.0,
                "jygs_signal_flags": [],
                "jygs_reason_summary": "",
                "jygs_theme_names": [],
            }
        news_count = int(row["news_count"] or 0)
        cls_news_count = int(row["cls_news_count"] or 0)
        jygs_news_count = int(row["jygs_news_count"] or 0)
        news_heat_score = min(news_count * 12 + cls_news_count * 6 + jygs_news_count * 8, 100.0)
        jygs_detail = self._get_jygs_signal_details(trade_date, symbol)
        return {
            "news_count": news_count,
            "cls_news_count": cls_news_count,
            "jygs_news_count": jygs_news_count,
            "news_heat_score": round(news_heat_score, 2),
            "jygs_signal_score": jygs_detail["signal_score"],
            "jygs_signal_flags": jygs_detail["signal_flags"],
            "jygs_reason_summary": jygs_detail["reason_summary"],
            "jygs_theme_names": jygs_detail["theme_names"],
        }

    def _resolve_effective_limit_reason(
        self,
        base_limit_reason: str,
        news_metrics: Dict[str, Any],
    ) -> Tuple[str, str]:
        jygs_reason = (news_metrics.get("jygs_reason_summary") or "").strip()
        jygs_themes = news_metrics.get("jygs_theme_names") or []
        if jygs_reason:
            return jygs_reason, "jygs_expound"
        if jygs_themes:
            return " / ".join(jygs_themes[:3]), "jygs_theme"
        if base_limit_reason:
            return base_limit_reason, "limit_reason"
        return "", ""

    def _get_stock_attention_metrics(self, trade_date: str, symbol: str) -> Dict[str, Any]:
        rows = self.db.fetchall(
            """
            SELECT source, metric_type, rank_value, metric_value, pct_chg, extra_json
            FROM daily_stock_attention
            WHERE trade_date = ?
              AND symbol = ?
            """,
            (trade_date, symbol),
        )
        if not rows:
            return {
                "attention_score": 0.0,
                "tech_bonus": 0.0,
                "hot_rank_em": None,
                "hot_up_rank_em": None,
                "xq_follow_count": None,
                "xq_tweet_count": None,
                "is_new_high_ths": 0,
                "consecutive_up_days_ths": 0,
                "is_breakout_ths": 0,
                "breakout_labels_ths": [],
            }

        hot_rank_em = None
        hot_up_rank_em = None
        xq_follow_count = None
        xq_tweet_count = None
        is_new_high_ths = 0
        consecutive_up_days_ths = 0
        is_breakout_ths = 0
        breakout_labels: List[str] = []

        for row in rows:
            metric_type = row["metric_type"] or ""
            rank_value = self._to_float(row["rank_value"])
            metric_value = self._to_float(row["metric_value"])
            extra = {}
            try:
                extra = json.loads(row["extra_json"]) if row["extra_json"] else {}
            except Exception:
                extra = {}

            if metric_type == "hot_rank":
                hot_rank_em = rank_value
            elif metric_type == "hot_up":
                hot_up_rank_em = rank_value
            elif metric_type == "follow_rank":
                xq_follow_count = metric_value
            elif metric_type == "tweet_rank":
                xq_tweet_count = metric_value
            elif metric_type == "ths_new_high":
                is_new_high_ths = 1
            elif metric_type == "ths_consecutive_up":
                consecutive_up_days_ths = max(
                    consecutive_up_days_ths,
                    int(self._to_float(extra.get("连涨天数")) or 0),
                )
            elif metric_type.startswith("ths_breakout_"):
                is_breakout_ths = 1
                breakout_labels.append(metric_type.replace("ths_breakout_", ""))

        attention_score = 0.0
        if hot_rank_em:
            attention_score += max(28.0 - hot_rank_em * 0.18, 0.0)
        if hot_up_rank_em:
            attention_score += max(20.0 - hot_up_rank_em * 0.08, 0.0)
        if xq_follow_count:
            attention_score += min(xq_follow_count / 300000.0, 16.0)
        if xq_tweet_count:
            attention_score += min(xq_tweet_count / 80000.0, 16.0)
        if is_new_high_ths:
            attention_score += 14.0
        if consecutive_up_days_ths:
            attention_score += min(consecutive_up_days_ths * 2.2, 12.0)
        if is_breakout_ths:
            attention_score += 10.0

        tech_bonus = 0.0
        if is_new_high_ths:
            tech_bonus += 10.0
        if is_breakout_ths:
            tech_bonus += 8.0
        if consecutive_up_days_ths >= 3:
            tech_bonus += min(consecutive_up_days_ths * 1.5, 8.0)

        return {
            "attention_score": round(min(attention_score, 100.0), 2),
            "tech_bonus": round(min(tech_bonus, 30.0), 2),
            "hot_rank_em": int(hot_rank_em) if hot_rank_em else None,
            "hot_up_rank_em": int(hot_up_rank_em) if hot_up_rank_em else None,
            "xq_follow_count": int(xq_follow_count) if xq_follow_count else None,
            "xq_tweet_count": int(xq_tweet_count) if xq_tweet_count else None,
            "is_new_high_ths": is_new_high_ths,
            "consecutive_up_days_ths": consecutive_up_days_ths,
            "is_breakout_ths": is_breakout_ths,
            "breakout_labels_ths": list(dict.fromkeys(breakout_labels)),
        }

    def _get_jygs_signal_details(self, trade_date: str, symbol: str) -> Dict[str, Any]:
        start_ts, end_ts = self._day_ts_range(trade_date)
        rows = self.db.fetchall(
            """
            SELECT
                ni.title,
                ni.content,
                ni.raw_json
            FROM news_items ni
            JOIN news_item_symbols nis
              ON ni.id = nis.news_id
            WHERE ni.publish_ts >= ?
              AND ni.publish_ts < ?
              AND ni.source = 'jygs'
              AND nis.symbol = ?
            ORDER BY ni.publish_ts DESC, ni.id DESC
            LIMIT 10
            """,
            (start_ts, end_ts, symbol),
        )
        if not rows:
            return {
                "signal_score": 0.0,
                "signal_flags": [],
                "reason_summary": "",
                "theme_names": [],
            }

        signal_flags = set()
        theme_names = []
        reasons = []
        signal_score = 0.0

        for row in rows:
            title = row["title"] or ""
            content = row["content"] or ""
            raw_json = row["raw_json"] or ""
            signal_score += 8.0

            parsed = {}
            try:
                parsed = json.loads(raw_json) if raw_json else {}
            except Exception:
                parsed = {}

            field_name = (parsed.get("field_name") or "").strip()
            action_num = (parsed.get("action_num") or "").strip()
            expound = (parsed.get("expound") or "").strip()
            parsed_flags = parsed.get("signal_flags") if isinstance(parsed.get("signal_flags"), list) else []

            if field_name:
                theme_names.append(field_name)
            if expound:
                reasons.append(expound)
            elif content:
                parts = [line.strip() for line in content.splitlines() if line.strip()]
                if parts:
                    reasons.append(parts[-1])

            for flag in parsed_flags:
                signal_flags.add(str(flag))

            joined_text = " ".join([title, content, action_num, expound])
            if any(keyword in joined_text for keyword in ["龙头", "核心", "总龙", "辨识度"]):
                signal_flags.add("core_signal")
                signal_score += 10.0
            if any(keyword in joined_text for keyword in ["补涨", "跟涨", "扩散", "分支", "跟风"]):
                signal_flags.add("follow_signal")
                signal_score += 6.0
            if any(keyword in joined_text for keyword in ["首板", "2板", "3板", "4板", "5板", "连板", "反包"]):
                signal_flags.add("streak_signal")
                signal_score += 8.0
            if any(keyword in joined_text for keyword in ["高位", "炸板", "回落", "兑现", "博弈", "分歧"]):
                signal_flags.add("risk_signal")

        reason_summary = "；".join(dict.fromkeys(reason for reason in reasons if reason))[:300]
        return {
            "signal_score": round(min(signal_score, 100.0), 2),
            "signal_flags": sorted(signal_flags),
            "reason_summary": reason_summary,
            "theme_names": list(dict.fromkeys(theme_names)),
        }

    def _get_window_return(self, trade_date: str, symbol: str, window: int) -> float | None:
        rows = self.db.fetchall(
            """
            SELECT close
            FROM daily_stock_quotes
            WHERE symbol = ?
              AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (symbol, trade_date, window),
        )
        if len(rows) < window:
            return None
        latest = self._to_float(rows[0]["close"])
        oldest = self._to_float(rows[-1]["close"])
        if latest is None or oldest in (None, 0):
            return None
        return round((latest - oldest) / oldest * 100, 4)

    def _score_trend_window(self, window: str, pct_chg: float | None) -> float:
        if pct_chg is None:
            return 0.0
        bands = self.strong_spec["trend_channel"]["window_score_bands"][window]
        for band in bands:
            if "lte" not in band or pct_chg <= float(band["lte"]):
                return float(band["score"])
        return 0.0

    def _compute_emotion_score(self, limit_up: int, limit_up_streak: int) -> float:
        config = self.strong_spec["emotion_channel"]
        scores: List[float] = []
        if limit_up:
            scores.append(float(config["limit_up_score"]))
        if limit_up_streak >= 3:
            scores.append(float(config["streak_3_score"]))
        elif limit_up_streak == 2:
            scores.append(float(config["streak_2_score"]))
        return max(scores) if scores else 0.0

    def _compute_capacity_bonus(self, amount: float) -> float:
        for tier in self.strong_spec["capacity_bonus"]:
            if amount >= float(tier["min_amount"]):
                return float(tier["bonus"])
        return 0.0

    def _compute_strong_stock_metrics(
        self,
        amount: float,
        pct_chg_5d: float | None,
        pct_chg_10d: float | None,
        pct_chg_20d: float | None,
        limit_up: int,
        limit_up_streak: int,
    ) -> Dict[str, Any]:
        trend_config = self.strong_spec["trend_channel"]
        emotion_config = self.strong_spec["emotion_channel"]
        window_scores = {
            "5d": self._score_trend_window("5d", pct_chg_5d),
            "10d": self._score_trend_window("10d", pct_chg_10d),
            "20d": self._score_trend_window("20d", pct_chg_20d),
        }
        weights = trend_config["window_weights"]
        trend_score = round(
            window_scores["5d"] * float(weights["5d"])
            + window_scores["10d"] * float(weights["10d"])
            + window_scores["20d"] * float(weights["20d"]),
            2,
        )
        available_windows = [pct_chg_5d, pct_chg_10d, pct_chg_20d]
        medium_count = sum(
            1 for score in window_scores.values()
            if score >= float(trend_config["min_medium_window_score"])
        )
        all_windows_present = all(value is not None for value in available_windows)
        trend_channel_hit = (
            all_windows_present
            and amount >= float(trend_config["min_amount"])
            and trend_score >= float(trend_config["min_trend_score"])
            and medium_count >= int(trend_config["min_medium_window_count"])
            and min(window_scores.values()) >= float(trend_config["min_weak_window_score"])
        )
        emotion_score = self._compute_emotion_score(limit_up, limit_up_streak)
        emotion_channel_hit = (
            amount >= float(emotion_config["min_amount"])
            and emotion_score > 0
        )
        capacity_bonus = self._compute_capacity_bonus(amount)
        labels: List[str] = []
        if trend_channel_hit:
            labels.append("trend_strong")
        if emotion_channel_hit:
            labels.append("emotion_strong")
        if amount >= float(self.strong_spec["capacity_label_min_amount"]):
            labels.append("capacity_strong")
        base_score = max(trend_score if trend_channel_hit else 0.0, emotion_score if emotion_channel_hit else 0.0)
        multi_channel_bonus = float(self.strong_spec["multi_channel_bonus"]) if trend_channel_hit and emotion_channel_hit else 0.0
        strong_score = round(min(base_score + capacity_bonus + multi_channel_bonus, 100.0), 2)
        return {
            "trend_score": trend_score,
            "trend_window_scores": window_scores,
            "trend_channel_hit": trend_channel_hit,
            "emotion_score": emotion_score,
            "emotion_channel_hit": emotion_channel_hit,
            "capacity_bonus": capacity_bonus,
            "multi_channel_bonus": multi_channel_bonus,
            "strong_score": strong_score,
            "labels": labels,
        }

    def _pick_strong_role_tag(self, strong_metrics: Dict[str, Any]) -> str:
        if strong_metrics.get("trend_channel_hit"):
            return "trend_strong"
        if strong_metrics.get("emotion_channel_hit"):
            return "emotion_strong"
        return "watchlist"

    def _compute_dragon_score(
        self,
        pct_chg: float,
        limit_up: int,
        limit_up_streak: int,
        board_score_ref: float,
        news_heat_score: float,
        jygs_signal_score: float,
        board_phase_hint: str | None,
        attention_score: float,
    ) -> float:
        config = self.spec["dragon_score"]
        weights = config["weights"]
        multipliers = config["phase_multipliers"]
        score = max(pct_chg * float(weights["pct_chg"]), 0.0)
        score += limit_up * float(weights["limit_up"])
        score += limit_up_streak * float(weights["limit_up_streak"])
        score += board_score_ref * float(weights["board_score_ref"])
        score += news_heat_score * float(weights["news_heat_score"])
        score += jygs_signal_score * float(weights["jygs_signal_score"])
        score += attention_score * float(weights["attention_score"])
        score *= float(multipliers.get(board_phase_hint or "", multipliers["default"]))
        return round(min(score, 100.0), 2)

    def _compute_center_score(
        self,
        pct_chg: float,
        amount: float,
        total_mv: float,
        board_score_ref: float,
        news_heat_score: float,
        jygs_signal_score: float,
        board_phase_hint: str | None,
        amount_rank_in_board: int,
        pct_chg_3d: float | None,
        attention_score: float,
        tech_bonus: float,
    ) -> float:
        config = self.spec["center_score"]
        amount_score = min(amount / float(config["amount_divisor"]), float(config["amount_score_cap"]))
        mv_score = 0.0
        market_cap_bonuses = config["market_cap_bonuses"]
        if float(market_cap_bonuses["mid_cap_min"]) <= total_mv <= float(market_cap_bonuses["mid_cap_max"]):
            mv_score = float(market_cap_bonuses["mid_cap_bonus"])
        elif total_mv > float(market_cap_bonuses["mid_cap_max"]):
            mv_score = float(market_cap_bonuses["mega_cap_bonus"])
        rank_bonuses = config["rank_bonuses"]
        rank_bonus = (
            float(rank_bonuses["top3_bonus"])
            if 0 < amount_rank_in_board <= 3
            else float(rank_bonuses["top8_bonus"])
            if 0 < amount_rank_in_board <= 8
            else 0.0
        )
        weights = config["weights"]
        trend_bonus = max((pct_chg_3d or 0.0) * float(weights["pct_chg_3d"]), 0.0)
        score = (
            amount_score
            + mv_score
            + rank_bonus
            + max(pct_chg * float(weights["pct_chg"]), 0.0)
            + trend_bonus
            + board_score_ref * float(weights["board_score_ref"])
            + news_heat_score * float(weights["news_heat_score"])
            + jygs_signal_score * float(weights["jygs_signal_score"])
            + attention_score * float(weights["attention_score"])
            + tech_bonus
        )
        multipliers = config["phase_multipliers"]
        score *= float(multipliers.get(board_phase_hint or "", multipliers["default"]))
        return round(min(score, 100.0), 2)

    def _compute_follow_score(
        self,
        pct_chg: float,
        board_score_ref: float,
        days_in_limit_up_last_20: int,
        pct_chg_3d: float | None,
        board_phase_hint: str | None,
        limit_up: int,
        jygs_signal_score: float,
        attention_score: float,
    ) -> float:
        config = self.spec["follow_score"]
        recent_momentum = pct_chg_3d or 0.0
        freshness = config["freshness_bonus"]
        freshness_bonus = max(
            float(freshness["base"])
            - days_in_limit_up_last_20 * float(freshness["days_in_limit_up_last_20_weight"]),
            0.0,
        )
        weights = config["weights"]
        score = (
            max(pct_chg * float(weights["pct_chg"]), 0.0)
            + board_score_ref * float(weights["board_score_ref"])
            + max(recent_momentum * float(weights["pct_chg_3d"]), 0.0)
            + freshness_bonus
            + jygs_signal_score * float(weights["jygs_signal_score"])
            + attention_score * float(weights["attention_score"])
        )
        if limit_up:
            score += float(config["limit_up_bonus"])
        multipliers = config["phase_multipliers"]
        score *= float(multipliers.get(board_phase_hint or "", multipliers["default"]))
        return round(min(score, 100.0), 2)

    def _build_risk_flags(
        self,
        pct_chg: float,
        turnover: float,
        amplitude: float,
        limit_up_streak: int,
        board_score_ref: float,
        board_phase_hint: str | None,
    ) -> List[str]:
        thresholds = self.spec["risk_thresholds"]
        flags: List[str] = []
        if limit_up_streak >= int(thresholds["high_streak_min"]):
            flags.append("high_streak")
        if turnover >= float(thresholds["high_turnover_min"]):
            flags.append("high_turnover")
        if amplitude >= float(thresholds["high_amplitude_min"]):
            flags.append("high_amplitude")
        if (
            pct_chg >= float(thresholds["isolated_spike_pct_min"])
            and board_score_ref < float(thresholds["isolated_spike_board_score_lt"])
        ):
            flags.append("isolated_spike")
        if pct_chg <= float(thresholds["weak_close_pct_lte"]):
            flags.append("weak_close")
        if board_phase_hint == "fade" and pct_chg > 0:
            flags.append("fading_board")
        return flags

    def _compute_risk_score(self, risk_flags: List[str]) -> float:
        weights = self.spec["risk_weights"]
        score = sum(float(weights.get(flag, 0.0)) for flag in risk_flags)
        return round(min(score, 100.0), 2)

    def _pick_role_tag(
        self,
        dragon_score: float,
        center_score: float,
        follow_score: float,
        limit_up: int,
        limit_up_streak: int,
        board_phase_hint: str | None,
        amount: float,
        amount_rank_in_board: int,
        pct_chg_3d: float | None,
        risk_flags: List[str],
    ) -> str:
        rules = self.spec["role_rules"]
        dragon_rule = rules["dragon"]
        center_rule = rules["center"]
        follow_rule = rules["follow"]
        dragon_allowed = (
            (not dragon_rule["require_limit_up_or_streak"] or limit_up == 1 or limit_up_streak >= 1)
            and board_phase_hint in set(dragon_rule["allowed_board_phases"])
            and not any(flag in risk_flags for flag in dragon_rule["disallowed_risk_flags"])
        )
        center_allowed = (
            amount >= float(center_rule["min_amount"])
            and amount_rank_in_board > 0
            and amount_rank_in_board <= int(center_rule["max_amount_rank_in_board"])
            and ((pct_chg_3d or 0.0) > 0 if center_rule["require_positive_3d_return"] else True)
            and board_phase_hint in set(center_rule["allowed_board_phases"])
        )
        follow_return_ok = pct_chg_3d is None and bool(follow_rule["allow_missing_3d_return"])
        if pct_chg_3d is not None:
            follow_return_ok = (pct_chg_3d or 0.0) > 0 if follow_rule["require_non_negative_3d_return"] else True
        follow_allowed = (
            board_phase_hint in set(follow_rule["allowed_board_phases"])
            and follow_return_ok
            and not any(flag in risk_flags for flag in follow_rule["disallowed_risk_flags"])
        )

        scores = {}
        if dragon_allowed:
            scores["dragon"] = dragon_score
        if center_allowed:
            scores["center"] = center_score
        if follow_allowed:
            scores["follow"] = follow_score

        if not scores:
            return "watchlist"
        role_tag = max(scores, key=scores.get)
        if scores[role_tag] < float(rules["watchlist_min_score"]):
            return "watchlist"
        return role_tag

    def _compute_final_score(
        self,
        role_tag: str,
        dragon_score: float,
        center_score: float,
        follow_score: float,
        board_score_ref: float,
        news_heat_score: float,
        risk_score: float,
    ) -> float:
        role_score = {
            "dragon": dragon_score,
            "center": center_score,
            "follow": follow_score,
            "watchlist": max(dragon_score, center_score, follow_score),
        }[role_tag]
        weights = self.spec["final_score_weights"]
        score = (
            role_score
            + board_score_ref * float(weights["board_score_ref"])
            + news_heat_score * float(weights["news_heat_score"])
            - risk_score
        )
        return round(max(score, 0.0), 2)

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
