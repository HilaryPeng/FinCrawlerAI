"""
Market breadth data collector using AkShare.
"""

from typing import Dict, Any
import pandas as pd
import akshare as ak

from src.db import DatabaseConnection, DailyMarketBreadthRepository


class MarketBreadthCollector:
    """Collector for market breadth and sentiment data."""
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.repo = DailyMarketBreadthRepository(db)
    
    def collect(self, trade_date: str) -> int:
        """
        Collect and store market breadth data for a given date.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            Number of records collected (1 if successful, 0 if failed)
        """
        print(f"Collecting market breadth for {trade_date}...", flush=True)
        
        record = self._fetch_breadth(trade_date)
        if not record:
            print(f"No market breadth data collected for {trade_date}", flush=True)
            return 0
        
        print(
            "Market breadth snapshot: "
            f"sh={record['sh_index_pct']} sz={record['sz_index_pct']} cyb={record['cyb_index_pct']} "
            f"up={record['up_count']} down={record['down_count']} limit_up={record['limit_up_count']} "
            f"broken_limit={record['broken_limit_count']} highest_streak={record['highest_streak']}",
            flush=True,
        )
        self.repo.upsert(record, ["trade_date"])
        print(f"Stored market breadth for {trade_date}", flush=True)
        return 1
    
    def _fetch_breadth(self, trade_date: str) -> Dict[str, Any]:
        """
        Fetch market breadth data from AkShare.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            Market breadth record
        """
        record = {
            "trade_date": trade_date,
            "sh_index_pct": None,
            "sz_index_pct": None,
            "cyb_index_pct": None,
            "total_amount": None,
            "up_count": None,
            "down_count": None,
            "limit_up_count": None,
            "limit_down_count": None,
            "broken_limit_count": None,
            "highest_streak": None,
        }
        
        print("Fetching index data...", flush=True)
        self._fetch_index_data(record, trade_date)
        print("Aggregating market summary from daily_stock_quotes...", flush=True)
        self._fetch_market_summary(record, trade_date)
        print("Fetching limit statistics...", flush=True)
        self._fetch_limit_stats(record, trade_date)
        
        return record
    
    def _fetch_index_data(self, record: Dict[str, Any], trade_date: str):
        """Fetch major index data for the given trade date."""
        date_str = trade_date.replace("-", "")
        try:
            df = ak.stock_zh_index_daily(symbol="sh000001")
            if df is not None and not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                target_date = pd.to_datetime(trade_date)
                df = df[df['date'] <= target_date]
                if not df.empty:
                    latest = df.iloc[-1]
                    close = latest.get('close', 0)
                    prev_close = df.iloc[-2].get('close', close) if len(df) > 1 else close
                    if prev_close and close:
                        record["sh_index_pct"] = round((close - prev_close) / prev_close * 100, 2)
        except Exception as e:
            print(f"Failed to fetch SH index: {e}", flush=True)
        
        try:
            df = ak.stock_zh_index_daily(symbol="sz399001")
            if df is not None and not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                target_date = pd.to_datetime(trade_date)
                df = df[df['date'] <= target_date]
                if not df.empty:
                    latest = df.iloc[-1]
                    close = latest.get('close', 0)
                    prev_close = df.iloc[-2].get('close', close) if len(df) > 1 else close
                    if prev_close and close:
                        record["sz_index_pct"] = round((close - prev_close) / prev_close * 100, 2)
        except Exception as e:
            print(f"Failed to fetch SZ index: {e}", flush=True)
        
        try:
            df = ak.stock_zh_index_daily(symbol="sz399006")
            if df is not None and not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                target_date = pd.to_datetime(trade_date)
                df = df[df['date'] <= target_date]
                if not df.empty:
                    latest = df.iloc[-1]
                    close = latest.get('close', 0)
                    prev_close = df.iloc[-2].get('close', close) if len(df) > 1 else close
                    if prev_close and close:
                        record["cyb_index_pct"] = round((close - prev_close) / prev_close * 100, 2)
        except Exception as e:
            print(f"Failed to fetch CYB index: {e}", flush=True)
    
    def _fetch_market_summary(self, record: Dict[str, Any], trade_date: str):
        """Fetch market summary from collected daily quotes for the given trade date."""
        try:
            rows = self.db.fetchall(
                """
                SELECT pct_chg, amount
                FROM daily_stock_quotes
                WHERE trade_date = ?
                """,
                (trade_date,),
            )
            if rows:
                pct_values = pd.Series(
                    pd.to_numeric(
                        [row["pct_chg"] for row in rows],
                        errors="coerce",
                    )
                )
                amount_values = pd.Series(
                    pd.to_numeric(
                        [row["amount"] for row in rows],
                        errors="coerce",
                    )
                )
                valid_pct = pct_values.dropna()
                valid_amount = amount_values.dropna()
                record["up_count"] = int((pct_values > 0).sum())
                record["down_count"] = int((pct_values < 0).sum())
                record["total_amount"] = float(valid_amount.sum()) if not valid_amount.empty else None
                print(
                    f"Market summary rows={len(rows)} valid_pct={len(valid_pct)} "
                    f"valid_amount={len(valid_amount)} total_amount={record['total_amount']}",
                    flush=True,
                )
                return
        except Exception as e:
            print(f"Failed to fetch market summary from daily_stock_quotes: {e}", flush=True)

        print(
            "Warning: daily_stock_quotes summary unavailable for "
            f"{trade_date}; market breadth summary fields remain null",
            flush=True,
        )
    
    def _fetch_limit_stats(self, record: Dict[str, Any], trade_date: str):
        """Fetch limit up/down statistics for the given trade date."""
        date_str = trade_date.replace("-", "")

        local_row = self.db.fetchone(
            """
            SELECT
                COUNT(*) AS limit_up_count,
                SUM(COALESCE(broken_limit, 0)) AS broken_limit_count,
                MAX(COALESCE(limit_up_streak, 0)) AS highest_streak
            FROM daily_stock_limits
            WHERE trade_date = ?
            """,
            (trade_date,),
        )
        if local_row and int(local_row["limit_up_count"] or 0) > 0:
            record["limit_up_count"] = int(local_row["limit_up_count"] or 0)
            record["broken_limit_count"] = int(local_row["broken_limit_count"] or 0)
            max_streak = int(local_row["highest_streak"] or 0)
            record["highest_streak"] = max_streak if max_streak > 0 else None
            print(
                "Limit stats loaded from daily_stock_limits: "
                f"limit_up={record['limit_up_count']} broken_limit={record['broken_limit_count']} "
                f"highest_streak={record['highest_streak']}",
                flush=True,
            )
            return

        try:
            df = ak.stock_zt_pool_em(date=date_str)
            if df is not None and not df.empty:
                record["limit_up_count"] = len(df)
        except Exception as e:
            print(f"Failed to fetch limit up count: {e}", flush=True)
        
        try:
            df = ak.stock_zt_pool_dtgc_em(date=date_str)
            if df is not None and not df.empty:
                record["broken_limit_count"] = len(df)
        except Exception as e:
            print(f"Failed to fetch broken limit count: {e}", flush=True)
        
        try:
            df = ak.stock_zt_pool_zbgc_em(date=date_str)
            if df is not None and not df.empty:
                record["highest_streak"] = int(df['连板数'].max()) if '连板数' in df.columns else None
        except Exception as e:
            print(f"Failed to fetch highest streak: {e}", flush=True)
    
    def collect_all(self, trade_date: str) -> int:
        """
        Collect all market data including detailed stats.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            Number of records collected
        """
        return self.collect(trade_date)
