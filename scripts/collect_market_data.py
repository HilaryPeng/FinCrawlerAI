#!/usr/bin/env python3
"""
Market daily data collection script.
Collects all market data for a given trade date.
"""

import sys
import argparse
import multiprocessing as mp
import os
import queue
from datetime import datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import get_config
from src.db import DatabaseConnection, create_all_tables
from src.market.collectors import (
    QuotesCollector,
    BoardsCollector,
    LimitUpCollector,
    MarketBreadthCollector,
    AttentionCollector,
)
from src.market.quality import DataQualityChecker
from scripts.collect_market_news import collect_market_news


ATTENTION_TIMEOUT_SECONDS = int(os.getenv("MARKET_ATTENTION_TIMEOUT_SECONDS", "300"))


def _collect_attention_worker(trade_date: str, db_path: str, result_queue) -> None:
    try:
        db = DatabaseConnection(Path(db_path))
        create_all_tables(db)
        count = AttentionCollector(db).collect(trade_date)
        result_queue.put({"ok": True, "count": count})
    except Exception as exc:
        result_queue.put({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def collect_attention_non_blocking(
    trade_date: str,
    db_path: Path | str,
    timeout_seconds: float = ATTENTION_TIMEOUT_SECONDS,
    worker_fn=_collect_attention_worker,
) -> int:
    result_queue = mp.Queue()
    process = mp.Process(
        target=worker_fn,
        args=(trade_date, str(db_path), result_queue),
        daemon=True,
    )
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(5)
        print(f"attention_timeout={timeout_seconds}s; attention_skipped=1", flush=True)
        return 0

    try:
        result = result_queue.get(timeout=1)
    except queue.Empty:
        print(f"attention_failed=no_result exitcode={process.exitcode}; attention_skipped=1", flush=True)
        return 0

    if not result.get("ok"):
        print(f"attention_failed={result.get('error', 'unknown')}; attention_skipped=1", flush=True)
        return 0

    return int(result.get("count", 0) or 0)


def collect_market_data(
    trade_date: str,
    db_path: Path = None,
    with_news: bool = False,
    news_sources: set[str] | None = None,
    with_attention: bool = False,
) -> dict:
    """
    Collect all market data for a given trade date.
    
    Args:
        trade_date: Trade date in YYYY-MM-DD format
        db_path: Optional database path override
        
    Returns:
        Dictionary with collection results
    """
    config = get_config()
    
    if db_path is None:
        db_path = config.MARKET_DAILY_DB
    
    db = DatabaseConnection(db_path)
    create_all_tables(db)
    
    results = {
        "trade_date": trade_date,
        "quotes": 0,
        "boards": 0,
        "limit_ups": 0,
        "market_breadth": 0,
        "news_total": 0,
        "attention": 0,
    }
    
    print(f"\n{'='*50}", flush=True)
    print(f"Collecting market data for {trade_date}", flush=True)
    print(f"{'='*50}\n", flush=True)
    
    print("[1/4] Collecting stock quotes...", flush=True)
    quotes_collector = QuotesCollector(db)
    quotes_count = quotes_collector.collect(trade_date)
    results["quotes"] = quotes_count
    
    print("[2/4] Collecting board quotes...", flush=True)
    boards_collector = BoardsCollector(db)
    # Board quote collection is stable on THS fallback; membership still needs
    # a separate reliable source and is skipped here to keep the pipeline moving.
    boards_count = boards_collector.collect(trade_date, include_members=False)
    results["boards"] = boards_count
    
    print("[3/4] Collecting limit-up pool...", flush=True)
    limit_up_collector = LimitUpCollector(db)
    limit_count = limit_up_collector.collect_zt_pool(trade_date)
    results["limit_ups"] = limit_count
    
    print("[4/4] Collecting market breadth...", flush=True)
    breadth_collector = MarketBreadthCollector(db)
    breadth_count = breadth_collector.collect(trade_date)
    results["market_breadth"] = breadth_count

    if with_news:
        print("[news] Collecting Cailian / 韭菜公社 news...", flush=True)
        news_results = collect_market_news(trade_date, news_sources or {"cailian", "jygs"})
        results["news_total"] = news_results["counts"]["total"]

    if with_attention:
        print("[attention] Collecting EM/Xueqiu/THS screeners...", flush=True)
        attention_count = collect_attention_non_blocking(trade_date, db_path)
        results["attention"] = attention_count
    
    print(f"\n{'='*50}", flush=True)
    print(f"Collection Summary for {trade_date}", flush=True)
    print(f"{'='*50}", flush=True)
    print(f"  Quotes:         {results['quotes']}", flush=True)
    print(f"  Boards:         {results['boards']}", flush=True)
    print(f"  Limit Ups:      {results['limit_ups']}", flush=True)
    print(f"  Market Breadth: {results['market_breadth']}", flush=True)
    if with_news:
        print(f"  News Total:     {results['news_total']}", flush=True)
    if with_attention:
        print(f"  Attention:      {results['attention']}", flush=True)
    quality = DataQualityChecker(db).check(trade_date)
    results["quality_status"] = quality["status"]
    print(
        "  Quality:        "
        f"{quality['status']} "
        f"(quotes={quality['quote_count']}/{quality['required_quotes']}, "
        f"boards={quality['board_count']}, breadth={quality['breadth_count']})",
        flush=True,
    )
    print(f"{'='*50}\n", flush=True)
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Collect market daily data")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Trade date in YYYY-MM-DD format (default: today)",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Database path override",
    )
    parser.add_argument(
        "--with-news",
        action="store_true",
        help="Also collect Cailian and JYGS (韭菜公社) news into market_daily.db",
    )
    parser.add_argument(
        "--news-sources",
        type=str,
        default="cailian,jygs",
        help="Comma-separated news sources for --with-news: cailian,jygs",
    )
    parser.add_argument(
        "--with-attention",
        action="store_true",
        help="Also collect EM/Xueqiu/THS hot-rank and screener data",
    )
    args = parser.parse_args()
    
    if args.date:
        trade_date = args.date
    else:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    
    db_path = Path(args.db_path) if args.db_path else None
    
    news_sources = {item.strip() for item in args.news_sources.split(",") if item.strip()}
    results = collect_market_data(
        trade_date,
        db_path,
        with_news=args.with_news,
        news_sources=news_sources,
        with_attention=args.with_attention,
    )
    
    total = sum(v for v in results.values() if isinstance(v, (int, float)))
    if total > 0:
        print(f"Successfully collected {total} records", flush=True)
        return 0
    else:
        print("No data collected", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
