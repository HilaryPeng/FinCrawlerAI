#!/usr/bin/env python3
"""
Generate an HTML index page for all daily market reports.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from html import escape
from pathlib import Path


def fmt_number(value: object, suffix: str = "") -> str:
    if value is None:
        return "--"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return escape(str(value))

    if number.is_integer():
        return f"{int(number)}{suffix}"
    return f"{number:.2f}{suffix}"


def phase_label(phase: str | None) -> str:
    mapping = {
        "start": "启动",
        "warm": "发酵",
        "accelerate": "加速",
        "split": "分歧",
        "fade": "退潮",
        "unknown": "未知",
        None: "未知",
    }
    return mapping.get(phase, phase)


def load_report_rows(output_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for json_path in sorted(output_dir.glob("market_daily_*.json"), reverse=True):
        stem = json_path.stem
        html_name = f"{stem}.html"
        html_path = output_dir / html_name
        if not html_path.exists():
            continue

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        metadata = payload.get("metadata", {})
        summary = payload.get("market_summary", {})
        top_boards = payload.get("top_boards", [])
        top_board = top_boards[0] if top_boards else {}

        rows.append(
            {
                "trade_date": metadata.get("trade_date") or stem.rsplit("_", 1)[-1],
                "generated_at": metadata.get("generated_at"),
                "html_name": html_name,
                "market_phase": phase_label(summary.get("market_phase")),
                "sh_index_pct": summary.get("sh_index_pct"),
                "sz_index_pct": summary.get("sz_index_pct"),
                "cyb_index_pct": summary.get("cyb_index_pct"),
                "up_count": summary.get("up_count"),
                "down_count": summary.get("down_count"),
                "limit_up_count": summary.get("limit_up_count"),
                "top_board_name": top_board.get("board_name"),
                "top_board_score": top_board.get("board_score"),
            }
        )
    return rows


def build_html(rows: list[dict]) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cards_html = "\n".join(
        f"""
        <a class="report-card" href="{escape(row['html_name'])}">
          <div class="report-card-head">
            <div>
              <div class="report-date">{escape(row['trade_date'])}</div>
              <div class="report-phase">{escape(row['market_phase'])}</div>
            </div>
            <div class="report-link">打开日报</div>
          </div>
          <div class="report-metrics">
            <div class="metric"><span>上证</span><strong>{fmt_number(row['sh_index_pct'], '%')}</strong></div>
            <div class="metric"><span>深成</span><strong>{fmt_number(row['sz_index_pct'], '%')}</strong></div>
            <div class="metric"><span>创业板</span><strong>{fmt_number(row['cyb_index_pct'], '%')}</strong></div>
            <div class="metric"><span>涨停数</span><strong>{fmt_number(row['limit_up_count'])}</strong></div>
          </div>
          <div class="report-footer">
            <span>上涨 / 下跌: {fmt_number(row['up_count'])} / {fmt_number(row['down_count'])}</span>
            <span>主线板块: {escape(row['top_board_name'] or '--')}</span>
          </div>
        </a>
        """
        for row in rows
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>市场观察日报索引</title>
  <style>
    :root {{
      --bg: #f4eee5;
      --panel: rgba(255, 251, 245, 0.86);
      --ink: #201712;
      --muted: #6f5b4a;
      --line: rgba(91, 62, 35, 0.12);
      --accent: #c96c22;
      --accent-deep: #7e3b13;
      --shadow: 0 24px 60px rgba(74, 46, 24, 0.12);
      --radius: 26px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 0% 0%, rgba(225, 154, 94, 0.18), transparent 28%),
        radial-gradient(circle at 100% 0%, rgba(33, 89, 83, 0.12), transparent 24%),
        linear-gradient(180deg, #faf4eb 0%, var(--bg) 100%);
      min-height: 100vh;
    }}
    .wrap {{
      width: min(1240px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 32px 0 64px;
    }}
    .hero {{
      background:
        radial-gradient(circle at top right, rgba(255, 210, 170, 0.24), transparent 28%),
        linear-gradient(135deg, #241712 0%, #4f2f1f 58%, #8d501f 100%);
      color: #fff7ef;
      border-radius: 32px;
      padding: 32px;
      box-shadow: 0 28px 72px rgba(58, 34, 18, 0.28);
    }}
    .eyebrow {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      color: rgba(255, 238, 221, 0.72);
    }}
    h1 {{
      margin: 12px 0 10px;
      font-size: clamp(30px, 5vw, 50px);
      line-height: 1.02;
    }}
    .hero p {{
      margin: 0;
      max-width: 760px;
      line-height: 1.7;
      color: rgba(255, 241, 229, 0.86);
    }}
    .meta {{
      margin-top: 18px;
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .chip {{
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.1);
      border: 1px solid rgba(255, 239, 225, 0.18);
      font-size: 13px;
    }}
    .section-title {{
      margin: 34px 0 16px;
      font-size: 20px;
      font-weight: 700;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 18px;
    }}
    .report-card {{
      display: block;
      text-decoration: none;
      color: inherit;
      background: var(--panel);
      backdrop-filter: blur(14px);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 22px;
      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }}
    .report-card:hover {{
      transform: translateY(-3px);
      box-shadow: 0 30px 76px rgba(74, 46, 24, 0.18);
      border-color: rgba(201, 108, 34, 0.3);
    }}
    .report-card-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      margin-bottom: 14px;
    }}
    .report-date {{
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.02em;
    }}
    .report-phase {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 14px;
    }}
    .report-link {{
      color: var(--accent-deep);
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }}
    .report-metrics {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin: 16px 0;
    }}
    .metric {{
      background: rgba(255, 255, 255, 0.58);
      border-radius: 18px;
      padding: 14px;
      border: 1px solid rgba(91, 62, 35, 0.08);
    }}
    .metric span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .metric strong {{
      font-size: 20px;
      font-weight: 800;
    }}
    .report-footer {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.5;
    }}
    @media (max-width: 760px) {{
      .wrap {{ width: min(100vw - 20px, 1240px); }}
      .hero {{ padding: 24px; border-radius: 26px; }}
      .report-card {{ padding: 18px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">FinCrawlerAI / Market Daily</div>
      <h1>市场观察日报索引</h1>
      <p>集中浏览已生成的日报页面，按交易日回看市场阶段、主线板块与重点观察标的。首页会随最新生成结果刷新，这个索引用来保留历史入口。</p>
      <div class="meta">
        <span class="chip">日报数量 {len(rows)}</span>
        <span class="chip">最后生成 {escape(generated_at)}</span>
      </div>
    </section>
    <h2 class="section-title">历史日报</h2>
    <section class="grid">
      {cards_html}
    </section>
  </div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate HTML index for daily market reports")
    parser.add_argument(
        "--output-dir",
        default="data/processed/market_daily",
        help="Directory containing market_daily_*.json/html files",
    )
    parser.add_argument(
        "--output-name",
        default="market_daily_index.html",
        help="Output HTML filename",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_report_rows(output_dir)
    html = build_html(rows)
    output_path = output_dir / args.output_name
    output_path.write_text(html, encoding="utf-8")
    print(f"index_path={output_path}")
    print(f"report_count={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
