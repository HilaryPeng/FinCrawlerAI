"""
Base repository for database operations with upsert support.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union
import json

from .connection import DatabaseConnection


class BaseRepository:
    """Base repository class for database operations."""
    
    def __init__(self, db_connection: DatabaseConnection, table_name: str):
        """
        Initialize repository.
        
        Args:
            db_connection: Database connection instance
            table_name: Name of the database table
        """
        self.db = db_connection
        self.table_name = table_name
    
    def _get_now(self) -> str:
        """Get current timestamp string."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def _row_to_dict(self, row) -> Dict:
        """Convert a sqlite3.Row to dictionary."""
        return dict(row) if row else {}
    
    def _rows_to_list(self, rows: List) -> List[Dict]:
        """Convert list of sqlite3.Row to list of dictionaries."""
        result: List[Dict] = []
        for row in rows:
            if row:
                result.append(dict(row))
        return result
    
    def insert(self, data: Dict[str, Any]) -> int:
        """
        Insert a single record.
        
        Args:
            data: Dictionary of column:value pairs
            
        Returns:
            Last inserted row id
        """
        if "created_at" not in data:
            data["created_at"] = self._get_now()
        
        columns = list(data.keys())
        placeholders = ["?"] * len(columns)
        values = list(data.values())
        
        sql = f"INSERT INTO {self.table_name} ({','.join(columns)}) VALUES ({','.join(placeholders)})"
        cursor = self.db.execute(sql, tuple(values))
        return cursor.lastrowid or 0
    
    def insert_many(self, data_list: List[Dict[str, Any]]) -> int:
        """
        Insert multiple records.
        
        Args:
            data_list: List of dictionaries
            
        Returns:
            Number of rows inserted
        """
        if not data_list:
            return 0
        
        # Add created_at if not present
        now = self._get_now()
        for data in data_list:
            if "created_at" not in data:
                data["created_at"] = now
        
        columns = list(data_list[0].keys())
        placeholders = ["?"] * len(columns)
        
        values_list = [list(d.values()) for d in data_list]
        
        sql = f"INSERT INTO {self.table_name} ({','.join(columns)}) VALUES ({','.join(placeholders)})"
        self.db.execute_many(sql, values_list)
        return len(data_list)
    
    def upsert(self, data: Dict[str, Any], unique_keys: List[str]) -> int:
        """
        Insert or update a record based on unique keys.
        
        Args:
            data: Dictionary of column:value pairs
            unique_keys: List of column names that define uniqueness
            
        Returns:
            Last inserted or updated row id
        """
        if "created_at" not in data:
            data["created_at"] = self._get_now()
        
        columns = list(data.keys())
        placeholders = ["?"] * len(columns)
        values = list(data.values())
        
        # Build ON CONFLICT clause
        update_parts = [f"{col} = excluded.{col}" for col in columns if col not in unique_keys]
        
        sql = f"""
            INSERT INTO {self.table_name} ({','.join(columns)})
            VALUES ({','.join(placeholders)})
            ON CONFLICT({','.join(unique_keys)}) DO UPDATE SET
            {','.join(update_parts)}
        """
        cursor = self.db.execute(sql, tuple(values))
        return cursor.lastrowid or 0
    
    def upsert_many(self, data_list: List[Dict[str, Any]], unique_keys: List[str]) -> int:
        """
        Insert or update multiple records.
        
        Args:
            data_list: List of dictionaries
            unique_keys: List of column names that define uniqueness
            
        Returns:
            Number of rows upserted
        """
        if not data_list:
            return 0
        
        now = self._get_now()
        for data in data_list:
            if "created_at" not in data:
                data["created_at"] = now
        
        columns = list(data_list[0].keys())
        placeholders = ["?"] * len(columns)
        
        update_parts = [f"{col} = excluded.{col}" for col in columns if col not in unique_keys]
        
        sql = f"""
            INSERT INTO {self.table_name} ({','.join(columns)})
            VALUES ({','.join(placeholders)})
            ON CONFLICT({','.join(unique_keys)}) DO UPDATE SET
            {','.join(update_parts)}
        """
        
        values_list = [list(d.values()) for d in data_list]
        self.db.execute_many(sql, values_list)
        return len(data_list)
    
    def find_by_id(self, id: int) -> Optional[Dict]:
        """
        Find a record by id.
        
        Args:
            id: Primary key value
            
        Returns:
            Dictionary or None
        """
        sql = f"SELECT * FROM {self.table_name} WHERE id = ?"
        row = self.db.fetchone(sql, (id,))
        return self._row_to_dict(row)
    
    def find_one(self, conditions: Dict[str, Any]) -> Optional[Dict]:
        """
        Find a single record matching conditions.
        
        Args:
            conditions: Dictionary of column:value pairs
            
        Returns:
            Dictionary or None
        """
        where_parts = [f"{k} = ?" for k in conditions.keys()]
        where_vals = list(conditions.values())
        
        sql = f"SELECT * FROM {self.table_name} WHERE {' AND '.join(where_parts)} LIMIT 1"
        row = self.db.fetchone(sql, tuple(where_vals))
        return self._row_to_dict(row)
    
    def find_all(self, conditions: Optional[Dict[str, Any]] = None, 
                 order_by: Optional[str] = None,
                 limit: Optional[int] = None) -> List[Dict]:
        """
        Find all records matching conditions.
        
        Args:
            conditions: Dictionary of column:value pairs (optional)
            order_by: ORDER BY clause (optional)
            limit: LIMIT value (optional)
            
        Returns:
            List of dictionaries
        """
        if conditions:
            where_parts = [f"{k} = ?" for k in conditions.keys()]
            where_vals = list(conditions.values())
            sql = f"SELECT * FROM {self.table_name} WHERE {' AND '.join(where_parts)}"
        else:
            sql = f"SELECT * FROM {self.table_name}"
            where_vals = []
        
        if order_by:
            sql += f" ORDER BY {order_by}"
        
        if limit:
            sql += f" LIMIT {limit}"
        
        rows = self.db.fetchall(sql, tuple(where_vals) if where_vals else ())
        return self._rows_to_list(rows)
    
    def find_by_date(self, trade_date: str) -> List[Dict]:
        """
        Find all records for a specific trade date.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            List of dictionaries
        """
        sql = f"SELECT * FROM {self.table_name} WHERE trade_date = ?"
        rows = self.db.fetchall(sql, (trade_date,))
        return self._rows_to_list(rows)
    
    def count(self, conditions: Optional[Dict[str, Any]] = None) -> int:
        """
        Count records.
        
        Args:
            conditions: Dictionary of column:value pairs (optional)
            
        Returns:
            Count of matching records
        """
        if conditions:
            where_parts = [f"{k} = ?" for k in conditions.keys()]
            where_vals = list(conditions.values())
            sql = f"SELECT COUNT(*) as cnt FROM {self.table_name} WHERE {' AND '.join(where_parts)}"
            row = self.db.fetchone(sql, tuple(where_vals))
        else:
            sql = f"SELECT COUNT(*) as cnt FROM {self.table_name}"
            row = self.db.fetchone(sql)
        
        return row["cnt"] if row else 0
    
    def delete(self, conditions: Dict[str, Any]) -> int:
        """
        Delete records matching conditions.
        
        Args:
            conditions: Dictionary of column:value pairs
            
        Returns:
            Number of deleted records
        """
        where_parts = [f"{k} = ?" for k in conditions.keys()]
        where_vals = list(conditions.values())
        
        sql = f"DELETE FROM {self.table_name} WHERE {' AND '.join(where_parts)}"
        cursor = self.db.execute(sql, tuple(where_vals))
        return cursor.rowcount
    
    def delete_by_date(self, trade_date: str) -> int:
        """
        Delete all records for a specific trade date.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            Number of deleted records
        """
        return self.delete({"trade_date": trade_date})
    
    def get_unique_keys(self) -> List[str]:
        """
        Get the unique key columns for this table.
        Should be overridden by subclasses.
        
        Returns:
            List of column names
        """
        return []


class NewsItemsRepository(BaseRepository):
    """Repository for news_items table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "news_items")
    
    def get_unique_keys(self) -> List[str]:
        return ["source", "source_uid"]


class NewsItemSymbolsRepository(BaseRepository):
    """Repository for news_item_symbols table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "news_item_symbols")


class NewsItemThemesRepository(BaseRepository):
    """Repository for news_item_themes table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "news_item_themes")


class DailyStockQuotesRepository(BaseRepository):
    """Repository for daily_stock_quotes table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "daily_stock_quotes")
    
    def get_unique_keys(self) -> List[str]:
        return ["trade_date", "symbol"]


class DailyStockLimitsRepository(BaseRepository):
    """Repository for daily_stock_limits table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "daily_stock_limits")
    
    def get_unique_keys(self) -> List[str]:
        return ["trade_date", "symbol"]


class StockBoardMembershipRepository(BaseRepository):
    """Repository for stock_board_membership table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "stock_board_membership")

    def get_unique_keys(self) -> List[str]:
        return ["trade_date", "symbol", "board_name", "board_type"]
    
    def get_unique_keys(self) -> List[str]:
        return ["trade_date", "symbol", "board_name", "board_type"]


class DailyBoardQuotesRepository(BaseRepository):
    """Repository for daily_board_quotes table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "daily_board_quotes")
    
    def get_unique_keys(self) -> List[str]:
        return ["trade_date", "board_type", "board_name"]


class DailyMarketBreadthRepository(BaseRepository):
    """Repository for daily_market_breadth table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "daily_market_breadth")


class DailyStockAttentionRepository(BaseRepository):
    """Repository for daily_stock_attention table."""

    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "daily_stock_attention")

    def get_unique_keys(self) -> List[str]:
        return ["trade_date", "symbol", "source", "metric_type"]


class DailyStockFeaturesRepository(BaseRepository):
    """Repository for daily_stock_features table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "daily_stock_features")
    
    def get_unique_keys(self) -> List[str]:
        return ["trade_date", "symbol"]


class DailyBoardFeaturesRepository(BaseRepository):
    """Repository for daily_board_features table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "daily_board_features")
    
    def get_unique_keys(self) -> List[str]:
        return ["trade_date", "board_type", "board_name"]


class DailyObservationPoolRepository(BaseRepository):
    """Repository for daily_observation_pool table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "daily_observation_pool")
    
    def get_unique_keys(self) -> List[str]:
        return ["trade_date", "symbol", "pool_group"]


class ObservationTrackingRepository(BaseRepository):
    """Repository for observation_tracking table."""
    
    def __init__(self, db_connection: DatabaseConnection):
        super().__init__(db_connection, "observation_tracking")
    
    def get_unique_keys(self) -> List[str]:
        return ["base_trade_date", "symbol"]
