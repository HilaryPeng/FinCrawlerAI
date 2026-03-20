"""
Stock daily quotes collector using AkShare.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List, Dict, Any, Callable, Optional
import pandas as pd
import akshare as ak
import requests

from src.db import DatabaseConnection, DailyStockQuotesRepository
from src.utils.symbols import normalize_symbol


class QuotesCollector:
    """Collector for stock daily quotes."""

    PROGRESS_EVERY = 50
    UPSERT_BATCH_SIZE = 100
    REQUEST_TIMEOUT_SECONDS = 20
    
    def __init__(self, db: DatabaseConnection):
        self.db = db
        self.repo = DailyStockQuotesRepository(db)
        self._stock_universe_cache: List[Dict[str, str]] | None = None
    
    def collect(self, trade_date: str) -> int:
        """
        Collect and store stock daily quotes for a given date.
        
        Args:
            trade_date: Trade date in YYYY-MM-DD format
            
        Returns:
            Number of records collected
        """
        print(f"Collecting stock quotes for {trade_date}...", flush=True)
        
        count = self._collect_streaming(trade_date)
        if count <= 0:
            print(f"No quotes data collected for {trade_date}", flush=True)
            return 0
        print(f"Stored {count} stock quotes for {trade_date}", flush=True)
        return count

    def collect_limited(self, trade_date: str, limit: int) -> int:
        """Collect and store quotes for only the first N stocks."""
        print(f"Collecting up to {limit} stock quotes for {trade_date}...", flush=True)
        count = self._collect_streaming(trade_date, limit=limit)
        if count <= 0:
            print(f"No quotes data collected for {trade_date}", flush=True)
            return 0
        print(f"Stored {count} stock quotes for {trade_date}", flush=True)
        return count

    def _collect_streaming(self, trade_date: str, limit: Optional[int] = None) -> int:
        """Fetch quotes and upsert them in batches for resumable execution."""
        all_stocks = self._get_all_stocks()
        if not all_stocks:
            print("Failed to load stock universe from AkShare sources", flush=True)
            return 0
        if limit is not None and limit > 0:
            all_stocks = all_stocks[:limit]
            print(f"Stock universe trimmed to first {limit} symbols", flush=True)

        total = len(all_stocks)
        print(f"Loaded stock universe with {total} symbols", flush=True)
        existing_symbols = self._get_existing_symbols(trade_date)
        if existing_symbols:
            print(
                f"Found {len(existing_symbols)} existing quotes for {trade_date}; will skip them and resume",
                flush=True,
            )

        success_count = 0
        error_count = 0
        no_data_count = 0
        skipped_count = 0
        inserted_count = 0
        batch: List[Dict[str, Any]] = []
        unique_keys = self.repo.get_unique_keys()

        for index, stock in enumerate(all_stocks, start=1):
            raw_code = stock.get("code", "")
            stock_name = stock.get("name", "")
            symbol = stock.get("symbol", "")
            if not raw_code:
                continue
            if symbol in existing_symbols:
                skipped_count += 1
                if index % self.PROGRESS_EVERY == 0 or index == total:
                    print(
                        f"[progress] processed={index}/{total} inserted={inserted_count} skipped={skipped_count} "
                        f"success={success_count} no_data={no_data_count} errors={error_count}",
                        flush=True,
                    )
                continue
            try:
                rows = self._fetch_daily_rows(symbol=symbol, trade_date=trade_date)
                if rows is not None and not rows.empty:
                    row = rows.iloc[-1]
                    prev_row = rows.iloc[-2] if len(rows) > 1 else None
                    record = self._normalize_quote(
                        row=row,
                        prev_row=prev_row,
                        trade_date=trade_date,
                        raw_code=raw_code,
                        stock_name=stock_name,
                    )
                    batch.append(record)
                    success_count += 1
                    if success_count <= 3:
                        print(
                            f"[sample {success_count}] {record['symbol']} {record['name']} close={record['close']} pct_chg={record['pct_chg']}",
                            flush=True,
                        )
                    if len(batch) >= self.UPSERT_BATCH_SIZE:
                        inserted_count += self._flush_batch(
                            batch=batch,
                            unique_keys=unique_keys,
                            trade_date=trade_date,
                        )
                        batch = []
                else:
                    no_data_count += 1

            except Exception as exc:
                error_count += 1
                if error_count <= 5:
                    print(f"[error {error_count}] {symbol or raw_code} {exc}", flush=True)
                continue

            if index % self.PROGRESS_EVERY == 0 or index == total:
                print(
                    f"[progress] processed={index}/{total} inserted={inserted_count} skipped={skipped_count} "
                    f"success={success_count} no_data={no_data_count} errors={error_count}",
                    flush=True,
                )

        if batch:
            inserted_count += self._flush_batch(
                batch=batch,
                unique_keys=unique_keys,
                trade_date=trade_date,
            )

        print(
            f"Finished fetching quotes: total={total} inserted={inserted_count} skipped={skipped_count} "
            f"success={success_count} no_data={no_data_count} errors={error_count}",
            flush=True,
        )
        return inserted_count

    def _flush_batch(
        self,
        batch: List[Dict[str, Any]],
        unique_keys: List[str],
        trade_date: str,
    ) -> int:
        """Upsert a batch of quote records."""
        print(
            f"Upserting batch of {len(batch)} quote records for {trade_date}...",
            flush=True,
        )
        count = self.repo.upsert_many(batch, unique_keys)
        print(
            f"Batch stored: {count} quote records for {trade_date}",
            flush=True,
        )
        return count

    def _get_existing_symbols(self, trade_date: str) -> set[str]:
        """Load already collected symbols for a trade date."""
        rows = self.db.fetchall(
            "SELECT symbol FROM daily_stock_quotes WHERE trade_date = ?",
            (trade_date,),
        )
        return {
            str(row["symbol"]).strip()
            for row in rows
            if row and str(row["symbol"]).strip()
        }

    def _fetch_daily_rows(self, symbol: str, trade_date: str) -> Optional[pd.DataFrame]:
        """Fetch daily rows up to the target date using a working AkShare source."""
        target_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
        start_date = (target_date - timedelta(days=40)).strftime("%Y%m%d")
        end_date = trade_date.replace("-", "")

        try:
            with self._requests_timeout():
                df = ak.stock_zh_a_daily(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    adjust="",
                )
            if df is not None and not df.empty:
                df = df.copy()
                df["date"] = pd.to_datetime(df["date"]).dt.date
                df = df[df["date"] <= target_date]
                if not df.empty:
                    return df
        except Exception:
            pass

        try:
            with self._requests_timeout():
                df = ak.stock_zh_a_hist_tx(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    adjust="",
                )
            if df is not None and not df.empty:
                df = df.copy()
                df["date"] = pd.to_datetime(df["date"]).dt.date
                df = df[df["date"] <= target_date]
                if not df.empty:
                    return df
        except Exception:
            pass

        return None

    @contextmanager
    def _requests_timeout(self):
        """Temporarily set a default timeout for third-party AkShare requests."""
        original_get = requests.get

        def timeout_get(*args, **kwargs):
            kwargs.setdefault("timeout", self.REQUEST_TIMEOUT_SECONDS)
            return original_get(*args, **kwargs)

        requests.get = timeout_get
        try:
            yield
        finally:
            requests.get = original_get

    def _get_all_stocks(self) -> List[Dict[str, str]]:
        """Get A-share stock universe with code and name."""
        if self._stock_universe_cache is not None:
            return self._stock_universe_cache

        fetchers: List[Callable[[], List[Dict[str, str]]]] = [
            self._get_all_stocks_from_code_name,
            self._get_all_stocks_from_exchange_lists,
            self._get_all_stocks_from_spot,
        ]

        for fetcher in fetchers:
            try:
                records = fetcher()
                if records:
                    print(
                        f"Loaded stock universe from {fetcher.__name__}: {len(records)} symbols",
                        flush=True,
                    )
                    self._stock_universe_cache = records
                    return records
            except Exception:
                continue
        return []

    def _get_all_stocks_from_code_name(self) -> List[Dict[str, str]]:
        """Fetch stock universe from a stable code-name list."""
        df = ak.stock_info_a_code_name()
        return self._normalize_stock_list_df(df, code_col="code", name_col="name")

    def _get_all_stocks_from_exchange_lists(self) -> List[Dict[str, str]]:
        """Fetch stock universe by merging SH/SZ/BJ code-name lists."""
        frames = []
        for fn_name in [
            "stock_info_sh_name_code",
            "stock_info_sz_name_code",
            "stock_info_bj_name_code",
        ]:
            fn = getattr(ak, fn_name, None)
            if fn is None:
                continue
            df = fn()
            if df is not None and not df.empty:
                frames.append(df)

        if not frames:
            return []

        merged = pd.concat(frames, ignore_index=True)
        code_col = "证券代码" if "证券代码" in merged.columns else "A股代码"
        name_col = "证券简称" if "证券简称" in merged.columns else "A股简称"
        return self._normalize_stock_list_df(merged, code_col=code_col, name_col=name_col)

    def _get_all_stocks_from_spot(self) -> List[Dict[str, str]]:
        """Fallback to spot list if static code lists are unavailable."""
        df = ak.stock_zh_a_spot_em()
        return self._normalize_stock_list_df(df, code_col="代码", name_col="名称")

    def _normalize_stock_list_df(
        self,
        df: pd.DataFrame,
        *,
        code_col: str,
        name_col: str,
    ) -> List[Dict[str, str]]:
        """Normalize a stock-list dataframe into code/name records."""
        if df is None or df.empty:
            return []
        if code_col not in df.columns or name_col not in df.columns:
            return []

        records: List[Dict[str, str]] = []
        seen: set[str] = set()
        for _, row in df.iterrows():
            raw_code = str(row.get(code_col, "")).strip()
            code = normalize_symbol(raw_code)
            if not code or code in seen:
                continue
            name = str(row.get(name_col, "")).strip()
            records.append({"code": raw_code, "name": name, "symbol": code})
            seen.add(code)
        return records

    def _normalize_quote(
        self,
        row: pd.Series,
        prev_row: Optional[pd.Series],
        trade_date: str,
        raw_code: str,
        stock_name: str,
    ) -> Dict[str, Any]:
        """Normalize a quote row to database format."""
        close = self._pick_float(row, ["收盘", "close"])
        open_price = self._pick_float(row, ["开盘", "open"])
        high = self._pick_float(row, ["最高", "high"])
        low = self._pick_float(row, ["最低", "low"])
        volume = self._pick_float(row, ["成交量", "volume"])
        amount = self._pick_float(row, ["成交额", "amount"])
        turnover = self._pick_float(row, ["换手率", "turnover"])

        prev_close = self._pick_float(prev_row, ["收盘", "close"]) if prev_row is not None else None
        chg = (close - prev_close) if (close is not None and prev_close is not None) else None
        pct_chg = ((chg / prev_close) * 100) if (chg is not None and prev_close) else None
        amplitude = ((high - low) / prev_close * 100) if (high is not None and low is not None and prev_close) else None

        outstanding_share = self._pick_float(row, ["outstanding_share"])
        total_mv = (close * outstanding_share) if (close is not None and outstanding_share is not None) else None

        return {
            "trade_date": trade_date,
            "symbol": normalize_symbol(raw_code),
            "name": stock_name,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "prev_close": prev_close,
            "pct_chg": pct_chg,
            "chg": chg,
            "volume": volume,
            "amount": amount,
            "amplitude": amplitude,
            "turnover": turnover,
            "total_mv": total_mv,
            "circ_mv": total_mv,
            "source": "akshare",
        }

    def _pick_float(self, row: Optional[pd.Series], keys: List[str]) -> Optional[float]:
        """Pick the first available numeric value from the given keys."""
        if row is None:
            return None
        for key in keys:
            if key in row and pd.notna(row.get(key)):
                try:
                    return float(row.get(key))
                except Exception:
                    continue
        return None
