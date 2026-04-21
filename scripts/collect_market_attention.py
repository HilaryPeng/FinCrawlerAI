#!/usr/bin/env python3
"""
Collect daily stock attention and screener data.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def clear_proxy_env() -> None:
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
    from src.market.collectors import AttentionCollector

    parser = argparse.ArgumentParser(description="Collect daily stock attention data")
    parser.add_argument("--date", required=True, help="Trade date in YYYY-MM-DD format")
    parser.add_argument(
        "--sources",
        default="eastmoney,xueqiu,ths",
        help="Comma-separated sources: eastmoney,xueqiu,ths",
    )
    args = parser.parse_args()

    config = get_config()
    config.ensure_directories()

    db = DatabaseConnection(config.MARKET_DAILY_DB)
    create_all_tables(db)

    sources = {item.strip() for item in args.sources.split(",") if item.strip()}
    count = AttentionCollector(db).collect(args.date, sources=sources)
    print(f"attention_rows_inserted={count}")
    return 0 if count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
