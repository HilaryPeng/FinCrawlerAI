#!/usr/bin/env python3
"""
Check market daily data completeness for a trade date.
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
    from src.market.quality import DataQualityChecker

    parser = argparse.ArgumentParser(description="Check market daily data quality")
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    args = parser.parse_args()

    config = get_config()
    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    result = DataQualityChecker(db).check(args.date)

    print(f"trade_date={result['trade_date']}")
    print(f"status={result['status']}")
    print(f"quote_count={result['quote_count']}")
    print(f"board_count={result['board_count']}")
    print(f"limit_count={result['limit_count']}")
    print(f"breadth_count={result['breadth_count']}")
    print(f"membership_count={result['membership_count']}")
    print(f"news_count={result['news_count']}")
    print(f"baseline_quotes={result['baseline_quotes']}")
    print(f"required_quotes={result['required_quotes']}")
    print(f"quote_ratio={result['quote_ratio']}")
    print(f"checks={result['checks']}")

    return 0 if result["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
