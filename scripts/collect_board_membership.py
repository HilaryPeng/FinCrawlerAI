#!/usr/bin/env python3
"""
Backfill stock_board_membership for a specific trade date.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def clear_proxy_env() -> None:
    """Clear common proxy env vars for the current process."""
    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ]:
        os.environ.pop(key, None)


def main() -> int:
    clear_proxy_env()

    from config.settings import get_config
    from src.db.connection import DatabaseConnection
    from src.db.schema import create_all_tables
    from src.market.collectors.boards_collector import BoardsCollector

    parser = argparse.ArgumentParser(description="Collect board membership only")
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    parser.add_argument(
        "--source",
        choices=["auto", "baostock"],
        default="baostock",
        help="Membership source to use",
    )
    parser.add_argument(
        "--board-type",
        choices=["industry", "concept"],
        default=None,
        help="Optional board type filter",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for number of boards to process",
    )
    args = parser.parse_args()

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    collector = BoardsCollector(db)
    if args.source == "baostock":
        count = collector.collect_industry_memberships_baostock(args.date)
    else:
        count = collector.collect_memberships_for_date(
            trade_date=args.date,
            board_type=args.board_type,
            limit=args.limit,
        )
    print(f"board_membership_inserted={count}")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
