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

        summary_cards = [
            ("市场阶段", market_summary.get("market_phase", "unknown")),
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
              <span class="chip chip-role chip-{self._esc(row['role_tag'])}">{self._esc(row['role_tag'])}</span>
              <span class="backup-meta">{self._esc(row.get('board_name'))}</span>
              <span class="backup-score">{self._fmt_number(row.get('final_score'))}</span>
            </li>
            """
            for row in backup_pool
        )

        role_summary_html = "\n".join(
            f"""
            <li>
              <span>{self._esc(row['role_tag'])}</span>
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
      --bg: #f4efe7;
      --panel: rgba(255, 252, 247, 0.86);
      --panel-strong: #fffaf2;
      --ink: #1f1a17;
      --muted: #675d55;
      --line: rgba(59, 43, 30, 0.12);
      --accent: #bb4d00;
      --accent-soft: rgba(187, 77, 0, 0.12);
      --rise: #b3362d;
      --fall: #1a8f55;
      --shadow: 0 20px 50px rgba(73, 54, 35, 0.12);
      --radius: 24px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(226, 155, 93, 0.22), transparent 30%),
        radial-gradient(circle at top right, rgba(53, 120, 120, 0.14), transparent 25%),
        linear-gradient(180deg, #f8f2ea 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    .wrap {{
      width: min(1380px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 56px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255, 250, 242, 0.92), rgba(248, 238, 225, 0.84));
      border: 1px solid var(--line);
      border-radius: 32px;
      box-shadow: var(--shadow);
      padding: 28px 30px 24px;
      position: relative;
      overflow: hidden;
    }}
    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -60px -60px auto;
      width: 220px;
      height: 220px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(187, 77, 0, 0.18), transparent 68%);
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
      font-size: clamp(34px, 5vw, 58px);
      line-height: 0.96;
      font-family: "Iowan Old Style", "Palatino Linotype", "Times New Roman", serif;
      font-weight: 700;
      max-width: 10ch;
    }}
    .hero-sub {{
      margin-top: 16px;
      color: var(--muted);
      font-size: 15px;
      max-width: 72ch;
      line-height: 1.65;
    }}
    .hero-sub strong {{
      color: var(--ink);
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
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      min-height: 96px;
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
    tr:last-child td {{ border-bottom: none; }}
    .chip {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 600;
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
      background: linear-gradient(180deg, rgba(255,255,255,0.72), rgba(255,249,241,0.85));
      border: 1px solid var(--line);
      border-radius: 22px;
      padding: 18px;
      box-shadow: 0 10px 28px rgba(73, 54, 35, 0.08);
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
      background: var(--accent-soft);
      color: var(--accent);
      border-radius: 18px;
      padding: 10px 12px;
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
      grid-template-columns: auto 1fr auto auto;
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
      .side-grid {{ grid-template-columns: 1fr; }}
      .backup-list li {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <div class="eyebrow">Market Daily Report</div>
      <h1>市场观察日报</h1>
      <div class="hero-sub">
        <strong>{self._esc(metadata['trade_date'])}</strong> 的市场观察页面。
        这版页面直接基于已生成的市场结构化结果，聚合 <strong>{len(top_boards)}</strong> 个主线板块、
        <strong>{len(observation_pool)}</strong> 只重点观察标的和 <strong>{len(backup_pool)}</strong> 只备选标的。
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
        <h2>主线板块</h2>
        <span>Top {len(top_boards)}</span>
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
        <span>龙头 / 中军 / 扩散 / 观察补位</span>
      </div>
      <div class="pool-grid">
        {observation_cards_html}
      </div>
    </section>

    <section class="section">
      <div class="section-title">
        <h2>结构分布</h2>
        <span>当前样本分布</span>
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
        <span>Backup 10</span>
      </div>
      <ul class="backup-list">
        {backup_html}
      </ul>
    </section>
  </main>
</body>
</html>"""

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
            <span class="chip chip-role chip-{self._esc(role_tag)}">{self._esc(role_tag)}</span>
            <span class="chip chip-board">{self._esc(row.get('board_name'))}</span>
            <span class="chip">板块排 {self._fmt_number(row.get('board_rank'))}</span>
            <span class="chip">股票排 {self._fmt_number(row.get('stock_rank'))}</span>
          </div>
          <div class="pool-detail">
            <div><strong>入选原因：</strong>{self._esc(row.get('selected_reason'))}</div>
            <div><strong>观察重点：</strong>{self._esc(row.get('watch_points'))}</div>
            <div><strong>风险标签：</strong>{self._esc(row.get('risk_flags'))}</div>
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
