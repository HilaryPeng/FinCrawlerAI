#!/usr/bin/env python3
"""
Market daily data collection script.
Collects all market data for a given trade date.
"""

import sys
import argparse
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
)


def collect_market_data(trade_date: str, db_path: Path = None) -> dict:
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
    
    print(f"\n{'='*50}", flush=True)
    print(f"Collection Summary for {trade_date}", flush=True)
    print(f"{'='*50}", flush=True)
    print(f"  Quotes:         {results['quotes']}", flush=True)
    print(f"  Boards:         {results['boards']}", flush=True)
    print(f"  Limit Ups:      {results['limit_ups']}", flush=True)
    print(f"  Market Breadth: {results['market_breadth']}", flush=True)
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
    args = parser.parse_args()
    
    if args.date:
        trade_date = args.date
    else:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    
    db_path = Path(args.db_path) if args.db_path else None
    
    results = collect_market_data(trade_date, db_path)
    
    total = sum(v for k, v in results.items() if k != "trade_date")
    if total > 0:
        print(f"Successfully collected {total} records", flush=True)
        return 0
    else:
        print("No data collected", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
