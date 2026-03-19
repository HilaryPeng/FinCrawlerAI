#!/usr/bin/env python3
"""
Test news collection.
"""

import sys
import argparse
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import get_config
from src.db import DatabaseConnection
from src.market.news import NewsCollector

config = get_config()
db = DatabaseConnection(config.MARKET_DAILY_DB)

collector = NewsCollector(db)


def cleanup_test_data():
    """Remove test data from database."""
    print("Cleaning up test data...")
    db.execute("DELETE FROM news_item_symbols WHERE news_id IN (SELECT id FROM news_items WHERE source = 'test')", ())
    db.execute("DELETE FROM news_item_themes WHERE news_id IN (SELECT id FROM news_items WHERE source = 'test')", ())
    db.execute("DELETE FROM news_items WHERE source = 'test'", ())
    print("Test data cleaned up.")


def main():
    parser = argparse.ArgumentParser(description="Test news collection")
    parser.add_argument("--cleanup", action="store_true", help="Clean up test data after running")
    args = parser.parse_args()
    
    test_news = [
        {
            "title": "比亚迪发布新车 搭载宁德时代电池",
            "content": "比亚迪今日发布新款电动汽车，采用宁德时代提供的磷酸铁锂电池。",
            "publish_time": "2026-03-18 10:00:00",
            "url": "https://example.com/1",
        },
        {
            "title": "人工智能板块持续火热",
            "content": "AI芯片、算力概念股今日集体上涨，寒武纪、海光信息涨幅居前。",
            "publish_time": "2026-03-18 11:00:00",
            "url": "https://example.com/2",
        },
        {
            "title": "贵州茅台股价创新高",
            "content": "白酒板块今日表现强势，贵州茅台股价突破1800元，五粮液、泸州老窖跟涨。",
            "publish_time": "2026-03-18 12:00:00",
            "url": "https://example.com/3",
        },
    ]

    count = collector.collect_from_scraper("test", test_news)
    print(f"Stored {count} test news items")

    total_news = collector.news_repo.count()
    total_symbols = collector.symbols_repo.count()
    total_themes = collector.themes_repo.count()

    print(f"\nTotal in database:")
    print(f"  news_items: {total_news}")
    print(f"  news_item_symbols: {total_symbols}")
    print(f"  news_item_themes: {total_themes}")
    
    if args.cleanup:
        cleanup_test_data()


if __name__ == "__main__":
    main()
