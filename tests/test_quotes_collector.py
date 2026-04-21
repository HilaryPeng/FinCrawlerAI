from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.db.connection import DatabaseConnection
from src.db.schema import create_all_tables
from src.market.collectors import quotes_collector as quotes_module
from src.market.collectors.quotes_collector import QuotesCollector


class _FakeBaoStockResult:
    def __init__(
        self,
        fields: list[str],
        rows: list[list[str]],
        *,
        error_code: str = "0",
        error_msg: str = "",
    ):
        self.fields = fields
        self._rows = rows
        self._index = -1
        self.error_code = error_code
        self.error_msg = error_msg

    def next(self) -> bool:
        self._index += 1
        return self._index < len(self._rows)

    def get_row_data(self) -> list[str]:
        return self._rows[self._index]


class QuotesCollectorBaoStockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseConnection(Path(self.temp_dir.name) / "market_daily.db")
        create_all_tables(self.db)
        self.collector = QuotesCollector(self.db)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_collect_uses_baostock_by_default_and_stores_quotes(
        self,
    ) -> None:
        fake_bs = SimpleNamespace(
            login=lambda: type("LoginResult", (), {"error_code": "0", "error_msg": "success"})(),
            logout=lambda: None,
            query_all_stock=lambda trade_date: _FakeBaoStockResult(
                ["code", "code_name"],
                [["sh.600000", "浦发银行"]],
            ),
            query_history_k_data_plus=lambda code, fields, start_date, end_date, frequency, adjustflag: _FakeBaoStockResult(
                [
                    "date",
                    "code",
                    "open",
                    "high",
                    "low",
                    "close",
                    "preclose",
                    "volume",
                    "amount",
                    "turn",
                    "pctChg",
                ],
                [
                    ["2026-04-17", "sh.600000", "10.00", "10.50", "9.80", "10.20", "9.90", "1000000", "10200000", "1.25", "3.03"],
                    ["2026-04-18", "sh.600000", "10.30", "10.80", "10.10", "10.60", "10.20", "1100000", "11500000", "1.35", "3.92"],
                ],
            ),
        )

        with patch.object(quotes_module, "bs", fake_bs, create=True):
            inserted = self.collector.collect("2026-04-18")

        self.assertEqual(inserted, 1)
        row = self.db.fetchone(
            """
            SELECT symbol, name, open, high, low, close, prev_close, pct_chg, volume, amount, turnover, source
            FROM daily_stock_quotes
            WHERE trade_date = ?
            """,
            ("2026-04-18",),
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["symbol"], "sh600000")
        self.assertEqual(row["name"], "浦发银行")
        self.assertEqual(row["open"], 10.3)
        self.assertEqual(row["high"], 10.8)
        self.assertEqual(row["low"], 10.1)
        self.assertEqual(row["close"], 10.6)
        self.assertEqual(row["prev_close"], 10.2)
        self.assertEqual(row["pct_chg"], 3.92)
        self.assertEqual(row["volume"], 1100000.0)
        self.assertEqual(row["amount"], 11500000.0)
        self.assertEqual(row["turnover"], 1.35)
        self.assertEqual(row["source"], "baostock")

    def test_get_all_stocks_from_baostock_normalizes_dot_symbols(
        self,
    ) -> None:
        fake_bs = SimpleNamespace(
            login=lambda: type("LoginResult", (), {"error_code": "0", "error_msg": "success"})(),
            logout=lambda: None,
            query_all_stock=lambda trade_date: _FakeBaoStockResult(
                ["code", "code_name"],
                [["sh.600000", "浦发银行"], ["sz.000001", "平安银行"]],
            ),
        )

        with patch.object(quotes_module, "bs", fake_bs, create=True):
            stocks = self.collector._get_all_stocks_from_baostock("2026-04-18")

        self.assertEqual(
            stocks,
            [
                {"code": "sh.600000", "name": "浦发银行", "symbol": "sh600000"},
                {"code": "sz.000001", "name": "平安银行", "symbol": "sz000001"},
            ],
        )

    def test_get_all_stocks_from_baostock_filters_non_a_share_securities(
        self,
    ) -> None:
        fake_bs = SimpleNamespace(
            login=lambda: type("LoginResult", (), {"error_code": "0", "error_msg": "success"})(),
            logout=lambda: None,
            query_all_stock=lambda trade_date: _FakeBaoStockResult(
                ["code", "tradeStatus", "code_name"],
                [
                    ["sh.000001", "1", "上证综合指数"],
                    ["sh.510300", "1", "沪深300ETF"],
                    ["sh.600000", "1", "浦发银行"],
                    ["sz.159001", "1", "ETF基金"],
                    ["sz.200001", "1", "深B"],
                    ["sz.300001", "1", "特锐德"],
                    ["sz.399001", "1", "深证成指"],
                    ["bj.430001", "1", "北交所样本"],
                ],
            ),
        )

        with patch.object(quotes_module, "bs", fake_bs, create=True):
            stocks = self.collector._get_all_stocks_from_baostock("2026-04-18")

        self.assertEqual(
            stocks,
            [
                {"code": "sh.600000", "name": "浦发银行", "symbol": "sh600000"},
                {"code": "sz.300001", "name": "特锐德", "symbol": "sz300001"},
                {"code": "bj.430001", "name": "北交所样本", "symbol": "bj430001"},
            ],
        )

    def test_get_all_stocks_from_baostock_retries_after_temporary_query_failure(
        self,
    ) -> None:
        query_calls = 0
        login_calls = 0
        logout_calls = 0

        def login():
            nonlocal login_calls
            login_calls += 1
            return type("LoginResult", (), {"error_code": "0", "error_msg": "success"})()

        def logout():
            nonlocal logout_calls
            logout_calls += 1

        def query_all_stock(trade_date):
            nonlocal query_calls
            query_calls += 1
            if query_calls == 1:
                return _FakeBaoStockResult(
                    ["code", "tradeStatus", "code_name"],
                    [],
                    error_code="10002007",
                    error_msg="网络接收错误。",
                )
            return _FakeBaoStockResult(
                ["code", "tradeStatus", "code_name"],
                [["sh.600000", "1", "浦发银行"]],
            )

        fake_bs = SimpleNamespace(
            login=login,
            logout=logout,
            query_all_stock=query_all_stock,
        )

        self.collector._baostock_session_active = True

        with patch.object(quotes_module, "bs", fake_bs, create=True):
            stocks = self.collector._get_all_stocks_from_baostock("2026-04-18")

        self.assertEqual(
            stocks,
            [{"code": "sh.600000", "name": "浦发银行", "symbol": "sh600000"}],
        )
        self.assertEqual(query_calls, 2)
        self.assertEqual(login_calls, 1)
        self.assertEqual(logout_calls, 1)


if __name__ == "__main__":
    unittest.main()
