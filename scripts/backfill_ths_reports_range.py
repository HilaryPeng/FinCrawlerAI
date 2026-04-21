#!/usr/bin/env python3
"""
Backfill attention signals and rebuild daily reports for a date range.

Notes:
- Skips Saturday/Sunday by default.
- When backfilling historical dates with Xueqiu/EM sources, the captured heat/rank
  reflects the fetch time snapshot rather than the true historical daily snapshot.
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
    from src.market.collectors import AttentionCollector
    from src.market.features import BoardFeatureBuilder, StockFeatureBuilder
    from src.market.ranker import ObservationPoolSelector
    from src.market.report import DailyReportGenerator

    parser = argparse.ArgumentParser(
        description="Backfill attention signals and rebuild reports for a date range"
    )
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD format")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD format")
    parser.add_argument(
        "--sources",
        default="eastmoney,xueqiu,ths",
        help="Comma-separated attention sources: eastmoney,xueqiu,ths",
    )
    parser.add_argument(
        "--include-weekends",
        action="store_true",
        help="Include Saturday/Sunday dates instead of skipping them",
    )
    args = parser.parse_args()

    trade_dates = iter_trade_dates(args.start, args.end, args.include_weekends)
    if not trade_dates:
        print("No dates selected")
        return 0
    sources = {item.strip() for item in args.sources.split(",") if item.strip()}
    if not sources:
        print("No sources selected")
        return 1

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    attention_collector = AttentionCollector(db)
    board_builder = BoardFeatureBuilder(db)
    stock_builder = StockFeatureBuilder(db)
    selector = ObservationPoolSelector(db)
    report_generator = DailyReportGenerator(db)

    print(f"Selected {len(trade_dates)} dates:", flush=True)
    for trade_date in trade_dates:
        print(f"  - {trade_date}", flush=True)

    for trade_date in trade_dates:
        print(f"\n{'=' * 60}", flush=True)
        print(f"Backfilling report for {trade_date}", flush=True)
        print(f"{'=' * 60}", flush=True)

        attention_count = attention_collector.collect(trade_date, sources=sources)
        print(f"attention_rows_inserted={attention_count}", flush=True)

        board_count = board_builder.build(trade_date)
        stock_count = stock_builder.build(trade_date)
        print(f"board_features={board_count} stock_features={stock_count}", flush=True)

        pool_count = selector.build(trade_date)
        print(f"observation_pool_inserted={pool_count}", flush=True)

        result = report_generator.generate(trade_date)
        print(f"html_path={result['html_path']}", flush=True)

    output_dir = project_root / "data" / "processed" / "market_daily"
    index_script = project_root / "scripts" / "generate_market_daily_index.py"
    exit_code = os.system(f"{sys.executable} {index_script}")
    if exit_code != 0:
        print("Warning: failed to rebuild market_daily_index.html", flush=True)

    print("\nDone.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
