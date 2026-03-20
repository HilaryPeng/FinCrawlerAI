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


class DailyReportGenerator:
    """Generate JSON and Markdown daily reports."""

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.config = get_config()
        self.output_dir = self.config.PROCESSED_DATA_DIR / "market_daily"
        self.output_dir.mkdir(parents=True, exist_ok=True)

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
            return {
                "trade_date": trade_date,
                "market_phase": "unknown",
            }

        summary = dict(row)
        summary["market_phase"] = self._infer_market_phase(summary)
        return summary

    def _get_top_boards(self, trade_date: str, limit: int = 10) -> List[Dict[str, Any]]:
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
        return [dict(row) for row in rows]

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

    def _infer_market_phase(self, summary: Dict[str, Any]) -> str:
        limit_up_count = summary.get("limit_up_count") or 0
        broken_limit_count = summary.get("broken_limit_count") or 0
        up_count = summary.get("up_count") or 0
        down_count = summary.get("down_count") or 0
        cyb_index_pct = summary.get("cyb_index_pct") or 0

        if limit_up_count >= 50 and cyb_index_pct >= 1.5 and up_count > down_count * 1.5:
            return "accelerate"
        if limit_up_count >= 30 and up_count > down_count:
            return "expand"
        if limit_up_count >= 10:
            return "start"
        if broken_limit_count > limit_up_count:
            return "fade"
        return "mixed"

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

        lines: List[str] = []
        lines.append(f"# 市场观察日报 {metadata['trade_date']}")
        lines.append("")
        lines.append(f"生成时间：{metadata['generated_at']}")
        lines.append("")

        lines.append("## 市场总览")
        lines.append("")
        lines.append(f"- 市场阶段：{market_summary.get('market_phase', 'unknown')}")
        lines.append(f"- 上证：{market_summary.get('sh_index_pct')}")
        lines.append(f"- 深成：{market_summary.get('sz_index_pct')}")
        lines.append(f"- 创业板：{market_summary.get('cyb_index_pct')}")
        lines.append(f"- 上涨家数：{market_summary.get('up_count')}")
        lines.append(f"- 下跌家数：{market_summary.get('down_count')}")
        lines.append(f"- 涨停家数：{market_summary.get('limit_up_count')}")
        lines.append(f"- 炸板家数：{market_summary.get('broken_limit_count')}")
        lines.append(f"- 连板高度：{market_summary.get('highest_streak')}")
        lines.append("")

        lines.append("## 主线板块 Top 10")
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

        lines.append("## 重点观察 20 只")
        lines.append("")
        lines.append("| 代码 | 名称 | 角色 | 板块 | 板块排名 | 股票排名 | 总分 |")
        lines.append("|---|---|---|---|---:|---:|---:|")
        for row in observation_pool:
            lines.append(
                f"| {row['symbol']} | {row['name']} | {row['role_tag']} | {row.get('board_name')} | "
                f"{row.get('board_rank')} | {row.get('stock_rank')} | {row.get('final_score')} |"
            )
        lines.append("")

        lines.append("## 观察理由")
        lines.append("")
        for index, row in enumerate(observation_pool, start=1):
            lines.append(f"### {index}. {row['name']} ({row['symbol']})")
            lines.append(f"- 角色：{row['role_tag']}")
            lines.append(f"- 板块：{row.get('board_name')}")
            lines.append(f"- 原因：{row.get('selected_reason')}")
            lines.append(f"- 观察点：{row.get('watch_points')}")
            lines.append(f"- 风险：{row.get('risk_flags')}")
            lines.append("")

        lines.append("## 角色分布")
        lines.append("")
        for row in role_summary:
            lines.append(f"- {row['role_tag']}: {row['cnt']}")
        lines.append("")

        lines.append("## 板块分布")
        lines.append("")
        for row in board_distribution:
            lines.append(f"- {row['board_name']}: {row['cnt']}")
        lines.append("")

        if backup_pool:
            lines.append("## 备选池")
            lines.append("")
            for row in backup_pool:
                lines.append(
                    f"- {row['symbol']} {row['name']} | {row['role_tag']} | "
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
        phase_label = self._phase_label(market_summary.get("market_phase"))
        hero_pills_html = self._build_hero_pills(
            market_summary=market_summary,
            top_boards=top_boards,
            observation_pool=observation_pool,
            backup_pool=backup_pool,
        )
        hero_focus_html = self._build_hero_focus(
            market_summary=market_summary,
            top_boards=top_boards,
            role_summary=role_summary,
            backup_pool=backup_pool,
        )
        decision_chain_html = self._build_decision_chain(
            market_summary=market_summary,
            top_boards=top_boards,
            observation_pool=observation_pool,
            role_summary=role_summary,
            backup_pool=backup_pool,
        )

        summary_cards = [
            ("市场阶段", phase_label),
            ("上证", self._fmt_number(market_summary.get("sh_index_pct"), suffix="%")),
            ("深成", self._fmt_number(market_summary.get("sz_index_pct"), suffix="%")),
            ("创业板", self._fmt_number(market_summary.get("cyb_index_pct"), suffix="%")),
            ("上涨家数", self._fmt_number(market_summary.get("up_count"))),
            ("下跌家数", self._fmt_number(market_summary.get("down_count"))),
            ("涨停家数", self._fmt_number(market_summary.get("limit_up_count"))),
            ("炸板家数", self._fmt_number(market_summary.get("broken_limit_count"))),
        ]

        cards_html = "\n".join(
            f"""
            <article class="metric-card">
              <div class="metric-label">{label}</div>
              <div class="metric-value">{value}</div>
            </article>
            """
            for label, value in summary_cards
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

        role_summary_html = "\n".join(
            f"""
            <li>
              <span>{self._role_label(row['role_tag'])}</span>
              <strong>{self._fmt_number(row['cnt'])}</strong>
            </li>
            """
            for row in role_summary
        )

        board_distribution_html = "\n".join(
            f"""
            <li>
              <span>{self._esc(row['board_name'])}</span>
              <strong>{self._fmt_number(row['cnt'])}</strong>
            </li>
            """
            for row in board_distribution
        )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>市场观察日报 {self._esc(metadata['trade_date'])}</title>
  <style>
    :root {{
      --bg: #f3ede3;
      --panel: rgba(255, 250, 243, 0.82);
      --panel-strong: rgba(255, 252, 246, 0.92);
      --ink: #211812;
      --muted: #6a5b4f;
      --line: rgba(84, 60, 40, 0.12);
      --line-strong: rgba(255, 236, 214, 0.16);
      --accent: #c76819;
      --accent-deep: #7a3b14;
      --accent-soft: rgba(199, 104, 25, 0.12);
      --accent-glow: rgba(232, 147, 83, 0.26);
      --rise: #ba3a30;
      --fall: #1a8f55;
      --shadow: 0 24px 60px rgba(77, 48, 21, 0.14);
      --radius: 24px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 0% 0%, rgba(227, 155, 84, 0.22), transparent 30%),
        radial-gradient(circle at 100% 10%, rgba(32, 90, 87, 0.14), transparent 24%),
        radial-gradient(circle at 50% 100%, rgba(146, 88, 29, 0.08), transparent 34%),
        linear-gradient(180deg, #f8f2e9 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(122, 59, 20, 0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(122, 59, 20, 0.03) 1px, transparent 1px);
      background-size: 26px 26px;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.3), transparent 88%);
    }}
    .wrap {{
      width: min(1380px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 30px 0 64px;
    }}
    .hero {{
      background:
        radial-gradient(circle at top right, rgba(250, 194, 141, 0.2), transparent 30%),
        linear-gradient(135deg, #221611 0%, #4f2d1c 52%, #8b4d1f 100%);
      border: 1px solid var(--line-strong);
      border-radius: 32px;
      box-shadow: 0 26px 70px rgba(53, 31, 17, 0.28);
      padding: 30px 32px 28px;
      position: relative;
      overflow: hidden;
      color: #fff7ef;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -70px -70px auto;
      width: 260px;
      height: 260px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(255, 205, 153, 0.34), transparent 68%);
    }}
    .hero::before {{
      content: "";
      position: absolute;
      inset: -40% auto auto -10%;
      width: 360px;
      height: 360px;
      background: radial-gradient(circle, rgba(255, 255, 255, 0.08), transparent 68%);
      transform: rotate(18deg);
    }}
    .hero-grid {{
      position: relative;
      z-index: 1;
      display: grid;
      grid-template-columns: minmax(0, 1.55fr) minmax(280px, 0.95fr);
      gap: 22px;
      align-items: stretch;
    }}
    .eyebrow {{
      font-size: 12px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: rgba(255, 235, 218, 0.72);
      margin-bottom: 10px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(34px, 5vw, 58px);
      line-height: 0.96;
      font-family: "Iowan Old Style", "Palatino Linotype", "Times New Roman", serif;
      font-weight: 700;
      max-width: 10ch;
    }}
    .hero-sub {{
      margin-top: 16px;
      color: rgba(255, 240, 228, 0.82);
      font-size: 15px;
      max-width: 72ch;
      line-height: 1.75;
    }}
    .hero-sub strong {{
      color: #fffaf5;
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
      background: rgba(255, 248, 239, 0.08);
      border: 1px solid rgba(255, 239, 224, 0.12);
      color: rgba(255, 242, 232, 0.92);
      font-size: 13px;
      backdrop-filter: blur(10px);
    }}
    .hero-pill strong {{
      color: #fffaf5;
      font-weight: 700;
    }}
    .hero-rail {{
      padding: 20px;
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(255, 248, 239, 0.1), rgba(255, 248, 239, 0.06));
      border: 1px solid rgba(255, 238, 218, 0.12);
      backdrop-filter: blur(12px);
    }}
    .hero-rail-title {{
      font-size: 12px;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: rgba(255, 235, 218, 0.68);
      margin-bottom: 14px;
    }}
    .hero-focus-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 12px;
    }}
    .hero-focus-item {{
      padding: 12px 14px;
      border-radius: 18px;
      background: rgba(255, 250, 244, 0.08);
      border: 1px solid rgba(255, 238, 218, 0.1);
    }}
    .hero-focus-kicker {{
      color: rgba(255, 232, 210, 0.68);
      font-size: 11px;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      margin-bottom: 6px;
    }}
    .hero-focus-main {{
      color: #fffaf5;
      font-size: 16px;
      line-height: 1.45;
    }}
    .hero-focus-main strong {{
      color: #ffd9bc;
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
      font-family: "Iowan Old Style", "Palatino Linotype", serif;
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
      background: linear-gradient(180deg, rgba(255, 253, 249, 0.9), rgba(255, 248, 239, 0.82));
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      min-height: 96px;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65);
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
      background: rgba(255, 255, 255, 0.55);
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
      background: rgba(255, 248, 240, 0.8);
    }}
    tbody tr {{
      transition: background 160ms ease, transform 160ms ease;
    }}
    tbody tr:hover {{
      background: rgba(255, 248, 240, 0.72);
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
      background: rgba(123, 92, 65, 0.08);
    }}
    .chip-board {{
      background: rgba(33, 113, 160, 0.1);
      color: #1f5c83;
    }}
    .chip-role {{
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }}
    .chip-dragon {{ background: rgba(179, 54, 45, 0.12); color: #9c2119; }}
    .chip-center {{ background: rgba(17, 94, 89, 0.12); color: #0e5e59; }}
    .chip-follow {{ background: rgba(160, 115, 31, 0.14); color: #8a5e12; }}
    .chip-watchlist {{ background: rgba(88, 81, 74, 0.12); color: #5d5750; }}
    .pool-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
      gap: 16px;
    }}
    .pool-card {{
      position: relative;
      overflow: hidden;
      background: linear-gradient(180deg, rgba(255,255,255,0.76), rgba(255,249,241,0.9));
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      box-shadow: 0 10px 28px rgba(73, 54, 35, 0.08);
    }}
    .pool-card::before {{
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 4px;
      background: linear-gradient(180deg, var(--accent), rgba(199, 104, 25, 0.18));
    }}
    .pool-card-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
    }}
    .pool-index {{
      font-size: 12px;
      color: var(--muted);
      letter-spacing: 0.14em;
      text-transform: uppercase;
      margin-bottom: 6px;
    }}
    .pool-name {{
      margin: 0;
      font-size: 24px;
      line-height: 1.05;
    }}
    .pool-symbol {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 4px;
    }}
    .score-badge {{
      min-width: 72px;
      text-align: center;
      background: linear-gradient(180deg, rgba(199, 104, 25, 0.16), rgba(199, 104, 25, 0.08));
      color: var(--accent);
      border-radius: 18px;
      padding: 10px 12px;
      border: 1px solid rgba(199, 104, 25, 0.12);
    }}
    .score-badge strong {{
      display: block;
      font-size: 22px;
      line-height: 1;
    }}
    .pool-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }}
    .pool-detail {{
      margin-top: 16px;
      display: grid;
      gap: 10px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }}
    .pool-detail strong {{
      color: var(--ink);
    }}
    .side-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }}
    .side-list {{
      margin: 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 10px;
    }}
    .side-list li {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: rgba(255,255,255,0.55);
      font-size: 14px;
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
      background: rgba(255,255,255,0.55);
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
    @media (max-width: 900px) {{
      .wrap {{ width: min(100vw - 18px, 1380px); padding-top: 18px; }}
      .hero, .section {{ padding: 18px; border-radius: 22px; }}
      .hero-grid {{ grid-template-columns: 1fr; }}
      .side-grid {{ grid-template-columns: 1fr; }}
      .backup-list li {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <div class="hero-grid">
        <div>
          <div class="eyebrow">Strategic Market Dashboard</div>
          <h1>市场观察日报</h1>
          <div class="hero-sub">
            <strong>{self._esc(metadata['trade_date'])}</strong> 的策略总览页。
            本页不堆砌过程噪音，只保留可执行结论，围绕 <strong>市场温度</strong>、
            <strong>主线强度</strong>、<strong>核心角色</strong> 与 <strong>节奏闸口</strong>
            四层框架完成收敛，形成一张可用于盘前定框架、盘中跟强度、盘后校验结构的高密度观察面板。
          </div>
          <div class="hero-pill-row">{hero_pills_html}</div>
        </div>
        <aside class="hero-rail">
          <div class="hero-rail-title">本页聚焦</div>
          <ul class="hero-focus-list">{hero_focus_html}</ul>
        </aside>
      </div>
    </section>

    <section class="section">
      <div class="section-title">
        <h2>市场总览</h2>
        <span>生成时间 {self._esc(metadata['generated_at'])}</span>
      </div>
      <div class="metric-grid">
        {cards_html}
      </div>
    </section>

    <section class="section">
      <div class="section-title">
        <h2>策略决策链路</h2>
        <span>从温度识别到执行分层</span>
      </div>
      <div class="logic-grid">
        {decision_chain_html}
      </div>
    </section>

    <section class="section">
      <div class="section-title">
        <h2>主线板块</h2>
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

    <section class="section">
      <div class="section-title">
        <h2>重点观察 20 只</h2>
        <span>按龙头 / 中军 / 扩散 / 观察补位分层编组</span>
      </div>
      <div class="pool-grid">
        {observation_cards_html}
      </div>
    </section>

    <section class="section">
      <div class="section-title">
        <h2>结构分布</h2>
        <span>角色密度与板块聚焦</span>
      </div>
      <div class="side-grid">
        <div>
          <h3>角色分布</h3>
          <ul class="side-list">{role_summary_html}</ul>
        </div>
        <div>
          <h3>板块分布</h3>
          <ul class="side-list">{board_distribution_html}</ul>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-title">
        <h2>备选池</h2>
        <span>二级预案与轮动补位</span>
      </div>
      <ul class="backup-list">
        {backup_html}
      </ul>
    </section>
  </main>
</body>
</html>"""

    def _phase_label(self, phase: Any) -> str:
        mapping = {
            "accelerate": "主升加速",
            "expand": "扩散强化",
            "start": "启动试错",
            "fade": "高位分歧",
            "mixed": "震荡博弈",
            "unknown": "待确认",
        }
        return mapping.get(str(phase or "").strip(), self._esc(phase) if phase else "待确认")

    def _role_label(self, role_tag: Any) -> str:
        mapping = {
            "dragon": "龙头",
            "center": "中军",
            "follow": "扩散",
            "watchlist": "观察补位",
        }
        value = str(role_tag or "").strip()
        return mapping.get(value, value or "-")

    def _build_hero_pills(
        self,
        market_summary: Dict[str, Any],
        top_boards: List[Dict[str, Any]],
        observation_pool: List[Dict[str, Any]],
        backup_pool: List[Dict[str, Any]],
    ) -> str:
        lead_names = " / ".join(self._esc(board.get("board_name")) for board in top_boards[:3]) or "待识别"
        pills = [
            ("市场阶段", self._phase_label(market_summary.get("market_phase"))),
            ("主线簇", lead_names),
            ("重点观察", f"{len(observation_pool)} 只"),
            ("备选预案", f"{len(backup_pool)} 只"),
        ]
        return "\n".join(
            f'<span class="hero-pill"><strong>{label}</strong>{value}</span>' for label, value in pills
        )

    def _build_hero_focus(
        self,
        market_summary: Dict[str, Any],
        top_boards: List[Dict[str, Any]],
        role_summary: List[Dict[str, Any]],
        backup_pool: List[Dict[str, Any]],
    ) -> str:
        lead_board = top_boards[0] if top_boards else {}
        strongest_role = role_summary[0] if role_summary else {}
        up_count = market_summary.get("up_count")
        down_count = market_summary.get("down_count")
        breadth_text = f"{self._fmt_number(up_count)} / {self._fmt_number(down_count)}"
        items = [
            (
                "主攻方向",
                f"<strong>{self._esc(lead_board.get('board_name') or '待识别')}</strong> 处于当前强度队列前沿，"
                f"板块分 {self._fmt_number(lead_board.get('board_score'))}。"
            ),
            (
                "情绪对照",
                f"上涨/下跌家数为 <strong>{breadth_text}</strong>，连板高度 "
                f"<strong>{self._fmt_number(market_summary.get('highest_streak'))}</strong>。"
            ),
            (
                "结构占优",
                f"{self._role_label(strongest_role.get('role_tag'))} 当前占比最高，样本数 "
                f"<strong>{self._fmt_number(strongest_role.get('cnt'))}</strong>。"
            ),
            (
                "节奏预案",
                f"备选池保留 <strong>{len(backup_pool)}</strong> 个切换位，用于轮动承接与风险回撤时的层级过渡。"
            ),
        ]
        return "\n".join(
            f"""
            <li class="hero-focus-item">
              <div class="hero-focus-kicker">{title}</div>
              <div class="hero-focus-main">{body}</div>
            </li>
            """
            for title, body in items
        )

    def _build_decision_chain(
        self,
        market_summary: Dict[str, Any],
        top_boards: List[Dict[str, Any]],
        observation_pool: List[Dict[str, Any]],
        role_summary: List[Dict[str, Any]],
        backup_pool: List[Dict[str, Any]],
    ) -> str:
        lead_names = " / ".join(self._esc(board.get("board_name")) for board in top_boards[:3]) or "待识别"
        role_text = " / ".join(
            f"{self._role_label(row.get('role_tag'))} {self._fmt_number(row.get('cnt'))}" for row in role_summary
        ) or "结构待识别"
        cards = [
            (
                "Step 01",
                "先定市场温度",
                f"优先识别环境是否支持放大仓位。当前市场阶段为 {self._phase_label(market_summary.get('market_phase'))}，"
                f"上涨家数 {self._fmt_number(market_summary.get('up_count'))}、下跌家数 {self._fmt_number(market_summary.get('down_count'))}，"
                f"连板高度 {self._fmt_number(market_summary.get('highest_streak'))} 板。",
                "这一层决定交易是否以进攻为主，还是以试错和控制回撤为先。",
            ),
            (
                "Step 02",
                "再做主线收敛",
                f"从板块强度里抽取资金最集中的方向，当前强势簇主要集中在 {lead_names}。"
                f"首位方向的板块分为 {self._fmt_number(top_boards[0].get('board_score')) if top_boards else '-'}，"
                f"用于界定今日的核心战场。",
                "这一层解决的是资金到底围绕哪条主线完成定价和扩散。",
            ),
            (
                "Step 03",
                "然后筛核心角色",
                f"在主线内部继续区分带动情绪的龙头、承接容量的中军以及负责扩散的补涨层。"
                f"当前观察池共 {len(observation_pool)} 只，角色结构为 {role_text}。",
                "这一层决定观察顺序、仓位层级和盘中跟踪优先级。",
            ),
            (
                "Step 04",
                "最后管执行节奏",
                f"把高弹性机会和回撤控制放进同一套闸门里。当前炸板家数为 "
                f"{self._fmt_number(market_summary.get('broken_limit_count'))}，并保留 {len(backup_pool)} 只备选标的作为轮动预案。",
                "这一层用于处理追强、分歧承接和失效切换，避免只看方向不看节奏。",
            ),
        ]
        return "\n".join(
            f"""
            <article class="logic-card">
              <div class="logic-step">{step}</div>
              <h3 class="logic-title">{title}</h3>
              <div class="logic-desc">{desc}</div>
              <div class="logic-foot">{foot}</div>
            </article>
            """
            for step, title, desc, foot in cards
        )

    def _render_observation_card(self, index: int, row: Dict[str, Any]) -> str:
        role_tag = row.get("role_tag") or "watchlist"
        return f"""
        <article class="pool-card">
          <div class="pool-card-top">
            <div>
              <div class="pool-index">#{index:02d}</div>
              <h3 class="pool-name">{self._esc(row['name'])}</h3>
              <div class="pool-symbol">{self._esc(row['symbol'])}</div>
            </div>
            <div class="score-badge">
              <span>总分</span>
              <strong>{self._fmt_number(row.get('final_score'))}</strong>
            </div>
          </div>
          <div class="pool-meta">
            <span class="chip chip-role chip-{self._esc(role_tag)}">{self._role_label(role_tag)}</span>
            <span class="chip chip-board">{self._esc(row.get('board_name'))}</span>
            <span class="chip">板块排 {self._fmt_number(row.get('board_rank'))}</span>
            <span class="chip">股票排 {self._fmt_number(row.get('stock_rank'))}</span>
          </div>
          <div class="pool-detail">
            <div><strong>核心叙事：</strong>{self._esc(row.get('selected_reason'))}</div>
            <div><strong>验证路径：</strong>{self._esc(row.get('watch_points'))}</div>
            <div><strong>风险闸口：</strong>{self._esc(row.get('risk_flags'))}</div>
          </div>
        </article>
        """

    def _fmt_number(self, value: Any, suffix: str = "") -> str:
        if value is None or value == "":
            return "-"
        if isinstance(value, float):
            text = f"{value:.2f}".rstrip("0").rstrip(".")
        else:
            text = str(value)
        return f"{text}{suffix}"

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
