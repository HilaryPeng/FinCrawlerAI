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


def fmt_amount(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "--"
    if number >= 1_0000_0000_0000:
        return f"{number / 1_0000_0000_0000:.2f}万亿"
    if number >= 1_0000_0000:
        return f"{number / 1_0000_0000:.0f}亿"
    return fmt_number(number)


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
        environment = payload.get("environment", {})
        mainlines = payload.get("mainlines", [])
        top_mainline = mainlines[0] if mainlines else {}
        observation_pool = payload.get("observation_pool", [])

        rows.append(
            {
                "trade_date": metadata.get("trade_date") or stem.rsplit("_", 1)[-1],
                "generated_at": metadata.get("generated_at"),
                "html_name": html_name,
                "market_phase": phase_label(summary.get("market_phase")),
                "environment_score": environment.get("score"),
                "environment_state": environment.get("state") or "--",
                "sh_index_pct": summary.get("sh_index_pct"),
                "sz_index_pct": summary.get("sz_index_pct"),
                "cyb_index_pct": summary.get("cyb_index_pct"),
                "total_amount": summary.get("total_amount"),
                "up_count": summary.get("up_count"),
                "down_count": summary.get("down_count"),
                "limit_up_count": summary.get("limit_up_count"),
                "broken_limit_count": summary.get("broken_limit_count"),
                "top_mainline_name": top_mainline.get("board_name") or "--",
                "top_mainline_score": top_mainline.get("mainline_score"),
                "top_mainline_status": top_mainline.get("status") or "--",
                "strong_count": len(observation_pool),
                "capacity_count": sum(1 for row in observation_pool if row.get("primary_role") == "容量票"),
            }
        )
    return rows


def build_html(rows: list[dict]) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    latest = rows[0] if rows else {}
    cards_html = "\n".join(
        f"""
        <a class="report-card" href="{escape(row['html_name'])}">
          <div class="report-card-head">
            <div>
              <div class="report-date">{escape(row['trade_date'])}</div>
              <div class="report-phase">{escape(row['environment_state'])} · {escape(row['top_mainline_status'])}</div>
            </div>
            <div class="score-pill">{fmt_number(row['environment_score'])}</div>
          </div>
          <div class="report-metrics">
            <div class="metric"><span>主线</span><strong>{escape(row['top_mainline_name'])}</strong></div>
            <div class="metric"><span>强势股</span><strong>{fmt_number(row['strong_count'])}</strong></div>
            <div class="metric"><span>容量票</span><strong>{fmt_number(row['capacity_count'])}</strong></div>
            <div class="metric"><span>涨停 / 炸板</span><strong>{fmt_number(row['limit_up_count'])} / {fmt_number(row['broken_limit_count'])}</strong></div>
          </div>
          <div class="report-footer">
            <span>指数: 上证 {fmt_number(row['sh_index_pct'], '%')} · 深成 {fmt_number(row['sz_index_pct'], '%')} · 创业板 {fmt_number(row['cyb_index_pct'], '%')}</span>
            <span>成交额 {fmt_amount(row['total_amount'])} · 上涨 / 下跌 {fmt_number(row['up_count'])} / {fmt_number(row['down_count'])}</span>
            <span class="report-link">打开日报</span>
          </div>
        </a>
        """
        for row in rows
    )
    recent_context_html = "\n".join(
        f"""
        <li>
          <span>{escape(row['trade_date'])}</span>
          <strong>{fmt_number(row['environment_score'])}</strong>
          <em>{escape(row['top_mainline_name'])}</em>
        </li>
        """
        for row in rows[:5]
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>强势股池日报总览</title>
  <style>
    :root {{
      --bg: #f3f6f1;
      --panel: rgba(255, 255, 255, 0.86);
      --ink: #172033;
      --muted: #667085;
      --line: rgba(23, 32, 51, 0.1);
      --blue: #175cd3;
      --amber: #b54708;
      --green: #067647;
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
    .wrap {{
      width: min(1320px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 70px;
    }}
    .hero {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 22px;
      background: linear-gradient(135deg, #172033 0%, #263c63 62%, #8a4b18 100%);
      color: #fff9ee;
      border-radius: 34px;
      padding: 30px;
      box-shadow: var(--shadow);
    }}
    .eyebrow {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.2em;
      color: rgba(255, 255, 255, 0.66);
    }}
    h1 {{
      margin: 14px 0 16px;
      font-size: clamp(28px, 4vw, 44px);
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    .hero p {{
      margin: 0;
      max-width: 760px;
      line-height: 1.7;
      color: rgba(255, 255, 255, 0.76);
    }}
    .hero-panel {{
      border: 1px solid rgba(255,255,255,0.18);
      background: rgba(255,255,255,0.1);
      backdrop-filter: blur(16px);
      border-radius: 24px;
      padding: 18px;
    }}
    .hero-panel span {{ color: rgba(255,255,255,0.66); font-size: 12px; }}
    .hero-panel strong {{ display: block; margin-top: 8px; font-size: 38px; }}
    .hero-panel em {{ display: block; margin-top: 8px; font-style: normal; color: rgba(255,255,255,0.8); }}
    .content-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 320px;
      gap: 22px;
      margin-top: 22px;
      align-items: start;
    }}
    .section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      padding: 22px;
    }}
    .section-title {{
      margin: 0 0 16px;
      font-size: 22px;
      letter-spacing: -0.04em;
    }}
    .report-card {{
      display: block;
      text-decoration: none;
      color: inherit;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 22px;
      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
      margin-bottom: 14px;
    }}
    .report-card:hover {{
      transform: translateY(-3px);
      box-shadow: var(--shadow);
      border-color: rgba(23, 92, 211, 0.28);
    }}
    .report-card-head {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      margin-bottom: 14px;
    }}
    .report-date {{
      font-size: 20px;
      font-weight: 900;
      letter-spacing: -0.04em;
    }}
    .report-phase {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 14px;
    }}
    .report-link {{
      color: var(--blue);
      font-size: 13px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .score-pill {{
      min-width: 64px;
      text-align: center;
      padding: 10px 12px;
      border-radius: 18px;
      background: #fff4e5;
      color: var(--amber);
      font-size: 22px;
      font-weight: 900;
    }}
    .report-metrics {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin: 16px 0;
    }}
    .metric {{
      background: #f8fafc;
      border-radius: 18px;
      padding: 14px;
      border: 1px solid var(--line);
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
    .context-list {{
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 10px;
    }}
    .context-list li {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 6px;
      padding: 13px 14px;
      border-radius: 18px;
      background: #fff;
      border: 1px solid var(--line);
    }}
    .context-list em {{
      grid-column: 1 / -1;
      color: var(--muted);
      font-style: normal;
      font-size: 13px;
    }}
    @media (max-width: 760px) {{
      .wrap {{ width: min(100vw - 20px, 1320px); }}
      .hero, .content-grid {{ grid-template-columns: 1fr; }}
      .hero {{ padding: 22px; border-radius: 26px; }}
      .report-card {{ padding: 18px; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div>
        <div class="eyebrow">FinCrawlerAI / Market Daily</div>
        <h1>强势股池日报总览</h1>
        <p>按交易日进入盘后工作台。这里不做复杂日历，只保留最近日报、环境状态、主线方向和强势股数量，方便快速回看。</p>
      </div>
      <aside class="hero-panel">
        <span>最新日报</span>
        <strong>{fmt_number(latest.get('environment_score'))}</strong>
        <em>{escape(str(latest.get('trade_date') or '--'))} · {escape(str(latest.get('environment_state') or '--'))}</em>
      </aside>
    </section>
    <div class="content-grid">
      <section class="section">
        <h2 class="section-title">日报入口</h2>
        {cards_html or '<p>暂无日报</p>'}
      </section>
      <aside class="section">
        <h2 class="section-title">最近 5 日</h2>
        <ul class="context-list">{recent_context_html}</ul>
        <p class="report-footer">日报数量 {len(rows)} · 最后生成 {escape(generated_at)}</p>
      </aside>
    </div>
  </div>
</body>
</html>
"""


def generate_index_page(
    output_dir: str | Path = "data/processed/market_daily",
    output_name: str = "market_daily_index.html",
) -> Path:
    output_dir_path = Path(output_dir).resolve()
    output_dir_path.mkdir(parents=True, exist_ok=True)
    rows = load_report_rows(output_dir_path)
    html = build_html(rows)
    output_path = output_dir_path / output_name
    output_path.write_text(html, encoding="utf-8")
    return output_path


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

    output_path = generate_index_page(args.output_dir, args.output_name)
    rows = load_report_rows(Path(args.output_dir).resolve())
    print(f"index_path={output_path}")
    print(f"report_count={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
