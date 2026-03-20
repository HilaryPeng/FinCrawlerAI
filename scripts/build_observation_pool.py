#!/usr/bin/env python3
"""
Build the daily observation pool from ranked features.
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
    from src.market.ranker import ObservationPoolSelector

    parser = argparse.ArgumentParser(description="Build daily observation pool")
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    args = parser.parse_args()

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    count = ObservationPoolSelector(db).build(args.date)
    print(f"observation_pool_inserted={count}")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
