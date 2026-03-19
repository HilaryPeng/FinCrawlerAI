"""
SQLite connection management for market daily system.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from contextlib import contextmanager


class DatabaseConnection:
    """SQLite database connection manager."""
    
    def __init__(self, db_path: Path):
        """
        Initialize database connection.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_directory()
    
    def _ensure_directory(self):
        """Ensure database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection.
        
        Returns:
            SQLite connection object
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    
    @contextmanager
    def transaction(self):
        """
        Context manager for database transactions.
        
        Yields:
            Database cursor
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """
        Execute a single SQL statement.
        
        Args:
            sql: SQL statement
            params: Query parameters
            
        Returns:
            Cursor object
        """
        with self.transaction() as cursor:
            cursor.execute(sql, params)
            return cursor
    
    def execute_many(self, sql: str, params_list: list) -> sqlite3.Cursor:
        """
        Execute a SQL statement with multiple parameter sets.
        
        Args:
            sql: SQL statement
            params_list: List of parameter tuples
            
        Returns:
            Cursor object
        """
        with self.transaction() as cursor:
            cursor.executemany(sql, params_list)
            return cursor
    
    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """
        Fetch a single row.
        
        Args:
            sql: SQL query
            params: Query parameters
            
        Returns:
            Row object or None
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchone()
        finally:
            conn.close()
    
    def fetchall(self, sql: str, params: tuple = ()) -> list:
        """
        Fetch all rows.
        
        Args:
            sql: SQL query
            params: Query parameters
            
        Returns:
            List of Row objects
        """
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            conn.close()
    
    def table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists.
        
        Args:
            table_name: Name of the table
            
        Returns:
            True if table exists
        """
        sql = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
        result = self.fetchone(sql, (table_name,))
        return result is not None
    
    def get_table_list(self) -> list:
        """
        Get list of all tables in the database.
        
        Returns:
            List of table names
        """
        sql = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        results = self.fetchall(sql)
        return [row["name"] for row in results]


# Global database connection instance
_db_connection: Optional[DatabaseConnection] = None


def init_db(db_path: Path) -> DatabaseConnection:
    """
    Initialize the global database connection.
    
    Args:
        db_path: Path to SQLite database file
        
    Returns:
        DatabaseConnection instance
    """
    global _db_connection
    _db_connection = DatabaseConnection(db_path)
    return _db_connection


def get_db_connection() -> DatabaseConnection:
    """
    Get the global database connection.
    
    Returns:
        DatabaseConnection instance
        
    Raises:
        RuntimeError: If database not initialized
    """
    global _db_connection
    if _db_connection is None:
        raise RuntimeError(
            "Database not initialized. Call init_db() first."
        )
    return _db_connection
