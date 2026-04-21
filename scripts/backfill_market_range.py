#!/usr/bin/env python3
"""
Backfill the full market daily pipeline for a date range.

Default behavior:
- Skip Saturday/Sunday
- Collect quotes / boards / limit-up / breadth
- Optionally collect news and attention data
- Rebuild membership, unified board quotes, features, observation pool, reports
- Refresh report index at the end
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


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


def iter_trade_dates(start_date: str, end_date: str, include_weekends: bool) -> list[str]:
    start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    if end_dt < start_dt:
        raise ValueError("end date must be >= start date")

    dates: list[str] = []
    current = start_dt
    while current <= end_dt:
        if include_weekends or current.weekday() < 5:
            dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def main() -> int:
    clear_proxy_env()

    from config.settings import get_config
    from src.db.connection import DatabaseConnection
    from src.db.schema import create_all_tables
    from src.market.collectors import AttentionCollector, BoardsCollector
    from src.market.features import BoardFeatureBuilder, StockFeatureBuilder
    from src.market.ranker import ObservationPoolSelector
    from src.market.report import DailyReportGenerator
    from collect_market_data import collect_market_data

    parser = argparse.ArgumentParser(description="Backfill full market daily pipeline for a date range")
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD format")
    parser.add_argument(
        "--include-weekends",
        action="store_true",
        help="Include Saturday/Sunday dates instead of skipping them",
    )
    parser.add_argument(
        "--with-news",
        action="store_true",
        help="Also collect news during backfill",
    )
    parser.add_argument(
        "--news-sources",
        default="cailian,jygs",
        help="Comma-separated news sources: cailian,jygs",
    )
    parser.add_argument(
        "--with-attention",
        action="store_true",
        help="Also collect attention/hot-rank data during backfill",
    )
    parser.add_argument(
        "--attention-sources",
        default="eastmoney,xueqiu,ths",
        help="Comma-separated attention sources: eastmoney,xueqiu,ths",
    )
    args = parser.parse_args()

    trade_dates = iter_trade_dates(args.start, args.end, args.include_weekends)
    if not trade_dates:
        print("No dates selected")
        return 0

    news_sources = {item.strip() for item in args.news_sources.split(",") if item.strip()}
    attention_sources = {item.strip() for item in args.attention_sources.split(",") if item.strip()}

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    attention_collector = AttentionCollector(db)
    boards_collector = BoardsCollector(db)
    board_builder = BoardFeatureBuilder(db)
    stock_builder = StockFeatureBuilder(db)
    selector = ObservationPoolSelector(db)
    report_generator = DailyReportGenerator(db)

    print(f"Selected {len(trade_dates)} dates:", flush=True)
    for trade_date in trade_dates:
        print(f"  - {trade_date}", flush=True)

    for trade_date in trade_dates:
        print(f"\n{'=' * 60}", flush=True)
        print(f"Backfilling full pipeline for {trade_date}", flush=True)
        print(f"{'=' * 60}", flush=True)

        collect_result = collect_market_data(
            trade_date=trade_date,
            db_path=config.MARKET_DAILY_DB,
            with_news=args.with_news,
            news_sources=news_sources,
            with_attention=False,
        )
        print(f"collect_result={collect_result}", flush=True)

        membership_count = boards_collector.collect_industry_memberships_baostock(trade_date)
        print(f"board_membership_inserted={membership_count}", flush=True)

        unified_count = boards_collector.build_csrc_industry_board_quotes(trade_date)
        print(f"unified_board_quotes_inserted={unified_count}", flush=True)

        if args.with_attention:
            attention_count = attention_collector.collect(trade_date, sources=attention_sources)
            print(f"attention_rows_inserted={attention_count}", flush=True)

        board_count = board_builder.build(trade_date)
        stock_count = stock_builder.build(trade_date)
        print(f"board_features={board_count} stock_features={stock_count}", flush=True)

        pool_count = selector.build(trade_date)
        print(f"observation_pool_inserted={pool_count}", flush=True)

        report_result = report_generator.generate(trade_date)
        print(f"html_path={report_result['html_path']}", flush=True)

    index_script = project_root / "scripts" / "generate_market_daily_index.py"
    exit_code = os.system(f"{sys.executable} {index_script}")
    if exit_code != 0:
        print("Warning: failed to rebuild market_daily_index.html", flush=True)

    print("\nDone.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
