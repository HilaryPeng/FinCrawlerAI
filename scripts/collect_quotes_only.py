#!/usr/bin/env python3
"""
Collect stock daily quotes only.

This script clears common proxy environment variables in-process so it can be
run directly after the user disables proxy usage for AkShare-related requests.
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
    from src.market.collectors.quotes_collector import QuotesCollector

    parser = argparse.ArgumentParser(description="Collect stock daily quotes only")
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    args = parser.parse_args()

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    collector = QuotesCollector(db)
    count = collector.collect(args.date)

    print(f"quotes_inserted={count}")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
