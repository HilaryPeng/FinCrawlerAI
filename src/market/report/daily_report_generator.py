"""
Daily market report generator.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from config.settings import get_config
from src.db import DatabaseConnection
from src.specs import load_market_daily_spec


class DailyReportGenerator:
    """Generate JSON and Markdown daily reports."""

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
                symbol,
                name,
                role_tag,
                board_name,
                board_rank,
                stock_rank,
                final_score,
                selected_reason,
                watch_points,
                risk_flags
            FROM daily_observation_pool
            WHERE trade_date = ?
              AND pool_group = ?
            ORDER BY
                CASE role_tag
                    WHEN 'dragon' THEN 1
                    WHEN 'center' THEN 2
                    WHEN 'follow' THEN 3
                    ELSE 4
                END,
                final_score DESC
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
        top_boards = report_data["top_boards"]
        observation_pool = report_data["observation_pool"]
        backup_pool = report_data["backup_pool"]
        role_summary = report_data["role_summary"]
        board_distribution = report_data["board_distribution"]
        strong_board_summary = report_data["strong_board_summary"]
        index_chips_html = self._build_index_chips(market_summary)
        hero_core_targets_html = self._build_hero_core_targets(observation_pool)
        observation_modals_html = self._build_observation_modals(observation_pool)

        summary_cards = [
            ("上证指数", self._fmt_number(market_summary.get("sh_index_pct"), suffix="%"), self._pct_class(market_summary.get("sh_index_pct"))),
            ("深证成指", self._fmt_number(market_summary.get("sz_index_pct"), suffix="%"), self._pct_class(market_summary.get("sz_index_pct"))),
            ("创业板指", self._fmt_number(market_summary.get("cyb_index_pct"), suffix="%"), self._pct_class(market_summary.get("cyb_index_pct"))),
            ("两市成交额", self._fmt_amount(market_summary.get("total_amount")), ""),
            ("上涨家数", self._fmt_number(market_summary.get("up_count"))),
            ("下跌家数", self._fmt_number(market_summary.get("down_count"))),
            ("涨停家数", self._fmt_number(market_summary.get("limit_up_count"))),
            ("连板高度", self._fmt_number(market_summary.get("highest_streak")), ""),
        ]

        cards_html = "\n".join(
            f"""
            <article class="metric-card">
              <div class="metric-label">{label}</div>
              <div class="metric-value {extra_class if len(item) > 2 else ''}">{value}</div>
            </article>
            """
            for item in summary_cards
            for label, value, extra_class in [item if len(item) == 3 else (item[0], item[1], "")]
        )
        hero_cards = [
            ("上证", self._fmt_number(market_summary.get("sh_index_pct"), suffix="%"), self._pct_class(market_summary.get("sh_index_pct"))),
            ("成交", self._fmt_amount(market_summary.get("total_amount")), ""),
            ("涨停", self._fmt_number(market_summary.get("limit_up_count")), ""),
            ("强票", self._fmt_number(len(observation_pool)), ""),
        ]
        hero_cards_html = "\n".join(
            f"""
            <article class="metric-card metric-card-compact">
              <div class="metric-label">{label}</div>
              <div class="metric-value {extra_class}">{value}</div>
            </article>
            """
            for label, value, extra_class in hero_cards
        )

        boards_html = "\n".join(
            f"""
            <tr>
              <td>{index}</td>
              <td>{self._esc(board['board_name'])}</td>
              <td><span class="chip chip-board">{self._esc(board['board_type'])}</span></td>
              <td>{self._fmt_number(board.get('board_score'))}</td>
              <td class="{self._pct_class(board.get('pct_chg'))}">{self._fmt_number(board.get('pct_chg'), suffix='%')}</td>
              <td>{self._esc(board.get('phase_hint'))}</td>
              <td>{self._fmt_number(board.get('limit_up_count'))}</td>
              <td>{self._fmt_number(board.get('core_stock_count'))}</td>
            </tr>
            """
            for index, board in enumerate(top_boards, start=1)
        )

        observation_cards_html = "\n".join(
            self._render_observation_card(index, row)
            for index, row in enumerate(observation_pool, start=1)
        )

        backup_html = "\n".join(
            f"""
            <li>
              <span class="backup-code">{self._esc(row['symbol'])}</span>
              <strong>{self._esc(row['name'])}</strong>
              <span class="chip chip-role chip-{self._esc(row['role_tag'])}">{self._role_label(row['role_tag'])}</span>
              <span class="backup-meta">{self._esc(row.get('board_name'))}</span>
              <span class="backup-score">{self._fmt_number(row.get('final_score'))}</span>
            </li>
            """
            for row in backup_pool
        )
        strong_board_html = "\n".join(
            f"""
            <tr>
              <td>{index}</td>
              <td>{self._esc(row['board_name'])}</td>
              <td>{self._fmt_number(row.get('strong_count'))}</td>
              <td>{self._fmt_amount(row.get('strong_amount'))}</td>
              <td>{self._fmt_number(row.get('avg_strong_score'))}</td>
              <td>{self._esc(row.get('top_stock_name'))} {self._esc(row.get('top_stock_symbol'))}</td>
            </tr>
            """
            for index, row in enumerate(strong_board_summary, start=1)
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{self._esc(self.presentation['html']['page_title'])} {self._esc(metadata['trade_date'])}</title>
  <style>
    :root {{
      --bg: #0f1511;
      --bg-soft: #182018;
      --panel: rgba(255, 255, 255, 0.055);
      --panel-strong: rgba(255, 255, 255, 0.078);
      --ink: #edf3e9;
      --muted: #98a495;
      --line: rgba(237, 243, 233, 0.11);
      --line-strong: rgba(237, 243, 233, 0.16);
      --accent: #d7b45c;
      --accent-deep: #f1d47d;
      --accent-soft: rgba(215, 180, 92, 0.16);
      --accent-glow: rgba(215, 180, 92, 0.2);
      --rise: #f06f61;
      --fall: #40c48a;
      --shadow: 0 28px 76px rgba(0, 0, 0, 0.34);
      --radius: 24px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 90% 0%, rgba(215, 180, 92, 0.16), transparent 24%),
        radial-gradient(circle at 8% 18%, rgba(64, 196, 138, 0.1), transparent 22%),
        linear-gradient(135deg, #0e130f 0%, var(--bg) 46%, #20281e 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(237, 243, 233, 0.032) 1px, transparent 1px),
        linear-gradient(90deg, rgba(237, 243, 233, 0.032) 1px, transparent 1px);
      background-size: 30px 30px;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.36), transparent 86%);
    }}
    .wrap {{
      width: min(1380px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 30px 0 64px;
    }}
    .terminal-shell {{
      position: relative;
    }}
    .hero {{
      background:
        radial-gradient(circle at top right, var(--accent-glow), transparent 28%),
        linear-gradient(145deg, rgba(255,255,255,0.06), rgba(255,255,255,0.026));
      border: 1px solid var(--line-strong);
      border-radius: 32px;
      box-shadow: var(--shadow);
      padding: 30px 32px 28px;
      position: relative;
      overflow: hidden;
      color: var(--ink);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -70px -70px auto;
      width: 260px;
      height: 260px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(215, 180, 92, 0.18), transparent 68%);
    }}
    .hero::before {{
      content: "";
      position: absolute;
      inset: -40% auto auto -10%;
      width: 360px;
      height: 360px;
      background: radial-gradient(circle, rgba(64, 196, 138, 0.08), transparent 68%);
      transform: rotate(18deg);
    }}
    .hero-grid {{
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: minmax(0, 0.9fr) minmax(360px, 1.1fr);
      gap: 22px;
      align-items: stretch;
    }}
    .eyebrow {{
      font-size: 12px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 10px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(34px, 4.8vw, 58px);
      line-height: 1;
      font-weight: 900;
      letter-spacing: -0.07em;
      max-width: none;
      white-space: nowrap;
    }}
    .hero-sub {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 15px;
      max-width: 72ch;
      line-height: 1.75;
    }}
    .hero-sub strong {{
      color: var(--ink);
    }}
    .hero-pill-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }}
    .hero-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 9px 14px;
      border-radius: 999px;
      background: var(--panel);
      border: 1px solid var(--line);
      color: var(--ink);
      font-size: 13px;
      backdrop-filter: blur(10px);
    }}
    .hero-pill strong {{
      color: var(--ink);
      font-weight: 700;
    }}
    .hero-rail {{
      padding: 20px;
      border-radius: 24px;
      background: linear-gradient(180deg, var(--panel-strong), var(--panel));
      border: 1px solid var(--line);
      backdrop-filter: blur(12px);
    }}
    .hero-rail-title {{
      font-size: 12px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--accent-deep);
      margin-bottom: 14px;
      font-weight: 700;
    }}
    .hero-rail-subtitle {{
      margin-top: 18px;
      margin-bottom: 10px;
      font-size: 12px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--accent-deep);
      font-weight: 700;
    }}
    .hero-metric-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }}
    .hero-core-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    .hero-core-item button {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      width: 100%;
      cursor: pointer;
      text-align: left;
      font: inherit;
      text-decoration: none;
      color: var(--ink);
      padding: 12px 14px;
      border-radius: 16px;
      background: var(--panel-strong);
      border: 1px solid var(--line);
      font-size: 14px;
    }}
    .hero-core-item strong {{
      color: var(--accent-deep);
    }}
    .hero-core-item:nth-child(1) button {{
      background: linear-gradient(90deg, rgba(215,180,92,0.18), rgba(255,255,255,0.055));
      border-color: rgba(215, 180, 92, 0.2);
    }}
    .hero-core-item:nth-child(2) button {{
      background: linear-gradient(90deg, rgba(240,111,97,0.12), rgba(255,255,255,0.055));
      border-color: rgba(240, 111, 97, 0.16);
    }}
    .hero-core-item:nth-child(3) button {{
      background: linear-gradient(90deg, rgba(64,196,138,0.12), rgba(255,255,255,0.055));
      border-color: rgba(64, 196, 138, 0.16);
    }}
    .hero-core-item:nth-child(1) strong {{ color: #f1d47d; }}
    .hero-core-item:nth-child(2) strong {{ color: #ffc0ad; }}
    .hero-core-item:nth-child(3) strong {{ color: #b9f1e1; }}
    .hero-core-name {{
      display: block;
      font-weight: 800;
      font-size: 16px;
      margin-bottom: 4px;
    }}
    .hero-core-tags {{
      display: block;
      color: var(--muted);
      font-size: 12px;
    }}
    .section {{
      margin-top: 22px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 24px;
      backdrop-filter: blur(10px);
    }}
    .section-title {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 18px;
    }}
    .section-title h2 {{
      margin: 0;
      font-size: 24px;
      color: var(--accent-deep);
    }}
    .section-title span {{
      color: var(--muted);
      font-size: 13px;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 14px;
    }}
    .metric-card {{
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      min-height: 96px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }}
    .metric-card-compact {{
      min-height: 88px;
      padding: 14px;
    }}
    .metric-label {{
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .metric-value {{
      margin-top: 10px;
      font-size: 28px;
      font-weight: 700;
      line-height: 1;
    }}
    .logic-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    .logic-card {{
      position: relative;
      overflow: hidden;
      background: linear-gradient(180deg, rgba(255, 253, 249, 0.96), rgba(252, 244, 232, 0.82));
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px 18px 16px;
      min-height: 210px;
      box-shadow: 0 12px 34px rgba(73, 54, 35, 0.08);
    }}
    .logic-card::after {{
      content: "";
      position: absolute;
      inset: auto -30px -40px auto;
      width: 120px;
      height: 120px;
      border-radius: 50%;
      background: radial-gradient(circle, var(--accent-glow), transparent 72%);
    }}
    .logic-step {{
      color: var(--accent-deep);
      font-size: 12px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      margin-bottom: 10px;
    }}
    .logic-title {{
      margin: 0;
      font-size: 22px;
      line-height: 1.1;
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
    }}
    .logic-desc {{
      position: relative;
      z-index: 1;
      margin-top: 12px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.72;
    }}
    .logic-foot {{
      position: relative;
      z-index: 1;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid rgba(84, 60, 40, 0.08);
      color: var(--ink);
      font-size: 13px;
      line-height: 1.6;
    }}
    .rise {{ color: var(--rise); }}
    .fall {{ color: var(--fall); }}
    .table-wrap {{
      overflow-x: auto;
      border-radius: 18px;
      border: 1px solid var(--line);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: rgba(255, 255, 255, 0.035);
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      font-size: 14px;
      white-space: nowrap;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      background: rgba(255, 255, 255, 0.055);
    }}
    tbody tr {{
      transition: background 160ms ease, transform 160ms ease;
    }}
    tbody tr:hover {{
      background: rgba(255, 255, 255, 0.06);
    }}
    tr:last-child td {{ border-bottom: none; }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 600;
      background: rgba(255, 255, 255, 0.07);
      color: var(--ink);
    }}
    .chip-board {{
      background: var(--accent-soft);
      color: var(--accent-deep);
    }}
    .chip-role {{
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .chip-dragon {{ background: rgba(240, 111, 97, 0.16); color: #ffc0ad; }}
    .chip-center {{ background: rgba(64, 196, 138, 0.14); color: #b9f1e1; }}
    .chip-follow {{ background: var(--accent-soft); color: var(--accent-deep); }}
    .chip-trend_strong {{ background: rgba(240, 111, 97, 0.16); color: #ffc0ad; }}
    .chip-emotion_strong {{ background: var(--accent-soft); color: var(--accent-deep); }}
    .chip-capacity_strong {{ background: rgba(64, 196, 138, 0.14); color: #b9f1e1; }}
    .chip-watchlist {{ background: rgba(255, 255, 255, 0.08); color: var(--muted); }}
    .pool-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(215px, 1fr));
      gap: 12px;
    }}
    .pool-card {{
      position: relative;
      overflow: hidden;
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      box-shadow: 0 10px 26px rgba(73, 54, 35, 0.08);
      padding: 0;
    }}
    .pool-card::before {{
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 4px;
      background: linear-gradient(180deg, var(--accent), rgba(215, 180, 92, 0.18));
    }}
    .pool-summary {{
      width: 100%;
      cursor: pointer;
      border: 0;
      background: transparent;
      color: var(--ink);
      text-align: left;
      font: inherit;
      padding: 14px 16px 12px 18px;
      display: grid;
      gap: 10px;
    }}
    .pool-summary-top {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: flex-start;
    }}
    .pool-index {{
      font-size: 11px;
      color: var(--muted);
      letter-spacing: 0.14em;
      text-transform: uppercase;
      margin-bottom: 4px;
    }}
    .pool-name {{
      margin: 0;
      font-size: 20px;
      line-height: 1.08;
      color: var(--ink);
    }}
    .pool-symbol {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }}
    .score-badge {{
      min-width: 64px;
      text-align: center;
      background: var(--accent-soft);
      color: var(--accent);
      border-radius: 16px;
      padding: 8px 10px;
      border: 1px solid rgba(215, 180, 92, 0.16);
    }}
    .score-badge strong {{
      display: block;
      font-size: 20px;
      line-height: 1;
    }}
    .pool-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .backup-list {{
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 10px;
    }}
    .backup-list li {{
      display: grid;
      grid-template-columns: auto 1fr auto auto auto;
      gap: 10px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px 14px;
      background: var(--panel-strong);
      font-size: 14px;
    }}
    .backup-code, .backup-score {{
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }}
    .backup-meta {{
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .modal-overlay {{
      position: fixed;
      inset: 0;
      background: rgba(5, 8, 6, 0.7);
      backdrop-filter: blur(6px);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 18px;
      z-index: 50;
    }}
    .modal-overlay.is-open {{
      display: flex;
    }}
    .modal-card {{
      width: min(760px, calc(100vw - 28px));
      max-height: min(86vh, 900px);
      overflow: auto;
      background: linear-gradient(180deg, #172018, #101611);
      border: 1px solid var(--line);
      border-radius: 24px;
      box-shadow: 0 30px 80px rgba(0, 0, 0, 0.46);
      padding: 22px;
    }}
    .modal-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: flex-start;
    }}
    .modal-head h3 {{
      margin: 0;
      font-size: 28px;
      line-height: 1.05;
    }}
    .modal-close {{
      border: 0;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.08);
      color: var(--ink);
      width: 36px;
      height: 36px;
      cursor: pointer;
      font-size: 18px;
    }}
    .modal-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }}
    .modal-body {{
      margin-top: 18px;
      display: grid;
      gap: 12px;
      color: var(--muted);
      line-height: 1.7;
      font-size: 14px;
    }}
    .modal-body strong {{
      color: var(--ink);
    }}
    .modal-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .modal-metric {{
      padding: 12px 14px;
      border-radius: 16px;
      background: var(--panel-strong);
      border: 1px solid var(--line);
    }}
    .modal-metric span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .modal-metric strong {{
      display: block;
      margin-top: 8px;
      font-size: 18px;
      line-height: 1.3;
    }}
    @media (max-width: 900px) {{
      .wrap {{ width: min(100vw - 18px, 1380px); padding-top: 18px; }}
      .hero, .section {{ padding: 18px; border-radius: 22px; }}
      .hero-grid {{ grid-template-columns: 1fr; }}
      .hero-metric-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .backup-list li {{ grid-template-columns: 1fr; }}
      .modal-grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="wrap terminal-shell">
    <section class="hero">
      <div class="hero-grid">
        <div>
          <div class="eyebrow">MARKET DAILY REPORT · {self._esc(metadata['trade_date'])}</div>
          <h1>强势池 Monitor</h1>
          <div class="hero-sub">
            {self._esc(self.presentation['html']['hero']['body_template'].format(trade_date=metadata['trade_date']))}
          </div>
          <div class="hero-pill-row">{index_chips_html}</div>
        </div>
        <aside class="hero-rail">
          <div class="hero-rail-title">MARKET SNAPSHOT</div>
          <div class="hero-metric-grid">{hero_cards_html}</div>
          <div class="hero-rail-subtitle">CORE TARGETS</div>
          <ul class="hero-core-list">{hero_core_targets_html}</ul>
        </aside>
      </div>
    </section>

    <section class="section" id="market-overview">
      <div class="section-title">
        <h2>{self._esc(self.presentation['html']['sections']['market_overview'])}</h2>
        <span>生成时间 {self._esc(metadata['generated_at'])}</span>
      </div>
      <div class="metric-grid">
        {cards_html}
      </div>
    </section>

    <section class="section" id="observation-pool">
      <div class="section-title">
        <h2>{self._esc(self.presentation['html']['sections']['observation_pool'])}</h2>
        <span></span>
      </div>
      <div class="pool-grid">
        {observation_cards_html}
      </div>
    </section>

    <section class="section" id="strong-board-summary">
      <div class="section-title">
        <h2>{self._esc(self.presentation['html']['sections']['strong_board_summary'])}</h2>
        <span>强势股聚集度</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>排名</th>
              <th>板块</th>
              <th>强势股</th>
              <th>合计成交</th>
              <th>均分</th>
              <th>最强股</th>
            </tr>
          </thead>
          <tbody>
            {strong_board_html}
          </tbody>
        </table>
      </div>
    </section>

    <section class="section" id="top-boards">
      <div class="section-title">
        <h2>{self._esc(self.presentation['html']['sections']['top_boards'])}</h2>
        <span>强度排序与阶段定位</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>排名</th>
              <th>板块</th>
              <th>类型</th>
              <th>板块分</th>
              <th>涨跌幅</th>
              <th>阶段</th>
              <th>涨停数</th>
              <th>核心股数</th>
            </tr>
          </thead>
          <tbody>
            {boards_html}
          </tbody>
        </table>
      </div>
    </section>

    <section class="section" id="backup-pool">
      <div class="section-title">
        <h2>{self._esc(self.presentation['html']['sections']['backup_pool'])}</h2>
        <span>二级预案与轮动补位</span>
      </div>
      <ul class="backup-list">
        {backup_html}
      </ul>
    </section>
  </main>
  {observation_modals_html}
  <script>
    (() => {{
      const openButtons = document.querySelectorAll('[data-modal-open]');
      const closeButtons = document.querySelectorAll('[data-modal-close]');
      const closeModal = (modal) => {{
        if (!modal) return;
        modal.classList.remove('is-open');
        document.body.style.overflow = '';
      }};
      const openModal = (modalId) => {{
        const modal = document.getElementById(modalId);
        if (!modal) return;
        modal.classList.add('is-open');
        document.body.style.overflow = 'hidden';
      }};
      openButtons.forEach((button) => {{
        button.addEventListener('click', (event) => {{
          event.preventDefault();
          openModal(button.dataset.modalOpen);
        }});
      }});
      closeButtons.forEach((button) => {{
        button.addEventListener('click', () => closeModal(button.closest('.modal-overlay')));
      }});
      document.querySelectorAll('.modal-overlay').forEach((modal) => {{
        modal.addEventListener('click', (event) => {{
          if (event.target === modal) closeModal(modal);
        }});
      }});
      document.addEventListener('keydown', (event) => {{
        if (event.key === 'Escape') {{
          document.querySelectorAll('.modal-overlay.is-open').forEach(closeModal);
        }}
      }});
    }})();
  </script>
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
