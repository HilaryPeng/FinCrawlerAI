"""
Database module for market daily system.
"""

from .connection import DatabaseConnection, get_db_connection
from .schema import create_all_tables, get_table_schemas
from .repository import (
    BaseRepository,
    NewsItemsRepository,
    NewsItemSymbolsRepository,
    NewsItemThemesRepository,
    DailyStockQuotesRepository,
    DailyStockLimitsRepository,
    StockBoardMembershipRepository,
    DailyBoardQuotesRepository,
    DailyMarketBreadthRepository,
    DailyStockFeaturesRepository,
    DailyBoardFeaturesRepository,
    DailyObservationPoolRepository,
    ObservationTrackingRepository,
)

__all__ = [
    "DatabaseConnection",
    "get_db_connection", 
    "create_all_tables",
    "get_table_schemas",
    "BaseRepository",
    "NewsItemsRepository",
    "NewsItemSymbolsRepository",
    "NewsItemThemesRepository",
    "DailyStockQuotesRepository",
    "DailyStockLimitsRepository",
    "StockBoardMembershipRepository",
    "DailyBoardQuotesRepository",
    "DailyMarketBreadthRepository",
    "DailyStockFeaturesRepository",
    "DailyBoardFeaturesRepository",
    "DailyObservationPoolRepository",
    "ObservationTrackingRepository",
]
