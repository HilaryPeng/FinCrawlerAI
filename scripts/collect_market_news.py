#!/usr/bin/env python3
"""
Collect daily market news into the market_daily database.

Sources:
- Cailian telegraph news for the given day
- JYGS (韭菜公社) action/limit-up style analysis for the given day
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))


def _day_ts_range(trade_date: str) -> tuple[int, int]:
    start_dt = datetime.strptime(trade_date, "%Y-%m-%d")
    end_dt = start_dt + timedelta(days=1)
    return int(start_dt.timestamp()), int(end_dt.timestamp())


def collect_market_news(trade_date: str, sources: set[str] | None = None) -> dict:
    from config.settings import get_config
    from src.db.connection import DatabaseConnection
    from src.db.schema import create_all_tables
    from src.market.news.news_collector import NewsCollector
    from src.scraper.cailian_scraper import CailianScraper
    from src.scraper.jiuyangongshe_scraper import JiuyangongsheScraper

    requested_sources = sources or {"cailian", "jygs"}

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)
    collector = NewsCollector(db)

    start_ts, end_ts = _day_ts_range(trade_date)
    results = {
        "trade_date": trade_date,
        "cailian_fetched": 0,
        "cailian_stored": 0,
        "jygs_fetched": 0,
        "jygs_stored": 0,
    }

    print(f"\n{'=' * 50}", flush=True)
    print(f"Collecting market news for {trade_date}", flush=True)
    print(f"{'=' * 50}", flush=True)

    requested_order = [source for source in ["cailian", "jygs"] if source in requested_sources]

    if "cailian" in requested_sources:
        step = requested_order.index("cailian") + 1
        total_steps = len(requested_order)
        print(f"[{step}/{total_steps}] Collecting Cailian news...", flush=True)
        try:
            cailian = CailianScraper(config)
            cailian_news = cailian.scrape_news(since_ts=start_ts, until_ts=end_ts)
            results["cailian_fetched"] = len(cailian_news)
            print(f"Fetched {len(cailian_news)} Cailian items", flush=True)
            stored = collector.collect_from_scraper("cailian", cailian_news)
            results["cailian_stored"] = stored
        except Exception as exc:
            print(f"Failed to collect Cailian news: {exc}", flush=True)

    if "jygs" in requested_sources:
        step = requested_order.index("jygs") + 1
        total_steps = len(requested_order)
        print(f"[{step}/{total_steps}] Collecting JYGS (韭菜公社) action news...", flush=True)
        try:
            jygs = JiuyangongsheScraper(config)
            jygs_news = jygs.scrape_action_as_news(trade_date)
            results["jygs_fetched"] = len(jygs_news)
            print(f"Fetched {len(jygs_news)} JYGS items", flush=True)
            stored = collector.collect_from_scraper("jygs", jygs_news)
            results["jygs_stored"] = stored
        except Exception as exc:
            print(f"Failed to collect JYGS news: {exc}", flush=True)

    counts = collector.get_news_count_by_date(trade_date)
    results["counts"] = counts

    print(f"\n{'=' * 50}", flush=True)
    print(f"News Summary for {trade_date}", flush=True)
    print(f"{'=' * 50}", flush=True)
    print(f"  Cailian fetched/stored: {results['cailian_fetched']} / {results['cailian_stored']}", flush=True)
    print(f"  JYGS fetched/stored:    {results['jygs_fetched']} / {results['jygs_stored']}", flush=True)
    print(f"  DB counts by source:    cailian={counts['cailian']} jygs={counts['jygs']} total={counts['total']}", flush=True)
    print(f"{'=' * 50}", flush=True)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect daily market news into database")
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    parser.add_argument(
        "--sources",
        default="cailian,jygs",
        help="Comma-separated sources to collect: cailian,jygs",
    )
    args = parser.parse_args()

    requested_sources = {item.strip() for item in args.sources.split(",") if item.strip()}
    results = collect_market_news(args.date, requested_sources)
    counts = results["counts"]
    return 0 if counts["total"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
