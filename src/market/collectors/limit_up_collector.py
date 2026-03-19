"""
Limit up data collector using AkShare.
"""

from datetime import datetime
from typing import List, Dict, Any
import pandas as pd
import akshare as ak

from src.db import DatabaseConnection, DailyStockLimitsRepository
from src.utils.symbols import normalize_symbol


class LimitUpCollector:
    """Collector for limit up (涨停), broken limit (炸板), and streak data."""
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.repo = DailyStockLimitsRepository(db)
    
    def collect(self, trade_date: str) -> int:
        """
        Collect and store limit up data for a given date.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            Number of limit up records collected
        """
        print(f"Collecting limit up data for {trade_date}...", flush=True)
        
        records = self._fetch_limit_ups(trade_date)
        if not records:
            print(f"No limit up data collected for {trade_date}", flush=True)
            return 0
        
        unique_keys = self.repo.get_unique_keys()
        count = self.repo.upsert_many(records, unique_keys)
        print(f"Stored {count} limit up records for {trade_date}", flush=True)
        return count
    
    def _fetch_limit_ups(self, trade_date: str) -> List[Dict[str, Any]]:
        """
        Fetch limit up data from AkShare.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            List of limit up records
        """
        records = []
        
        date_str = trade_date.replace("-", "")
        
        print(f"Fetching limit-up pools for {trade_date}...", flush=True)
        limit_up_df = self._fetch_limit_up_stocks(date_str)
        if limit_up_df is not None:
            print(f"Limit-up pool rows={len(limit_up_df)}", flush=True)
            for _, row in limit_up_df.iterrows():
                record = self._normalize_limit_record(row, trade_date, limit_up=True)
                records.append(record)
        
        limit_down_df = self._fetch_limit_down_stocks(date_str)
        if limit_down_df is not None:
            print(f"Broken-limit pool rows={len(limit_down_df)}", flush=True)
            for _, row in limit_down_df.iterrows():
                record = self._normalize_limit_record(row, trade_date, limit_up=False)
                records.append(record)

        if records:
            sample = records[0]
            print(
                f"Limit record sample: {sample['symbol']} {sample['name']} streak={sample['limit_up_streak']} reason={sample['limit_reason']}",
                flush=True,
            )
        
        return records
    
    def _fetch_limit_up_stocks(self, date_str: str) -> pd.DataFrame:
        """Fetch limit up stocks from AkShare."""
        try:
            df = ak.stock_zt_pool_em(date=date_str)
            return df
        except Exception as e:
            print(f"Failed to fetch limit up pool: {e}", flush=True)
            return None
    
    def _fetch_limit_down_stocks(self, date_str: str) -> pd.DataFrame:
        """Fetch limit down stocks from AkShare."""
        try:
            df = ak.stock_zt_pool_dtgc_em(date=date_str)
            return df
        except Exception as e:
            print(f"Failed to fetch limit down pool: {e}", flush=True)
            return None
    
    def _normalize_limit_record(self, row: pd.Series, trade_date: str, limit_up: bool) -> Dict[str, Any]:
        """Normalize a limit up/down record to database format."""
        raw_symbol = row.get('代码', '')
        return {
            "trade_date": trade_date,
            "symbol": normalize_symbol(raw_symbol),
            "name": row.get('名称', ''),
            "limit_up": 1 if limit_up else 0,
            "broken_limit": 0,
            "limit_up_streak": int(row.get('连板数', 0)) if pd.notna(row.get('连板数')) else 0,
            "first_limit_time": None,
            "final_limit_time": row.get('最后一次涨停时间', None),
            "limit_reason": row.get('涨停原因', ''),
            "source": "akshare",
        }
    
    def collect_zt_pool(self, trade_date: str) -> int:
        """
        Collect detailed limit up pool data.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            Number of records collected
        """
        date_str = trade_date.replace("-", "")
        
        try:
            print(f"Fetching detailed ZT pool for {trade_date}...", flush=True)
            df = ak.stock_zt_pool_em(date=date_str)
            if df is None or df.empty:
                print(f"ZT pool empty for {trade_date}", flush=True)
                return 0
        except Exception as e:
            print(f"Failed to fetch ZT pool: {e}", flush=True)
            return 0
        
        records = []
        for _, row in df.iterrows():
            raw_symbol = row.get('代码', '')
            record = {
                "trade_date": trade_date,
                "symbol": normalize_symbol(raw_symbol),
                "name": row.get('名称', ''),
                "limit_up": 1,
                "broken_limit": 0,
                "limit_up_streak": int(row.get('连板数', 0)) if pd.notna(row.get('连板数')) else 0,
                "first_limit_time": row.get('首次涨停时间', None),
                "final_limit_time": row.get('最后一次涨停时间', None),
                "limit_reason": row.get('涨停原因', ''),
                "source": "akshare",
            }
            records.append(record)
        
        if records:
            unique_keys = self.repo.get_unique_keys()
            print(f"ZT pool rows={len(records)}", flush=True)
            sample = records[0]
            print(
                f"ZT sample: {sample['symbol']} {sample['name']} streak={sample['limit_up_streak']} reason={sample['limit_reason']}",
                flush=True,
            )
            count = self.repo.upsert_many(records, unique_keys)
            print(f"Stored {count} ZT pool records for {trade_date}", flush=True)
            return count
        return 0
    
    def collect_zt_pool_strong(self, trade_date: str) -> int:
        """
        Collect strong limit up pool (强势股池).
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            Number of records collected
        """
        date_str = trade_date.replace("-", "")
        
        try:
            df = ak.stock_zt_pool_strong_em(date=date_str)
            if df is None or df.empty:
                print(f"Strong ZT pool empty for {trade_date}", flush=True)
                return 0
        except Exception as e:
            print(f"Failed to fetch strong ZT pool: {e}", flush=True)
            return 0
        
        records = []
        for _, row in df.iterrows():
            raw_symbol = row.get('代码', '')
            record = {
                "trade_date": trade_date,
                "symbol": normalize_symbol(raw_symbol),
                "name": row.get('名称', ''),
                "limit_up": 1,
                "broken_limit": 0,
                "limit_up_streak": int(row.get('连板数', 0)) if pd.notna(row.get('连板数')) else 0,
                "first_limit_time": None,
                "final_limit_time": None,
                "limit_reason": row.get('涨停原因', ''),
                "source": "akshare",
            }
            records.append(record)
        
        if records:
            unique_keys = self.repo.get_unique_keys()
            print(f"Strong ZT pool rows={len(records)}", flush=True)
            count = self.repo.upsert_many(records, unique_keys)
            print(f"Stored {count} strong ZT pool records for {trade_date}", flush=True)
            return count
        return 0
