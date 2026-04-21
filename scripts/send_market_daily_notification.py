#!/usr/bin/env python3
"""
Send a Feishu markdown notification for a generated daily market report.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def build_markdown(report_json_path: Path, report_url: str, quality_status: str | None = None) -> str:
    data = json.loads(report_json_path.read_text(encoding="utf-8"))
    trade_date = data.get("metadata", {}).get("trade_date", "-")
    market_summary = data.get("market_summary", {})
    top_boards = data.get("top_boards", [])[:3]
    observation_pool = data.get("observation_pool", [])[:5]

    index_bits: list[str] = []
    for label, key in [("上证", "sh_index_pct"), ("深成", "sz_index_pct"), ("创业板", "cyb_index_pct")]:
        value = market_summary.get(key)
        if value is None:
            continue
        try:
            text = f"{float(value):+.2f}%"
        except Exception:
            text = str(value)
        index_bits.append(f"{label} {text}")

    board_lines = [
        f"- {board.get('board_name', '-')}: 分数 {board.get('board_score', '-')}, 涨跌 {board.get('pct_chg', '-')}"
        for board in top_boards
    ]

    stock_lines = [
        f"- {row.get('name', '-')} {row.get('symbol', '-')}"
        f" | {row.get('role_tag', '-')}"
        f" | {row.get('board_name', '-')}"
        for row in observation_pool
    ]

    parts = [
        f"## 市场观察日报 {trade_date}",
        "",
        f"**数据质量**: {quality_status or '-'}",
        f"**指数**: {' | '.join(index_bits) if index_bits else '-'}",
        f"**涨停 / 连板**: {market_summary.get('limit_up_count', '-')} / {market_summary.get('highest_streak', '-')}",
        "",
        "### 主线板块",
        *(board_lines or ["- 暂无"]),
        "",
        "### 核心标的",
        *(stock_lines or ["- 暂无"]),
        "",
        f"[打开网页日报]({report_url})",
    ]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Feishu notification for a market daily report")
    parser.add_argument("--json-path", required=True, help="Path to market_daily_YYYYMMDD.json")
    parser.add_argument("--report-url", required=True, help="Public URL of the HTML report")
    parser.add_argument("--quality-status", default="", help="Optional quality status label")
    parser.add_argument("--title", default="", help="Optional Feishu title")
    args = parser.parse_args()

    from config.settings import get_config
    from src.notifier.feishu import FeishuNotifier

    json_path = Path(args.json_path).expanduser().resolve()
    if not json_path.exists():
        raise FileNotFoundError(f"Report JSON not found: {json_path}")

    cfg = get_config()
    notifier = FeishuNotifier(cfg)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    trade_date = payload.get("metadata", {}).get("trade_date", "-")
    title = args.title or f"市场观察日报 {trade_date}"
    markdown = build_markdown(json_path, args.report_url, args.quality_status or None)
    notifier.send_markdown(title=title, markdown=markdown)
    print("feishu_sent=1", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
