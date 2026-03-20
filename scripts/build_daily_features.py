#!/usr/bin/env python3
"""
Build daily board and stock features.
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
    from src.market.features import BoardFeatureBuilder, StockFeatureBuilder

    parser = argparse.ArgumentParser(description="Build daily board and stock features")
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    args = parser.parse_args()

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    print(f"\n{'=' * 50}", flush=True)
    print(f"Building daily features for {args.date}", flush=True)
    print(f"{'=' * 50}", flush=True)

    print("[1/2] Building board features...", flush=True)
    board_count = BoardFeatureBuilder(db).build(args.date)

    print("[2/2] Building stock features...", flush=True)
    stock_count = StockFeatureBuilder(db).build(args.date)

    print(f"\n{'=' * 50}", flush=True)
    print(f"Feature Summary for {args.date}", flush=True)
    print(f"{'=' * 50}", flush=True)
    print(f"  Board Features: {board_count}", flush=True)
    print(f"  Stock Features: {stock_count}", flush=True)
    print(f"{'=' * 50}", flush=True)

    return 0 if (board_count + stock_count) > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
