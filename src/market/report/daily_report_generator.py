"""
Daily market report generator.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from config.settings import get_config
from src.db import DatabaseConnection
from src.specs import load_market_daily_spec


class DailyReportGenerator:
    """Generate JSON and Markdown daily reports."""

    CSRC_DISPLAY_NAMES = {
        "C39计算机、通信和其他电子设备制造业": "电子设备制造",
        "C38电气机械和器材制造业": "电气机械",
        "C32有色金属冶炼和压延加工业": "有色金属",
        "K70房地产业": "房地产",
    }
    RISK_LABELS = {
        "weak_close": "弱收盘",
        "high_turnover": "高换手",
        "fading_board": "板块退潮",
        "isolated_spike": "孤立冲高",
        "broken_limit": "炸板",
    }

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.config = get_config()
        self.output_dir = self.config.PROCESSED_DATA_DIR / "market_daily"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        spec = load_market_daily_spec()
        self.presentation = spec.presentation
        self.role_labels = self.presentation["roles"]

    def generate(self, trade_date: str) -> Dict[str, str]:
        report_data = self._build_report_data(trade_date)
        json_path = self._write_json(report_data, trade_date)
        md_path = self._write_markdown(report_data, trade_date)
        html_path = self._write_html(report_data, trade_date)
        return {
            "json_path": str(json_path),
            "markdown_path": str(md_path),
            "html_path": str(html_path),
        }

    def _build_report_data(self, trade_date: str) -> Dict[str, Any]:
        market_summary = self._get_market_summary(trade_date)
        top_boards = self._get_top_boards(trade_date)
        observation_pool = self._get_observation_pool(trade_date)
        backup_pool = self._get_observation_pool(trade_date, pool_group="backup")
        role_summary = self._get_pool_role_summary(trade_date)
        board_distribution = self._get_pool_board_distribution(trade_date)
        strong_board_summary = self._get_strong_board_summary(trade_date)
        observation_pool = self._decorate_observation_rows(observation_pool)
        backup_pool = self._decorate_observation_rows(backup_pool)
        environment = self._compute_environment(market_summary, observation_pool)
        mainlines = self._build_mainlines(top_boards, strong_board_summary, observation_pool)

        return {
            "metadata": {
                "trade_date": trade_date,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "report_type": "market_daily",
            },
            "market_summary": market_summary,
            "top_boards": top_boards,
            "observation_pool": observation_pool,
            "backup_pool": backup_pool,
            "role_summary": role_summary,
            "board_distribution": board_distribution,
            "strong_board_summary": strong_board_summary,
            "environment": environment,
            "mainlines": mainlines,
        }

    def _get_market_summary(self, trade_date: str) -> Dict[str, Any]:
        row = self.db.fetchone(
            """
            SELECT
                trade_date,
                sh_index_pct,
                sz_index_pct,
                cyb_index_pct,
                total_amount,
                up_count,
                down_count,
                limit_up_count,
                broken_limit_count,
                highest_streak
            FROM daily_market_breadth
            WHERE trade_date = ?
            """,
            (trade_date,),
        )
        if not row:
            return {"trade_date": trade_date}

        return dict(row)

    def _get_top_boards(self, trade_date: str, limit: int = 10) -> List[Dict[str, Any]]:
        limit = min(limit, self._top_boards_limit())
        rows = self.db.fetchall(
            """
            SELECT
                board_name,
                board_type,
                pct_chg,
                board_score,
                phase_hint,
                limit_up_count,
                core_stock_count
            FROM daily_board_features
            WHERE trade_date = ?
            ORDER BY board_score DESC, pct_chg DESC
            LIMIT ?
            """,
            (trade_date, limit),
        )
        return [dict(row) for row in rows]

    def _get_observation_pool(self, trade_date: str, pool_group: str = "top20") -> List[Dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT
                p.symbol,
                p.name,
                p.role_tag,
                p.board_name,
                p.board_rank,
                p.stock_rank,
                p.final_score,
                p.selected_reason,
                p.watch_points,
                COALESCE(p.risk_flags, f.risk_flags) AS risk_flags,
                f.pct_chg,
                f.amount,
                f.turnover,
                f.amplitude,
                f.limit_up,
                f.broken_limit,
                f.limit_up_streak,
                f.feature_json
            FROM daily_observation_pool p
            LEFT JOIN daily_stock_features f
              ON p.trade_date = f.trade_date
             AND p.symbol = f.symbol
            WHERE p.trade_date = ?
              AND p.pool_group = ?
            ORDER BY
                CASE p.role_tag
                    WHEN 'dragon' THEN 1
                    WHEN 'center' THEN 2
                    WHEN 'follow' THEN 3
                    ELSE 4
                END,
                p.final_score DESC
            """,
            (trade_date, pool_group),
        )
        return self._attach_trading_boards(trade_date, [dict(row) for row in rows])

    def _get_pool_role_summary(self, trade_date: str) -> List[Dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT role_tag, COUNT(*) AS cnt
            FROM daily_observation_pool
            WHERE trade_date = ?
              AND pool_group = 'top20'
            GROUP BY role_tag
            ORDER BY cnt DESC, role_tag ASC
            """,
            (trade_date,),
        )
        return [dict(row) for row in rows]

    def _get_pool_board_distribution(self, trade_date: str) -> List[Dict[str, Any]]:
        rows = self._get_observation_pool(trade_date)
        counts: Dict[str, int] = {}
        for row in rows:
            board_name = row.get("board_name")
            if not board_name:
                continue
            counts[str(board_name)] = counts.get(str(board_name), 0) + 1
        return [
            {"board_name": board_name, "cnt": cnt}
            for board_name, cnt in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _get_legacy_pool_board_distribution(self, trade_date: str) -> List[Dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT board_name, COUNT(*) AS cnt
            FROM daily_observation_pool
            WHERE trade_date = ?
              AND pool_group = 'top20'
            GROUP BY board_name
            ORDER BY cnt DESC, board_name ASC
            """,
            (trade_date,),
        )
        return [dict(row) for row in rows]

    def _get_trading_board_map(self, trade_date: str) -> Dict[str, Dict[str, Any]]:
        rows = self.db.fetchall(
            """
            SELECT
                m.symbol,
                m.board_name,
                m.board_type,
                COALESCE(bf.board_score, 0) AS board_score,
                COALESCE(bf.pct_chg, 0) AS pct_chg
            FROM stock_board_membership m
            LEFT JOIN daily_board_features bf
              ON m.trade_date = bf.trade_date
             AND m.board_name = bf.board_name
             AND m.board_type = bf.board_type
            WHERE m.trade_date = ?
              AND m.board_type IN ('concept', 'industry')
            """,
            (trade_date,),
        )
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            grouped.setdefault(str(item["symbol"]), []).append(item)

        result: Dict[str, Dict[str, Any]] = {}
        for symbol, memberships in grouped.items():
            sorted_memberships = sorted(
                memberships,
                key=lambda item: (
                    0 if item.get("board_type") == "concept" else 1,
                    -float(item.get("board_score") or 0.0),
                    -float(item.get("pct_chg") or 0.0),
                    str(item.get("board_name") or ""),
                ),
            )
            primary = sorted_memberships[0]
            related = [
                str(item["board_name"])
                for item in sorted_memberships[1:6]
                if item.get("board_name")
            ]
            result[symbol] = {
                "trading_board_name": primary.get("board_name"),
                "trading_board_type": primary.get("board_type"),
                "related_board_names": related,
            }
        return result

    def _attach_trading_boards(self, trade_date: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        trading_map = self._get_trading_board_map(trade_date)
        result: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            csrc_board_name = item.get("board_name")
            trading = trading_map.get(str(item.get("symbol") or ""), {})
            trading_board_name = trading.get("trading_board_name")
            item["csrc_board_name"] = csrc_board_name
            item["trading_board_name"] = trading_board_name
            item["trading_board_type"] = trading.get("trading_board_type")
            item["related_board_names"] = trading.get("related_board_names", [])
            if trading_board_name:
                item["board_name"] = trading_board_name
            return_board_name = item.get("board_name")
            item["display_board_name"] = return_board_name
            result.append(item)
        return result

    def _get_strong_board_summary(self, trade_date: str) -> List[Dict[str, Any]]:
        raw_rows = self.db.fetchall(
            """
            SELECT
                p.board_name,
                p.symbol,
                p.name,
                p.final_score,
                f.amount
            FROM daily_observation_pool p
            LEFT JOIN daily_stock_features f
              ON p.trade_date = f.trade_date
             AND p.symbol = f.symbol
            WHERE p.trade_date = ?
              AND p.pool_group = 'top20'
              AND p.board_name IS NOT NULL
            ORDER BY p.board_name ASC, p.final_score DESC, f.amount DESC
            """,
            (trade_date,),
        )
        rows = self._attach_trading_boards(trade_date, [dict(row) for row in raw_rows])
        grouped: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            board_name = row["board_name"]
            if board_name not in grouped:
                grouped[board_name] = {
                    "board_name": board_name,
                    "strong_count": 0,
                    "strong_amount": 0.0,
                    "score_sum": 0.0,
                    "top_stock_symbol": row["symbol"],
                    "top_stock_name": row["name"],
                    "top_stock_score": row["final_score"],
                }
            item = grouped[board_name]
            item["strong_count"] += 1
            item["strong_amount"] += float(row["amount"] or 0.0)
            item["score_sum"] += float(row["final_score"] or 0.0)
        result = []
        for item in grouped.values():
            count = int(item["strong_count"])
            result.append(
                {
                    "board_name": item["board_name"],
                    "strong_count": count,
                    "strong_amount": round(float(item["strong_amount"]), 2),
                    "avg_strong_score": round(float(item["score_sum"]) / count, 2) if count else 0.0,
                    "top_stock_symbol": item["top_stock_symbol"],
                    "top_stock_name": item["top_stock_name"],
                    "top_stock_score": item["top_stock_score"],
                }
            )
        return sorted(
            result,
            key=lambda item: (
                -int(item["strong_count"]),
                -float(item["strong_amount"]),
                str(item["board_name"]),
            ),
        )

    def _decorate_observation_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        decorated = []
        for row in rows:
            item = dict(row)
            item["display_board_name"] = self._display_board_name(item.get("board_name"))
            item["risk_list"] = self._parse_list(item.get("risk_flags"))
            item["risk_labels"] = [self.RISK_LABELS.get(flag, str(flag)) for flag in item["risk_list"]]
            item["primary_role"] = self._primary_stock_role(item)
            item["role_labels"] = self._stock_role_labels(item)
            item["watch_conditions"] = self._watch_conditions(item)
            decorated.append(item)
        return decorated

    def _display_board_name(self, board_name: Any) -> str:
        text = str(board_name or "").strip()
        if not text:
            return "-"
        if text in self.CSRC_DISPLAY_NAMES:
            return self.CSRC_DISPLAY_NAMES[text]
        match = re.match(r"^[A-Z]\d{2}(.+)$", text)
        if not match:
            return text
        simplified = match.group(1)
        for suffix in ("制造业", "加工业", "业"):
            if simplified.endswith(suffix):
                simplified = simplified[: -len(suffix)]
                break
        return simplified.replace("和", "").replace("、", "")

    def _parse_json_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _parse_list(self, value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if not value or value == "-":
            return []
        try:
            parsed = json.loads(str(value))
        except Exception:
            return [part.strip() for part in str(value).replace("，", ",").split(",") if part.strip()]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if item]
        if isinstance(parsed, dict):
            return [str(key) for key, enabled in parsed.items() if enabled]
        return [str(parsed)] if parsed else []

    def _strong_metrics(self, row: Dict[str, Any]) -> Dict[str, Any]:
        feature_json = self._parse_json_dict(row.get("feature_json"))
        metrics = feature_json.get("strong_metrics", {})
        return metrics if isinstance(metrics, dict) else {}

    def _trend_window_hit_count(self, row: Dict[str, Any]) -> int:
        metrics = self._strong_metrics(row)
        window_scores = metrics.get("trend_window_scores")
        if isinstance(window_scores, dict):
            values = window_scores.values()
        elif isinstance(window_scores, list):
            values = window_scores
        else:
            values = [metrics.get("trend_score")]
        count = 0
        for value in values:
            try:
                if float(value or 0) >= 80:
                    count += 1
            except Exception:
                continue
        return count

    def _is_capacity_stock(self, row: Dict[str, Any]) -> bool:
        metrics = self._strong_metrics(row)
        try:
            amount = float(row.get("amount") or 0)
        except Exception:
            amount = 0.0
        try:
            capacity_bonus = float(metrics.get("capacity_bonus") or 0)
        except Exception:
            capacity_bonus = 0.0
        return amount >= 1_500_000_000 or capacity_bonus > 0

    def _is_emotion_stock(self, row: Dict[str, Any]) -> bool:
        metrics = self._strong_metrics(row)
        return (
            bool(metrics.get("emotion_channel_hit"))
            or int(row.get("limit_up") or 0) == 1
            or int(row.get("limit_up_streak") or 0) >= 2
        )

    def _is_trend_stock(self, row: Dict[str, Any]) -> bool:
        metrics = self._strong_metrics(row)
        return bool(metrics.get("trend_channel_hit")) and self._trend_window_hit_count(row) >= 2

    def _primary_stock_role(self, row: Dict[str, Any]) -> str:
        try:
            final_score = float(row.get("final_score") or 0)
            stock_rank = int(row.get("stock_rank") or 9999)
        except Exception:
            final_score = 0.0
            stock_rank = 9999
        if final_score >= 95 and stock_rank <= 10 and not row.get("risk_list"):
            return "核心票"
        if self._is_capacity_stock(row):
            return "容量票"
        if self._is_emotion_stock(row):
            return "情绪票"
        if self._is_trend_stock(row):
            return "趋势票"
        return "观察票"

    def _stock_role_labels(self, row: Dict[str, Any]) -> List[str]:
        labels = [row.get("primary_role") or self._primary_stock_role(row)]
        if self._is_capacity_stock(row) and "容量票" not in labels:
            labels.append("容量票")
        if self._is_emotion_stock(row) and "情绪票" not in labels:
            labels.append("情绪票")
        if self._is_trend_stock(row) and "趋势票" not in labels:
            labels.append("趋势票")
        labels.extend(row.get("risk_labels") or [])
        return labels

    def _watch_conditions(self, row: Dict[str, Any]) -> List[str]:
        conditions = []
        if row.get("primary_role") == "容量票" or self._is_capacity_stock(row):
            conditions.append("成交额继续保持 15 亿以上")
        if row.get("primary_role") in {"核心票", "情绪票"} or self._is_emotion_stock(row):
            conditions.append("涨停或高位强承接不能明显转弱")
        if row.get("primary_role") in {"核心票", "趋势票"} or self._is_trend_stock(row):
            conditions.append("5/10/20 日趋势结构至少两个周期不弱")
        if row.get("display_board_name") and row.get("display_board_name") != "-":
            conditions.append(f"{row['display_board_name']} 内强势股数量不明显塌缩")
        if row.get("risk_labels"):
            conditions.append("风险标签未继续扩散：" + "、".join(row["risk_labels"]))
        return conditions[:4] if conditions else ["继续观察强度是否能维持"]

    def _compute_environment(self, market_summary: Dict[str, Any], observation_pool: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_amount = float(market_summary.get("total_amount") or 0)
        amount_score = self._bucket_score(total_amount, [(1_500_000_000_000, 25), (1_200_000_000_000, 20), (1_000_000_000_000, 15), (800_000_000_000, 10)], 5)

        limit_up = float(market_summary.get("limit_up_count") or 0)
        limit_score = self._bucket_score(limit_up, [(80, 15), (60, 12), (40, 9), (20, 5)], 2)
        broken_limit = float(market_summary.get("broken_limit_count") or 0)
        if broken_limit <= 10:
            broken_score = 10
        elif broken_limit <= 20:
            broken_score = 6
        elif broken_limit <= 35:
            broken_score = 3
        else:
            broken_score = 0
        emotion_score = limit_score + broken_score

        breadth_ratio = self._compute_breadth_ratio(market_summary)
        breadth_score = self._bucket_score(breadth_ratio, [(60, 20), (50, 15), (40, 10), (30, 5)], 2)

        index_values = [
            float(market_summary.get("sh_index_pct") or 0),
            float(market_summary.get("sz_index_pct") or 0),
            float(market_summary.get("cyb_index_pct") or 0),
        ]
        index_avg = sum(index_values) / len(index_values)
        if index_avg >= 1:
            index_score = 15
        elif index_avg >= 0:
            index_score = 11
        elif index_avg >= -1:
            index_score = 7
        elif index_avg >= -2:
            index_score = 3
        else:
            index_score = 0

        scores = [float(row.get("final_score") or 0) for row in observation_pool[:20]]
        avg_score = sum(scores) / len(scores) if scores else 0
        if avg_score >= 95:
            avg_quality_score = 8
        elif avg_score >= 90:
            avg_quality_score = 6
        elif avg_score >= 85:
            avg_quality_score = 4
        else:
            avg_quality_score = 2 if scores else 0
        capacity_count = sum(1 for row in observation_pool if self._is_capacity_stock(row))
        if capacity_count >= 10:
            capacity_score = 7
        elif capacity_count >= 5:
            capacity_score = 5
        elif capacity_count >= 1:
            capacity_score = 3
        else:
            capacity_score = 0
        quality_score = avg_quality_score + capacity_score

        total_score = int(amount_score + emotion_score + breadth_score + index_score + quality_score)
        if total_score >= 80:
            state = "强"
        elif total_score >= 60:
            state = "结构性机会"
        elif total_score >= 40:
            state = "弱修复 / 分歧"
        else:
            state = "弱"

        return {
            "score": total_score,
            "state": state,
            "breadth_ratio": round(breadth_ratio, 1),
            "index_avg": round(index_avg, 2),
            "capacity_count": capacity_count,
            "parts": [
                {"label": "成交额", "score": amount_score, "max_score": 25, "value": self._fmt_amount(total_amount)},
                {"label": "涨停情绪", "score": emotion_score, "max_score": 25, "value": f"涨停 {self._fmt_number(limit_up)} / 炸板 {self._fmt_number(broken_limit)}"},
                {"label": "市场宽度", "score": breadth_score, "max_score": 20, "value": f"{breadth_ratio:.1f}%"},
                {"label": "指数环境", "score": index_score, "max_score": 15, "value": f"{index_avg:.2f}%"},
                {"label": "强势股质量", "score": quality_score, "max_score": 15, "value": f"均分 {avg_score:.1f} / 容量 {capacity_count}"},
            ],
        }

    def _bucket_score(self, value: float, buckets: List[tuple], fallback: int) -> int:
        for threshold, score in buckets:
            if value >= threshold:
                return int(score)
        return int(fallback)

    def _build_mainlines(
        self,
        top_boards: List[Dict[str, Any]],
        strong_board_summary: List[Dict[str, Any]],
        observation_pool: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        board_scores = {
            self._display_board_name(row.get("board_name")): float(row.get("board_score") or 0)
            for row in top_boards
        }
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in observation_pool:
            grouped.setdefault(row.get("display_board_name") or self._display_board_name(row.get("board_name")), []).append(row)

        summaries = {
            self._display_board_name(row.get("board_name")): row
            for row in strong_board_summary
        }
        board_names = set(board_scores) | set(grouped) | set(summaries)
        mainlines = []
        for board_name in board_names:
            if not board_name or board_name == "-":
                continue
            stocks = sorted(grouped.get(board_name, []), key=lambda row: float(row.get("final_score") or 0), reverse=True)
            strong_count = int(summaries.get(board_name, {}).get("strong_count") or len(stocks))
            capacity_count = sum(1 for row in stocks if self._is_capacity_stock(row))
            core_count = sum(1 for row in stocks if row.get("primary_role") == "核心票")
            score = round(board_scores.get(board_name, 0) + min(core_count, 10) * 2 + strong_count * 3 + capacity_count * 2, 2)
            if score >= 60:
                status = "主线明确"
            elif score >= 40:
                status = "方向活跃"
            elif score >= 20:
                status = "局部强"
            else:
                status = "弱 / 噪音"
            mainlines.append(
                {
                    "board_name": board_name,
                    "mainline_score": score,
                    "status": status,
                    "strong_count": strong_count,
                    "capacity_count": capacity_count,
                    "core_count": core_count,
                    "top_stocks": stocks[:5],
                }
            )
        return sorted(mainlines, key=lambda item: (-float(item["mainline_score"]), -int(item["strong_count"]), str(item["board_name"])))

    def _write_json(self, report_data: Dict[str, Any], trade_date: str) -> Path:
        path = self.output_dir / f"market_daily_{trade_date.replace('-', '')}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=self.config.JSON_INDENT)
        return path

    def _write_markdown(self, report_data: Dict[str, Any], trade_date: str) -> Path:
        path = self.output_dir / f"market_daily_{trade_date.replace('-', '')}.md"
        content = self._render_markdown(report_data)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _write_html(self, report_data: Dict[str, Any], trade_date: str) -> Path:
        path = self.output_dir / f"market_daily_{trade_date.replace('-', '')}.html"
        content = self._render_html(report_data)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _render_markdown(self, report_data: Dict[str, Any]) -> str:
        metadata = report_data["metadata"]
        market_summary = report_data["market_summary"]
        top_boards = report_data["top_boards"]
        observation_pool = report_data["observation_pool"]
        backup_pool = report_data["backup_pool"]
        role_summary = report_data["role_summary"]
        board_distribution = report_data["board_distribution"]
        strong_board_summary = report_data["strong_board_summary"]
        markdown = self.presentation["markdown"]

        lines: List[str] = []
        lines.append(f"# {markdown['report_title']} {metadata['trade_date']}")
        lines.append("")
        lines.append(f"生成时间：{metadata['generated_at']}")
        lines.append("")

        lines.append(f"## {markdown['market_overview']}")
        lines.append("")
        lines.append(f"- 上证：{market_summary.get('sh_index_pct')}")
        lines.append(f"- 深成：{market_summary.get('sz_index_pct')}")
        lines.append(f"- 创业板：{market_summary.get('cyb_index_pct')}")
        lines.append(f"- 成交额：{market_summary.get('total_amount')}")
        lines.append(f"- 上涨家数：{market_summary.get('up_count')}")
        lines.append(f"- 下跌家数：{market_summary.get('down_count')}")
        lines.append(f"- 涨停家数：{market_summary.get('limit_up_count')}")
        lines.append(f"- 连板高度：{market_summary.get('highest_streak')}")
        lines.append("")

        lines.append(f"## {markdown['top_boards']}")
        lines.append("")
        lines.append("| 排名 | 板块 | 类型 | 板块分 | 涨跌幅 | 阶段 | 涨停数 | 核心股数 |")
        lines.append("|---|---|---|---:|---:|---|---:|---:|")
        for index, board in enumerate(top_boards, start=1):
            lines.append(
                f"| {index} | {board['board_name']} | {board['board_type']} | "
                f"{board.get('board_score', 0)} | {board.get('pct_chg')} | {board.get('phase_hint')} | "
                f"{board.get('limit_up_count')} | {board.get('core_stock_count')} |"
            )
        lines.append("")

        lines.append(f"## {markdown['observation_pool']}")
        lines.append("")
        lines.append("| 代码 | 名称 | 角色 | 板块 | 板块排名 | 股票排名 | 总分 |")
        lines.append("|---|---|---|---|---:|---:|---:|")
        for row in observation_pool:
            lines.append(
                f"| {row['symbol']} | {row['name']} | {self._role_label(row['role_tag'])} | {row.get('board_name')} | "
                f"{row.get('board_rank')} | {row.get('stock_rank')} | {row.get('final_score')} |"
            )
        lines.append("")

        lines.append(f"## {markdown['observation_reason']}")
        lines.append("")
        for index, row in enumerate(observation_pool, start=1):
            lines.append(f"### {index}. {row['name']} ({row['symbol']})")
            lines.append(f"- 角色：{self._role_label(row['role_tag'])}")
            lines.append(f"- 板块：{row.get('board_name')}")
            related_board_text = self._related_board_text(row)
            if related_board_text:
                lines.append(f"- 相关标签：{related_board_text}")
            lines.append(f"- 原因：{row.get('selected_reason')}")
            lines.append(f"- 观察点：{row.get('watch_points')}")
            lines.append(f"- 风险：{row.get('risk_flags')}")
            lines.append("")

        lines.append(f"## {markdown['role_distribution']}")
        lines.append("")
        for row in role_summary:
            lines.append(f"- {self._role_label(row['role_tag'])}: {row['cnt']}")
        lines.append("")

        lines.append(f"## {markdown['board_distribution']}")
        lines.append("")
        for row in board_distribution:
            lines.append(f"- {row['board_name']}: {row['cnt']}")
        lines.append("")

        lines.append(f"## {markdown['strong_board_summary']}")
        lines.append("")
        for row in strong_board_summary:
            lines.append(
                f"- {row['board_name']}: 强势股 {row['strong_count']} 只，"
                f"合计成交 {self._fmt_amount(row['strong_amount'])}，"
                f"均分 {self._fmt_number(row['avg_strong_score'])}，"
                f"最强 {row['top_stock_name']}({row['top_stock_symbol']})"
            )
        lines.append("")

        if backup_pool:
            lines.append(f"## {markdown['backup_pool']}")
            lines.append("")
            for row in backup_pool:
                lines.append(
                    f"- {row['symbol']} {row['name']} | {self._role_label(row['role_tag'])} | "
                    f"{row.get('board_name')} | {row.get('final_score')}"
                )
            lines.append("")

        return "\n".join(lines)

    def _render_html(self, report_data: Dict[str, Any]) -> str:
        metadata = report_data["metadata"]
        market_summary = report_data["market_summary"]
        observation_pool = report_data["observation_pool"]
        environment = report_data.get("environment") or self._compute_environment(market_summary, observation_pool)
        mainlines = report_data.get("mainlines") or []

        def chips(labels: List[str], css_class: str = "") -> str:
            return "".join(f'<span class="chip {css_class}">{self._esc(label)}</span>' for label in labels if label)

        env_parts_html = "\n".join(
            f"""
            <article class="score-part">
              <div class="part-top"><span>{self._esc(part['label'])}</span><strong>{self._fmt_number(part['score'])}/{self._fmt_number(part['max_score'])}</strong></div>
              <div class="bar"><span style="width:{min(float(part['score']) / float(part['max_score']) * 100, 100):.0f}%"></span></div>
              <p>{self._esc(part['value'])}</p>
            </article>
            """
            for part in environment.get("parts", [])
        )
        mainline_cards_html = "\n".join(
            f"""
            <article class="mainline-card">
              <div class="mainline-head">
                <div>
                  <span class="rank">#{index:02d}</span>
                  <h3>{self._esc(line['board_name'])}</h3>
                </div>
                <div class="mainline-score">{self._fmt_number(line.get('mainline_score'))}</div>
              </div>
              <div class="mainline-meta">
                <span>{self._esc(line.get('status'))}</span>
                <span>强势 {self._fmt_number(line.get('strong_count'))}</span>
                <span>容量 {self._fmt_number(line.get('capacity_count'))}</span>
              </div>
              <div class="mainline-stocks">
                {''.join(f'<span>{self._esc(stock.get("name"))} <b>{self._fmt_number(stock.get("final_score"))}</b></span>' for stock in line.get('top_stocks', [])[:4]) or '<span>暂无强势股聚合</span>'}
              </div>
            </article>
            """
            for index, line in enumerate(mainlines[:6], start=1)
        )
        stock_cards_html = "\n".join(
            f"""
            <article class="stock-card">
              <div class="stock-card-top">
                <div>
                  <span class="rank">#{index:02d}</span>
                  <h3>{self._esc(row.get('name'))}</h3>
                  <p>{self._esc(row.get('symbol'))} · {self._esc(row.get('display_board_name'))}</p>
                </div>
                <div class="stock-score">{self._fmt_number(row.get('final_score'))}</div>
              </div>
              <div class="chip-row">{chips(row.get('role_labels') or [row.get('primary_role')], 'role-chip')}</div>
              <dl>
                <div><dt>成交额</dt><dd>{self._fmt_amount(row.get('amount'))}</dd></div>
                <div><dt>涨跌幅</dt><dd class="{self._pct_class(row.get('pct_chg'))}">{self._fmt_number(row.get('pct_chg'), '%')}</dd></div>
                <div><dt>排序</dt><dd>板块 {self._fmt_number(row.get('board_rank'))} / 股票 {self._fmt_number(row.get('stock_rank'))}</dd></div>
              </dl>
              <p class="reason">{self._esc(row.get('selected_reason'))}</p>
            </article>
            """
            for index, row in enumerate(observation_pool[:24], start=1)
        )
        evidence_rows_html = "\n".join(
            f"""
            <tr>
              <td>{index}</td>
              <td><strong>{self._esc(row.get('name'))}</strong><small>{self._esc(row.get('symbol'))}</small></td>
              <td>{self._esc(row.get('primary_role'))}</td>
              <td>{self._esc(row.get('display_board_name'))}</td>
              <td>{self._fmt_number(row.get('final_score'))}</td>
              <td>{self._fmt_amount(row.get('amount'))}</td>
              <td>{self._esc(row.get('selected_reason'))}</td>
            </tr>
            """
            for index, row in enumerate(observation_pool[:40], start=1)
        )
        watch_cards_html = "\n".join(
            f"""
            <article class="watch-card">
              <div class="watch-title">
                <strong>{self._esc(row.get('name'))}</strong>
                <span>{self._esc(row.get('primary_role'))}</span>
              </div>
              <ul>{''.join(f'<li>{self._esc(condition)}</li>' for condition in row.get('watch_conditions', [])[:4])}</ul>
            </article>
            """
            for row in observation_pool[:12]
        )
        role_counts: Dict[str, int] = {}
        for row in observation_pool:
            role = str(row.get("primary_role") or "观察票")
            role_counts[role] = role_counts.get(role, 0) + 1
        radar_html = "\n".join(
            f"""
            <article class="radar-card">
              <span>{self._esc(label)}</span>
              <strong>{self._fmt_number(value)}</strong>
            </article>
            """
            for label, value in [
                ("强势股", len(observation_pool)),
                ("容量票", role_counts.get("容量票", 0)),
                ("情绪票", role_counts.get("情绪票", 0)),
                ("趋势票", role_counts.get("趋势票", 0)),
                ("涨停", market_summary.get("limit_up_count")),
                ("炸板", market_summary.get("broken_limit_count")),
            ]
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>强势股池日报 {self._esc(metadata['trade_date'])}</title>
  <style>
    :root {{
      --bg: #f3f6f1;
      --ink: #172033;
      --muted: #667085;
      --panel: rgba(255, 255, 255, 0.86);
      --panel-strong: #ffffff;
      --line: rgba(23, 32, 51, 0.1);
      --blue: #175cd3;
      --amber: #b54708;
      --green: #067647;
      --red: #b42318;
      --soft-blue: #e8f1ff;
      --soft-amber: #fff4e5;
      --soft-green: #e7f6ee;
      --shadow: 0 24px 70px rgba(26, 42, 72, 0.12);
      --radius: 28px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 2%, rgba(23, 92, 211, 0.13), transparent 28%),
        radial-gradient(circle at 94% 0%, rgba(181, 71, 8, 0.15), transparent 26%),
        linear-gradient(180deg, #fbfcf8 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(23, 32, 51, 0.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(23, 32, 51, 0.035) 1px, transparent 1px);
      background-size: 36px 36px;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.18), transparent 80%);
    }}
    .workbench-shell {{
      width: min(1440px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 70px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) 360px;
      gap: 20px;
      align-items: stretch;
      background: linear-gradient(135deg, #172033 0%, #263c63 62%, #8a4b18 100%);
      border-radius: 34px;
      box-shadow: var(--shadow);
      padding: 30px;
      overflow: hidden;
      color: var(--ink);
    }}
    .eyebrow {{
      font-size: 12px;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: rgba(255,255,255,0.66);
    }}
    h1 {{
      margin: 14px 0 16px;
      font-size: clamp(28px, 4vw, 46px);
      line-height: 1;
      font-weight: 900;
      letter-spacing: -0.04em;
      color: #fff9ee;
    }}
    .hero p {{
      margin: 0;
      max-width: 820px;
      color: rgba(255,255,255,0.76);
      font-size: 15px;
      line-height: 1.75;
    }}
    .hero-metrics {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 26px;
    }}
    .hero-metric, .env-panel {{
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.1);
      backdrop-filter: blur(16px);
      border-radius: 22px;
      padding: 14px 16px;
      color: #fff9ee;
    }}
    .hero-metric span, .env-panel span {{
      display: block;
      font-size: 12px;
      color: rgba(255,255,255,0.64);
    }}
    .hero-metric strong {{
      display: block;
      margin-top: 7px;
      font-size: 20px;
    }}
    .env-panel {{
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 260px;
    }}
    .env-score {{
      font-size: 56px;
      line-height: 0.9;
      font-weight: 900;
      letter-spacing: -0.06em;
      color: #fff9ee;
    }}
    .env-state {{
      display: inline-flex;
      width: fit-content;
      margin-top: 12px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255,255,255,0.16);
      color: #fff9ee;
      font-weight: 800;
    }}
    .section {{
      margin-top: 22px;
      padding: 24px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: flex-end;
      margin-bottom: 18px;
    }}
    .section-kicker {{
      color: var(--blue);
      font-size: 12px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-weight: 800;
    }}
    .section h2 {{
      margin: 0;
      font-size: clamp(22px, 2.4vw, 30px);
      letter-spacing: -0.04em;
    }}
    .section-head p {{
      margin: 6px 0 0;
      color: var(--muted);
      line-height: 1.6;
    }}
    .score-grid, .mainline-grid, .stock-grid, .watch-grid, .radar-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 14px;
    }}
    .score-part, .mainline-card, .stock-card, .watch-card, .radar-card {{
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 16px;
    }}
    .part-top, .mainline-head, .stock-card-top, .watch-title {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }}
    .part-top span, .rank, dt {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .bar {{
      height: 8px;
      margin: 14px 0 10px;
      border-radius: 999px;
      background: #eef2f6;
      overflow: hidden;
    }}
    .bar span {{
      display: block;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--blue), var(--amber));
    }}
    .rise {{ color: var(--rise); }}
    .fall {{ color: var(--fall); }}
    .rise {{ color: var(--red); }}
    .fall {{ color: var(--green); }}
    .mainline-card h3, .stock-card h3 {{
      margin: 4px 0 0;
      font-size: 20px;
      letter-spacing: -0.04em;
    }}
    .mainline-score, .stock-score {{
      font-size: 24px;
      font-weight: 900;
      color: var(--amber);
    }}
    .mainline-meta, .mainline-stocks, .chip-row, .hero-metrics {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .mainline-meta span, .mainline-stocks span {{
      padding: 7px 10px;
      border-radius: 999px;
      background: var(--soft-blue);
      color: var(--blue);
      font-size: 12px;
      font-weight: 700;
    }}
    .mainline-stocks {{
      margin-top: 14px;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 12px;
      font-weight: 800;
      background: #eef2f6;
      color: var(--ink);
    }}
    .role-chip:nth-child(1) {{ background: var(--soft-amber); color: var(--amber); }}
    .stock-card p, .score-part p, .reason {{
      color: var(--muted);
      line-height: 1.6;
      font-size: 14px;
    }}
    dl {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin: 16px 0;
    }}
    dd {{ margin: 4px 0 0; font-weight: 800; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--line); border-radius: 20px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel-strong); }}
    th, td {{ padding: 13px 14px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ color: var(--muted); font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; background: #f8fafc; }}
    td small {{ display: block; margin-top: 4px; color: var(--muted); }}
    tr:last-child td {{ border-bottom: 0; }}
    .watch-card ul {{ margin: 12px 0 0; padding-left: 18px; color: var(--muted); line-height: 1.7; }}
    .watch-title span {{ color: var(--amber); font-weight: 800; }}
    .radar-card strong {{ display: block; margin-top: 10px; font-size: 22px; color: var(--blue); }}
    @media (max-width: 960px) {{
      .workbench-shell {{ width: min(100vw - 18px, 1440px); padding-top: 12px; }}
      .hero {{ grid-template-columns: 1fr; padding: 20px; border-radius: 26px; }}
      .section {{ padding: 18px; border-radius: 22px; }}
      .section-head {{ display: block; }}
      dl {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="workbench-shell">
    <section class="hero">
      <div>
        <div class="eyebrow">MARKET DAILY REPORT · {self._esc(metadata['trade_date'])}</div>
        <h1>强势股池日报</h1>
        <p>基于收盘后的市场宽度、板块强度和个股强度，整理当日强势方向、核心标的和次日跟踪条件。</p>
        <div class="hero-metrics">
          <div class="hero-metric"><span>上证</span><strong class="{self._pct_class(market_summary.get('sh_index_pct'))}">{self._fmt_number(market_summary.get('sh_index_pct'), '%')}</strong></div>
          <div class="hero-metric"><span>深成</span><strong class="{self._pct_class(market_summary.get('sz_index_pct'))}">{self._fmt_number(market_summary.get('sz_index_pct'), '%')}</strong></div>
          <div class="hero-metric"><span>创业板</span><strong class="{self._pct_class(market_summary.get('cyb_index_pct'))}">{self._fmt_number(market_summary.get('cyb_index_pct'), '%')}</strong></div>
          <div class="hero-metric"><span>成交额</span><strong>{self._fmt_amount(market_summary.get('total_amount'))}</strong></div>
        </div>
      </div>
      <aside class="env-panel">
        <div>
          <span>市场环境</span>
          <div class="env-score">{self._fmt_number(environment.get('score'))}</div>
          <div class="env-state">{self._esc(environment.get('state'))}</div>
        </div>
        <p>宽度 {self._fmt_number(environment.get('breadth_ratio'), '%')} · 容量票 {self._fmt_number(environment.get('capacity_count'))} 只 · 生成 {self._esc(metadata['generated_at'])}</p>
      </aside>
    </section>

    <section class="section" id="environment">
      <div class="section-head">
        <div>
          <div class="section-kicker">市场环境</div>
          <h2>环境强度</h2>
          <p>将成交额、涨停情绪、市场宽度、指数表现和强势股质量合成为统一环境分，用于判断当日强弱背景。</p>
        </div>
      </div>
      <div class="score-grid">{env_parts_html}</div>
    </section>

    <section class="section" id="mainlines">
      <div class="section-head">
        <div>
          <div class="section-kicker">主线结构</div>
          <h2>强势方向</h2>
          <p>优先使用概念和交易板块名称，缺失时回落到简化行业名。主线分综合板块强度、强势股数量、核心票和容量票。</p>
        </div>
      </div>
      <div class="mainline-grid">{mainline_cards_html or '<article class="mainline-card">暂无主线聚合</article>'}</div>
    </section>

    <section class="section" id="radar">
      <div class="section-head">
        <div>
          <div class="section-kicker">结构概览</div>
          <h2>池内分布</h2>
          <p>按强势股、容量票、情绪票和趋势票拆解池内结构，先观察整体质量，再进入个股明细。</p>
        </div>
      </div>
      <div class="radar-grid">{radar_html}</div>
    </section>

    <section class="section" id="stocks">
      <div class="section-head">
        <div>
          <div class="section-kicker">强势标的</div>
          <h2>强势股池</h2>
          <p>所有入池标的统一排序，并用角色标签说明强度来源，便于快速区分容量、趋势和情绪属性。</p>
        </div>
      </div>
      <div class="stock-grid">{stock_cards_html or '<article class="stock-card">暂无强势股</article>'}</div>
    </section>

    <section class="section" id="evidence">
      <div class="section-head">
        <div>
          <div class="section-kicker">入选依据</div>
          <h2>个股证据</h2>
          <p>保留每只股票的角色、所属方向、分数、成交额和入选理由，方便回溯强势判断来源。</p>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>#</th><th>股票</th><th>角色</th><th>主线</th><th>总分</th><th>成交额</th><th>证据</th></tr>
          </thead>
          <tbody>{evidence_rows_html}</tbody>
        </table>
      </div>
    </section>

    <section class="section" id="watchlist">
      <div class="section-head">
        <div>
          <div class="section-kicker">次日跟踪</div>
          <h2>观察条件</h2>
          <p>列出次日需要验证的强度条件，只用于跟踪强势是否延续，不作为买卖指令。</p>
        </div>
      </div>
      <div class="watch-grid">{watch_cards_html or '<article class="watch-card">暂无观察条件</article>'}</div>
    </section>
  </main>
</body>
</html>"""

    def _role_label(self, role_tag: Any) -> str:
        value = str(role_tag or "").strip()
        return self.role_labels.get(value, value or "-")

    def _top_boards_limit(self) -> int:
        title = str(self.presentation["markdown"]["top_boards"])
        suffix = title.rsplit(" ", 1)
        if len(suffix) == 2 and suffix[1].isdigit():
            return int(suffix[1])
        return 10

    def _build_index_chips(self, market_summary: Dict[str, Any]) -> str:
        labels = self.presentation["html"]["labels"]
        items = [
            (labels["index_sh"], market_summary.get("sh_index_pct")),
            (labels["index_sz"], market_summary.get("sz_index_pct")),
            (labels["index_cyb"], market_summary.get("cyb_index_pct")),
        ]
        return "\n".join(
            f'<span class="hero-pill"><strong>{label}</strong><span class="{self._pct_class(value)}">{self._fmt_number(value, suffix="%")}</span></span>'
            for label, value in items
        )

    def _build_hero_gauges(self, market_summary: Dict[str, Any]) -> str:
        breadth_ratio = self._compute_breadth_ratio(market_summary)
        emotion_score = self._compute_emotion_score(market_summary)
        labels = self.presentation["html"]["labels"]
        gauges = [
            (labels["gauge_market"], breadth_ratio, f"{self._fmt_number(market_summary.get('up_count'))} / {self._fmt_number(market_summary.get('down_count'))}"),
            (labels["gauge_emotion"], emotion_score, f"涨停 {self._fmt_number(market_summary.get('limit_up_count'))} · 连板 {self._fmt_number(market_summary.get('highest_streak'))}"),
        ]
        return "\n".join(
            f"""
            <div class="hero-gauge-card">
              <div class="gauge-dial" style="--gauge:{max(min(value, 100), 0)}">
                <div class="gauge-needle"></div>
              </div>
              <div class="gauge-core">
                <strong>{self._fmt_number(value)}</strong>
                <span>{self._esc(title)}</span>
              </div>
              <div class="gauge-meta">{self._esc(meta)}</div>
            </div>
            """
            for title, value, meta in gauges
        )

    def _build_hero_core_targets(self, observation_pool: List[Dict[str, Any]]) -> str:
        candidates = observation_pool[:5]
        if not candidates:
            return "<li class=\"hero-core-item\">暂无核心标的</li>"
        return "\n".join(
            f"""
            <li class="hero-core-item">
              <button type="button" data-modal-open="modal-{self._esc(row['symbol'])}">
                <span>
                  <span class="hero-core-name">{index:02d}. {self._esc(row['name'])}</span>
                  <span class="hero-core-tags">{self._esc(row.get('board_name'))}{self._hero_related_suffix(row)}</span>
                </span>
                <strong>{self._role_label(row.get('role_tag'))}</strong>
              </button>
            </li>
            """
            for index, row in enumerate(candidates, start=1)
        )

    def _hero_related_suffix(self, row: Dict[str, Any]) -> str:
        related = self._related_board_text(row)
        if not related:
            return ""
        return f" / {self._esc(related)}"

    def _render_observation_card(self, index: int, row: Dict[str, Any]) -> str:
        role_tag = row.get("role_tag") or "watchlist"
        related_board_text = self._related_board_text(row)
        related_chip = (
            f'<span class="chip chip-board-muted">相关 {self._esc(related_board_text)}</span>'
            if related_board_text
            else ""
        )
        return f"""
        <article class="pool-card" id="stock-{self._esc(row['symbol'])}">
          <button type="button" class="pool-summary" data-modal-open="modal-{self._esc(row['symbol'])}">
            <div class="pool-summary-top">
              <div>
                <div class="pool-index">#{index:02d}</div>
                <h3 class="pool-name">{self._esc(row['name'])}</h3>
                <div class="pool-symbol">{self._esc(row['symbol'])}</div>
              </div>
              <div class="score-badge">
                <span>{self._esc(self.presentation['html']['labels']['summary_score'])}</span>
                <strong>{self._fmt_number(row.get('final_score'))}</strong>
              </div>
            </div>
            <div class="pool-meta">
              <span class="chip chip-role chip-{self._esc(role_tag)}">{self._role_label(role_tag)}</span>
              <span class="chip chip-board">{self._esc(row.get('board_name'))}</span>
              {related_chip}
              <span class="chip">{self._esc(self.presentation['html']['labels']['board_rank'])} {self._fmt_number(row.get('board_rank'))}</span>
              <span class="chip">{self._esc(self.presentation['html']['labels']['stock_rank'])} {self._fmt_number(row.get('stock_rank'))}</span>
            </div>
          </button>
        </article>
        """

    def _build_observation_modals(self, observation_pool: List[Dict[str, Any]]) -> str:
        if not observation_pool:
            return ""
        return "\n".join(
            f"""
            <div class="modal-overlay" id="modal-{self._esc(row['symbol'])}">
              <div class="modal-card">
                <div class="modal-head">
                  <div>
                    <h3>{self._esc(row['name'])}</h3>
                    <div class="pool-symbol">{self._esc(row['symbol'])}</div>
                    <div class="modal-meta">
                      <span class="chip chip-role chip-{self._esc(row.get('role_tag') or 'watchlist')}">{self._role_label(row.get('role_tag'))}</span>
                      <span class="chip chip-board">{self._esc(row.get('board_name'))}</span>
                    </div>
                  </div>
                  <button type="button" class="modal-close" data-modal-close>×</button>
                </div>
                <div class="modal-body">
                  <div class="modal-grid">
                    <div class="modal-metric">
                      <span>{self._esc(self.presentation['html']['labels']['summary_score'])}</span>
                      <strong>{self._fmt_number(row.get('final_score'))}</strong>
                    </div>
                    <div class="modal-metric">
                      <span>板块 / 股票排序</span>
                      <strong>{self._esc(self.presentation['html']['labels']['board_rank'])} {self._fmt_number(row.get('board_rank'))} · {self._esc(self.presentation['html']['labels']['stock_rank'])} {self._fmt_number(row.get('stock_rank'))}</strong>
                    </div>
                  </div>
                  {self._render_related_board_block(row)}
                  <div><strong>{self._esc(self.presentation['html']['labels']['modal_selected_reason'])}</strong><br>{self._esc(row.get('selected_reason'))}</div>
                  <div><strong>{self._esc(self.presentation['html']['labels']['modal_watch_points'])}</strong><br>{self._esc(row.get('watch_points'))}</div>
                  <div><strong>{self._esc(self.presentation['html']['labels']['modal_risk_flags'])}</strong><br>{self._esc(row.get('risk_flags'))}</div>
                </div>
              </div>
            </div>
            """
            for row in observation_pool
        )

    def _related_board_text(self, row: Dict[str, Any]) -> str:
        related = row.get("related_board_names") or []
        if not related:
            return ""
        return " / ".join(str(item) for item in related[:5] if item)

    def _render_related_board_block(self, row: Dict[str, Any]) -> str:
        related_board_text = self._related_board_text(row)
        if not related_board_text:
            return ""
        return (
            f"<div><strong>相关交易标签</strong><br>"
            f"{self._esc(related_board_text)}</div>"
        )

    def _fmt_number(self, value: Any, suffix: str = "") -> str:
        if value is None or value == "":
            return "-"
        if isinstance(value, float):
            text = f"{value:.2f}".rstrip("0").rstrip(".")
        else:
            text = str(value)
        return f"{text}{suffix}"

    def _fmt_amount(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return "-"
        if numeric >= 1_0000_0000_0000:
            return f"{numeric / 1_0000_0000_0000:.2f}万亿"
        if numeric >= 1_0000_0000:
            return f"{numeric / 1_0000_0000:.0f}亿"
        return self._fmt_number(numeric)

    def _compute_breadth_ratio(self, market_summary: Dict[str, Any]) -> float:
        up_count = float(market_summary.get("up_count") or 0)
        down_count = float(market_summary.get("down_count") or 0)
        total = up_count + down_count
        if total <= 0:
            return 0.0
        return round(up_count / total * 100, 1)

    def _compute_emotion_score(self, market_summary: Dict[str, Any]) -> float:
        limit_up = float(market_summary.get("limit_up_count") or 0)
        highest_streak = float(market_summary.get("highest_streak") or 0)
        score = min(limit_up * 1.2 + highest_streak * 8, 100.0)
        return round(score, 1)

    def _pct_class(self, value: Any) -> str:
        try:
            numeric = float(value)
        except Exception:
            return ""
        if numeric > 0:
            return "rise"
        if numeric < 0:
            return "fall"
        return ""

    def _esc(self, value: Any) -> str:
        if value is None:
            return "-"
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
