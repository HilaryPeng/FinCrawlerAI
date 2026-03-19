"""
Database schema definitions for market daily system.
"""

# All table creation statements
TABLE_SCHEMAS = {
    # News tables
    "news_items": """
        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            source_uid TEXT,
            title TEXT,
            content TEXT,
            publish_time TEXT,
            publish_ts INTEGER,
            url TEXT,
            event_id TEXT,
            raw_json TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(source, source_uid)
        );
        CREATE INDEX IF NOT EXISTS idx_news_publish_ts ON news_items(publish_ts);
        CREATE INDEX IF NOT EXISTS idx_news_event_id ON news_items(event_id);
    """,
    
    "news_item_symbols": """
        CREATE TABLE IF NOT EXISTS news_item_symbols (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            stock_name TEXT,
            relation_type TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (news_id) REFERENCES news_items(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_news_symbols_news_id ON news_item_symbols(news_id);
        CREATE INDEX IF NOT EXISTS idx_news_symbols_symbol ON news_item_symbols(symbol);
    """,
    
    "news_item_themes": """
        CREATE TABLE IF NOT EXISTS news_item_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER NOT NULL,
            theme_name TEXT NOT NULL,
            theme_type TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (news_id) REFERENCES news_items(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_news_themes_news_id ON news_item_themes(news_id);
        CREATE INDEX IF NOT EXISTS idx_news_themes_name ON news_item_themes(theme_name);
    """,
    
    # Market data tables
    "daily_stock_quotes": """
        CREATE TABLE IF NOT EXISTS daily_stock_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            prev_close REAL,
            pct_chg REAL,
            chg REAL,
            volume REAL,
            amount REAL,
            amplitude REAL,
            turnover REAL,
            total_mv REAL,
            circ_mv REAL,
            source TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_stock_quotes_date ON daily_stock_quotes(trade_date);
        CREATE INDEX IF NOT EXISTS idx_stock_quotes_symbol ON daily_stock_quotes(symbol);
        CREATE INDEX IF NOT EXISTS idx_stock_quotes_pct_chg ON daily_stock_quotes(pct_chg);
        CREATE INDEX IF NOT EXISTS idx_stock_quotes_amount ON daily_stock_quotes(amount);
    """,
    
    "daily_stock_limits": """
        CREATE TABLE IF NOT EXISTS daily_stock_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            limit_up INTEGER DEFAULT 0,
            broken_limit INTEGER DEFAULT 0,
            limit_up_streak INTEGER DEFAULT 0,
            first_limit_time TEXT,
            final_limit_time TEXT,
            limit_reason TEXT,
            source TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_stock_limits_date ON daily_stock_limits(trade_date);
        CREATE INDEX IF NOT EXISTS idx_stock_limits_symbol ON daily_stock_limits(symbol);
    """,
    
    "stock_board_membership": """
        CREATE TABLE IF NOT EXISTS stock_board_membership (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            board_name TEXT NOT NULL,
            board_type TEXT,
            is_primary INTEGER DEFAULT 0,
            source TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, symbol, board_name, board_type)
        );
        CREATE INDEX IF NOT EXISTS idx_board_membership_date_symbol ON stock_board_membership(trade_date, symbol);
        CREATE INDEX IF NOT EXISTS idx_board_membership_date_name ON stock_board_membership(trade_date, board_name);
    """,
    
    "daily_board_quotes": """
        CREATE TABLE IF NOT EXISTS daily_board_quotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            board_name TEXT NOT NULL,
            board_type TEXT,
            pct_chg REAL,
            up_count INTEGER,
            down_count INTEGER,
            leader_symbol TEXT,
            leader_name TEXT,
            leader_pct_chg REAL,
            source TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, board_type, board_name)
        );
        CREATE INDEX IF NOT EXISTS idx_board_quotes_date ON daily_board_quotes(trade_date);
    """,
    
    "daily_market_breadth": """
        CREATE TABLE IF NOT EXISTS daily_market_breadth (
            trade_date TEXT PRIMARY KEY,
            sh_index_pct REAL,
            sz_index_pct REAL,
            cyb_index_pct REAL,
            total_amount REAL,
            up_count INTEGER,
            down_count INTEGER,
            limit_up_count INTEGER,
            limit_down_count INTEGER,
            broken_limit_count INTEGER,
            highest_streak INTEGER,
            created_at TEXT NOT NULL
        );
    """,
    
    # Feature tables
    "daily_stock_features": """
        CREATE TABLE IF NOT EXISTS daily_stock_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            primary_board_name TEXT,
            primary_board_type TEXT,
            pct_chg REAL,
            amount REAL,
            turnover REAL,
            amplitude REAL,
            total_mv REAL,
            circ_mv REAL,
            limit_up INTEGER DEFAULT 0,
            broken_limit INTEGER DEFAULT 0,
            limit_up_streak INTEGER DEFAULT 0,
            days_in_limit_up_last_20 INTEGER DEFAULT 0,
            news_count INTEGER DEFAULT 0,
            cls_news_count INTEGER DEFAULT 0,
            jygs_news_count INTEGER DEFAULT 0,
            news_heat_score REAL DEFAULT 0,
            board_score_ref REAL DEFAULT 0,
            dragon_score REAL DEFAULT 0,
            center_score REAL DEFAULT 0,
            follow_score REAL DEFAULT 0,
            risk_score REAL DEFAULT 0,
            final_score REAL DEFAULT 0,
            role_tag TEXT,
            risk_flags TEXT,
            feature_json TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_stock_features_date ON daily_stock_features(trade_date);
        CREATE INDEX IF NOT EXISTS idx_stock_features_symbol ON daily_stock_features(symbol);
        CREATE INDEX IF NOT EXISTS idx_stock_features_role ON daily_stock_features(role_tag);
    """,
    
    "daily_board_features": """
        CREATE TABLE IF NOT EXISTS daily_board_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            board_name TEXT NOT NULL,
            board_type TEXT,
            pct_chg REAL,
            up_count INTEGER,
            down_count INTEGER,
            limit_up_count INTEGER,
            core_stock_count INTEGER,
            news_count INTEGER,
            news_heat_score REAL DEFAULT 0,
            dragon_strength REAL DEFAULT 0,
            center_strength REAL DEFAULT 0,
            breadth_score REAL DEFAULT 0,
            continuity_score REAL DEFAULT 0,
            board_score REAL DEFAULT 0,
            phase_hint TEXT,
            feature_json TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, board_type, board_name)
        );
        CREATE INDEX IF NOT EXISTS idx_board_features_date ON daily_board_features(trade_date);
    """,
    
    # Observation pool tables
    "daily_observation_pool": """
        CREATE TABLE IF NOT EXISTS daily_observation_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            role_tag TEXT,
            board_name TEXT,
            board_rank INTEGER,
            stock_rank INTEGER,
            final_score REAL,
            selected_reason TEXT,
            watch_points TEXT,
            risk_flags TEXT,
            pool_group TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(trade_date, symbol, pool_group)
        );
        CREATE INDEX IF NOT EXISTS idx_observation_pool_date ON daily_observation_pool(trade_date);
        CREATE INDEX IF NOT EXISTS idx_observation_pool_group ON daily_observation_pool(pool_group);
    """,
    
    "observation_tracking": """
        CREATE TABLE IF NOT EXISTS observation_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_trade_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            role_tag TEXT,
            entry_price REAL,
            next_1d_pct REAL,
            next_3d_pct REAL,
            next_5d_pct REAL,
            max_up_5d REAL,
            max_drawdown_5d REAL,
            still_hot_3d INTEGER DEFAULT 0,
            still_hot_5d INTEGER DEFAULT 0,
            tracking_json TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(base_trade_date, symbol)
        );
        CREATE INDEX IF NOT EXISTS idx_observation_tracking_date ON observation_tracking(base_trade_date);
        CREATE INDEX IF NOT EXISTS idx_observation_tracking_symbol ON observation_tracking(symbol);
    """,
}


def get_table_schemas() -> dict:
    """
    Get all table schemas.
    
    Returns:
        Dictionary of table name to CREATE statement
    """
    return TABLE_SCHEMAS.copy()


def create_all_tables(db_connection) -> None:
    """
    Create all tables in the database.
    
    Args:
        db_connection: DatabaseConnection instance
    """
    for table_name, create_sql in TABLE_SCHEMAS.items():
        # Split by semicolons to handle multiple statements
        statements = [s.strip() for s in create_sql.split(";") if s.strip()]
        for stmt in statements:
            db_connection.execute(stmt)


def get_table_columns(table_name: str) -> list:
    """
    Get column names for a table.
    
    Args:
        table_name: Name of the table
        
    Returns:
        List of column names
    """
    # This would need a real database connection to work
    # For now, return empty list - will be implemented with actual DB
    return []
