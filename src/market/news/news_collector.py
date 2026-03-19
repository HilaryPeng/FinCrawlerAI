"""
News collector for integrating scrapers with database.
"""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from src.db import (
    DatabaseConnection,
    NewsItemsRepository,
    NewsItemSymbolsRepository,
    NewsItemThemesRepository,
)
from src.market.news.stock_mention_extractor import StockMentionExtractor
from src.market.news.theme_extractor import ThemeExtractor


class NewsCollector:
    """Collector for news data from scrapers."""
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.news_repo = NewsItemsRepository(db)
        self.symbols_repo = NewsItemSymbolsRepository(db)
        self.themes_repo = NewsItemThemesRepository(db)
        self.stock_extractor = StockMentionExtractor()
        self.theme_extractor = ThemeExtractor()
    
    def collect_from_scraper(self, source: str, news_list: List[Dict]) -> int:
        """
        Collect news from scraper output and store in database.
        
        Args:
            source: Source name (cailian/jygs)
            news_list: List of news items from scraper
            
        Returns:
            Number of news items stored
        """
        print(f"Collecting {len(news_list)} news items from {source}...")
        
        count = 0
        symbols_count = 0
        themes_count = 0
        
        for news in news_list:
            try:
                news_id = self._store_news(source, news)
                if news_id:
                    sym_count = self._store_symbols(news_id, news)
                    themes_cnt = self._store_themes(news_id, news)
                    count += 1
                    symbols_count += sym_count
                    themes_count += themes_cnt
            except Exception as e:
                print(f"Failed to store news '{news.get('title', 'unknown')}': {e}")
                continue
        
        print(f"Stored {count} news items, {symbols_count} symbols, {themes_count} themes from {source}")
        return count
    
    def _store_news(self, source: str, news: Dict) -> Optional[int]:
        """Store a single news item."""
        source_uid = news.get("id") or news.get("url", "")
        
        publish_time = news.get("publish_time", "")
        publish_ts = None
        if publish_time:
            try:
                dt = datetime.strptime(publish_time, "%Y-%m-%d %H:%M:%S")
                publish_ts = int(dt.timestamp())
            except Exception:
                pass
        
        record = {
            "source": source,
            "source_uid": source_uid,
            "title": news.get("title", ""),
            "content": news.get("content", ""),
            "publish_time": publish_time,
            "publish_ts": publish_ts,
            "url": news.get("url", ""),
            "event_id": None,
            "raw_json": json.dumps(news, ensure_ascii=False),
        }
        
        unique_keys = self.news_repo.get_unique_keys()
        return self.news_repo.upsert(record, unique_keys)
    
    def _store_symbols(self, news_id: int, news: Dict) -> int:
        """Store stock symbols associated with news."""
        symbols = self.stock_extractor.extract(news.get("title", "") + " " + news.get("content", ""))
        
        count = 0
        for symbol_data in symbols:
            record = {
                "news_id": news_id,
                "symbol": symbol_data.get("symbol", ""),
                "stock_name": symbol_data.get("name", ""),
                "relation_type": "mentioned",
            }
            try:
                self.symbols_repo.insert(record)
                count += 1
            except Exception as e:
                print(f"Warning: Failed to insert symbol {symbol_data.get('symbol')}: {e}")
        
        return count
    
    def _store_themes(self, news_id: int, news: Dict) -> int:
        """Store themes/topics associated with news."""
        themes = self.theme_extractor.extract(news.get("title", "") + " " + news.get("content", ""))
        
        count = 0
        for theme_data in themes:
            record = {
                "news_id": news_id,
                "theme_name": theme_data.get("name", ""),
                "theme_type": theme_data.get("type", "concept"),
            }
            try:
                self.themes_repo.insert(record)
                count += 1
            except Exception as e:
                print(f"Warning: Failed to insert theme {theme_data.get('name')}: {e}")
        
        return count
    
    def get_news_count_by_date(self, trade_date: str) -> Dict[str, int]:
        """Get news count by source for a specific date."""
        result = {"cailian": 0, "jygs": 0, "total": 0}
        
        start_ts = int(datetime.strptime(trade_date, "%Y-%m-%d").timestamp())
        end_ts = start_ts + 86400
        
        for source in ["cailian", "jygs"]:
            sql = """
                SELECT COUNT(*) as cnt FROM news_items 
                WHERE source = ? AND publish_ts >= ? AND publish_ts < ?
            """
            row = self.db.fetchone(sql, (source, start_ts, end_ts))
            cnt = row["cnt"] if row else 0
            result[source] = cnt
            result["total"] += cnt
        
        return result
