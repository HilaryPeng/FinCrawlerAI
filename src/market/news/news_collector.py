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
                    self._reset_derived_links(news_id)
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
        source_uid = news.get("source_uid") or news.get("id") or news.get("url", "")
        if not source_uid:
            source_uid = f"{source}:{news.get('publish_time', '')}:{news.get('title', '')[:80]}"
        
        publish_time = news.get("publish_time", "")
        publish_ts = news.get("publish_ts")
        if publish_ts is None and publish_time:
            try:
                dt = datetime.strptime(publish_time, "%Y-%m-%d %H:%M:%S")
                publish_ts = int(dt.timestamp())
            except Exception:
                publish_ts = None
        
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
        self.news_repo.upsert(record, unique_keys)
        stored = self.news_repo.find_one({"source": source, "source_uid": source_uid})
        if stored:
            return stored.get("id")
        return None

    def _reset_derived_links(self, news_id: int) -> None:
        """Remove old symbol/theme links before recomputing them for a news item."""
        self.db.execute("DELETE FROM news_item_symbols WHERE news_id = ?", (news_id,))
        self.db.execute("DELETE FROM news_item_themes WHERE news_id = ?", (news_id,))

    def _store_symbols(self, news_id: int, news: Dict) -> int:
        """Store stock symbols associated with news."""
        symbols = self._extract_symbols(news)
        count = 0
        seen = set()
        for symbol_data in symbols:
            symbol = symbol_data.get("symbol", "")
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            record = {
                "news_id": news_id,
                "symbol": symbol,
                "stock_name": symbol_data.get("name", ""),
                "relation_type": symbol_data.get("relation_type", "mentioned"),
            }
            try:
                self.symbols_repo.insert(record)
                count += 1
            except Exception as e:
                print(f"Warning: Failed to insert symbol {symbol}: {e}")
        
        return count
    
    def _store_themes(self, news_id: int, news: Dict) -> int:
        """Store themes/topics associated with news."""
        themes = self._extract_themes(news)
        count = 0
        seen = set()
        for theme_data in themes:
            theme_name = theme_data.get("name", "")
            theme_type = theme_data.get("type", "concept")
            theme_key = (theme_name, theme_type)
            if not theme_name or theme_key in seen:
                continue
            seen.add(theme_key)
            record = {
                "news_id": news_id,
                "theme_name": theme_name,
                "theme_type": theme_type,
            }
            try:
                self.themes_repo.insert(record)
                count += 1
            except Exception as e:
                print(f"Warning: Failed to insert theme {theme_name}: {e}")
        
        return count

    def _extract_symbols(self, news: Dict) -> List[Dict[str, Any]]:
        explicit_symbols = news.get("symbols")
        if isinstance(explicit_symbols, list) and explicit_symbols:
            return explicit_symbols

        stock_code = news.get("stock_code")
        stock_name = news.get("stock_name")
        if stock_code:
            return [
                {
                    "symbol": self.stock_extractor.normalize(stock_code),
                    "name": stock_name or stock_code,
                    "relation_type": "primary",
                }
            ]

        text = news.get("title", "") + " " + news.get("content", "")
        return self.stock_extractor.extract(text)

    def _extract_themes(self, news: Dict) -> List[Dict[str, Any]]:
        explicit_themes = news.get("themes")
        if isinstance(explicit_themes, list) and explicit_themes:
            return explicit_themes

        themes: List[Dict[str, Any]] = []
        field_name = (news.get("field_name") or "").strip()
        stock_name = (news.get("stock_name") or "").strip()
        stock_code = (news.get("stock_code") or "").strip()
        if field_name:
            themes.append({"name": field_name, "type": "concept"})

        for tag in news.get("tags") or []:
            if not isinstance(tag, str):
                continue
            tag = tag.strip()
            if (
                len(tag) >= 2
                and tag not in {"异动解析", "财联社", "韭研公社", "韭菜公社"}
                and tag != stock_name
                and tag != stock_code
                and not tag.isdigit()
            ):
                themes.append({"name": tag, "type": "concept"})

        text = news.get("title", "") + " " + news.get("content", "")
        themes.extend(self.theme_extractor.extract(text))
        return themes
    
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
