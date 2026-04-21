"""
OpenSpec-backed runtime configuration loaders.
"""

from .market_daily import MarketDailySpec, load_market_daily_spec

__all__ = [
    "MarketDailySpec",
    "load_market_daily_spec",
]
