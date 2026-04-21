"""
Market attention and technical screener collector.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, List

import akshare as ak
import pandas as pd

from src.db import DatabaseConnection, DailyStockAttentionRepository
from src.utils.symbols import normalize_symbol


class AttentionCollector:
    """Collect hot-rank and screener snapshots for a trade date."""

    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.repo = DailyStockAttentionRepository(db)

    def collect(self, trade_date: str, sources: set[str] | None = None) -> int:
        print(f"Collecting stock attention screeners for {trade_date}...", flush=True)
        self.db.execute("DELETE FROM daily_stock_attention WHERE trade_date = ?", (trade_date,))
        enabled = sources or {"eastmoney", "xueqiu", "ths"}

        records: List[Dict[str, Any]] = []
        if "eastmoney" in enabled:
            records.extend(self._safe_collect("eastmoney_hot_rank", self._fetch_eastmoney_hot_rank, trade_date))
            records.extend(self._safe_collect("eastmoney_hot_up", self._fetch_eastmoney_hot_up, trade_date))
        if "xueqiu" in enabled:
            records.extend(self._safe_collect("xueqiu_follow", self._fetch_xueqiu_follow_rank, trade_date))
            records.extend(self._safe_collect("xueqiu_tweet", self._fetch_xueqiu_tweet_rank, trade_date))
        if "ths" in enabled:
            records.extend(self._safe_collect("ths_new_high", self._fetch_ths_new_high, trade_date))
            records.extend(self._safe_collect("ths_consecutive_up", self._fetch_ths_consecutive_up, trade_date))
            records.extend(self._safe_collect("ths_breakout", self._fetch_ths_breakouts, trade_date))

        if not records:
            print(f"No attention records collected for {trade_date}", flush=True)
            return 0

        unique_keys = self.repo.get_unique_keys()
        count = self.repo.upsert_many(records, unique_keys)
        print(f"Stored {count} stock attention rows for {trade_date}", flush=True)
        return count

    def _safe_collect(
        self,
        label: str,
        func: Callable[[str], List[Dict[str, Any]]],
        trade_date: str,
    ) -> List[Dict[str, Any]]:
        try:
            rows = func(trade_date)
            print(f"  {label}: {len(rows)}", flush=True)
            return rows
        except Exception as exc:
            print(f"  {label}: ERROR {exc!r}", flush=True)
            return []

    def _fetch_eastmoney_hot_rank(self, trade_date: str) -> List[Dict[str, Any]]:
        df = ak.stock_hot_rank_em()
        return self._normalize_em_rank(
            trade_date=trade_date,
            df=df,
            source="eastmoney",
            metric_type="hot_rank",
            rank_col="当前排名",
        )

    def _fetch_eastmoney_hot_up(self, trade_date: str) -> List[Dict[str, Any]]:
        df = ak.stock_hot_up_em()
        return self._normalize_em_rank(
            trade_date=trade_date,
            df=df,
            source="eastmoney",
            metric_type="hot_up",
            rank_col="当前排名",
            extra_cols=["排名较昨日变动"],
        )

    def _fetch_xueqiu_follow_rank(self, trade_date: str) -> List[Dict[str, Any]]:
        df = ak.stock_hot_follow_xq(symbol="最热门")
        return self._normalize_xueqiu_rank(
            trade_date=trade_date,
            df=df,
            source="xueqiu",
            metric_type="follow_rank",
            value_col="关注",
        )

    def _fetch_xueqiu_tweet_rank(self, trade_date: str) -> List[Dict[str, Any]]:
        df = ak.stock_hot_tweet_xq(symbol="最热门")
        return self._normalize_xueqiu_rank(
            trade_date=trade_date,
            df=df,
            source="xueqiu",
            metric_type="tweet_rank",
            value_col="讨论",
        )

    def _fetch_ths_new_high(self, trade_date: str) -> List[Dict[str, Any]]:
        df = ak.stock_rank_cxg_ths()
        return self._normalize_ths_screener(
            trade_date=trade_date,
            df=df,
            metric_type="ths_new_high",
        )

    def _fetch_ths_consecutive_up(self, trade_date: str) -> List[Dict[str, Any]]:
        df = ak.stock_rank_lxsz_ths()
        return self._normalize_ths_screener(
            trade_date=trade_date,
            df=df,
            metric_type="ths_consecutive_up",
            extra_cols=["连涨天数", "连续涨跌幅", "累计换手率", "所属行业"],
        )

    def _fetch_ths_breakouts(self, trade_date: str) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for line in ("20日均线", "60日均线"):
            df = ak.stock_rank_xstp_ths(symbol=line)
            records.extend(
                self._normalize_ths_screener(
                    trade_date=trade_date,
                    df=df,
                    metric_type=f"ths_breakout_{line}",
                    extra_cols=["突破均线", "所属行业"],
                )
            )
        return records

    def _normalize_em_rank(
        self,
        trade_date: str,
        df: pd.DataFrame,
        source: str,
        metric_type: str,
        rank_col: str,
        extra_cols: Iterable[str] | None = None,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        extra_cols = list(extra_cols or [])
        for _, row in df.iterrows():
            symbol = normalize_symbol(row.get("代码"))
            if not symbol:
                continue
            payload = {col: self._clean_value(row.get(col)) for col in extra_cols}
            records.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "name": self._clean_text(row.get("股票名称")),
                    "source": source,
                    "metric_type": metric_type,
                    "rank_value": self._to_float(row.get(rank_col)),
                    "metric_value": None,
                    "pct_chg": self._to_float(row.get("涨跌幅")),
                    "extra_json": json.dumps(payload, ensure_ascii=False) if payload else None,
                }
            )
        return records

    def _normalize_xueqiu_rank(
        self,
        trade_date: str,
        df: pd.DataFrame,
        source: str,
        metric_type: str,
        value_col: str,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        for rank, (_, row) in enumerate(df.iterrows(), start=1):
            symbol = normalize_symbol(row.get("股票代码"))
            if not symbol:
                continue
            records.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "name": self._clean_text(row.get("股票简称")),
                    "source": source,
                    "metric_type": metric_type,
                    "rank_value": float(rank),
                    "metric_value": self._to_float(row.get(value_col)),
                    "pct_chg": None,
                    "extra_json": None,
                }
            )
        return records

    def _normalize_ths_screener(
        self,
        trade_date: str,
        df: pd.DataFrame,
        metric_type: str,
        extra_cols: Iterable[str] | None = None,
    ) -> List[Dict[str, Any]]:
        records: List[Dict[str, Any]] = []
        extra_cols = list(extra_cols or [])
        for rank, (_, row) in enumerate(df.iterrows(), start=1):
            code = row.get("股票代码") or row.get("证券代码") or row.get("代码")
            symbol = normalize_symbol(code)
            if not symbol:
                continue
            payload = {col: self._clean_value(row.get(col)) for col in extra_cols if col in row.index}
            pct = self._to_float(row.get("涨跌幅"))
            if pct is None:
                pct = self._to_float(row.get("连续涨跌幅"))
            records.append(
                {
                    "trade_date": trade_date,
                    "symbol": symbol,
                    "name": self._clean_text(row.get("股票简称") or row.get("股票名称")),
                    "source": "ths",
                    "metric_type": metric_type,
                    "rank_value": float(rank),
                    "metric_value": None,
                    "pct_chg": pct,
                    "extra_json": json.dumps(payload, ensure_ascii=False) if payload else None,
                }
            )
        return records

    def _clean_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _clean_value(self, value: Any) -> Any:
        if value is None:
            return None
        if pd.isna(value):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        return text or None

    def _to_float(self, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace("%", "").replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None
