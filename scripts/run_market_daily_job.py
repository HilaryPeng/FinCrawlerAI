#!/usr/bin/env python3
"""
Run the full daily market pipeline locally on the server:
- collect market data
- collect board membership
- build unified board quotes
- build features
- build observation pool
- generate report + index
- publish HTML to nginx web root
- optionally notify Feishu
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

MIN_QUOTES_FOR_RETRY = 4500
MAX_COLLECT_RETRIES = 1


def clear_proxy_env() -> None:
    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]:
        os.environ.pop(key, None)


def publish_local_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    os.chmod(dest, 0o644)


def is_a_share_trade_date(trade_date: str) -> bool:
    import akshare as ak

    calendar = ak.tool_trade_date_hist_sina()
    if "trade_date" not in calendar.columns:
        raise RuntimeError("A-share calendar response missing trade_date column")
    trade_dates = {str(value)[:10] for value in calendar["trade_date"].astype(str).tolist()}
    return trade_date in trade_dates


def build_notification_markdown(report_json_path: Path, report_url: str, quality_status: str) -> str:
    data = json.loads(report_json_path.read_text(encoding="utf-8"))
    trade_date = data.get("metadata", {}).get("trade_date", "-")
    market_summary = data.get("market_summary", {})
    top_boards = data.get("top_boards", [])[:3]
    observation_pool = data.get("observation_pool", [])[:5]

    index_bits = []
    for label, key in [("上证", "sh_index_pct"), ("深成", "sz_index_pct"), ("创业板", "cyb_index_pct")]:
        value = market_summary.get(key)
        if value is None:
            continue
        try:
            text = f"{float(value):+.2f}%"
        except Exception:
            text = str(value)
        index_bits.append(f"{label} {text}")

    board_lines = []
    for board in top_boards:
        board_lines.append(
            f"- {board.get('board_name', '-')}: 分数 {board.get('board_score', '-')}, 涨跌 {board.get('pct_chg', '-')}"
        )

    stock_lines = []
    for row in observation_pool:
        stock_lines.append(
            f"- {row.get('name', '-')} {row.get('symbol', '-')}"
            f" | {row.get('role_tag', '-')}"
            f" | {row.get('board_name', '-')}"
        )

    parts = [
        f"## 市场观察日报 {trade_date}",
        "",
        f"**数据质量**: {quality_status}",
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


def run_collection_with_retry(
    *,
    collect_market_data_fn,
    trade_date: str,
    db_path,
    with_news: bool,
    news_sources: set[str],
    with_attention: bool,
    min_quote_count: int,
    max_collect_retries: int,
) -> tuple[dict, int]:
    retry_count = 0
    collect_result = collect_market_data_fn(
        trade_date=trade_date,
        db_path=db_path,
        with_news=with_news,
        news_sources=news_sources,
        with_attention=with_attention,
    )

    while (
        int(collect_result.get("quotes", 0) or 0) < min_quote_count
        and retry_count < max_collect_retries
    ):
        retry_count += 1
        print(
            f"quote_count_below_retry_threshold={collect_result.get('quotes', 0)}<{min_quote_count}; "
            f"retry_collect_attempt={retry_count}/{max_collect_retries}",
            flush=True,
        )
        collect_result = collect_market_data_fn(
            trade_date=trade_date,
            db_path=db_path,
            with_news=with_news,
            news_sources=news_sources,
            with_attention=with_attention,
        )

    return collect_result, retry_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily market pipeline on the server")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="Trade date in YYYY-MM-DD format")
    parser.add_argument("--with-news", action="store_true", help="Also collect news")
    parser.add_argument("--news-sources", default="jygs", help="Comma-separated news sources, e.g. jygs,cailian")
    parser.add_argument("--with-attention", action="store_true", help="Also collect attention / screener data")
    parser.add_argument(
        "--check-trade-date",
        action="store_true",
        help="Check the A-share trade calendar before running and skip non-trading dates",
    )
    parser.add_argument("--clear-proxy-env", action="store_true", help="Clear proxy env vars in current process before running")
    parser.add_argument("--web-root", default="/var/www/html", help="Nginx web root")
    parser.add_argument("--base-url", required=True, help="Public base URL, e.g. http://167.179.78.250")
    parser.add_argument("--notify-feishu", action="store_true", help="Send a Feishu update after publish")
    args = parser.parse_args()

    if args.clear_proxy_env:
        clear_proxy_env()

    trade_date = args.date
    datetime.strptime(trade_date, "%Y-%m-%d")
    if args.check_trade_date:
        if not is_a_share_trade_date(trade_date):
            print(f"skip_non_trading_date={trade_date}")
            return 0
        print(f"trade_date_check=passed:{trade_date}", flush=True)

    from config.settings import get_config
    from scripts.collect_market_data import collect_market_data
    from src.db.connection import DatabaseConnection
    from src.db.schema import create_all_tables
    from src.market.collectors.boards_collector import BoardsCollector
    from src.market.features import BoardFeatureBuilder, StockFeatureBuilder
    from src.market.quality import DataQualityChecker
    from src.market.ranker import ObservationPoolSelector
    from src.market.report import DailyReportGenerator
    from src.notifier.feishu import FeishuNotifier
    from src.specs import load_market_daily_spec
    from scripts.generate_market_daily_index import generate_index_page

    config = get_config()
    config.ensure_directories()

    news_sources = {item.strip() for item in args.news_sources.split(",") if item.strip()}

    print(f"=== Daily job start: {trade_date} ===", flush=True)
    collect_result, collect_retry_count = run_collection_with_retry(
        collect_market_data_fn=collect_market_data,
        trade_date=trade_date,
        db_path=config.MARKET_DAILY_DB,
        with_news=args.with_news,
        news_sources=news_sources,
        with_attention=args.with_attention,
        min_quote_count=MIN_QUOTES_FOR_RETRY,
        max_collect_retries=MAX_COLLECT_RETRIES,
    )
    print(f"collect_result={collect_result}", flush=True)
    print(f"collect_retry_count={collect_retry_count}", flush=True)

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    membership_count = BoardsCollector(db).collect_industry_memberships_baostock(trade_date)
    print(f"membership_inserted={membership_count}", flush=True)

    unified_count = BoardsCollector(db).build_csrc_industry_board_quotes(trade_date)
    print(f"unified_board_quotes_inserted={unified_count}", flush=True)

    board_feature_count = BoardFeatureBuilder(db).build(trade_date)
    stock_feature_count = StockFeatureBuilder(db).build(trade_date)
    print(f"board_features={board_feature_count}", flush=True)
    print(f"stock_features={stock_feature_count}", flush=True)

    observation_count = ObservationPoolSelector(db).build(trade_date)
    print(f"observation_pool_inserted={observation_count}", flush=True)

    report_result = DailyReportGenerator(db).generate(trade_date)
    print(f"report_result={report_result}", flush=True)

    index_path = generate_index_page()
    print(f"index_path={index_path}", flush=True)

    html_path = Path(report_result["html_path"]).resolve()
    report_name = html_path.name
    web_root = Path(args.web_root).expanduser().resolve()
    publish_local_file(html_path, web_root / report_name)
    publish_local_file(Path(index_path).resolve(), web_root / "index.html")
    publish_local_file(Path(index_path).resolve(), web_root / "market_daily_index.html")
    print(f"published_report={web_root / report_name}", flush=True)
    print(f"published_index={web_root / 'index.html'}", flush=True)

    quality = DataQualityChecker(db).check(trade_date)
    runtime_quality_spec = load_market_daily_spec().runtime["quality"]
    print(f"quality={quality}", flush=True)

    report_url = f"{args.base_url.rstrip('/')}/{report_name}"
    index_url = f"{args.base_url.rstrip('/')}/"
    print(f"report_url={report_url}", flush=True)
    print(f"index_url={index_url}", flush=True)
    publish_allowed = quality["status"] in set(runtime_quality_spec["publish_allow_statuses"])
    if not publish_allowed:
        print(f"publish_skipped_due_to_quality={quality['status']}", flush=True)

    if args.notify_feishu and publish_allowed:
        notifier = FeishuNotifier(config)
        markdown = build_notification_markdown(Path(report_result["json_path"]), report_url, quality["status"])
        notifier.send_markdown(title=f"市场观察日报 {trade_date}", markdown=markdown)
        print("feishu_notified=1", flush=True)

    print(f"=== Daily job done: {trade_date} ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
