#!/usr/bin/env python3
"""
Build unified board quotes from normalized membership and stock quotes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def main() -> int:
    from config.settings import get_config
    from src.db.connection import DatabaseConnection
    from src.db.schema import create_all_tables
    from src.market.collectors.boards_collector import BoardsCollector

    parser = argparse.ArgumentParser(description="Build unified board quotes")
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    args = parser.parse_args()

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    collector = BoardsCollector(db)
    count = collector.build_csrc_industry_board_quotes(args.date)
    print(f"unified_board_quotes_inserted={count}")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
