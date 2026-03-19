#!/usr/bin/env python3
"""
Database initialization script for market daily system.
Run this to create all tables in the database.

Usage:
    python scripts/init_market_db.py
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import get_config
from src.db import DatabaseConnection, create_all_tables, get_table_schemas


def main():
    """Initialize the market daily database."""
    config = get_config()
    
    # Ensure directories exist
    config.ensure_directories()
    
    # Get database path
    db_path = config.MARKET_DAILY_DB
    print(f"Initializing database at: {db_path}")
    
    # Create database connection
    db = DatabaseConnection(db_path)
    
    # Create all tables
    print("Creating tables...")
    create_all_tables(db)
    
    # Verify tables were created
    tables = db.get_table_list()
    print(f"\nCreated {len(tables)} tables:")
    for table in tables:
        print(f"  - {table}")
    
    # Show expected tables
    expected_tables = list(get_table_schemas().keys())
    print(f"\nExpected tables: {len(expected_tables)}")
    
    missing = set(expected_tables) - set(tables)
    if missing:
        print(f"WARNING: Missing tables: {missing}")
        return 1
    
    print("\nDatabase initialization complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
