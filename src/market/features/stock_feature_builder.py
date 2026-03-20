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


class StockFeatureBuilder:
    """Build stock-level daily features from collected market data."""

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.repo = DailyStockFeaturesRepository(db)

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
        board_score_ref = self._to_float(row.get("board_score_ref")) or 0.0

        days_in_limit_up_last_20 = self._count_limit_up_days(trade_date, symbol, 20)
        news_metrics = self._get_stock_news_metrics(trade_date, symbol)
        pct_chg_3d = self._get_window_return(trade_date, symbol, 3)
        pct_chg_5d = self._get_window_return(trade_date, symbol, 5)
        amount_rank_in_board = amount_rank_by_board.get((board_name or "", symbol), 0)

        dragon_score = self._compute_dragon_score(
            pct_chg=pct_chg,
            limit_up=limit_up,
            limit_up_streak=limit_up_streak,
            board_score_ref=board_score_ref,
            news_heat_score=news_metrics["news_heat_score"],
            jygs_signal_score=news_metrics["jygs_signal_score"],
            board_phase_hint=board_phase_hint,
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
        )
        follow_score = self._compute_follow_score(
            pct_chg=pct_chg,
            board_score_ref=board_score_ref,
            days_in_limit_up_last_20=days_in_limit_up_last_20,
            pct_chg_3d=pct_chg_3d,
            board_phase_hint=board_phase_hint,
            limit_up=limit_up,
            jygs_signal_score=news_metrics["jygs_signal_score"],
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
        final_score = self._compute_final_score(
            role_tag=role_tag,
            dragon_score=dragon_score,
            center_score=center_score,
            follow_score=follow_score,
            board_score_ref=board_score_ref,
            news_heat_score=news_metrics["news_heat_score"],
            risk_score=risk_score,
        )

        feature_json = json.dumps(
            {
                "pct_chg_3d": pct_chg_3d,
                "pct_chg_5d": pct_chg_5d,
                "amount_rank_in_board": amount_rank_in_board,
                "close": self._to_float(row.get("close")),
                "days_in_limit_up_last_20": days_in_limit_up_last_20,
                "board_phase_hint": board_phase_hint,
                "jygs_signal_score": news_metrics["jygs_signal_score"],
                "jygs_signal_flags": news_metrics["jygs_signal_flags"],
                "jygs_reason_summary": news_metrics["jygs_reason_summary"],
                "jygs_theme_names": news_metrics["jygs_theme_names"],
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
            "role_tag": role_tag,
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
        if len(rows) < 2:
            return None
        latest = self._to_float(rows[0]["close"])
        oldest = self._to_float(rows[-1]["close"])
        if latest is None or oldest in (None, 0):
            return None
        return round((latest - oldest) / oldest * 100, 4)

    def _compute_dragon_score(
        self,
        pct_chg: float,
        limit_up: int,
        limit_up_streak: int,
        board_score_ref: float,
        news_heat_score: float,
        jygs_signal_score: float,
        board_phase_hint: str | None,
    ) -> float:
        score = max(pct_chg * 4, 0.0)
        score += limit_up * 25
        score += limit_up_streak * 15
        score += board_score_ref * 0.25
        score += news_heat_score * 0.1
        score += jygs_signal_score * 0.12
        if board_phase_hint == "fade":
            score *= 0.55
        elif board_phase_hint == "start":
            score *= 1.08
        elif board_phase_hint == "accelerate":
            score *= 1.12
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
    ) -> float:
        amount_score = min(amount / 2_000_000_000, 45.0)
        mv_score = 0.0
        if 20_000_000_000 <= total_mv <= 500_000_000_000:
            mv_score = 25.0
        elif total_mv > 500_000_000_000:
            mv_score = 18.0
        rank_bonus = 12.0 if 0 < amount_rank_in_board <= 3 else 6.0 if 0 < amount_rank_in_board <= 8 else 0.0
        trend_bonus = max((pct_chg_3d or 0.0) * 1.2, 0.0)
        score = (
            amount_score
            + mv_score
            + rank_bonus
            + max(pct_chg * 2, 0.0)
            + trend_bonus
            + board_score_ref * 0.15
            + news_heat_score * 0.05
            + jygs_signal_score * 0.04
        )
        if board_phase_hint == "fade":
            score *= 0.72
        elif board_phase_hint == "start":
            score *= 1.05
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
    ) -> float:
        recent_momentum = pct_chg_3d or 0.0
        freshness_bonus = max(12 - days_in_limit_up_last_20 * 2, 0.0)
        score = (
            max(pct_chg * 3, 0.0)
            + board_score_ref * 0.22
            + max(recent_momentum * 1.5, 0.0)
            + freshness_bonus
            + jygs_signal_score * 0.08
        )
        if limit_up:
            score += 8
        if board_phase_hint == "fade":
            score *= 0.58
        elif board_phase_hint == "start":
            score *= 1.08
        elif board_phase_hint == "accelerate":
            score *= 1.12
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
        flags: List[str] = []
        if limit_up_streak >= 3:
            flags.append("high_streak")
        if turnover >= 0.20:
            flags.append("high_turnover")
        if amplitude >= 12:
            flags.append("high_amplitude")
        if pct_chg >= 9 and board_score_ref < 40:
            flags.append("isolated_spike")
        if pct_chg <= -5:
            flags.append("weak_close")
        if board_phase_hint == "fade" and pct_chg > 0:
            flags.append("fading_board")
        return flags

    def _compute_risk_score(self, risk_flags: List[str]) -> float:
        weights = {
            "high_streak": 18.0,
            "high_turnover": 12.0,
            "high_amplitude": 10.0,
            "isolated_spike": 15.0,
            "weak_close": 10.0,
            "fading_board": 12.0,
        }
        score = sum(weights.get(flag, 0.0) for flag in risk_flags)
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
        dragon_allowed = (
            (limit_up == 1 or limit_up_streak >= 1)
            and board_phase_hint in {"start", "expand", "accelerate"}
            and "fading_board" not in risk_flags
        )
        center_allowed = (
            amount >= 2_000_000_000
            and amount_rank_in_board > 0
            and amount_rank_in_board <= 8
            and (pct_chg_3d or 0.0) > 0
            and board_phase_hint in {"start", "expand", "accelerate"}
        )
        follow_allowed = (
            board_phase_hint in {"start", "expand", "accelerate"}
            and ((pct_chg_3d or 0.0) > 0 or pct_chg_3d is None)
            and "fading_board" not in risk_flags
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
        if scores[role_tag] < 20:
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
        score = role_score + board_score_ref * 0.2 + news_heat_score * 0.1 - risk_score
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
