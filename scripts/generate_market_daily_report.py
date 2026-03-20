#!/usr/bin/env python3
"""
Generate JSON and Markdown daily market report.
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
    from src.market.report import DailyReportGenerator

    parser = argparse.ArgumentParser(description="Generate daily market report")
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    args = parser.parse_args()

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    result = DailyReportGenerator(db).generate(args.date)
    print(f"json_path={result['json_path']}")
    print(f"markdown_path={result['markdown_path']}")
    print(f"html_path={result['html_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
